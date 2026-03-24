# small_app_test Generation Prompt

Create the directory `small_app_test/` in the repo root of `c:\Cast\GraphQL\com.castsoftware.uc.graphql`
and generate the following files. Do NOT skip any file. Generate them in the batch order below.
Each batch is independently executable. After each batch, verify the files exist before proceeding.

---

## Context

This is a CAST GraphQL extension test application. It covers every detection pattern the extension
supports across TypeScript and JavaScript — both client-side (React, Angular) and server-side
(Apollo Server). The app uses 3 domain entities: User, Post, Comment.

The extension detects:
- Client: `useQuery`, `useMutation`, `useLazyQuery`, `useSubscription` hook calls
- Client: `client.query(...)` and `client.mutate(...)` direct calls
- Client: TypedDocumentNode annotations (colon `:` form and `as` cast form)
- Client: `useMemo(() => gql\`...\` as TypedDocumentNode<...>, [dep])` wrapper
- Client: codegen-style hooks `useGetXxxQuery()`, `useCreateXxxMutation()`
- Client: `this.apollo.query(...)`, `this.apollo.mutate(...)`, `this.apollo.watchQuery(...).valueChanges`
- Client: cross-file GQL const imports (hook in file A imports const from file B)
- Server: `const typeDefs = gql\`...\`` (inline gql tag)
- Server: `const typeDefs = \`...\`` (raw template string, no gql tag)
- Server: `readFileSync(path.join(..., 'schema.graphql'), 'utf8')` (file load)
- Server: resolver maps `{ Query: {...}, Mutation: {...}, Subscription: {...} }` with all function variants
- Server: custom field resolvers (e.g. `User: { posts: ... }`)
- Server: Subscription with `withFilter`
- Server: service method calls (TS static: `UserService.findById(id)`, JS context: `ctx.userService.findById(id)`)
- Server: raw SQL (`db.query('SELECT * FROM users WHERE id = $1', [id])`)
- Server: Prisma ORM (`prisma.post.findMany(...)`)
- Server: Sequelize ORM (`Post.findAll({ where: { userId } })`)
- Server: context mapping `new UserService(db)` allowing `ctx.userService → UserService`

---

## GQL Operation Name Consistency Table

Every name MUST be exactly consistent across all files. No deviations.

### User entity

| Const (SCREAMING) | Operation (PascalCase) | Schema field | Resolver key | Service method |
|-------------------|----------------------|-------------|-------------|----------------|
| GET_USER | GetUser | getUser(id: ID!): User | getUser | findById |
| GET_USERS | GetUsers | getUsers: [User!]! | getUsers | findAll |
| CREATE_USER | CreateUser | createUser(input: CreateUserInput!): User! | createUser | create |
| UPDATE_USER | UpdateUser | updateUser(id: ID!, input: UpdateUserInput!): User | updateUser | update |
| DELETE_USER | DeleteUser | deleteUser(id: ID!): Boolean! | deleteUser | delete |
| ON_USER_CREATED | OnUserCreated | onUserCreated: User! | onUserCreated | (pubsub only) |

### Post entity

| Const | Operation | Schema field | Resolver key | Service method |
|-------|-----------|-------------|-------------|----------------|
| GET_POST | GetPost | getPost(id: ID!): Post | getPost | findById |
| GET_POSTS | GetPosts | getPosts(userId: ID): [Post!]! | getPosts | findAll |
| CREATE_POST | CreatePost | createPost(input: CreatePostInput!): Post! | createPost | create |
| UPDATE_POST | UpdatePost | updatePost(id: ID!, input: UpdatePostInput!): Post | updatePost | update |
| DELETE_POST | DeletePost | deletePost(id: ID!): Boolean! | deletePost | delete |
| ON_POST_PUBLISHED | OnPostPublished | onPostPublished: Post! | onPostPublished | (pubsub only) |

### Comment entity

| Const | Operation | Schema field | Resolver key | Service method |
|-------|-----------|-------------|-------------|----------------|
| GET_COMMENTS | GetComments | getComments(postId: ID!): [Comment!]! | getComments | findByPostId |
| GET_COMMENT | GetComment | getComment(id: ID!): Comment | getComment | findById |
| CREATE_COMMENT | CreateComment | createComment(input: CreateCommentInput!): Comment! | createComment | create |
| DELETE_COMMENT | DeleteComment | deleteComment(id: ID!): Boolean! | deleteComment | delete |
| ON_COMMENT_ADDED | OnCommentAdded | onCommentAdded(postId: ID!): Comment! | onCommentAdded | (pubsub only) |

---

## Mandatory Generation Rules

### File header (first 3 lines of every file — required)
```
// Pattern tested: <comma-separated list of patterns in this file>
// Expected Imaging objects: <comma-separated list of KB object types>
// Expected Imaging links: <from → to pairs>
```
For `.graphql` and `.sql` files, use `#` instead of `//` for the header lines.

### use-> inline comments (required on every applicable line)
These are the ONLY body comments allowed beyond the 3-line header.
Format: `// use -> <NAME> (<Type>) [<source>]`
Where Type is one of: GqlConst, ApolloHook, GqlSchema, Resolver, Service, SqlTable
Where source is "same file" or the relative path from the current file.

Apply to EVERY occurrence of:
- Hook call: `useQuery(GET_USER, ...)` → `// use -> GET_USER (GqlConst) [../../shared/queries-ts/user.queries.ts]`
- `this.apollo.*` call: `this.apollo.query({ query: GET_USERS })` → `// use -> GET_USERS (GqlConst) [same file]`
- `client.query` / `client.mutate`: `client.query({ query: GET_USER })` → `// use -> GET_USER (GqlConst) [path]`
- Resolver calling a service: `UserService.findById(id)` → `// use -> findById (Service) [../services/user.service.ts]`
- Service executing SQL: `db.query('SELECT * FROM users WHERE id = $1', [id])` → `// use -> users (SqlTable) [../../../database/schema.sql]`
- Prisma call: `prisma.post.findMany(...)` → `// use -> posts (SqlTable) [../../../database/schema.sql]`
- Sequelize call: `Post.findAll(...)` → `// use -> posts (SqlTable) [path]`
- readFileSync in server: `readFileSync(path.join(..., 'user.graphql'), 'utf8')` → `// use -> user.graphql (GqlSchema) [../schemas/user.graphql]`
- Schema field (in .graphql, use `#` comment): `getUser(id: ID!): User` → `# use -> getUser (Resolver) [../ts/resolvers/user.resolver.ts]`
- GQL const body → schema field: add a `# use -> getUser (GqlSchema field) [../../../server/schemas/user.graphql]` comment after the operation line inside the template literal
- `new UserService(db)` in server.js context: `// use -> UserService (Service) [./services/user.service.js]`

Do NOT add any other explanatory or descriptive comments anywhere.

### File size: 150–350 lines. Never exceed 400.
### Minimal JSX: focus on Apollo wiring. No elaborate form validation or decorative UI.
### All imports use correct relative paths per the directory layout below.

---

## Directory Layout

```
small_app_test/
  client/
    shared/
      queries-ts/
        user.queries.ts
        post.queries.ts
        comment.queries.ts
    react-ts/
      components/
        UserList.tsx
        PostList.tsx
        CommentList.tsx
      hooks/
        useUserData.ts
      context/
        ApolloContext.tsx
    react-js/
      components/
        UserList.jsx
        PostList.jsx
      shared/
        queries-js/
          user.queries.js
          post.queries.js
          comment.queries.js
    angular-ts/
      services/
        user.service.ts
        post.service.ts
      components/
        user-list/
          user-list.component.ts
    angular-js/
      services/
        user.service.js
  server/
    schemas/
      user.graphql
      post.graphql
      comment.graphql
    ts/
      resolvers/
        user.resolver.ts
        post.resolver.ts
        comment.resolver.ts
      services/
        user.service.ts
        post.service.ts
        comment.service.ts
      server.ts
    js/
      resolvers/
        user.resolver.js
        post.resolver.js
        comment.resolver.js
      services/
        user.service.js
        post.service.js
        comment.service.js
      server.js
  database/
    schema.sql
  TRANSACTIONS.md
```

