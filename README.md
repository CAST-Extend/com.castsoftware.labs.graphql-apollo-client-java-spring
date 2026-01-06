# GraphQL Universal Analyzer Extension

**Version:** 1.0.6  
**Author:** CAST  
**Namespace:** uc

---

## Overview

This CAST Universal Analyzer extension provides automated analysis of **GraphQL** applications including schema files and client-side code. It identifies GraphQL structures and creates call relationships to enable full-stack software architecture analysis in CAST Imaging.

### What This Extension Does

- ✅ **Schema Object Detection**: Extracts GraphQL types, queries, mutations from schema files
- ✅ **Client-Side Linking**: Links React/Apollo Client code to GraphQL schema objects
- ✅ **Full-Stack Transactions**: Enables end-to-end transaction analysis from UI to GraphQL operations
- ✅ **Smart Resolution**: Uses intelligent heuristics to match client operations to schema definitions

### Supported File Extensions

**Schema Files:** `*.graphql`, `*.gql`, `*.graphqls`  
**Client Files:** `*.js`, `*.jsx`, `*.ts`, `*.tsx` (via HTML5/JavaScript analyzer integration)

---

## Supported Code Structures

This extension detects and analyzes the following GraphQL constructs:

- **Program**: Top-level program definitions
- **Schema**: Top-level schema definitions
- **Type**: Type within Schema
- **Interface**: Interface within Schema
- **Enum**: Enum within Schema
- **EnumValue**: EnumValue within Enum
- **Input**: Input within Schema
- **Union**: Union within Schema
- **Scalar**: Scalar within Schema
- **Directive**: Directive within Schema
- **Field**: Field within Type
- **Argument**: Argument within Field
- **Query**: Query within Schema
- **Mutation**: Mutation within Schema
- **Subscription**: Subscription within Schema
- **Fragment**: Fragment within Schema
- **Variable**: Variable within Query

### Client-Side Objects (NEW in v1.0.6)

The extension also creates custom objects for GraphQL operations in React/JavaScript code:

- **CAST_GraphQL_ClientQuery**: Represents a `useQuery()` hook call
- **CAST_GraphQL_ClientMutation**: Represents a `useMutation()` hook call

These objects are created as children of JavaScript functions and linked to the corresponding GraphQL schema objects.

**Example hierarchy in Imaging:**
```
App.jsx
└── Function: App
    ├── CAST_GraphQL_ClientQuery "query:users"
    │   └── USE link → GraphQLQuery "users" (from schema.graphqls)
    └── CAST_GraphQL_ClientMutation "mutation:createUser"
        └── USE link → GraphQLMutation "createUser" (from schema.graphqls)
```

---

## Client-Side GraphQL Detection

### Supported Patterns

The extension detects Apollo Client GraphQL operations in React code:

| Pattern | Example | Detection |
|---------|---------|-----------|
| **useQuery hook** | `const { data } = useQuery(GET_USERS)` | ✅ Detected |
| **useMutation hook** | `const [createUser] = useMutation(CREATE_USER)` | ✅ Detected |
| **gql template literals** | ``const GET_USERS = gql`query GetUsers { users { id } }` `` | ✅ Parsed |
| **Named operations** | `query GetUsers { ... }` | ✅ Operation name extracted |
| **Anonymous queries** | `query { users { ... } }` | ✅ Field name extracted |

### How It Works

1. **Event-Driven Architecture**: Listens to HTML5/JavaScript analyzer events
2. **Two-Pass Analysis**:
   - Pass 1: Collect all `gql` template literal definitions
   - Pass 2: Find `useQuery`/`useMutation` calls and resolve variables
3. **Variable Resolution**: Traces query variable to its `gql` definition
4. **GraphQL Parsing**: Extracts operation type (query/mutation), name, and field
5. **Object Creation**: Creates custom client objects as children of JS functions
6. **Linking**: Creates USE links to existing GraphQL schema objects

### Example

Given this React code:

