"""
Apollo Client symbols for TypeScript analysis.
This module contains symbol classes specific to Apollo Client operations.
"""
import traceback
from cast.analysers import CustomObject, Bookmark, log, create_link

# Import Symbol base class for proper inheritance
try:
    from typescript_dependencies.symbols import Symbol
except:
    Symbol = object  # Fallback if imports fail


class ApolloHookSymbol(Symbol):
    """
    Symbol class for Apollo Client hooks.
    Inherits from Symbol to be properly integrated in the symbol table.
    """
    metamodel_type = 'CAST_TypeScript_Apollo_Hook'

    def __init__(self, name, parent, hook_name, operation_name=None):
        """
        Initialize an Apollo Hook symbol.

        Args:
            name: Symbol name (typically the operation name)
            parent: Parent symbol (typically the SourceFile or Function)
            hook_name: The Apollo hook name (e.g., 'useQuery', 'useMutation')
            operation_name: The GraphQL operation name (e.g., 'GET_LAMBDA_INVOCATIONS')
        """
        Symbol.__init__(self, name, parent)
        self.hook_name = hook_name
        self.operation_name = operation_name or name
        self.gql_definition = None  # Link to GqlDefinition
        self.inline = None  # Set to operation name if gql is defined inline

    def get_hook_name(self):
        """Return the Apollo hook name (e.g., 'useQuery')"""
        return self.hook_name

    def get_operation_name(self):
        """Return the GraphQL operation name"""
        return self.operation_name
    
    def save(self, source_file):
        """
        Override save() to prevent automatic KB object creation.
        KB objects are created manually in graphql_typescript_analyzer.py.
        """
        # Do not create KB objects here - they are created manually
        # in graphql_typescript_analyzer.py with the correct types
        # (TsGqlQuery, TsGqlMutation, TsGqlSubscription)
        pass

    def __repr__(self):
        return "ApolloHookSymbol({}, {})".format(self.hook_name, self.operation_name)


class GqlDefinitionSymbol(Symbol):
    """
    Symbol class for GraphQL definitions (const GET_USERS = gql`...`).
    Inherits from Symbol to be properly integrated in the symbol table.
    """
    metamodel_type = 'CAST_TypeScript_GraphQL_Definition'

    def __init__(self, name, parent, operation_type=None):
        """
        Initialize a GQL definition symbol.

        Args:
            name: Symbol name (typically the constant name like 'GET_LAMBDA_INVOCATIONS')
            parent: Parent symbol (typically the SourceFile)
            operation_type: Type of GraphQL operation ('query', 'mutation', 'subscription')
        """
        Symbol.__init__(self, name, parent)
        self.operation_type = operation_type
        self.operation_name = None  # Extracted from the query text
        self.variables = []
        self.fields_selected = []
        self.raw_query_text = None

    def get_operation_type(self):
        """Return the GraphQL operation type"""
        return self.operation_type

    def get_operation_name(self):
        """Return the GraphQL operation name"""
        return self.operation_name
    
    def save(self, source_file):
        """
        Override save() to prevent automatic KB object creation.
        KB objects are created manually in graphql_typescript_analyzer.py.
        """
        # Do not create KB objects here - they are created manually
        # in graphql_typescript_analyzer.py with the correct types
        # (GraphQLApolloHookQuery, GraphQLApolloHookMutation, etc.)
        pass

    def __repr__(self):
        return "GqlDefinitionSymbol({}, {})".format(self.get_name(), self.operation_type)


class ApolloHookObject:
    """
    Represents an Apollo Client hook invocation (useQuery, useMutation, useSubscription, useLazyQuery).
    Captures the hook type, GraphQL operation name, and location in the source code.
    """

    def __init__(self, hook_name, operation_name, ast_node, raw_bookmark, module,
                 source_pattern='react_hook', parent_symbol=None):
        """
        Initialize an Apollo Hook object.

        Args:
            hook_name: The Apollo hook name (e.g., 'useQuery', 'useMutation')
            operation_name: The GraphQL operation name (e.g., 'GET_LAMBDA_INVOCATIONS')
            ast_node: The AST node representing the hook call
            raw_bookmark: Position in the source code (RawBookmark instance)
            module: The parent module/caller
            source_pattern: Origin of the hook call. One of:
                'react_hook'    — direct useQuery/useMutation/etc. call
                'client_method' — imperative client.query/mutate/subscribe
                'angular_method'— Angular this.apollo.query/mutate/watchQuery
                'codegen_hook'  — Apollo Codegen generated hook (useGetXQuery etc.)
            parent_symbol: The TS symbol (Function/Method/Class) containing this hook call.
                Used in graphql_typescript_analyzer to set the correct callLink source
                (e.g., the wrapper function, not just the file).
        """
        self.hook_name = hook_name
        self.operation_name = operation_name
        self.ast_node = ast_node
        self.raw_bookmark = raw_bookmark
        self.module = module
        self.source_pattern = source_pattern
        self.parent_symbol = parent_symbol  # Symbol that contains this hook call
        self.kb_symbol = None
        self.inline = None  # Set to operation name if gql is defined inline

    def save(self, _):
        """
        No-op: KB objects are created manually in graphql_typescript_analyzer.py
        with the correct metamodel types (GraphQLApolloHookQuery, etc.).
        The TypeScript analyzer calls save() automatically on registered objects,
        but the old types (CAST_TypeScript_Apollo_useQuery, etc.) are not in the metamodel.
        """
        pass

    def get_hook_name(self):
        """Return the Apollo hook name (e.g., 'useQuery')"""
        return self.hook_name

    def get_operation_name(self):
        """Return the GraphQL operation name"""
        return self.operation_name

    def __repr__(self):
        return "ApolloHookObject({}, {}, {})".format(self.hook_name, self.operation_name, self.source_pattern)


class ApolloClientMethodObject:
    """
    Represents an Apollo Client method invocation (client.query, client.mutate, client.subscribe).
    This is for direct client method calls, not hooks.

    Example:
        const result = await client.query({ query: GET_DATA });
    """

    def __init__(self, method_name, operation_name, ast_node, raw_bookmark, module):
        """
        Initialize an Apollo Client method object.

        Args:
            method_name: The client method name (e.g., 'query', 'mutate', 'subscribe')
            operation_name: The GraphQL operation name
            ast_node: The AST node representing the method call
            raw_bookmark: Position in the source code (RawBookmark instance)
            module: The parent module/caller
        """
        self.method_name = method_name
        self.operation_name = operation_name
        self.ast_node = ast_node
        self.raw_bookmark = raw_bookmark
        self.module = module
        self.kb_symbol = None

    def save(self, _):
        """
        No-op: KB objects are created manually in graphql_typescript_analyzer.py.
        The old types (CAST_TypeScript_Apollo_ClientQuery, etc.) are not in the metamodel.
        """
        pass

    def get_method_name(self):
        """Return the Apollo client method name (e.g., 'query')"""
        return self.method_name

    def get_operation_name(self):
        """Return the GraphQL operation name"""
        return self.operation_name

    def __repr__(self):
        return "ApolloClientMethodObject({}, {})".format(self.method_name, self.operation_name)
