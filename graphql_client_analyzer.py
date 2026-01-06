# -*- coding: utf-8 -*-
"""
GraphQL Client Analyzer - Links React/Apollo Client code to GraphQL schema

This extension listens to HTML5/JavaScript analyzer events to detect GraphQL
operations in React code (useQuery, useMutation) and creates links to the
GraphQL schema objects created by the main GraphQL extension.

Architecture:
- Event-driven: Listens to HTML5/JS analyzer broadcasts
- AST traversal: Walks JavaScript AST to find Apollo Client hooks
- Variable resolution: Traces query variables to gql template literals
- GraphQL parsing: Extracts operation metadata from GraphQL text
- Object creation: Creates custom client objects as children of JS functions
- Linking: Links client objects to existing GraphQL schema objects
"""

import re
import traceback
from cast.analysers import ua, log, CustomObject, Bookmark, create_link
from cast import Event


class GraphQLClientAnalyzer(ua.Extension):
    """
    Extension that links React GraphQL operations to schema objects.
    
    Workflow:
    1. Receives JavaScript AST for each file via 'start_javascript_content' event
    2. Collects GraphQL operations (useQuery/useMutation calls) during parsing
    3. After all files processed ('end_javascript_contents'), creates objects and links
    """
    
    def __init__(self):
        """Initialize the analyzer."""
        self.graphql_operations = []  # List of detected GraphQL operations
        self.gql_definitions = {}  # Map of variable names to GraphQL text
        self.operation_counter = {}  # Counter for unique object naming
    
    @Event('com.castsoftware.html5', 'start_javascript_content')
    def on_js_file(self, jsContent):
        """
        Event handler for each JavaScript/JSX file processed.
        
        Args:
            jsContent: JavaScript AST object from HTML5/JS analyzer
        """
        try:
            log.debug('[GraphQL Client] Processing file: ' + str(jsContent.get_file().get_path()))
            
            # First pass: Find all gql template literal definitions
            self._collect_gql_definitions(jsContent)
            
            # Second pass: Find useQuery/useMutation calls
            self._find_graphql_operations(jsContent)
            
        except Exception as e:
            log.warning('[GraphQL Client] Error processing file: ' + str(e))
            log.debug('[GraphQL Client] ' + traceback.format_exc())
    
    @Event('com.castsoftware.html5', 'end_javascript_contents')
    def on_all_files_done(self):
        """
        Event handler called after all JavaScript files are processed.
        
        Creates CAST objects for detected GraphQL operations and links them
        to existing GraphQL schema objects.
        """
        try:
            log.info('[GraphQL Client] Creating objects for ' + 
                    str(len(self.graphql_operations)) + ' GraphQL operations')
            
            for operation in self.graphql_operations:
                self._create_client_object(operation)
            
            log.info('[GraphQL Client] GraphQL client analysis complete')
            
        except Exception as e:
            log.warning('[GraphQL Client] Error in end_javascript_contents: ' + str(e))
            log.debug('[GraphQL Client] ' + traceback.format_exc())
        finally:
            # Clean up for next analysis
            self.graphql_operations = []
            self.gql_definitions = {}
            self.operation_counter = {}
    
    # =========================================================================
    # PHASE 1: COLLECT GQL DEFINITIONS
    # =========================================================================
    
    def _collect_gql_definitions(self, jsContent):
        """
        Find all gql template literal definitions in the file.
        
        Looks for patterns like:
            const GET_USERS = gql`query GetUsers { users { id } }`
            const CREATE_USER = gql`mutation CreateUser($input: ...) { ... }`
        
        Args:
            jsContent: JavaScript AST object
        """
        try:
            for statement in jsContent.get_statements():
                self._find_gql_definitions_recursive(statement, jsContent)
        except Exception as e:
            log.debug('[GraphQL Client] Error collecting gql definitions: ' + str(e))
    
    def _find_gql_definitions_recursive(self, statement, jsContent):
        """
        Recursively walk AST to find gql template literal assignments.
        
        Args:
            statement: AST node
            jsContent: JavaScript AST object for file context
        """
        if not statement:
            return
        
        try:
            # Check if this is an assignment
            if self._is_assignment(statement):
                left_operand = statement.get_left_operand()
                right_operand = statement.get_right_operand()
                
                # Check if right side is a gql function call
                if right_operand and self._is_function_call(right_operand):
                    fcall_parts = right_operand.get_function_call_parts()
                    if fcall_parts and len(fcall_parts) > 0:
                        first_part = fcall_parts[0]
                        if first_part.get_name() == 'gql':
                            # Found gql`...` template literal
                            variable_name = self._get_identifier_name(left_operand)
                            if variable_name:
                                # Extract GraphQL text from template literal
                                graphql_text = self._extract_template_literal_text(right_operand)
                                if graphql_text:
                                    self.gql_definitions[variable_name] = graphql_text
                                    log.debug('[GraphQL Client] Found gql definition: ' + 
                                            variable_name + ' = ' + graphql_text[:50] + '...')
            
            # Recurse into children
            if hasattr(statement, 'get_children'):
                for child in statement.get_children():
                    self._find_gql_definitions_recursive(child, jsContent)
                    
        except Exception as e:
            log.debug('[GraphQL Client] Error in recursive gql search: ' + str(e))
    
    def _extract_template_literal_text(self, function_call):
        """
        Extract the text content from a gql template literal.
        
        The gql function call contains parameters which include the template
        literal parts. We need to reconstruct the full GraphQL query text.
        
        Args:
            function_call: FunctionCall AST node for gql`...`
            
        Returns:
            str: GraphQL query/mutation text, or None if not found
        """
        try:
            # Get the function call parts
            fcall_parts = function_call.get_function_call_parts()
            if not fcall_parts or len(fcall_parts) == 0:
                return None
            
            # The first part should be 'gql', parameters contain the template literal
            first_part = fcall_parts[0]
            params = first_part.get_parameters()
            
            if params and len(params) > 0:
                # Template literal is in the first parameter
                param = params[0]
                # Try to get the text content
                if hasattr(param, 'get_text'):
                    text = param.get_text()
                    if text:
                        # Clean up the text (remove backticks, normalize whitespace)
                        text = text.strip('`').strip()
                        return text
                
                # Alternative: Try to evaluate the parameter
                if hasattr(param, 'evaluate'):
                    evaluated = param.evaluate()
                    if evaluated and len(evaluated) > 0:
                        return str(evaluated[0]).strip('`').strip()
            
            return None
            
        except Exception as e:
            log.debug('[GraphQL Client] Error extracting template literal: ' + str(e))
            return None
    
    # =========================================================================
    # PHASE 2: FIND GRAPHQL OPERATIONS
    # =========================================================================
    
    def _find_graphql_operations(self, jsContent):
        """
        Find useQuery and useMutation calls in the JavaScript AST.
        
        Args:
            jsContent: JavaScript AST object
        """
        try:
            for statement in jsContent.get_statements():
                self._find_operations_recursive(statement, jsContent)
        except Exception as e:
            log.debug('[GraphQL Client] Error finding operations: ' + str(e))
    
    def _find_operations_recursive(self, statement, jsContent):
        """
        Recursively walk AST to find useQuery/useMutation calls.
        
        Args:
            statement: AST node
            jsContent: JavaScript AST object for file context
        """
        if not statement:
            return
        
        try:
            # Check if this is a function call
            if self._is_function_call(statement):
                fcall_parts = statement.get_function_call_parts()
                if fcall_parts and len(fcall_parts) > 0:
                    first_part = fcall_parts[0]
                    function_name = first_part.get_name()
                    
                    # Check if it's useQuery or useMutation
                    if function_name in ['useQuery', 'useMutation']:
                        # Extract the GraphQL variable being passed
                        params = first_part.get_parameters()
                        if params and len(params) > 0:
                            query_param = params[0]
                            variable_name = self._get_identifier_name(query_param)
                            
                            if variable_name:
                                # Look up the gql definition
                                graphql_text = self.gql_definitions.get(variable_name)
                                
                                if graphql_text:
                                    # Extract operation metadata
                                    operation_info = self._parse_graphql_operation(graphql_text)
                                    
                                    if operation_info:
                                        # Find the parent JavaScript function
                                        parent_function = self._get_parent_function(statement)
                                        
                                        # Store operation for later object creation
                                        operation = {
                                            'hook_type': function_name,  # useQuery or useMutation
                                            'variable_name': variable_name,
                                            'graphql_text': graphql_text,
                                            'operation_type': operation_info['operation_type'],  # query/mutation
                                            'operation_name': operation_info['operation_name'],  # GetUsers
                                            'field_name': operation_info['field_name'],  # users
                                            'parent_function': parent_function,
                                            'ast_node': statement,
                                            'file': jsContent.get_file()
                                        }
                                        
                                        self.graphql_operations.append(operation)
                                        log.debug('[GraphQL Client] Found ' + function_name + 
                                                '(' + variable_name + ') calling ' + 
                                                operation_info['field_name'])
                                else:
                                    log.debug('[GraphQL Client] GraphQL text not found for variable: ' + 
                                            variable_name)
            
            # Recurse into children
            if hasattr(statement, 'get_children'):
                for child in statement.get_children():
                    self._find_operations_recursive(child, jsContent)
                    
        except Exception as e:
            log.debug('[GraphQL Client] Error in recursive operation search: ' + str(e))
    
    def _parse_graphql_operation(self, graphql_text):
        """
        Parse GraphQL operation text to extract metadata.
        
        Extracts:
        - operation_type: 'query' or 'mutation'
        - operation_name: Named operation (e.g., 'GetUsers') or None
        - field_name: The root field being queried (e.g., 'users')
        
        Examples:
            query GetUsers { users { id } }
            -> type='query', name='GetUsers', field='users'
            
            mutation CreateUser($input: CreateUserInput!) { createUser(input: $input) { id } }
            -> type='mutation', name='CreateUser', field='createUser'
        
        Args:
            graphql_text (str): GraphQL query/mutation text
            
        Returns:
            dict: {operation_type, operation_name, field_name} or None
        """
        try:
            # Clean up text
            text = graphql_text.strip()
            
            # Pattern for named operations: query OperationName { field ...
            named_pattern = r'^\s*(query|mutation)\s+([A-Z][A-Za-z0-9_]*)\s*(?:\([^)]*\))?\s*\{\s*([a-z][A-Za-z0-9_]*)'
            match = re.search(named_pattern, text, re.IGNORECASE)
            
            if match:
                return {
                    'operation_type': match.group(1).lower(),
                    'operation_name': match.group(2),
                    'field_name': match.group(3)
                }
            
            # Pattern for anonymous queries: query { field ...
            anonymous_pattern = r'^\s*(query|mutation)\s*(?:\([^)]*\))?\s*\{\s*([a-z][A-Za-z0-9_]*)'
            match = re.search(anonymous_pattern, text, re.IGNORECASE)
            
            if match:
                return {
                    'operation_type': match.group(1).lower(),
                    'operation_name': None,
                    'field_name': match.group(2)
                }
            
            # Pattern for implicit query (no 'query' keyword): { field ...
            implicit_pattern = r'^\s*\{\s*([a-z][A-Za-z0-9_]*)'
            match = re.search(implicit_pattern, text)
            
            if match:
                return {
                    'operation_type': 'query',
                    'operation_name': None,
                    'field_name': match.group(1)
                }
            
            log.debug('[GraphQL Client] Could not parse GraphQL operation: ' + text[:50])
            return None
            
        except Exception as e:
            log.debug('[GraphQL Client] Error parsing GraphQL operation: ' + str(e))
            return None
    
    # =========================================================================
    # PHASE 3: CREATE OBJECTS AND LINKS
    # =========================================================================
    
    def _create_client_object(self, operation):
        """
        Create a CAST custom object for a GraphQL client operation.
        
        Creates objects like:
        - GraphQLClientQuery for useQuery calls
        - GraphQLClientMutation for useMutation calls
        
        Then creates USE links to the corresponding GraphQL schema objects.
        
        Args:
            operation (dict): Operation metadata from _find_operations_recursive
        """
        try:
            # Determine object type
            if operation['hook_type'] == 'useQuery':
                object_type = 'GraphQLClientQuery'
            elif operation['hook_type'] == 'useMutation':
                object_type = 'GraphQLClientMutation'
            else:
                log.warning('[GraphQL Client] Unknown hook type: ' + operation['hook_type'])
                return
            
            # Get parent function object from CAST
            parent_function = operation['parent_function']
            if not parent_function:
                log.debug('[GraphQL Client] No parent function found, using file as parent')
                return
            
            parent_kb_object = parent_function.get_kb_object()
            if not parent_kb_object:
                log.debug('[GraphQL Client] Parent has no KB object')
                return
            
            # Build unique name for this client operation
            # Format: "query:fieldName" or "mutation:fieldName"
            operation_name = operation['operation_type'] + ':' + operation['field_name']
            
            # Build fullname (add counter if duplicate)
            parent_fullname = parent_function.get_kb_symbol().get_kb_fullname()
            base_fullname = parent_fullname + '/' + operation_name
            
            # Handle duplicates by adding counter
            if base_fullname not in self.operation_counter:
                self.operation_counter[base_fullname] = 0
                fullname = base_fullname
            else:
                self.operation_counter[base_fullname] += 1
                fullname = base_fullname + '_' + str(self.operation_counter[base_fullname])
            
            # Create custom object
            client_obj = CustomObject()
            client_obj.set_type(object_type)
            client_obj.set_parent(parent_kb_object)
            client_obj.set_fullname(fullname)
            client_obj.set_name(operation_name)
            
            # Save object first before adding properties
            client_obj.save()
            
            # Store metadata for application-level linking
            # These properties will be used in end_application to create links
            client_obj.save_property('GraphQL.operationType', operation['operation_type'])
            client_obj.save_property('GraphQL.fieldName', operation['field_name'])
            
            # Create bookmark
            try:
                file = operation['file']
                ast_node = operation['ast_node']
                bookmark = ast_node.create_bookmark(file)
                client_obj.save_position(bookmark)
            except Exception as e:
                log.debug('[GraphQL Client] Could not create bookmark: ' + str(e))
            
            # Note: Links to schema objects will be created in end_application
            # after all objects from all technologies have been created
            
            log.info('[GraphQL Client] Created ' + object_type + ': ' + operation_name)
            
        except Exception as e:
            log.warning('[GraphQL Client] Error creating client object: ' + str(e))
            log.debug('[GraphQL Client] ' + traceback.format_exc())
    
    # =========================================================================
    # AST HELPER METHODS
    # =========================================================================
    
    def _is_assignment(self, token):
        """Check if AST node is an assignment."""
        try:
            return token.is_assignment()
        except:
            return False
    
    def _is_function_call(self, token):
        """Check if AST node is a function call."""
        try:
            return token.is_function_call()
        except:
            return False
    
    def _is_identifier(self, token):
        """Check if AST node is an identifier."""
        try:
            return token.is_identifier()
        except:
            return False
    
    def _get_identifier_name(self, token):
        """Extract identifier name from AST node."""
        try:
            if self._is_identifier(token):
                return token.get_name()
            return None
        except:
            return None
    
    def _get_parent_function(self, statement):
        """
        Find the parent JavaScript function containing this statement.
        
        Args:
            statement: AST node
            
        Returns:
            Function AST node or None
        """
        try:
            return statement.get_first_kb_parent()
        except:
            return None