```javascript
import { gql, useQuery, useMutation } from "@apollo/client";

const GET_USERS = gql`
  query GetUsers {
    users { id name email }
  }
`;

const CREATE_USER = gql`
  mutation CreateUser($input: CreateUserInput!) {
    createUser(input: $input) { id name }
  }
`;

function App() {
  const { data } = useQuery(GET_USERS);
  const [createUser] = useMutation(CREATE_USER);
  // ...
}
```

The extension creates:
- `CAST_GraphQL_ClientQuery` object named "query:users" inside function `App`
- `CAST_GraphQL_ClientMutation` object named "mutation:createUser" inside function `App`
- USE links from these objects to the corresponding `GraphQLQuery` and `GraphQLMutation` objects in your schema

This enables **end-to-end transaction analysis** from React UI → GraphQL operations → Backend resolvers.

---

## Original Schema Link Detection (Legacy)

### What CAN Be Detected ✅

The extension reliably detects and creates links for:

| Call Type | Example | Resolution Strategy |
|-----------|---------|---------------------|
| **Direct function calls** | `myFunction()` | Same file first, then cross-file if unambiguous |
| **Self/this calls** | `self.method()`, `this.method()` | Only within the containing class |
| **Static/Class calls** | `MyClass.staticMethod()` | Exact fullname match |
| **Same-file calls** | Local function calling another local function | High confidence resolution |

### What CANNOT Be Detected ❌

Due to the limitations of regex-based parsing without full type inference:

| Call Type | Example | Why It Fails |
|-----------|---------|--------------|
| **Variable method calls** | `obj.method()` | Unknown variable type (requires static type analysis) |
| **Dynamic calls** | `getattr(obj, 'method')()` | Method name resolved at runtime |
| **Polymorphic calls** | `animal.speak()` | Type ambiguity (Dog/Cat/Bird) |
| **Callback references** | `callback()` where callback is passed as parameter | No reference tracking |

**Unresolved calls are reported** in the `GraphQL_UnresolvedCalls` report in CAST Imaging.

---

## Strict Resolution Strategy

To **avoid false positives**, the extension uses strict resolution rules:

### Rule 1: Self/This Calls
```# Example
self.helper_method()  # ✅ Resolved within current class only
```
- Searches **only** in the containing class
- High confidence, creates link

### Rule 2: Variable Calls (SKIPPED)
```# Example
obj.method()         # ❌ SKIPPED - type unknown
list.append(item)    # ❌ SKIPPED - type unknown
```
- Cannot determine variable type without static analysis
- **No link created** (prevents false positives)
- Logged in Unresolved Calls Report

### Rule 3: Direct Calls
```# Example
calculate_total()    # ✅ Resolved if unambiguous
```
- Same file preferred
- Cross-file **only if exactly ONE candidate**
- Multiple definitions → No link (ambiguous)

### Rule 4: Qualified Calls
```# Example
Math.abs(-5)         # ✅ Resolved by exact match
MyClass::method()    # ✅ Resolved by exact match
```
- Exact fullname lookup
- High confidence

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

2. **Copy the .nupkg file** to the extensions folder:
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

7. **Resume the analysis** (blue button, bottom right of **Overview**).

### Verification

After analysis completes, verify the extension worked:
- Check Analysis logs for `[GraphQL] Starting GraphQL analysis`
- Review the Analysis Summary for detected objects and links
- Check CAST Imaging for the `GraphQL_UnresolvedCalls` report

---

## Configuration

### Default Settings

The extension is pre-configured with sensible defaults for GraphQL:

- **File Extensions**: `*.graphql`, `*.gql`, `*.graphqls`
- **Comment Syntax**: `#`

- **Multi-line Comments**: `""" ... """`- **Block Delimiters**: braces

### Customizing Detection Patterns

If you need to adjust what gets detected, you can modify the generated source files:

