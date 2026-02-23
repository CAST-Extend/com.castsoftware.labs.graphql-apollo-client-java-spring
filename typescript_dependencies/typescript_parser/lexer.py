from .light_parser.splitter import Splitter # @UnresolvedImport
from .light_parser import Token # @UnresolvedImport
from pygments.token import Generic, Comment, String, Keyword, Name, Number, Operator, \
    Punctuation, Whitespace, Token as PygmentToken, \
    is_token_subtype  # @UnusedImport
import re

Regexp = PygmentToken.Regexp
WeakKeyword = Keyword.Weak  # @UndefinedVariable
LineFeed = PygmentToken.LineFeed 
AesteticLineFeed = PygmentToken.AesteticLineFeed
StartLine = PygmentToken.StartLine
StringTemplate = String.Backtick

CommentEndOfLine = Comment.EndOfLine # @UndefinedVariable


class TypeScriptLexer:
    """
    A very basic lexer 
    """
    
    def __init__(self, stripnl=False):
        pass
        
        self.cannot_preceed_or_follow_linefeed = [".", "==", "===", "!=", '<', '<=', '>=', '!=', '!==',
                      '+=', '-=', '*=', '/=', '%=', '&=', '^=', '|=', '||=', '&&=', '??=', '||', '??', '<<=', '>>=', '>>', '>>>', '<<', '<<<', '&&', "+", "-",
                       "{", "=>", "=", "[", ",", ";", ":", "?", '*', '/', '%', '|', '&', '^', '||']

        # the st
        # note that ">" can preceed a linefeed only when its closes a GenericsParameter
        # this case is handled separately but may fail in some very complex cases
        self.cannot_follow_linefeed = ["}", "]", ">", ")"]
        self.cannot_preceed_linefeed = ['~', '(']
        self.cannot_preceed_linefeed += self.cannot_preceed_or_follow_linefeed
        self.cannot_follow_linefeed += self.cannot_preceed_or_follow_linefeed

        self.cannot_preceed_and_follow_linefeed = [["}", "else"]]
        
        self.previous_token = Token(None)
        self.previous_token.begin_line = 0
        self.previous_token.end_line = 0
        self.previous_token.begin_column = 0
        self.previous_token.end_column = 0

        self.previous2_token = Token(None)
        self.previous2_token.begin_line = 0
        self.previous2_token.end_line = 0
        self.previous2_token.begin_column = 0
        self.previous2_token.end_column = 0

    def add_filter(self, _):
        pass

    def is_linefeed(self,token_next,token_prev_text,token_prev_type):
        
        if token_next in self.cannot_follow_linefeed :
            return False
        
        if [token_prev_text, token_next] in self.cannot_preceed_and_follow_linefeed :
            return False

        if (token_prev_type in [Generic, Keyword, WeakKeyword] or token_prev_text == ")") \
             and token_next == "(":
            return False
        
        else:
            return True
    
    def my_yield(self, result):
        if result in ["(", "<"] and self.previous_token.text and (self.previous_token == ":" or (self.previous_token == '(' and hasattr(self.previous_token, 'is_following_colon'))):
            result.is_following_colon = True

        # used to save the previous non_whitespace token
        if not result.is_whitespace() and not result.type == Comment:
            self.previous2_token = self.previous_token
            self.previous_token = result

        yield result
        
    def get_tokens(self, text, unfiltered=False):
        """
        To keep compliant with pygment 
        
        But still returns positionned tokens
        """
        # text can be a file...
        if isinstance(text, str):
            text = text.splitlines(True)
            
        # see : https://github.com/Microsoft/TypeScript/blob/master/doc/spec.md
        s = Splitter(['<>','</>','(', ')', '{', '}', '[', ']',
                      ';', ',', ':', '.', '...',
                      '++', '--', '+', '-', '~', '!',
                      '/', '%',
                      '&', '|', '^',
                      '+=', '-=', '*=', '/=', '%=',  # assignment current operators
                      '<<=', '>>=', '&=', '|=', '^=',  # assignment Bitwise operators
                      '=', '<', '>', '==', '===', '<=', '>=', '!=', '!==','||=', '&&=', '??=',

                      '||', '&&', '=>', '??',
                      '/*', '*/', '**/', '//', '**', '*',
                      '"', '\\', "'", "`",
                      '</', '/>', '@'
                      ])
        split = s.split
        
        checking_linefeed = False
        linefeed_list = []
        # param
        multi_line_string_marker = '`'
        
        
        # state 
        mono_line_comment = False
        
        current_comment = None 
        multi_line_comment = False
        multi_line_comment_begin_line = None
        multi_line_comment_begin_column = None
        
        multi_line_string = False
        multi_line_string_begin_line = None
        multi_line_string_begin_column = None
        
        may_be_real_number = False

        is_string = False
        current_string = None
        current_separator = None
        previous_is_backslash = False
        previous_is_dot = False

        current_regexp = None
        seen_end_regexp = False
        current_line_number = 0
        real_part = None
        
        generics_is_open = False
        closing_generics = False #is set to True if the last ">" is following a "<"
        
        for line in text:
            current_line_number += 1
            begin_column = 0
            end_column = 0
            
            # true when we have seen something non blank and non comment on the line
            seen_something = False
            mono_line_comment_begin_column = None
            
            string_begin_column = None
            
            is_regexp = False
            regexp_begin_column = None
            
            # used for identifying function name
            current_is_function_def = False
            
            token_len = 0 
            splitted_line = split(line)
            case_seen = False
            for i, token in enumerate(splitted_line, 1):

                if token == 'case':
                    case_seen = True
                token_len = token_len + len(token)
                begin_column = end_column + 1
                end_column = begin_column + len(token) - 1

                # we did not have a real_number, we had an integer
                if may_be_real_number :
                    if real_part.text[-1] != "." and token == ".":
                        real_part.text += "."
                        continue
                    elif real_part.text[-1] == "." :
                        real_part.text += token
                        real_part.end_line = current_line_number
                        real_part.end_column = end_column
                        yield from self.my_yield(real_part)
                        may_be_real_number = False
                        real_part = None
                        continue
                    # we just had an integer
                    else :
                        yield from self.my_yield(real_part)
                        may_be_real_number = False
                        real_part = None

