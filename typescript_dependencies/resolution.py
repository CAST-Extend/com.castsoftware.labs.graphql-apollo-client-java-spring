import re
import traceback
import typescript_dependencies.symbols as symbols
from collections import OrderedDict
from typescript_dependencies.common_tools import DefaultOrderedDict
from typescript_dependencies.filtering import get_closest_path
from typescript_dependencies.resolution_tools import Context
from typescript_dependencies.resolve_recursively import resolve_recursively, ResolutionParams
from typescript_dependencies.typescript_parser.light_parser import Walker, Token
from cast.analysers import log
from os.path import dirname, basename, join, normpath, sep
from typescript_dependencies.typescript_parser.parser import MemberAccess, Instantiation, \
    Parenthesis, MethodCall, FunctionCall, Identifier, Assignment, Class, Field, \
    VariableDeclaration, climb, Parameter, Function, ArrowExpression, is_function, \
    is_method, is_class, Return, is_identifier, is_member_access, is_method_call, If, \
    BinaryOperation, ForBlock, ObjectCurlyBracket, Method, Argument, \
    Decorator, Bracket, Root, CurlyBracket, \
    signature_matching, get_signature_for_ts_callable, ArrayAccess, Type, UnaryOperation, ConstructorField, IfTernary, \
    IfThenElseBlock, WithParameters
from pathlib import PureWindowsPath, Path
try:
    from frameworks.resolve_imported_frameworks import resolve_imported_frameworks
except ImportError:
    # frameworks module not available, define stub
    def resolve_imported_frameworks(*args, **kwargs):
        pass
from types import SimpleNamespace


def check_imported_frameworks(import_path, program):
    for framework, used in program.frameworks_used.items():
        if used:
            continue

        if is_importing_this_framework(import_path, program.frameworks_importpath[framework]):
            program.frameworks_used[framework] = True


def is_importing_this_framework(import_path, framework_name):
    if isinstance(framework_name, list):
        for f_i_n in framework_name:
            if f_i_n == import_path or re.search(r'\b' + f_i_n + r'\b', import_path):
                return True
    else:
        if framework_name == import_path:
            return True
        elif re.search(r'\b' + framework_name + r'\b', import_path):
            return True
    return False


def get_module_path_from_node(_ast):
    while True:
        if not hasattr(_ast, "parent"):
            return
        _ast = _ast.parent
        if isinstance(_ast.parent, Root):
            return _ast.parent.module.get_path()


def get_module_from_node(_ast):
    while True:
        if not hasattr(_ast, "parent"):
            return
        _ast = _ast.parent
        if isinstance(_ast, Root):
            return _ast.module


def get_callable_symbol_from_node(_ast):
    """
    :type _ast: Node
    """

    if isinstance(_ast, Argument):
        _ast = _ast.children[-1]

    if isinstance(_ast, (Function, ArrowExpression)):
        return _ast.symbol

    if hasattr(_ast, "get_resolution"):
        resol = _ast.get_resolution()
        if isinstance(resol, (symbols.Function, symbols.Method)):
            return resol

    if isinstance(_ast, MemberAccess):
        expr_resol = _ast.get_expression().get_resolution()
        if isinstance(expr_resol, symbols.Class):
            meth = expr_resol.get_symbol(_ast.get_name())
            if meth:
                return meth


def resolve_expressions(module, program):
    """
    Resolve the content of a file (a module or package)
    
    :param module: symbols.SourceFile
    :param program: symbols.Program
    """
    # walk the forest
    walker = Walker()
    interpreter = FirstPassResolutionInterpreter(module)
    walker.register_interpreter(interpreter)
    walker.walk(module.get_ast())
    
    interpreter.on_end()

    resolve_imported_frameworks(module)

    interpreter.on_end()


def get_descendants(node, kinds, max_level=None, level=0):
    """
    Get all descendants of a node of a certain kind
    """
    
    if not isinstance(kinds, (list, tuple)):
        kinds = [kinds]
    result = []
    for sub_node in node.get_sub_nodes():
        if type(sub_node) in kinds:
            result.append(sub_node)
        level = level + 1
        if max_level == level:
            break
        result += get_descendants(sub_node, kinds, level=level)
    return result


def resolve_call_using_class_instantiation(call_ast, instantiation_ast, arg_pos):
    try:
        arg = instantiation_ast.get_argument(arg_pos)
    except AttributeError:
        return
    if not arg:
        return
    resol = arg.get_resolution()
    if not isinstance(resol, symbols.Class):
        try:
            resol = resol.get_assigned_expression().get_class_identifier().get_resolution()
        except:
            pass
        if not isinstance(resol, symbols.Class):
            return
    resol_meth = resol.get_method(call_ast.get_name())
    if resol_meth and resol_meth not in call_ast._resolutions:
        resol_meth.get_ast().add_caller(call_ast)
        call_ast._resolutions.append(resol_meth)


def detect_elements(elements, program):
    """
    Register interesting framework/APIs
    """
    if elements:
        element_names = (elm.get_element().get_name() for elm in elements)
        for name in element_names:
            if name in program.imported_APIs:
                program.imported_APIs[name] = True


def get_parent_dir(file):
    """
    Returns the parent directory of the file passed
    """
    if file:
        file_path = file.get_path()
        dir_name = dirname(file_path)
        return dir_name
    return None


def get_nested_index_path(base_index, folder_name):
    """
    This function returns the path of the nested index file
    (barrel imports), by combining the following :
    
    > base_index : represents the base index file
    > folder_name : represents the folder name in which nested index file
                    can be found
    
    :param base_index: typescript_parser.symbols.SourceFile
    :param folder_name: typescript_parser.parser.Identifier
    """
    base_index_file_path = dirname(base_index.get_path())
    # Presently working for relative imports only
    folder = folder_name.get_text().lstrip('./')  
    nested_index_file_path = join(base_index_file_path, folder)
    return nested_index_file_path


def get_barrel_index_file(program_index_files, imr, module):
    """
    Returns the required index file by searching :
    > program_index_files: List of all the index files present in the program
    
    > imr: Reference to the imported module, points where the index file should
      be searched
    
    > module: Role of importing module is only when the imported module is 
      mentioned as '../../../'. So, to get the exact location (folder) where 
      index file could be located, importing module (location) is used.
    """
    
    index_file = None
    
    for file in program_index_files:
        
        index_parent_dir = get_parent_dir(file)
        
        # Extracting the imported module name (reference)
        imr_text = imr.get_text()
        
        if imr_text.endswith('../'):
        
            steps_to_location = imr_text.count('../')
            
            imr_location = PureWindowsPath(module.get_path()).parents[steps_to_location]
            
            # If the parent directory of the index file and the path
            # deduced using path of the module (importer)
            if index_parent_dir == str(imr_location):
                index_file = file
                break
        
        else:
            # If the import is of type import {sd,.. } from './data/'
            if imr_text.endswith('/'):
                imr_text = imr_text.rstrip('/')
            
            if basename(imr_text) == basename(index_parent_dir):
                index_file = file
                break
    return index_file