---

## BATCH 1 — GraphQL Schemas + Database (4 files)

### File 1: `small_app_test/server/schemas/user.graphql`

Patterns: SDL schema with use-> comments on every root field linking to the TS resolver file.

Content:
- Header (3 # lines): Pattern tested: SDL GraphQL schema; Expected objects: GraphQLField per root field; Expected links: GraphQLField → Resolver
- `enum Role { ADMIN USER }`
- `type User { id: ID!, username: String!, email: String!, role: Role!, createdAt: String! }`
- `input CreateUserInput { username: String!, email: String!, role: Role! }`
- `input UpdateUserInput { username: String, email: String, role: Role }`
- `type Query { getUser(id: ID!): User, getUsers: [User!]! }` — each field gets `# use -> <fieldName> (Resolver) [../ts/resolvers/user.resolver.ts]`
- `type Mutation { createUser(input: CreateUserInput!): User!, updateUser(id: ID!, input: UpdateUserInput!): User, deleteUser(id: ID!): Boolean! }` — each field gets `# use -> <fieldName> (Resolver) [../ts/resolvers/user.resolver.ts]`
- `type Subscription { onUserCreated: User! }` — field gets `# use -> onUserCreated (Resolver) [../ts/resolvers/user.resolver.ts]`

### File 2: `small_app_test/server/schemas/post.graphql`

Content:
- Header (3 # lines)
- `enum PostStatus { DRAFT PUBLISHED ARCHIVED }`
- `type Post { id: ID!, userId: ID!, title: String!, content: String!, status: PostStatus!, createdAt: String! }`
- `input CreatePostInput { userId: ID!, title: String!, content: String!, status: PostStatus! }`
- `input UpdatePostInput { title: String, content: String, status: PostStatus }`
- `type Query { getPost(id: ID!): Post, getPosts(userId: ID): [Post!]! }` — use-> comments to `../ts/resolvers/post.resolver.ts`
- `type Mutation { createPost(input: CreatePostInput!): Post!, updatePost(id: ID!, input: UpdatePostInput!): Post, deletePost(id: ID!): Boolean! }` — use-> comments
- `type Subscription { onPostPublished: Post! }` — use-> comment

### File 3: `small_app_test/server/schemas/comment.graphql`

Content:
- Header (3 # lines)
- `type Comment { id: ID!, postId: ID!, userId: ID!, text: String!, createdAt: String! }`
- `input CreateCommentInput { postId: ID!, userId: ID!, text: String! }`
- `type Query { getComments(postId: ID!): [Comment!]!, getComment(id: ID!): Comment }` — use-> to `../ts/resolvers/comment.resolver.ts`
- `type Mutation { createComment(input: CreateCommentInput!): Comment!, deleteComment(id: ID!): Boolean! }` — use-> comments
- `type Subscription { onCommentAdded(postId: ID!): Comment! }` — use-> comment

### File 4: `small_app_test/database/schema.sql`

Content:
- Header (3 # lines): Pattern tested: SQL schema; Expected objects: SqlTable per CREATE TABLE
- `CREATE TABLE users (id SERIAL PRIMARY KEY, username VARCHAR(100) NOT NULL UNIQUE, email VARCHAR(200) NOT NULL UNIQUE, role VARCHAR(20) NOT NULL DEFAULT 'USER', created_at TIMESTAMP DEFAULT NOW());`
- `CREATE TABLE posts (id SERIAL PRIMARY KEY, user_id INTEGER REFERENCES users(id), title VARCHAR(255) NOT NULL, content TEXT, status VARCHAR(20) DEFAULT 'DRAFT', created_at TIMESTAMP DEFAULT NOW());`
- `CREATE TABLE comments (id SERIAL PRIMARY KEY, post_id INTEGER REFERENCES posts(id), user_id INTEGER REFERENCES users(id), text TEXT NOT NULL, created_at TIMESTAMP DEFAULT NOW());`

---

## BATCH 2 — Shared GQL Consts TypeScript (3 files)

### File 5: `small_app_test/client/shared/queries-ts/user.queries.ts`

Patterns: TypedDocumentNode colon form, TypedDocumentNode as-cast form, plain gql.
Import: `import { gql } from '@apollo/client'; import type { TypedDocumentNode } from '@graphql-typed-document-node/core';`

Each exported const gets a `# use ->` comment inside the template literal body on the operation line.
Specifically, add on the line after the operation declaration: a `# use -> <schemaField> (GqlSchema field) [../../../server/schemas/user.graphql]` comment within the template literal (use `#` since it's inside a GraphQL template literal — GraphQL comments use `#`).

Consts to define:
1. `GET_USER` — colon TypedDocumentNode form:
   `export const GET_USER: TypedDocumentNode<{ getUser: User }, { id: string }> = gql\`query GetUser($id: ID!) { getUser(id: $id) { id username email role createdAt } }\`;`
2. `GET_USERS` — plain gql form:
   `export const GET_USERS = gql\`query GetUsers { getUsers { id username email role createdAt } }\`;`
3. `CREATE_USER` — as-cast TypedDocumentNode form:
   `export const CREATE_USER = gql\`mutation CreateUser($input: CreateUserInput!) { createUser(input: $input) { id username email role } }\` as TypedDocumentNode<...>;`
4. `UPDATE_USER` — colon TypedDocumentNode form
5. `DELETE_USER` — plain gql form
6. `ON_USER_CREATED` — as-cast TypedDocumentNode form

Local interface types (`interface User`, `interface CreateUserInput`, etc.) must be declared above the consts so the TypedDocumentNode generics compile.

### File 6: `small_app_test/client/shared/queries-ts/post.queries.ts`

Same structure as user.queries.ts. Alternate TypedDocumentNode forms across the 6 consts.
Mix: GET_POST (colon), GET_POSTS (plain), CREATE_POST (as-cast), UPDATE_POST (colon), DELETE_POST (plain), ON_POST_PUBLISHED (as-cast).
use-> comments in GraphQL template body pointing to `../../../server/schemas/post.graphql`.

### File 7: `small_app_test/client/shared/queries-ts/comment.queries.ts`

**Special requirement:** Use an ALIASED gql import to test alias detection:
`import { gql as gqlTag } from '@apollo/client';`
Then use `gqlTag\`...\`` for all consts (not `gql\`...\``).

Consts: GET_COMMENTS (plain gqlTag), GET_COMMENT (colon TypedDocumentNode with gqlTag), CREATE_COMMENT (as-cast TypedDocumentNode with gqlTag), DELETE_COMMENT (plain gqlTag), ON_COMMENT_ADDED (plain gqlTag).
use-> comments in template body pointing to `../../../server/schemas/comment.graphql`.

---

## BATCH 3 — Shared GQL Consts JavaScript (3 files)

### File 8: `small_app_test/client/react-js/shared/queries-js/user.queries.js`

Patterns: plain `gql` template literals, no TypeScript annotations.
Import: `const { gql } = require('@apollo/client');` (CommonJS) OR `import { gql } from '@apollo/client';` (ESM — pick ESM for consistency).
Export all 6 consts (GET_USER, GET_USERS, CREATE_USER, UPDATE_USER, DELETE_USER, ON_USER_CREATED) as named exports.
Each const body includes `# use -> <schemaField> (GqlSchema field) [../../../../server/schemas/user.graphql]` comment within the GraphQL template literal.

### File 9: `small_app_test/client/react-js/shared/queries-js/post.queries.js`

Same structure. 6 consts for Post. use-> comments to `../../../../server/schemas/post.graphql`.

### File 10: `small_app_test/client/react-js/shared/queries-js/comment.queries.js`

Same structure. 5 consts for Comment. use-> comments to `../../../../server/schemas/comment.graphql`.

---

## BATCH 4 — Server TS Services + Server (4 files)

### File 11: `small_app_test/server/ts/services/user.service.ts`

Patterns: raw SQL via `pg` Pool.

Content:
- Import: `import { Pool } from 'pg'; const db = new Pool({ connectionString: process.env.DATABASE_URL });`
- `export class UserService` with static async methods:
  - `findAll()`: `db.query('SELECT * FROM users ORDER BY created_at DESC')` // use -> users (SqlTable) [../../../database/schema.sql]
  - `findById(id: string)`: `db.query('SELECT * FROM users WHERE id = $1', [id])` // use -> users (SqlTable) [../../../database/schema.sql]
  - `create(input: any)`: `db.query('INSERT INTO users (username, email, role) VALUES ($1, $2, $3) RETURNING *', [...])` // use -> users (SqlTable) [...]
  - `update(id: string, input: any)`: `db.query('UPDATE users SET username=$1, email=$2, role=$3 WHERE id=$4 RETURNING *', [...])` // use -> users (SqlTable) [...]
  - `delete(id: string)`: `db.query('DELETE FROM users WHERE id = $1', [id])` // use -> users (SqlTable) [...]
- Each method returns `result.rows[0]` or `result.rows` as appropriate. `delete` returns `true`.

### File 12: `small_app_test/server/ts/services/post.service.ts`

Patterns: Prisma ORM.

Content:
- Import: `import { PrismaClient } from '@prisma/client'; const prisma = new PrismaClient();`
- `export class PostService` with static async methods:
  - `findAll()`: `prisma.post.findMany({ orderBy: { createdAt: 'desc' } })` // use -> posts (SqlTable) [../../../database/schema.sql]
  - `findById(id: string)`: `prisma.post.findUnique({ where: { id } })` // use -> posts (SqlTable) [...]
  - `findByUserId(userId: string)`: `prisma.post.findMany({ where: { userId } })` // use -> posts (SqlTable) [...]
  - `create(input: any)`: `prisma.post.create({ data: input })` // use -> posts (SqlTable) [...]
  - `update(id: string, input: any)`: `prisma.post.update({ where: { id }, data: input })` // use -> posts (SqlTable) [...]
  - `delete(id: string)`: `prisma.post.delete({ where: { id } })` followed by `return true;` // use -> posts (SqlTable) [...]

### File 13: `small_app_test/server/ts/services/comment.service.ts`

Patterns: raw SQL via `pg` Pool (same as UserService but for comments table).

Content:
- `export class CommentService` with static async methods:
  - `findByPostId(postId: string)`: `db.query('SELECT * FROM comments WHERE post_id = $1 ORDER BY created_at ASC', [postId])` // use -> comments (SqlTable) [../../../database/schema.sql]
  - `findById(id: string)`: `db.query('SELECT * FROM comments WHERE id = $1', [id])` // use -> comments (SqlTable) [...]
  - `create(input: any)`: INSERT into comments // use -> comments (SqlTable) [...]
  - `delete(id: string)`: DELETE from comments // use -> comments (SqlTable) [...]

### File 14: `small_app_test/server/ts/server.ts`

Patterns: All 3 typeDefs forms — readFileSync, inline gql tag, raw template string.

Content:
- Imports: `ApolloServer` from `@apollo/server`, `readFileSync` from `fs`, `path`, `gql` from `graphql-tag`, `mergeResolvers` from `@graphql-tools/merge`, and the 3 resolver files.
- **Form 1 (readFileSync):** Load all 3 schema files:
  ```ts
  const userSchemaSdl = readFileSync(path.join(__dirname, '../schemas/user.graphql'), 'utf8'); // use -> user.graphql (GqlSchema) [../schemas/user.graphql]
  const postSchemaSdl = readFileSync(path.join(__dirname, '../schemas/post.graphql'), 'utf8'); // use -> post.graphql (GqlSchema) [../schemas/post.graphql]
  const commentSchemaSdl = readFileSync(path.join(__dirname, '../schemas/comment.graphql'), 'utf8'); // use -> comment.graphql (GqlSchema) [../schemas/comment.graphql]
  ```
- **Form 2 (inline gql tag):** Define a small extension schema:
  ```ts
  const healthTypeDefs = gql`
    type HealthCheck { status: String! version: String! }
    extend type Query { health: HealthCheck! }
  `;
  ```
- **Form 3 (raw template string, no gql tag):**
  ```ts
  const metaTypeDefs = `
    type Meta { totalUsers: Int! totalPosts: Int! }
    extend type Query { meta: Meta! }
  `;
  ```
- Combine: `const typeDefs = [userSchemaSdl, postSchemaSdl, commentSchemaSdl, healthTypeDefs, metaTypeDefs];`
- `const resolvers = mergeResolvers([userResolvers, postResolvers, commentResolvers]);`
- `const server = new ApolloServer({ typeDefs, resolvers });`
- For TS server, services are static — no context injection needed.
- Add a `startStandaloneServer(server, { listen: { port: 4000 } })` call.

---

## BATCH 5 — Server TS Resolvers (3 files)

### File 15: `small_app_test/server/ts/resolvers/user.resolver.ts`

Patterns: Query + Mutation + Subscription + custom field resolver. Multiple function syntax variants.

Imports: `UserService` from `../services/user.service`, `PostService` from `../services/post.service`, `PubSub` and `withFilter` from `graphql-subscriptions`.

```ts
const pubsub = new PubSub();

export const userResolvers = {
  Query: {
    getUser: async (_: unknown, { id }: { id: string }) =>
      UserService.findById(id),  // use -> findById (Service) [../services/user.service.ts]
    getUsers: async () => UserService.findAll(),  // use -> findAll (Service) [../services/user.service.ts]
  },
  Mutation: {
    createUser: async function(_: unknown, { input }: any) {  // async function expression variant
      const user = await UserService.create(input);  // use -> create (Service) [../services/user.service.ts]
      pubsub.publish('USER_CREATED', { onUserCreated: user });
      return user;
    },
    updateUser: async (_: unknown, { id, input }: any) =>
      UserService.update(id, input),  // use -> update (Service) [../services/user.service.ts]
    deleteUser(_: unknown, { id }: any) {  // method shorthand variant
      return UserService.delete(id);  // use -> delete (Service) [../services/user.service.ts]
    },
  },
  Subscription: {
    onUserCreated: {
      subscribe: withFilter(
        () => pubsub.asyncIterator(['USER_CREATED']),
        () => true
      ),
    },
  },
  User: {  // custom field resolver
    posts: (parent: any) => PostService.findByUserId(parent.id),  // use -> findByUserId (Service) [../services/post.service.ts]
  },
};
```

### File 16: `small_app_test/server/ts/resolvers/post.resolver.ts`

Patterns: Query + Mutation + Subscription + custom field resolver (Post.comments). Async arrow functions throughout.

Imports: `PostService`, `CommentService`, `PubSub`.

```ts
export const postResolvers = {
  Query: {
    getPost: async (_: unknown, { id }: { id: string }) =>
      PostService.findById(id),  // use -> findById (Service) [../services/post.service.ts]
    getPosts: async (_: unknown, { userId }: { userId?: string }) =>
      userId ? PostService.findByUserId(userId) : PostService.findAll(),  // use -> findAll (Service) [../services/post.service.ts]
  },
  Mutation: {
    createPost: async (_: unknown, { input }: any) => {
      const post = await PostService.create(input);  // use -> create (Service) [../services/post.service.ts]
      pubsub.publish('POST_PUBLISHED', { onPostPublished: post });
      return post;
    },
    updatePost: async (_: unknown, { id, input }: any) =>
      PostService.update(id, input),  // use -> update (Service) [../services/post.service.ts]
    deletePost: async (_: unknown, { id }: any) =>
      PostService.delete(id),  // use -> delete (Service) [../services/post.service.ts]
  },
  Subscription: {
    onPostPublished: {
      subscribe: withFilter(
        () => pubsub.asyncIterator(['POST_PUBLISHED']),
        (payload: any, variables: any) => !variables.userId || payload.onPostPublished.userId === variables.userId
      ),
    },
  },
  Post: {  // custom field resolver
    comments: (parent: any) => CommentService.findByPostId(parent.id),  // use -> findByPostId (Service) [../services/comment.service.ts]
  },
};
```

### File 17: `small_app_test/server/ts/resolvers/comment.resolver.ts`

Patterns: Query + Mutation + Subscription. No custom field resolver (simpler). Mix of arrow and async variants.

Imports: `CommentService`, `PubSub`.

```ts
export const commentResolvers = {
  Query: {
    getComments: (_: unknown, { postId }: { postId: string }) =>
      CommentService.findByPostId(postId),  // use -> findByPostId (Service) [../services/comment.service.ts]
    getComment: async (_: unknown, { id }: { id: string }) =>
      CommentService.findById(id),  // use -> findById (Service) [../services/comment.service.ts]
  },
  Mutation: {
    createComment: async (_: unknown, { input }: any) => {
      const comment = await CommentService.create(input);  // use -> create (Service) [../services/comment.service.ts]
      pubsub.publish('COMMENT_ADDED', { onCommentAdded: comment });
      return comment;
    },
    deleteComment: (_: unknown, { id }: any) =>
      CommentService.delete(id),  // use -> delete (Service) [../services/comment.service.ts]
  },
  Subscription: {
    onCommentAdded: {
      subscribe: withFilter(
        () => pubsub.asyncIterator(['COMMENT_ADDED']),
        (payload: any, variables: any) => payload.onCommentAdded.postId === variables.postId
      ),
    },
  },
};
```

---

## BATCH 6 — Server JS Services + Server (4 files)

### File 18: `small_app_test/server/js/services/user.service.js`

Patterns: raw SQL via pg Pool. Instance methods (not static — JS services use `this`).

Content:
- `class UserService { constructor(db) { this.db = db; } }`
- Instance methods: `async findAll()`, `async findById(id)`, `async create(input)`, `async update(id, input)`, `async delete(id)`
- Each `this.db.query(...)` call gets `// use -> users (SqlTable) [../../../database/schema.sql]`
- `module.exports = { UserService };`

### File 19: `small_app_test/server/js/services/post.service.js`

Patterns: Sequelize ORM. Instance methods.

Content:
- `class PostService { constructor(sequelize) { this.Post = sequelize.define('Post', { ... }); } }`
- Or simpler: `constructor(sequelize) { this.Post = sequelize.models.Post; }`
- Instance methods: `async findAll()`, `async findById(id)`, `async findByUserId(userId)`, `async create(input)`, `async update(id, input)`, `async delete(id)`
- `this.Post.findAll(...)` → `// use -> posts (SqlTable) [../../../database/schema.sql]`
- `this.Post.findByPk(id)` → `// use -> posts (SqlTable) [...]`
- `this.Post.findAll({ where: { userId } })` → `// use -> posts (SqlTable) [...]`
- `this.Post.create(input)` → `// use -> posts (SqlTable) [...]`
- `this.Post.destroy({ where: { id } })` → `// use -> posts (SqlTable) [...]`
- `module.exports = { PostService };`

### File 20: `small_app_test/server/js/services/comment.service.js`

Patterns: raw SQL via pg Pool. Same structure as user.service.js.

Content:
- Instance methods targeting `comments` table
- `this.db.query('SELECT * FROM comments WHERE post_id = $1 ORDER BY created_at ASC', [postId])` → `// use -> comments (SqlTable) [...]`
- findByPostId, findById, create, delete
- `module.exports = { CommentService };`

### File 21: `small_app_test/server/js/server.js`

Patterns: All 3 typeDefs forms. Context mapping `new UserService(db)` for resolver service injection.

Content:
- `const { ApolloServer } = require('@apollo/server');`
- `const { readFileSync } = require('fs');`
- `const path = require('path');`
- `const gql = require('graphql-tag');`
- `const { mergeResolvers } = require('@graphql-tools/merge');`
- `const { Pool } = require('pg'); const { Sequelize } = require('sequelize');`
- `const { UserService } = require('./services/user.service');`
- `const { PostService } = require('./services/post.service');`
- `const { CommentService } = require('./services/comment.service');`
- `const { userResolvers } = require('./resolvers/user.resolver');`
- `const { postResolvers } = require('./resolvers/post.resolver');`
- `const { commentResolvers } = require('./resolvers/comment.resolver');`
- **Form 1** (readFileSync × 3):
  `const userSchemaSdl = readFileSync(path.join(__dirname, '../schemas/user.graphql'), 'utf8');` // use -> user.graphql (GqlSchema) [../schemas/user.graphql]
  `const postSchemaSdl = readFileSync(path.join(__dirname, '../schemas/post.graphql'), 'utf8');` // use -> post.graphql (GqlSchema) [../schemas/post.graphql]
  `const commentSchemaSdl = readFileSync(path.join(__dirname, '../schemas/comment.graphql'), 'utf8');` // use -> comment.graphql (GqlSchema) [../schemas/comment.graphql]
- **Form 2** (inline gql tag):
  `const healthTypeDefs = gql\`type HealthCheck { status: String! } extend type Query { health: HealthCheck! }\`;`
- **Form 3** (raw template string):
  `const metaTypeDefs = \`type Meta { totalUsers: Int! } extend type Query { meta: Meta! }\`;`
- Context object (critical for JS resolver→service linking):
  ```js
  const db = new Pool({ connectionString: process.env.DATABASE_URL });
  const sequelize = new Sequelize(process.env.DATABASE_URL);
  const server = new ApolloServer({
    typeDefs: [userSchemaSdl, postSchemaSdl, commentSchemaSdl, healthTypeDefs, metaTypeDefs],
    resolvers: mergeResolvers([userResolvers, postResolvers, commentResolvers]),
    context: async () => ({
      userService: new UserService(db),       // use -> UserService (Service) [./services/user.service.js]
      postService: new PostService(sequelize), // use -> PostService (Service) [./services/post.service.js]
      commentService: new CommentService(db),  // use -> CommentService (Service) [./services/comment.service.js]
    }),
  });
  ```

---

## BATCH 7 — Server JS Resolvers (3 files)

### File 22: `small_app_test/server/js/resolvers/user.resolver.js`

Patterns: Query + Mutation + Subscription + custom field resolver. JS context injection (`ctx.userService.method()`).

Content:
```js
const { withFilter } = require('graphql-subscriptions');
const pubsub = /* imported or created */ ...;

const userResolvers = {
  Query: {
    getUser: async (_, { id }, ctx) => ctx.userService.findById(id),   // use -> findById (Service) [../services/user.service.js]
    getUsers: async (_, __, ctx) => ctx.userService.findAll(),          // use -> findAll (Service) [../services/user.service.js]
  },
  Mutation: {
    createUser: async (_, { input }, ctx) => {
      const user = await ctx.userService.create(input);                 // use -> create (Service) [../services/user.service.js]
      pubsub.publish('USER_CREATED', { onUserCreated: user });
      return user;
    },
    updateUser: async (_, { id, input }, ctx) => ctx.userService.update(id, input), // use -> update (Service) [../services/user.service.js]
    deleteUser: (_, { id }, ctx) => ctx.userService.delete(id),        // use -> delete (Service) [../services/user.service.js]
  },
  Subscription: {
    onUserCreated: {
      subscribe: withFilter(
        () => pubsub.asyncIterator(['USER_CREATED']),
        () => true
      ),
    },
  },
  User: {
    posts: (parent, _, ctx) => ctx.postService.findByUserId(parent.id), // use -> findByUserId (Service) [../services/post.service.js]
  },
};
module.exports = { userResolvers };
```

### File 23: `small_app_test/server/js/resolvers/post.resolver.js`

Patterns: Query + Mutation + Subscription. ctx.postService injection.

```js
const postResolvers = {
  Query: {
    getPost: async (_, { id }, ctx) => ctx.postService.findById(id),   // use -> findById (Service) [../services/post.service.js]
    getPosts: async (_, { userId }, ctx) =>
      userId ? ctx.postService.findByUserId(userId) : ctx.postService.findAll(), // use -> findAll (Service) [../services/post.service.js]
  },
  Mutation: {
    createPost: async (_, { input }, ctx) => {
      const post = await ctx.postService.create(input);                 // use -> create (Service) [../services/post.service.js]
      pubsub.publish('POST_PUBLISHED', { onPostPublished: post });
      return post;
    },
    updatePost: async (_, { id, input }, ctx) => ctx.postService.update(id, input), // use -> update (Service) [../services/post.service.js]
    deletePost: async (_, { id }, ctx) => ctx.postService.delete(id),  // use -> delete (Service) [../services/post.service.js]
  },
  Subscription: {
    onPostPublished: {
      subscribe: withFilter(
        () => pubsub.asyncIterator(['POST_PUBLISHED']),
        (payload, variables) => !variables.userId || payload.onPostPublished.userId === variables.userId
      ),
    },
  },
  Post: {
    comments: (parent, _, ctx) => ctx.commentService.findByPostId(parent.id), // use -> findByPostId (Service) [../services/comment.service.js]
  },
};
module.exports = { postResolvers };
```

### File 24: `small_app_test/server/js/resolvers/comment.resolver.js`

Patterns: Query + Mutation + Subscription. ctx.commentService injection.

```js
const commentResolvers = {
  Query: {
    getComments: (_, { postId }, ctx) => ctx.commentService.findByPostId(postId), // use -> findByPostId (Service) [../services/comment.service.js]
    getComment: async (_, { id }, ctx) => ctx.commentService.findById(id),        // use -> findById (Service) [../services/comment.service.js]
  },
  Mutation: {
    createComment: async (_, { input }, ctx) => {
      const comment = await ctx.commentService.create(input);                      // use -> create (Service) [../services/comment.service.js]
      pubsub.publish('COMMENT_ADDED', { onCommentAdded: comment });
      return comment;
    },
    deleteComment: (_, { id }, ctx) => ctx.commentService.delete(id),            // use -> delete (Service) [../services/comment.service.js]
  },
  Subscription: {
    onCommentAdded: {
      subscribe: withFilter(
        () => pubsub.asyncIterator(['COMMENT_ADDED']),
        (payload, variables) => payload.onCommentAdded.postId === variables.postId
      ),
    },
  },
};
module.exports = { commentResolvers };
```

---

## BATCH 8 — React TS Components + Hook + Context (5 files)

### File 25: `small_app_test/client/react-ts/components/UserList.tsx`

Patterns: cross-file import, useQuery, useMutation, client.query, codegen hook.

Imports from `../../shared/queries-ts/user.queries.ts`: GET_USER, GET_USERS, CREATE_USER, DELETE_USER.
Import `useApolloClient` from `@apollo/client`.

```tsx
import { useQuery, useMutation, useApolloClient } from '@apollo/client';
import { GET_USER, GET_USERS, CREATE_USER, DELETE_USER } from '../../shared/queries-ts/user.queries';

export function UserList() {
  const client = useApolloClient();

  const { data: usersData } = useQuery(GET_USERS);                        // use -> GET_USERS (GqlConst) [../../shared/queries-ts/user.queries.ts]
  const [createUser] = useMutation(CREATE_USER);                          // use -> CREATE_USER (GqlConst) [../../shared/queries-ts/user.queries.ts]
  const [deleteUser] = useMutation(DELETE_USER);                          // use -> DELETE_USER (GqlConst) [../../shared/queries-ts/user.queries.ts]

  const fetchUser = async (id: string) => {
    const result = await client.query({ query: GET_USER, variables: { id } }); // use -> GET_USER (GqlConst) [../../shared/queries-ts/user.queries.ts]
    return result.data.getUser;
  };

  const handleCreate = async (input: any) => {
    await createUser({ variables: { input } });
  };

  const handleDelete = async (id: string) => {
    await deleteUser({ variables: { id } });
  };

  return (/* minimal JSX: a div with user list and buttons */);
}
```

Also add codegen hook usage:
```tsx
import { useGetUsersQuery, useCreateUserMutation } from '@apollo/client';
// (these are codegen-generated typed hooks)
const { data: codegenData } = useGetUsersQuery();                         // use -> GetUsers (ApolloHook) [same file]
const [codegenCreate] = useCreateUserMutation();                          // use -> CreateUser (ApolloHook) [same file]
```

### File 26: `small_app_test/client/react-ts/components/PostList.tsx`

Patterns: cross-file import, useLazyQuery, useSubscription, codegen hooks.

Imports from `../../shared/queries-ts/post.queries.ts`: GET_POST, GET_POSTS, CREATE_POST, ON_POST_PUBLISHED.

```tsx
const [loadPosts, { data: postsData }] = useLazyQuery(GET_POSTS);        // use -> GET_POSTS (GqlConst) [../../shared/queries-ts/post.queries.ts]
const { data: newPost } = useSubscription(ON_POST_PUBLISHED);             // use -> ON_POST_PUBLISHED (GqlConst) [../../shared/queries-ts/post.queries.ts]
const [createPost] = useMutation(CREATE_POST);                            // use -> CREATE_POST (GqlConst) [../../shared/queries-ts/post.queries.ts]
const { data: singlePost } = useQuery(GET_POST, { variables: { id: '1' } }); // use -> GET_POST (GqlConst) [../../shared/queries-ts/post.queries.ts]
const { data: codegenPosts } = useGetPostsQuery();                        // use -> GetPosts (ApolloHook) [same file]
const [codegenCreatePost] = useCreatePostMutation();                      // use -> CreatePost (ApolloHook) [same file]
```

### File 27: `small_app_test/client/react-ts/components/CommentList.tsx`

Patterns: cross-file import for GET_COMMENTS/CREATE_COMMENT/ON_COMMENT_ADDED, PLUS local gql as-cast TypedDocumentNode for DELETE_COMMENT_LOCAL.

Imports from `../../shared/queries-ts/comment.queries.ts`: GET_COMMENTS, CREATE_COMMENT, ON_COMMENT_ADDED.

Local const (as-cast pattern, declared inside the file, not from shared):
```tsx
import { gql } from '@apollo/client';
import type { TypedDocumentNode } from '@graphql-typed-document-node/core';

const DELETE_COMMENT_LOCAL = gql`
  mutation DeleteComment($id: ID!) {
    deleteComment(id: $id)
  }
` as TypedDocumentNode<{ deleteComment: boolean }, { id: string }>;

export function CommentList({ postId }: { postId: string }) {
  const { data } = useQuery(GET_COMMENTS, { variables: { postId } });    // use -> GET_COMMENTS (GqlConst) [../../shared/queries-ts/comment.queries.ts]
  const [createComment] = useMutation(CREATE_COMMENT);                   // use -> CREATE_COMMENT (GqlConst) [../../shared/queries-ts/comment.queries.ts]
  const { data: newComment } = useSubscription(ON_COMMENT_ADDED, { variables: { postId } }); // use -> ON_COMMENT_ADDED (GqlConst) [../../shared/queries-ts/comment.queries.ts]
  const [deleteComment] = useMutation(DELETE_COMMENT_LOCAL);            // use -> DELETE_COMMENT_LOCAL (GqlConst) [same file]
  ...
}
```

### File 28: `small_app_test/client/react-ts/hooks/useUserData.ts`

Patterns: colon TypedDocumentNode (local const), useMemo wrapper with as-cast TypedDocumentNode (local const).

Both consts declared locally in this file — no imports from shared/queries-ts.

```tsx
import { gql, useQuery, useMutation, useMemo } from '@apollo/client';
import type { TypedDocumentNode } from '@graphql-typed-document-node/core';

interface UserProfileData { getUserProfile: { id: string; username: string; email: string } }
interface UserProfileVars { id: string }
interface UpdateProfileInput { username?: string; email?: string }
interface UpdateProfileData { updateUserProfile: { id: string; username: string } }

const USER_PROFILE_QUERY: TypedDocumentNode<UserProfileData, UserProfileVars> = gql`
  query GetUserProfile($id: ID!) {
    getUser(id: $id) {
      id username email role createdAt
    }
  }
`;

const UPDATE_PROFILE_MUTATION = useMemo(
  () => gql`
    mutation UpdateUserProfile($id: ID!, $input: UpdateUserInput!) {
      updateUser(id: $id, input: $input) {
        id username email role
      }
    }
  ` as TypedDocumentNode<UpdateProfileData, { id: string; input: UpdateProfileInput }>,
  []
);

export function useUserData(id: string) {
  const { data, loading } = useQuery(USER_PROFILE_QUERY, { variables: { id } }); // use -> USER_PROFILE_QUERY (GqlConst) [same file]
  const [updateProfile] = useMutation(UPDATE_PROFILE_MUTATION);                   // use -> UPDATE_PROFILE_MUTATION (GqlConst) [same file]
  return { user: data?.getUserProfile, loading, updateProfile };
}
```

### File 29: `small_app_test/client/react-ts/context/ApolloContext.tsx`

Patterns: client.mutate direct calls.

Imports from `../../shared/queries-ts/user.queries.ts`: UPDATE_USER, DELETE_USER.

```tsx
import { useApolloClient } from '@apollo/client';
import { UPDATE_USER, DELETE_USER } from '../../shared/queries-ts/user.queries';

export function useUserActions() {
  const client = useApolloClient();

  const updateUser = async (id: string, input: any) => {
    return client.mutate({
      mutation: UPDATE_USER,  // use -> UPDATE_USER (GqlConst) [../../shared/queries-ts/user.queries.ts]
      variables: { id, input },
    });
  };

  const deleteUser = async (id: string) => {
    return client.mutate({
      mutation: DELETE_USER,  // use -> DELETE_USER (GqlConst) [../../shared/queries-ts/user.queries.ts]
      variables: { id },
    });
  };

  return { updateUser, deleteUser };
}
```

---

## BATCH 9 — React JS + Angular TS + Angular JS (5 files)

### File 30: `small_app_test/client/react-js/components/UserList.jsx`

Patterns: cross-file import (JS), useQuery, useMutation, client.query.

Imports from `../shared/queries-js/user.queries.js`: GET_USER, GET_USERS, CREATE_USER, DELETE_USER.

```jsx
import { useQuery, useMutation, useApolloClient } from '@apollo/client';
import { GET_USER, GET_USERS, CREATE_USER, DELETE_USER } from '../shared/queries-js/user.queries';

export function UserList() {
  const client = useApolloClient();
  const { data } = useQuery(GET_USERS);                                    // use -> GET_USERS (GqlConst) [../shared/queries-js/user.queries.js]
  const [createUser] = useMutation(CREATE_USER);                          // use -> CREATE_USER (GqlConst) [../shared/queries-js/user.queries.js]
  const [deleteUser] = useMutation(DELETE_USER);                          // use -> DELETE_USER (GqlConst) [../shared/queries-js/user.queries.js]

  const fetchUser = async (id) => {
    const result = await client.query({ query: GET_USER, variables: { id } }); // use -> GET_USER (GqlConst) [../shared/queries-js/user.queries.js]
    return result.data.getUser;
  };

  return (/* minimal JSX */);
}
```

### File 31: `small_app_test/client/react-js/components/PostList.jsx`

Patterns: cross-file import (JS), useLazyQuery, useSubscription, client.mutate.

Imports from `../shared/queries-js/post.queries.js`: GET_POSTS, CREATE_POST, ON_POST_PUBLISHED.

```jsx
const [loadPosts, { data }] = useLazyQuery(GET_POSTS);                   // use -> GET_POSTS (GqlConst) [../shared/queries-js/post.queries.js]
const { data: newPost } = useSubscription(ON_POST_PUBLISHED);             // use -> ON_POST_PUBLISHED (GqlConst) [../shared/queries-js/post.queries.js]

const handleCreate = async (input) => {
  await client.mutate({ mutation: CREATE_POST, variables: { input } });   // use -> CREATE_POST (GqlConst) [../shared/queries-js/post.queries.js]
};
```

### File 32: `small_app_test/client/angular-ts/services/user.service.ts`

Patterns: Angular Apollo service wrapping — multi-line query, compact query, mutate, watchQuery.

Imports from `../../../shared/queries-ts/user.queries.ts`: GET_USER, GET_USERS, CREATE_USER, UPDATE_USER, ON_USER_CREATED.

```ts
import { Injectable } from '@angular/core';
import { Apollo } from 'apollo-angular';
import { GET_USER, GET_USERS, CREATE_USER, UPDATE_USER, ON_USER_CREATED } from '../../../shared/queries-ts/user.queries';

@Injectable({ providedIn: 'root' })
export class UserService {
  constructor(private apollo: Apollo) {}

  getUsers() {
    return this.apollo.watchQuery({ query: GET_USERS }).valueChanges;    // use -> GET_USERS (GqlConst) [../../../shared/queries-ts/user.queries.ts]
  }

  getUser(id: string) {
    return this.apollo.query({                                            // use -> GET_USER (GqlConst) [../../../shared/queries-ts/user.queries.ts]
      query: GET_USER,
      variables: { id },
    });
  }

  createUser(input: any) {
    return this.apollo.mutate({ mutation: CREATE_USER, variables: { input } }); // use -> CREATE_USER (GqlConst) [../../../shared/queries-ts/user.queries.ts]
  }

  updateUser(id: string, input: any) {
    return this.apollo.mutate({                                           // use -> UPDATE_USER (GqlConst) [../../../shared/queries-ts/user.queries.ts]
      mutation: UPDATE_USER,
      variables: { id, input },
    });
  }

  watchUsers() {
    return this.apollo.watchQuery({                                       // use -> GET_USERS (GqlConst) [../../../shared/queries-ts/user.queries.ts]
      query: GET_USERS,
    }).valueChanges;
  }
}
```

### File 33: `small_app_test/client/angular-ts/services/post.service.ts`

Patterns: compact query, watchQuery, mutate.

Imports from `../../../shared/queries-ts/post.queries.ts`: GET_POST, GET_POSTS, CREATE_POST, UPDATE_POST.

```ts
@Injectable({ providedIn: 'root' })
export class PostService {
  constructor(private apollo: Apollo) {}

  getPosts() {
    return this.apollo.query({ query: GET_POSTS });                       // use -> GET_POSTS (GqlConst) [../../../shared/queries-ts/post.queries.ts]
  }

  getPost(id: string) {
    return this.apollo.watchQuery({ query: GET_POST, variables: { id } }).valueChanges; // use -> GET_POST (GqlConst) [../../../shared/queries-ts/post.queries.ts]
  }

  createPost(input: any) {
    return this.apollo.mutate({ mutation: CREATE_POST, variables: { input } }); // use -> CREATE_POST (GqlConst) [../../../shared/queries-ts/post.queries.ts]
  }

  updatePost(id: string, input: any) {
    return this.apollo.mutate({                                           // use -> UPDATE_POST (GqlConst) [../../../shared/queries-ts/post.queries.ts]
      mutation: UPDATE_POST,
      variables: { id, input },
    });
  }
}
```

### File 34: `small_app_test/client/angular-ts/components/user-list/user-list.component.ts`

Patterns: DIRECT Angular component injection (no service wrapper). Apollo injected into component.

Imports from `../../../../shared/queries-ts/user.queries.ts`: GET_USERS, DELETE_USER.

```ts
import { Component, OnInit } from '@angular/core';
import { Apollo } from 'apollo-angular';
import { GET_USERS, DELETE_USER } from '../../../../shared/queries-ts/user.queries';

@Component({ selector: 'app-user-list', template: `<div>...</div>` })
export class UserListComponent implements OnInit {
  users: any[] = [];

  constructor(private apollo: Apollo) {}

  ngOnInit() {
    this.apollo.query({ query: GET_USERS }).subscribe(({ data }) => {    // use -> GET_USERS (GqlConst) [../../../../shared/queries-ts/user.queries.ts]
      this.users = (data as any).getUsers;
    });
  }

  deleteUser(id: string) {
    this.apollo.mutate({                                                  // use -> DELETE_USER (GqlConst) [../../../../shared/queries-ts/user.queries.ts]
      mutation: DELETE_USER,
      variables: { id },
    }).subscribe();
  }

  watchUsers() {
    return this.apollo.watchQuery({ query: GET_USERS }).valueChanges;    // use -> GET_USERS (GqlConst) [../../../../shared/queries-ts/user.queries.ts]
  }
}
```

---

## BATCH 10 — Angular JS Service (1 file)

### File 35: `small_app_test/client/angular-js/services/user.service.js`

Patterns: Angular JS Apollo service — this.apollo.query, this.apollo.mutate, this.apollo.watchQuery.

Imports from `../../react-js/shared/queries-js/user.queries.js`: GET_USER, GET_USERS, CREATE_USER.

```js
import { Injectable } from '@angular/core';
import { Apollo } from 'apollo-angular';
import { GET_USER, GET_USERS, CREATE_USER } from '../../react-js/shared/queries-js/user.queries';

export class UserAngularService {
  constructor(apollo) {
    this.apollo = apollo;
  }

  getUsers() {
    return this.apollo.watchQuery({ query: GET_USERS }).valueChanges;   // use -> GET_USERS (GqlConst) [../../react-js/shared/queries-js/user.queries.js]
  }

  getUser(id) {
    return this.apollo.query({                                           // use -> GET_USER (GqlConst) [../../react-js/shared/queries-js/user.queries.js]
      query: GET_USER,
      variables: { id },
    });
  }

  createUser(input) {
    return this.apollo.mutate({ mutation: CREATE_USER, variables: { input } }); // use -> CREATE_USER (GqlConst) [../../react-js/shared/queries-js/user.queries.js]
  }
}
```

---

## BATCH 11 — TRANSACTIONS.md (final file)

### File 36: `small_app_test/TRANSACTIONS.md`

Generate this file LAST, after all 35 source files are created.

The file must document 7 representative end-to-end transactions that are traceable in CAST Imaging.
Each transaction exercises the maximum number of distinct patterns in a single chain.
Use the exact format below.

```markdown
# small_app_test — End-to-End Transaction Map

## Purpose
Lists every fully-traceable transaction chain in CAST Imaging for the small_app_test application.
Each chain is traceable from a React/Angular hook or direct client call down to a SQL table.

---

### TX-01: React TS cross-file useQuery → TS Resolver → UserService raw SQL
**Patterns covered:** cross-file GQL const import, useQuery, TS resolver arrow function, static service method, raw SQL
**Chain:**
TsGraphQLApolloHookQuery "GetUsers"            [file: client/react-ts/components/UserList.tsx]
--useLink-->
TsGqlQuery "GetUsers"                          [file: client/shared/queries-ts/user.queries.ts]
--useLink-->
GraphQLField "getUsers"                        [file: server/schemas/user.graphql]
--callLink-->
TsNodeJsResolverQuery "getUsers"               [file: server/ts/resolvers/user.resolver.ts]
--callLink-->
CAST_TS_Method "UserService.findAll"           [file: server/ts/services/user.service.ts]
--sqlCall-->
SqlTable "users"                               [file: database/schema.sql]

**Note:** Demonstrates cross-file import resolution — GET_USERS const defined in shared/queries-ts/ and consumed in react-ts/components/

---

### TX-02: React TS client.mutate → TS Resolver async function → UserService raw SQL
**Patterns covered:** client.mutate direct call, as-cast TypedDocumentNode, TS resolver mutation, static service method, raw SQL
**Chain:**
TsGraphQLApolloHookMutation "DeleteUser"       [file: client/react-ts/context/ApolloContext.tsx]
--useLink-->
TsGqlMutation "DeleteUser"                     [file: client/shared/queries-ts/user.queries.ts]
--useLink-->
GraphQLField "deleteUser"                      [file: server/schemas/user.graphql]
--callLink-->
TsNodeJsResolverMutation "deleteUser"          [file: server/ts/resolvers/user.resolver.ts]
--callLink-->
CAST_TS_Method "UserService.delete"            [file: server/ts/services/user.service.ts]
--sqlCall-->
SqlTable "users"                               [file: database/schema.sql]

**Note:** client.mutate() direct Apollo Client call (not a hook) — tests ApolloClientMethod detection pattern

---

### TX-03: React TS useMemo TypedDocumentNode → TS Resolver → PostService Prisma
**Patterns covered:** useMemo wrapper gql as TypedDocumentNode, useQuery local const, TS resolver Prisma, Prisma ORM call
**Chain:**
TsGraphQLApolloHookQuery "GetUserProfile"      [file: client/react-ts/hooks/useUserData.ts]
--useLink-->
TsGqlQuery "GetUserProfile"                    [file: client/react-ts/hooks/useUserData.ts]  ← same file (local const)
--useLink-->
GraphQLField "getUser"                         [file: server/schemas/user.graphql]
--callLink-->
TsNodeJsResolverQuery "getUser"                [file: server/ts/resolvers/user.resolver.ts]
--callLink-->
CAST_TS_Method "UserService.findById"          [file: server/ts/services/user.service.ts]
--sqlCall-->
SqlTable "users"                               [file: database/schema.sql]

**Note:** UPDATE_PROFILE_MUTATION is the useMemo-wrapped pattern — same file local const, no cross-file import

---

### TX-04: React TS useSubscription → TS Resolver withFilter → Subscription
**Patterns covered:** useSubscription hook, Subscription resolver with withFilter, PubSub
**Chain:**
TsGraphQLApolloHookSubscription "OnPostPublished"  [file: client/react-ts/components/PostList.tsx]
--useLink-->
TsGqlSubscription "OnPostPublished"               [file: client/shared/queries-ts/post.queries.ts]
--useLink-->
GraphQLField "onPostPublished"                    [file: server/schemas/post.graphql]
--callLink-->
TsNodeJsResolverSubscription "onPostPublished"    [file: server/ts/resolvers/post.resolver.ts]

**Note:** Subscription chain ends at the resolver (no service call — withFilter uses PubSub directly)

---

### TX-05: Angular TS watchQuery → TS Resolver → PostService Prisma
**Patterns covered:** this.apollo.watchQuery(...).valueChanges, colon TypedDocumentNode GQL const, Prisma ORM service
**Chain:**
TsGraphQLApolloHookLazyQuery "GetPosts"        [file: client/angular-ts/services/post.service.ts]
--useLink-->
TsGqlQuery "GetPosts"                          [file: client/shared/queries-ts/post.queries.ts]
--useLink-->
GraphQLField "getPosts"                        [file: server/schemas/post.graphql]
--callLink-->
TsNodeJsResolverQuery "getPosts"               [file: server/ts/resolvers/post.resolver.ts]
--callLink-->
CAST_TS_Method "PostService.findAll"           [file: server/ts/services/post.service.ts]
--sqlCall-->
SqlTable "posts"                               [file: database/schema.sql]

**Note:** Angular TS pattern — this.apollo.watchQuery maps to useLazyQuery hook type

---

### TX-06: React JS cross-file useQuery → JS Resolver → UserService raw SQL
**Patterns covered:** React JS cross-file import, JS useQuery, JS context resolver, JS raw SQL service
**Chain:**
JsGraphQLApolloHookQuery "GetUsers"            [file: client/react-js/components/UserList.jsx]
--useLink-->
JsGqlQuery "GetUsers"                          [file: client/react-js/shared/queries-js/user.queries.js]
--useLink-->
GraphQLField "getUsers"                        [file: server/schemas/user.graphql]
--callLink-->
JsNodeJsResolverQuery "getUsers"               [file: server/js/resolvers/user.resolver.js]
--callLink-->
CAST_HTML5_JavaScript_Method "UserService.findAll"  [file: server/js/services/user.service.js]
--sqlCall-->
SqlTable "users"                               [file: database/schema.sql]

**Note:** Full JS equivalent of TX-01 — tests JS cross-file import resolution and JS resolver→service linking via ctx.userService

---

### TX-07: React JS client.mutate → JS Resolver → PostService Sequelize
**Patterns covered:** React JS client.mutate, JS context resolver, Sequelize ORM call
**Chain:**
JsGraphQLApolloHookMutation "CreatePost"       [file: client/react-js/components/PostList.jsx]
--useLink-->
JsGqlMutation "CreatePost"                     [file: client/react-js/shared/queries-js/post.queries.js]
--useLink-->
GraphQLField "createPost"                      [file: server/schemas/post.graphql]
--callLink-->
JsNodeJsResolverMutation "createPost"          [file: server/js/resolvers/post.resolver.js]
--callLink-->
CAST_HTML5_JavaScript_Method "PostService.create"  [file: server/js/services/post.service.js]
--sqlCall-->
SqlTable "posts"                               [file: database/schema.sql]

**Note:** Sequelize chain — PostService.create maps to this.Post.create(input) which targets the posts table

---
```

---

## Pattern Verification Table

After all files are generated, verify that every pattern is covered by at least one file.

| Pattern | File(s) that cover it |
|---------|----------------------|
| `useQuery(CONST)` — outline const | UserList.tsx, PostList.tsx, CommentList.tsx, UserList.jsx, useUserData.ts |
| `useMutation(CONST)` | UserList.tsx, CommentList.tsx, UserList.jsx |
| `useLazyQuery(CONST)` | PostList.tsx, PostList.jsx |
| `useSubscription(CONST)` | PostList.tsx, CommentList.tsx, PostList.jsx |
| `client.query({ query: CONST })` | UserList.tsx, UserList.jsx |
| `client.mutate({ mutation: CONST })` | ApolloContext.tsx, PostList.jsx |
| `: TypedDocumentNode<D,V> = gql\`...\`` (colon) | user.queries.ts, post.queries.ts, comment.queries.ts, useUserData.ts |
| `= gql\`...\` as TypedDocumentNode<...>` (as cast) | user.queries.ts, post.queries.ts, CommentList.tsx |
| `useMemo(() => gql\`...\` as TypedDocumentNode<...>, [])` | useUserData.ts |
| `useGetXxxQuery()` codegen hook | UserList.tsx, PostList.tsx |
| `useCreateXxxMutation()` codegen hook | UserList.tsx, PostList.tsx |
| cross-file import (TS) | UserList.tsx (imports from shared/queries-ts) |
| cross-file import (JS) | UserList.jsx (imports from shared/queries-js) |
| aliased gql import (`gql as gqlTag`) | comment.queries.ts |
| `this.apollo.query({ query: VAR })` compact | post.service.ts, user.service.ts, user-list.component.ts |
| `this.apollo.query({ query: VAR, variables })` multi-line | user.service.ts |
| `this.apollo.mutate({ mutation: VAR })` | user.service.ts, post.service.ts, user-list.component.ts |
| `this.apollo.watchQuery({ query: VAR }).valueChanges` | user.service.ts, post.service.ts, user-list.component.ts |
| Angular direct component injection | user-list.component.ts |
| Angular JS `this.apollo.*` | angular-js/services/user.service.js |
| `readFileSync(path.join(...), 'utf8')` | server.ts, server.js |
| `const typeDefs = gql\`...\`` inline | server.ts, server.js |
| `const typeDefs = \`...\`` raw template | server.ts, server.js |
| Resolver arrow function | user.resolver.ts, post.resolver.ts |
| Resolver async function expression | user.resolver.ts |
| Resolver method shorthand | user.resolver.ts |
| Resolver async arrow function | post.resolver.ts, comment.resolver.ts |
| Custom field resolver (User.posts) | user.resolver.ts, user.resolver.js |
| Custom field resolver (Post.comments) | post.resolver.ts, post.resolver.js |
| Subscription with withFilter | user.resolver.ts, post.resolver.ts, comment.resolver.ts, user.resolver.js, post.resolver.js, comment.resolver.js |
| TS static service call: `UserService.findById(id)` | user.resolver.ts, post.resolver.ts, comment.resolver.ts |
| JS context service call: `ctx.userService.findById(id)` | user.resolver.js, post.resolver.js, comment.resolver.js |
| Raw SQL (pg): `db.query('SELECT * FROM ...')` | user.service.ts, comment.service.ts, user.service.js, comment.service.js |
| Prisma ORM: `prisma.post.findMany(...)` | post.service.ts |
| Sequelize ORM: `Post.findAll(...)` | post.service.js |
| Context mapping `new UserService(db)` | server.js |
| `use ->` comments on every applicable line | all files above |

---

## Execution Notes for the Agent

1. Create directories as needed before writing files (use `mkdir -p` equivalent — create each file with its full path).
2. If a file already exists, overwrite it.
3. Every file MUST start with the 3-line header comment block. Never omit it.
4. Every applicable line MUST have the `// use ->` inline comment. Never omit it.
5. Keep each file between 150 and 350 lines. Target ~200–280 lines for most files.
6. Verify the operation name consistency table before writing any resolver or query file.
7. Generate TRANSACTIONS.md last, after all 35 source files are complete.
8. After completing all batches, output a summary table listing each file path and its actual line count.
