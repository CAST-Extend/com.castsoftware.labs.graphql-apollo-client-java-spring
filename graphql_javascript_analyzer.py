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
    'query':  ('JsGraphQLApolloClientQuery',    'client.query'),
    'mutate': ('JsGraphQLApolloClientMutation', 'client.mutate'),
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
    'Query':        'JsGraphQLApolloHookQuery',
    'LazyQuery':    'JsGraphQLApolloHookLazyQuery',
    'Mutation':     'JsGraphQLApolloHookMutation',
    'Subscription': 'JsGraphQLApolloHookSubscription',
}

# Import names that signal a file uses Apollo Client (used to filter jsContent)
_FILTER_NAMES = (
    set(_APOLLO_HOOKS.keys())
    | {'gql', 'Apollo', 'ApolloClient', 'InMemoryCache', 'ApolloProvider',
       'useApolloClient'}
)

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

        # (hook_obj, var_name, caller_kb, source_pattern) awaiting Phase 3 (Bug 2 fix)
        self.pending_links = []

        # operation_name → JsGqlUnresolvedDefinition; deduplicated across hooks
        self.missing_gql_objects = {}

        # jsContent objects collected in start_javascript_content
        self._js_contents = []

        # stats
        self._created = 0
        self._failed  = 0

    # ──────────────────────────────── event handlers ───────────────────────────

    @Event('com.castsoftware.html5', 'start_javascript_content')
    def _on_start(self, jsContent):
        """Collect jsContent objects that import Apollo Client or gql."""
        try:
            for imp in jsContent.get_imports():
                try:
                    if imp.get_what_name() in _FILTER_NAMES:
                        self._js_contents.append(jsContent)
                        return
                except Exception:
                    pass
        except Exception as e:
            log.warning('[GraphQL JS] start_javascript_content error: ' + str(e))

    @Event('com.castsoftware.html5', 'end_javascript_contents')
    def _on_end(self):
        """Two-phase extraction then pending link resolution."""
        log.info('[GraphQL JS] Analyzing ' + str(len(self._js_contents)) + ' JS file(s)')

        # Phase 1 — gql definitions (must run first across ALL files)
        for jsc in self._js_contents:
            try:
                self._extract_gql_definitions(jsc)
            except Exception as e:
                log.warning('[GraphQL JS] Phase 1 error in '
                            + str(jsc.get_file()) + ': ' + str(e))

        # Phase 2 — hooks + client methods + Angular
        for jsc in self._js_contents:
            try:
                self._extract_apollo_hooks(jsc)
            except Exception as e:
                log.warning('[GraphQL JS] Phase 2 error in '
                            + str(jsc.get_file()) + ': ' + str(e))

        # Phase 3 — resolve pending useLinks (Bug 2 fix)
        self._resolve_pending_links()

        log.info('[GraphQL JS] Done — '
                 + str(self._created) + ' created, '
                 + str(self._failed)  + ' failed')

    # ──────────────────────────────── gql alias detection ─────────────────────

    def _gql_aliases(self, jsContent):
        """Return set of local names bound to the gql template tag in this file."""
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
                    if what == 'gql':
                        aliases.add(local)
                except Exception:
                    pass
        except Exception:
            pass
        return aliases

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

                # Walk up to find "const VAR = gql`...`"
                var_name = self._get_var_name(node)
                if not var_name:
                    return

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

                self._create_gql_def(
                    var_name, op_name, op_type, text, variables, fields, node, jsContent)
            except Exception as e:
                log.warning('[GraphQL JS] gql visitor error: ' + str(e))

        _walk(jsContent, visit)

    def _get_var_name(self, gql_node):
        """Walk up AST to find the variable name in 'const VAR = gql`...`'."""
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
                            return name
                current = parent
            except Exception:
                break
        return None

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

        # Fields selected: identifiers in the first { } block of the operation body
        fields = ''
        fb = re.search(r'\{([^{}]+)\}', clean)
        if fb:
            field_matches = re.findall(r'\b([a-z][a-zA-Z0-9_]*)\b', fb.group(1))
            fields = ', '.join(dict.fromkeys(field_matches))  # ordered dedup

        return op_type, op_name, variables, fields

    def _create_gql_def(self, var_name, op_name, op_type, raw_text,
                        variables, fields, ast_node, jsContent):
        """Create the CAST KB object for a GQL definition and register it."""
        try:
            parent_kb = jsContent.get_kb_object()
            if parent_kb is None:
                self._failed += 1
                return

            obj = CustomObject()
            obj.set_name(op_name)       # named by operation_name (Bug 8 fix)
            obj.set_type(op_type)
            obj.set_parent(parent_kb)

            obj.save()

            try:
                obj.save_position(ast_node.create_bookmark(jsContent.get_file()))
            except Exception as e:
                log.info('[GraphQL JS] save_position failed for "' + op_name + '": ' + str(e))

            obj.save_property('GraphQL_Client_Definition.operationName', op_name)
            obj.save_property('GraphQL_Client_Definition.rawQueryText',  raw_text)
            if variables:
                obj.save_property('GraphQL_Client_Definition.variables',     variables)
            if fields:
                obj.save_property('GraphQL_Client_Definition.fieldsSelected', fields)

            self._created += 1
            self.gql_definitions[op_name] = obj

            # First-seen wins: outer-scope variable takes priority on collision
            if var_name not in self.var_name_to_op_name:
                self.var_name_to_op_name[var_name] = op_name
            else:
                log.warning('[GraphQL JS] var_name collision: "' + var_name
                            + '" already → "' + self.var_name_to_op_name[var_name]
                            + '"; new op "' + op_name + '" stored, hook lookup uses first')
        except Exception as e:
            log.warning('[GraphQL JS] Failed to create GQL def "'
                        + op_name + '": ' + str(e))
            self._failed += 1

    # ────────────────────────────── Phase 2 — hooks ───────────────────────────

    def _extract_apollo_hooks(self, jsContent):
        """Walk jsContent AST; register every Apollo hook / client method call."""
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

                # Diagnostic: log when a potentially relevant method name is seen
                if (last_name in _APOLLO_HOOKS or last_name in _CLIENT_METHODS
                        or last_name in _ANGULAR_METHODS
                        or _CODEGEN_PATTERN.match(last_name)):
                    penult_diag = (_part_name(parts[-2])
                                   if n_parts >= 2 else '<none>')
                    log.info('[GraphQL JS] FC n_parts=' + str(n_parts)
                             + ' last=' + last_name
                             + ' penult=' + str(penult_diag))

                if n_parts == 1:
                    # ── React hooks: useQuery(VAR) etc. ──
                    if last_name in _APOLLO_HOOKS:
                        kb_type  = _APOLLO_HOOKS[last_name]
                        var_name = self._simple_hook_arg(parts[0])
                        if var_name:
                            self._create_hook(
                                last_name, kb_type, var_name, last_name,
                                _PAT_REACT, node, jsContent)

                    # ── Codegen hooks: useGetXQuery() etc. ──
                    elif _CODEGEN_PATTERN.match(last_name):
                        suffix   = _CODEGEN_PATTERN.match(last_name).group(1)
                        kb_type  = _CODEGEN_SUFFIX_MAP[suffix]
                        self._create_hook(
                            last_name, kb_type, last_name, last_name,
                            _PAT_CODEGEN, node, jsContent)

                    # ── Single-part client method: mutate({mutation:VAR}) / query({query:VAR})
                    # Fallback for when HTML5 AST returns only the method part without
                    # the receiver (e.g. 'mutate' alone instead of ['client','mutate']).
                    elif last_name in _CLIENT_METHODS:
                        kb_type, display = _CLIENT_METHODS[last_name]
                        obj_keys = (['mutation'] if last_name == 'mutate'
                                    else ['query', 'mutation', 'subscription'])
                        var_name = self._object_arg(parts[0], obj_keys)
                        if var_name:
                            log.info('[GraphQL JS] client method (1-part): '
                                     + display + ' → ' + var_name)
                            self._create_hook(
                                display, kb_type, var_name, display,
                                _PAT_CLIENT, node, jsContent)


                    # ── Single-part Angular: watchQuery({query:VAR}) when penult='apollo'
                    # is not available (but name matches an angular method).
                    # Note: 'query' and 'mutate' are caught by _CLIENT_METHODS above;
                    # this branch activates primarily for 'watchQuery'.
                    elif last_name in _ANGULAR_METHODS:
                        kb_type, display = _ANGULAR_METHODS[last_name]
                        obj_keys = (['mutation'] if last_name == 'mutate'
                                    else ['query', 'mutation', 'subscription'])
                        var_name = self._object_arg(parts[0], obj_keys)
                        if var_name:
                            log.info('[GraphQL JS] angular method (1-part): '
                                     + display + ' → ' + var_name)
                            self._create_hook(
                                display, kb_type, var_name, display,
                                _PAT_ANGULAR, node, jsContent)

                elif n_parts >= 2:
                    penult = _part_name(parts[-2])

                    # ── Angular: this.apollo.method({ query/mutation: VAR }) ──
                    if penult == 'apollo' and last_name in _ANGULAR_METHODS:
                        kb_type, display = _ANGULAR_METHODS[last_name]
                        var_name = self._object_arg(parts[-1])
                        if var_name:
                            self._create_hook(
                                display, kb_type, var_name, display,
                                _PAT_ANGULAR, node, jsContent)

                    # ── Direct client: client.query({ query: VAR }) etc. ──
                    elif penult != 'apollo' and last_name in _CLIENT_METHODS:
                        kb_type, display = _CLIENT_METHODS[last_name]
                        var_name = self._object_arg(parts[-1])
                        if var_name:
                            self._create_hook(
                                display, kb_type, var_name, display,
                                _PAT_CLIENT, node, jsContent)

            except Exception as e:
                log.warning('[GraphQL JS] hook visitor error: ' + str(e))

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

    def _object_arg(self, last_part, keys=('query', 'mutation', 'subscription')):
        """
        For apollo.query({ query: VAR, ... }): extract VAR from the object literal.

        Method 1: ObjectValue.get_item(key) — the correct CAST HTML5 API used by
        the NodeJS resolver extractor.  Works when the argument is an ObjectValue node.

        Method 2 (fallback): walks AST children looking for property nodes whose
        get_name() returns one of `keys`.

        Method 3 (fallback): searches the string repr of the first parameter for
        the pattern "key: IDENTIFIER".
        """
        params = _part_params(last_part)
        log.info('[GraphQL JS] _object_arg: last_part type=' + str(type(last_part))
                 + ' str=' + str(last_part)[:200]
                 + ' repr=' + repr(str(last_part))[:200])
        log.info('[GraphQL JS] _object_arg: keys=' + str(keys)
                 + ' params_count=' + str(len(params)))
        if not params:
            log.info('[GraphQL JS] _object_arg: no params, returning None')
            return None
        obj_node = params[0]
        log.info('[GraphQL JS] _object_arg: obj_node type=' + str(type(obj_node))
                 + ' repr=' + repr(str(obj_node))[:200])
        log.info('[GraphQL JS] _object_arg: obj_node has is_object_value='
                 + str(hasattr(obj_node, 'is_object_value')))

        # Method 1: ObjectValue.get_item(key) — mirrors NodeJS resolver extraction
        try:
            if (hasattr(obj_node, 'is_object_value')
                    and callable(getattr(obj_node, 'is_object_value', None))
                    and obj_node.is_object_value()):
                log.info('[GraphQL JS] _object_arg: Method1 — is_object_value=True')
                for key in keys:
                    try:
                        val = obj_node.get_item(key)
                        log.info('[GraphQL JS] _object_arg: Method1 get_item("'
                                 + key + '") → type=' + str(type(val))
                                 + ' repr=' + repr(str(val))[:120])
                        if val is not None:
                            n = self._ident_name(val)
                            log.info('[GraphQL JS] _object_arg: Method1 _ident_name="' + str(n) + '"')
                            if n:
                                return n
                    except Exception as e:
                        log.info('[GraphQL JS] _object_arg: Method1 get_item("'
                                 + key + '") exception: ' + str(e))
            else:
                log.info('[GraphQL JS] _object_arg: Method1 skipped — is_object_value='
                         + str(obj_node.is_object_value()
                               if hasattr(obj_node, 'is_object_value') else 'N/A'))
        except Exception as e:
            log.info('[GraphQL JS] _object_arg: Method1 outer exception: ' + str(e))

        # Method 2: walk children (works if property nodes have get_name() == key)
        log.info('[GraphQL JS] _object_arg: Method2 — walking '
                 + str(len(_node_children(obj_node))) + ' children')
        for child in _node_children(obj_node):
            try:
                child_name = (child.get_name()
                              if hasattr(child, 'get_name') else None)
                log.info('[GraphQL JS] _object_arg: Method2 child name='
                         + str(child_name) + ' type=' + str(type(child)))
                if child_name in keys:
                    for val in _node_children(child):
                        n = self._ident_name(val)
                        log.info('[GraphQL JS] _object_arg: Method2 val _ident_name="' + str(n) + '"')
                        if n:
                            return n
            except Exception as e:
                log.info('[GraphQL JS] _object_arg: Method2 child exception: ' + str(e))

        # Method 3: string-repr fallback — search "key: IDENTIFIER" in node repr
        try:
            text = str(obj_node)
            log.info('[GraphQL JS] _object_arg: Method3 — repr[:200]=' + repr(text)[:200])
            for key in keys:
                m = re.search(
                    r'\b' + re.escape(key) + r'\s*:\s*([A-Za-z_][A-Za-z0-9_]*)',
                    text)
                if m:
                    name = m.group(1)
                    log.info('[GraphQL JS] _object_arg: Method3 matched key="'
                             + key + '" name="' + name + '"')
                    if name not in ('unknown', 'null', 'undefined', 'gql',
                                    'true', 'false', 'function'):
                        return name
        except Exception as e:
            log.info('[GraphQL JS] _object_arg: Method3 exception: ' + str(e))

        log.info('[GraphQL JS] _object_arg: all methods failed, returning None')
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

    def _create_hook(self, display_name, hook_type, var_name, hook_label,
                     source_pattern, ast_node, jsContent):
        """Create the CAST KB object for a hook call and attempt useLink resolution."""
        try:
            parent_kb = self._hook_parent(ast_node, jsContent)
            if parent_kb is None:
                self._failed += 1
                return

            obj = CustomObject()
            obj.set_name(display_name + ':' + var_name)
            obj.set_type(hook_type)
            obj.set_parent(parent_kb)

            obj.save()

            bm = None
            try:
                bm = ast_node.create_bookmark(jsContent.get_file())
                obj.save_position(bm)
            except Exception as e:
                log.info('[GraphQL JS] bookmark failed for "' + display_name + ':' + var_name + '": ' + str(e))

            # hookType property only for React hook types (mirrors TS behavior)
            if source_pattern == _PAT_REACT:
                obj.save_property('GraphQL_Hook_Request.hookType', hook_label)

            # callLink: parent component → hook object
            if bm:
                try:
                    create_link('callLink', parent_kb, obj, bm)
                except Exception as e:
                    log.info('[GraphQL JS] callLink failed for "' + display_name + ':' + var_name + '": ' + str(e))

            self._created += 1

            # Resolve variable → operation_name → gql_definitions
            lookup_key = self._resolve_lookup_key(var_name, source_pattern)

            if lookup_key in self.gql_definitions:
                create_link('useLink', obj, self.gql_definitions[lookup_key])
            else:
                self.pending_links.append(
                    (obj, var_name, jsContent.get_kb_object(), source_pattern))

        except Exception as e:
            log.warning('[GraphQL JS] Failed to create hook "'
                        + display_name + ':' + var_name + '": ' + str(e))
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
        except Exception as e:
            log.info('[GraphQL JS] get_first_kb_parent error, using file KB: ' + str(e))
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
        """Retry useLink creation for hooks whose GQL def was not yet known in Phase 2."""
        if not self.pending_links:
            return
        log.info('[GraphQL JS] Resolving '
                 + str(len(self.pending_links)) + ' pending link(s)')

        still = []
        for entry in self.pending_links:
            hook_obj, var_name, caller_kb, source_pattern = entry
            lookup_key = self._resolve_lookup_key(var_name, source_pattern)

            if lookup_key in self.gql_definitions:
                try:
                    create_link('useLink', hook_obj, self.gql_definitions[lookup_key])
                except Exception as e:
                    log.warning('[GraphQL JS] Pending link error: ' + str(e))
            else:
                still.append(entry)

        # Create JsGqlUnresolvedDefinition objects for hooks whose GQL def was never found
        for hook_obj, var_name, caller_kb, source_pattern in still:
            lookup_key = self._resolve_lookup_key(var_name, source_pattern)
            if lookup_key not in self.missing_gql_objects:
                try:
                    missing = CustomObject()
                    missing.set_name(lookup_key)
                    missing.set_type('JsGqlUnresolvedDefinition')
                    if caller_kb:
                        missing.set_parent(caller_kb)
                    missing.save()
                    self.missing_gql_objects[lookup_key] = missing
                except Exception as e:
                    log.warning('[GraphQL JS] JsGqlUnresolvedDefinition creation failed for "' + lookup_key + '": ' + str(e))

            if lookup_key in self.missing_gql_objects:
                try:
                    create_link('useLink', hook_obj,
                                self.missing_gql_objects[lookup_key])
                except Exception as e:
                    log.info('[GraphQL JS] useLink to unresolved failed for "' + lookup_key + '": ' + str(e))
