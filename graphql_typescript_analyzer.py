#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
GraphQL TypeScript Analyzer Extension

This extension analyzes TypeScript files for GraphQL usage patterns.
Similar to the JavaScript analyzer, it processes TypeScript content to extract
GraphQL definitions and Apollo hook calls.

LEVEL 1: gql definitions (TsGqlQuery/TsGqlMutation/TsGqlSubscription)
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
        # Track definitions for linking (LEVEL 2 -> LEVEL 1)
        self.gql_definitions = {}  # Map operation_name -> KB object (e.g. "GetLambdaInvocations" -> CustomObject)
        self.source_file_counter = 0

        # Pending useLinks: hooks processed before their GQL definition file (Bug 2)
        self.pending_links = []  # List of (request_obj, operation_name, caller_file_kb)

        # Dedup cache for TsGqlUnresolvedDefinition objects (keyed by operation_name)
        self.missing_gql_objects = {}

        # Scope-keyed variable resolution: (file_path, var_name, id(parent_symbol)) -> op_name.
        # Enables correct resolution when the same variable name (e.g. "QUERY") is declared
        # in multiple scopes of the same file (e.g. 3 codegen wrapper functions).
        self.scoped_var_map = {}
        # Global fallback for cross-file resolution (first-seen wins).
        self.global_var_map = {}

        # Import-aware cross-file resolution (Bug 9 fix).
        # gql_defs_by_file_var: (source_file_path, var_name) -> op_name
        #   Allows matching useQuery(QUERY) to the exact GQL def exported by a specific file.
        self.gql_defs_by_file_var = {}
        # gql_obj_by_file_var: (source_file_path, var_name) -> KB object (CustomObject)
        #   Direct KB object lookup; bypasses gql_definitions[op_name] last-writer-wins
        #   collision when the same operation name is defined in multiple source files.
        self.gql_obj_by_file_var = {}
        # imported_var_to_file: (consumer_file_path, local_name) -> source_file_path
        #   Populated from import statements: import { QUERY } from './queries' maps
        #   (consumer.tsx, 'QUERY') -> absolute path of queries.ts
        self.imported_var_to_file = {}

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

            # STEP 1: Run analysis (like in test_hooks_outline_01 and test_hooks_inline_02)
            apollo_analysis_results = analyse(source_file)

            # STEP 2: Get results for this specific file
            file_path = source_file.get_path()
            gql_defs = apollo_analysis_results.gql_definitions_by_file[file_path]
            hooks = apollo_analysis_results.apollo_hooks_by_file[file_path]

            # STEP 2b: Build import map for this file so cross-file GQL lookups are
            # import-aware rather than relying on the global first-seen fallback (Bug 9).
            self._build_import_map_for_file(source_file)

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

        except Exception as e:
            log.warning('[GraphQL TS Client] Error processing file: ' + str(e))
            log.warning(traceback.format_exc())
    
    def _build_import_map_for_file(self, source_file):
        """
        Parse import statements of source_file and populate self.imported_var_to_file.

        For each named import  import { FOO } from './bar'  (or  import { FOO as F } from …)
        we record:  (consumer_file_path, local_name) -> resolved_source_file_path

        This enables import-aware cross-file resolution: when useQuery(FOO) is found in
        consumer.tsx, we look up which file exports FOO rather than using the global
        first-seen fallback.

        Only named imports are handled ({...} syntax).  Default imports and star imports
        are skipped — GQL constants are virtually always named exports in real codebases.
        External packages (@apollo/client, etc.) fail get_module_from_import and are
        silently skipped.
        """
        try:
            consumer_path = str(source_file.get_path())
            for imp in source_file.get_imports():
                try:
                    elements = imp.get_imported_elements()
                    if not elements:
                        continue
                    # Resolve the import path to an actual SourceFile object.
                    # get_module_from_import handles relative paths and extensions (.ts/.tsx).
                    # Raises / returns None for unresolvable modules (e.g. npm packages).
                    try:
                        imported_sf = source_file.get_module_from_import(imp)
                    except Exception:
                        imported_sf = None
                    if imported_sf is None:
                        # Try non-exact (fuzzy) path resolution as fallback
                        try:
                            imported_sf = source_file.get_module_from_import_with_non_exact_path(imp)
                        except Exception:
                            imported_sf = None
                    if imported_sf is None:
                        continue
                    source_path = str(imported_sf.get_path())
                    for elem in elements:
                        # local_name is the alias if present, else the original name.
                        # e.g. import { GET_USERS as MY_QUERY } → local_name = 'MY_QUERY'
                        local_name = None
                        try:
                            local_name = elem.get_alias_name() or elem.get_element_name()
                        except Exception as e:
                            log.warning('[GraphQL TS Client] import element name lookup failed: ' + str(e))
                        if local_name:
                            key = (consumer_path, local_name)
                            if key not in self.imported_var_to_file:
                                self.imported_var_to_file[key] = source_path
                except Exception as elem_ex:
                    log.info('[GraphQL TS Client] _build_import_map: skip import: ' + str(elem_ex))
        except Exception as ex:
            log.warning('[GraphQL TS Client] _build_import_map_for_file failed: ' + str(ex))

    def _resolve_variable_in_scope(self, variable_name, hook_parent_symbol, file_path):
        """
        Resolve a variable name to a GQL operation name.

        Resolution order (Bug 9 fix):
          1. Scope-keyed intra-file lookup (same file, innermost scope first).
          2. Import-aware cross-file lookup: if the consumer file imports `variable_name`
             from a specific source file, resolve using (source_file, variable_name) key
             instead of the global first-seen map.  This prevents wrong matches when the
             same variable name (e.g. "QUERY") is defined in multiple files.
          3. Global first-seen fallback (kept for backward compat / unresolvable imports).
        """
        # 1. Scoped intra-file lookup
        if file_path and hook_parent_symbol is not None:
            visited = set()
            scope = hook_parent_symbol
            while scope is not None:
                sid = id(scope)
                if sid in visited:
                    break
                visited.add(sid)
                key = (file_path, variable_name, sid)
                if key in self.scoped_var_map:
                    return self.scoped_var_map[key]
                scope = getattr(scope, 'get_parent_symbol', lambda: None)()

        # 2. Import-aware cross-file lookup
        if file_path:
            source_path = self.imported_var_to_file.get((file_path, variable_name))
            if source_path is not None:
                op_name = self.gql_defs_by_file_var.get((source_path, variable_name))
                if op_name is not None:
                    return op_name
                # Source file known but GQL def not yet processed (ordering) — return a
                # sentinel that will still miss in gql_definitions and land in pending_links,
                # where it will be re-resolved after all files are done.

        # 3. Global first-seen fallback
        return self.global_var_map.get(variable_name, variable_name)

    def _direct_resolve_gql_obj(self, variable_name, hook_ps, fp):
        """
        Resolve variable_name directly to a KB object (CustomObject), bypassing the
        op_name indirection that causes wrong useLinks when the same operation name
        (e.g. 'SearchTransactions') is defined in multiple source files.

        Resolution priority:
          1. Scoped intra-file: scope chain confirms var defined in this file
             → gql_obj_by_file_var[(fp, variable_name)]
          1b. Direct intra-file fallback (when hook_ps is None or scope walk missed)
             → gql_obj_by_file_var.get((fp, variable_name))
          2. Import-aware: consumer imports var from a specific source file
             → gql_obj_by_file_var[(source_path, variable_name)]
             Returns sentinel 'PENDING' when source known but def not yet processed.
          3. Global fallback (op_name based, last-writer-wins risk retained for
             anonymous/unresolvable cases where no better path exists).

        Returns:
          - CustomObject: the resolved KB object
          - 'PENDING': import source is known but the def hasn't been processed yet
          - None: unresolvable at this point (should land in pending_links)
        """
        # 1. Scoped intra-file lookup
        if fp and hook_ps is not None:
            visited = set()
            scope = hook_ps
            while scope is not None:
                sid = id(scope)
                if sid in visited:
                    break
                visited.add(sid)
                key = (fp, variable_name, sid)
                if key in self.scoped_var_map:
                    obj = self.gql_obj_by_file_var.get((fp, variable_name))
                    if obj is not None:
                        return obj
                    break  # confirmed in scope but no obj entry — fall through
                scope = getattr(scope, 'get_parent_symbol', lambda: None)()

        # 1b. Direct intra-file (no scope confirmation; handles hook_ps=None edge case)
        if fp:
            obj = self.gql_obj_by_file_var.get((fp, variable_name))
            if obj is not None:
                return obj

        # 2. Import-aware cross-file lookup
        if fp:
            source_path = self.imported_var_to_file.get((fp, variable_name))
            if source_path is not None:
                obj = self.gql_obj_by_file_var.get((source_path, variable_name))
                if obj is not None:
                    return obj
                return 'PENDING'

        # 3. Global fallback (op_name-based — collision risk when same op_name in multiple files)
        op_name = self.global_var_map.get(variable_name, variable_name)
        obj = self.gql_definitions.get(op_name)
        return obj  # None if not found

    def _create_gql_definition (self, gql_def, source_file):
        """
        LEVEL 1: Create GraphQL client definition object (TsGqlQuery/TsGqlMutation/TsGqlSubscription).
        
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
            # Step 1: Determine object type based on operation type (same as JS analyzer)
            op_type = gql_def.operation_type
            if op_type == 'query':
                object_type = 'TsGqlQuery'
            elif op_type == 'mutation':
                object_type = 'TsGqlMutation'
            elif op_type == 'subscription':
                object_type = 'TsGqlSubscription'
            else:
                log.warning('[GraphQL TS Client] Unknown operation type: ' + str(op_type))
                object_type = 'TsGqlQuery'  # fallback

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
            else:
                log.warning('[GraphQL TS Client] No parent KB object found for file')
            
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
            except Exception as e:
                log.warning('[GraphQL TS Client] Could not save bookmark: ' + str(e))
            
            # Step 8: Store in cache for LEVEL 2 linking (keyed by operation name).
            # Also record variable_name -> kb_name mapping so hook lookup can resolve
            # useQuery(VAR_NAME) -> self.gql_definitions[operation_name].
            # First-seen wins on variable name collision (outer scope takes priority).
            self.gql_definitions[kb_name] = client_obj
            # Scope-keyed map: exact scope match for intra-file resolution
            ps = getattr(gql_def, 'parent_symbol', None)
            scoped_key = (file_path, variable_name, id(ps) if ps is not None else None)
            if scoped_key not in self.scoped_var_map:
                self.scoped_var_map[scoped_key] = kb_name
            # File+var map for import-aware cross-file resolution (Bug 9).
            # Key: (source_file_path, exported_var_name) → allows a consumer that imports
            # { QUERY } from this file to resolve to exactly this operation.
            fv_key = (file_path, variable_name)
            if fv_key not in self.gql_defs_by_file_var:
                self.gql_defs_by_file_var[fv_key] = kb_name
            # Direct KB object cache — avoids op_name collision when same operation name
            # is defined in multiple source files (extends Bug 9 fix: gql_obj_by_file_var).
            if fv_key not in self.gql_obj_by_file_var:
                self.gql_obj_by_file_var[fv_key] = client_obj
            # Global fallback for cross-file (first-seen wins)
            if variable_name not in self.global_var_map:
                self.global_var_map[variable_name] = kb_name
            else:
                log.warning('[GraphQL TS Client] var_name collision: "' + variable_name + '" in multiple scopes')
            self.created_objects.append({'name': kb_name, 'type': object_type, 'file_path': file_path})
            
        except Exception as e:
            log.warning('[GraphQL TS Client] Error creating definition: ' + str(e))
            log.warning(traceback.format_exc())
            self.failed_objects.append({'name': _track_name, 'type': _track_type, 'file_path': _track_file})
    
    # Map (source_pattern, hook_name) -> metamodel type name.
    # All TS types use the Ts* prefix to distinguish from JS equivalents.
    _HOOK_TYPE_MAP = {
        ('react_hook',    'useQuery'):        'TsGraphQLApolloHookQuery',
        ('react_hook',    'useLazyQuery'):    'TsGraphQLApolloHookLazyQuery',
        ('react_hook',    'useMutation'):     'TsGraphQLApolloHookMutation',
        ('react_hook',    'useSubscription'): 'TsGraphQLApolloHookSubscription',
        ('client_method', 'useQuery'):        'TsGraphQLApolloClientQuery',
        ('client_method', 'useMutation'):     'TsGraphQLApolloClientMutation',
        ('client_method', 'useSubscription'): 'TsGraphQLApolloClientSubscription',
        ('angular_method','useQuery'):        'TsGraphQLApolloAngularQuery',
        ('angular_method','useMutation'):     'TsGraphQLApolloAngularMutation',
        ('angular_method','useLazyQuery'):    'TsGraphQLApolloAngularWatchQuery',
        ('codegen_hook',  'useQuery'):        'TsGraphQLApolloCodegenQuery',
        ('codegen_hook',  'useMutation'):     'TsGraphQLApolloCodegenMutation',
        ('codegen_hook',  'useSubscription'): 'TsGraphQLApolloCodegenSubscription',
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

            # Step 1: Determine object type from (source_pattern, hook_name)
            object_type = self._HOOK_TYPE_MAP.get((source_pattern, hook_name))
            if not object_type:
                log.warning('[GraphQL TS Client] Unknown (source_pattern, hook_name): (' +
                            source_pattern + ', ' + hook_name + ')')
                object_type = 'TsGraphQLApolloHookQuery'
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
                except Exception:
                    parent_kb = None

            if not parent_kb and hook.raw_bookmark and hook.raw_bookmark.ast:
                if hasattr(hook.raw_bookmark.ast, 'get_first_kb_parent'):
                    first_kb_parent = hook.raw_bookmark.ast.get_first_kb_parent()
                    if first_kb_parent:
                        parent_kb = first_kb_parent.get_kb_object()

            # Fallback: use the file as parent
            if not parent_kb:
                parent_kb = source_file.get_kb_object()

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
                        try:
                            create_link("callLink", parent_kb, request_obj, bookmark)
                        except Exception as link_ex:
                            log.warning('[GraphQL TS Client] Could not create CALL link: ' + str(link_ex))
            except Exception as e:
                log.warning('[GraphQL TS Client] Could not create bookmark/link: ' + str(e))

            # Step 9: Create useLink (request -> GQL definition).
            # Codegen hooks do NOT get a useLink here — their chain is:
            #   codegen call site → CALL → codegen wrapper function → CALL → standard hook → useLink → GQL def
            # The useLink is created by the standard hook object inside the wrapper, not here.

            if source_pattern != 'codegen_hook':
                hook_ps = getattr(hook, 'parent_symbol', None)
                fp = str(source_file.get_path())
                direct_obj = self._direct_resolve_gql_obj(operation_name, hook_ps, fp)
                if direct_obj == 'PENDING' or direct_obj is None:
                    self.pending_links.append(
                        (request_obj, operation_name, source_file.get_kb_object(), source_pattern, hook_ps, fp))
                else:
                    try:
                        create_link("useLink", request_obj, direct_obj)
                    except Exception as link_ex:
                        log.warning('[GraphQL TS Client] Failed to create useLink: ' + str(link_ex))
            else:
                # Codegen hook: create callLink to the TS wrapper function so the chain
                # codegen_obj → CALL → wrapper_function → CALL → useLazyQuery → USE → GqlDef is visible.
                if operation_name in self.ts_functions:
                    fn_kb = self.ts_functions[operation_name]
                    try:
                        create_link("callLink", request_obj, fn_kb)
                    except Exception as link_ex:
                        log.warning('[GraphQL TS Client] Failed to create codegen callLink: ' + str(link_ex))
                else:
                    self.pending_codegen_links.append((request_obj, operation_name))
            self.created_objects.append({'name': unique_request_name, 'type': object_type, 'file_path': file_path})
            
        except Exception as e:
            log.warning('[GraphQL TS Client] Error creating request: ' + str(e))
            log.warning(traceback.format_exc())
            self.failed_objects.append({'name': _track_name, 'type': _track_type, 'file_path': _track_file})
    
    def _create_missing_gql_definition(self, request_obj, operation_name, caller_file_kb):
        """
        Create (or reuse) a TsGqlUnresolvedDefinition object for a hook whose GQL definition
        was never found in any analyzed file.

        Deduplication: one object per operation_name regardless of how many hooks reference it.
        All hooks get a useLink to the same object.
        """
        try:
            if operation_name not in self.missing_gql_objects:
                missing_obj = CustomObject()
                missing_obj.set_type('TsGqlUnresolvedDefinition')
                missing_obj.set_name(operation_name)
                missing_obj.set_fullname('[missing]:' + operation_name)
                if caller_file_kb:
                    missing_obj.set_parent(caller_file_kb)
                missing_obj.save()
                self.missing_gql_objects[operation_name] = missing_obj
                self.created_objects.append({'name': operation_name, 'type': 'TsGqlUnresolvedDefinition',
                                             'file_path': str(caller_file_kb)})
            else:
                missing_obj = self.missing_gql_objects[operation_name]
            create_link("useLink", request_obj, missing_obj)
        except Exception as e:
            log.warning('[GraphQL TS Client] Error creating TsGqlUnresolvedDefinition for "' +
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
            for (codegen_obj, fn_name) in self.pending_codegen_links:
                if fn_name in self.ts_functions:
                    fn_kb = self.ts_functions[fn_name]
                    try:
                        create_link("callLink", codegen_obj, fn_kb)
                    except Exception as e:
                        log.warning('[GraphQL TS Client] Failed codegen callLink for "' + fn_name + '": ' + str(e))
            self.pending_codegen_links = []

        # Bug 2 fix: resolve pending useLinks for cross-file GQL definitions.
        # Tuple format: (request_obj, operation_name, caller_file_kb, source_pattern, hook_ps, file_path)
        # Codegen hooks are never added to pending_links (no useLink created for them).
        if self.pending_links:
            still_unresolved = []
            for entry in self.pending_links:
                if len(entry) == 6:
                    request_obj, operation_name, caller_file_kb, source_pattern, hook_ps, fp = entry
                elif len(entry) == 4:
                    request_obj, operation_name, caller_file_kb, source_pattern = entry
                    hook_ps, fp = None, None
                else:
                    request_obj, operation_name, caller_file_kb = entry
                    source_pattern, hook_ps, fp = 'react_hook', None, None

                direct_obj = self._direct_resolve_gql_obj(operation_name, hook_ps, fp)
                # At on_end time all files are processed, so 'PENDING' is treated as unresolved.
                if direct_obj and direct_obj != 'PENDING':
                    try:
                        create_link("useLink", request_obj, direct_obj)
                    except Exception as link_ex:
                        log.warning('[GraphQL TS Client] Could not resolve pending useLink for "' +
                                    operation_name + '": ' + str(link_ex))
                else:
                    still_unresolved.append((request_obj, operation_name, caller_file_kb, source_pattern))
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
        self.scoped_var_map = {}
        self.global_var_map = {}
        self.gql_defs_by_file_var = {}
        self.gql_obj_by_file_var = {}
        self.imported_var_to_file = {}
        self.missing_gql_objects = {}
        self.ts_functions = {}
        self.pending_codegen_links = []
        self.source_file_counter = 0
        self.created_objects = []
        self.failed_objects = []
        
        log.info('[GraphQL TS Client] === FINISH: Complete ===')