def resolve_globals(module, program):
    """
    Resolve the global elements of a file.
    Mainly the imports...
    
    Iterate over all the imports of a module 
    Search all imported symbols with a recursive search for the re-exports.
    @param module: symbols.SourceFile
    @param program: symbols.Program
    """
    # we start by the imports
    imports_angular = False
    i_import_angular = -1
    i = 0
    for _import in module.get_imports():
        try:
            import_path = _import.get_module().get_name()
            check_imported_frameworks(import_path, program)
            if 'angular' in import_path and i_import_angular==-1:
                i_import_angular = i
                module.is_angular = True

        except AttributeError:
            pass
        i+=1
        # _import: import node. import {element1, element2} from 'path_to_module';
        # @type _import: typescript_parser.parser.Import

        # @type elements: list of typescript_parser.parser.ImportedElement
        elements = _import.imported_elements
        
        detect_elements(elements, program)
        
        accessible_module = module.get_module_from_import(_import)
        if not accessible_module:
            accessible_module = module.get_module_from_import_with_non_exact_path(_import)

            if not accessible_module:
                continue

        if accessible_module not in module.accessible_modules:
            module.accessible_modules.append(accessible_module)
        # we create exported symbols for all exported constants (if they where not created already)
        accessible_module.create_exported_variable_symbols()

        if i_import_angular>-1 and accessible_module:
            accessible_module.is_angular = True

        _import._resolutions.append(accessible_module)
        ############################################################
        # case of require import: import element = require("path_to_module")
        if _import.is_require_import:
            imported_element_name = accessible_module._require_export_symbol_name
            if imported_element_name:
                symbol = accessible_module.get_symbol(imported_element_name)
                if symbol:
                    module.add_symbol(_import.get_imported_elements()[0].element.get_name(), symbol)
            else:
                # the whole module may be imported
                module.add_symbol(elements[0].get_element_name(), accessible_module)

            continue

        ############################################################
        # case or default import. Necessarly : import foo from 'foopath';  Note that foo is not within CurlyBracket
        default_import_local_name = _import.get_local_name_of_default_imported_variable()
        if default_import_local_name:
            if accessible_module.get_name().endswith('.json'):
                symbol = accessible_module
            else:
                symbol = accessible_module.get_default_symbol()

            if symbol:
                # found we register it with its aliased name or original name
                # if symbol.is_exported:
                module.add_symbol(default_import_local_name, symbol)

        ############################################################
        # case of a star alias : import * as star_alias from 'path_to_module'
        star_alias = _import.get_star_alias()
        # @type star_alias: typescript_parser.parser.Identifier
        if star_alias:
            # define a local name that points to the resolved module itself
            module.add_symbol(star_alias.get_text(), accessible_module)
            continue

        ############################################################
        # other cases
        imported_elements = _import.get_imported_elements()
        if imported_elements:
            imported_symbols = accessible_module.get_imported_symbols(imported_elements)
        elif not default_import_local_name:  # all elements are imported  : import * from 'foopath'
            imported_symbols = accessible_module.get_imported_symbols('all')
        else:
            imported_symbols = []

        for imported_symbol in imported_symbols:
            module.add_symbol(imported_symbol.import_name, imported_symbol.symbol)

    if i_import_angular>0:
        j = 0
        for _import in module.get_imports():
            if j == i_import_angular:
                break
            j+=1
            for res in _import._resolutions:
                res.is_angular = True

    # then ...
    resolve_sub_symbols(module)

    # see tests test_angular_resolution_with_injection_token in test_our_frameworks.py
    for decorator in get_descendants(module.get_ast(), Decorator):
        if decorator.get_name() == "NgModule":
            providers_from_import = []
            naming_match_from_imported_providers = OrderedDict()
            for parameter in decorator.get_parameters():
                if not isinstance(parameter, ObjectCurlyBracket):
                    continue
                try:
                    imports = parameter.get_dictionary()['imports']
                except KeyError:
                    pass
                else:
                    if not isinstance(imports, Bracket):
                        continue
                    for _import in imports.get_items():
                        if isinstance(_import, MethodCall):
                            try:
                                _class = module.get_symbol(_import.get_expression().get_name())
                                _method = _class.get_method(_import.get_name()).get_ast()

                                params = _method.get_parameters()
                                # the class may be passed as an argument
                                for i_arg, arg in enumerate(_import.get_arguments()):
                                    if i_arg == len(params):
                                        continue
                                    arg_id = arg.get_identifier()
                                    if not arg_id:
                                        continue
                                    if not params[i_arg].get_identifier():
                                        continue
                                    naming_match_from_imported_providers[params[i_arg].get_identifier().get_name()] = arg_id.get_name()

                                _returns = _method.get_returns()
                                for _return in _returns:
                                    pr = _return.get_expression().get_dictionary()['providers']
                                    if isinstance(pr, Bracket):
                                        providers_from_import.append(_return.get_expression().get_dictionary()['providers'])

                            except:
                                pass

                try:
                    providers = parameter.get_dictionary()['providers']
                except KeyError:
                    providers = []
                if not isinstance(providers, Bracket):
                    providers = []
                else:
                    providers = [providers]
                for prov in providers + providers_from_import:
                    for item in prov.get_items():
                        if not isinstance(item, ObjectCurlyBracket):
                            continue
                        item = item.get_dictionary()
                        try:
                            provide = item['provide']
                        except KeyError:
                            continue

                        try:
                            useClass = item['useClass']
                        except KeyError:
                            try:
                                useValue = item['useValue']
                            except KeyError:
                                continue
                            else:
                                provided = useValue
                        else:
                            if not isinstance(useClass, Identifier) and not isinstance(provide, Identifier):
                                continue
                            _class = module.get_symbol(useClass.get_name())
                            if not _class:
                                if useClass.get_name() in naming_match_from_imported_providers.keys():
                                    _class = module.get_symbol(naming_match_from_imported_providers[useClass.get_name()])
                                if not _class:
                                    continue
                            provided = _class
                        if isinstance(provide, Token):
                            provide_name = provide.text
                        elif isinstance(provide, Identifier):
                            provide_name = provide.get_name()
                        else:
                            continue
                        if provide_name not in program.angular_providers.keys():
                            program.angular_providers[provide_name] = [symbols.AngularProvider(provide_name, provided, module.get_path())]
                        else:
                            program.angular_providers[provide_name].append(symbols.AngularProvider(provide_name, provided, module.get_path()))


def resolve_sub_symbols(symbol):
    """
    Resolve the inheritances of all sub symbols recursively
    """
    implements = []
    try:
        implements = symbol.get_implements()
    except:
        # not a class
        pass
    
    # resolve inheritance if exist
    for implement in implements:
        # @type inheritance: typescript_parser.parser.Identifier
        if not isinstance(implement, Identifier):
            continue
        name = implement.get_text()
        resolved = find_symbol(symbol, name, symbols.Interface)
        if not resolved == symbol:
            implement.resolve_to(resolved)
        if not resolved:
            resolved = find_symbol(symbol, name)
            if not resolved == symbol:
                implement.resolve_to(resolved)

    extends = []
    try:
        extends = symbol.get_extendss()
    except:
        # not a class
        pass

    # resolve inheritance if exist
    for extend in extends:
        # @type inheritance: typescript_parser.parser.Identifier
        if not isinstance(extend, Identifier):
            continue
        name = extend.get_text()
        resolved = find_symbol(symbol, name, symbols.Class)
        if not resolved == symbol:
            extend.resolve_to(resolved)

    for sub_symbol in symbol.get_all_symbols():
        #we don't want to get out of the file
        if isinstance(sub_symbol, symbols.SourceFile):
            continue
        resolve_sub_symbols(sub_symbol)


def find_symbol(symbol, name, _type=None):
    """
    Find a symbol of given possibly qualified name referenced inside symbol
    @type symbol: symbols.Symbol
    """
    parent = symbol.get_parent_symbol()
    if not parent:
        # top level keep symbol as start
        parent = symbol
    
    qualified_names = name.split('.')
    
    # search first
    elementary_name = qualified_names[0]
    local = parent.get_symbol(elementary_name, _type)
    if not local and parent != symbol:
        # look up
        local = find_symbol(parent, elementary_name, _type)
        
    if not local:
        return
    
    parent = local
    
    # now recurse...
    for elementary_name in qualified_names[1:]:
        
        parent = parent.get_symbol(elementary_name)
        if not parent:
            return
        
    return parent


