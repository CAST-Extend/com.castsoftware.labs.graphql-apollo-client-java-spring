from typescript_dependencies.common_tools import DefaultOrderedDict
from .light_parser import Parser, BlockStatement, Statement, Term, Seq,\
    Optional, Repeat, Node, Or, Not, NotFollowedBy, \
    NodePath, AnyPath, Token, Lookahead, TokenIterator
from .lexer import TypeScriptLexer, Keyword, String, Number, Generic,\
    Name, WeakKeyword, LineFeed, StringTemplate as ST, Operator, \
    is_token_subtype, Punctuation
from .tsx_lexer import TypeScriptXLexer
from cast.analysers import log, Bookmark
import itertools
import re, traceback
from collections import OrderedDict
from pygments.token import Token as pygmentsToken, Whitespace, Comment
pure_binary_operators = ["==", "!=", "===", "||", '&&', '<', '===', '!==',
                         '/', '*', '**', '<<', '>>', '>>>', '^', '|', '&', '>', '??']
unary_and_binary_operators = ['+', '-']
all_binary_operators = pure_binary_operators + unary_and_binary_operators


def climb(node, types):
    """
    Climb an AST from a Node only if the type 
    of the parent nodes coincides with those 
    given in the list "types":
    
        A[
          B[
               Indentifier['a']
          ]
        ]
        
        climb(a, [B, A])  -->  A
        climb(a, [B])     -->  B
        climb(a, [A])     --> None
    
    """
    if not isinstance(node, Node):
        return

    for typ in types:
        parent = node.parent
        if not parent:
            return
        try:
            if isinstance(parent, typ):
                node = parent
            else:
                return
        except:
            return

    return node

def is_linefeed_or_semicolon(token):
    if token == ';':
        return True

    if isinstance(token, Token) and token.type == LineFeed:
        return True

    return False


def get_descendants_multiple_kinds(node, kinds, escaping_nodes=[]):
    result = []
    if isinstance(node, list):
        for sub_node in node:
            if type(sub_node) in kinds:
                result.append(sub_node)
            if not isinstance(sub_node, tuple(escaping_nodes)):
                result.extend(get_descendants(sub_node, kinds, escaping_nodes))
        return result

    for sub_node in node.get_sub_nodes():
        if type(sub_node) in kinds :
            result.append(sub_node)
        if not isinstance(sub_node, tuple(escaping_nodes)):
            result += get_descendants(sub_node, kinds, escaping_nodes)

    return result

def get_descendants(node, kind, escaping_nodes=[]):
    """
    Get all descendants of a node of a certain kind
    """
    if isinstance(kind, (tuple, list)):
        return get_descendants_multiple_kinds(node, kind, escaping_nodes)
    result = []
    if isinstance(node, list):
        for sub_node in node:
            if type(sub_node) == kind :
                result.append(sub_node)
            if not isinstance(sub_node, tuple(escaping_nodes)):
                result.extend(get_descendants(sub_node, kind, escaping_nodes))
        return result

    for sub_node in node.get_sub_nodes():
        if type(sub_node) == kind :
            result.append(sub_node)
        if not isinstance(sub_node, tuple(escaping_nodes)):
            result += get_descendants(sub_node, kind, escaping_nodes)

    return result


def set_linefeed_as_whitespace(node):
    
    if isinstance(node, list):
        children = node
    else:
        try:
            children = node.children
        except :
            return

    for sub_node in children:
        try:
            if sub_node.type == LineFeed:
                sub_node._is_whitespace = True
        except :
            pass
        set_linefeed_as_whitespace(sub_node)


def handle_parsing_within_html_tag(node):
    """
    We basically remove the parsing within html_tags except for what is inside curly bracket
    and for the first token within an Opening Tag (we need to have an identifier for the resolution)
    We also substitute GenericsParameter nodes with OpeningHtmlTag
    """
    if isinstance(node, (Token, CurlyBracket, SelfClosingHtmlTag)):
        return [node]
    elif isinstance(node, ObjectCurlyBracket):
        # we replace the objectCurlyBracket with a standard CurlyBracket
        curly_bra = CurlyBracket()
        curly_bra.children = node.children
        if hasattr(node, "parent"):
            curly_bra.parent = node.parent
        return [curly_bra]

    to_return = []
    for tok in node.get_children():
        to_return = to_return + handle_parsing_within_html_tag(tok)

    return to_return


def get_descendants_with_escape(node, kind, escaping_nodes):
    """
    Get all descendants of a node of a certain kind
    """
    result = []
    if isinstance(node, list):
        for sub_node in node:
            if isinstance(sub_node, kind):
                result.append(sub_node)
            elif isinstance(sub_node, escaping_nodes):
                continue
            result.extend(get_descendants(sub_node, kind))
        return result

    for sub_node in node.get_sub_nodes():
        if type(sub_node) == kind:
            result.append(sub_node)
        elif isinstance(sub_node, escaping_nodes):
            continue
        result += get_descendants(sub_node, kind)

    return result





class CanBeExported:

    def __init__(self):
        self.is_exported = False
        self.is_default_export = False
        self.is_require_export = False

    def on_end_export(self):
        tokens = self.get_children()
        tok = next(tokens)
        if isinstance(tok, Token):
            text = tok.text
        else:
            text = None
        while text not in ["class", "function", "interface", "namespace", "module", "=>"]:
            if text == "export":
                self.is_exported = True
                if tokens.look_next() == "=":
                    self.is_require_export = True

            # check for default export
            if text == "default":
                self.is_default_export = True
            tok = next(tokens)
            if isinstance(tok, Token):
                text = tok.text
            else:
                text = None

                

def get_light_pattern(is_tsx= False):
    if is_tsx :
        lexer = TypeScriptXLexer
    else:
        lexer = TypeScriptLexer
    return (lexer,
            [Parenthesis, CurlyBracket, Bracket, ObjectCurlyBracket],
            # GenericsParameter should be parsed before Declare
            [GenericsParameter, OpeningHtmlTag, ClosingHtmlTag],
            # Declare should be parsed before ArrowExpression and Function
            [HtmlTag],
            [TSType, FunctionType, Decorator, Import, ReExport, Declare, SelfClosingHtmlTag],

            # ArrowExpression should be declared before Function
            # because they can be used for defining the function type
            [ArrowExpression],
            [Namespace, Function, Class, Interface, Enum],
            [Export],

            {NodePath(AnyPath, Class, CurlyBracket):[Field, Method],
             NodePath(AnyPath, Interface, CurlyBracket): [Field, InterfaceMethod],
             NodePath(AnyPath, ObjectCurlyBracket): [ObjectMethod]

            },
            {NodePath(AnyPath, Class, CurlyBracket, Method, Parenthesis): [ConstructorField]
            }
            )


def light_parse(text, is_tsx = False):
    """
    First pass of parsing : create high level AST
    """
    light_pattern = get_light_pattern(is_tsx)
    parser = Parser(*light_pattern)
    ast = list(parser.parse(text))
    set_linefeed_as_whitespace(ast)
    # we first refine ArrowExpression to check if it corresponds to arrow_function, arrow_method or function_type
    refine_arrow_expressions(ast)
    return ast


def _parse(text, is_tsx = False):
    """
    Intermediate step in full parsing, 
    useful for debugging the AST before
    the handling expressions manually.
    
    WARNING!!!: for efficiency reasons (less loops) the nodes
    below should be grouped as much as possible!
    """
    
    light_pattern = get_light_pattern(is_tsx)

    full_pattern = light_pattern + (
                    [StringTemplate],
                    # Instantiation must be before Return
                    [Instantiation],
                    # Return must be before IfThenElseBlock
                    [Return],
                    # here add additional nodes (statements, structure, ...)
                    [VariableDeclaration, TryBlock, CatchBlock,
                     FinallyBlock, SwitchCase, ForBlock, WhileBlock, DoWhileBlock,
                     Break, Continue, Throw, IfThenElseBlock],
                    # If must be parsed after IfThenElseBlock
                    [If],
                    [ExpressionStatement],
                    # await and UnaryOperation must be after ExpressionStatement
                    [Await, UnaryOperation]
                    )

    parser = Parser(*full_pattern)

    return parser.parse(text)


def parse(text, is_tsx = False, module = None):
    """
    Second pass of parsing : create method body level AST
    """
    root = Root(token for token in _parse(text, is_tsx))
    root.module = module
    handle_expression(root)


    set_linefeed_as_whitespace(root)

    # we first refine ArrowExpression to check if it corresponds to arrow_function, arrow_method or function_type
    refine_arrow_expressions(root)
    return root


def is_parenthesis(self):
    try:
        return self.is_parenthesis()
    except:
        return False


def is_identifier_but_not_member(token):
    try:
        if is_identifier(token) and not token.previous_is_dot :
            return True
        else :
            return False
    except:
        return False


def is_identifier(token):
    """
    Returns True if Identifier instance, or if token
    compatible with identifier nomenclature
    
    TODO: revise whether we can remove the exception code.
    """
    try:
        return token.is_identifier()
    except AttributeError:
        # @todo: handle Name.Variable
        if token:
            try:
                typ = token.type
            except AttributeError:
                typ = None

            if not typ == Generic:
                return False
            if token.is_whitespace():
                return False
             
            if token in all_binary_operators:
                return False 

            return True
            
        return False 


def is_string_template(token):
    return token.type and token.type == ST


def is_string_literal(token):
    # TODO: find origin of None so
    # that we don't need a try-except
    try:
        return token.type and token.type == String
    except AttributeError:
        return False


def is_number_literal(token):
    return token.type and token.type == Number


def is_namespace(node):
    return isinstance(node, Namespace)


def is_function_type(node):
    """
    some ArrowExpression are actually FunctionType
    """
    if not isinstance(node, ArrowExpression):
        return False

    if hasattr(node, 'parent'):
        parent = node.parent
    else:
        return False
    while True:
        if isinstance(parent, TSType):
            return True
        if hasattr(parent, 'parent'):
            parent = parent.parent
        else:
            return False

def is_function(node):
    if isinstance(node, Function):
        return True
    if is_function_type(node):
        return False
    if isinstance(node, ArrowExpression) and node.is_arrow_function:
        return True

    if isinstance(node, FunctionType) and hasattr(node, "parent") and isinstance(node.parent, (ObjectCurlyBracket, IfTernary)):
        return True

    return False

def is_arrow_function(node):
    return isinstance(node, ArrowExpression)and node.is_arrow_function


def is_class(node):
    if isinstance(node, Class):
        return True
    try:
        return node.is_external_class()
    except:
        return False


def is_interface(node):
    return isinstance(node, Interface)


def is_method(node, parent_symbol_is_interface=True):
    if isinstance(node, ArrowExpression) and node.is_arrow_method:
        return True
    if isinstance(node, Method):
        if parent_symbol_is_interface:
            return True
        for child in node.get_children():
            if isinstance(child, CurlyBracket):
                return True
            if child == 'abstract':
                return True

    return False


def is_field(node):
    return isinstance(node, Field)


def is_member_access(node):
    return isinstance(node, MemberAccess)


def is_import(node):
    return isinstance(node, Import)


def is_variable_declaration(node):
    return isinstance(node, VariableDeclaration)


def is_re_export(node):
    return isinstance(node, ReExport)


def is_export(node):
    return isinstance(node, Export)


def is_enum(node):
    return isinstance(node, Enum)


def is_method_call(node):
    return isinstance(node, MethodCall)


def is_function_call(node):
    return isinstance(node, FunctionCall)


def is_declare(node):
    return isinstance(node, Declare)


def is_if_then_else(self):
    try:
        return self.is_if_then_else()
    except:
        return False


def is_for(self):
    try:
        return self.is_for()
    except AttributeError:
        return False


def is_while(self):
    try:
        return self.is_while()
    except AttributeError:
        return False


def is_do_while(self):
    try:
        return self.is_do_while()
    except AttributeError:
        return False


class Root(Node):
    """topmost node in the AST"""

    def __init__(self, tokens):
        super().__init__()
        self.children = list(tokens)
        self.parent = None

    def __iter__(self):
        return (child for child in self.children)

    def __getitem__(self, key):
        children = list(self.get_children())  # removes whitespaces
        return children[key]

    def shift_ast(self, ast):
        '''
        When we parse a TypeScript fragment, we need to shift bookmarks
        '''
        if not hasattr(self, 'token_text'):
            return
        if not isinstance(ast, list):
            return

        for a in ast:
            if hasattr(a, 'begin_line'):
                if a.begin_line == 1:
                    a.begin_column = a.begin_column + self.token_text.get_begin_column() - 1
                if a.end_line == 1:
                    a.end_column = a.end_column + self.token_text.get_begin_column() - 1
                a.begin_line = a.begin_line + self.token_text.get_begin_line() - 1
                a.end_line = a.end_line + self.token_text.get_begin_line() - 1
            if hasattr(a, 'children'):
                self.shift_ast(a.children)


class WithResolution:
    """
    For something resolvable
    """
    def __init__(self):
        
        # resolution made
        self._resolutions = []

    def _get_resolutions(self):
        """
        The possible elements it resolve to.
        """
        to_return = []
        for r in self._resolutions:
            if not r in to_return:
                to_return.append(r)
        return to_return

    def get_resolutions(self):
        """
        The possible elements it resolve to.
        """
        resols = self._get_resolutions()
        if resols:
            return resols
        decl = self.get_declaration()
        if decl:
            return [decl]
        return []

    def _get_resolution(self):
        """
        Handy when non-ambiguous resolution
        is needed
        """
        if len(self._resolutions) == 1:
            return self._resolutions[0]

        return None

    def get_resolution(self):
        resol = self._get_resolution()
        if resol:
            return resol
        return self.get_declaration()

    def set_resolutions(self, resolutions):
        self._resolutions = resolutions

    def add_resolution(self, resolution):
        if not resolution in self._resolutions:
            self._resolutions.append(resolution)

    def get_declaration(self):
        if not hasattr(self, 'declaration'):
            return
        return self.declaration

       
class Parenthesis(BlockStatement):

    begin = '('
    end = ')'
    
    def is_empty(self):
        if len(list(self.get_children())) == 2:
            return True
        return False
    
    def is_parenthesis(self):
        return True

def is_opening_object_curly_bracket(token, stream):
    if token == "{" and hasattr(token, "is_object_curlybracket"):
        return True
    else :
        return False

class Counter:

    def __init__(self):
        self.value = 0

class Identifier(Node):
    """
    Hand created
    """

    def __init__(self, token):
        Node.__init__(self)
        self.children = [token]
        self.resolved_as = None
        self.text = self.children[0].text
        self.is_imported_from_framework = None
        self.original_name = None

    def resolve_to(self, symbol):
        """
        Say that the identifier is resolved to something
        """
        self.resolved_as = symbol

    def get_resolution(self):
        if self.resolved_as:
            return self.resolved_as
        return self.get_declaration()

    def get_declaration(self):
        if hasattr(self, 'declaration'):
            return self.declaration
        return None

    def get_variable_type(self, seen_asts=None):
        """
        return the ast_node corresponding to the declared variable type.
        This function is designed to be fast rather than exhaustive
        """
        if not seen_asts:
            seen_asts = []
        if self in seen_asts:
            return
        seen_asts.append(self)
        if not hasattr(self, 'parent'):
            return
        if isinstance(self.parent, VariableDeclaration):
            return self.parent.get_vartypes().get(self.get_name(), None)
        if isinstance(self.parent, Parameter) and self.parent.get_variable_type():
            return self.parent.get_variable_type()
        if isinstance(self.parent, Field):
            resol = self
        else:
            resol = self.get_resolution()

        if not resol:
            return

        if not hasattr(resol, "parent"):
            return

        result = None
        if isinstance(resol.parent, Field):
            result = resol.parent.get_variable_type(seen_asts)
        elif isinstance(resol.parent, Parameter):
            result = resol.parent.get_variable_type(seen_asts)

        if result:
            return result

        # we check if the assigned value exists and has a type defined
        for id in [self, resol]:
            if not hasattr(id, "get_assigned_expression") or id==self:
                continue
            if hasattr(id.get_assigned_expression(), "get_variable_type"):
                result = id.get_assigned_expression().get_variable_type(seen_asts)
                if result:
                    return result

            if isinstance(id.parent, Assignment):
                result = id.parent.get_variable_type(seen_asts)
                if result:
                    return result

    def get_enclosing_callable_ast(self):

        parent = self.parent
        while parent and not isinstance(parent, (Function, Method, ArrowExpression)):
            if not hasattr(parent, 'parent'):
                return
            parent = parent.parent

        return parent

    def get_text(self):
        """
        Deprecated, use get_name
        """
        text = self.children[0].text
        if text.startswith('"') or text.startswith("'"):
            return text[1:-1]
        return text

    def get_name(self):
        """
        Remove the extra quotes if exist
        """
        try:
            text = self.children[0].text
        except:
            text = self.children[0].get_name()

        if text:
            if text.startswith('"') or text.startswith("'"):
                return text[1:-1]
        # return an empty string if the text is None
        text = text or ""

        return text
    def is_identifier(self):
        return True

    def __eq__(self, identifier):
        """
        Overload to compare with string
        """
        if isinstance(identifier, str):
            return self.children[0] == identifier
        # fallback on normal eq
        return object.__eq__(self, identifier)

    def __hash__(self):
        return object.__hash__(self)

    def resolve_assigned_expression(self):
        """Generalize the 'get_assigned_expression' by adding
        resolution to the search.

        TODO:
        ----
        For more complex scenarios, we might consider returning
        a list because of potential ambiguity.
        """
        expression = self.get_assigned_expression()
        if expression:
            return expression
        else:
            resolution = self.get_resolution()
            if isinstance(resolution, Identifier):
                return resolution.get_assigned_expression()

    def get_assigned_expression(self):
        """Return the expression assigned to the variable
        in the enclosing statement.
        """
        if not hasattr(self, "parent"):
            return
        declaration = climb(self, [VariableDeclaration])
        if not declaration and isinstance(self.parent, CurlyBracket):
            declaration = climb(self.parent, [VariableDeclaration])

        if declaration:
            if self.get_name() in declaration.get_expressions():
                return declaration.get_expressions()[self.get_name()]

        assignment = climb(self, [Assignment])
        if assignment:
            expression = assignment.get_right_expression()
            if not expression == self:
                return expression

        exported_variable = climb(self, [Export])
        if exported_variable:
            return exported_variable.get_value()

        parameter = climb(self, [Parameter])
        if parameter:
            expression = parameter.get_value()
            return expression

        return None

    def get_dictionary(self):
        """should be used when we know that the identifier
        should have a dictionary assigned to it"""
        try:
            return self.get_resolution().get_assigned_expression().get_dictionary()
        except AttributeError:
            return None

    def get_original_name(self):
        """
        Return the original name of the called identifier.
        import {toto as lala} from 'base';
        identifier.get_original_name() = toto
        """
        return self.original_name

    def get_enclosing_field(self):
        """
        Find and return the Field enclosing the given identifier.
        """
        if not self.parent:
            return None
        parent = self.parent
        while parent and not isinstance(parent, Field):
            if not hasattr(parent, "parent"):
                return None
            parent = parent.parent

        return parent


class ObjectCurlyBracket(BlockStatement):
    """
    ObjectCurlyBracket are "dictionaries" or "map" :
var a_dict = {
 a : "a",
 b : 1,
 m1(){
 }
}
In the parsing to know if we have an ObjectCurlyBracket or a "standard" CurlyBracket,
we check if the previous token is one of ["=", "return", "(", ",", "[", "{"] or ":" in some cases.
(the "is_object_curlybracket" is added to the opening "{" token in the lexer).

Some specific cases we have to handle:
  - Inside html_tags we might have (<tag prop={value}).
    In that case the parser creates an ObjectCurlyBracket
    which is subtituted with standard CurlyBracket in handle_parsing_within_html_tag()
    """

    begin = is_opening_object_curly_bracket
    end = '}'
    name = None

    def __init__(self):
        super().__init__()

    def get_name(self):
        if self.name is not None:
            return self.name
        self.name = ''
        parent = self.parent
        if isinstance(parent, VariableDeclaration):
            for name, value in parent.get_expressions().items():
                if value == self:
                    self.name = name
                    return self.name
        elif isinstance(parent, ObjectCurlyBracket):
            for name, value in parent.get_dictionary().items():
                if value == self:
                    self.name = name
                    return self.name
        elif isinstance(parent, Assignment):
            left_expr = parent.get_left_expression()
            if isinstance(left_expr, Identifier):
                self.name = left_expr.get_name()
                return self.name

        return self.name


    def handle_expression(self):
        """
        used to parse identifiers within ObjectCurlyBracket
        """
        if hasattr(self, 'expression_handled'):
            return
        self.expression_handled = True
        should_preceed_id = ["{", "...", ",", ":"]
        if len(self.children) < 3:
            return
        new_children = []
        children = list(self.get_children())
        next_may_be_id = False
        for child in self.get_children():
            if not next_may_be_id:
                if child in should_preceed_id:
                    next_may_be_id = True
                new_children.append(child)
            else:
                if is_identifier(child):
                    identifier = Identifier(child)
                    identifier.parent = self
                    new_children.append(identifier)
                else:
                    new_children.append(child)
                if not child in should_preceed_id:
                    next_may_be_id = False

        self.children = new_children

    def get_method_symbol(self, method_name):
        """deprecated, should use more explicit name get_method_symbol_local"""
        return self.get_method_symbol_local(method_name)

    def get_method_symbol_local(self, method_name):
        result = OrderedDict()
        tokens = self.get_children()
        prev_tok = None
        self.current_name = ''
        for token in tokens:
            if token == ':' and isinstance(prev_tok, Identifier):
                self.current_name = prev_tok.get_name()
            elif isinstance(token, Bracket):
                if hasattr(token, 'value'):
                    self.current_name = token.value
            elif isinstance(token, Method) and token.get_name() == method_name:
                if hasattr(token, 'symbol'):
                    return token.symbol
            elif isinstance(token, ArrowExpression) and self.current_name == method_name:
                if hasattr(token, 'symbol'):
                    return token.symbol

            prev_tok = token

    def get_method_ast(self, method_name):
        result = OrderedDict()
        tokens = self.get_children()
        for token in tokens:
            if isinstance(token, Method) and token.get_name() == method_name:
                return token

    def get_dictionary(self):
        """
        return dictionary from {a: 1, b:2, ...}
        when the dict countains a spread operator we add a key $spread_maps which returns a list of spread maps:

map1 = {a:"a"}
map2 = {...map1, b:"b"}

        """
        result = OrderedDict()
        tokens = self.get_children()
        while True:
            try:
                # consumes first "{" and moves until
                # next key
                token = next(tokens)
                if token == "...":
                    token = next(tokens)
                    if not '$spread_maps' in result:
                        result['$spread_maps'] = [token]
                    else:
                        result['$spread_maps'].append(token)
                if tokens.look_next() in [",", "}"] and isinstance(token, Identifier):
                    key = token.get_name()
                    result[key] = token

                if tokens.look_next() == ":":
                    try:
                        key = token.text
                        key = key.strip("'").strip('"')

                    except AttributeError:
                        continue

                    next(tokens)  # consume key
                    token = next(tokens)  # consume ":"
                    result[key] = token


            except StopIteration:
                return result

    def get_key_values(self):
        to_return = []
        stream = self.get_children()
        key = None
        tok = next(stream) #curly bra
        tok = next(stream)
        if isinstance(tok, Identifier):
            key = tok.get_name()
        elif isinstance(tok,Assignment):
            key = tok.get_left_expression().get_name()
        elif isinstance(tok, Bracket):
            if hasattr(tok, 'value'):
                key = tok.value

        while True:
            try:
                tok = next(stream)
                if tok == ',':
                    tok = next(stream)
                    if isinstance(tok, Identifier):
                        key = tok.get_name()
                    elif isinstance(tok, Assignment):
                        key = tok.get_left_expression().get_name()

                    elif isinstance(tok, Bracket):
                        if hasattr(tok, 'value'):
                            key = tok.value
                elif tok == ':':
                    tok = next(stream)
                    if key:
                        to_return.append((key, tok))
                        key = None

            except StopIteration:
                break
        return to_return

    def get_key_identifiers(self):
        if isinstance(self.children[1], Identifier):
            identifiers = [self.children[1]]
        elif isinstance(self.children[1],Assignment):
            identifiers = [self.children[1].get_left_expression()]
        else:
            identifiers = []
        for i, child in enumerate(self.children):
            if child == ",":
                id = self.children[i+1]
                if isinstance(id, Identifier):
                    identifiers.append(id)
                elif isinstance(id, Assignment):
                    id = id.get_left_expression()
                    if isinstance(id, Identifier):
                        identifiers.append(id)


        return identifiers

    def get_methods(self):
        meths = []
        for child in self.get_children():
            if isinstance(child, Method):
                meths.append(child)

        return meths

    def get_method_symbol_by_name(self, method_name):
        meth = self.get_method_symbol_local(method_name)
        if meth:
            return meth

        _dict = self.get_dictionary()
        if method_name in _dict:
            val = _dict[method_name]
            if isinstance(val, Identifier):
                val = val.get_resolution()
            if isinstance(val, (ArrowExpression, Function)):
                val = val.symbol
            if hasattr(val, 'get_ast'):
                return val


    def get_methods_and_functions_by_name(self):
        _dict = OrderedDict()
        for meth in self.get_methods():
            _dict[meth.get_name()] = meth
        for key, function in self.get_key_values():
            if isinstance(function, (ArrowExpression, Function)):
                _dict[key] = function


        return _dict

