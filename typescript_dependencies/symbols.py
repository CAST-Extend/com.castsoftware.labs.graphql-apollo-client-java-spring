"""
Symbols for typescript
"""
try:
    import cast_upgrade_1_6_17  # @UnusedImport
except ImportError:
    try:
        import cast_upgrade_1_6_23  # @UnusedImport - fallback to newer version
    except ImportError:
        pass  # Not critical for tests
from collections import OrderedDict, defaultdict
import os
from os.path import normpath

from typescript_dependencies.aws_common_tools import arn2name4lambda
from typescript_dependencies.common_tools import DefaultOrderedDict, clean_url, get_type_id_from_type_name
from typescript_dependencies.filtering import get_closest_path
from typescript_dependencies.typescript_parser.light_parser import Node, TokenIterator, Walker, Token
from typescript_dependencies.typescript_parser.parser import light_parse, parse, is_namespace, is_class, is_function, is_method, \
    is_interface, is_import, is_re_export, is_export, is_identifier, is_function_call, \
    is_variable_declaration, Root, Identifier, \
    StringTemplate, ArrowExpression, _GenericCall, Function as parser_Function, \
    Method as parser_Method, FunctionType, CurlyBracket, \
    Parenthesis, Bracket, set_linefeed_as_whitespace, HtmlTag, \
    SelfClosingHtmlTag, FunctionCall, OpeningHtmlTag, substitute, MethodCall, \
    ObjectCurlyBracket, get_bookmark_from_ast, Return, VariableDeclaration, Type as parser_Type, BinaryOperation, \
    is_field, Assignment, MemberAccess, Declare, ConstructorField, _GenericCall, Instantiation, \
    is_linefeed_or_semicolon, TSType, is_function_type, InterfaceMethod
try:
    from clean_up_project_name import get_project_fullname
except ImportError:
    def get_project_fullname(name):
        return name  # Fallback implementation
from cast.application import open_source_file  # @UnresolvedImport
from cast.analysers import CustomObject, Bookmark, log, create_link, get_cast_version, external_link,\
    Object as cast_analyzers_object
import statistics
import re
from distutils.version import StrictVersion
import traceback
from pygments.token import Token as PygmentToken, Comment

LineFeed = PygmentToken.LineFeed


def get_descendants(node, kind):
    """
    Get all descendants of a node of a certain kind
    """
    if not isinstance(kind, list):
        kind = [kind]
    result = []
    for sub_node in node.get_sub_nodes():
        if type(sub_node) in kind:
            result.append(sub_node)
        
        result += get_descendants(sub_node, kind)
    
    return result


class DataSensitivitySettings:

    gdpr = OrderedDict()
    pci = OrderedDict()
    custom = OrderedDict()

    @classmethod
    def reset(cls):
        cls.gdpr = OrderedDict()
        cls.pci = OrderedDict()
        cls.custom = OrderedDict()


class SymbolTable:
    """
    Dictionary of symbols
    """
    
    def __init__(self):
        
        # defined symbols
        self.symbols = OrderedDict()
    
    def add_symbol(self, name, symbol):
        """
        Register a symbol
        """
        # we should not add its own symbol to a symbol
        # this could happen when a module imports a library which has the same name as the module
        # (seen in git project typescript-node-express-realworld-example-app)
        # this would raise recursion loop issue
        if symbol == self:
            return

        try:
            if symbol not in self.symbols[name]:
                self.symbols[name].append(symbol)
        except:
            self.symbols[name] = [symbol]

    def get_local_symbols(self):
        """
        Access to all symbols as a dict(list)
        """
        return self.symbols
    
    def get_all_symbols(self):
        """
        Access to all symbols as a list
        """
        import itertools
        
        return list(itertools.chain.from_iterable(self.symbols.values()))
    
    def find_local_symbols(self, name, types=None):
        """
        Search for a symbol of a given name with optional possible types
        """
        if not name:
            return []
        
        if name in self.symbols:
            symbols = self.symbols[name]
            
            if types:
                symbols_to_return = []
                # if the types have metamodel we use these
                type_metamodels = [_type.metamodel_type for _type in types if _type.metamodel_type is not None]
                # else we check the instance
                type_classes = [_type for _type in types if _type.metamodel_type is None]
                for symbol in symbols:
                    if (hasattr(symbol, "metamodel_type")
                            and symbol.metamodel_type
                            and symbol.metamodel_type in type_metamodels):
                        symbols_to_return.append(symbol)
                    elif any([isinstance(symbol, type_class) for type_class in type_classes]):
                        symbols_to_return.append(symbol)

                return symbols_to_return
            else:
                return symbols
        else:
            return []

    def find_exported_local_symbols(self, name, types=None):
        symbols = self.find_local_symbols(name, types)
        to_return = []
        for symbol in symbols:
            if hasattr(symbol, 'is_exported') and not symbol.is_exported:
                continue
            to_return.append(symbol)

        return to_return

    def print(self, ident=0):
        """
        Pretty print.
        """
        result = ' '*ident+'%s %s\n'%(type(self).__name__, self.get_name())
        for symbols in self.symbols.values():
            for symbol in symbols:
                result += symbol.print(ident+1)
        
        return result

def get_old_default_guid(fullname:str, metamodel_type:str, file):
    """
    @param fullname: fullname
    @param metamodel_type:
    @param file: the SourceFile
    @return: return the default guid !!! does not work when the fullname is not the concatenation of parent names
    """
    prefix = file.get_path()
    if fullname.startswith(prefix):
        fullname = fullname[len(prefix):]

    file_name = file.get_name()
    if file_name.endswith('.vue'):
        file_name = file_name.rstrip('.vue')
    elif file_name.endswith('.html'):
        file_name = file_name.rstrip('.html')
    return get_type_id_from_type_name(metamodel_type) + '?[' + file.get_path() + '].' + file_name + fullname


