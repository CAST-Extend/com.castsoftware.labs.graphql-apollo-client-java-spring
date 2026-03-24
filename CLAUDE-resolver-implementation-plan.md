# Apollo Server Resolver Detection & Service Linking — Implementation Plan

**Date:** 2026-03-17
**Status:** Design complete, implementation not started
**Context:** This plan was defined in session 6 through a detailed Q&A discussion.

---

## 1. Objective

Extend the CAST GraphQL extension to detect **Apollo Server resolver functions** in both TypeScript
and JavaScript source files, create typed KB objects for each resolver, and **link each resolver to
the service method it calls** (e.g., `getInterestRates` → `InterestService.findAll`).

This completes the full-stack transaction chain:
```
React Hook → GqlTemplate → GraphQLField (schema) → NodeJsResolver → Service Method
```

The extension already handles the first three steps. This plan covers the last two.

---

## 2. Resolver Declaration Patterns to Support

### 2.1 The Standard Pattern (covers 95%+ of real code)

An object literal with `Query`, `Mutation`, `Subscription` as top-level keys, and optionally
custom GraphQL type names (e.g., `User`, `InterestRate`) for field resolvers.

```js
const resolvers = {
  Query: {
    getUsers: (parent, args, ctx) => ctx.userService.findAll(),
    getUser: async (parent, { id }, ctx) => ctx.userService.findById(id),
  },
  Mutation: {
    createUser: async (parent, { input }, ctx) => ctx.userService.create(input),
  },
  Subscription: {
    onUserCreated: {
      subscribe: () => pubsub.asyncIterator(['USER_CREATED']),
    },
  },
  User: {
    posts: (parent, args, ctx) => ctx.postService.findByUserId(parent.id),
  },
}
```

### 2.2 Function Syntax Variants (all detected by keying on object property names, not function form)

```js
// Arrow function (most common)
getUsers: (parent, args, ctx) => ctx.userService.findAll(),

// Async arrow function
getUsers: async (parent, args, ctx) => { return ctx.userService.findAll(); },

// Method shorthand
getUsers(parent, args, ctx) { return ctx.userService.findAll(); },

// Async function expression
getUsers: async function(parent, args, ctx) { return ctx.userService.findAll(); },
```

The analyzer detects **the property key name** (`getUsers`), NOT the function syntax.
All variants above produce the same KB object.

### 2.3 Subscription with `subscribe` + `resolve` (special case)

```js
Subscription: {
  onUserCreated: {
    subscribe: withFilter(
      () => pubsub.asyncIterator(['USER_CREATED']),
      (payload, variables) => payload.onUserCreated.branchId === variables.branchId
    ),
    resolve: (payload) => payload.onUserCreated,
  },
}
```

The resolver field name is `onUserCreated` (the outer key), NOT `subscribe` or `resolve`.
The `_SKIP_FIELD_NAMES` set (`__resolveType`, `__isTypeOf`, `subscribe`) prevents creating
resolver objects for meta-keys.

### 2.4 TS-Specific Patterns

TypeScript resolvers use the same object literal pattern but with type annotations:

```ts
export const userResolvers: IResolvers = {
  Query: {
    getUser: async (_: unknown, { id }: { id: string }, context: AuthContext) => {
      return UserService.findById(id);
    },
  },
}
```

Key difference from JS: TS resolvers typically call **static methods on imported classes**
(`UserService.findById(id)`) rather than using context injection (`ctx.userService.findById(id)`).

### 2.5 Merged Resolvers (NO special handling needed)

```ts
// server.ts
const resolvers = mergeResolvers([userResolvers, accountResolvers, ...])
```

Each file declares its own `{ Query: {...}, Mutation: {...} }` object. The analyzer processes
files independently — the merge in `server.ts` is irrelevant for detection.

### 2.6 Patterns Explicitly NOT Supported

| Pattern | Reason |
|---------|--------|
| TypeGraphQL / NestJS decorators (`@Resolver`, `@Query()`) | Different framework entirely; needs its own analyzer |
| `makeExecutableSchema({ typeDefs, resolvers })` | Wiring call, not a resolver declaration |
| `addResolversToSchema()` | Same — wiring, not declaration |
| Resolver classes without decorators | Too ambiguous to detect statically |
| SDL-first with directive resolvers | Extremely rare |

