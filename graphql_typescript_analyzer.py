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

import re
from cast.analysers import ua, log, CustomObject, Bookmark, create_link
from cast import Event

# ─── Structured log helpers ────────────────────────────────────────────────────
# Format: [GraphQL][TS][<STAGE>][<ENTITY>][ctx=N] message
_ctx_seq = [0]


def _ctx():
    _ctx_seq[0] += 1
    return _ctx_seq[0]


def _glog(stage, entity, ctx, msg):
    log.info('[GraphQL][TS][{}][{}][ctx={}] {}'.format(stage, entity, ctx, msg))

# ─── Resolver detection constants ─────────────────────────────────────────────

# Map operation type → TS KB type name for resolver objects
_TS_RESOLVER_TYPE_MAP = {
    'Query':        'TsNodeJsResolverQuery',
    'Mutation':     'TsNodeJsResolverMutation',
    'Subscription': 'TsNodeJsResolverSubscription',
}

# Built-in GraphQL scalars and standard types — NOT custom field resolvers
_BUILTIN_GRAPHQL_NAMES = frozenset({
    'Query', 'Mutation', 'Subscription',
    'String', 'Int', 'Float', 'Boolean', 'ID',
    'Date', 'DateTime', 'JSON', 'Upload',
})

# Special resolver keys to skip
_SKIP_FIELD_NAMES = frozenset({'__resolveType', '__isTypeOf', 'subscribe'})

# Regex to extract service call from TS resolver body: ClassName.methodName(
_TS_SERVICE_CALL_RE = re.compile(r'([A-Z]\w+)\.(\w+)\s*\(')

# Regex to match a resolver section header like  Query: {  or  Mutation: {
# Captures: (1) type name, (2) everything inside the outer braces
# This is used in the two-pass approach for resolver detection.
_RESOLVER_SECTION_RE = re.compile(
    r'(?:^|\n)\s*(\w+)\s*:\s*\{',
    re.MULTILINE
)

