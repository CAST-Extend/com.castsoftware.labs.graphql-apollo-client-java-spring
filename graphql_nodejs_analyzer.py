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

import os
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

# Special resolver keys that are meta-resolvers or middleware helpers, not field resolvers
_SKIP_FIELD_NAMES = frozenset({
    '__resolveType', '__isTypeOf', 'subscribe',
    # Apollo cache policy helpers (false positive from InMemoryCache type policies)
    'merge', 'read', 'keyArgs',
    # Common middleware / utility function calls that appear inside resolver bodies
    'requireAuth', 'validateRole', 'validateMinimumRole',
    'withFilter', 'publish',
})

# Built-in GraphQL scalars and meta-keys that are NOT custom type resolvers
_BUILTIN_GRAPHQL_NAMES = frozenset({
    'Query', 'Mutation', 'Subscription',
    'String', 'Int', 'Float', 'Boolean', 'ID',
    'Date', 'DateTime', 'JSON', 'Upload',
})

# Regex to extract service call from JS resolver body: ctx.serviceName.methodName(
# Matches any short lowercase context-like variable (ctx, context, req, etc.)
_JS_SERVICE_CALL_RE = re.compile(r'\b(?:ctx|context|req|request)\b\.(\w+)\.(\w+)\s*\(')

# Regex to extract context key → class mapping: key: new ClassName(  or  key = new ClassName(
_CONTEXT_KEY_TO_CLASS_RE = re.compile(r'(\w+)\s*[:=]\s*new\s+(\w+)\s*\(')

# ES6 import: import { Name } from 'path'  or  import Name from 'path'
_ES6_IMPORT_RE = re.compile(
    r"import\s+(?:\{([^}]+)\}|(\w+))\s+from\s+['\"]([^'\"]+)['\"]"
)
# CommonJS require: const { Name } = require('path')  or  const Name = require('path')
_CJS_REQUIRE_RE = re.compile(
    r"(?:const|let|var)\s+(?:\{([^}]+)\}|(\w+))\s*=\s*require\(['\"]([^'\"]+)['\"]\)"
)
# Instance creation: const varName = new ClassName(
_NEW_INSTANCE_RE = re.compile(
    r'(?:const|let|var)\s+(\w+)\s*=\s*new\s+([A-Z]\w+)\s*\('
)
# Direct class call: ClassName.methodName(
_JS_DIRECT_CLASS_RE = re.compile(r'([A-Z]\w+)\.(\w+)\s*\(')
# Instance call: instanceVar.methodName(
_JS_INSTANCE_CALL_RE = re.compile(r'([a-z]\w+)\.(\w+)\s*\(')
# this.property.methodName(  — class method body calling an injected service
_JS_THIS_INSTANCE_CALL_RE = re.compile(r'this\.([a-z]\w+)\.(\w+)\s*\(')

# ── var_type_map enrichment regexes ──────────────────────────────────────────

# this.foo = new Foo(  — assignment in class constructor body
_THIS_NEW_INSTANCE_RE = re.compile(
    r'this\.([a-z]\w+)\s*=\s*new\s+([A-Z]\w+)\s*\('
)
# JSDoc: @type {Foo} ... const foo = ...  (up to ~120 chars / ~3 lines between annotation and decl)
_JSDOC_TYPE_RE = re.compile(
    r'@type\s*\{\s*([A-Z]\w+)[^}]*\}[\s\S]{0,120}?(?:const|let|var)\s+(\w+)'
)
# Singleton / factory: const foo = Foo.getInstance() / Foo.create() / Foo.shared etc.
_SINGLETON_INSTANCE_RE = re.compile(
    r'(?:const|let|var)\s+(\w+)\s*=\s*([A-Z]\w+)'
    r'\.(?:getInstance|getDefault|getShared|create|instance|shared)\s*\('
)
# Context destructuring: const { foo, bar: localBar } = ctx / context / req / request
_CTX_DESTRUCTURE_RE = re.compile(
    r'(?:const|let|var)\s*\{([^}]+)\}\s*=\s*(?:ctx|context|req|request)\b'
)
# Constructor injection: this.foo = foo  (heuristic: capitalize(foo) → Foo)
# Only when property name equals the assigned name (standard DI pattern)
_THIS_PARAM_ASSIGN_RE = re.compile(
    r'this\.([a-z]\w+)\s*=\s*([a-z]\w+)\s*[;,\n\r]'
)

