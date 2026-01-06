# GraphQL Client-Side Analyzer - Implementation Summary

## Overview

Successfully implemented a new CAST extension module (`graphql_client_analyzer.py`) that bridges the gap between React/Apollo Client code and GraphQL schema objects in CAST Imaging.

## What Was Built

### New File: `graphql_client_analyzer.py`

A complete event-driven extension that:
1. Listens to HTML5/JavaScript analyzer broadcasts
2. Detects Apollo Client GraphQL operations (`useQuery`, `useMutation`)
3. Resolves GraphQL variables to their `gql` template literal definitions
4. Parses GraphQL query/mutation text to extract metadata
5. Creates custom CAST objects for client operations
6. Links these objects to existing GraphQL schema objects

### Updated Files

- **`__init__.py`** (NEW): Package initialization that registers all three extensions
- **`plugin.nuspec`**: Updated version to 1.0.6 and enhanced description
- **`README.md`**: Added comprehensive documentation for client-side detection

## Architecture

### Event-Driven Design

```python
@Event('com.castsoftware.html5', 'start_javascript_content')
def on_js_file(self, jsContent):
    # Process each JavaScript/JSX file
    
@Event('com.castsoftware.html5', 'end_javascript_contents')  
def on_all_files_done(self):
    # Create objects and links after all files processed
```

### Two-Pass Analysis

**Pass 1: Collect gql Definitions**
- Recursively walks JavaScript AST
- Finds assignments like `const GET_USERS = gql`...``
- Extracts GraphQL text from template literals
- Stores in `self.gql_definitions` dictionary

**Pass 2: Find GraphQL Operations**
- Recursively walks JavaScript AST
- Finds `useQuery(VARIABLE)` and `useMutation(VARIABLE)` calls
- Resolves VARIABLE to its gql definition from Pass 1
- Parses GraphQL text to extract operation metadata
- Stores operation info for later object creation

**Pass 3: Create Objects and Links** (in `end_javascript_contents`)
- Creates `CAST_GraphQL_ClientQuery` or `CAST_GraphQL_ClientMutation` objects
- Sets parent to the containing JavaScript function
- Creates USE links to GraphQL schema objects

## Key Features

### 1. Variable Resolution

Traces query variables back to their definitions:

```javascript
const GET_USERS = gql`query GetUsers { users { id } }`;
//    ↑ DEFINITION

function App() {
  const { data } = useQuery(GET_USERS);
  //                         ↑ USAGE
}
```

### 2. GraphQL Text Parsing

Extracts operation metadata using regex patterns:

```python
# Handles named operations:
query GetUsers { users { id } }
→ type='query', name='GetUsers', field='users'

# Handles anonymous operations:
query { users { id } }
→ type='query', name=None, field='users'

# Handles implicit queries:
{ users { id } }
→ type='query', name=None, field='users'
```

### 3. Smart Object Creation

```python
# Creates objects as children of JavaScript functions
client_obj = CustomObject()
client_obj.set_type('CAST_GraphQL_ClientQuery')
client_obj.set_parent(parent_kb_object)
client_obj.set_fullname(parent_fullname + '/query:users')
client_obj.set_name('query:users')
client_obj.save()
```

### 4. Schema Object Linking

```python
# Finds existing GraphQL schema objects
schema_object = self._find_schema_object('GraphQLQuery', 'users')

# Creates USE link
create_link('useLink', client_obj, schema_object, bookmark)
```

## Expected Result in CAST Imaging

```
App.jsx
└── Function: App
    ├── CAST_GraphQL_ClientQuery "query:users"
    │   └── USE link → GraphQLQuery "users" (from schema.graphqls)
    │
    └── CAST_GraphQL_ClientMutation "mutation:createUser"
        └── USE link → GraphQLMutation "createUser" (from schema.graphqls)
```

## Technical Patterns Used

### From `prospect.angular` Extension
- Event listening pattern (`@Event` decorator)
- Recursive AST traversal
- CustomObject creation and linking
- Duplicate prevention with counters

### From `nodejs.2.12.1-funcrel` Extension
- AST helper methods (`_is_function_call`, `_is_identifier`, etc.)
- Parent function resolution (`get_first_kb_parent()`)
- Bookmark creation for source code location

### From Existing GraphQL Extension
- GUID generation pattern
- Fullname construction using file path
- Object registration in symbol tables

## Error Handling

The implementation includes comprehensive error handling:

```python
try:
    # Main logic
except Exception as e:
    log.warning('[GraphQL Client] Error: ' + str(e))
    log.debug('[GraphQL Client] ' + traceback.format_exc())
```

