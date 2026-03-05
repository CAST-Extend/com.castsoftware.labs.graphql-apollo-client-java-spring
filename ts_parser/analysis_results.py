"""
Apollo Client Analysis Results
This module stores the results of Apollo Client analysis, similar to vue_analysis_results.py
"""
try:
    import traceback
    from cast.analysers import log, CustomObject, Bookmark
    from collections import OrderedDict
    from ts_parser.apollo_symbols import ApolloHookObject, ApolloClientMethodObject
except:
    from cast.analysers import log
    import traceback
    log.info('Problem in imports: ' + str(traceback.format_exc()))


class DefaultOrderedDict(OrderedDict):
    """
    OrderedDict with default factory support
    Source: http://stackoverflow.com/a/6190500/562769
    """

    def __init__(self, default_factory=None, *a, **kw):
        if (default_factory is not None and
           not callable(default_factory)):
            raise TypeError('first argument must be callable')
        OrderedDict.__init__(self, *a, **kw)
        self.default_factory = default_factory

    def __getitem__(self, key):
        try:
            return OrderedDict.__getitem__(self, key)
        except KeyError:
            return self.__missing__(key)

    def __missing__(self, key):
        if self.default_factory is None:
            raise KeyError(key)
        self[key] = value = self.default_factory()
        return value

    def __reduce__(self):
        if self.default_factory is None:
            args = tuple()
        else:
            args = self.default_factory,
        return type(self), args, None, None, self.items()

    def copy(self):
        return self.__copy__()

    def __copy__(self):
        return type(self)(self.default_factory, self)

    def __deepcopy__(self, memo):
        import copy
        return type(self)(self.default_factory,
                          copy.deepcopy(self.items()))

    def __repr__(self):
        return 'DefaultOrderedDict(%s, %s)' % (self.default_factory,
                                               OrderedDict.__repr__(self))


class RawBookmark:
    """
    Simple wrapper for AST node bookmarks
    """
    def __init__(self, ast_node, module):
        self.ast = ast_node
        self.module = module

    def get_bookmark(self):
        try:
            begin_line = self.ast.get_begin_line()
            if begin_line is None:
                log.warning('[RawBookmark] get_bookmark() missing line info for AST node: ' + str(self.ast))
                return None

            # Resolve the file object: SourceFile IS the Extensibility::File directly.
            # Try get_file() as a convenience if it exists; fall back to self.module.
            try:
                file_obj = self.module.get_file()
            except Exception:
                file_obj = self.module

            # Column info is not guaranteed on all node types — fall back to 0 if unavailable.
            try:
                begin_col = self.ast.get_begin_column()
                end_line  = self.ast.get_end_line()
                end_col   = self.ast.get_end_column() + 1
            except Exception:
                begin_col = 0
                end_line  = begin_line
                end_col   = 0

            return Bookmark(file_obj, begin_line, begin_col, end_line, end_col)
        except Exception as e:
            log.warning('[RawBookmark] get_bookmark() exception: ' + str(e))
            import traceback as _tb
            log.warning(_tb.format_exc())
            return None

    def __eq__(self, other):
        if isinstance(other, RawBookmark):
            return self.ast == other.ast and self.module == other.module
        return False

    def __hash__(self):
        return hash((id(self.ast), id(self.module)))


class Violation:
    """
    Represents a quality rule violation
    """

    def __init__(self, rulename: str, symbol, raw_bookmark: RawBookmark):
        """
        :param rulename: name of the violation (or property) as defined in the metamodel
        :param symbol: the symbol that hosts the violation
        :param raw_bookmark: RawBookmark instance
        """
        self.rulename = rulename
        self.symbol = symbol
        self.raw_bookmark = raw_bookmark

    def __eq__(self, other):
        if isinstance(other, Violation):
            return self.__key() == other.__key()
        return NotImplemented

    def __key(self):
        return (self.rulename, self.symbol, self.raw_bookmark)

    def save(self):
        pass


class KbProperty:
    """
    Represents a knowledge base property
    """

    def __init__(self, name: str, symbol):
        """
        :param name: name of the property as defined in the metamodel
        :param symbol: the symbol that hosts the property
        """
        self.name = name
        self.symbol = symbol

    def __eq__(self, other):
        if isinstance(other, KbProperty):
            return self.__key() == other.__key()
        return NotImplemented

    def __key(self):
        return (self.name, self.symbol)

    def save(self):
        pass


