# -*- coding: utf-8 -*-
"""
GraphQL JavaScript Analyzer — mirrors graphql_typescript_analyzer.py architecture.

Patterns supported:
  P1  useQuery / useMutation / useLazyQuery / useSubscription(CONST)
  P2  const X = gql`...`  (outline gql definition)
  P9  client.query({ query: VAR })  / client.mutate({ mutation: VAR })
  P11 codegen hooks: useGetXQuery(), useCreateXMutation(), etc.
  P15 this.apollo.query({ query: VAR })
  P16 this.apollo.mutate({ mutation: VAR })
  P17 this.apollo.watchQuery({ query: VAR }).valueChanges

Two-phase architecture (mirrors TS):
  1. collect jsContent in start_javascript_content
  2. Phase 1 (gql defs)  — keyed by operation_name (Bug 8 equivalent fix)
  3. Phase 2 (hooks)     — resolve via var_name_to_op_name map
  4. Phase 3 (links)     — resolve pending_links for cross-file defs (Bug 2 fix)

Key differences from TS analyzer:
  - jsContent (HTML5 JsContent) instead of source_file (TypeScript SourceFile)
  - FunctionCall.get_function_call_parts() instead of TS AST walk
  - gql detection via FunctionCall.get_name() in gql_aliases
  - parent chain walk via get_parent() to find var name for gql defs
  - hook args via FunctionCallPart.get_parameters()
  - text extraction via AstString.evaluate()
"""

import re
from cast.analysers import ua, log, CustomObject, Bookmark, create_link
from cast import Event

# ─── Structured log helpers ────────────────────────────────────────────────────
# Format: [GraphQL][JS][<STAGE>][<ENTITY>][ctx=N] message
_ctx_seq = [0]


def _ctx():
    _ctx_seq[0] += 1
    return _ctx_seq[0]


def _glog(stage, entity, ctx, msg):
    log.info('[GraphQL][JS][{}][{}][ctx={}] {}'.format(stage, entity, ctx, msg))


# ─────────────────────────────────────────────────── constants ────────────────

# React hooks: exact function name → KB type
_APOLLO_HOOKS = {
    'useQuery':        'JsGraphQLApolloHookQuery',
    'useLazyQuery':    'JsGraphQLApolloHookLazyQuery',
    'useMutation':     'JsGraphQLApolloHookMutation',
    'useSubscription': 'JsGraphQLApolloHookSubscription',
}

# Angular apollo service methods → (KB type, display prefix)
_ANGULAR_METHODS = {
    'query':      ('JsGraphQLApolloAngularQuery',      'apollo.query'),
    'mutate':     ('JsGraphQLApolloAngularMutation',   'apollo.mutate'),
    'watchQuery': ('JsGraphQLApolloAngularWatchQuery', 'apollo.watchQuery'),
}

# Direct Apollo Client methods → (KB type, display prefix)
_CLIENT_METHODS = {
    'query':     ('JsGraphQLApolloClientQuery',        'client.query'),
    'mutate':    ('JsGraphQLApolloClientMutation',     'client.mutate'),
    'subscribe': ('JsGraphQLApolloClientSubscription', 'client.subscribe'),
}

# GraphQL operation keyword → GQL definition KB type
_OP_TYPE_MAP = {
    'query':        'JsGqlQuery',
    'mutation':     'JsGqlMutation',
    'subscription': 'JsGqlSubscription',
}

# Codegen hook pattern: useGetXQuery, useCreateXMutation, etc.
_CODEGEN_PATTERN = re.compile(
    r'^use[A-Z][A-Za-z0-9_]*(Query|LazyQuery|Mutation|Subscription)$')
_CODEGEN_SUFFIX_MAP = {
    'Query':        'JsGraphQLApolloCodegenQuery',
    'LazyQuery':    'JsGraphQLApolloCodegenQuery',       # no dedicated LazyQuery codegen type in metamodel
    'Mutation':     'JsGraphQLApolloCodegenMutation',
    'Subscription': 'JsGraphQLApolloCodegenSubscription',
}

# Import names that signal a file uses Apollo Client (used to filter jsContent)
_FILTER_NAMES = (
    set(_APOLLO_HOOKS.keys())
    | {'gql', 'Apollo', 'ApolloClient', 'InMemoryCache', 'ApolloProvider',
       'useApolloClient'}
)

# Import names that mark a file as Angular (uses Apollo service from apollo-angular)
# Used to distinguish this.apollo.query/mutate/watchQuery from client.query/mutate
_ANGULAR_IMPORT_NAMES = frozenset({'Apollo'})

# npm packages that provide the `gql` template tag (named OR default export).
# Used to detect aliased imports: import gqlTag from 'graphql-tag'
#                                 import { gql as gqlHelper } from '@apollo/client'
GQL_PACKAGES = frozenset([
    'graphql-tag', '@apollo/client', '@apollo/client/core',
    'apollo-boost', 'apollo-client', 'apollo-cache-inmemory',
    'apollo-link', 'react-apollo', '@apollo/react-hooks',
    '@apollo/react-hoc', '@apollo/react-components',
])

# Source pattern tags (mirrors TS _HOOK_TYPE_MAP source_pattern keys)
_PAT_REACT   = 'react_hook'
_PAT_ANGULAR = 'angular_method'
_PAT_CLIENT  = 'client_method'
_PAT_CODEGEN = 'codegen_hook'