# Regex to match individual field resolvers inside a section.
# Matches:  fieldName: (  or  fieldName: async (  or  fieldName: async function(
# or  fieldName(parent  (method shorthand)
_RESOLVER_FIELD_RE = re.compile(
    r'(?:^|[,\n])\s*(\w+)\s*(?::\s*(?:async\s+)?(?:function\s*)?[\(]|[\(])',
    re.MULTILINE
)

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
    # Create Apollo analysis results container
    apollo_analysis_results = ApolloAnalysisResults()
    apollo_analysis_results.ts_evaluation_tool = EvaluationTool()

    # Analyze the source file for Apollo patterns
    source_file.parsing_results = analyse_ts_fragment(source_file, apollo_analysis_results)

    # Create links between hooks and their GQL definitions
    apollo_analysis_results.create_links()

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

        # Scope-keyed GQL resolution: (file_path, var_name, id(parent_symbol)) -> KB object.
        # Enables correct same-file resolution via scope chain walk (nearest-scope-wins).
        # When a hook calls useQuery(Q), we walk from the hook's scope upward until we find
        # a GQL definition for "Q" — this correctly handles shadowing in nested scopes.
        self.scoped_gql_defs = {}

        # Import-aware cross-file resolution (Bug 9 fix).
        # gql_defs_by_file_var: (source_file_path, var_name) -> op_name
        #   Allows matching useQuery(QUERY) to the exact GQL def exported by a specific file.
        self.gql_defs_by_file_var = {}
        # gql_obj_by_file_var: (source_file_path, var_name) -> KB object (CustomObject)
        #   Direct KB object lookup; bypasses gql_definitions[op_name] last-writer-wins
        #   collision when the same operation name is defined in multiple source files.
        self.gql_obj_by_file_var = {}
        # imported_var_to_file: (consumer_file_path, local_name) -> (source_file_path, original_name)
        #   Populated from import statements:
        #     import { QUERY } from './queries'       → (consumer, 'QUERY') -> (source, 'QUERY')
        #     import { QUERY as Q } from './queries'  → (consumer, 'Q')     -> (source, 'QUERY')
        #   Storing original_name fixes alias resolution: gql_obj_by_file_var is keyed by
        #   the variable name in the source file, not the consumer's local alias.
        self.imported_var_to_file = {}

        # Map function_name -> KB object, populated from every processed TS file.
        # Used to create callLink from codegen hook objects to the TS wrapper function.
        self.ts_functions = {}

        # Map "ClassName.methodName" -> KB object, for resolver→service callLink resolution.
        self.service_methods = {}

        # Codegen hooks whose TS wrapper function was not yet seen when the hook was created.
        # Each entry: (codegen_obj, function_name)
        self.pending_codegen_links = []

        # Resolver→service callLinks deferred when service file not yet processed.
        # Each entry: (resolver_kb_obj, service_class, service_method)
        self.pending_service_links = []

        # Set of (file_path, var_name) tuples for GQL defs that are exported.
        # Used as a guard in import-aware cross-file resolution: non-exported defs
        # must not be matched to hooks in other files.
        self.exported_gql_fv_keys = set()

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
                        if fn_name:
                            fn_kb = sym.get_kb_object() if hasattr(sym, 'get_kb_object') else None
                            if fn_kb:
                                if fn_name not in self.ts_functions:
                                    self.ts_functions[fn_name] = fn_kb
                                # Also store "ClassName.methodName" for resolver→service linking.
                                if sym_type == 'Method':
                                    try:
                                        parent_kb = fn_kb.get_parent()
                                        if parent_kb:
                                            parent_name = parent_kb.get_name()
                                            if parent_name:
                                                qualified = parent_name + '.' + fn_name
                                                if qualified not in self.service_methods:
                                                    self.service_methods[qualified] = fn_kb
                                    except Exception:
                                        pass
            except Exception as sym_ex:
                log.warning('[GraphQL][TS] Error collecting function symbols: ' + str(sym_ex))

            # STEP 4: LEVEL 1 - Save GQL definitions to KB
            for gql_def in gql_defs:
                try:
                    self._create_gql_definition(gql_def, source_file)
                except Exception as save_ex:
                    log.warning('[GraphQL][TS] Error saving GQL definition: ' + str(save_ex))

            # STEP 5: LEVEL 2 - Save Apollo hooks to KB
            for hook in hooks:
                try:
                    self._create_hook_object(hook, source_file, apollo_analysis_results)
                except Exception as save_ex:
                    log.warning('[GraphQL][TS] Error saving Apollo hook: ' + str(save_ex))

            # STEP 6: Detect Apollo Server resolver maps and create resolver KB objects
            try:
                self._extract_ts_resolvers(source_file)
            except Exception as resolver_ex:
                log.warning('[GraphQL][TS] Error extracting resolvers: ' + str(resolver_ex))

        except Exception as e:
            log.warning('[GraphQL][TS] Error processing file: ' + str(e))
    
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
                        # original_name is always the element name in the source file.
                        # e.g. import { GET_USERS as MY_QUERY } → local='MY_QUERY', original='GET_USERS'
                        # e.g. import { GET_USERS }             → local='GET_USERS', original='GET_USERS'
                        local_name = None
                        original_name = None
                        try:
                            original_name = elem.get_element_name()
                            local_name = elem.get_alias_name() or original_name
                        except Exception as e:
                            log.warning('[GraphQL][TS] import element name lookup failed: ' + str(e))
                        if local_name and original_name:
                            key = (consumer_path, local_name)
                            if key not in self.imported_var_to_file:
                                self.imported_var_to_file[key] = (source_path, original_name)
                except Exception:
                    pass
        except Exception as ex:
            log.warning('[GraphQL][TS] _build_import_map_for_file failed: ' + str(ex))

    def _resolve_gql_for_hook(self, variable_name, hook_ps, fp):
        """
        Resolve a hook's variable reference to the GQL definition KB object.

        Strategy — scope chain walk, nearest-scope-wins:
          1. Same-file: walk from the hook's scope upward through parent scopes.
             First match wins (lexical scoping: inner scope shadows outer).
          1.5. Same-file flat fallback: id()-based walk always fails with CAST Boost.Python
             wrappers (each call creates a new wrapper object). String-keyed (fp, var_name)
             lookup in gql_obj_by_file_var avoids the id() problem entirely.
          2. Import-aware cross-file: the consumer file imports `variable_name`
             from a known source file → look up that source file's GQL def.
             Guard: the source def must be exported (non-exported defs are
             file-private and must not be linked cross-file).
             Returns 'PENDING' if source known but def not yet processed.

        Returns:
          - CustomObject: the resolved KB object
          - 'PENDING': import source known but def not yet processed
          - None: unresolvable
        """
        # 1. Same-file scope chain walk
        if fp and hook_ps is not None:
            try:
                visited = set()
                scope = hook_ps
                _diag_steps = []
                while scope is not None:
                    sid = id(scope)
                    if sid in visited:
                        _diag_steps.append('CYCLE at id={}'.format(sid))
                        break
                    visited.add(sid)
                    key = (fp, variable_name, sid)
                    try:
                        scope_name = scope.get_name() if hasattr(scope, 'get_name') else '?'
                    except Exception:
                        scope_name = '?'
                    _diag_steps.append('scope_type={} scope_name={} scope_id={} key_match={}'.format(
                        type(scope).__name__, scope_name, sid, key in self.scoped_gql_defs))
                    if key in self.scoped_gql_defs:
                        method = 'same_scope' if scope is hook_ps else 'scope_chain'
                        obj = self.scoped_gql_defs[key]
                        try:
                            obj_name = obj.get_name() if hasattr(obj, 'get_name') else '?'
                        except Exception:
                            obj_name = '?'
                        _glog('RESOLVE', 'Hook', _ctx(),
                              '{} → {} via {}'.format(variable_name, obj_name, method))
                        return obj
                    try:
                        scope = getattr(scope, 'get_parent_symbol', lambda: None)()
                    except Exception as e:
                        log.warning('[GraphQL][TS] _resolve_gql_for_hook: get_parent_symbol failed '
                                    'for var={} scope_type={}: {}'.format(
                                        variable_name, type(scope).__name__, str(e)))
                        break
                _glog('DIAG', 'ScopeWalk', _ctx(),
                      'MISS var={} hook_ps_type={} hook_ps_id={} steps=[{}]'.format(
                          variable_name,
                          type(hook_ps).__name__ if hook_ps else 'None',
                          id(hook_ps) if hook_ps else 'None',
                          ' | '.join(_diag_steps)))
            except Exception as e:
                log.warning('[GraphQL][TS] _resolve_gql_for_hook: scope walk crashed '
                            'for var={}: {}'.format(variable_name, str(e)))

        # 1.5. Same-file flat fallback.
        # The scope chain walk above uses id() to compare CAST Boost.Python wrapper objects.
        # Each call to get_all_symbols() / get_parent_symbol() creates a NEW Python wrapper
        # for the same underlying C++ object, so id() comparisons always fail (849 MISSes
        # observed in production logs). Fall back to a string-keyed lookup: (file_path, var_name).
        # No export guard — same-file access is always valid regardless of export status.
        if fp:
            try:
                obj = self.gql_obj_by_file_var.get((fp, variable_name))
                if obj is not None:
                    try:
                        obj_name = obj.get_name() if hasattr(obj, 'get_name') else '?'
                    except Exception:
                        obj_name = '?'
                    _glog('RESOLVE', 'Hook', _ctx(),
                          '{} → {} via same-file flat fallback'.format(variable_name, obj_name))
                    return obj
                _glog('DIAG', 'FlatFallback', _ctx(),
                      'MISS var={} not in gql_obj_by_file_var for fp={}'.format(variable_name, fp))
            except Exception as e:
                log.warning('[GraphQL][TS] _resolve_gql_for_hook: flat fallback crashed '
                            'for var={} fp={}: {}'.format(variable_name, fp, str(e)))

        # 2. Import-aware cross-file lookup
        if fp:
            try:
                import_entry = self.imported_var_to_file.get((fp, variable_name))
                if import_entry is not None:
                    source_path, original_name = import_entry
                    obj = self.gql_obj_by_file_var.get((source_path, original_name))
                    if obj is not None:
                        fv_key = (source_path, original_name)
                        if fv_key not in self.exported_gql_fv_keys:
                            _glog('RESOLVE', 'Hook', _ctx(),
                                  '{} → BLOCKED (not exported, file={})'.format(
                                      variable_name, source_path))
                            return None
                        try:
                            obj_name = obj.get_name() if hasattr(obj, 'get_name') else '?'
                        except Exception:
                            obj_name = '?'
                        _glog('RESOLVE', 'Hook', _ctx(),
                              '{} → {} via import from {} (original={})'.format(
                                  variable_name, obj_name, source_path, original_name))
                        return obj
                    _glog('DIAG', 'ImportAware', _ctx(),
                          'PENDING var={} source_path={} original={} (def not yet processed)'.format(
                              variable_name, source_path, original_name))
                    return 'PENDING'
                _glog('DIAG', 'ImportAware', _ctx(),
                      'MISS var={} not in imported_var_to_file for fp={}'.format(variable_name, fp))
            except Exception as e:
                log.warning('[GraphQL][TS] _resolve_gql_for_hook: import-aware lookup crashed '
                            'for var={} fp={}: {}'.format(variable_name, fp, str(e)))

        return None

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
            # Step 1: Determine object type based on operation type
            op_type = gql_def.operation_type
            if op_type == 'query':
                object_type = 'TsGqlQuery'
            elif op_type == 'mutation':
                object_type = 'TsGqlMutation'
            elif op_type == 'subscription':
                object_type = 'TsGqlSubscription'
            else:
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
            parent_kb = source_file.get_kb_object()
            if parent_kb:
                client_obj.set_parent(parent_kb)
            
            # Step 5: Save object to KB (MUST be done before save_property)
            client_obj.save()
            
            # Step 6: Save properties (AFTER save())
            client_obj.save_property('GraphQL_Client_Definition.operationName', gql_def.operation_name or '')
            client_obj.save_property('GraphQL_Client_Definition.rawQueryText', gql_def.raw_query_text or '')
            client_obj.save_property('GraphQL_Client_Definition.variables', gql_def.variables or '')
            client_obj.save_property('GraphQL_Client_Definition.fieldsSelected', gql_def.fields_selected or '')
            client_obj.save_property('GraphQL_Client_Definition.exported', 'true' if gql_def.exported else 'false')
            
            # Step 7: Create bookmark for source navigation
            try:
                if gql_def.raw_bookmark:
                    bookmark = gql_def.raw_bookmark.get_bookmark()
                    if bookmark:
                        client_obj.save_position(bookmark)
            except Exception:
                pass
            
            # Step 8: Store in caches for LEVEL 2 linking.
            _c = _ctx()
            self.gql_definitions[kb_name] = client_obj

            # Scope-keyed map: stores KB object directly for same-file scope chain walk.
            # First-seen wins per (file, var, scope) — prevents redeclaration collisions.
            ps = getattr(gql_def, 'parent_symbol', None)
            scoped_key = (file_path, variable_name, id(ps) if ps is not None else None)
            _glog('DIAG', 'ScopedKey', _c,
                  'STORE var={} ps_type={} ps_name={} ps_id={} key={}'.format(
                      variable_name,
                      type(ps).__name__ if ps else 'None',
                      ps.get_name() if ps and hasattr(ps, 'get_name') else '?',
                      id(ps) if ps else 'None',
                      scoped_key))
            if scoped_key not in self.scoped_gql_defs:
                self.scoped_gql_defs[scoped_key] = client_obj

            # File+var map for import-aware cross-file resolution.
            fv_key = (file_path, variable_name)
            if fv_key not in self.gql_defs_by_file_var:
                self.gql_defs_by_file_var[fv_key] = kb_name
            if fv_key not in self.gql_obj_by_file_var:
                self.gql_obj_by_file_var[fv_key] = client_obj

            # Track exported defs for cross-file resolution guard.
            if gql_def.exported:
                self.exported_gql_fv_keys.add(fv_key)
            self.created_objects.append({'name': kb_name, 'type': object_type, 'file_path': file_path})

            _glog('RESULT', 'Object', _c, '{} "{}" created'.format(object_type, kb_name))

        except Exception as e:
            log.warning('[GraphQL][TS] _create_gql_definition failed for "{}": {}'.format(_track_name, str(e)))
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
            _c = _ctx()
            _glog('RESULT', 'Object', _c, '{} "{}" created'.format(object_type, unique_request_name))

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
                            log.warning('[GraphQL][TS] callLink failed for "{}": {}'.format(unique_request_name, str(link_ex)))
            except Exception as e:
                log.warning('[GraphQL][TS] bookmark/callLink failed for "{}": {}'.format(unique_request_name, str(e)))

            # Step 9: Create useLink (request -> GQL definition).
            # Codegen hooks do NOT get a useLink here — their chain is:
            #   codegen call site → CALL → codegen wrapper function → CALL → standard hook → useLink → GQL def
            # The useLink is created by the standard hook object inside the wrapper, not here.

            if source_pattern != 'codegen_hook':
                hook_ps = getattr(hook, 'parent_symbol', None)
                fp = str(source_file.get_path())
                resolved_obj = self._resolve_gql_for_hook(operation_name, hook_ps, fp)
                if resolved_obj == 'PENDING' or resolved_obj is None:
                    self.pending_links.append(
                        (request_obj, operation_name, source_file.get_kb_object(), source_pattern, hook_ps, fp))
                    if resolved_obj is None:
                        _glog('RESOLVE', 'Hook', _c, '{} → UNRESOLVED (pending)'.format(operation_name))
                else:
                    try:
                        create_link("useLink", request_obj, resolved_obj)
                        _glog('RESULT', 'Link', _c, 'useLink {} → {}'.format(unique_request_name, operation_name))
                    except Exception as link_ex:
                        log.warning('[GraphQL][TS] useLink failed for "{}": {}'.format(unique_request_name, str(link_ex)))
            else:
                # Codegen hook: create callLink to the TS wrapper function so the chain
                # codegen_obj → CALL → wrapper_function → CALL → useLazyQuery → USE → GqlDef is visible.
                if operation_name in self.ts_functions:
                    fn_kb = self.ts_functions[operation_name]
                    try:
                        create_link("callLink", request_obj, fn_kb)
                    except Exception as link_ex:
                        log.warning('[GraphQL][TS] codegen callLink failed for "{}": {}'.format(operation_name, str(link_ex)))
                else:
                    self.pending_codegen_links.append((request_obj, operation_name))
            self.created_objects.append({'name': unique_request_name, 'type': object_type, 'file_path': file_path})

        except Exception as e:
            log.warning('[GraphQL][TS] _create_hook_object failed for "{}": {}'.format(_track_name, str(e)))
            self.failed_objects.append({'name': _track_name, 'type': _track_type, 'file_path': _track_file})
    
    # ──────────────────────────────────── Resolver detection (Phase 3) ────────

    def _extract_ts_resolvers(self, source_file):
        """
        Detect Apollo Server resolver maps in a TypeScript file.

        Uses regex on raw source text to find resolver sections:
          { Query: { getUsers: ... }, Mutation: { createUser: ... }, User: { posts: ... } }

        Creates TsNodeJsResolver{Query,Mutation,Subscription,Custom} KB objects.
        """
        try:
            file_path = str(source_file.get_path())
            try:
                with open(file_path, 'r', encoding='utf-8', errors='replace') as f:
                    source_text = f.read()
            except Exception:
                return

            if not source_text:
                return

            # Quick guard: file must contain at least one standard resolver section keyword
            has_query = 'Query' in source_text
            has_mutation = 'Mutation' in source_text
            has_subscription = 'Subscription' in source_text
            if not (has_query or has_mutation or has_subscription):
                return

            # Find all resolver section headers and extract their fields.
            # Strategy: for each  TypeName: {  match, find the balanced closing brace,
            # then extract field names from the content between the braces.
            found = []  # list of (op_type, field_name, line_number)
            has_standard_type = False

            for section_match in _RESOLVER_SECTION_RE.finditer(source_text):
                type_name = section_match.group(1)
                brace_start = section_match.end() - 1  # position of the '{'

                # Find balanced closing brace
                brace_content = self._extract_brace_content(source_text, brace_start)
                if brace_content is None:
                    continue

                is_standard = type_name in ('Query', 'Mutation', 'Subscription')
                if is_standard:
                    has_standard_type = True

                # Extract field names from the section content
                for field_match in _RESOLVER_FIELD_RE.finditer(brace_content):
                    field_name = field_match.group(1)
                    if (field_name in _SKIP_FIELD_NAMES
                            or field_name in ('async', 'function', 'return', 'const',
                                              'let', 'var', 'if', 'else', 'try', 'catch')):
                        continue

                    # Compute line number for the field
                    abs_pos = brace_start + 1 + field_match.start()
                    line_num = source_text[:abs_pos].count('\n') + 1

                    # Extract the field's function body for service call extraction
                    field_body_start = brace_start + 1 + field_match.end()
                    field_body = source_text[field_body_start:field_body_start + 500]

                    if is_standard:
                        found.append((type_name, field_name, line_num, field_body))
                    else:
                        # Store as potential custom resolver; will only create if
                        # file also has at least one standard type
                        found.append((type_name, field_name, line_num, field_body))

            if not found or not has_standard_type:
                return

            # Dedup and create KB objects
            parent_kb = source_file.get_kb_object()
            if not parent_kb:
                return

            seen = set()
            for op_type, field_name, line_num, field_body in found:
                pair = (op_type, field_name)
                if pair in seen:
                    continue
                # Custom types only created if file has standard types (guard against false positives)
                if op_type not in ('Query', 'Mutation', 'Subscription'):
                    if op_type in _BUILTIN_GRAPHQL_NAMES:
                        continue
                    if not op_type[0].isupper():
                        continue
                seen.add(pair)
                self._create_ts_resolver(op_type, field_name, line_num,
                                         field_body, parent_kb, file_path, source_file)

        except Exception as e:
            log.warning('[GraphQL][TS] _extract_ts_resolvers failed: ' + str(e))

    def _extract_brace_content(self, text, brace_start):
        """
        Extract content between balanced braces starting at brace_start.
        Returns the content string (excluding outer braces), or None if unbalanced.
        """
        depth = 0
        i = brace_start
        while i < len(text):
            ch = text[i]
            if ch == '{':
                depth += 1
            elif ch == '}':
                depth -= 1
                if depth == 0:
                    return text[brace_start + 1:i]
            elif ch in ('"', "'", '`'):
                # Skip string literals to avoid false brace matches
                quote = ch
                i += 1
                while i < len(text) and text[i] != quote:
                    if text[i] == '\\':
                        i += 1  # skip escaped char
                    i += 1
            i += 1
        return None

    def _extract_ts_service_call(self, field_body):
        """
        Extract (serviceClass, serviceMethod) from a TS resolver function body.

        TS resolvers typically call static methods: ClassName.methodName(...)
        Returns (serviceClass, serviceMethod) or (None, None).
        """
        if not field_body:
            return (None, None)
        m = _TS_SERVICE_CALL_RE.search(field_body)
        if m:
            cls = m.group(1)
            method = m.group(2)
            # Filter out common false positives (Promise.resolve, console.log, etc.)
            if cls in ('Promise', 'console', 'Object', 'Array', 'JSON', 'Math',
                       'Error', 'Date', 'String', 'Number', 'Boolean', 'RegExp'):
                return (None, None)
            return (cls, method)
        return (None, None)

    def _create_ts_resolver(self, op_type, field_name, line_num, field_body,
                            parent_kb, file_path, source_file=None):
        """Create a TsNodeJsResolver* KB object for one TS resolver function."""
        try:
            resolver_type = _TS_RESOLVER_TYPE_MAP.get(op_type, 'TsNodeJsResolverCustom')
            fullname = file_path + ':' + str(line_num)

            obj = CustomObject()
            obj.set_name(field_name)
            obj.set_type(resolver_type)
            obj.set_fullname(fullname)
            obj.set_parent(parent_kb)
            obj.save()

            try:
                if source_file is not None and line_num:
                    try:
                        file_obj = source_file.get_file()
                    except Exception:
                        file_obj = source_file
                    obj.save_position(Bookmark(file_obj, line_num, 1, line_num, 1))
            except Exception as bm_e:
                log.info('[GraphQL][TS] Resolver bookmark failed for "'
                         + op_type + '.' + field_name + '": ' + str(bm_e))

            obj.save_property('GraphQL_NodeJs_Resolver.operationType', op_type)
            obj.save_property('GraphQL_NodeJs_Resolver.fieldName', field_name)

            # Extract service call info
            service_class, service_method = self._extract_ts_service_call(field_body)
            if service_class:
                obj.save_property('GraphQL_NodeJs_Resolver.serviceClass', service_class)
            if service_method:
                obj.save_property('GraphQL_NodeJs_Resolver.serviceMethod', service_method)

            # Create callLink: resolver → service method KB object
            if service_class and service_method:
                qualified = service_class + '.' + service_method
                svc_kb = self.service_methods.get(qualified) or self.ts_functions.get(service_method)
                if svc_kb:
                    try:
                        create_link("callLink", obj, svc_kb)
                        _glog('RESULT', 'ServiceLink', _ctx(),
                              'callLink {} → {}'.format(field_name, qualified))
                    except Exception as link_ex:
                        log.warning('[GraphQL][TS] service callLink failed for "{}": {}'.format(
                            qualified, str(link_ex)))
                else:
                    # Service file not yet processed — defer to on_end
                    self.pending_service_links.append((obj, service_class, service_method))

            self.created_objects.append({
                'name': field_name, 'type': resolver_type, 'file_path': file_path})

            _glog('RESULT', 'Resolver', _ctx(),
                  '{} "{}" ({}.{})'.format(resolver_type, field_name, op_type, field_name)
                  + (' → ' + str(service_class) + '.' + str(service_method)
                     if service_class else ''))

        except Exception as e:
            log.warning('[GraphQL][TS] _create_ts_resolver failed for "'
                        + op_type + '.' + field_name + '": ' + str(e))
            self.failed_objects.append({
                'name': field_name, 'type': 'TsNodeJsResolver*', 'file_path': file_path})

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
            _glog('RESULT', 'Object', _ctx(), 'TsGqlUnresolvedDefinition "{}" created'.format(operation_name))
        except Exception as e:
            log.warning('[GraphQL][TS] TsGqlUnresolvedDefinition failed for "{}": {}'.format(operation_name, str(e)))

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
                        log.warning('[GraphQL][TS] codegen callLink failed for "{}": {}'.format(fn_name, str(e)))
            self.pending_codegen_links = []

        # Resolve pending resolver→service callLinks.
        if self.pending_service_links:
            for (resolver_obj, svc_class, svc_method) in self.pending_service_links:
                qualified = svc_class + '.' + svc_method
                svc_kb = self.service_methods.get(qualified) or self.ts_functions.get(svc_method)
                if svc_kb:
                    try:
                        create_link("callLink", resolver_obj, svc_kb)
                        _glog('RESULT', 'ServiceLink', _ctx(),
                              'pending callLink resolved → {}'.format(qualified))
                    except Exception as e:
                        log.warning('[GraphQL][TS] pending service callLink failed for "{}": {}'.format(
                            qualified, str(e)))
                else:
                    log.warning('[GraphQL][TS] service method not found in KB: {}'.format(qualified))
            self.pending_service_links = []

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

                resolved_obj = self._resolve_gql_for_hook(operation_name, hook_ps, fp)
                # At on_end time all files are processed, so 'PENDING' is treated as unresolved.
                if resolved_obj and resolved_obj != 'PENDING':
                    try:
                        create_link("useLink", request_obj, resolved_obj)
                        _glog('RESULT', 'Link', _ctx(), 'pending useLink resolved → {}'.format(operation_name))
                    except Exception as link_ex:
                        log.warning('[GraphQL][TS] pending useLink failed for "{}": {}'.format(
                            operation_name, str(link_ex)))
                else:
                    still_unresolved.append((request_obj, operation_name, caller_file_kb, source_pattern))
            for (request_obj, operation_name, caller_file_kb, _) in still_unresolved:
                self._create_missing_gql_definition(request_obj, operation_name, caller_file_kb)
            self.pending_links = []  # free memory — on_end is the real finish point

        # ── End-of-analysis summary ────────────────────────────────────────────
        type_counts = {}
        for obj in self.created_objects:
            type_counts[obj['type']] = type_counts.get(obj['type'], 0) + 1

        log.info('[GraphQL][TS][SUMMARY] files={} created={} failed={}'.format(
            self.source_file_counter, len(self.created_objects), len(self.failed_objects)))
        for obj_type, count in sorted(type_counts.items()):
            log.info('[GraphQL][TS][SUMMARY]   {}: {}'.format(obj_type, count))
        if self.failed_objects:
            for obj in self.failed_objects:
                log.warning('[GraphQL][TS][SUMMARY] FAILED: name="{}" type={}'.format(obj['name'], obj['type']))

        self.gql_definitions = {}
        self.scoped_gql_defs = {}
        self.gql_defs_by_file_var = {}
        self.gql_obj_by_file_var = {}
        self.exported_gql_fv_keys = set()
        self.imported_var_to_file = {}
        self.missing_gql_objects = {}
        self.ts_functions = {}
        self.service_methods = {}
        self.pending_codegen_links = []
        self.pending_service_links = []
        self.source_file_counter = 0
        self.created_objects = []
        self.failed_objects = []


