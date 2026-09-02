"""
Apollo Client TypeScript Interpreter
Based on vue_basic_interpreter_ts.py structure, adapted for Apollo Client hooks and GraphQL operations.
"""
try:
    import os
    import re
    import traceback
    from collections import OrderedDict
    from cast.analysers import log
    
    # Import from typescript_dependencies
    from typescript_dependencies.typescript_walker import is_ts_node_type, get_descendants, is_ts_symbol_type, Walker
    from typescript_dependencies.symbols import SourceFile
    from typescript_dependencies.evaluation import EvaluationTool
    
    # Local imports
    from ts_parser.analysis_results import ApolloAnalysisResults, RawBookmark, GqlDefinition
    from ts_parser.apollo_symbols import ApolloHookObject, ApolloClientMethodObject, ApolloHookSymbol, GqlDefinitionSymbol
except:
    from cast.analysers import log
    import traceback
    log.info('Problem in imports: ' + str(traceback.format_exc()))


# List of Apollo Client hooks to detect
APOLLO_HOOKS = ['useQuery', 'useMutation', 'useSubscription', 'useLazyQuery']

# List of Apollo Client methods (for future support)
APOLLO_CLIENT_METHODS = ['query', 'mutate', 'subscribe']

# ─── PATTERN 2: Codegen-generated typed hooks ─────────────────────────────────
# Matches: useGetUsersQuery, useCreateUserMutation, useSubscribeSubscription, etc.
# Pattern: use[UpperCamelCase](Query|Mutation|Subscription)
CODEGEN_HOOK_PATTERN = re.compile(r'^use[A-Z][A-Za-z0-9]+(Query|Mutation|Subscription)$')

# ─── Structured log helpers ────────────────────────────────────────────────────
# Format: [GraphQL][TS][<STAGE>][<ENTITY>][ctx=N] message
# DETECT   → a GraphQL/Apollo pattern was recognized in the AST
# DECISION → the analyzer inferred semantics or chose a code branch
# RESULT   → a CAST object or link was created / registered

_ctx_seq = [0]


def _ctx():
    _ctx_seq[0] += 1
    return _ctx_seq[0]


def _glog(stage, entity, ctx, msg):
    log.info('[GraphQL][TS][{}][{}][ctx={}] {}'.format(stage, entity, ctx, msg))


# ─── PATTERN 3: Angular this.apollo.* calls ───────────────────────────────────
# Maps the Apollo service method name to the normalized React hook name.
# watchQuery → useLazyQuery (both are "lazy" / deferred execution patterns).
ANGULAR_METHOD_TO_HOOK = {
    'query':      'useQuery',
    'mutate':     'useMutation',
    'watchQuery': 'useLazyQuery',
}

# ─── PATTERN 1: Direct Apollo Client imperative calls ─────────────────────────
# Maps client.X() method name to the normalized hook name used for KB objects.
# Note: 'subscribe' maps to useSubscription (client.subscribe({query: X})).
CLIENT_METHOD_TO_HOOK = {
    'query':     'useQuery',
    'mutate':    'useMutation',
    'subscribe': 'useSubscription',
}

# Union of all method names handled by Patterns 1 & 3 (used in MethodCall scan).
ALL_RECEIVER_METHODS = set(ANGULAR_METHOD_TO_HOOK) | set(CLIENT_METHOD_TO_HOOK)
# = {'query', 'mutate', 'watchQuery', 'subscribe'}

# ─── gql tag alias support ────────────────────────────────────────────────────
# Packages that export a `gql` tagged-template function under any local name.
GQL_PACKAGES = frozenset([
    'graphql-tag', '@apollo/client', '@apollo/client/core',
    'apollo-boost', 'apollo-client', 'apollo-cache-inmemory',
    'apollo-link', 'react-apollo', '@apollo/react-hooks',
    '@apollo/react-hoc', '@apollo/react-components',
])


def _build_gql_tag_names(module):
    """
    Scan the import statements of *module* and return the set of local names
    bound to the gql tag function in this file.

    Always includes 'gql' (canonical).  Adds any aliases such as:
      import { gql as gqlTag } from '@apollo/client'  → adds 'gqlTag'
      import gqlTag from 'graphql-tag'                → adds 'gqlTag'
    """
    gql_names = {'gql'}
    try:
        for imp in module.get_imports():
            imp_str = str(imp)
            # Check if this import is from a known gql-providing package.
            from_gql_pkg = any(
                ("'" + pkg + "'") in imp_str or ('"' + pkg + '"') in imp_str
                for pkg in GQL_PACKAGES
            )
            if not from_gql_pkg:
                continue

            # Named imports: { gql } or { gql as gqlTag }
            try:
                elements = imp.get_imported_elements()
                if elements:
                    for elem in elements:
                        try:
                            original = elem.get_element_name()
                            if original == 'gql':
                                alias = elem.get_alias_name() or original
                                gql_names.add(alias)
                        except Exception:
                            pass
                    continue  # Named import handled; skip default-import detection
            except Exception:
                pass

            # Default import: import gqlTag from 'graphql-tag'
            # The first Identifier sub-node of the Import node IS the default-import name.
            try:
                for sub in imp.get_sub_nodes():
                    if type(sub).__name__ == 'Identifier':
                        name = sub.get_name() if hasattr(sub, 'get_name') else None
                        if name:
                            gql_names.add(name)
                        break
            except Exception:
                pass
    except Exception:
        pass
    return gql_names


def _is_var_exported(var_decl):
    """
    Return True if this VariableDeclaration is preceded by a bare 'export' token
    among its parent's raw children.

    For 'export const X = gql`...`', the bundled parser emits two siblings at
    Root level: Token('export') then VariableDeclaration[const X = ...].
    The VariableDeclaration itself has no is_exported / get_modifiers attribute.
    """
    parent = getattr(var_decl, 'parent', None)
    if parent is None:
        return False
    raw_children = getattr(parent, 'children', None)
    if raw_children is None:
        return False
    try:
        idx = raw_children.index(var_decl)
    except ValueError:
        return False
    # Scan backwards, skipping whitespace tokens (up to 4 positions)
    for k in range(idx - 1, max(idx - 4, -1), -1):
        prev = raw_children[k]
        prev_text = getattr(prev, 'text', '')
        if prev_text == 'export':
            return True
        if prev_text and prev_text.strip():
            break  # Hit a non-whitespace non-export token — not exported
    return False