class Symbol(SymbolTable):
    """
    base class for symbols
    """
    
    def __init__(self, name, parent=None):
        SymbolTable.__init__(self)
        self.__name = name
        self.__parent = parent
        
        # for saving
        self.__kb_symbol = None
        self.subObjectsGuids = {}
        self.old_subObjectsGuids = {}
        # when there is only one ast
        self._ast = None
        # when the object has ast fragments (case of namespace, class interface)
        self._ast_fragments = []
        
        self.__start_line = None
        # constructed latter during parsing
        self.__imports = []
        self.__re_exports = []
        self._statements = []
        
        self._line_count = None
        self._body_comments_line_count = None
        self._body_comments = ''
        self._header_comments_line_count = None
        self._header_comments = ''
        
        # violations for quality rules property name --> ast's
        self.__violations = defaultdict(list)
        
        self.__violations_in_html = defaultdict(list)
        # idem
        self.__properties = {}
        
        self._web_services = []
        self._web_operations = []
        
        # all node symbols will be saved by nodejs extension (they must be stored at module level)
        self.node_symbols = OrderedDict()
        
        self.react_symbols = OrderedDict()
        
        self._alias_exports = []
        self._exported_elements = []
        self.positions = []
        self.node_stack = []
        self._database_queries = []
        self.attribute_functions = OrderedDict()
        self.base_guid_by_name_and_metamodel_type = OrderedDict()
        self.guid_index_by_name_and_metamodel_type = OrderedDict()

        self.old_anonymous_functions = OrderedDict()  # we changed the naming for arrow expression. We need to keep track of the old name for proper migration

    def get_begin_line_without_comment(self):
        if self.__start_line:
            default_return = self.__start_line
        else:
            default_return = -1
        if isinstance(self.get_ast(), list):
            _ast = self.get_ast()[0]
        else:
            _ast = self.get_ast()

        if not hasattr(_ast, 'get_children'):
            return default_return
        try:
            return next(_ast.get_children()).get_begin_line()
        except:
            return default_return

    def handle_exports(self, node, symbol):
        symbol.is_exported = node.is_exported
        symbol.is_default_export = node.is_default_export
        if node.is_require_export:
            symbol.get_root_symbol()._require_export_symbol_name = node.get_name()

    def get_sub_nodes(self, _type=None):
        v = []
        if not _type:
            _type = Node
        for child in self._ast:
            if isinstance(child, _type):
                v.append(child)
        return (child for child in v)

    def get_parent_symbol(self):
        
        return self.__parent
    
    def get_root_symbol(self):
        
        if self.__parent and hasattr(self.__parent, 'get_root_symbol'):
            return self.__parent.get_root_symbol()
        
        return self
    
    def get_kb_object(self):
        
        return self.__kb_symbol

    def set_kb_object(self, kb_object):

        self.__kb_symbol = kb_object

    def get_old_fullname(self):
        if isinstance(self, SourceFile):
            return self.get_fullname()  # there was not change for file fullname
        if not self.__parent or not hasattr(self.__parent, 'get_old_fullname'):
            return self.get_old_name()

        return self.__parent.get_old_fullname() + '.' + self.get_old_name()


    def get_old_name(self):
        if hasattr(self, 'old_name'):
            return self.old_name
        return self.get_name()

    def get_name(self):
        """
        Return name
        """
        return self.__name
    
    def get_fullname(self):
        """
        Full name
        """
        # Temporary Fix
        if self.__name:
            if self.__parent and self.__name:
                result = self.__parent.get_fullname()+"."+self.__name
            else:
                # module
                result = os.path.splitext(self.__name)[0]

            return result

    def create_bookmark(self, file):
        return get_bookmark_from_ast(self.get_ast())

    def get_ast(self):
        """
        Access to AST of symbol.
        
        Only for objects that have exactly one ast
        Other have several ast fragments
        """
        return self._ast
    
    def print_tree(self, depth=0):
        """
        Print as a tree.
        """
        indent = ' '*(depth*2)
        print(indent, self.__class__.__name__)
        
        for token in self._ast:
            token.print_tree(depth+1)
    
    def get_symbol(self, name, check_for_alias_exports=False, _type=None):
        """
        Return the symbol with given name if exist
        
        A symbol may have been exported with an alias using : 
        export {local_name as alias_name};
        in that case, with check_for_alias_exports=True
        get_symbol("alias_name") will return the symbol with name "local_name"
        """
        if check_for_alias_exports:
            _locals = self.find_exported_local_symbols(name)
        else:
            _locals = self.find_local_symbols(name)
        if len(_locals) == 1 and not _type:
            return _locals[0]
        else:
            _type_loc = _type
            if not _type_loc:
                _type_loc = (Class, Function, Method, SourceFile)
            for _local in _locals:
                if isinstance(_local, _type_loc):
                    return _local
        
        if check_for_alias_exports:
            for alias_export in self._alias_exports:
                if name == alias_export.get_alias():
                    _locals = self.find_local_symbols(alias_export.get_element().get_name())
                    if len(_locals) == 1 and not _type:
                        return _locals[0]
                    else:
                        if not _type:
                            _type = Class
                        for _local in _locals:
                            if isinstance(_local, _type):
                                return _local

        _locals = self.find_local_symbols(name)
        if len(_locals) == 1 and not _type:
            return _locals[0]
        else:
            _type_loc = _type
            if not _type_loc:
                _type_loc = (Class, Function, Method, SourceFile)
            for _local in _locals:
                if isinstance(_local, _type_loc):
                    return _local
        return None
    
    def _get_typed_symbol(self, name, begin_line, _type):
        try:
            _locals = self.find_local_symbols(name, [_type])
            if len(_locals) == 1:
                return _locals[0]
            if locals:
                for local in _locals:
                    if local.get_begin_line_without_comment() == begin_line or local.__start_line == begin_line:
                        return local
        except:
            pass
        
        return None

    def is_default_variable_export(self, export_ast):
        if not is_export(export_ast):
            return False

        if not export_ast.is_default_export:
            return False

        identifier = export_ast.get_exported_elements()[0].get_element()
        if not isinstance(identifier, Identifier):
            return True

        # we export an exisiting symbol (a function, a class or a method)
        if self.get_symbol(identifier.get_name()):
            return False

        return True

    def get_class(self, name, begin_line=None):
        """
        Return a class by name.
        From the classes inside that symbol.
        """
        return self._get_typed_symbol(name, begin_line, Class)
    
    def get_exported_variable(self, name, begin_line=None):
        """
        Return a class by name.
        From the classes inside that symbol.
        """
        return self._get_typed_symbol(name, begin_line, ExportedVariable)
    
    def get_function(self, name, begin_line=None):
        """
        Return a function by name
        From the functions inside that symbol.
        """
        
        return self._get_typed_symbol(name, begin_line, Function)

    def get_old_anonymous_functions(self, name):
        if name in self.old_anonymous_functions:
            return  self.old_anonymous_functions[name]

    def get_method_for_parsing(self, name, begin_line=None):
        return self._get_typed_symbol(name, begin_line, Method)

    def get_method(self, name, begin_line=None, setter=None, getter=None):
        """
        Return a method by name
        From the method inside that symbol .
        begin_line use is incompatible with setter or getter use
        begin_line argument has been added for backward compatibility with vuesjs extension that use the get_method method that has now been replaced with the get_method_for_parsing method
        """
        if begin_line:
            return self.get_method_for_parsing(name, begin_line)

        if not name in self.symbols:
            return
        if setter:
            for symbol in self.symbols[name]:
                if not isinstance(symbol, Method):
                    continue
                if symbol.is_setter():
                    return symbol
            return

        if getter:
            for symbol in self.symbols[name]:
                if not isinstance(symbol, Method):
                    continue
                if symbol.is_getter():
                    return symbol
            return

        setter_symbol = None
        for symbol in self.symbols[name]:
            if not isinstance(symbol, Method):
                continue

            # if we have a getter and getters are not excluded from expected method we return it
            if symbol.is_getter():
                if getter is False:
                    continue
                else:
                    return symbol
            # if we have a setter and setters are not excluded from expected method we return it only if no other symbol is found
            elif symbol.is_setter():
                if setter is False:
                    continue
                else:
                    setter_symbol = symbol
                    continue
            else:
                return symbol

        return setter_symbol

    def get_namespace(self, name, begin_line=None):
        return self._get_typed_symbol(name, begin_line, Namespace)
    
    def get_interface(self, name, begin_line=None):
        return self._get_typed_symbol(name, begin_line, Interface)

    def get_field(self, name, begin_line=None):
        local_decl = self._get_typed_symbol(name, begin_line, Field)
        if local_decl:
            return local_decl

        for extended_class in self.get_inherited_classes_recursively():
            if not hasattr(extended_class, 'get_field'):
                continue
            decl = extended_class.get_field(name)
            if decl:
                return decl
        return

    def get_field_or_meth(self, name, setter=False, getter=None):
        # we first search for a method (when both a method and a field are defined with the same name (which is a very bad practice), the method seems to be taken
        meth = self.get_method(name, recursive=False, setter=setter, getter=getter)
        if meth:
            return meth

        # we then search for a field
        local_decl = self._get_typed_symbol(name, 0, Field)
        if local_decl:
            return local_decl

        for extended_class in self.get_inherited_classes_recursively():
            if not hasattr(extended_class, 'get_field_or_meth'):
                continue
            decl = extended_class.get_field_or_meth(name, setter=setter, getter=getter)
            if decl:
                return decl

        # if nothing was found we check in the constructor
        return self.get_initialized_undeclared_properties_in_constr(name)

    def get_initialized_undeclared_properties_in_constr(self, name):
        """
        searches in the constructor if a non declared property is set in the constructor
        """
        constr = self.get_method('constructor')
        if not constr:
            return

        if not hasattr(constr, 'initialized_undeclared_properties'):
            constr.initialized_undeclared_properties = OrderedDict()
            for assign in get_descendants(constr.get_ast(), Assignment):
                left = assign.get_left_expression()
                if not isinstance(left, MemberAccess) or not left.get_expression()=='this' or len(left.get_fullname().split('.')) != 2:
                    continue
                if not left.get_name() in constr.initialized_undeclared_properties:
                    constr.initialized_undeclared_properties[left.get_name()] = left

        if name in constr.initialized_undeclared_properties:
            return constr.initialized_undeclared_properties[name]
    def get_field_or_constr_decl(self, name):
        field = self.get_field(name)
        if field:
            return field

        self.get_initialized_undeclared_properties_in_constr(name)



    def add_import(self, _import):
        """
        Add an import
        """
        self.__imports.append(_import)
    
    def add_re_export(self, _export):
        self.__re_exports.append(_export)

    def get_all_import_paths(self):
        for f_call in get_descendants(self.get_ast(), FunctionCall):
            if not f_call.get_name() == 'require':
                continue
            try:
                yield (f_call.get_argument(0).children[0].text.strip('"').strip("'"), f_call)
            except (AttributeError, IndexError):
                continue
        for _import in self.get_imports():

            try:
                yield (_import.get_module().get_name(), _import)
            except AttributeError:
                continue

    def is_package_imported(self, package_name: str):
        for pack_name, _ in self.get_all_import_paths():
            if pack_name == package_name:
                return True

        return False

    def get_imports(self):
        return self.__imports
    
    def get_re_exports(self):
        return self.__re_exports
    
    def get_code_only_crc(self):
        
        node = self._ast
        
        if type(self._ast) is list:
            # build a fake node
            node = Node()
            node.children = self._ast
        
        # so that we reuse common code 
        return node.get_code_only_crc()
    
    def set_start_line(self):
        ast = self._ast
        if not ast:
            ast = self._ast_fragments
        if ast and isinstance(ast, list):
            ast = ast[0]
            self.__start_line = ast.get_begin_line()
    
    def get_start_line(self):
        return self.__start_line
    
    def get_line_count(self):
        return self._line_count
    
    def set_line_count(self):
        
        def get_all_tokens(ast_node):
            """
            Iterates on all tokens of a tree or forest
            """
            if type(ast_node) is Token:
                yield ast_node
            elif type(ast_node) is list:
                for token in ast_node:
                    for sub in get_all_tokens(token):
                        yield sub
            else:
                for token in ast_node.children:
                    for sub in get_all_tokens(token):
                        yield sub
        
        def get_code_only_line_count(ast_node):
            
            result = 0
            if type(ast_node) is Token:
                # only for nodes or list of tokens
                return 0
            
            else:
                
                current_line = -1
                for token in get_all_tokens(ast_node):
                    
                    if token.type == LineFeed or token.is_whitespace() or token.is_comment():
                        
                        pass
                    
                    else:
                        if token.get_begin_line() > current_line:
                            result += 1
                            current_line = token.get_begin_line()
                        if token.get_begin_line() != token.get_end_line():
                            result += token.get_end_line()-token.get_begin_line()
                            current_line = token.get_end_line()
                        pass
                return result
        if self._ast_fragments:
            self._line_count = 0
            for ast in self._ast_fragments:
                self._line_count += get_code_only_line_count(ast)
        else:
            self._line_count = get_code_only_line_count(self._ast)
    
    def _set_body_comments_line_count(self):
        
        comments = self.get_body_comments()
        if not comments:
            self._body_comments_line_count = 0


        # we want to add constructor Field comments to the constructor see test test_constructor_with_commented_field
        if isinstance(self, Method) and self.get_name() =='constructor':

            ast = self.get_ast()
            if isinstance(ast, list):
                ast=ast[0]
            for param in ast.get_parameters():
                if isinstance(param, ConstructorField):
                    header_comments = param.get_header_comments()
                    comments += ''.join(comment.text + '\n' for comment in header_comments)
        self._body_comments_line_count = comments.count('\n')
    
    def get_body_comments_line_count(self):
        return self._body_comments_line_count

    def get_body_comments(self):
        return self._body_comments

    def _set_body_comments(self):
        """concatenate all comments from sub-nodes, adding a "\n" separator
        allowing straightforward comment line count
        """
        if type(self._ast) is list:
            allComments = ''
            for token in self._ast:
                
                if token.type == Comment:
                    comments = [token]
                else:
                    comments = token.get_body_comments()

                allComments += ''.join(comment.text + '\n' for comment in comments)

            self._body_comments = allComments
            return
        
        else:
            comments = ''
            for comment in self._ast.get_body_comments():
                comments += comment.text
                comments += "\n"
            self._body_comments = comments

    def _set_header_comments_line_count(self):
        
        comments = self.get_header_comments()
        if not comments:
            self._header_comments_line_count = 0
        
        self._header_comments_line_count = comments.count('\n')
    
    def get_header_comments_line_count(self):
        return self._header_comments_line_count

    def get_header_comments(self):
        return self._header_comments

    def _set_header_comments(self):
        
        if not self._ast:
            return
        
        if type(self._ast) is list:
            comments = ""
            comment_list = self._ast[0].get_header_comments()
            for comment in comment_list:
                if comment and comment.text:
                    comments += comment.text
                    comments += "\n"
            self._header_comments = comments
            return
        else:
            
            comments = ''
            
            for comment in self._ast.get_header_comments():
                comments += comment.text
                comments += '\n'
            self._header_comments = comments
    
    def add_react_symbol(self, name, symbol):
        """
        Register a react symbol
        """
        if symbol == self:
            return

        try:
            if symbol not in self.react_symbols[name]:
                self.react_symbols[name].append(symbol)
        except:
            self.react_symbols[name] = [symbol]

    def get_react_symbol(self, name, _type=None):
        """
        Return the symbol with given name if exist

        """
        try:
            symbols = self.react_symbols[name]
            if _type:
                for symbol in symbols:
                    if isinstance(symbol, _type):
                        return symbol
            else:
                if symbols:
                    return symbols[0]
        except KeyError:
            return None
    
    def add_node_symbol(self, name, symbol):
        """
        Register a node symbol
        """
        if symbol == self:
            return

        try:
            if symbol not in self.node_symbols[name]:
                self.node_symbols[name].append(symbol)
        except:
            self.node_symbols[name] = [symbol]

    def get_node_symbol(self, name, _type=None):
        """
        Return the symbol with given name if exist

        """
        try:
            symbols = self.node_symbols[name]
            if _type:
                for symbol in symbols:
                    if isinstance(symbol, _type):
                        return symbol
            else:
                if symbols:
                    return symbols[0]
        except KeyError:
            return None
    
    def add_web_service(self, service):
        self._web_services.append(service)
    
    def add_web_operation(self, operation):
        self._web_operations.append(operation)
    
    def add_db_query(self, query):
        self._database_queries.append(query)
    
    def get_db_queries(self):
        return self._database_queries
    
    def save_db_queries(self):
        """
        Save all queries.
        """
        for query in self._database_queries:
            query.save(self)

    def get_duplicate_safe_guid(self, file, guid_signature):
        """
        returns None if there is no guid conflict with already saved symbols
        returns an incremented guid if there is a conflice
        """
        if not guid_signature:
            return
        try:
            if guid_signature in file.guid_indexes:
                file.guid_indexes[guid_signature]+=1
                return file.base_guid[guid_signature] + '_' + str(file.guid_indexes[guid_signature])
        except:
            log.warning('Problem missing guid_indexes attribute for file ' + str(file))
            log.debug(traceback.format_exc())

    def get_old_duplicate_safe_guid(self, file, guid_signature):
        """
        returns None if there is no guid conflict with already saved symbols
        returns an incremented guid if there is a conflice
        """
        if not guid_signature:
            return
        try:
            if guid_signature in file.old_guid_indexes:
                file.old_guid_indexes[guid_signature]+=1
                return file.old_base_guid[guid_signature] + '_' + str(file.old_guid_indexes[guid_signature])
        except:
            log.warning('Problem missing guid_indexes attribute for file ' + str(file))
            log.debug(traceback.format_exc())

    def get_base_guid(self, file):
        fullname =  self.get_fullname()
        prefix = file.get_path()
        if fullname.startswith(prefix):
            fullname = fullname[len(prefix):]

        file_name = file.get_name()
        if file_name.endswith('.vue'):
            file_name = file_name[:-4]
        elif file_name.endswith('.html'):
            file_name = file_name[:-5]

        return get_type_id_from_type_name(self.metamodel_type) + '?[' + file.get_path() + '].' + file_name + fullname


    def get_old_base_guid(self, file):
        return get_old_default_guid(fullname=self.get_old_fullname(),
                                    metamodel_type=self.metamodel_type,
                                    file=file)

    def set_crc(self):

        # save only crc for method and function
        # because class/namespace have several asts
        if self.metamodel_type in [Function.metamodel_type]:
            crc = self.get_code_only_crc()
            self.crc = crc


        for symbol in self.get_all_symbols():
            symbol.set_crc()

    def save(self, file=None):
        """
        Save the objects and all its children to the KB.
        """
        if not file:
            file = self.get_file()
        
        if not self.__kb_symbol:
            
            log.debug('saving '+self.metamodel_type+' '+str(self.__name))

            fullname = self.get_fullname()
            if self.get_parent_symbol():
                if isinstance(self.__parent, ExportedVariable):
                    parent = self.__parent.__parent.get_kb_object()
                elif isinstance(self.__parent, CustomObject):
                    parent = self.__parent
                else:
                    parent = self.__parent.get_kb_object()
            else:
                parent = file

            if not isinstance(self, SourceFile) or isinstance(self, TypeScriptFragment):
                if  hasattr(self.__parent, 'get_old_fullname'):
                    parent_old_fullname = self.__parent.get_old_fullname()
                elif isinstance(self, TypeScriptFragment):
                    parent_old_fullname = self.__parent.fullname
                else:
                    parent_old_fullname = parent.fullname
                old_guid_signature = (parent_old_fullname, self.metamodel_type, self.get_old_name())
                old_guid = self.get_old_base_guid(file)
                old_duplicate_safe_guid = self.get_old_duplicate_safe_guid(file, old_guid_signature)


            kb_symbol = CustomObject()
            self.__kb_symbol = kb_symbol
            kb_symbol.set_name(self.__name)
            kb_symbol.set_type(self.metamodel_type)
            kb_symbol.set_parent(parent)

            kb_symbol.set_fullname(fullname)
            if not isinstance(self, SourceFile) or isinstance(self, TypeScriptFragment):
                if old_duplicate_safe_guid:
                    kb_symbol.set_guid(old_duplicate_safe_guid)
                else:
                    kb_symbol.set_guid(old_guid)
            kb_symbol.save()

            if not isinstance(self, SourceFile):
                try:
                    if not old_guid_signature in file.old_guid_indexes:
                        file.old_guid_indexes[old_guid_signature] = 0
                        file.old_base_guid[old_guid_signature] = old_guid
                except:
                    log.warning('Problem missing guid_indexes attribute for file ' + str(file))
                    log.debug(traceback.format_exc())


            try:
                source = self.get_root_symbol()
                program = source.get_program()
                try:
                    program.metamodel_counters[self.metamodel_type] += 1
                except KeyError:
                    pass
                if self.metamodel_type == 'CAST_TS_SourceCode':
                    if source.get_path().endswith(".tsx"):
                        program.nbTSXfiles += 1
                    elif source.get_path().endswith(".ts"):
                        program.nbTSfiles += 1
                    elif source.get_path().endswith(".cts"):
                        program.nbCTSfiles += 1
                    elif source.get_path().endswith(".mts"):
                        program.nbMTSfiles += 1
            except AttributeError:
                pass

            if hasattr(self , 'crc'):
                kb_symbol.save_property('checksum.CodeOnlyChecksum', self.crc)
                delattr(self, 'crc')
            
            # do not save line count for class, interface, namespace and file content...
            if self.metamodel_type not in [SourceFile.metamodel_type,
                                           Class.metamodel_type,
                                           Interface.metamodel_type,
                                           Namespace.metamodel_type]:
                codeLines = self.get_line_count()
                kb_symbol.save_property('metric.CodeLinesCount', codeLines)
                
                headerCommentsLines = self.get_header_comments_line_count()
                if headerCommentsLines:
                    kb_symbol.save_property('metric.LeadingCommentLinesCount', headerCommentsLines)
                    kb_symbol.save_property('comment.commentBeforeObject', self.get_header_comments())
                bodyCommentsLines = self.get_body_comments_line_count()
                if bodyCommentsLines:
                    kb_symbol.save_property('metric.BodyCommentLinesCount', bodyCommentsLines)
                    kb_symbol.save_property('comment.sourceCodeComment', self.get_body_comments())
            
            # special case for sourceFiles
            if self.metamodel_type == SourceFile.metamodel_type:
                version = get_cast_version()
                if (version >= StrictVersion('8.2.11') and version < StrictVersion('8.3.0'))\
                        or version >= StrictVersion('8.3.4'):
                    
                    # in those version range, UA do not calculate LOC on sourceFile so we do it ourself
                    # due to the usage of <languagePattern id="Python" UsedByUA="false">
                    file.save_property('metric.CodeLinesCount', self.get_line_count())
                    
                    # the commentlinescount is not implemented properly for sourceFiles. This should be fixed before adding it
                    
                    # file.save_property('metric.BodyCommentLinesCount', self.get_body_comments_line_count())
                    # file.save_property('metric.LeadingCommentLinesCount', self.get_header_comments_line_count())
                    # file.save_property('comment.sourceCodeComment', self.get_body_comments())
                    # file.save_property('comment.commentBeforeObject', '')

            self._save_position(file)
        
        # recurse...
        for symbol in self.get_all_symbols():
            symbol.save(file=file)
        
        # memory cleanup
    
    #         self._ast = None
    #         self._ast_fragments = None

    def _set_position(self):
        if self._ast:
            for tok in self._ast[::-1]:
                while isinstance(tok, Node):

                    last_tok = list(tok.get_children())[-1]
                    # FunctionType node may contain extra tokens which are removed afterward
                    if isinstance(tok, FunctionType):
                        if last_tok in [":", ",", "=", ")"]:
                            last_tok = list(tok.get_children())[-2]
                    tok = last_tok
                if not tok.is_whitespace():
                    break

            self.positions = [[self._ast[0].get_begin_line(),
                              self._ast[0].get_begin_column(),
                              tok.get_end_line(),
                              tok.get_end_column() + 1]]

        elif self._ast_fragments:
            for ast in self._ast_fragments:
                self.positions.append([
                                       ast.get_begin_line(),
                                       ast.get_begin_column(),
                                       ast.get_end_line(),
                                       ast.get_end_column() + 1])

    def _save_position(self, file):
        for pos in self.positions:
            self.__kb_symbol.save_position(Bookmark(file, pos[0], pos[1], pos[2], pos[3]))

    def is_function_light_parser_specific(self, node):
        if not isinstance(node, FunctionType) or len(self.node_stack) == 0:
            return False
        if hasattr(self.node_stack[-1], "cannot_be_map"):
            return False
        if isinstance(self.node_stack[-1], CurlyBracket) and not isinstance(self, (Interface, Class)):
            return True
        
        if isinstance(self.node_stack[-1], ObjectCurlyBracket):
            return True
        
        return False
    
    def _light_parse(self, stream, parent=None, current_assign_var_name=None):
        """
        Create symbols and sub symbols.
        """
        
        def get_or_create_symbol(name, _type):
            """
            Return existing or create a new one
            
            We merge all occurences of the same namespace/class/interface into one symbol
            @see: merging
            """
            
            if not name:
                log.debug('name is empty '+str(name))
            if _type in [Namespace, Class, Interface]:
                symbols = self.find_local_symbols(name, [_type])
                if symbols:
                    return symbols[0]
            
            # ExportedVariables are created only in the light parser
            # a symbol which is below an ExportedVariable should be added
            # to the parent symbol
            if isinstance(self, ExportedVariable):
                symbol = _type(name, self.get_parent_symbol())
            else:
                symbol = _type(name, self)
            
            self.add_symbol(name, symbol)
            return symbol

        if not isinstance(self, SymbolNotSavedInKb):
            self._set_position()

        prev_tok = None
        prev_name = None
        prev_tok_is_return = False
        for node in stream:
            if is_identifier(node):
                if isinstance(node, Token):
                    prev_name = node.text
                else:
                    prev_name = node.get_name()
            if node == '?':
                current_assign_var_name = None
            if is_import(node):
                self.add_import(node)

            elif is_re_export(node):
                self.add_re_export(node)

            elif self.is_default_variable_export(node):
                export_name = '<Default Export>'
                symbol = get_or_create_symbol(export_name, ExportedVariable)
                symbol.is_pure_export = node.is_pure_export
                symbol.is_default_export = True
                symbol.is_exported = True
                self._light_parse(node.get_children())

            elif is_export(node):

                for element in node.get_exported_elements():
                    # identifier might be an Enum
                    identifier = element.get_element()
                    alias = element.get_alias()
                    if alias:
                        export_name = alias
                    else:
                        export_name = identifier.get_name()
                    if not is_identifier(identifier):
                        if not isinstance(identifier, Node):
                            break

                    # if there is already a symbol for that Element
                    # we do not need to create a symbol
                    if not isinstance(node.children[1], VariableDeclaration) and self.get_symbol(identifier.get_name()):
                        self._light_parse(node.get_children())
                    else:
                        symbol = get_or_create_symbol(export_name, ExportedVariable)
                        symbol._ast = identifier
                        symbol.is_pure_export = node.is_pure_export
                        symbol._light_parse(node.get_children())
                
                # case of export = and import = require()
                try:
                    tokens = list(node.get_children())
                    if len(tokens) > 2 and tokens[1].text == "=":
                        element = tokens[2].text
                        exported_symbol = self.get_symbol(element)
                        if exported_symbol:
                            module_symbol = exported_symbol.get_root_symbol()
                            module_symbol._require_export_symbol_name = element
                        continue
                except:
                    # TODO: add context to the debug output!
                    log.debug(str(node))
                    pass
                
                # other cases
                if not isinstance(node.children[1], VariableDeclaration):
                    for exported_element in node.get_exported_elements():
                        element = exported_element.element
                        exported_symbol = self.get_symbol(element.get_name())
                        if not exported_symbol:
                            continue

                        if node.is_default_export:
                            exported_symbol.is_default_export = True

                        exported_symbol.is_exported = True
                        # if there is an alias in the export, we need to save that information in module symbol
                        module_symbol = exported_symbol.get_root_symbol()
                        module_symbol._exported_elements.append(element.get_name())
                        if exported_element.get_alias():

                            module_symbol._alias_exports.append(exported_element)

            elif is_namespace(node):
                name = node.get_name()
                symbol = get_or_create_symbol(name, Namespace)
                self.handle_exports(node, symbol)
                symbol._ast_fragments.append(node)
                symbol._light_parse(node.get_children())
            
            elif is_class(node):
                name = node.get_name()
                symbol = get_or_create_symbol(name, Class)
                for decorator in node.get_decorators():
                    if decorator.children[1] == 'Injectable':
                        symbol.is_injectable = True
                self.handle_exports(node, symbol)
                symbol._ast_fragments.append(node)
                symbol._light_parse(node.get_children())
                
                # append inheritances
                symbol.inheritances += node.get_direct_inheritances()

            elif is_interface(node):
                name = node.get_name()
                symbol = get_or_create_symbol(name, Interface)
                self.handle_exports(node, symbol)
                symbol._ast_fragments.append(node)
                symbol._light_parse(node.get_children())
                # append inheritances
                symbol.inheritances += node.get_direct_inheritances()

            elif isinstance(node, ConstructorField):
                name = node.get_name()
                _class = self.get_parent_symbol()
                if (isinstance(self, Method)
                        and self.get_name() == 'constructor'
                        and isinstance(_class, Class)
                        and not _class.get_symbol(name, _type=Field)):
                    symbol = Field(name, self.get_parent_symbol())
                    _class.add_symbol(name, symbol)
                    symbol._ast = [node]
                    node.symbol = symbol
                    symbol._set_position()
                self._light_parse(node.get_children())
            elif is_field(node):
                name = node.get_name()
                symbol = get_or_create_symbol(name, Field)
                symbol._ast = [node]
                node.symbol = symbol
                symbol._set_position()
                # we want to create Field symbols without changing the AST hierarchy.
                # By calling "_light_parse" with "self" instead of "symbol", we make sure that the sub nodes are
                # the children of the "self" which is the parent of the Field, instead of the Field itself.
                self._light_parse(node.get_children())

            elif (is_function(node) or self.is_function_light_parser_specific(node)) and not isinstance(parent, TSType):
                name = node.get_name()
                if name.startswith('<Anonymous') and current_assign_var_name:
                    node.old_name = name
                    node.name = current_assign_var_name
                    name = node.name
                if name.startswith('<Anonymous') and prev_tok in ['=', '||=', '??=', '&&='] and prev_name:
                    node.old_name = node.get_old_name()
                    node.name = prev_name
                    name = prev_name
                if prev_tok_is_return and name.startswith('<Anonymous'):
                    node.old_name = name
                    node.name = 'RETURN'
                    name = node.name

                    if self.get_function('RETURN'):
                        ii = 2
                        while True:
                            if self.get_function('RETURN_#' + str(ii)):
                                ii+=1
                            else:
                                break
                        node.name = 'RETURN_#' + str(ii)
                        name = node.name
                if name.startswith('<Anonymous') and node.is_default_export and hasattr(self.get_root_symbol(), 'get_name'):
                    node.old_name = name
                    name = os.path.splitext(self.get_root_symbol().get_name())[0]
                    node.name = name


                if hasattr(node, 'get_old_name'):
                    old_name = node.get_old_name()
                else:
                    if name.startswith('<Anonymous'):
                        old_name = name.replace('#', '')
                    else:
                        old_name = name

                
                # we need to check if there is already an anonymous function in current symbol
                # the node will be renamed with the proper integer
                if node.get_name() == "<Anonymous1>":
                    ii = 1
                    # if self is ExportedVariable, the symbol for the anonymous
                    # will be added to its parent (ExportedVariable is used only in
                    # lightparsing
                    if isinstance(self, ExportedVariable):
                        _parent = self.get_parent_symbol()
                    else:
                        _parent = self
                    while _parent.get_function("<Anonymous"+str(ii)+">"):
                        ii += 1
                    node.name = "<Anonymous"+str(ii)+">"
                    name = node.name
                if old_name == "<Anonymous1>":
                    ii = 1
                    # if self is ExportedVariable, the symbol for the anonymous
                    # will be added to its parent (ExportedVariable is used only in
                    # lightparsing
                    if isinstance(self, ExportedVariable):
                        _parent = self.get_parent_symbol()
                    else:
                        _parent = self
                    while _parent.get_old_anonymous_functions("<Anonymous"+str(ii)+">"):
                        ii += 1
                    node.old_name = "<Anonymous"+str(ii)+">"

                # we do not want to create Function for each overloaded definition
                if hasattr(node, 'from_declare') or any([isinstance(sn, CurlyBracket) or sn == '=>' or sn == 'abstract' for sn in node.children]):
                    ii = 0
                    if self.get_function(name):
                        ii = 2
                        while True:
                            if self.get_function(name + '_#' + str(ii)):
                                ii+=1
                            else:
                                break
                        # name = name + '_#' + str(ii)
                    symbol = get_or_create_symbol(name, Function)
                    if current_assign_var_name == name:
                        symbol.is_htm_attribute_function = True
                    if prev_tok_is_return:
                        symbol.is_return_function = True
                    if ii>1:
                        symbol.old_name = symbol._Symbol__name
                        symbol._Symbol__name = symbol._Symbol__name + '_#' + str(ii)
                    self.handle_exports(node, symbol)
                    symbol._ast = [node]
                    if isinstance(name, str) and  "<Anonymous" in name:
                        symbol.set_property("CAST_HTML5_JavaScript_Function_Properties.anonymous", 1)
                        _parent.old_anonymous_functions[node.get_old_name()] = symbol
                        symbol.old_name = node.get_old_name()
                    elif hasattr(node, 'get_old_name') and node.get_old_name() and '<Anonymous' in node.get_old_name():
                        _parent.old_anonymous_functions[node.get_old_name()] = symbol
                        symbol.old_name = node.get_old_name()
                    if hasattr(symbol, 'is_return_function') and node.get_old_name() and '<Anonymous' in node.get_old_name():
                        symbol.set_property("CAST_HTML5_JavaScript_Function_Properties.anonymous", 1)
                    if hasattr(node, 'object_field_name'):
                        symbol.is_from_object = True

                    symbol._light_parse(node.get_children())
            
            elif isinstance(node, SelfClosingHtmlTag):
                if isinstance(self, HtmlFragment):
                    self.node_stack.append(node)
                    self._light_parse(node.get_children())
                else:
                    if isinstance(self, ExportedVariable):
                        parent_name = self.get_parent_symbol().get_name()
                    else:
                        parent_name = self.get_name()
                    i_frag = 1
                    while self._get_typed_symbol(parent_name+'_fragment_'+str(i_frag),
                                                 begin_line=None,
                                                 _type=HtmlFragment):
                        i_frag += 1
                    fragment_name = parent_name+'_fragment_'+str(i_frag)
                    symbol = HtmlFragment(fragment_name,
                                          self, [node])
                    self.add_symbol(fragment_name, symbol)
                    if self.get_old_name() != self.get_name():
                        symbol.old_name = self.get_old_name() + '_fragment_'+str(i_frag)

                    symbol._light_parse(node.get_children())
            
            elif isinstance(node, HtmlTag):
                
                # we create a fragment only for the root HtmlTag
                if isinstance(self, HtmlFragment):
                    self.node_stack.append(node)
                    self._light_parse(node.get_children())
                else:
                    if isinstance(self, ExportedVariable):
                        parent_name = self.get_parent_symbol().get_name()
                    else:
                        parent_name = self.get_name()
                    i_frag = 1
                    while self._get_typed_symbol(parent_name+'_fragment_'+str(i_frag),
                                                 begin_line=None,
                                                 _type=HtmlFragment):
                        i_frag += 1
                    fragment_name = parent_name+'_fragment_'+str(i_frag)
                    symbol = HtmlFragment(fragment_name,
                                          self, [node])
                    self.add_symbol(fragment_name, symbol)
                    if self.get_old_name() != self.get_name():
                        symbol.old_name = self.get_old_name() + '_fragment_'+str(i_frag)
                    symbol._light_parse(node.get_children())
            
            elif is_method(node, isinstance(self, Interface)):
                name = node.get_name()
                symbol = get_or_create_symbol(name, Method)
                symbol._ast = [node]
                node.symbol = symbol
                symbol._light_parse(node.get_children())

            elif isinstance(node, Node):

                if isinstance(node, ObjectCurlyBracket):
                    for name, val in node.get_dictionary().items():
                        if isinstance(val, (FunctionType, parser_Function, ArrowExpression)):
                            val.object_field_name = name


                # recurse
                self.node_stack.append(node)
                # we check if we may have a dict
                for child in node.get_children():
                    if isinstance(child, Token) and child.text in ["var", "const", "let"]:
                        self.node_stack[-1].cannot_be_map = True
                        break
                if isinstance(node, Declare):
                    for c in node.get_children():
                        if isinstance(c, parser_Function):
                            c.from_declare = True

                # see test test_in_tsx_with_extra_curly_bra
                if isinstance(node, TSType):
                    pass
                elif isinstance(self, HtmlFragment) and prev_tok == '=' and prev_name:
                    self._light_parse(node.get_children(), current_assign_var_name=prev_name)
                else:
                    self._light_parse(node.get_children(), parent=node)

            if not node.is_whitespace():
                prev_tok=node

            try:
                if symbol._ast:
                    symbol.set_line_count()
                    symbol._set_body_comments()
                    symbol._set_body_comments_line_count()
                    symbol._set_header_comments()
                    symbol._set_header_comments_line_count()
                    symbol.set_start_line()

            except UnboundLocalError:
                pass

            if node == 'return':
                prev_tok_is_return = True
            else:
                prev_tok_is_return = False
        if len(self.node_stack) > 0:
            del self.node_stack[-1]
    
    def _fully_parse(self, stream):
        
        for node in stream:
            
            symbol = self
            
            if is_namespace(node):
                symbol = self.get_namespace(node.get_name(), node.get_begin_line())
                symbol._ast = node
            
            elif is_variable_declaration(node):
                pass
            
            elif is_class(node):
                # search the class
                symbol = self.get_class(node.get_name(), node.get_begin_line())
                symbol._ast = node
                node.symbol = symbol
                
                # update inheritances
                symbol.inheritances = node.get_direct_inheritances()
            
            elif is_interface(node):
                
                symbol = self.get_interface(node.get_name(), node.get_begin_line())
                if symbol:
                    symbol._ast = node

                # update inheritances
                symbol.inheritances = node.get_direct_inheritances()

            elif isinstance(node, ConstructorField):
                _class = self.get_parent_symbol()
                if isinstance(_class, Class):
                    symbol = _class.get_field(node.get_name(), node.get_begin_line())
                    if symbol:
                        symbol._ast = node
                        node.symbol = symbol
            elif is_field(node):
                symbol = self.get_field(node.get_name(), node.get_begin_line())
                if symbol:
                    symbol._ast = node
                    node.symbol = symbol

            elif isinstance(node, SelfClosingHtmlTag):
                # we create a fragment only for the root HtmlTag
                if not isinstance(symbol, HtmlFragment):
                    if isinstance(self, ExportedVariable):
                        parent_name = self.get_parent_symbol().get_name()
                    else:
                        parent_name = self.get_name()
                    i_frag = 1
                    while True:
                        symbol = self._get_typed_symbol(parent_name+'_fragment_'+str(i_frag),
                                                        begin_line=None,
                                                        _type=HtmlFragment)
                        if not symbol:
                            log.debug("The symbol of the following fragment was not found : "+str(node))
                            break
                        if not hasattr(symbol, "ast_reasigned"):
                            node.symbol_name = parent_name+'_fragment_'+str(i_frag)
                            symbol._ast = node
                            symbol.ast_reasigned = True
                            break
                        else:
                            i_frag += 1
            
            elif isinstance(node, HtmlTag):
                # we create a fragment only for the root HtmlTag
                if not isinstance(symbol, HtmlFragment):
                    if isinstance(self, ExportedVariable):
                        parent_name = self.get_parent_symbol().get_name()
                    else:
                        parent_name = self.get_name()
                    
                    i_frag = 1
                    while True:
                        symbol = self._get_typed_symbol(parent_name+'_fragment_'+str(i_frag),
                                                        begin_line=None,
                                                        _type=HtmlFragment)
                        if not symbol:
                            log.debug("The symbol of the following fragment was not found : "+str(node))
                            break
                        if not hasattr(symbol, "ast_reasigned"):
                            node.symbol_name = parent_name+'_fragment_'+str(i_frag)
                            symbol._ast = node
                            symbol.ast_reasigned = True
                            break
                        else:
                            i_frag += 1
            elif is_function_type(node):
                new_node = substitute(node, FunctionType, node.children)
                parent = node.parent
                for i, child in enumerate(parent.children):
                    if child == node:
                        parent.children[i] = new_node
                new_node.parent = parent
                node = new_node

            elif is_function(node) and hasattr(node, 'within_type'):
                delattr(node, 'within_type')

            elif is_function(node):
                if node.get_name().startswith('<Anonymous') and isinstance(node.parent, Assignment) and node==node.parent.get_right_expression():
                    node.name = node.parent.get_left_expression().get_name()
                elif node.get_name().startswith('<Anonymous') and isinstance(node.parent, VariableDeclaration):
                    for key, val in node.parent.get_expressions().items():
                        if val == node:
                            node.name = key

                elif isinstance(node.parent, Return) and node.parent.get_expression()==node and node.get_name().startswith('<Anony'):
                    node.name = 'RETURN'
                elif node.get_name().startswith('<Anonymous') and node.is_default_export and hasattr(self.get_root_symbol(), 'get_name'):
                    name = os.path.splitext(self.get_root_symbol().get_name())[0]
                    node.name = name
                elif (isinstance(self, HtmlFragment)
                      and isinstance(node.parent, ObjectCurlyBracket)
                      and node.parent.children[1] == node
                      and isinstance(node.parent.parent, Assignment)
                      and node.parent.parent.get_right_expression() == node.parent):
                    node.name = node.parent.parent.get_left_expression().get_name()
                if node.get_name() == "RETURN":
                    ii = 1
                    while True:
                        if ii == 1:
                            try_ast = self.get_function("RETURN")._ast
                        else:
                            try_ast = self.get_function("RETURN_#" + str(ii))._ast
                        if isinstance(try_ast, list):
                            try_ast = try_ast[0]
                        # there may be some comments at the beginning of try_ast which
                        # were removed from node
                        stream = try_ast.get_children()
                        tok = next(stream)
                        stream2 = node.get_children()
                        tok2 = next(stream2)

                        if (tok.get_begin_line() == tok2.get_begin_line() and
                                tok.get_begin_column() == tok2.get_begin_column()):
                            break
                        ii += 1
                    if ii>1:
                        node.name = "RETURN_#" + str(ii)
                # we need to find the symbol corresponding to that anonymous function
                # we do this by comparing the begin_line and begin_column
                if node.get_name() == "<Anonymous1>":
                    ii = 1
                    while True:
                        try_ast = self.get_function("<Anonymous"+str(ii)+">")._ast
                        if isinstance(try_ast, list):
                            try_ast = try_ast[0]
                        # there may be some comments at the beginning of try_ast which
                        # where removed from node
                        stream = try_ast.get_children()
                        tok = next(stream)
                        stream2 = node.get_children()
                        tok2 = next(stream2)
                        
                        if (tok.get_begin_line() == tok2.get_begin_line() and
                                tok.get_begin_column() == tok2.get_begin_column()):
                            break
                        ii += 1

                    node.name = "<Anonymous"+str(ii)+">"

                # if the node is a FunctionType
                # it should be substituted with an ArrowExpression node
                if isinstance(node, FunctionType):
                    new_node = substitute(node, ArrowExpression, node.children)

                    parent = node.parent
                    for i, child in enumerate(parent.children):
                        if child == node:
                            parent.children[i] = new_node
                    new_node.parent = parent
                    new_node.name = node.get_name()
                    node = new_node
                    node.is_arrow_function = True
                    node.handle_expression()
                symbol = self.get_function(node.get_name(), node.get_begin_line())
                
                if not symbol:
                    log.debug("Problem parsing, symbol not found for function {} in {} ".format(node.get_name(),
                                                                                                self.get_fullname()))
                    
                    if isinstance(node, ArrowExpression):
                        # we check if the ArrowExpression was parsed as a method in the light_parsing
                        symbol = self.get_method_for_parsing(node.get_name(), node.get_begin_line())
                        if symbol:
                            log.debug("The node is actually a method")
                            node.is_arrow_function = False
                            node.is_arrow_method = True
                            symbol._ast = node
                            node.symbol = symbol
                if symbol:
                    symbol._ast = node
                    node.symbol = symbol
                    symbol.handle_function_added_to_attr()

            elif is_method(node):
                symbol = self.get_method_for_parsing(node.get_name(), node.get_begin_line())
                # we originately did not make a difference between InterfaceMethod and Method
                # we add this distinction to overcome parsing difficulties
                # we transform back the InterfaceMethod
                if isinstance(node, InterfaceMethod):
                    new_node = substitute(node, parser_Method, node.children)
                    new_node.return_types = node.return_types
                    parent = node.parent
                    for i, child in enumerate(parent.children):
                        if child == node:
                            parent.children[i] = new_node
                    new_node.parent = parent
                    node = new_node

                symbol._ast = node
                node.symbol = symbol
            
            elif is_export(node):
                if node.is_default_export:
                    for exported_elem in node.get_exported_elements():
                        if hasattr(exported_elem, '_fully_parse'):
                            self._fully_parse(exported_elem.get_element().get_sub_nodes())
                    symbol = self.get_exported_variable('<Default Export>', node.get_begin_line())
                    if symbol:
                        symbol._ast = exported_elem.get_element()
                else:
                    for exported_elem in node.get_exported_elements():
                        name = exported_elem.get_alias()
                        element = exported_elem.get_element()
                        if not name and hasattr(element, 'get_name'):
                            name = element.get_name()

                        # in case we have an
                        # export default {}
                        # with the {} containing functions or class...
                        if not name:
                            self._fully_parse(exported_elem.get_element().get_sub_nodes())
                        if not name:
                            continue
                        symbol = self.get_exported_variable(name, node.get_begin_line())
                        if symbol:
                            symbol._ast = exported_elem.get_element()
            if isinstance(node, TSType):
                node.tag_functiontypes_as_within_type()
            if isinstance(node, Node):
                # recurse
                if isinstance(node, ObjectCurlyBracket):
                    for name, val in node.get_dictionary().items():
                        if isinstance(val, (FunctionType, parser_Function, ArrowExpression)):
                            val.object_field_name = name
                if symbol:
                    # for the symbols below, we associate the sub nodes to their parent; either because they aren't
                    # saved in KB or because we don't want to change the AST hierarchy (ex: Field)
                    if isinstance(symbol, (ExportedVariable, ExpressRouter, Field)):
                        try:
                            self._fully_parse(node.get_sub_nodes())
                        except AttributeError:
                            return
                    else:
                        try:
                            symbol._fully_parse(node.get_sub_nodes())
                        except AttributeError:
                            return

            if isinstance(node, _GenericCall):
                node.name_argument_anonymous_functions()

    def get_old_final_guid(self, guid):
        if guid not in self.old_subObjectsGuids:
            self.old_subObjectsGuids[guid] = 0
            return guid
        value = self.old_subObjectsGuids[guid]
        self.old_subObjectsGuids[guid] = value+1
        return guid+'_'+str(value+1)

    def get_final_guid(self, guid):
        if guid not in self.subObjectsGuids:
            self.subObjectsGuids[guid] = 0
            return guid
        value = self.subObjectsGuids[guid]
        self.subObjectsGuids[guid] = value+1
        return guid+'_'+str(value+1)

    def reorganise_after_fullparsing(self):
        """
        The arrow functions that are passed as argument are renamed during fullparsing
        The symbols dict should be reorganised
        """
        if hasattr(self, 'i_param_symbols'):
            delattr(self, 'i_param_symbols')
        if hasattr(self, 'renamed_symbols'):
            # update self.symbols according to updated names
            new_symbols = []
            for old_name, symb in self.renamed_symbols.items():
                for s in self.symbols[old_name]:
                    if s == symb:
                        continue
                    else:
                        new_symbols.append(s)
                if not new_symbols:
                    del self.symbols[old_name]
                else:
                    self.symbols[old_name] = new_symbols

                if not symb.get_name() in self.symbols:
                    self.symbols[symb.get_name()] = [symb]
                else:
                    self.symbols[symb.get_name()].append(symb)

            delattr(self, 'renamed_symbols')

    def add_violation(self, property, ast):
        """
        Add a violation for a quality rule.
        
        :param property: fullname of the property
        :param ast: location of the violation or [ast, *extrabookmarks]
        """
        self.__violations[property].append(ast)
    
    def add_violation_in_html(self, property, html_file_name, bookmark):
        """
        Add a violation for a quality rule.
        
        :param property: fullname of the property
        :param html_file_name: full name (with path) of the html_file in which we have the violation
        :param bookmark: position of the violation (of type quality_rule._Bookmark)
        """
        self.__violations_in_html[property].append([html_file_name, bookmark])
    
    def get_violations(self, property_name):
        """
        Returns all violations for a given rule.
        """
        try:
            return self.__violations[property_name]
        except:
            return []
    
    def set_property(self, prop, value):
        """
        Used to set a generic property on object
        
        mainly used for quality rules

        :param property: fullname of the property
        :param value: value of the property
        """
        self.__properties[prop] = value
    
    def save_violations(self, file=None):
        
        def get_bookmark(file, ast):
            bookmark = Bookmark(file,
                                ast.get_begin_line(),
                                ast.get_begin_column(),
                                ast.get_end_line(),
                                ast.get_end_column()+1)
            
            return bookmark
        
        def is_symbol_in_file(file_name, symbol):
            
            """
            This function checks if the symbol belongs 
            to the file by checking the root of the symbol
            """
            try:
                root_symbol = symbol.get_root_symbol()
                if file_name == root_symbol.get_file().get_fullname():
                    return True
            except:
                return False
        
        if isinstance(self, SymbolNotSavedInKb):
            return
        if not self.__kb_symbol:
            log.warning('The symbol '+str(self)+' has no kb_symbol.')
            return
        # save the violations
        for rule in self.__violations:
            for ast in self.__violations[rule]:
                if ast and isinstance(ast, list):
                    position = get_bookmark(file, ast[0])
                    extended_positions = []
                    if len(ast) > 1:
                        for ext_pos in ast[1:]:
                            # ext_pos can be the bookmark
                            if isinstance(ext_pos, Bookmark):
                                extended_positions.append(ext_pos)
                            else:
                                extended_positions.append(get_bookmark(file, ext_pos))
                    try:
                        if extended_positions:
                            self.__kb_symbol.save_violation(rule, position, extended_positions)
                        else:
                            self.__kb_symbol.save_violation(rule, position)
                    except:
                        log.debug("Error saving violation: {}".format(rule))
                        log.debug(traceback.format_exc())
                
                else:
                    position = get_bookmark(file, ast)
                    try:
                        self.__kb_symbol.save_violation(rule, position)
                    except RuntimeError:
                        log.debug("Error saving violation: {}".format(rule))
                        log.debug(traceback.format_exc())
        
        # and the properties
        for property_name in self.__properties:
            self.__kb_symbol.save_property(property_name, self.__properties[property_name])
        
        try:
            complexity = self.complexity
        except AttributeError:
            pass
        else:
            self.__kb_symbol.save_property('CAST_TS_Metrics_From_MA.cyclomaticComplexity',
                                           complexity)
        
        # recurse on children
        for symbol in self.get_all_symbols():
            # Recurse on only those symbols which belong to the file (not imported ones)
            if is_symbol_in_file(file.get_fullname(), symbol):
                symbol.save_violations(file=file)
                # ng_component are not directly accessible from get_all_symbols()
                if isinstance(symbol, Class):
                    if symbol.ng_component:
                        symbol.ng_component.save_violations(file=file)
    
    def save_violations_in_html_file(self, html_files):
        
        def get_bookmark(file, ast):
            """
            generate the bookmark in a format compatible with cast.analysers.Bookmark
            @param file: file of type cast.application.File
            """
            bookmark = Bookmark(file,
                                ast.get_begin_line(),
                                ast.get_begin_column(),
                                ast.get_end_line(),
                                ast.get_end_column())
            
            return bookmark
        
        for rule in self.__violations_in_html:
            for violation in self.__violations_in_html[rule]:
                if violation:
                    violation_file_fullname = violation[0]
                    violation_file_name = os.path.basename(violation_file_fullname)
                    bookmark = violation[1]
                    
                    if violation_file_name not in html_files:
                        return
                    for html_file in html_files[violation_file_name]:
                        # we use startswith for comparison because in old versions of html5 analyzer
                        # the symbol type was appended to the fullname
                        if html_file.fullname.startswith(violation_file_fullname):
                            html_file.save_violation(rule, get_bookmark(html_file.parent, bookmark))