# ─────────────────────────────────────────────────── AST helpers ──────────────

def _part_name(part):
    """Return identifier name of a FunctionCallPart node."""
    try:
        ident = part.get_identifier()
        return ident.get_name() if ident else None
    except Exception:
        return None


def _part_params(part):
    """Return parameters of a FunctionCallPart as a list, or []."""
    try:
        return list(part.get_parameters())
    except Exception:
        return []


def _node_children(node):
    """Return children of any AST node as a list, or []."""
    try:
        return list(node.get_children())
    except Exception:
        return []


def _walk(node, callback):
    """Depth-first recursive walk; callback receives every descendant."""
    for child in _node_children(node):
        callback(child)
        _walk(child, callback)


# ─────────────────────────────────────────────────── main class ───────────────

class GraphQLJavascriptAnalyzer(ua.Extension):

    def __init__(self):
        # LEVEL 1 cache: operation_name → CustomObject (Bug 8 fix — keyed by op, not var)
        self.gql_definitions = {}

        # variable_name → operation_name; first-seen wins on collision (Bug 8 fix)
        self.var_name_to_op_name = {}

        # Scope-keyed GQL resolution: (file_path, var_name, id(enclosing_kb_parent)) -> KB object.
        # Enables correct same-file resolution via scope chain walk (nearest-scope-wins).
        self.scoped_gql_defs = {}

        # (hook_obj, var_name, caller_kb, source_pattern, file_path) awaiting Phase 3
        self.pending_links = []

        # operation_name → JsGqlUnresolvedDefinition; deduplicated across hooks
        self.missing_gql_objects = {}

        # Import-aware cross-file resolution (mirrors TS Bug 9 fix).
        # gql_obj_by_file_var: (source_file_path, var_name) -> KB object (CustomObject)
        self.gql_obj_by_file_var = {}
        # imported_var_to_file: (consumer_file_path, local_name) -> (source_file_path, original_name)
        #   import { GET_USERS } from './queries'       → (consumer, 'GET_USERS') -> (source, 'GET_USERS')
        #   import { GET_USERS as MY_Q } from './queries' → (consumer, 'MY_Q') -> (source, 'GET_USERS')
        self.imported_var_to_file = {}

        # Set of (file_path, var_name) tuples for GQL defs that are exported.
        # Used as a guard in import-aware cross-file resolution: non-exported defs
        # must not be matched to hooks in other files.
        self.exported_gql_fv_keys = set()

        # jsContent objects collected in start_javascript_content
        self._js_contents = []

        # subset of _js_contents: files that import Angular Apollo service
        self._angular_js_contents = set()

        # stats
        self._created = 0
        self._failed  = 0

    # ──────────────────────────────── event handlers ───────────────────────────

    @Event('com.castsoftware.html5', 'start_javascript_content')
    def _on_start(self, jsContent):
        """Collect jsContent objects that import Apollo Client or gql.
        Also detects Angular files (import Apollo from apollo-angular) for
        correct routing of query/mutate/watchQuery to Angular KB types."""
        has_filter_import = False
        is_angular = False
        try:
            for imp in jsContent.get_imports():
                try:
                    what = imp.get_what_name()
                    if what in _FILTER_NAMES:
                        has_filter_import = True
                    if what in _ANGULAR_IMPORT_NAMES:
                        is_angular = True
                    # Detect aliased gql imports: import gqlTag from 'graphql-tag'
                    # get_what_name() returns the local name (e.g. 'gqlTag'), not 'gql'.
                    # Use get_from_token().name to read the package string directly,
                    # matching how CAST's own use_framework() identifies packages.
                    if not has_filter_import:
                        try:
                            from_token = imp.get_from_token()
                            if from_token:
                                from_text = (getattr(from_token, 'name', None)
                                             or getattr(from_token, 'text', None)
                                             or '')
                                from_text = from_text.strip("'\" ")
                                if from_text in GQL_PACKAGES:
                                    has_filter_import = True
                        except Exception:
                            pass
                except Exception:
                    pass
        except Exception as e:
            log.warning('[GraphQL][JS] start_javascript_content error: ' + str(e))
        if has_filter_import:
            self._js_contents.append(jsContent)
            if is_angular:
                self._angular_js_contents.add(jsContent)

    @Event('com.castsoftware.html5', 'end_javascript_contents')
    def _on_end(self):
        """Two-phase extraction then pending link resolution."""
        # Phase 1 — gql definitions (must run first across ALL files)
        for jsc in self._js_contents:
            try:
                self._extract_gql_definitions(jsc)
            except Exception as e:
                log.warning('[GraphQL][JS] Phase 1 error in {}: {}'.format(str(jsc.get_file()), str(e)))

        # Phase 1b — build import maps for all files (needed by Phase 2 import-aware resolution)
        for jsc in self._js_contents:
            try:
                self._build_import_map_for_file(jsc)
            except Exception as e:
                log.warning('[GraphQL][JS] Phase 1b import map error: ' + str(e))

        # Phase 2 — hooks + client methods + Angular
        for jsc in self._js_contents:
            try:
                self._extract_apollo_hooks(jsc)
            except Exception as e:
                log.warning('[GraphQL][JS] Phase 2 error in {}: {}'.format(str(jsc.get_file()), str(e)))

        # Phase 3 — resolve pending useLinks (Bug 2 fix)
        self._resolve_pending_links()

        log.info('[GraphQL][JS][SUMMARY] files={} created={} failed={}'.format(
            len(self._js_contents), self._created, self._failed))

        # Reset all state (mirrors TS on_end_html5_and_typescript reset).
        # Guards against stale data if CAST re-uses the same extension instance.
        self.gql_definitions = {}
        self.var_name_to_op_name = {}
        self.scoped_gql_defs = {}
        self.pending_links = []
        self.missing_gql_objects = {}
        self.gql_obj_by_file_var = {}
        self.imported_var_to_file = {}
        self.exported_gql_fv_keys = set()
        self._js_contents = []
        self._angular_js_contents = set()
        self._created = 0
        self._failed = 0

    # ──────────────────────────────── gql alias detection ─────────────────────

    def _gql_aliases(self, jsContent):
        """Return set of local names bound to the gql template tag in this file.

        Handles three import forms:
          1. import { gql } from '@apollo/client'              → adds 'gql'  (already in default)
          2. import { gql as gqlHelper } from '@apollo/client' → adds 'gqlHelper'
          3. import gqlTag from 'graphql-tag'                  → adds 'gqlTag'
             (default import: get_what_name() returns local binding, not 'gql')

        For form 3, we use get_from_token().name to read the package string directly,
        matching how CAST's own use_framework() identifies packages. The local name
        (e.g. 'gqlTag') is then added to aliases so FunctionCall detection finds it.
        """
        aliases = {'gql'}
        try:
            for imp in jsContent.get_imports():
                try:
                    what = imp.get_what_name()
                    local = what
                    try:
                        alias = imp.get_alias_name()
                        if alias:
                            local = alias
                    except Exception:
                        pass
                    # Form 1 & 2: named import of 'gql' (with or without alias)
                    if what == 'gql':
                        aliases.add(local)
                        continue
                    # Form 3: default/aliased import from a known GQL package
                    # e.g. import gqlTag from 'graphql-tag'
                    # Use get_from_token().name (same as CAST's use_framework()).
                    if local and local not in ('default', 'unknown', ''):
                        try:
                            from_token = imp.get_from_token()
                            if from_token:
                                from_text = (getattr(from_token, 'name', None)
                                             or getattr(from_token, 'text', None)
                                             or '')
                                from_text = from_text.strip("'\" ")
                                if from_text in GQL_PACKAGES:
                                    aliases.add(local)
                        except Exception:
                            pass
                except Exception:
                    pass
        except Exception:
            pass
        return aliases

    # ──────────────────────────────── import map ─────────────────────────────

    def _build_import_map_for_file(self, jsContent):
        """
        Parse import statements of jsContent and populate self.imported_var_to_file.

        For each import  import { FOO } from './bar'  (or  import { FOO as F } from …)
        we record:  (consumer_file_path, local_name) -> (source_file_path, original_name)

        JS API: each named import element is a separate Import object.
          imp.get_what_name()  → original name in the source file (e.g. 'GET_USERS')
          imp.get_alias_name() → local alias if present (e.g. 'MY_Q'), else None
          imp.get_js_content() → resolved jsContent of the source file, or None

        External packages (@apollo/client, etc.) return None from get_js_content()
        and are silently skipped.
        """
        try:
            consumer_path = str(jsContent.get_file().get_path())
        except Exception:
            return
        try:
            for imp in jsContent.get_imports():
                try:
                    original_name = imp.get_what_name()
                    if not original_name:
                        continue
                    local_name = original_name
                    try:
                        alias = imp.get_alias_name()
                        if alias:
                            local_name = alias
                    except Exception:
                        pass
                    # Resolve source file
                    resolved_jsc = None
                    try:
                        resolved_jsc = imp.get_js_content()
                    except Exception:
                        pass
                    if resolved_jsc is None:
                        continue
                    try:
                        source_path = str(resolved_jsc.get_file().get_path())
                    except Exception:
                        continue
                    key = (consumer_path, local_name)
                    if key not in self.imported_var_to_file:
                        self.imported_var_to_file[key] = (source_path, original_name)
                except Exception:
                    pass
        except Exception as ex:
            log.warning('[GraphQL][JS] _build_import_map_for_file failed: ' + str(ex))

    # ────────────────────────────── Phase 1 — gql defs ────────────────────────

    def _extract_gql_definitions(self, jsContent):
        """Walk jsContent AST; register every const X = gql`...` declaration."""
        gql_aliases = self._gql_aliases(jsContent)

        def visit(node):
            try:
                # Only FunctionCall nodes are gql template-tag calls
                if not (hasattr(node, 'is_function_call') and node.is_function_call()):
                    return
                # FunctionCall.get_name() returns the last part's identifier name
                if node.get_name() not in gql_aliases:
                    return

                # Walk up to find "const VAR = gql`...`" (also detects export status)
                var_name, is_exported = self._get_var_name(node)
                if not var_name:
                    return

                # Fallback export detection: if is_in_export_statement() returned False,
                # double-check via jsContent.get_exports() which is authoritatively
                # populated by the CAST HTML5 parser from all export statements.
                if not is_exported:
                    try:
                        exports = jsContent.get_exports()
                        if exports and var_name in exports:
                            is_exported = True
                    except Exception:
                        pass

                # Extract template literal text from first part's first parameter
                parts = node.get_function_call_parts()
                if not parts:
                    return
                params = _part_params(parts[0])
                if not params:
                    return
                text = self._eval_text(params[0])
                if not text:
                    return

                op_type, op_name, variables, fields = self._parse_gql_content(text)
                if op_name is None:
                    return

                _c = _ctx()
                _glog('DETECT', 'GqlDef', _c, 'gql`` found: var={} op={} ({}) exported={}'.format(
                    var_name, op_name, op_type, is_exported))
                self._create_gql_def(
                    var_name, op_name, op_type, text, variables, fields, node, jsContent,
                    is_exported=is_exported)
            except Exception as e:
                log.warning('[GraphQL][JS] gql visitor error: ' + str(e))

        _walk(jsContent, visit)

    def _get_var_name(self, gql_node):
        """Walk up AST to find the variable name and export status in 'const VAR = gql`...`'.

        Returns (var_name, is_exported) or (None, False) if not found.
        is_exported is True when the Assignment node reports is_in_export_statement().
        """
        current = gql_node
        for _ in range(12):
            try:
                parent = current.get_parent()
                if parent is None:
                    break
                if hasattr(parent, 'is_assignment') and parent.is_assignment():
                    left = parent.get_left_operand()
                    if left and hasattr(left, 'get_name'):
                        name = left.get_name()
                        if name and name not in ('unknown', 'const', 'let', 'var'):
                            is_exported = False
                            try:
                                is_exported = bool(parent.is_in_export_statement())
                            except Exception:
                                pass
                            return name, is_exported
                current = parent
            except Exception:
                break
        return None, False

    def _eval_text(self, param):
        """Extract string from an AstString / template-literal parameter via evaluate()."""
        try:
            for ev in param.evaluate():
                text = str(ev).strip('`').strip()
                # Remove CAST metadata appended as tab-separated values
                if '\t' in text:
                    text = text.split('\t')[0].strip()
                if text:
                    return text
        except Exception:
            pass
        try:
            return param.get_name()
        except Exception:
            return None

    def _parse_gql_content(self, text):
        """
        Parse GraphQL template text → (kb_type, operation_name, variables_str, fields_str).

        Strips leading ${...} fragment-spread interpolations before matching so that
          ${FRAGMENT_FIELDS}
          query AllTransfers(...) { ... }
        is correctly parsed as operation_name='AllTransfers'.

        Returns (None, None, '', '') when no operation name is found.
        """
        if not text:
            return None, None, '', ''

        # Remove leading ${...} blocks (fragment spreads injected before the operation keyword)
        clean = re.sub(r'(\$\{[^}]+\}\s*)+', '', text, flags=re.MULTILINE)

        # Match operation keyword + PascalCase name (no { required — mirrors TS Bug 4 fix)
        m = re.search(
            r'^\s*(query|mutation|subscription)\s+([A-Z][A-Za-z0-9_]*)',
            clean, re.IGNORECASE | re.MULTILINE)
        if not m:
            return None, None, '', ''

        op_type = _OP_TYPE_MAP.get(m.group(1).lower(), 'JsGqlQuery')
        op_name = m.group(2)

        # Variables: $varName patterns in the operation signature
        variables = ', '.join(
            '$' + v for v in re.findall(r'\$([a-zA-Z_][a-zA-Z0-9_]*)', clean))

        # Fields selected: top-level field names in the operation body.
        # Pattern matches identifiers right after '{' that are followed by '(' or '{',
        # i.e. the first-level fields of the operation — NOT the leaf fields inside them.
        # Mirrors the TS analyzer's parse_graphql_content() regex.
        fields = ''
        fields_pattern = r'\{\s*([a-z][a-zA-Z0-9_]*)\s*[\(\{]'
        field_matches = re.findall(fields_pattern, clean)
        keywords = {'query', 'mutation', 'subscription', 'fragment'}
        unique_fields = []
        seen = set()
        for f in field_matches:
            if f not in keywords and f not in seen:
                unique_fields.append(f)
                seen.add(f)
        if unique_fields:
            fields = ', '.join(unique_fields)

        return op_type, op_name, variables, fields

    def _create_gql_def(self, var_name, op_name, op_type, raw_text,
                        variables, fields, ast_node, jsContent, is_exported=False):
        """Create the CAST KB object for a GQL definition and register it."""
        try:
            parent_kb = jsContent.get_kb_object()
            if parent_kb is None:
                self._failed += 1
                return

            # Build unique fullname (file:line format, same as TS analyzer — F3 fix)
            try:
                line_num = ast_node.get_begin_line() if hasattr(ast_node, 'get_begin_line') else 0
            except Exception:
                line_num = 0
            try:
                file_path_for_fn = str(jsContent.get_file().get_path())
            except Exception:
                file_path_for_fn = ''
            fullname = file_path_for_fn + ':' + str(line_num)

            obj = CustomObject()
            obj.set_name(op_name)       # named by operation_name (Bug 8 fix)
            obj.set_type(op_type)
            obj.set_fullname(fullname)
            obj.set_parent(parent_kb)

            obj.save()

            try:
                obj.save_position(ast_node.create_bookmark(jsContent.get_file()))
            except Exception:
                pass

            obj.save_property('GraphQL_Client_Definition.operationName', op_name)
            obj.save_property('GraphQL_Client_Definition.rawQueryText',  raw_text)
            if variables:
                obj.save_property('GraphQL_Client_Definition.variables',     variables)
            if fields:
                obj.save_property('GraphQL_Client_Definition.fieldsSelected', fields)
            obj.save_property('GraphQL_Client_Definition.exported', 'true' if is_exported else 'false')

            self._created += 1
            self.gql_definitions[op_name] = obj

            # Scope-keyed map: stores KB object directly for same-file scope chain walk.
            # First-seen wins per (file, var, scope) — prevents redeclaration collisions.
            try:
                file_path = str(jsContent.get_file().get_path()) if jsContent.get_file() else None
            except Exception:
                file_path = None
            if file_path:
                enclosing_sym = None
                try:
                    enclosing_sym = ast_node.get_first_kb_parent()
                except Exception:
                    pass
                scope_id = id(enclosing_sym) if enclosing_sym is not None else None
                scoped_key = (file_path, var_name, scope_id)
                if scoped_key not in self.scoped_gql_defs:
                    self.scoped_gql_defs[scoped_key] = obj
                    _glog('SCOPE', 'GqlDef', _ctx(),
                          'registered var={} op={} scope_id={}'.format(var_name, op_name, scope_id))

            # File+var map for import-aware cross-file resolution.
            if file_path:
                fv_key = (file_path, var_name)
                if fv_key not in self.gql_obj_by_file_var:
                    self.gql_obj_by_file_var[fv_key] = obj
                # Track exported defs for cross-file resolution guard.
                if is_exported:
                    self.exported_gql_fv_keys.add(fv_key)

            # First-seen wins: outer-scope variable takes priority on collision
            if var_name not in self.var_name_to_op_name:
                self.var_name_to_op_name[var_name] = op_name
            _glog('RESULT', 'Object', _ctx(), '{} "{}" created'.format(op_type, op_name))
        except Exception as e:
            log.warning('[GraphQL][JS] Failed to create GQL def "{}": {}'.format(op_name, str(e)))
            self._failed += 1

    # ────────────────────────────── Phase 2 — hooks ───────────────────────────

    def _extract_apollo_hooks(self, jsContent):
        """Walk jsContent AST; register every Apollo hook / client method call."""
        # Compute gql aliases once per file (needed for F1 inline gql detection)
        gql_aliases = self._gql_aliases(jsContent)

        # Angular files import { Apollo } from 'apollo-angular'.
        # For these files, single-part calls like query({query:VAR}) or
        # mutate({mutation:VAR}) must be routed to _ANGULAR_METHODS, not _CLIENT_METHODS.
        is_angular = jsContent in self._angular_js_contents

        def visit(node):
            try:
                if not (hasattr(node, 'is_function_call') and node.is_function_call()):
                    return

                parts = node.get_function_call_parts()
                if not parts:
                    return

                n_parts   = len(parts)
                last_name = _part_name(parts[-1])
                if last_name is None:
                    return

                if n_parts == 1:
                    # ── React hooks: useQuery(VAR) etc. ──
                    if last_name in _APOLLO_HOOKS:
                        kb_type  = _APOLLO_HOOKS[last_name]
                        var_name = self._simple_hook_arg(parts[0])
                        if not var_name:
                            # F1: inline gql — useQuery(gql`query X {...}`)
                            var_name = self._try_inline_gql(
                                parts[0], node, jsContent, gql_aliases)
                        if var_name:
                            self._create_hook(
                                last_name, kb_type, var_name, last_name,
                                _PAT_REACT, node, jsContent)

                    # ── Codegen hooks: useGetXQuery() etc. ──
                    elif _CODEGEN_PATTERN.match(last_name):
                        suffix  = _CODEGEN_PATTERN.match(last_name).group(1)
                        kb_type = _CODEGEN_SUFFIX_MAP[suffix]
                        _glog('DETECT', 'Hook', _ctx(), 'codegen {}'.format(last_name))
                        self._create_hook(
                            last_name, kb_type, last_name, last_name,
                            _PAT_CODEGEN, node, jsContent)

                    # ── Angular method (single-part, angular file) ──
                    # Must precede _CLIENT_METHODS: 'query' and 'mutate' appear in both
                    # dicts; for Angular files the Apollo service is used, not ApolloClient.
                    elif is_angular and last_name in _ANGULAR_METHODS:
                        kb_type, display = _ANGULAR_METHODS[last_name]
                        obj_keys = (['mutation'] if last_name == 'mutate'
                                    else ['query', 'mutation', 'subscription'])
                        var_name = self._object_arg(parts[0], obj_keys)
                        if var_name:
                            self._create_hook(
                                display, kb_type, var_name, display,
                                _PAT_ANGULAR, node, jsContent)

                    # ── Direct client method: client.query/mutate({...}) ──
                    elif last_name in _CLIENT_METHODS:
                        kb_type, display = _CLIENT_METHODS[last_name]
                        obj_keys = (['mutation'] if last_name == 'mutate'
                                    else ['query', 'mutation', 'subscription'])
                        var_name = self._object_arg(parts[0], obj_keys)
                        if var_name:
                            self._create_hook(
                                display, kb_type, var_name, display,
                                _PAT_CLIENT, node, jsContent)

                    # ── Angular watchQuery.valueChanges (string-based detection) ──
                    # The HTML5 AST collapses this.apollo.watchQuery({…}).valueChanges
                    # into a single FunctionCallPart with last_name='valueChanges'.
                    # str(parts[0]) contains the full expression, e.g.:
                    #   this.apollo.watchQuery([OrderedDict([(query, WATCH_BALANCE), …])]).valueChanges
                    # We extract the query variable name via regex on that string.
                    elif is_angular and last_name == 'valueChanges':
                        part_str = str(parts[0])
                        if 'watchQuery' in part_str:
                            m = re.search(
                                r'watchQuery.*?\(query,\s*([A-Za-z_][A-Za-z0-9_]*)\)',
                                part_str)
                            if m:
                                var_name = m.group(1)
                                kb_type, display = _ANGULAR_METHODS['watchQuery']
                                self._create_hook(
                                    display, kb_type, var_name, display,
                                    _PAT_ANGULAR, node, jsContent)

                    # ── Angular method fallback (non-angular-import file) ──
                    elif last_name in _ANGULAR_METHODS:
                        kb_type, display = _ANGULAR_METHODS[last_name]
                        obj_keys = (['mutation'] if last_name == 'mutate'
                                    else ['query', 'mutation', 'subscription'])
                        var_name = self._object_arg(parts[0], obj_keys)
                        if var_name:
                            self._create_hook(
                                display, kb_type, var_name, display,
                                _PAT_ANGULAR, node, jsContent)

            except Exception as e:
                log.warning('[GraphQL][JS] hook visitor error: ' + str(e))

        _walk(jsContent, visit)

    def _simple_hook_arg(self, first_part):
        """For useQuery(VAR): return VAR name from the first part's first parameter."""
        params = _part_params(first_part)
        if not params:
            return None
        param = params[0]
        # Bug 5 guard: if arg is itself a function call (e.g. useQuery(useMemo(...))),
        # skip — avoids creating misleading "useQuery:useMemo" objects.
        if hasattr(param, 'is_function_call') and param.is_function_call():
            return None
        return self._ident_name(param)

    def _try_inline_gql(self, first_part, hook_node, jsContent, gql_aliases):
        """F1: detect inline gql`...` as hook argument, create GQL def, return op_name.

        Pattern: useQuery(gql`query GetData { field }`)
        The gql call is the first parameter of the hook's first FunctionCallPart.
        We create the GQL definition object inline (not exported, var_name = op_name)
        and return op_name so the caller can create the hook with proper useLink resolution.
        Returns None if the argument is not an inline gql call or has no operation name.
        """
        params = _part_params(first_part)
        if not params:
            return None
        param = params[0]
        if not (hasattr(param, 'is_function_call') and param.is_function_call()):
            return None
        try:
            if param.get_name() not in gql_aliases:
                return None
        except Exception:
            return None
        # Extract template text from the inline gql call
        try:
            gql_parts = param.get_function_call_parts()
            if not gql_parts:
                return None
            gql_params = _part_params(gql_parts[0])
            if not gql_params:
                return None
            text = self._eval_text(gql_params[0])
            if not text:
                return None
        except Exception:
            return None
        op_type, op_name, variables, fields = self._parse_gql_content(text)
        if op_name is None:
            return None
        _c = _ctx()
        _glog('DETECT', 'GqlDef', _c,
              'inline gql in hook: op={} ({})'.format(op_name, op_type))
        self._create_gql_def(
            op_name, op_name, op_type, text, variables, fields, param, jsContent,
            is_exported=False)
        return op_name

    def _object_arg(self, last_part, keys=('query', 'mutation', 'subscription')):
        """
        For apollo.query({ query: VAR, ... }): extract VAR from the object literal.

        Method 1: ObjectValue.get_item(key) — the correct CAST HTML5 API.
        Method 2 (fallback): walks AST children for property nodes.
        Method 3 (fallback): string repr search for "key: IDENTIFIER".
        """
        params = _part_params(last_part)
        if not params:
            return None
        obj_node = params[0]

        # Method 1: ObjectValue.get_item(key)
        try:
            if (hasattr(obj_node, 'is_object_value')
                    and callable(getattr(obj_node, 'is_object_value', None))
                    and obj_node.is_object_value()):
                for key in keys:
                    try:
                        val = obj_node.get_item(key)
                        if val is not None:
                            n = self._ident_name(val)
                            if n:
                                return n
                    except Exception:
                        pass
        except Exception:
            pass

        # Method 2: walk children
        for child in _node_children(obj_node):
            try:
                child_name = child.get_name() if hasattr(child, 'get_name') else None
                if child_name in keys:
                    for val in _node_children(child):
                        n = self._ident_name(val)
                        if n:
                            return n
            except Exception:
                pass

        # Method 3: string-repr fallback
        try:
            text = str(obj_node)
            for key in keys:
                m = re.search(r'\b' + re.escape(key) + r'\s*:\s*([A-Za-z_][A-Za-z0-9_]*)', text)
                if m:
                    name = m.group(1)
                    if name not in ('unknown', 'null', 'undefined', 'gql', 'true', 'false', 'function'):
                        return name
        except Exception:
            pass

        return None

    def _ident_name(self, node):
        """Return get_name() if it is a meaningful identifier, else None."""
        try:
            name = node.get_name()
            if name and name not in ('unknown', 'null', 'undefined', 'gql'):
                return name
        except Exception:
            pass
        return None

    def _resolve_gql_for_hook_js(self, var_name, ast_node, jsContent, source_pattern):
        """
        Resolve a hook's variable reference to the GQL definition KB object.

        Strategy — scope chain walk, nearest-scope-wins (mirrors TS _resolve_gql_for_hook):
          1. Same-file: walk from the hook's enclosing KB parent upward through parent scopes.
             First match wins (lexical scoping: inner scope shadows outer).
          2. Import-aware cross-file: imported_var_to_file[(file, var)] → (source, original)
             → gql_obj_by_file_var[(source, original)] → KB object.
             Guard: the source def must be exported (non-exported defs are file-private).
             Returns 'PENDING' if source known but def not yet processed.

        Returns CustomObject, 'PENDING', or None.
        """
        try:
            file_path = str(jsContent.get_file().get_path()) if jsContent.get_file() else None
        except Exception:
            file_path = None

        # 1. Same-file scope chain walk
        if file_path and ast_node is not None:
            try:
                scope = ast_node.get_first_kb_parent()
            except Exception:
                scope = None

            visited = set()
            while scope is not None:
                sid = id(scope)
                if sid in visited:
                    break
                visited.add(sid)
                key = (file_path, var_name, sid)
                if key in self.scoped_gql_defs:
                    method = 'same_scope' if len(visited) == 1 else 'scope_chain'
                    obj = self.scoped_gql_defs[key]
                    _glog('RESOLVE', 'Hook', _ctx(),
                          '{} → {} via {}'.format(var_name, obj.get_name() if hasattr(obj, 'get_name') else '?', method))
                    return obj
                # Walk up: parent's first KB parent
                try:
                    parent = scope.parent if hasattr(scope, 'parent') else None
                    if parent is not None and hasattr(parent, 'get_first_kb_parent'):
                        scope = parent.get_first_kb_parent()
                    else:
                        scope = None
                except Exception:
                    scope = None

        # 1.5. Same-file flat fallback (B2 fix — mirrors TS Bug 1.5).
        # The scope chain walk above uses id() to compare CAST Boost.Python wrapper objects.
        # Each call may create a NEW Python wrapper for the same underlying C++ object, so
        # id() comparisons can fail. Fall back to a string-keyed lookup: (file_path, var_name).
        if file_path:
            obj = self.gql_obj_by_file_var.get((file_path, var_name))
            if obj is not None:
                _glog('RESOLVE', 'Hook', _ctx(),
                      '{} → {} via same-file flat fallback'.format(
                          var_name, obj.get_name() if hasattr(obj, 'get_name') else '?'))
                return obj

        # 2. Import-aware cross-file lookup
        # No export guard here: the presence of an explicit import statement
        # (recorded in imported_var_to_file) is sufficient authorization for the link.
        # Export detection for "export { FOO, BAR }" blocks is unreliable in CAST's
        # HTML5 parser, so we trust the import map instead.
        if file_path:
            import_entry = self.imported_var_to_file.get((file_path, var_name))
            if import_entry is not None:
                source_path, original_name = import_entry
                obj = self.gql_obj_by_file_var.get((source_path, original_name))
                if obj is not None:
                    _glog('RESOLVE', 'Hook', _ctx(),
                          '{} → {} via import from {} (original={})'.format(
                              var_name, obj.get_name() if hasattr(obj, 'get_name') else '?',
                              source_path, original_name))
                    return obj
                return 'PENDING'

        return None

    def _create_hook(self, display_name, hook_type, var_name, hook_label,
                     source_pattern, ast_node, jsContent):
        """Create the CAST KB object for a hook call and attempt useLink resolution."""
        try:
            parent_kb = self._hook_parent(ast_node, jsContent)
            if parent_kb is None:
                self._failed += 1
                return

            # F6 fix: codegen hooks use just the function name (no redundant "name:name")
            if source_pattern == _PAT_CODEGEN:
                hook_name = var_name
            else:
                hook_name = display_name + ':' + var_name
            _c = _ctx()
            _glog('DETECT', 'Hook', _c, '{} var={}'.format(display_name, var_name))

            # Build unique fullname (file:line format, same as TS analyzer — F3 fix)
            try:
                line_num = ast_node.get_begin_line() if hasattr(ast_node, 'get_begin_line') else 0
            except Exception:
                line_num = 0
            try:
                fp_for_fn = str(jsContent.get_file().get_path())
            except Exception:
                fp_for_fn = ''
            fullname = fp_for_fn + ':' + str(line_num)

            obj = CustomObject()
            obj.set_name(hook_name)
            obj.set_type(hook_type)
            obj.set_fullname(fullname)
            obj.set_parent(parent_kb)

            obj.save()

            bm = None
            try:
                bm = ast_node.create_bookmark(jsContent.get_file())
                obj.save_position(bm)
            except Exception:
                pass

            # hookType property only for React hook types (mirrors TS behavior)
            if source_pattern == _PAT_REACT:
                obj.save_property('GraphQL_Hook_Request.hookType', hook_label)

            # callLink: parent component → hook object
            if bm:
                try:
                    create_link('callLink', parent_kb, obj, bm)
                except Exception:
                    pass

            self._created += 1
            _glog('RESULT', 'Object', _c, '{} "{}" created'.format(hook_type, hook_name))

            # Resolve variable → GQL definition via scoped resolution
            resolved_obj = self._resolve_gql_for_hook_js(var_name, ast_node, jsContent, source_pattern)

            if resolved_obj is not None and resolved_obj != 'PENDING':
                create_link('useLink', obj, resolved_obj)
                _glog('RESULT', 'Link', _c, 'useLink {} → {}'.format(hook_name, resolved_obj.get_name() if hasattr(resolved_obj, 'get_name') else var_name))
            else:
                try:
                    fp = str(jsContent.get_file().get_path())
                except Exception:
                    fp = None
                self.pending_links.append(
                    (obj, var_name, jsContent.get_kb_object(), source_pattern, fp, bm))
                _glog('RESULT', 'Hook', _c, '{} → pending (cross-file)'.format(hook_name))

        except Exception as e:
            log.warning('[GraphQL][JS] Failed to create hook "{}:{}": {}'.format(display_name, var_name, str(e)))
            self._failed += 1

    def _hook_parent(self, ast_node, jsContent):
        """Get parent KB object: try get_first_kb_parent(), fallback to file."""
        try:
            if hasattr(ast_node, 'get_first_kb_parent'):
                first = ast_node.get_first_kb_parent()
                if first:
                    kb = first.get_kb_object()
                    if kb:
                        return kb
        except Exception:
            pass
        return jsContent.get_kb_object()

    def _resolve_lookup_key(self, var_name, source_pattern):
        """
        Translate a hook's var_name to the operation_name key in gql_definitions.

        For codegen hooks the var_name is the full generated function name
        (e.g. 'useGetLambdaInvocationsQuery'); we extract the base operation name.
        For all other patterns we resolve through var_name_to_op_name.
        """
        if source_pattern == _PAT_CODEGEN:
            m = re.match(
                r'^use([A-Z][A-Za-z0-9]+?)(LazyQuery|Query|Mutation|Subscription)$',
                var_name)
            return m.group(1) if m else var_name
        return self.var_name_to_op_name.get(var_name, var_name)

    # ────────────────────────────── Phase 3 — pending links ───────────────────

    def _resolve_pending_links(self):
        """Retry useLink creation for hooks whose GQL def was not yet known in Phase 2.

        At Phase 3 time all files are processed, so gql_obj_by_file_var is fully populated.
        Import-aware lookup with export guard: non-exported defs are blocked.
        Truly unresolvable hooks become JsGqlUnresolvedDefinition objects.
        """
        if not self.pending_links:
            return

        still = []
        for entry in self.pending_links:
            # Backward-compat: old tuples have 4 or 5 elements, new ones have 6
            if len(entry) == 6:
                hook_obj, var_name, caller_kb, source_pattern, fp, hook_bm = entry
            elif len(entry) == 5:
                hook_obj, var_name, caller_kb, source_pattern, fp = entry
                hook_bm = None
            else:
                hook_obj, var_name, caller_kb, source_pattern = entry
                fp, hook_bm = None, None

            resolved_obj = None

            # B1 fix: same-file flat fallback (mirrors TS on_end resolution).
            # At Phase 3 time all files are processed, so gql_obj_by_file_var is complete.
            if fp:
                same_file_obj = self.gql_obj_by_file_var.get((fp, var_name))
                if same_file_obj is not None:
                    resolved_obj = same_file_obj

            # Import-aware lookup with export guard (only if same-file didn't resolve)
            if resolved_obj is None and fp:
                import_entry = self.imported_var_to_file.get((fp, var_name))
                if import_entry is not None:
                    source_path, original_name = import_entry
                    candidate = self.gql_obj_by_file_var.get((source_path, original_name))
                    if candidate is not None:
                        # No export guard: import statement is sufficient authorization.
                        resolved_obj = candidate

            if resolved_obj is not None:
                try:
                    create_link('useLink', hook_obj, resolved_obj)
                    _glog('RESULT', 'Link', _ctx(), 'pending useLink resolved → {}'.format(
                        resolved_obj.get_name() if hasattr(resolved_obj, 'get_name') else var_name))
                except Exception as e:
                    log.warning('[GraphQL][JS] pending useLink failed for "{}": {}'.format(var_name, str(e)))
                    still.append(entry)  # link failed — fall through to JsGqlUnresolvedDefinition
            else:
                still.append(entry)

        # Create JsGqlUnresolvedDefinition objects for hooks whose GQL def was never found
        for entry in still:
            hook_obj = entry[0]
            var_name = entry[1]
            caller_kb = entry[2]
            source_pattern = entry[3]
            hook_bm = entry[5] if len(entry) >= 6 else None
            lookup_key = self._resolve_lookup_key(var_name, source_pattern)
            if lookup_key not in self.missing_gql_objects:
                try:
                    missing = CustomObject()
                    missing.set_name(lookup_key)
                    missing.set_type('JsGqlUnresolvedDefinition')
                    # Use caller_kb (consumer file) as parent; fall back to hook's own parent
                    # if caller_kb is None (prevents save() failing with no-parent error).
                    parent_for_unresolved = caller_kb
                    if parent_for_unresolved is None:
                        try:
                            parent_for_unresolved = hook_obj.get_parent()
                        except Exception:
                            pass
                    if parent_for_unresolved:
                        missing.set_parent(parent_for_unresolved)
                    missing.save()
                    if hook_bm:
                        try:
                            missing.save_position(hook_bm)
                        except Exception:
                            pass
                    self.missing_gql_objects[lookup_key] = missing
                    _glog('RESULT', 'Object', _ctx(), 'JsGqlUnresolvedDefinition "{}" created'.format(lookup_key))
                except Exception as e:
                    log.warning('[GraphQL][JS] JsGqlUnresolvedDefinition failed for "{}": {}'.format(lookup_key, str(e)))

            if lookup_key in self.missing_gql_objects:
                try:
                    create_link('useLink', hook_obj, self.missing_gql_objects[lookup_key])
                except Exception:
                    pass