class TypeInference:
    """
    Type inference engine ( Work in progress ).
    
    Adapted from "com.castsoftware.python" analyzer
    
    Limitations
    -----------
        - Not implemented "return_type"
    """
    
    def __init__(self):
        self.variables = []
        self.declarations = []
        self.assignments = []
        self.calls = []  # method_calls

        self.variable_types = DefaultOrderedDict(set)
    
    def add_method_call(self, ast):
        if isinstance(ast, MemberAccess):
            return
        self.calls.append(ast)

    def add_declaration(self, ast):
        self.declarations.append(ast)

    def add_assignment(self, ast):
        self.assignments.append(ast)
        
    def add_variable(self, identifier):
        if not isinstance(identifier, Identifier):
            return
        expr = Expression(identifier)
        if expr not in self.variables:
            self.variables.append(expr)
    
    def infer(self):

        groups = AliasGroups(self.variables)

        #---------------------------
        # group variables by alias
        #---------------------------
        # (I) trivial assignements (aliasing) of the form
        #         a = b
        #
        # (II) variable declarations with assignments
        #         var a = b
        #
        for assignment in self.assignments:

            left = Expression(assignment.get_left_expression())
            if not left.variable or left.rest:
                continue

            right_expr = assignment.get_right_expression()
            if not right_expr:
                continue
            right = Expression(right_expr)
            if not right.variable or right.rest:
                continue

            groups.connect(left, right)  # new groups

        for declaration in self.declarations:
            for variable in declaration.get_variables():
                left = Expression(variable)
                if not left.variable or left.rest:
                    continue
                if not variable.get_name() in declaration.get_expressions():
                    continue
                right = Expression(declaration.get_expressions()[variable.get_name()])
                if not right.variable or right.rest:
                    continue
                groups.connect(left, right)

        # constructor calls in variable declarations give sure types
        for declaration in self.declarations:

            right = None

            if isinstance(declaration, VariableDeclaration):
                right_expressions = declaration.get_expressions()
                for var in declaration.get_variables():
                    expression = Expression(var)
                    if not expression.variable:
                        continue
                    group = groups.find_group(expression)
                    if not group:
                        continue
                    if not var.get_name() in right_expressions:
                        continue
                    right = right_expressions[var.get_name()]
                    if right and isinstance(right, Instantiation):
                        clazz = right.get_resolution()  # here we expect well-defined type
                        if clazz:
                            group.add_sure_type(clazz)

            # work in progress (currently non-active)
            elif isinstance(declaration, Field):
                assig = next(declaration.get_sub_nodes(Assignment))
                if not assig:
                    continue
                expression = Expression(assig.get_left_expression2())
                group = groups.find_group(expression)
                if not group:
                    continue
                right = assig.get_right_expression()

                if right and isinstance(right, Instantiation):
                    clazz = right.get_resolution()  # here we expect well-defined type
                    if clazz:
                        group.add_sure_type(clazz)

        # ============
        # method calls
        # ============
        # using information from method calls
        for call in self.calls:
            expression = Expression(call.get_expression())
            if not expression.variable or expression.rest:
                continue

            group = groups.find_group(expression)
            if not group:
                continue

            group.add_called_method_name(call.get_name())
            group.add_call(call)

            for method in call.get_resolutions():
                _class = method.get_parent_symbol()
                if isinstance(_class, symbols.Class):
                    group.add_possible_type(_class)

        for group in groups.groups:

            # debugging
            if False:
                # @type group: AliasGroup
                log.info('AliasGroup')
                for variable in group.variables:
                    log.info('   ', variable)
                log.info('  Possibles')
                for _type in group.possible_types:
                    # log.info('   ', _type.get_qualified_name())
                    log.info('   ', _type.get_name())
                log.info('  Methods')
                for method in group.called_method_names:
                    log.info('   ', method)
                log.info('  Sures')
                for _type in group.sure_types:
                    # log.info('   ', _type.get_qualified_name())
                    log.info('   ', _type.get_name())
#             log.info('  Contains parameter ?', group.contains_parameter())
                log.info('  Calls')
                for call in group.calls:
                    log.info('   ', call)

            if group.is_sure() and group.sure_types:
                # we do not have assignment from
                # a parameter and we have found sure types
                # ==> reset all calls with sure types only
                apply_types_to_calls(group.calls, group.sure_types)


def apply_types_to_calls(calls, types):
    for call in calls:
        resolutions = []
        for method in call.get_resolutions():
            for _class in types:
                resolved_methods = _class.find_method(method.get_name())
                for resolved in resolved_methods:
                    if method == resolved:
                        resolutions.append(method)

        # handling of "inverse link" of _resolutions
        # used by evaluation
        # remove old ones
# TODO
#         for resolution in call._resolutions:
#             if resolution.get_ast():
#                 try:
#                     resolution.get_ast().remove_caller(call)
#                 except:
#                     pass
#                     log.info("  **Some issue ...")
#                     raise
#                     # should not happen as it called should be a function
#                     log.debug('Issue in end_MethodCall for token %s' % str(call))
#
        # add new ones
        call._resolutions = resolutions

# TODO
#         for resolution in call.get_resolutions():
#             if resolution.get_ast():
#                 try:
#                     resolution.get_ast().add_caller(call)
#                 except:
#                     # should not happen as it called should be a function
#                     log.debug('Issue in end_MethodCall for token %s' % str(call))
#                     log.info("Some issue ...")


def is_formal_parameter(node):
    """
    True when node is a parameter of a method
    @todo : decide for parameter that can be 
    either Identifier or Assignement
    """
    pass
#
#     statement = node.get_enclosing_statement()
#
#     if not is_function(statement):
#         return False
#
#     # @type statement:  python_parser.Function
#     for parameter in statement.get_parameters():
#
#         if parameter == node:
#             return True
#
#         if is_assignement(parameter) and node == parameter.get_left_expression():
#             return True
#
#     return False


class Variable:
    """
    Auxiliar class to make variable identifiers
    hashable.
    """

    def __init__(self, identifier):
        self.identifier = identifier

    def __eq__(self, variable):
        object.__eq__(self.identifier, variable.identifier)

    def __hash__(self):
        return object.__hash__(self)


class Expression:
    """
    Auxiliar class wrapping an expression (including 
    standalone variables), possibly nested inside a general 
    method call in which case the leading expression 
    is returned:    
        
        a.b.c.d.e()  --->  a + "b.c.d.e"
                 get_expression
    
    In the case of nested expressions, information 
    on the enclosing expression is kept (self.rest).
    
    It implements __hash__ for being able to register 
    into a set (only accepting hashable objects)  
        
    todo: support other expressions: c(), c[], c["k"], ..
    """
    def __init__(self, node):
        self.node = node
        self.variable, self.rest = extract_variable_and_rest(node)

    def __eq__(self, expression):

        try:
            return self.variable == expression.variable and self.rest == expression.rest
        except:
            return False

    def __hash__(self):
        return hash((self.variable, self.rest))
    
    def __repr__(self):
        return 'Expression(' + str(self.variable) + ', ' + str(self.rest) + ')'


def extract_variable_and_rest(node):
    """
    split method call
    """
    if isinstance(node, Identifier):
        # why it returns the resolution of an identifier?
        resolution = node.get_resolution()
        if resolution and resolution.__hash__:
            return resolution, ''
        else:
            return node, ''

    return None, None


class AliasGroup:
    """
    A group of variables.
    """

    def __init__(self):
        self.variables = []
        self.possible_types = []
        self.called_method_names = []
        self.sure_types = []
        self.calls = []
        self.sure = True

    def add_sure_type(self, _type):
        """
        Say that _type is a sure type
        :type _type: symbols.Class
        """
        if not _type in self.sure_types:
            self.sure_types.append(_type)

    def add_possible_type(self, _type):
        """
        Say that _type is a possible type
        """
        if not _type in self.possible_types:
            self.possible_types.append(_type)

    def add_called_method_name(self, name):
        if not name in self.called_method_names:
            self.called_method_names.append(name)

    def add_call(self, call):
        self.calls.append(call)

    def is_sure(self):
        """
        True when assigned types can be considered as sure.
        
        Whenever something with unclear type is 
        assigned to one of the expressions,
        then it is unsure.
        """
        if not self.sure:
            return False

        # by essence, parameters have unknown type
        if self.contains_parameter():
            return False

        return True

    def set_as_not_sure(self):

        self.sure = False

