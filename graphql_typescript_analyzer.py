#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
GraphQL TypeScript Analyzer Extension

This extension analyzes TypeScript files for GraphQL usage patterns.
Similar to the JavaScript analyzer, it processes TypeScript content to extract
GraphQL definitions and Apollo hook calls.

LEVEL 1: gql definitions (GqlQuery/Mutation/Subscription)
  - Extracts gql`...` template literals
  - Creates objects for query/mutation/subscription definitions
  
LEVEL 2: Apollo hook calls (GraphQL*Request)
  - Extracts useQuery/useLazyQuery/useMutation/useSubscription
  - Creates objects for hook usage
  - Links to LEVEL 1 definitions
"""

import re
import traceback
from cast.analysers import ua, log, CustomObject, Bookmark, create_link
from cast import Event
from datetime import datetime

# Import from typescript_dependencies (local)
from typescript_dependencies.symbols import SourceFile
from typescript_dependencies.resolution import resolve_expressions
from typescript_dependencies.evaluation import EvaluationTool
from typescript_dependencies.ProgramSymbol import Program

# Import analysis tools from ts_parser
from ts_parser.analysis_results import ApolloAnalysisResults
from ts_parser.apollo_interpreter_ts import analyse_ts_fragment
from ts_parser.apollo_symbols import ApolloHookSymbol, GqlDefinitionSymbol


def analyse(source_file):
    """
    Analyze TypeScript source file for Apollo Client hooks and GraphQL operations.
    Based on test_ts.py analyse() function.
    
    NOTE: For the real analyzer, the source_file is already parsed by the TypeScript analyzer.
    We don't need to parse it again.
    """
    log.info('[GraphQL TS Client] Starting analysis of: ' + source_file.get_path())
    
    # Create Apollo analysis results container
    apollo_analysis_results = ApolloAnalysisResults()
    apollo_analysis_results.ts_evaluation_tool = EvaluationTool()
    
    # Analyze the source file for Apollo patterns
    source_file.parsing_results = analyse_ts_fragment(source_file, apollo_analysis_results)
    
    # Create links between hooks and their GQL definitions
    apollo_analysis_results.create_links()
    
    log.info('[GraphQL TS Client] Analysis complete for: ' + source_file.get_path())
    return apollo_analysis_results


class GraphQLTypeScriptAnalyzer(ua.Extension):
    """
    Two-level GraphQL TypeScript Client analysis:
    - LEVEL 1: gql definitions 
    - LEVEL 2: Apollo hook calls
    """
    
    def __init__(self):
        log.info('[GraphQL TS Client] ========================================')
        log.info('[GraphQL TS Client] GraphQL TypeScript Analyzer initialized')
        log.info('[GraphQL TS Client] ========================================')
        
        # Track definitions for linking (LEVEL 2 -> LEVEL 1)
        self.gql_definitions = {}  # Map variable name to KB object
        self.source_file_counter = 0
        
        # Track created/failed objects for end-of-analysis summary
        # Each entry: {'name': str, 'type': str, 'file_path': str}
        self.created_objects = []
        self.failed_objects = []
        
    @Event('com.castsoftware.typescript', 'typescript_file')
    def get_typescript_file(self, source_file):
        """
        Event handler for TypeScript files.
        
        This event is triggered for each TypeScript file analyzed.
        We use this to process GraphQL-related code in TypeScript files.
        """
        try:
            self.source_file_counter += 1
            log.info('[GraphQL TS Client] ========================================')
            log.info('[GraphQL TS Client] Processing file #' + str(self.source_file_counter) + ': ' + source_file.get_path())
            
            # STEP 1: Run analysis (like in test_hooks_outline_01 and test_hooks_inline_02)
            apollo_analysis_results = analyse(source_file)
            
            # STEP 2: Get results for this specific file
            file_path = source_file.get_path()
            gql_defs = apollo_analysis_results.gql_definitions_by_file[file_path]
            hooks = apollo_analysis_results.apollo_hooks_by_file[file_path]
            
            log.info('[GraphQL TS Client] Found ' + str(len(gql_defs)) + ' GQL definitions')
            log.info('[GraphQL TS Client] Found ' + str(len(hooks)) + ' Apollo hooks')
            
            # STEP 3: LEVEL 1 - Save GQL definitions to KB (same as JavaScript analyzer)
            for gql_def in gql_defs:
                try:
                    self._create_gql_definition (gql_def, source_file)
                except Exception as save_ex:
                    log.warning('[GraphQL TS Client] Error saving GQL definition: ' + str(save_ex))
                    log.warning(traceback.format_exc())
            
            # STEP 4: LEVEL 2 - Save Apollo hooks to KB (same as JavaScript analyzer)
            for hook in hooks:
                try:
                    self._create_hook_object(hook, source_file, apollo_analysis_results)
                except Exception as save_ex:
                    log.warning('[GraphQL TS Client] Error saving Apollo hook: ' + str(save_ex))
                    log.warning(traceback.format_exc())
            
            log.info('[GraphQL TS Client] File processing complete')
            log.info('[GraphQL TS Client] ========================================')
            
        except Exception as e:
            log.warning('[GraphQL TS Client] Error processing file: ' + str(e))
            log.warning(traceback.format_exc())
    
    def _create_gql_definition (self, gql_def, source_file):
        """
        LEVEL 1: Create GraphQL client definition object (GqlQuery/GqlMutation/GqlSubscription).
        
        Same logic as graphql_javascript_analyzer.py _create_gql_definition ()
        
        Args:
            gql_def: GqlDefinition object from analysis results
            source_file: TypeScript SourceFile
        """
        # Initialize tracking vars early so they're available in the except block
        _track_name = '(unknown)'
        _track_type = '(unknown)'
        _track_file = str(source_file.get_path())
        try:
            log.info('[GraphQL TS Client] >>> Creating client definition')
            
            # Step 1: Determine object type based on operation type (same as JS analyzer)
            op_type = gql_def.operation_type
            if op_type == 'query':
                object_type = 'GqlQuery'
            elif op_type == 'mutation':
                object_type = 'GqlMutation'
            elif op_type == 'subscription':
                object_type = 'GqlSubscription'
            else:
                log.warning('[GraphQL TS Client] Unknown operation type: ' + str(op_type))
                object_type = 'GqlQuery'  # fallback
            
            variable_name = gql_def.name
            _track_name = variable_name
            _track_type = object_type
            
            # Step 2: Build unique fullname (file:line format, same as JS analyzer)
            file_path = str(source_file.get_path())
            line_num = gql_def.raw_bookmark.ast.get_begin_line() if gql_def.raw_bookmark and gql_def.raw_bookmark.ast else 0
            fullname = file_path + ':' + str(line_num)
            
            log.info('[GraphQL TS Client] Creating ' + object_type + ': ' + variable_name)
            log.info('[GraphQL TS Client]   - Fullname: ' + fullname)
            log.info('[GraphQL TS Client]   - Operation: ' + str(gql_def.operation_name))
            
            # Step 3: Create CAST custom object
            client_obj = CustomObject()
            client_obj.set_type(object_type)
            client_obj.set_name(variable_name)
            client_obj.set_fullname(fullname)
            
            # Step 4: Set parent (file-level KB object)
            # For GQL definitions, the parent is the file itself
            parent_kb = source_file.get_kb_object()
            if parent_kb:
                client_obj.set_parent(parent_kb)
                log.info('[GraphQL TS Client]   - Parent: ' + str(parent_kb))
            else:
                log.warning('[GraphQL TS Client]   - No parent KB object found for file')
            
            # Step 5: Save object to KB (MUST be done before save_property)
            client_obj.save()
            
            # Step 6: Save properties (AFTER save())
            client_obj.save_property('GraphQL_Client_Definition.operationName', gql_def.operation_name or '')
            client_obj.save_property('GraphQL_Client_Definition.rawQueryText', gql_def.raw_query_text or '')
            client_obj.save_property('GraphQL_Client_Definition.variables', gql_def.variables or '')
            client_obj.save_property('GraphQL_Client_Definition.fieldsSelected', gql_def.fields_selected or '')
            
            # Step 7: Create bookmark for source navigation
            try:
                if gql_def.raw_bookmark:
                    bookmark = gql_def.raw_bookmark.get_bookmark()
                    if bookmark:
                        client_obj.save_position(bookmark)
                        log.info('[GraphQL TS Client]   - Bookmark saved')
                    else:
                        log.warning('[GraphQL TS Client]   - Bookmark is None')
                else:
                    log.warning('[GraphQL TS Client]   - No raw_bookmark available')
            except Exception as e:
                log.warning('[GraphQL TS Client] Could not save bookmark: ' + str(e))
                log.warning(traceback.format_exc())
            
            # Step 8: Store in cache for LEVEL 2 linking
            log.info('[GraphQL TS Client] >>> Storing definition in cache')
            log.info('[GraphQL TS Client]     KEY: "' + variable_name + '"')
            self.gql_definitions[variable_name] = client_obj
            log.info('[GraphQL TS Client]     Cache now contains ' + str(len(self.gql_definitions)) + ' definition(s)')
            log.info('[GraphQL TS Client] ✓ Created ' + object_type + ': ' + variable_name)
            self.created_objects.append({'name': variable_name, 'type': object_type, 'file_path': file_path})
            
        except Exception as e:
            log.warning('[GraphQL TS Client] Error creating definition: ' + str(e))
            log.warning(traceback.format_exc())
            self.failed_objects.append({'name': _track_name, 'type': _track_type, 'file_path': _track_file})
    
    def _create_hook_object(self, hook, source_file, apollo_analysis_results):
        """
        LEVEL 2: Create GraphQL hook request object (GraphQLApolloHook*).
        
        Same logic as graphql_javascript_analyzer.py _create_request_object()
        
        Args:
            hook: ApolloHookObject from analysis results
            source_file: TypeScript SourceFile
            apollo_analysis_results: ApolloAnalysisResults with gql_definitions
        """
        # Initialize tracking vars early so they're available in the except block
        _track_name = '(unknown)'
        _track_type = '(unknown)'
        _track_file = str(source_file.get_path())
        try:
            hook_name = hook.hook_name
            operation_name = hook.operation_name
            _track_name = hook_name + ':' + operation_name
            
            log.info('[GraphQL TS Client] Processing hook: ' + hook_name)
            log.info('[GraphQL TS Client] Operation name: ' + operation_name)
            
            # Step 1: Determine object type based on hook type (same as JS analyzer)
            if hook_name == 'useQuery':
                object_type = 'GraphQLApolloHookQuery'
            elif hook_name == 'useLazyQuery':
                object_type = 'GraphQLApolloHookLazyQuery'
            elif hook_name == 'useMutation':
                object_type = 'GraphQLApolloHookMutation'
            elif hook_name == 'useSubscription':
                object_type = 'GraphQLApolloHookSubscription'
            else:
                log.warning('[GraphQL TS Client] Unknown hook type: ' + hook_name)
                object_type = 'GraphQLApolloHookQuery'  # fallback
            _track_type = object_type
            
            # Step 2: Get parent component (KB object)
            # For hooks, we need to find the containing function/component from the raw_bookmark
            parent_kb = None
            
            # Try to get parent from the hook's AST location
            if hook.raw_bookmark and hook.raw_bookmark.ast:
                # Try get_first_kb_parent() if available (similar to JS analyzer)
                if hasattr(hook.raw_bookmark.ast, 'get_first_kb_parent'):
                    first_kb_parent = hook.raw_bookmark.ast.get_first_kb_parent()
                    if first_kb_parent:
                        parent_kb = first_kb_parent.get_kb_object()
                        log.info('[GraphQL TS Client] Parent from get_first_kb_parent: ' + str(parent_kb))
            
            # Fallback: use the file as parent
            if not parent_kb:
                parent_kb = source_file.get_kb_object()
                log.info('[GraphQL TS Client] Using file as parent: ' + str(parent_kb))
            
            if not parent_kb:
                log.warning('[GraphQL TS Client] No parent KB object for hook')
                return
            
            # Step 3: Build unique fullname (file:line format, same as JS analyzer)
            file_path = str(source_file.get_path())
            line_num = hook.raw_bookmark.ast.get_begin_line() if hook.raw_bookmark and hook.raw_bookmark.ast else 0
            fullname = file_path + ':' + str(line_num)
            
            # Step 4: Build unique name (same as JS analyzer: hookType:operationName)
            unique_request_name = hook_name + ':' + operation_name
            
            log.info('[GraphQL TS Client] Creating ' + object_type + ': ' + unique_request_name)
            log.info('[GraphQL TS Client]   - Fullname: ' + fullname)
            
            # Step 5: Create CAST custom object
            request_obj = CustomObject()
            request_obj.set_type(object_type)
            request_obj.set_name(unique_request_name)
            request_obj.set_fullname(fullname)
            request_obj.set_parent(parent_kb)
            
            # Step 6: Save object to KB (MUST be done before save_property)
            request_obj.save()
            
            # Step 7: Save properties (AFTER save(), same as JS analyzer)
            request_obj.save_property('GraphQL_Hook_Request.hookType', hook_name)
            
            # Note: TypeScript analyzer doesn't extract fetchPolicy/errorPolicy yet
            # Could be added later if needed
            
            # Step 8: Create bookmark and CALL link (component -> request)
            try:
                if hook.raw_bookmark:
                    bookmark = hook.raw_bookmark.get_bookmark()
                    if bookmark:
                        request_obj.save_position(bookmark)
                        log.info('[GraphQL TS Client]   - Bookmark saved')
                        try:
                            create_link("callLink", parent_kb, request_obj, bookmark)
                            log.info('[GraphQL TS Client]   - CALL link created (with bookmark)')
                        except Exception as link_ex:
                            log.warning('[GraphQL TS Client]   - Could not create CALL link: ' + str(link_ex))
                    else:
                        log.warning('[GraphQL TS Client]   - Bookmark is None')
                else:
                    log.warning('[GraphQL TS Client]   - No raw_bookmark available')
            except Exception as e:
                log.warning('[GraphQL TS Client] Could not create bookmark/link: ' + str(e))
                log.warning(traceback.format_exc())
            
            # Step 9: Create USES link (request -> client definition)
            log.info('[GraphQL TS Client] >>> Searching for client definition')
            log.info('[GraphQL TS Client]     SEARCHING FOR: "' + operation_name + '"')
            log.info('[GraphQL TS Client]     AVAILABLE KEYS: ' + str(list(self.gql_definitions.keys())))
            
            if operation_name in self.gql_definitions:
                client_obj = self.gql_definitions[operation_name]
                log.info('[GraphQL TS Client]     ✓ Found client definition: ' + str(client_obj))
                try:
                    create_link("useLink", request_obj, client_obj)
                    log.info('[GraphQL TS Client]     ✓ Created USES link: ' + unique_request_name + ' -> ' + operation_name)
                except Exception as link_ex:
                    log.warning('[GraphQL TS Client]     ✗ Failed to create USES link: ' + str(link_ex))
            else:
                log.info('[GraphQL TS Client]     ✗ Client definition not found: "' + operation_name + '"')
                log.info('[GraphQL TS Client]         This is expected for inline gql definitions')
                log.info('[GraphQL TS Client]         Inline case: hook references the GraphQL operation name directly')
            
            log.info('[GraphQL TS Client] ✓ Created ' + object_type + ': ' + operation_name)
            self.created_objects.append({'name': unique_request_name, 'type': object_type, 'file_path': file_path})
            
        except Exception as e:
            log.warning('[GraphQL TS Client] Error creating request: ' + str(e))
            log.warning(traceback.format_exc())
            self.failed_objects.append({'name': _track_name, 'type': _track_type, 'file_path': _track_file})
    
    @Event('com.castsoftware.typescript', 'typescript_endanalysis_completed')
    def on_end_html5_and_typescript(self, data):
        """
        Event handler for end of TypeScript analysis.
        
        This is called when all TypeScript files have been processed.
        We use this to display final statistics.
        """
        log.info('[GraphQL TS Client] ================================================')
        log.info('[GraphQL TS Client] === END OF ANALYSIS SUMMARY ===')
        log.info('[GraphQL TS Client] Total TypeScript files analyzed: ' + str(self.source_file_counter))
        log.info('[GraphQL TS Client] ------------------------------------------------')
        
        # --- Successfully created objects ---
        log.info('[GraphQL TS Client] OBJECTS CREATED SUCCESSFULLY (' + str(len(self.created_objects)) + '):')
        if self.created_objects:
            for obj in self.created_objects:
                log.info('[GraphQL TS Client]   [OK] name="' + obj['name'] + '" type=' + obj['type'] + ' file=' + obj['file_path'])
        else:
            log.info('[GraphQL TS Client]   (none)')
        
        log.info('[GraphQL TS Client] ------------------------------------------------')
        
        # --- Objects that failed ---
        log.info('[GraphQL TS Client] OBJECTS WITH ERRORS (' + str(len(self.failed_objects)) + '):')
        if self.failed_objects:
            for obj in self.failed_objects:
                log.info('[GraphQL TS Client]   [ERR] name="' + obj['name'] + '" type=' + obj['type'] + ' file=' + obj['file_path'])
        else:
            log.info('[GraphQL TS Client]   (none)')
        
        log.info('[GraphQL TS Client] ------------------------------------------------')
        
        # --- Count by object type ---
        type_counts = {}
        for obj in self.created_objects:
            obj_type = obj['type']
            type_counts[obj_type] = type_counts.get(obj_type, 0) + 1
        
        log.info('[GraphQL TS Client] OBJECTS CREATED PER TYPE:')
        if type_counts:
            for obj_type, count in sorted(type_counts.items()):
                log.info('[GraphQL TS Client]   ' + obj_type + ': ' + str(count))
        else:
            log.info('[GraphQL TS Client]   (none)')
        
        log.info('[GraphQL TS Client] ================================================')
    
    def finish(self):
        """Clean up at end of analysis."""
        log.info('[GraphQL TS Client] === FINISH: Cleanup ===')
        log.info('[GraphQL TS Client] Processed ' + str(self.source_file_counter) + ' TypeScript files total')
        log.info('[GraphQL TS Client] Created ' + str(len(self.gql_definitions)) + ' gql definitions')
        
        self.gql_definitions = {}
        self.source_file_counter = 0
        self.created_objects = []
        self.failed_objects = []
        
        log.info('[GraphQL TS Client] === FINISH: Complete ===')