def analyse_ts_fragment(ts_fragment, apollo_analysis_results):
    """
    Main entry point for analyzing a TypeScript fragment for Apollo Client usage.
    Similar to analyse_ts_fragment in vue_basic_interpreter_ts.py

    Args:
        ts_fragment: TypeScript SourceFile to analyze
        apollo_analysis_results: ApolloAnalysisResults instance to store results

    Returns:
        ApolloBasicInterpreterTS instance or None on error
    """
    try:
        interpreter = ApolloBasicInterpreterTS(ts_fragment, apollo_analysis_results)
        apollo_analysis_results.ts_files.append(ts_fragment)

        # Create walker and register interpreter
        walker = Walker()
        walker.register_interpreter(interpreter)

        # Get AST fragments
        fragments = ts_fragment._ast_fragments
        if not fragments:
            fragments = [ts_fragment.get_ast()]

        # Walk through all fragments
        for frag in fragments:
            walker.walk(frag.get_children())

        # Post-processing after walking the AST
        interpreter.on_end()

        return interpreter
    except Exception:
        log.warning("Problem during analysis of ts_fragment for Apollo Client")
        log.warning(traceback.format_exc())
        return None


class BaseFrameworkInterpreter:
    """
    Base interpreter class for framework-specific analysis.
    Similar to BaseFrameworkInterpreter in vue_basic_interpreter_ts.py
    """

    def __init__(self, module):
        self.__module = module
        self.__symbol_stack = [module]

    def push_symbol(self, symbol):
        return self.__symbol_stack.append(symbol)

    def pop_symbol(self):
        self.__symbol_stack.pop()

    def get_program(self):
        return self.get_current_module().get_program()

    def get_current_callable(self):
        symbol = self.__symbol_stack[-1]
        while is_ts_node_type(symbol, 'Class'):
            symbol_initializer = symbol.get_initializer()
            if symbol_initializer:
                return symbol_initializer
            else:
                symbol = symbol.get_parent_symbol()
        return symbol

    def get_current_module(self):
        return self.__module

    def _get_current_symbol(self):
        return self.__symbol_stack[-1]

    def get_current_class(self):
        """
        @rtype : symbols.Class | None
        """
        symbol = self._get_current_symbol()
        while symbol and not is_ts_symbol_type(symbol, 'Class'):
            symbol = symbol.get_parent_symbol()
        return symbol

    def get_current_method(self):
        """
        @rtype : symbols.Method | None
        """
        symbol = self._get_current_symbol()
        while symbol and not is_ts_node_type(symbol, 'Method'):
            symbol = symbol.get_parent_symbol()
        return symbol

    def get_current_function(self):
        """
        @rtype : symbols.Function | None
        """
        symbol = self._get_current_symbol()
        while symbol and not is_ts_symbol_type(symbol, 'Function'):
            symbol = symbol.get_parent_symbol()
        return symbol

    def start_Class(self, _ast_class):
        """
        @type _ast_class: typescript_parser.parser.Class
        """
        _class = self._get_current_symbol().get_class(_ast_class.get_name(), _ast_class.get_begin_line())
        # Guard: never push None — re-push the current symbol so end_Class still pops correctly
        self.push_symbol(_class or self._get_current_symbol())

    def end_Class(self, _ast_class):
        self.pop_symbol()

    def start_Namespace(self, _ast):
        """
        @type _ast: typescript_parser.parser.Namespace
        """
        namespace = self._get_current_symbol().get_namespace(_ast.get_name())
        self.push_symbol(namespace or self._get_current_symbol())

    def end_Namespace(self, _ast_namespace):
        self.pop_symbol()

    def start_Interface(self, _ast):
        """
        @type _ast: typescript_parser.parser.Interface
        """
        interface = self._get_current_symbol().get_interface(_ast.get_name())
        self.push_symbol(interface or self._get_current_symbol())

    def end_Interface(self, _ast):
        self.pop_symbol()

    def start_ArrowExpression(self, _ast_function):
        if _ast_function.is_arrow_function:
            self.start_Function(_ast_function)
        elif _ast_function.is_arrow_method:
            self.start_Method(_ast_function)

    def end_ArrowExpression(self, _ast_function):
        if _ast_function.is_arrow_function:
            self.end_Function(_ast_function)
        elif _ast_function.is_arrow_method:
            self.end_Method(_ast_function)

    def start_Function(self, _ast_function):
        """
        @type _ast_function: typescript_parser.parser.Function
        """
        name = _ast_function.get_name()
        function = self._get_current_symbol().get_function(name, _ast_function.get_begin_line())
        self.push_symbol(function or self._get_current_symbol())

    def end_Function(self, _ast_function):
        self.pop_symbol()

    def start_Method(self, _ast_method):
        """
        @type _ast_method: typescript_parser.parser.Method
        """
        name = _ast_method.get_name()
        method = self._get_current_symbol().get_method(name, _ast_method.get_begin_line())
        self.push_symbol(method or self._get_current_symbol())

    def end_Method(self, _ast_method):
        self.pop_symbol()


