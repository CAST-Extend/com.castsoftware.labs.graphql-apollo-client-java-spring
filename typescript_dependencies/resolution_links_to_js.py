import os.path
import typescript_dependencies.symbols as symbols
import difflib
import traceback

from cast.analysers import log
from typescript_dependencies.typescript_parser.parser import Class, Method, Function, Identifier, Instantiation, MemberAccess, StringTemplate


js_extensions = ['.js', '.jsx', '.mjs', '.jsm', '.cjs']
css_extensions = ['.css', '.scss', '.less', '.sass', '.styl', '.stylus', '.pcss', '.postcss', '.cssm']
css_extensions_tuple = tuple(css_extensions)


def is_javascript_function(ast):
    try:
        return ast.is_function()
    except:
        return False


def is_javascript_class(ast):
    try:
        return ast.is_class()
    except:
        return False


def is_javascript_identifier(ast):
    try:
        return ast.is_identifier()
    except:
        return False


def get_module_exports(js_content, name):
    try:
        return js_content.get_module_exports(name)
    except:
        return None

def signature_matching(a, b):
    return True


def get_signature_for_js_callable(a):
    return None

def get_nearer_pathes(currentPath, pathes):
    commonRootPath = ''
    calleeCandidate = []
    for path in pathes:
        calleePath = os.path.normpath(path)
        matches = difflib.SequenceMatcher(None, currentPath, calleePath).get_matching_blocks()
        for firstMatch in matches:
            if firstMatch.a == 0 and firstMatch.b == 0:
                rootPath = calleePath[:firstMatch.size - 1]
                if len(rootPath) > len(commonRootPath):
                    commonRootPath = rootPath
                    calleeCandidate = [path]
                elif len(rootPath) == len(commonRootPath):
                    calleeCandidate.append(path)
            break
    return calleeCandidate

class ExternalObject:
    def __init__(self, original_object):
        self.original_object = original_object
        self.parent = None

    def __eq__(self, other):
        if other == self.original_object:
            return True
        if hasattr(other, 'original_object') and other.original_object == self.original_object:
            return True
        return False

    def get_parent_symbol(self):
        return self.parent

    def get_name(self):
        return self.original_object.get_name()

    def get_file(self):
        return self.original_object.get_file()

    def get_ast(self):
        return self.original_object


class ExternalClass(ExternalObject, Class):
    def __init__(self, original_class):
        ExternalObject.__init__(self, original_class)
        Class.__init__(self)

    def get_kb_object(self):
        return self.original_object.get_kb_object()

    def _get_current_symbol(self):
        return self.original_object

    def is_external_class(self):
        return True


class ExternalMethod(ExternalObject, Method):
    def __init__(self, original_method):
        ExternalObject.__init__(self, original_method)
        Method.__init__(self)

    def get_kb_object(self):
        return self.original_object.get_kb_object()

    def _get_current_symbol(self):
        return self.original_object

    def add_call(self, call):
        self.original_object.add_call(call)

    def get_calls(self):
        return self.original_object.get_calls()


class ExternalFunction(ExternalObject, Function):
    def __init__(self, original_function):
        ExternalObject.__init__(self, original_function)
        Function.__init__(self)

    def get_kb_object(self):
        return self.original_object.get_kb_object()

    def _get_current_symbol(self):
        return self.original_object

    def add_call(self, call):
        self.original_object.add_call(call)

    def get_calls(self):
        return self.original_object.get_calls()


class ExternalIdentifier(ExternalObject, Identifier):
    def __init__(self, original_identifier):
        ExternalObject.__init__(self, original_identifier)
        Identifier.__init__(self, original_identifier.tokens[0])