class TypeScriptIndividualFragment(Node):
    """
    A fragment of TypeScript source code inside an .html or a .vue file
    """
    def __init__(self, children, token_text):
        super().__init__()
        self.children = children
        self.token_text = token_text

def is_opening_curly_bracket(token, stream):
    if token == "{" and not hasattr(token, "is_object_curlybracket"):
        return True
    else :
        return False

class CurlyBracket(BlockStatement):

    begin = is_opening_curly_bracket
    end = '}'

    def __init__(self):
        super().__init__()

    def on_end(self):
        """
we check if the CurlyBracket should be an ObjectCurlyBracket
(i.e. a dict
{ a: "a",
  b: "b"}
beware the CurlyBracket of a class can start as an objectCurlyBracket
(see test_fields.py TestFields test_08)
Since we do not have access to parent here, we cannot discriminate and these will be temporary changed to ObjectCurlyBracket; in the on_end of the Class they will be changed back to CurlyBracket.

        """
        stream = self.get_children()
        next(stream)  # "{"
        tok = next(stream)
        if not is_identifier(tok):
            return
        tok = next(stream)
        if isinstance(tok, Node):
            stream2 = tok.get_children()
            tok = next(stream2)
        if not tok == ":":
            return
        self.__class__ = ObjectCurlyBracket

    def get_dictionary(self):
        """
        return dictionary from {a: 1, b:2, ...}
        """
        log.debug("""Problem, this get_dictionary method should never be called on CurlyBracket object.
    Ultimately this method should be removed.""")

        result = {}
        tokens = self.get_children()
        while True:
            try:
                # consumes first "{" and moves until
                # next key
                token = next(tokens)
                if tokens.look_next() == ":" :
                    try:
                        key = token.text
                        key = key.strip("'").strip('"')
                    
                    except AttributeError:
                        return result
                    
                    next(tokens) # consume key
                    token = next(tokens) # consume ":"
                    result[key] = token

            except StopIteration:
                return result


class Bracket(BlockStatement):

    begin = '['
    end = ']'

    """
    with this method we extract only literals and StringTemplates
    """
    def extract_literal_items(self):
        result = []
        tokens = self.get_children()
        while True:
            try:
                token = next(tokens)
                while str(token.get_type()).startswith("Token.Literal") or str(token.get_type()) == "StringTemplate":
                    try:
                        key = token.text
                        if str(token.get_type()) == "StringTemplate":
                            st = StringTemplate()
                            st.text= key
                            st.extract_expression()
                            key = st.template
                        else:
                            key = key.strip('"')
                            key = key.strip("'")
                        result.append(key)
                    except AttributeError:
                        return result
    
                    next(tokens)  # consume key
                    token = next(tokens)  # consume literals

            except StopIteration:
                return result

    def get_items(self):
        result = []
        tokens = self.get_children()
        tok = next(tokens)
        tok = next(tokens)
        result.append(tok)
        while True:
            try:
                tok = next(tokens)
                if tok == ",":
                    tok = next(tokens)
                    result.append(tok)
            except StopIteration:
                break
        return result

    def handle_expression(self):
        # parse first token after < as Identifier
        new_children = []
        for tok in self.get_children():
            if isinstance(tok, Token) and tok.get_type() == Generic:
                identifier = Identifier(tok)
                identifier.parent = self
                new_children.append(identifier)
            else:
                new_children.append(tok)

        self.children = new_children


def is_generics(token, stream):


    if not token == "<" :
        return False
    if hasattr(token, "is_opening_tag"):
        return False
    try:
        next_tok = next(stream)
        if next_tok.type == Number :
            return False
    except StopIteration:
        return False

    nesting_level = 0

    try:
        while True:
            node = next(stream)
            if node in [";", "/>"]:
                return False
            elif node == "<":
                nesting_level += 1
            elif node == ">":
                if nesting_level == 0:
                    break
                else:
                    nesting_level -= 1

    except StopIteration:
        return False

    return True


class GenericsParameter(Term):
    """
    There is no simple way to make the difference between a GenericsParameter and an html opening tag
    """
    match = is_generics

    def get_tag_name(self):
        if len(list(self.get_children()))==1:
            return "<BlankTag>"
        stream = self.get_children()
        stream.move_to("<")
        tok = next(stream)

        if isinstance(tok, Token):
            return tok.text
        elif isinstance(tok, Identifier):
            return tok.get_name()
        return

    def on_end(self):
        # a tag of an html tag may contain - signs
        new_children = []
        children = list(self.get_children())

        new_children = allow_minus_in_html_tags(children)

        self.children = new_children

def allow_minus_in_html_tags(children):
    if len(children) < 3:
        return children
    if not isinstance(children[2], Token):
        return children
    if not children[2] == "-":
        return children

    new_children = children[:2]  # appending the '<' token
    out_of_tag = False
    for child in children[2:]:
        if out_of_tag:
            new_children.append(child)
            continue
        if (isinstance(child, Token) and
                (child == "-" or str(child.get_type()) == "Token.Generic") and
                child.get_begin_column() == new_children[-1].get_end_column() + 1
        ):
            new_children[-1].text += child.text
            new_children[-1].end_column = child.end_column
        else:
            out_of_tag = True
            new_children.append(child)
    return new_children

def is_opening_html_tag(token, stream):

    if token == "<>":
        return True


    if not token == "<" :
        return False
    if not hasattr(token, "is_opening_tag"):
        return False
    try:
        next_tok = next(stream)
        if next_tok.type == Number :
            return False
    except StopIteration:
        return False

    nesting_level = 0

    try:
        while True:
            node = next(stream)
            if node in [";", "/>"]:
                return False
            elif node == "<":
                nesting_level += 1
            elif node == ">":
                if nesting_level == 0:
                    break
                else:
                    nesting_level -= 1

    except StopIteration:
        return False

    return True


class OpeningHtmlTag(GenericsParameter):

    match = is_opening_html_tag

    def parse_first_tok_as_Identifier(self):
        if len(list(self.get_children()))==1:
            return
        children = list(self.get_children())
        if isinstance(children[1], Token):
            children[1] = Identifier(children[1])
            children[1].parent = self
            children[1].children[0].parent = children[1]
        self.children = children

    def get_identifier(self):
        if len(list(self.get_children()))==1:
            return None
        stream = self.get_children()

        next(stream)
        tok = next(stream)
        if isinstance(tok, Identifier):
            return tok

    def get_tag_name(self):
        if len(list(self.get_children()))>1:
            return super().get_tag_name()
        else:
            return "<BlankTag>"

    def on_end(self):
        self.parse_first_tok_as_Identifier()

def is_closing_html_tag(token, stream):

    if token == "</>":
        return True
    if not token == "</":
        return False

    try:
        while True:
            node = next(stream)

            # not sure that we need this one
            if node == ";" :
                return False
            elif node == "<":
                return False
            elif node == ">":
                return True

    except StopIteration:
        return False


class ClosingHtmlTag(Term):

    match = is_closing_html_tag

    def get_tag_name(self):
        if len(list(self.get_children())) == 1:
            return "<BlankTag>"
        stream = self.get_children()
        stream.move_to("</")
        tok = next(stream)

        if isinstance(tok, Token):
            return tok.text
        elif isinstance(tok, Identifier):
            return tok.get_name()
        return

    def on_end(self):
        # a tag of an html tag may contain - signs
        new_children = []
        children = list(self.get_children())

        new_children = allow_minus_in_html_tags(children)

        self.children = new_children

def unparse_node(node:Node, escaping_nodes):
    new_children = []
    for child in node.children:
        if isinstance(child, Token) or isinstance(child, escaping_nodes):
            new_children.append(child)
        else:
            new_children.extend(unparse_node(child,escaping_nodes))

    return new_children


class HtmlTag(BlockStatement):

    begin = OpeningHtmlTag;
    end = ClosingHtmlTag

    def __init__(self, children= None):
        super().__init__()
        self.children = children


    def handle_expression(self):
        new_children = unparse_node(self, escaping_nodes = (CurlyBracket, ObjectCurlyBracket, HtmlTag, ClosingHtmlTag, SelfClosingHtmlTag, OpeningHtmlTag))
        for child in new_children:
            if isinstance(child, ObjectCurlyBracket):
                child.__class__ = CurlyBracket
            child.parent = self
        self.children = new_children

def is_self_closing_html_tag(token, stream):

    if not token == "<":
        return False

    try:
        while True:
            node = next(stream)

            # not sure that we need this one
            if node == ";" :
                return False
            elif node == "<":
                return False
            elif node == ">":
                return False
            elif node == "/>":
                return True

    except StopIteration:
        return False


class SelfClosingHtmlTag(Term):

    match = is_self_closing_html_tag

    def on_end(self):
        # parse first token after < as Identifier
        children = list(self.get_children())
        if isinstance(children[1], Token):
            tok = children[1]
            children[1] = Identifier(tok)
            tok.parent = children[1]
            children[1].parent = self
        self.children = children

    def get_identifier(self):
        stream = self.get_children()
        next(stream)
        tok = next(stream)
        if isinstance(tok, Identifier):
            return tok


class StringTemplate(Term):
    match = is_string_template

    def __init__(self):
        super().__init__()
        self.expressions = []
        self.template = ""

    def extract_expressions(self):
        """Return strings inside ${ ... }
        
        TODO: analyze the performance impact of 
            full-parsing string templates
        """
        if self.template:
            return
        previous_is_backslash = False
        inside_expression = False
        stack_to_close = []
        current_string = ""
        template = ""
        expression_strings = []
        for char in self.text.replace('\n', '')[1:-1]:
            current_string += char
            if inside_expression:
                current_expression += char
            else:
                template += char
            if current_string.endswith("${") and not current_string.endswith("\${"):
                template = template[:-2] + "{}"
                stack_to_close.append("${")
                if not inside_expression:
                    current_expression = ""
                inside_expression = True
            elif current_string.endswith("{") and not previous_is_backslash:
                if not "${" in stack_to_close:
                    template = template[:-1]+'U+007B'
                if stack_to_close and stack_to_close[-1] in ["{", "${"]:
                    stack_to_close.append("{")
            elif current_string.endswith("`") and not previous_is_backslash:
                if stack_to_close[-1] == "`":
                    stack_to_close = stack_to_close[:-1]
                else:
                    stack_to_close.append("`")

            elif current_string.endswith("}"):
                if stack_to_close:
                    if stack_to_close[-1] == "{":
                        stack_to_close = stack_to_close[:-1]
                    elif stack_to_close[-1] == "${":
                        stack_to_close = stack_to_close[:-1]
                        if not "${" in stack_to_close:
                            inside_expression = False
                            expression_strings.append(current_expression[:-1])
                else:
                    template = template[:-1] + 'U+007D'


            if char == "\\":
                previous_is_backslash = True
            else:
                previous_is_backslash = False

        self.template = template
        if not expression_strings:
            return
        for expression in expression_strings:
            root = parse(expression)
            if not root.children:
                continue

            token = root[0]
            if isinstance(token, Token):
                identifier = Identifier(token)
                identifier.parent = self
                self.expressions.append(identifier)
            else:
                token.parent = self
                self.expressions.append(token)



def is_end_of_arrow_function(token, stream):

    def consume_semicolon(stream):
        # include ";" if needed

        index_of_stream = stream.tokens.index
        next_token = next(stream)
        if next_token == ";":
            return
        # restore state
        stream.tokens.index = index_of_stream

    index_of_stream = stream.tokens.index

    # if next_token == "=" or next_token == "," or next_token == ">":
    if token == "," \
        or token == ")" \
        or isinstance(token, Decorator)\
            or isinstance(token, FunctionType):
        stream.tokens.index = index_of_stream
        return True

    next_tok = next(stream)
    if next_tok == ":":
        next_tok = next(stream)
        if isinstance(next_tok, FunctionType):
            stream.tokens.index = index_of_stream
            return True


def is_end_of_function_type(token, stream):
    index_of_stream = stream.tokens.index
    next_token = next(stream)
    if not token.is_whitespace() and isinstance(next_token, CurlyBracket):
        stream.tokens.index = index_of_stream
        return True

def is_generics_following_colon(token, stream):
    if not isinstance(token, GenericsParameter):
        return False
    lt = next(token.get_children())
    if hasattr(lt, "is_following_colon"):
        return True
    return False

def is_parenthesis_following_colon(token,stream):
    if not isinstance(token, Parenthesis):
        return False
    opening_parenthesis = next(token.get_children())

    # we are in the case of a functionType defined within a parenthesis
    # see test_function_type_in_parenthesis
    if isinstance(token.children[1], FunctionType):
        return False

    if hasattr(opening_parenthesis, "is_following_colon"):
        return True
    return False

def followed_by_linefeed(token , stream):
    index_of_stream = stream.tokens.index
    next_token = next(stream)
    if next_token.type == LineFeed or next_token == ";":
        stream.tokens.index = index_of_stream
        return True
    return False

class FunctionType(Statement, CanBeExported):
    begin = Seq(
        Or(is_parenthesis_following_colon,
           Seq(is_generics_following_colon, Parenthesis)), '=>'
            )

    end = Or(followed_by_linefeed,
             #
             NotFollowedBy(Not(Or(":", "=", ",", ")", CurlyBracket, ObjectCurlyBracket, "Decorator"))),
             Seq(is_end_of_function_type),
             Seq(is_end_of_arrow_function)
             )

    def __init__(self):
        Statement.__init__(self)
        CanBeExported.__init__(self)

    def get_old_name(self):
        if hasattr(self, 'old_name'):
            return self.old_name
        return "<Anonymous1>"

    def get_name(self):
        """ 
        we may have an anonymous function, so we need to define get_name
        """
        if hasattr(self, 'object_field_name'):
            return self.object_field_name
        if hasattr(self, 'name'):
            return self.name
        return '<Anonymous1>'

    def handle_expression(self):
        """
Plus some extra tokens are caught by the ArrowExpression due to the parsing approach used.
We need to remove them from within the ArrowExpression and put them after the ArrowExpression node.
This is the purpose of this handle_expression.

Ideally we would do this in an on_end(), but the parent is not accessible in the on_end() method.
"""
        children = self.children
        for i, child in enumerate(children):
            if child.get_type() == ST:
                string_template = StringTemplate()
                string_template.children = [child]
                self.children[i] = string_template

        last_child = children[-1]
        try:
            text_last = last_child.text
        except:
            pass

        if text_last in [":", ",", "=", ")"] or isinstance(last_child, Decorator):
            self.children = self.children[:-1]

            parent = self.parent
            for i, sibling in enumerate(parent.children):
                if sibling == self:
                    break

            parent.children = parent.children[:i] + [self, last_child] + parent.children[i + 1:]


class SignatureCaller:
    """
    Class for signature of Method
    """

    def __init__(self, nb_params, nb_required_params):
        self.nb_params = nb_params
        self.nb_required_params = nb_required_params


class SignatureCallee:
    """
    Class for signature of MethodCall
    """

    def __init__(self, nb_args, spread_arg):
        self.nb_args = nb_args
        self.spread_arg = spread_arg


def get_signature_for_js_callable(_ast):
    """
    Get the signature for an ast javascript
    @type _ast: Method or Function
    """

    parameters_in_definition = _ast.get_parameters()
    nb_params = len(parameters_in_definition)
    try:
        nb_required_params = _ast.get_mandatory_parameters_number()
    except AttributeError:
        nb_required_params = 0
    spread_param = False

    if nb_params > 0:
        for param in parameters_in_definition:
            if _ast.is_method():
                try:
                    spread_param = param.is_operator()
                except AttributeError:
                    continue
            elif _ast.is_function():
                try:
                    spread_param = param.is_iterated()
                except AttributeError:
                    continue
            if spread_param:
                nb_params = 100000
                break

    return SignatureCaller(nb_params, nb_required_params)


def get_signature_for_ts_callable(_ast):
    """
    Get the signature for an ast typescript
    @type _ast: Method or Function
    """

    parameters_in_definition = _ast.get_parameters()
    nb_params = len(parameters_in_definition)

    # we check for a rest parameter (...param)
    if nb_params > 0:
        last_param = parameters_in_definition[-1]
        if isinstance(last_param, Parameter) and last_param.is_spread_param:
            nb_params = 100000

    nb_required_params = 0
    for param in parameters_in_definition:
        if not isinstance(last_param, Parameter):
            continue
        # a param with default value is optional
        if param.is_optional or param.get_value():
            break
        # we check for a rest parameter (...param) which is optional
        if param.is_spread_param:
            break
        nb_required_params += 1

    return SignatureCaller(nb_params, nb_required_params)


def signature_matching(callee, caller):
    """
    Compare signatures
    @type callee: Signature
    @type caller: Signature
    """

    has_signature = False

    nb_arguments = callee.nb_args
    spread_argument = callee.spread_arg

    nb_params = caller.nb_params
    nb_required_params = caller.nb_required_params

    if nb_arguments >= nb_required_params or spread_argument:
        if nb_arguments <= nb_params:
            has_signature = True

    return has_signature


class _GenericCall:
    """
    Class for common methods in MethodCall and FunctionCall
    """

    def get_arguments(self):
        """
        Get the arguments passed to the method call
        
        This method might substitute in the future get_parameters,
        and should also serve as a transition step for the parsing 
        of arguments inside method calls (and functions) 
        """
        nodes = self.get_sub_nodes(Parenthesis)
        if not nodes:
            return []
        if hasattr(self, 'is_fake_call'):
            return []
        arguments = []
        try:
            parenthesis = next(nodes)
        except StopIteration:
            log.debug("Problem getting argument for call " + str(self))
            return []
        first_child= next(self.get_children())
        if parenthesis == first_child:
            try:
                parenthesis = next(nodes)
            except StopIteration:
                return
        tokens = list(parenthesis.get_children())[1:-1]  # removes "(" and ")"
        if tokens:
            children = []
            for token in tokens:
                if token == ',':
                    arguments.append(Argument(children.copy()))
                    children.clear()
                    continue

                children.append(token)

            if children:
                arguments.append(Argument(children))

            for arg in arguments:
                if "=>" in arg.children:
                    arg.is_lambda_function = True

        return arguments

    def get_argument(self, position=0):
        """
        This method returns argument at the position
        :position : Position of the argument in the method call.
        """
        arguments = self.get_arguments()

        try:
            return arguments[position]
        except IndexError:
            return None

    def get_enclosing_callable_ast(self):

        parent = self.parent
        while parent and not isinstance(parent, (Function, Method, ArrowExpression)):
            if not hasattr(parent, 'parent'):
                break
            parent = parent.parent

        return parent

    def get_signature(self):
        """
        Get the signature of method call
        """
        nb_args = 0
        spread_arg = False

        if self.get_arguments():
            nb_args = len(self.get_arguments())
            for arg in self.get_arguments():
                if arg.is_spread_arg:
                    spread_arg = True
                    break

        return SignatureCallee(nb_args, spread_arg)

    def name_argument_anonymous_functions(self):
        arg_number = 0
        for a in self.get_arguments():
            arg_number += 1
            if not hasattr(a, 'children'):
                continue
            func = a.children[0]
            if not isinstance(func, (ArrowExpression, Function)):
                continue
            if not hasattr(func, 'symbol'):
                continue
            if isinstance(func, Function) and not func.get_name().startswith('<Anonym'):
                continue
            f_symb = func.symbol
            parent_symbol = f_symb.get_parent_symbol()
            symbol_new_name = self.get_name() + '_PARAM_' + str(arg_number)
            module = parent_symbol.get_root_symbol()
            if not hasattr(module, 'symbols_to_reorganise'):
                module.symbols_to_reorganise = set()
            module.symbols_to_reorganise.add(parent_symbol)
            if not hasattr(parent_symbol, 'renamed_symbols'):
                parent_symbol.renamed_symbols = DefaultOrderedDict(list)

            i_anonym = 1
            while True:
                anonym_name = '<Anonymous'+str(i_anonym)+'>'
                if not anonym_name in parent_symbol.symbols:
                    break
                if f_symb in parent_symbol.symbols[anonym_name]:
                    parent_symbol.renamed_symbols[anonym_name] = f_symb
                    break
                i_anonym+=1

            if not hasattr(parent_symbol, 'i_param_symbols'):
                parent_symbol.i_param_symbols = DefaultOrderedDict(int)
            parent_symbol.i_param_symbols[symbol_new_name]+=1

            if parent_symbol.i_param_symbols[symbol_new_name]>1:
                symbol_new_name = symbol_new_name + '_#' + str(parent_symbol.i_param_symbols[symbol_new_name])

            f_symb.get_ast().name = symbol_new_name
            f_symb._Symbol__name = symbol_new_name