# parameters do have type!
    def contains_parameter(self):
        """
        Return true when this group contains a formal parameter
        """
        pass
#         for expression in self.variables:
#             # @type expression: Expression
#             if is_formal_parameter(expression.variable):
#                 return True
#
#         return False

    def contains_this(self):
        """
        Return true when this group contains a formal parameter
        """
        for expression in self.variables:
            # @type expression: Expression
            if expression.variable.get_name() == 'this':
                return True

        return False

    def get_possible_types(self):
        """
        Get all the possible types
        
        Heuristic - restrict by keeping only types 
        that contains all methods called on variables
        
        TODO: try-except
        """
        result = []
        for _type in self.possible_types:
            # @type _type: symbols.Class
            ok = True

            for method_name in self.called_method_names:
                if not _type.get_function(method_name):
                    ok = False
                    break

            if ok:
                result.append(_type)

        return result

    def contains(self, variable):
        return variable in self.variables

    @staticmethod
    def create(variable):
        result = AliasGroup()
        result.variables = [variable]
        return result

    @staticmethod
    def merge(group1, group2):
        result = AliasGroup()
        result.variables = group1.variables + group2.variables
        return result


class AliasGroups:

    def __init__(self, variables):
        self.groups = []
        for variable in variables:
            self.groups.append(AliasGroup.create(variable))

    def find_group(self, variable):
        for group in self.groups:
            if group.contains(variable):
                return group

    def connect(self, tr1, tr2):
        """
        find groups and replace them by merged one 
        """
        group1 = self.find_group(tr1)
        group2 = self.find_group(tr2)

        if group1 and group2 and group1 != group2:
            self.groups.remove(group1)
            self.groups.remove(group2)
            self.groups.append(AliasGroup.merge(group1, group2))



def handle_or_binary(asts):
    if not asts:
        return []
    to_return = []
    if isinstance(asts, list):
        for ast in asts:
            to_return.extend(handle_or_binary(ast))
    else:
        if isinstance(asts, BinaryOperation) and asts.get_operator() == "||":
            to_return.extend(handle_or_binary(asts.get_left_expression()))
            to_return.extend(handle_or_binary(asts.get_right_expression()))
        else:
            to_return.append(asts)
    return to_return

def add_possible_value_to_resolution(resolution, possible_value):
    if not resolution:
        return
    possible_values = handle_or_binary(possible_value)
    for v in possible_values:
        if not hasattr(resolution, "possible_values"):
            resolution.possible_values = [v]

        else:
            resolution.possible_values.append(v)

def resolve_to_declaration(module):
    """
    Resolve the content of a file (a module or package)

    :param module: symbols.SourceFile
    """
    # walk the forest
    walker = Walker()
    interpreter = FirstPassResolutionInterpreter(module)
    walker.register_interpreter(interpreter)
    walker.walk(module.get_ast())

