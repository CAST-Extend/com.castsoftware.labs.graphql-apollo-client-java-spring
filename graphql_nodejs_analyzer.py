# -*- coding: utf-8 -*-
"""
GraphQL Node.js Apollo Server Analyzer

Detects Apollo Server patterns in JavaScript files and creates KB objects:

  - JsNodeJsApolloSchema: inline typeDefs (const typeDefs = gql`type Query {...}`)
    Created only in files that import an Apollo Server package.

  - JsNodeJsResolver{Query,Mutation,Subscription,Custom}: one resolver function per field
    (const resolvers = { Query: { users: ... }, Mutation: { createUser: ... } })
    Created in ALL JS files — the resolver object pattern is self-selecting.

Architecture (mirrors graphql_javascript_analyzer.py):
  Phase 0 (start_javascript_content): collect all jsContent objects
  Phase 1 (end_javascript_contents): typeDefs → JsNodeJsApolloSchema (server files only)
  Phase 2 (end_javascript_contents): resolvers → JsNodeJsResolver* (all JS files)

Links are created in graphql_application_level.py:
  GraphQLField -callLink-> JsNodeJsResolver*  (matched by operationType + fieldName)
"""

import re
from cast.analysers import ua, log, CustomObject, create_link, Bookmark
from cast import Event


# ─────────────────────────────────────────────────── constants ────────────────

# npm package names that identify Apollo Server files
_APOLLO_SERVER_PACKAGES = frozenset({
    'apollo-server',
    '@apollo/server',
    'apollo-server-express',
    'apollo-server-core',
    'apollo-server-lambda',
    'apollo-server-koa',
    'apollo-server-fastify',
    'apollo-server-hapi',
    'apollo-server-micro',
    'apollo-server-azure-functions',
})

# GraphQL operation type sections found inside resolver maps
_OPERATION_TYPES = ('Query', 'Mutation', 'Subscription')

# Map operation type → JS KB type name
_OPERATION_TYPE_TO_JS_TYPE = {
    'Query':        'JsNodeJsResolverQuery',
    'Mutation':     'JsNodeJsResolverMutation',
    'Subscription': 'JsNodeJsResolverSubscription',
}

# Special resolver keys that are meta-resolvers, not field resolvers
_SKIP_FIELD_NAMES = frozenset({'__resolveType', '__isTypeOf', 'subscribe'})

# Built-in GraphQL scalars and meta-keys that are NOT custom type resolvers
_BUILTIN_GRAPHQL_NAMES = frozenset({
    'Query', 'Mutation', 'Subscription',
    'String', 'Int', 'Float', 'Boolean', 'ID',
    'Date', 'DateTime', 'JSON', 'Upload',
})

# Regex to extract service call from JS resolver body: ctx.serviceName.methodName(
_JS_SERVICE_CALL_RE = re.compile(r'ctx\.(\w+)\.(\w+)\s*\(')

# Regex to extract context key → class mapping: key: new ClassName(  or  key = new ClassName(
_CONTEXT_KEY_TO_CLASS_RE = re.compile(r'(\w+)\s*[:=]\s*new\s+(\w+)\s*\(')

# Variable names that typically carry the Apollo Server typeDefs
_TYPEDEFS_VAR_NAMES = frozenset({'typedefs', 'type_defs', 'types', 'schema'})


# ─────────────────────────────────────────────────── AST helpers ──────────────

def _node_children(node):
    """Return get_children() as a list, or [] on error."""
    try:
        return list(node.get_children())
    except Exception:
        return []


def _walk(node, callback):
    """Depth-first recursive walk; callback is called on every descendant."""
    for child in _node_children(node):
        callback(child)
        _walk(child, callback)


def _is_object_value(node):
    """Return True if node is an ObjectValue (has get_item + is_object_value)."""
    return (hasattr(node, 'is_object_value')
            and callable(getattr(node, 'is_object_value', None))
            and node.is_object_value())


def _is_function_call(node):
    """Return True if node is a FunctionCall."""
    return (hasattr(node, 'is_function_call')
            and callable(getattr(node, 'is_function_call', None))
            and node.is_function_call())


# ─────────────────────────────────────────────────── main class ───────────────