class Instantiation(Term, _GenericCall):
    match = Or(Seq("new", is_identifier, Optional(Seq(".", is_identifier)),
                Optional(GenericsParameter), Optional(Parenthesis)),
               Seq("new", is_identifier)
            )


    def on_end(self):
        children = list(self.get_children())
        if isinstance(children[1], Token):
            children[1] = Identifier(children[1])
            children[1].parent = self
            self.children = children

        for i, child in enumerate(self.children):
            if isinstance(child, Parenthesis):
                new_children = []
                stream = child.get_children()
                try:
                    while True:
                        tok = next(stream)
                        if is_token_subtype(tok.type, Generic):
                            try:
                                next_tok = stream.look_next()
                                if not next_tok == "." and children[-1] != ".":
                                    identifier = Identifier(tok)
                                    new_children.append(identifier)
                                else:
                                    new_children.append(tok)
                            except StopIteration:
                                identifier = Identifier(tok)
                                new_children.append(identifier)

                        else:
                            new_children.append(tok)
                except StopIteration:
                    pass
                child.children = new_children
                for c in child.children:
                    c.parent = child
                # parse_parenthesis_of_call(self.children[i])

    def __init__(self):
        super().__init__()
        self._resolution = None
        self.original_class_name = None


    def get_declaration(self):
        try:
            return self.get_class_identifier().get_declaration()
        except AttributeError:
            return None

    def get_class_identifier(self):
        tokens = self.get_children()
        tokens.move_to("new")
        tok = next(tokens)
        if isinstance(tok, Identifier):
            return tok

    def get_class_name(self):

        tokens = self.get_children()
        tokens.move_to("new")
        tok = next(tokens)

        text = None
        try :
            text = tok.text
        except:
            pass
        return text

    def get_original_class_name(self):
        """
        Return the original name of the instantiation.
        import {Toto as Lala} from 'base';
        instantiation.get_original_class_name() = ToTo
        """

        return self.original_class_name

    # in case the class is defined in a module
    def get_fullname(self):
        tokens = self.get_children()
        tokens.move_to("new")
        text = ""
        try:
            for tok in tokens:
                if isinstance(tok, Identifier):
                    text += tok.get_name()
                elif str(tok.type) == "Token.LineFeed":
                    break
                else:
                    if tok.text == "(":
                        break
                    text += tok.text
        except:
            pass
        if text == "" :
            return None
        else:
            return text

    def get_name(self):
        tokens = self.get_children()
        tokens.move_to("new")
        text = ""
        try:
            for tok in tokens:
                if isinstance(tok, Identifier):
                    text = tok.get_name()
                elif str(tok.type) == "Token.LineFeed" or isinstance(tok, Parenthesis) or tok.text == "(":
                    break
                elif hasattr(tok, 'text') and tok.text:
                    text = tok.text
        except:
            pass
        if text == "" :
            return None
        else:
            return text

    def get_resolution(self):
        return self._resolution

    def get_resolutions(self):
        return [self._resolution]

    # to be deprecated ..
    def get_parameters(self):
        """
        Return the list of arguments passed
        to the constructor of the class
        
        @todo: rename it as get_arguments
        """
        nodes = self.get_sub_nodes(Parenthesis)
        if not nodes:
            return []

        parameters = []
        try:
            parenthesis = next(nodes)
        except StopIteration :
            return []

        tokens = parenthesis.children[1:-1]
        if tokens:
            for token in tokens:

                if token == ',':
                    continue

                parameters.append(token)

        return parameters

def is_start_function_call_with_type(token, stream):

    if not is_identifier(token) and not (isinstance(token, Token) and token.type==Keyword):
        return False

    # this is a hack. In theory, we could have a function call named await
    # but there are some complex cases (see test_function_call_wtih_type_assertion_non_reg2 in test_parser()
    # that are hard to handle properly.
    if isinstance(token, Token) and token.text in ['await', 'new']:
        return False
    index_of_stream = stream.tokens.index
    next_token = next(stream)
    if isinstance(next_token, Parenthesis):
        stream.tokens.index = index_of_stream
        return True
    if not isinstance(next_token, GenericsParameter):
        return False

    index_of_stream = stream.tokens.index
    next_token = next(stream)
    if isinstance(next_token, Parenthesis):
        stream.tokens.index = index_of_stream
        return True
    return False

def is_start_function_call_with_type_assertion(token, root_stream):
    if not isinstance(token, Parenthesis):
        return False
    try:
        stream = token.get_children()
        tok = next(stream) #(
        tok = next(stream)
        if not (is_identifier(tok) or isinstance(tok, (ExpressionStatement, MemberAccess))):
            return False
        tok = next(stream)
        if not tok == "as":
            return False

        tok = next(stream)
        if not is_identifier(tok):
            return False
        tok = next(stream)
        if not tok == ")":
            return False

        if isinstance(root_stream, TokenIterator):
            index_of_stream = root_stream.tokens.index
        root_next_token = next(root_stream)
        if isinstance(root_stream, TokenIterator):
            root_stream.tokens.index = index_of_stream
        if root_next_token == ',':
            return False
        return True
    except StopIteration:
        return False

def followed_by_var_decl_equal(token, stream):
    index_of_stream = stream.tokens.index
    next_token = next(stream)
    if next_token == '=' and hasattr(next_token, 'is_var_decl_equal'):
        stream.tokens.index = index_of_stream
        return True
    return False

     
class ExpressionStatement(Statement):
    """Generic expression statement
    
    ExpressionStatement nodes are expected to be 
    substituted by more specific ones in handle_expression:
        - MethodCall, 
        - FunctionCall
        - ArrayAccess
        - ...
    
    Important!
    ---------
        Generally we should not rely on this node
        to do posterior parsing (in full parsing) or 
        reference it in quality rules.
    """

    begin = Or(is_start_function_call_with_type,
               is_start_function_call_with_type_assertion,

                Seq(Or(is_identifier,
                       Seq(Parenthesis, NotFollowedBy(Not('.'))),  # ().reduce()
                       Token('this', Keyword),
                       Token('super', Keyword),
                       Token('eval', Keyword)
                      ),
                    NotFollowedBy(Or(',', '=', '+=', '-=', ':', ';', '?', '||', '??', '|', '&&', '<=', '>=','||=', '&&=', '??=',
                                        '+', '=>', '++', '--', '^',
                                        Seq('.', is_identifier, GenericsParameter, "="), Seq("!", ","), FunctionType,
                                        Keyword, ClosingHtmlTag, SelfClosingHtmlTag, GenericsParameter,
                                        CurlyBracket, ObjectCurlyBracket, HtmlTag, LineFeed)
                    )
                ),
                Seq(Instantiation, "."),
                # array's or string methods:   [].concat() or "".concat()
                Seq(Or(Bracket, Token('module', Keyword),is_string_literal), NotFollowedBy(Not('.'))),
                # for operators like .catch()
                Seq('.', Token('catch', Keyword)))

    end = Or(
            # Field access
            Seq(Seq(Or(is_identifier, WeakKeyword, is_string_literal, is_number_literal),
                    NotFollowedBy(Or(".", Bracket, Parenthesis, GenericsParameter))),
                Optional(';')),
            # xxx
            Seq('.', Token('module', Keyword), '='),
            # Function/Method Calls
            Seq(Seq(Parenthesis, NotFollowedBy(Or(".", Bracket, Parenthesis))), Optional(';')),
            # ArrayAccess
            Seq(Seq(Bracket, NotFollowedBy(Or(".", Parenthesis))), Optional(';')),
            Seq(Keyword, ";"),
            followed_by_var_decl_equal
            )
    def __init__(self):
        super().__init__()

    def handle_expression(self):
        """
        a GenerticsParameter can be caught in the ExpressionStatement. We need to remove it
        """

        children = list(self.get_children())

        if isinstance(children[-1], GenericsParameter):

            for i, tok in enumerate(self.parent.children):
                if tok == self:
                    break

            children[-1].parent = self.parent
            self.parent.children = self.parent.children[:i + 1] + [children[-1]] + self.parent.children[i + 1:]
            self.children = children[:-1]

            
class ImportedElement:
    """
    Something inside import {element as alias}
    
    Attributes : 
        - element: name of the element (str) (for an export) 
                   or Identifier(token) where token is the token defining the element
        - alias: name of the alias (str)
    """
    def __init__(self, element, alias=None):
        
        self.element = element
        self.alias = alias
        
    def get_element(self):
        
        return self.element

    def get_element_name(self):
        if isinstance(self.element, Identifier):
            return self.element.get_name()
        elif isinstance(self.element, Token):
            return self.element.text
        elif isinstance(self.element, str):
            return self.element

    def get_alias(self):
        return self.alias
    
    def get_alias_name(self):
        if isinstance(self.alias,Identifier):
            return self.alias.get_name()
        elif isinstance(self.alias, Token):
            return self.alias.text
        elif isinstance(self.alias, str):
            return self.alias
    
    def get_alias_or_element(self):
        if not self.alias:
            return self.element
        else:
            return self.alias

    def __repr__(self):
        
        return str(self.element) + ' as ' + str(self.alias)


class ExportedElement(ImportedElement):
    """
    Something inside export
    
    Attributes : 
        - element: name of the element (str) (for an export) 
        - alias: name of the alias (str)
    """


def is_export_term(token, stream):
    
    if not token == 'export':
        return False
    next_token = next(stream)
    if next_token == 'default':
        next_token = next(stream)
        if next_token == 'new':
            next(stream)
            next_token = next(stream)
            if not (isinstance(next_token, (Parenthesis, Identifier, Bracket)) or next_token == '.'):
                return False
            while isinstance(next_token, (Parenthesis, Bracket)) or next_token == '.' or is_identifier(next_token):
                index_of_stream = stream.tokens.index
                try:
                    next_token = next(stream)
                except StopIteration:
                    break
            stream.tokens.index = index_of_stream
            return True
            if not isinstance(next_token, Parenthesis):
                return False
        elif isinstance(next_token, Parenthesis):
            return False
    else:
        if not isinstance(next_token, CurlyBracket):
            return False
    index_of_stream = stream.tokens.index
    try:
        next_token = next(stream)
        if isinstance(next_token, GenericsParameter):
            next_token = next(stream)
        if next_token == "from":
            return False
        elif next_token == ";":
            return True
        elif isinstance(next_token, (Parenthesis, Identifier, Bracket)) or next_token == '.':

            while isinstance(next_token, (Parenthesis, Bracket)) or next_token == '.' or is_identifier(next_token):
                index_of_stream = stream.tokens.index
                try:
                    next_token = next(stream)
                except StopIteration:
                    break
            stream.tokens.index = index_of_stream
            return True

    except StopIteration:
        return True
        
    stream.tokens.index = index_of_stream
    return True


class Enum(Statement):
    begin = Seq(Optional(Token('declare', Keyword)),
                Optional(Token('const', Keyword)),
                Token('enum', Keyword), NotFollowedBy(':'))
    end = CurlyBracket

    def get_name(self):
        tokens = self.get_children()
        tokens.move_to(['enum'])
        return next(tokens).text

    def get_value(self, name: str):
        for tok in self.get_children():
            if isinstance(tok, CurlyBracket):
                curly_bra = tok
                break
        tokens = curly_bra.get_children()
        for child in tokens:
            if isinstance(child, Assignment):
                if not child.get_left_expression().get_name() == name:
                    continue
                res = child.get_right_expression()
                if isinstance(res, GenericsParameter):
                    return next(tokens)
                return child.get_right_expression()


class Export(Term):
    """
    Function, classes and namespace are usually exported by 
    adding the export keyword before the declaration,
    however they can be exported outside of the declaration.
    This Export node corresponds to this kind of exports.
    """

    match = Or(
        # if the CurlyBracket is followed by 'from' we have a ReExport and not an Export
        Seq('export', Optional('type'), Seq(CurlyBracket, NotFollowedBy('from')), Optional(";")),
        is_export_term,
        # this corresponds to the specific case of a required export
        Seq('export', "=", Seq(is_identifier, NotFollowedBy(Parenthesis)), Optional(";")),

        Seq('export', 'const', is_identifier, Optional(Seq(':', is_identifier)), '=',
            Or(
                # constant dictionaries
                ObjectCurlyBracket,

                # instantiation
                Seq("new", is_identifier, Optional(GenericsParameter), Optional(Parenthesis), Optional(Seq(".", is_identifier, Parenthesis,Optional(Seq(".", is_identifier, Parenthesis, Optional(Seq(".", is_identifier, Parenthesis))))))
                ),

                Seq(is_identifier, Bracket),
                Seq(is_identifier, Parenthesis)
            ),
            Optional(Parenthesis),
            Optional(";")),

        # constant variable
        Seq('export', 'const', Or(is_identifier, ObjectCurlyBracket), Optional(Seq(':', is_identifier)), '=',
            Or(Seq(is_identifier, Parenthesis),
               Seq(is_identifier, '.', is_identifier, Parenthesis),
               Seq(is_identifier, '.', is_identifier),
               is_identifier,
               is_string_literal), Or(";", LineFeed)),

        # enum
        Seq('export', Optional('const'), Enum)
        )

    def __init__(self):
        Statement.__init__(self)
        self.__exported_elements = []

        # a pure export does not contain the definition
        # export const a = foo //is not a pure export
        # export {a, b} //is a pure export
        self.is_pure_export = True
        self.is_default_export = False

    def on_end(self):
        children = list(self.get_children())
        if len(children)>1 and children[1] in ['const', 'var', 'let']:
            var_decl = VariableDeclaration()
            var_decl.parent = self
            if children[-1] == ";":
                var_decl.children = children[1:-1]
                self.children = [children[0], var_decl, children[-1]]
            else:
                var_decl.children = children[1:]
                self.children = [children[0], var_decl]
            var_decl.on_end()
            for identifier in var_decl.get_variables():
                self.__exported_elements.append(ExportedElement(identifier))
            return
        if isinstance(children[1], Enum):
            self.__exported_elements.append(ExportedElement(children[1]))
            return

        if 'const' in self.children:
            # parse Identifiers
            children = list(self.get_children())  # remove whitespaces & comments
            index = children.index('const') + 1
            begin = children[0:index]
            end = children[index + 1:]
            identifier = Identifier(children[index])



            new_children = begin + [identifier] + end
            self.children = new_children
            identifier.parent = self
            self.__exported_elements.append(ExportedElement(identifier))
            self.is_pure_export = False
            return

        #default 
        tokens = self.get_children()
        next(tokens)
        if next(tokens) == "default":
            # TODO: ANGTS-192
            self.is_default_export = True
            next_token = next(tokens)
            i_switch = 0
            if next_token == "new":
                i_switch = 1
                next_token = next(tokens)
            if not is_identifier(next_token):
                self.__exported_elements.append(ExportedElement(next_token))
                return
            identifier = Identifier(next_token)
            identifier.parent = self
            children = list(self.get_children())
            new_children = children[0:2+i_switch] + [identifier] + children[3+i_switch:]
            self.children = new_children
            self.__exported_elements.append(ExportedElement(identifier))
            return

        try:
            curly_bracket = next(self.get_sub_nodes(CurlyBracket))
        except:
            return

        tokens = curly_bracket.get_children()
        tok = next(tokens)  # "{" token
        new_children = [tok]
        alias_expected = False  # i.e. previous tok was "as"
        element_expected = True
        alias = None
        try:
            while True:
                tok = next(tokens)
                new_children.append(tok)
                if tok == 'type':
                    tok = next(tokens)
                    new_children.append(tok)
                if alias_expected:
                    alias = tok.text
                    alias_expected = False
                if element_expected:
                    element = Identifier(tok)
                    element.parent = curly_bracket
                    new_children[-1] = element
                    element_expected = False
                if tok.text == "as":
                    alias_expected = True
                if tok.text == ",":
                    self.__exported_elements.append(ExportedElement(element, alias))
                    alias = None
                    element_expected = True
        except StopIteration:
            pass
        self.__exported_elements.append(ExportedElement(element, alias))
        curly_bracket.children = new_children

    def handle_default_parsing(self, id_tok: Identifier, tokens):

        expr_statement = None
        try:
            n_tok_in_expr = 1
            tok = next(tokens)
            if tok == ';':
                return
            expr_statement = ExpressionStatement()
            expr_statement.children = [id_tok]
            if isinstance(tok, GenericsParameter):
                tok = next(tokens)
            if isinstance(tok, (Parenthesis, Bracket)) or tok == '.':

                while isinstance(tok, (Parenthesis, Bracket)) or tok == '.' or is_identifier(tok):
                    expr_statement.children.append(tok)
                    n_tok_in_expr += 1
                    try:
                        tok = next(tokens)
                    except StopIteration:
                        tok = None

        except StopIteration:
            pass

        children = list(self.get_children())
        if expr_statement:
            expr_statement.handle_expression()
            try:
                new_node = parse_calls(expr_statement)
            except:
                new_node = None
                log.debug("  Error when parsing calls in expression statement at line {}"
                          .format(expr_statement.get_begin_line()))

            if new_node:
                new_children = children[0:2] + [new_node] + children[2 + n_tok_in_expr:]
                new_node.parent = self
                self.children = new_children

    def handle_expression(self):
        tokens = self.get_children()
        next(tokens)
        if next(tokens) == "default":
            self.is_default_export = True
            id_tok = next(tokens)
            if isinstance(id_tok, Identifier) and id_tok.get_name()!='new':
                self.handle_default_parsing(id_tok, tokens)

        # parse Instantiation
        if not "new" in self.children:
            return
        stream = self.get_children()
        new_children = []
        while True:
            tok = next(stream)
            if tok == "new":
                break
            else:
                new_children.append(tok)

        instantiation = Instantiation()
        instantiation.children.append(tok)
        tok = next(stream)
        if not is_identifier(tok):
            return
        instantiation.children.append(tok)
        stream_ended = False
        try:
            tok = next(stream)
        except StopIteration:
            stream_ended = True
        if isinstance(tok, GenericsParameter):
            instantiation.children.append(tok)
            try:
                tok = next(stream)
            except StopIteration:
                stream_ended = True


        if isinstance(tok, (Parenthesis, Bracket)) or tok == '.' or is_identifier(tok):
            while isinstance(tok, (Parenthesis, Bracket)) or tok == '.' or is_identifier(tok):
                instantiation.children.append(tok)
                try:
                    tok = next(tokens)
                except StopIteration:
                    break

        new_children.append(instantiation)
        for child in instantiation.children:
            child.parent = instantiation
        instantiation.on_end()
        if not stream_ended:
            while True:
                try:
                    tok = next(stream)
                    new_children.append(tok)
                except StopIteration:
                    break
        self.children = new_children

    def get_exported_elements(self):
        if self.is_default_export:
            stream = self.get_children()
            stream.move_to('default')
            return [ExportedElement(next(stream))]

        return self.__exported_elements

    def get_value(self):
        """
        get the right expression if assignment
        """
        tokens = self.get_children()
        try:
            tokens.move_to("=")
            return next(tokens)
        except:
            return None


class ReExport(Statement):
    """
    A ReExport forwards a variable without importing it locally, or introduce a local variable.
    """
    begin = Seq('export', Or('*', CurlyBracket), Token('from', Keyword))
    end = Seq(is_string_literal,
            Optional(";"))

    def __init__(self):
        Statement.__init__(self)
        self.module = None
        self.__exported_elements = []
        
    def on_end(self):
        """
        local parsing
        """
        tokens = self.get_children()
        tokens.move_to(['from'])
        try:
            self.module = Identifier(next(tokens))
        except StopIteration:
            pass

        curly_bracket = None
        for sub_node in self.children:
            if isinstance(sub_node, CurlyBracket):
                curly_bracket = sub_node
                break
        if curly_bracket:
            tokens = curly_bracket.get_children()

            tokens.move_to("{")
            alias_expected = False #i.e. previous tok was "as"
            element_expected=True
            alias = None
            try:
                while True:
                    tok = next(tokens)
                    if alias_expected:
                        alias = tok.text
                        alias_expected = False
                    if element_expected:
                        element = tok.text
                        element_expected = False
                    if tok.text == "as":
                        alias_expected = True
                    if tok.text == ",":
                        self.__exported_elements.append(ExportedElement(element, alias))
                        alias = None
                        element_expected = True
            except StopIteration:
                pass
            self.__exported_elements.append(ExportedElement(element, alias))
        else:
            self.__exported_elements = "all"
        
    def get_module(self):
        return self.module

    def get_exported_elements(self):
        return self.__exported_elements