class BaseResolutionInterpreter:


    def __init__(self, module):
        """
        :param module: symbols.SourceFile
        """

        # Context Stack
        self.__context_stack = []

        # Creating the context with symbol (parent is None)
        self.module = module
        # Pushing the context

        self.pinia_mapped_stores = OrderedDict()

        # Symbol Stack with module at the bottom of stack
        self.__symbol_stack = []
        self.push_symbol(module)
        self.__class_and_object_stack = []
        self.resol_import = OrderedDict()
        self.conditional_instances = []
        self.imported_names = []

    def member_resolves_to_class_Field(self, m_a):
        for resol in m_a.get_resolutions():
            if hasattr(resol, 'get_parent_symbol') and isinstance(resol.get_parent_symbol(), symbols.Class):
                return True
        return False

    def resolves_to_callable(self, m_c):
        for resol in m_c.get_resolutions():
            if hasattr(resol, 'get_parent_symbol') and isinstance(resol.get_parent_symbol(), symbols.Class):
                return True
            if isinstance(resol, symbols.Function):
                return True

        return False

    def start_IfThenElseBlock(self, _ast):

        if  _ast.is_else():
            return
        condition = _ast.get_condition()

        if not hasattr(condition, 'get_children'):
            return
        prev_child = None
        for child in condition.get_children():
            if isinstance(child, UnaryOperation) and child.get_operator() == 'instanceof':
                self.conditional_instances.append(ConditionalInstance(prev_child, child.get_expression(), _ast))
            prev_child = child

    def end_IfThenElseBlock(self, _ast):
        if not self.conditional_instances:
            return
        if self.conditional_instances[-1].condtionblock_ast == _ast:
            self.conditional_instances = self.conditional_instances[:-1]


    def get_current_class_or_object(self):
        if len(self.__class_and_object_stack) > 0:
            return self.__class_and_object_stack[-1]
    def push_symbol(self, symbol):
        # Creating the context with symbol (parent is None)
        context = Context(symbol, parent=self.get_current_context())
        self.push_context(context)
        for sub_symbol_name, sub_symbols in symbol.symbols.items():
            for sub_symbol in sub_symbols:
                if isinstance(sub_symbol, symbols.Field) and not isinstance(sub_symbol.get_ast(), ConstructorField):
                    continue
                elif isinstance(sub_symbol, symbols.ExportedVariable) and sub_symbol.get_parent_symbol()==symbol:
                    continue
                elif isinstance(sub_symbol, symbols.Function):
                    if sub_symbol.is_from_object:
                        continue
                    if hasattr(sub_symbol, 'is_htm_attribute_function'):
                        continue
                    if hasattr(sub_symbol.get_ast(), 'parent'):
                        parent_ast = sub_symbol.get_ast().parent
                        if isinstance(parent_ast, Assignment):
                            try:
                                if parent_ast.get_left_expression().get_fullname().startswith('this'):
                                    continue
                            except AttributeError:
                                pass
                        elif isinstance(parent_ast, Parameter):
                            continue



                self.get_current_context().declare_variable(sub_symbol_name, sub_symbol)
        return self.__symbol_stack.append(symbol)

    def pop_symbol(self):
        self.__symbol_stack.pop()

    def push_class_or_object(self, symbol):
        # this stack is usefull for getting the this
        return self.__class_and_object_stack.append(symbol)

    def pop_class_or_object(self):
        self.__class_and_object_stack.pop()

    def push_context(self, context):
        """
        :param context : Context
        """
        #         for _import in context.get_symbol().get_imports():
        #             context.use_import(_import)
        #
        self.__context_stack.append(context)

    def pop_context(self):
        self.__context_stack.pop()

    def get_current_context(self):
        """
        @rtype : Context
        """
        if self.__context_stack:
            return self.__context_stack[-1]

    def get_current_module(self):
        """
        @type: SourceFile
        """
        return self.__symbol_stack[0]

    def _get_current_symbol(self):
        """
        @rtype: symbols.Symbol
        """
        return self.__symbol_stack[-1]

    def get_current_callable(self):
        symbol = self.__symbol_stack[-1]
        while isinstance(symbol, symbols.Class):
            symbol_initializer = symbol.get_initializer()
            if symbol_initializer:
                return symbol_initializer
            else:
                symbol = symbol.get_parent_symbol()

        return symbol

    def get_current_class(self):
        """
        @rtype : symbols.Class
        """
        symbol = self._get_current_symbol()
        """
        @type symbol: symbols.Symbol
        """
        while symbol and not isinstance(symbol, symbols.Class):
            if not hasattr(symbol, 'get_parent_symbol'):
                return
            symbol = symbol.get_parent_symbol()

        return symbol

    def start_ObjectCurlyBracket(self, ast_object):
        self.push_class_or_object(ast_object)

    def end_ObjectCurlyBracket(self, _):
        self.pop_class_or_object()

    def start_Class(self, ast_class):
        """
        @type: ast_class: typescript_parser.parser.Class
        """
        symbol = self._get_current_symbol()
        name = ast_class.get_name()

        _class = symbol.get_class(name, ast_class.get_begin_line())
        if not _class :
            log.warning("No class found for %s under %s" % (str(name), str(symbol)))
            ast_class.no_symbol_found = True
        else:
            self.push_symbol(_class)
            self.push_class_or_object(_class)

    def end_Class(self, _ast):
        if hasattr(_ast, 'no_symbol_found'):
            return
        self.pop_symbol()
        self.pop_context()
        self.pop_class_or_object()

    def start_Namespace(self, ast_namespace):
        """
        @type: ast_namespace: typescript_parser.parser.Namespace
        """
        symbol = self._get_current_symbol()
        name = ast_namespace.get_name()

        namespace = symbol.get_namespace(name)
        if not namespace:
            log.warning("No namespace found for %s under %s" % (str(name), str(symbol)))

        self.push_symbol(namespace)

    def end_Namespace(self, _ast):
        self.pop_context()
        self.pop_symbol()

    def start_SelfClosingHtmlTag(self, ast):
        # only the outtermost htmltag should have a symbol
        if hasattr(ast, "symbol_name"):
            symbol = self._get_current_symbol()
            html_fragment = symbol._get_typed_symbol(ast.symbol_name,
                                                     ast.get_begin_line(),
                                                     symbols.HtmlFragment)

            if not html_fragment :
                log.warning("No html fragment found for %s under %s" % (str(ast.symbol_name), str(symbol)))

            self.push_symbol(html_fragment)

    def end_SelfClosingHtmlTag(self, _ast):
        if hasattr(_ast, "symbol_name"):
            self.pop_symbol()
            self.pop_context()

    def start_HtmlTag(self, _ast):

        # only the outtermost htmltag should have a symbol
        if hasattr(_ast, "symbol_name"):
            symbol = self._get_current_symbol()
            html_fragment = symbol._get_typed_symbol(_ast.symbol_name,
                                                     _ast.get_begin_line(),
                                                     symbols.HtmlFragment)
            if not html_fragment :
                log.warning("No html fragment found for %s under %s" % (str(_ast.symbol_name), str(symbol)))

            self.push_symbol(html_fragment)

    def end_HtmlTag(self, _ast):
        if hasattr(_ast, "symbol_name"):
            self.pop_context()
            self.pop_symbol()

    def start_Interface(self, ast_interface):
        """
        @type ast_interface: typescript_parser.parser.Interface
        """
        symbol = self._get_current_symbol()
        name = ast_interface.get_name()

        interface = symbol.get_interface(name)
        if not interface:
            log.warning("No interface found for %s under %s" % (str(name), str(symbol)))

        self.push_symbol(interface)

    def end_Interface(self, _ast):
        self.pop_symbol()
        self.pop_context()

    def start_ArrowExpression(self, _ast_function):
        if _ast_function.is_arrow_function:
            self.start_Function(_ast_function)
            if _ast_function.children[0] in ['var', 'const', 'let']:
                return
            if not '=' in _ast_function.children:
                return
            # the arrow function is assigned to a variable
            context = self.get_current_context()
            resol = context.resolve_variable(_ast_function.get_name())
            add_possible_value_to_resolution(resol, _ast_function)
        elif _ast_function.is_arrow_method:
            self.start_Method(_ast_function)

    def end_ArrowExpression(self, _ast_function):
        if _ast_function.is_arrow_function:
            self.end_Function(_ast_function)
        elif _ast_function.is_arrow_method:
            self.end_Method(_ast_function)

    def start_Function(self, ast_function):
        """
        @type ast_function: typescript_parser.parser.Function
        """
        name = ast_function.get_name()
        symbol = self._get_current_symbol()

        if symbol:
            function = symbol.get_function(name, ast_function.get_begin_line())
            if not function:
                log.warning("No function found for %s under %s"
                            % (str(name), str(symbol.get_fullname())))
                log.debug(str(ast_function))
                ast_function.no_symbol_found = True
                return

            function._ast = ast_function

            self.push_symbol(function)

        else:
            log.debug("no symbol found for function {} in {}".format(name, self.__symbol_stack[-1].get_fullname()))

    def end_Function(self, _ast):
        if hasattr(_ast, 'no_symbol_found'):
            delattr(_ast, 'no_symbol_found')
            return

        context = self.get_current_context()
        symbol = self._get_current_symbol()
        if symbol:
            if isinstance(_ast, Function) or (isinstance(_ast, ArrowExpression) and _ast.is_arrow_function):
                self.pop_context()
            self.pop_symbol()
            return symbol

    def start_Method(self, ast_method):
        """
        @type ast_method: typescript_parser.parser.Method
        """
        name = ast_method.get_name()
        symbol = self._get_current_symbol()

        if symbol:
            method = symbol.get_method_for_parsing(name, ast_method.get_begin_line())
            if not method:
                log.warning("no method found for %s under %s"
                            % (str(name), str(symbol.get_name())))
                ast_method.no_symbol_found = True
                return

            self.push_symbol(method)
        else:
            log.debug("no symbol found for method {} in {}".format(name, self.__symbol_stack[-1].get_fullname()))

    def end_Method(self, _ast):
        if hasattr(_ast, 'no_symbol_found'):
            delattr(_ast, 'no_symbol_found')
            return

        context = self.get_current_context()
        symbol = self._get_current_symbol()
        if symbol:
            self.pop_context()
            self.pop_symbol()

    def end_MemberAccess(self, m_a):
        self.end_MemberAccess_or_MethodCall(m_a)

        if not m_a.get_resolutions() and m_a.get_expression() == 'this':
            if m_a.get_name() in self.pinia_mapped_stores:
                m_a._resolutions.append(self.pinia_mapped_stores[m_a.get_name()])

        if m_a.is_set() and m_a.get_resolution():
            resolution = m_a.get_resolution()

            add_possible_value_to_resolution(resolution, m_a.parent.get_right_expression())

    def end_MemberAccess_or_MethodCall_handle_require(self, _ast):
        expression = _ast.get_expression()
        # we first check if the expression is a require import
        if isinstance(expression, Identifier):
            if _ast.get_name() == 'default':
                try:
                    resols = self.module.symbols[expression.get_name() + ".default"]
                    for resol in resols:
                        resol.get_ast().add_caller(_ast)
                    _ast._resolutions = resols
                    return
                except KeyError:
                    pass

            node_import = self.module.get_symbol(expression.get_name(), _type=symbols.NodeExport)

            if node_import:
                resolution = node_import.get_symbol(_ast.get_name)
                if resolution:
                    resolution.get_ast().add_caller(_ast)
                    _ast._resolutions = [resolution]
                return

    def resolves_to_actual_method(self, ast):
        resolves = False
        for res in ast.get_resolution():
            pass

    def end_MemberAccess_or_MethodCall(self, ast):
        resolve_to_non_interface_attribute = False
        for res in ast.get_resolutions():
            if hasattr(res, 'get_parent_symbol') and isinstance(res.get_parent_symbol(), symbols.Interface):
                continue
            resolve_to_non_interface_attribute = True
        if resolve_to_non_interface_attribute:
            return

        expr = ast.get_expression()
        for cond in self.conditional_instances[::-1]:
            if cond.matches_expr(expr):
                expr = cond.type
                break

        resolve_recursively(expr,
                            resolution_params=ResolutionParams(
                                imported_names=self.imported_names,
                                resolution_interpreter=self,
                                initial_target=ast,
                                save_resolution=True
                            ))
        if not ast.get_resolution():
            self.end_MemberAccess_or_MethodCall_handle_require(ast)

    def start_Identifier(self, identifier):
        pass

    def end_MethodCall(self, m_c):

        m_c.parent_symbol = self.get_current_callable()
        self.end_MemberAccess_or_MethodCall(m_c)

        if not m_c.get_resolution() and m_c.get_name() == 'apply':
            expr = m_c.get_expression()
            if hasattr(expr, 'get_resolutions'):
                for res in expr.get_resolutions():
                    if isinstance(res, symbols.Method):
                        m_c._resolutions.append(res)

