# -*- coding: utf-8 -*-
"""
GraphQL Client Analyzer - Two-level extraction for Apollo Client

LEVEL 1: gql definitions (GraphQLClientQuery/Mutation/Subscription)
  - Extracts gql`...` template literals
  - Creates objects for query/mutation/subscription definitions
  
LEVEL 2: Apollo hook calls (GraphQL*Request)
  - Extracts useQuery/useLazyQuery/useMutation/useSubscription
  - Creates objects for hook usage
  - Links to LEVEL 1 definitions

Architecture:
- Event-driven: Listens to HTML5/JS analyzer broadcasts
- AST traversal: Finds both gql definitions and hook calls
- Linking: Request objects → Client definitions → Schema fields
"""

import re
import traceback
from cast.analysers import ua, log, CustomObject, Bookmark, create_link
from cast import Event


def is_function_call(ast):
    """Check if AST node is a function call."""
    try:
        return ast.is_function_call()
    except:
        return False


def is_function_call_part(ast):
    """Check if AST node is a function call part."""
    try:
        return ast.is_function_call_part()
    except:
        return False


class GraphQLClientAnalyzer(ua.Extension):
    """
    Two-level GraphQL client analysis:
    - LEVEL 1: gql definitions 
    - LEVEL 2: Apollo hook calls
    """
    
    def __init__(self):
        self.graphql_jscontent = []
        self.gql_definitions = {}  # Map variable name to client object
    
    def _get_function_parameters(self, ast):
        """
        Extract parameters from FunctionCall or FunctionCallPart.
        
        FunctionCall (e.g., gql`...`) needs to access its first FunctionCallPart.
        FunctionCallPart (e.g., useQuery(...)) has direct access to parameters.
        """
        try:
            log.info('[GraphQL Client] _get_function_parameters: ast type=' + str(type(ast)))
            
            # Case 1: FunctionCall (has get_function_call_parts())
            if is_function_call(ast):
                log.info('[GraphQL Client]   -> Detected as FunctionCall, getting first part...')
                parts = ast.get_function_call_parts()
                log.info('[GraphQL Client]   -> Found ' + str(len(parts) if parts else 0) + ' function call parts')
                if parts and len(parts) > 0:
                    params = parts[0].get_parameters()
                    log.info('[GraphQL Client]   -> Extracted ' + str(len(params)) + ' parameters from first part')
                    return params
                log.info('[GraphQL Client]   -> No parts found, returning empty list')
                return []
            
            # Case 2: FunctionCallPart (has get_parameters() directly)
            elif is_function_call_part(ast):
                log.info('[GraphQL Client]   -> Detected as FunctionCallPart, getting parameters directly...')
                params = ast.get_parameters()
                log.info('[GraphQL Client]   -> Extracted ' + str(len(params)) + ' parameters')
                return params
            
            # Case 3: Unknown type, try get_parameters() anyway
            elif hasattr(ast, 'get_parameters'):
                log.info('[GraphQL Client]   -> Unknown type but has get_parameters(), trying anyway...')
                params = ast.get_parameters()
                log.info('[GraphQL Client]   -> Extracted ' + str(len(params)) + ' parameters')
                return params
            
            log.info('[GraphQL Client]   -> No known method to extract parameters from type: ' + str(type(ast)))
            return []
        except Exception as e:
            log.info('[GraphQL Client] Error in _get_function_parameters: ' + str(e))
            log.info('[GraphQL Client] ' + traceback.format_exc())
            return []
    
    @Event('com.castsoftware.html5', 'start_javascript_content')
    def on_start_javascript_content(self, jsContent):
        """
        LEVEL 0: Collect files with GraphQL imports.
        
        Called for each JavaScript/JSX file during analysis.
        Filters files that import Apollo Client hooks or gql template tag.
        """
        try:
            file_path = str(jsContent.get_file().get_path())
            log.info('[GraphQL Client] Processing file: ' + file_path)
            
            # Log jsContent structure for local testing
            log.info('[GraphQL Client] jsContent type: ' + str(type(jsContent)))
            log.info('[GraphQL Client] jsContent methods: ' + str(dir(jsContent)))
            
            # Check imports for GraphQL-related symbols
            imports = jsContent.get_imports()
            log.info('[GraphQL Client] Found ' + str(len(list(imports))) + ' imports')
            
            for _import in jsContent.get_imports():
                import_name = _import.get_what_name()
                log.info('[GraphQL Client]   - Import: ' + str(import_name))
                
                # Filter: only process files that use Apollo Client or gql
                if import_name in ['useQuery', 'useLazyQuery', 'useMutation', 'useSubscription', 'gql']:
                    self.graphql_jscontent.append(jsContent)
                    log.info('[GraphQL Client] ✓ File added for processing: ' + file_path)
                    break
                    
        except Exception as e:
            log.info('[GraphQL Client] Error in start_javascript_content: ' + str(e))
            log.info('[GraphQL Client] ' + traceback.format_exc())
    
    @Event('com.castsoftware.html5', 'end_javascript_contents')
    def on_end_javascript_contents(self):
        """Process all GraphQL files."""
        try:
            log.info('[GraphQL Client] Processing ' + str(len(self.graphql_jscontent)) + ' files')
            
            for jscontent in self.graphql_jscontent:
                self._process_graphql_content(jscontent)
            
            log.info('[GraphQL Client] Analysis complete')
            
        except Exception as e:
            log.info('[GraphQL Client] Error in end_javascript_contents: ' + str(e))
    
    def _process_graphql_content(self, jscontent):
        """
        Process one file for both LEVEL 1 and LEVEL 2 extraction.
        
        Two-phase approach:
        1. Extract all gql definitions first (LEVEL 1)
        2. Extract all Apollo hook calls (LEVEL 2)
        
        This order ensures gql_definitions dict is populated before 
        hook calls try to link to them.
        """
        try:
            file_path = str(jscontent.get_file().get_path())
            log.info('[GraphQL Client] ========================================')
            log.info('[GraphQL Client] Processing file: ' + file_path)
            log.info('[GraphQL Client] ========================================')
            
            # Debug: Print full jscontent structure
            log.info('[GraphQL Client] === JSCONTENT INSPECTION ===')
            log.info('[GraphQL Client] jscontent type: ' + str(type(jscontent)))
            log.info('[GraphQL Client] jscontent dir: ' + str([m for m in dir(jscontent) if not m.startswith('_')]))
            
            # Try to get children
            try:
                children = jscontent.get_children()
                log.info('[GraphQL Client] jscontent.get_children() count: ' + str(len(list(children))))
                children = jscontent.get_children()  # Re-get since we consumed it
                if children:
                    for idx, child in enumerate(children):
                        if idx < 5:  # Limit to first 5
                            log.info('[GraphQL Client]   Child ' + str(idx) + ': type=' + str(type(child)) + ', name=' + str(getattr(child, 'get_name', lambda: 'N/A')()))
            except Exception as e:
                log.info('[GraphQL Client] Error getting children: ' + str(e))
            
            # Try to get file content
            try:
                file_obj = jscontent.get_file()
                log.info('[GraphQL Client] file object: ' + str(file_obj))
                log.info('[GraphQL Client] file path: ' + str(file_obj.get_path()))
            except Exception as e:
                log.info('[GraphQL Client] Error getting file: ' + str(e))
            
            log.info('[GraphQL Client] === END JSCONTENT INSPECTION ===')
            
            # LEVEL 1: Extract gql`...` definitions
            # Creates GraphQLClientQuery/Mutation/Subscription objects
            log.info('[GraphQL Client] LEVEL 1: Extracting gql definitions...')
            
            # Debug: Check if we have a valid AST root
            root = jscontent.get_children()[0] if jscontent.get_children() else None
            log.info('[GraphQL Client] AST root: ' + str(root))
            log.info('[GraphQL Client] AST root type: ' + str(type(root) if root else 'None'))
            if root:
                log.info('[GraphQL Client] AST root has ' + str(len(list(root.get_children()))) + ' children')
            
            gql_defs = self._extract_gql_definitions(jscontent)
            log.info('[GraphQL Client] Found ' + str(len(gql_defs)) + ' gql definitions')
            
            for gql_def in gql_defs:
                self._create_client_definition(gql_def, jscontent)
            
            # LEVEL 2: Extract Apollo hook calls
            # Creates GraphQL*Request objects that link to LEVEL 1 objects
            log.info('[GraphQL Client] LEVEL 2: Extracting Apollo hooks...')
            hook_calls = self._extract_apollo_hooks(jscontent)
            log.info('[GraphQL Client] Found ' + str(len(hook_calls)) + ' Apollo hook calls')
            
            for hook_call in hook_calls:
                self._create_request_object(hook_call, jscontent)
            
            log.info('[GraphQL Client] File processing complete: ' + file_path)
                
        except Exception as e:
            log.info('[GraphQL Client] Error processing content: ' + str(e))
            log.info('[GraphQL Client] ' + traceback.format_exc())
    
    def _extract_gql_definitions(self, jscontent):
        """LEVEL 1: Extract gql`...` definitions."""
        definitions = []
        
        # BUGFIX: Traverse ALL children, not just the first one
        log.info('[GraphQL Client] Traversing all jscontent children for gql definitions...')
        for idx, child in enumerate(jscontent.get_children()):
            log.info('[GraphQL Client]   Searching child ' + str(idx) + ': ' + str(type(child)))
            self._find_gql_definitions(child, definitions)
        
        return definitions
    
    def _find_gql_definitions(self, ast, results):
        """Recursively find gql template literals."""
        if not ast:
            return
        
        try:
            # Debug: log every node we traverse
            node_name = 'unknown'
            try:
                node_name = ast.get_name()
            except:
                pass
            
            is_call = is_function_call(ast)
            
            # Log when we find 'gql' anywhere
            if node_name == 'gql':
                log.info('[GraphQL Client] >>> Found node named "gql", is_function_call=' + str(is_call))
                log.info('[GraphQL Client]     Node type: ' + str(type(ast)))
                log.info('[GraphQL Client]     Node methods: ' + str([m for m in dir(ast) if not m.startswith('_')]))
            
            if is_call and node_name == 'gql':
                log.info('[GraphQL Client] ✓ FOUND gql definition!')
                results.append(ast)
            
            for child in ast.get_children():
                self._find_gql_definitions(child, results)
        except Exception as e:
            log.info('[GraphQL Client] Error in _find_gql_definitions: ' + str(e))
    
    def _create_client_definition(self, gql_ast, jscontent):
        """
        LEVEL 1: Create GraphQLClient* object for gql definition.
        
        Example input:
            export const GET_USERS = gql`query GetUsers { users { id } }`;
        
        Creates:
            - Object type: GraphQLClientQuery
            - Name: GET_USERS (variable name)
            - Properties: operationName, rawQueryText, variables, fieldsSelected, aliases
        """
        try:
            log.info('[GraphQL Client] >>> Entering _create_client_definition')
            
            # Step 1: Extract GraphQL text from gql template literal
            graphql_text = self._extract_gql_text(gql_ast)
            if not graphql_text:
                log.info('[GraphQL Client] FAILED: Could not extract gql text, skipping')
                return
            
            log.info('[GraphQL Client] Extracted GraphQL text (first 100 chars): ' + graphql_text[:100])
            
            # Step 2: Parse GraphQL operation to extract metadata
            operation_data = self._parse_operation(graphql_text)
            if not operation_data:
                log.info('[GraphQL Client] FAILED: Could not parse GraphQL operation, skipping')
                log.info('[GraphQL Client] GraphQL text: ' + graphql_text)
                return
            
            log.info('[GraphQL Client]     ✓ Parsed operation successfully')
            log.info('[GraphQL Client]       - Type: ' + str(operation_data.get('type')))
            log.info('[GraphQL Client]       - Operation name: ' + str(operation_data.get('operationName')))
            log.info('[GraphQL Client]       - Fields selected: ' + str(operation_data.get('fieldsSelected')))
            log.info('[GraphQL Client]       - Variables: ' + str(operation_data.get('variables')))
            
            # Step 3: Determine object type based on operation type
            op_type = operation_data['type']
            if op_type == 'query':
                object_type = 'GraphQLClientQuery'
            elif op_type == 'mutation':
                object_type = 'GraphQLClientMutation'
            elif op_type == 'subscription':
                object_type = 'GraphQLClientSubscription'
            else:
                log.info('[GraphQL Client] Unknown operation type: ' + str(op_type))
                return
            
            # Step 4: Get variable name (e.g., GET_USERS)
            variable_name = self._get_variable_name(gql_ast)
            if not variable_name:
                log.info('[GraphQL Client] FAILED: Could not determine variable name, skipping')
                log.info('[GraphQL Client] Operation type: ' + str(op_type) + ', operation name: ' + str(operation_data.get('operationName')))
                return
            
            # Step 5: Build unique fullname (file:line format)
            file_path = str(jscontent.get_file().get_path())
            line_num = self._get_line_number(gql_ast)
            fullname = file_path + ':' + str(line_num)
            
            log.info('[GraphQL Client] Creating ' + object_type + ': ' + variable_name)
            log.info('[GraphQL Client]   - Fullname: ' + fullname)
            log.info('[GraphQL Client]   - Operation: ' + str(operation_data.get('operationName', 'anonymous')))
            
            # Step 6: Create CAST custom object
            client_obj = CustomObject()
            client_obj.set_type(object_type)
            client_obj.set_name(variable_name)
            client_obj.set_fullname(fullname)
            
            # Step 7: Set parent (file-level KB object)
            parent_kb = self._get_file_parent(jscontent)
            if parent_kb:
                client_obj.set_parent(parent_kb)
                log.info('[GraphQL Client]   - Parent: ' + str(parent_kb))
            
            # Step 8: Save object to KB (MUST be done before save_property)
            client_obj.save()
            
            # Step 9: Save properties (AFTER save())
            client_obj.save_property('GraphQL_Client_Definition.operationName', operation_data.get('operationName', ''))
            client_obj.save_property('GraphQL_Client_Definition.rawQueryText', graphql_text)
            
            # Convert lists to comma-separated strings (save_property only accepts str or int)
            if operation_data.get('variables'):
                variables_str = ', '.join(operation_data['variables'])
                log.info('[GraphQL Client]     ✓ Saving property: variables = "' + variables_str + '"')
                client_obj.save_property('GraphQL_Client_Definition.variables', variables_str)
            
            if operation_data.get('fieldsSelected'):
                fields_str = ', '.join(operation_data['fieldsSelected'])
                log.info('[GraphQL Client]     ✓ Saving property: fieldsSelected = "' + fields_str + '"')
                client_obj.save_property('GraphQL_Client_Definition.fieldsSelected', fields_str)
            else:
                log.info('[GraphQL Client]     ✗ NO fieldsSelected to save! operation_data["fieldsSelected"] = ' + str(operation_data.get('fieldsSelected')))
            
            if operation_data.get('aliases'):
                log.info('[GraphQL Client]     ✓ Saving ' + str(len(operation_data['aliases'])) + ' aliases')
                for alias, field in operation_data['aliases'].items():
                    client_obj.save_property('GraphQL_Client_Definition.alias.' + alias, field)
            
            # Step 10: Create bookmark for source navigation
            try:
                bookmark = gql_ast.create_bookmark(jscontent.get_file())
                client_obj.save_position(bookmark)
                log.info('[GraphQL Client]   - Bookmark saved')
            except Exception as e:
                log.info('[GraphQL Client]   - Could not create bookmark: ' + str(e))
            
            # Step 11: Store in cache for LEVEL 2 linking
            log.info('[GraphQL Client] >>> Storing definition in cache')
            log.info('[GraphQL Client]     KEY (variable_name): "' + variable_name + '"')
            log.info('[GraphQL Client]     VALUE (object type): ' + object_type)
            self.gql_definitions[variable_name] = client_obj
            log.info('[GraphQL Client]     Cache now contains ' + str(len(self.gql_definitions)) + ' definition(s): ' + str(list(self.gql_definitions.keys())))
            log.info('[GraphQL Client] ✓ Created ' + object_type + ': ' + variable_name)
            
        except Exception as e:
            log.info('[GraphQL Client] Error creating definition: ' + str(e))
            log.info('[GraphQL Client] ' + traceback.format_exc())
    
    def _extract_apollo_hooks(self, jscontent):
        """LEVEL 2: Extract Apollo hook calls."""
        hooks = []
        
        # BUGFIX: Traverse ALL children, not just the first one
        log.info('[GraphQL Client] Traversing all jscontent children for Apollo hooks...')
        for idx, child in enumerate(jscontent.get_children()):
            log.info('[GraphQL Client]   Searching child ' + str(idx) + ': ' + str(type(child)))
            self._find_apollo_hooks(child, hooks)
        
        return hooks
    
    def _find_apollo_hooks(self, ast, results):
        """Recursively find Apollo hook calls."""
        if not ast:
            return
        
        try:
            # Debug: log when we encounter hooks
            node_name = 'unknown'
            try:
                node_name = ast.get_name()
            except:
                pass
            
            is_call_part = is_function_call_part(ast)
            
            # Log when we find hook names anywhere
            if node_name in ['useQuery', 'useLazyQuery', 'useMutation', 'useSubscription']:
                log.info('[GraphQL Client] >>> Found node named "' + node_name + '", is_function_call_part=' + str(is_call_part))
                log.info('[GraphQL Client]     Node type: ' + str(type(ast)))
            
            if is_call_part and node_name in ['useQuery', 'useLazyQuery', 'useMutation', 'useSubscription']:
                log.info('[GraphQL Client] ✓ FOUND Apollo hook: ' + node_name)
                results.append(ast)
            
            for child in ast.get_children():
                self._find_apollo_hooks(child, results)
        except Exception as e:
            log.info('[GraphQL Client] Error in _find_apollo_hooks: ' + str(e))
    
    def _create_request_object(self, hook_ast, jscontent):
        """
        LEVEL 2: Create GraphQL*Request object for Apollo hook call.
        
        Example input:
            const { data } = useQuery(GET_USERS, { fetchPolicy: 'cache-first' });
        
        Creates:
            - Object type: GraphQLQueryRequest
            - Name: GET_USERS (query variable name)
            - Properties: hookType, fetchPolicy, errorPolicy
            - Links: CALL (parent -> request), USES (request -> client definition)
        """
        try:
            hook_name = hook_ast.get_name()
            log.info('[GraphQL Client] Processing hook: ' + hook_name)
            
            # Step 1: Extract query name from first parameter
            params = self._get_function_parameters(hook_ast)
            if not params:
                log.info('[GraphQL Client] No parameters found for hook, skipping')
                return
            
            log.info('[GraphQL Client] Hook has ' + str(len(params)) + ' parameters')
            
            query_name = self._get_query_name_from_param(params[0])
            if not query_name:
                log.info('[GraphQL Client] Could not extract query name from parameter, skipping')
                return
            
            log.info('[GraphQL Client] Query name: ' + query_name)
            
            # Step 2: Determine object type based on hook type
            if hook_name == 'useQuery':
                object_type = 'GraphQLQueryRequest'
            elif hook_name == 'useLazyQuery':
                object_type = 'GraphQLLazyQueryRequest'
            elif hook_name == 'useMutation':
                object_type = 'GraphQLMutationRequest'
            elif hook_name == 'useSubscription':
                object_type = 'GraphQLSubscriptionRequest'
            else:
                log.info('[GraphQL Client] Unknown hook type: ' + hook_name)
                return
            
            # Step 3: Get parent component (KB object)
            parent_kb = hook_ast.get_first_kb_parent()
            if not parent_kb:
                log.info('[GraphQL Client] No KB parent found, skipping')
                return
            
            parent_obj = parent_kb.get_kb_object()
            if not parent_obj:
                log.info('[GraphQL Client] Parent has no KB object, skipping')
                return
            
            log.info('[GraphQL Client] Parent: ' + str(parent_obj))
            
            # Step 4: Build unique fullname (file:line format)
            file_path = str(jscontent.get_file().get_path())
            line_num = self._get_line_number(hook_ast)
            fullname = file_path + ':' + str(line_num)
            
            # Step 4b: Build unique name by prepending hook type to query name
            # This differentiates Request objects from Client Definition objects
            # Example: useQuery + GET_USERS → useQuery:GET_USERS
            unique_request_name = hook_name + ':' + query_name
            
            log.info('[GraphQL Client] Creating ' + object_type + ': ' + unique_request_name)
            log.info('[GraphQL Client]   - Fullname: ' + fullname)
            log.info('[GraphQL Client]   - Parent component: ' + str(parent_obj.get_fullname() if hasattr(parent_obj, 'get_fullname') else parent_obj))
            
            # Step 5: Create CAST custom object
            request_obj = CustomObject()
            request_obj.set_type(object_type)
            request_obj.set_name(unique_request_name)
            request_obj.set_fullname(fullname)
            request_obj.set_parent(parent_obj)
            
            # Step 6: Save object to KB (MUST be done before save_property)
            request_obj.save()
            
            # Step 7: Save properties (AFTER save())
            request_obj.save_property('GraphQL_Hook_Request.hookType', hook_name)
            
            # Extract options from second parameter if present
            options = self._extract_hook_options(params)
            if options.get('fetchPolicy'):
                log.info('[GraphQL Client]   - fetchPolicy: ' + options['fetchPolicy'])
                request_obj.save_property('GraphQL_Hook_Request.fetchPolicy', options['fetchPolicy'])
            if options.get('errorPolicy'):
                log.info('[GraphQL Client]   - errorPolicy: ' + options['errorPolicy'])
                request_obj.save_property('GraphQL_Hook_Request.errorPolicy', options['errorPolicy'])
            
            # Step 8: Create bookmark and CALL link (component -> request)
            try:
                bookmark = hook_ast.create_bookmark(jscontent.get_file())
                request_obj.save_position(bookmark)
                create_link('callLink', parent_obj, request_obj, bookmark)
                log.info('[GraphQL Client]   - CALL link created (with bookmark)')
            except:
                try:
                    create_link('callLink', parent_obj, request_obj)
                    log.info('[GraphQL Client]   - CALL link created (no bookmark)')
                except Exception as e:
                    log.info('[GraphQL Client]   - Could not create CALL link: ' + str(e))
            
            # Step 9: Create USES link (request -> client definition)
            log.info('[GraphQL Client] >>> Searching for client definition')
            log.info('[GraphQL Client]     SEARCHING FOR: "' + query_name + '"')
            log.info('[GraphQL Client]     AVAILABLE KEYS: ' + str(list(self.gql_definitions.keys())))
            log.info('[GraphQL Client]     Cache size: ' + str(len(self.gql_definitions)))
            
            if query_name in self.gql_definitions:
                client_obj = self.gql_definitions[query_name]
                log.info('[GraphQL Client]     ✓ MATCH FOUND!')
                try:
                    create_link('useLink', request_obj, client_obj)
                    log.info('[GraphQL Client]   - ✓ USES link created: ' + object_type + ' -> ' + query_name)
                except Exception as e:
                    log.info('[GraphQL Client]   - Could not create USES link: ' + str(e))
            else:
                log.info('[GraphQL Client]     ✗ NO MATCH FOUND!')
                log.info('[GraphQL Client]   - No client definition found for: ' + query_name)
                log.info('[GraphQL Client]   - Available definitions: ' + str(list(self.gql_definitions.keys())))
                # Comparaison caractère par caractère pour debug
                for available_key in self.gql_definitions.keys():
                    if available_key.upper() == query_name.upper():
                        log.info('[GraphQL Client]   - CASE MISMATCH detected: "' + available_key + '" vs "' + query_name + '"')
                    else:
                        log.info('[GraphQL Client]   - Comparing "' + available_key + '" vs "' + query_name + '" (len: ' + str(len(available_key)) + ' vs ' + str(len(query_name)) + ')')
            
            log.info('[GraphQL Client] ✓ Created ' + object_type + ': ' + query_name)
            
        except Exception as e:
            log.info('[GraphQL Client] Error creating request: ' + str(e))
            log.info('[GraphQL Client] ' + traceback.format_exc())
    
    def _extract_gql_text(self, gql_ast):
        """Extract GraphQL text from gql template literal."""
        try:
            log.info('[GraphQL Client] >>> _extract_gql_text: Starting extraction')
            log.info('[GraphQL Client]     gql_ast type: ' + str(type(gql_ast)))
            
            params = self._get_function_parameters(gql_ast)
            log.info('[GraphQL Client]     _get_function_parameters() returned: ' + str(type(params)) + ' with ' + str(len(params) if params else 0) + ' items')
            
            if not params:
                log.info('[GraphQL Client]     ✗ No parameters found in gql call')
                return None
            
            text_param = params[0]
            log.info('[GraphQL Client]     First parameter type: ' + str(type(text_param)))
            log.info('[GraphQL Client]     First parameter methods: ' + str([m for m in dir(text_param) if not m.startswith('_')][:20]))
            
            evs = text_param.evaluate()
            log.info('[GraphQL Client]     evaluate() returned: ' + str(type(evs)) + ' with ' + str(len(list(evs)) if evs else 0) + ' items')
            
            if not evs:
                log.info('[GraphQL Client]     ✗ No evaluations returned from text_param.evaluate()')
                return None
            
            evs = text_param.evaluate()  # Re-evaluate since we consumed the iterator
            for idx, ev in enumerate(evs):
                log.info('[GraphQL Client]       Evaluation ' + str(idx) + ': type=' + str(type(ev)) + ', str=' + str(ev)[:100])
                text = str(ev).strip('`').strip()
                
                # Clean CAST metadata (tab-separated values after the GraphQL text)
                # Example: "query { ... }\t0 ; 0\t0\t\t0\t[Module name]"
                if '\t' in text:
                    text = text.split('\t')[0].strip()
                    log.info('[GraphQL Client]       Cleaned metadata from text')
                
                if text:
                    log.info('[GraphQL Client]     ✓ Extracted gql text (first 100 chars): ' + text[:100])
                    return text
            
            log.info('[GraphQL Client]     ✗ No valid text found in evaluations')
            return None
        except Exception as e:
            log.info('[GraphQL Client]     ✗ Exception in _extract_gql_text: ' + str(e))
            log.info('[GraphQL Client]     ' + traceback.format_exc())
            return None
    
    def _get_variable_name(self, gql_ast):
        """Get the variable name for gql definition (e.g., GET_USERS)."""
        try:
            log.info('[GraphQL Client] >>> _get_variable_name: Starting extraction')
            log.info('[GraphQL Client]     gql_ast type: ' + str(type(gql_ast)))
            
            # Navigate up the AST tree to find the variable name
            # For: const GET_USERS = gql`...`
            # AST structure: VarDeclaration -> Assignment -> Identifier (left) / FunctionCall (right)
            
            current = gql_ast
            for level in range(10):  # Limit depth to avoid infinite loops
                parent = current.get_parent()
                if not parent:
                    log.info('[GraphQL Client]     Level ' + str(level) + ': No parent found')
                    break
                
                parent_type = str(type(parent).__name__)
                log.info('[GraphQL Client]     Level ' + str(level) + ': parent type=' + parent_type)
                
                # Check if parent is an Assignment
                if hasattr(parent, 'is_assignment') and parent.is_assignment():
                    log.info('[GraphQL Client]     Found Assignment at level ' + str(level))
                    # Try to get left operand (variable name)
                    if hasattr(parent, 'get_left_operand'):
                        left = parent.get_left_operand()
                        if left and hasattr(left, 'get_name'):
                            name = left.get_name()
                            log.info('[GraphQL Client]       Assignment.left.get_name(): ' + str(name))
                            if name and name not in ['unknown', 'const', 'let', 'var']:
                                log.info('[GraphQL Client]     ✓ Variable name from Assignment.left: ' + name)
                                return name
                
                # Check if parent has a useful name
                if hasattr(parent, 'get_name'):
                    name = parent.get_name()
                    log.info('[GraphQL Client]       parent.get_name(): ' + str(name))
                    if name and name not in ['unknown', 'const', 'let', 'var', None]:
                        log.info('[GraphQL Client]     ✓ Variable name from parent level ' + str(level) + ': ' + name)
                        return name
                
                current = parent
            
            fallback = 'anonymous_gql_' + str(id(gql_ast))
            log.info('[GraphQL Client]     ✗ No variable name found after traversing AST, using fallback: ' + fallback)
            return fallback
        except Exception as e:
            fallback = 'anonymous_gql_' + str(id(gql_ast))
            log.info('[GraphQL Client]     ✗ Exception in _get_variable_name: ' + str(e))
            log.info('[GraphQL Client]     ' + traceback.format_exc())
            log.info('[GraphQL Client]     Using fallback: ' + fallback)
            return fallback
    
    def _get_query_name_from_param(self, param_ast):
        """Extract query variable name from hook parameter."""
        try:
            log.info('[GraphQL Client] >>> _get_query_name_from_param: Starting extraction')
            log.info('[GraphQL Client]     param_ast type: ' + str(type(param_ast)))
            
            if hasattr(param_ast, 'get_name'):
                name = param_ast.get_name()
                log.info('[GraphQL Client]     param_ast.get_name(): ' + str(name))
                if name and name != 'unknown':
                    log.info('[GraphQL Client]     ✓ Query name from PARAM.get_name(): ' + name)
                    return name
            
            evs = param_ast.evaluate_ast()
            log.info('[GraphQL Client]     param_ast.evaluate_ast() returned ' + str(len(evs) if evs else 0) + ' evaluations')
            
            if evs:
                for idx, ev in enumerate(evs):
                    log.info('[GraphQL Client]       Evaluation ' + str(idx) + ': type=' + str(type(ev)))
                    if hasattr(ev, 'get_name'):
                        name = ev.get_name()
                        log.info('[GraphQL Client]       ev.get_name(): ' + str(name))
                        if name and name != 'unknown' and name != 'gql':
                            log.info('[GraphQL Client]     ✓ Query name from EVALUATION: ' + name)
                            return name
            
            log.info('[GraphQL Client]     ✗ No query name found in parameter')
            return None
        except Exception as e:
            log.info('[GraphQL Client]     ✗ Exception in _get_query_name_from_param: ' + str(e))
            log.info('[GraphQL Client]     ' + traceback.format_exc())
            return None
    
    def _extract_hook_options(self, params):
        """Extract fetchPolicy, errorPolicy from hook options."""
        options = {}
        if len(params) < 2:
            return options
        
        try:
            options_param = params[1]
            children = options_param.get_children()
            
            for child in children:
                try:
                    if hasattr(child, 'get_name'):
                        opt_name = child.get_name()
                        if opt_name in ['fetchPolicy', 'errorPolicy']:
                            value = self._extract_option_value(child)
                            if value:
                                options[opt_name] = value
                except:
                    pass
        except:
            pass
        
        return options
    
    def _extract_option_value(self, option_ast):
        """Extract string value from option node."""
        try:
            children = option_ast.get_children()
            if children:
                evs = children[0].evaluate()
                if evs:
                    for ev in evs:
                        val = str(ev).strip('"').strip("'")
                        if val:
                            return val
        except:
            pass
        return None
    
    def _get_line_number(self, ast):
        """Get line number from AST node."""
        try:
            if hasattr(ast, 'get_position'):
                pos = ast.get_position()
                if pos and hasattr(pos, 'get_line'):
                    return pos.get_line()
        except:
            pass
        return 0
    
    def _get_file_parent(self, jscontent):
        """Get file-level parent KB object."""
        try:
            log.info('[GraphQL Client] _get_file_parent: jscontent type=' + str(type(jscontent)))
            
            # Option 1: Try to get JavaScript initialisation (preferred for JsContent)
            if hasattr(jscontent, 'create_javascript_initialisation'):
                parent = jscontent.create_javascript_initialisation()
                log.info('[GraphQL Client]   -> Got javascript_initialisation: ' + str(parent))
                if parent:
                    return parent
            
            # Option 2: Try to get KB object from JsContent itself
            if hasattr(jscontent, 'get_kb_object'):
                parent = jscontent.get_kb_object()
                log.info('[GraphQL Client]   -> Got KB object from jscontent: ' + str(parent))
                if parent:
                    return parent
            
            # Option 3: Try to get file's KB object
            file_obj = jscontent.get_file()
            if file_obj:
                log.info('[GraphQL Client]   -> file_obj: ' + str(file_obj))
                if hasattr(file_obj, 'get_kb_object'):
                    parent = file_obj.get_kb_object()
                    log.info('[GraphQL Client]   -> Got KB object from file: ' + str(parent))
                    if parent:
                        return parent
            
            log.info('[GraphQL Client]   -> No valid parent KB object found')
        except Exception as e:
            log.info('[GraphQL Client] Error in _get_file_parent: ' + str(e))
            log.info('[GraphQL Client] ' + traceback.format_exc())
        return None
    
    def _parse_operation(self, graphql_text):
        """
        Parse GraphQL operation to extract metadata.
        
        Handles:
        - Named operations: query GetUsers($id: ID!) { ... }
        - Anonymous operations: query { ... }
        - Mutations and subscriptions
        
        Returns dict with: type, operationName, variables, fieldsSelected, aliases
        """
        try:
            text = graphql_text.strip()
            log.info('[GraphQL Client]     >>> Parsing GraphQL operation (first 200 chars): ' + text[:200])
            
            result = {'type': None, 'operationName': None, 'variables': [], 'fieldsSelected': [], 'aliases': {}}
            
            # Pattern for named operations: query OperationName($var: Type) { field ... }
            named_pattern = r'^\s*(query|mutation|subscription)\s+([A-Z][A-Za-z0-9_]*)\s*(\([^)]*\))?\s*\{\s*([a-zA-Z_][a-zA-Z0-9_]*)'
            match = re.search(named_pattern, text, re.IGNORECASE)
            
            if match:
                result['type'] = match.group(1).lower()
                result['operationName'] = match.group(2)
                
                # Extract variables from parameter list
                if match.group(3):
                    variables = re.findall(r'\$([a-zA-Z_][a-zA-Z0-9_]*)', match.group(3))
                    result['variables'] = ['$' + v for v in variables]
                
                # Extract top-level fields and aliases
                result['fieldsSelected'] = self._extract_fields(text)
                result['aliases'] = self._extract_aliases(text)
                
                log.info('[GraphQL Client]     ✓ Parsed as named ' + result['type'] + ': ' + result['operationName'])
                log.info('[GraphQL Client]       - Variables: ' + str(result['variables']))
                log.info('[GraphQL Client]       - Fields selected: ' + str(result['fieldsSelected']))
                log.info('[GraphQL Client]   - Aliases: ' + str(result['aliases']))
                
                return result
            
            # Pattern for anonymous operations: query($var: Type) { field ... }
            anon_pattern = r'^\s*(query|mutation|subscription)\s*(\([^)]*\))?\s*\{\s*([a-zA-Z_][a-zA-Z0-9_]*)'
            match = re.search(anon_pattern, text, re.IGNORECASE)
            
            if match:
                result['type'] = match.group(1).lower()
                
                # Extract variables from parameter list
                if match.group(2):
                    variables = re.findall(r'\$([a-zA-Z_][a-zA-Z0-9_]*)', match.group(2))
                    result['variables'] = ['$' + v for v in variables]
                
                # Extract top-level fields and aliases
                result['fieldsSelected'] = self._extract_fields(text)
                result['aliases'] = self._extract_aliases(text)
                
                log.info('[GraphQL Client] Parsed as anonymous ' + result['type'])
                log.info('[GraphQL Client]   - Variables: ' + str(result['variables']))
                log.info('[GraphQL Client]   - Fields: ' + str(result['fieldsSelected']))
                log.info('[GraphQL Client]   - Aliases: ' + str(result['aliases']))
                
                return result
            
            log.info('[GraphQL Client] Could not parse GraphQL operation')
            return None
            
        except Exception as e:
            log.info('[GraphQL Client] Error parsing operation: ' + str(e))
            log.info('[GraphQL Client] ' + traceback.format_exc())
            return None
    
    def _extract_fields(self, graphql_text):
        """
        Extract top-level fields (flat, no nesting).
        
        Handles:
        - Regular fields: users { id }
        - Aliased fields: mainUser: user { id }
        
        Returns only the real field names, not the aliases.
        Aliases are stored separately by _extract_aliases().
        """
        try:
            # Find the first { ... } block (operation body)
            match = re.search(r'\{([^}]+)\}', graphql_text)
            if not match:
                log.info('[GraphQL Client] No fields block found')
                return []
            
            content = match.group(1)
            log.info('[GraphQL Client] Fields block content: ' + content[:100])
            
            # Extract aliases first to avoid duplicates
            alias_pattern = r'([a-zA-Z_][a-zA-Z0-9_]*)\s*:\s*([a-zA-Z_][a-zA-Z0-9_]*)'
            aliases = re.findall(alias_pattern, content)
            aliased_names = {alias for alias, field in aliases}
            
            # Extract field names (followed by { or ()
            field_pattern = r'\b([a-z][a-zA-Z0-9_]*)\s*[{\(]'
            fields = re.findall(field_pattern, content)
            
            # Build result: regular fields + real field names from aliases
            result = []
            for field in fields:
                if field not in aliased_names:  # Skip alias names, keep field names
                    result.append(field)
            
            # Add the real field names from aliases
            for alias, field in aliases:
                result.append(field)
            
            # Remove duplicates
            result = list(set(result))
            
            log.info('[GraphQL Client] Extracted fields: ' + str(result))
            log.info('[GraphQL Client] Excluded aliases: ' + str(aliased_names))
            
            return result
            
        except Exception as e:
            log.info('[GraphQL Client] Error extracting fields: ' + str(e))
            return []
    
    def _extract_aliases(self, graphql_text):
        """
        Extract field aliases.
        
        Example:
            mainUser: user(id: 1) { ... }
            
        Returns:
            {'mainUser': 'user'}
        """
        try:
            # Pattern: alias: field followed by ( or {
            alias_pattern = r'([a-zA-Z_][a-zA-Z0-9_]*)\s*:\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*[\(\{]'
            matches = re.findall(alias_pattern, graphql_text)
            
            aliases = {alias: field for alias, field in matches}
            
            if aliases:
                log.info('[GraphQL Client] Extracted aliases: ' + str(aliases))
            
            return aliases
            
        except Exception as e:
            log.info('[GraphQL Client] Error extracting aliases: ' + str(e))
            return {}

    def finish(self):
        """
        Called at the very end of the analysis.
        Clean up caches and temporary data.
        """
        log.info('[GraphQL Client] === FINISH: Cleaning up caches ===')
        log.info('[GraphQL Client] Processed ' + str(len(self.graphql_jscontent)) + ' files total')
        log.info('[GraphQL Client] Created ' + str(len(self.gql_definitions)) + ' gql definitions')
        log.info('[GraphQL Client] Definition keys: ' + str(list(self.gql_definitions.keys())))
        
        self.graphql_jscontent = []
        self.gql_definitions = {}
        
        log.info('[GraphQL Client] === FINISH: Cleanup complete ===')
