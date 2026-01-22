# GraphQL Universal Analyzer Extension

**Version:** 1.0.0  
**Author:** CAST  
**Namespace:** labs

---

## Overview

This CAST Universal Analyzer extension provides automated analysis of **GraphQL** applications including schema files and client-side code. It identifies GraphQL structures and creates call relationships to enable full-stack software architecture analysis in CAST Imaging.

### What This Extension Does

- ✅ **Schema Object Detection**: Extracts GraphQL types, queries, mutations from schema files
- ✅ **Client-Side Linking**: Links React/Apollo Client code to GraphQL schema objects
- ✅ **Backend Linking**: Links GraphQL schema fields to Java backend methods (resolvers)
- ✅ **Smart Resolution**: Uses intelligent heuristics to match client operations to schema definitions

### Supported File Extensions

**Schema Files:** `*.graphql`, `*.gql`, `*.graphqls`  
**Client Files:** `*.js`, `*.jsx`, `*.ts`, `*.tsx` (via HTML5/JavaScript analyzer integration)

---

## Supported Code Structures

This extension detects and analyzes the following GraphQL constructs:

### Schema Objects (from .graphql/.gql/.graphqls files)
- **Program**: Top-level program definitions
- **Schema**: Top-level schema definitions
- **Type**: Type definitions within Schema
- **Interface**: Interface definitions within Schema
- **Enum**: Enumeration definitions within Schema
- **EnumValue**: Enumeration value within Enum
- **Input**: Input type definitions within Schema
- **Union**: Union type definitions within Schema
- **Scalar**: Scalar type definitions within Schema
- **Directive**: Directive definitions within Schema
- **Field**: Field within Type, Interface, Query, Mutation, or Subscription
- **Argument**: Argument within Field
- **Query**: Query operation definitions within Schema
- **Mutation**: Mutation operation definitions within Schema
- **Subscription**: Subscription operation definitions within Schema
- **Fragment**: Fragment definitions within Schema
- **Variable**: Variable definitions within operations

### Client-Side Objects (from React/JavaScript code)

#### Request Objects (Apollo Hook Calls)
- **GraphQLQueryRequest**: Apollo `useQuery()` hook call
- **GraphQLLazyQueryRequest**: Apollo `useLazyQuery()` hook call
- **GraphQLMutationRequest**: Apollo `useMutation()` hook call
- **GraphQLSubscriptionRequest**: Apollo `useSubscription()` hook call

#### Client Definition Objects (gql Templates)
- **GraphQLClientQuery**: Client-side query definition (gql template)
- **GraphQLClientMutation**: Client-side mutation definition (gql template)
- **GraphQLClientSubscription**: Client-side subscription definition (gql template)

---

## GraphQL Architecture

This extension creates a complete end-to-end analysis chain from React frontend to GraphQL schema to Java backend.

### Complete Code Example

**Frontend (App.jsx) - React/Apollo Client:**
```javascript
import { gql, useQuery } from "@apollo/client";

// gql template definition
const GET_USERS = gql`
  query GetUsers {
    users { id name email }
  }
`;

function App() {
  // Apollo hook call
  const { data } = useQuery(GET_USERS);
  return <div>{/* render users */}</div>;
}
```

**Schema (schema.graphqls) - GraphQL Schema:**
```graphql
type Query {
  users: [User!]!
}

type User {
  id: ID!
  name: String!
  email: String!
}
```

**Backend (UserController.java) - Spring GraphQL:**
```java
@Controller
public class UserController {
    
    @QueryMapping
    public List<User> users() {
        return userService.findAll();
    }
}
```

### Links Created

```
JavaScript Function "App" (in App.jsx)
│
├─ GraphQLQueryRequest "useQuery:GET_USERS"
│  │  (Apollo hook call - transforms definition into HTTP request)
│  │
│  └─ [USE link]
│     │
│     ↓
│  GraphQLClientQuery "GET_USERS"
│     (gql template definition - describes data structure to fetch)
│     │
│     └─ [USE link]
│        │
│        ↓
│     GraphQLQuery > Field "users"
│        (schema.graphqls - backend field in Type Query)
│        │
│        └─ [CALL link]
│           │
│           ↓
│        JV_METHOD users()
│           (Java resolver method with @QueryMapping)
```

