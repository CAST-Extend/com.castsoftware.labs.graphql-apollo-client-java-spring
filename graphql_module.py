# -*- coding: utf-8 -*-
"""
GraphQL Module - File-level parsing logic

This module encapsulates all parsing logic for a single GraphQL source file.
It follows a modular, extensible architecture:

  - Light parsing (Pass 1): Automatic extraction of global structures
  - Full parsing (Pass 2): MANUAL IMPLEMENTATION REQUIRED for link detection

IMPORTANT:
----------
Pass 1 (object detection) is fully implemented and automatic.
Pass 2 (link detection) requires YOU to implement technology-specific logic.

The following methods are SKELETONS that you must implement:
  - full_parse(): Detect function/method calls
  - resolve(): Resolve call targets to objects
  - save_links(): Create links using the CAST SDK

See each method's docstring for detailed implementation guidance.

Python 3.4+ compatible.
"""

from cast.analysers import log, CustomObject, create_link, Bookmark
import os
import re
from collections import defaultdict


# =============================================================================
# OBJECT HIERARCHY CONFIGURATION
# =============================================================================
# This configuration is generated from config_input.json
# It defines:
#   - Object types and their parent relationships
#   - Pattern keys that detect each object type
#
# Format:
#   'ObjectType': {
#       'parent': 'ParentType' or 'file',  # Where this object can be contained
#       'pattern_keys': ['pattern1', ...]   # Grammar patterns that detect this type
#   }
# =============================================================================

OBJECTS_CONFIG = {
        'Program': {'parent': 'file', 'pattern_keys': []},
        'Schema': {'parent': 'file', 'pattern_keys': ['schema_def']},
        'Type': {'parent': 'Schema', 'pattern_keys': ['type_def', 'type_def_implements', 'type_def_implements_multiple', 'type_extend', 'type_extend_implements', 'type_def_description']},
        'Interface': {'parent': 'Schema', 'pattern_keys': ['interface_def', 'interface_def_implements', 'interface_extend', 'interface_def_description']},
        'Enum': {'parent': 'Schema', 'pattern_keys': ['enum_def', 'enum_extend', 'enum_def_description']},
        'EnumValue': {'parent': 'Enum', 'pattern_keys': ['enum_value', 'enum_value_deprecated', 'enum_value_directive', 'enum_value_description']},
        'Input': {'parent': 'Schema', 'pattern_keys': ['input_def', 'input_extend', 'input_def_description']},
        'Union': {'parent': 'Schema', 'pattern_keys': ['union_def', 'union_extend', 'union_def_description']},
        'Scalar': {'parent': 'Schema', 'pattern_keys': ['scalar_def', 'scalar_directive', 'scalar_def_description']},
        'Directive': {'parent': 'Schema', 'pattern_keys': ['directive_def', 'directive_def_with_args', 'directive_def_repeatable']},
        'Field': {'parent': 'Type', 'pattern_keys': ['field_def', 'field_def_with_args', 'field_def_non_null', 'field_def_list', 'field_def_list_non_null', 'field_def_deprecated', 'field_def_directive', 'field_def_description']},
        'Argument': {'parent': 'Field', 'pattern_keys': ['argument_def', 'argument_def_default', 'argument_def_non_null', 'argument_def_list']},
        'Query': {'parent': 'Schema', 'pattern_keys': ['query_operation', 'query_operation_named', 'query_operation_with_vars', 'query_operation_anonymous']},
        'Mutation': {'parent': 'Schema', 'pattern_keys': ['mutation_operation', 'mutation_operation_named', 'mutation_operation_with_vars']},
        'Subscription': {'parent': 'Schema', 'pattern_keys': ['subscription_operation', 'subscription_operation_named', 'subscription_operation_with_vars']},
        'Fragment': {'parent': 'Schema', 'pattern_keys': ['fragment_def', 'fragment_def_directive', 'inline_fragment']},
        'Variable': {'parent': 'Query', 'pattern_keys': ['variable_def', 'variable_def_default', 'variable_def_non_null']},
}

# Build reverse mapping: pattern_key -> object_type
PATTERN_TO_OBJECT_TYPE = {}
for obj_type, obj_def in OBJECTS_CONFIG.items():
    for pattern_key in obj_def.get('pattern_keys', []):
        PATTERN_TO_OBJECT_TYPE[pattern_key] = obj_type

# Build parent hierarchy for containment tracking
OBJECT_PARENTS = {obj_type: obj_def['parent'] for obj_type, obj_def in OBJECTS_CONFIG.items()}


# =============================================================================
# PARSER REGISTRY - Extensibility point for custom parsers
# =============================================================================

class ParserRegistry:
    """
    Registry for pluggable AST node handlers.
    
    Allows users to extend parsing capabilities without modifying core code.
    Register handlers for specific node types or patterns.
    
    Usage:
        registry = ParserRegistry()
        registry.register('ClassDef', my_class_handler)
        registry.register('FunctionDef', my_function_handler)
    """
    
    def __init__(self):
        self._handlers = defaultdict(list)
        self._pattern_handlers = []
    
    def register(self, node_type, handler):
        """
        Register a handler for a specific node type.
        
        Args:
            node_type (str): AST node type name (e.g., 'ClassDef', 'FunctionDef')
            handler (callable): Function(node, module) -> list of objects
        """
        self._handlers[node_type].append(handler)
    
    def register_pattern(self, pattern, handler):
        """
        Register a handler for nodes matching a regex pattern.
        
        Args:
            pattern (str): Regex pattern to match against node types
            handler (callable): Function(node, module) -> list of objects
        """
        self._pattern_handlers.append((re.compile(pattern), handler))
    
    def get_handlers(self, node_type):
        """Get all handlers for a node type."""
        handlers = list(self._handlers.get(node_type, []))
        for pattern, handler in self._pattern_handlers:
            if pattern.match(node_type):
                handlers.append(handler)
        return handlers


# Global parser registry - extend this to add custom handlers
PARSER_REGISTRY = ParserRegistry()


# =============================================================================
# LIBRARY - Container for all modules
# =============================================================================