class Builtin(Symbol):
    """
    A Typescript builtin object
    """

    metamodel_type = 'CAST_TS_Class'

    def __init__(self, name, parent=None):
        Symbol.__init__(self, name, parent)
        self.inherited_by = []

    def save(self, parent=None):
        builtin_object = CustomObject()
        name = self.get_name()
        builtin_object.set_name(name)
        builtin_object.set_fullname(name)
        builtin_object.set_type(self.metamodel_type)
        builtin_object.set_parent(self.get_parent_symbol())
        builtin_object.save()
        self.set_kb_object(builtin_object)


class SymbolNotSavedInKb(Symbol):
    
    def __init__(self, name, parent=None):
        super().__init__(name, parent)
    
    def add_symbol(self, name, symbol):
        """
        Since these symbols are not saved in the kb
        no symbols should be added to it
        """
        if isinstance(self, NodeExport):
            super().add_symbol(name, symbol)
            return
        self.get_parent_symbol().add_symbol(name, symbol)
        if symbol._Symbol__parent == self:
            symbol._Symbol__parent = self.get_parent_symbol()
    
    def _get_typed_symbol(self, name, begin_line, _type):
        return self.get_parent_symbol()._get_typed_symbol(name, begin_line, _type)
    
    def save(self, file=None):
        pass  # do nothing


class SourceFile(Symbol):
    """
    A ts source file.
    """
    
    metamodel_type = 'CAST_TS_SourceCode'
    
    def __init__(self, path, _file=None, text=None):
        """
        :param _file: cast.application.File
        """
        name = os.path.basename(path)
        if name.endswith('.vue'):
            self.old_name = name.rstrip('.vue')  # was bas choice because if the file name ends with an 'v', 'u' or 'e' it does not work => file.vue => fil
            name = name[:-4]

        elif name.endswith('.html'):
            self.old_name = name.rstrip('.html')
            name = name[:-5]
        Symbol.__init__(self, name)
        self.__file = _file
        self.__path = os.path.normpath(path)
        self.__text = text
        
        self._program = None
        self._components = []
        self._directives = []
        self.class_initializers = []
        self._require_export_symbol_name = None
        self.node_links = []  # all node links will be saved by nodejs extension (they must be stored at module level)
        self.created_all_exported_variable_symbols = False
        self.accessible_modules = []
        self.sequelize_operations = []
        self.framework_symbols = OrderedDict()

    def get_framework_symbols_by_name(self, name):
        to_return = []
        for (name_s, parent, metamodel), symbol in self.framework_symbols.items():
            if name_s == name:
                to_return.append(symbol)

        return to_return

    
    def get_symbols_from_export(self, symbol_name,  types=None):
        """
        there are alias exports so when trying to find a symbol from another file the name may change.
        See test test_import_all_with_alias_and_export_alias
        """
        for alias_export in self._alias_exports:
            if symbol_name == alias_export.get_alias():
                symbols = self.find_local_symbols(alias_export.get_element().get_name(), types)
                if symbols:
                    return symbols

        # no alias_export found
        return self.find_local_symbols(symbol_name, types)

    
    def create_exported_variable_symbols(self):
        if self.created_all_exported_variable_symbols:
            return
        self.created_all_exported_variable_symbols = True
        stream = self.get_ast().get_children()
        
        within_export = False
        while True:
            try:
                child = next(stream)
            except StopIteration:
                break
            else:
                if isinstance(child, Token) and child.text == 'export':
                    try:
                        child = next(stream)
                    except StopIteration:
                        break
                    else:
                        if not isinstance(child, VariableDeclaration) or not child.children[0] == 'const':
                            continue
                        name = child.get_name()
                        if not name:
                            continue
                        exported_var = ExportedVariable(name, self)
                        exported_var._ast = child.get_identifier()
                        
                        self.add_symbol(child.get_name(), exported_var)
    
    def add_symbol(self, name, symbol):
        super().add_symbol(name, symbol)
        if isinstance(symbol, Class) and hasattr(symbol, 'is_injectable'):
            node_package = self.get_node_package_name()
            if not node_package:
                return
            if symbol.get_node_package_name() != node_package:
                if node_package not in symbol.node_packages_using_it:
                    symbol.node_packages_using_it.append(node_package)
                    symbol.node_packages_using_it.sort()
    
    def get_node_package_name(self):
        for package_name, package_file in self.get_program().node_packages.items():
            if self.get_path().startswith(os.path.dirname(package_file.get_path())):
                return package_name
    
    def get_text(self):
        """
        Return something to pass to parsing method.
        - text (for unit testing)
        - or opened file 
        """
        if self.__text is not None:
            return self.__text
        
        return open_source_file(self.get_path())
    
    def get_program(self):
        return self._program
    
    def get_fullname(self):
        return self.__path
    
    def get_path(self):
        return self.__path
    
    def get_file(self):
        return self.__file
    
    def get_ast(self):
        try:
            return Root(TokenIterator(super().get_ast()))
        except:
            log.debug("Problem getting the ast of file "+self.get_fullname()+". The file may be empty.")
            log.debug(traceback.format_exc())
    
    def print_tree(self, depth=0):
        self.get_ast().print_tree(depth=depth)

    def light_parse(self):
        """
        Parse and create the global symbols.
        """
        self._ast = light_parse(self.get_text(), is_tsx=self.get_name().endswith(".tsx"))
        
        self._light_parse(self._ast)

    def refine_parsing_for_json(self):
        root = self.get_ast()
        new_children = []
        for child in root.get_children():
            if isinstance(child, CurlyBracket):
                obj_curl = ObjectCurlyBracket()
                for c in child.get_children():
                    obj_curl.children.append(c)
                    c.parent = obj_curl
                new_children.append(obj_curl)
                obj_curl.parent = root
            else:
                new_children.append(child)

        root.children = new_children
        # we create exported variables for each key of the ObjectCurlyBracket
        for child in new_children:
            if isinstance(child, ObjectCurlyBracket):
                for key, value in child.get_dictionary().items():
                    exported_symbol = ExportedVariable(key, self)
                    exported_symbol._ast = value
                    self.add_symbol(key, exported_symbol)
                return

    def fully_parse(self):
        
        self._ast = parse(self.get_text(), is_tsx=self.get_name().endswith("tsx"), module=self).children
        
        self._fully_parse(self._ast)
        if hasattr(self, 'symbols_to_reorganise'):
            for symb in self.symbols_to_reorganise:
                symb.reorganise_after_fullparsing()
    
    def get_path_match_level(self, splitted_import_path, filepath):
        
        for i in range(len(splitted_import_path)):
            try:
                if os.path.basename(filepath) != splitted_import_path[-i-1]:
                    break
                filepath = os.path.dirname(filepath)
                if not filepath:
                    i += 1
                    break
            except IndexError:
                break
        
        # when the path contains dist, we are likely to find the import in some project which for distribution purpose would be added to a dist dir.
        if i == 0 or (i == 1 and not any(
                [dist_name in splitted_import_path for dist_name in ['dist', 'distrib', 'distribution']])):
            return False
        else:
            return i
    
    def get_module_from_import_with_non_exact_path(self, import_node):
        
        progr = self.get_program()
        possible_matches = []
        redirected_matches = []
        matching_level = 0
        module_path = os.path.normpath(self.get_fullname())
        if not import_node.get_module():
            return
        imported_module_reference = os.path.normpath(import_node.get_module().get_text())
        pathmapped_references = []
        if progr.pathmapping and imported_module_reference in progr.pathmapping:
            pathmapped_references = progr.pathmapping[imported_module_reference]
        
        for module_reference in pathmapped_references+[imported_module_reference]:
            splitted_import_path = module_reference.split(os.sep)
            
            #for
            for redirection in progr.import_redirection.keys():
                if self.get_path_match_level(splitted_import_path, redirection):
                    redirected_matches.append(progr.import_redirection[redirection].get_path())
            
            for filepath in progr.files.keys():
                may_be_redirected = False
                # a file cannot import itself
                if module_path == os.path.normpath(filepath):
                    continue
                if os.path.basename(filepath) in ['index.ts', 'index.tsx']:
                    test_filepath = os.path.dirname(filepath)
                elif filepath.endswith(".ts"):
                    test_filepath = filepath[:-3]
                elif filepath.endswith(".tsx"):
                    test_filepath = filepath[:-4]
                
                else:
                    continue
                i = self.get_path_match_level(splitted_import_path, test_filepath)
                if not i:
                    continue
                
                if may_be_redirected:
                    redirected = progr.import_redirection[os.path.dirname(filepath)]
                    if redirected:
                        redirected_matches.append(redirected)
                        continue
                if i > matching_level:
                    possible_matches = [filepath]
                    matching_level = i
                elif i == matching_level:
                    possible_matches.append(filepath)
            
            # if we have a match with a pathmapping we do not check further
            if module_reference in pathmapped_references:
                break
        if not possible_matches and not redirected_matches:
            return
        
        # we favored redirected_matches (i.e. using path_mapping)
        if redirected_matches:
            return progr.files[get_closest_path(self.get_path(), redirected_matches)]
        # we select only the matches which are the closest relatives
        return progr.files[get_closest_path(module_reference, possible_matches)]
    
    def get_module_from_import(self, import_node):
        """
        @param import_node: parser.Import
        @rtype symbols.SourceFile
        @return the SourceFile refered by the import
        """
        imported_module_reference = import_node.get_module()
        # @type imported_module_reference: typescript_parser.parser.Identifier   # WHY??? --> A string is not an identifier!!!!
        
        if not imported_module_reference:
            return

        imported_module_path = imported_module_reference.get_name()
        # Skipping external libraries with @
        # TODO: restrict @ to the starting character
        # of a name string .../toto/@angular/...?

        if imported_module_path in self.get_program().node_packages:
            return self.get_program().node_packages[imported_module_path]

        to_return = self.get_program().find_module(self,
                                                   imported_module_reference.get_name())
        if to_return:
            return to_return

        # we check if we have a pathmapping
        pathmapping = self.get_program().pathmapping
        if not pathmapping:
            return
        try:
            path = normpath(imported_module_path)
            for shortcut_name, root_paths in pathmapping.items():
                if path.startswith(shortcut_name):
                    
                    for root_path in root_paths:
                        full_path_to_module = path.replace(shortcut_name, root_path, 1)
                        imported_module = self.get_program().find_module(self,
                                                                         full_path_to_module)
                        if imported_module:
                            return imported_module
        except (AttributeError, KeyError):
            return
    
    def get_imported_symbols(self, elements_to_import, depth=0):
        """
        @param elements_to_import: list of ImportedElement
        @rtype: list of ImportedSymbol
        @return: return the list of imported symbol taking recursive re-export into account
        """
        if depth > 20:
            return []
        depth += 1
        # we first handle re-exports
        imported_from_re_export = []
        for re_export in self.get_re_exports():
            accessible_module = self.get_module_from_import(re_export)
            if not accessible_module:
                continue
            accessible_module.create_exported_variable_symbols()
            imported_from_re_export.extend(
                accessible_module.get_imported_symbols(re_export.get_exported_elements(), depth))

        imported_symbols = []

        if elements_to_import == "all":
            # we check if the elements_to_import are within the module
            for symbol in self.get_all_symbols():
                imported_symbols.append(ImportedSymbol(symbol.get_name(), symbol))
            imported_symbols.extend(imported_from_re_export)
        else:
            for e in elements_to_import:
                imported_element_name = e.get_element_name()
                if e.get_alias():
                    alias = e.get_alias_name()
                else:
                    alias = imported_element_name
                symbol = self.get_symbol(imported_element_name, check_for_alias_exports=True)
                
                if not symbol and imported_element_name == "default":
                    symbol = self.get_default_symbol()
                
                if not symbol:
                    for imported_symbol in imported_from_re_export:
                        if imported_symbol.import_name == imported_element_name:
                            imported_symbol.import_name = alias
                            imported_symbols.append(imported_symbol)
                
                # when we have an exported variable, we check if it was imported
                if isinstance(symbol, ExportedVariable):
                    for _import in self.get_imports():
                        
                        star_alias = _import.get_star_alias()
                        # @type star_alias: typescript_parser.parser.Identifier
                        if star_alias:
                            # define a local name that points to the resolved module itself
                            accessible_module = self.get_module_from_import(_import)
                            if not accessible_module:
                                continue
                            imported_symbols.append(ImportedSymbol(star_alias.get_text(), accessible_module))
                        
                        for imported_elem in _import.get_imported_elements():
                            if imported_elem.get_alias_or_element().get_name() == symbol.get_name():
                                accessible_module = self.get_module_from_import(_import)
                                if not accessible_module:
                                    continue
                                imported_symbols.extend(
                                        accessible_module.get_imported_symbols([imported_elem], depth))
                                break
                
                if symbol:
                    imported_symbols.append(ImportedSymbol(alias, symbol))
        return imported_symbols
    
    def add_component(self, component):
        self._components.append(component)
    
    def add_directive(self, directive):
        self._directives.append(directive)
    
    def save_components(self):
        for component in self._components:
            component.save(self)
    
    def save_directives(self):
        for directive in self._directives:
            directive.save(self)
    
    def save_services(self):
        for service in self._web_services:
            service.save(self)
    
    def save_links(self):
        walker = Walker()
        walker.register_interpreter(LinkInterpreter(self))
        walker.walk(self.get_ast())
    
    def save_class_initializers(self):
        for initializer in self.class_initializers:
            try:
                initializer.save(self)
            except:
                path = self.get_file().get_path()
                log.debug("Problem saving class initializer for {}".format(path))
    
    def get_default_symbol(self):
        # default symbol can be function, class, namespace or interface
        all_symbols = self.get_local_symbols()
        for _, symbols in all_symbols.items():
            for symbol in symbols:
                try:
                    if symbol.is_default_export:
                        return symbol
                except AttributeError:
                    pass
        
        for re_export in self.get_re_exports():
            accessible_module = self.get_module_from_import(re_export)
            default_re_exported = False
            for ee in re_export.get_exported_elements():
                if not hasattr(ee, 'get_element'):
                    continue
                if ee.get_element() == "default":
                    default_re_exported = True
            if not accessible_module or not default_re_exported:
                continue
            if accessible_module.get_default_symbol():
                return accessible_module.get_default_symbol()


