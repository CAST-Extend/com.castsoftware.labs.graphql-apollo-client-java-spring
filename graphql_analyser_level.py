# -*- coding: utf-8 -*-
"""
GraphQL Analyzer Level Extension

This module implements the analyzer-level processing for GraphQL source files.
It follows the CAST 2-pass analysis architecture:
  - PHASE 1 (start_file): Light parsing to extract global structures
  - PHASE 2 (end_analysis): Full parsing for reference resolution and link creation

Architecture:
    - Analyzer Level: Orchestrates the 2-pass analysis
    - Module: Encapsulates file-specific parsing logic (see graphql_module)
    - Parsing is modular and extensible

Python 3.4+ compatible.
"""

import cast_upgrade_1_6_23  # noqa: F401 - Required for CAST SDK compatibility
import cast.analysers
from cast.analysers import log, Bookmark
from cast.analysers import ua
import os
import traceback

# Import the Module class for file-level parsing
from graphql_module import GraphQLModule, GraphQLLibrary


class GraphQLAnalyzerExtension(ua.Extension):
    """
    GraphQL Analyzer Extension.
    
    Implements the CAST 2-pass analysis pattern:
    1. start_file(): Light parse each file, create objects, store in library
    2. end_analysis(): Full parse all modules, resolve references, create links
    
    Attributes:
        active (bool): Whether the extension is active for this analysis
        extensions (list): List of file extensions to process
        library (GraphQLLibrary): Container for all parsed modules
    """
    
    def __init__(self):
        """Initialize the analyzer with default configuration."""
        self.active = True
        self.extensions = ['.graphql', '.gql', '.graphqls']
        # Main container for all parsed modules
        self.library = GraphQLLibrary()
    
    def start_analysis(self):
        """
        Called once at the beginning of the analysis.
        
        Initializes the analyzer and retrieves configuration from UA options.
        Sets self.active based on whether GraphQL is configured.
        """
        log.debug('[GraphQL] Starting GraphQL analysis')
        
        try:
            options = cast.analysers.get_ua_options()  # @UndefinedVariable
            if 'GraphQL' in options:
                self.active = True
                self.extensions = options['GraphQL'].extensions
                log.debug('[GraphQL] Extensions configured: ' + str(self.extensions))
            else:
                self.active = False
                log.debug('[GraphQL] No GraphQL configuration found, extension inactive')
        except Exception as e:
            # Fallback for unit tests where get_ua_options() may not be available
            log.debug('[GraphQL] Using default configuration: ' + str(e))
            pass
    
    def start_file(self, file):
        """
        PHASE 1: Light parsing of a single file.
        
        Called for each file in the analysis. If the file matches our language:
        1. Create a Module instance for the file
        2. Run light_parse() to extract global structures
        3. Create CAST objects for discovered elements
        4. Store the module in the library for Phase 2
        
        Args:
            file: CAST File object representing the source file
        """
        if not self.active:
            return
        
        filepath = file.get_path()
        filename = os.path.basename(filepath).lower()
        _, ext = os.path.splitext(filepath)
        
        # Normalize extension (remove leading dot if present)
        ext = ext.lstrip('.').lower()
        
        # Check if this file matches our language extensions
        extensions_normalized = [e.lstrip('.').lower() for e in self.extensions]
        if ext not in extensions_normalized:
            log.debug('[GraphQL] Skipping non-GraphQL file: ' + filepath)
            return
        
        log.debug('[GraphQL] Processing file: ' + filepath)
        
        try:
            # Create a module instance for this file
            module = GraphQLModule(filepath, file)
            
            # PHASE 1: Light parse to extract global structures
            module.light_parse()
            
            # Store module in library for Phase 2 processing
            self.library.add_module(module)
            
            log.debug('[GraphQL] Light parse complete for: ' + filename)
            
        except Exception as e:
            log.warning('[GraphQL] Error during light parse of ' + filepath + ': ' + str(e))
            log.debug('[GraphQL] ' + traceback.format_exc())
    
    def end_analysis(self):
        """
        PHASE 2: Full parsing and reference resolution.
        
        Called once after all files have been processed. For each module:
        1. Run full_parse() to detect calls (REQUIRES MANUAL IMPLEMENTATION)
        2. Resolve references using the complete symbol table (REQUIRES MANUAL IMPLEMENTATION)
        3. Create links between objects (REQUIRES MANUAL IMPLEMENTATION)
        4. Clean up AST to free memory
        
        NOTE: Link detection, resolution, and creation are SKELETON methods.
        You must implement technology-specific logic in the module class.
        See the module template for detailed guidance.
        """
        if not self.active:
            return
        
        log.debug('[GraphQL] Starting Phase 2: Full parsing')
        log.debug('[GraphQL] Total modules to process: ' + str(len(self.library.get_modules())))
        
        # Statistics for logging
        total_objects = 0
        total_links = 0
        errors = 0
        
        for module in self.library.get_modules():
            try:
                log.debug('[GraphQL] Full parsing: ' + str(module.get_path()))
                
                # PHASE 2: Full parse for detailed structure (MANUAL IMPLEMENTATION REQUIRED)
                # By default, this is a skeleton that does nothing.
                # Implement technology-specific call detection in the module class.
                module.full_parse()
                
                # Resolve references using complete symbol table (MANUAL IMPLEMENTATION REQUIRED)
                # By default, this is a skeleton that does nothing.
                # Implement technology-specific resolution in the module class.
                module.resolve(self.library)
                
                # Count objects created in Pass 1
                total_objects += len(module.objects)
                
                # Create links between objects (MANUAL IMPLEMENTATION REQUIRED)
                # By default, this returns 0 because it's a skeleton.
                # Implement technology-specific link creation in the module class.
                links_count = module.save_links()
                total_links += links_count
                
                # Clean up AST to free memory
                module.clean_ast()
                
            except Exception as e:
                errors += 1
                log.warning('[GraphQL] Error during full parse of ' + 
                           str(module.get_path()) + ': ' + str(e))
                log.debug('[GraphQL] ' + traceback.format_exc())
        
        # =====================================================================
        # FINAL SUMMARY
        # =====================================================================
        log.info('[GraphQL] ')
        log.info('[GraphQL] ╔══════════════════════════════════════════════════════════════╗')
        log.info('[GraphQL] ║              GraphQL ANALYSIS SUMMARY                          ║')
        log.info('[GraphQL] ╚══════════════════════════════════════════════════════════════╝')
        
        # --- OBJECTS BY FILE ---
        log.info('[GraphQL] ')
        log.info('[GraphQL] ┌─── OBJECTS CREATED (' + str(total_objects) + ' total) ───')
        for module in self.library.get_modules():
            filename = os.path.basename(module.get_path())
            objects_in_file = []
            for fullname in module.objects.keys():
                if fullname != module.get_path():  # Skip Program objects
                    # Extract short name from fullname
                    short = fullname.split('.')[-1] if '.' in fullname else fullname
                    # Get type
                    for obj_type, objs in module.objects_by_type.items():
                        if module.objects[fullname] in objs:
                            objects_in_file.append((short, obj_type))
                            break
            if objects_in_file:
                log.info('[GraphQL] │')
                log.info('[GraphQL] │  ' + filename)
                for obj_name, obj_type in objects_in_file:
                    type_short = obj_type.replace('GraphQL', '')
                    log.info('[GraphQL] │    └─ ' + obj_name + ' (' + type_short + ')')
        
        log.info('[GraphQL] │')
        log.info('[GraphQL] └───────────────────────────────────────────────────────────────')
        
        # --- LINKS STATUS ---
        log.info('[GraphQL] ')
        if total_links == 0:
            log.info('[GraphQL] ┌─── LINKS ───')
            log.info('[GraphQL] │')
            log.info('[GraphQL] │  No links created (expected for skeleton implementation)')
            log.info('[GraphQL] │')
            log.info('[GraphQL] │  To create links, implement these methods in the module class:')
            log.info('[GraphQL] │    - full_parse(): Detect function/method calls')
            log.info('[GraphQL] │    - resolve(): Resolve call targets using the symbol table')
            log.info('[GraphQL] │    - save_links(): Create links using create_link() SDK method')
            log.info('[GraphQL] │')
            log.info('[GraphQL] │  See the module source code for detailed documentation.')
            log.info('[GraphQL] └───────────────────────────────────────────────────────────────')
        else:
            log.info('[GraphQL] ┌─── LINKS CREATED (' + str(total_links) + ' total) ───')
            log.info('[GraphQL] │')
            log.info('[GraphQL] │  Custom link implementation active.')
            log.info('[GraphQL] └───────────────────────────────────────────────────────────────')
        
        log.info('[GraphQL] ')
        log.info('[GraphQL] ════════════════════════════════════════════════════════════════')
        
        if errors > 0:
            log.warning('[GraphQL]   Modules with errors: ' + str(errors))
