"""
Apollo Client TypeScript Interpreter
Based on vue_basic_interpreter_ts.py structure, adapted for Apollo Client hooks and GraphQL operations.
"""
try:
    import os
    import re
    import traceback
    from collections import OrderedDict
    from cast.analysers import log
    
    # Import from typescript_dependencies
    from typescript_dependencies.typescript_walker import is_ts_node_type, get_descendants, is_ts_symbol_type, Walker
    from typescript_dependencies.symbols import SourceFile
    from typescript_dependencies.evaluation import EvaluationTool
    
    # Local imports
    from ts_parser.analysis_results import ApolloAnalysisResults, RawBookmark, GqlDefinition
    from ts_parser.apollo_symbols import ApolloHookObject, ApolloClientMethodObject, ApolloHookSymbol, GqlDefinitionSymbol
    from tests.tools import get_descendants as get_descendants_tool
except:
    from cast.analysers import log
    import traceback
    print('Problem in imports: ' + str(traceback.format_exc()))


# List of Apollo Client hooks to detect
APOLLO_HOOKS = ['useQuery', 'useMutation', 'useSubscription', 'useLazyQuery']

# List of Apollo Client methods (for future support)
APOLLO_CLIENT_METHODS = ['query', 'mutate', 'subscribe']


def analyse_ts_fragment(ts_fragment, apollo_analysis_results):
    """
    Main entry point for analyzing a TypeScript fragment for Apollo Client usage.
    Similar to analyse_ts_fragment in vue_basic_interpreter_ts.py
    
    Args:
        ts_fragment: TypeScript SourceFile to analyze
        apollo_analysis_results: ApolloAnalysisResults instance to store results
        
    Returns:
        ApolloBasicInterpreterTS instance or None on error
    """
    print('*** analyse_ts_fragment() called for: {} ***'.format(ts_fragment.get_fullname()))
    try:
        interpreter = ApolloBasicInterpreterTS(ts_fragment, apollo_analysis_results)
        apollo_analysis_results.ts_files.append(ts_fragment)
        print('Created interpreter and appended to ts_files')
        
        # Create walker and register interpreter
        walker = Walker()
        walker.register_interpreter(interpreter)
        
        # Get AST fragments
        fragments = ts_fragment._ast_fragments
        if not fragments:
            fragments = [ts_fragment.get_ast()]
        
        # Walk through all fragments
        for frag in fragments:
            walker.walk(frag.get_children())
        
        # Post-processing after walking the AST
        interpreter.on_end()
        print('Completed interpreter.on_end()')
        
        return interpreter
    except:
        print("Problem during analysis of ts_fragment for Apollo Client")
        print(traceback.format_exc())
        return None