### Frontend Objects Created

The extension creates **GraphQL-specific objects** for React/Apollo Client code:

#### 1. Request Objects (Hook Calls)
- **GraphQLQueryRequest** - Created at `useQuery()` call site
- **GraphQLLazyQueryRequest** - Created at `useLazyQuery()` call site
- **GraphQLMutationRequest** - Created at `useMutation()` call site
- **GraphQLSubscriptionRequest** - Created at `useSubscription()` call site

#### 2. Client Definition Objects (gql Templates)
- **GraphQLClientQuery** - Created at `gql` query definition
- **GraphQLClientMutation** - Created at `gql` mutation definition
- **GraphQLClientSubscription** - Created at `gql` subscription definition

**Why we create these objects:**
The HTML5/JavaScript analyzer does not support the Apollo Client framework used for GraphQL requests. It also does not create objects for `gql` template definitions. Without these custom GraphQL objects, there would be no way to link JavaScript code to GraphQL schema objects. Our extension bridges this gap by:
- Creating GraphQL-specific objects (Request and Definition objects) for Apollo hooks and gql templates
- Linking these custom objects to JavaScript objects created by the HTML5/JavaScript analyzer (e.g., functions, variables)
- Linking these custom objects to GraphQL schema objects created by our GraphQL schema analyzer
- Enabling end-to-end transaction analysis from React frontend through schema to Java backend

### Schema Objects Created

From `.graphql`/`.gql`/`.graphqls` files, the extension creates:
- **GraphQLQuery** - Query type fields (e.g., "users")
- **GraphQLMutation** - Mutation type fields (e.g., "createUser")
- **GraphQLSubscription** - Subscription type fields
- **GraphQLType** - Custom types (e.g., "User")
- **GraphQLField** - Type fields (e.g., "id", "name", "email")
- And other schema constructs (Interface, Enum, Input, etc.)

### Backend Objects (Java)

**Important:** The extension does **NOT** create any Java objects. It relies entirely on objects created by the **JEE Analyzer** (JV_METHOD, JV_CLASS, etc.) and creates links between GraphQL schema objects and these existing Java objects.

The linking is done by:
1. Detecting `@Controller` classes
2. Finding methods with `@QueryMapping`, `@MutationMapping`, or `@SubscriptionMapping` annotations
3. Matching method names to GraphQL schema field names
4. Creating CALL links from GraphQL schema fields to Java methods

### Complete Transaction Flow

**End-to-end analysis example:**
1. **Frontend**: User clicks button → triggers `useQuery(GET_USERS)` (GraphQLQueryRequest)
2. **Client Definition**: Request uses `GET_USERS` gql template (GraphQLClientQuery "GetUsers")
3. **Schema**: Query asks for "users" field from Type Query (GraphQLQuery field "users")
4. **Backend**: Field resolves to Java method `users()` with @QueryMapping (JV_METHOD)
5. **Data flow**: Java method fetches data → returns to schema → returns to client → updates UI

This enables **full-stack transaction analysis** in CAST Imaging from React UI → GraphQL operations → Backend resolvers.

---

## Link Implementation Details

### 1. Request/Definition → JavaScript Objects

**Implementation:** `graphql_client_analyzer.py`

Client objects (GraphQLQueryRequest, GraphQLClientQuery, etc.) are created as **children** of JavaScript objects. During object creation, links are established to JavaScript objects:
- **CONTAINMENT** links: Request/Definition objects are children of JS objects
- **CALL** links: If the parent JS object is a function
- **USE** links: To JavaScript variables (e.g., linking GraphQLQueryRequest to the GraphQLClientQuery referencing the gql template)

This file communicates with the HTML5/JavaScript analyzer using an **event-driven architecture** to:
- Catch events from the HTML5/JS analyzer
- Access the JavaScript AST (Abstract Syntax Tree)
- Create GraphQL client objects
- Establish containment and reference links to JS objects