class Import(Statement, WithResolution):
    """Import statements with optional ";"

    interesting discussion:
        https://stackoverflow.com/questions/35706164/typescript-import-as-vs-import-require

    @todo: nice to have
        https://github.com/Microsoft/TypeScript/wiki/What's-new-in-TypeScript#typescript-24
    
    Examples
        import 'string';                  # (i)
        import 'string'                   #  "
        import {a, b} from 'string';      #  "
        import toto = require('toto');    # (ii)
        import t = c.d.t                  # (iii)
        
    """
    begin = Seq(Token('import', Keyword), NotFollowedBy(Or(Parenthesis,":")))  # with parenthesis it would be a method
    end = Seq(Optional(Parenthesis),  # allows not to parse a functionCall in a require import : import f1 = require("")
              Or(LineFeed, ";"))

    def __init__(self):
        Statement.__init__(self)
        WithResolution.__init__(self)
        self.module = None
        self.import_star_alias = None
        self.imported_elements = []
        self.is_require_import = False

    def get_local_name_of_default_imported_variable(self):
        """
        
        return the local name of default import : 
        import foo from 'foopath'     returns 'foo'
        we know it's a default import because foo is not inside a curly bracket
        
        returns None when we do not have a default import:
        import {foo} from 'foopath'
        import 'lala'
        import toto = require('toto')
        """
        local_name = None
        tokens = self.get_children()
        try:
            tokens.move_to('import')
            tok = next(tokens)
        except StopIteration:
            return None
        if (not tok == "*" and
            isinstance(tok, Token)):
            # we check that we have a from
            local_name = tok.text
            tokens.move_to("from")
            try :
                next(tokens)
                return local_name
            except StopIteration:
                return None
        return None

    def get_module(self):
        """
        The module from which it is imported, may be none.
        
        :rtype: Identifier
        """
        return self.module

    def get_star_alias(self):
        """
        When the import is an import * as ... returns the ...
        """
        return self.import_star_alias

    def get_imported_elements(self):
        """
        When the import is import {..., ...} returns the list of ...
        """
        return self.imported_elements
    
    def on_end(self):
        """
        local parsing
        """

        # check if we have a require_import
        try:  # we may have a require import: import element = require("path_to_module")
            tokens = self.get_children()
            tokens.move_to("import")
            tok = next(tokens)
            imported_element = tok

            tokens.move_to("=")
            tok = next(tokens)
            # we have a require import
            if tok.text == "require":
                self.is_require_import = True
                parenthesis_tok = next(tokens)
                tokens = parenthesis_tok.get_children()
                tokens.move_to("(")
                tok = next(tokens)
                self.module = Identifier(tok)
                self.imported_elements.append(ImportedElement(Identifier(imported_element), None))
                return
        except:
            pass

        tokens = self.get_children()
        next(tokens) # import
        token = next(tokens)
        if is_string_literal(token) :
            text = token.text.rstrip('"')
            
            # This condition is to check import './module.Js'
            if text.endswith('.ts') or text.endswith('.js'):
                self.module = None
            else :
                self.module = Identifier(token)

            return
        
        while token and token != "from":
            if token == ",":
                token = next(tokens)
            # For direct imports i.e. import './module';

            if token == '*':
                token = next(tokens)  # as
                token = next(tokens)
                self.import_star_alias = Identifier(token)

            elif isinstance(token, (CurlyBracket, ObjectCurlyBracket)):
                elements = token.get_children()
                next(elements)  # {
                try:
                    while True:
                        next_elem = next(elements)
                        if next_elem == 'type':
                            next_elem = next(elements)
                        element = Identifier(next_elem)

                        token = next(elements)

                        if token == 'as':
                            alias = Identifier(next(elements))
                            next(elements)
                        else:
                            alias = None

                        self.imported_elements.append(ImportedElement(element, alias))

                except StopIteration:
                    pass

            # else:
            #    self.imported_elements.append(ImportedElement(Identifier(token)))

            try:
                token = next(tokens)
            except StopIteration:
                token = None

        tokens = self.get_children()
        tokens.move_to(['from'])
        try:
            self.module = Identifier(next(tokens))
        except StopIteration:
            pass


def is_decorator(token, stream):
    if not token == '@':
        return False
    prev_tok = token
    tok = next(stream)
    index_of_stream = stream.tokens.index
    while is_identifier(tok) or isinstance(tok, (Parenthesis, Bracket)) or tok == '.':
        if is_identifier(tok) and prev_tok not in ['@', '.']:
            break
        index_of_stream = stream.tokens.index
        try:
            prev_tok = tok
            tok = next(stream)
        except StopIteration:
            tok = None
    if (isinstance(tok, Token) and tok.type == LineFeed) or tok == ';':
        return True
    stream.tokens.index = index_of_stream
    return True

class Decorator(Term, _GenericCall):
    match = is_decorator

    is_imported_from_framework = None

    def get_name(self):
        element = self.get_expression()

        if hasattr(element, 'get_name'):
            return element.get_name()

        return ''

    def get_arguments(self):
        element = self.get_expression()

        if hasattr(element, 'get_arguments'):
            args = [a.children[0] if isinstance(a, Argument) else a for a in element.get_arguments()]
            if not args:
                return []
            else:
                return args

        return []

    def get_parameters(self):
        """ should use get_arguments instead of get_parameters"""
        return self.get_arguments()

    def get_expression(self):
        children = self.get_children()
        next(children)  # '@'
        return next(children)

    def handle_expression(self):

        contains_expression = False
        for child in self.get_children():
            if child == '.' or isinstance(child, Parenthesis):
                contains_expression = True

        if contains_expression:
            new_children = []
            at_seen = False
            for child in self.children:
                if not at_seen:
                    new_children.append(child)
                    if child == '@':
                        at_seen = True
                        expression_statement = ExpressionStatement()
                        expression_statement.parent = self
                        new_children.append(expression_statement)
                    continue


                if not is_linefeed_or_semicolon(child) :
                    expression_statement.children.append(child)

            if child == ';':
                new_children.append(child)

            expression_statement.handle_expression()

            self.children = new_children

        new_children = []
        for child in self.children:
            if isinstance(child, Token) and child.type in [Generic, WeakKeyword]:
                child = Identifier(child)
                child.parent = self
            new_children.append(child)
        self.children = new_children


class Namespace(Statement, CanBeExported):
    # @todo : consider 'module' keyword as equivalent to 'namespace' (>= v1.5)
    begin = Or(Seq(
                Optional(Token('export', Keyword)),
                Optional(Token('default', Keyword)),
                Or(Token('namespace', Keyword),Token('module', Keyword)),
                is_identifier,
                )
                ,
                # require export
                Seq(
                Token('export', Keyword),
                "=",
                Or(Token('namespace', Keyword), Token('module', Keyword)),
                is_identifier,
                )
            )
    end = CurlyBracket

    def __init__(self):
        Statement.__init__(self)
        CanBeExported.__init__(self)

    def get_name(self):
        
        tokens = self.get_children()
        tokens.move_to(["namespace", "module"])
        return next(tokens).text

    def on_end(self):
        """
        check if the Namespace is exported and default export
        """
        self.on_end_export()
        #
class ClassOrInterfaceCommon(CanBeExported):
    def __init__(self):
        CanBeExported.__init__(self)

    def handle_expression(self):

        new_children = []
        tokens = self.get_children()
        for tok in tokens:
            if isinstance(tok, Token) and tok.text not in ['extends', 'implements', 'class', 'export',
                                                           'default', 'abstract']:
                new_children.append(Identifier(tok))
                new_children[-1].parent = self
            else:
                new_children.append(tok)
                if tok.text == "abstract":
                    self.is_abstract = True

        self.children = new_children

    def get_extends(self):
        """
        Returns the inherited classes via "extends"
        """
        self.inherited_classes = []
        tokens = self.get_children()
        token = tokens.move_to('extends')

        if token == 'extends':
            tok = next(tokens)
            if isinstance(tok, Token):
                self.inherited_classes.append(Identifier(tok))
            else:
                self.inherited_classes.append(tok)
        return self.inherited_classes


    def on_end_class_or_interface(self):
        """
        check if the class is exported and default export
        """
        self.on_end_export()  #
        for child in self.get_children():
            if isinstance(child, CurlyBracket):
                return
            #the CurlyBracket may have been wrongly changed to ObjectCurlyBracket
            # in the on_end of CurlyBracket
            elif isinstance(child, ObjectCurlyBracket):
                child.__class__ = CurlyBracket

    def get_implements(self):
        """ Is overided for methods"""
        return []

    def get_direct_inheritances(self):
        """
        Returns all direct inheritances via both "extends" and "implements"
        """
        return self.get_extends() + self.get_implements()

class Class(Statement, ClassOrInterfaceCommon):
    
    begin = Or(
                Seq(Optional(Repeat(Seq(Decorator, Optional(LineFeed)))),
                    Optional(Token('export', Keyword)),
                    Optional(Token('default', Keyword)),
                    Optional(Token('abstract', Keyword)),
                    Token('class', Keyword),
                    is_identifier,
                    ),
                # necessary for mixin classes
                Seq(Token('class', Keyword), 'extends')

                # export = class
                ,
                Seq(Optional(Repeat(Decorator)),
                    Token('export', Keyword),
                    "=",
                    Optional(Token('abstract', Keyword)),
                    Token('class', Keyword),
                    is_identifier,
                    )
                )

    end = Or(CurlyBracket, ObjectCurlyBracket)

    def __init__(self):
        Statement.__init__(self)
        ClassOrInterfaceCommon.__init__(self)

        self.inherited_classes = []
        self.is_abstract = False

    def get_name(self):
        tokens = self.get_children()
        tokens.move_to(['class'])
        name = next(tokens).text
        if name == "extends":
            return "<Anonymous>"
        else:
            return name

    def get_member_declaration(self, member_name: str):
        for field in self.get_fields():
            if field.get_name()==member_name:
                return field.get_identifier()

        for constr in get_descendants(self, Method):
            if not (isinstance(constr, Method) and constr.get_name() == 'constructor'):
                continue
            for param in constr.get_parameters():
                if param.get_name() == member_name:
                    return param.get_identifier()



    def get_implements(self):
        """
        Returns the implemented interfaces via "implements" (abstract classes can be implemented also in TypeScript)
        """
        interfaces = []
        tokens = self.get_children()
        token = tokens.move_to('implements')

        if token == 'implements':
            try:
                while True:
                    token = next(tokens)
                    if isinstance(token, Token):
                        interfaces.append(Identifier(token))
                    else:
                        interfaces.append(token)
                    tokens.move_to([','])

            except StopIteration:
                pass

        return interfaces

    
    def get_decorators(self):
        
        return list(self.get_sub_nodes(Decorator))

    def get_fields(self):
        curly_bracket = next(self.get_sub_nodes(CurlyBracket))
        return list(curly_bracket.get_sub_nodes(Field))

    def on_end(self):
        """
        local parsing of parameters inside parenthesis
        """
        self.on_end_class_or_interface()

class Interface(Statement, ClassOrInterfaceCommon):
    
    begin = Or(Seq(Optional(Repeat(Decorator)),
                Optional(Token('export', Keyword)),
                Optional(Token('default', Keyword)),
                Token('interface', Keyword),
                Or(is_identifier, WeakKeyword),
                )
                ,
                # require interface
                Seq(Optional(Repeat(Decorator)),
                Token('export', Keyword),
                "=",
                Token('interface', Keyword),
                Or(is_identifier, WeakKeyword),
                )
                )
    end = Or(CurlyBracket, ObjectCurlyBracket)

    def __init__(self):
        Statement.__init__(self)
        CanBeExported.__init__(self)

    def get_name(self):
        tokens = self.get_children()
        tokens.move_to(['interface'])
        return next(tokens).text

    def on_end(self):
        """
        local parsing of parameters inside parenthesis
        """
        self.on_end_class_or_interface()

class Parameter(Node):
    """
    Parameter definition node of 
    function/method 
    """

    def __init__(self, children):
        super().__init__()
        self.children = children
        self.is_optional = False
        self._parse_identifiers()
        self.is_spread_param = False
        if self.children[0] == "...":
            self.is_spread_param = True

    def get_name(self):
        """
        return name of the parameter
        """
        name = None
        for token in self.children:
            # when assignment
            if isinstance(token, Assignment):
                identifier = token.get_left_expression()
                name = identifier.get_name()
            elif isinstance(token, ArrowExpression) and token.get_name():
                name = token.get_name()
            elif is_identifier(token):
                try:
                    name = token.get_name()
                except:
                    name = token.text

            if name:
                return name.rstrip('?')  # without 'optional' mark

    def get_identifier(self):
        for token in self.children:
            if token == ":":
                return
            if isinstance(token, Identifier):
                return token

    def reparse_param_containing_default_arrow_expression(self):
        new_children = []
        contains_arrow_expr = False
        for child in self.get_children():

            if isinstance(child, ArrowExpression):
                child.set_name()
                contains_arrow_expr = True
                equal_seen = False
                arrow_expr_new_children = []
                for sub_child in child.get_children():
                    if equal_seen:
                        arrow_expr_new_children.append(sub_child)
                    else:
                        if is_identifier(sub_child) and not isinstance(sub_child, Identifier):
                            new_children.append(Identifier(sub_child))
                        else:
                            new_children.append(sub_child)
                            if sub_child == '=':
                                equal_seen=True
                if equal_seen:
                    child.children = arrow_expr_new_children
                    new_children.append(child)
            else:
                new_children.append(child)
        if contains_arrow_expr and equal_seen:
            self.children = new_children
            for c in new_children:
                c.parent = self

    def _parse_identifiers(self):
        children = self.get_children()
        new_children = []
        for token in children:

            # only as Identifer the first Generic token
            if token.type in [Generic, WeakKeyword]:
                name = token.text
                if not name == name.rstrip("?"):
                    self.is_optional = True
                
                identifier = Identifier(token)
                identifier.parent = self
                new_children.append(identifier)

                break

            new_children.append(token)

        new_children.extend(list(children))
        self.children = new_children

    # TODO: change name to more coherent: -> get_parameter_type
    def get_variable_type(self, seen_asts=None):
        tokens = self.get_children()
        token = tokens.move_to(':')
        if not token:
            return
        tok = next(tokens)
        if tok == 'typeof':
            try:
                return Type(next(tokens))
            except StopIteration:
                return Type(tok)
        return Type(tok)

    # TODO: -> get_default_value?
    def get_value(self):
        """Get default value
        """
        tokens = self.get_children()
        token = tokens.move_to('=')
        if not token:
            return

        return next(tokens)

    def get_function_or_method_ast(self):
        parent = self.parent
        for i in range(4):
            if isinstance(parent, (Function, Method, ArrowExpression)):
                return parent
            try:
                parent = parent.parent
            except AttributeError:
                break
        log.warning("Warning: no function or method found for parameter: {} ".format(str(self)))

    def get_callable(self):
        callable = self.parent
        while not isinstance(callable, (Function, Method, ArrowExpression)):
            try:
                callable = callable.parent
            except AttributeError:
                return
        return callable

    def get_position(self):
        try:
            for i, param in enumerate(self.parent.parent.get_parameters()):
                if param == self:
                    return i
        except AttributeError:
            return
        return


class WithParameters:
    def __init__(self):
        self.is_abstract = False
        self.return_types = []
        self.children = None

    def get_declared_return_types(self):
        return self.return_types

    def get_parameters(self):

        # case of arrow function
        if hasattr(self, 'is_arrow_function') and self.is_arrow_function:
            tokens = self.get_children()
            try :
                for tok in tokens:
                    if tokens.look_next() == "=>":
                        if isinstance(tok, Parenthesis):
                            return list(tok.get_sub_nodes(Parameter))
                        elif isinstance(tok, Parameter):
                            return [tok]
            except :
                log.debug("Problem in get_parameters for node : " + str(self))
        try:
            parens = next(self.get_sub_nodes(Parenthesis))
            return list(parens.get_sub_nodes(Parameter))
        except:
            return []

    def get_parameter_types(self):
        """
        returns a dictionary mapping parameter name
        to its type (type is none if the type is not given)
        """
        result = OrderedDict()
        parameters = self.get_parameters()
        for param in parameters:
            if not isinstance(param, Parameter):
                continue
            name = param.get_name()
            typ = param.get_variable_type()
            result[name] = typ

        return result

    def get_parameter_values(self):
        """
        returns a dictionary mapping parameter name
        to its default values (default value is None if not given)
        """
        result = OrderedDict()
        parameters = self.get_parameters()
        for param in parameters:
            name = param.get_name()
            value = param.get_value()
            result[name] = value

        return result

    def get_ts_type_ast(self):
        """
        returns AST return type
        """
        tokens = self.get_children()
        semicolon = tokens.move_to(':')
        if not semicolon:
            return
        return next(tokens)

    def identify_declared_return_types(self):
        """
        Identify the declared return types for a Function or a Method and store them in the corresponding attributes
        param self: A Method or a Function AST
        """
        if not isinstance(self, (Method, Function, ArrowExpression)):
            return
        if not hasattr(self, "return_types"):
            return
        new_children = []
        prev_token = None
        inside_type_declaration = False
        self.is_abstract = False
        for token in self.children:
            # set the flag for abstract methods if detected
            if ((isinstance(self, Method) or
                 (isinstance(self, ArrowExpression) and self.is_arrow_method))
                    and token == "abstract"):
                self.is_abstract = True
            # usual case for type declaration
            if isinstance(prev_token, Parenthesis) and token == ":":
                inside_type_declaration = True
            # end of declaration
            if (isinstance(token, CurlyBracket) and not prev_token == ':') or token == "=>":
                inside_type_declaration = False
            # only interested in identifies as types are defined with them
            if inside_type_declaration and (is_identifier(token) or token in ['this', 'super']):
                token = Identifier(token)
                token.parent = self
                self.return_types.append(Type(token))
            if inside_type_declaration and isinstance(token, (CurlyBracket, BinaryOperation)):
                sub_children = []
                for sub_child in token.get_children():
                    if isinstance(sub_child, Token) and is_identifier(sub_child):
                        _id = Identifier(sub_child)
                        _id.parent = token
                        sub_children.append(_id)
                    else:
                        sub_children.append(sub_child)
                token.children = sub_children
                self.return_types.append(Type(token))
            new_children.append(token)
            # ignore whitespaces and comments
            if token.type not in [Whitespace, Comment]:
                prev_token = token
        self.children = new_children


def _parse_single_parameter_for_arrow_function(function):

    new_children = []
    tokens = function.get_children()

    for tok in tokens:
        try :
            next_tok = tokens.look_next()
        except StopIteration:
            next_tok = None
        if next_tok == "=>" and is_identifier(tok):
            parameter = Parameter([tok])
            parameter.parent = function
            new_children.append(parameter)
        else :
            new_children.append(tok)
    function.children = new_children


def _parse_parameters(parenthesis):
    new_children = []
    consumed = []
    tokens = parenthesis.get_children()

    if parenthesis.is_empty():
        return

    nb_open_generics = 0
    new_children.append(next(tokens))  # consume '('
    tokens = list(tokens)
    prev_tok_is_colon = False
    for token in tokens:
        if token == "<":
            nb_open_generics += 1
        if token == ">":
            nb_open_generics -= 1

        if token in (',', ')') and not nb_open_generics:
            # handle special case: trailing comma in
            # argument list
            if not consumed and new_children[-1] == ',':
                new_children.append(token)
                break

            if isinstance(consumed[-1], ConstructorField):
                parameter = consumed[-1]
            else:
                parameter = Parameter(consumed.copy())
                parameter.reparse_param_containing_default_arrow_expression()

            # we remove the assignment within the parameter node
            for i, tok in enumerate(parameter.children):
                tok.parent = parameter
                if isinstance(tok, Assignment):
                    break
            if isinstance(tok, Assignment):
                parameter.children = parameter.children[:i] + tok.children + parameter.children[i + 1:]
                for child in parameter.children:
                    child.parent = parameter

            parameter.parent = parenthesis
            new_children.append(parameter)
            new_children.append(token)
            consumed.clear()
        else:
            if prev_tok_is_colon and isinstance(token, Token):
                consumed.append(Identifier(token))
            else:
                consumed.append(token)
            if token == ":":
                prev_tok_is_colon = True
            else:
                prev_tok_is_colon = False

    return new_children


class Function(Statement, WithParameters, CanBeExported):

    begin = Or(
        Seq(Or('const', 'var', 'let'), is_identifier,
            Or(
                Seq(Optional(Seq(":", Generic)), '='),
                Optional(FunctionType)
                ),
            Optional('async'),
            Token('function', Keyword))
        ,
        # default unnamed functions
        Seq(Optional(Token('export', Keyword)),
            Optional(Token('default', Keyword)),
            Optional(Token('async', Keyword)),
            Token('function', Keyword), Optional(Token('*', Operator)), Parenthesis),

        # regular functions
        Seq(
            Optional(Token('export', Keyword)),

            Optional(Token('default', Keyword)),
            Optional(Token('async', Keyword)),
            Token('function', Keyword),
            Optional(Token('*', Operator)),
            Or(Name, WeakKeyword)
            )
        ,
        # export = function           case
        Seq(Token('export', Keyword),
            '=',
            Optional(Token('async', Keyword)),
            Token('function', Keyword)
            )
        )

    end = Or(Seq(Repeat(CurlyBracket), NotFollowedBy(Or('>', '|'))),
             ';',
             Seq(CurlyBracket, LineFeed))

    def __init__(self):
        Statement.__init__(self)
        WithParameters.__init__(self)
        CanBeExported.__init__(self)
        self.name = None
        self.old_name = None

    def get_old_name(self):
        if self.old_name:
            return self.old_name
        else:
            return self.get_name()

    def set_name(self):
        tokens = self.get_children()
        tok = next(tokens)
        is_equal_export = False
        if tok == 'export' and tokens.look_next()=='=':
            is_equal_export = True
        inside_var_decl = False
        while True:
            if tok == '*':
                self.name = tokens.look_next().text
                if self.name == None:
                    self.name = '<Anonymous1>'
                break

            # case of assigned anonymous function : let f = function(){}
            if tok in ["let", 'const', 'var']:
                inside_var_decl = True
                self.name = tokens.look_next().text
                if self.name == None:
                    self.name = '<Anonymous1>'
                    break

            # the parsing was wrong see test_anonym_var_decl_with_type_2 in test_parser.py
            if inside_var_decl and tok == 'async':
                self.old_name = '<Anonymous1>'
                break

            try:
                tok = next(tokens)
            except StopIteration:
                break

        if self.name:
            return self.name

        tokens = self.get_children()
        token = tokens.move_to(['default', 'function'])

        name = ''

        if token == 'default':
            # can be the name if none is provided
            name = 'default'
            tokens.move_to(['function'])

        try:
            token = next(tokens)
            if token.text:
                self.name = token.text
                return token.text
            elif isinstance(token, Parenthesis):
                if is_equal_export:
                    self.name = 'export'
                    self.old_name = '<Anonymous1>'
                else:
                    self.name = "<Anonymous1>"
                return self.name

        except StopIteration:
            pass

        self.name = name
        return name

    def get_name(self):
        if self.name:
            return self.name
        self.set_name()
        if isinstance(self.name, str) and self.name.startswith('<Anonymous') and hasattr(self, 'object_field_name'):
            self.old_name = self.name
            self.name = self.object_field_name
            return self.object_field_name
        if self.name:
            return self.name


    def get_parameters(self):
        params = super().get_parameters()
        return params

    def get_statements(self):
        """
        Access to statements list of the function
        """
        for block in self.get_sub_nodes(CurlyBracket):
            return list(block.get_sub_nodes())
        else:
            return list(self.get_sub_nodes(TSSimpleStatement))
    
    def on_end(self):
        """
        local parsing of parameters inside parenthesis
        """
        super().on_end()

        # check if the function is exported and default export
        self.on_end_export()

    def handle_expression(self):
        # parsing
        try:
            parens = next(self.get_sub_nodes(Parenthesis))
        except StopIteration:
            log.debug("Error parsing parameters in function {}".format(self.get_name()))
            return

        new_parens_children = _parse_parameters(parens)
        if new_parens_children:
            parens.children = new_parens_children

        self.identify_declared_return_types()

    def get_returns(self):

        return get_descendants(self, Return, [Function, Method, ArrowExpression])

    # -------- refactor with those of Method --------
    # methods to be used
    def add_caller(self, caller):
        # print("[add_caller]")
        if isinstance(caller, MemberAccess):
            return

        if not hasattr(self, '_callers'):
            setattr(self, '_callers', [])

        if not caller in self._callers:
            self._callers.append(caller)

    def remove_caller(self, caller):
        if hasattr(self, '_callers'):
            # print("removing caller: ", caller)
            self._callers.remove(caller)

    def get_calling_asts(self):
        """
        Access to other asts calling that function.
        Feed during resolution.
        """

        if not hasattr(self, '_callers'):
            setattr(self, '_callers', [])
        return self._callers