class BaseFrameworkInterpreter:
    """
    Base interpreter class for framework-specific analysis.
    Similar to BaseFrameworkInterpreter in vue_basic_interpreter_ts.py
    """

    def __init__(self, module):
        self.__module = module
        self.__symbol_stack = [module]

    def push_symbol(self, symbol):
        return self.__symbol_stack.append(symbol)

    def pop_symbol(self):
        self.__symbol_stack.pop()

    def get_program(self):
        return self.get_current_module().get_program()

    def get_current_callable(self):
        symbol = self.__symbol_stack[-1]
        while is_ts_node_type(symbol, 'Class'):
            symbol_initializer = symbol.get_initializer()
            if symbol_initializer:
                return symbol_initializer
            else:
                symbol = symbol.get_parent_symbol()
        return symbol

    def get_current_module(self):
        return self.__module

    def _get_current_symbol(self):
        return self.__symbol_stack[-1]

    def get_current_class(self):
        """
        @rtype : symbols.Class | None
        """
        symbol = self._get_current_symbol()
        while symbol and not is_ts_symbol_type(symbol, 'Class'):
            symbol = symbol.get_parent_symbol()
        return symbol

    def get_current_method(self):
        """
        @rtype : symbols.Method | None
        """
        symbol = self._get_current_symbol()
        while symbol and not is_ts_node_type(symbol, 'Method'):
            symbol = symbol.get_parent_symbol()
        return symbol

    def get_current_function(self):
        """
        @rtype : symbols.Function | None
        """
        symbol = self._get_current_symbol()
        while symbol and not is_ts_symbol_type(symbol, 'Function'):
            symbol = symbol.get_parent_symbol()
        return symbol

    def start_Class(self, _ast_class):
        """
        @type _ast_class: typescript_parser.parser.Class
        """
        _class = self._get_current_symbol().get_class(_ast_class.get_name(), _ast_class.get_begin_line())
        if not _class:
            print("No class found for %s under %s" % (str(_ast_class.get_name()), str(self._get_current_symbol().get_fullname())))
        self.push_symbol(_class)

    def end_Class(self, _ast_class):
        self.pop_symbol()

    def start_Namespace(self, _ast):
        """
        @type _ast: typescript_parser.parser.Namespace
        """
        namespace = self._get_current_symbol().get_namespace(_ast.get_name())
        if not namespace:
            print("No namespace found for %s under %s" % (str(_ast.get_name()), str(self._get_current_symbol().get_fullname())))
        self.push_symbol(namespace)

    def end_Namespace(self, _ast_namespace):
        self.pop_symbol()

    def start_Interface(self, _ast):
        """
        @type _ast: typescript_parser.parser.Interface
        """
        interface = self._get_current_symbol().get_interface(_ast.get_name())
        if not interface:
            print("No interface found for %s under %s" % (str(_ast.get_name()), str(self._get_current_symbol().get_fullname())))
        self.push_symbol(interface)

    def end_Interface(self, _ast):
        self.pop_symbol()

    def start_ArrowExpression(self, _ast_function):
        if _ast_function.is_arrow_function:
            self.start_Function(_ast_function)
        elif _ast_function.is_arrow_method:
            self.start_Method(_ast_function)

    def end_ArrowExpression(self, _ast_function):
        if _ast_function.is_arrow_function:
            self.end_Function(_ast_function)
        elif _ast_function.is_arrow_method:
            self.end_Method(_ast_function)

    def start_Function(self, _ast_function):
        """
        @type _ast_function: typescript_parser.parser.Function
        """
        name = _ast_function.get_name()
        function = self._get_current_symbol().get_function(name, _ast_function.get_begin_line())
        if not function:
            print("No function found for %s under %s" % (str(name), str(self._get_current_symbol().get_fullname())))
        self.push_symbol(function)

    def end_Function(self, _ast_function):
        self.pop_symbol()

    def start_Method(self, _ast_method):
        """
        @type _ast_method: typescript_parser.parser.Method
        """
        name = _ast_method.get_name()
        method = self._get_current_symbol().get_method(name, _ast_method.get_begin_line())
        if not method:
            print("No method found for %s under %s" % (str(name), str(self._get_current_symbol().get_fullname())))
        self.push_symbol(method)

    def end_Method(self, _ast_method):
        self.pop_symbol()