class ResolutionLinksToJSInterpreter:
    """
    Resolve the ast of a module.
    """

    def __init__(self, module, evaluation_tool, javascript_resolution_tool):
        """
        @type module: symbols.SourceFile
        @type js_global_functions: Dict of GlobalFunction & GlobalClass
        """

        self.__module = module
        self.evaluation_tool = evaluation_tool
        self.javascript_resolution_tool = javascript_resolution_tool
        self.some_resolution_to_js = False
        if not javascript_resolution_tool:
            return

        # Typescript name imports
        self.__name_imports = {}
        self.__name_star_imports = {}
        self.__name_default_imports = {}
        self.requires = {}

        for _import in module.get_imports():
            resol = _import.get_resolution()
            if not resol:
                if _import.module:
                    try:
                        resol = self.javascript_resolution_tool.get_imported_js_content(module.get_file(), _import.module.get_name())
                    except:
                        log.debug(traceback.format_exc())
                        resol = None
            if resol:
                self.some_resolution_to_js = True
            if _import.get_star_alias():
                star_alias = _import.get_star_alias().get_name()
                self.__name_star_imports[star_alias] = (_import.get_star_alias(), resol, star_alias)
            else:
                imported_elements = _import.get_imported_elements()
                if imported_elements:
                    for imported_element in imported_elements:
                        if imported_element.alias:
                            try:
                                self.__name_imports[imported_element.alias.get_name()] = (imported_element, resol, imported_element.element.get_name())
                            except:
                                pass
                        else:
                            self.__name_imports[imported_element.element.get_name()] = (imported_element, resol, imported_element.element.get_name())
                else:
                    name = _import.get_local_name_of_default_imported_variable()
                    if name:
                        self.__name_default_imports[name] = (_import, resol, name)

    def start_FunctionCall(self, _ast):
        """
        @type _ast: typescript_parser.parser.FunctionCall
        """

        if not self.javascript_resolution_tool:
            return

        # if resolutions are found in ts side, do not need to create link to js
        if _ast.get_resolutions():
            return

        name = _ast.get_name()

        if name == "require":
            arguments = _ast.get_arguments()
            if not len(arguments) == 1:
                return
            arg = arguments[0]
            arg_children = list(arg.get_children())

            if len(arg_children) != 1:
                return

            if isinstance(arg_children[0], StringTemplate):
                imported_module_path = self.evaluation_tool.evaluate(arg_children[0], with_trace=False, max_counter=100)[0]
            elif str(arg_children[0].get_type()) == "Token.Literal.String":
                imported_module_path = arg_children[0].text[1:-1]
            else:
                imported_module_path = ''
            if imported_module_path:
                try:
                    resol = self.javascript_resolution_tool.get_imported_js_content(self.__module.get_file(), imported_module_path)
                except:
                    log.debug(traceback.format_exc())
                    resol = None
                if resol:
                    self.some_resolution_to_js = True
                    try:
                        var_name = _ast.parent.get_name()
                        self.requires[var_name] = resol
                    except:
                        pass
            return

        if not self.some_resolution_to_js:
            return
        funcs = self.get_functions(name)

        for func in funcs:
            _ast._resolutions.append(ExternalFunction(func))
            _ast._resolutions[-1].add_call(_ast)

    def start_MethodCall(self, _ast):
        """
        @type _ast: typescript_parser.parser.MethodCall
        """
        if not self.some_resolution_to_js:
            return

        if not self.javascript_resolution_tool:
            return
        # may be also a function call when name contains a dot
        # if resolutions are found in ts side, do not need to create link to js
        if _ast.get_resolutions():
            return

        method_name = _ast.get_name()

        class_name = None
        if _ast.get_expression() == "this":
            parent = _ast.parent
            while True:
                if isinstance(parent, Class):
                    break
                try:
                    parent = parent.parent
                except (AttributeError, TypeError):
                    break

            if parent:
                for expr in parent.get_extends():
                    if isinstance(expr, Instantiation):
                        # class_name = expr.get_original_class_name()
                        class_name = expr.get_class_name()
                    elif isinstance(expr, Identifier):
                        # class_name = expr.get_original_name()
                        class_name = expr.get_name()

        elif self.evaluation_tool:
            for expr in self.evaluation_tool.evaluate(_ast.get_expression(), with_trace=False, ast_node_expected=True, max_counter=100):
                if isinstance(expr, Instantiation):
                    # class_name = expr.get_original_class_name()
                    # class_name = expr.get_class_name()
                    class_name = expr.get_fullname()
                elif isinstance(expr, Identifier):
                    # class_name = expr.get_original_name()
                    try:
                        class_name = expr.get_variable_type().get_name()
                    except:
                        class_name = expr.get_name()

        if not class_name and hasattr(_ast.get_expression(), 'get_resolution'):
            if isinstance(_ast.get_expression().get_resolution(), symbols.Field):
                try:
                    class_name = _ast.get_expression().get_resolution().get_variable_type().get_identifier().get_name()
                except AttributeError:
                    pass

        if not class_name:
            classes = []
        else:
            classes = self.get_classes(class_name)

        if classes:
            for _class in classes:
                methods = _class.get_methods(method_name)
                for meth in methods:
                    _ast._resolutions.append(ExternalMethod(meth))
                    _ast._resolutions[-1].add_call(_ast)
        else:
            funcname = _ast.get_fullname()
            if '.' in funcname:
                prefix = funcname[:funcname.find('.')]
                if prefix in self.__name_star_imports or prefix in self.requires:
                    functions = self.get_functions(funcname)
                    for func in functions:
                        _ast._resolutions.append(ExternalFunction(func))
                        _ast._resolutions[-1].add_call(_ast)

    def start_Instantiation(self, _ast):
        """
        @type _ast: typescript_parser.parser.Instantiation
        """
        if not self.some_resolution_to_js:
            return
        if not self.javascript_resolution_tool:
            return
        # if resolutions are found in ts side, do not need to create link to js
        if _ast.get_resolution():
            return

        # class_name = _ast.get_class_name()
        class_name = _ast.get_fullname()

        if not class_name:
            return

        classes = self.get_classes(class_name)

        for _class in classes:
            methods = _class.get_methods(class_name)
            if not methods:
                _ast._resolution = ExternalClass(_class)
                break
            for meth in methods:
                _ast._resolution = ExternalMethod(meth)
                _ast._resolution.add_call(_ast)
                break

    def start_MemberAccess(self, _ast):
        """
        @type _ast: typescript_parser.parser.MemberAccess
        """
        if not self.some_resolution_to_js:
            return
        if not self.javascript_resolution_tool:
            return
        # if resolutions are found in ts side, do not need to create link to js
        if _ast.get_resolutions():
            return

        # name = _ast.get_original_name()
        fullname = _ast.get_fullname()
        if '.' not in fullname:
            return

        functions = self.get_functions(fullname)
        if functions:
            for func in functions:
                _ast._resolutions.append(ExternalFunction(func))
                _ast._resolutions[-1].add_call(_ast)
            return

        variables = self.get_variables(fullname)

        if variables:
            for _variable in variables:
                _ast._resolutions.append(ExternalIdentifier(_variable))
            return

        try:
            class_name = _ast.get_expression().get_name()
        except:
            class_name = ''
        if not class_name:
            classes = []
        else:
            classes = self.get_classes(class_name)

        if classes:
            for _class in classes:
                method_name = _ast.get_member().get_name()
                methods = _class.get_methods(method_name)
                for meth in methods:
                    _ast._resolutions.append(ExternalMethod(meth))
                    _ast._resolutions[-1].add_call(_ast)
        else:
            funcname = _ast.get_fullname()
            if '.' in funcname:
                prefix = funcname[:funcname.find('.')]
                if prefix in self.__name_star_imports or prefix in self.requires:
                    functions = self.get_functions(funcname)
                    for func in functions:
                        _ast._resolutions.append(ExternalMethod(func))
                        _ast._resolutions[-1].add_call(_ast)

    def start_Identifier(self, _ast):
        """
        @type _ast: typescript_parser.parser.Identifier
        """
        if not self.some_resolution_to_js:
            return
        if not self.javascript_resolution_tool:
            return
        # if resolutions are found in ts side, do not need to create link to js
        if _ast.get_resolution():
            return
        if _ast.parent and type(_ast.parent) is MemberAccess:
            return

        name = _ast.get_name()
        if not name:
            return

        classes = self.get_classes(name)
        if classes:
            for _class in classes:
                if type(_class).__name__ == 'ExternalClass':
                    try:
                        _ast.resolved_as = _class.tokens[0]
                    except:
                        pass
                else:
                    _ast.resolved_as = ExternalClass(_class)
            return

        functions = self.get_functions(name)
        if functions:
            for _function in functions:
                _ast.resolved_as = ExternalFunction(_function)
                _ast.resolved_as.add_call(_ast)
            return

        variables = self.get_variables(name)

        for _variable in variables:
            _ast.resolved_as = ExternalIdentifier(_variable)
            break

    def start_Class(self, _ast):
        """
        @type _ast: typescript_parser.parser.Class
        """
        if not self.some_resolution_to_js:
            return
        if not self.javascript_resolution_tool:
            return
        inherited_classes = _ast.get_direct_inheritances()
        if not inherited_classes:
            return

        for inherited_class in inherited_classes:
            resol = inherited_class.get_resolution()
            if resol:
                continue

            class_name = inherited_class.get_name()

            classes = self.get_classes(class_name)
            for _class in classes:
                inherited_class.resolved_as = ExternalClass(_class)

    def get_functions(self, name):

        if '.' in name:
            prefix = name[:name.find('.')]
            real_name = name[name.find('.') + 1:]
        else:
            prefix = name
            real_name = name

        if self.requires and prefix in self.requires:
            js_content = self.requires[prefix]
            result = get_module_exports(js_content, real_name)
            if is_javascript_function(result):
                return [result]
            return []

        # check function call must be from imports
        if prefix not in self.__name_imports and prefix not in self.__name_default_imports and prefix not in self.__name_star_imports:
            return []

        if prefix in self.__name_imports:
            import_source_resol = self.__name_imports[prefix][1]
            if not import_source_resol:
                return []
            real_name = self.__name_imports[prefix][2]
            exported_default = None
        elif prefix in self.__name_star_imports:
            import_source_resol = self.__name_star_imports[prefix][1]
            if not import_source_resol:
                return []
            real_name = name[name.find('.') + 1:]
            exported_default = None
        else:
            import_source_resol = self.__name_default_imports[prefix][1]
            if not import_source_resol:
                return []
            real_name = self.__name_default_imports[prefix][2]
            try:
                exported_default = import_source_resol.get_exported_default()
            except:
                return []

        javascript_resolution_context = self.javascript_resolution_tool.create_jscontent_context(import_source_resol)
        if javascript_resolution_context:
            if exported_default:
                if is_javascript_function(exported_default):
                    funcs = [exported_default]
                else:
                    funcs = []
                    try:
                        for resol in exported_default.get_resolutions():
                            if is_javascript_function(resol.callee):
                                funcs.append(resol.callee)
                    except:
                        pass
                return funcs
            else:
                return javascript_resolution_context.get_functions(real_name)
        return []

    def get_classes(self, name):

        if '.' in name:
            prefix = name[:name.find('.')]
            real_name = name[name.find('.') + 1:]
        else:
            prefix = name
            real_name = name

        if self.requires and prefix in self.requires:
            js_content = self.requires[prefix]
            result = get_module_exports(js_content, real_name)
            if is_javascript_class(result):
                return [result]
            return []

        exported_default = None
        real_name = name
        if prefix in self.__name_star_imports:
            import_source_resol = self.__name_star_imports[prefix][1]
            real_name = name[name.find('.') + 1:]
        else:
            if prefix not in self.__name_imports:
                if prefix in self.__name_default_imports:
                    import_source_resol = self.__name_default_imports[prefix][1]
                    try:
                        exported_default = import_source_resol.get_exported_default()
                    except:
                        return []
                else:
                    return []
            else:
                import_source_resol = self.__name_imports[prefix][1]
                real_name = self.__name_imports[prefix][2]

        if not import_source_resol:
            return []

        javascript_resolution_context = self.javascript_resolution_tool.create_jscontent_context(import_source_resol)
        if javascript_resolution_context:
            if exported_default:
                if is_javascript_class(exported_default):
                    classes = [exported_default]
                else:
                    classes = []
                    try:
                        for resol in exported_default.get_resolutions():
                            if is_javascript_class(resol.callee):
                                classes.append(resol.callee)
                    except:
                        pass
                return classes
            else:
                return javascript_resolution_context.get_classes(real_name)
        return []

    def get_variables(self, name):

        if '.' in name:
            prefix = name[:name.find('.')]
            real_name = name[name.find('.') + 1:]
        else:
            prefix = name
            real_name = name

        if self.requires and prefix in self.requires:
            js_content = self.requires[prefix]
            result = get_module_exports(js_content, real_name)
            if is_javascript_identifier(result):
                return [result]
            return []

        # check function call must be from imports
        exported_default = None
        if prefix not in self.__name_imports:
            if prefix in self.__name_star_imports:
                import_source_resol = self.__name_star_imports[prefix][1]
            elif prefix in self.__name_default_imports:
                import_source_resol = self.__name_default_imports[prefix][1]
                try:
                    exported_default = import_source_resol.get_exported_default()
                except:
                    pass
            else:
                return []
        else:
            import_source_resol = self.__name_imports[prefix][1]
            real_name = self.__name_imports[prefix][2]

        if not import_source_resol:
            return []

        javascript_resolution_context = self.javascript_resolution_tool.create_jscontent_context(import_source_resol)
        if javascript_resolution_context:
            if exported_default:
                if is_javascript_identifier(exported_default):
                    variables = [exported_default]
                else:
                    variables = []
                    try:
                        for resol in exported_default.get_resolutions():
                            if is_javascript_identifier(resol.callee):
                                variables.append(resol.callee)
                    except:
                        pass
                return variables
            else:
                return javascript_resolution_context.get_variables(real_name)
        return []