class ConditionalInstance:
    """
    when there is a condition and an instance such as
    if (expr instanceof A){}
    """

    def __init__(self, expr, _type, conditionblock_ast:IfThenElseBlock):
        self.expr = expr
        self.type = _type  #
        self.condtionblock_ast = conditionblock_ast

    def matches_expr(self, e):
        if isinstance(e, Identifier) and isinstance(self.expr, Token):
            if e.get_name()==self.expr:
                return True

        if isinstance(e, MemberAccess) and isinstance(self.expr, MemberAccess) and e.get_fullname() == self.expr.get_fullname():
            return True

        return False


class FirstPassResolutionInterpreter(BaseResolutionInterpreter):


    def on_end(self):
        context = self.get_current_context()
        symbol = self._get_current_symbol()
        if symbol:
            symbol.complexity = context.complexity

    def end_Function(self, _ast):
        if hasattr(_ast, 'no_symbol_found'):
            delattr(_ast, 'no_symbol_found')
            return

        context = self.get_current_context()
        symbol = self._get_current_symbol()
        if symbol:
            symbol.complexity = context.complexity
            if isinstance(_ast, Function) or (isinstance(_ast, ArrowExpression) and _ast.is_arrow_function):
                self.pop_context()
            self.pop_symbol()
            return symbol

    def end_Method(self, _ast):
        if hasattr(_ast, 'no_symbol_found'):
            delattr(_ast, 'no_symbol_found')
            return

        context = self.get_current_context()
        symbol = self._get_current_symbol()
        if symbol:
            symbol.complexity = context.complexity
            self.pop_context()
            self.pop_symbol()

    def end_ConstructorField(self, ast):
        for decorator in ast.get_decorators():
            if not decorator.get_name() == 'Inject':
                continue
            params = decorator.get_parameters()
            if not len(params) == 1:
                continue
            param = decorator.get_parameters()[0]
            if not hasattr(param, 'text') or not param.text:
                return
            injected_name = param.text.strip('"').strip("'")
            resolution = None
            try:
                angular_providers = self.get_current_module().get_program().angular_providers[injected_name]
            except KeyError:
                pass
            else:
                if len(angular_providers) > 1:
                    closest_path = get_closest_path(self.get_current_module().get_path(),
                                                    [prov.path for prov in angular_providers])
                    angular_providers = [prov for prov in angular_providers if prov.path == closest_path]
                resolution = angular_providers[0]._class

            if resolution:
                ast._resolutions = [resolution]
            else:
                classes = self.module.get_program().get_classes_by_name(injected_name)
                ast._resolutions = classes

    @staticmethod
    def store_inherited_types(_class):
        """
        Get extended classes and implemented interfaces of the given class and store them in "Class.inherited_by" or
        in "Interface.inherited_by"
        :param _class: symbols.Class
        """
        for inherited_class in _class.get_inheritances():
            inherited_symbol = inherited_class.get_resolution()
            if not isinstance(inherited_symbol, (symbols.Class, symbols.Interface)):
                continue
            # add "_class" to the set of classes that implement\extend the "inherited_class"
            if not _class in inherited_symbol.inherited_by:
                inherited_symbol.inherited_by.append(_class)

    def end_Class(self, _ast):
        if hasattr(_ast, 'no_symbol_found'):
            return

        _class = self._get_current_symbol()
        ast_fragments = _class.initializer_ast_fragments
        self.store_inherited_types(_class)

        for impl in _ast.get_implements():
            if not hasattr(impl, 'get_resolution'):
                continue

            if isinstance(impl.get_resolution(), symbols.Interface):
                if not self in impl.get_resolution().implemented_by:
                    impl.get_resolution().implemented_by.append(_class)


        if ast_fragments:
            initializer = symbols.ClassInitializer(ast_fragments, _class)
            self.module.class_initializers.append(initializer)
            _class.initializer = initializer
            _class.add_symbol('ClassInitializer', initializer)

        super().end_Class(_ast)

    def start_IfThenElseBlock(self, _ast):

        if not _ast.is_else():
            self.increment_complexity()

            condition = _ast.get_condition()
            self.analyse_complexity(condition)
        super().start_IfThenElseBlock(_ast)

    def end_IfThenElseBlock(self, _ast):
        pass

    def start_ForBlock(self, _ast):
        condition = _ast.get_condition()
        self.analyse_complexity(condition, _ast)

    def start_WhileBlock(self, _ast):
        self.increment_complexity()
        condition = _ast.get_condition()
        self.analyse_complexity(condition)

    def start_DoWhileBlock(self, _ast):
        self.increment_complexity()

    def increment_complexity(self):
        context = self.get_current_context()
        context.increment_complexity()

    def analyse_complexity(self, condition, node=None):
        if not condition:
            return

        operations = get_descendants(condition, BinaryOperation, max_level=1)
        for operation in operations:
            operator = operation.get_operator()
            if operator in ['||', '&&']:
                self.increment_complexity()
            elif operation in ['<', '>']:
                if isinstance(node, ForBlock):
                    self.increment_complexity()

    def start_StringTemplate(self, string):
        """
        We resolve the expression inside the String Template.
        This expressions are parsed independently, so they
        do not belong to the module AST. Thus the identifiers
        (among others) inside the expressions of the String
        Template resolved explicitly below.
        """
        string.extract_expressions()

        def resolve_arguments(expr):
            if not hasattr(expr, 'get_arguments'):
                return

            for arg in expr.get_arguments():
                try:
                    if isinstance(arg, Argument):
                        child = arg.children[0]
                    else:
                        child = arg
                    if isinstance(child, Identifier):
                        self.start_Identifier(child)
                    elif isinstance(child, MemberAccess):
                        self.end_MemberAccess(child)
                        root_expr = child.get_root_expression()
                        if isinstance(root_expr, Identifier):
                            self.start_Identifier(root_expr)
                    elif isinstance(child, MethodCall):
                        self.end_MethodCall(child)
                    elif isinstance(child, FunctionCall):
                        self.start_FunctionCall(child)
                except:
                    continue

        for expression in string.expressions:

            if is_identifier(expression):
                self.start_Identifier(expression)
            elif isinstance(expression, ArrayAccess):
                if isinstance(expression.children[0], Identifier):
                    self.start_Identifier(expression.children[0])
                resolve_arguments(expression)
            elif is_member_access(expression):

                self.end_MemberAccess(expression)

                instance = expression.get_expression()
                if is_identifier(instance):
                    self.start_Identifier(instance)
                else:
                    while True:
                        if hasattr(instance, 'get_expression'):
                            instance2 = instance.get_expression()
                            if instance2 == instance:
                                break
                            instance = instance2
                            if is_identifier(instance):
                                self.start_Identifier(instance)
                        else:
                            break

                member = expression.get_member()
                if is_identifier(member):
                    self.start_Identifier(member)

            elif is_method_call(expression):
                self.end_MethodCall(expression)

                if expression.get_resolution():
                    resolve_arguments(expression)

    def start_Instantiation(self, _ast):
        # Get import original class name
        for alias_class_name, original_class_name in self.resol_import.items():
            if alias_class_name == _ast.get_class_name():
                _ast.original_class_name = original_class_name
                break
        if not _ast.original_class_name:
            _ast.original_class_name = _ast.get_class_name()

        # we check if the Map is assigned to a variable
        parent = _ast.parent
        the_map = OrderedDict()
        while True:
            if isinstance(parent, MethodCall):
                if parent.get_name() == 'set':
                    try:
                        key = parent.get_argument(0).children[0].text[1:-1]
                        the_map[key] = parent.get_argument(1).children[0]
                    except:
                        pass
                parent = parent.parent
            elif isinstance(parent, VariableDeclaration):
                break
            else:
                return

        # we get the identifier to which the map was assigned
        for variable in parent.get_variables():
            assigned = variable.get_assigned_expression()

            if assigned:
                if assigned == _ast or _ast in get_descendants(assigned, Instantiation):
                    variable.assigned_map = the_map


    def add_caller_to_constr(self, caller, class_symbol):
        constr = class_symbol.get_symbol("constructor")
        if not constr:
            return
        constr.get_ast().add_caller(caller)

    def end_Instantiation(self, _ast):
        class_identifier = _ast.get_class_identifier()
        if isinstance(class_identifier, Identifier) and isinstance(class_identifier.get_resolution(), symbols.Class):
            _ast._resolution = class_identifier.get_resolution()
            self.add_caller_to_constr(_ast, class_identifier.get_resolution())

        if not '.' in _ast.get_fullname():
            return
        expr_identifier = None
        for child in _ast.get_children():
            if isinstance(child, Identifier) and _ast.get_fullname().startswith(child.get_name()):
                expr_identifier = child
                break

        if isinstance(expr_identifier.get_resolution(), symbols.SourceFile):
            _classes = expr_identifier.get_resolution().get_symbols_from_export(_ast.get_fullname().split('.')[1], [symbols.Class])
            if _classes:
                _ast._resolution = _classes[0]
            for _class in _classes:
                self.add_caller_to_constr(_ast, _class)

    def start_Decorator(self, _ast):
        clss = self.get_current_class()
        if clss:
            for decorator in clss.get_ast().get_decorators():
                if decorator.get_name() in ['Injectable', 'Component']:
                    clss.is_injectable = True

                # I would rather put the whole decorator as class initializer when there is a call inside the decorator but historically we but the parenthesis a class initializer so we keep that for consistency
                expression = decorator.get_expression()
                parenthesis = None
                for child in expression.get_children():
                    if isinstance(child, Parenthesis):
                        parenthesis = child
                        break
                if not parenthesis:
                    return

                descendants = get_descendants(parenthesis, [MethodCall, FunctionCall])
                if descendants:
                    clss.initializer_ast_fragments.append(parenthesis)

    def start_Field(self, _ast):
        clss = self.get_current_class()
        if clss:
            clss.initializer_ast_fragments.append(_ast)
            context = self.get_current_context()
            identifier = _ast.get_identifier()
            context.declare_member(identifier.get_name(), identifier)
            _ast.parent_symbol = clss

    def end_Assignment(self, assignment):
        identifier = assignment.get_left_expression()
        if isinstance(identifier, Identifier) and not identifier.get_resolution() and not isinstance(assignment.parent, Field):
            context = self.get_current_context()
            context.declare_variable(identifier.get_name(), identifier)
        elif isinstance(identifier, MemberAccess):
            self.handle_map_assignment(assignment)
        if isinstance(assignment.get_left_expression(), MemberAccess) and isinstance(
                assignment.get_left_expression().get_expression(),
                Identifier) and assignment.get_left_expression().get_expression().get_name() == 'window':
            _file = self.get_current_module()
            program = _file.get_program()
            key = assignment.get_left_expression().get_name()
            if key not in program.window_object:
                program.window_object[key] = [[assignment.get_right_expression(), _file.get_path()]]
            else:
                program.window_object[key].append([assignment.get_right_expression(), _file.get_path()])


    def start_Import(self, _ast):
        """
        Handle import original name if defined with and without alias
        """
        imported_elements = _ast.get_imported_elements()
        for imported_element in imported_elements:
            alias_name = imported_element.get_alias()
            original_name = imported_element.get_element()
            if alias_name:
                self.imported_names.append(alias_name.get_name())
                self.resol_import[alias_name.get_name()] = original_name.get_name()
            else:
                self.imported_names.append(original_name.get_name())
                self.resol_import[original_name.get_name()] = original_name.get_name()


    def start_VariableDeclaration(self, declaration):

        identifiers = declaration.get_variables()
        for identifier in identifiers:
            if not isinstance(identifier, Identifier):
                continue
            # this is for destructuring see test_parser.py class TestVariableDeclarationWithDestructuring

            if isinstance(identifier.parent, Bracket) and isinstance(identifier.parent.parent, VariableDeclaration):
                assigned_value = declaration.get_assigned_value(identifier.parent)
                if assigned_value:
                    identifier.resolve_to(assigned_value)

            if isinstance(identifier.parent, (CurlyBracket, ObjectCurlyBracket)):
                fake_member_access = identifier.get_resolution()
                if fake_member_access:
                    assigned_value = declaration.get_assigned_value(identifier.parent)
                    if assigned_value:
                        fake_member_access.get_expression().resolve_to(assigned_value)
            if isinstance(identifier.get_assigned_expression(), FunctionCall) and identifier.get_assigned_expression().get_name()=='require':
                imported_symbols = self.module.find_local_symbols(identifier.get_text(), [symbols.NodeExport, symbols.ExportedVariable])
                if imported_symbols:
                    context = self.get_current_context()
                    context.declare_variable(identifier.get_text(), imported_symbols[0])
                    return
            if identifier:
                context = self.get_current_context()
                context.declare_variable(identifier.get_text(), identifier, from_var_decl=True, declaration=declaration)


    def start_Enum(self, _ast):
        context= self.get_current_context()
        context.declare_variable(_ast.get_name(), _ast)

    def start_Parameter(self, parameter):
        context = self.get_current_context()
        identifier = parameter.get_identifier()
        if identifier:
            identifier_name = identifier.get_text()
            if identifier_name.endswith('?'):
                identifier_name = identifier_name[:-1]
            context.declare_variable(identifier_name, identifier)
        if isinstance(parameter.children[0], ObjectCurlyBracket):
            obj_c = parameter.children[0]
            for key_id in obj_c.get_key_identifiers():
                context.declare_variable(key_id.get_name(), key_id)


    def start_FunctionCall(self, f_c):
        f_c.parent_symbol = self.get_current_callable()
        name = f_c.get_name()

        # Get import original name
        for alias_name, original_name in self.resol_import.items():
            if alias_name == name:
                f_c.original_name = original_name
                break
        if not f_c.original_name:
            f_c.original_name = name

        context = self.get_current_context()
        resolution = context.resolve_variable(f_c.get_name(), [symbols.Function, symbols.NodeExport, symbols.ExportedVariable, Identifier])
        if isinstance(resolution, symbols.NodeExport):
            if '<SingleExport>' in resolution.symbols:
                resolution = resolution.symbols['<SingleExport>'][0]
            else:
                return

        if resolution:
            f_c.declaration = resolution
            if isinstance(resolution, symbols.Function):
                resolution.get_ast().add_caller(f_c)

        if hasattr(f_c, 'declaration') and isinstance(f_c.declaration, Identifier) and hasattr(f_c.declaration, 'possible_values'):
            for p_v in f_c.declaration.possible_values:
                if hasattr(p_v, 'symbol'):
                    p_v = p_v.symbol
                if isinstance(p_v, symbols.Function):
                    if not p_v in  f_c._resolutions:
                        f_c._resolutions.append(p_v)
                        p_v.get_ast().add_caller(f_c)

        if f_c.get_name() == 'super':
            _class = self.get_current_class()
            if _class:
                # @todo: what happens if function call
                # inside class (static) code?
                method = self._get_current_symbol()

                # the current symbol may be a function within method:
                # it can then access the symbols of that method
                while isinstance(method, symbols.Function):
                    method = method.get_parent_symbol()

                resolutions = _class.find_method(method.get_name(), with_super=True)
                if resolutions:
                    f_c._resolutions = resolutions
                    for resolution in resolutions:
                        resolution.get_ast().add_caller(f_c)
                    return

    def end_FunctionCall(self, f_c):
        if f_c.get_original_name() == 'mapStores':
            for arg in f_c.get_arguments():

                if not isinstance(arg.get_identifier(), Identifier) or not arg.get_resolution():
                    continue

                self.pinia_mapped_stores[arg.get_identifier().get_name()] = arg.get_resolution()

    def handle_map_assignment(self, assignment: Assignment):
        m_a = assignment.get_left_expression()
        expr = m_a.get_expression()
        if not hasattr(expr, 'get_resolution'):
            return
        resol = expr.get_resolution()

        if not resol:
            return

        if not hasattr(resol, "possible_map_values"):
            resol.possible_map_values = OrderedDict()

        if not m_a.get_name() in resol.possible_map_values.keys():
            resol.possible_map_values[m_a.get_name()] = [assignment.get_right_expression()]
        else:
            resol.possible_map_values[m_a.get_name()].append(assignment.get_right_expression())


    def check_if_identifier_is_injected(self, identifier):
        if not self.get_current_callable() or not self.get_current_callable().get_name() == 'constructor':
            return

        if not hasattr(self.get_current_class(), 'is_injectable'):
            return

        try:
            _type = identifier.parent.get_variable_type().get_name()
        except:
            return
        progr = self.get_current_module().get_program()
        if _type in progr.angular_providers:
            matching_providers = progr.angular_providers[_type]
            the_provider = self.get_most_relevant_provider(matching_providers, progr)
            if not the_provider:
                return
            identifier.is_injected = True
            if the_provider.useValue:
                identifier.resolve_to(the_provider.useValue)
            elif the_provider._class:
                identifier.resolve_to(the_provider._class)

    def get_most_relevant_provider(self, providers, progr):
        if not providers:
            return []
        if len(providers) == 1:
            return providers[0]

        # if the source code is using node packages, we consider only the providers within the node package
        if progr.node_packages:
            current_node_package_name = self.get_current_module().get_node_package_name()
            if current_node_package_name:
                matching_providers = [m_p for m_p in providers if m_p.path.startswith(progr.node_packages[current_node_package_name].get_path())]

                if len(matching_providers) == 1:
                    return matching_providers[0]
                elif len(matching_providers) > 1:
                    closest_path = get_closest_path(self.get_current_module().get_path(),
                                                [prov.path for prov in matching_providers])
                    return [prov for prov in matching_providers if prov.path == closest_path][0]

            # we check if the class was imported in some other project
            if hasattr(self.get_current_class(), 'node_packages_using_it'):
                for node_package in self.get_current_class().node_packages_using_it:
                    try:
                        matching_providers = [m_p for m_p in providers if
                                          m_p.path.startswith(progr.node_packages[node_package].get_path())]
                    except KeyError:
                        continue

                    if len(matching_providers) == 1:
                        return matching_providers[0]
                    elif len(matching_providers) > 1:
                        closest_path = get_closest_path(self.get_current_module().get_path(),
                                                        [prov.path for prov in matching_providers])
                        return [prov for prov in matching_providers if prov.path == closest_path][0]

        #we just take the closest when no node packages are used or if no matching provider was found
        closest_path = get_closest_path(self.get_current_module().get_path(),
                                        [prov.path for prov in providers])
        return [prov for prov in providers if prov.path == closest_path][0]

    def start_Identifier(self, identifier):
        if isinstance(identifier.parent, FunctionCall):
            return

        if isinstance(identifier.parent, Parameter) and identifier.parent.get_identifier()==identifier:
            self.check_if_identifier_is_injected(identifier)
        if isinstance(identifier.parent, (MemberAccess, MethodCall)) and not identifier.parent.get_expression() == identifier:
            return
        if hasattr(identifier, 'declaration'):
            return


        if isinstance(identifier.parent, VariableDeclaration) and identifier in identifier.parent.get_variables():
            return


        name = identifier.get_name()
        for alias_name, original_name in self.resol_import.items():
            if alias_name == name:
                identifier.original_name = original_name
                break
        if not identifier.original_name:
            identifier.original_name = name
        context = self.get_current_context()
        if isinstance(identifier.parent, Instantiation):
            resolution = context.resolve_variable(identifier.get_name(), [symbols.Class])
            if not resolution:
                resolution = context.resolve_variable(identifier.get_name())
        elif isinstance(identifier.parent, Class) and identifier in identifier.parent.get_implements():
            resolution = context.resolve_variable(identifier.get_name(), [symbols.Interface])
            if not resolution:
                resolution = context.resolve_variable(identifier.get_name())
        else:
            resolution = context.resolve_variable(identifier.get_name())
        if not resolution:
            return

        # if isinstance(resolution, symbols.Field) and isinstance(identifier.parent, Assignment) and identifier.parent.get_operator() == '=' and identifier.parent.get_left_expression() == identifier and not isinstance(identifier.parent.parent, Field):
        if isinstance(identifier.parent, Assignment) and identifier.parent.get_operator() == '=' and identifier.parent.get_left_expression() == identifier and not isinstance(
                identifier.parent.parent, Field):

            if resolution != identifier:
                # we do not want to add the possible value if the resolution is in the current context (because the evaluation is made with the block
                if not resolution in context._Context__local_variables.values():
                    add_possible_value_to_resolution(resolution, identifier.parent.get_right_expression())
                else:
                    if not hasattr(resolution, "possible_values_within_block"):
                        resolution.possible_values_within_block = [identifier.parent.get_right_expression()]

                    else:
                        resolution.possible_values_within_block.append(identifier.parent.get_right_expression())

        if isinstance(resolution, symbols.Field) and resolution.get_ast().get_identifier() == identifier:
            return

        if resolution and resolution != identifier:
            identifier.declaration = resolution

    def end_MethodCall(self, m_c):
        super().end_MethodCall(m_c)

        if m_c.get_name() == 'set' and hasattr(m_c.get_expression(), 'get_resolution'):
            resol = m_c.get_expression().get_resolution()
            if hasattr(resol, 'assigned_map'):
                try:
                    resol.assigned_map[m_c.get_argument(0).children[0].text[1:-1]] = m_c.get_argument(1).children[0]
                except (AttributeError, IndexError, KeyError, TypeError):
                    pass


        # specific case of class loaded in a mongo schema
        # see test_model_with_methods in test_mongoose.py
        if not hasattr(m_c.get_expression(), 'get_resolution'):
            return
        expr_resol = m_c.get_expression().get_resolution()
        if isinstance(expr_resol, symbols.ExportedVariable):
            if hasattr(expr_resol.get_ast(), 'get_resolution'):
                expr_resol = expr_resol.get_ast().get_resolution()
        if not hasattr(expr_resol, 'get_assigned_expression'):
            return
        assigned = expr_resol.get_assigned_expression()
        if not hasattr(assigned, 'get_fullname') or not expr_resol.get_assigned_expression().get_fullname() == "mongoose.model":
            return
        parent = expr_resol.parent
        while not isinstance(parent, Root):
            if not hasattr(parent, 'parent'):
                return
            parent = parent.parent

        source_file = parent.module
        if not hasattr(source_file, 'symbols'):
            return
        for _, symbol in source_file.symbols.items():
            # note that we do not check that the class is actually loaded by the mongo schema
            # we take the first method matching the name so if there are several classes having the same method name, we would get a bad resolution
            if isinstance(symbol[0], symbols.Class):
                meth = symbol[0].get_method(m_c.get_name())
                if meth:
                    m_c._resolutions = [meth]
                    meth.get_ast().add_caller(m_c)
                    return