---

## 3. KB Object Taxonomy

### 3.1 Types to CREATE (10 new types)

**Resolver types (8) — replace the current single `NodeJsResolver` (rid 60):**

| Type | rid | Description | `operationType` property |
|------|-----|-------------|--------------------------|
| `TsNodeJsResolverQuery` | 61 | TS Query resolver | Not set (type implies it) |
| `TsNodeJsResolverMutation` | 62 | TS Mutation resolver | Not set |
| `TsNodeJsResolverSubscription` | 63 | TS Subscription resolver | Not set |
| `TsNodeJsResolverCustom` | 64 | TS custom field resolver (e.g., `User.posts`) | Set to type name (e.g., `"User"`) |
| `JsNodeJsResolverQuery` | 65 | JS Query resolver | Not set |
| `JsNodeJsResolverMutation` | 66 | JS Mutation resolver | Not set |
| `JsNodeJsResolverSubscription` | 67 | JS Subscription resolver | Not set |
| `JsNodeJsResolverCustom` | 68 | JS custom field resolver | Set to type name |

**Schema types (2) — replace the current single `NodeJsApolloSchema` (rid 59):**

| Type | rid | Description |
|------|-----|-------------|
| `TsNodeJsApolloSchema` | 69 | TS inline typeDefs |
| `JsNodeJsApolloSchema` | 70 | JS inline typeDefs |

### 3.2 Types to DELETE

| Type | rid | Replaced by |
|------|-----|-------------|
| `NodeJsResolver` | 60 | 8 specific resolver types above |
| `NodeJsApolloSchema` | 59 | `TsNodeJsApolloSchema` + `JsNodeJsApolloSchema` |

### 3.3 Category (KEEP and EXTEND)

`GraphQL_NodeJs_Resolver` (rid 58) stays as the shared category for all 8 resolver types.

**Existing properties:**
- `operationType` (rid 107) — only used on `*Custom` types
- `fieldName` (rid 108) — the GraphQL field name (e.g., `"getInterestRates"`)

**New properties to add:**
- `serviceClass` (rid 110) — the class name of the service called (e.g., `"InterestService"`)
- `serviceMethod` (rid 111) — the method name of the service called (e.g., `"findAll"`)

### 3.4 KB Object Naming

Resolver KB objects are named by **field name only** (NOT qualified):
- `"getInterestRates"` (not `"Query.getInterestRates"`)

Rationale: the type already encodes the operation type (Query/Mutation/Subscription/Custom).
If a collision occurs (same field name under Query and Mutation), the different KB object types
prevent dedup issues.

### 3.5 Links Created

| Link type | From → To | Level | Matching strategy |
|-----------|-----------|-------|-------------------|
| `callLink` | `GraphQLField` → `*NodeJsResolver*` | Application | `fieldName` + operation type |
| `callLink` | `*NodeJsResolver*` → `CAST_TS_Method` or `CAST_HTML5_JavaScript_Method` / `CAST_HTML5_JavaScript_Generic_Method` | Application | `(serviceClass, serviceMethod)` → `(parent_class_from_fullname, method_name)` |

---

## 4. Service Linking Strategy

### 4.1 Extraction of `(serviceClass, serviceMethod)` at Analyzer Level

**TS resolvers** call static methods on imported classes:
```ts
return UserService.findById(id);
```
Regex: `(\w+)\.(\w+)\s*\(` applied to the resolver function body.
Extracts: `serviceClass = "UserService"`, `serviceMethod = "findById"`.

**JS resolvers** call methods via context injection:
```js
ctx.interestService.findAll(args.filter)
```
Regex: `ctx\.(\w+)\.(\w+)\s*\(` applied to the resolver function body.
Extracts: `contextKey = "interestService"`, `serviceMethod = "findAll"`.

To resolve `contextKey → serviceClass`, scan for `new ClassName()` bindings:
```js
// Pattern 1: object property (context factory)
context: { interestService: new InterestService(db), ... }

// Pattern 2: variable assignment
const interestService = new InterestService(db);
```
Regex for both: `(\w+)\s*[:=]\s*new\s+(\w+)\s*\(`
Produces map: `{"interestService": "InterestService", "userService": "UserService", ...}`

