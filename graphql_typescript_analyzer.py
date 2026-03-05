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
        self.gql_definitions = {}  # Map operation_name -> KB object (e.g. "GetLambdaInvocations" -> CustomObject)
        self.source_file_counter = 0

        # Pending useLinks: hooks processed before their GQL definition file (Bug 2)
        self.pending_links = []  # List of (request_obj, operation_name, caller_file_kb)

        # Dedup cache for GqlUnresolvedDefinition objects (keyed by operation_name)
        self.missing_gql_objects = {}

        # Map variable_name -> kb_name (operation_name) for hook lookup resolution.
        # Populated by _create_gql_definition(); first-seen wins on collision (outer scope wins).
        self.var_name_to_op_name = {}

        # Map function_name -> KB object, populated from every processed TS file.
        # Used to create callLink from codegen hook objects to the TS wrapper function.
        self.ts_functions = {}

        # Codegen hooks whose TS wrapper function was not yet seen when the hook was created.
        # Each entry: (codegen_obj, function_name)
        self.pending_codegen_links = []

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

            # STEP 3: Collect TS function / method KB objects for codegen callLink resolution.
            # CAST has already created these KB objects before our event fires (CAST processes
            # the file first, then fires 'typescript_file' for extensions).
            # We do this BEFORE hook processing so same-file codegen callLinks can be resolved
            # immediately without queuing (e.g. useGetXQuery defined and called in the same file).
            try:
                for sym in source_file.get_all_symbols():
                    sym_type = type(sym).__name__
                    if sym_type in ('Function', 'Method'):
                        fn_name = sym.get_name() if hasattr(sym, 'get_name') else None
                        if fn_name and fn_name not in self.ts_functions:
                            fn_kb = sym.get_kb_object() if hasattr(sym, 'get_kb_object') else None
                            if fn_kb:
                                self.ts_functions[fn_name] = fn_kb
            except Exception as sym_ex:
                log.warning('[GraphQL TS Client] Error collecting function symbols: ' + str(sym_ex))

            # STEP 4: LEVEL 1 - Save GQL definitions to KB (same as JavaScript analyzer)
            for gql_def in gql_defs:
                try:
                    self._create_gql_definition (gql_def, source_file)
                except Exception as save_ex:
                    log.warning('[GraphQL TS Client] Error saving GQL definition: ' + str(save_ex))
                    log.warning(traceback.format_exc())

            # STEP 5: LEVEL 2 - Save Apollo hooks to KB (same as JavaScript analyzer)
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
            # Use the GQL operation name as the KB object name (e.g. "GetLambdaInvocations").
            # This is globally unique (GQL spec), avoids CAST dedup collisions when the same
            # variable name (e.g. "QUERY") is declared in multiple scopes of the same file,
            # and makes schema matching trivial: operation_name == field in type Query/Mutation/Subscription.
            # Fall back to variable_name only for anonymous gql templates (no parsed operation name).
            kb_name = gql_def.operation_name or variable_name
            _track_name = kb_name
            _track_type = object_type

            # Step 2: Build unique fullname (file:line format, same as JS analyzer)
            file_path = str(source_file.get_path())
            line_num = gql_def.raw_bookmark.ast.get_begin_line() if gql_def.raw_bookmark and gql_def.raw_bookmark.ast else 0
            fullname = file_path + ':' + str(line_num)

            log.info('[GraphQL TS Client] Creating ' + object_type + ': ' + kb_name +
                     ' (var=' + variable_name + ')')
            log.info('[GraphQL TS Client]   - Fullname: ' + fullname)
            log.info('[GraphQL TS Client]   - Operation: ' + str(gql_def.operation_name))
            
            # Step 3: Create CAST custom object
            client_obj = CustomObject()
            client_obj.set_type(object_type)
            client_obj.set_name(kb_name)
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
            
            # Step 8: Store in cache for LEVEL 2 linking (keyed by operation name).
            # Also record variable_name -> kb_name mapping so hook lookup can resolve
            # useQuery(VAR_NAME) -> self.gql_definitions[operation_name].
            # First-seen wins on variable name collision (outer scope takes priority).
            log.info('[GraphQL TS Client] >>> Storing definition in cache')
            log.info('[GraphQL TS Client]     KEY: "' + kb_name + '" (var="' + variable_name + '")')
            self.gql_definitions[kb_name] = client_obj
            if variable_name not in self.var_name_to_op_name:
                self.var_name_to_op_name[variable_name] = kb_name
            else:
                log.warning('[GraphQL TS Client]   - Variable name collision: "' + variable_name +
                            '" already maps to "' + self.var_name_to_op_name[variable_name] +
                            '"; new op "' + kb_name + '" stored in cache but hook lookup will use first')
            log.info('[GraphQL TS Client]     Cache now contains ' + str(len(self.gql_definitions)) + ' definition(s)')
            log.info('[GraphQL TS Client] ✓ Created ' + object_type + ': ' + kb_name)
            self.created_objects.append({'name': kb_name, 'type': object_type, 'file_path': file_path})
            
        except Exception as e:
            log.warning('[GraphQL TS Client] Error creating definition: ' + str(e))
            log.warning(traceback.format_exc())
            self.failed_objects.append({'name': _track_name, 'type': _track_type, 'file_path': _track_file})
    
    # Map (source_pattern, hook_name) -> metamodel type name.
    # React hooks use the existing GraphQLApolloHook* types.
    # Patterns 1/2/3 use the new dedicated types.
    _HOOK_TYPE_MAP = {
        ('react_hook',    'useQuery'):        'GraphQLApolloHookQuery',
        ('react_hook',    'useLazyQuery'):    'GraphQLApolloHookLazyQuery',
        ('react_hook',    'useMutation'):     'GraphQLApolloHookMutation',
        ('react_hook',    'useSubscription'): 'GraphQLApolloHookSubscription',
        ('client_method', 'useQuery'):        'GraphQLApolloClientQuery',
        ('client_method', 'useMutation'):     'GraphQLApolloClientMutation',
        ('client_method', 'useSubscription'): 'GraphQLApolloClientSubscription',
        ('angular_method','useQuery'):        'GraphQLApolloAngularQuery',
        ('angular_method','useMutation'):     'GraphQLApolloAngularMutation',
        ('angular_method','useLazyQuery'):    'GraphQLApolloAngularWatchQuery',
        ('codegen_hook',  'useQuery'):        'GraphQLApolloCodegenQuery',
        ('codegen_hook',  'useMutation'):     'GraphQLApolloCodegenMutation',
        ('codegen_hook',  'useSubscription'): 'GraphQLApolloCodegenSubscription',
    }

    # Map (source_pattern, hook_name) -> visible name prefix used in set_name().
    # React hooks keep the original useXxx prefix.
    # Angular uses the call syntax (this.apollo.query/mutate/watchQuery).
    # Apollo Client direct calls use client.query/mutate/subscribe.
    _HOOK_NAME_PREFIX = {
        ('react_hook',    'useQuery'):        'useQuery',
        ('react_hook',    'useLazyQuery'):    'useLazyQuery',
        ('react_hook',    'useMutation'):     'useMutation',
        ('react_hook',    'useSubscription'): 'useSubscription',
        ('client_method', 'useQuery'):        'client.query',
        ('client_method', 'useMutation'):     'client.mutate',
        ('client_method', 'useSubscription'): 'client.subscribe',
        ('angular_method','useQuery'):        'apollo.query',
        ('angular_method','useMutation'):     'apollo.mutate',
        ('angular_method','useLazyQuery'):    'apollo.watchQuery',
        ('codegen_hook',  'useQuery'):        'useQuery',
        ('codegen_hook',  'useMutation'):     'useMutation',
        ('codegen_hook',  'useSubscription'): 'useSubscription',
    }

    def _create_hook_object(self, hook, source_file, apollo_analysis_results):
        """
        LEVEL 2: Create GraphQL hook/call request object.

        Dispatches to the correct metamodel type based on (source_pattern, hook_name):
          react_hook    → GraphQLApolloHook*
          client_method → GraphQLApolloClient*
          angular_method→ GraphQLAngular*
          codegen_hook  → GraphQLApolloCodegen*

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
            source_pattern = getattr(hook, 'source_pattern', 'react_hook')
            _track_name = hook_name + ':' + operation_name

            log.info('[GraphQL TS Client] Processing hook: ' + hook_name +
                     ' (source_pattern=' + source_pattern + ')')
            log.info('[GraphQL TS Client] Operation name: ' + operation_name)

            # Step 1: Determine object type from (source_pattern, hook_name)
            object_type = self._HOOK_TYPE_MAP.get((source_pattern, hook_name))
            if not object_type:
                log.warning('[GraphQL TS Client] Unknown (source_pattern, hook_name): (' +
                            source_pattern + ', ' + hook_name + ') — falling back to GraphQLApolloHookQuery')
                object_type = 'GraphQLApolloHookQuery'
            _track_type = object_type
            
            # Step 2: Get parent component (KB object).
            # Priority:
            #   1. hook.parent_symbol (stored by the interpreter via find_parent_symbol_for_ast_node)
            #      — gives the innermost Function/Method that contains the hook call.
            #      This makes callLink(function → hook_obj) correct even for hooks inside
            #      nested functions (e.g. useLazyQuery inside a codegen wrapper function).
            #   2. get_first_kb_parent() on the raw AST node (only works for CAST AST nodes,
            #      not for typescript_dependencies nodes — kept as a future-proof fallback).
            #   3. The file itself as last resort.
            parent_kb = None

            if hook.parent_symbol and hasattr(hook.parent_symbol, 'get_kb_object'):
                try:
                    parent_kb = hook.parent_symbol.get_kb_object()
                    if parent_kb:
                        log.info('[GraphQL TS Client] Parent from parent_symbol: ' + str(parent_kb))
                    else:
                        log.info('[GraphQL TS Client] parent_symbol.get_kb_object() returned None')
                except Exception as ps_ex:
                    log.info('[GraphQL TS Client] parent_symbol.get_kb_object() failed: ' + str(ps_ex))
                    parent_kb = None

            if not parent_kb and hook.raw_bookmark and hook.raw_bookmark.ast:
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
            
            # Step 4: Build unique name.
            # React hooks: useQuery:GetUsers — Angular: apollo.query:GetUsers — Client: client.query:GetUsers
            # Codegen hooks: the full hook function name IS the name (e.g. "useGetPortfolioAllocationLazyQuery")
            if source_pattern == 'codegen_hook':
                unique_request_name = operation_name
            else:
                name_prefix = self._HOOK_NAME_PREFIX.get((source_pattern, hook_name), hook_name)
                unique_request_name = name_prefix + ':' + operation_name
            
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
            
            # Step 7: Save properties (AFTER save()).
            # Only GraphQLApolloHook* types inherit GraphQL_Hook_Request (which defines hookType).
            # The new Pattern 1/2/3 types have no properties — skip save_property for them.
            if source_pattern == 'react_hook':
                request_obj.save_property('GraphQL_Hook_Request.hookType', hook_name)

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

            # Step 9: Create useLink (request -> GQL definition).
            # Codegen hooks do NOT get a useLink here — their chain is:
            #   codegen call site → CALL → codegen wrapper function → CALL → standard hook → useLink → GQL def
            # The useLink is created by the standard hook object inside the wrapper, not here.
            log.info('[GraphQL TS Client] >>> Searching for client definition')
            log.info('[GraphQL TS Client]     AVAILABLE KEYS: ' + str(list(self.gql_definitions.keys())))

            if source_pattern != 'codegen_hook':
                resolved_key = None
                lookup_key = self.var_name_to_op_name.get(operation_name, operation_name)
                log.info('[GraphQL TS Client]     VAR: "' + operation_name + '" -> KEY: "' + lookup_key + '"')
                if lookup_key in self.gql_definitions:
                    resolved_key = lookup_key
                else:
                    log.info('[GraphQL TS Client]     ✗ Not found yet — queued for retry (Bug 2)')
                    self.pending_links.append(
                        (request_obj, operation_name, source_file.get_kb_object(), source_pattern))

                if resolved_key is not None:
                    client_obj = self.gql_definitions[resolved_key]
                    log.info('[GraphQL TS Client]     ✓ Found client definition: ' + str(client_obj))
                    try:
                        create_link("useLink", request_obj, client_obj)
                        log.info('[GraphQL TS Client]     ✓ Created useLink: ' + unique_request_name +
                                 ' -> ' + resolved_key)
                    except Exception as link_ex:
                        log.warning('[GraphQL TS Client]     ✗ Failed to create useLink: ' + str(link_ex))
            else:
                # Codegen hook: create callLink to the TS wrapper function so the chain
                # codegen_obj → CALL → wrapper_function → CALL → useLazyQuery → USE → GqlDef is visible.
                log.info('[GraphQL TS Client]     Codegen hook — no useLink; creating callLink to TS function')
                if operation_name in self.ts_functions:
                    fn_kb = self.ts_functions[operation_name]
                    try:
                        create_link("callLink", request_obj, fn_kb)
                        log.info('[GraphQL TS Client]     ✓ callLink: codegen obj → TS function ' + operation_name)
                    except Exception as link_ex:
                        log.warning('[GraphQL TS Client]     ✗ Failed to create codegen callLink: ' + str(link_ex))
                else:
                    self.pending_codegen_links.append((request_obj, operation_name))
                    log.info('[GraphQL TS Client]     ✗ TS function "' + operation_name + '" not yet seen — queued')
            
            log.info('[GraphQL TS Client] ✓ Created ' + object_type + ': ' + operation_name)
            self.created_objects.append({'name': unique_request_name, 'type': object_type, 'file_path': file_path})
            
        except Exception as e:
            log.warning('[GraphQL TS Client] Error creating request: ' + str(e))
            log.warning(traceback.format_exc())
            self.failed_objects.append({'name': _track_name, 'type': _track_type, 'file_path': _track_file})
    
    def _create_missing_gql_definition(self, request_obj, operation_name, caller_file_kb):
        """
        Create (or reuse) a GqlUnresolvedDefinition object for a hook whose GQL definition
        was never found in any analyzed file.

        Deduplication: one object per operation_name regardless of how many hooks reference it.
        All hooks get a useLink to the same object.
        """
        try:
            if operation_name not in self.missing_gql_objects:
                missing_obj = CustomObject()
                missing_obj.set_type('GqlUnresolvedDefinition')
                missing_obj.set_name(operation_name)
                missing_obj.set_fullname('[missing]:' + operation_name)
                if caller_file_kb:
                    missing_obj.set_parent(caller_file_kb)
                missing_obj.save()
                self.missing_gql_objects[operation_name] = missing_obj
                log.info('[GraphQL TS Client] Created GqlUnresolvedDefinition: ' + operation_name)
                self.created_objects.append({'name': operation_name, 'type': 'GqlUnresolvedDefinition',
                                             'file_path': str(caller_file_kb)})
            else:
                missing_obj = self.missing_gql_objects[operation_name]
                log.info('[GraphQL TS Client] Reusing GqlUnresolvedDefinition: ' + operation_name)
            create_link("useLink", request_obj, missing_obj)
            log.info('[GraphQL TS Client]   ✓ useLink: hook -> [unresolved] ' + operation_name)
        except Exception as e:
            log.warning('[GraphQL TS Client] Error creating GqlUnresolvedDefinition for "' +
                        operation_name + '": ' + str(e))
            log.warning(traceback.format_exc())

    @Event('com.castsoftware.typescript', 'typescript_endanalysis_completed')
    def on_end_html5_and_typescript(self, data):
        """
        Event handler for end of TypeScript analysis.
        
        This is called when all TypeScript files have been processed.
        We use this to display final statistics.
        """
        # Resolve pending codegen callLinks (function defined in a file processed after the call site).
        if self.pending_codegen_links:
            log.info('[GraphQL TS Client] Resolving ' + str(len(self.pending_codegen_links)) + ' pending codegen callLink(s)...')
            for (codegen_obj, fn_name) in self.pending_codegen_links:
                if fn_name in self.ts_functions:
                    fn_kb = self.ts_functions[fn_name]
                    try:
                        create_link("callLink", codegen_obj, fn_kb)
                        log.info('[GraphQL TS Client]   ✓ Resolved codegen callLink: ' + fn_name)
                    except Exception as e:
                        log.warning('[GraphQL TS Client]   ✗ Failed codegen callLink for "' + fn_name + '": ' + str(e))
                else:
                    log.info('[GraphQL TS Client]   ✗ TS function not found anywhere: "' + fn_name + '" (external/generated)')
            self.pending_codegen_links = []

        # Bug 2 fix: resolve pending useLinks for cross-file GQL definitions.
        # Tuple format: (request_obj, operation_name, caller_file_kb, source_pattern)
        # Codegen hooks are never added to pending_links (no useLink created for them).
        if self.pending_links:
            log.info('[GraphQL TS Client] Resolving ' + str(len(self.pending_links)) + ' pending useLink(s)...')
            still_unresolved = []
            for entry in self.pending_links:
                # Support both 3-tuple (legacy) and 4-tuple (new, with source_pattern)
                if len(entry) == 4:
                    request_obj, operation_name, caller_file_kb, source_pattern = entry
                else:
                    request_obj, operation_name, caller_file_kb = entry
                    source_pattern = 'react_hook'

                lookup_key = self.var_name_to_op_name.get(operation_name, operation_name)

                if lookup_key in self.gql_definitions:
                    client_obj = self.gql_definitions[lookup_key]
                    try:
                        create_link("useLink", request_obj, client_obj)
                        log.info('[GraphQL TS Client]   ✓ Resolved pending useLink: "' +
                                 operation_name + '" -> "' + lookup_key + '"')
                    except Exception as link_ex:
                        log.warning('[GraphQL TS Client]   ✗ Could not resolve pending useLink for "' +
                                    lookup_key + '": ' + str(link_ex))
                else:
                    log.info('[GraphQL TS Client]   ✗ Still unresolved: "' + operation_name +
                             '" key="' + lookup_key + '" — creating GqlUnresolvedDefinition')
                    still_unresolved.append((request_obj, lookup_key, caller_file_kb, source_pattern))
            for (request_obj, operation_name, caller_file_kb, _) in still_unresolved:
                self._create_missing_gql_definition(
                    request_obj, operation_name, caller_file_kb)
            self.pending_links = []  # free memory — on_end is the real finish point

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
        
        log.info('[GraphQL TS Client] === FINISH: Cleanup ===')
        log.info('[GraphQL TS Client] Processed ' + str(self.source_file_counter) + ' TypeScript files total')
        log.info('[GraphQL TS Client] Created ' + str(len(self.gql_definitions)) + ' gql definitions')
        
        self.gql_definitions = {}
        self.var_name_to_op_name = {}
        self.missing_gql_objects = {}
        self.ts_functions = {}
        self.pending_codegen_links = []
        self.source_file_counter = 0
        self.created_objects = []
        self.failed_objects = []
        
        log.info('[GraphQL TS Client] === FINISH: Complete ===')