class TypeScriptFragment(SourceFile):
    """
    A fragment of TypeScript in a <script lang="ts"> of an .html or a .vue file
    """
    metamodel_type = 'CAST_HTML5_TypeScript_SourceCode_Fragment'

    def __init__(self, file, program, parent):
        if not hasattr(file, 'get_path') and isinstance(file, str):
            # for tests
            SourceFile.__init__(self, file)
        else:
            SourceFile.__init__(self, file.get_path(), _file=file)

        self.file = file
        self._program = program
        self._Symbol__parent = parent
        self.get_file()

    def get_parent_symbol(self):
        return None

    def get_fullname(self):

        return self._Symbol__parent.fullname

    def fully_parse(self):
        """
        we fully parse the fragments
        :return:
        """

        new_ast_fragments = []
        for frag in self._ast_fragments:
            individual_fragment = parse(frag.token_text.text, module=self)
            individual_fragment.token_text = frag.token_text
            individual_fragment.shift_ast(individual_fragment.children)
            new_ast_fragments.append(individual_fragment)

            self._fully_parse([individual_fragment])
        if hasattr(self, 'symbols_to_reorganise'):
            for symb in self.symbols_to_reorganise:
                symb.reorganise_after_fullparsing()
        self._ast_fragments = new_ast_fragments

        self._ast = Root(self._ast_fragments)


class ImportedSymbol:
    
    def __init__(self, import_name, symbol):
        self.import_name = import_name
        self.symbol = symbol


class Namespace(Symbol):
    """
    A typescript namespace.
    
    """
    metamodel_type = 'CAST_TS_Namespace'
    
    def __init__(self, name, parent):
        """
        """
        Symbol.__init__(self, name, parent)


class CommonClassInterface(Symbol):

    def __init__(self, name, parent):
        """
        """
        Symbol.__init__(self, name, parent)
        self.inheritances = []
        self.inherited_by = []

    def get_method(self, name, begin_line=None, recursive=True, setter=None, getter=None):
        meth = Symbol.get_method(self, name, begin_line, setter, getter)
        if meth or not recursive:
            return meth
        for c in self.get_inherited_classes_recursively():
            if name in c.symbols:
                meths = c.symbols[name]
                for m in meths:
                    if isinstance(m, Method):

                        if setter and m.is_setter():
                            return m
                        elif getter and m.is_getter():
                            return m
                        elif setter is False and not m.is_setter():
                            return m
                        elif getter is False and not m.is_getter():
                            return m
                        elif setter is None and getter is None:
                            return m

    def find_method(self, name, with_super=False):
        """
        Find a method of the class, using inheritance

        Present Functionality
        =====================
        Inherited members are also found.
        In case of super, an attempt is made to find
        method only in the inherited members.
        """

        if not with_super:
            local_methods = self.find_local_symbols(name, [Method])
            if local_methods:
                return local_methods

        candidates = []

        for inheritance in self.inheritances:
            try:
                # first one wins, depth left first inheritance
                parent_class = inheritance.get_resolution()
            except AttributeError:
                return []
            if parent_class and isinstance(parent_class, CommonClassInterface) and not parent_class == self:
                candidates += parent_class.find_method(name)

        if candidates:
            return candidates

        return []

    def get_inheritances(self):
        """
        :rtype: list of typescript_parser.parser.Identifier
        """
        # "self.inheritances" contains inheritance types of both "extends" and "implements"
        return self.inheritances

    def get_inherited_classes_recursively(self, classes=None, depth=0):
        '''Returns all extended and implemented classes recursively. Note that for interfaces, it will be i'''
        if classes is None:
            classes = []
        if depth > 3:
            return classes
        for _class_identifier in self.get_ast().get_direct_inheritances():
            resol = _class_identifier.get_resolution()
            if isinstance(resol, CommonClassInterface) and resol not in classes and resol != self:
                classes.append(resol)
                resol.get_inherited_classes_recursively(classes, depth+1)

        return classes

    def get_extends(self):
        """
        Returns the extended class symbols via the AST.
        :returns: list of symbols.Class
        """
        extended_classes = []
        ast = self.get_ast()
        if not ast:
            log.debug("No ast found for the class {}, while getting extends".format(self.get_fullname()))
            return extended_classes
        for inheritance in ast.get_extends():
            symbol = inheritance.get_resolution()
            if not symbol:
                symbol = self.get_root_symbol().get_program().get_or_create_builtin_type(inheritance.get_name())
            if symbol:
                extended_classes.append(symbol)
        return extended_classes


class Class(CommonClassInterface):
    """
    A typescript class.
    """
    metamodel_type = 'CAST_TS_Class'
    
    def __init__(self, name, parent):
        """
        """
        CommonClassInterface.__init__(self, name, parent)
        
        # Angular framework
        self.ng_component = None
        self.http_instances = OrderedDict()
        self.express_instances = []
        self.http_call_candidates = []
        self.axios_call_candidates = []
        self.constructor_param_types = OrderedDict()  # type: OrderedDict[str, parser_Type]
        self.initializer_ast_fragments = []
        self.initializer = None
        self.node_packages_using_it = []

        source = self.get_root_symbol()
        program = source.get_program()
        if program:
            program.add_class(self)

    def get_node_package_name(self):
        """
        get the package name of the node module to which the class belongs
        """
        root_symbol = self.get_root_symbol()
        if not hasattr(root_symbol, 'get_node_package_name'):
            return
        
        try:
            return root_symbol.get_node_package_name()
        except AttributeError:
            return

    def get_methods(self):
        methods = []
        for symbols in self.symbols.values():
            for s in symbols:
                if isinstance(s, Method):
                    methods.append(s)

        return methods

    def get_member_declaration(self, member_name: str):
        local_decl = self.get_local_member_declaration(member_name)
        if local_decl:
            return local_decl

        for extended_class in self.get_inherited_classes_recursively():
            if not hasattr(extended_class, 'get_local_member_declaration'):
                continue
            decl = extended_class.get_local_member_declaration(member_name)
            if decl:
                return decl

    def get_local_member_declaration(self, member_name: str):
        _ast = self.get_ast()
        for field in _ast.get_fields():
            id = field.get_identifier()
            if not isinstance(id, Identifier):
                continue
            if id.get_name() == member_name:
                return id

        constr = self.get_method('constructor', recursive=False)
        if not constr:
            return
        for param in constr.get_ast().get_parameters():
            if param.get_name() == member_name:
                return param.get_identifier()

    def get_initializer(self):
        return self.initializer
    
    def get_ng_component(self):
        return self.ng_component
    
    def is_class(self):
        return True

    def get_implements(self):
        """
        Returns the implemented interface symbols via the AST.
        :returns: list of symbols.Interface
        """
        interfaces = []
        ast = self.get_ast()
        if not ast:
            log.debug("No ast found for the class {}, while getting implements".format(self.get_fullname()))
            return interfaces
        for inheritance in ast.get_implements():
            symbol = inheritance.get_resolution()
            if not symbol:
                symbol = self.get_root_symbol().get_program().get_or_create_builtin_type(inheritance.get_name())
            if symbol:
                interfaces.append(symbol)
        return interfaces


class Interface(CommonClassInterface):
    """
    A typescript interface.
    """
    metamodel_type = 'CAST_TS_Interface'
    
    def __init__(self, name, parent):
        """
        """
        CommonClassInterface.__init__(self, name, parent)
        self.implemented_by = []

    def is_class(self):
        return True


class Method(Symbol):
    """
    A typescript method.
    """
    metamodel_type = 'CAST_TS_Method'
    
    def __init__(self, name, parent):
        """
        """
        Symbol.__init__(self, name, parent)
        
        if parent and hasattr(parent, "is_class") and parent.is_class():
            source = self.get_root_symbol()
            program = source.get_program()
            if program:
                program.add_method(self)

    def is_getter(self):
        try:
            return self.get_ast().is_getter()
        except AttributeError:
            return False

    def is_setter(self):
        try:
            return self.get_ast().is_setter()
        except AttributeError:
            return False


class Function(Symbol):
    """
    A typescript function.
    
    """
    metamodel_type = 'CAST_TS_Function'
    
    def __init__(self, name, parent):
        """
        """
        Symbol.__init__(self, name, parent)
        self.is_from_object = False

    def handle_function_added_to_attr(self):
        node = self.get_ast()

        if not (hasattr(node, 'parent') and isinstance(node.parent, Assignment) and node.parent.get_right_expression() == node and isinstance(
                node.parent.get_left_expression(), MemberAccess)):
            return
        # we have a function added to a symbol (see test_function_added_to_function_attr
        m_a = node.parent.get_left_expression()
        if not isinstance(m_a.get_expression(), Identifier):
            return
        symb_name = m_a.get_expression().get_name()
        symb = self.get_parent_symbol().get_symbol(symb_name)
        if symb:
            symb.attribute_functions[m_a.get_name()] = self


class Field(Symbol):
    """
    A typescript class field.
    """
    metamodel_type = 'CAST_TS_Field'

    def __init__(self, name, parent):
        Symbol.__init__(self, name, parent)

    def get_variable_type(self):
        return self.get_ast().get_variable_type()

    def get_ast(self):
        if isinstance(self._ast, list):
            return self._ast[0]
        else:
            return self._ast

class NgDirective(Symbol):
    """An angular directive
    
    @todo: refactor common code into a base class for NgDirective and NgComponent
    """
    
    metamodel_type = 'CAST_TS_Angular_Directive'
    
    def __init__(self, name, parent, ast_decorator, _class):
        super().__init__(name, parent)
        self._ast = ast_decorator
        self._class = _class
        self.html_attribute = self.extract_selector()
    
    def extract_selector(self):
        literal = self.extract_parameters("selector")
        try:
            attribute = literal.text
            attribute = attribute.strip("'").strip('"')
            # Angular convention: if brackets -> html attribute-like format
            attribute = attribute.strip("[]")
        except AttributeError:
            attribute = None
        
        return attribute
    
    def _create_initialization_links(self, component):
        #@todo: resolve constructor when inherited method
        constructor = self._class.get_symbol("constructor")
        if constructor:
            create_link('callLink', component, constructor.get_kb_object())
        for hook_meth_name in ['ngOnChanges', 'ngOnInit', 'ngDoCheck', 'ngAfterContentInit', 'ngAfterContentChecked',
                               'ngAfterViewInit', 'ngAfterViewChecked', 'ngOnDestroy']:
            hook_meth = self._class.get_symbol(hook_meth_name)
            
            if hook_meth:
                create_link('callLink', component, hook_meth.get_kb_object())
    
    def extract_parameters(self, key):
        try:
            parameters = self._ast.get_parameters()
        except AttributeError:
            log.debug("Error extracting component parameters from {}".format(self.get_name()))
        
        if parameters:
            curly_bracket = parameters[0]
            try:
                parameter_dictionary = curly_bracket.get_dictionary()
            except AttributeError:
                log.info("Error: no input parameters found in angular component {}".format(self.get_name()))
                return None
            if not parameter_dictionary:
                return None
            try:
                result = parameter_dictionary[key]
            except KeyError:
                if key == "selector":
                    log.info("Error: no selector key found in angular component {}".format(self.get_name()))
                return None
            
            return result
    
    def save(self, module):
        """
        Save to KB.
        """
        program = module.get_program()
        
        position = Bookmark(module.get_file(),
                            self._ast.get_begin_line(),
                            self._ast.get_begin_column(),
                            self._ast.get_end_line(),
                            self._ast.get_end_column()+1)
        
        directive_object = CustomObject()
        # @todo: should we use Symbol.save()?
        self._Symbol__kb_symbol = directive_object
        directive_object.set_name(self.get_name())
        directive_object.set_type(self.metamodel_type)
        directive_object.set_parent(module.get_kb_object())
        
        directive_object.save()  # into kb
        directive_object.save_position(position)
        
        log.debug('saving '+self.metamodel_type+' '+str(self.get_name()))
        
        program.nbNgDirectives += 1
        
        self._create_initialization_links(directive_object)


class NgComponent(Symbol):
    """An Angular component.
    
    Characterized by the ast of the Decorator @Component 
    
    """
    
    metamodel_type = 'CAST_TS_Angular_Component'
    
    def __init__(self, name, parent, ast_decorator, _class):
        super().__init__(name, parent)
        self._ast = ast_decorator
        self._class = _class
        _class.ng_component = self
        self.htmltag = None
        self.html_fragment = None
        self.templateUrl = None
        self.styleUrls = []
        self.accessible_modules = []  # a list of modules that a imported in the module and recursively
        # statistics
        self.nbExternalMetadata = 0
        self.accessible_classes = OrderedDict()
        self.extract_metadata()
    
    def extract_metadata(self):
        
        self.htmltag = self.extract_htmltag()
        
        self.templateUrl = self.extract_template()
        self.extract_styles()
        if not self.templateUrl:
            self.html_fragment = self.extract_html_fragment()
        if not self.htmltag and not self.html_fragment:
            return
        if not (self.templateUrl or self.html_fragment):
            log.debug("Error extracting template(Url) metadata from Angular Component "+str(self.get_name()))
    
    def extract_html_fragment(self):
        html_text = self.extract_parameters("template")
        if html_text:
            return AngularHtmlFragment(self.get_name(), self, html_text)
    
    def extract_htmltag(self):
        
        literal = self.extract_parameters('selector')
        if isinstance(literal, StringTemplate):
            literal = next(literal.get_children())
        try:
            htmltag = literal.text
            htmltag = htmltag.strip("'").strip('"')
        except AttributeError:
            htmltag = None
        
        return htmltag
    
    def extract_styles(self):
        
        literal = self.extract_parameters("styleUrls")
        if isinstance(literal, Bracket):
            for item in literal.get_items():
                if isinstance(item, Identifier):
                    name = item.get_name()
                elif isinstance(item, Token):
                    name = item.text
                if name:
                    self.styleUrls.append(name.strip("'").strip('"'))
    
    def extract_template(self):
        
        literal = self.extract_parameters('templateUrl')
        try:
            filename = literal.text
            filename = filename.strip("'").strip('"')
        except AttributeError:
            filename = None
        
        if not filename:
            # 
            template = self.extract_parameters('template')
            if is_function_call(template) and template.get_name() == 'require':
                filename = template.get_argument(0)
                try:
                    filename = filename.children[0].text.strip("'").strip('"')
                except (AttributeError, IndexError):
                    filename = None
        
        return filename
    
    def extract_parameters(self, key):
        try:
            parameters = self._ast.get_parameters()
        except AttributeError:
            log.debug("Error extracting component parameters from {}".format(self.get_name()))
        
        if parameters:
            #@todo: resolve identifier when metadata passed implicitly
            curly_bracket = parameters[0]
            if is_identifier(curly_bracket):
                log.debug("Component metadata non-resolved")
                self.nbExternalMetadata += 1
                
                # @todo: reosolve identifier
                #curly_bracket = curly_bracket.resolve()
                return
            
            try:
                parameter_dictionary = curly_bracket.get_dictionary()
            except AttributeError:
                log.debug("Error: no input parameters found in angular component {}".format(self.get_name()))
                return None
            try:
                result = parameter_dictionary[key]
            except KeyError:
                if key == "selector":
                    log.debug("Error: no selector key found in angular component {}".format(self.get_name()))
                return None
            
            return result
    
    def _save_fragments(self, module):
        if self.html_fragment:
            self.html_fragment.save(module)
    
    def _create_initialization_links(self, component):
        #@todo: resolve constructor when inherited method
        constructor = self._class.get_symbol("constructor")
        if constructor:
            create_link('callLink', component, constructor.get_kb_object())
        
        for hook_meth_name in ['ngOnChanges', 'ngOnInit', 'ngDoCheck', 'ngAfterContentInit', 'ngAfterContentChecked',
                               'ngAfterViewInit', 'ngAfterViewChecked', 'ngOnDestroy']:
            hook_meth = self._class.get_symbol(hook_meth_name)
            
            if hook_meth:
                create_link('callLink', component, hook_meth.get_kb_object())
    
    def extract_method_calls(self, evaluation_engine):
        if self.html_fragment:
            self.html_fragment.extract_method_calls(evaluation_engine)
    
    def save(self, module):
        """
        Save to KB.
        """
        program = module.get_program()
        
        position = Bookmark(module.get_file(),
                            self._ast.get_begin_line(),
                            self._ast.get_begin_column(),
                            self._ast.get_end_line(),
                            self._ast.get_end_column()+1)
        
        component_object = CustomObject()
        # @todo: should we use Symbol.save()?
        self._Symbol__kb_symbol = component_object
        component_object.set_name(self.get_name())
        component_object.set_type(self.metamodel_type)
        component_object.set_parent(module.get_kb_object())
        
        component_object.save()  # into kb
        component_object.save_position(position)
        
        if self.htmltag:
            component_object.save_property('CAST_TS_Angular_Component.htmltag', self.htmltag)
        
        log.debug('saving '+self.metamodel_type+' '+str(self.get_name()))
        
        program.nbNgComponents += 1
        program.nbExternalMetadata += self.nbExternalMetadata
        
        self._save_fragments(module)
        
        self._create_initialization_links(component_object)


class HtmlFragment(Symbol):
    
    metamodel_type = 'CAST_HTML5_HTML_Fragment'
    
    def __init__(self, name, parent, ast):
        super().__init__(name, parent)
        self._ast = ast
        self.parent = parent

    def save_links_to_callees(self):
        for link in self.get_links_to_callees():
            create_link(link.link_type,
                        self.get_kb_object(),
                        link.callee.get_kb_object(),
                        link.bookmark)

    def get_links_to_callees(self):
        links = []
        _ast = self.get_ast()
        self_closing_tags = []
        if isinstance(_ast, SelfClosingHtmlTag):
            self_closing_tags = [_ast]

        self_closing_tags.extend(get_descendants(_ast, SelfClosingHtmlTag))
        self_closing_tags.extend(get_descendants(_ast, OpeningHtmlTag))

        # we check the tag of the self_closing_tags
        # if it resolves to a Function or a Component we have get a link
        for tag in self_closing_tags:
            callee = None
            identifier = tag.get_identifier()
            if not identifier:
                continue
            resolution = identifier.get_resolution()
            if isinstance(resolution, ExportedVariable):
                if hasattr(resolution.get_ast(), 'get_assigned_expression'):
                    assigned = resolution.get_ast().get_assigned_expression()
                    if assigned and not hasattr(assigned, 'symbol'):
                        functions = get_descendants(assigned, [parser_Function, ArrowExpression])
                        if functions:
                            assigned = functions[0]
                    if hasattr(assigned, 'symbol'):
                        resolution = assigned.symbol
                if not isinstance(resolution, (Class, Function)):
                    # we try to find a symbol in the file containing the export
                    try:
                        resolution = resolution.get_parent_symbol().symbols[identifier.get_name()][0]
                    except (AttributeError, IndexError, KeyError):
                        continue

            if isinstance(resolution, Class):
                callee_module = resolution.get_root_symbol()
                if not callee_module:
                    continue
                callee = callee_module.get_react_symbol(resolution.get_name(), _type=ReactComponent)
            elif isinstance(resolution, Function):
                callee = resolution
            elif type(resolution).__name__ == 'ExternalFunction':
                if hasattr(resolution.original_object, 'react_function_component'):
                    callee = getattr(resolution.original_object, 'react_function_component')
                    if not callee.get_kb_object():
                        callee = resolution
                else:
                    callee = resolution
            elif type(resolution).__name__ == 'ExternalClass':
                if hasattr(resolution.original_object, 'react_component'):
                    callee = getattr(resolution.original_object, 'react_component')
                    if not callee.get_kb_object():
                        callee = None

            if not callee:
                # we try to check if a reactComponent matching the identifier name
                try:
                    callee_module = resolution.get_root_symbol()
                    if not callee_module:
                        continue
                except:
                    continue

                callee = callee_module.get_react_symbol(identifier.get_name(), _type=ReactComponent)

                if not callee:
                    continue

            if callee:
                bookmark = Bookmark(self.get_root_symbol().get_file(), tag.get_begin_line(),
                                    tag.get_begin_column(),
                                    tag.get_end_line(),
                                    tag.get_end_column())
                link = LinkTo(callee=callee, link_type='callLink', bookmark=bookmark)
                links.append(link)
        
        return links