class GraphQLLibrary:
    """
    Container for all GraphQL modules in the analysis.
    
    This class stores all parsed modules and maintains a global symbol table
    that can be used for cross-file resolution.
    
    IMPORTANT: The resolve_symbol() method is an OPTIONAL HELPER UTILITY.
    It attempts generic resolution which may or may not work for your
    specific language.
    
    When implementing link detection in the Module class, you can:
    1. Use this helper method as a starting point
    2. Ignore it and implement your own resolution logic
    3. Extend it with technology-specific knowledge
    
    Attributes:
        modules (list): List of GraphQLModule instances
        symbols (dict): Global symbol table {fullname: object}
        symbols_by_name (dict): Maps short names to list of fullnames
        module_by_path (dict): Maps file paths to modules
    """
    
    def __init__(self):
        self.modules = []
        self.symbols = {}  # {fullname: CustomObject}
        self.symbols_by_name = defaultdict(list)  # {short_name: [fullnames]}
        self.module_by_path = {}  # {path: module} for import resolution
    
    def add_module(self, module):
        """Add a module to the library and register its objects."""
        self.modules.append(module)
        self.module_by_path[module.path] = module
        # Register all objects from this module in the global symbol table
        for fullname, obj in module.objects.items():
            short_name = None
            if hasattr(module, '_short_names') and fullname in module._short_names:
                short_name = module._short_names[fullname]
            self.register_symbol(fullname, obj, short_name)
    
    def get_modules(self):
        """Get all modules in the library."""
        return self.modules
    
    def register_symbol(self, fullname, obj, short_name=None):
        """
        Register a symbol in the global symbol table.
        
        Args:
            fullname (str): Fully qualified name of the symbol
            obj: The CAST CustomObject
            short_name (str, optional): Short name for resolution
        """
        self.symbols[fullname] = obj
        if short_name:
            self.symbols_by_name[short_name].append(fullname)
    
    def resolve_symbol(self, name, context_module=None, restrict_to_file=False, restrict_to_class=None):
        """
        [OPTIONAL HELPER] Resolve a symbol name to its object.
        
        This is a GENERIC resolution algorithm with strict rules to avoid
        false positives. It may work for some languages but will likely need
        customization for your specific technology.
        
        Resolution strategy:
        1. Exact fullname match (qualified calls like "ClassName.method")
        2. Same-file match (prefer local definitions)
        3. Cross-file match ONLY if there's exactly ONE candidate (no ambiguity)
        
        Args:
            name (str): Symbol name to resolve
            context_module: Module providing context for resolution
            restrict_to_file (bool): Only search in same file (for self/this calls)
            restrict_to_class (str): Only search in specific class fullname prefix
            
        Returns:
            tuple: (CustomObject, fullname) or (None, None)
        """
        # Try exact match first (handles qualified calls)
        if name in self.symbols:
            return self.symbols[name], name
        
        # Try resolution by short name
        if name in self.symbols_by_name:
            candidates = self.symbols_by_name[name]
            
            # If restricted to a specific class, filter candidates
            if restrict_to_class:
                class_candidates = [fn for fn in candidates if fn.startswith(restrict_to_class + '.')]
                if len(class_candidates) == 1:
                    return self.symbols[class_candidates[0]], class_candidates[0]
                return None, None  # Multiple or no matches in class
            
            # If restricted to same file, filter candidates
            if restrict_to_file and context_module:
                file_prefix = context_module.path + '.'
                file_candidates = [fn for fn in candidates if fn.startswith(file_prefix)]
                if len(file_candidates) == 1:
                    return self.symbols[file_candidates[0]], file_candidates[0]
                return None, None  # Multiple or no matches in file
            
            # Prefer same-file match
            if context_module:
                file_prefix = context_module.path + '.'
                file_candidates = [fn for fn in candidates if fn.startswith(file_prefix)]
                if len(file_candidates) == 1:
                    return self.symbols[file_candidates[0]], file_candidates[0]
                elif len(file_candidates) > 1:
                    # Multiple matches in same file - ambiguous, don't guess
                    return None, None
            
            # Cross-file resolution: ONLY if exactly ONE candidate exists
            # This prevents false positives when multiple files define same function
            if len(candidates) == 1:
                return self.symbols[candidates[0]], candidates[0]
            else:
                # Multiple candidates across files - too ambiguous, don't create link
                return None, None
        
        # Try suffix matching: look for fullnames ending with .name or :name
        # This handles cases like resolving "new" to "UserService.new"
        suffix_patterns = ['.' + name, ':' + name]
        candidates = []
        for fullname in self.symbols:
            for suffix in suffix_patterns:
                if fullname.endswith(suffix):
                    candidates.append(fullname)
                    break
        
        if candidates:
            # Prefer same-file match
            if context_module:
                file_prefix = context_module.path + '.'
                file_candidates = [fn for fn in candidates if fn.startswith(file_prefix)]
                if len(file_candidates) == 1:
                    return self.symbols[file_candidates[0]], file_candidates[0]
                elif len(file_candidates) > 1:
                    return None, None  # Ambiguous
            
            # Only return if exactly one candidate
            if len(candidates) == 1:
                return self.symbols[candidates[0]], candidates[0]
        
        return None, None


# =============================================================================
# AST NODE - Generic AST representation
# =============================================================================

class ASTNode:
    """
    Generic AST node representation.
    
    Provides a language-agnostic structure for representing parsed elements.
    Can be extended or replaced with language-specific implementations.
    
    Attributes:
        type (str): Node type (e.g., 'class', 'function', 'method')
        name (str): Node name
        start_line (int): Starting line number
        end_line (int): Ending line number
        children (list): Child nodes
        properties (dict): Additional node-specific properties
    """
    
    def __init__(self, node_type, name=None, start_line=0, end_line=0):
        self.type = node_type
        self.name = name
        self.start_line = start_line
        self.end_line = end_line
        self.children = []
        self.properties = {}
        self.parent = None
    
    def add_child(self, child):
        """Add a child node."""
        child.parent = self
        self.children.append(child)
        return child
    
    def get_children_by_type(self, node_type):
        """Get all children of a specific type."""
        return [c for c in self.children if c.type == node_type]
    
    def walk(self):
        """
        Generator that yields all nodes in the tree (depth-first).
        
        Yields:
            ASTNode: Each node in the tree
        """
        yield self
        for child in self.children:
            for node in child.walk():
                yield node


# =============================================================================
# MODULE CLASS - Core file parsing logic
# =============================================================================

