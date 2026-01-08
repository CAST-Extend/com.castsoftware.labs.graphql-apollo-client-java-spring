# -*- coding: utf-8 -*-
"""
GraphQL Client Analyzer - Links React/Apollo Client code to GraphQL schema

This extension listens to HTML5/JavaScript analyzer events to detect GraphQL
operations in React code (useQuery, useMutation) and creates links to the
GraphQL schema objects created by the main GraphQL extension.

Based on the approach from Isabelle Boillon (HTML5/JS extension expert).

Architecture:
- Event-driven: Listens to HTML5/JS analyzer broadcasts
- AST traversal: Walks JavaScript AST to find Apollo Client hooks
- GraphQL parsing: Extracts operation metadata from GraphQL text
- Object creation: Creates custom client objects as children of JS functions
- Linking: Links client objects to existing GraphQL schema objects
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
    Extension that links React GraphQL operations to schema objects.
    
    Workflow (based on Isabelle's approach):
    1. In start_javascript_content: Collect files with useQuery/useMutation imports
    2. In end_javascript_contents: Walk AST to find calls, create objects and links
    """
    
    def __init__(self):
        """Initialize the analyzer."""
        self.graphql_jscontent = []  # JS content files with GraphQL imports
    
    @Event('com.castsoftware.html5', 'start_javascript_content')
    def on_start_javascript_content(self, jsContent):
        """
        Event handler for each JavaScript/JSX file.
        Collect files that have useQuery or useMutation imports.
        
        Args:
            jsContent: JavaScript AST object from HTML5/JS analyzer
        """
        try:
            log.debug('[GraphQL Client] start_javascript_content: ' + 
                     str(jsContent.get_file().get_path()))
            
            # Check if this file imports useQuery or useMutation
            for _import in jsContent.get_imports():
                import_name = _import.get_what_name()
                if import_name in ['useQuery', 'useMutation']:
                    self.graphql_jscontent.append(jsContent)
                    log.debug('[GraphQL Client] File has GraphQL imports: ' + 
                             str(jsContent.get_file().get_path()))
                    break
                    
        except Exception as e:
            log.warning('[GraphQL Client] Error in start_javascript_content: ' + str(e))
            log.debug('[GraphQL Client] ' + traceback.format_exc())
    
    @Event('com.castsoftware.html5', 'end_javascript_contents')
    def on_end_javascript_contents(self):
        """
        Event handler called after all JavaScript files are processed.
        Walk AST to find GraphQL calls and create objects/links.
        """
        try:
            log.info('[GraphQL Client] end_javascript_contents - Processing ' + 
                    str(len(self.graphql_jscontent)) + ' files with GraphQL imports')
            
            for jscontent in self.graphql_jscontent:
                self._process_graphql_content(jscontent)
            
            log.info('[GraphQL Client] GraphQL client analysis complete')
            
        except Exception as e:
            log.warning('[GraphQL Client] Error in end_javascript_contents: ' + str(e))
            log.debug('[GraphQL Client] ' + traceback.format_exc())
        finally:
            # Clean up for next analysis
            self.graphql_jscontent = []
    
    def _process_graphql_content(self, jscontent):
        """
        Process a JavaScript content file for GraphQL operations.
        
        Args:
            jscontent: JavaScript AST object
        """
        try:
            # Find all useQuery/useMutation calls in the AST
            graphql_calls = self._get_graphql_calls(jscontent)
            log.info('[GraphQL Client] graphql_calls=' + str(graphql_calls))
            
            for graphql_call in graphql_calls:
                self._process_graphql_call(graphql_call, jscontent)
                
        except Exception as e:
            log.warning('[GraphQL Client] Error processing content: ' + str(e))
            log.debug('[GraphQL Client] ' + traceback.format_exc())
    
    def _get_graphql_calls(self, ast):
        """
        Recursively find all useQuery/useMutation calls in AST.
        
        Args:
            ast: AST node
            
        Returns:
            list: List of function call AST nodes
        """
        if not ast:
            return []
        
        if is_function_call_part(ast) and ast.get_name() in ['useQuery', 'useMutation']:
            return [ast]
        
        results = []
        try:
            for child in ast.get_children():
                results.extend(self._get_graphql_calls(child))
        except:
            pass
        
        return results
    
    def _process_graphql_call(self, graphql_call, jscontent):
        """
        Process a single useQuery/useMutation call.
        
        Args:
            graphql_call: Function call AST node
            jscontent: JavaScript AST object for file context
        """
        try:
            # Get the hook type (useQuery or useMutation)
            hook_type = graphql_call.get_name()
            
            # Get the parent function (first KB parent)
            parent_ast = graphql_call.get_first_kb_parent()
            if not parent_ast:
                log.debug('[GraphQL Client] No parent found for ' + hook_type)
                return
            
            log.info('[GraphQL Client] parent=' + str(parent_ast))
            
            # Get the KB object for the parent
            parent_kb_object = parent_ast.get_kb_object()
            if not parent_kb_object:
                log.debug('[GraphQL Client] Parent has no KB object')
                return
            
            log.info('[GraphQL Client] parent kb object=' + str(parent_kb_object))
            
            # Get the parameters
            params = graphql_call.get_parameters()
            if not params:
                log.debug('[GraphQL Client] No parameters for ' + hook_type)
                return
            
            param = params[0]
            log.info('[GraphQL Client] param=' + str(param))
            
            # Evaluate the parameter to get the GraphQL text
            graphql_text = self._evaluate_graphql_param(param)
            if not graphql_text:
                log.debug('[GraphQL Client] Could not evaluate GraphQL text')
                return
            
            log.info('[GraphQL Client] graphql_text=' + graphql_text[:100] + '...')
            
            # Parse the GraphQL operation
            operation_info = self._parse_graphql_operation(graphql_text)
            if not operation_info:
                log.debug('[GraphQL Client] Could not parse GraphQL operation')
                return
            
            # Create the client object
            self._create_client_object(
                hook_type=hook_type,
                operation_info=operation_info,
                parent_kb_object=parent_kb_object,
                graphql_call=graphql_call,
                jscontent=jscontent
            )
            
        except Exception as e:
            log.warning('[GraphQL Client] Error processing GraphQL call: ' + str(e))
            log.debug('[GraphQL Client] ' + traceback.format_exc())
    
    def _evaluate_graphql_param(self, param):
        """
        Evaluate the GraphQL parameter to get the query/mutation text.
        
        The parameter is typically a variable that references a gql`...` template literal.
        We need to evaluate it to get the actual GraphQL text.
        
        Args:
            param: Parameter AST node
            
        Returns:
            str: GraphQL text or None
        """
        try:
            # Try to evaluate the parameter
            evs = param.evaluate_ast()
            if not evs:
                return None
            
            for ev in evs:
                log.debug('[GraphQL Client] evaluation=' + str(ev))
                
                # gql`...` is parsed as a function call with the string as parameter
                # Like: gql('query GetUsers { ... }')
                if ev and is_function_call(ev) and ev.get_name() == 'gql':
                    try:
                        # Get the first function call part
                        fcall_parts = ev.get_function_call_parts()
                        if fcall_parts and len(fcall_parts) > 0:
                            # Get the string parameter
                            string_param = fcall_parts[0].get_parameters()[0]
                            # Evaluate the string
                            evs2 = string_param.evaluate()
                            if evs2:
                                for ev2 in evs2:
                                    text = str(ev2).strip('`').strip()
                                    log.info('[GraphQL Client] final evaluation=' + text)
                                    return text
                    except Exception as e:
                        log.debug('[GraphQL Client] Error evaluating gql: ' + str(e))
            
            return None
            
        except Exception as e:
            log.debug('[GraphQL Client] Error evaluating param: ' + str(e))
            return None
    
    def _parse_graphql_operation(self, graphql_text):
        """
        Parse GraphQL operation text to extract metadata.
        
        Extracts:
        - operation_type: 'query' or 'mutation'
        - operation_name: Named operation (e.g., 'GetUsers') or None
        - field_name: The root field being queried (e.g., 'users')
        
        Args:
            graphql_text (str): GraphQL query/mutation text
            
        Returns:
            dict: {operation_type, operation_name, field_name} or None
        """
        try:
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
    
    def _create_client_object(self, hook_type, operation_info, parent_kb_object, graphql_call, jscontent):
        """
        Create a CAST custom object for a GraphQL client operation.
        
        Creates objects like:
        - GraphQLClientQuery for useQuery calls
        - GraphQLClientMutation for useMutation calls
        
        And creates a CALL link from the parent JS function to this object.
        
        Args:
            hook_type (str): 'useQuery' or 'useMutation'
            operation_info (dict): Parsed operation metadata
            parent_kb_object: KB object of the parent function
            graphql_call: AST node of the useQuery/useMutation call
            jscontent: JavaScript AST object for file context
        """
        try:
            # Determine object type
            if hook_type == 'useQuery':
                object_type = 'GraphQLClientQuery'
            elif hook_type == 'useMutation':
                object_type = 'GraphQLClientMutation'
            else:
                log.warning('[GraphQL Client] Unknown hook type: ' + hook_type)
                return
            
            # Build name: "query:fieldName" or "mutation:fieldName"
            operation_name = operation_info['operation_type'] + ':' + operation_info['field_name']
            
            # Build fullname using parent's fullname
            parent_fullname = parent_kb_object.get_fullname() if hasattr(parent_kb_object, 'get_fullname') else str(parent_kb_object)
            fullname = parent_fullname + '/' + operation_name
            
            log.info('[GraphQL Client] Creating ' + object_type + ': ' + operation_name)
            log.info('[GraphQL Client] Fullname: ' + fullname)
            
            # Create custom object with parent function as parent
            client_obj = CustomObject()
            client_obj.set_type(object_type)
            client_obj.set_parent(parent_kb_object)
            client_obj.set_fullname(fullname)
            client_obj.set_name(operation_name)
            
            # Save object
            client_obj.save()
            log.info('[GraphQL Client] Object saved successfully')
            
            # Create bookmark for source navigation
            bookmark = None
            try:
                file = jscontent.get_file()
                bookmark = graphql_call.create_bookmark(file)
                client_obj.save_position(bookmark)
                log.debug('[GraphQL Client] Bookmark saved')
            except Exception as e:
                log.debug('[GraphQL Client] Could not create bookmark: ' + str(e))
            
            # Create CALL link from parent function to this client object
            try:
                if bookmark:
                    create_link('callLink', parent_kb_object, client_obj, bookmark)
                else:
                    create_link('callLink', parent_kb_object, client_obj)
                log.info('[GraphQL Client] Created CALL link from function to ' + operation_name)
            except Exception as e:
                log.warning('[GraphQL Client] Could not create CALL link: ' + str(e))
            
            log.info('[GraphQL Client] SUCCESS: Created ' + object_type + ': ' + operation_name)
            
        except Exception as e:
            log.warning('[GraphQL Client] Error creating client object: ' + str(e))
            log.debug('[GraphQL Client] ' + traceback.format_exc())