def is_function_return_type(_, stream):
    return is_general_return_type(_, stream, ending_token="=")


def is_return_type(_, stream):
    return is_general_return_type(_, stream, ending_token="=>")


def is_general_return_type(_, stream, ending_token):

    max_token = 6
    n_token = 1
    try :
        while True:
            if n_token > max_token :
                return False

            n_token += 1

            index_of_stream = stream.tokens.index

            # if next_token == ":" or next_token == "=" or next_token == "," or next_token == ">":

            # this is useful for the case test_parser2.p test_function_type()

            next_token = next(stream)
            if next_token == "|" :
                n_token = 0

            if (next_token in [";", ","] or next_token.type == LineFeed
                or isinstance(next_token, CurlyBracket)):
                return False

            if next_token == ending_token:
                stream.tokens.index = index_of_stream
                return True
    except :
        return False

def is_parenthesis_not_following_colon(token,stream):
    if not isinstance(token, Parenthesis):
        return False
    opening_parenthesis = next(token.get_children())
    if not hasattr(opening_parenthesis, "is_following_colon"):
        return True
    return False

class TSType(Statement):

    begin = Seq(Optional(Token('export', Keyword)),
                'type',
                is_identifier,
                Optional(GenericsParameter),
                '='
               )
    end =  Or(Seq(is_identifier, GenericsParameter),
              LineFeed, ";")

    def __init__(self):
        Statement.__init__(self)

    def tag_functiontypes_as_within_type(self, current_node=None):
        """
        we tag all FunctionType within the TSType as within_type to prevent converting them into ArrowExpression
        (see test test_function_types_within_type in test_parser.py)
        """
        for f_type in get_descendants(self, FunctionType):
            f_type.within_type = True


class ArrowExpression(Statement, WithParameters, CanBeExported):
    """
ArrowExpression can be used for implementing :
    - a function
    - a method
All these are parsed as an ArrowExpression (since they have the same structure).
ArrowExpression nodes have the properties is_arrow_function, is_arrow_method
The properties are set in symbols.SourceFile._light_parse() and in symbols.SourceFile._fully_parse()
based on the environment of the ArrowExpression
    """
    begin = Seq(Optional(Repeat(Seq(Decorator, Optional(LineFeed)))),
            Optional(Seq(Token('export', Keyword), Optional('='))),
            Optional(Token('default', Keyword)),
            Optional(Token('static', Keyword)),
            Optional(Token('async', Keyword)),
            Optional(Or('const', 'var', 'let')),
            Optional(Or(Seq(is_identifier_but_not_member, '='),
                        # before handle_expression is called the FunctionType node
                        # contains the =
                        Seq(is_identifier_but_not_member, ":", FunctionType, "="),
                        Seq(is_identifier_but_not_member, ":", FunctionType),  # to be fixed, "=" is sometimes caught by FunctionType
                        Seq(is_identifier_but_not_member, ":", is_function_return_type, "=") #,
                        # Seq(is_identifier_but_not_member, ":", Or(Generic, Parenthesis), "=")
                        )
                    )
            ,
            Optional(Token('async', Keyword)),
            Optional(GenericsParameter),
            Or(Generic,
               Identifier,
               Seq(is_parenthesis_not_following_colon
                   # the return type may be specified after the parameters :
                   # var double = (x):number => 2*x
                   # note that the return type cannot be given when the param in not inside ()
                   # var double = x:number => 2*x // is not valid
                   , Optional(
                            Seq(":", Optional(is_return_type))
                             )
                   ),
               Seq(Parenthesis, ":", Optional(is_return_type))
               )
            , '=>'
            )

    end = Or(LineFeed, ";",
             Seq(is_end_of_arrow_function),

             # the following line is not really needed
             # it is kept only for historical reason
             # i.e. in order not to change the checksum of the arrow exp followed by "," or ":"
             Seq(CurlyBracket, NotFollowedBy(Not(Or(",", ":"))))
             )

    def __init__(self):
        Statement.__init__(self)
        CanBeExported.__init__(self)
        self.name = None
        self.return_types = []
        self.is_arrow_function = False
        self.is_arrow_method = False
        self.is_abstract = False

    def is_getter(self):
        return False

    def on_end(self):
        super().on_end()
        self.on_end_export()

    def get_old_name(self):
        if hasattr(self, 'old_name'):
            return self.old_name
        else:
            return self.get_name()

    def set_name(self, consider_object_fiel_name=True):
        if self.name:
            return self.name

        if self.is_arrow_function:
            tokens = self.get_children()
            for tok in tokens:
                # case of assigned anonymous function : let f = ()=>{} or let f = function(){}
                if tok in ["let", 'const', 'var']:
                    self.name = tokens.look_next().text
                    return

        tokens = self.get_children()
        # we first check if we have an export =
        # in which case the export = must not be considered
        list_tok = list(tokens)
        tokens = self.get_children()
        if list_tok[0] == "export" and list_tok[1] == "=":
            next(tokens)
            next(tokens)

        for tok in tokens:
            try:
                next_tok = tokens.look_next()
                next_text = next_tok.text
                if next_text == "=>":
                    break
            except:
                break
            if isinstance(next_tok, FunctionType) or next_text in ["=", ":"]:
                if not isinstance(tok, Parenthesis) and tok.text:
                    self.name = tok.text
                    return

        tokens = self.get_children()
        try:
            for tok in tokens:
                if tok == "=>":
                    break
                if (tokens.look_next() == "="):
                    if is_identifier(tok) or tok == 'export':
                        self.name = tok.text
                        if tok == 'export':
                            self.old_name = "<Anonymous1>"
                        return
        except StopIteration:
            pass

        self.name = "<Anonymous1>"

    def get_name(self):
        if hasattr(self, 'object_field_name') and self.name!=self.object_field_name:
            self.old_name = self.name
            self.name = self.object_field_name

        if not self.name:
            self.set_name()

        return self.name

    def get_decorators(self):
        return list(self.get_sub_nodes(Decorator))

    def get_parameters(self):
        tokens = self.get_children()
        for tok in tokens:
            try:
                if tokens.look_next() == "=>" or \
                   (tokens.look_next() == ":" and isinstance(tok, Parenthesis)):
                    # case of arrow function without parameter ()=>{};
                    if isinstance(tok, Parenthesis):
                        params = get_descendants(tok, Parameter)
                        if params :
                            return params
                        else :
                            return []
                    return [tok]
            except StopIteration:
                pass
        return params

    def get_statements(self):
        """
        Access to statements list of the function
        """

        # the statement may not be in a CurlyBracket
        tokens = self.get_children()
        tokens.move_to("=>")
        statements = []
        next_tok = tokens.look_next()
        if isinstance(next_tok, CurlyBracket):
            return list(next_tok.get_sub_nodes())

        for tok in tokens:
            statements.append(tok)
        return statements

    def parse_single_expression_as_identifier(self):
        """
        if we have an arrowExpression of type:
        a => b
        will parse b as an identifier. Does nothing otherwise
        """
        children = []
        tokens = self.get_children()
        while True:
            tok = next(tokens)
            children.append(tok)
            if tok == "=>":
                break
        try:
            tok = next(tokens)
        except StopIteration:
            parent = self.parent
            if not isinstance(parent, FunctionType):
                return

            parent_tokens  = parent.get_children()
            parent_new_children = []
            try:
                while True:
                    p_tok = next(parent_tokens)
                    parent_new_children.append(p_tok)
                    if p_tok == self:
                        p_tok = next(parent_tokens)
                        children.append(p_tok)
                        p_tok.parent = self
            except StopIteration:
                parent.children = parent_new_children
                self.children = children
            return
        if not isinstance(tok, Token) or tok.type == String:
            return
        
        next_tok = next(tokens, None)
        if (not next_tok or
            next_tok in [";", ":", ",", "=", ")"] or
            (isinstance(next_tok, Token) and next_tok.type == LineFeed)):
            identifier = Identifier(tok)
            identifier.parent = self

            children.append(identifier)
            if next_tok:
                children.append(next_tok)
            self.children = children

    def handle_expression(self):
        """
Some extra tokens are caught by the ArrowExpression due to the parsing approach used.
We need to remove them from within the ArrowExpression and put them after the ArrowExpression node.
This is the purpose of this handle_expression.

Ideally we would do this in an on_end(), but the parent is not accessible in the on_end() method.

Also parse parameters inside parenthesis
"""
        self.parse_single_expression_as_identifier()
        children = self.children
        for i, child in enumerate(children):
            if child.get_type() == ST:
                string_template = StringTemplate()
                string_template.children = [child]
                self.children[i] = string_template

        last_child = children[-1]
        try:
            text_last = last_child.text
        except:
            pass

        if text_last in [":", ",", "=", ")"] or isinstance(last_child, Decorator):
            self.children = self.children[:-1]

            parent = self.parent
            for i, sibling in enumerate(parent.children):
                if sibling == self:
                    break

            parent.children = parent.children[:i] + [self, last_child] + parent.children[i + 1:]

        # parsing a  parameters
        tokens = self.get_children()
        for token in tokens:
            if tokens.look_next() == "=>" or \
               (tokens.look_next() == ":" and isinstance(token, Parenthesis)):
                if isinstance(token, Parenthesis):  # we have multiple parameters
                    parens = token
                else :
                    _parse_single_parameter_for_arrow_function(self)
                    return
                break

        new_children = _parse_parameters(parens)
        if new_children:
            parens.children = new_children

        self.identify_declared_return_types()

    def get_returns(self):

        # we first check if we have a direct return : let f = (x,y) => x+y ; (x+y is returned)
        tokens = self.get_children()
        tokens.move_to("=>")
        try:
            tok = next(tokens)
            # we have a direct return (there is no need to put return keyword when there is no curlybracket
            if not isinstance(tok, CurlyBracket):
                statements = [tok]
                return statements
        except StopIteration:
            pass
        return get_descendants(self, Return, [Function, Method, ArrowExpression])

    # -------- refactor with those of Method --------
    # methods to be used
    def add_caller(self, caller):
        # print("[add_caller]")
        if not hasattr(self, '_callers'):
            setattr(self, '_callers', [])

        if not caller in self._callers:
            self._callers.append(caller)

    def remove_caller(self, caller):
        if hasattr(self, '_callers'):
            # print("removing caller: ", caller)
            self._callers.remove(caller)

    def get_calling_asts(self):
        """
        Access to other asts calling that function.
        Feed during resolution.
        """

        if not hasattr(self, '_callers'):
            setattr(self, '_callers', [])
        return self._callers


def is_begin_of_method(from_interface=False):
    def to_return(token, stream):
        if not (is_identifier(token) or
                token.type in [Keyword, WeakKeyword] or
                isinstance(token, Decorator)
        ):

            return False
        is_abstract = from_interface
        keyword_that_might_be_identifier_seen = False
        tok = token
        try:
            while True:
                if isinstance(tok, Decorator):
                    tok = next(stream)
                    continue
                if tok == 'abstract':
                    keyword_that_might_be_identifier_seen = True
                    is_abstract = True
                    tok = next(stream)
                    continue
                if tok in ['public', 'private', 'protected', 'static', 'get', 'set']:
                    keyword_that_might_be_identifier_seen = True
                    tok = next(stream)
                    continue
                if tok == 'async':
                    keyword_that_might_be_identifier_seen = True
                    tok = next(stream)
                    continue
                else:
                    break
        except StopIteration:
            return False

        if is_identifier(tok) or tok.type in [Keyword, WeakKeyword]:
            try:
                tok = next(stream)
            except StopIteration:
                return False
        elif not keyword_that_might_be_identifier_seen:
            return False
        if isinstance(tok, GenericsParameter):
            try:
                tok = next(stream)
            except StopIteration:
                return False
        if not isinstance(tok, Parenthesis):
            return False

        if is_abstract:
            return True
        index_of_stream = stream.tokens.index
        try:
            tok = next(stream)
        except StopIteration:
            return False
        if isinstance(tok, (Bracket)) or is_linefeed_or_semicolon(tok):
            return False
        stream.tokens.index = index_of_stream
        return True
    return to_return

class Method(Statement, WithParameters):

    # see https://github.com/Microsoft/TypeScript/blob/master/doc/spec.md#842-member-function-declarations
    begin = is_begin_of_method(False)

    end = Optional(
            Or(Seq(CurlyBracket, CurlyBracket),
               Seq(CurlyBracket, NotFollowedBy("|")),
               ";")
            )

    def __init__(self):
        Statement.__init__(self)
        WithParameters.__init__(self)

    def handle_expression(self):
        """
        local parsing of parameters inside parenthesis
        """
        try:
            parens = next(self.get_sub_nodes(Parenthesis))
        except StopIteration:
            log.debug("Error parsing parameters in method {}".format(self.get_name()))
            return

        new_parens_children = _parse_parameters(parens)
        if new_parens_children:
            parens.children = new_parens_children

        self.identify_declared_return_types()


    def get_returns(self):

        return get_descendants(self, Return, [Function, Method, ArrowExpression])

    def get_name(self):

        tokens = self.get_children()
        while True:
            token = next(tokens)
            if isinstance(tokens.look_next(), (Parenthesis, GenericsParameter)):
                break

        return token.text

    def get_statements(self):
        """
        Access to statements list of the function
        """
        for block in self.get_sub_nodes(CurlyBracket):
            return list(block.get_sub_nodes())
        else:
            return list(self.get_sub_nodes(TSSimpleStatement))

    # methods to be used
    def add_caller(self, caller):

        # print("[add_caller]")
        if not hasattr(self, '_callers'):
            setattr(self, '_callers', [])

        if not caller in self._callers:
            self._callers.append(caller)

    def remove_caller(self, caller):
        if hasattr(self, '_callers'):
            # print("removing caller: ", caller)
            self._callers.remove(caller)

    def get_calling_asts(self):
        """
        Access to other asts calling that function.
        Feed during resolution.
        """

        if not hasattr(self, '_callers'):
            setattr(self, '_callers', [])
        return self._callers

    def is_getter(self):
        tokens = self.get_children()
        tok = next(tokens)
        next_tok = next(tokens)
        while True:
            if isinstance(next_tok, Parenthesis) or next_tok == ':':
                return False
            if isinstance(tok, Token) and tok.text == 'get':
                return True
            tok = next_tok
            try:
                next_tok = next(tokens)
            except StopIteration:
                return False

        return False

    def is_setter(self):
        tokens = self.get_children()
        tok = next(tokens)
        next_tok = next(tokens)
        while True:
            if isinstance(next_tok, Parenthesis) or next_tok == ':':
                return False
            if isinstance(tok, Token) and tok.text == 'set':
                return True
            tok = next_tok
            try:
                next_tok = next(tokens)
            except StopIteration:
                return False

        return False

    def get_decorators(self):
        return list(self.get_sub_nodes(Decorator))


class InterfaceMethod(Method):
    begin = is_begin_of_method(True)

    end = Optional(
            Or(Seq(CurlyBracket, CurlyBracket),
               Seq(CurlyBracket, NotFollowedBy("|")),
               ";")
            )
class ObjectMethod(Term):
    match = Or(
                Seq(Optional(Or(Token('public', Keyword), Token('private', Keyword), Token('protected', Keyword))),
                    Optional(Or(Token('static', Keyword), Token('abstract', Keyword))),
                    Or(Seq(Or('get', 'set'), Or(is_identifier, WeakKeyword, Keyword)),
                       Or(is_identifier, WeakKeyword, Keyword),
                       ),
                    Optional(GenericsParameter),
                    Parenthesis,
                    Optional(Seq(":", is_identifier)),
                    Optional(GenericsParameter),
                    CurlyBracket)
                ,
                Seq(Or(Token('public', Keyword), Token('private', Keyword), Token('protected', Keyword),
                       Token('static', Keyword), Token('abstract', Keyword),
                       'get', 'set'),
                Parenthesis,
                CurlyBracket)
            )

    def __init__(self):
        super().__init__()
        self.__class__ = Method
        self.is_abstract = False
        self.return_types = []


def is_function_type_not_ending_with_equal(token):
    if not isinstance(token, FunctionType):
        return
    if not token.children[-1] == "=" :
        return True

def is_end_of_constructor_field(token, stream):
    index_of_stream = stream.tokens.index

    token = next(stream)
    # if next_token == "=" or next_token == "," or next_token == ">":
    if token == "," or token == ")" :
        stream.tokens.index = index_of_stream
        return True

class ConstructorField(Statement, Parameter):
    """
    A ConstructorField is a param of the constructor.
    It is equivalent to a Field
    """
    begin = Seq(Optional(Decorator),
                Or(Token('public', Keyword), Token('readonly', Keyword), Token('private', Keyword), Token('protected', Keyword)))
    end = Seq(is_end_of_constructor_field)

    def __init__(self):
        Statement.__init__(self)
        self._resolutions = []
        self.is_spread_param = False
        self.is_optional = False

    def get_resolutions(self):
        return self._resolutions

    def remove_node(self):
        parent = self.parent
        new_children = []
        for c in parent.children:
            if c == self:
                for sub_c in self.children:
                    new_children.append(sub_c)
                    sub_c.parent = parent
            else:
                new_children.append(c)
        parent.children = new_children
        self.to_delete = True

    def handle_expression(self):
        try:
            if (not isinstance(self.parent.parent, Method)
                    or self.parent.parent.get_name() != 'constructor'):
                self.remove_node()
                return
        except AttributeError:
            self.remove_node()
            return
        tokens = self.get_children()
        children = [next(tokens)]

        try:
            while True:
                tok = next(tokens)

                if isinstance(tok, Token) and is_identifier(tok):
                    id = Identifier(tok)
                    id.parent = self
                    children.append(id)
                else:
                    children.append(tok)
        except StopIteration:
            pass
        self.children = children

    def get_decorators(self):
        return [child  for child in self.get_children() if isinstance(child, Decorator)]

class Field(Statement):
    
    # see https://github.com/Microsoft/TypeScript/blob/master/doc/spec.md#841-member-variable-declarations
    begin = Seq(Optional(Repeat(Seq(Decorator, Optional(LineFeed)))),
                Optional(Or(Token('public', Keyword), Token('readonly', Keyword),
                            Token('private', Keyword), Token('protected', Keyword))),
                Optional(Token('static', Keyword)), 
                is_identifier,
                Optional('!'),
                Or('=', ':'))
    
    end = Or(";", LineFeed, ArrowExpression, is_function_type_not_ending_with_equal)
    
    def __init__(self):
        super().__init__()
        self.name = None
        self.value = None
        self._resolutions = []

    def get_resolutions(self):
        return self._resolutions

    def handle_expression(self):
        new_children = []
        for child in self.children:
            # if there is an Assignment the parsing was done properly
            if isinstance(child, Assignment):
                return
            elif is_identifier(child):
                identifier = Identifier(child)
                identifier.parent = self
                new_children.append(identifier)
            else:
                new_children.append(child)
        self.children = new_children

    def get_identifier(self):
        tokens = self.get_children()
        token = next(tokens)
        while not is_identifier(token):
            if isinstance(token, Assignment):
                assign_tokens = token.get_children()
                for assign_token in list(assign_tokens):
                    if isinstance(assign_token, Identifier):
                        return assign_token
            token = next(tokens)
        return token

    def get_name(self):

        if self.name:
            return self.name

        tokens = self.get_children()
        token = next(tokens)

        while not is_identifier(token):
            if isinstance(token, Assignment):
                assign_tokens = token.get_children()
                for assign_token in list(assign_tokens):
                    if isinstance(assign_token, Identifier):
                        return assign_token.get_text()

            token = next(tokens)
        if token.text.endswith('?'):
            self.name = token.text[:-1]
        else:
            self.name = token.text

        return self.name
    
    def get_variable_type(self, seen_asts=None):
        tokens = self.get_children()
        try:
            tokens.move_to(':')
            return Type(next(tokens))
        except StopIteration:
            pass

    def get_value(self):
        
        if self.value:
            return self.value

        # in case there is no Assignment
        tokens = self.get_children()
        try:
            tokens.move_to('=')
            return next(tokens)
        except StopIteration:
            pass
        tokens = self.get_children()
        
        try:
            while True:
                token = next(tokens)
                if isinstance(token, Assignment):
                    return token.get_right_expression()
        except StopIteration:
            # log.debug("Error returning value from field")
            pass

    def get_expression(self):
        """synonym for name consistency with VariableDeclarations"""
        return self.get_value()

    def get_decorators(self):
        return [child  for child in self.get_children() if isinstance(child, Decorator)]


class Argument(Node):
    """
    Helper class to handle arguments
    in method and function calls
    """
    def __init__(self, children):
        super().__init__()
        self.children = children
        self.is_lambda_function = False
        self.is_spread_arg = False

        if self.children[0].text == '...':
            self.is_spread_arg = True

    # def __eq__(self, text):
    #     return self.children[0].text == text

    def get_variable_type(self, seen_asts=None):
        if not seen_asts:
            seen_asts = []
        if self in seen_asts:
            return
        seen_asts.append(self)
        if hasattr(self.children[0], 'get_variable_type'):
            return self.children[0].get_variable_type(seen_asts)


    def get_dictionary(self):
        first_child = self.children[0]
        if isinstance(first_child, (Identifier, ObjectCurlyBracket, CurlyBracket)):
            return first_child.get_dictionary()
        else:
            return None

    def get_identifier(self):
        first_child = self.children[0]
        if isinstance(first_child, Identifier):
            return first_child
        else:
            return None

    def get_resolution(self):
        identifier = self.get_identifier()
        if identifier:
            return identifier.get_resolution()

        try:
            return self.children[0].get_resolution()
        except AttributeError:
            pass