class AngularHtmlFragment(Symbol):
    
    metamodel_type = 'CAST_HTML5_HTML_Fragment'
    
    def __init__(self, name, parent, ast):
        super().__init__(name, parent)
        self._ast = ast
        self.parent = parent
        self.called_method_names = []
    
    def save(self, file):
        if not self._ast:
            return
        program = file.get_program()
        
        try:
            position = Bookmark(file.get_file(),
                                self._ast.get_begin_line(),
                                self._ast.get_begin_column(),
                                self._ast.get_end_line(),
                                self._ast.get_end_column()+1)
        except:
            return

        fragment_object = CustomObject()
        self._Symbol__kb_symbol = fragment_object
        
        fragment_object.set_name(self.get_name())
        fragment_object.set_type(self.metamodel_type)
        
        component_object = self.get_parent_symbol().get_kb_object()
        fragment_object.set_parent(component_object)
        
        fragment_object.save()  # into kb
        fragment_object.save_position(position)
        
        log.debug('saving '+self.metamodel_type+' '+str(self.get_name()))
        
        program.nbAngularHtmlFragments += 1
        
        # add call link
        create_link('callLink', component_object, fragment_object)
        
        # call links
        _class = self.parent._class
        
        for name_method in self.called_method_names:
            method_symbol = _class.get_symbol(name_method)
            if method_symbol:
                method_kb = method_symbol.get_kb_object()
                create_link('callLink', fragment_object, method_kb)
    
    def extract_htmltags(self, text=None):
        
        if not text:
            text = self._ast.text.strip("`")
        
        tags = []
        for m in re.finditer("<[\s]*([\w]+)", text):
            tags.append(m.group(1))
        
        return tags
    
    def extract_method_calls(self, evaluation_engine):
        """
        We pass the evaluation function as a workaround
        to avoid problems with circular dependencies
        
        Evaluation is used mainly to handle string 
        concatenations when defining the templates
        """
        
        values = evaluation_engine(self._ast)
        if values:
            # assume single value (usual case)
            text = values[0]
            
            # we remove duplicated names
            called_method_names = list(OrderedDict.fromkeys(self.extract_calls_from_html(text)))
            self.called_method_names = called_method_names
    
    @staticmethod
    def extract_calls_from_html(text):
        calls = []
        for string in re.findall(r"\)=\"(.*)\"", text)+re.findall(r"\)=\'(.*)\'", text):
            for call in re.findall("([\w]+)\(", string):
                calls.append(call)
        return calls


def _get_uri_evaluation(uriToEvaluate, idList=None):
    """
    @todo: fully adapt this method taken from Python analyser.
    
    if not None, isList will contain ids present in the url, at the end of method
    evaluates uriToEvaluate replacing ids with {} and evaluating values of variables if present in uriToEvaluate
    """
    if isinstance(uriToEvaluate, str):
        uri = uriToEvaluate
    else:
        return ['']
    
    if uri:
        if isinstance(uri, str):
            uris = uri.split('/')
            uri = None
            if uris:
                uri = ''
                for part in uris:
                    if part:
                        if part.startswith('http:'):
                            uri += 'http://'
                        elif part.startswith('https:'):
                            uri += 'https://'
                        elif part.startswith(':'):
                            if idList != None:
                                idList.append(part[1:])
                            uri += '{}/'
                        elif '?' in part:
                            # we don't add optional ending '/'
                            uri += part
                        else:
                            uri += (part+'/')
            if not uri:
                return ['']
            return [uri]
        else:
            res = []
            for ur in uri:
                uris = ur.split('/')
                ur = None
                if uris:
                    ur = ''
                    for part in uris:
                        if part:
                            if part.startswith('http:'):
                                ur += 'http://'
                            elif part.startswith('https:'):
                                ur += 'https://'
                            elif part.startswith(':'):
                                if idList != None:
                                    idList.append(part[1:])
                                ur += '{}/'
                            elif '?' in part:
                                ur += part[:part.find('?')]
                                ur += '/'
                            else:
                                ur += (part+'/')
                    res.append(ur)
            return res
    
    return ['']


class WebService:
    """
    Stores a service present on the client side to communicate to the server by http requests.
    """
    
    def __init__(self, name, typ, uri, ast, parentFullname, caller, caller_bookmark=None):
        """
        name is the service name
        type is GET, POST, PUT or DELETE as a string
        uri is the url
        ast is the ast used for position
        parent is the resource parent
        """
        self.name = name
        self.ast = ast
        self.uri = clean_url(uri)   # str
        self.type = typ  # GET/PUT/POST/DELETE
        self.kbObjects = []
        self.kbCallers = []
        self.parent = None
        self.parentFullname = parentFullname
        self.caller = caller
        self.caller_bookmark = caller_bookmark
        self.file = None
        self.extra_bookmarks = []

    def add_bookmark(self, ast, file=None):
        # if the file is not specified, the file will be found using method get_file() from the ast
        try:
            if not file:
                if isinstance(ast, Token) and not hasattr(ast, "parent"):
                    parent = ast.parent_curly
                else:
                    parent = ast.parent
                while True:
                    if isinstance(parent, Root):
                        break
                    parent = parent.parent
            file = parent.module
        except AttributeError:
            log.debug("Warning! File not found for ast_node  "+str(ast))
        if not file:
            return
        
        self.extra_bookmarks.append(Bookmark(file.get_file(),
                                             ast.get_begin_line(),
                                             ast.get_begin_column(),
                                             ast.get_end_line(),
                                             ast.get_end_column()+1))

    # if not None, isList will contain ids present in the url, at the end of method
    def get_uri_evaluation(self, idList=None):
        """
        Evaluate urls values and normalise them
        """
        return _get_uri_evaluation(self.uri, idList)
    
    def get_type(self):
        
        return self.type
    
    # @revise not used?
    def get_kb_objects(self):
        return self.kbObjects
    
    def save(self, module):
        """
        Save to KB.
        """
        fullname = self.parentFullname+'/'+self.get_metamodel_type()
        if hasattr(self, 'parent_old_fullname') and self.parent_old_fullname:
            old_fullname = self.parent_old_fullname + '/' + self.get_metamodel_type()
        else:
            old_fullname = fullname

        checksum = self.ast.get_code_only_crc()
        position = Bookmark(module.get_file(),
                            self.ast.get_begin_line(),
                            self.ast.get_begin_column(),
                            self.ast.get_end_line(),
                            self.ast.get_end_column()+1)
        
        program = module.get_program()

        # we would rather use clean_url but this would lead to some change in url and identity of objects...
        for uri in self.get_uri_evaluation():
            if not uri:
                continue
            service_object = CustomObject()

            self.name = uri
            service_object.set_name(self.name)
            service_object.set_type(self.get_metamodel_type())

            service_object.set_parent(module.get_kb_object())


            old_guid = module.get_old_final_guid(old_fullname)

            service_object.set_guid(old_guid)
            service_object.set_fullname(fullname)
            service_object.save()

            service_object.save_property('CAST_ResourceService.uri', uri)
            service_object.save_property('checksum.CodeOnlyChecksum', checksum)
            service_object.save_position(position)
            for extra_bookmark in self.extra_bookmarks:
                service_object.save_position(extra_bookmark)

            create_link('callLink', self.caller.get_kb_object(), service_object, self.caller_bookmark.get_bookmark())

            if isinstance(self, AngularWebService):
                program.nbNgHttpServices += 1


class AngularWebService(WebService):
    
    def __init__(self, name, type_, uri, ast, parentFullname, caller, caller_bookmark=None):
        WebService.__init__(self, name, type_, uri, ast, parentFullname, caller, caller_bookmark)
    
    def get_metamodel_type(self):
        if self.type == 'POST':
            return 'CAST_TS_PostNgHttpService'
        elif self.type == 'PUT':
            return 'CAST_TS_PutNgHttpService'
        elif self.type == 'DELETE':
            return 'CAST_TS_DeleteNgHttpService'
        else:
            return 'CAST_TS_GetNgHttpService'


class NodeWebService(WebService):
    
    def __init__(self, name, type_, uri, ast, parentFullname, caller, caller_bookmark=None):
        WebService.__init__(self, name, type_, uri, ast, parentFullname, caller, caller_bookmark)
    
    def get_metamodel_type(self):
        if self.type == 'POST':
            return 'CAST_NodeJS_PostHttpRequestService'
        elif self.type == 'PUT':
            return 'CAST_NodeJS_PutHttpRequestService'
        elif self.type == 'DELETE':
            return 'CAST_NodeJS_DeleteHttpRequestService'
        else:
            return 'CAST_NodeJS_GetHttpRequestService'


class TSHttpService(WebService):
    
    def __init__(self, name, type_, uri, ast, parentFullname, caller, caller_bookmark=None):
        WebService.__init__(self, name, type_, uri, ast, parentFullname, caller, caller_bookmark)
    
    def get_metamodel_type(self):
        if self.type == 'POST':
            return 'CAST_TS_PostHttpRequestService'
        elif self.type == 'PUT':
            return 'CAST_TS_PutHttpRequestService'
        elif self.type == 'DELETE':
            return 'CAST_TS_DeleteHttpRequestService'
        else:
            return 'CAST_TS_GetHttpRequestService'


class JQueryAjaxService(WebService):
    
    def __init__(self, name, type_, uri, ast, parentFullname, caller, caller_bookmark=None):
        WebService.__init__(self, name, type_, uri, ast, parentFullname, caller, caller_bookmark)
    
    def get_metamodel_type(self):
        if self.type == 'POST':
            return 'CAST_TS_PostHttpRequestService'
        elif self.type == 'PUT':
            return 'CAST_TS_PutHttpRequestService'
        elif self.type == 'DELETE':
            return 'CAST_TS_DeleteHttpRequestService'
        else:
            return 'CAST_TS_GetHttpRequestService'


class WebOperation:
    """
    Stores an operation present on the server side to respond to a request from the client through http requests.
    """
    
    def __init__(self, name, typ, uri, ast, parentFullname, callees, parentOldFullname=None):
        """
        name is the operation name
        type is GET, POST, PUT or DELETE as a string
        uri is the url as an AST expression
        ast is the ast used for position
        parent is the resource parent
        """
        self.name = name
        self.ast = ast
        self.uri = uri
        self.type = typ  # GET/PUT/POST/DELETE
        self.kbObjects = []
        self.kbCallers = []
        self.parent = None
        self.parentFullname = parentFullname
        self.parentOldFullname = parentOldFullname
        self.callees = callees
        self.file = None
        self.extra_bookmarks = []
    
    def add_bookmark(self, ast, file=None):
        # if the file is not specified, the file will be found using method get_file() from the ast
        try:
            if not file:
                if isinstance(ast, Token) and not hasattr(ast, "parent"):
                    parent = ast.parent_curly
                else:
                    parent = ast.parent
                while True:
                    if isinstance(parent, Root):
                        break
                    parent = parent.parent
            file = parent.module
        except AttributeError:
            log.debug("Warning! File not found for ast_node  "+str(ast))
        if not file:
            return
        
        self.extra_bookmarks.append(Bookmark(file.get_file(),
                                             ast.get_begin_line(),
                                             ast.get_begin_column(),
                                             ast.get_end_line(),
                                             ast.get_end_column()+1))
    
    # if not None, isList will contain ids present in the url, at the end of method
    def get_uri_evaluation(self, idList=None):
        """
        Evaluate urls values and normalise them 
        """
        return _get_uri_evaluation(self.uri, idList)
    
    def get_type(self):
        
        return self.type
    
    # @revise not used?
    def get_kb_objects(self):
        return self.kbObjects
    
    def save(self, module):
        """
        Save to KB.
        """
        if self.name == '/':
            fullname = self.parentFullname+'/'+self.get_metamodel_type()+'/'
        else:
            fullname = self.parentFullname+'/'+self.get_metamodel_type()+self.name

        old_fullname = fullname
        if self.parentOldFullname:
            if self.name == '/':
                old_fullname = self.parentOldFullname + '/' + self.get_metamodel_type() + '/'
            else:
                old_fullname = self.parentOldFullname + '/' + self.get_metamodel_type() + self.name

        checksum = self.ast.get_code_only_crc()
        position = Bookmark(module.get_file(),
                            self.ast.get_begin_line(),
                            self.ast.get_begin_column(),
                            self.ast.get_end_line(),
                            self.ast.get_end_column()+1)
        
        for uri in self.get_uri_evaluation():
            service_object = CustomObject()
            if uri:
                self.name = uri
            log.debug("Saving web operation "+self.name)
            service_object.set_name(self.name)
            service_object.set_type(self.get_metamodel_type())
            
            service_object.set_parent(module.get_kb_object())
            
            guid = module.get_old_final_guid(old_fullname)

            service_object.set_guid(guid)
            service_object.set_fullname(fullname)
            service_object.save()
            service_object.save_property('checksum.CodeOnlyChecksum', checksum)
            service_object.save_position(position)

            for callee in self.callees:
                try:
                    create_link('callLink', service_object, callee.get_kb_object(), position)
                except AttributeError:
                    pass


class ExpressUse:
    """
    An ExpressUse object is an object created when an express app calls its method use:
    var app = express() 
    app.use('/root', router)
    """
    
    def __init__(self, method_call, method_call_current_symbol, urls):
        """
        @param method_call: is the ast of the method_call
        @param method_call_current_symbol: is the current_symbol of the call
        @param urls: is a list of evaluated possible urls
        """
        self.router_resolved = False
        self.method_call = method_call
        self.urls = urls
        self.method_call_current_symbol = method_call_current_symbol
        self.module = method_call_current_symbol.get_root_symbol()
        self.last_resolve = False
        self.operations = []
    
    def resolve(self):
        """
        this method tries to resolve the router of the use :
        app.use(url, router)
        if the identifier router resolves to an ExpressRouter symbol
        operations will be created         
        """
        # if the router was already resolved, it means that the operations
        # where already created
        if self.router_resolved:
            return
        
        args = self.method_call.get_arguments()
        if len(args) == 1:
            i_router = 0
        else:
            i_router = 1
        
        router_arg = args[i_router].children[0]
        router = None
        if isinstance(router_arg, Identifier):
            router_symbol_name = router_arg.get_name()
            # we first check if the router is defined in the same file
            router = self.module.get_symbol(router_symbol_name, _type=ExpressRouter)
        
        elif isinstance(router_arg, (FunctionCall, MethodCall)):
            resol = router_arg.get_resolution()
            if isinstance(resol, (Function, Method)):
                router_name = None
                try:
                    router_name = resol.get_ast().get_returns()[0].get_expression().text
                except (AttributeError, IndexError):
                    pass
                router = resol.get_root_symbol().get_symbol(router_name, _type=ExpressRouter)
        
        if not router:
            resolution = None
            if isinstance(router_arg, Identifier) or is_function_call(router_arg):
                resolution = router_arg.get_resolution()
            
            if isinstance(resolution, ExportedVariable):
                module_defining_router = resolution.get_root_symbol()
                try:
                    router_name = resolution.get_ast().get_name()
                    router = module_defining_router.get_symbol(router_name, _type=ExpressRouter)
                except AttributeError:
                    router = None
                if not router:
                    exported_identifier = resolution.get_ast()
                    if hasattr(exported_identifier, 'get_assigned_expression'):
                        assigned_expr = exported_identifier.get_assigned_expression()
                        if isinstance(assigned_expr, Identifier):
                            router_name = assigned_expr.get_name()
                            router = module_defining_router.get_symbol(router_name, _type=ExpressRouter)
            elif isinstance(resolution, NodeExport):
                module_defining_router = resolution.get_root_symbol()
                if resolution.is_single_export:
                    router_name = resolution.get_symbol("<SingleExport>").get_ast().get_name()
                    router = module_defining_router.get_symbol(router_name, _type=ExpressRouter)
            elif isinstance(resolution, Identifier):
                assigned_expr = resolution.get_assigned_expression()
                # case where -> router = getRouter();
                if isinstance(assigned_expr, (FunctionCall, MethodCall)):
                    try:
                        call_resolution = assigned_expr.get_resolution()
                        module_defining_router = call_resolution.get_root_symbol()
                        returns = call_resolution.get_ast().get_returns()
                    except AttributeError:
                        call_resolution, module_defining_router, returns = (None, None, [])
                    router = None
                    if call_resolution and module_defining_router and returns:
                        for ret in returns:
                            try:
                                router_name = ret.get_expression().get_name()
                                router = module_defining_router.get_symbol(router_name, _type=ExpressRouter)
                                if router:
                                    break
                            except AttributeError:
                                continue

        
        if router:
            router.is_used = True
            if not self.last_resolve:
                # we first check if among the router.operations we have a use
                # in which case we are not sure that we have all the resolution
                for op in router.operations:
                    if op.type == "USE":
                        return
            
            self.router_resolved = True
            
            for url_app in self.urls:
                self.mount_router_operation(url_app, router)
            
            for operation in self.operations:
                if operation.file:
                    operation.file.add_web_operation(operation)
                else:
                    self.module.add_web_operation(operation)
    
    def mount_router_operation(self, base_url, router):
        """ 
        This method mounts the router and add all operations to self.operations
            Note that the router may himself call a another router through a use.
                see test test_nested_routers in test_frameworks.
            To handle this case we use recursion.
        """
        for router_operation in router.operations:
            if router_operation.type == "USE":
                
                for url in router_operation.get_uri_evaluation():
                    
                    for sub_op in router_operation.callees:
                        if isinstance(sub_op, ExportedVariable):
                            sub_op.get_root_symbol()
                            module_defining_router = sub_op.get_root_symbol()
                            router_name = sub_op.get_name()
                            _sub_op = module_defining_router.get_symbol(router_name, _type=ExpressRouter)
                            if not _sub_op:
                                exported_identifier = sub_op.get_ast()
                                assigned_expr = exported_identifier.get_assigned_expression()
                                if isinstance(assigned_expr, Identifier):
                                    router_name = assigned_expr.get_name()
                                    _sub_op = module_defining_router.get_symbol(router_name, _type=ExpressRouter)
                            sub_op = _sub_op
                        
                        # we check if the functioncall returns a router
                        elif isinstance(sub_op, (FunctionCall, MethodCall)):
                            resolution = sub_op.get_resolution()
                            if not resolution:
                                continue
                            returned_name = None
                            try:
                                returned_name = resolution.get_ast().get_returns()[0].get_expression().text
                            except (AttributeError, IndexError):
                                continue
                            
                            if not returned_name:
                                continue
                            
                            router = resolution.get_root_symbol().get_symbol(returned_name, _type=ExpressRouter)
                            if router:
                                sub_op = router
                        
                        if isinstance(sub_op, ExpressRouter):
                            new_base_url = base_url+"/"+url
                            if new_base_url[-1] == "/":
                                new_base_url = new_base_url[:-1]
                            self.mount_router_operation(new_base_url, sub_op)
            else:
                if base_url.endswith("/") and router_operation.uri.startswith("/"):
                    url = base_url[:-1]+router_operation.uri
                else:
                    url = base_url+router_operation.uri
                
                fullname = self.method_call_current_symbol.get_fullname()

                if hasattr(self.method_call_current_symbol, 'get_old_fullname') and self.method_call_current_symbol.get_old_fullname() != fullname:
                    old_fullname = self.method_call_current_symbol.get_old_fullname()
                else:
                    old_fullname = None
                type_ = router_operation.type
                handler_function = router_operation.callees+router.handler_functions
                operation = ExpressOperation(url, type_.upper(), url, router_operation.ast, fullname, handler_function,parentOldFullname=old_fullname)
                operation.file = router_operation.file
                self.operations.append(operation)


class NodeOperation(WebOperation):
    def get_metamodel_type(self):
        if self.type == 'POST':
            return 'CAST_NodeJS_PostOperation'
        elif self.type == 'PUT':
            return 'CAST_NodeJS_PutOperation'
        elif self.type == 'DELETE':
            return 'CAST_NodeJS_DeleteOperation'
        elif self.type == 'USE':
            return 'CAST_NodeJS_UseOperation'
        else:
            return 'CAST_NodeJS_GetOperation'


class LoopbackOperation(NodeOperation):
    pass


class ExpressOperation(NodeOperation):
    """
    Express operation object
    """
    
    def __init__(self, name, type_, uri, ast, parentFullname, handler_functions, is_router_operation=False, parentOldFullname=None):
        """
        @param uri : url
        @param ast : ast of the operation which is (always?) a MethodCall node 
        @param handler_functions: functions which are called by the operation : app.get(url, handler_functions)
        @param is_router_operation set to true if we have a router_operation such as router.get(url, handler_functions) 
        """
        self.is_router_operation = is_router_operation
        WebOperation.__init__(self, name, type_, uri, ast, parentFullname, handler_functions, parentOldFullname)
        
        # file in which the operation is declared
        self.file = None
    
    def save(self, module):
        # the router operations are only created when
        if not self.is_router_operation:
            WebOperation.save(self, module)


class ExpressRouter(SymbolNotSavedInKb):
    """
    This symbol is used for handling a router such as:
    
    var router = express.Router()
    router.get('/about', handler_function)
    
    The ExpressRouter object has an attribute operations which is a list of ExpressOperation objects.
    In the example above, the ExpressRouter would have one ExpressOperation with url "/about"
    
    An ExpressRouter object is not saved in the kb since it is not an operation in itself.
    An operation is created when the router is called with an express app.use() such as:
    
    var app = express() 
    app.use('/root', router)

    or if the router is never used (most likely due to an issue in the resolution)
    """
    
    def __init__(self, name):
        self.name = name
        self.operations = []
        self.handler_functions = []
        self.is_used = False
    
    def add_operation(self, operation):
        self.operations.append(operation)


class ClassInitializer(Symbol):
    
    metamodel_type = 'CAST_TS_ClassInitializer'
    
    def __init__(self, ast_fragments, _class):
        Symbol.__init__(self, name='ClassInitializer', parent=_class)
        self._ast_fragments = ast_fragments
        self.parent_class = _class
        self.caller = None
        self.file = None
    
    def save(self, module):
        """
        Save to KB.
        """
        parent = self.parent_class.get_kb_object()
        fullname = parent.fullname+'/'+self.metamodel_type
        
        parent = self.parent_class.get_kb_object()
        
        initializer = CustomObject()
        self._Symbol__kb_symbol = initializer
        
        initializer.set_name(self.get_name())
        initializer.set_parent(parent)
        initializer.set_type(self.metamodel_type)
        initializer.set_fullname(fullname)

        old_fullname = self.parent_class.get_old_fullname() + '/' + self.metamodel_type
        old_guid = module.get_final_guid(old_fullname)

        initializer.set_guid(old_guid)
        
        initializer.save()

        for _ast in self._ast_fragments:
            position = Bookmark(module.get_file(),
                                _ast.get_begin_line(),
                                _ast.get_begin_column(),
                                _ast.get_end_line(),
                                _ast.get_end_column()+1)
            initializer.save_position(position)