1. **Edit patterns** in `graphql_module.py`:
   - Patterns are defined in the `PATTERN_MAPPING` dictionary
   - Each pattern uses regex with named groups like `(?P<name>\w+)`
   - Example: Function detection uses patterns from config's `grammar.patterns.function`

2. **Regenerate the .nupkg** by double-clicking:
   ```
   plugin-to-nupkg.bat
   ```

3. **Redeploy** the extension (repeat deployment steps above).

---

## Customization

### Adding Custom Object Types

To detect additional code structures:

1. **Edit the configuration** (if regenerating from scratch):
   ```json
   "objects": {
     "YourNewType": {
       "parent": "Program",
       "pattern_keys": ["your_pattern"]
     }
   }
   ```

2. **Add detection pattern**:
   ```python
   'your_pattern': [r'^\s*your_keyword\s+(?P<name>\w+)']
   ```

3. **Update MetaModel XML** to include the new type.

### Custom Call Detection

Override `_extract_calls()` in `graphql_module.py`:

```python
class GraphQLModule(GraphQLModule):
    def _extract_calls(self):
        # Call parent implementation
        super()._extract_calls()
        
        # Add custom detection logic
        for i, line in enumerate(self.source_content.splitlines(), 1):
            # Your custom regex here
            match = re.search(r'SPECIAL_CALL\s+(\w+)', line)
            if match:
                self.pending_links.append({
                    'caller': self._get_context_for_line(i),
                    'callee': match.group(1),
                    'type': 'call',
                    'line': i
                })
```

### Custom Symbol Resolution

> **Note:** A "symbol" is any named code element (function, class, method, variable) that can be referenced in code.

Override `resolve_symbol()` in the Library class for language-specific resolution:

```python
class GraphQLLibrary(GraphQLLibrary):
    def resolve_symbol(self, name, context_module=None, **kwargs):
        # Try standard resolution first
        result = super().resolve_symbol(name, context_module, **kwargs)
        if result[0]:
            return result
        
        # Add custom resolution logic
        # e.g., import-aware resolution, namespace lookup, etc.
        return None, None
```

---

## Analysis Output

### Objects Created

The extension creates CAST objects for each detected code structure:

```
GraphQL ANALYSIS SUMMARY
┌─── OBJECTS CREATED (X total) ───
│
│  myfile.graphql
│    └─ MyClass (Class)
│    └─ my_function (Function)
│    └─ helper (Function)
└─────────────────────────────────
```

### Links Created

Call relationships are created between objects:

```
┌─── LINKS CREATED (Y total) ───
│
│  Intra-file calls:
│    myfile.graphql:
│      my_function → helper (L23)
│      MyClass.method1 → MyClass.method2 (L45)
│
│  Inter-file calls:
│    fileA.graphql::funcA → fileB.graphql::funcB (L67)
└────────────────────────────────────
```

### Unresolved Calls Report

Transparency report showing what couldn't be resolved:

```
┌─── UNRESOLVED CALLS REPORT (Z total) ───
│
│  Variable call - type unknown (X occurrences)
│  Ambiguous - N definitions found (Y occurrences)
│  Symbol not found in project (Z occurrences)
└──────────────────────────────────────────────
```

Access the detailed report in CAST Imaging under Reports > `GraphQL_UnresolvedCalls`.

---

## Limitations

### Known Limitations

1. **No Type Inference**
   - Cannot resolve `variable.method()` calls without knowing variable type
   - Requires static type analysis (not implemented)

2. **Ambiguous Names**
   - Multiple functions with same name across files → No link created
   - Prevents false positives but misses some valid calls

3. **External Libraries**
   - Calls to external libraries (not in analyzed code) are not resolved
   - Appears in Unresolved Calls Report

4. **Dynamic Code**
   - Runtime-generated code not analyzed
   - `eval()`, `exec()`, reflection, metaprogramming not supported

5. **Complex Language Features**
   - Language-specific advanced features may not be fully supported
   - Regex-based parsing has inherent limitations

### Workarounds