class GraphQLModule:
    """
    Encapsulates parsing logic for a single GraphQL source file.
    
    Implements the 2-pass parsing architecture:
    - light_parse(): Extract global structures (classes, functions)
    - full_parse(): Deep analysis for references and calls (SKELETON - implement manually)
    - resolve(): Resolve call targets (SKELETON - implement manually)
    - save_links(): Create links using CAST SDK (SKELETON - implement manually)
    
    Attributes:
        path (str): Full path to the source file
        file: CAST File object
        ast (ASTNode): Parsed AST (available after light_parse)
        objects (dict): Created CAST objects {fullname: CustomObject}
        pending_links (list): Links to create during resolution
        imported_symbols (dict): Tracked imports {name: fullname}
    """
    
    def __init__(self, path, file=None):
        """
        Initialize a module for a source file.
        
        Args:
            path (str): Full path to the source file
            file: CAST File object (from start_file callback)
        """
        self.path = path
        self.file = file
        self.ast = None
        self.source_content = None
        self.cleaned_source = None  # Source with strings/comments removed
        
        # Object storage
        self.objects = {}  # {fullname: CustomObject}
        self.objects_by_type = defaultdict(list)  # {type: [objects]}
        self.object_lines = {}  # {fullname: (start_line, end_line)} for caller resolution
        
        # Links to create during resolution
        self.pending_links = []  # [(caller_fullname, callee_name, link_type, line)]
        
        # Unresolved calls for reporting
        self.unresolved_calls = []  # [{file, line, code, callee, reason}]
        
        # Import tracking (may be useful for link resolution)
        self.imported_symbols = {}  # {imported_name: source_module_hint}
        self.import_statements = []  # Raw import statements for analysis
        
        # Program-level object (container for file)
        self.program = None
    
    def get_path(self):
        """Get the file path."""
        return self.path
    
    def get_base_name(self):
        """Get the base filename without extension."""
        return os.path.splitext(os.path.basename(self.path))[0]
    
    def get_filename(self):
        """Get the filename with extension."""
        return os.path.basename(self.path)
    
    # =========================================================================
    # SOURCE CLEANING - Remove strings and comments before parsing
    # =========================================================================
    
    def _clean_source_for_parsing(self, content):
        """
        Remove strings and comments from source to avoid false positives.
        
        This prevents detecting calls inside:
        - String literals: "call helper() here"
        - Comments: # call helper() 
        - Multi-line strings/comments
        
        Preserves line structure (replaces with spaces of same length).
        
        Args:
            content (str): Raw source content
            
        Returns:
            str: Cleaned source with strings/comments replaced by spaces
        """
        if not content:
            return content
        
        result = []
        lines = content.splitlines(keepends=True)
        
        in_multiline_string = False
        in_multiline_comment = False
        multiline_delim = None
        
        # Get comment syntax from config
        single_comment = '#'
        
        for line in lines:
            cleaned_line = []
            i = 0
            line_len = len(line)
            
            while i < line_len:
                # Check if we're ending a multiline construct
                if in_multiline_string:
                    if line[i:i+len(multiline_delim)] == multiline_delim:
                        # End of multiline string
                        cleaned_line.append(' ' * len(multiline_delim))
                        i += len(multiline_delim)
                        in_multiline_string = False
                        multiline_delim = None
                    else:
                        cleaned_line.append(' ')
                        i += 1
                    continue
                
                if in_multiline_comment:
                    if line[i:i+2] == '*/':
                        cleaned_line.append('  ')
                        i += 2
                        in_multiline_comment = False
                    else:
                        cleaned_line.append(' ')
                        i += 1
                    continue
                
                char = line[i]
                
                # Check for single-line comment
                if single_comment and line[i:i+len(single_comment)] == single_comment:
                    # Replace rest of line with spaces
                    remaining = line_len - i
                    cleaned_line.append(' ' * remaining)
                    break
                
                # Check for multi-line comment start /*
                if line[i:i+2] == '/*':
                    in_multiline_comment = True
                    cleaned_line.append('  ')
                    i += 2
                    continue
                
                # Check for triple-quoted strings (Python, GraphQL)
                if line[i:i+3] in ('"""', "'''"):
                    delim = line[i:i+3]
                    # Look for end on same line
                    end_pos = line.find(delim, i+3)
                    if end_pos != -1:
                        # Single-line triple-quoted string
                        length = end_pos - i + 3
                        cleaned_line.append(' ' * length)
                        i = end_pos + 3
                    else:
                        # Start of multiline string
                        in_multiline_string = True
                        multiline_delim = delim
                        cleaned_line.append('   ')
                        i += 3
                    continue
                
                # Check for regular strings
                if char in ('"', "'"):
                    quote = char
                    j = i + 1
                    while j < line_len:
                        if line[j] == '\\' and j + 1 < line_len:
                            j += 2  # Skip escaped char
                        elif line[j] == quote:
                            j += 1
                            break
                        else:
                            j += 1
                    # Replace string content with spaces
                    length = j - i
                    cleaned_line.append(' ' * length)
                    i = j
                    continue
                
                # Regular character - keep it
                cleaned_line.append(char)
                i += 1
            
            result.append(''.join(cleaned_line))
        
        return ''.join(result)
    
    # =========================================================================
    # IMPORT TRACKING - Detect and track import statements
    # =========================================================================
    
    def _extract_imports(self):
        """
        Extract import statements from the source.
        
        Detects common import patterns across languages:
        - Python: import X, from X import Y
        - JavaScript/TypeScript: import X from 'Y', require('Y')
        - Go: import "path"
        - etc.
        
        Populates self.imported_symbols with {name: source_hint}
        """
        if not self.source_content:
            return
        
        # Generic import patterns (covers most languages)
        import_patterns = [
            # Python: from module import name
            r'^\s*from\s+([a-zA-Z_][\w.]*)\s+import\s+([a-zA-Z_][\w,\s*]*)',
            # Python: import module
            r'^\s*import\s+([a-zA-Z_][\w.]*)',
            # JavaScript/TypeScript: import { name } from 'module'
            r'^\s*import\s+\{([^}]+)\}\s+from\s+[\'"]([^"\']+)[\'"]',
            # JavaScript/TypeScript: import name from 'module'
            r'^\s*import\s+([a-zA-Z_][\w]*)\s+from\s+[\'"]([^"\']+)[\'"]',
            # JavaScript: require('module')
            r'\brequire\s*\(\s*[\'"]([^"\']+)[\'"]\s*\)',
            # Go: import "path"
            r'^\s*import\s+[\'"]([^"\']+)[\'"]',
            # Go: import ( "path" )
            r'^\s*[\'"]([^"\']+)[\'"]',  # Inside import block
        ]
        
        lines = self.source_content.splitlines()
        in_import_block = False
        
        for line in lines:
            stripped = line.strip()
            
            # Track Go-style import blocks
            if stripped.startswith('import ('):
                in_import_block = True
                continue
            if in_import_block and stripped == ')':
                in_import_block = False
                continue
            
            for pattern in import_patterns:
                match = re.search(pattern, line)
                if match:
                    groups = match.groups()
                    if len(groups) >= 2:
                        # Pattern captured both name and source
                        names = groups[0]
                        source = groups[1]
                        # Handle multiple names (e.g., "name1, name2")
                        for name in re.split(r'[,\s]+', names):
                            name = name.strip().strip('*')
                            if name and name != 'as':
                                self.imported_symbols[name] = source
                                self.import_statements.append({
                                    'name': name,
                                    'source': source,
                                    'line': line
                                })
                    elif len(groups) == 1:
                        # Pattern captured just module name
                        module = groups[0]
                        # Extract short name (last component)
                        short_name = module.split('.')[-1].split('/')[-1]
                        self.imported_symbols[short_name] = module
                        self.import_statements.append({
                            'name': short_name,
                            'source': module,
                            'line': line
                        })
                    break
        
        log.debug('[GraphQL] Extracted ' + str(len(self.imported_symbols)) + ' imports from ' + self.path)
    
    # =========================================================================
    # PHASE 1: LIGHT PARSING
    # =========================================================================
    
    def light_parse(self):
        """
        PHASE 1: Light parsing to extract global structures.
        
        This method:
        1. Reads the source file
        2. Builds a coarse AST
        3. Extracts global elements (classes, functions, etc.)
        4. Creates CAST objects for discovered elements
        
        Override _build_light_ast() and _extract_globals() for custom logic.
        """
        log.debug('[GraphQL] Light parsing: ' + self.path)
        
        # Read source content
        self._read_source()
        
        # Build coarse AST
        self.ast = self._build_light_ast()
        
        # Create program-level object
        self._create_program_object()
        
        # Extract global structures
        self._extract_globals()
    
    def _read_source(self):
        """Read the source file content."""
        try:
            with open(self.path, 'r', encoding='utf-8') as f:
                self.source_content = f.read()
        except UnicodeDecodeError:
            # Fallback to latin-1 for non-UTF8 files
            with open(self.path, 'r', encoding='latin-1') as f:
                self.source_content = f.read()
        except Exception as e:
            log.warning('[GraphQL] Failed to read file: ' + str(e))
            self.source_content = ''
    
    def _get_structure_patterns(self):
        """
        Get regex patterns for detecting global structures.
        
        These patterns are configurable via config_input.json grammar section.
        Multiple patterns per object type are supported.
        
        Returns:
            dict: {node_type: [list of compiled_regex_patterns]}
        """
        # Patterns defined in config_input.json - multiple patterns per type supported
        raw_patterns = {
            'schema_def': ['^\\s*schema\\s*\\{', '^\\s*schema\\s*@[^{]*\\{'],
            'type_def': ['^\\s*type\\s+(?P<n>[A-Z][A-Za-z0-9_]*)\\s*\\{', '^\\s*type\\s+(?P<n>[A-Z][A-Za-z0-9_]*)\\s*@[^{]*\\{', '^\\s*type\\s+(?P<n>[A-Z][A-Za-z0-9_]*)\\s*$'],
            'type_def_implements': ['^\\s*type\\s+(?P<n>[A-Z][A-Za-z0-9_]*)\\s+implements\\s+[A-Z][A-Za-z0-9_]*\\s*\\{'],
            'type_def_implements_multiple': ['^\\s*type\\s+(?P<n>[A-Z][A-Za-z0-9_]*)\\s+implements\\s+[A-Z][A-Za-z0-9_&\\s]*\\s*\\{'],
            'type_extend': ['^\\s*extend\\s+type\\s+(?P<n>[A-Z][A-Za-z0-9_]*)\\s*\\{', '^\\s*extend\\s+type\\s+(?P<n>[A-Z][A-Za-z0-9_]*)\\s*@[^{]*\\{', '^\\s*extend\\s+type\\s+(?P<n>[A-Z][A-Za-z0-9_]*)\\s*$'],
            'type_extend_implements': ['^\\s*extend\\s+type\\s+(?P<n>[A-Z][A-Za-z0-9_]*)\\s+implements\\s+[A-Z][A-Za-z0-9_&\\s]*\\s*\\{'],
            'type_def_description': ['^\\s*"""[^"]*"""\\s*type\\s+(?P<n>[A-Z][A-Za-z0-9_]*)\\s*\\{', '^\\s*"[^"]*"\\s*type\\s+(?P<n>[A-Z][A-Za-z0-9_]*)\\s*\\{'],
            'interface_def': ['^\\s*interface\\s+(?P<n>[A-Z][A-Za-z0-9_]*)\\s*\\{', '^\\s*interface\\s+(?P<n>[A-Z][A-Za-z0-9_]*)\\s*@[^{]*\\{', '^\\s*interface\\s+(?P<n>[A-Z][A-Za-z0-9_]*)\\s*$'],
            'interface_def_implements': ['^\\s*interface\\s+(?P<n>[A-Z][A-Za-z0-9_]*)\\s+implements\\s+[A-Z][A-Za-z0-9_&\\s]*\\s*\\{'],
            'interface_extend': ['^\\s*extend\\s+interface\\s+(?P<n>[A-Z][A-Za-z0-9_]*)\\s*\\{', '^\\s*extend\\s+interface\\s+(?P<n>[A-Z][A-Za-z0-9_]*)\\s*$'],
            'interface_def_description': ['^\\s*"""[^"]*"""\\s*interface\\s+(?P<n>[A-Z][A-Za-z0-9_]*)\\s*\\{', '^\\s*"[^"]*"\\s*interface\\s+(?P<n>[A-Z][A-Za-z0-9_]*)\\s*\\{'],
            'enum_def': ['^\\s*enum\\s+(?P<n>[A-Z][A-Za-z0-9_]*)\\s*\\{', '^\\s*enum\\s+(?P<n>[A-Z][A-Za-z0-9_]*)\\s*@[^{]*\\{', '^\\s*enum\\s+(?P<n>[A-Z][A-Za-z0-9_]*)\\s*$'],
            'enum_extend': ['^\\s*extend\\s+enum\\s+(?P<n>[A-Z][A-Za-z0-9_]*)\\s*\\{', '^\\s*extend\\s+enum\\s+(?P<n>[A-Z][A-Za-z0-9_]*)\\s*$'],
            'enum_def_description': ['^\\s*"""[^"]*"""\\s*enum\\s+(?P<n>[A-Z][A-Za-z0-9_]*)\\s*\\{', '^\\s*"[^"]*"\\s*enum\\s+(?P<n>[A-Z][A-Za-z0-9_]*)\\s*\\{'],
            'enum_value': ['^\\s*(?P<n>[A-Z][A-Z0-9_]*)\\s*$', '^\\s*(?P<n>[A-Z][A-Z0-9_]*)\\s*(?:#|$)'],
            'enum_value_deprecated': ['^\\s*(?P<n>[A-Z][A-Z0-9_]*)\\s*@deprecated'],
            'enum_value_directive': ['^\\s*(?P<n>[A-Z][A-Z0-9_]*)\\s*@[a-zA-Z]'],
            'enum_value_description': ['^\\s*"""[^"]*"""\\s*(?P<n>[A-Z][A-Z0-9_]*)', '^\\s*"[^"]*"\\s*(?P<n>[A-Z][A-Z0-9_]*)'],
            'input_def': ['^\\s*input\\s+(?P<n>[A-Z][A-Za-z0-9_]*)\\s*\\{', '^\\s*input\\s+(?P<n>[A-Z][A-Za-z0-9_]*)\\s*@[^{]*\\{', '^\\s*input\\s+(?P<n>[A-Z][A-Za-z0-9_]*)\\s*$'],
            'input_extend': ['^\\s*extend\\s+input\\s+(?P<n>[A-Z][A-Za-z0-9_]*)\\s*\\{', '^\\s*extend\\s+input\\s+(?P<n>[A-Z][A-Za-z0-9_]*)\\s*$'],
            'input_def_description': ['^\\s*"""[^"]*"""\\s*input\\s+(?P<n>[A-Z][A-Za-z0-9_]*)\\s*\\{', '^\\s*"[^"]*"\\s*input\\s+(?P<n>[A-Z][A-Za-z0-9_]*)\\s*\\{'],
            'union_def': ['^\\s*union\\s+(?P<n>[A-Z][A-Za-z0-9_]*)\\s*=', '^\\s*union\\s+(?P<n>[A-Z][A-Za-z0-9_]*)\\s*@[^=]*=', '^\\s*union\\s+(?P<n>[A-Z][A-Za-z0-9_]*)\\s*$'],
            'union_extend': ['^\\s*extend\\s+union\\s+(?P<n>[A-Z][A-Za-z0-9_]*)\\s*=', '^\\s*extend\\s+union\\s+(?P<n>[A-Z][A-Za-z0-9_]*)\\s*$'],
            'union_def_description': ['^\\s*"""[^"]*"""\\s*union\\s+(?P<n>[A-Z][A-Za-z0-9_]*)\\s*=', '^\\s*"[^"]*"\\s*union\\s+(?P<n>[A-Z][A-Za-z0-9_]*)\\s*='],
            'scalar_def': ['^\\s*scalar\\s+(?P<n>[A-Z][A-Za-z0-9_]*)\\s*$', '^\\s*scalar\\s+(?P<n>[A-Z][A-Za-z0-9_]*)\\s*(?:#|$)'],
            'scalar_directive': ['^\\s*scalar\\s+(?P<n>[A-Z][A-Za-z0-9_]*)\\s*@'],
            'scalar_def_description': ['^\\s*"""[^"]*"""\\s*scalar\\s+(?P<n>[A-Z][A-Za-z0-9_]*)', '^\\s*"[^"]*"\\s*scalar\\s+(?P<n>[A-Z][A-Za-z0-9_]*)'],
            'directive_def': ['^\\s*directive\\s+@(?P<n>[a-z][A-Za-z0-9_]*)\\s+on\\s+'],
            'directive_def_with_args': ['^\\s*directive\\s+@(?P<n>[a-z][A-Za-z0-9_]*)\\s*\\('],
            'directive_def_repeatable': ['^\\s*directive\\s+@(?P<n>[a-z][A-Za-z0-9_]*)\\s*\\([^)]*\\)\\s*repeatable\\s+on'],
            'field_def': ['^\\s*(?P<n>[a-z][A-Za-z0-9_]*)\\s*:\\s*[A-Z\\[]', '^\\s*(?P<n>[a-z][A-Za-z0-9_]*)\\s*:\\s*[A-Z][A-Za-z0-9_]*\\s*(?:#|$)'],
            'field_def_with_args': ['^\\s*(?P<n>[a-z][A-Za-z0-9_]*)\\s*\\([^)]+\\)\\s*:\\s*'],
            'field_def_non_null': ['^\\s*(?P<n>[a-z][A-Za-z0-9_]*)\\s*(?:\\([^)]*\\))?\\s*:\\s*[A-Z\\[][^!]*!'],
            'field_def_list': ['^\\s*(?P<n>[a-z][A-Za-z0-9_]*)\\s*(?:\\([^)]*\\))?\\s*:\\s*\\[[A-Z][A-Za-z0-9_!]*\\]'],
            'field_def_list_non_null': ['^\\s*(?P<n>[a-z][A-Za-z0-9_]*)\\s*(?:\\([^)]*\\))?\\s*:\\s*\\[[A-Z][A-Za-z0-9_!]*\\]!'],
            'field_def_deprecated': ['^\\s*(?P<n>[a-z][A-Za-z0-9_]*)\\s*[:(][^@]*@deprecated'],
            'field_def_directive': ['^\\s*(?P<n>[a-z][A-Za-z0-9_]*)\\s*[:(][^@]*@[a-z]'],
            'field_def_description': ['^\\s*"""[^"]*"""\\s*(?P<n>[a-z][A-Za-z0-9_]*)\\s*:', '^\\s*"[^"]*"\\s*(?P<n>[a-z][A-Za-z0-9_]*)\\s*:'],
            'argument_def': ['\\s*(?P<n>[a-z][A-Za-z0-9_]*)\\s*:\\s*[A-Z\\[][A-Za-z0-9_\\[\\]!]*'],
            'argument_def_default': ['\\s*(?P<n>[a-z][A-Za-z0-9_]*)\\s*:\\s*[A-Z\\[][A-Za-z0-9_\\[\\]!]*\\s*='],
            'argument_def_non_null': ['\\s*(?P<n>[a-z][A-Za-z0-9_]*)\\s*:\\s*[A-Z\\[][A-Za-z0-9_\\[\\]]*!'],
            'argument_def_list': ['\\s*(?P<n>[a-z][A-Za-z0-9_]*)\\s*:\\s*\\[[A-Z][A-Za-z0-9_!]*\\]'],
            'query_operation': ['^\\s*(?P<n>query)\\s*\\{'],
            'query_operation_named': ['^\\s*query\\s+(?P<n>[A-Z][A-Za-z0-9_]*)\\s*\\{', '^\\s*query\\s+(?P<n>[A-Z][A-Za-z0-9_]*)\\s*$'],
            'query_operation_with_vars': ['^\\s*query\\s+(?P<n>[A-Z][A-Za-z0-9_]*)\\s*\\([^)]*\\)\\s*\\{', '^\\s*query\\s*\\([^)]*\\)\\s*\\{'],
            'query_operation_anonymous': ['^\\s*\\{\\s*[a-z][A-Za-z0-9_]*'],
            'mutation_operation': ['^\\s*(?P<n>mutation)\\s*\\{'],
            'mutation_operation_named': ['^\\s*mutation\\s+(?P<n>[A-Z][A-Za-z0-9_]*)\\s*\\{', '^\\s*mutation\\s+(?P<n>[A-Z][A-Za-z0-9_]*)\\s*$'],
            'mutation_operation_with_vars': ['^\\s*mutation\\s+(?P<n>[A-Z][A-Za-z0-9_]*)\\s*\\([^)]*\\)\\s*\\{', '^\\s*mutation\\s*\\([^)]*\\)\\s*\\{'],
            'subscription_operation': ['^\\s*(?P<n>subscription)\\s*\\{'],
            'subscription_operation_named': ['^\\s*subscription\\s+(?P<n>[A-Z][A-Za-z0-9_]*)\\s*\\{', '^\\s*subscription\\s+(?P<n>[A-Z][A-Za-z0-9_]*)\\s*$'],
            'subscription_operation_with_vars': ['^\\s*subscription\\s+(?P<n>[A-Z][A-Za-z0-9_]*)\\s*\\([^)]*\\)\\s*\\{', '^\\s*subscription\\s*\\([^)]*\\)\\s*\\{'],
            'fragment_def': ['^\\s*fragment\\s+(?P<n>[A-Z][A-Za-z0-9_]*)\\s+on\\s+[A-Z][A-Za-z0-9_]*\\s*\\{', '^\\s*fragment\\s+(?P<n>[A-Z][A-Za-z0-9_]*)\\s+on\\s+[A-Z][A-Za-z0-9_]*\\s*$'],
            'fragment_def_directive': ['^\\s*fragment\\s+(?P<n>[A-Z][A-Za-z0-9_]*)\\s+on\\s+[A-Z][A-Za-z0-9_]*\\s*@[a-z][^{]*\\{'],
            'inline_fragment': ['^\\s*\\.\\.\\.\\s*on\\s+(?P<n>[A-Z][A-Za-z0-9_]*)\\s*\\{'],
            'variable_def': ['\\$(?P<n>[a-z][A-Za-z0-9_]*)\\s*:\\s*[A-Z\\[][A-Za-z0-9_\\[\\]!]*'],
            'variable_def_default': ['\\$(?P<n>[a-z][A-Za-z0-9_]*)\\s*:\\s*[A-Z\\[][A-Za-z0-9_\\[\\]!]*\\s*='],
            'variable_def_non_null': ['\\$(?P<n>[a-z][A-Za-z0-9_]*)\\s*:\\s*[A-Z\\[][A-Za-z0-9_\\[\\]]*!'],
        }
        
        patterns = {}
        for obj_type, pattern_list in raw_patterns.items():
            compiled = []
            for p in pattern_list:
                try:
                    compiled.append(re.compile(p, re.IGNORECASE))
                except Exception as e:
                    log.warning('[GraphQL] Invalid pattern for ' + obj_type + ': ' + str(e))
            if compiled:
                patterns[obj_type] = compiled
        
        return patterns
    
    def _get_container_types(self):
        """
        Get object types that can contain other objects.
        
        Returns:
            set: Object types that have children (based on parent relationships)
        """
        container_types = set()
        for obj_type, obj_def in OBJECTS_CONFIG.items():
            parent = obj_def.get('parent', 'file')
            if parent != 'file' and parent != 'Program':
                # This parent type is a container
                container_types.add(parent)
        return container_types
    
    def _get_children_types(self, parent_type):
        """
        Get object types that can be children of a given parent type.
        
        Args:
            parent_type (str): Parent object type name
            
        Returns:
            set: Pattern keys for objects that are children of this type
        """
        child_patterns = set()
        for obj_type, obj_def in OBJECTS_CONFIG.items():
            if obj_def.get('parent') == parent_type:
                for pattern_key in obj_def.get('pattern_keys', []):
                    child_patterns.add(pattern_key)
        return child_patterns
    
    def _get_block_delimiter_style(self):
        """
        Get the block delimiter style for this language.
        
        Returns:
            str: 'braces', 'end_keyword', or 'indentation'
        """
        return 'braces'
    
    def _build_light_ast(self):
        """
        Build a coarse AST from the source content.
        
        Dynamically handles object hierarchy based on OBJECTS_CONFIG.
        Supports multiple block delimiter styles:
        - braces: {...} (Go, Java, Rust, C, etc.)
        - end_keyword: def...end (Ruby, Lua)
        - indentation: Python-style
        - sequential: Block ends when next block starts (COBOL, Assembly, MUMPS)
        
        Returns:
            ASTNode: Root node of the AST
        """
        root = ASTNode('module', self.get_base_name())
        root.start_line = 1
        root.end_line = len(self.source_content.splitlines()) if self.source_content else 1
        
        if not self.source_content:
            return root
        
        lines = self.source_content.splitlines()
        
        # Get patterns (multiple per type)
        patterns = self._get_structure_patterns()
        
        # Determine which pattern types are containers (can have children)
        container_patterns = set()
        for obj_type in self._get_container_types():
            for pattern_key in OBJECTS_CONFIG.get(obj_type, {}).get('pattern_keys', []):
                container_patterns.add(pattern_key)
        
        # ALL pattern types need to be tracked for end_line calculation
        all_tracked_patterns = set(patterns.keys())
        
        # Determine block delimiter style
        block_style = self._get_block_delimiter_style()
        
        # Stack of current containers: [(node, depth_marker)]
        # For braces: depth_marker = brace_depth at start
        # For end_keyword: depth_marker = keyword_depth
        # For indentation: depth_marker = indentation_level
        # For sequential: depth_marker = pattern_key (to match same-level blocks)
        container_stack = []
        depth = 0
        
        for i, line in enumerate(lines, 1):
            stripped = line.strip()
            
            # Calculate depth change based on block style
            if block_style == 'braces':
                open_count = line.count('{')
                close_count = line.count('}')
                new_depth = depth + open_count - close_count
                
                # Check if any containers have ended
                while container_stack and new_depth <= container_stack[-1][1]:
                    ended_node, _ = container_stack.pop()
                    ended_node.end_line = i
                
                depth = new_depth
                depth_at_match = depth - open_count  # Depth before the open brace
                should_track = open_count > 0
                
                # Flag for single-line blocks (e.g., "int func() { return 0; }")
                # This will be used to close the block immediately after adding it
                single_line_block = (open_count > 0 and close_count > 0 and open_count == close_count)
                
            elif block_style == 'end_keyword':
                # Count opening keywords (class, module, def, do, if, etc.)
                # and closing keywords (end)
                open_keywords = 0
                close_keywords = 0
                
                # Opening patterns - be careful with word boundaries
                # Includes both Ruby (class, module, def) and Lua (function) keywords
                if re.match(r'^\s*(class|module|def|do|if|unless|case|while|until|for|begin|function)\b', line):
                    open_keywords = 1
                # Handle block openers like { or do
                if re.search(r'\bdo\s*(\|[^|]*\|)?\s*$', line):
                    open_keywords = 1
                
                # Closing keyword
                if re.match(r'^\s*end\b', stripped):
                    close_keywords = 1
                
                new_depth = depth + open_keywords - close_keywords
                
                # Check if any containers have ended (when we see 'end')
                if close_keywords > 0 and container_stack:
                    ended_node, _ = container_stack.pop()
                    ended_node.end_line = i
                
                depth = new_depth
                depth_at_match = depth - open_keywords
                should_track = open_keywords > 0
                single_line_block = False  # Not applicable for end_keyword style
                
            elif block_style == 'indentation':
                # Calculate indentation level
                if stripped:  # Non-empty line
                    indent = len(line) - len(line.lstrip())
                    new_depth = indent
                    
                    # Check if any containers have ended (decreased indentation)
                    while container_stack and new_depth <= container_stack[-1][1] and stripped:
                        ended_node, _ = container_stack.pop()
                        ended_node.end_line = i - 1  # Previous line ends the block
                    
                    depth = new_depth
                else:
                    new_depth = depth  # Keep current depth for empty lines
                
                depth_at_match = depth
                should_track = True  # Always track in indentation mode
                single_line_block = False  # Not applicable for indentation style
                
            elif block_style == 'sequential':
                # Sequential mode: blocks end when the next block at same level starts
                # Used for COBOL paragraphs, Assembly labels, MUMPS routines, etc.
                # We'll check for matches first, then close previous blocks
                depth_at_match = 0
                should_track = True  # Always track in sequential mode
                single_line_block = False  # Not applicable for sequential style
                # Note: block closing happens AFTER pattern matching below
            
            else:
                # Default to braces behavior
                depth_at_match = 0
                should_track = True
                single_line_block = False
            
            # Now check for pattern matches
            matched_on_line = False
            for pattern_key, pattern_list in patterns.items():
                if matched_on_line:
                    break
                for pattern in pattern_list:
                    match = pattern.match(line)
                    if match:
                        # Support both (?P<name>...) and (?P<n>...) named groups
                        groups = match.groupdict()
                        if 'name' in groups:
                            name = match.group('name')
                        elif 'n' in groups:
                            name = match.group('n')
                        else:
                            name = match.group(1) if match.groups() else None
                        
                        if not name:
                            continue
                        
                        node = ASTNode(pattern_key, name, start_line=i)
                        
                        # Check for receiver/parent group in pattern
                        if 'receiver' in match.groupdict() and match.group('receiver'):
                            receiver = match.group('receiver').lstrip('*')
                            node.properties['receiver'] = receiver
                        
                        # Determine where to add this node based on hierarchy
                        obj_type = PATTERN_TO_OBJECT_TYPE.get(pattern_key)
                        parent_type = OBJECT_PARENTS.get(obj_type, 'Program') if obj_type else 'Program'
                        
                        # SEQUENTIAL MODE: Close previous block of same or higher level
                        # before adding the new one
                        if block_style == 'sequential' and container_stack:
                            # Close all blocks at same level or lower in hierarchy
                            # A new block at same level closes the previous one
                            while container_stack:
                                prev_node, prev_pattern = container_stack[-1]
                                prev_obj_type = PATTERN_TO_OBJECT_TYPE.get(prev_node.type)
                                prev_parent = OBJECT_PARENTS.get(prev_obj_type, 'Program') if prev_obj_type else 'Program'
                                
                                # If previous block is at same level (same parent), close it
                                # Also close if new block is at a higher level
                                if prev_parent == parent_type or parent_type in ('Program', 'file'):
                                    ended = container_stack.pop()
                                    ended[0].end_line = i - 1
                                else:
                                    break
                        
                        # Find the appropriate parent in the stack
                        added = False
                        if parent_type != 'Program' and parent_type != 'file':
                            for container_node, _ in reversed(container_stack):
                                container_obj_type = PATTERN_TO_OBJECT_TYPE.get(container_node.type)
                                if container_obj_type == parent_type:
                                    container_node.add_child(node)
                                    added = True
                                    break
                            
                            if not added and container_stack:
                                nearest_container, _ = container_stack[-1]
                                nearest_container.add_child(node)
                                added = True
                        
                        if not added:
                            root.add_child(node)
                        
                        # Track this construct for end_line calculation
                        if pattern_key in all_tracked_patterns and should_track:
                            # For sequential mode, store pattern_key as depth_marker
                            if block_style == 'sequential':
                                container_stack.append((node, pattern_key))
                            else:
                                container_stack.append((node, depth_at_match))
                            
                            # Close immediately if this is a single-line block
                            if block_style == 'braces' and 'single_line_block' in locals() and single_line_block:
                                node.end_line = i
                                container_stack.pop()
                        
                        matched_on_line = True
                        break
        
        # Close any remaining open containers at end of file
        while container_stack:
            ended_node, _ = container_stack.pop()
            if ended_node.end_line == 0:
                ended_node.end_line = len(lines)
        
        return root
    
    def _create_program_object(self):
        """Create the program-level container object."""
        self.program = CustomObject()
        self.program.set_type('GraphQLProgram')
        self.program.set_name(self.get_filename())
        self.program.set_fullname(self.path)
        self.program.set_parent(self.file)
        self.program.set_guid(self._generate_guid('GraphQLProgram', self.path, 0))
        self.program.save()
        
        # Bookmark must be set AFTER save() - allows F11 Code Viewer
        if self.ast and self.ast.end_line > 0:
            self._set_bookmark(self.program, 1, self.ast.end_line)
        
        # Register in objects
        self._register_object(self.path, self.program, self.get_filename(), 'GraphQLProgram')
    
    def _extract_globals(self):
        """
        Extract global structures from the AST.
        
        Dynamically creates CAST objects based on OBJECTS_CONFIG hierarchy.
        Uses the parser registry for extensibility.
        """
        if not self.ast:
            return
        
        # Process all children of root AST node
        for node in self.ast.children:
            # Check registry for custom handlers first
            handlers = PARSER_REGISTRY.get_handlers(node.type)
            for handler in handlers:
                try:
                    handler(node, self)
                except Exception as e:
                    log.debug('[GraphQL] Handler error: ' + str(e))
            
            # Extract object using dynamic hierarchy
            self._extract_object(node, self.program, '')
    
    def _extract_object(self, node, parent_cast_obj, parent_name_prefix):
        """
        Dynamically extract an object based on OBJECTS_CONFIG.
        
        Args:
            node (ASTNode): AST node to extract
            parent_cast_obj: Parent CAST object
            parent_name_prefix (str): Prefix for fullname (e.g., 'ClassName.')
            
        Returns:
            CustomObject: The created CAST object
        """
        # Determine object type from pattern key
        pattern_key = node.type
        obj_type = PATTERN_TO_OBJECT_TYPE.get(pattern_key)
        
        if not obj_type:
            # Unknown pattern, skip
            log.debug('[GraphQL] Unknown pattern type: ' + pattern_key)
            return None
        
        # Build fullname based on hierarchy BEFORE creating object
        # Priority: 1) receiver from pattern (Go-style), 2) parent_name_prefix from AST, 3) none
        effective_prefix = parent_name_prefix
        if 'receiver' in node.properties:
            # For Go-style methods: use receiver as prefix
            effective_prefix = node.properties['receiver'] + '.'
        
        # Use FULL PATH instead of just filename to ensure unique fullnames
        # This prevents collisions when multiple files have the same name in different folders
        if effective_prefix:
            fullname = self.path + '.' + effective_prefix + node.name
        else:
            fullname = self.path + '.' + node.name
        
        # DUPLICATE PREVENTION: Skip if fullname already exists
        # This handles cases where multiple patterns match the same construct
        if fullname in self.objects:
            log.debug('[GraphQL] Skipping duplicate: ' + fullname)
            # Still process children in case they're unique
            child_name_prefix = parent_name_prefix + node.name + '.'
            for child in node.children:
                self._extract_object(child, self.objects[fullname], child_name_prefix)
            return self.objects[fullname]
        
        # Create CAST object
        cast_obj = CustomObject()
        cast_obj.set_type('GraphQL' + obj_type)
        cast_obj.set_name(node.name)
        cast_obj.set_fullname(fullname)
        cast_obj.set_parent(parent_cast_obj)
        cast_obj.set_guid(self._generate_guid('GraphQL' + obj_type, fullname, node.start_line))
        cast_obj.save()
        
        # Bookmark must be set AFTER save()
        if node.start_line > 0:
            self._set_bookmark(cast_obj, node.start_line, node.end_line or node.start_line)
        
        self._register_object(fullname, cast_obj, node.name, 'GraphQL' + obj_type, node.start_line, node.end_line or node.start_line)
        
        # Recursively extract children (e.g., methods inside classes)
        child_name_prefix = parent_name_prefix + node.name + '.'
        for child in node.children:
            self._extract_object(child, cast_obj, child_name_prefix)
    
    def _register_object(self, fullname, obj, short_name=None, obj_type=None, start_line=0, end_line=0):
        """Register an object in the module's symbol table."""
        self.objects[fullname] = obj
        # Store line range for caller resolution
        if start_line > 0:
            self.object_lines[fullname] = (start_line, end_line if end_line > 0 else start_line)
        # Store by type name (passed explicitly since get_type() may not work after save)
        type_name = obj_type if obj_type else 'unknown'
        self.objects_by_type[type_name].append(obj)
        # Store short_name for later registration in library
        if short_name:
            if not hasattr(self, '_short_names'):
                self._short_names = {}
            self._short_names[fullname] = short_name
        log.debug('[GraphQL] Created object: ' + fullname + ' (type: ' + type_name + ')')

    def _generate_guid(self, cast_type, fullname, start_line=0):
        """Create deterministic GUIDs combining type, file path and location."""
        safe_path = self.path.replace('?', '_')
        line_marker = start_line if start_line is not None else 0
        return cast_type + '?[' + safe_path + '].' + fullname + '@' + str(line_marker)
    
    def _set_bookmark(self, obj, start_line, end_line):
        """Set a bookmark on an object for source code location."""
        try:
            if self.file and start_line > 0:
                # Create bookmark following Easytrieve pattern:
                # end_line + 1 and end_column = 1
                bookmark = Bookmark(self.file, start_line, 1, end_line + 1, 1)
                obj.save_position(bookmark)
        except Exception as e:
            log.info('[GraphQL] Bookmark error: ' + str(e))
    
    # =========================================================================
    # PHASE 2: FULL PARSING - LINK DETECTION (MANUAL IMPLEMENTATION REQUIRED)
    # =========================================================================
    #
    # IMPORTANT: Generic link detection has been removed from this generator.
    #
    # WHY GENERIC LINK DETECTION DOES NOT WORK:
    # -----------------------------------------
    # 1. Without a full semantic parser, we cannot determine variable types
    #    Example: "obj.method()" - we don't know what type "obj" is
    #
    # 2. Without import resolution, we cannot link cross-file calls
    #    Example: "from utils import helper" then "helper()" - requires import analysis
    #
    # 3. Different languages have radically different calling conventions
    #    Example: Lua uses ":" for method calls, Ruby uses implicit receivers
    #
    # 4. Generic regex patterns produce too many false positives
    #    Example: "if(" matches as a function call without language-specific keywords
    #
    # WHAT YOU MUST IMPLEMENT:
    # ------------------------
    # For each technology, you must implement custom logic in:
    #   - full_parse(): Detect calls using technology-specific patterns
    #   - resolve(): Resolve call targets using technology-specific rules
    #   - save_links(): Create links using the CAST SDK
    #
    # REUSING OBJECTS FROM PASS 1:
    # ----------------------------
    # All objects created in Pass 1 are available in:
    #   - self.objects: dict {fullname -> CustomObject}
    #   - self.object_lines: dict {fullname -> (start_line, end_line)}
    #   - library.symbols: dict {fullname -> CustomObject} (global)
    #   - library.symbols_by_name: dict {short_name -> [fullnames]} (global)
    #
    # =========================================================================
    
    def full_parse(self):
        """
        PHASE 2: Full parsing for link detection - MANUAL IMPLEMENTATION REQUIRED.
        
        This method is a SKELETON. You must implement technology-specific logic
        to detect function/method calls in the source code.
        
        WHAT TO IMPLEMENT:
        ------------------
        1. Parse the source code to find call sites (function calls, method calls)
        2. For each call, determine:
           - The CALLER: Which function/method contains the call?
           - The CALLEE: What is being called? (function name, method name)
           - The LINE: Where does the call occur?
        3. Store call information in self.pending_links for later resolution
        
        ACCESSING SOURCE CODE:
        ----------------------
        - self.source_content: Raw source file content (string)
        - self.path: Full path to the source file
        
        ACCESSING OBJECTS FROM PASS 1:
        ------------------------------
        - self.objects: All objects created in this file {fullname: CustomObject}
        - self.object_lines: Line ranges for each object {fullname: (start, end)}
        - self.program: The Program (file-level) object
        
        PENDING LINKS FORMAT:
        ---------------------
        Each entry in self.pending_links should be a dict:
        {
            'caller': fullname of the calling function/method,
            'callee': name of the called function/method (to be resolved),
            'type': 'call' (or other link type),
            'line': line number of the call
        }
        
        EXAMPLE IMPLEMENTATION (pseudo-code):
        -------------------------------------
        def full_parse(self):
            if not self.source_content:
                return
            
            lines = self.source_content.splitlines()
            for line_num, line in enumerate(lines, 1):
                # Technology-specific: detect calls in this line
                # Example for a simple "name()" pattern:
                for match in re.finditer(r'\\b(\\w+)\\s*\\(', line):
                    callee_name = match.group(1)
                    
                    # Skip language keywords
                    if callee_name in {'if', 'while', 'for'}:
                        continue
                    
                    # Find which function contains this line
                    caller = self._find_caller_for_line(line_num)
                    
                    self.pending_links.append({
                        'caller': caller,
                        'callee': callee_name,
                        'type': 'call',
                        'line': line_num
                    })
        """
        # =====================================================================
        # SKELETON - IMPLEMENT YOUR TECHNOLOGY-SPECIFIC CALL DETECTION HERE
        # =====================================================================
        #
        # This method intentionally does nothing by default.
        # You must implement call detection for your specific technology.
        #
        # See the docstring above for guidance on what to implement.
        #
        pass
    
    def _extract_calls(self):
        """
        SKELETON - Technology-specific call extraction.
        
        THIS METHOD IS INTENTIONALLY EMPTY.
        Implement technology-specific call detection logic here.
        
        See full_parse() docstring for implementation guidance.
        """
        # =====================================================================
        # IMPLEMENT YOUR TECHNOLOGY-SPECIFIC CALL DETECTION HERE
        # =====================================================================
        pass
    
    def _find_caller_for_line(self, line_num):
        """
        HELPER: Find which function/method contains a given line number.
        
        Use this in your full_parse() implementation to determine the caller
        for a call detected on a specific line.
        
        Args:
            line_num (int): Line number (1-based)
            
        Returns:
            str: Fullname of the containing function/method, or self.path if at file level
        """
        # Search through object line ranges to find the innermost containing object
        best_match = self.path  # Default to file-level
        best_range = float('inf')
        
        for fullname, (start, end) in self.object_lines.items():
            if fullname == self.path:
                continue  # Skip the Program object
            if start <= line_num <= end:
                range_size = end - start
                if range_size < best_range:
                    best_match = fullname
                    best_range = range_size
        
        return best_match
    
    # =========================================================================
    # RESOLUTION AND LINK CREATION - MANUAL IMPLEMENTATION REQUIRED
    # =========================================================================
    #
    # The methods below are SKELETONS for technology-specific implementation.
    #
    # CAST SDK LINK TYPES (IMPORTANT - ONLY THESE ARE ALLOWED):
    # ----------------------------------------------------------
    # The CAST SDK only supports a predefined set of link types.
    # You CANNOT invent new link types - they must be declared in MetaModel XML.
    #
    # Common predefined link types:
    #   - 'callLink'     : Function/method calls
    #   - 'useLink'      : General usage (read/write access)
    #   - 'relyonLink'   : Dependency relationship
    #   - 'inheritLink'  : Inheritance relationship
    #   - 'referLink'    : Reference/mention
    #
    # To check available link types, see the MetaModel XML files in the
    # product_extensions_examples/ folder or the CAST SDK documentation.
    #
    # =========================================================================
    
    def resolve(self, library):
        """
        PHASE 2: Resolve call targets - MANUAL IMPLEMENTATION REQUIRED.
        
        This method is a SKELETON. You must implement technology-specific logic
        to resolve call targets (i.e., determine which object is being called).
        
        WHAT TO IMPLEMENT:
        ------------------
        1. Iterate through self.pending_links (populated by full_parse)
        2. For each pending link, resolve the callee name to an actual object
        3. Update the link entry with the resolved object
        
        ACCESSING THE GLOBAL SYMBOL TABLE:
        ----------------------------------
        The 'library' parameter provides access to ALL objects across ALL files:
        
        - library.symbols: dict {fullname -> CustomObject}
          All objects indexed by their full qualified name.
          Example: library.symbols['src/utils.py.helper']
        
        - library.symbols_by_name: dict {short_name -> [fullnames]}
          Objects indexed by short name (may have multiple matches).
          Example: library.symbols_by_name['helper'] -> ['file1.helper', 'file2.helper']
        
        RESOLUTION STRATEGIES:
        ----------------------
        Different technologies require different strategies:
        
        1. INTRA-FILE RESOLUTION (same file):
           - Look for the callee in self.objects first
           - Simple: callee_obj = self.objects.get(fullname)
        
        2. CROSS-FILE RESOLUTION (across files):
           - Use library.symbols_by_name to find candidates
           - May require import analysis to disambiguate
        
        3. METHOD RESOLUTION (on objects):
           - Requires type information (not available in generic parser)
           - Usually requires language-specific semantic analysis
        
        UPDATING PENDING LINKS:
        -----------------------
        For each resolved link, add the resolved object to the link_info dict:
        
            link_info['resolved_callee'] = callee_obj  # The CustomObject
            link_info['resolved_callee_fullname'] = fullname  # For debugging
        
        Links without 'resolved_callee' will be skipped by save_links().
        
        Args:
            library: The global library containing all symbols across all files
        """
        # =====================================================================
        # SKELETON - IMPLEMENT YOUR TECHNOLOGY-SPECIFIC RESOLUTION HERE
        # =====================================================================
        #
        # Example implementation (pseudo-code):
        #
        # for link_info in self.pending_links:
        #     callee_name = link_info['callee']
        #     
        #     # Strategy 1: Try same-file resolution first
        #     for fullname, obj in self.objects.items():
        #         if fullname.endswith('.' + callee_name):
        #             link_info['resolved_callee'] = obj
        #             link_info['resolved_callee_fullname'] = fullname
        #             break
        #     
        #     # Strategy 2: Try cross-file if not found locally
        #     if 'resolved_callee' not in link_info:
        #         candidates = library.symbols_by_name.get(callee_name, [])
        #         if len(candidates) == 1:  # Only if unambiguous
        #             fullname = candidates[0]
        #             link_info['resolved_callee'] = library.symbols[fullname]
        #             link_info['resolved_callee_fullname'] = fullname
        #
        pass
    
    def save_links(self):
        """
        PHASE 2: Create links in CAST - MANUAL IMPLEMENTATION REQUIRED.
        
        This method creates links using the CAST SDK for all resolved calls.
        You may need to customize this for technology-specific link types.
        
        =====================================================================
        CAST SDK: create_link() FUNCTION
        =====================================================================
        
        The create_link() function creates a relationship between two objects
        in the CAST knowledge base. These links are visible in CAST Imaging
        and used for architecture analysis.
        
        FUNCTION SIGNATURE:
        -------------------
        from cast.analysers import create_link, Bookmark
        
        create_link(link_type, caller, callee)
        create_link(link_type, caller, callee, bookmark)
        
        PARAMETERS:
        -----------
        - link_type (str): The type of link to create.
          MUST be one of the predefined types (see below).
          Examples: 'callLink', 'useLink', 'inheritLink'
        
        - caller (CustomObject): The SOURCE object (who is calling).
          Must be a saved CustomObject from Pass 1.
        
        - callee (CustomObject): The TARGET object (who is being called).
          Must be a saved CustomObject from Pass 1.
        
        - bookmark (Bookmark, optional): Source location of the call.
          Allows navigation to the exact line in CAST Imaging.
        
        PREDEFINED LINK TYPES (DO NOT INVENT NEW ONES):
        ------------------------------------------------
        The following link types are predefined in CAST:
        
        | Link Type     | Meaning                        | Example                    |
        |---------------|--------------------------------|----------------------------|
        | 'callLink'    | Function/method invocation     | foo() calls bar()          |
        | 'useLink'     | Uses/reads/writes              | function uses variable     |
        | 'relyonLink'  | Dependency relationship        | module relies on library   |
        | 'inheritLink' | Inheritance                    | class extends parent       |
        | 'referLink'   | Reference/mention              | code references constant   |
        
        Custom link types can be defined in the MetaModel XML file.
        
        CREATING A BOOKMARK:
        --------------------
        from cast.analysers import Bookmark
        
        # Bookmark(file, start_line, start_col, end_line, end_col)
        bookmark = Bookmark(self.file, line_num, 1, line_num, -1)
        
        - file: The CAST File object (self.file)
        - start_line, end_line: 1-based line numbers
        - start_col: 1-based column (usually 1 for start of line)
        - end_col: -1 means end of line
        
        EXAMPLE:
        --------
        # Create a call link from function A to function B at line 42
        caller_obj = self.objects['src/main.py.process']
        callee_obj = library.symbols['src/utils.py.helper']
        bookmark = Bookmark(self.file, 42, 1, 42, -1)
        
        create_link('callLink', caller_obj, callee_obj, bookmark)
        
        WHAT THIS CREATES IN IMAGING:
        -----------------------------
        In CAST Imaging, this link will appear as:
        
            process() ──callLink──> helper()
        
        Users can click on the link to navigate to line 42 in the source file.
        
        =====================================================================
        
        Returns:
            int: Number of links created
        """
        # =====================================================================
        # SKELETON - IMPLEMENT YOUR TECHNOLOGY-SPECIFIC LINK CREATION HERE
        # =====================================================================
        #
        # Example implementation:
        #
        # links_created = 0
        # for link_info in self.pending_links:
        #     if 'resolved_callee' not in link_info:
        #         continue  # Skip unresolved links
        #     
        #     caller_fullname = link_info['caller']
        #     callee_obj = link_info['resolved_callee']
        #     line = link_info.get('line', 0)
        #     
        #     caller_obj = self.objects.get(caller_fullname)
        #     if not caller_obj:
        #         continue
        #     
        #     # Create bookmark for navigation
        #     bookmark = None
        #     if line > 0 and self.file:
        #         bookmark = Bookmark(self.file, line, 1, line, -1)
        #     
        #     # Create the link using CAST SDK
        #     if bookmark:
        #         create_link('callLink', caller_obj, callee_obj, bookmark)
        #     else:
        #         create_link('callLink', caller_obj, callee_obj)
        #     
        #     links_created += 1
        # 
        # return links_created
        #
        return 0  # Skeleton returns 0 - implement your logic above
    
    # =========================================================================
    # CLEANUP
    # =========================================================================
    
    def clean_ast(self):
        """
        Clean up the AST and temporary data to free memory.
        
        Called after Phase 2 processing is complete.
        """
        self.ast = None
        self.source_content = None
        self.cleaned_source = None
        log.debug('[GraphQL] Cleaned AST for: ' + self.path)


# =============================================================================
# EXTENSIBILITY EXAMPLES
# =============================================================================

def register_custom_handler(node_type, handler):
    """
    Register a custom handler for a node type.
    
    Example usage:
        def my_class_handler(node, module):
            # Custom class processing logic
            pass
        
        register_custom_handler('class', my_class_handler)
    
    Args:
        node_type (str): AST node type to handle
        handler (callable): Handler function(node, module)
    """
    PARSER_REGISTRY.register(node_type, handler)


def register_pattern_handler(pattern, handler):
    """
    Register a handler for nodes matching a pattern.
    
    Args:
        pattern (str): Regex pattern for node types
        handler (callable): Handler function(node, module)
    """
    PARSER_REGISTRY.register_pattern(pattern, handler)