class MethodCall(Node, WithResolution, _GenericCall):
    
    def __init__(self):
        Node.__init__(self)
        WithResolution.__init__(self)
        self.links = []
        self.is_imported_from_framework = None
        self.query_handled = False

    def add_link(self, link):
        self.links.append(link)

    def get_method(self):
        tokens = self.get_children()
        tok = next(tokens)

        if is_start_function_call_with_type_assertion(tok, self.get_children()):
            if isinstance(tokens.look_next(), Parenthesis):
                return tok.children[1].children[-1]
        try:
            to_return= next(token for token in tokens
                            if isinstance(tokens.look_next(), (Parenthesis, GenericsParameter)))
        except:
            # tokens.look_next() may result in StopIteration exception
            return None

        # we may have a method_call a.return()
        # the issue is that return is parsed as a Return
        #                we have to enhance LineFeed to be able to remove this fake Return node
        # this is a work around such that MethodCall.get_name() would work in such a case
        if isinstance(to_return, (Return, Break, Continue)):
            to_return = to_return.children[0]
        return to_return
        
    def get_name(self):
        """
        Returns the name of the method called.
        """
        # @todo: not valid when generics? -> m1<T[]>() ?
        # Preceeding token of Parenthesis
        token = self.get_method()
        if isinstance(token, Identifier):
            return token.get_text()
        elif token and token.text:
            return token.text
        else:
            return ''
        
    def get_fullname(self):
        """
        Returns the dotted full name of the method called
        e.g. a.b.c(); --> will return a.b.c
        a(foo).b("foo").c.d("fooagain") --> will return a().b().c.d
        @rtype: str
        """
        expression = ""

        if is_start_function_call_with_type_assertion(self.children[0], self.get_children()):
            if isinstance(self.children[1], Parenthesis):
                return self.children[0].children[1].get_fullname()
        tokens = self.get_children()
        
        for token in tokens:
            if isinstance(token, Parenthesis):
                break
            elif isinstance(token, Identifier):
                expression = expression + token.get_name()
            elif isinstance(token, MemberAccess):
                expression += token.get_fullname()
            elif isinstance(token, MethodCall):
                expression += token.get_fullname() + '()'
            elif isinstance(token, FunctionCall):
                expression += token.get_name() + '()'
            elif token.text:
                expression = expression + token.text
        return expression


    def get_resolved_name(self):
        """
        Return the name that specifies which 
        method a call refers to.
        
        First tries symbol resolution. If resolution 
        is ambiguous it will return
        nothing.
        
        In case the call refers to a method defined in 
        an external class (and most likely not having 
        a corresponding symbol), type resolution will
        be used.
        """
        
        # Use symbol resolution
        # ---------------------
        # print("using method resolution")
        resolutions = self.get_resolutions()
        if resolutions:        
            if len(resolutions) > 1:                
                return  # ambiguous resolution
                
            method = resolutions[0]
            resolved_name = method.get_parent_symbol().get_name() + "." + method.get_name()
            return resolved_name

        # Use type resolution
        # -------------------
        # print("using type resolution")
        expr = self.get_expression()

        # case: a.m1()
        if isinstance(expr, Identifier):
            identifier = expr
            resolution = identifier.get_resolution()
            if resolution:
                declaration = climb(resolution, [VariableDeclaration])
                if declaration:
                    instantiation = declaration.get_expressions()[identifier.get_name()]
                    if isinstance(instantiation, Instantiation):
                        resolved_name = self.get_name()
                        class_name = instantiation.get_class_name()
                        resolved_name = class_name + '.' + resolved_name
            else:
                pass
                # print("No RESOLUTION !!!")

        # case: a.b.m1()
        elif isinstance(expr, MemberAccess):
            pass

        return resolved_name

    def get_expression(self):
        tokens = self.get_children()
        first_child = next(tokens)
        if is_start_function_call_with_type_assertion(first_child, self.get_children()):
            if isinstance(tokens.look_next(), Parenthesis):
                return first_child.children[1].get_expression()
            else:
                return first_child.children[1]
        else:
            return first_child

    def get_root_expression(self):
        """
        Returns the root expression :
        a.b.c() => a
        a().b.c().d => a()
        this.a.b() => this.a
        this.a().b() => this.a()
        """
        expr = self.get_expression()
        if isinstance(expr, (Identifier, FunctionCall)):
            return expr
        elif isinstance(expr, Token) and expr.text == "this":
            return None
        elif isinstance(expr, (MemberAccess, MethodCall)):
            child_root = expr.get_root_expression()
            if not child_root :
                return expr
            else:
                return child_root
        else:
            return None


class FunctionCall(Node, WithResolution, _GenericCall):
    
    def __init__(self):
        Node.__init__(self)
        WithResolution.__init__(self)
        self.is_imported_from_framework = None
        self.original_name = None
        self.declaration = None

    def is_function_call(self):
        return True
    
    def get_function(self):
        return self.children[0]

    def get_declaration(self):
        return self.declaration

    def get_name(self):
        """
        Return the name of the called function.
        """

        tokens = self.get_children()
        tok = next(tokens)
        # (fetch as any)()
        if isinstance(tok, Parenthesis):
            stream = tok.get_children()
            next(stream)
            token = next(stream)
            if isinstance(token, Identifier):
                return token.get_text()
            elif token.text:
                return token.text

        tokens = self.get_children()
        # Preceeding token of Parenthesis or GenericsParameter
        try:
            token = next(token for token in tokens if isinstance(tokens.look_next(), (Parenthesis, GenericsParameter)))
        except StopIteration:
            return ''
        if isinstance(token, Identifier):
            return token.get_text()
        elif token.text:
            return token.text

        #we check if we have require('something')() in which case we whant to return 'somerthing'
        first_child = next(self.get_children())
        to_return = ''
        if isinstance(first_child, FunctionCall) and first_child.get_name() == 'require':
            try:
                to_return = first_child.get_argument(0).children[0].text[1:-1]
            except:
                pass
        return to_return
    
    def is_require_import(self,module_import = None):
        """
        return True if the FunctionCall is a require(module_import)
        """
        if not self.get_name() == 'require':
            return False
        args = self.get_arguments()
        if not len(args) == 1:
            return False
        if not module_import:
            return True
        try :
            text = args[0].children[0].text
            if len(text) > 2 and text[1:-1] == module_import:
                return True
        except (IndexError, AttributeError):
            pass
        
        return False 

    def get_original_name(self):
        """
        Return the original name of the called function.
        import {toto as lala} from 'base';
        function_call.get_original_name() = toto
        """

        return self.original_name


class Declare(Statement):
    begin = Seq(Optional(Token('export', Keyword)),
                Token('declare', Keyword))
    end = Or(';', LineFeed)
             

def handle_expression(node, context=[]):
    if not isinstance(node, Node):
        return node

    # ==============
    # Class
    # =============
    if isinstance(node, ClassOrInterfaceCommon) :
        node.handle_expression()

    if isinstance(node, Throw):
        node.handle_expression()

    elif isinstance(node, Decorator):
        node.handle_expression()


    # =============
    # ArrowExpression
    # =============
    elif isinstance(node, ArrowExpression):
            node.handle_expression()

    elif isinstance(node, Export):
        node.handle_expression()


    elif isinstance(node, Assignment):
        node.handle_expression()

    elif isinstance(node, Parameter):
        node.reparse_param_containing_default_arrow_expression()
        if isinstance(node, ConstructorField):
            node.handle_expression()
            if hasattr(node, 'to_delete'):
            # not sure that handling expression of sub_node is realy necessary but prefer be safe
                for sub_node in node.get_sub_nodes():
                    handle_expression(sub_node, context )
                del node
                return
    # apply recursively expression handling
    for sub_node in node.get_sub_nodes():
        # parentship
        setattr(sub_node, 'parent', node)
        handle_expression(sub_node, context + [node])

    # ===========
    # FunctionType
    # ===========
    if isinstance(node, FunctionType):
        node.handle_expression()

    # ===========
    # Return
    # ===========
    if isinstance(node, Return):
        node.handle_expression()

    # ===========
    # HtmlTag
    # ===========
    elif isinstance(node, HtmlTag):
        node.handle_expression()
    # ===========
    # Bracket
    # ===========
    elif isinstance(node, Bracket):
        node.handle_expression()

    # ===========
    # Function
    # ===========
    elif isinstance(node, Function):
        node.handle_expression()

    # ===========
    # Method
    # ===========
    elif isinstance(node, Method):
        node.handle_expression()

    # ===========
    # VariableDeclaration
    # ===========
    elif isinstance(node, VariableDeclaration):
        node.handle_expression()

    # ===========
    # switch case
    # ===========
    if "switch" in node.children :
        try :
            parse_switch_case(node)
        except :
            log.debug("Error parsing switch case in lines {} -- {}".
                  format(node.get_begin_line(), node.get_end_line()))


    # ==========
    # map
    # ==========
    if isinstance(node, ObjectCurlyBracket):
        node.handle_expression()


    # =======================================
    # function/method calls and member access
    # =======================================
    if isinstance(node, ExpressionStatement):
        node.handle_expression()
        try:
            new_node = parse_calls(node)
        except:
            new_node = None
            log.debug("  Error when parsing calls in expression statement at line {}"
                      .format(node.get_begin_line()))
        
        if new_node:
            parent = context[-1]
            new_children = [new_node if node is child else child for child in parent.children]
            parent.children = new_children
            node=new_node


    # =====================
    # variable declarations
    # =====================
    if isinstance(node, VariableDeclaration):
        parse_variable_declarations(node)



    # =====================
    # fields
    # =====================
    if isinstance(node, Field):
        node.handle_expression()

    #===========================================================================
    # StringTemplate
    #===========================================================================
    if isinstance(node, StringTemplate):
        # we had a text attribute so that stringTemplates can be handled as a string Token
        for child in node.children:
            if hasattr(child, 'is_comment') and child.is_comment():
                continue
            node.text = child.text
        
    # =========
    # If blocks
    # =========
    if isinstance(node, (IfThenElseBlock, WhileBlock, ForBlock)):
        parse_conditions(node)

    # ============
    # return block
    # ============
    if isinstance(node, Return):
        parse_return(node)
    #===========================================================================
    # binary operations
    #===========================================================================
    # we do not subparse GenericsParameters for now (may be needed in some case)
    if not isinstance(node, GenericsParameter) and any(op in node.children for op in all_binary_operators):
        if isinstance(node, ExpressionStatement):
            new_node = substitute(node, BinaryOperation)

            # parse identifiers
            new_children = []
            for child in new_node.get_children():
                if child.type == Generic:
                    identifier = Identifier(child)
                    identifier.parent = new_node
                    new_children.append(identifier)
                    continue
                new_children.append(child)
            new_node.children = new_children

            parent = context[-1]
            new_parent_children = [new_node if node is child else child for child in parent.children]
            parent.children = new_parent_children
            node = new_node
            parse_binary_op_children(node)

        else:
            children = parse_binary_operations_AZU(node.get_children(), parent=node)
            node.children = list(children)

    children = parse_ternary(node.children)
    node.children = children
    for child in node.children:
        child.parent = node
    node = parse_binary_operations_in_variable_decl(node)

    # ===========
    # assignments
    # ===========
    if any([tok in node.children for tok in ["=", '+=', '-=', '||=', '&&=', '??=']]):
        if not isinstance(node, (ArrowExpression, Assignment)):
            try:
                parse_assignments(node)
            except:
                log.debug("Error parsing assignments in lines {} -- {}".
                          format(node.get_begin_line(), node.get_end_line()))


    return node 

def parse_double_lt(node):
    
    n_copy = None
    for i, child in enumerate(node.children):
        try:
            if child in ['<', '>']:
                if isinstance(node.children[i + 1], Token) and node.children[i + 1].text == child.text:
                    i_begin = i
                    if isinstance(node.children[i + 2], Token) and node.children[i + 2].text == child.text:
                        n_copy = 3
                    else:
                        n_copy = 2
                    break
        except IndexError:
            pass
    if n_copy:
        ini_text = node.children[i_begin].text
        for _ in range(n_copy - 1):
            node.children[i_begin].text += ini_text
        node.children[i_begin].end_line = node.children[i_begin + n_copy - 1].end_line
        node.children[i_begin].end_column = node.children[i_begin + n_copy - 1].end_column

        node.children = node.children[:i_begin + 1] + node.children[i_begin + n_copy:]
            
        
def parse_binary_op_children(node):
    parse_double_lt(node)
    expressions = [[]]
    operators = []
    for child in node.children:
        if (child in pure_binary_operators
            or (child in unary_and_binary_operators and (not hasattr(child, 'is_unary_operator') or not child.is_unary_operator))) :
            operators.append(child)
            if expressions[-1]:
                expressions.append([])
        else:
            expressions[-1].append(child)

    for i, expr in enumerate(expressions):

        if not expr:
            log.debug("Problem parsing the binary_operation, the right member is missing " + str(node))
            continue
        # it was already properly parsed
        if len(expr) == 1 and isinstance(expr[0], Node):
            continue
        temporary_node = Node()
        if isinstance(expr, list) and len(expr) > 0 and expr[0] == "!":
            expr_is_unary_op = True
            temporary_node.children = expr[1:]
        else:
            expr_is_unary_op = False
            temporary_node.children = expr

        new_node = parse_calls(temporary_node)
        if new_node == temporary_node or not new_node:
            continue
        if type(new_node) == Node:
            new_node = new_node.children
        if expr_is_unary_op:
            unary_op = UnaryOperation()
            
            if isinstance(new_node, list):
                unary_op.children = [expr[0]] + new_node
            else :
                unary_op.children = [expr[0]] + [new_node]
            for child in unary_op.children:
                child.parent = unary_op
            new_node = unary_op
        expressions[i] = new_node

    new_children = []
    for i, expr in enumerate(expressions):
        new_children = new_children + (expr if isinstance(expr, list) else [expr])
        if i < len(operators):
            new_children = new_children + [operators[i]]

    node.children = new_children
    for child in node.children:
        child.parent = node


def parse_binary_operation(tokens, parent):
    """
    This function takes the list of tokens and creates binary nodes if binary operation is found.
    Nested binary operations are taken care of.
    """
    binary_node = False
    binary_operation = None
    
    children = tokens
    tokens = Lookahead(children)
    

    try :
        for token in tokens :
            
            if (tokens.look_next() in all_binary_operators and
                not isinstance(token, GenericsParameter)
                ):
                
                left_binary = token
                operator = next(tokens)
                
                #=====================================================================
                # Try - Except - Else
                # Try and except are mainly to handle unusual ending like a = b+
                # Else does the main job for creation of binary and nested binary nodes
                #======================================================================
                try :
                    next_node = tokens.look_next()
                
                except StopIteration:  
                    # Unusual ending in case of nested binary, 
                    # Add the children to parent binary node and exit
                    # In a plain case, e.g. var a = b+, just break from the loop and return children list
                    if binary_node : 
                        binary_operation.children.append(left_binary)
                        binary_operation.children.append(operator)
                    break
                
                else :
                    if binary_node : # nested binary nodes
                        
                        remaining_tokens = [left_binary, operator]
                        remaining_tokens.extend(tokens)
                        
                        nested_node = parse_binary_operation(remaining_tokens, binary_operation)
                        
                        # TODO: refactor to avoid returning two different types (list & BinaryOperation)
                        if isinstance(nested_node, BinaryOperation):
                            binary_operation.children.append(nested_node)
                        else : # Returned output may be a list in case the nested binary operation does not end properly i.e. var a = b + c+
                            binary_operation.children.extend(nested_node)
                
                    else :
                        if next_node == ";":  # Handling unusual endings like var a = b+; If next node is ';' then no need to create binary operation node
                            break
                        
                        binary_operation = BinaryOperation()
                        binary_operation.parent = parent
                        binary_operation.children.extend([left_binary, operator]) # Add the token before binary operator and binary operator
                        
                        binary_node = True
                    
            elif binary_node :# Deals with the token after the operator
                binary_operation.children.append(token)
        
        
    except StopIteration:
        if binary_operation :
            binary_operation.children.append(token)
            for child in binary_operation.get_sub_nodes():
                child.parent = binary_operation
                
    if binary_operation:
        for child in binary_operation.get_sub_nodes():
            child.parent = binary_operation
        return binary_operation
    # If no binary operation was found
    return children


def parse_binary_operations_in_variable_decl (node ):
    """
    This function returns the variable declaration node after parsing the binary operations 
    """
    
    if isinstance(node, VariableDeclaration):
        
        node_new_children = []
        tokens = node.get_children()
        
        for token in tokens :
            
            node_new_children.append(token)
            
            if token.type == Operator and token in ['=']:
                # for multiple variable declarations we need to select
                # only tokens before "," for parsing the binary operation
                list_tokens = []
                next_is_comma = False
                comma_token = None
                while not next_is_comma :
                    try :
                        next_tok = tokens.look_next()
                        if next_tok == ",":
                            next_is_comma = True
                            token = next(tokens)
                            comma_token = token
                        else :
                            list_tokens.append(next_tok)
                            token = next(tokens)
                    except :
                        break

                list_tokens = parse_ternary(list_tokens)

                binary_node = parse_binary_operation(list_tokens, node)
                
                if isinstance(binary_node, BinaryOperation):
                    node_new_children.append(binary_node)
                else:
                    # No BinaryOperation node is parsed
                    node_new_children.extend(binary_node)

                if comma_token:
                    node_new_children.append(comma_token)

        node.children = node_new_children
    
    return node


def parse_conditions(node):


    tokens = node.get_children()
    node = None
    i = 0
    while not isinstance(node, Parenthesis):
        try:
            node = next(tokens)
            i+=1
        except:
            return
        if i>3 :
            return
    new_children = []

    tokens = node.children
    new_children = []
    new_children.append(tokens[0])

    # Iterating over the children of Parenthesis but escaping "(" and ")"
    condition = None
    for index, token in enumerate(tokens[1:-1]):
        if index == 0 :
            condition = Condition()  # For the first condition in If
            condition.parent = node

        condition.children.append(token)

    for child in condition.get_sub_nodes():
        child.parent = condition

    new_children.append(condition)

    if new_children:
        new_children.append(tokens[-1])
        node.children = new_children
        return


def parse_return(node):
    tokens = node.get_children()
    tokens = parse_binary_operations_AZU(tokens, parent=node)
    node.children = list(tokens)
    for sub_node in node.get_sub_nodes():
        sub_node.parent = node


def parse_variable_declarations(node):
    """
    References:
      https://www.typescriptlang.org/docs/handbook/variable-declarations.html
      https://stackoverflow.com/questions/34232315/declaring-multiple-typescript-variables-with-the-same-type
    """

    def add_identifier(new_children, token, node):
        identifier = Identifier(token)
        identifier.parent = node
        new_children.append(identifier)

    consumed = []
    new_children = []
    inside_type = False
    tokens = node.get_children()
    try:
        while True:
            token = next(tokens)
            if not inside_type and is_token_subtype(token.type, Generic):
                new_children.extend(consumed)
                consumed.clear()
                add_identifier(new_children, token, node)
            else:                
                consumed.append(token)

                if token == ':':
                    inside_type = True  # avoids wrapping types as identifiers
                elif token in (',', '='):
                    inside_type = False
#                     if token == '=':
#                         tokens = parse_binary_operations_AZU(tokens)

    except StopIteration:
        pass

    if new_children:
        new_children.extend(consumed)
        node.children = new_children


def check_for_assignment(tokens):
    assign = any (ch_text in ['=', '+=', '-=', '||=', '&&=', '??='] for ch_text in [child.text for child in tokens])
    return True if assign else False
    
def create_and_add_identifier(token, node):
    identifier = Identifier(token)
    identifier.parent = node
    
    return identifier

def parse_assignment_in_field(node):
    
    token_line = []
    tokens_list = []
    
    # This loop filters out all the whitespaces and comments of the node
    # Creates a list of list where each nested list consists 
    # all the token of a line (including LineFeed
    for token in node.children :
        if not isinstance(token, Node):
            if token._Token__is_whitespace() or token._Token__is_comment():
                if token.type == LineFeed :
                    tokens_list.append(token_line)
                    token_line = []
                continue
        token_line.append(token)     
        
    if token_line :
        tokens_list.append(token_line)        
    
    new_children = []
    
    for i in range(len(tokens_list)):
    
        token_line = tokens_list[i]
        
        assignment = Assignment()
        assignment.parent = node
        
        if check_for_assignment (token_line) and isinstance(token_line[0], Token) and token_line[0].text in ['public', 'private', 'protected', 'static', 'abstract']:
            keyword = [token_line[0]]
            token_line = token_line[1:]
        else :
            keyword = []

        for index, token in enumerate(token_line):
            line_ended = False
            if isinstance(node, Field) and isinstance(token, Decorator):
                new_children.append(token)
                continue
            if not check_for_assignment (token_line):
                new_children.append(token)
                continue
           
            if is_token_subtype(token.type, Generic):
                assignment.children.append(create_and_add_identifier(token, assignment))  # left expression
            else:
                assignment.children.append(token)
                 
            if token == '=':
                tokens = iter(token_line[index+1 :])  # Create iterator for remaining tokens in the line
                try :
                    while True :
                        token = next(tokens)
                        
                        if token.text in [")", "}", ']']:
                            new_children += keyword + [assignment]
                            break
                         
                        if is_token_subtype(token.get_type(), Generic):
                            token = create_and_add_identifier(token, [assignment])
                        
                        assignment.children.append(token)  # right expression
                              
                except StopIteration :
                    try :
                        # When the field assignment is spread over multiple lines
                        if assignment.children[-1] == "=" and tokens_list[i+1] :
                            assignment.children.extend(tokens_list[i+1])
                            i = i + 1
                    except :
                        pass
                    new_children += keyword + [assignment]
                    line_ended = True
                    break
            if line_ended :
                break
        for child in assignment.get_children():
            child.parent = assignment

        if any(op in assignment.children for op in all_binary_operators):
            children = parse_binary_operations_AZU(assignment.get_children(), parent=node)
            assignment.children = list(children)
    return new_children