- All major methods wrapped in try/except
- Debug logging for troubleshooting
- Graceful degradation if objects not found

## Supported Patterns

### ✅ Detected Patterns

| Pattern | Example |
|---------|---------|
| useQuery with const | `const { data } = useQuery(GET_USERS)` |
| useMutation with const | `const [createUser] = useMutation(CREATE_USER)` |
| gql template literals | ``const Q = gql`query { ... }` `` |
| Named operations | `query GetUsers { users { id } }` |
| Anonymous operations | `query { users { id } }` |
| Operations with variables | `query GetUsers($id: ID!) { ... }` |

### ❌ Not Supported (Limitations)

| Pattern | Reason |
|---------|--------|
| Inline gql in hooks | `useQuery(gql`...`)` - harder to parse |
| Dynamic query building | Requires runtime evaluation |
| Imported queries from other files | No cross-file import resolution (yet) |

## Testing Recommendations

### Unit Testing
1. Test gql definition extraction with various template literal formats
2. Test GraphQL text parsing with edge cases (comments, formatting)
3. Test variable resolution with different assignment patterns

### Integration Testing
1. Analyze sample React app with Apollo Client
2. Verify objects created in CAST Imaging
3. Check that links point to correct schema objects
4. Validate transaction paths from UI → GraphQL → Backend

### Edge Cases to Test
- Multiple hooks in same function
- Same query used in multiple places
- Queries without operation names
- Mutations with complex inputs
- Fragments and directives

## Deployment Steps

1. **Package the extension:**
   ```
   plugin-to-nupkg.bat
   ```

2. **Copy to CAST extensions folder:**
   ```
   C:\Cast\ProgramData\CAST\AIP-Console-Standalone\data\shared\extensions\
   ```

3. **Install in CAST Console:**
   - Fast Scan → Extensions tab → Add extension
   - Reinstall when prompted

4. **Configure analysis unit:**
   - Create Universal Analyzer unit for GraphQL
   - Point to schema files (`.graphqls`)

5. **Run Deep Scan**

6. **Verify in Imaging:**
   - Check for `CAST_GraphQL_ClientQuery` objects
   - Verify USE links to GraphQL schema objects
   - Test transaction analysis end-to-end

## Troubleshooting

### No Objects Created

**Check:**
- HTML5/JS analyzer is active
- Event handlers are registered (`@Event` decorator)
- Log shows "[GraphQL Client] Processing file:"

**Fix:**
- Verify `__init__.py` imports the extension
- Check CAST logs for errors

### No Links Created

**Check:**
- GraphQL schema objects exist (run schema analysis first)
- Schema object naming conventions match expectations
- Log shows "[GraphQL Client] Schema object not found"

**Fix:**
- Adjust `_find_schema_object()` search logic
- Verify schema object fullname pattern

### Variable Resolution Fails

**Check:**
- gql definitions use standard `const NAME = gql`...`` pattern
- Template literal text extraction works
- Log shows gql definitions found

**Fix:**
- Add more patterns to `_extract_template_literal_text()`
- Handle different assignment styles

## Future Enhancements

### Short-term
1. Support for `useLazyQuery` and `useSubscription` hooks
2. Handle inline gql templates (no variable)
3. Better error messages in Imaging UI

### Medium-term  
1. Cross-file import resolution for shared queries
2. Support for GraphQL fragments
3. Link to specific fields within queries

### Long-term
1. Support for Relay, URQL, and other GraphQL clients
2. Detect REST-to-GraphQL gateway patterns
3. Custom quality rules for GraphQL best practices

## References

### Reference Extensions Studied
- **`com.castsoftware.uc.cgi.prospect.angular`**: Event patterns, AST traversal
- **`com.castsoftware.nodejs.2.12.1-funcrel`**: Advanced AST handling, object creation

### CAST SDK Documentation
- JavaScript AST API (from PDF)
- CustomObject creation patterns
- Link creation methods
- Event system documentation

### Source Code Examples
- **`App.jsx`**: Sample React component with Apollo Client
- **`schema.graphqls`**: Sample GraphQL schema

## Success Metrics

✅ **All Requirements Met:**
- [x] Event listeners implemented
- [x] AST traversal for useQuery/useMutation
- [x] Variable resolution to gql definitions  
- [x] GraphQL text parsing
- [x] Custom object creation
- [x] Linking to schema objects
- [x] Integration with main extension
- [x] Documentation updated
- [x] Error handling implemented

🎯 **Ready for Testing and Deployment**