#               #https://developer.mozilla.org/en-US/docs/Web/JavaScript/Reference/Global_Objects/RegExp
                if seen_end_regexp:
                    if token in ('g', 'i', 'm', 'u', 'y'):
                        current_regexp += token
                        result = Token(current_regexp, Regexp)
                        result.begin_line = current_line_number
                        result.end_line = current_line_number
                        result.begin_column = regexp_begin_column
                        result.end_column = end_column
                        
                        yield from self.my_yield(result)

                        regexp_begin_column = None
                        is_regexp = False
                        seen_end_regexp = False
                        continue
                    
                    yield from self.my_yield(result)
                    
                    regexp_begin_column = None
                    is_regexp = False
                    seen_end_regexp = False
                    
                if mono_line_comment and token[-1] != '\n':
                    current_comment += token
                elif multi_line_comment:
                    current_comment += token
                    if token in ['*/', '**/']:

                        result = Token(current_comment, Comment)
                        result.begin_line = multi_line_comment_begin_line
                        result.end_line = current_line_number
                        result.begin_column = multi_line_comment_begin_column
                        result.end_column = end_column
                        
                        if checking_linefeed:
                            linefeed_list.append(result)
                        else:
                            yield from self.my_yield(result)
                        multi_line_comment = False
                elif multi_line_string:
                    current_string += token
                    if current_string.endswith("${") and not current_string.endswith("\${"):
                        stack_to_close.append("{")
                    elif current_string.endswith("{") and not previous_is_backslash:
                        if stack_to_close and stack_to_close[-1] == "{":
                            stack_to_close.append("{")

                    if current_string.endswith("}") and stack_to_close and stack_to_close[-1] == "{":
                        stack_to_close = stack_to_close[:-1]
                    # end of multiline string
                    if token == multi_line_string_marker and not previous_is_backslash:
                        if not stack_to_close:
                            result = Token(current_string, StringTemplate)
                            result.begin_line = multi_line_string_begin_line
                            result.end_line = current_line_number
                            result.begin_column = multi_line_string_begin_column
                            result.end_column = end_column

                            yield from self.my_yield(result)
                            multi_line_string = False
                        else:

                            if stack_to_close[-1] == "`":
                                stack_to_close = stack_to_close[:-1]
                            else:
                                stack_to_close.append("`")
                        
                elif is_string:
                    current_string += token
                    if token == current_separator and not previous_is_backslash:
                        locations = [index for index, element in enumerate(line) if element == current_separator]
                        
                        # This if condition is to check for apositfy s.
                        # If condition ensures that the boundaries are not checked
                        if len(locations) >2 and token_len < len(line):
                            if line[token_len] == "s" :
                                continue
                            else :
                                result = Token(current_string, String)
                                result.begin_line = current_line_number
                                result.end_line = current_line_number
                                result.begin_column = string_begin_column
                                result.end_column = end_column
                                yield from self.my_yield(result)
                                string_begin_column = None
                                is_string = False
                            
                            
                        else :    
                            result = Token(current_string, String)
                            result.begin_line = current_line_number
                            result.end_line = current_line_number
                            result.begin_column = string_begin_column
                            result.end_column = end_column

                            yield from self.my_yield(result)

                            string_begin_column = None
                            is_string = False

                elif is_regexp:
                    nb_tokens = len(split(line))
                    if not seen_end_regexp:
                        current_regexp += token

                    if not is_in_block and ((token == '/' and not previous_is_backslash) or
                            token in ('//', '</', '*/')):
                        result = Token(current_regexp, Regexp)
                        result.begin_line = current_line_number
                        result.end_line = current_line_number
                        result.begin_column = regexp_begin_column
                        result.end_column = end_column
                        
                        if i == nb_tokens:
                            yield from self.my_yield(result)
                        seen_end_regexp = True
                        continue

                    if (token=='[') and not previous_is_backslash :
                        is_in_block = True

                    if (token==']') and is_in_block and not previous_is_backslash :
                        is_in_block = False

                elif token == '//':
                    mono_line_comment = True
                    mono_line_comment_begin_column = begin_column
                    current_comment = '//'
                elif token == '/*':
                    multi_line_comment = True
                    multi_line_comment_begin_line = current_line_number
                    multi_line_comment_begin_column = begin_column
                    current_comment = '/*'
                elif token == multi_line_string_marker:
                    multi_line_string = True
                    stack_to_close = []
                    multi_line_string_begin_line = current_line_number
                    multi_line_string_begin_column = begin_column
                    current_string = multi_line_string_marker
                elif token == '"' or token == "'":
                    is_string = True
                    current_string = token
                    current_separator = token
                    seen_something = True
                    string_begin_column = begin_column

                elif token in ['/', '/>']:
                    # @todo: discern between regular expression and a
                    # mathematical division
                    rest_line = split(line)[i - 1:]
                    rest_line = "".join(rest_line)
                    
                    match = re.search('/.+?/[gimuy]?', rest_line)
                    
                    # check that we don't have self closing tag followed by a closing tag
                    # this is required for react .tsx files (which can contain html tags)
                    match2 = re.search('/>.*</', rest_line)
                    match3 = re.search('/>.*/>', rest_line)
                    if not match or match2 or match3 or (
                            self.previous_token.text is not None and
                            self.previous_token not in ["=", "(", ":", "!", "[", ",", "return", '||=', '&&=', '??=', "||", '&&', "??"]):
                        result = Token(token, Operator)
                        result.begin_line = current_line_number
                        result.end_line = current_line_number
                        result.begin_column = begin_column
                        result.end_column = end_column
                        yield from self.my_yield(result)
                        continue
                    
                    is_regexp = True
                    is_in_block = False
                    nb_tokens = len(split(line))
                    current_regexp = token
                    regexp_begin_column = begin_column
                    
                else:
                    _type = Generic
                    
                    # there is no reserved keyword for methods
                    # we therefore cannot have a keyword after a "."
                    if token and not previous_is_dot:

                        # 'delete' : !!! not restricted as method name
                        if token in  ['async', 'abstract', 'break', 'case', 'catch', 'class',
                                      'const',  'continue', 'debugger', 'declare',
                                      'do', 'else', 'enum', 'eval',
                                      'false', 'finally',
                                      'for', 'if', 'interface',
                                      'in', 'instanceof', 'module', 'namespace', 'new', 'null',
                                      'return', 'super', 'switch', 'this', 'await',
                                      'throw', 'true', 'try', 'typeof', 
                                      'var', 'void',  'while', 'with', 'let',
                                      # method modificators
                                      'public', 'private', 'static', 'protected', 'readonly'
                                      ]:
                            _type = Keyword

                        # few strict-mode reserved words
                        # https://github.com/Microsoft/TypeScript/issues/2536
                        elif token in ['as', 'implements',
                                       'interface', 'let',
                                       'package', 'yield',
                                       'symbol',
                                       'implements', # seen in compodoc
                                       'extends',    # "
                                       'function',   # "
                                       'default',  # seen in angular-gantt project
                                       #'type',  # @todo: analyse impact in non-regression tests
                                       'from', 'of', 'export', 'import',
                                       ]:

                            _type = WeakKeyword
                            current_is_function_def = (token == 'function')

                        # @todo: revise need of this,
                        # thus, we can have : $f1() function calls
                        # if      var $f1 = function(){return 4;};
                        #if token.startswith(('$', '_')):
                            # if token and any(s in token for s in ['$', '_']):  # maybe better
                        #    _type = Name.Variable
                    
                        elif token[0].isdigit() :
                            _type = Number
                            
                        elif token.isspace():
                            if token[-1] == "\n":

                                # _type = LineFeedNonSyntaxic
                                if not checking_linefeed:
                                    
                                    if (self.previous_token.text not in self.cannot_preceed_linefeed + [None] and
                                        self.previous_token.type != Comment):
                                        checking_linefeed = True
                                        linefeed_list = []
                                
                            else :
                                _type = Whitespace
                    
                        # https://www.tutorialspoint.com/typescript/typescript_operators.htm
                        # - we don't include bitwise operators here &~<<>>>=<<=& ...
                        elif token in "++=--=*/%><>=<=!==*=/=?||=&&=!!===%=**??=^":  # fast check
                            # '<<=', '>>=', '&=', '|=', '^=',
                            _type = Operator
                            if token == "<":
                                generics_is_open = True
                            elif token == ">":
                                if generics_is_open :
                                    generics_is_open = False
                                    closing_generics = True
                                else:
                                    closing_generics = False
                        elif token in ('.', '...', ':', ';', '=>', ')', '(', '{', '}', ',', '[', ']', '@'):

                            _type = Punctuation
                            current_is_function_def = False
                            if token == ";":
                                generics_is_open = False
                                closing_generics = False

                        elif current_is_function_def:
                            _type = Name

                               
                    if not seen_something:
                        seen_something = not token.isspace()
                    
                    result = Token(token, _type)
                    result.begin_line = current_line_number
                    result.end_line = current_line_number
                    result.begin_column = begin_column
                    result.end_column = end_column
                    if _type == Generic:
                        if previous_is_dot :
                            result.previous_is_dot = True
                        else:
                            result.previous_is_dot = False
                    elif result == '.':
                        if splitted_line[i].isdigit():
                            # we have a real number
                            may_be_real_number = True
                            real_part = result
                            continue

                    if result in ["-", "+"]:
                        p_t = self.previous_token
                        if (p_t and
                            (p_t.text in ["]", ")"] or
                             p_t.type in [Generic, String, Number])
                            ):
                            result.is_unary_operator = False
                        else:
                            result.is_unary_operator = True
                    # we are getting out of the linefeed zone
                    if checking_linefeed and not result.is_whitespace():
                        
                        # we did not have a linefeed
                        if not self.is_linefeed(token_next=token,
                                                token_prev_text=self.previous_token.text,
                                                token_prev_type=self.previous_token.type):
                            pass
                        
                        elif self.previous_token.text == ">" and not closing_generics :
                            pass
                        
                        # we did have a linefeed
                        else:
                            linefeed_list[0].type = LineFeed
                            linefeed_list[0]._is_whitespace = False
                            generics_is_open = False
                            closing_generics = False
                            
                        for res in linefeed_list :
                            yield from self.my_yield(res)

                        checking_linefeed = False
                        yield from self.my_yield(result)

                    # checking if we have a real number
                    elif _type == Number and not may_be_real_number :
                        may_be_real_number = True
                        real_part = result

                    elif checking_linefeed:
                        linefeed_list.append(result)
                    else:
                        if not (token[-1] == '\n' and mono_line_comment and self.previous_token.text == None):
                            if self.previous_token.text and result == "{":
                                    if (  self.previous_token in ["=", "return", "(", ",", "[", "{", "&&", '||', '==', '!==', '!', '?', 'var', 'const', 'let', 'default'] or
                                          (self.previous_token == ":" and self.previous2_token != ")" and case_seen == False)) :
                                        result.is_object_curlybracket = True

                            yield from self.my_yield(result)

                current_is_backslash = token == '\\'  # note: print(token) -> '\'
                if previous_is_backslash and current_is_backslash:
                    # for \\ case (escaping of escape)
                    previous_is_backslash = False
                else:
                    previous_is_backslash = current_is_backslash



                if not (mono_line_comment or multi_line_comment):
                    previous_is_dot = token == "."

            if mono_line_comment:
                result = Token(current_comment, Comment if not seen_something else CommentEndOfLine)
                result.begin_line = current_line_number
                result.end_line = current_line_number
                result.begin_column = mono_line_comment_begin_column
                result.end_column = end_column
                if checking_linefeed:
                    linefeed_list.append(result)
                else:
                    yield from self.my_yield(result)
                mono_line_comment = False

        if real_part:
            yield from self.my_yield(real_part)

        # adding a linefeed at the end if needed
        if self.previous_token.text not in self.cannot_preceed_linefeed:
            result = Token('\n', type=LineFeed)
            result._is_whitespace = False
            result.begin_line = self.previous_token.end_line
            result.end_line = self.previous_token.end_line
            result.begin_column = self.previous_token.end_column
            result.end_column = self.previous_token.end_column
            yield from self.my_yield(result)