class ApolloBasicInterpreterTS(BaseFrameworkInterpreter):
    """
    TypeScript interpreter for Apollo Client hooks and GraphQL operations.
    Walks the AST and extracts Apollo-specific patterns.
    """

    def __init__(self, module, apollo_analysis_results):
        """
        Args:
            module: TypeScript SourceFile
            apollo_analysis_results: ApolloAnalysisResults instance
        """
        BaseFrameworkInterpreter.__init__(self, module)
        self.module = module
        self.apollo_analysis_results = apollo_analysis_results
        
        # Use evaluation tool if available
        if apollo_analysis_results.ts_evaluation_tool:
            self.ts_evaluate = apollo_analysis_results.ts_evaluation_tool.evaluate
        else:
            self.ts_evaluate = None

        # Set of local names bound to the gql tag in this file (alias-aware).
        # Always contains 'gql'; extended by _build_gql_tag_names with any import aliases.
        self.gql_tag_names = _build_gql_tag_names(module)

    def on_end(self):
        """
        Called after walking the AST. Perform final processing.
        """
        self.extract_all_gql_definitions()
        self.extract_all_apollo_hooks()
        self.create_hook_to_gql_links()

    def find_parent_symbol_for_ast_node(self, ast_node):
        """
        Find the parent symbol (Function, Method, Class) that contains this AST node.
        Returns the parent symbol or the module if no parent found.
        """
        if not ast_node:
            return self.module

        line_number = ast_node.get_begin_line() if hasattr(ast_node, 'get_begin_line') else -1

        # Get all symbols from the module
        all_symbols = self.module.get_all_symbols()

        # Find the most specific (smallest range) symbol that contains this line
        best_match = self.module
        best_range = float('inf')

        for symbol in all_symbols:
            # Check if this symbol is a Function, Method, or Class
            symbol_type = type(symbol).__name__
            if symbol_type not in ['Function', 'Method', 'Class']:
                continue

            # Get the symbol's AST node
            symbol_ast = symbol.get_ast() if hasattr(symbol, 'get_ast') else None
            if not symbol_ast:
                continue

            # Handle both single AST and list of ASTs
            if isinstance(symbol_ast, list):
                symbol_ast = symbol_ast[0] if symbol_ast else None

            if not symbol_ast:
                continue

            # Get the symbol's line range
            if hasattr(symbol_ast, 'get_begin_line') and hasattr(symbol_ast, 'get_end_line'):
                start_line = symbol_ast.get_begin_line()
                end_line = symbol_ast.get_end_line()

                # Check if our node is inside this symbol
                if start_line <= line_number <= end_line:
                    range_size = end_line - start_line
                    # Keep the smallest range (most specific parent)
                    if range_size < best_range:
                        best_range = range_size
                        best_match = symbol

        return best_match

    def _has_gql_tag_token(self, text):
        """
        Return True if *text* (a node repr string) contains a Token.Generic token
        whose value is one of the known gql tag names in this file.
        Handles both single-quoted and double-quoted token repr formats.
        """
        for name in self.gql_tag_names:
            if "Token.Generic,'{}'".format(name) in text:
                return True
            if 'Token.Generic,"{}"'.format(name) in text:
                return True
        return False

    def extract_all_gql_definitions(self):
        """
        Extract all GraphQL definitions (const GET_USERS = gql`...`)
        """
        try:
            ast = self.module.get_ast()
            if not ast:
                return

            # Find all variable declarations
            var_declarations = get_descendants(ast, 'VariableDeclaration')

            # Bug 10: track every StringTemplate already claimed by a successful
            # registration (main loop + Bug 3 fallback).  Used by the fragment-level
            # recovery fallback below to avoid double-processing.
            processed_template_ids = set()

            for var_decl in var_declarations:
                # First try: setup only — if var_name/expr_statements fail, skip this var_decl
                try:
                    var_name = var_decl.get_name()

                    # Skip inline gql in hooks (var_name = None)
                    # These will be handled by extract_all_apollo_hooks
                    if var_name is None:
                        continue

                    # Look for gql`...` tagged template (ExpressionStatement with gql identifier)
                    expr_statements = get_descendants(var_decl, 'ExpressionStatement')
                except Exception as setup_ex:
                    log.warning('[GraphQL][TS] GQL def setup error: {}'.format(str(setup_ex)))
                    continue

                # Second try: scanning loop — exceptions here do NOT skip the Bug 3 fallback
                definition_found = False
                processed_names = set()  # prevent duplicate definitions within the same VarDecl
                try:
                    for expr_stmt in expr_statements:
                        # Check if this ExpressionStatement contains 'gql' identifier and StringTemplate
                        has_gql = False
                        string_template = None

                        for sub_node in expr_stmt.get_sub_nodes():
                            if hasattr(sub_node, 'get_name') and sub_node.get_name() in self.gql_tag_names:
                                has_gql = True
                            elif is_ts_node_type(sub_node, 'StringTemplate'):
                                string_template = sub_node

                        # Fallback for the `as` cast pattern: `const X = gql\`...\` as TypedDocumentNode<...>`
                        # In this case the gql identifier is a bare Token (not a Node) inside the
                        # ExpressionStatement, so get_sub_nodes() misses it.  Detect via repr.
                        if string_template is not None and not has_gql:
                            expr_str = str(expr_stmt)
                            if self._has_gql_tag_token(expr_str):
                                has_gql = True

                        # Deep fallback: for assignment-type ExpressionStatements like
                        #   `POST_PUBLISHED = gql\`...\` as Type`
                        # the StringTemplate and gql are nested one level further inside an inner
                        # ExpressionStatement.  get_sub_nodes() finds only the outer Term/identifier
                        # so we need a recursive search within this ExpressionStatement.
                        if string_template is None:
                            nested = get_descendants(expr_stmt, 'StringTemplate')
                            if nested:
                                string_template = nested[0]
                        if string_template is not None and not has_gql:
                            expr_str = str(expr_stmt)
                            if self._has_gql_tag_token(expr_str):
                                has_gql = True

                        if has_gql and string_template:
                            # Determine the effective variable name for this ExpressionStatement.
                            # Normally (one VarDecl per const) the VarDecl name is correct.
                            # When multiple `const X = gql\`...\` as Type` declarations WITHOUT
                            # semicolons are parsed into one merged VarDecl, the parser names the
                            # VarDecl after the *first* const only.  Each subsequent declaration
                            # becomes an ExpressionStatement whose get_name() returns its own
                            # variable name.  We use that when it differs from the VarDecl name.
                            effective_var_name = var_name
                            try:
                                expr_name = expr_stmt.get_name() if hasattr(expr_stmt, 'get_name') else None
                                if (expr_name is not None
                                        and expr_name != 'gql'
                                        and expr_name != var_name
                                        and str(expr_name).replace('_', '').isalnum()):
                                    effective_var_name = expr_name
                            except Exception:
                                pass

                            # Deduplicate: skip if we already registered this name in this VarDecl
                            if effective_var_name in processed_names:
                                continue

                            _c = _ctx()
                            _line = var_decl.get_begin_line() if hasattr(var_decl, 'get_begin_line') else '?'
                            _glog('DETECT', 'GqlDef', _c, 'gql`` found: var={} line={}'.format(effective_var_name, _line))

                            graphql_metadata = self.parse_graphql_content(string_template)

                            if graphql_metadata.get('operationName'):
                                _glog('DECISION', 'GqlDef', _c, 'op={} name={}'.format(
                                    graphql_metadata.get('operationType', '?'),
                                    graphql_metadata['operationName']))
                                ast_node = expr_stmt if effective_var_name != var_name else var_decl
                                # Create GqlDefinition object
                                raw_bookmark = RawBookmark(ast_node, self.module)

                                gql_def = GqlDefinition(
                                    name=effective_var_name,
                                    operation_name=graphql_metadata['operationName'],
                                    operation_type=graphql_metadata.get('operationType', 'query'),
                                    raw_query_text=graphql_metadata.get('rawQueryText', ''),
                                    variables=graphql_metadata.get('variables', ''),
                                    fields_selected=graphql_metadata.get('fieldsSelected', ''),
                                    ast_node=ast_node,
                                    raw_bookmark=raw_bookmark
                                )
                                gql_def.exported = _is_var_exported(var_decl)

                                # Add to analysis results
                                self.apollo_analysis_results.add_gql_definition(gql_def)

                                # ✨ CREATE AND ADD SYMBOL TO SOURCEFILE
                                # Find the correct parent symbol (Function, Method, Class, or Module)
                                parent_symbol = self.find_parent_symbol_for_ast_node(var_decl)
                                gql_def.parent_symbol = parent_symbol

                                gql_symbol = GqlDefinitionSymbol(
                                    name=effective_var_name,
                                    parent=parent_symbol,
                                    operation_type=graphql_metadata.get('operationType', 'query')
                                )
                                gql_symbol.operation_name = graphql_metadata['operationName']
                                gql_symbol.variables = graphql_metadata.get('variables', '')
                                gql_symbol.fields_selected = graphql_metadata.get('fieldsSelected', '')
                                gql_symbol.raw_query_text = graphql_metadata.get('rawQueryText', '')
                                gql_symbol._ast = ast_node

                                # Add symbol to BOTH:
                                # 1. Parent symbol's table (for correct parent-child relationship)
                                parent_symbol.add_symbol(effective_var_name, gql_symbol)
                                # 2. Module's table (for global visibility with get_all_symbols)
                                if parent_symbol != self.module:
                                    self.module.add_symbol(effective_var_name, gql_symbol)

                                _glog('RESULT', 'GqlDef', _c, 'registered {} → {}'.format(
                                    effective_var_name, graphql_metadata['operationName']))
                                processed_names.add(effective_var_name)
                                processed_template_ids.add(id(string_template))
                                definition_found = True
                                # No break — keep iterating to handle merged VarDecl case where
                                # multiple `const X = gql\`...\` as Type` declarations without
                                # semicolons are all nested under one VarDecl node.
                except Exception as inner_ex:
                    log.warning('[GraphQL][TS] GQL def scan error for {!r}: {}'.format(var_name, str(inner_ex)))
                    # Do NOT continue — let the Bug 3 fallback run below

                # Bug 3 fallback: `as` cast moves StringTemplate outside ExpressionStatement.
                # The normal loop above found no (gql + StringTemplate) pair in any
                # ExpressionStatement. Search for StringTemplate anywhere inside the
                # VariableDeclaration and verify at least one ExpressionStatement holds
                # the `gql` identifier (ensuring this is a gql`...` call, not a plain template).
                if not definition_found:
                    string_templates_in_decl = get_descendants(var_decl, 'StringTemplate')
                    if string_templates_in_decl:
                        has_gql_in_decl = False
                        for _expr in expr_statements:
                            for sub_node in _expr.get_sub_nodes():
                                if hasattr(sub_node, 'get_name') and sub_node.get_name() in self.gql_tag_names:
                                    has_gql_in_decl = True
                                    break
                            if not has_gql_in_decl:
                                _expr_str = str(_expr)
                                if self._has_gql_tag_token(_expr_str):
                                    has_gql_in_decl = True
                            if has_gql_in_decl:
                                break
                        # Broader check: scan the entire var_decl string repr if expr-level checks missed it
                        if not has_gql_in_decl:
                            var_decl_str = str(var_decl)
                            if self._has_gql_tag_token(var_decl_str):
                                has_gql_in_decl = True
                        if has_gql_in_decl:
                            _c = _ctx()
                            _line = var_decl.get_begin_line() if hasattr(var_decl, 'get_begin_line') else '?'
                            _glog('DETECT', 'GqlDef', _c, 'as-cast gql found: var={} line={}'.format(var_name, _line))
                            self._register_gql_from_template(
                                var_name, var_decl, string_templates_in_decl[0], _c,
                                exported=_is_var_exported(var_decl)
                            )
                            processed_template_ids.add(id(string_templates_in_decl[0]))

            # ─── Bug 10 fallback: broken AST recovery ──────────────────────────
            # When TypeScript object type literals with `;` member separators appear
            # inside generic parameters (e.g. `TypedDocumentNode<{a: string; b: number}>`),
            # the bundled parser's `is_generics()` heuristic bails out on the `;` and
            # treats `<` / `>` as binary operators.  This breaks the VariableDeclaration
            # subtree so badly that the `gql\`...\`` template ends up outside the
            # VarDecl entirely — neither the main loop nor the Bug 3 fallback can find it.
            #
            # Recovery strategy: at fragment level, scan all StringTemplates that no
            # earlier path has claimed.  For each gql-tagged orphan template, find the
            # nearest preceding "lonely" VariableDeclaration (one that has a name but
            # no associated GQL definition yet) by source line proximity, and register
            # the GQL definition with that variable name.
            self._recover_orphaned_gql_templates(ast, var_declarations, processed_template_ids)

        except Exception as e:
            log.warning('[GraphQL][TS] extract_all_gql_definitions error: {}'.format(str(e)))

    def parse_graphql_content(self, string_template):
        """
        Parse GraphQL content from a StringTemplate node.
        Returns a dictionary with operation metadata.
        """
        result = {
            'operationName': None,
            'operationType': 'query',  # default
            'variables': '',
            'fieldsSelected': '',
            'rawQueryText': ''
        }

        try:
            from typescript_dependencies.typescript_parser.light_parser import Token

            raw_text = ''

            # Method 1: Direct access to the backtick Token in StringTemplate.children.
            # StringTemplate is a Term node whose children[0] is the String.Backtick Token.
            # Token.text contains the FULL template literal text (including surrounding backticks
            # and any ${...} interpolations verbatim). This is the most reliable extraction path.
            # NOTE: get_sub_nodes() is NOT used here because it filters out Token objects,
            # returning only Node subclass instances — so it never finds the backtick Token.
            if hasattr(string_template, 'children') and string_template.children:
                for child in string_template.children:
                    if isinstance(child, Token) and hasattr(child, 'text') and child.text:
                        raw_text = child.text
                        break

            # Method 2: Fallback via string representation of the node.
            # Used when Method 1 fails (e.g. no children, or non-standard node layout).
            # The repr format is: StringTemplate[Token(Token.Literal.String.Backtick,'`...`',...)]
            # The regex extracts the content from the first single-quoted string in the repr.
            if not raw_text:
                raw_text = str(string_template)
                if 'Token.Literal.String.Backtick' in raw_text:
                    match = re.search(r"'([^']*)'", raw_text)
                    if match:
                        raw_text = match.group(1)

            if not raw_text:
                return result

            # Strip surrounding backtick delimiters and leading/trailing whitespace/newlines.
            # Method 1: token.text has REAL newlines → strip() removes them correctly.
            # Method 2: repr has escaped \n (two chars) → convert before stripping.
            if '\\n' in raw_text:  # literal backslash-n from repr escaping (Method 2 only)
                raw_text = raw_text.replace('\\n', '\n')
            raw_text = raw_text.strip('`').strip()

            result['rawQueryText'] = raw_text

            # Extract operation type and name.
            # Bug 4: do NOT require `{` — template literals with ${...} interpolations in the
            # variable-type list truncate raw_text before the opening brace of the query body.
            # `query/mutation/subscription PascalCaseName` is specific enough to be safe.
            operation_pattern = r'^\s*(query|mutation|subscription)\s+([A-Z][A-Za-z0-9_]*)'
            match = re.search(operation_pattern, raw_text, re.MULTILINE | re.DOTALL)

            if match:
                result['operationType'] = match.group(1)
                result['operationName'] = match.group(2)

                # Extract all $variable references from the raw text (no group(3) — regex has 2 groups).
                variables = re.findall(r'\$[a-zA-Z_][a-zA-Z0-9_]*', raw_text)
                if variables:
                    result['variables'] = ', '.join(variables)

            # Extract selected fields
            fields_pattern = r'\{\s*([a-z][a-zA-Z0-9_]*)\s*[\(\{]'
            fields = re.findall(fields_pattern, raw_text)

            keywords = ['query', 'mutation', 'subscription', 'fragment']
            unique_fields = []
            seen = set()

            for field in fields:
                if field not in keywords and field not in seen:
                    unique_fields.append(field)
                    seen.add(field)

            if unique_fields:
                result['fieldsSelected'] = ', '.join(unique_fields)

        except Exception as e:
            log.warning('[GraphQL][TS] parse_graphql_content error: {}'.format(str(e)))

        return result

    def _register_gql_from_template(self, var_name, var_decl, string_template, ctx=None, exported=False):
        """
        Parse a StringTemplate and register the resulting GQL definition.
        Shared by the normal path and the Bug 3 as-cast fallback path.
        """
        graphql_metadata = self.parse_graphql_content(string_template)

        if not graphql_metadata.get('operationName'):
            return

        raw_bookmark = RawBookmark(string_template, self.module)
        gql_def = GqlDefinition(
            name=var_name,
            operation_name=graphql_metadata['operationName'],
            operation_type=graphql_metadata.get('operationType', 'query'),
            raw_query_text=graphql_metadata.get('rawQueryText', ''),
            variables=graphql_metadata.get('variables', ''),
            fields_selected=graphql_metadata.get('fieldsSelected', ''),
            ast_node=var_decl,
            raw_bookmark=raw_bookmark
        )
        gql_def.exported = exported
        self.apollo_analysis_results.add_gql_definition(gql_def)

        parent_symbol = self.find_parent_symbol_for_ast_node(var_decl)
        gql_def.parent_symbol = parent_symbol
        gql_symbol = GqlDefinitionSymbol(
            name=var_name,
            parent=parent_symbol,
            operation_type=graphql_metadata.get('operationType', 'query')
        )
        gql_symbol.operation_name = graphql_metadata['operationName']
        gql_symbol.variables = graphql_metadata.get('variables', '')
        gql_symbol.fields_selected = graphql_metadata.get('fieldsSelected', '')
        gql_symbol.raw_query_text = graphql_metadata.get('rawQueryText', '')
        gql_symbol._ast = var_decl

        parent_symbol.add_symbol(var_name, gql_symbol)
        if parent_symbol != self.module:
            self.module.add_symbol(var_name, gql_symbol)

        _c = ctx or _ctx()
        _glog('DECISION', 'GqlDef', _c, 'op={} name={}'.format(
            graphql_metadata.get('operationType', '?'), graphql_metadata['operationName']))
        _glog('RESULT', 'GqlDef', _c, 'registered {} → {}'.format(var_name, graphql_metadata['operationName']))

    # ──────────────────────────────────────────────────────────────────────────
    # Bug 10 — Fragment-level recovery for broken AST
    # ──────────────────────────────────────────────────────────────────────────
    # Root cause: the bundled TS parser's `is_generics()` heuristic abandons
    # whenever it sees a `;` while scanning for the closing `>` of a generic
    # parameter list.  TypeScript object type literals legitimately use `;` as
    # a member separator (`{ id: string; foo?: number }`), so any generic that
    # contains such a literal causes `<` and `>` to be parsed as binary operators
    # — and the entire `const X: T<...> = gql\`...\`` subtree fragments apart.
    #
    # The two recovery helpers below fish out the orphan StringTemplate and
    # re-associate it with the original variable name by source-line proximity.

    def _is_gql_tagged_template(self, string_template):
        """
        Return True if *string_template* is preceded by a gql tag identifier in
        any of its ancestor nodes' children lists (up to 4 levels).  Used by the
        fragment-level recovery fallback when the parser breaks the VarDecl tree.

        Walks back through up to 6 preceding siblings at each level, skipping
        whitespace, and accepts either an Identifier node whose get_name() is a
        known gql alias, or a bare Token whose text/repr contains the gql tag.
        Returns False on the first non-whitespace, non-gql token at any level.
        """
        node = string_template
        for _ in range(4):
            parent = getattr(node, 'parent', None)
            if parent is None:
                break
            children = getattr(parent, 'children', None)
            if children:
                try:
                    idx = children.index(node)
                except ValueError:
                    idx = -1
                if idx > 0:
                    for k in range(idx - 1, max(idx - 7, -1), -1):
                        prev = children[k]
                        prev_text = getattr(prev, 'text', '')
                        # Skip pure-whitespace tokens
                        if not prev_text or not prev_text.strip():
                            continue
                        # Identifier-node check
                        if hasattr(prev, 'get_name'):
                            try:
                                pname = prev.get_name()
                                if pname in self.gql_tag_names:
                                    return True
                            except Exception:
                                pass
                        # Bare token text check
                        if prev_text in self.gql_tag_names:
                            return True
                        # Repr-based token check (covers Token.Generic representations)
                        try:
                            if self._has_gql_tag_token(str(prev)):
                                return True
                        except Exception:
                            pass
                        # First non-whitespace token at this level is not gql → stop here
                        break
            node = parent
        return False

    def _recover_orphaned_gql_templates(self, ast, var_declarations, processed_template_ids):
        """
        Final-stage fallback: scan every StringTemplate in the fragment, filter
        to gql-tagged orphans (not already processed by the main loop or Bug 3
        fallback), and pair each one with the nearest preceding VariableDeclaration
        that still has no associated GQL definition.

        Why line proximity is safe here:
        - Broken VarDecls still report the correct start line (where `const` sits).
        - The orphan StringTemplate is always on a later line within the same
          original declaration (a few lines after the `=`).
        - We never reassign a template that was already claimed, and we mark a
          var_name as "taken" as soon as we register it, so two consecutive
          broken declarations cannot swap their templates.
        """
        try:
            all_templates = get_descendants(ast, 'StringTemplate')
            if not all_templates:
                return

            file_path = self.module.get_path()
            already_named = set(
                gd.name for gd in
                self.apollo_analysis_results.gql_definitions_by_file.get(file_path, [])
            )

            for var_decl in var_declarations:
                try:
                    var_name = var_decl.get_name()
                except Exception:
                    continue
                if var_name is None or var_name in already_named:
                    continue

                vd_line = (var_decl.get_begin_line()
                           if hasattr(var_decl, 'get_begin_line') else None)
                if vd_line is None:
                    continue

                best_template = None
                best_distance = None
                for st in all_templates:
                    if id(st) in processed_template_ids:
                        continue
                    st_line = (st.get_begin_line()
                               if hasattr(st, 'get_begin_line') else None)
                    if st_line is None or st_line < vd_line:
                        continue
                    if not self._is_gql_tagged_template(st):
                        continue
                    distance = st_line - vd_line
                    if best_distance is None or distance < best_distance:
                        best_distance = distance
                        best_template = st

                # Sanity bound: only accept matches within ~30 lines of the const
                # declaration — beyond that we are almost certainly guessing wrong.
                if best_template is None or best_distance > 30:
                    continue

                _c = _ctx()
                _glog('DETECT', 'GqlDef', _c,
                      'orphan recovery (broken AST): var={} const_line={} template_line={}'.format(
                          var_name, vd_line, best_template.get_begin_line()))
                self._register_gql_from_template(
                    var_name, var_decl, best_template, _c,
                    exported=_is_var_exported(var_decl)
                )
                processed_template_ids.add(id(best_template))
                already_named.add(var_name)
        except Exception as e:
            log.warning('[GraphQL][TS] _recover_orphaned_gql_templates error: {}'.format(str(e)))

    def extract_all_apollo_hooks(self):
        """
        Extract all Apollo Client hooks (useQuery, useMutation, useSubscription, useLazyQuery)
        """
        try:
            ast = self.module.get_ast()
            if not ast:
                return

            # Find all function calls
            func_calls = get_descendants(ast, 'FunctionCall')

            for func_call in func_calls:
                try:
                    hook_name = func_call.get_name()

                    # ═══════════════════════════════════════════════════════════
                    # PATTERN 2 — Codegen-generated typed hooks
                    # e.g. useGetLambdaInvocationsQuery({variables: ...})
                    #      useInvokeLambdaMutation({onCompleted: ...})
                    #
                    # These are wrapper functions produced by @graphql-codegen.
                    # They match use[Name](Query|Mutation|Subscription) but are
                    # NOT in APOLLO_HOOKS (which only has the 4 standard hooks).
                    # The operation_name IS the hook function name itself (no arg
                    # to extract — the document is baked into the wrapper).
                    # ═══════════════════════════════════════════════════════════
                    if hook_name and hook_name not in APOLLO_HOOKS:
                        codegen_match = CODEGEN_HOOK_PATTERN.match(hook_name)
                        if codegen_match:
                            self._process_codegen_hook(func_call, hook_name, codegen_match)
                        continue

                    # Check if it's an Apollo hook (standard: useQuery etc.)
                    if hook_name not in APOLLO_HOOKS:
                        continue

                    _c = _ctx()
                    _line = func_call.get_begin_line() if hasattr(func_call, 'get_begin_line') else '?'
                    _glog('DETECT', 'Hook', _c, '{} line={}'.format(hook_name, _line))

                    # Extract operation name
                    operation_name = self.extract_operation_name(func_call)

                    # Check for inline gql
                    is_inline = False
                    if not operation_name:
                        inline_name, inline_metadata = self.extract_inline_gql(func_call)
                        if inline_name:
                            operation_name = inline_name
                            is_inline = True
                            
                            # Store inline GQL definition
                            raw_bookmark = RawBookmark(func_call, self.module)
                            gql_def = GqlDefinition(
                                name=inline_name,
                                operation_name=inline_metadata['operationName'],
                                operation_type=inline_metadata.get('operationType', 'query'),
                                raw_query_text=inline_metadata.get('rawQueryText', ''),
                                variables=inline_metadata.get('variables', ''),
                                fields_selected=inline_metadata.get('fieldsSelected', ''),
                                ast_node=func_call,
                                raw_bookmark=raw_bookmark
                            )
                            self.apollo_analysis_results.add_gql_definition(gql_def)

                            # ✨ CREATE AND ADD SYMBOL FOR INLINE GQL
                            # Find the correct parent symbol
                            parent_symbol = self.find_parent_symbol_for_ast_node(func_call)
                            gql_def.parent_symbol = parent_symbol

                            inline_gql_symbol = GqlDefinitionSymbol(
                                name=inline_name + '_inline',
                                parent=parent_symbol,
                                operation_type=inline_metadata.get('operationType', 'query')
                            )
                            inline_gql_symbol.operation_name = inline_metadata['operationName']
                            inline_gql_symbol.variables = inline_metadata.get('variables', '')
                            inline_gql_symbol.fields_selected = inline_metadata.get('fieldsSelected', '')
                            inline_gql_symbol.raw_query_text = inline_metadata.get('rawQueryText', '')
                            inline_gql_symbol._ast = func_call

                            # Add symbol to BOTH parent and module
                            parent_symbol.add_symbol(inline_name + '_inline', inline_gql_symbol)
                            if parent_symbol != self.module:
                                self.module.add_symbol(inline_name + '_inline', inline_gql_symbol)

                    if not operation_name:
                        continue
                    
                    # Find the correct parent symbol BEFORE creating the hook object so it can
                    # be stored on hook_obj for use by _create_hook_object() in the analyzer.
                    parent_symbol = self.find_parent_symbol_for_ast_node(func_call)

                    # Create ApolloHookObject
                    raw_bookmark = RawBookmark(func_call, self.module)

                    hook_obj = ApolloHookObject(
                        hook_name=hook_name,
                        operation_name=operation_name,
                        ast_node=func_call,
                        raw_bookmark=raw_bookmark,
                        module=self.module,
                        parent_symbol=parent_symbol
                    )

                    # Mark as inline if applicable
                    if is_inline:
                        hook_obj.inline = operation_name

                    # Add to analysis results
                    self.apollo_analysis_results.add_apollo_hook(hook_obj)

                    # Register in module's node_symbols
                    self.module.add_node_symbol(operation_name, hook_obj)

                    # ✨ CREATE AND ADD SYMBOL

                    hook_symbol = ApolloHookSymbol(
                        name=operation_name,
                        parent=parent_symbol,  # ← Le parent est correct (LambdaManager)
                        hook_name=hook_name,
                        operation_name=operation_name
                    )
                    hook_symbol._ast = func_call

                    # Add symbol to BOTH:
                    # 1. Parent symbol's table (for correct parent-child relationship)
                    parent_symbol.add_symbol(operation_name, hook_symbol)
                    # 2. Module's table (for global visibility with get_all_symbols)
                    if parent_symbol != self.module:
                        self.module.add_symbol(operation_name, hook_symbol)

                    _glog('DECISION', 'Hook', _c, '{} op={} inline={}'.format(hook_name, operation_name, is_inline))
                    _glog('RESULT', 'Hook', _c, 'registered {}:{}'.format(hook_name, operation_name))

                except Exception as inner_ex:
                    log.warning('[GraphQL][TS] Hook scan error: {}'.format(str(inner_ex)))
                    continue
                    
            # ═══════════════════════════════════════════════════════════════════
            # PATTERN 1 — Direct Apollo Client calls: client.query({query: X})
            # PATTERN 3 — Angular service calls:      this.apollo.query({query: X})
            #                                         this.apollo.watchQuery({query: X})
            #
            # In the CAST TypeScript parser, method calls on objects (obj.method())
            # are represented as 'MethodCall' nodes, NOT 'FunctionCall' nodes.
            # That is why the FunctionCall scan above cannot detect them and why
            # test 06 currently asserts 0 hooks for client.query/mutate/subscribe.
            #
            # We scan MethodCall nodes here using a separate call to get_descendants.
            # ═══════════════════════════════════════════════════════════════════
            method_calls = get_descendants(ast, 'MethodCall')
            for method_call in method_calls:
                try:
                    method_name = method_call.get_name() if hasattr(method_call, 'get_name') else None
                    if not method_name or method_name not in ALL_RECEIVER_METHODS:
                        continue
                    self._process_receiver_method_call(method_call, method_name)
                except Exception as mc_ex:
                    log.warning('[GraphQL][TS] MethodCall scan error: {}'.format(str(mc_ex)))
                    continue

        except Exception as e:
            log.warning('[GraphQL][TS] extract_all_apollo_hooks error: {}'.format(str(e)))

    def extract_operation_name(self, func_call):
        """
        Extract the GraphQL operation name from a hook call.
        For outline definitions: useQuery(GET_USERS, {...})
        """
        try:
            # Get the arguments
            parentheses = get_descendants(func_call, 'Parenthesis')
            if not parentheses:
                return None

            args_parenthesis = parentheses[0]

            # Get first child
            first_child = None
            for child in args_parenthesis.get_sub_nodes():
                first_child = child
                break

            if not first_child:
                return None

            # If the first argument is itself a function call (e.g., useMemo(...)),
            # it is not a variable identifier. Skip it here — extract_inline_gql handles
            # the gql`...` case via ExpressionStatement detection.
            if is_ts_node_type(first_child, 'FunctionCall'):
                return None

            # Check if it's an identifier (outline case)
            if hasattr(first_child, 'get_name'):
                operation_name = first_child.get_name()
                if operation_name and operation_name not in self.gql_tag_names:
                    return operation_name

            return None

        except Exception:
            return None

    def extract_inline_gql(self, func_call):
        """
        Extract inline gql definition from a hook call.
        For inline definitions: useQuery(gql`...`, {...})
        
        Returns: (operation_name, metadata_dict) or (None, None)
        """
        try:
            # Get the arguments
            parentheses = get_descendants(func_call, 'Parenthesis')
            if not parentheses:
                return (None, None)

            args_parenthesis = parentheses[0]

            # Get first child - if it's an ExpressionStatement, check for gql
            first_child = None
            for child in args_parenthesis.get_sub_nodes():
                first_child = child
                break

            if not first_child:
                return (None, None)

            # Check if first child is an ExpressionStatement (inline gql case)
            if is_ts_node_type(first_child, 'ExpressionStatement'):
                has_gql = False
                string_template = None

                # Look for 'gql' token and StringTemplate in the ExpressionStatement
                # Use get_children() instead of get_sub_nodes() to get both tokens and nodes
                for child in first_child.get_children():
                    # Check for gql identifier node (alias-aware)
                    if is_ts_node_type(child, 'Identifier'):
                        node_name = child.get_name() if hasattr(child, 'get_name') else None
                        if node_name in self.gql_tag_names:
                            has_gql = True

                    # Check for gql token (direct Token object, alias-aware)
                    elif hasattr(child, '__class__') and 'Token' in child.__class__.__name__:
                        token_str = str(child)
                        if self._has_gql_tag_token(token_str):
                            has_gql = True

                    # Check for StringTemplate node
                    if is_ts_node_type(child, 'StringTemplate'):
                        string_template = child

                if has_gql and string_template:
                    metadata = self.parse_graphql_content(string_template)
                    operation_name = metadata.get('operationName')
                    if operation_name:
                        return (operation_name, metadata)

            return (None, None)

        except Exception:
            return (None, None)

    # ──────────────────────────────────────────────────────────────────────────
    # PATTERN 2 helper — Codegen-generated typed hooks
    # ──────────────────────────────────────────────────────────────────────────

    def _process_codegen_hook(self, func_call, hook_name, codegen_match):
        """
        PATTERN 2: Create an ApolloHookObject for a codegen-generated hook call.

        The hook function name itself (e.g. 'useGetLambdaInvocationsQuery') is used
        as the operation_name since there is no GQL document argument to extract.
        The suffix ('Query'/'Mutation'/'Subscription') determines the normalized
        hook type stored on the object (useQuery / useMutation / useSubscription).

        Examples detected:
            useGetLambdaInvocationsQuery({ variables: ... })
            useInvokeLambdaMutation({ onCompleted: ... })
            useOnLambdaInvocationResultSubscription({ variables: ... })
        """
        suffix = codegen_match.group(1)   # 'Query', 'Mutation', or 'Subscription'
        normalized_hook = 'use' + suffix   # 'useQuery', 'useMutation', 'useSubscription'
        operation_name = hook_name         # e.g. 'useGetLambdaInvocationsQuery'

        parent_symbol = self.find_parent_symbol_for_ast_node(func_call)
        raw_bookmark = RawBookmark(func_call, self.module)
        hook_obj = ApolloHookObject(
            hook_name=normalized_hook,
            operation_name=operation_name,
            ast_node=func_call,
            raw_bookmark=raw_bookmark,
            module=self.module,
            source_pattern='codegen_hook',
            parent_symbol=parent_symbol
        )
        self.apollo_analysis_results.add_apollo_hook(hook_obj)
        self.module.add_node_symbol(operation_name, hook_obj)
        hook_symbol = ApolloHookSymbol(
            name=operation_name,
            parent=parent_symbol,
            hook_name=normalized_hook,
            operation_name=operation_name
        )
        hook_symbol._ast = func_call
        parent_symbol.add_symbol(operation_name, hook_symbol)
        if parent_symbol != self.module:
            self.module.add_symbol(operation_name, hook_symbol)

        _c = _ctx()
        _line = func_call.get_begin_line() if hasattr(func_call, 'get_begin_line') else '?'
        _glog('DETECT', 'Hook', _c, 'codegen {} line={}'.format(hook_name, _line))
        _glog('RESULT', 'Hook', _c, 'registered codegen {}:{}'.format(normalized_hook, hook_name))

    # ──────────────────────────────────────────────────────────────────────────
    # PATTERN 1 & 3 helpers — client.X() and this.apollo.X() method calls
    # ──────────────────────────────────────────────────────────────────────────

    def _extract_gql_var_from_node_str(self, node_str, method_name):
        """
        Extract the GQL document variable name from the string representation of
        a MethodCall node such as:
            client.query({ query: GET_USERS, variables: {...} })
            this.apollo.mutate({ mutation: CREATE_USER, ... })
            this.apollo.watchQuery({ query: GET_USERS }).valueChanges

        Strategy:
          1. Determine the object-literal arg key expected for this method:
               query / watchQuery / subscribe  →  look for 'query':  VAR
               mutate                          →  look for 'mutation': VAR
          2. In the token repr, identifiers appear as Token.Generic,'name'.
             Scan for the arg key token followed (non-greedily) by an
             UPPER_SNAKE_CASE identifier (which is the GQL document const name).
          3. Reject trivially short or generic tokens (GET, SET, NULL…).

        Returns the variable name string, or None if not found.
        """
        arg_key = 'mutation' if method_name == 'mutate' else 'query'
        # Match: 'arg_key'  ...any chars (non-greedy)...  'UPPER_CASE_VAR'
        pattern = r"'" + arg_key + r"'.*?'([A-Z][A-Z0-9_]{2,})'"
        m = re.search(pattern, node_str, re.DOTALL)
        if m:
            candidate = m.group(1)
            excluded = {'GET', 'SET', 'ALL', 'ANY', 'MAP', 'NULL', 'TRUE',
                        'FALSE', 'STRING', 'INT', 'FLOAT', 'BOOLEAN', 'ID'}
            if candidate not in excluded:
                return candidate
        return None

    def _process_receiver_method_call(self, method_call, method_name):
        """
        PATTERN 1 — React: client.query({query: GET_X})   → GraphQLApolloHookQuery
                            client.mutate({mutation: DO_X}) → GraphQLApolloHookMutation
                            client.subscribe({query: ON_X}) → GraphQLApolloHookSubscription

        PATTERN 3 — Angular: this.apollo.query({query: GET_X})      → GraphQLApolloHookQuery
                              this.apollo.mutate({mutation: DO_X})   → GraphQLApolloHookMutation
                              this.apollo.watchQuery({query: GET_X}) → GraphQLApolloHookLazyQuery

        Discrimination between the two patterns:
          - Angular: the MethodCall string repr contains the token 'apollo'
                     (from the 'this.apollo' receiver expression).
          - React:   no 'apollo' token in the repr; receiver is typically 'client'.

        The operation_name extracted is the GQL document const variable name
        (e.g. 'GET_USERS'), which var_name_to_op_name will later resolve to the
        GQL operation name (e.g. 'GetUsers') for the useLink creation.
        """
        node_str = str(method_call)

        # ── Discriminate Angular vs React client ──────────────────────────────
        is_angular = ("'apollo'" in node_str or '"apollo"' in node_str)

        if is_angular:
            normalized_hook = ANGULAR_METHOD_TO_HOOK.get(method_name)
            pattern_label = 'Pattern 3 (Angular this.apollo.{})'.format(method_name)
        else:
            normalized_hook = CLIENT_METHOD_TO_HOOK.get(method_name)
            pattern_label = 'Pattern 1 (client.{})'.format(method_name)

        if not normalized_hook:
            return

        # ── Extract the GQL document variable from the object arg ─────────────
        operation_name = self._extract_gql_var_from_node_str(node_str, method_name)
        if not operation_name:
            return

        _c = _ctx()
        _line = method_call.get_begin_line() if hasattr(method_call, 'get_begin_line') else '?'
        _glog('DETECT', 'Hook', _c, '{} line={}'.format(pattern_label, _line))

        # ── Create ApolloHookObject (same class as standard hooks) ────────────
        parent_symbol = self.find_parent_symbol_for_ast_node(method_call)
        raw_bookmark = RawBookmark(method_call, self.module)
        hook_obj = ApolloHookObject(
            hook_name=normalized_hook,
            operation_name=operation_name,
            ast_node=method_call,
            raw_bookmark=raw_bookmark,
            module=self.module,
            source_pattern='angular_method' if is_angular else 'client_method',
            parent_symbol=parent_symbol
        )
        self.apollo_analysis_results.add_apollo_hook(hook_obj)
        self.module.add_node_symbol(operation_name, hook_obj)
        hook_symbol = ApolloHookSymbol(
            name=operation_name,
            parent=parent_symbol,
            hook_name=normalized_hook,
            operation_name=operation_name
        )
        hook_symbol._ast = method_call
        parent_symbol.add_symbol(operation_name, hook_symbol)
        if parent_symbol != self.module:
            self.module.add_symbol(operation_name, hook_symbol)

        _glog('RESULT', 'Hook', _c, 'registered {}:{}'.format(normalized_hook, operation_name))

    def create_hook_to_gql_links(self):
        """
        Create links between hooks and their GQL definitions
        """
        for operation_name, hooks in self.apollo_analysis_results.apollo_hooks_by_operation.items():
            for hook in hooks:
                # Try to find the corresponding GQL definition
                gql_def = self.apollo_analysis_results.get_gql_definition(operation_name)
                
                if gql_def:
                    # Store reference to GQL definition in hook
                    hook.gql_definition = gql_def.to_dict()