class LinkInterpreter:
    """
    This class deals with creation of links
    """
    
    def __init__(self, source_file):
        
        # Current Source File
        self.file = source_file.get_file()
        self.program = source_file.get_program()

        # Stack of symbols
        self.__symbol_stack = [source_file]
    
    def push_symbol(self, symbol):
        self.__symbol_stack.append(symbol)
    
    def pop_symbol(self):
        self.__symbol_stack.pop()
    
    def get_current_kb_symbol(self):
        return self.__symbol_stack[-1].get_kb_object()
    
    def _get_current_symbol(self):
        return self.__symbol_stack[-1]
    
    def create_bookmark(self, ast):
        """
        Create a bookmark from an ast node
        """
        return Bookmark(self.file, ast.get_begin_line(),
                        ast.get_begin_column(),
                        ast.get_end_line(),
                        ast.get_end_column()+1)
    
    def start_Class(self, ast_class):
        """
        :param ast_class: typescript_parser.parser.Class
        """
        symbol = self._get_current_symbol()
        name = ast_class.get_name()

        _class = symbol.get_class(name, ast_class.get_begin_line())

        self.push_symbol(_class)

        if not _class:
            log.warning("No class found for {} under {}".format(name, str(symbol.get_fullname())))
            return None

        bookmark = self.create_bookmark(ast_class)
        caller = _class.get_kb_object()
        if not caller:
            log.warning("No KB object found for the class {}".format(name))
            return None
        # create links to the super classes that "_class" extends
        self.create_inheritance_links(_class, bookmark, caller)

        # create links to the interfaces that "_class" implements
        self.create_inheritance_links(_class, bookmark, caller, implements=True)

    @staticmethod
    def create_inheritance_links(_class, bookmark, caller, implements=False):
        """
        Create links from a given class to all superclasses it extends or all interfaces it implements
        :param _class: symbols.Class
        :param bookmark: cast.analysers.Bookmark
        :param caller: cast.analysers.CustomObject
        :param implements: bool
        """
        if implements:
            # get all interfaces that "_class" implements
            inheritances = _class.get_implements()
            link_type = 'inheritImplementLink'
        else:
            # get all classes that "_class" extends
            inheritances = _class.get_extends()
            link_type = 'inheritExtendLink'

        for inheritance in inheritances:
            if not hasattr(inheritance, "get_kb_object"):
                continue
            callee = inheritance.get_kb_object()
            if not callee:
                continue
            # create link to the inherited class or interface
            create_link(link_type,
                        caller,
                        callee,
                        bookmark)
            # create links for overriden methods (or implemented ones if it's an interface)
            LinkInterpreter.create_override_links(_class, bookmark, inheritance, implements=implements)

    @staticmethod
    def create_override_links(_class, bookmark, inheritance, implements=False):
        """
        Create links from a given class's overriden/implemented methods, to the superclass counterparts.
        :param _class: symbols.Class
        :param bookmark: cast.analysers.Bookmark
        :param inheritance: cast.analysers.Class or cast.analysers.Interface
        :param implements: bool
        """
        if implements:
            override_link_type = 'inheritImplementLink'
        else:
            override_link_type = "inheritOverrideLink"
        # find methods under "inheritance"
        if not hasattr(inheritance, "get_all_symbols"):
            return
        methods = [sym for sym in inheritance.get_all_symbols() if isinstance(sym, Method)]
        for method in methods:
            method_name = method.get_name()
            # check if the found method is present in "_class"
            method_overrides = _class.find_local_symbols(method_name, [Method])
            for override in method_overrides:
                create_link(override_link_type,
                            override.get_kb_object(),
                            method.get_kb_object(),
                            bookmark)
                # add an "implements" link for abstract methods of the superclass
                if implements or not inheritance.get_ast().is_abstract:
                    continue
                create_link('inheritImplementLink',
                            override.get_kb_object(),
                            method.get_kb_object(),
                            bookmark)

    def end_Class(self, _ast):
        self.pop_symbol()
    
    def start_HtmlTag(self, _ast):
        # only the outtermost htmltag should have a symbol
        if hasattr(_ast, "symbol_name"):
            symbol = self._get_current_symbol()
            html_fragment = symbol._get_typed_symbol(_ast.symbol_name,
                                                     _ast.get_begin_line(),
                                                     HtmlFragment)
            
            if not html_fragment:
                log.warning("No html fragment found for %s under %s" % (str(_ast.symbol_name), str(symbol.get_fullname())))
            html_fragment.save_links_to_callees()
            self.push_symbol(html_fragment)
    
    def end_HtmlTag(self, _ast):
        if hasattr(_ast, "symbol_name"):
            self.pop_symbol()
    
    def start_Namespace(self, ast_namespace):
        """
        :param ast_namespace: typescript_parser.parser.Namespace
        """
        symbol = self._get_current_symbol()
        name = ast_namespace.get_name()
        
        namespace = symbol.get_namespace(name)
        if not namespace:
            log.warning("No namespace found for %s under %s" % (str(name), str(symbol.get_fullname())))
        
        self.push_symbol(namespace)
    
    def end_Namespace(self, _ast):
        self.pop_symbol()

    # ast is an Identifier or a MemberAccess
    # see test_react_components
    def link_for_onEvent_propr_in_html(self, ast):
        if not isinstance(self.get_current_callable(), symbols.HtmlFragment):
            return
        if not isinstance(ast.parent, (ObjectCurlyBracket, CurlyBracket)):
            return
        assign = ast.parent.parent
        if not isinstance(assign, Assignment):
            return
        if not isinstance(assign.get_left_expression(), Identifier):
            return
        if not isinstance(ast.get_resolution(), (symbols.Function, symbols.Method)):
            return
        if not assign.get_left_expression().get_name().startswith('on'):
            return

        create_link('callLink',
                    self.get_current_callable().get_kb_object(),
                    ast.get_resolution().get_kb_object(),
                    self.create_bookmark(ast))

    def start_Identifier(self, identifier):
        self.link_for_onEvent_propr_in_html(identifier)

    def start_Interface(self, ast_interface):
        """
        :param ast_interface: typescript_parser.parser.Interface
        """
        symbol = self._get_current_symbol()
        name = ast_interface.get_name()
        
        interface = symbol.get_interface(name)
        if not interface:
            log.warning("No interface found for %s under %s" % (str(name), str(symbol.get_fullname())))
        
        self.push_symbol(interface)
    
    def end_Interface(self, _ast):
        self.pop_symbol()
    
    def start_Method(self, ast_method):
        """
        :param ast_method: typescript_parser.parser.Method
        """
        name = ast_method.get_name()
        symbol = self._get_current_symbol()

        if symbol:
            method = symbol.get_method_for_parsing(name, ast_method.get_begin_line())
            if not method:
                log.warning("No method found for %s under %s" % (str(name), str(symbol.get_fullname())))
                ast_method.no_symbol_found = True
                return

            try:
                self.create_return_type_links(ast_method)
            except Exception as e:
                log.warning("Error creating return type link for the method {}".format(str(name)))
                log.debug(traceback.format_exc())
                pass

            self.push_symbol(method)
    
    def end_Method(self, _ast):
        if hasattr(_ast, 'no_symbol_found'):
            delattr(_ast, 'no_symbol_found')
            return

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
    
    def is_within_return(self, ast):
        if not hasattr(ast, 'parent'):
            return False
        
        if isinstance(ast.parent, Return):
            return True
        elif hasattr(ast.parent, 'symbol'):
            return False
        
        return self.is_within_return(ast.parent)
    
    def start_Function(self, ast_function):
        """
        :param ast_function: typescript_parser.parser.Function
        """
        symbol = self._get_current_symbol()
        name = ast_function.get_name()
        try:
            self.create_return_type_links(ast_function)
        except Exception as e:
            log.warning("Error creating return type link for the function {}".format(str(name)))
            log.debug(traceback.format_exc())
            pass
        
        function = symbol.get_function(name, ast_function.get_begin_line())
        if not function:
            log.warning("No function found for %s under %s" % (str(name), str(symbol.get_fullname())))
        
        self.push_symbol(function)

    def create_return_type_links(self, ast_callable):
        """
        Identifies the declared return types and creates rely on links where it applies
        param ast_callable: Function or Method AST
        """
        # retrieve declared type
        if not hasattr(ast_callable, "return_types"):
            return
        declared_types = ast_callable.return_types
        for declared_type in declared_types:
            type_identifier = declared_type.get_identifier()
            if is_identifier(type_identifier):
                type_symbol = type_identifier.get_resolution()
                # if nothing resolved, check if it's a builtin type
                if not type_symbol:
                    type_symbol = self.program.get_or_create_builtin_type(type_identifier.get_name())
                    if not type_symbol:
                        return
                # create a link from the callable to the Class/Interface
                if isinstance(type_symbol, (Class, Interface, Builtin)):
                    create_link('relyonLink',
                                ast_callable.symbol.get_kb_object(),
                                type_symbol.get_kb_object(),
                                self.create_bookmark(ast_callable))

    def end_Function(self, _ast):
        self.pop_symbol()

    def start_ConstructorField(self, ast):

        self.push_symbol(ast.symbol)
        self.start_Parameter(ast)

    def end_ConstructorField(self, ast):
        self.pop_symbol()

    def start_Parameter(self, ast_param):
        """
        :param ast_param: typescript_parser.parser.Parameter
        """
        # get function/method symbol
        if isinstance(ast_param, ConstructorField):
            constructor = ast_param.get_callable()
            if constructor and hasattr(constructor, 'symbol'):
                create_link('accessWriteLink',
                            constructor.symbol.get_kb_object(),
                            ast_param.symbol.get_kb_object(),
                            self.create_bookmark(ast_param))

            callable = ast_param
        else:
            callable = ast_param.get_callable()
        if not callable or not hasattr(callable, "symbol"):
            return
        callable_symbol = callable.symbol
        if not callable_symbol:
            return
        # get param type's symbol
        param_type = ast_param.get_variable_type()
        if not param_type:
            return
        identifier = param_type.get_identifier()
        if identifier:
            param_type_symbol = identifier.get_resolution()
            # if nothing resolved, check if it's a builtin type
            if not param_type_symbol:
                param_type_symbol = self.program.get_or_create_builtin_type(identifier.get_name())
                if not param_type_symbol:
                    return

            # we do not have symbol for Enum
            if not hasattr(param_type_symbol, 'get_kb_object') or isinstance(param_type_symbol, SymbolNotSavedInKb):
                return
            try:
                create_link('relyonLink',
                            callable_symbol.get_kb_object(),
                            param_type_symbol.get_kb_object(),
                            self.create_bookmark(ast_param))
            except:
                log.debug(traceback.format_exc())
                return

            if isinstance(ast_param, ConstructorField):
                constructor = ast_param.get_callable()
                try:
                    create_link('relyonLink',
                                constructor.symbol.get_kb_object(),
                                param_type_symbol.get_kb_object(),
                                self.create_bookmark(ast_param))
                except:
                    log.debug(traceback.format_exc())

    def start_VariableDeclaration(self, ast_var):
        """
        :param ast_var: typescript_parser.parser.VariableDeclaration
        """
        try:
            encolsing_ast = ast_var.get_identifier().get_enclosing_callable_ast()
        except:
            return
        if not isinstance(encolsing_ast, (parser_Method, parser_Function, ArrowExpression)):
            return
        for var_type in ast_var.get_vartypes().values():
            if not var_type:
                try:
                    var_type = ast_var.get_assigned_value(ast_var.get_identifier())
                    var_identifier = var_type.get_class_identifier()
                except:
                    continue
            else:
                var_identifier = var_type.get_identifier()
            if not var_identifier:
                continue
            try:
                caller = encolsing_ast.symbol.get_kb_object()
                type_symbol = var_identifier.get_resolution()
                # if nothing resolved, check if it's a builtin type
                if not type_symbol:
                    type_symbol = self.program.get_or_create_builtin_type(var_identifier.get_name())
                    if not type_symbol:
                        return
                callee = type_symbol.get_kb_object()
                create_link('relyonLink',
                            caller,
                            callee,
                            self.create_bookmark(ast_var))
            except:
                continue

    def start_Field(self, ast_field):
        """
        :param ast_field: typescript_parser.parser.Field
        """
        bookmark = self.create_bookmark(ast_field)
        # create a writeLink if a value is already assigned in class initializer
        if ast_field.get_value():
            try:
                caller = self._get_current_symbol().get_initializer().get_kb_object()
            except:
                log.debug("Caller object error while creating accessWriteLink for the field {} for the file {}".format(
                    ast_field.get_name(),
                self.file.get_fullname()))
                log.debug(traceback.format_exc())
                caller = None
            try:
                callee = None
                if getattr(ast_field, "symbol", None):
                    callee = ast_field.symbol.get_kb_object()
            except:
                log.debug("Callee object error while creating accessWriteLink for the field {}".format(
                    ast_field.get_name()))
                log.debug(traceback.format_exc())
                callee = None
            if caller and callee:
                create_link("accessWriteLink",
                            caller,
                            callee,
                            bookmark)

        # create rely on links between classes and their fields' types (if they're Class or Interface)
        field_type = ast_field.get_variable_type()
        if not field_type:
            return
        try:
            self.create_field_relyon_link(field_type.get_expression(), bookmark)
        except:
            log.debug(
                "Error while creating a Rely On link for the field {} and type {}".format(ast_field.get_name(),
                                                                                          field_type.text))

    def create_field_relyon_link(self, field_type_expr, bookmark):
        """
        Creates relyOn links from classes to the resolved field types of them.
        :param field_type_expr: Expression of the Type associated with the field
        :param bookmark: Bookmark of the class field declaration
        """
        # resolve the type if it's an identifier
        if isinstance(field_type_expr, Identifier):
            type_res = field_type_expr.get_resolution()
            # if nothing resolved, check if it's a builtin type
            if not type_res:
                type_res = self.program.get_or_create_builtin_type(field_type_expr.get_name())
                if not type_res:
                    return
            if not isinstance(type_res, (Class, Interface, Builtin)):
                return
            field_class = self._get_current_symbol()
            if not isinstance(field_class, (Class, Interface)):
                return
            create_link('relyonLink',
                        field_class.get_kb_object(),
                        type_res.get_kb_object(),
                        bookmark)
        # if it's a BinaryOperation (ex: Type1 | Type1) it requires to be resolved recursively;
        # because one of the operations inside could be another BinaryOperation as well
        elif isinstance(field_type_expr, BinaryOperation):
            self.create_field_relyon_link(field_type_expr.get_left_expression(), bookmark)
            self.create_field_relyon_link(field_type_expr.get_right_expression(), bookmark)
    
    def start_SelfClosingHtmlTag(self, ast):
        # only the outtermost htmltag should have a symbol
        if hasattr(ast, "symbol_name"):
            symbol = self._get_current_symbol()
            html_fragment = symbol._get_typed_symbol(ast.symbol_name,
                                                     ast.get_begin_line(),
                                                     HtmlFragment)
            
            if not html_fragment:
                log.warning("No html fragment found for %s under %s" % (str(ast.symbol_name), str(symbol.get_fullname())))
            html_fragment.save_links_to_callees()
            self.push_symbol(html_fragment)
    
    def end_SelfClosingHtmlTag(self, _ast):
        if hasattr(_ast, "symbol_name"):
            self.pop_symbol()

    def get_current_callable(self):
        symbol = self._get_current_symbol()

        if isinstance(symbol, Field):
            if isinstance(symbol.get_ast(), ConstructorField):
                parent_symbol = symbol.get_parent_symbol()
                if isinstance(parent_symbol, Class):
                    return parent_symbol.get_method('constructor')
            symbol = parent_symbol
        if isinstance(symbol, Class):
            try:
                if not symbol.get_initializer():
                    return
                return symbol.get_initializer()
            except AttributeError:
                log.debug("Error creating link from class initializer in generic call")

        return symbol

    def resolves_to_callable(self, m_c):
        for resol in m_c.get_resolutions():
            if hasattr(resol, 'get_parent_symbol') and isinstance(resol.get_parent_symbol(), Class):
                return True
            if isinstance(resol, Function):
                return True

        return False

    def handle_links_to_function_passed_as_argument(self, call_ast):
        if not self.get_current_callable():
            return

        for arg in call_ast.get_arguments():
            callees = []
            try:
                arg = arg.children[0]
            except IndexError:
                continue
            if isinstance(arg, (parser_Function, ArrowExpression)) and hasattr(arg, 'symbol'):
                callees = [arg.symbol]
            elif isinstance(arg, Identifier):
                resol = arg.get_resolution()
                if isinstance(resol, (Function, Method)):
                    callees = [resol]
            elif isinstance(arg, ObjectCurlyBracket):
                for val in arg.get_dictionary().values():
                    if isinstance(val, (parser_Function, ArrowExpression)) and hasattr(val, 'symbol'):
                        callees.append(val.symbol)
            if not callees:
                continue


            for callee in callees:
                if not callee.get_ast().get_calling_asts():

                    create_link('callLink', self.get_current_callable().get_kb_object(), callee.get_kb_object(), self.create_bookmark(arg))
                    continue


    def _start_GenericCall(self, ast, inferred_links=None):
        if hasattr(ast, 'called_by_redux_switch_handler'):
            return

        self.handle_links_to_function_passed_as_argument(ast)
        resolutions = ast.get_resolutions()
        link_created = False
        if resolutions:
            if is_function_call(ast):
                bookmark_ast = ast.get_function()
            else:
                bookmark_ast = ast.get_method()
            
            for resolution in resolutions:
                if is_class(resolution):
                    log.debug("Skipped call link to Class symbol")
                    continue
                if not hasattr(resolution, 'get_kb_object'):
                    continue
                callee = resolution.get_kb_object()
                if not callee:
                    continue

                symbol = self.get_current_callable()
                if not hasattr(symbol, 'get_kb_object'):
                    continue
                caller = symbol.get_kb_object()
                # Skip links that are already created with Class Hierarchy Analysis
                if inferred_links and (caller.fullname, callee.fullname) in inferred_links:
                    continue
                create_link('callLink',
                            caller,
                            callee,
                            self.create_bookmark(bookmark_ast))
                link_created = True

        if not link_created:
            for _arg in ast.get_arguments():
                if is_identifier(_arg.get_identifier()) and _arg.get_resolution() and is_function(_arg.get_resolution()):
                    symbol = self.get_current_callable()
                    if not hasattr(symbol, 'get_kb_object'):
                        continue
                    caller = symbol.get_kb_object()

                    if is_function_call(ast):
                        bookmark_ast = ast.get_function()
                    else:
                        bookmark_ast = ast.get_method()
                    create_link('callLink',
                                caller,
                                _arg.get_resolution().get_kb_object(),
                                self.create_bookmark(bookmark_ast))

    def start_FunctionCall(self, ast):
        self._start_GenericCall(ast)
    
    def start_MethodCall(self, ast):
        # via type of the object that calls the method; infer implementations of the method using class hierarchy
        try:
            inferred_links = self.create_inferred_method_links(ast)
        except Exception as e:
            log.warning("Error creating inferred method link")
            log.debug(traceback.format_exc())
            inferred_links = None
        self._start_GenericCall(ast, inferred_links)

    def create_inferred_method_links(self, ast):
        """
        Creates links for methods that are overriden and called by other classes in runtime.
        See: https://cast-products.atlassian.net/wiki/x/XIoQ
        :param typescript_parser.parser.MethodCall ast: Ast of the passed method call
        """
        inferred_links = []
        method_ast = ast.get_method()
        calling_obj = ast.get_expression()
        # get calling object's type
        if not hasattr(calling_obj, 'get_variable_type'):
            return
        try:
            type_identifier = calling_obj.get_variable_type()
        except:
            type_identifier = None
        if not type_identifier:
            return
        # then get the symbol of the type to access implemented methods via that (Interface/Class)
        if isinstance(type_identifier, parser_Type):
            type_identifier = type_identifier.get_identifier()
        if not is_identifier(type_identifier):
            return
        type_symbol = type_identifier.get_resolution()
        if not isinstance(type_symbol, (Interface, Class)):
            return

        bookmark = self.create_bookmark(method_ast)
        enclosing_callable = ast.get_enclosing_callable_ast()
        if enclosing_callable:
            enclosing_callable_symbol = enclosing_callable.symbol
        else:
            return
        caller = enclosing_callable_symbol.get_kb_object()
        # get classes that inherit from the interface/class retrieved above
        for _class in type_symbol.inherited_by:
            # get the method which the class implements from the interface above
            # recursive option returns the methods of parent class, so we disable that option
            class_method = _class.get_method(method_ast.text, recursive=False)
            # skip if none or if returns the same object as the initial method
            if class_method and class_method != enclosing_callable_symbol:
                # create a link from the caller to the class implemented method
                callee = class_method.get_kb_object()
                link = create_link('callLink',
                                   caller,
                                   callee,
                                   bookmark)
                # add the corresponding property to distinguish the direct calls from inferred calls
                link.save_property('physicalLink.inferenceEngineRequests',
                                   "Created by inference using Class Hierarchy Analysis")
                if not (caller.fullname, callee.fullname) in inferred_links:
                    inferred_links.append((caller.fullname, callee.fullname))
        return inferred_links

    def start_MemberAccess(self, ast):
        self.link_for_onEvent_propr_in_html(ast)
        caller = self._get_current_symbol().get_kb_object()
        bookmark = self.create_bookmark(ast)
        self.create_member_access_links(ast, caller, bookmark)

    @staticmethod
    def create_member_access_links(ast, caller, bookmark):
        """
        Create a link to Field symbol whenever there's a read/write operation
        """
        for field_symbol in ast.get_resolutions():
            if isinstance(field_symbol, Method) and ast in field_symbol.get_ast().get_calling_asts():
                create_link('callLink', caller, field_symbol.get_kb_object(), bookmark)
            # in case the MemberAccess is another type (function, method, etc.) rather than Field; return
            if not field_symbol or not isinstance(field_symbol, (Field, Identifier)):
                continue
            if isinstance(field_symbol, Identifier):
                # if it's of type parser.identifier, retrieve the corresponding Field symbol
                field_ast = field_symbol.get_enclosing_field()
                if not field_ast:
                    return
                field_symbol = field_ast.symbol

            callee = field_symbol.get_kb_object()
            if not callee:
                return
            # the MemberAccess should be on the left-side of the Assignment to be a write operation
            if isinstance(ast.parent, Assignment) and ast.parent.get_left_expression() == ast:
                link_type = "accessWriteLink"
            # otherwise it's a read operation
            else:
                link_type = "accessReadLink"
            # create the link using the corresponding link type and callee
            create_link(link_type, caller, callee, bookmark)

    def start_Instantiation(self, ast):
        resolution = ast.get_resolution()

        self.handle_links_to_function_passed_as_argument(ast)
        if not isinstance(resolution, Class) and not type(resolution).__name__.startswith('External'):
            return
        
        symbol = self.get_current_callable()
        if not hasattr(symbol, 'get_kb_object'):
            return
        caller = symbol.get_kb_object()
        bookmark = self.create_bookmark(ast)


        if type(resolution).__name__.startswith('External'):
            callee = resolution.get_kb_object()
            if not callee:
                return
            if type(resolution).__name__ == 'ExternalMethod':
                create_link('callLink',
                            caller,
                            callee,
                            self.create_bookmark(ast))
            elif type(resolution).__name__ == 'ExternalClass':
                create_link('accessLink',
                            caller,
                            callee,
                            self.create_bookmark(ast))
            return

        # find the constructor of the instantiated class and create a link to the constructor
        self.create_constructor_link(bookmark, caller, resolution)

        # get the ClassInitializer of the instantiated class and create a link from the current symbol to it
        self.create_initializer_link(bookmark, caller, resolution)



    @staticmethod
    def create_initializer_link(bookmark, caller, resolution):
        initializer = resolution.get_initializer()
        if not initializer:
            return
        callee = initializer.get_kb_object()
        if not callee:
            return
        create_link('callLink',
                    caller,
                    callee,
                    bookmark)

    @staticmethod
    def create_constructor_link(bookmark, caller, resolution):
        constr = resolution.get_method("constructor")
        if not constr:
            return
        callee = constr.get_kb_object()
        if not callee:
            return
        create_link('callLink',
                    caller,
                    callee,
                    bookmark)


class ExportedVariable(SymbolNotSavedInKb):
    """Symbol representing an exported variable.
    
    This symbol is used for handling variable exports/imports
    between different source codes. However it's not saved in 
    the kb (overriden function below) because it's not a callable 
    and thus will not contribute directly into the transactions.
    
    Notes
    -----
    We might use in the future a (fake) name for metamodel_type
    to discern between different non-saved symbols.
    """
    metamodel_type = None
    
    def __init__(self, name, parent):
        """
        """
        Symbol.__init__(self, name, parent)
        self.is_pure_export = True