class ApolloBasicInterpreterTS(BaseFrameworkInterpreter):
    """
    TypeScript interpreter for Apollo Client hooks and GraphQL operations.
    Walks the AST and extracts Apollo-specific patterns.
    """

    def __init__(self, module, apollo_analysis_results):
        """
        Args:
            module: TypeScript SourceFile
            apollo_analysis_results: ApolloAnalysisResults instance
        """
        BaseFrameworkInterpreter.__init__(self, module)
        self.module = module
        self.apollo_analysis_results = apollo_analysis_results
        
        # Use evaluation tool if available
        if apollo_analysis_results.ts_evaluation_tool:
            self.ts_evaluate = apollo_analysis_results.ts_evaluation_tool.evaluate
        else:
            self.ts_evaluate = None

    def on_end(self):
        """
        Called after walking the AST. Perform final processing.
        """
        print('SourceFile: {}'.format(self.module.get_fullname()))

        # Extract all GQL definitions first
        print('Starting extract_all_gql_definitions...')
        self.extract_all_gql_definitions()
        print('Finished extract_all_gql_definitions. Found {} definitions'.format(
            len(self.apollo_analysis_results.gql_definitions_by_name)))

        # Then extract all Apollo hooks
        print('Starting extract_all_apollo_hooks...')
        self.extract_all_apollo_hooks()
        print('Finished extract_all_apollo_hooks. Found {} hooks'.format(
            len(self.apollo_analysis_results.apollo_hooks_by_operation)))

        # Create links between hooks and GQL definitions
        print('Starting create_hook_to_gql_links...')
        self.create_hook_to_gql_links()
        print('=== ApolloBasicInterpreterTS.on_end() finished ===')

    def find_parent_symbol_for_ast_node(self, ast_node):
        """
        Find the parent symbol (Function, Method, Class) that contains this AST node.
        Returns the parent symbol or the module if no parent found.
        """
        if not ast_node:
            return self.module

        line_number = ast_node.get_begin_line() if hasattr(ast_node, 'get_begin_line') else -1

        # Get all symbols from the module
        all_symbols = self.module.get_all_symbols()

        # Find the most specific (smallest range) symbol that contains this line
        best_match = self.module
        best_range = float('inf')

        for symbol in all_symbols:
            # Check if this symbol is a Function, Method, or Class
            symbol_type = type(symbol).__name__
            if symbol_type not in ['Function', 'Method', 'Class']:
                continue

            # Get the symbol's AST node
            symbol_ast = symbol.get_ast() if hasattr(symbol, 'get_ast') else None
            if not symbol_ast:
                continue

            # Handle both single AST and list of ASTs
            if isinstance(symbol_ast, list):
                symbol_ast = symbol_ast[0] if symbol_ast else None

            if not symbol_ast:
                continue

            # Get the symbol's line range
            if hasattr(symbol_ast, 'get_begin_line') and hasattr(symbol_ast, 'get_end_line'):
                start_line = symbol_ast.get_begin_line()
                end_line = symbol_ast.get_end_line()

                # Check if our node is inside this symbol
                if start_line <= line_number <= end_line:
                    range_size = end_line - start_line
                    # Keep the smallest range (most specific parent)
                    if range_size < best_range:
                        best_range = range_size
                        best_match = symbol
                        print('    Found potential parent: {} (line {}-{})'.format(
                            symbol.get_fullname(), start_line, end_line))

        return best_match

    def extract_all_gql_definitions(self):
        """
        Extract all GraphQL definitions (const GET_USERS = gql`...`)
        """
        try:
            ast = self.module.get_ast()
            print('  extract_all_gql_definitions: searching for gql definitions...')
            if not ast:
                print('  No AST found for module')
                return
            
            # Find all variable declarations
            var_declarations = get_descendants(ast, 'VariableDeclaration')
            print('  Found {} VariableDeclaration nodes'.format(len(var_declarations)))

            for var_decl in var_declarations:
                try:
                    var_name = var_decl.get_name()

                    # Skip inline gql in hooks (var_name = None)
                    # These will be handled by extract_all_apollo_hooks
                    if var_name is None:
                        print('    Skipping inline gql (var_name = None)')
                        continue
                    
                    # Look for gql`...` tagged template (ExpressionStatement with gql identifier)
                    expr_statements = get_descendants(var_decl, 'ExpressionStatement')
                    print('    Found {} ExpressionStatement nodes in variable'.format(len(expr_statements)))

                    for expr_stmt in expr_statements:
                        # Check if this ExpressionStatement contains 'gql' identifier and StringTemplate
                        has_gql = False
                        string_template = None
                        
                        for sub_node in expr_stmt.get_sub_nodes():
                            if hasattr(sub_node, 'get_name') and sub_node.get_name() == 'gql':
                                has_gql = True
                                print('    Found gql identifier in ExpressionStatement')
                            elif is_ts_node_type(sub_node, 'StringTemplate'):
                                string_template = sub_node
                                print('    Found StringTemplate in ExpressionStatement')

                        if has_gql and string_template:
                            # Found a gql definition
                            print('  ✓ Found gql`...` tagged template in variable: {}'.format(var_name))

                            if True:
                                graphql_metadata = self.parse_graphql_content(string_template)
                                print('    Parsed GraphQL metadata: {}'.format(graphql_metadata))

                                if graphql_metadata.get('operationName'):
                                    # Create GqlDefinition object
                                    raw_bookmark = RawBookmark(var_decl, self.module)

                                    gql_def = GqlDefinition(
                                        name=var_name,
                                        operation_name=graphql_metadata['operationName'],
                                        operation_type=graphql_metadata.get('operationType', 'query'),
                                        raw_query_text=graphql_metadata.get('rawQueryText', ''),
                                        variables=graphql_metadata.get('variables', ''),
                                        fields_selected=graphql_metadata.get('fieldsSelected', ''),
                                        ast_node=var_decl,
                                        raw_bookmark=raw_bookmark
                                    )

                                    # Add to analysis results
                                    self.apollo_analysis_results.add_gql_definition(gql_def)

                                    # ✨ CREATE AND ADD SYMBOL TO SOURCEFILE
                                    # Find the correct parent symbol (Function, Method, Class, or Module)
                                    parent_symbol = self.find_parent_symbol_for_ast_node(var_decl)
                                    
                                    gql_symbol = GqlDefinitionSymbol(
                                        name=var_name,
                                        parent=parent_symbol,
                                        operation_type=graphql_metadata.get('operationType', 'query')
                                    )
                                    gql_symbol.operation_name = graphql_metadata['operationName']
                                    gql_symbol.variables = graphql_metadata.get('variables', '')
                                    gql_symbol.fields_selected = graphql_metadata.get('fieldsSelected', '')
                                    gql_symbol.raw_query_text = graphql_metadata.get('rawQueryText', '')
                                    gql_symbol._ast = var_decl

                                    # Add symbol to BOTH:
                                    # 1. Parent symbol's table (for correct parent-child relationship)
                                    parent_symbol.add_symbol(var_name, gql_symbol)
                                    # 2. Module's table (for global visibility with get_all_symbols)
                                    if parent_symbol != self.module:
                                        self.module.add_symbol(var_name, gql_symbol)

                                    print('  ✓ Created GQL definition: {} -> {}'.format(
                                        var_name, graphql_metadata['operationName']))
                                    print('  ✓ Added GqlDefinitionSymbol to parent: {}'.format(parent_symbol.get_fullname()))
                                else:
                                    print('    No operationName found in GraphQL metadata')
                except Exception as inner_ex:
                    print('  Exception in var_decl loop: {}'.format(str(inner_ex)))
                    print(traceback.format_exc())
                    continue
                    
        except Exception as e:
            print('Error extracting GQL definitions: {}'.format(str(e)))
            print(traceback.format_exc())

    def parse_graphql_content(self, string_template):
        """
        Parse GraphQL content from a StringTemplate node.
        Returns a dictionary with operation metadata.
        """
        result = {
            'operationName': None,
            'operationType': 'query',  # default
            'variables': '',
            'fieldsSelected': '',
            'rawQueryText': ''
        }
        
        try:
            # Try to extract raw text from StringTemplate
            from typescript_dependencies.typescript_parser.light_parser import Token
            
            raw_text = ''
            
            # Method 1: Get tokens from string template
            if hasattr(string_template, 'get_sub_nodes'):
                for token in string_template.get_sub_nodes():
                    if isinstance(token, Token):
                        if hasattr(token, 'value'):
                            raw_text = token.value
                            break
            
            # Method 2: Convert to string
            if not raw_text:
                raw_text = str(string_template)
                # Clean the string representation
                if 'Token.Literal.String.Backtick' in raw_text:
                    match = re.search(r"'([^']*)'", raw_text)
                    if match:
                        raw_text = match.group(1)
            
            if not raw_text:
                return result
            
            # Clean text (remove backticks)
            raw_text = raw_text.strip('`').strip()
            
            # Convert literal \n to actual newlines
            if '\\n' in raw_text:
                raw_text = raw_text.replace('\\n', '\n')
            
            result['rawQueryText'] = raw_text
            
            # Extract operation type and name
            operation_pattern = r'^\s*(query|mutation|subscription)\s+([A-Z][A-Za-z0-9_]*)\s*(\([^)]*\))?\s*\{'
            match = re.search(operation_pattern, raw_text, re.MULTILINE | re.DOTALL)
            
            if match:
                result['operationType'] = match.group(1)
                result['operationName'] = match.group(2)
                
                # Extract variables
                if match.group(3):
                    params_text = match.group(3)
                    variables = re.findall(r'(\$[a-zA-Z_][a-zA-Z0-9_]*)', params_text)
                    if variables:
                        result['variables'] = ', '.join(variables)
            
            # Extract selected fields
            fields_pattern = r'\{\s*([a-z][a-zA-Z0-9_]*)\s*[\(\{]'
            fields = re.findall(fields_pattern, raw_text)
            
            keywords = ['query', 'mutation', 'subscription', 'fragment']
            unique_fields = []
            seen = set()
            
            for field in fields:
                if field not in keywords and field not in seen:
                    unique_fields.append(field)
                    seen.add(field)
            
            if unique_fields:
                result['fieldsSelected'] = ', '.join(unique_fields)
        
        except Exception as e:
            print('Error parsing GraphQL content: {}'.format(str(e)))
        
        return result

    def extract_all_apollo_hooks(self):
        """
        Extract all Apollo Client hooks (useQuery, useMutation, useSubscription, useLazyQuery)
        """
        try:
            ast = self.module.get_ast()
            print('  extract_all_apollo_hooks: searching for Apollo hooks...')
            if not ast:
                print('  No AST found for module')
                return
            
            # Find all function calls
            func_calls = get_descendants(ast, 'FunctionCall')
            print('  Found {} FunctionCall nodes total'.format(len(func_calls)))
            
            for func_call in func_calls:
                try:
                    hook_name = func_call.get_name()
                    
                    # Check if it's an Apollo hook
                    if hook_name not in APOLLO_HOOKS:
                        print('  Skipping non-Apollo hook: {}'.format(hook_name))
                        continue
                    
                    print('  Found Apollo hook call: {}'.format(hook_name))

                    # Extract operation name
                    operation_name = self.extract_operation_name(func_call)
                    
                    # Check for inline gql
                    is_inline = False
                    if not operation_name:
                        print('    No outline operation, checking for inline gql...')
                        inline_name, inline_metadata = self.extract_inline_gql(func_call)
                        print('    Extracted inline operation_name: {}'.format(inline_name))
                        if inline_name:
                            operation_name = inline_name
                            is_inline = True
                            
                            # Store inline GQL definition
                            raw_bookmark = RawBookmark(func_call, self.module)
                            gql_def = GqlDefinition(
                                name=inline_name,
                                operation_name=inline_metadata['operationName'],
                                operation_type=inline_metadata.get('operationType', 'query'),
                                raw_query_text=inline_metadata.get('rawQueryText', ''),
                                variables=inline_metadata.get('variables', ''),
                                fields_selected=inline_metadata.get('fieldsSelected', ''),
                                ast_node=func_call,
                                raw_bookmark=raw_bookmark
                            )
                            self.apollo_analysis_results.add_gql_definition(gql_def)

                            # ✨ CREATE AND ADD SYMBOL FOR INLINE GQL
                            # Find the correct parent symbol
                            parent_symbol = self.find_parent_symbol_for_ast_node(func_call)

                            inline_gql_symbol = GqlDefinitionSymbol(
                                name=inline_name + '_inline',
                                parent=parent_symbol,
                                operation_type=inline_metadata.get('operationType', 'query')
                            )
                            inline_gql_symbol.operation_name = inline_metadata['operationName']
                            inline_gql_symbol.variables = inline_metadata.get('variables', '')
                            inline_gql_symbol.fields_selected = inline_metadata.get('fieldsSelected', '')
                            inline_gql_symbol.raw_query_text = inline_metadata.get('rawQueryText', '')
                            inline_gql_symbol._ast = func_call

                            # Add symbol to BOTH parent and module
                            parent_symbol.add_symbol(inline_name + '_inline', inline_gql_symbol)
                            if parent_symbol != self.module:
                                self.module.add_symbol(inline_name + '_inline', inline_gql_symbol)

                            print('    ✓ Added inline GqlDefinitionSymbol to parent: {}'.format(parent_symbol.get_fullname()))

                    if not operation_name:
                        print('    Could not extract operation name from {} hook'.format(hook_name))
                        continue
                    
                    # Create ApolloHookObject
                    raw_bookmark = RawBookmark(func_call, self.module)
                    
                    hook_obj = ApolloHookObject(
                        hook_name=hook_name,
                        operation_name=operation_name,
                        ast_node=func_call,
                        raw_bookmark=raw_bookmark,
                        module=self.module
                    )
                    
                    # Mark as inline if applicable
                    if is_inline:
                        hook_obj.inline = operation_name
                    
                    # Add to analysis results
                    self.apollo_analysis_results.add_apollo_hook(hook_obj)
                    
                    # Register in module's node_symbols
                    self.module.add_node_symbol(operation_name, hook_obj)
                    
                    # ✨ CREATE AND ADD SYMBOL
                    # Find the correct parent symbol (should be the Function/Method containing this hook call)
                    parent_symbol = self.find_parent_symbol_for_ast_node(func_call)

                    hook_symbol = ApolloHookSymbol(
                        name=operation_name,
                        parent=parent_symbol,  # ← Le parent est correct (LambdaManager)
                        hook_name=hook_name,
                        operation_name=operation_name
                    )
                    hook_symbol._ast = func_call

                    # Add symbol to BOTH:
                    # 1. Parent symbol's table (for correct parent-child relationship)
                    parent_symbol.add_symbol(operation_name, hook_symbol)
                    # 2. Module's table (for global visibility with get_all_symbols)
                    if parent_symbol != self.module:
                        self.module.add_symbol(operation_name, hook_symbol)

                    print('  ✓ Created Apollo hook: {} with operation {}'.format(
                        hook_name, operation_name))
                    print('  ✓ Added ApolloHookSymbol to parent: {}'.format(parent_symbol.get_fullname()))

                except Exception as inner_ex:
                    print('  Exception in func_call loop: {}'.format(str(inner_ex)))
                    print(traceback.format_exc())
                    continue
                    
        except Exception as e:
            print('Error extracting Apollo hooks: {}'.format(str(e)))
            print(traceback.format_exc())

    def extract_operation_name(self, func_call):
        """
        Extract the GraphQL operation name from a hook call.
        For outline definitions: useQuery(GET_USERS, {...})
        """
        try:
            # Get the arguments
            parentheses = get_descendants(func_call, 'Parenthesis')
            if not parentheses:
                print('      No parentheses found')
                return None
            
            args_parenthesis = parentheses[0]
            
            # Get first child
            first_child = None
            for child in args_parenthesis.get_sub_nodes():
                first_child = child
                break

            
            if not first_child:
                print('      No first child found')
                return None
            
            # Check if it's an identifier (outline case)
            if hasattr(first_child, 'get_name'):
                operation_name = first_child.get_name()
                print('      First child get_name(): {}'.format(operation_name))
                if operation_name and operation_name != 'gql':
                    return operation_name
            else:
                print('      First child has no get_name() method')
            
            return None
            
        except:
            return None

    def extract_inline_gql(self, func_call):
        """
        Extract inline gql definition from a hook call.
        For inline definitions: useQuery(gql`...`, {...})
        
        Returns: (operation_name, metadata_dict) or (None, None)
        """
        try:
            # Get the arguments
            parentheses = get_descendants(func_call, 'Parenthesis')
            if not parentheses:
                print('    extract_inline_gql: No Parenthesis found')
                return (None, None)
            
            args_parenthesis = parentheses[0]
            
            # Get first child - if it's an ExpressionStatement, check for gql
            first_child = None
            for child in args_parenthesis.get_sub_nodes():
                first_child = child
                break
            
            if not first_child:
                print('    extract_inline_gql: No first child')
                return (None, None)
            
            # Check if first child is an ExpressionStatement (inline gql case)
            if is_ts_node_type(first_child, 'ExpressionStatement'):
                print('    extract_inline_gql: First child is ExpressionStatement')
                has_gql = False
                string_template = None
                
                # Look for 'gql' token and StringTemplate in the ExpressionStatement
                # Use get_children() instead of get_sub_nodes() to get both tokens and nodes
                for child in first_child.get_children():
                    print('      Checking child: {}'.format(type(child).__name__))
                    
                    # Check for 'gql' identifier node
                    if is_ts_node_type(child, 'Identifier'):
                        node_name = child.get_name() if hasattr(child, 'get_name') else None
                        print('      Identifier name: {}'.format(node_name))
                        if node_name == 'gql':
                            has_gql = True
                            print('      Found gql identifier')
                    
                    # Check for 'gql' token (direct Token object)
                    elif hasattr(child, '__class__') and 'Token' in child.__class__.__name__:
                        # It's a Token - check if it says 'gql'
                        token_str = str(child)
                        if "'gql'" in token_str or '"gql"' in token_str or 'Token.Generic,\'gql\'' in token_str:
                            has_gql = True
                            print('      Found gql token')
                    
                    # Check for StringTemplate node
                    if is_ts_node_type(child, 'StringTemplate'):
                        string_template = child
                        print('      Found StringTemplate')
                
                if has_gql and string_template:
                    print('    extract_inline_gql: Found inline gql definition')
                    # Parse the GraphQL content
                    metadata = self.parse_graphql_content(string_template)
                    operation_name = metadata.get('operationName')
                    print('    extract_inline_gql: Parsed operation_name = {}'.format(operation_name))
                    
                    if operation_name:
                        return (operation_name, metadata)
                else:
                    print('    extract_inline_gql: has_gql={}, string_template={}'.format(has_gql, string_template))
            else:
                print('    extract_inline_gql: First child is not ExpressionStatement, type={}'.format(type(first_child).__name__))
            
            return (None, None)
            
        except Exception as e:
            print('    extract_inline_gql: Exception: {}'.format(str(e)))
            print(traceback.format_exc())
            return (None, None)

    def create_hook_to_gql_links(self):
        """
        Create links between hooks and their GQL definitions
        """
        for operation_name, hooks in self.apollo_analysis_results.apollo_hooks_by_operation.items():
            for hook in hooks:
                # Try to find the corresponding GQL definition
                gql_def = self.apollo_analysis_results.get_gql_definition(operation_name)
                
                if gql_def:
                    # Store reference to GQL definition in hook
                    hook.gql_definition = gql_def.to_dict()