class GqlDefinition:
    """
    Represents a GraphQL definition (const GET_USERS = gql`...`)
    """

    def __init__(self, name: str, operation_name: str, operation_type: str, raw_query_text: str, 
                 variables: str, fields_selected: str, ast_node, raw_bookmark: RawBookmark):
        """
        :param name: Variable name (e.g., 'GET_LAMBDA_INVOCATIONS')
        :param operation_name: GraphQL operation name (e.g., 'GetLambdaInvocations')
        :param operation_type: 'query', 'mutation', or 'subscription'
        :param raw_query_text: The full GraphQL query text
        :param variables: GraphQL variables (e.g., '$functionName')
        :param fields_selected: Root field being queried (e.g., 'lambdaInvocations')
        :param ast_node: AST node of the definition
        :param raw_bookmark: Position in source code
        """
        self.name = name
        self.operation_name = operation_name
        self.operation_type = operation_type
        self.raw_query_text = raw_query_text
        self.variables = variables
        self.fields_selected = fields_selected
        self.ast_node = ast_node
        self.raw_bookmark = raw_bookmark

    def to_dict(self):
        """Convert to dictionary format for compatibility with existing tests"""
        return {
            'operationName': self.operation_name,
            'operationType': self.operation_type,
            'variables': self.variables,
            'fieldsSelected': self.fields_selected,
            'rawQueryText': self.raw_query_text,
            'bookmark': self.raw_bookmark
        }