class NodeExport(SymbolNotSavedInKb):
    """
    This symbol is used for handling node exports (which follow the CommonJS specification)
    It is not saved in the kb. 
    """
    metamodel_type = None
    
    def __init__(self, parent):
        """
        """
        Symbol.__init__(self, "<NodeExport>", parent)
        self.is_single_export = False
        self.exported_ast = OrderedDict()
    
    def save(self, file=None):
        pass  # do nothing


class LinkTo:
    
    def __init__(self, callee, link_type, bookmark=None):
        """
        @param callee: the symbol of the object which is called
        @param link_type: type of link
        @param bookmark: the bookmark of the call
        """
        self.callee = callee
        self.link_type = link_type
        self.bookmark = bookmark


class FrameworkSymbol:
    """
    Any symbol used for a framework. These are not part of the AST.
    """
    
    def __init__(self, name, ast, file):
        """
        @param name
        @param ast: ast used for position
        @param file: is the module symbol
        """
        self.name = name
        self.file = file
        self.ast = ast
        self.metamodel_type = None
        self.kb_symbol = None
        self.__violations = defaultdict(list)
        self.extra_bookmarks = []
    
    def get_violations(self, property_name):
        """
        Returns all violations for a given rule.
        """
        try:
            return self.__violations[property_name]
        except:
            return []
    
    def add_violation(self, property, ast):
        """
        Add a violation for a quality rule.
        
        :param property: fullname of the property
        :param ast: location of the violation
        """
        self.__violations[property].append(ast)
    
    def save_violations(self, file=None):
        
        def get_bookmark(file, ast):
            bookmark = Bookmark(file,
                                ast.get_begin_line(),
                                ast.get_begin_column(),
                                ast.get_end_line(),
                                ast.get_end_column()+1)
            
            return bookmark
        
        # save the violations
        for rule in self.__violations:
            for ast in self.__violations[rule]:
                if ast and isinstance(ast, list):
                    position = get_bookmark(file, ast[0])
                    extended_positions = []
                    if len(ast) > 1:
                        for ext_pos in ast[1:]:
                            # ext_pos can be the bookmark
                            if isinstance(ext_pos, Bookmark):
                                extended_positions.append(ext_pos)
                            else:
                                extended_positions.append(get_bookmark(file, ext_pos))
                    try:
                        if extended_positions:
                            self.__kb_symbol.save_violation(rule, position, extended_positions)
                        else:
                            self.__kb_symbol.save_violation(rule, position)
                    except:
                        log.debug("Error saving violation: {}".format(rule))
                        log.debug(traceback.format_exc())
                
                else:
                    position = get_bookmark(file, ast)
                    try:
                        self.kb_symbol.save_violation(rule, position)
                    except RuntimeError:
                        log.debug("Error saving violation: {}".format(rule))
                        log.debug(traceback.format_exc())
    
    def add_bookmark(self, ast, file):
        self.extra_bookmarks.append(Bookmark(file.get_file(),
                                             ast.get_begin_line(),
                                             ast.get_begin_column(),
                                             ast.get_end_line(),
                                             ast.get_end_column()+1))
    
    def get_name(self):
        return self.name
    
    def get_kb_object(self):
        
        return self.kb_symbol
    
    def get_ast(self):
        return self.ast
    
    def save(self, file, parent=None):
        if not self.metamodel_type:
            return
        fullname = self.file.get_fullname()+"."+self.metamodel_type+"."+self.name
        position = Bookmark(file.get_file(),
                            self.ast.get_begin_line(),
                            self.ast.get_begin_column(),
                            self.ast.get_end_line(),
                            self.ast.get_end_column()+1)
        object = CustomObject()
        self.kb_symbol = object
        object.set_name(self.name)
        object.set_type(self.metamodel_type)
        object.set_fullname(fullname)
        if not parent:
            object.set_parent(file.get_kb_object())
        else:
            object.set_parent(parent.get_kb_object())
        object.save()
        object.save_position(position)
        
        for bookmark in self.extra_bookmarks:
            object.save_position(bookmark)
        
        return object
    
    def save_links(self, file):
        pass


class NoSQLSymbol:
    
    def __init__(self, name, parent=None):
        self.saved = False
        self.bookmarks = []
        self.parent = parent
        self.name = name
        self.saved = False
    
    def add_bookmark(self, _ast, file):
        """
        since a no sql symbol can be accessed by several frameworks, there can be several bookmarks
        """
        self.bookmarks.append(Bookmark(file.get_file(),
                                       _ast.get_begin_line(),
                                       _ast.get_begin_column(),
                                       _ast.get_end_line(),
                                       _ast.get_end_column()+1))
    
    def get_parent(self):
        return self.parent
    
    def get_fullname(self):
        """
        Full name
        """
        # Temporary Fix
        if self.name:
            if self.parent and self.name and not isinstance(self.parent, cast_analyzers_object):
                result = self.parent.get_fullname()+"."+self.metamodel_type+"."+self.name
            else:
                # module
                result = self.metamodel_type+"."+self.name
            
            return result
    
    def get_kb_object(self):
        return self.kb_symbol
    
    def save(self):

        if not self.metamodel_type or self.saved:
            return
        
        log.debug("Saving "+self.metamodel_type+": "+self.get_fullname())
        parent = self.parent
        self.saved = True
        fullname = self.get_fullname()
        kb_symbol = CustomObject()
        self.kb_symbol = kb_symbol
        kb_symbol.set_name(self.name)
        kb_symbol.set_type(self.metamodel_type)
        kb_symbol.set_fullname(fullname)
        if parent:
            if isinstance(parent, cast_analyzers_object):
                kb_symbol.set_parent(parent)
            else:
                kb_symbol.set_parent(parent.kb_symbol)
        else:
            if not self.bookmarks:
                log.debug("Problem, no parent for no-sql symbol "+self.get_fullname())
            else:
                kb_symbol.set_parent(self.bookmarks[0].get_file().get_project())
        kb_symbol.save()
        for bookmark in self.bookmarks:
            kb_symbol.save_position(bookmark)
        return kb_symbol


class NoSQLConnection(NoSQLSymbol):
    
    def __init__(self, name, metamodel_type, project):
        super().__init__(name)
        self.url = name
        self.metamodel_type = metamodel_type
        self.parent = project


class NoSQLCollection(NoSQLSymbol):
    """
    A NoSQL collection

    In our modelization a collection is child of a connection.
    """
    
    def __init__(self, name, metamodel_type, connection=None):
        """
        @param name: is the name of the collection
        @param connection: in the corresponding connection
        @type connection: NoSQLConnection
        """
        super().__init__(name, parent=connection)
        self.metamodel_type = metamodel_type
        self.connection = connection
    
    def get_connection_name(self):
        if self.connection:
            return self.connection.name
        else:
            return "<Unknown>"

    def save(self, project=None):
        kb_symbol = NoSQLSymbol.save(self)
        save_datasensitivity(self.name, kb_symbol)


class MongodbConnection(FrameworkSymbol):
    """
    A Mongodb connection.
    This is the root connection but since it does not necessarly contains the database name, we do not save it.
    """
    
    def __init__(self, name, ast):
        self.name = name
        self.ast = ast
        try:
            if isinstance(ast, Token) and not hasattr(ast, "parent"):
                parent = ast.parent_curly
            else:
                parent = ast.parent
            while True:
                if isinstance(parent, Root):
                    break
                parent = parent.parent
            file = parent.module
        except AttributeError:
            log.debug("Warning! File not found for ast_node  "+str(ast))
            return
        self.file = file
        self.saved_connections = []


class MongodbDatabase(FrameworkSymbol):
    """
    This is a database.
    client.db(dbname) where client is an instance of a root connection

    """
    
    def __init__(self, name, ast: MethodCall, connection):
        """
        :type connection: MongodbConnection or Identifier

type can be an Identifier because when our analyzer generates the MongodbDatabase, the MongodbConnection may not have yet been created.

In that case, the connection identifier will be later on assigned the MongodbConnection.
        """
        self.name = name
        self.ast = ast
        self.connection = connection
        try:
            if isinstance(ast, Token) and not hasattr(ast, "parent"):
                parent = ast.parent_curly
            else:
                parent = ast.parent
            while True:
                if isinstance(parent, Root):
                    break
                parent = parent.parent
            self.file = parent.module
        except AttributeError:
            log.debug("Warning! File not found for ast_node  "+str(ast))
            return
        self.saved = False
    
    def get_connection_name(self):
        if isinstance(self.connection, Identifier):
            if hasattr(self.connection, "mongodb_connection"):
                self.connection = self.connection.mongodb_connection
            else:
                if hasattr(self.connection.get_assigned_expression(), "mongodb_connection"):
                    self.connection = self.connection.get_assigned_expression().mongodb_connection
                else:
                    return None
        if self.connection.name == "<Unknown>":
            return self.connection.name
        if not self.connection.name.endswith("/") and self.name:
            return self.connection.name+"/"+self.name
        else:
            return self.connection.name+self.name
    
    def save(self):
        if not self.saved:
            progr = self.file.get_program()
            
            # creates the mongodb connection if does not exist
            if self.name and self.get_connection_name():
                connection = progr.add_bookmark_to_mongodb_connection(self.get_connection_name(),
                                                                      bookmark=Bookmark(self.file.get_file(),
                                                                                        self.ast.get_begin_line(),
                                                                                        self.ast.get_begin_column(),
                                                                                        self.ast.get_end_line(),
                                                                                        self.ast.get_end_column()+1))
                self.kb_symbol = connection.get_kb_object()
            self.saved = True
            
            #we add the root bookmark for the MongodbConnection if it was not saved
            if not self.get_connection_name() in self.connection.saved_connections:
                self.connection.saved_connections.append(self.get_connection_name())
                self.kb_symbol = progr.add_bookmark_to_mongodb_connection(self.get_connection_name(),
                                                                          bookmark=Bookmark(
                                                                                  self.connection.file.get_file(),
                                                                                  self.connection.ast.get_begin_line(),
                                                                                  self.connection.ast.get_begin_column(),
                                                                                  self.connection.ast.get_end_line(),
                                                                                  self.connection.ast.get_end_column()+1))


class MongodbCollection:
    """
    A Mongodb collection.

    """
    
    def __init__(self, name, ast, file=None, database=None):
        self.name = name
        self.ast = ast
        self.saved = False
        try:
            if not file:
                if isinstance(ast, Token) and not hasattr(ast, "parent"):
                    parent = ast.parent_curly
                else:
                    parent = ast.parent
                while True:
                    if isinstance(parent, Root):
                        break
                    parent = parent.parent
            file = parent.module
        except AttributeError:
            log.debug("Warning! File not found for ast_node  "+str(ast))
        self.file = file
        self.database = database
    
    def save(self):
        if not self.saved:
            self.saved = True
            progr = self.file.get_program()
            connection_name = self.database.get_connection_name()
            
            # it was actually not a mongodb connection
            if not connection_name:
                return
            # also create the mongodb collection if does not exist
            collection = progr.add_bookmark_to_mongodb_collection(self.name,
                                                                  connection_name,
                                                                  bookmark=Bookmark(self.file.get_file(),
                                                                                    self.ast.get_begin_line(),
                                                                                    self.ast.get_begin_column(),
                                                                                    self.ast.get_end_line(),
                                                                                    self.ast.get_end_column()+1))
            
            self.kb_symbol = collection.get_kb_object()


class MongooseConnection(FrameworkSymbol):
    """
    A Mongoose connection.
    """
    
    def __init__(self, name, ast, file):
        
        self.name = self.clean_name(name)
        self.ast = ast
        self.file = file
        self.saved = False
    
    def clean_name(self, name: str):
        if '?' in name:
            name = name.split('?')[0]
        
        if '@' in name:
            
            splitted_name = name.split('@')
            if len(splitted_name) != 2:
                return name
            begin = splitted_name[0].split('//')
            if len(begin) > 2:  # not sure what to do in that case
                return name
            elif len(begin) == 1:
                return splitted_name[1]
            
            return begin[0]+'//'+splitted_name[1]
        return name
    
    def save(self):
        if not self.saved:
            progr = self.file.get_program()
            
            # also create the mongodb collection if does not exist
            connection = progr.add_bookmark_to_mongodb_connection(self.name,
                                                                  bookmark=Bookmark(self.file.get_file(),
                                                                                    self.ast.get_begin_line(),
                                                                                    self.ast.get_begin_column(),
                                                                                    self.ast.get_end_line(),
                                                                                    self.ast.get_end_column()+1))
            self.kb_symbol = connection.get_kb_object()
            previous_guid = self.file.get_kb_object().guid+"."+self.name
            
            self.saved = True
            if self.name == '<Unknown>':
                return
            previous_guid = "1020219"+previous_guid[7:]
            if connection.get_kb_object().typename == 'CAST_NodeJS_MongoDB_Connection':
                connection.get_kb_object().save_property('TypeScript_GUID_Migration.previousGUID', previous_guid)
                # set technicalLevel used to tell if the migration should be carried out
                connection.get_kb_object().save_property('TypeScript_GUID_Migration.technicalLevel', 1)


class MongooseCollection:
    """
    A Mongoose collection.
    """
    
    def __init__(self, name, ast, file, connection=None):
        self.name = name
        self.ast = ast
        self.saved = False
        self.file = file
        self.connection = connection
    
    def get_connection_name(self):
        if self.connection:
            return self.connection.name
        else:
            return "<Unknown>"
    
    def save(self):
        if not self.saved:
            progr = self.file.get_program()
            
            # also create the mongodb collection if it does not exist
            collection = progr.add_bookmark_to_mongodb_collection(self.name,
                                                                  self.get_connection_name(),
                                                                  bookmark=Bookmark(self.file.get_file(),
                                                                                    self.ast.get_begin_line(),
                                                                                    self.ast.get_begin_column(),
                                                                                    self.ast.get_end_line(),
                                                                                    self.ast.get_end_column()+1))
            
            self.kb_symbol = collection.get_kb_object()
            previous_guid = self.file.get_kb_object().guid+"."+self.name
            previous_guid = "1020220"+previous_guid[7:]
            collection.get_kb_object().save_property('TypeScript_GUID_Migration.previousGUID', previous_guid)
            # set technicalLevel used to tell if the migration should be carried out
            collection.get_kb_object().save_property('TypeScript_GUID_Migration.technicalLevel', 1)
            self.saved = True
    
    def resolve_connection(self, program):
        if not self.connection:
            if hasattr(program, 'mongoose_connections'):
                for connection in program.mongoose_connections:
                    if hasattr(connection, "is_mongoose_default_connection"):
                        self.connection = connection
                        return


class TypeORMConnection(FrameworkSymbol):
    """
    Represents a TypeORM connection
    """

    def __init__(self, name, ast, parent, database_name=None):
        super().__init__(name, ast, parent)
        self.entities = []
        self.unresolved_entities = []
        self.saved = False
        self.database_name = database_name

    def save(self, file):
        if not self.saved:
            progr = self.file.get_program()
            
            # also create the mongodb collection if it does not exist
            progr.add_bookmark_to_mongodb_connection(self.name,
                                                     bookmark=Bookmark(self.file.get_file(),
                                                                       self.ast.get_begin_line(),
                                                                       self.ast.get_begin_column(),
                                                                       self.ast.get_end_line(),
                                                                       self.ast.get_end_column()+1))
            self.saved = True


class TypeORMEntityOperation:
    """
    Represents a TypeORM entity operation
    """

    def __init__(self, operation_name: str, caller, bookmark=None, triggeredby=None):
        self.operation_name = operation_name
        self.caller = caller
        self.bookmark = bookmark
        self.triggeredby = triggeredby


class TypeORMEntity(FrameworkSymbol):
    """
    Represents a TypeORM entity for sql or a TypeORM collection for nosql
    """

    entity_operation_table = {
        'Add': 'CAST_Insert_Table.tableName',
        'Update': 'CAST_Update_Table.tableName',
        'Remove': 'CAST_Delete_Table.tableName',
        'Select': 'CAST_Select_Table.tableName'
    }

    def __init__(self, name, ast, parent):
        super().__init__(name, ast, parent)
        self.tables = []
        self.cascade = OrderedDict()
        self.parent = parent
        self.database_name = None
        self.bookmark = None
        self.is_nosql = False
        self.class_symbol = None
        self.vendor = 'typeorm'
        self.callers = []
        self.operations = []
        self.__kb_object_operations = defaultdict()  # no need to order it since it can only be some operations

    def get_connection_name(self):
        if isinstance(self.parent, TypeORMConnection):
            return self.parent.name

    def add_caller(self, operation_name, caller, bookmark=None, triggeredby=None):
        self.callers.append(TypeORMEntityOperation(operation_name, caller, bookmark, triggeredby=triggeredby))

    def save(self, file):
        if self.is_nosql:
            self.save_nosql()
        else:
            self.save_sql()

    def save_nosql(self):
        # we save the entity object only if the table was not found
        log.info("Saving TypeORM collection " + self.name)
        tbls = []
        try:
            tbls += external_link.find_objects(self.name, 'Database Table')
            tbls += external_link.find_objects(self.name, 'Database View')
            if self.name.casefold() != self.name:
                tbls += external_link.find_objects(self.name.casefold(), 'Database Table')
                tbls += external_link.find_objects(self.name.casefold(), 'Database View')
            if self.name.upper() != self.name:
                tbls += external_link.find_objects(self.name.upper(), 'Database Table')
                tbls += external_link.find_objects(self.name.upper(), 'Database View')
        except:
            pass

        if tbls:
            self.tables = tbls
            log.info('A table named as the typeORM entity was found. The links to the entity will be added to that table named :' + self.name)
        else:
            # we save the entity only if we have a nosql db
            # (which is the case only when the progr.typeORMConnections dict has at least one entry)
            log.info("Saving mongodb collection for typeORM entity " + self.name)

            progr = self.file.get_program()

            # if the collection does not exist, it is created
            progr.add_bookmark_to_mongodb_collection(self.name,
                                                     self.get_connection_name(),
                                                     bookmark=Bookmark(self.file.get_file(),
                                                                       self.ast.get_begin_line(),
                                                                       self.ast.get_begin_column(),
                                                                       self.ast.get_end_line(),
                                                                       self.ast.get_end_column() + 1))

    def save_sql(self):
        name = self.name
        log.info("Saving TypeORM entity: {}".format(name))
        parent = self.parent.get_kb_object()
        obj_entity = CustomObject()
        obj_entity.set_name(name)
        obj_entity.set_type('CAST_NodeJS_Entity')
        obj_entity.set_parent(parent)
        guid = ''.join(['1020666', '?', parent.fullname, '.', name])
        obj_entity.set_guid(guid)
        obj_entity.save()

        obj_entity.save_position(self.bookmark)

        obj_entity.save_property('CAST_Entity.vendor', self.vendor)

        if self.class_symbol is not None:
            create_link('relyonLink', obj_entity, self.class_symbol.get_kb_object(), self.bookmark)

        for caller in self.callers:
            operation_name = caller.operation_name
            if operation_name not in self.operations:
                self.operations.append(operation_name)
                log.info("Saving TypeORM entity operation: {}".format(operation_name))
                obj_operation = CustomObject()
                obj_operation.set_name(operation_name)
                obj_operation.set_type('CAST_NodeJS_Entity_Operation')
                obj_operation.set_parent(obj_entity)
                guid = ''.join(['1020667', '?', obj_entity.fullname, '.', operation_name])
                obj_operation.set_guid(guid)
                obj_operation.save()
                self.__kb_object_operations[operation_name] = obj_operation

                obj_operation.save_property(self.entity_operation_table[operation_name], self.name.lower())
                obj_operation.save_property('CAST_Entity_Operation.vendor', self.vendor)
            else:
                obj_operation = self.__kb_object_operations[operation_name]

            if hasattr(caller, 'bookmark') and caller.bookmark:
                obj_operation.save_position(caller.bookmark)
                link = create_link('callLink', caller.caller.get_kb_object(), obj_operation, caller.bookmark)
            else:
                link = create_link('callLink', caller.caller.get_kb_object(), obj_operation)

            if caller.triggeredby:
                link.save_property('physicalLink.triggeredBy', caller.triggeredby)


class SqlQuery:
    """
    Represents a SQL Query object
    """
    
    def __init__(self, sql, ast, parentFullname, vendor=None, triggeredby=None):
        self.sql = sql
        self.ast = ast
        self.caller = None
        self.parentFullname = parentFullname
        self.name = None
        self.real_caller = None
        self.raw_bookmarks = []
        self.initialize_name()
        self.vendor = vendor
        self.entity = None
        self.incomplete_query = False
        self.triggeredby = triggeredby

    def initialize_name(self):
        max_words = 4
        if self.sql.upper().startswith(('EXEC', 'EXECUTE', 'QUERY')):
            # we don't show parameters in the name for procedure calls
            max_words = 2
        truncated_sql = self.sql
        
        splitted = self.sql.split()
        if len(splitted) > max_words:
            truncated_sql = " ".join(splitted[0:max_words])
        
        if truncated_sql.endswith("\\"):
            truncated_sql = truncated_sql[:-1]
        self.name = truncated_sql
    
    def save(self, module):
        """
        Save query object to KB.
        """

        fullname = self.parentFullname+'/'+self.name
        checksum = self.ast.get_code_only_crc()
        position = Bookmark(module.get_file(),
                            self.ast.get_begin_line(),
                            self.ast.get_begin_column(),
                            self.ast.get_end_line(),
                            self.ast.get_end_column())

        log.info("Saving TS query: {}".format(self.name))
        query_object = CustomObject()
        query_object.set_name(self.name)
        query_object.set_type('CAST_TS_Query')
        query_object.set_parent(module.get_kb_object())
        guid = module.get_final_guid(fullname)
        query_object.set_guid(guid)
        query_object.set_fullname(fullname)
        query_object.save()

        for raw_bookmark in self.raw_bookmarks:
            if isinstance(raw_bookmark, Bookmark):
                query_object.save_position(raw_bookmark)
            else:
                query_object.save_position(raw_bookmark.get_bookmark())

        query_object.save_property('checksum.CodeOnlyChecksum', checksum)
        query_object.save_property("CAST_SQL_MetricableQuery.sqlQuery", self.sql)
        if self.vendor is not None:
            query_object.save_property('CAST_SQL_MetricableQuery.vendor', self.vendor)
        if self.incomplete_query:
            query_object.save_property('CAST_SQL_MetricableQuery.incomplete_sql_query', 1)

        log.debug("Detected SQL statement : {}".format(self.sql))

        # Create callLink
        link = create_link('callLink', self.real_caller.get_kb_object(), query_object, position)
        if self.triggeredby:
            link.save_property('physicalLink.triggeredBy', self.triggeredby)
        log.debug(str(link))


class ReactApplication(FrameworkSymbol):
    """
    A ReactJS application.
    """
    
    def __init__(self, name, ast, parent):
        FrameworkSymbol.__init__(self, name, ast, parent)
        self.metamodel_type = 'CAST_ReactJS_Application'
        self.html_fragments = []
    
    def __repr__(self):
        
        result = "reactjs.application("+self.name+")"
        return result
    
    def save(self, file):
        kb_obj = FrameworkSymbol.save(self, file)
        self.kb_symbol = kb_obj
    
    def save_links(self, file):
        
        if not self.html_fragments:
            return
        for html_frag in self.html_fragments:
            node = html_frag.get_ast()
            create_link('relyonLink', self.kb_symbol, html_frag.get_kb_object(),
                        Bookmark(file.get_file(), node.get_begin_line(),
                                 node.get_begin_column(),
                                 node.get_end_line(),
                                 node.get_end_column())
                        )