def parse_assignments(node):

    if isinstance(node, (VariableDeclaration, Parameter)):
        # we choose NOT to add an additional node inside
        # VariableDeclaration and Parameter nodes, for 3 reasons:
        # (1) Reducing the AST density
        # (2) responsability of handling particularities
        #     such as types, multiple declarations etc will
        #     rely on each particular node
        # (3) an assignment inside VariableDeclaration or Parameter is not a "statement" by themselves
        return

    if isinstance(node, Field):
        new_children = parse_assignment_in_field(node)
        node.children = new_children
        return

    # check if we have an assignment of an anonymous function
    if isinstance(node, (Function, ArrowExpression)):
        return

    consumed = []
    new_children = []
    tokens = node.get_children()
    seen_nested_assign = False

    try:
        while True:
            token = next(tokens)
            consumed.append(token)
            if tokens.look_next() in ('=', '+=', '-=', '||=', '&&=', '??='):
                if token == "export":  # we have a default export and not an assignment
                    continue
                assignment = Assignment()
                assignment.parent = node
                if (len(consumed) > 3 and
                        consumed[-2]==":" and
                        consumed[-3] not in ["default"] and
                        consumed[-4] not in ["case"]) :
                    left_tokens = consumed[-3:]
                    consumed = consumed[:-3]
                else:
                    left_tokens = [consumed[-1]]
                    consumed = consumed[:-1]
                left_token = left_tokens[0]
                if is_token_subtype(left_token.type, Generic):
                    identifier = Identifier(left_token)
                    identifier.parent = assignment
                    assignment.children.append(identifier)  # left expression
                else:
                    assignment.children.append(left_token)
                if len(left_tokens) > 1:
                    prev_tok = None
                    for tok_loc in left_tokens[1:]:
                        if prev_tok == ":" and is_token_subtype(tok_loc.type, Generic):
                            identifier = Identifier(tok_loc)
                            identifier.parent = assignment
                            assignment.children.append(identifier)
                        else:
                            assignment.children.append(tok_loc)
                        prev_tok = tok_loc
                assignment.children.append(next(tokens))  # '='
                tokens = parse_binary_operations_AZU(tokens, parent=assignment)
                token = next(tokens)
                new_assignment = Assignment()
                new_assignment.parent = assignment
                if is_token_subtype(token.type, Generic) or isinstance(token, MemberAccess):
                    try:
                        next_token = tokens.look_next()
                    except StopIteration:
                        if is_token_subtype(token.type, Generic):
                            identifier = Identifier(token)
                            identifier.parent = assignment
                            token = identifier
                        assignment.children.append(token)
                    else:
                        if next_token == '=':
                            seen_nested_assign = True
                            assignment.children.append(new_assignment)
                            if is_token_subtype(token.type, Generic):
                                identifier = Identifier(token)
                                identifier.parent = new_assignment
                                token = identifier
                            else:
                                token.parent = new_assignment
                            new_assignment.children.append(token)
                            next_tok = next(tokens)
                            next_tok.parent = new_assignment
                            new_assignment.children.append(next_tok)
                        elif is_token_subtype(token.type, Generic):
                            identifier = Identifier(token)
                            identifier.parent = assignment
                            token = identifier
                            assignment.children.append(token)
                        else:
                            token.parent = assignment
                            assignment.children.append(token)
                else:
                    assignment.children.append(token)  # right expression
                for child in assignment.get_children():
                    child.parent = assignment
                new_children.extend(consumed + [assignment])
                consumed.clear()

                if tokens.look_next() == ';':
                    assignment.children.append(next(tokens))
                elif seen_nested_assign:
                    seen_nested_assign = False
                    token = next(tokens)
                    if is_token_subtype(token.type, Generic):
                        identifier = Identifier(token)
                        identifier.parent = new_assignment
                        token = identifier
                    else:
                        token.parent = new_assignment
                    new_assignment.children.append(token)

    except StopIteration:
        if new_children:
            new_children.extend(consumed)
            node.children = new_children
            return


def substitute(old_expression, _type, children=None):
    """
    Return a new Node with substituted "_type"
    """
    expression = _type()
    if children:
        expression.children = children
    else:
        expression.children = old_expression.children

    try:
        expression.parent = old_expression.parent
    except AttributeError:
        pass

    for child in expression.children:
        child.parent = expression

    return expression

def parse_ternary(tokens):
    """
    A basic parser of a ternary operation
    """
    result = []

    if "?" in tokens and ":" in tokens:
        tokens = Lookahead(TokenIterator(tokens))

        ternary = IfTernary()
        current_ternary = ternary
        previous_token = None
        seen_interrogation_mark = False
        token = next(tokens)
        new_ternary = None
        while True:
            try:
                next_token = tokens.look_next()
            except StopIteration:
                next_token = None

            if next_token == "?" and not seen_interrogation_mark:
                seen_interrogation_mark = True
                result.append(ternary)

            if seen_interrogation_mark:
                if previous_token == ":":
                    if next_token != "?":
                        if is_identifier(token) and not isinstance(token, Identifier):
                            identifier = Identifier(token)
                            identifier.parent = current_ternary
                            current_ternary.children.append(identifier)
                        else:
                            token.parent = current_ternary
                            current_ternary.children.append(token)
                        break
                    else:
                        new_ternary = IfTernary()
                        current_ternary = new_ternary
                        token.parent = new_ternary
                        new_ternary.children.append(token)
                        new_ternary.parent = ternary
                        ternary.children.append(new_ternary)
                else:
                    token.parent = current_ternary
                    current_ternary.children.append(token)

                previous_token = token

            else:
                result.append(token)

            try:
                token = next(tokens)
            except StopIteration:
                break

        result = result + list(tokens)

    if not result:
        return tokens

    return result


def parse_parenthesis_of_call(parenthesis):
    new_children = []
    for token in parenthesis.get_children():
        if is_token_subtype(token.type, Generic):
            identifier = Identifier(token)
            identifier.parent = parenthesis
            token = identifier
        # @todo: parse constants
        new_children.append(token)

    new_children = parse_ternary(new_children)
    new_children = list(parse_binary_operations_AZU(Lookahead(new_children), parent=parenthesis))
    parenthesis.children = new_children
    for child in parenthesis.children:
        child.parent = parenthesis


def parse_calls(node):
    """
    Parses:
        method calls
        function calls
        array access
    
    Parsing is performed recursevily
    in chained calls 
    """

    for op in all_binary_operators:
        if op in node.children:
            return node

    # Warning: we parse the access/calls expressions
    # starting from the rigthmost tokens.
    # rtokens denotes the "tokens" generator in
    # reversed order (whitespaces are skipped)
    rtokens = reversed(list(node.get_children()))
    consumed = []

    token = next(rtokens)
    consumed.append(token)
    
    if token == ";" or (isinstance(token, Token) and token.type == LineFeed):
        token = next(rtokens)
        consumed.append(token)

    if isinstance(token, Bracket):
        # a.b().c[].d...p.q[] -->  ArrayAccess[ ExpressionStatement[a.b().c[].d..] .p.q[]]
        expression = ExpressionStatement()
        children = list(reversed(list(rtokens)))
        new_children = list(reversed(consumed))
         
        if len(children) > 1:
            # a.b.c.d[]  --> ArrayAccess[ ExpressionStatement[a.b.c] .d[] ]
            expression.children = children
            new_expression = parse_calls(expression)
            if new_expression:
                expression = new_expression
            new_children = [expression] + new_children
            array_access = substitute(node, ArrayAccess, new_children)
            expression.parent = array_access
        else:
            # a[]      -->  ArrayAccess[a[]]
            new_children = [Identifier(children[0])] + new_children
            array_access = substitute(node, ArrayAccess, new_children)
         
        return array_access

    if not isinstance(token, Parenthesis):

        # @todo: revise redifinitions of a parent link when token is a node
        try:
            token = next(rtokens)

        except:
            # no more dot access
            return node

        else:
            if not token == '.':

                if token.type == Generic:
                    last_tok = Identifier(token)
                    last_tok.parent = node
                else:
                    last_tok = token
                prev_tokens = []
                preceed_semi_colon = False

                while True:
                    try:
                        prev_tok = next(rtokens)
                    except StopIteration:
                        break
                    if preceed_semi_colon and prev_tok.type == Generic:
                        id = Identifier(prev_tok)
                        id.parent = node
                        prev_tokens.insert(0, id)
                    else:
                        prev_tokens.insert(0, prev_tok)
                    if prev_tok == ',':
                        preceed_semi_colon = True
                    else:
                        preceed_semi_colon = False

                new_children = prev_tokens + [last_tok] + consumed
                node.children = new_children

                return node

            consumed.append(token)
        
        expression = ExpressionStatement()
        children = list(reversed(list(rtokens)))
        new_children = list(reversed(consumed))
        member_access = None
        if len(children) > 1:
            # a.b.c.d  -->  MemberAccess[ ExpressionStatement[a.b.c] .d]
            expression.children = children
            new_expression = parse_calls(expression)
            if new_expression:
                expression = new_expression
            
            offset = 0
            if new_children[-1] == ';':
                offset = 1
            if isinstance(new_children[-1 - offset], Identifier):
                member = new_children[-1 - offset]
            else:
                member = Identifier(new_children[-1 - offset])
            
            new_children = [expression] + new_children[:-1 - offset] + [member]
            member_access = substitute(node, MemberAccess, new_children)
            expression.parent = member_access
            
        elif len(children)>0:
            # a.b  -->  MemberAccess[a.b]
            # Note: offset and rest serve to handle the optional ending ';'
            child = new_children[-1]
            if not isinstance(child, Identifier) and isinstance(child, Node):
                # log.debug("Unexpected member-access identifier: {}".format(node))
                return None
            else:
                offset = 0
                if child == ";":
                    offset = 1
                if isinstance(new_children[-1 - offset], Identifier):
                    member = new_children[-1 - offset]
                else:
                    member = Identifier(new_children[-1 - offset])
                child = children[0]
                if child.type == Generic:
                    instance = Identifier(children[0])
                else:
                    instance = child
                rest = []
                if offset:
                    rest = [new_children[-1]]
                new_children = [instance] + new_children[:-1 - offset] + [member] + rest
                    
                member_access = substitute(node, MemberAccess, new_children)
                member.parent = member_access
                instance.parent = member_access

        return member_access

    # parse arguments inside parenthesis
    parse_parenthesis_of_call(token)

    try:
        rtokens, rtokens_copy = itertools.tee(rtokens)
        token = next(rtokens)
    except StopIteration:
        return node
    consumed.append(token)
    
    if isinstance(token, GenericsParameter):
        token = next(rtokens)
        consumed.append(token)

    if is_start_function_call_with_type_assertion(token, rtokens_copy):
        if isinstance(node.children[0].children[1], MemberAccess):
            return substitute(node, MethodCall, children=list(reversed(consumed)))
    try:
        token = next(rtokens)
        if token == '.':
            consumed.append(token)
            try :
                token = next(rtokens)
                consumed.append(token)

                token = next(rtokens)
                consumed.append(token)
            except StopIteration:

                last = consumed[-1]
                if last != '.' and is_token_subtype(last.type, Generic):
                    last = Identifier(last)
                    consumed = consumed[:-1] + [last]
                return substitute(node, MethodCall, children=list(reversed(consumed)))
        else:
            return substitute_to_function_call(node)
    except StopIteration:
        return substitute_to_function_call(node)

    # a.b.c().d...p.q() -->  MethodCall[ ExpressionStatement[a.b.c().d..] .p.q()]
    expression = ExpressionStatement()  # auxiliary Node
    expression.children = list(reversed(list(rtokens))) + list(reversed(consumed[-2:]))
    new_expression = parse_calls(expression)
    if new_expression:
        new_children = [new_expression] + list(reversed(consumed[:-2]))
        new_node = substitute(node, MethodCall, new_children)
        expression.parent = new_node
        return new_node


def substitute_to_function_call(node):
    if "=" in node.children:
        return
    function_call = substitute(node, FunctionCall)

    # if there are more than one parenthesis we have a nested function call : a()()
    children = list(function_call.get_children())
    function_call.children = children
    if function_call.children[-1] == ';':
        switch = 1
    else:
        switch = 0
    if isinstance(function_call.children[-1-switch], Parenthesis):
        function_call.children[-1-switch] = parse_calls(function_call.children[-1-switch])
    if not len(children)>2+switch or not (isinstance(children[-1-switch], Parenthesis) and isinstance(children[-2-switch], Parenthesis)):
        return function_call

    expression = ExpressionStatement()  # auxiliary Node
    expression.children = children[:-1-switch]
    new_expression = parse_calls(expression)
    new_expression.parent = function_call
    function_call.children = [new_expression, children[-1-switch]]
    if switch == 1:
        function_call.children.append(children[-1])

    return function_call


def parse_switch_case (node):
    """
    Re-arrange the children of SwitchCase to form Cases.
    """
    
    curly_bracket_nodes = node.get_sub_nodes(CurlyBracket)
    
    new_children = []
    for cb_node in curly_bracket_nodes :
        tokens = cb_node.get_children()
        
        try :
            while True : 
                token = next(tokens)
                last_token = False
                
                if token.text == "case"  or token.text == "default":
                    case_block = Case()
                    case_block.parent = cb_node
                    case_block.children.append(token)
                    token = next(tokens)
                    try :
                        while  True:
                            
                            if tokens.look_next() == "case"  or \
                               tokens.look_next() == "default":
                                case_block.children.append(token)
                                break
                             
                            case_block.children.append(token)
                            token = next(tokens)
                         
                    except StopIteration  :
                        last_token = True
                        pass
                    new_children.append(case_block)
                    for child in case_block.children:
                        child.parent = case_block
                    if last_token :
                        new_children.append(token)
                else :
                    new_children.append(token)
        except StopIteration:
            pass
        
        cb_node.children = new_children
    return
         
class ArrayAccess(Statement):
    """
    exp [...]
    """
    
    def get_arguments(self):
        """
        Get the arguments passed by the ArrayAccess
        """
        bracket = next(reversed(list(self.get_sub_nodes(Bracket))))
        return bracket.children[1:-1]

    def get_name(self):
        id = self.children[0]
        try:
            return id.get_name()
        except AttributeError:
            return

    
class MemberAccess(Statement, WithResolution):
    
    def __init__(self):
        Statement.__init__(self)
        WithResolution.__init__(self)

    def get_resolution(self):
        resol = WithResolution.get_resolution(self)
        if resol:
            return resol

        resol = self.get_member().get_resolution()
        if resol == self:
            return
        if resol:
            return resol

        expr = self.get_expression()
        if not hasattr(expr, 'get_resolution'):
            return resol
        expr_resol = expr.get_resolution()
        if hasattr(expr_resol, 'get_ast') and isinstance(expr_resol.get_ast(), Identifier):
            assigned = expr_resol.get_ast().get_assigned_expression()
            if isinstance(assigned, ObjectCurlyBracket):
                assigned_as_dict = assigned.get_dictionary()
                if self.get_name() in assigned_as_dict:
                    return assigned_as_dict[self.get_name()]
            elif isinstance(assigned, CurlyBracket):
                for i in assigned.get_children():
                    if not isinstance(i, Identifier):
                        continue
                    if i.get_name()==self.get_name():
                        return i

        elif hasattr(expr_resol, 'get_symbol'):
            resol = expr_resol.get_symbol(self.get_name())
            if resol:
                self._resolutions = [resol]
                return resol

    def is_set(self):
        if isinstance(self.parent, Assignment):
            if self.parent.get_left_expression() == self:
                return  True
        return  False

    def get_member(self):
        return next(reversed(list(self.get_sub_nodes(Identifier))))

    def get_expression(self):
        return next(self.get_children())

    def get_root_expression(self):
        """
        Returns the root expression :
        a.b.c() => a
        a().b.c().d => a()
        this.a.b() => this.a
        this.a().b() => this.a()
        """
        expr = self.get_expression()
        if isinstance(expr, (Identifier, FunctionCall)):
            return expr
        elif isinstance(expr, Token) and expr.text == "this":
            return None
        elif isinstance(expr, (MemberAccess, MethodCall)):
            child_root = expr.get_root_expression()
            if not child_root :
                return expr
            else:
                return child_root
        else:
            return None

    def get_name(self):
        member = self.get_member()
        if isinstance(member, Identifier):
            return member.get_name().rstrip('?')
        elif isinstance(member, Token):
            return member.text.rstrip('?')

    def get_variable_type(self, seen_asts=None):
        """
        return the possible declared type of the member.
        """
        if hasattr(self.get_resolution(), 'get_ast'):
            resol_ast = self.get_resolution().get_ast()
            if hasattr(resol_ast, 'get_variable_type'):
                return resol_ast.get_variable_type()
        if not seen_asts:
            seen_asts = []
        if self in seen_asts:
            return
        seen_asts.append(self)
        if hasattr(self.get_member(), "get_variable_type"):
            return self.get_member().get_variable_type(seen_asts)

    def get_fullname(self):
        """
        Returns the dotted full name of the member access
        e.g. a.b.c; --> will return a.b.c
        a(foo).b("foo").c --> will return a().b().c
        @rtype: String
        """
        expression = ""
        tokens = self.get_children()

        for token in tokens:
            if isinstance(token, Parenthesis):
                break
            elif isinstance(token, Identifier):
                expression = expression + token.get_name()
            elif isinstance(token, MemberAccess):
                expression += token.get_fullname()
            elif isinstance(token, MethodCall):
                expression += token.get_fullname() + '()'
            elif isinstance(token, FunctionCall):
                expression += token.get_name() + '()'
            elif token.text and token.text != ";":
                expression = expression + token.text
        return expression




class VariableDeclaration(Statement):

    begin = Or('const', 'var', 'let')
    end = Or(";", LineFeed)

    def __init__(self):
        super().__init__()

    def on_end(self):
        new_children = []
        next_is_variable = False
        var_found = False
        equal_found = False
        for child in self.children:
            if var_found:
                new_children.append(child)
                if child == '=' and not equal_found:
                    equal_found = True
                    child.is_var_decl_equal = True
                continue

            if next_is_variable and is_identifier(child) and not isinstance(child, Identifier):
                id = Identifier(child)
                id.parent = self
                new_children.append(id)
                next_is_variable = False
                var_found = True
            else:
                new_children.append(child)
                if child in ['const', 'var', 'let']:
                    next_is_variable = True

        self.children = new_children

    def handle_expression(self):
        if isinstance(self.children[0], VariableDeclaration):
            self.children = self.children[0].children
            for child in self.children:
                child.parent = self

        new_children = []
        prev_child = None
        for child in self.get_children():
            # if isinstance(child, ObjectCurlyBracket):
            #     if not any([sub_child == ':' for sub_child in child.get_children()]):
            #         new_child = CurlyBracket()
            #         new_child.children = child.children
            #         for ch in child.children:
            #             ch.parent=new_child
            #         new_child.parent = self
            #         child = new_child
            if isinstance(child, CurlyBracket):
                self.parse_curly_bra(child)
            if isinstance(child, ObjectCurlyBracket) and prev_child not in [':', '=']:
                self.create_fake_m_a(child)
            if prev_child ==':' and is_identifier(child) and not isinstance(child, Identifier):
                new_child = Identifier(child)
                new_child.parent = self
                new_children.append(new_child)
            else:
                new_children.append(child)
            prev_child = child

        self.children = new_children

    def create_fake_m_a(self, obj_curly_bra):
        for attr, identifier in obj_curly_bra.get_dictionary().items():
            if not isinstance(identifier, Identifier):
                log.debug('Unsuported destructuration case')
                log.debug(str(obj_curly_bra))
                continue
            fake_member_access = MemberAccess()
            fake_member_access.children.append(Identifier(Token('fakeexpr', pygmentsToken.Generic)))
            fake_member_access.children.append(Token('.', pygmentsToken.Punctuation))
            fake_member_access.children.append(Identifier(Token(attr, pygmentsToken.Generic)))
            for child in fake_member_access.children:
                child.parent = fake_member_access
            identifier.resolve_to(fake_member_access)

    def parse_curly_bra(self, curly_bra):
        new_children = []
        i = 0
        tokens = curly_bra.get_children()
        tok = next(tokens)
        new_children.append(tok)
        tok = next(tokens)
        if not is_identifier(tok):
            return
        if not isinstance(tok, Identifier):
            id = Identifier(tok)
            id.parent = curly_bra
        else:
            id=tok

        new_children.append(id)

        tok = next(tokens)
        new_children.append(tok)

        try:
            next(tokens)
        except StopIteration:
            curly_bra.children = new_children
            fake_member_access = MemberAccess()
            fake_member_access.children.append(Identifier(Token('fakeexpr', pygmentsToken.Generic)))
            fake_member_access.children.append(Token('.', pygmentsToken.Punctuation))
            fake_member_access.children.append(Identifier(Token(id.get_name(), pygmentsToken.Generic)))
            for child in fake_member_access.children:
                child.parent = fake_member_access
            id.resolve_to(fake_member_access)


    def get_name(self):
        """
        Return name of variable
        """
        tokens = self.get_children()
        token = next(tokens)
        
        if token.text in ["let", "const", "var"]:
            token = next(tokens)
        
        elif token.text == "export":
            next(tokens)
            token = next(tokens)

        if not hasattr(token, 'get_text'):
            return
        var_name = token.get_text()
        
        return var_name
    
    # to get deprecated
    def get_identifier(self):
        tokens = self.get_children()
        try:
            while True:
                token = next(tokens)
                if isinstance(token, Identifier):
                    return token

        except StopIteration:
            pass
    
    def get_variables(self):
        """
        Returns the list of variables defined inside
        a variable declaration statement
        
        This should deprecate above "get_identifier"
        """

        class EnhancedList(list):
            """
            Experimental enhancement class for 
            lists of certain type of nodes
            """
            def get_names(self):
                try:
                    return [var.get_name() for var in self]
                except AttributeError:
                    return []

        to_return = []
        tokens = self.get_children()
        try:
            token = next(tokens)

            while not token.text in ["let", "const", "var"]:
                token = next(tokens)
            next_tok = next(tokens)
        except StopIteration:
            return EnhancedList([])
        if isinstance(next_tok, CurlyBracket):
            sub_tokens = next_tok.get_children()
            try:
                next(sub_tokens)
                sub_tok = next(sub_tokens)
            except StopIteration:
                return EnhancedList([])
            if isinstance(sub_tok, Identifier):
                to_return.append(sub_tok)
        elif isinstance(next_tok, Identifier):
            to_return.append(next_tok)
        elif isinstance(next_tok , ObjectCurlyBracket):
            next_tok.handle_expression()
            for _, id in next_tok.get_dictionary().items():
                if isinstance(id, Identifier):
                    to_return.append(id)
        elif isinstance(next_tok, Bracket):
            for item in next_tok.get_items():
                if isinstance(item, Identifier):
                    to_return.append(item)
                elif isinstance(item, Bracket):
                    for sub_item in item.get_items():
                        if isinstance(sub_item, Identifier):
                            to_return.append(sub_item)
            
        while True:
            try:
                token = next(tokens)
                if token == ",":
                    token = next(tokens)
                    if isinstance(token, Identifier):
                        to_return.append(token)
                    elif isinstance(token, CurlyBracket):
                        sub_tokens = token.get_children()
                        next(sub_tokens)
                        sub_tok = next(sub_tokens)
                        if isinstance(sub_tok, Identifier):
                            to_return.append(sub_tok)
                    elif isinstance(token, ObjectCurlyBracket):
                        for _, id in token.get_dictionary().items():
                            if isinstance(id, Identifier):
                                to_return.append(id)
                    elif isinstance(token, Bracket):
                        children = token.children
                        if len(children) == 3:
                            if children[0].text == '[' and children[2].text == ']':
                                to_return.append(children[1])

            except StopIteration:
                break
        return EnhancedList(to_return)
    
    def get_vartypes(self):
        var_names = self.get_variables().get_names()
        result = OrderedDict()
        tokens = self.get_children()

        for var in var_names:
            result[var] = None  # default value
            token = tokens.move_to(var)
            try:
                while not token == ',':
                    token = next(tokens)
                    if token == ':':
                        result[var] = Type(next(tokens))
                        continue
            except:
                pass

        return result

    def get_assigned_value(self, node):
        """
        return what is assigned to the node:
var a = b   // self.get_assigned_value(a_identifier) => b_identifier
var {a} = b // self.get_assigned_value({a}) => b_identifier   // {a} being the curlyBracket node

        """
        tokens = self.get_children()
        token = tokens.move_to(node)
        try:
            while not token == ',':
                token = next(tokens)
                if token == '=':
                    tok = next(tokens)
                    if isinstance(tok, Await):
                        tok = tok.get_statement()
                    return tok
        except:
            pass

    def get_expressions(self):
        """
        return a dictionary with variable names as keys
        and expressions as values. 

        Removes unnecessary () in the expressions
        If some variable does not have an expression 
        the corresponding value will be "None".
        
        TODO: handle 
        """
        variables = self.get_variables()
        result = OrderedDict()        
        tokens = self.get_children()
        
        
        for var in variables:
            result[var.get_name()] = None  # default value
            if isinstance(var.parent, (ObjectCurlyBracket, CurlyBracket)):
                result[var.get_name()] = var.get_resolution()
                continue
            if isinstance(var.parent, Bracket):
                reso = var.get_resolution()
                if reso:
                    result[var.get_name()] = reso
                else:
                    # to improve readability
                    bracket = var.parent
                    var_dec = bracket.parent
                    if not hasattr(var_dec, 'get_assigned_value'):
                        continue
                    assigned_value = var_dec.get_assigned_value(bracket)
                    result[var.get_name()] = assigned_value

            token = tokens.move_to(var)
            try:
                while not token == ',':
                    token = next(tokens)
                    if token == '=':
                        tok = next(tokens)
                        if isinstance(tok, Await):
                            tok = tok.get_statement()
                        # in theory, typeof should be included in a node...
                        elif tok == 'typeof':
                            tok = next(tokens)
                        if isinstance(tok, Parenthesis) and len(tok.children)==3:
                            tok = tok.children[1]

                        if isinstance(tok, Assignment):
                            tok = tok.get_right_expression()
                        result[var.get_name()] = tok
                        continue
            except:
                pass

        if isinstance(result, Await):
            result = result.get_statement()


        return result
        

    def is_constant_declaration(self):
        """
        Return True if the variable is a constant,
        otherwise return False.
        """
        
        tokens = self.get_children()
        return True if any(True for token in tokens if token == "const") else False
    
    # to be deprecated
    def get_data_type(self):
        
        tokens = self.get_children()
        types = []
        typ = None
        try:
            tokens.move_to(":")
            typ = next(tokens)
            if isinstance(typ, Bracket):
                tokens = typ.get_children()
                 
                try:
                    while True:
                        token = next(tokens)
                        if token in (',','[',']'):
                            continue
                        types.append(token)
                except StopIteration:
                    pass
        
        except StopIteration:
            pass
        
        if typ and not types:
            types.append(Type(typ))
        
        return types