class ApolloAnalysisResults:
    """
    Central storage for Apollo Client analysis results.
    Similar to VueAnalysisResults but for Apollo/GraphQL.
    """

    def __init__(self):
        # TypeScript evaluation tool (from the TypeScript analyzer)
        self.ts_evaluation_tool = None

        # Storage for analyzed TypeScript files
        self.ts_files = []

        # GQL definitions by variable name (e.g., 'GET_LAMBDA_INVOCATIONS')
        # Key: variable name
        # Value: GqlDefinition object
        self.gql_definitions_by_name = OrderedDict()

        # Apollo hooks by operation name
        # Key: operation name (e.g., 'GET_LAMBDA_INVOCATIONS' or 'GetLambdaInvocations')
        # Value: List[ApolloHookObject]
        self.apollo_hooks_by_operation = DefaultOrderedDict(list)

        # Apollo client method calls (client.query, client.mutate, etc.)
        # Key: operation name
        # Value: List[ApolloClientMethodObject]
        self.apollo_client_methods_by_operation = DefaultOrderedDict(list)

        # GQL definitions by file path
        # Key: file path
        # Value: List[GqlDefinition]
        self.gql_definitions_by_file = DefaultOrderedDict(list)

        # Apollo hooks by file path
        # Key: file path
        # Value: List[ApolloHookObject]
        self.apollo_hooks_by_file = DefaultOrderedDict(list)

        # Violations and properties
        self.violations = DefaultOrderedDict(list)  # [Violation] - key is the symbol
        self.kb_properties = DefaultOrderedDict(list)  # [KbProperty] - key is the symbol

        # GUIDs to avoid duplication
        self.guids_to_not_duplicate = []

    def add_gql_definition(self, gql_def: GqlDefinition):
        """
        Add a GraphQL definition to the analysis results
        
        :param gql_def: GqlDefinition object
        """
        self.gql_definitions_by_name[gql_def.name] = gql_def
        
        # Also add to file-based dictionary
        if gql_def.raw_bookmark and gql_def.raw_bookmark.module:
            file_path = gql_def.raw_bookmark.module.get_path()
            if gql_def not in self.gql_definitions_by_file[file_path]:
                self.gql_definitions_by_file[file_path].append(gql_def)

    def get_gql_definition(self, name: str):
        """
        Get a GraphQL definition by its variable name
        
        :param name: Variable name (e.g., 'GET_LAMBDA_INVOCATIONS')
        :return: GqlDefinition object or None
        """
        return self.gql_definitions_by_name.get(name)

    def add_apollo_hook(self, hook: ApolloHookObject):
        """
        Add an Apollo hook to the analysis results
        
        :param hook: ApolloHookObject
        """
        self.apollo_hooks_by_operation[hook.operation_name].append(hook)
        
        # Also add to file-based dictionary
        if hook.module:
            file_path = hook.module.get_path()
            if hook not in self.apollo_hooks_by_file[file_path]:
                self.apollo_hooks_by_file[file_path].append(hook)

    def add_apollo_client_method(self, method: ApolloClientMethodObject):
        """
        Add an Apollo client method call to the analysis results
        
        :param method: ApolloClientMethodObject
        """
        self.apollo_client_methods_by_operation[method.operation_name].append(method)

    def add_violation(self, rulename: str, symbol, raw_bookmark: RawBookmark):
        """
        Add a quality rule violation
        
        :param rulename: name of the violation as defined in metamodel
        :param symbol: the symbol that hosts the violation
        :param raw_bookmark: RawBookmark instance
        """
        violation = Violation(rulename, symbol, raw_bookmark)
        if violation not in self.violations[symbol]:
            self.violations[symbol].append(violation)

    def has_violation(self, symbol, rulename, raw_bookmark=None):
        """
        Check if a symbol has a specific violation (for testing)
        
        :param symbol: The symbol to check
        :param rulename: The violation rule name
        :param raw_bookmark: Optional specific bookmark to match
        :return: True if violation exists
        """
        if symbol not in self.violations:
            return False

        for violation in self.violations[symbol]:
            if not violation.rulename == rulename:
                continue
            if raw_bookmark:
                if not raw_bookmark == violation.raw_bookmark:
                    continue
            return True

        return False

    def add_property(self, symbol, property_name: str):
        """
        Add a knowledge base property
        
        :param symbol: the symbol that hosts the property
        :param property_name: name of the property
        """
        property = KbProperty(property_name, symbol)
        if property not in self.kb_properties[symbol]:
            self.kb_properties[symbol].append(property)

    def save_violations_and_properties(self):
        """
        Save all violations and properties to the knowledge base
        """
        for symbol, properties in self.kb_properties.items():
            if hasattr(symbol, 'get_kb_object'):
                symbol = symbol.get_kb_object()

            if not hasattr(symbol, 'save_property'):
                log.warning('Problem, trying to save a property for non valid symbol ' + str(symbol))
                continue

            for property in properties:
                symbol.save_property(property.name, 1)

        for symbol, violations in self.violations.items():
            if hasattr(symbol, 'get_kb_object'):
                symbol = symbol.get_kb_object()

            if not hasattr(symbol, 'save_violation'):
                log.warning('Problem, trying to save a violation for non valid symbol ' + str(symbol))
                continue

            for violation in violations:
                try:
                    symbol.save_violation(violation.rulename, violation.raw_bookmark.get_bookmark())
                except:
                    log.warning('Problem saving violation for symbol ' + str(symbol))
                    log.warning(traceback.format_exc())

    def create_links(self):
        """
        Create all links between Apollo objects and their dependencies
        """
        log.info('Creating links for Apollo Client hooks and GraphQL definitions')
        
        # Link hooks to their GraphQL definitions
        for operation_name, hooks in self.apollo_hooks_by_operation.items():
            for hook in hooks:
                # Try to find the corresponding GQL definition
                gql_def = self.get_gql_definition(operation_name)
                if gql_def:
                    # Store reference to GQL definition in hook
                    hook.gql_definition = gql_def.to_dict()
                    log.debug('Linked hook {} to GQL definition {}'.format(
                        hook.hook_name, gql_def.name))

    def get_cache_dicts(self):
        """
        Get analysis results as cache dictionaries (for backward compatibility with tests)
        
        :return: Tuple (gql_cache, hooks_cache)
        """
        # GQL cache
        gql_cache = {}
        for name, gql_def in self.gql_definitions_by_name.items():
            gql_cache[name] = gql_def.to_dict()

        # Hooks cache
        hooks_cache = {}
        for operation_name, hooks in self.apollo_hooks_by_operation.items():
            for hook in hooks:
                key = '{}:{}'.format(hook.hook_name, operation_name)
                hooks_cache[key] = {
                    'hookType': hook.hook_name,
                    'operationName': operation_name,
                    'bookmark': hook.raw_bookmark
                }

        return [gql_cache, hooks_cache]

    def log_summary(self):
        """
        Log a summary of the analysis results
        """
        log.info('='*80)
        log.info('Apollo Client Analysis Summary')
        log.info('='*80)
        log.info('GraphQL Definitions: {}'.format(len(self.gql_definitions_by_name)))
        log.info('Apollo Hooks: {}'.format(sum(len(hooks) for hooks in self.apollo_hooks_by_operation.values())))
        log.info('Apollo Client Methods: {}'.format(sum(len(methods) for methods in self.apollo_client_methods_by_operation.values())))
        log.info('Violations: {}'.format(sum(len(viols) for viols in self.violations.values())))
        log.info('Properties: {}'.format(sum(len(props) for props in self.kb_properties.values())))
        log.info('='*80)