# Class names that are JS builtins — skip when scanning for service calls
_SKIP_CLASS_NAMES = frozenset({
    'Promise', 'Object', 'Array', 'JSON', 'Math', 'Error', 'Date',
    'String', 'Number', 'Boolean', 'console', 'process', 'module',
    'require', 'exports',
})
# Instance variable names that are framework-injected — skip for service resolution
_SKIP_INSTANCE_NAMES = frozenset({
    'ctx', 'context', 'this', 'req', 'res', 'next',
    'console', 'process', 'module',
})

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

        # Build import_map and var_type_map from source text for service resolution
        source_text = self._get_source_text(jsContent)
        file_path = None
        try:
            file_path = str(jsContent.get_file().get_path())
        except Exception:
            pass
        import_map = self._build_import_map(source_text)
        var_type_map = self._build_var_type_map(source_text)

        log.info('[GraphQL NodeJs] _extract_resolvers: file=' + str(file_path)
                 + ' resolvers_found=' + str(len(found))
                 + ' source_text=' + ('None' if source_text is None
                                      else str(len(source_text)) + 'chars')
                 + ' import_map=' + str(len(import_map or {}))
                 + ' var_type_map=' + str(len(var_type_map or {}))
                 + ' context_key_map=' + str(len(self._context_key_to_class)))

        # Dedup within file: keep first occurrence of each (op_type, field_name)
        seen = set()
        _diag_body_ok = 0
        _diag_body_empty = 0
        for op_type, field_name, key_node, value_node in found:
            pair = (op_type, field_name)
            if pair not in seen:
                seen.add(pair)
                field_body = self._body_text_from_value_node(value_node, source_text)
                if field_body:
                    _diag_body_ok += 1
                else:
                    _diag_body_empty += 1
                    # Diagnostic: why is body empty?
                    try:
                        bl = value_node.get_begin_line()
                    except Exception:
                        bl = '(exception)'
                    log.info('[GraphQL NodeJs] DIAG empty body for '
                             + op_type + '.' + field_name
                             + ' begin_line=' + str(bl)
                             + ' source_text=' + ('None' if source_text is None
                                                  else str(len(source_text)) + 'chars')
                             + ' value_node_type=' + str(type(value_node).__name__))
                self._create_resolver(op_type, field_name, key_node,
                                      value_node, jsContent,
                                      import_map, var_type_map, file_path,
                                      field_body=field_body)
        if found:
            log.info('[GraphQL NodeJs] _extract_resolvers file=' + str(file_path)
                     + ' total=' + str(len(seen))
                     + ' body_ok=' + str(_diag_body_ok)
                     + ' body_empty=' + str(_diag_body_empty)
                     + ' source_text=' + ('None' if source_text is None
                                          else str(len(source_text)) + 'chars'))

    def _build_import_map(self, source_text):
        """Build {ClassName: relative_path} from ES6 imports and CommonJS requires."""
        import_map = {}
        if not source_text:
            return import_map
        # ES6 imports
        for m in _ES6_IMPORT_RE.finditer(source_text):
            named_group = m.group(1)   # e.g. "UserService, AdminService as AS"
            default_name = m.group(2)  # default import
            path = m.group(3)
            if named_group:
                for part in named_group.split(','):
                    part = part.strip()
                    if ' as ' in part:
                        local_name = part.split(' as ', 1)[1].strip()
                    else:
                        local_name = part
                    if local_name and local_name[0].isupper():
                        import_map[local_name] = path
            elif default_name and default_name[0].isupper():
                import_map[default_name] = path
        # CommonJS requires
        for m in _CJS_REQUIRE_RE.finditer(source_text):
            named_group = m.group(1)
            single_name = m.group(2)
            path = m.group(3)
            if named_group:
                for part in named_group.split(','):
                    part = part.strip()
                    if ' as ' in part:
                        local_name = part.split(' as ', 1)[1].strip()
                    else:
                        local_name = part
                    if local_name and local_name[0].isupper():
                        import_map[local_name] = path
            elif single_name and single_name[0].isupper():
                import_map[single_name] = path
        return import_map

    def _build_var_type_map(self, source_text):
        """
        Build {instanceVar: ClassName} from as many JS patterns as are regex-detectable.

        Sources (first-seen wins; applied in precedence order):
          1. const/let/var foo = new Foo()      — direct instantiation
          2. this.foo = new Foo()               — constructor body assignment
          3. @type {Foo} ... const foo = ...    — JSDoc type annotation
          4. const foo = Foo.getInstance()      — singleton / factory
          5. const { foo } = ctx               — context destructuring
          6. this.foo = foo  (same name)        — constructor DI heuristic
        """
        var_type_map = {}
        if not source_text:
            return var_type_map

        def _add(var_name, cls_name, src):
            """Insert into map (first-seen wins) and log each new entry."""
            try:
                if var_name and cls_name and var_name not in var_type_map:
                    var_type_map[var_name] = cls_name
                    log.info('[GraphQL NodeJs] var_type_map %-16s %s → %s'
                             % (src, var_name, cls_name))
            except Exception as e:
                log.warning('[GraphQL NodeJs] var_type_map _add error (%s): %s' % (src, e))

        # ── Source 1: const/let/var foo = new Foo() ──────────────────────────
        try:
            for m in _NEW_INSTANCE_RE.finditer(source_text):
                _add(m.group(1), m.group(2), '[new]')
        except Exception as e:
            log.warning('[GraphQL NodeJs] var_type_map source1 (new): ' + str(e))

        # ── Source 2: this.foo = new Foo() ───────────────────────────────────
        # Adds both bare 'foo' (for local calls) and 'this.foo' (for class methods).
        try:
            for m in _THIS_NEW_INSTANCE_RE.finditer(source_text):
                prop, cls = m.group(1), m.group(2)
                _add(prop,           cls, '[this.new]')
                _add('this.' + prop, cls, '[this.new]')
        except Exception as e:
            log.warning('[GraphQL NodeJs] var_type_map source2 (this.new): ' + str(e))

        # ── Source 3: JSDoc  @type {Foo} … const foo = … ─────────────────────
        try:
            for m in _JSDOC_TYPE_RE.finditer(source_text):
                _add(m.group(2), m.group(1), '[jsdoc]')
        except Exception as e:
            log.warning('[GraphQL NodeJs] var_type_map source3 (jsdoc): ' + str(e))

        # ── Source 4: Foo.getInstance() / Foo.create() / etc. ────────────────
        try:
            for m in _SINGLETON_INSTANCE_RE.finditer(source_text):
                _add(m.group(1), m.group(2), '[singleton]')
        except Exception as e:
            log.warning('[GraphQL NodeJs] var_type_map source4 (singleton): ' + str(e))

        # ── Source 5: const { foo, bar: localBar } = ctx / context ───────────
        # Class resolved from Phase-0 _context_key_to_class; PascalCase fallback.
        try:
            for m in _CTX_DESTRUCTURE_RE.finditer(source_text):
                try:
                    for part in m.group(1).split(','):
                        part = part.strip()
                        if not part:
                            continue
                        if ':' in part:
                            orig_key, local_name = (p.strip() for p in part.split(':', 1))
                        else:
                            orig_key = local_name = part
                        if not orig_key or not local_name:
                            continue
                        cls_name = self._context_key_to_class.get(orig_key)
                        if not cls_name:
                            # PascalCase heuristic: accountService → AccountService
                            cls_name = orig_key[0].upper() + orig_key[1:]
                        _add(local_name, cls_name, '[ctx-destr]')
                except Exception as e:
                    log.warning('[GraphQL NodeJs] var_type_map source5 inner: ' + str(e))
        except Exception as e:
            log.warning('[GraphQL NodeJs] var_type_map source5 (ctx-destructure): ' + str(e))

        # ── Source 6: this.foo = foo  (constructor DI, same name on both sides) ──
        # Heuristic: capitalize param name → class guess (fooService → FooService).
        try:
            for m in _THIS_PARAM_ASSIGN_RE.finditer(source_text):
                prop_name, param_name = m.group(1), m.group(2)
                if prop_name == param_name:
                    cls_guess = param_name[0].upper() + param_name[1:]
                    _add(prop_name,           cls_guess, '[ctor-di]')
                    _add('this.' + prop_name, cls_guess, '[ctor-di]')
        except Exception as e:
            log.warning('[GraphQL NodeJs] var_type_map source6 (ctor-di): ' + str(e))

        # ── Summary ──────────────────────────────────────────────────────────
        if var_type_map:
            pairs = ', '.join(k + '→' + v for k, v in list(var_type_map.items())[:8])
            log.info('[GraphQL NodeJs] var_type_map: %d entries — %s'
                     % (len(var_type_map), pairs))
        else:
            log.info('[GraphQL NodeJs] var_type_map: empty (no instance patterns found)')

        return var_type_map

    def _resolve_service_file(self, class_name, import_map, file_path):
        """Resolve class_name to an absolute service file path via import_map."""
        if not import_map or not file_path:
            return None
        relative_path = import_map.get(class_name)
        if not relative_path:
            return None
        resolver_dir = os.path.dirname(file_path)
        for ext in ('', '.js', '/index.js'):
            candidate = os.path.normpath(
                os.path.join(resolver_dir, relative_path + ext))
            if os.path.exists(candidate):
                return candidate
        # Fallback: assume .js extension even if file doesn't exist on disk
        return os.path.normpath(os.path.join(resolver_dir, relative_path + '.js'))

    def _extract_brace_content(self, text, brace_start):
        """
        Extract content between balanced braces starting at brace_start.
        Returns the content string (excluding outer braces), or None if unbalanced.
        Skips string literals to avoid false brace matches.
        """
        try:
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
                    quote = ch
                    i += 1
                    while i < len(text) and text[i] != quote:
                        if text[i] == '\\':
                            i += 1
                        i += 1
                i += 1
            return None
        except Exception as e:
            log.warning('[GraphQL NodeJs] _extract_brace_content: failed at pos '
                        + str(brace_start) + ': ' + str(e))
            return None

    def _body_text_from_value_node(self, value_node, source_text, window=500):
        """
        Extract the resolver function body as raw source text.

        Uses value_node.get_begin_line() to anchor into source_text, then
        brace-matches for the full body — mirrors _extract_ts_resolvers in the TS
        analyzer. Falls back to a 500-char slice for arrow functions without braces
        (e.g. fieldName: (args) => expr).

        Returns '' if position info is unavailable or source_text is None.
        """
        if not source_text:
            log.info('[GraphQL NodeJs] _body_text_from_value_node: source_text is None/empty')
            return ''
        try:
            begin_line = value_node.get_begin_line()
        except Exception as e:
            log.warning('[GraphQL NodeJs] _body_text_from_value_node: '
                        'get_begin_line() failed: ' + str(e))
            return ''
        if not begin_line or begin_line < 1:
            log.info('[GraphQL NodeJs] _body_text_from_value_node: '
                     'invalid begin_line=' + str(begin_line))
            return ''
        try:
            # Convert 1-indexed line number to char offset (same arithmetic as TS analyzer)
            char_offset = 0
            for i, line in enumerate(source_text.split('\n')):
                if i + 1 >= begin_line:
                    break
                char_offset += len(line) + 1
            remaining = source_text[char_offset:]
            # Diagnostic: log first 200 chars of remaining to see what we're working with
            log.info('[GraphQL NodeJs] _body_text_from_value_node: begin_line='
                     + str(begin_line) + ' char_offset=' + str(char_offset)
                     + ' remaining[:200]=' + repr(remaining[:200]))
            # For arrow functions, skip past => to avoid matching parameter
            # destructuring (e.g. { id } in `async (_, { id }, ctx) => { ... }`)
            # as the function body.
            arrow_pos = remaining.find('=>')
            if arrow_pos != -1:
                after_arrow = remaining[arrow_pos + 2:]
                open_brace = after_arrow.find('{')
                if open_brace != -1:
                    body = self._extract_brace_content(after_arrow, open_brace)
                    if body is not None:
                        log.info('[GraphQL NodeJs] _body_text_from_value_node: '
                                 'arrow-fn brace-matched body, len=' + str(len(body))
                                 + ' (begin_line=' + str(begin_line) + ')')
                        return body
                    log.info('[GraphQL NodeJs] _body_text_from_value_node: '
                             'unbalanced braces after => at begin_line=' + str(begin_line)
                             + ' — falling back to ' + str(window) + '-char slice')
                else:
                    # Arrow function without braces (=> expr) — use slice after =>
                    log.info('[GraphQL NodeJs] _body_text_from_value_node: '
                             'arrow fn without braces at begin_line=' + str(begin_line)
                             + ' — using ' + str(window) + '-char slice after =>')
                    return after_arrow[:window]
            # No arrow: regular function — first { is the body
            open_brace = remaining.find('{')
            if open_brace != -1:
                body = self._extract_brace_content(remaining, open_brace)
                if body is not None:
                    log.info('[GraphQL NodeJs] _body_text_from_value_node: '
                             'brace-matched body, len=' + str(len(body))
                             + ' (begin_line=' + str(begin_line) + ')')
                    return body
                log.info('[GraphQL NodeJs] _body_text_from_value_node: '
                         'unbalanced braces at begin_line=' + str(begin_line)
                         + ' — falling back to ' + str(window) + '-char slice')
            else:
                log.info('[GraphQL NodeJs] _body_text_from_value_node: '
                         'no opening brace at begin_line=' + str(begin_line)
                         + ' (arrow fn?) — using ' + str(window) + '-char slice')
            # Fallback: fixed slice for bodyless arrow functions (=> expr)
            return remaining[:window]
        except Exception as e:
            log.warning('[GraphQL NodeJs] _body_text_from_value_node: '
                        'body extraction failed at begin_line=' + str(begin_line)
                        + ': ' + str(e))
            return ''

    def _extract_service_call(self, field_body,
                              import_map=None, var_type_map=None, file_path=None):
        """
        Extract (serviceClass, serviceMethod, serviceFilePath) from a resolver function body.

        Priority 1 — Direct class call: ClassName.methodName(
        Priority 2 — Instance call:     instanceVar.methodName(  resolved via var_type_map
        Priority 3 — Context fallback:  ctx/context.key.methodName(  resolved via _context_key_to_class

        Returns (serviceClass, serviceMethod, serviceFilePath), any element may be None.
        """
        try:
            body_text = field_body or ''
            if not body_text:
                log.info('[GraphQL NodeJs] _extract_service_call: empty field_body')
                return (None, None, None)

            # Priority 1 — Direct class call (UpperCamelCase.method)
            # Guard: class must be in import_map (when available) to avoid false positives
            # like Error.captureStackTrace( or Symbol.iterator( blocking P2/P3.
            m = _JS_DIRECT_CLASS_RE.search(body_text)
            if m:
                cls_name = m.group(1)
                method_name = m.group(2)
                if cls_name in _SKIP_CLASS_NAMES:
                    log.info('[GraphQL NodeJs] service_call: P1 skipped builtin '
                             + cls_name)
                elif import_map is not None and cls_name not in import_map:
                    log.info('[GraphQL NodeJs] service_call: P1 skipped "{}" '
                             '(not in import_map) — trying P2/P3'.format(cls_name))
                else:
                    service_file_path = self._resolve_service_file(
                        cls_name, import_map, file_path)
                    log.info('[GraphQL NodeJs] service_call: P1 {}.{} → {}'.format(
                             cls_name, method_name, service_file_path))
                    return (cls_name, method_name, service_file_path)

            # Priority 2a — this.property.method(  (class method body calling injected service)
            if var_type_map:
                m = _JS_THIS_INSTANCE_CALL_RE.search(body_text)
                if m:
                    prop_name = m.group(1)
                    method_name = m.group(2)
                    cls_name = var_type_map.get('this.' + prop_name) or var_type_map.get(prop_name)
                    if cls_name:
                        service_file_path = self._resolve_service_file(
                            cls_name, import_map, file_path)
                        log.info('[GraphQL NodeJs] _extract_service_call P2a this.'
                                 + prop_name + '→' + cls_name + '.' + method_name
                                 + ' → ' + str(service_file_path))
                        return (cls_name, method_name, service_file_path)
                    else:
                        log.info('[GraphQL NodeJs] _extract_service_call P2a: this.'
                                 + prop_name + ' not in var_type_map')

            # Priority 2 — Instance call (lowerCase.method) resolved via var_type_map
            if var_type_map:
                m = _JS_INSTANCE_CALL_RE.search(body_text)
                if m:
                    instance_var = m.group(1)
                    method_name = m.group(2)
                    if instance_var not in _SKIP_INSTANCE_NAMES:
                        cls_name = var_type_map.get(instance_var)
                        if cls_name:
                            service_file_path = self._resolve_service_file(
                                cls_name, import_map, file_path)
                            log.info('[GraphQL NodeJs] _extract_service_call P2: '
                                     + instance_var + '→' + cls_name + '.' + method_name
                                     + ' → ' + str(service_file_path))
                            return (cls_name, method_name, service_file_path)
                        else:
                            log.info('[GraphQL NodeJs] _extract_service_call P2: '
                                     + instance_var + ' not in var_type_map '
                                     + str(list(var_type_map.keys())[:10]))
                    else:
                        log.info('[GraphQL NodeJs] _extract_service_call P2: skipped '
                                 + instance_var + ' (framework var)')

            # Priority 3 — Fallback: ctx/context.key.method(
            m = _JS_SERVICE_CALL_RE.search(body_text)
            if m:
                ctx_key = m.group(1)
                method = m.group(2)
                cls = self._context_key_to_class.get(ctx_key)
                if not cls:
                    # PascalCase heuristic: userService → UserService
                    cls = ctx_key[0].upper() + ctx_key[1:] if ctx_key else ctx_key
                log.info('[GraphQL NodeJs] _extract_service_call P3 ctx: '
                         + ctx_key + '→' + cls + '.' + method)
                return (cls, method, None)

            log.info('[GraphQL NodeJs] _extract_service_call: no match. '
                     'import_map keys=' + str(list((import_map or {}).keys())[:10])
                     + ' var_type_map keys=' + str(list((var_type_map or {}).keys())[:10])
                     + ' body[:120]=' + repr(body_text[:120]))

        except Exception as e:
            log.warning('[GraphQL NodeJs] _extract_service_call: unexpected error: ' + str(e))
        return (None, None, None)

    def _create_resolver(self, op_type, field_name, ast_node, value_node, jsContent,
                         import_map=None, var_type_map=None, file_path=None,
                         field_body=None):
        """Create a JsNodeJsResolver* KB object for one resolver function."""
        try:
            parent_kb = jsContent.get_kb_object()
            if parent_kb is None:
                self._failed += 1
                return

            # Determine the correct KB type
            resolver_type = _OPERATION_TYPE_TO_JS_TYPE.get(op_type, 'JsNodeJsResolverCustom')

            try:
                begin_line = ast_node.get_begin_line()
            except Exception as bl_e:
                log.warning('[GraphQL NodeJs] _create_resolver: get_begin_line() failed for "'
                            + op_type + '.' + field_name + '": ' + str(bl_e))
                begin_line = None
            fullname = (file_path or '') + ':' + str(begin_line)

            obj = CustomObject()
            obj.set_name(field_name)
            obj.set_type(resolver_type)
            obj.set_fullname(fullname)
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
            service_class, service_method, service_file_path = self._extract_service_call(
                field_body, import_map, var_type_map, file_path)
            if service_class:
                obj.save_property('GraphQL_NodeJs_Resolver.serviceClass', service_class)
            if service_method:
                obj.save_property('GraphQL_NodeJs_Resolver.serviceMethod', service_method)
            if service_file_path:
                obj.save_property('GraphQL_NodeJs_Resolver.serviceFilePath', service_file_path)

            self._created += 1
            log.info('[GraphQL NodeJs] Created ' + resolver_type + ': '
                     + op_type + '.' + field_name
                     + (' → ' + str(service_class) + '.' + str(service_method)
                        if service_class else ''))

        except Exception as e:
            log.warning('[GraphQL NodeJs] Failed resolver "'
                        + op_type + '.' + field_name + '": ' + str(e))
            self._failed += 1
