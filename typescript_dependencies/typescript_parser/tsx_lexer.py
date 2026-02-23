from .lexer import TypeScriptLexer, Number, Token
from .light_parser import Parser, BlockStatement, Term, Node


class Parenthesis(BlockStatement):

    begin = '('
    end = ')'

class CurlyBracket(BlockStatement):
    begin = '{'
    end = '}'

class Bracket(BlockStatement):
    begin = '['
    end = ']'


def is_generics(token, stream):

    if not token == "<":
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
    There is no simple way to make the difference between a GenericsParameter and an html opening tag since they all start with "<" and end with ">". So we parse all as GenericsParameter.
    """
    match = is_generics

    def get_tag_name(self):
        if len(list(self.get_children()))==1:
            return "<BlankTag>"
        stream = self.get_children()
        stream.move_to("<")
        tok = next(stream)
        return tok.text


def is_closing_html_tag(token, stream):

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
    """closing htmlTags are easy to parse."""
    match = is_closing_html_tag

    def get_tag_name(self):
        stream = self.get_children()
        stream.move_to("</")
        tok = next(stream)

        return tok.text


class TypeScriptXLexer:
    """ we use  a specific Lexer for tsx files.
This lexer is built on the standard lexer TypeScriptLexer and its purpose is to add the property is_opening_tag to the "<" tokens which are opening an OpeningHtmlTag.
This lexer runs as follow :
   - we run a simple parsing including all parenthesis and Brackets, GenericsParameter (which can either be GenericsParameters or OperningHtmlTag) and ClosingHtmlTag
   - we analyse the tokens backward (within each node using self.get_tags_tokens_within_node()), we build a closingHtmlTag stack and when we meet a GenercisParameter, if it is an OpeningTag matching the ClosingHtmlTag on top of the stack :
       - we record the position of that tag in self.position_of_opening_tags
       - remove the ClosingHtmlTag from the stack
   - we then tokenize the code using TypeScriptLexer
   - for each "<" token whose position match a self.position_of_opening_tags we set the property is_opening_tag to True
    """

    def __init__(self, stripnl=False):
        self.light_pattern = (TypeScriptLexer,
                             [Parenthesis, Bracket, CurlyBracket],
                             [GenericsParameter],
                             [ClosingHtmlTag])
        self.position_of_opening_tags = []

    def add_filter(self, _):
        pass

    def get_tags_tokens_within_node(self, node):
        if isinstance(node, list):
            node_children = node
        else:
            node_children = node.children
        closing_stack = []
        for child in node_children[::-1]:
            if isinstance(child, ClosingHtmlTag):
                closing_stack.append(child)
            elif isinstance(child, GenericsParameter) and closing_stack:
                if child.get_tag_name() == closing_stack[-1].get_tag_name():
                    # we get the first non comment token
                    stream = child.get_children()
                    tok = next(stream)
                    self.position_of_opening_tags.append([tok.get_begin_line(), tok.get_begin_column()])
                    del closing_stack[-1]
            elif isinstance(child, Node):
                self.get_tags_tokens_within_node(child)


    def get_tokens(self, text, unfiltered=False):
        parser = Parser(*self.light_pattern)
        self._ast = list(parser.parse(text))
        self.get_tags_tokens_within_node(self._ast)

        self.position_of_opening_tags= sorted(self.position_of_opening_tags)
        lexer = TypeScriptLexer()
        tokens = list(lexer.get_tokens(text))
        for tok in tokens:
            if tok == "<" and self.position_of_opening_tags:
                if (tok.get_begin_line() == self.position_of_opening_tags[0][0] and
                    tok.get_begin_column() == self.position_of_opening_tags[0][1]):
                    del self.position_of_opening_tags[0]
                    tok.is_opening_tag = True
            yield tok