class GraphQLNodeJsAnalyzer(ua.Extension):
    """
    Node.js Apollo Server analyzer: detects typeDefs and resolver maps in JS files.

    Subscribes to the same com.castsoftware.html5 events as the JS client analyzer.
    Does NOT detect client-side hooks (those are in graphql_javascript_analyzer.py).
    """

    def __init__(self):
        self._all_contents    = []   # all collected jsContent objects
        self._server_contents = []   # subset: files that import ApolloServer
        self._created = 0
        self._failed  = 0
        self._context_key_to_class = {}  # e.g. {"interestService": "InterestService"}

    # ──────────────────────────────────────────── event handlers ──────────────

    @Event('com.castsoftware.html5', 'start_javascript_content')
    def _on_start(self, jsContent):
        """Collect every jsContent; flag server files by ApolloServer import."""
        try:
            self._all_contents.append(jsContent)
            if self._is_server_file(jsContent):
                self._server_contents.append(jsContent)
                log.info('[GraphQL NodeJs] Server file detected: '
                         + str(jsContent.get_file()))
        except Exception as e:
            log.warning('[GraphQL NodeJs] start error: ' + str(e))

    @Event('com.castsoftware.html5', 'end_javascript_contents')
    def _on_end(self):
        """Three-phase extraction: context mapping, typeDefs, then resolvers."""
        log.info('[GraphQL NodeJs] Analyzing '
                 + str(len(self._all_contents)) + ' JS file(s), '
                 + str(len(self._server_contents)) + ' server file(s)')

        # Phase 0 — scan all files for context key → class bindings (new ClassName())
        for jsc in self._all_contents:
            try:
                self._extract_context_key_bindings(jsc)
            except Exception as e:
                log.warning('[GraphQL NodeJs] Phase 0 error in '
                            + str(jsc.get_file()) + ': ' + str(e))
        if self._context_key_to_class:
            log.info('[GraphQL NodeJs] Context key→class map: '
                     + str(len(self._context_key_to_class)) + ' entries')

        # Phase 1 — typeDefs → JsNodeJsApolloSchema (all files; variable-name filter is the guard)
        for jsc in self._all_contents:
            try:
                self._extract_typedefs(jsc)
            except Exception as e:
                log.warning('[GraphQL NodeJs] Phase 1 error in '
                            + str(jsc.get_file()) + ': ' + str(e))

        # Phase 2 — resolver maps → JsNodeJsResolver* (all JS files)
        for jsc in self._all_contents:
            try:
                self._extract_resolvers(jsc)
            except Exception as e:
                log.warning('[GraphQL NodeJs] Phase 2 error in '
                            + str(jsc.get_file()) + ': ' + str(e))

        log.info('[GraphQL NodeJs] Done — '
                 + str(self._created) + ' created, '
                 + str(self._failed)  + ' failed')

    # ──────────────────────────────────────────── server file detection ────────

    def _is_server_file(self, jsContent):
        """Return True if the file imports any known Apollo Server package (ES6 or CommonJS)."""
        # Method 1: ES6 import — try get_from_name()
        try:
            for imp in jsContent.get_imports():
                try:
                    from_name = imp.get_from_name()
                    if from_name and (from_name in _APOLLO_SERVER_PACKAGES
                                      or from_name.startswith('apollo-server')
                                      or from_name == '@apollo/server'):
                        return True
                except Exception:
                    pass
        except Exception:
            pass

        # Method 2: CommonJS require('apollo-server*') — use jsContent.get_requires()
        try:
            for req in jsContent.get_requires():
                try:
                    pkg = req.get_param()
                    if pkg and (pkg in _APOLLO_SERVER_PACKAGES
                                or pkg.startswith('apollo-server')
                                or pkg == '@apollo/server'):
                        return True
                except Exception:
                    pass
        except Exception:
            pass

        return False

    def _eval_string(self, node):
        """Extract a string value from a string-literal AST node."""
        try:
            for ev in node.evaluate():
                text = str(ev).strip("'\"`").strip()
                if text:
                    return text
        except Exception:
            pass
        try:
            name = node.get_name()
            if name and name not in ('unknown', 'null'):
                return name
        except Exception:
            pass
        try:
            text = str(node)
            m = re.search(r"['\"`]([^'\"`]+)['\"`]", text)
            if m:
                return m.group(1)
        except Exception:
            pass
        return None

    # ──────────────────────────────────────────── gql alias detection ──────────

    def _gql_aliases(self, jsContent):
        """Return the set of local names bound to the gql template tag."""
        aliases = {'gql'}
        try:
            for imp in jsContent.get_imports():
                try:
                    what = imp.get_what_name()
                    if what != 'gql':
                        continue
                    local = None
                    try:
                        local = imp.get_alias_name()
                    except Exception:
                        pass
                    aliases.add(local or what)
                except Exception:
                    pass
        except Exception:
            pass
        return aliases

    # ──────────────────────────────────────────── Phase 1: typeDefs ────────────

    def _extract_typedefs(self, jsContent):
        """
        Detect  const typeDefs = gql`type Query {...}`  in server files.
        Creates one JsNodeJsApolloSchema KB object per typeDefs assignment.

        readFileSync-based schemas are already parsed from .graphql SDL files
        by graphql_analyser_level.py, so they are intentionally skipped here.
        """
        gql_aliases = self._gql_aliases(jsContent)

        def visit(node):
            try:
                if not _is_function_call(node):
                    return
                call_name = node.get_name()
                if call_name not in gql_aliases:
                    return
                var_name = self._get_var_name(node)
                if not var_name:
                    return
                # Accept any variable whose name matches common typeDefs conventions
                if var_name.lower() not in _TYPEDEFS_VAR_NAMES:
                    return
                self._create_apollo_schema(var_name, node, jsContent)
            except Exception as e:
                log.info('[GraphQL NodeJs] typeDefs visitor error: ' + str(e))

        _walk(jsContent, visit)

    def _get_var_name(self, gql_node):
        """Walk up the AST to find the variable name in  const VAR = gql`...`."""
        current = gql_node
        for _ in range(12):
            try:
                parent = (current.get_parent()
                          if hasattr(current, 'get_parent') else None)
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

    def _create_apollo_schema(self, var_name, ast_node, jsContent):
        """Create a JsNodeJsApolloSchema KB object for an inline typeDefs."""
        try:
            parent_kb = jsContent.get_kb_object()
            if parent_kb is None:
                self._failed += 1
                return

            obj = CustomObject()
            obj.set_name(var_name)
            obj.set_type('JsNodeJsApolloSchema')
            obj.set_parent(parent_kb)
            obj.save()

            try:
                obj.save_position(ast_node.create_bookmark(jsContent.get_file()))
            except Exception as bm_e:
                log.info('[GraphQL NodeJs] ApolloSchema bookmark failed for "'
                         + var_name + '": ' + str(bm_e))

            self._created += 1
            log.info('[GraphQL NodeJs] Created JsNodeJsApolloSchema: ' + var_name
                     + ' in ' + str(jsContent.get_file()))

        except Exception as e:
            log.warning('[GraphQL NodeJs] Failed JsNodeJsApolloSchema "'
                        + var_name + '": ' + str(e))
            self._failed += 1

    # ──────────────────────────────── Phase 0: context key → class mapping ────

    def _extract_context_key_bindings(self, jsContent):
        """
        Scan for  key: new ClassName(  or  key = new ClassName(  patterns.

        Populates self._context_key_to_class so that resolver service extraction
        can resolve  ctx.interestService.findAll()  →  serviceClass=InterestService.
        """
        try:
            source_text = self._get_source_text(jsContent)
            if not source_text:
                return
            for m in _CONTEXT_KEY_TO_CLASS_RE.finditer(source_text):
                key, cls = m.group(1), m.group(2)
                if key not in self._context_key_to_class:
                    self._context_key_to_class[key] = cls
        except Exception as e:
            log.info('[GraphQL NodeJs] context key scan error: ' + str(e))

    def _get_source_text(self, jsContent):
        """Extract raw source text from a jsContent object."""
        try:
            source_file = jsContent.get_file()
            if source_file and hasattr(source_file, 'get_path'):
                path = str(source_file.get_path())
                try:
                    with open(path, 'r', encoding='utf-8', errors='replace') as f:
                        return f.read()
                except Exception:
                    pass
        except Exception:
            pass
        return None

    # ──────────────────────────────────────────── Phase 2: resolvers ───────────

    def _extract_resolvers(self, jsContent):
        """
        Walk the jsContent AST looking for resolver maps:

          { Query: { fieldName: (parent, args, ctx) => {...} },
            Mutation: { createX: async (...) => {...} },
            Subscription: { eventX: { subscribe: ... } },
            User: { posts: (parent, args, ctx) => {...} } }

        Creates one JsNodeJsResolver* KB object per resolver field + op type.
        Handles both standard operation types (Query/Mutation/Subscription) and
        custom field resolvers (any other PascalCase key with object-valued properties).
        Deduplication is done within the file by (op_type, field_name).
        """
        found = []   # list of (op_type, field_name, key_ast_node, value_node)

        def visit(node):
            if not _is_object_value(node):
                return
            has_standard_type = False
            for op_type in _OPERATION_TYPES:
                try:
                    type_section = node.get_item(op_type)
                    if type_section is None:
                        continue
                    has_standard_type = True
                    if not _is_object_value(type_section):
                        continue
                    items_dict = type_section.get_items_dictionary()
                    if not items_dict:
                        continue
                    for key_ident, value_node in items_dict.items():
                        try:
                            field_name = (key_ident.get_name()
                                          if hasattr(key_ident, 'get_name')
                                          else str(key_ident))
                            if (field_name
                                    and field_name not in _SKIP_FIELD_NAMES
                                    and field_name != 'unknown'):
                                found.append((op_type, field_name, key_ident, value_node))
                        except Exception:
                            pass
                except Exception:
                    pass

            # Custom field resolvers: any PascalCase key that is NOT a standard type
            # and contains object-valued properties (field resolvers).
            # Only scan objects that already have at least one standard type (Query/Mutation/Subscription)
            # to avoid false positives on arbitrary JS objects.
            if has_standard_type:
                try:
                    items_dict = node.get_items_dictionary()
                    if items_dict:
                        for key_ident, value_node in items_dict.items():
                            try:
                                type_name = (key_ident.get_name()
                                             if hasattr(key_ident, 'get_name')
                                             else str(key_ident))
                                if (not type_name
                                        or type_name in _BUILTIN_GRAPHQL_NAMES
                                        or type_name == 'unknown'
                                        or not type_name[0].isupper()):
                                    continue
                                if not _is_object_value(value_node):
                                    continue
                                inner_dict = value_node.get_items_dictionary()
                                if not inner_dict:
                                    continue
                                for field_key, field_val in inner_dict.items():
                                    try:
                                        field_name = (field_key.get_name()
                                                      if hasattr(field_key, 'get_name')
                                                      else str(field_key))
                                        if (field_name
                                                and field_name not in _SKIP_FIELD_NAMES
                                                and field_name != 'unknown'):
                                            found.append((type_name, field_name,
                                                          field_key, field_val))
                                    except Exception:
                                        pass
                            except Exception:
                                pass
                except Exception:
                    pass

        _walk(jsContent, visit)

        if not found:
            return

        # Dedup within file: keep first occurrence of each (op_type, field_name)
        seen = set()
        for op_type, field_name, key_node, value_node in found:
            pair = (op_type, field_name)
            if pair not in seen:
                seen.add(pair)
                self._create_resolver(op_type, field_name, key_node,
                                      value_node, jsContent)

    def _extract_service_call(self, value_node):
        """
        Extract (serviceClass, serviceMethod) from a resolver function body.

        For JS resolvers, looks for  ctx.serviceName.methodName(  patterns.
        Resolves the context key to a class name via self._context_key_to_class.

        Returns (serviceClass, serviceMethod) or (None, None).
        """
        try:
            body_text = str(value_node)
            m = _JS_SERVICE_CALL_RE.search(body_text)
            if m:
                ctx_key = m.group(1)
                method = m.group(2)
                cls = self._context_key_to_class.get(ctx_key, ctx_key)
                return (cls, method)
        except Exception:
            pass
        return (None, None)

    def _create_resolver(self, op_type, field_name, ast_node, value_node, jsContent):
        """Create a JsNodeJsResolver* KB object for one resolver function."""
        try:
            parent_kb = jsContent.get_kb_object()
            if parent_kb is None:
                self._failed += 1
                return

            # Determine the correct KB type
            resolver_type = _OPERATION_TYPE_TO_JS_TYPE.get(op_type, 'JsNodeJsResolverCustom')

            obj = CustomObject()
            obj.set_name(field_name)
            obj.set_type(resolver_type)
            obj.set_parent(parent_kb)
            obj.save()

            try:
                obj.save_position(ast_node.create_bookmark(jsContent.get_file()))
            except Exception as bm_e:
                log.info('[GraphQL NodeJs] Resolver bookmark failed for "'
                         + op_type + '.' + field_name + '": ' + str(bm_e))

            obj.save_property('GraphQL_NodeJs_Resolver.operationType', op_type)
            obj.save_property('GraphQL_NodeJs_Resolver.fieldName', field_name)

            # Extract service call info from resolver body
            service_class, service_method = self._extract_service_call(value_node)
            if service_class:
                obj.save_property('GraphQL_NodeJs_Resolver.serviceClass', service_class)
            if service_method:
                obj.save_property('GraphQL_NodeJs_Resolver.serviceMethod', service_method)

            self._created += 1
            log.info('[GraphQL NodeJs] Created ' + resolver_type + ': '
                     + op_type + '.' + field_name
                     + (' → ' + str(service_class) + '.' + str(service_method)
                        if service_class else ''))

        except Exception as e:
            log.warning('[GraphQL NodeJs] Failed resolver "'
                        + op_type + '.' + field_name + '": ' + str(e))
            self._failed += 1