class ReduxForm(FrameworkSymbol):
    
    def __init__(self, name, ast, parent):
        FrameworkSymbol.__init__(self, name, ast, parent)
        self.metamodel_type = 'CAST_ReactJS_Redux_Form'
        self.resolution = None
    
    def save(self, file):
        kb_obj = FrameworkSymbol.save(self, file)
        self.kb_symbol = kb_obj
    
    def save_links(self, file):
        if not self.resolution:
            return
        ast = self.get_ast()
        parent = ast.parent
        if not isinstance(parent, FunctionCall):
            return
        
        create_link('relyonLink', self.kb_symbol, self.resolution.get_kb_object(),
                    Bookmark(file.get_file(), parent.get_begin_line(),
                             parent.get_begin_column(),
                             parent.get_end_line(),
                             parent.get_end_column())
                    )


class ReactComponent(FrameworkSymbol):
    """
    A ReactJS component.
    """
    
    def __init__(self, name, ast, parent, class_symbol=None):
        FrameworkSymbol.__init__(self, name, ast, parent)
        self.metamodel_type = 'CAST_ReactJS_Component'
        self.render_symbol = None
        self.saved = False
        self.class_symbol = class_symbol

    def get_class_symbol(self):
        return self.class_symbol

    def __repr__(self):
        
        result = "reactjs.application("+self.name+")"
        return result
    
    def save(self, file):
        
        if self.saved:
            return
        self.saved = True
        
        kb_obj = FrameworkSymbol.save(self, file)
        
        self.kb_symbol = kb_obj
    
    def save_links(self, file):
        if self.render_symbol:
            node = self.render_symbol.get_ast()
            create_link('callLink', self.kb_symbol, self.render_symbol.get_kb_object(),
                        Bookmark(file.get_file(), node.get_begin_line(),
                                 node.get_begin_column(),
                                 node.get_end_line(),
                                 node.get_end_column())
                        )
            
            # we also create callLink between render method and html fragment
            i_frag = 1
            while True:
                frag = self.render_symbol.get_symbol("render_fragment_"+str(i_frag), HtmlFragment)
                if not frag:
                    break
                node = frag.get_ast()
                if isinstance(node, list):
                    node = node[0]
                create_link('callLink', self.render_symbol.get_kb_object(), frag.get_kb_object(),
                            Bookmark(file.get_file(), node.get_begin_line(),
                                     node.get_begin_column(),
                                     node.get_end_line(),
                                     node.get_end_column())
                            )
                i_frag += 1


class NodeLink:
    
    def __init__(self, link_type, node, caller, callee, file=None, bookmark=None, triggeredby=None):
        self.link_type = link_type
        self.caller = caller
        self.callee = callee
        self.triggeredby = triggeredby
        module = None
        
        if file:
            module = file
        
        if not module:
            try:
                module = caller.file
            except AttributeError:
                pass
        if not module:
            try:
                module = caller.get_root_symbol()
            except AttributeError:
                pass
        
        if not bookmark:
            self.bookmark = Bookmark(module.get_file(), node.get_begin_line(),
                                     node.get_begin_column(),
                                     node.get_end_line(),
                                     node.get_end_column())
        else:
            self.bookmark = bookmark

    def save(self, progr):
        if isinstance(self.callee, TypeORMEntity) and self.callee.is_nosql:
            if self.callee.tables:
                # we have sql callee
                callees = self.callee.tables
            else:
                link = progr.create_link_to_mongodb_collection(self.link_type,
                                                        self.caller,
                                                        self.callee.name,
                                                        self.callee.get_connection_name(),
                                                        self.bookmark)
                if self.triggeredby:
                    link.save_property('physicalLink.triggeredBy', self.triggeredby)
                return
        else:
            try:
                callees = [self.callee.get_kb_object()]
            except AttributeError:
                callees = [self.callee]
        
        try:
            caller = self.caller.get_kb_object()
        except AttributeError:
            caller = self.caller
        
        if not caller:
            return
        for callee in callees:
            if not callee:
                continue
            else:
                link = create_link(self.link_type,
                            caller,
                            callee,
                            self.bookmark)

                if self.triggeredby:
                    link.save_property('physicalLink.triggeredBy', self.triggeredby)

class LinkToCollection:
    
    def __init__(self, link_type, ast, file, caller: Symbol, callee, triggeredby=None):
        self.bookmark = Bookmark(file.get_file(),
                                 ast.get_begin_line(),
                                 ast.get_begin_column(),
                                 ast.get_end_line(),
                                 ast.get_end_column())
        self.link_type = link_type
        self.caller = caller
        if not isinstance(callee, (MongooseCollection, TypeORMEntity, MongodbCollection)):
            log.debug("Problem : invalid callee "+str(self.callee)+"for a MongoDBLink")
        
        self.callee = callee
        self.triggeredby=triggeredby
    
    def save(self, progr):
        if hasattr(self.callee, "database"):
            database = self.callee.database
        else:
            database = self.callee
        link = progr.create_link_to_mongodb_collection(self.link_type,
                                                       self.caller,
                                                       self.callee.name,
                                                       database.get_connection_name(),
                                                       self.bookmark)
        if self.triggeredby:
            link.save_property('physicalLink.triggeredBy', self.triggeredby)

class SequelizeOperation:
    """
    A sequelize entity operation
    """

    def __init__(self, name_variable, model_variable, file, api_operation, caller, bookmark):
        self.name_variable = name_variable
        self.model_variable = model_variable
        self.file = file
        self.api_operation = api_operation
        self.caller = caller
        self.bookmark = bookmark


class S3Bucket(FrameworkSymbol):
    """
    A S3Bucket
    """
    
    def __init__(self, name, ast, file):
        
        FrameworkSymbol.__init__(self, name, ast, file)
        self.metamodel_type = 'CAST_NodeJS_S3_Bucket'
        if name == '{}':
            self.name = 'Unknown S3 Bucket'
            self.metamodel_type = 'CAST_NodeJS_Unknown_S3_Bucket'
    
    def save(self, parent):
        fullname = self.metamodel_type+"."+self.name
        new_object = CustomObject()
        self.kb_symbol = new_object
        if self.name == 'Unknown S3 Bucket':
            new_object.set_name('Unknown')
        else:
            new_object.set_name(self.name)
        new_object.set_type(self.metamodel_type)
        new_object.set_fullname(fullname)
        new_object.set_guid(fullname)
        new_object.set_parent(self.file.get_file().get_project())
        new_object.save()
        if self.metamodel_type == 'CAST_NodeJS_S3_Bucket':
            save_datasensitivity(self.name, new_object)
        if self.ast:
            position = Bookmark(self.file.get_file(),
                                self.ast.get_begin_line(),
                                self.ast.get_begin_column(),
                                self.ast.get_end_line(),
                                self.ast.get_end_column()+1)
            
            new_object.save_position(position)
        
        return new_object


class AngularProvider:
    
    def __init__(self, name: str, injected: Identifier or Class, path: str):
        """
        :param name: name through which a class can be injected
        :param injected: the injected identifier (which
        :param path: the path to the module in which the
        """
        self.name = name
        self._class = None
        self.useValue = None
        if isinstance(injected, Class):
            self._class = injected
        elif isinstance(injected, Identifier):
            self.useValue = injected
        self.path = path
    
    def __eq__(self, other):
        return self.name == other.name and self._class == other._class and self.path == other.path


class MailSender(Symbol):
    
    def __init__(self, ast, parent, framework_used: str):
        i_num = 1
        self.name = 'an Email'
        self.parent = parent
        self.ast = ast
        Symbol.__init__(self, self.name, parent)
        self.framework_used = framework_used
        self.metamodel_type = 'CAST_NodeJS_Email'
    
    def save(self, module):
        fullname = self.parent.get_fullname()+'/'+self.metamodel_type
        old_fullname = self.parent.get_old_fullname() + '/' + self.metamodel_type

        position = Bookmark(module.get_file(),
                            self.ast.get_begin_line(),
                            self.ast.get_begin_column(),
                            self.ast.get_end_line(),
                            self.ast.get_end_column()+1)
        
        program = module.get_program()
        
        service_object = CustomObject()
        
        service_object.set_name(self.name)
        service_object.set_type(self.metamodel_type)
        
        service_object.set_parent(self.parent.get_kb_object())

        old_guid = module.get_final_guid(old_fullname)
        service_object.set_guid(old_guid)
        service_object.set_fullname(fullname)
        service_object.save()
        service_object.save_position(position)
        
        create_link('callLink', self.parent.get_kb_object(), service_object, position)


class AWSDynamoDBEndpoint:
    
    def __init__(self, name: str, module):
        self.metamodel_type = 'CAST_NodeJS_DynamoDB_Endpoint'
        self.name = name
        self.raw_bookmarks = []
        self.module = module  #use to access the project
    
    def save(self):
        custom_obj = CustomObject()
        self.kb_symbol = custom_obj
        custom_obj.set_name(self.name)
        project_fullname_normalized = get_project_fullname(self.module.get_file().get_project())
        fullname = '{}.{}'.format(project_fullname_normalized, self.name)
        guid = '{}/ts/CAST_NodeJS_DynamoDB_Endpoint/{}'.format(project_fullname_normalized, self.name)
        custom_obj.set_parent(self.module.get_file().get_project())
        custom_obj.set_fullname(fullname)
        custom_obj.set_guid(fullname)
        custom_obj.set_type('CAST_NodeJS_DynamoDB_Endpoint')
        custom_obj.save()
        for raw_bookmark in self.raw_bookmarks:
            custom_obj.save_position(raw_bookmark.get_bookmark())


def save_datasensitivity(name: str, kb_symbol: CustomObject):
    """
    Should be called in the save of any nosql table. Check if the table name is sensitive
    """
    name = name.lower()
    if name in DataSensitivitySettings.custom:
        kb_symbol.save_property('CAST_Data_Sensitive.Custom_DataSensitive_indicator',
                                DataSensitivitySettings.custom[name])
    if name in DataSensitivitySettings.gdpr:
        kb_symbol.save_property('CAST_Data_Sensitive.GDPR_indicator', DataSensitivitySettings.gdpr[name])
    if name in DataSensitivitySettings.pci:
        kb_symbol.save_property('CAST_Data_Sensitive.PCI_indicator', DataSensitivitySettings.pci[name])


class AWSDynamoDBTable:
    
    def __init__(self, name: str, endpoint_name: str):
        self.name = name
        self.ast = None
        self.module = None
        self.endpoint_name = endpoint_name
        self.raw_bookmarks = []
        self.callers = []
    
    def save(self, dynamodb_endpoints: OrderedDict):
        if self.endpoint_name not in dynamodb_endpoints:
            log.debug("Problem, the endpoint was not created")
            return
        else:
            endpoint = dynamodb_endpoints[self.endpoint_name]
        custom_obj = CustomObject()
        self.kb_symbol = custom_obj
        custom_obj.set_name(self.name)
        custom_obj.set_parent(endpoint.kb_symbol)
        fullname = '{}.{}'.format(endpoint.kb_symbol.fullname, self.name)
        guid = '{}/CAST_NodeJS_DynamoDB_Endpoint/{}'.format(endpoint.kb_symbol.fullname, self.name)
        custom_obj.set_parent(endpoint.kb_symbol)
        custom_obj.set_fullname(fullname)
        custom_obj.set_guid(fullname)
        custom_obj.set_type('CAST_NodeJS_DynamoDB_Table')
        custom_obj.save()
        save_datasensitivity(self.name, custom_obj)
        for raw_bookmark in self.raw_bookmarks:
            custom_obj.save_position(raw_bookmark.get_bookmark())
        
        for caller in self.callers:
            if len(self.raw_bookmarks) == 0:
                custom_obj.save_position(caller.raw_bookmark.get_bookmark())
            link = create_link(caller.link_type, caller.caller.get_kb_object(), custom_obj)
            if caller.triggeredby:
                link.save_property('physicalLink.triggeredBy', caller.triggeredby)

class AWSDynamoDBTableCaller:
    
    def __init__(self, caller, ast: Node, module: SourceFile, link_type: str, triggeredby:str=None):
        self.caller = caller
        self.raw_bookmark = RawBookmark(ast, module)
        self.link_type = link_type
        self.triggeredby = triggeredby


class RawBookmark:
    """
    raw bookmark save the ast and module.
    It is usefull for unitests
    """
    
    def __init__(self, ast: Node, module: SourceFile = None):
        self.ast = ast
        if not module:
            try:
                if isinstance(ast, Token) and not hasattr(ast, "parent"):
                    parent = ast.parent_curly
                else:
                    parent = ast.parent
                while True:
                    if isinstance(parent, Root):
                        break
                    parent = parent.parent
                module = parent.module
            except:
                pass
        self.module = module
    
    def get_bookmark(self):
        return Bookmark(self.module.get_file(),
                        self.ast.get_begin_line(),
                        self.ast.get_begin_column(),
                        self.ast.get_end_line(),
                        self.ast.get_end_column()+1
                        )
    
    def __eq__(self, other):
        if isinstance(other, RawBookmark):
            return self.__key() == other.__key()
        return NotImplemented
    
    def __key(self):
        return (self.ast, self.module)
    
    def __hash__(self):
        return hash(self.__key())


class AWSSNSPublish:
    
    def __init__(self, topic_name, caller, bookmarks, real_caller=None):
        if topic_name == "{}":
            self.topic_name = 'Unknown'
            self.metamodel = 'CAST_NodeJS_AWS_SNS_Unknown_Publisher'
        else:
            self.metamodel = 'CAST_NodeJS_AWS_SNS_Publisher'
            self.topic_name = topic_name
        self.caller = caller
        if real_caller:
            self.real_caller = real_caller
        else:
            self.real_caller = caller
        if isinstance(bookmarks, list):
            self.raw_bookmarks = bookmarks
        elif isinstance(bookmarks, RawBookmark):
            self.raw_bookmarks = [bookmarks]
        else:
            self.raw_bookmarks = []
    
    def save(self):
        custom_obj = CustomObject()
        self.kb_symbol = custom_obj
        custom_obj.set_name(self.topic_name)
        caller = self.caller.get_kb_object()
        custom_obj.set_parent(self.caller.get_kb_object())
        guid = '{}/{}/{}'.format(caller.fullname, self.metamodel, self.topic_name)
        fullname = '{}.{}'.format(caller.fullname, self.topic_name)
        custom_obj.set_type(self.metamodel)
        old_guid = '{}/{}/{}'.format(self.caller.get_old_fullname(), self.metamodel, self.topic_name)
        try:
            old_guid = self.caller.get_root_symbol().get_old_final_guid(old_guid)
        except AttributeError:
            pass
        custom_obj.set_fullname(fullname)
        custom_obj.set_guid(old_guid)
        custom_obj.save()

        for raw_bookmark in self.raw_bookmarks:
            custom_obj.save_position(raw_bookmark.get_bookmark())
        
        if self.caller:
            create_link("callLink", self.real_caller.get_kb_object(), custom_obj)


class AWSSNSSubscriber:
    
    def __init__(self, topic_name: str, bookmarks: [RawBookmark], protocol: str, endpoint: str, parent):
        if topic_name == "{}":
            self.topic_name = 'Unknown'
            self.metamodel = 'CAST_NodeJS_AWS_SNS_Unknown_Subscriber'
        else:
            self.metamodel = 'CAST_NodeJS_AWS_SNS_Subscriber'
            self.topic_name = topic_name
        
        if isinstance(bookmarks, list):
            self.raw_bookmarks = bookmarks
        elif isinstance(bookmarks, RawBookmark):
            self.raw_bookmarks = [bookmarks]
        else:
            self.raw_bookmarks = []
        
        self.protocol = protocol
        self.endpoint = endpoint
        self.parent = parent
    
    def save(self):
        
        if not hasattr(self.parent, 'saved_sns_subscriptions'):
            self.parent.saved_sns_subscriptions = OrderedDict()
        if self.topic_name in self.parent.saved_sns_subscriptions:
            custom_obj = self.parent.saved_sns_subscriptions[self.topic_name]
            self.kb_symbol = custom_obj
        else:
            custom_obj = self.save_first_time()
            self.parent.saved_sns_subscriptions[self.topic_name] = custom_obj
        
        for raw_bookmark in self.raw_bookmarks:
            custom_obj.save_position(raw_bookmark.get_bookmark())
        
        if self.protocol in ['email', 'sms', 'email-json']:
            self.save_endpoint()
        
        elif self.protocol.startswith('http'):
            self.save_http_endpoint()
        
        elif self.protocol == 'sqs':
            self.save_sqs_endpoint()
        
        elif self.protocol == 'lambda':
            self.save_lambda_endpoint()
    
    def save_lambda_endpoint(self):
        lambda_name = self.endpoint
        if lambda_name == "{}":
            metamodel = "CAST_NodeJS_AWS_Unknown_Lambda_Call"
            lambda_name = 'Unknown'
        else:
            metamodel = "CAST_NodeJS_AWS_Lambda_Call"
            if ":" in lambda_name:
                lambda_name = arn2name4lambda(lambda_name)
        fullname = self.kb_symbol.fullname+'.'+lambda_name
        service_object = CustomObject()
        service_object.set_name(lambda_name)
        service_object.set_type(metamodel)
        module = self.parent.get_root_symbol()
        service_object.set_parent(self.kb_symbol)
        old_guid = self.kb_symbol.old_fullname + '/' + metamodel + '/' + lambda_name
        old_guid = module.get_old_final_guid(old_guid)
        service_object.set_guid(old_guid)
        service_object.set_fullname(fullname)
        service_object.save()

        for raw_bookmark in self.raw_bookmarks:
            service_object.save_position(raw_bookmark.get_bookmark())
        create_link('callLink', self.kb_symbol, service_object)
    
    def save_sqs_endpoint(self):
        queue_name = self.endpoint
        if queue_name == "{}":
            metamodel = "CAST_TS_AWS_SQS_Unknown_Publisher"
            queue_name = 'Unknown'
        else:
            metamodel = "CAST_TS_AWS_SQS_Publisher"
        fullname = self.kb_symbol.fullname+'.'+queue_name
        service_object = CustomObject()
        service_object.set_name(queue_name)
        service_object.set_type(metamodel)
        module = self.parent.get_root_symbol()
        service_object.set_parent(self.kb_symbol)
        old_guid = self.kb_symbol.old_fullname + '/' + metamodel + '/' + queue_name
        old_guid = module.get_old_final_guid(old_guid)

        service_object.set_guid(old_guid)
        service_object.set_fullname(fullname)
        service_object.save()

        for raw_bookmark in self.raw_bookmarks:
            service_object.save_position(raw_bookmark.get_bookmark())
        if queue_name != 'Unknown':
            service_object.save_property('CAST_AWS_SQS_Sender.queueName', queue_name)
        create_link('callLink', self.kb_symbol, service_object)
    
    def save_http_endpoint(self):
        metamodel = 'CAST_NodeJS_PostHttpRequestService'
        fullname = self.kb_symbol.fullname+'/'+metamodel
        uri = self.endpoint
        service_object = CustomObject()
        service_object.set_name(uri)
        service_object.set_type(metamodel)
        module = self.parent.get_root_symbol()
        service_object.set_parent(self.kb_symbol)

        old_guid = self.kb_symbol.old_fullname + '/' + metamodel
        old_guid = module.get_old_final_guid(old_guid)
        service_object.set_guid(old_guid)
        service_object.set_fullname(fullname)
        service_object.save()

        service_object.save_property('CAST_ResourceService.uri', uri)
        for raw_bookmark in self.raw_bookmarks:
            service_object.save_position(raw_bookmark.get_bookmark())
        create_link('callLink', self.kb_symbol, service_object)
    
    def save_endpoint(self):
        if 'email' in self.protocol:
            metamodel = 'CAST_NodeJS_Email'
            name = 'an Email'
        
        elif self.protocol == 'sms':
            metamodel = 'CAST_NodeJS_SMS'
            name = 'an SMS'

        old_guid = '{}/{}/{}'.format(self.kb_symbol.old_fullname, metamodel, self.protocol)
        if old_guid in self.kb_symbol.saved_endpoints:
            custom_obj = self.kb_symbol.saved_endpoints[old_guid]
        else:
            custom_obj = self.save_email_or_sms_first_time(name, metamodel, old_guid)
            self.kb_symbol.saved_endpoints[old_guid] = custom_obj

        for raw_bookmark in self.raw_bookmarks:
            custom_obj.save_position(raw_bookmark.get_bookmark())
    
    def save_email_or_sms_first_time(self, name, metamodel, guid):
        custom_obj = CustomObject()
        custom_obj.set_name(name)
        custom_obj.set_parent(self.kb_symbol)
        
        custom_obj.set_type(metamodel)
        custom_obj.set_guid(guid)
        custom_obj.save()
        create_link('callLink', self.kb_symbol, custom_obj)
        return custom_obj
    
    def save_first_time(self):
        
        custom_obj = CustomObject()
        self.kb_symbol = custom_obj
        self.kb_symbol.saved_endpoints = OrderedDict()
        custom_obj.set_name(self.topic_name)
        parent = self.parent.get_kb_object()
        custom_obj.set_parent(parent)
        custom_obj.set_type(self.metamodel)
        fullname = '{}.{}'.format(parent.fullname, self.topic_name)
        custom_obj.set_fullname(fullname)
        old_guid = '{}/{}/{}'.format(self.parent.get_old_fullname(), self.metamodel, self.topic_name)
        try:
            old_guid = self.caller.get_root_symbol().get_old_final_guid(old_guid)
        except AttributeError:
            pass
        custom_obj.set_guid(old_guid)
        custom_obj.save()
        custom_obj.old_fullname = '{}.{}'.format(self.parent.get_old_fullname(),self.topic_name)
        return custom_obj


class AWSLambdaInvokeObject:
    
    def __init__(self, name, raw_bookmark: RawBookmark, caller):
        self.name = name.value  # lambda function name
        self.raw_bookmark = raw_bookmark
        self.caller = caller  # caller, which will be the parent
        self.ast_nodes = name.ast_nodes
    
    def save(self, _):
        custom_obj = CustomObject()
        self.kb_symbol = custom_obj
        if self.name == '<Unknown>':
            name = 'Unknown'
            metamodel = "CAST_NodeJS_AWS_Unknown_Lambda_Call"
        else:
            name = self.name
            metamodel = "CAST_NodeJS_AWS_Lambda_Call"
        
        custom_obj.set_name(name)
        caller = self.caller.get_kb_object()
        custom_obj.set_parent(self.caller.get_kb_object())
        guid = '{}/{}/{}'.format(caller.fullname, metamodel, name)
        fullname = '{}.{}'.format(caller.fullname, name)
        custom_obj.set_type(metamodel)
        custom_obj.set_fullname(fullname)
        try:
            guid = self.caller.get_root_symbol().get_final_guid(guid)
        except:
            pass
        try:

            old_guid = self.caller.get_old_fullname()+'/'+metamodel+'/'+name
            try:
                old_guid = self.caller.get_root_symbol().get_old_final_guid(old_guid)
            except AttributeError:
                pass
            custom_obj.set_guid(old_guid)
        except:
            log.warning('Problem calculating old guid for SNS protocol ' + self.protocol)
            log.warning(traceback.format_exc())
            custom_obj.set_guid(guid)
        custom_obj.save()
        
        custom_obj.save_position(self.raw_bookmark.get_bookmark())


        try:
            for ast_node in self.ast_nodes:
                bookmark = get_bookmark_from_ast(ast_node)
                if bookmark:
                    custom_obj.save_position(bookmark)
        except:
            pass
        
        create_link("callLink", self.caller.get_kb_object(), custom_obj)