**Documentation:** For details on the event system, see [CAST HTML5/JavaScript Extension SDK](https://cast-projects.github.io/Extension-SDK/doc/html5.html?highlight=javascript)

### 2. Client Definitions → Schema (USE Links)

**Implementation:** `_link_client_to_schema()` in `graphql_application_level.py`

**Matching logic:**
- Parse the `gql` template to extract the root field being queried (e.g., "users" from `query GetUsers { users { ... } }`)
- Match this field name to a corresponding GraphQLQuery/GraphQLMutation/GraphQLSubscription object in the schema
- Create USE link: `GraphQLClientQuery/Mutation/Subscription` → `GraphQLQuery/Mutation/Subscription` field

**Example:** Client query "GetUsers" selecting field "users" → links to schema's `Query.users` field

### 3. Schema → Backend (CALL Links)

**Implementation:** `_link_schema_to_backend()` in `graphql_application_level.py`

**Matching logic:**
1. Find all Java classes with `@Controller` annotation (JV_CLASS objects from JEE Analyzer)
2. Find methods with `@QueryMapping`, `@MutationMapping`, or `@SubscriptionMapping` annotations
3. Match method name to GraphQL field name
4. Verify annotation type matches operation type (QueryMapping → Query type, etc.)
5. Create CALL link: `GraphQLQuery/Mutation/Subscription` field → `JV_METHOD`

**Example:** Schema field `Query.users` → links to Java method `users()` with `@QueryMapping` in a `@Controller` class

**Note:** Currently uses naive name-based matching. See [Backend-to-Schema Linking](#backend-to-schema-linking-future-enhancement) section for planned improvements.

---

## Deployment

### Prerequisites

- CAST AIP 8.3 or higher
- CAST Imaging console access

### Installation Steps

1. **Generate the .nupkg package** by double-clicking:
   ```
   plugin-to-nupkg.bat
   ```

2. **Move the .nupkg file** to the extensions folder:
   ```
   C:\Cast\ProgramData\CAST\AIP-Console-Standalone\data\shared\extensions\
   ```

3. **Launch a Fast Scan** on your application in CAST Console.

4. **Install the extension** (after Fast Scan completes):
   - Go to the **Extensions** tab (left sidebar)
   - Click on the **Available** tab
   - Add your generated extension
   - CAST will prompt you to reinstall extensions → **Click to reinstall**
   - Wait for installation to complete

5. **Launch Deep Scan**.

6. **Create Analysis Unit** (since extension has no discoverer):
   - Wait until the **Run** step of the Deep Scan begins
   - **STOP** the scan (red button)
   - Go to **Config** tab (gear icon, left sidebar)
   - Click on **Universal Analyzer**
   - Click **+Add**
   - **Name**: e.g., `GraphQLAnalysisUnit`
   - **Package** dropdown: Select `main_sources`
   - **Language**: Enter your extension name (e.g., `GraphQL`)
   - Click **Save**

7. **Configure entry point for transactions** (to make transactions visible in Imaging):
   - After creating the Analysis Unit, go to the **Transactions** tab (left sidebar)
   - This opens a window with three tabs; select **Rules**
   - Click the **+ADD** button
   - Name the rule (e.g., `ReactJS Entry Point`)
   - Activate the toggle **Activation**
   - Click **UPDATE**
   - Click on the square object for your new entry point (e.g., `ReactJS Entry Point`)
   - This opens a page on the right to configure the entry point
   - Click the large **+** button, then the small **+** button
   - In the dropdown, select **Property - Identification**
   - Set **Property** to `type`, **Operator** to `=`, and **Values** to `ReactJS Function Component`
   - Click **Check Content** to view objects with this property
   - Click **Save** at the top right of the main page
   - Your entry point is now configured

8. **Resume the analysis** (blue button, bottom right of **Overview**).

### Verification

After analysis completes, verify the extension worked:
- Check Analysis logs for `[GraphQL] Starting GraphQL analysis`
- Review the Analysis Summary for detected objects and links

---

**GraphQL schema objects generated by CAST Extension Generator**  
For questions or issues, refer to the generator documentation.

---

## Release Notes

### Version 1.0.0 (2026-01-23)
---
- Initial release supporting JS Apollo and Java Spring integration through GraphQL with full-stack transaction analysis