Then: `serviceClass = contextKeyToClass["interestService"]` = `"InterestService"`.

### 4.2 Application-Level Matching

At `end_application`, build an index of all service methods:

```python
method_index = {}  # (class_name, method_name) → KB object

for obj in application.search_objects(load_properties=True):
    if obj.get_type() in ('CAST_TS_Method',
                          'CAST_HTML5_JavaScript_Method',
                          'CAST_HTML5_JavaScript_Generic_Method'):
        fullname = obj.get_fullname()   # e.g., "services/user.service.UserService.findById"
        parts = fullname.split('.')
        if len(parts) >= 2:
            class_name = parts[-2]      # "UserService"
            method_name = obj.get_name() # "findById"
            method_index[(class_name, method_name)] = obj
```

For each resolver KB object:
```python
service_class = resolver.get_property('GraphQL_NodeJs_Resolver.serviceClass')
service_method = resolver.get_property('GraphQL_NodeJs_Resolver.serviceMethod')
if (service_class, service_method) in method_index:
    create_link('callLink', resolver, method_index[(service_class, service_method)])
```

### 4.3 Disambiguation Power

The `(class_name, method_name)` pair is virtually always unique:
- `("UserService", "findById")` — only one such pair in the codebase
- Even `("InterestService", "findAll")` vs `("UserService", "findAll")` are distinct

This avoids the problem of matching by `method_name` alone (10+ `findAll` methods across services).

### 4.4 Known Limitations (accepted)

| Case | Result | Frequency |
|------|--------|-----------|
| DataSource pattern: `ctx.dataSources.interestAPI.getAll()` | Not detected | Rare in Apollo Server 4+ |
| DI frameworks (InversifyJS, tsyringe) | Not detected | Rare in Apollo ecosystem |
| Dynamic services: `ctx[key][method]()` | Impossible statically | Extremely rare |
| Factory pattern: `createService(InterestService)` | Not detected | Rare |
| Import rename: `import { InterestService as IS }` | Only if `IS` is used in `new IS()` | Handleable via regex |
| `new ClassName()` in a separate factory file (not server.js/context) | Missed by context scan | Uncommon |

**Estimated coverage: 95%+ for real Apollo Server projects.**

### 4.5 What Was Considered and Rejected

| Approach | Why rejected |
|----------|-------------|
| Match by `method_name` alone | Too many false positives (multiple `findAll`, `create`, `update` across services) |
| Parse the `context` factory in `server.ts`/`server.js` to map context keys → classes | Added as a SUPPORTED approach (Section 4.1), not rejected |
| File naming convention (`interest.service.ts` → `InterestService`) | Heuristic, less reliable than `new ClassName()` binding |
| Single `NodeJsResolver` type with `operationType` property | Rejected because Imaging viewer cannot filter by property value in the tree — separate types enable filtering |
| `operationType` on Query/Mutation/Subscription types | Redundant — the type itself encodes the operation. Only `*Custom` needs it |
| Qualified KB name (`"Query.getInterestRates"`) | Unnecessary — different types prevent collisions. Simpler names are easier to match |

---

## 5. Implementation Order

### Phase 1 — Metamodel Changes

**File:** `configuration/Languages/GraphQL/GraphQLMetaModel.xml`

1. Add `serviceClass` (rid 110) and `serviceMethod` (rid 111) properties to category
   `GraphQL_NodeJs_Resolver` (rid 58)
2. Remove type `NodeJsResolver` (rid 60)
3. Remove type `NodeJsApolloSchema` (rid 59)
4. Add 8 resolver types: `TsNodeJsResolverQuery` (61), `TsNodeJsResolverMutation` (62),
   `TsNodeJsResolverSubscription` (63), `TsNodeJsResolverCustom` (64),
   `JsNodeJsResolverQuery` (65), `JsNodeJsResolverMutation` (66),
   `JsNodeJsResolverSubscription` (67), `JsNodeJsResolverCustom` (68)
5. Add 2 schema types: `TsNodeJsApolloSchema` (69), `JsNodeJsApolloSchema` (70)