class Type(Node):
    """
    A wrapping node to be used when returning types 
    from VariableDeclarations and Parameters to provide 
    some general functionality, for example, handling
    arrays, resolutions, etc. However, it is not part of 
    the AST.
    """

    def __init__(self, token):
        Node.__init__(self)
        self.children = [token]
        self.resolved_as = None

    def __eq__(self, typ):
        """
        Overload to compare with string
        """
        if isinstance(typ, str):
            name = self.get_name()
            if name:
                names = [name]
            else:
                names = self.get_names()
            return typ in names
        # fallback on normal eq
        return object.__eq__(self, typ)

    def get_type_name(self, expression):
        """
        Utility function to manage all types of nodes
        """
        if hasattr(expression, "get_name"):
            # to manage complex types, such as method call found in constructors
            return expression.get_name()
        else:
            return expression.text

    def get_name(self):
        """
        Return the name of the expression of the type, using 'get_name()'.
        This will work when the expression is simple (i.e. not an intersection or union of types)
        """
        expression = self.children[0]
        return self.get_type_name(expression)

    def get_names(self):
        """
        Return the name of the types in the expression. 
        """
        def flatten_tuples(t):
            for x in t:
                if isinstance(x, tuple):
                    yield from flatten_tuples(x)
                else:
                    yield x
        def walk_tree(bin_op):
            """get the leafs recursively"""
            if not isinstance(bin_op, BinaryOperation):
                return bin_op

            left = bin_op.get_left_expression()
            right = walk_tree(bin_op.get_right_expression())
            result = tuple(flatten_tuples((left, right)))
            return result

        expression = self.children[0]

        # unwrap
        if isinstance(expression, (Parenthesis, UnaryOperation)):
            # afield: (A | B)
            # afield: typeof A
            inner_body = tuple(expression.get_inner_body())
            if inner_body:
                expression = inner_body[0]

        if isinstance(expression, BinaryOperation):
            # afield: A | B | C
            return [self.get_type_name(leaf) for leaf in walk_tree(expression)]
        else:
            return [self.get_type_name(expression)]

    # TODO: code below better?
#        typ = self.children[0]
#        
#        if isinstance(typ, ArrayAccess) :
#            tokens = typ.get_children()
#            try :
#                while True:
#                    token = next(tokens)
#                    if token.text  and isinstance(tokens.look_next(), Bracket):
#                        return token.text + " array"
#            except StopIteration :
#                pass
#        
#        elif isinstance(typ,Identifier):
#            return typ.get_name()
#        elif isinstance(typ, Token):           
#            return typ.text
#        
#        return None

    def get_identifiers(self):
        def flatten_tuples(t):
            for x in t:
                if isinstance(x, tuple):
                    yield from flatten_tuples(x)
                else:
                    yield x
        def walk_tree(bin_op):
            """get the leafs recursively"""
            if not isinstance(bin_op, BinaryOperation):
                return bin_op

            left = bin_op.get_left_expression()
            right = walk_tree(bin_op.get_right_expression())
            result = tuple(flatten_tuples((left, right)))
            return result

        expression = self.children[0]

        # unwrap
        if isinstance(expression, (Parenthesis, UnaryOperation)):
            # afield: (A | B)
            # afield: typeof A
            inner_body = tuple(expression.get_inner_body())
            if inner_body:
                expression = inner_body[0]

        if isinstance(expression, (ObjectCurlyBracket, CurlyBracket)):
            children = expression.get_children()
            children.move_to(':')
            try:
                id = next(children)
            except StopIteration:
                return []
            else:
                if isinstance(id, Identifier):
                    return [id]
                return []
        if isinstance(expression, BinaryOperation):
            # afield: A | B | C
            return [leaf for leaf in walk_tree(expression)]
        else:
            return [expression]

        return []

    def get_identifier(self):
        identifier = None
        first_child = self.children[0]
        if isinstance(first_child, Identifier):
            identifier = first_child
        return identifier

    def get_expression(self):
        """
        Return the AST node encapsulated by this type
        """
        return self.children[0]

    def get_resolution(self):
        first_child = self.children[0]
        if hasattr(first_child, 'get_resolution'):
            return first_child.get_resolution()

def parse_binary_operations_AZU(tokens, parent):
    """Based on Swift analyzer
    
    Parameters
    ----------
    tokens: a Lookahead object
    
    return: a reconstructed Lookahead object 
    
    """
    consumed = []
    new_children = []
    try:
        while True:
            token = next(tokens)
            consumed.append(token)
            if token.type in [Keyword, Punctuation] or isinstance(token, GenericsParameter):
                continue
            consumed_copy = consumed.copy()
            if (tokens.look_next() in [op for op in all_binary_operators if op != '*']
                or (tokens.look_next() == "*" and token != "function" and token != 'import')):

                operation = BinaryOperation()
                operation.parent = parent
                left_token = consumed.pop()
                if is_token_subtype(left_token.type, Generic):
                    identifier = Identifier(left_token)
                    operation.children.append(identifier)  # left expression
                else:
                    operation.children.append(left_token)
                operator = next(tokens)

                # handle badly-formed expressions ending with '+'
                try:
                    tokens.look_next()
                except:
                    consumed = consumed_copy + [operator]
                    raise StopIteration

                operation.children.append(operator)

                # handle right part, recursively
                tokens = parse_binary_operations_AZU(tokens, parent=operation)
                token = next(tokens)

                if is_token_subtype(token.type, Generic):
                    identifier = Identifier(token)
                    token = identifier
                operation.children.append(token)  # right expression

                new_children.extend(consumed + [operation])
                consumed.clear()
                for sub_node in operation.get_sub_nodes():
                    sub_node.parent = operation

                if tokens.look_next() == ';':
                    operation.children.append(next(tokens))

    except StopIteration:
        if new_children:
            new_children.extend(consumed)
            return Lookahead(new_children)
    return Lookahead(consumed)

def is_unary_operator(token):
    if token in ["+","-"] and token.is_unary_operator:
        return True
    
class UnaryOperation(Term):
    """
    TODO: "!" operator
    """
    match = Or(
        Seq(Or(is_identifier, ExpressionStatement),Or("--","++",)),
        Seq(Or("!", '~'), Or(Seq(is_identifier, NotFollowedBy(Or(Parenthesis, "."))), Parenthesis)),
        Seq(Or(Token('typeof', Keyword), Token('instanceof', Keyword)), is_identifier),
        Seq(Or("--", "++",), is_identifier),
        Seq(is_unary_operator, Or(is_identifier, is_number_literal))
    )

    def get_operator(self):
        for child in self.get_children():
            if child in ['--', '++', "!", '~', 'typeof', 'instanceof', '+', '-']:
                return child

    def get_expression(self):
        for child in self.get_children():
            if child in ['--', '++', "!", '~', 'typeof', 'instanceof', '+', '-']:
                continue
            return child

    def get_name(self):
        return self.get_expression().get_name()
    
    def on_end(self):
        # parse Identifiers
        new_children = []
        for child in self.get_children():
            if isinstance(child, Token) and is_identifier(child):
                identifier = Identifier(child)
                new_children.append(identifier)
                identifier.parent = self
            else:
                new_children.append(child)
        self.children = new_children



class BinaryOperation(Node):

    def __init__(self):
        super().__init__()

    def get_operator(self):
        try:
            return next(child for child in self.get_children()
                    if child.type == Operator)
        except StopIteration:
            return

    def get_right_expression(self):
        expression = self.children[-1]
        if expression == ';':
            expression = self.children[-2]
        return expression

    def get_left_expression(self):
        return self.children[0]

class Assignment(Node):

    def __init__(self):
        super().__init__()

    def get_variable_type(self, seen_asts=None):
        tokens = self.get_children()
        tokens.move_to(':')
        try:
            tok = Type(next(tokens))
        except StopIteration:
            return
        return tok


    def get_right_expression(self):
        """
        This should replace the original 
        version at some point, in such a way
        that only a single node will be returned
        (this might require improving the rest
         of the parser)
        """
        try:
            tokens = self.get_children()
            tokens.move_to(["=", "+=", "-=", '||=', '&&=', '??='])
            next_tok = next(tokens)
            if isinstance(next_tok, Parenthesis):
                children = list(next_tok.get_children())
                if len(children) == 3:
                    next_tok = children[1]
                if isinstance(next_tok, Assignment):
                    return next_tok.get_right_expression()
            if isinstance(next_tok, Await):
                return next_tok.get_statement()
            return next_tok
        except StopIteration:
            return None
    
    def get_left_expression(self):
        """
        this should replace the old 
        version at some point
        """

        def search_expression(tokens):
            token = next(tokens)
            while True:
                if tokens.look_next() in ("=", "+=", "-=", ":", '||=', '&&=', '??='):
                    return token
                token = next(tokens)
            
        try:
            return search_expression(self.get_children())
        except StopIteration:
            return None

    def get_operator(self):
        children = self.get_children()
        next(children)
        return next(children)


class Await(Statement):
     
    begin = Seq(Token('await', Keyword), NotFollowedBy(Parenthesis))
    end = ExpressionStatement

    def get_statement(self):
        tokens = self.get_children()
        tokens.move_to('await')
        return next(tokens)

class FinallyBlock(Term):
    
    match = Seq('finally', CurlyBracket)

    
class TryBlock(Statement):
    
    begin = Token('try', Keyword)
    end = CurlyBracket
    
class CatchBlock(Statement):
    
    begin = Seq(Not('.'), Token('catch', Keyword))
    end = CurlyBracket
    
class TSSimpleStatement:
    
    end = Or(';', LineFeed)
    
class Throw(Statement, TSSimpleStatement):
    
    begin = Seq(Token('throw', Keyword), NotFollowedBy(':'))
    end = Or(';', LineFeed)

    def get_thrown(self):
        stream = self.get_children()
        try:
            stream = self.get_children()
            stream.move_to("throw")
            tok = next(stream)
            if isinstance(tok, Parenthesis):
                sub_tok = tok.get_children()
                next(sub_tok)
                tok = next(sub_tok)
            return tok
        except StopIteration:
            pass

    def handle_expression(self):
        # parse first token after < as Identifier
        new_children = []
        for tok in self.get_children():
            if isinstance(tok, Token) and tok.get_type() == Generic:
                identifier = Identifier(tok)
                identifier.parent = self
                new_children.append(identifier)
            else:
                new_children.append(tok)

        self.children = new_children
    
class Return(Statement, TSSimpleStatement):
    
    begin = Seq(Token('return', Keyword), NotFollowedBy(':'))
    end = Or(';', LineFeed)

    def get_expression(self):
        try:
            return next(self.get_sub_nodes())
        except StopIteration:
            pass

        try:
            stream = self.get_children()
            stream.move_to("return")
            return next(stream)
        except StopIteration:
            pass

    def handle_expression(self):
        new_children = []
        children = self.get_children()
        while True:
            try:
                tok = next(children)
            except StopIteration:
                break
            new_children.append(tok)

            if tok == 'return':
                try:
                    tok = next(children)
                except StopIteration:
                    break
                if is_identifier(tok) and not isinstance(tok, Identifier):
                    tok = Identifier(tok)
                new_children.append(tok)
        self.children = new_children
        for child in children:
            child.parent = self


class Yield(Statement, TSSimpleStatement):

    begin = Token('yield', Keyword)
    end = Or(';', LineFeed)

    def get_expression(self):
        try:
            return next(self.get_sub_nodes())
        except StopIteration:
            pass


class Break(Statement, TSSimpleStatement):
    
    begin = Token('break', Keyword)
    end = Or(';' , LineFeed)

    
class Continue(Statement, TSSimpleStatement):
    
    begin = Token('continue', Keyword)
    end = Or(';', LineFeed)

    
class SwitchCase(Term):
    
    match = Seq(Token('switch', Keyword), Parenthesis, CurlyBracket)

    def get_cases(self):
        cases = []
        for token in self.get_children():
            if isinstance(token, CurlyBracket):
                for tok in token.get_children():
                    if isinstance(tok, Case):
                        cases.append(tok)
                break
        return cases

    def get_expression(self):
        stream = self.get_children()
        for tok in self.get_children():
            if isinstance(tok, Parenthesis):
                return tok.children[1]
    
class Case (Statement):

    def get_statements(self):
        statements = []
        tokens = self.get_children()
        tokens.move_to(":")
        while True:
            try:
                tok = next(tokens)
                statements.append(tok)
            except StopIteration:
                break
        return statements

    def get_case_value(self):
        stream = self.get_children()
        next(stream) # case
        tok = next(stream)
        if isinstance(tok, Token) and is_string_literal(tok):
            return tok.text[1:-1]
        else:
            return tok

    def get_case(self):
        stream = self.get_children()
        next(stream)  # case
        return next(stream)

def is_if(token, stream):
    
    def get_first_sub_token(node):
        
        if isinstance(node, IfThenElse):
            children = node.get_children()
            return next(children)
            
    first = get_first_sub_token(token)

    if first != 'if':
        return False

    index_of_stream = stream.tokens.index
    try:
        node = next(stream)
    except StopIteration:
        return True  # single node

    try:
        first = get_first_sub_token(node)
        while first in [ 'else']:  # "else if" or "else"
            index_of_stream = stream.tokens.index
            node = next(stream)
            first = get_first_sub_token(node)
        
        stream.tokens.index = index_of_stream # do not consume last unmatching one
    except StopIteration:
        pass
    
    return True


class If (Term):
    
    match = is_if
    
    def get_cases(self):
        """
        Access to each sub case.
         
        @rtype: list of IfThenElse
        """
        return list(self.get_sub_nodes())
     
      
class IfThenElse:
    
    def __init__(self):
        self.condition = None
        
    def is_else(self):
        
        children = self.get_children()
        try:
            return next(children) == 'else' and next(children) != 'if'
        except StopIteration:
            return False
    
    def is_else_if(self):
        
        children = self.get_children()
        if next(children) == 'else' and next(children) == 'if':
            return True
        else :
            return False
            
    def get_conditions(self):
        """
        TODO: general case: nested conditions, ...
        or maybe deprecate it
        """
#
        condition = self.get_condition()
        if not condition:
            return []

        try:
            condition = next(condition.get_sub_nodes())
        except StopIteration:
            pass

        def search_conditions(condition):
            if isinstance(condition, BinaryOperation):
                operator = condition.get_operator()
                if operator in ('||', '&&'):
                    left = search_conditions(condition.get_left_expression())
                    right = search_conditions(condition.get_right_expression())
                    result = left + right
                    if result:
                        return result

            return [condition]


        return search_conditions(condition)

    def get_condition(self):
        try:
            parenthesis = next(self.get_sub_nodes(Parenthesis))
            return next(parenthesis.get_sub_nodes(Condition))
        except StopIteration:
            pass
        
        
    def is_if_then_else(self):
        return True
  
class TSBlockStatement(BlockStatement):  
   
    def get_statements(self):

        try:
            block = next(self.get_sub_nodes(CurlyBracket))
        except StopIteration:
            # for single statements curly-brackets are optional
            return list(self.get_sub_nodes())

        return list(block.get_sub_nodes())


class IfThenElseBlock(TSBlockStatement, IfThenElse):
    """
    Classical block
    """
    def __init__(self):
        TSBlockStatement.__init__(self)
        IfThenElse.__init__(self)
    
    begin = Or(Token('if', Keyword),
               Seq(Token('else', Keyword), Token('if', Keyword)),
               Token('else', Keyword))
                   
    end = Or(CurlyBracket, ';', Return)


class IfTernary(Statement):

    def __init__(self):
        super().__init__()

    def get_first_value(self):
        tokens = self.get_children()
        tokens.move_to('?')
        return next(tokens)

    def get_second_value(self):
        tokens = self.get_children()
        tokens.move_to(':')
        try:
            return next(tokens)
        except:
            log.warning('Problem of parsing for IfTernary : ' + str(self))

    def get_condition(self):
        tokens = self.get_children()
        return next(tokens)


class Condition(Statement):
    pass


class ForBlock(TSBlockStatement):
    
    begin = Seq(Token('for', Keyword), Parenthesis)
    end = CurlyBracket
    
    def __init__(self):
        TSBlockStatement.__init__(self)
        
    def is_for(self):
        return True
    
    def get_conditions(self):
        """
        TODO: general case: nested conditions, ...
        or maybe deprecate it
        """
#
        condition = self.get_condition()
        if not condition:
            return []

        try:
            condition = next(condition.get_sub_nodes())
        except StopIteration:
            pass

        def search_conditions(condition):
            if isinstance(condition, BinaryOperation):
                operator = condition.get_operator()
                if operator in ('||', '&&'):
                    left = search_conditions(condition.get_left_expression())
                    right = search_conditions(condition.get_right_expression())
                    result = left + right
                    if result:
                        return result

            return [condition]

        return search_conditions(condition)

    def get_condition(self):
        try:
            parenthesis = next(self.get_sub_nodes(Parenthesis))
            return next(parenthesis.get_sub_nodes(Condition))
        except StopIteration:
            pass

    
class WhileBlock(TSBlockStatement):
    
    begin = Seq(Token('while', Keyword), Parenthesis)
    end = CurlyBracket
    
    def __init__(self):
        TSBlockStatement.__init__(self)
        
    def is_while(self):
        return True
    
    def get_conditions(self):
        """
        TODO: general case: nested conditions, ...
        or maybe deprecate it
        """
#
        condition = self.get_condition()
        if not condition:
            return []

        try:
            condition = next(condition.get_sub_nodes())
        except StopIteration:
            pass

        def search_conditions(condition):
            if isinstance(condition, BinaryOperation):
                operator = condition.get_operator()
                if operator in ('||', '&&'):
                    left = search_conditions(condition.get_left_expression())
                    right = search_conditions(condition.get_right_expression())
                    result = left + right
                    if result:
                        return result

            return [condition]

        return search_conditions(condition)

    def get_condition(self):
        try:
            parenthesis = next(self.get_sub_nodes(Parenthesis))
            return next(parenthesis.get_sub_nodes(Condition))
        except StopIteration:
            pass

        
class DoWhileBlock(TSBlockStatement):
    
    begin = Seq(Token('do', Keyword), NotFollowedBy(Parenthesis))
    end = Seq(CurlyBracket, Token('while', Keyword), Parenthesis, Optional(';'))
    
    def __init__(self):
        TSBlockStatement.__init__(self)
    
    def is_do_while(self):
        return True
    
    def get_statements(self):
        curly_bracket = get_descendants(self, CurlyBracket)[0]
        return [node for node in curly_bracket.get_sub_nodes()]

    def get_conditions(self):
        """
        TODO: general case: nested conditions, ...
        or maybe deprecate it
        """
#
        condition = self.get_condition()
        if not condition:
            return []

        try:
            condition = next(condition.get_sub_nodes())
        except StopIteration:
            pass

        def search_conditions(condition):
            if isinstance(condition, BinaryOperation):
                operator = condition.get_operator()
                if operator in ('||', '&&'):
                    left = search_conditions(condition.get_left_expression())
                    right = search_conditions(condition.get_right_expression())
                    result = left + right
                    if result:
                        return result

            return [condition]

        return search_conditions(condition)

    def get_condition(self):
        try:
            parenthesis = next(self.get_sub_nodes(Parenthesis))
            return next(parenthesis.get_sub_nodes(Condition))
        except StopIteration:
            pass


def get_bookmark_from_ast(ast):
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
        return Bookmark(file.get_file(),
                 ast.get_begin_line(),
                 ast.get_begin_column(),
                 ast.get_end_line(),
                 ast.get_end_column() + 1)
    except:
        log.debug("problem getting bookmark from ast " + str(ast))


def refine_arrow_expressions(ast_nodes, is_in_class=False):
    """
allow to identify the type of ArrowExpression nodes
set one of the property (is_arrow_method, is_arrow_function) to True

    """

    # nothing to do on a Token
    if not isinstance(ast_nodes, list):
        ast_nodes = [ast_nodes]

    for i_node, node in enumerate(ast_nodes):
        if isinstance(node, ArrowExpression):
            # a method cannot be anonymous
            if node.get_name().startswith("<Anonym"):
                node.is_arrow_function = True
            elif is_in_class:
                node.is_arrow_method = True
            else:
                node.is_arrow_function = True

        next_is_in_class = is_in_class
        if isinstance(node, (Namespace, Function
                             , ArrowExpression, Method
                             , Interface, Enum, Parenthesis, Bracket)):
            next_is_in_class = False
        elif isinstance(node, Class):
            next_is_in_class = True
        if hasattr(node, 'children'):
            refine_arrow_expressions(node.children, is_in_class=next_is_in_class)
