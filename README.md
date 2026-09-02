# GraphQL for Apollo (TypeScript, JavaScript, Node.js) and Java Spring

**Extension id:** `com.castsoftware.labs.graphql-apollo-client-java-spring`
**Version:** 1.3.15
**Type:** CAST Universal Analyzer extension (analysis level + application level)
**Status:** functional, last verified end-to-end against a real Knowledge Base in **May 2026** on
AIP Core 8.3.x. **Not yet re-verified on CAST Imaging v3** — see [Verification status](#verification-status).

---

## Overview

This extension makes GraphQL traffic visible in CAST Imaging. It detects where an application
*calls* GraphQL, where the GraphQL *schema* is defined, and where each operation is *implemented*
on the backend — then links the three together so a transaction can be followed from a React
component down to a Java method or a Node.js service call.

```
┌─────────────────────┐   useLink    ┌──────────────────┐   useLink   ┌──────────────┐
│  Apollo call site   │─────────────▶│  gql definition  │────────────▶│ GraphQL      │
│  useQuery(GET_USER) │              │  query GetUser   │             │ schema field │
│  this.apollo.query  │              │  (TsGql*/JsGql*) │             │ Query.user   │
│  client.mutate      │              └──────────────────┘             └──────┬───────┘
│  useGetUserQuery()  │                                                      │ callLink
└─────────────────────┘                                                      ▼
        ▲ callLink                                          ┌───────────────────────────────┐
        │                                                   │ Java Spring  @QueryMapping    │
   parent component                                         │ Node.js resolver Query.user   │
                                                            └───────────┬───────────────────┘
                                                                        │ callLink
                                                                        ▼
                                                              service method (TS/JS)
```

### Supported source languages

| Language | File extensions | Detection driven by |
|---|---|---|
| TypeScript | `.ts`, `.tsx` | events from `com.castsoftware.typescript` |
| JavaScript | `.js`, `.jsx`, `.mjs`, `.cjs` | events from `com.castsoftware.html5` |
| GraphQL SDL | `.graphql`, `.gql`, `.graphqls` | this extension's own parser |
| Java | — | read from the KB at application level (requires the Java analyzer) |

---

## Prerequisites

- **CAST AIP Core 8.3.3** or higher (declared in `plugin.nuspec`)
- **`com.castsoftware.typescript`** — required for any `.ts` / `.tsx` detection
- **`com.castsoftware.html5`** — required for any `.js` / `.jsx` detection
- The **Java analyzer**, if you want the schema → Java Spring links

> ⚠️ The two extension dependencies above are **not yet declared** in `plugin.nuspec` (a verified
> minimum version is needed first). If they are absent from the installation, this extension
> produces **no TypeScript and no JavaScript object at all**, and does so silently.

---

## What is detected

### 1. `gql` template definitions

Detected in both TypeScript and JavaScript, as a standalone constant or inline in the call:

```ts
const GET_USER = gql`query GetUser($id: ID!) { user(id: $id) { id name } }`;

const GET_USER: TypedDocumentNode<Data, Vars> = gql`query GetUser { ... }`;   // colon annotation

const GET_USER = gql`query GetUser { ... }` as TypedDocumentNode<Data, Vars>; // as-cast

const GET_USER = useMemo(() => gql`query GetUser { ... }` as TypedDocumentNode<D, V>, [dep]);

const { data } = useQuery(gql`query GetUser { ... }`);                        // inline
```

The KB object is named after the **GraphQL operation name** (`GetUser`), not the variable name.
This keeps names unique when the same constant name is reused in several scopes, and makes
schema matching direct (`operationName` == field name in `type Query`).

**Alias-aware:** the local name bound to the `gql` tag is resolved per file, so
`import gqlTag from 'graphql-tag'` and `import { gql as gqlHelper } from '@apollo/client'`
are both detected.

### 2. Apollo Client call sites

| Pattern | Example | TS object | JS object |
|---|---|---|---|
| React hook | `useQuery(GET_USER)` | `TsGraphQLApolloHookQuery` | `JsGraphQLApolloHookQuery` |
| React hook | `useLazyQuery(SEARCH)` | `TsGraphQLApolloHookLazyQuery` | `JsGraphQLApolloHookLazyQuery` |
| React hook | `useMutation(CREATE)` | `TsGraphQLApolloHookMutation` | `JsGraphQLApolloHookMutation` |
| React hook | `useSubscription(ON_X)` | `TsGraphQLApolloHookSubscription` | `JsGraphQLApolloHookSubscription` |
| Imperative | `client.query({ query: GET_USER })` | `TsGraphQLApolloClientQuery` | `JsGraphQLApolloClientQuery` |
| Imperative | `client.mutate({ mutation: CREATE })` | `TsGraphQLApolloClientMutation` | `JsGraphQLApolloClientMutation` |
| Imperative | `client.subscribe({ query: ON_X })` | `TsGraphQLApolloClientSubscription` | `JsGraphQLApolloClientSubscription` |
| Angular | `this.apollo.query({ query: GET_USER })` | `TsGraphQLApolloAngularQuery` | `JsGraphQLApolloAngularQuery` |
| Angular | `this.apollo.mutate({ mutation: CREATE })` | `TsGraphQLApolloAngularMutation` | `JsGraphQLApolloAngularMutation` |
| Angular | `this.apollo.watchQuery({...}).valueChanges` | `TsGraphQLApolloAngularWatchQuery` | `JsGraphQLApolloAngularWatchQuery` |
| Codegen | `useGetUserQuery()`, `useCreateUserMutation()` | `TsGraphQLApolloCodegenQuery` / `…Mutation` / `…Subscription` | same, `Js…` |

Whitespace and line breaks are irrelevant — the call may be written on one line or spread over
several, with arbitrary indentation.

### 3. Apollo Server (Node.js)

| Pattern | Object created | TS | JS |
|---|---|---|---|
| `const resolvers = { Query: { user: () => … } }` | resolver | `TsNodeJsResolverQuery` | `JsNodeJsResolverQuery` |
| `Mutation: { createUser: … }` | resolver | `TsNodeJsResolverMutation` | `JsNodeJsResolverMutation` |
| `Subscription: { userUpdated: … }` | resolver | `TsNodeJsResolverSubscription` | `JsNodeJsResolverSubscription` |
| field resolvers on a custom type (`User: { posts: … }`) | resolver | `TsNodeJsResolverCustom` | `JsNodeJsResolverCustom` |
| `const typeDefs = gql\`type Query {…}\``, raw string, or `readFileSync('schema.graphql')` | schema | ❌ not implemented | `JsNodeJsApolloSchema` |

Resolver bodies are scanned for the service call they delegate to
(`ctx.userService.findById(...)`, `UserService.findById(...)`, `this.userService.findById(...)`),
which is what produces the resolver → service link.

### 4. GraphQL SDL schema files

`.graphql` / `.gql` / `.graphqls` files are parsed into a full object tree:
`GraphQLProgram`, `GraphQLSchema`, `GraphQLType`, `GraphQLInterface`, `GraphQLEnum`,
`GraphQLEnumValue`, `GraphQLInput`, `GraphQLUnion`, `GraphQLScalar`, `GraphQLDirective`,
`GraphQLField`, `GraphQLArgument`, `GraphQLQuery`, `GraphQLMutation`, `GraphQLSubscription`,
`GraphQLFragment`, `GraphQLVariable`.

### 5. Java Spring backend

At application level, schema fields are matched by name to Java methods carrying
`@QueryMapping`, `@MutationMapping` or `@SubscriptionMapping`.

---

## Links created

| Link | From → To | Created by |
|---|---|---|
| `callLink` | parent component/function → Apollo call site | analysis level (TS/JS) |
| `useLink` | Apollo call site → `gql` definition | analysis level (TS/JS) |
| `callLink` | codegen hook → generated wrapper function | analysis level (TS) |
| `useLink` | `gql` definition → `GraphQLField` (schema) | application level |
| `callLink` | `GraphQLField` → Java method (`@QueryMapping`, …) | application level |
| `callLink` | `GraphQLField` → Node.js resolver | application level |
| `callLink` | Node.js resolver → service method | application level |

### Resolution across files

A call site and the `gql` constant it uses are usually in different files. Resolution is
attempted in three steps, in order:

1. **Scoped, same file** — the scope chain is walked, so an inner declaration shadows an outer one.
2. **Import-aware** — the `import { GET_USER } from './queries'` statement of the calling file is
   resolved to the actual source file, including renamed imports (`as MY_QUERY`).
3. **Global first-seen fallback** — for imports that cannot be resolved (re-exports, star imports).

Anything still unresolved when the analysis ends becomes an explicit placeholder object
(`TsGqlUnresolvedDefinition`, `JsGqlUnresolvedDefinition`, `UnresolvedSchemaField`,
`TsUnresolvedNodeJsResolver`, `JsUnresolvedNodeJsResolver`, `TsUnresolvedServiceMethod`,
`JsUnresolvedServiceMethod`) instead of being dropped. Missing links stay visible in Imaging
rather than silently disappearing.

---

## Properties stored on objects

| Category | Properties |
|---|---|
| `GraphQL_Client_Definition` | `operationName`, `rawQueryText`, `variables`, `fieldsSelected`, `exported` |
| `GraphQL_Hook_Request` | `hookType`, `fetchPolicy`, `errorPolicy` |
| `GraphQL_NodeJs_Resolver` | `operationType`, `fieldName`, `serviceFilePath`, `serviceMethod` |

---

## Known limitations

- **`typeDefs` in TypeScript** is not detected (the JavaScript equivalent is). The metamodel type
  `TsNodeJsApolloSchema` exists but has no producer yet; an implementation plan is in
  `CLAUDE-typedefs-implementation-plan.md`.
- **`useQuery(useMemo(() => gql\`…\`, [dep]))`** — a `useMemo` passed *directly* as the hook
  argument produces no call-site object (it is deliberately skipped rather than producing a
  wrong one). Assigning the `useMemo` to a constant first works.
- **Star imports** (`import * as Queries from './queries'`) fall back to global resolution.
- **Client → schema matching is name-based.** An operation whose name does not match the schema
  field it selects (aliases) relies on `fieldsSelected` and can be missed.
- **No transaction configuration.** `configuration/TCC/Base_GraphQL.TCCSetup` is an empty
  placeholder — no free definition, no entry point is declared by this extension.
- **Icons are incomplete.** Only the SDL schema object types have an icon; the Apollo call-site
  and `gql` definition types render with the default icon in Imaging.
- **Other GraphQL clients** (Relay, URQL, graphql-request) and other backends are not supported.

---

## Verification status

| Item | State |
|---|---|
| Metamodel integrity (68 types, rid/INF_TYPE uniqueness, XML validity) | ✅ verified 2026-09-02 |
| Object types created by the code vs. metamodel | ✅ consistent |
| Python compatibility of the extension code | ✅ compiles from 3.4 to 3.12 |
| End-to-end scan producing objects and links in a KB | ✅ May 2026, AIP Core 8.3.x |
| End-to-end scan on **CAST Imaging v3** | ❌ **not done** |
| Unit tests (`tests/`) | ⚠️ require the `cast` module — runnable only inside a CAST installation |

The bundled TypeScript parser under `typescript_dependencies/` ships native binaries built
against **`python34.dll`**. They are optional (there is a pure-Python fallback), but on any
platform whose embedded Python is not 3.4 the analysis falls back to the slower path.
See [PROVENANCE.md](PROVENANCE.md).

---

## Installation

> Validated on AIP Core 8.3.x / AIP Console standalone. **To be re-validated on CAST Imaging v3** —
> the extension folder and the scan workflow changed between versions.

1. Build the package (requires `nuget.exe` on the `PATH`):
   ```
   plugin-to-nupkg.bat
   ```
2. Copy the resulting `.nupkg` to the console's shared extensions folder, e.g.
   ```
   C:\Cast\ProgramData\CAST\AIP-Console-Standalone\data\shared\extensions\
   ```
3. Run a Fast Scan on the application.
4. Enable the extension for the application, then run a full analysis.
5. Check the analysis log for lines prefixed `[GraphQL]`, `[GraphQL][TS]`, `[GraphQL][JS]` and
   `[GraphQL Application]` — each stage reports how many objects and links it created.

---

## Repository layout

| Path | Role |
|---|---|
| `graphql_analyser_level.py` | UA extension for `.graphql` / `.gql` / `.graphqls` files |
| `graphql_module.py` | SDL parser and schema object builder |
| `graphql_typescript_analyzer.py` | TypeScript call sites, `gql` definitions, TS resolvers |
| `graphql_javascript_analyzer.py` | JavaScript call sites and `gql` definitions |
| `graphql_nodejs_analyzer.py` | Apollo Server detection in JavaScript (`typeDefs`, resolvers) |
| `graphql_application_level.py` | Cross-level linking: client → schema → Java / resolver → service |
| `ts_parser/` | AST walker and result model for the TypeScript side |
| `typescript_dependencies/` | Bundled copy of CAST's TypeScript parser — see [PROVENANCE.md](PROVENANCE.md) |
| `configuration/Languages/GraphQL/` | Metamodel, language pattern, Enlighten icons |
| `res/` | Imaging icons (SVG) |
| `configuration/TCC/` | Transaction configuration (currently empty) |
| `tests/` | Unit tests (require a CAST installation) |
| `cast_graphql_extension_kb_architecture.html` | Visual map of every KB object type and link — open it in a browser |

---

## Release notes

### 1.3.x — March to May 2026
- Node.js resolver detection (TypeScript and JavaScript) with resolver → service method linking
- Unresolved placeholder objects for resolvers, service methods and schema fields
- Source bookmark fixes on all created objects

### 1.2.x — February to March 2026
- **TypeScript support added**, using CAST's bundled TypeScript parser
- `gql` definitions: outline, inline, `: TypedDocumentNode<…>`, `as TypedDocumentNode<…>`,
  `useMemo(() => gql\`…\`)`
- Codegen-generated hooks (`useGetUserQuery`, …)
- Imperative Apollo Client calls (`client.query` / `mutate` / `subscribe`)
- Angular services (`this.apollo.query` / `mutate` / `watchQuery`)
- Separate object types for JavaScript (`Js…`) and TypeScript (`Ts…`)
- Import-aware cross-file resolution between a call site and its `gql` constant
- Alias-aware `gql` tag detection

### 1.0.0 — 22 January 2026
- Initial release: JavaScript Apollo Client → GraphQL schema → Java Spring, with full-stack
  transaction analysis

---

## License

LGPL v3 — see [licenses/COPYING.LESSER.txt](licenses/COPYING.LESSER.txt).
Note that `typescript_dependencies/` contains CAST-authored code redistributed inside this
repository; see [PROVENANCE.md](PROVENANCE.md) for its origin and licensing status.