### Phase 2 — JS Analyzer Update (resolver detection)

**File:** `graphql_nodejs_analyzer.py` (currently handles JS only via `com.castsoftware.html5` events)

1. Update `_create_resolver()` to use the 4 `Js*` types instead of single `NodeJsResolver`:
   - `Query` → `JsNodeJsResolverQuery`
   - `Mutation` → `JsNodeJsResolverMutation`
   - `Subscription` → `JsNodeJsResolverSubscription`
   - Anything else → `JsNodeJsResolverCustom` (with `operationType` = the type name)
2. Update `_create_apollo_schema()` to use `JsNodeJsApolloSchema` instead of `NodeJsApolloSchema`
3. Add `serviceClass` + `serviceMethod` extraction:
   - For each resolver, extract `ctx.(\w+)\.(\w+)\s*\(` from the function body
   - Save as properties on the KB object
4. Add context-key-to-class mapping:
   - In Phase 1 (`_extract_typedefs` or a new Phase 0), scan all JS files for
     `(\w+)\s*[:=]\s*new\s+(\w+)\s*\(` to build `context_key_to_class` dict
   - Use this dict to resolve `"interestService"` → `"InterestService"` when saving `serviceClass`
5. Support **custom field resolvers** (e.g., `InterestRate: { rateHistory }`):
   - Extend `_OPERATION_TYPES` or add a separate loop that captures non-Query/Mutation/Subscription
     top-level keys that are object values with function-valued properties
   - Filter out built-in GraphQL scalars and obvious non-resolver keys

### Phase 3 — TS Analyzer for Resolvers (NEW)

**New file or extend:** Need to determine where TS resolver detection runs.

The current `graphql_nodejs_analyzer.py` subscribes to `com.castsoftware.html5` events (JS only).
TS files fire `typescript_file` events handled by `graphql_typescript_analyzer.py`.

Options:
- **Option A:** Add resolver detection to `graphql_typescript_analyzer.py` (in `get_typescript_file`)
- **Option B:** Create a new `graphql_nodejs_ts_analyzer.py` that subscribes to `typescript_file`

**Recommendation: Option A** — add to the existing TS analyzer. The resolver detection logic is
small (regex on source text + KB object creation). No need for a separate file.

Implementation:
1. In `get_typescript_file(source_file)`, after existing GQL definition + hook extraction:
   - Get raw source text
   - Detect resolver map pattern: object with `Query:`, `Mutation:`, `Subscription:` keys
   - For each resolver field, create `TsNodeJsResolver*` KB object
2. Extract `(serviceClass, serviceMethod)` from resolver bodies:
   - TS pattern: `(\w+)\.(\w+)\s*\(` (static class method call)
   - The class name IS the `serviceClass` directly (no context mapping needed for TS)
3. Create `TsNodeJsApolloSchema` for inline `typeDefs` in TS files

**Important:** The TS bundled parser provides AST access. Consider using AST-based detection
(walking `ObjectLiteral` nodes) rather than regex where possible, for robustness.

### Phase 4 — Application-Level Linking (Resolver → Service)

**File:** `graphql_application_level.py`

1. Update `_link_schema_to_nodejs_resolvers()`:
   - Replace `obj.get_type() == 'NodeJsResolver'` with check against all 8 new types
   - For Custom types, use `operationType` property to determine which schema dict to search
2. Add new method `_link_resolvers_to_services()`:
   - Build method index: `(class_name, method_name) → KB object` from
     `CAST_TS_Method`, `CAST_HTML5_JavaScript_Method`, `CAST_HTML5_JavaScript_Generic_Method`
   - For each resolver with `serviceClass` + `serviceMethod` properties set:
     - Look up `(serviceClass, serviceMethod)` in the index
     - If found, `create_link('callLink', resolver_obj, method_obj)`
   - Log stats: matched, unmatched, ambiguous
3. Call `_link_resolvers_to_services()` from `end_application()` after existing link creation

### Phase 5 — Testing

**Cannot run tests in Claude's environment** (CAST `cast` module required).

1. Add test cases to `tests/test_ts.py` for TS resolver detection:
   - Test module: resolver map with Query + Mutation + Subscription + Custom
   - Assert correct number of objects per type
   - Assert `serviceClass` and `serviceMethod` properties
