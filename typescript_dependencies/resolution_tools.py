import traceback
from cast.analysers import log
from typescript_dependencies.symbols import Class as symbolClass, SourceFile as symbolSourceFile, Interface as symbolInterface
from collections import OrderedDict
from typescript_dependencies.typescript_parser.parser import IfThenElseBlock, Assignment, Import

class Context:
    """
    Resolution is done by escalating contexts.
    As soon as a resolution is found at a context level,
    the search ends.
    """

    def __init__(self, symbol, parent=None):
        """
        :param parent: parent context
        @type parent: Context
        """
        self.__current_symbol = symbol

        # parent context
        self.__parent = parent

        self.__local_variables = OrderedDict()
        self.__local_members = OrderedDict()

        self.__all_accessible_classes = []

        self.__symbols_by_name = OrderedDict()

        self.__imports_by_name = OrderedDict()

        self.complexity = 1

    def get_symbol(self):
        return self.__current_symbol

    def declare_variable(self, name, identifier, from_var_decl=False, declaration=None):
        """
        Declare a local variable

        if already declared, do not redeclare it.
        """
        if not name in self.__local_variables:
            self.__local_variables[name] = identifier
            return
        elif not from_var_decl:
            if isinstance(self.__local_variables[name], (symbolInterface, symbolClass)) and isinstance(identifier, (symbolInterface, symbolClass)):
                # we put the Class first because by default, the Class will be assigned
                if isinstance(identifier, symbolClass):
                    self.__local_variables[name] = [identifier,self.__local_variables[name]]
                else:
                    self.__local_variables[name] = [self.__local_variables[name], identifier]
            return

        if hasattr(declaration, 'parent') and isinstance(declaration.parent.parent, IfThenElseBlock):
            return
        # we have a redeclaration which is not in an IfThenElseBlock
        self.__local_variables[name] = identifier

    def declare_member(self, name, identifier):
        """
        Declare a local variable

        if already declared, do not redeclare it.
        """
        if not name in self.__local_members:
            self.__local_members[name] = identifier

    def resolve(self, name, kinds=None):
        """
        Resolves a name as a symbol of a type in @param kinds.

        :param name: str, named searched, can be qualified
        :param kinds: list of type, the searched types for symbols for example [Class], [Class, Function] etc...
        """
        if kinds is None:
            kinds = []

        # For the name such as a.b
        l_name = name.split('.')  # @todo: choose better identifier name

        if len(l_name) == 1:
            current_symbols = [self.__current_symbol]
        else:
            current_symbols = [self.__current_symbol]

            # if the variable is local
            if self.resolve_variable(l_name[0]):
                if not (isinstance(self.resolve_variable(l_name[0]).parent, Assignment) and
                        isinstance(self.resolve_variable(l_name[0]).parent.parent, Import)):
                    return []

            # Extracting symbols for left part of the name e.g. "a"
            for local_name in l_name[:-1]:

                next_symbols = []

                for current_symbol in current_symbols:
                    next_symbols += current_symbol.find_local_symbols(local_name, [symbolClass, symbolSourceFile])

                current_symbols = next_symbols

                if not current_symbols:
                    break

        # If the symbols are found then extract symbols for the right part e.g. "b"
        if current_symbols:
            results = []

            for current_symbol in current_symbols:

                results = results + current_symbol.find_local_symbols(l_name[-1], kinds)

                if not results and isinstance(current_symbol, symbolSourceFile):
                    if current_symbol not in [self.__current_symbol]:
                        # we check for alias exports : export {local_name as export_name};
                        for alias_export in current_symbol._alias_exports:
                            if l_name[-1] == alias_export.get_alias():
                                results = results + current_symbol.find_local_symbols(
                                    alias_export.get_element().get_name(), kinds)

            if results:
                return results

        # Searching in parent context, leads to recursion
        if self.__parent:
            return self.__parent.resolve(name, kinds)

    def resolve_variable(self, name, types=None):
        try:
            resol = self.__local_variables[name]
            if not isinstance(resol, list):
                resol = [resol]

            for res in resol:
                if not types or any([isinstance(res, t) for t in types]):
                    return res
        except:
            pass
        if self.__parent:
            return self.__parent.resolve_variable(name, types)
        return None

    def resolve_member(self, name):
        try:
            return self.__local_members[name]
        except:
            if self.__parent:
                return self.__parent.resolve_member(name)
            return None

    def resolve_as_import(self, name):

        if name in self.__imports_by_name:
            return True

        if self.__parent:
            self.__parent.resolve_as_import(name)

        return None

    def is_accessible(self, _class):
        """
        This method :
        > Returns True if class is a member of all_accessible_classes
        > Returns False otherwise
        > Uses recursion to check all the classes in parent context also

        @type _class : symbols.Class
        """
        accessible_classes = self.get_all_accessible_classes()
        if accessible_classes:
            if _class in accessible_classes:
                return True

        if self.__parent:
            return self.__parent.is_accessible(_class)

        return False

    def get_all_accessible_classes(self):
        """
        This method returns all the accessible classes
        in the module / sourcefile. It is very important,
        especially in case of inherited members

        @rtype all_accssible_classes: set
        """
        if not self.__all_accessible_classes:

            def add_class(result, _class):
                """
                This method adds a class and all its inheritence
                @type _class : symbols.Class

                Assumption:
                ============
                Only class will be checked for inheritance not interface

                Acceptable
                ==========
                Class implements interface (At present functionality such as
                find_method, get_inheritance exists only for Class

                Future
                ========
                Interface implements interface
                """
                if _class:
                    if not _class in result:
                        result.append(_class)  # Adding class to the set

                    if isinstance(_class, symbolClass):
                        # get_inheritances() returns list of Identifers

                        for inherited_element in _class.get_inheritances():
                            if not hasattr(inherited_element, "get_resolution"):
                                continue

                            # get_resolution() returns the symbol corresponding to the inherited element
                            parent = inherited_element.get_resolution()
                            if parent in result:
                                continue
                            add_class(result, parent)

            result = []

            # For all the classes in the current sourcefile / module
            if type(self.__current_symbol) == symbolSourceFile:

                # Iterate over the local symbols of the current module /file
                for _, local_symbol in self.__current_symbol.get_local_symbols().items():

                    for _class in local_symbol:

                        if type(_class) == symbolClass:
                            # Add the class
                            add_class(result, _class)

            self.__all_accessible_classes = result

        return self.__all_accessible_classes

    def increment_complexity(self):
        self.complexity += 1
