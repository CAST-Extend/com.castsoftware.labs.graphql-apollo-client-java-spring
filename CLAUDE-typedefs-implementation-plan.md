# TS-side `typeDefs` Detection — Implementation Plan

> **Goal:** detect Apollo Server `typeDefs` declarations in `.ts` / `.tsx` files and create
> `TsNodeJsApolloSchema` KB objects. The metamodel type (`rid=69`,
> display name *"TS NodeJS Apollo Server inline typeDefs schema"*) already exists in
> [configuration/Languages/GraphQL/GraphQLMetaModel.xml](configuration/Languages/GraphQL/GraphQLMetaModel.xml).
> Zero objects of this type exist in the KB today — the gap is the producer code in
> [graphql_typescript_analyzer.py](graphql_typescript_analyzer.py).

## Why this matters

The JS analyzer at [graphql_nodejs_analyzer.py:_extract_typedefs](graphql_nodejs_analyzer.py#L322)
already does this for `.js` files (9 `JsNodeJsApolloSchema` objects in current KB).
TS server code (`server.ts`, `subscriptions/*.ts`, federation entry points, etc.) is invisible
to CAST Imaging today — there is no object to anchor the schema definition to.

## Constraints

- **The JavaScript analyzer must not be touched.** All work is in `graphql_typescript_analyzer.py`.
- **No new metamodel types needed** — `TsNodeJsApolloSchema` already exists with the right
  inheritance (`UAObject + GraphQL_Artifacts + GraphQL + GraphQL_Module`). No properties to set.
- **Tests cannot be run by Claude** — see `CLAUDE.md`. Verification is via Neo4j queries only.
  After each wave, the user re-scans `BigAppTest7` in CAST Analyzer and Claude inspects the KB.

---

## Wave 1 — Core high-value patterns

Covers ~80% of real-world Apollo Server TS code. Strict server-file gate; structural
detection (not variable-name based) so it catches `const userSchema = ...` as well as
`const typeDefs = ...`.

### Prompt for a fresh Claude Code session

````
Implement TS-side typeDefs detection in graphql_typescript_analyzer.py.

CONTEXT
- Read CLAUDE-typedefs-implementation-plan.md first for full background.
- Read graphql_nodejs_analyzer.py (specifically _extract_typedefs and _is_server_file)
  for the reference implementation on the JS side. Mirror the architecture, not the code —
  the TS parser uses typescript_dependencies (Node objects), the JS parser uses jsContent.
- Read graphql_typescript_analyzer.py to see existing patterns (_extract_ts_resolvers is a
  good template — it reads source_text, uses regex + balanced-brace extraction, creates
  KB objects with set_name / set_type / set_fullname / save / save_position).

DO
1. Add a new method _extract_ts_typedefs(self, source_file) to GraphQLTypeScriptAnalyzer.
2. Call it from get_typescript_file() AFTER _extract_ts_resolvers(), wrapped in try/except
   identical to the existing pattern (warn on failure, continue).
3. Server-file gate: scan source_file.get_imports() and only proceed if any import
   resolves to one of these packages:
     apollo-server, apollo-server-express, apollo-server-core, apollo-server-lambda,
     apollo-server-koa, apollo-server-fastify, apollo-server-hapi, apollo-server-micro,
     apollo-server-azure-functions, @apollo/server, @apollo/server/express4,
     @apollo/subgraph, @graphql-tools/schema, @graphql-tools/merge,
     @graphql-tools/load, @graphql-tools/load-files, graphql-yoga, mercurius
   Use a startswith('apollo-server') fallback to catch any new sub-packages.

4. Detect these source forms (each creates ONE TsNodeJsApolloSchema KB object):

   Form 1 — Inline gql template:
       const typeDefs = gql`type Query { ... }`
     Alias-aware: must call _build_gql_tag_names(source_file) and accept any local name
     bound to gql (e.g. gqlTag, gqlHelper). The existing helper in apollo_interpreter_ts.py
     can be reused — import it.

   Form 2 — Raw template literal (no tag):
       const typeDefs = `type Query { ... }`
     Detect via VariableDeclaration → StringTemplate descendant where there is NO
     gql/alias Identifier sibling. Content must pass SDL validation regex (see below).

   Form 3 — Plain string literal:
       const typeDefs = "type Query { ... }"
       const typeDefs = 'type Query { ... }'
     Detect on raw source_text (regex `(?:const|let|var)\s+(\w+)\s*=\s*["']([^"']{60,})["']`)
     plus SDL validation.

   Form 4 — String concatenation:
       const typeDefs = "type Query {" + "field: String" + "}"
     Detect on raw source_text by finding "(?:const|let|var)\s+(\w+)\s*=\s*(\"[^\"]+\"\s*\+\s*)+",
     then capture all concatenated string parts, join them, and validate as SDL.

   Form 5 — readFileSync single file (named or destructured import of fs.readFileSync):
       const userSchema = readFileSync(path.join(__dirname, '../schemas/x.graphql'), 'utf8')
     Detect with regex on source_text:
       (?:const|let|var)\s+(\w+)\s*=\s*(?:readFileSync|fs\.readFileSync)\s*\(([^)]*\.(?:graphql|gql|graphqls)[^)]*)\)
     The variable name is the captured group 1. Path text doesn't need parsing — just
     create the schema object anchored at the readFileSync call line.

   Form 6 — readFileSync with chained .toString():
       const x = readFileSync(p).toString()
     Same regex as Form 5 with optional `\s*\.toString\(\)` suffix.

   Form 8 — Array literal of multiple typeDefs sources:
       const typeDefs = [userSchema, accountSchema, readFileSync(...)]
     If the variable name on the LHS is one we'd recognize as a typeDefs aggregator AND
     at least one element is a previously-created schema variable or a readFileSync call,
     create ONE TsNodeJsApolloSchema named after the LHS variable.

   Form 9 — @graphql-tools / Apollo helpers:
       const typeDefs = mergeTypeDefs([a, b, c])
       const typeDefs = loadFilesSync(path.join(__dirname, '**/*.graphql'))
       const typeDefs = loadSchemaSync('./schema.graphql', { loaders: [...] })
     Detect with regex:
       (?:const|let|var)\s+(\w+)\s*=\s*(?:mergeTypeDefs|loadFilesSync|loadSchemaSync)\s*\(
     Create one schema object per match, named after the LHS variable.

   Form 11 — Inline in makeExecutableSchema:
       makeExecutableSchema({ typeDefs: gql`...`, resolvers })
       makeExecutableSchema({ typeDefs: combinedTypeDefs, resolvers: combinedResolvers })
     Use regex on source_text to find `makeExecutableSchema\s*\(\s*\{` then balanced-brace
     extract the object, then regex for `typeDefs\s*:\s*[^,}]+`. Create one schema object
     with synthetic name `makeExecutableSchema@<line>`.

   Form 12 — Inline in new ApolloServer:
       new ApolloServer({ typeDefs: gql`...`, resolvers })
     Same approach as Form 11, synthetic name `ApolloServer@<line>`.

5. SDL validation regex (apply to extracted content for forms 2, 3, 4 to avoid false positives):
       \b(type|extend\s+type|input|enum|interface|union|scalar|directive|schema)\s+\w+
     If the content does not match, skip the candidate.

6. Deduplication: maintain a per-file set of (variable_name, line_number) seen during the
   call; skip duplicates. Don't dedup across files — same variable name in different files
   must create separate KB objects.

7. KB object creation (mirror _create_ts_resolver style):
       obj = CustomObject()
       obj.set_name(variable_name_or_synthetic)
       obj.set_type('TsNodeJsApolloSchema')
       obj.set_fullname(file_path + ':' + str(line_num))
       obj.set_parent(source_file.get_kb_object())
       obj.save()
       obj.save_position(Bookmark(source_file.get_file(), begin_line, 1, end_line, 1))
     Record in self.created_objects for the end-of-analysis summary.

8. Log every detection with _glog('RESULT', 'Schema', _ctx(), '...').
   Log every skipped candidate at log.info level so we can debug missed detections.

DO NOT
- Do not change graphql_javascript_analyzer.py or graphql_nodejs_analyzer.py.
- Do not modify the metamodel.
- Do not add properties to the schema object beyond what set_name / set_type / set_parent /
  set_fullname / save_position provide — the metamodel does not define any.
- Do not implement async readFileSync (await fs.promises.readFile), graphql-loader imports
  (import typeDefs from './schema.graphql'), or buildSubgraphSchema federation — those are
  Wave 2 / Wave 3.

VERIFY
After implementing, run the verification queries in the "Wave 1 verification" section of
CLAUDE-typedefs-implementation-plan.md. Tell the user which queries to run and what
counts to expect.
````

### Wave 1 verification (Neo4j)

> Neo4j connection: see the local Imaging endpoint and credentials in CLAUDE.md (not versioned).

```cypher
// 1. The object type now has entries — should be > 0 (expected ~30-50 from BigAppTest7)
MATCH (n) WHERE n.Type = "TS NodeJS Apollo Server inline typeDefs schema"
RETURN n.Name, n.FullName ORDER BY n.FullName LIMIT 50
```

```cypher
// 2. Coverage by source form — look at the variable names to confirm all forms hit
MATCH (n) WHERE n.Type = "TS NodeJS Apollo Server inline typeDefs schema"
RETURN n.Name AS schema_name, count(*) AS count
ORDER BY count DESC LIMIT 30
```

```cypher
// 3. No regression in existing TS detection — these counts must stay stable
MATCH (n) WHERE n.Type IN [
  "TS GraphQL gql Query Definition",       // expected ~4648
  "TS GraphQL gql Mutation Definition",     // expected ~4329
  "TS Apollo useQuery Hook Call",           // expected ~1276
  "TS NodeJS Apollo Server Query resolver"  // expected ~903
]
RETURN n.Type AS type, count(*) AS count ORDER BY type
```

```cypher
// 4. Parent file relationship sanity — every schema should belong to its source file
MATCH (n)-[:BELONGTO]->(parent)
WHERE n.Type = "TS NodeJS Apollo Server inline typeDefs schema"
RETURN parent.Type AS parent_type, count(*) AS count
```

Expected outcome for query 1: rows like `userSchema`, `accountTypeDefs`, `cardTypeDefs`,
`typeDefs`, `makeExecutableSchema@<line>` with absolute paths under `BigAppTest7/main_sources/server/ts/`.

---

## Wave 2 — Tail patterns (after Wave 1 is verified working)

Lower frequency but still in the wild. Implement only after Wave 1 ships clean.

### Prompt for a fresh Claude Code session

````
Extend the TS typeDefs detection in graphql_typescript_analyzer.py (already implemented
in Wave 1 — read CLAUDE-typedefs-implementation-plan.md and the existing
_extract_ts_typedefs() method first).

DO
1. Form 7 — Async file load:
       const typeDefs = await fs.promises.readFile(path, 'utf8')
       const typeDefs = await readFile(path)  // when imported as `import { readFile } from 'fs/promises'`
     Regex on source_text:
       (?:const|let|var)\s+(\w+)\s*=\s*await\s+(?:fs\.promises\.readFile|readFile|fsPromises\.readFile)\s*\(
     Only match when path arg contains \.graphql or \.gql or \.graphqls.

2. Form 10 — GraphQL file import (graphql-loader / @graphql-tools/load):
       import typeDefs from './schema.graphql'
       import * as typeDefs from './schema.graphql'
     Detect by iterating source_file.get_imports() and checking if get_module_from_import
     resolves to a path ending in .graphql / .gql / .graphqls. Use the imported local
     name as the variable name. Create the schema object anchored at the import statement.

3. Form 13 — Apollo Federation subgraph:
       buildSubgraphSchema({ typeDefs: gql`...`, resolvers })
       buildSubgraphSchema([{ typeDefs: gql`...`, resolvers }])
     Same approach as Form 11 (makeExecutableSchema) but with the additional twist that
     the argument may be an array of objects (federation supports merging modules).
     For the array form, create one schema object per element with synthetic name
     `buildSubgraphSchema[<index>]@<line>`.

4. Fallback for the server-file gate:
   Some codebases don't import the Apollo Server package directly (they wrap it in a
   factory module). If the import scan fails BUT the source_text contains any of:
       makeExecutableSchema(
       new ApolloServer(
       buildSubgraphSchema(
       new GraphQLServer(   (graphql-yoga 1.x)
       Mercurius(
   then treat the file as a server file. Log this fallback at log.info level so we can
   see how often it fires.

DO NOT
- Do not change the existing Wave 1 logic — only add the new forms.
- Do not regress Wave 1 verification queries.

VERIFY
Run the queries in the "Wave 2 verification" section of CLAUDE-typedefs-implementation-plan.md.
````

### Wave 2 verification (Neo4j)

```cypher
// 1. Total schemas should increase vs Wave 1 (new forms detected)
MATCH (n) WHERE n.Type = "TS NodeJS Apollo Server inline typeDefs schema"
RETURN count(*) AS total
```

```cypher
// 2. Find federation subgraph entries specifically
MATCH (n) WHERE n.Type = "TS NodeJS Apollo Server inline typeDefs schema"
  AND n.Name STARTS WITH "buildSubgraphSchema"
RETURN n.Name, n.FullName LIMIT 20
```

```cypher
// 3. Find graphql-loader imports (schema named after the imported binding)
MATCH (n) WHERE n.Type = "TS NodeJS Apollo Server inline typeDefs schema"
RETURN n.Name, n.FullName ORDER BY n.FullName
```

---

## Wave 3 — Schema ↔ SDL Program linking (optional polish)

Wires the new `TsNodeJsApolloSchema` objects to the `GraphQLProgram` objects produced
by [graphql_analyser_level.py](graphql_analyser_level.py) from `.graphql` SDL files. This
gives users a navigable callLink from `server.ts` to the actual schema definitions.

### Prompt for a fresh Claude Code session

````
Add cross-tech linking from TsNodeJsApolloSchema → GraphQLProgram in
graphql_application_level.py.

CONTEXT
- Read graphql_application_level.py for the existing linking patterns
  (_link_client_to_schema, _link_schema_to_nodejs_resolvers, etc.).
- Read CLAUDE-typedefs-implementation-plan.md for the schema detection waves.
- Schema objects from readFileSync forms have variable names like userSchema, cardTypeDefs.
  The .graphql file basenames are user, account, card, loan, etc.
  Matching strategy: strip common suffixes (Schema, TypeDefs, Type_defs, Types) from the
  schema object name and lowercase it, then compare to the .graphql file basename.

DO
1. Add a new method _link_schema_to_sdl_program(self, application) to GraphQLApplicationLevel.
2. Call it from end_application_create_objects after _link_schema_to_nodejs_resolvers.
3. Find all TsNodeJsApolloSchema and JsNodeJsApolloSchema objects.
4. Find all GraphQLProgram objects (one per .graphql / .gql / .graphqls file).
5. For each schema object:
     a. Extract a normalized key from the schema name:
          strip suffixes (Schema, TypeDefs, type_defs, Types) case-insensitively,
          lowercase, then strip underscores.
     b. Find the GraphQLProgram whose basename (without extension) normalizes to the same key.
     c. Create a callLink from the schema object to the GraphQLProgram.
6. If no match is found, log at info level — do NOT create unresolved stubs (a schema may
   legitimately be inline-only with no SDL counterpart).

DO NOT
- Do not modify the schema detection logic (Wave 1 / Wave 2).
- Do not create new metamodel types or unresolved stubs.

VERIFY
Run the queries in the "Wave 3 verification" section of CLAUDE-typedefs-implementation-plan.md.
````

### Wave 3 verification (Neo4j)

```cypher
// 1. Count of new schema→SDL links
MATCH (n)-[r:callLink]->(p) WHERE n.Type ENDS WITH "Apollo Server inline typeDefs schema"
  AND p.Type = "GraphQL Program"
RETURN count(*) AS schema_to_sdl_links
```

```cypher
// 2. Unmatched schemas (sanity check — should be small relative to total)
MATCH (n) WHERE n.Type ENDS WITH "Apollo Server inline typeDefs schema"
  AND NOT (n)-[:callLink]->(:`GraphQL Program`)
RETURN n.Name, n.FullName LIMIT 30
```

---

## Final test plan (Claude can execute these directly via Neo4j)

After all three waves are implemented and a fresh scan of `BigAppTest7` is complete,
Claude should run the following queries against Neo4j (no user involvement needed for
verification — only for triggering the scan).

> **Neo4j access:** `curl -s -u <user>:<password> <imaging-endpoint> -H "Content-Type: application/json" -X POST -d '{"statements":[{"statement":"<CYPHER>"}]}'`

### Test 1 — Schema objects exist
```cypher
MATCH (n) WHERE n.Type = "TS NodeJS Apollo Server inline typeDefs schema"
RETURN count(*) AS total
```
**Pass:** total > 30. **Fail:** total = 0 (Wave 1 broken) or < 10 (most patterns silent).

### Test 2 — All expected source forms produced output
```cypher
MATCH (n) WHERE n.Type = "TS NodeJS Apollo Server inline typeDefs schema"
WITH n.Name AS name
RETURN
  sum(CASE WHEN name CONTAINS '@' THEN 1 ELSE 0 END) AS inline_in_constructor,
  sum(CASE WHEN name =~ '.*[Ss]chema$' THEN 1 ELSE 0 END) AS named_schema,
  sum(CASE WHEN name =~ '.*[Tt]ype[Dd]efs?$' THEN 1 ELSE 0 END) AS named_typedefs,
  sum(CASE WHEN name STARTS WITH 'buildSubgraphSchema' THEN 1 ELSE 0 END) AS federation,
  count(*) AS total
```
**Pass:** `named_schema + named_typedefs > 20`; `inline_in_constructor > 0` if BigAppTest7 has
makeExecutableSchema/ApolloServer constructors with inline typeDefs.

### Test 3 — Each schema is in a server file
```cypher
MATCH (n)-[:BELONGTO]->(parent)
WHERE n.Type = "TS NodeJS Apollo Server inline typeDefs schema"
RETURN parent.FullName AS file, count(*) AS schemas_in_file
ORDER BY schemas_in_file DESC LIMIT 20
```
**Pass:** files listed are under `server/` or contain `apollo-server` imports.
**Fail:** schemas appear in `client/` or random files (server-file gate broken).

### Test 4 — No false positives on client code
```cypher
MATCH (n)-[:BELONGTO]->(parent)
WHERE n.Type = "TS NodeJS Apollo Server inline typeDefs schema"
  AND (parent.FullName CONTAINS '\\client\\' OR parent.FullName CONTAINS '/client/')
RETURN n.Name, parent.FullName LIMIT 10
```
**Pass:** zero rows. **Fail:** any row means a client file was misclassified.

### Test 5 — No regression in existing detection
```cypher
MATCH (n) WHERE n.Type IN [
  "TS GraphQL gql Query Definition",
  "TS GraphQL gql Mutation Definition",
  "TS GraphQL gql Subscription Definition",
  "TS Apollo useQuery Hook Call",
  "TS Apollo useMutation Hook Call",
  "TS Apollo useSubscription Hook Call",
  "TS Apollo useLazyQuery Hook Call",
  "TS NodeJS Apollo Server Query resolver",
  "TS NodeJS Apollo Server Mutation resolver",
  "TS Angular Apollo query call (this.apollo.query)",
  "TS Apollo Client query call"
]
RETURN n.Type AS type, count(*) AS count ORDER BY type
```
Compare against the baseline captured BEFORE the changes:

| Type | Baseline (pre-Wave1) |
|------|---------------------|
| TS GraphQL gql Query Definition | 4648 |
| TS GraphQL gql Mutation Definition | 4329 |
| TS GraphQL gql Subscription Definition | 1347 |
| TS Apollo useQuery Hook Call | 1276 |
| TS Apollo useMutation Hook Call | 1662 |
| TS Apollo useSubscription Hook Call | 522 |
| TS Apollo useLazyQuery Hook Call | 433 |
| TS NodeJS Apollo Server Query resolver | 903 |
| TS NodeJS Apollo Server Mutation resolver | 878 |
| TS Angular Apollo query call (this.apollo.query) | 648 |
| TS Apollo Client query call | 720 |

**Pass:** every row within ±2% of baseline. **Fail:** any drop > 5% means the new code path
is interfering with existing detection (likely an unhandled exception in `_extract_ts_typedefs`
that propagates and aborts the per-file handler).

### Test 6 — Schema → SDL links (Wave 3 only)
```cypher
MATCH (n)-[r:callLink]->(p)
WHERE n.Type ENDS WITH "Apollo Server inline typeDefs schema"
  AND p.Type = "GraphQL Program"
RETURN count(*) AS schema_sdl_links
```
**Pass after Wave 3:** ≥ 20 links. **Skip if Wave 3 not done.**

---

## Rollback procedure

If any wave produces regressions or excess false positives:

1. `git log --oneline graphql_typescript_analyzer.py | head -5` to find the commit before the wave.
2. `git diff <commit-before-wave>..HEAD graphql_typescript_analyzer.py` to review changes.
3. `git revert <wave-commit>` (do NOT `git reset --hard` — preserves history).
4. Re-scan BigAppTest7, re-run Test 5 to confirm baseline counts are restored.