2. Add test input files:
   - `tests/resources/` — sample TS resolver file, sample JS resolver file
3. Ask user to run tests in their CAST IDE environment

### Phase 6 — big_app_test Verification

The `big_app_test/` already contains resolver files in both TS and JS:
- `server/ts/resolvers/*.ts` — 31 files
- `server/js/resolvers/*.js` — 28 files

After implementation, a CAST analysis of `big_app_test/` should produce:
- ~31 × (N query fields + M mutation fields + P subscription fields) `TsNodeJsResolver*` objects
- ~28 × (similar counts) `JsNodeJsResolver*` objects
- `callLink` from each `GraphQLField` to matching resolver
- `callLink` from each resolver to the correct service method

---

## 6. File Inventory (what changes where)

| File | Change |
|------|--------|
| `configuration/Languages/GraphQL/GraphQLMetaModel.xml` | Add 10 types, 2 properties; remove 2 old types |
| `graphql_nodejs_analyzer.py` | Update to use `Js*` types; add service extraction; add custom resolver detection |
| `graphql_typescript_analyzer.py` | Add TS resolver detection + `TsNodeJsResolver*` creation + service extraction |
| `graphql_application_level.py` | Update schema→resolver linking for 8 types; add resolver→service linking |
| `tests/test_ts.py` | Add resolver detection test modules |
| `plugin.nuspec` | Version bump |

---

## 7. Reference: Existing Code to Modify

### `graphql_nodejs_analyzer.py` (current state)

- `_extract_resolvers()` (line 305): walks AST looking for `{ Query: {...}, Mutation: {...} }`
- `_create_resolver()` (line 358): creates `NodeJsResolver` → change to `JsNodeJsResolver*`
- `_create_apollo_schema()` (line 274): creates `NodeJsApolloSchema` → change to `JsNodeJsApolloSchema`
- `_OPERATION_TYPES` (line 45): `('Query', 'Mutation', 'Subscription')` → keep, but add custom detection

### `graphql_application_level.py` (current state)

- `_link_schema_to_nodejs_resolvers()` (line 443): filters by `get_type() == 'NodeJsResolver'`
  → update to check all 8 types
- Uses `operationType` and `fieldName` properties → keep using these

### `graphql_typescript_analyzer.py` (current state)

- `get_typescript_file()` (entry point per `.ts` file): add resolver detection after hook extraction
- Has access to `source_file` (bundled TS parser) — can use AST or raw text

### Metamodel current state

- `GraphQL_NodeJs_Resolver` category (rid 58) with `operationType` (107) and `fieldName` (108)
- `NodeJsApolloSchema` (rid 59) — to be replaced
- `NodeJsResolver` (rid 60) — to be replaced

---

## 8. Full Transaction Chain (end goal)

```
[React/Angular Client]                    [GraphQL Schema]              [Apollo Server]              [Service Layer]

TsGraphQLApolloHookQuery  --useLink-->  TsGqlQuery  --useLink-->  GraphQLField  --callLink-->  TsNodeJsResolverQuery  --callLink-->  CAST_TS_Method
  "useQuery:GetUsers"                   "GetUsers"                 "getUsers"                   "getUsers"                           "UserService.findById"
                                        (fieldsSelected:                (under                     (serviceClass: UserService          (fullname: ...UserService.findById)
                                         "getUsers")                    Query type)                 serviceMethod: findById)
```

This chain is fully traceable in CAST Imaging, enabling:
- Impact analysis: "what client components are affected if I change `UserService.findById`?"
- Transaction tracing: from UI hook down to database service method
- Dependency analysis: which resolvers depend on which services?

---

## 9. Open Items / Future Work

- **DataSource pattern** (`ctx.dataSources.X.method()`) — not in scope, could be added later
- **NestJS / TypeGraphQL decorator-based resolvers** — separate analyzer, not in scope
- **Resolver-level authorization analysis** (detecting `validateRole` calls) — not in scope
- **Multiple service calls per resolver** — current plan extracts only the first
  `ctx.service.method()` call. Could be extended to extract all and create multiple links.