- **Type hints**: Add inline comments for critical variable types
- **Manual links**: Use Application Level extension to create cross-technology links
- **Custom parsers**: Override parsing methods for specific constructs
- **External stubs**: Create stub definitions for external libraries if critical

---

## Troubleshooting

### No Objects Detected

**Symptom**: Analysis completes but no objects found.

**Possible causes**:
1. File extensions don't match configured patterns
2. Detection patterns don't match your code style
3. Files are binary or encoded incorrectly

**Solutions**:
- Check file extensions in configuration
- Review detection patterns in `graphql_module.py`
- Verify source files are UTF-8 text

### Too Many Unresolved Calls

**Symptom**: Most calls appear in Unresolved Calls Report.

**Possible causes**:
1. Heavy use of OOP with variable method calls (expected)
2. Missing object types in configuration
3. Naming conventions don't match detection patterns

**Solutions**:
- Review the report to identify patterns
- Add missing object types if needed
- Consider custom resolution for your codebase

### False Positive Links

**Symptom**: Links created between unrelated code.

**This should be rare** due to strict resolution. If it occurs:
1. Check for naming collisions (same names in different contexts)
2. Review fullname construction (should include full path)
3. Report the issue with code samples

### Analysis Errors

**Symptom**: Extension crashes or throws exceptions.

**Solutions**:
1. Check Analysis logs for error details
2. Verify source files are valid GraphQL code
3. Look for edge cases in regex patterns
4. Review graphql_analyser_level.py logs

---

## Performance

### Typical Performance

- **Light Parse** (Phase 1): ~1000 files/minute
- **Full Parse** (Phase 2): ~500 files/minute
- **Memory**: ~100MB for 10,000 files

### Optimization Tips

1. **Exclude unnecessary files**: Configure `.castignore` to skip test files, generated code, etc.
2. **Simplify patterns**: Complex regex patterns slow down parsing
3. **Limit keywords list**: Only include essential keywords to exclude

---

## Support

### Getting Help

1. **Documentation**: First, consult the main generator README and this documentation
2. **Logs**: Check CAST Analysis logs for detailed execution trace
3. **Reports**: Review Unresolved Calls Report for insight into limitations
4. **Contact**: For questions or support, contact **Ayoub ALA** (Solutions Architect, NY)

### Contributing

This extension was generated by the CAST Extension Generator. To improve it:

1. **Report issues**: Document edge cases and unexpected behavior
2. **Share patterns**: Contribute improved regex patterns
3. **Custom implementations**: Share successful customizations

---

## Version History

### 1.0.5 (Current)
- Initial release
- Strict resolution to avoid false positives
- Unresolved calls reporting
- Support for GraphQL core constructs

---

## License

See COPYING.LESSER.txt for license information.

---

## Technical Details

### Architecture

```
GraphQLAnalyzerExtension (analyser_level)
    ├─ Phase 1: Light Parse
    │   ├─ Read source files
    │   ├─ Extract global structures
    │   └─ Create CAST objects
    │
    └─ Phase 2: Full Parse & Resolution
        ├─ Extract calls
        ├─ Resolve references (strict)
        ├─ Create links
        └─ Generate reports

GraphQLLibrary
    ├─ Global symbol table
    ├─ Resolution with ambiguity detection
    └─ Multi-file coordination

GraphQLModule
    ├─ File-level parsing
    ├─ AST construction
    └─ Link tracking
```

### File Structure

```
com.castsoftware.uc.graphql/
├── configuration/
│   └── Languages/
│       └── GraphQL/
│           ├── GraphQLMetaModel.xml
│           └── GraphQLLanguagePattern.xml
├── graphql_analyser_level.py      # Main analyzer
├── graphql_module.py              # File parser
├── graphql_application_level.py   # Cross-tech hooks
├── plugin.nuspec                       # Package metadata
└── README.md                           # This file
```

---

**Generated by CAST Extension Generator**  
For questions or issues, refer to the generator documentation.
