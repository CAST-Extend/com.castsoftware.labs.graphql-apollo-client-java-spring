import traceback, datetime
from cast.analysers import log

import typescript_dependencies.symbols as symbols
from typescript_dependencies.common_tools import clean_url, DefaultOrderedDict
from typescript_dependencies.filtering import get_closest_path
from typescript_dependencies.typescript_parser.light_parser import Token, Node
from pygments.token import is_token_subtype, Literal, Generic, Punctuation
from typescript_dependencies.typescript_parser.lexer import StringTemplate as ST
from typescript_dependencies.typescript_parser.parser import Identifier, Assignment, VariableDeclaration, MethodCall, \
    FunctionCall, Parenthesis, MemberAccess, StringTemplate, Export, Bracket, CurlyBracket, \
    BinaryOperation, Parameter, IfThenElseBlock, ArrayAccess, Return, IfTernary, \
    is_method_call, Instantiation, Argument, Await, Case, ObjectCurlyBracket, Function, If, SwitchCase, Method, Enum, \
    is_method, is_function, ArrowExpression, ConstructorField, Class
from typescript_dependencies.symbols import ExportedVariable, NodeExport, Class as SymbolClass, Method as SymbolMethod, RawBookmark, Symbol, SymbolNotSavedInKb
from typescript_dependencies.resolution_links_to_js import ExternalIdentifier

import itertools
from collections import OrderedDict
from copy import copy
from typescript_dependencies.resolution import get_module_path_from_node, get_module_from_node, get_descendants

quote_marks = ("'", '"')


class EvaluationTool:

    def __init__(self):
        pass

    @staticmethod
    def evaluate(node, with_trace=True, url_expected=False, charForUnknown=None, ast_node_expected=False, symbol_expected=False, max_counter=None):

        try:
            return evaluate(node, evaluation_params=EvaluationParams(with_trace=with_trace, charForUnknown=charForUnknown, url_expected=url_expected, ast_node_expected=ast_node_expected, symbol_expected=symbol_expected, max_counter=max_counter))

        except:
            return []


def get_direct_descendants(node, kind):
    """
    Get direct descendants of a node of a certain kind
    """
    for sub_node in node.get_sub_nodes():
        if type(sub_node) == kind:
            yield sub_node

def get_dict_from_export(export_node, progr):
    stream = export_node.get_children()
    next(stream) # export toke
    tok = next(stream)
    # we only consider const
    if not tok == "const":
        return
    tok = next(stream)
    if not isinstance(tok,Assignment):
        return
    assigned = tok.get_right_expression()
    if not isinstance(assigned, ObjectCurlyBracket):
        return
    check_map_and_add_to_progr(assigned, progr)

def check_map_and_add_to_progr(curly_bracket: ObjectCurlyBracket, progr):
    exported_map = curly_bracket.get_dictionary()
    # we check if environment conditions are specified
    # the order matters (the first match will be used)
    env_types = ["production", "prod", "stage", "test", "mock"]
    if len(exported_map) < 10 and any([env_type in exported_map.keys() for env_type in env_types]):
        for env_type in env_types:
            try:
                if isinstance(exported_map[env_type], ObjectCurlyBracket):
                    exported_map = exported_map[env_type].get_dictionary()
                    break
            except KeyError:
                pass

    exported_map["<AST_NODE>"] = curly_bracket
    progr.config_maps.append(exported_map)

def save_config_info(file, progr):
    root = file.get_ast()
    for child in root.get_children():
        if isinstance(child, Export):
            if child.is_pure_export: # the variable declaration is not in that child node
                for exported_elem in child.get_exported_elements():
                    elem = exported_elem.element
                    if not isinstance(elem, Identifier):
                        continue
                    assigned_expr = elem.get_assigned_expression()
                    if not isinstance(assigned_expr, ObjectCurlyBracket):
                        resol = elem.get_resolution()
                        if not isinstance(resol, Identifier):
                            continue
                        assigned_expr = resol.get_assigned_expression()
                        if not isinstance(assigned_expr, ObjectCurlyBracket):
                            continue
                    check_map_and_add_to_progr(assigned_expr, progr)
            else:
                get_dict_from_export(child,progr)

def get_types_matching_url(url_value, type_values):
    """
    :type url_value: Value
    : type_values: [Value]
    """
    if not hasattr(url_value, 'calls_passing_urls'):
        return type_values

    best_match_level = 0
    best_matching_types = []
    for type_value in type_values:
        match_level = 0
        for i in range(len(url_value.calls_passing_urls)):
            try:
                if url_value.calls_passing_urls[-i].ast_nodes[0] == type_value.calls_passing_urls[-i].ast_nodes[0]:
                    match_level+=1
            except (AttributeError, IndexError):
                break
        if match_level > best_match_level:
            best_match_level = match_level
            best_matching_types = [type_value]
        elif match_level == best_match_level:
            best_matching_types.append(type_value)

    return best_matching_types



def values_coming_from_same_branch(value1, value2):
    """
    :type value11: Value
    :type value2: Value
    :type res: bool
Check if two values come from the same branch of calls (by checking calls_passing_urls properties).
    """
    if not hasattr(value1, "calls_passing_urls") or not hasattr(value2, "calls_passing_urls"):
        return True


    for i in range(1, len(value1.calls_passing_urls)+1):
        if i > len(value2.calls_passing_urls):
            return True
        if value1.calls_passing_urls[-i].ast_nodes[0].get_resolution() != value2.calls_passing_urls[-i].ast_nodes[0].get_resolution():
            continue
        if value1.calls_passing_urls[-i].ast_nodes[0] != value2.calls_passing_urls[-i].ast_nodes[0]:
            return False
    return True

class Value:
    """
    Represent a calculated value, plus the statements that created the value
    """

    def __init__(self, value, ast_node=None):
        self.value = value
        self.ast_nodes = []
        if isinstance(ast_node, list):
            self.ast_nodes=ast_node
        elif ast_node:
            self.ast_nodes.append(ast_node)

    def __eq__(self, other):
        if isinstance(other, Value):
            return self.value == other.value and tuple(self.ast_nodes) == tuple(other.ast_nodes)
        return False

    def __hash__(self):
        return hash((self.value, tuple(self.ast_nodes)))

    @staticmethod
    def concat(value1, value2, ast_node= None):
        """
        Concatenation of values.
        """
        if not values_coming_from_same_branch(value1, value2):
            return None
        if isinstance(value1, str) and isinstance(value2, str):
            return value1 + value2
        if isinstance(value1, Value):
            new_value = value1.value
            new_ast_nodes = []
            for node in value1.ast_nodes:
                new_ast_nodes.append(node)
        else:
            new_value = value1
            new_ast_nodes = []
        if ast_node:
            new_ast_nodes.append(ast_node)
        if isinstance(value2,Value):
            new_value += value2.value
            for node in value2.ast_nodes:
                if not node in new_ast_nodes:
                    new_ast_nodes.append(node)
        else:
            new_value += value2
        to_return = Value(new_value, new_ast_nodes)
        if hasattr(value1, "calls_passing_urls"):
            to_return.calls_passing_urls = value1.calls_passing_urls
        elif hasattr(value2, "calls_passing_urls"):
            to_return.calls_passing_urls = value2.calls_passing_urls
        return to_return

    def __add__(self, other):
        new_value = self.value
        new_ast_node = self.ast_nodes
        if isinstance(other,str):
            new_value += other
        else:
            new_value += other.value
            new_ast_node.extend(other.ast_nodes)
        return Value(new_value, new_ast_node)

    def add_call_passing_urls(self, caller):
        # the only case an instantatiation might be a real_caller, it is when we evaluate from a constructor... This is a current limitation
        if isinstance(caller, Instantiation):
            return
        if hasattr(self, "calls_passing_urls"):
            self.calls_passing_urls.append(Value(self.value, caller))
        else:
            self.calls_passing_urls = [ Value(self.value, caller)]

    def get_real_caller(self):
        """
        returns the real caller and the corresponding raw_bookmark
        """
        calling_ast = None
        if hasattr(self, "calls_passing_urls"):
            url_ref = self.value.split('?')[0]
            for call in self.calls_passing_urls:
                if not isinstance(call.value, str):
                    continue
                call_url = call.value
                if call_url == '{}':
                    continue
                call_url = clean_url(call_url).split('?')[0]
                if not call_url:
                    continue
                if url_ref.endswith(call_url):
                    calling_ast = call.ast_nodes[0]
                    break

        if not calling_ast:
            return (None, None)

        try:
            symbol = calling_ast.parent_symbol
            return (symbol, RawBookmark(calling_ast, symbol.get_root_symbol()))
        except:
            log.debug("Problem saving link from ast " + str(self.callee_ast))
            log.debug(traceback.format_exc())
            return (None, None)

    def get_raw_bookmarks(self):
        raw_bookmarks = []
        for ast in self.ast_nodes:
            module = get_module_from_node(ast)
            if module:
                raw_bookmarks.append(RawBookmark(ast, module))

        return raw_bookmarks


max_duration_url_eval = 1200
max_duration_query_eval = 1200

class EvaluationParams:
    """
An instance of this class can be passed to an evaluation to parameterize this evaluation
    """
    def __init__(self, charForUnknown=None, url_expected=False, progr=None, with_trace=False, dict_expected=False, key_word_expected=False, heuristic=None, dict_keys=None, dict_keys_found=None, max_duration=False, list_expected=False, ast_node_expected=False, symbol_expected=False, track_real_caller=False, types_expected=None, stack_limit_reached=False, evaluate_in_block=True, query_expected=False, max_counter=None, debug=False):
        """
        :type charForUnknown: str
        :type url_expected: bool
        :type with_trace: bool
        :param heuristic: a function which will replace evaluate() in some specific cases
        :param with_trace: when set to True, the evaluation will return a list(Value) where each Value has an associated trace Value.ast_nodes which is a list of ast_nodes which were used in the evaluation
        :param track_real_caller: if set to true a calls_passing_urls attribute is added to each Value returned. Also set with_trace to True
        :param url_expected: when set to True, an url is expected. This will have two main effects in the evaluation:
        : param ast_node_expected: when set to True the evaluation will return a list of ast_nodes
        :param symbol_expected: will return only Symbol
        :param max_duration: maximum duration in seconds of an evaluation
        (1) when the evaluation is not successful, we try to see if some config files have a matching entry
        (2) set_ track_real_caller to True
        """
        self.charForUnknown=charForUnknown
        self.url_expected = url_expected
        self.progr = progr
        # when all the frameworks have been updated next line should be replaced with
        # self.with_trace = with_trace or self.url_expected
        self.with_trace = with_trace
        self.dict_expected = dict_expected
        self.key_word_expected = key_word_expected
        self.heuristic = heuristic
        self.evaluate_in_block = evaluate_in_block
        self.debug = debug
        if dict_keys is None:
            self.dict_keys = []
        else:
            self.dict_keys = dict_keys
        if dict_keys_found is None:
            self.dict_keys_found = set()
        elif isinstance(dict_keys_found, list):
            self.dict_keys_found = set(dict_keys_found)
        else:
            self.dict_keys_found = dict_keys

        self.from_call_stack = []

        self.query_expected = query_expected
        if query_expected:
            self.url_expected = True   # the query_expected should work as url_expected (except that we cut the evaluation when the query gets too long)
        self.list_expected = list_expected
        self.ast_node_expected = ast_node_expected
        self.symbol_expected = symbol_expected
        self.max_duration = max_duration
        if not self.max_duration:
            if symbol_expected or ast_node_expected:
                self.max_duration = 20
            if url_expected:
                self.max_duration = max_duration_url_eval
            else:
                self.max_duration = 150
        self.track_real_caller = track_real_caller
        if types_expected is None:
            self.types_expected = []
        else:
            self.types_expected = types_expected
        self.stack_limit_reached = stack_limit_reached
        if self.url_expected:
            self.track_real_caller=True

        if self.track_real_caller:
            self.with_trace = True
        self.max_counter = max_counter # stop the evaluation if the evaluate_with_context is called more than this value

    def copy(self):
        new_eval_param = copy(self)
        new_eval_param.from_call_stack = copy(self.from_call_stack)
        new_eval_param.types_expected = copy(self.types_expected)
        new_eval_param.dict_keys = copy(self.dict_keys)
        new_eval_param.dict_keys_found = copy(self.dict_keys_found)
        return new_eval_param

class EvaluationContext:
    """
    Current context of a given evaluation.
    """
    def __init__(self):

        # the AST node target stack
        self.target_stack = []
        # moment of the beginning of evaluation
        self.start_time = datetime.datetime.now()
        
    def copy(self):
        
        result = EvaluationContext()
        result.start_time = self.start_time
        result.target_stack = self.target_stack.copy()
        return result
        

def is_unknown_evaluation(evaluation_values:list, evaluation_params):
    if not evaluation_values:
        return True
    if evaluation_values == [evaluation_params.charForUnknown]:
        return True
    if len(evaluation_values)>1:
        for val in evaluation_values:
            if isinstance(val, Value):
                if val.value != '':
                    return False
            elif val != '':
                return False
        return True
    if isinstance(evaluation_values[0], Value):
        if evaluation_values[0].value == evaluation_params.charForUnknown:
            return True
        if not evaluation_values[0].value and not evaluation_params.charForUnknown:
            return True
    return False

def handle_unknown_eval(res, evaluation_params):
    """
    :type res: string or Value
this function is used to handle different cases depending on evaluation_params when a single evaluation may be unknown
    """

    if evaluation_params.charForUnknown and not res:
        if evaluation_params.with_trace:
            return [Value(evaluation_params.charForUnknown)]
        else:
            return [evaluation_params.charForUnknown]
    else:
        return res

def clean_evaluation_results(results, evaluation_params, target = None):
    """
we expect an evaluation to return a list of :
    - str if evaluation_params.with_trace == False
    - Value if evaluation_params.with_trace == True
    """

    # we first handle charForUnknown (when we have no results or an empty list)
    if evaluation_params.charForUnknown and not results:
        if evaluation_params.with_trace:
            return [Value(evaluation_params.charForUnknown)]
        else:
            return [evaluation_params.charForUnknown]
    elif results == None:
        results = []
    results = [x for x in results if (x is not None and not (isinstance(x, dict) and len(x)==0))]

    if not isinstance(results, list):
        results = [results]
    all_clean = True
    for i in range(len(results)):
        res = results[i]
        if evaluation_params.with_trace and not (isinstance(res, dict) and evaluation_params.dict_expected):
            if not isinstance(res, Value) :
                try:
                    raise TypeError(
                        "Problem in evaluations : Value expected but got something else")
                except:
                    if target:
                        log.debug("The target was " + str(target) + ' and the evaluation gives ' + str(res))
                    log.debug(traceback.format_exc())
                    continue
            val = res.value
        else:
            val = res

        if evaluation_params.ast_node_expected and isinstance(val, (Node, Token)):
            pass # ok
        elif evaluation_params.dict_expected and isinstance(val, dict):
            pass # ok
        elif evaluation_params.symbol_expected and isinstance(val, Symbol):
            pass # ok
        elif type(val) in evaluation_params.types_expected:
            pass # ok
        elif isinstance(val, str):
            pass #ok
        else :
            try:
                raise TypeError("Problem in evaluations: got unexpected type")
            except:
                log.debug("      for evaluation " + str(val))
                if target:
                    log.debug("The target was " + str(target))
                log.debug(traceback.format_exc())

    # we remove the unknown results (we just keep one result)
    if len(results)>1 and evaluation_params.with_trace:
        new_results = []
        for res in results:
            if hasattr(res, 'value') and (res.value == evaluation_params.charForUnknown or res.value is None or res.value == ''):
                continue
            new_results.append(res)
        if new_results:
            return new_results
        else:
            return handle_unknown_eval([], evaluation_params)
    if len(results) >1000:
        log.debug("During evaluation, too many values where found. Only the first 1000 are kept.")
        return results[:1000]
    else:
        return results

def remove_last_target_from_stack(context:EvaluationContext):
    if len(context.target_stack)==0:
        log.warning('Problem, target_stack should not be empty')
    context.target_stack.pop()

class EvaluationState:
    eval_broken = False
    counter = 0
    root_evaluation_params = None
    printed_time_limit = False
    debug = False


    @classmethod
    def break_evaluation(cls):
        return cls.eval_broken

    @classmethod
    def evaluation_failed(cls):
        cls.eval_broken = True

    @classmethod
    def has_printed_time_limit(cls):
        cls.printed_time_limit = True

    @classmethod
    def reset(cls, evaluation_params):
        cls.eval_broken = False
        cls.counter = 0
        cls.root_evaluation_params = evaluation_params
        cls.printed_time_limit = False

    @classmethod
    def reset_debug(cls):
        cls.debug = False

    @classmethod
    def set_debug(cls, debug):
        cls.debug = True


def extract_values_from_tree(calls_passing_urls):
    for v in calls_passing_urls.values():
        if isinstance(v, Value):
            yield v
        elif isinstance(v, OrderedDict):
            yield from extract_values_from_tree(v)

def remove_duplicate_with_trace(evls):
    """
    remove all duplicates.
    If two evaluations have the same value, we compare the calls_passing_urls. If the calls_passing_urls do not match, we keep both results. If they match we keep the value having the shortest calls_passing_urls
    Should be use at the end of the eval or before concatenation

    """
    if len(evls)<2:
        return evls

    # we first sort the evls by value
    evls_by_values = DefaultOrderedDict(list)
    for ev in evls:
        evls_by_values[ev.value].append(ev)

    all_unique_values = []
    for evals in evls_by_values.values():
        # we only want to keep values coming from different calls_passing_urls
        calls_passing_urls = OrderedDict() # this is a tree of calls_passing_url. The key is ast nodes from calls_passing_urls value is either another OrderedDict a an eval
        for e in evals:

            if not hasattr(e, 'calls_passing_urls'):
                # we do not need to keep other values because this value will be compatible with any value coming from any call_passing_urls
                all_unique_values.append(e)
                break

            else:
                current_dict = calls_passing_urls
                for i in range(len(e.calls_passing_urls)):
                    call = e.calls_passing_urls[-1-i].ast_nodes[0]

                    if call in current_dict:

                        if isinstance(current_dict[call], Value):
                            break  # there is a shorter one
                        elif i==len(e.calls_passing_urls)-1:
                            current_dict[call] = e # we remove the longer pathes, this one is shorter
                        else:
                            current_dict = current_dict[call]
                    else:
                        if i==len(e.calls_passing_urls)-1:
                            current_dict[call] = e
                        else:
                            current_dict[call] = OrderedDict()
                            current_dict = current_dict[call]


        for unique_value in extract_values_from_tree(calls_passing_urls):
            all_unique_values.append(unique_value)
    return all_unique_values

def remove_duplicates(evls, evaluation_params):
    if len(evls)<2 or evaluation_params.dict_expected or evaluation_params.symbol_expected or evaluation_params.ast_node_expected:
        return evls
    if evaluation_params.with_trace:
        return remove_duplicate_with_trace(evls)
    else:
        seen = set()
        return [x for x in evls if not (x in seen or seen.add(x))]

class EvaluationStatistics:
    nb_string_evals = 0
    nb_ast_evals = 0 # ast plus symbol evals
    total_time_spent_in_string_evals = datetime.timedelta()
    total_time_spent_in_ast_evals = datetime.timedelta()
    max_duration_in_string_eval = datetime.timedelta()
    max_evaluation_steps = 0
    max_evaluation_steps_for_ast_eval = 0

    @classmethod
    def reset(cls):
        cls.nb_string_evals = 0
        cls.nb_ast_evals = 0  # ast plus symbol evals
        cls.total_time_spent_in_string_evals = datetime.timedelta()
        cls.total_time_spent_in_ast_evals = datetime.timedelta()
        cls.max_duration_in_string_eval = datetime.timedelta()

    @classmethod
    def log_statistics(cls):
        log.info('Number of ast resolution using eval: %s' % cls.nb_ast_evals)
        log.info('Total duration of ast resolution using eval %s' % str(cls.total_time_spent_in_ast_evals))
        log.info('[Evaluation] Number of evaluations: %s' % cls.nb_string_evals)
        log.info('[Evaluation] Total evaluation duration %s' % str(cls.total_time_spent_in_string_evals))
        log.info('[Evaluation] Max evaluation duration %s' % str(cls.max_duration_in_string_eval))
        log.info('[Evaluation] Max evaluation number of steps: %s' % cls.max_evaluation_steps)
        log.info('[Evaluation] Max evaluation number of steps for ast_node or symbol: %s' % cls.max_evaluation_steps_for_ast_eval)

def evaluate(target, evaluation_params=None):
    start_time = datetime.datetime.now()
    if not evaluation_params:
        evaluation_params = EvaluationParams()
    context = EvaluationContext()
    EvaluationState.reset(evaluation_params)
    results = evaluate_with_context(target,
                                    context=context,
                                    evaluation_params=evaluation_params)
    results = remove_duplicates(results, evaluation_params)
    duration = datetime.datetime.now() - start_time
    if evaluation_params.ast_node_expected or evaluation_params.symbol_expected or evaluation_params.dict_expected:
        EvaluationStatistics.nb_ast_evals += 1
        EvaluationStatistics.total_time_spent_in_ast_evals += duration
    else:
        EvaluationStatistics.nb_string_evals += 1
        EvaluationStatistics.total_time_spent_in_string_evals += duration
        if duration > EvaluationStatistics.max_duration_in_string_eval:
            EvaluationStatistics.max_duration_in_string_eval = duration

    if EvaluationState.counter > EvaluationStatistics.max_evaluation_steps:
        EvaluationStatistics.max_evaluation_steps = EvaluationState.counter

    if evaluation_params.ast_node_expected or evaluation_params.symbol_expected:
        if EvaluationState.counter > EvaluationStatistics.max_evaluation_steps_for_ast_eval:
            EvaluationStatistics.max_evaluation_steps_for_ast_eval = EvaluationState.counter

    return results

def evaluate_with_context(target: object, context: object, evaluation_params: object) -> object:

    # something went wrong. Stop further evaluation
    if EvaluationState.break_evaluation():
        return clean_evaluation_results([], evaluation_params)

    ######################################################
    ##Uncomment the following for debuging
    # try:
    #
    #     if evaluation_params.url_expected and hasattr(target, "parent"):
    #         parent = target.parent
    #         while True:
    #             if isinstance(parent, Root):
    #                 break
    #             parent = parent.parent
    #
    #         log.debug("Evaluating target " + str(target))
    #         log.debug("       from file " + parent.module.get_fullname())
    # except:
    #     pass

    ## end of to remove
    ######################################################
    try:
        if evaluation_params.stack_limit_reached:
            return clean_evaluation_results([], evaluation_params)

        if EvaluationState.debug:
            log.debug('debug evaluation target ' + str(target))

        if len(context.target_stack) > 50:
            return clean_evaluation_results([], evaluation_params)
        if len(traceback.extract_stack()) > 500:
            log.warning('Problem: exceeding stack limit')
            log.debug(str(traceback.extract_stack()[-100]))
            evaluation_params.stack_limit_reached = True
            EvaluationState.evaluation_failed()
            return clean_evaluation_results([], evaluation_params)
        if context.target_stack.count(target)>2:
            return clean_evaluation_results([], evaluation_params)
        context.target_stack.append(target)
        EvaluationState.counter += 1

        root_eval_params = EvaluationState.root_evaluation_params
        if evaluation_params.max_counter:
            if EvaluationState.counter > evaluation_params.max_counter:
                EvaluationState.evaluation_failed()
                if evaluation_params.max_counter<250:
                    log.debug('Problem : evaluation takes more than ' + str(
                        evaluation_params.max_counter) + ' steps (maximum allowed here) when evaluating symbol or ast_node ' + str(
                    context.target_stack[0]))
                else:
                    log.info('Problem : evaluation takes more than ' + str(
                        evaluation_params.max_counter) + ' steps (maximum allowed here) when evaluating symbol or ast_node ' + str(
                        context.target_stack[0]))

                remove_last_target_from_stack(context)
                return clean_evaluation_results([], evaluation_params)

        elif root_eval_params.ast_node_expected or root_eval_params.symbol_expected:
            if EvaluationState.counter > 350:
                EvaluationState.evaluation_failed()
                log.warning('Problem : evaluation takes too many steps when evaluating symbol or ast_node ' + str(context.target_stack[0]))
                remove_last_target_from_stack(context)
                return clean_evaluation_results([], evaluation_params)

        elif root_eval_params.url_expected or root_eval_params.query_expected:
            if EvaluationState.counter > 3500:
                EvaluationState.evaluation_failed()
                log.warning('Problem : evaluation takes too many steps when evaluating url or query ' + str(context.target_stack[0]))
                remove_last_target_from_stack(context)
                return clean_evaluation_results([], evaluation_params)
        else:
            if EvaluationState.counter > 1500:
                EvaluationState.evaluation_failed()
                log.warning('Problem : evaluation takes too many steps')
                remove_last_target_from_stack(context)
                return clean_evaluation_results([], evaluation_params)

        # current duration of evaluation
        now = datetime.datetime.now()
        delta = now - context.start_time
        if delta >= datetime.timedelta(seconds=evaluation_params.max_duration):
            EvaluationState.evaluation_failed()
            # max duration reached
            if not EvaluationState.printed_time_limit:
                EvaluationState.has_printed_time_limit()
                if context.target_stack:
                    if evaluation_params.max_duration > 20:
                        log.warning("Problem: Exceeding time limit (" + str(
                            evaluation_params.max_duration) + " s) when evaluating " + str(context.target_stack[0]))
                        log.warning("Problem: counter = " + str(EvaluationState.counter))
                    else:
                        log.debug("Problem: Exceeding time limit (" + str(evaluation_params.max_duration) + " s) when evaluating " + str(context.target_stack[0]))
                        log.warning("Problem: counter = " + str(EvaluationState.counter))
                else:
                    if evaluation_params.max_duration > 20:
                        log.warning("Problem: Exceeding time limit (" + str(evaluation_params.max_duration) + " s)")
                        log.warning("Problem: counter = " + str(EvaluationState.counter))
                    else:
                        log.debug('Problem: Exceeding time limit (' + str(evaluation_params.max_duration) + ' s)')
                        log.warning("Problem: counter = " + str(EvaluationState.counter))
            remove_last_target_from_stack(context)
            return clean_evaluation_results([], evaluation_params)

        if isinstance(target, ExternalIdentifier):
            # evaluate_identifier(target, context, evaluation_params)
            try:
                _results = target.original_object.evaluate_with_trace()
                return [result if type(result) is str else Value(result.value, result.ast_nodes) for result in _results]
            except:
                return []
        result = []
        if evaluation_params.heuristic:
            if isinstance(evaluation_params.heuristic, list):
                heuristics = evaluation_params.heuristic
            else:
                heuristics = [evaluation_params.heuristic]

            for heuristic in heuristics:
                try:
                    result = heuristic(target, context, evaluation_params)
                except:
                    pass
                if result:
                    break
            if result == None:
                result =[]

        if evaluation_params.symbol_expected:
            if isinstance(target, (Identifier, MemberAccess, Method, Function, ArrowExpression)):
                result.extend(evaluate_symbol(target, evaluation_params))

        if result:
            pass
        elif isinstance(target, Parameter):
            result = evaluate_with_context(target.get_identifier(), context, evaluation_params)
        elif isinstance(target, str):
            return  [target]
        elif isinstance(target, Class) and evaluation_params.ast_node_expected:
            return [target]
        elif isinstance(target, symbols.Field):
            result = evaluate_field(target, context, evaluation_params)
        elif isinstance(target, Await):
            tokens = target.get_children()
            try:
                next(tokens)
                tok = next(tokens)
                result =  evaluate_with_context(tok, context, evaluation_params)
            except StopIteration:
                pass

        elif isinstance(target, Identifier):
            result = evaluate_identifier(target, context, evaluation_params)

        elif isinstance(target, Bracket) and evaluation_params.list_expected:
            result = evaluate_list(target, context, evaluation_params)

        elif isinstance(target, Instantiation) and evaluation_params.dict_keys:
            _class = target.get_resolution()
            if isinstance(_class, SymbolClass):
                decl = _class.get_field_or_constr_decl(evaluation_params.dict_keys[-1])
                if decl:
                    if not evaluation_params.dict_keys[-1] in evaluation_params.dict_keys_found:
                        evaluation_params.dict_keys_found.add(evaluation_params.dict_keys[-1])
                    result =  evaluate_with_context(decl, context=context, evaluation_params=evaluation_params)

        elif isinstance(target, MemberAccess):
            result = evaluate_member_access(target, context, evaluation_params)
            if is_unknown_evaluation(result, evaluation_params) and evaluation_params.url_expected and evaluation_params.progr:
                # we check if there is an entry in progr.config_maps which corresponds to target.get_name()
                for config_map in evaluation_params.progr.config_maps:
                    if not target.get_name() in config_map.keys():
                        continue
                    result =  evaluate_with_context(config_map[target.get_name()], context=context, evaluation_params=evaluation_params)
                    # we want to add config_map[target.get_name()] to the trace
                    # if it is a Token, we wont be able to generate the Bookmark because Tokens do not have parent attribute.
                    # so we add a parent_curly attribute
                    if isinstance(config_map[target.get_name()], Token):
                        config_map[target.get_name()].parent_curly = config_map["<AST_NODE>"]
                    add_ast_node_to_values(result, config_map[target.get_name()],evaluation_params)


        elif isinstance(target, StringTemplate):
            result = evaluate_string_template(target, context, evaluation_params)
        elif isinstance(target, NodeExport):
            result = evaluate_node_export(target, context, evaluation_params)
        elif isinstance(target, ObjectCurlyBracket):

            evals = []
            if evaluation_params.dict_keys:
                tar_dict = target.get_dictionary()
                seen_keys = []
                for key in evaluation_params.dict_keys:

                    if key in tar_dict:
                        if not key in evaluation_params.dict_keys_found:
                            evaluation_params.dict_keys_found.add(key)
                        extra_evals =  evaluate_with_context(tar_dict[key], context, evaluation_params)
                        for e_e in extra_evals:
                            if not e_e in evals:
                                evals.append(e_e)

                if not evals and '$spread_maps' in tar_dict.keys():
                    for spread_map in tar_dict['$spread_maps']:
                        extra_results =  evaluate_with_context(spread_map, context=context, evaluation_params=evaluation_params)
                        if extra_results:
                            evals.extend(extra_results)
            if evals:
                result = evals

            elif evaluation_params.dict_expected:
                if evaluation_params.with_trace:
                    remove_last_target_from_stack(context)
                    return [Value(target.get_dictionary())]
                else:
                    remove_last_target_from_stack(context)
                    return [target.get_dictionary()]

        elif isinstance(target, BinaryOperation):
            result = evaluate_binary_operation(target, context, evaluation_params)

        elif isinstance(target, IfTernary):
            result = evaluate_ternary_operation(target, context, evaluation_params)

        elif isinstance(target, (MethodCall, FunctionCall)):
            result = evaluate_call(target, context, evaluation_params)

        elif isinstance(target, Assignment):
            result = evaluate_assignment(target, context, evaluation_params)

        elif isinstance(target, Argument):
            result =  evaluate_with_context(list(target.get_children())[0], context, evaluation_params= evaluation_params)
        elif isinstance(target, ArrayAccess):
            result = evaluate_array_access(target, context,evaluation_params)
        elif isinstance(target, ExportedVariable):
            result =  evaluate_with_context(target.get_ast(), context, evaluation_params)

        elif isinstance(target, Parenthesis):
            result =  evaluate_with_context(target.children[1], context, evaluation_params)
        else:
            result = evaluate_constant(target, context, evaluation_params)

        if evaluation_params.ast_node_expected:
            if not result and isinstance(target, Node):
                remove_last_target_from_stack(context)
                if evaluation_params.with_trace:
                    return [Value(target)]
                else:
                    return [target]
        remove_last_target_from_stack(context)
        return clean_evaluation_results(result, evaluation_params, target)
    except:
        log.warning("Problem in the evaluation")
        try:
            # put this in a try because if we have stack size issue that might bug
            log.debug(traceback.format_exc())
        except:
            pass
        remove_last_target_from_stack(context)
        return []

def evaluate_url(parameter, evaluation_params=None):
    """
    :type parameter: Node
    :param parameter: an ast_node which can be evaluated
    :type evaluation_params: EvaluationParams
    """
    if not evaluation_params:
        evaluation_params = EvaluationParams(url_expected=True, with_trace=True)

    def get_relevant_url_call(url):
        """
        :type url: Value
        """
        if hasattr(url, "calls_passing_urls"):
            for call in url.calls_passing_urls:
                if call.value == url.value:
                    call_node = call.ast_nodes[0]
                    return call_node

    evaluation_params.max_duration = max_duration_url_eval
    try:
        #         log.info('evaluating ' + str(parameter) + '...')
        evaluations =  evaluate(parameter, evaluation_params=evaluation_params)
    #         log.info('...evaluated to ' + str([value.value for value in evaluations]))
    except:
        log.warning('Problem during url evaluation')
        log.warning(traceback.format_exc())
        return False
    try:
        for eval in evaluations:
            eval.value = clean_url(eval.value)
    except AttributeError:
        pass
    # remove duplicates
    if len(evaluations) > 1:
        new_evals = []
        for i, eval1 in enumerate(evaluations[:-1]):
            if not isinstance(eval1, Value):
                log.debug("Problem, Value expected")
                continue
            if eval1.value == '':
                continue

            if evaluation_params.charForUnknown and eval1.value == evaluation_params.charForUnknown:
                continue
            has_duplicate = False
            for eval2 in evaluations[i + 1:]:
                if eval2.value == eval1.value:
                    try:
                        if list(eval1.get_real_caller())[0] == list(eval2.get_real_caller())[0] :
                            has_duplicate = True
                            for ast_node in eval1.ast_nodes:
                                if not ast_node in eval2.ast_nodes:
                                    eval2.ast_nodes.append(ast_node)
                            break
                    except (AttributeError, IndexError):
                        pass

            if not has_duplicate:
                new_evals.append(eval1)
        new_evals.append(evaluations[-1])
        evaluations = new_evals
    # cleaning
    cleaned = []
    for evaluation in evaluations:
        if isinstance(evaluation, OrderedDict) or evaluation.value == '':
            continue

        if evaluation_params.charForUnknown and evaluation.value == evaluation_params.charForUnknown:
            continue
        evaluation.value = clean_url(evaluation.value)
        cleaned.append(evaluation)

    # in case of empty eval
    return clean_evaluation_results(cleaned, evaluation_params, target=None)


def filter_compatible_evals(compatible_values, list_of_evals_to_check):
    """
    :type compatible_values: list(Value)
    :type list_of_evals_to_check: list(list(Value))
    :param compatible_values: list of Values which are compatible
    :param list_of_evals_to_check
    """
    for value in list_of_evals_to_check[0]:
        if compatible_values:
            is_compatible=True
            for check_value in compatible_values:
                if not values_coming_from_same_branch(value, check_value):
                    is_compatible = False
                    break
            if is_compatible:
                if len(list_of_evals_to_check) > 1:
                    yield from filter_compatible_evals(compatible_values + [value], list_of_evals_to_check[1:])
                else:
                    yield compatible_values + [value]

        else:
            yield from filter_compatible_evals([value], list_of_evals_to_check[1:])



def evaluate_array_access(target, context=None, evaluation_params=None):
    if not evaluation_params:
        evaluation_params = EvaluationParams()
    if target.get_name() == 'window':
        if not evaluation_params.progr:
            log.debug("Warning, cannot evaluate window variable since the program was not provided")
            return
        args = target.get_arguments()
        if len(args) == 1:
            new_evaluation_params = evaluation_params.copy()
            new_evaluation_params.with_trace = False
            evals =  evaluate_with_context(args[0], context, new_evaluation_params)
            if evals and evals[0] in evaluation_params.progr.window_object:
                matching_objects = evaluation_params.progr.window_object[evals[0]]
                if len(matching_objects) == 1:
                    return  evaluate_with_context(matching_objects[0][0], context, evaluation_params)
                else:
                    paths = [m_o[1] for m_o in matching_objects]
                    current_path = get_module_path_from_node(target)
                    closest_path = get_closest_path(current_path, paths)
                    for m_o in matching_objects:
                        if closest_path == m_o[1]:
                            return  evaluate_with_context(m_o[0], context, evaluation_params)


    # it may be an access to a map
    # we create a fake member access equivalent to the ArrayAccess
    m_a = MemberAccess()
    for child in target.children:
        if not isinstance(child, Bracket):
            if child == ";":
                break
            m_a.children.append(child)
        else:
            items = child.extract_literal_items()
            if len(items) != 1:
                if not len(child.children) ==3:
                    return []
                identifier = child.children[1]
                if not isinstance(identifier, Identifier):
                    return []
                eval_params = EvaluationParams(max_duration=10)
                eval_params.from_call_stack = evaluation_params.from_call_stack
                items =  evaluate_with_context(identifier, context, eval_params)
                if not items:
                    return []
            item = items[0]
            m_a.children.append(Token(".", Punctuation))
            m_a.children.append(Identifier(Token(item, Generic)))

    return  evaluate_with_context(m_a, context, evaluation_params)


def evaluate_node_export(target, context, evaluation_params):

    if target.is_single_export:
        resolution_tmp = target.get_symbol("<SingleExport>")
        if isinstance(resolution_tmp, ExportedVariable):
            return  evaluate_with_context(resolution_tmp.get_ast(), context, evaluation_params)
        if resolution_tmp:
            return  evaluate_with_context(resolution_tmp, context, evaluation_params)
        # there might be no symbol exported
        # in that case the ast of the exported element should be checked
        else:
            assigned = target.exported_ast["<SingleExport>"]
            if assigned:
                return  evaluate_with_context(assigned, context, evaluation_params)

def evaluate_string_template(string, context=None, evaluation_params=None):
    if not evaluation_params:
        evaluation_params = EvaluationParams()
    if not string.template:
        string.extract_expressions()
    results = []
    nb_expressions = len(string.expressions)

    if nb_expressions:
        list_of_values = []
        for expression in string.expressions:
            values =  evaluate_with_context(expression, context, evaluation_params)
            values = handle_unknown_eval(values, evaluation_params)
            list_of_values.append(remove_duplicates(values, evaluation_params))

        template = string.template

        if nb_expressions == 1:
            for value in list_of_values[0]:

                if isinstance(value, Value):
                    val = template.format(value.value)
                    val = val.replace('U+007D', "}")
                    val = val.replace('U+007B', "{")
                    result = value
                    result.value = val
                else:
                    value = template.format(value)
                    value = value.replace('U+007B', "{")
                    result = value.replace('U+007D', "}")

                results.append(result)
        else:
            if evaluation_params.with_trace:
                products = filter_compatible_evals(None, list_of_values)
            else:
                products = itertools.product(*list_of_values)
            for combination in products:
                try:
                    if evaluation_params.with_trace:

                        value = template.format(*tuple([elem.value if hasattr(elem, "value") else '{}' for elem in combination]))
                        value = value.replace('U+007B', "{")
                        value = value.replace('U+007D', "}")
                        result = Value(value)
                        for elem in combination:
                            result.ast_nodes.extend(elem.ast_nodes)
                            if hasattr(elem, "calls_passing_urls") and elem.calls_passing_urls:
                                result.calls_passing_urls = elem.calls_passing_urls
                    else:
                        result = template.format(*combination)
                        result = result.replace('U+007B', "{")
                        result = result.replace('U+007D', "}")
                    results.append(result)
                except ValueError:
                    log.debug("Problem formating template " + template)
                    continue
        if len(results) == 0:
            if evaluation_params.with_trace:
                results = [Value(string.template.strip())]
            else:
                results = [string.template.strip()]

    else:
        val = string.template.strip()
        val = val.replace('U+007B', "{")
        val = val.replace('U+007D', "}")
        if evaluation_params.with_trace:
            results = [Value(val)]
        else:
            results = [val]

    if not results and evaluation_params.charForUnknown:
        return [evaluation_params.charForUnknown]
    return results

    
def evaluate_individual(element, context=None, evaluation_params=None):
    if not evaluation_params:
        evaluation_params = EvaluationParams()
    if evaluation_params.key_word_expected and isinstance(element, Token):
        if element in ["true", "false", "any"]:
            return [element.text]

    if not element or not hasattr(element, 'type'):
        return []
    if is_token_subtype(element.type, ST):
        text = element.text
        ts = StringTemplate()
        ts.text= text
        ts.extract_expressions()
        text = ts.template
        return [text]
    if is_token_subtype(element.type, Literal):
        text = element.text
        if text.startswith(quote_marks):
            for mark in quote_marks:
                text_stripped = text.strip(mark)
                if text_stripped == text:
                    continue
                text = text_stripped

        return [text]
    return handle_unknown_eval([], evaluation_params)


    
def evaluate_constant(constant, context=None, evaluation_params=None):
    if not evaluation_params:
        evaluation_params = EvaluationParams()
    if evaluation_params.ast_node_expected == True or evaluation_params.symbol_expected==True:
        return []
    value = []
    if isinstance(constant, Instantiation) and constant.get_fullname() == "String":
        argument = constant.get_argument()
        if not argument:
            value.extend([''])
        else:
            value.extend(evaluate_with_context(next(argument.get_children()), context, evaluation_params))

    elif isinstance(constant, list):
        for element in constant:
            value.extend(evaluate_individual(element, context, evaluation_params))
    else:
        value.extend(evaluate_individual(constant, context, evaluation_params))

    if evaluation_params.with_trace:
        return [Value(val) if isinstance(val, str) else val for val in value]
    else:
        return value

def is_unsuccessful_evaluation(values, evaluation_params):
    """ return true if the values returned by an evaluation is an empty list or if it corresponds to the charForUnknown value"""
    if not values:
        return True
    if len(values)>1:
        return False
    if evaluation_params.charForUnknown:
        if values[0] == evaluation_params.charForUnknown:
            return True
        if isinstance(values[0], Value) and values[0].value == evaluation_params.charForUnknown:
            return True

    return False

def evaluate_map(expression, key_names, context=None, evaluation_params=None, strict=True):
    """
    deprecated should use dictkeys from EvaluationParam
    """
    if not isinstance(key_names, list):
        key_names = [key_names]
    if not evaluation_params:
        evaluation_params = EvaluationParams()
    if not context:
        context = EvaluationContext()
    EvaluationState.reset(evaluation_params)
    new_evaluation_param = evaluation_params.copy()
    for k in key_names:
        if not k in new_evaluation_param.dict_keys:
            new_evaluation_param.dict_keys.append(k)
    evls =  evaluate_with_context(expression, context, evaluation_params=new_evaluation_param)
    if not any([k in new_evaluation_param.dict_keys_found for k in key_names]) and (strict or evaluation_params.ast_node_expected):
        return []
    for found_key in new_evaluation_param.dict_keys_found:
        if len(key_names)>20:
            log.info(key_names)
        if not found_key in key_names:
            evaluation_params.dict_keys_found.add(found_key)
    return evls


def evaluate_member_access(access, context=None, evaluation_params=None):
    """
    Member access can refer to
    three different scenarios:
    
        (i) access to instance member
        (ii) access to map (dictionary)
        (iii) access to a getter
    """
    if not evaluation_params:
        evaluation_params = EvaluationParams()

    # (i) relies on member resolution
    resolution = access.get_resolution()
    if resolution and not isinstance(resolution, SymbolMethod) and not resolution == access:
        return  evaluate_with_context(resolution, context, evaluation_params)
    if access._resolutions and not isinstance(access._resolutions[0], SymbolMethod):
        return  evaluate_with_context(access._resolutions[0], context, evaluation_params)

    # check for getter
    if isinstance(resolution, SymbolMethod):
        if resolution.get_ast().is_getter():
            fake_call = MethodCall()
            fake_call.children = access.children
            fake_call.children
            fake_call._resolutions.append(resolution)

            fake_call.is_fake_call = True
            try:
                evaluation =  evaluate_with_context(fake_call, context=context, evaluation_params=evaluation_params)
                return evaluation
            except:
                log.debug("Problem evaluating member access " + str(access) + " through getter")

    # (ii) and (iii) rely on expression resolution
    expression = access.get_expression()  # a.b -> a
    evaluation = evaluate_map(expression, access.get_name(), context, evaluation_params)
    if evaluation :
        if len(evaluation)!=1 or isinstance(evaluation[0], dict):
            return evaluation
        elif isinstance(evaluation[0], str) and evaluation[0] != evaluation_params.charForUnknown :
            return evaluation
        elif isinstance(evaluation[0], Value) and evaluation[0].value != evaluation_params.charForUnknown:
            return evaluation


    if isinstance(expression, (Identifier, MemberAccess)):
        for resolution in  evaluate_with_context(expression, context=context, evaluation_params = EvaluationParams(ast_node_expected=True, max_duration=evaluation_params.max_duration)):
            if isinstance(resolution, Instantiation):
                resolution = resolution.get_resolution()
            if isinstance(resolution, ExportedVariable):
                resolution = resolution.get_ast()
                if hasattr(resolution, 'get_resolution'):
                    if resolution.get_resolution():
                        resolution = resolution.get_resolution()
            if isinstance(resolution, Identifier):
                assigned_expr = resolution.get_assigned_expression()
                if isinstance(assigned_expr, Instantiation):
                    resolution = assigned_expr.get_resolution()
                if not assigned_expr and isinstance(resolution.parent, Parameter):
                    try:
                        resolution = resolution.parent.get_variable_type().get_expression().get_resolution()
                    except AttributeError:
                        pass
            if isinstance(resolution, Enum):
                val = resolution.get_value(access.get_name())
                if val:
                    results =  evaluate_with_context(val, context=context, evaluation_params=evaluation_params)
                    return add_ast_node_to_values(results, resolution, evaluation_params)

            elif isinstance(resolution, SymbolClass):
                decl = resolution.get_member_declaration(access.get_name())
                if decl:
                    results =  evaluate_with_context(decl, context=context, evaluation_params=evaluation_params)
                    if evaluation_params.with_trace:
                        return add_ast_node_to_values(results, decl, evaluation_params)
                    else:
                        return results
            elif isinstance(resolution, ObjectCurlyBracket) and access.get_name() in resolution.get_dictionary():
                return  evaluate_with_context(resolution.get_dictionary()[access.get_name()], context=context, evaluation_params=evaluation_params)

    # check if we are within ObjectCurlyBracket (i.e. map)
    if expression == "this" and hasattr(access, 'parent'):
        parent = access.parent
        while True:
            if isinstance(parent, ObjectCurlyBracket):
                try:
                    val = parent.get_dictionary()[access.get_name()]
                    results =  evaluate_with_context(val, context=context, evaluation_params = evaluation_params)
                    if evaluation_params.with_trace:
                        for res in results:
                            res.ast_nodes.append(val)
                    return results
                except (KeyError, AttributeError, TypeError):
                    break
            elif isinstance(parent, (SymbolClass, Function)):
                break
            try:
                parent= parent.parent
            except (AttributeError, TypeError):
                break

    if is_unknown_evaluation(evaluation, evaluation_params) and hasattr(access, 'parent') and isinstance(access.parent, Assignment) and access.parent.get_left_expression()==access:
        evaluation =  evaluate_with_context(access.parent.get_right_expression(), evaluation_params=evaluation_params, context=context)
    return evaluation



def evaluate_assignment(assignment, context=None, evaluation_params=None):
    if not evaluation_params:
        evaluation_params = EvaluationParams()

    right = assignment.get_right_expression()
    values =  evaluate_with_context(right, context, evaluation_params)
    return values


def evaluate_object_assign(call, context, evaluation_params):
    final_evls = []
    my_dict = OrderedDict()
    for arg in call.get_arguments():
        evls =  evaluate_with_context(arg, context, evaluation_params)
        if not evls:
            continue
        if not final_evls:
            final_evls = evls
        else:
            for evl in evls:
                if not evl in final_evls:
                    final_evls.append(evl)

    return final_evls

def evaluate_lodash_find(call, context, evaluation_params):
    try:
        predicate = call.get_argument(1).children[0]
    except (AttributeError, IndexError):
        return

    # for now we only support the case of a CurlyBracket
    if not isinstance(predicate, ObjectCurlyBracket):
        return
    predicate = predicate.get_dictionary()

    if len(predicate) > 1:
        log.warning(
            "Problem: the lodash find method is not supported when the predicate contains more than one element (i.e. : find(users, {element1: 'foo', element2: 'bar'. Canceling evaluation")
        return

    for predicate_key, predicate_val_ast in predicate.items():
        predicate_values =  evaluate_with_context(predicate_val_ast, context=context.copy(), evaluation_params=evaluation_params.copy())


    new_eval_params = evaluation_params.copy()
    new_eval_params.ast_node_expected = True
    new_eval_params.with_trace = False
    arg_evals =  evaluate_with_context(call.get_argument(0), context=context, evaluation_params=new_eval_params)
    if not arg_evals:
        return
    arg_eval = arg_evals[0]
    if not isinstance(arg_eval, Bracket):
        log.warning('Problem evaluating lodash find')
        return

    to_return = []

    for ocb in arg_eval.get_items():
        if not isinstance(ocb, ObjectCurlyBracket):
            new_eval_params = evaluation_params.copy()
            new_eval_params.ast_node_expected = True
            ocbs =  evaluate_with_context(ocb, context=context, evaluation_params=new_eval_params)
            if not ocbs:
                continue
            ocb = ocbs[0]
            if not isinstance(ocb, ObjectCurlyBracket):
                continue
        ocb_dict = ocb.get_dictionary()
        if not predicate_key in ocb_dict:
            continue
        new_eval_params = evaluation_params.copy()
        new_eval_params.with_trace = False
        element_values =  evaluate_with_context(ocb_dict[predicate_key], context.copy(), new_eval_params)
        # element_values =  evaluate2(ocb_dict[predicate_key])
        if not element_values:
            continue
        if len(element_values)>1:
            log.warning('Problem, the support of lodash find is limited when on element has several values. Only first value will be considered')
        element_value = element_values[0]

        for predicate_val in predicate_values:
            predicate_string_val = predicate_val
            if isinstance(predicate_val, Value):
                predicate_string_val = predicate_val.value

            if not predicate_string_val==element_value:
                continue

            if evaluation_params.dict_keys:
                if evaluation_params.dict_keys[-1] in ocb_dict:
                    if not evaluation_params.dict_keys[-1] in evaluation_params.dict_keys_found:
                        evaluation_params.dict_keys_found.add(evaluation_params.dict_keys[-1])
                    evls =  evaluate_with_context(ocb_dict[evaluation_params.dict_keys[-1]], context=context.copy(), evaluation_params=EvaluationParams(max_duration=evaluation_params.max_duration))
                    if not evls:
                        continue
                    if len(evls)>1:
                        log.warning(
                            'Problem, the support of lodash find is limited when on element has several values. Only first value will be considered. May lead to missing values.')
                    evl = evls[0]

                    if isinstance(predicate_val, Value):
                        value_to_return = copy(predicate_val)
                        value_to_return.value = evl
                        # we cheat and change the value for the calls passing the url because we want the real_caller to be that of the predicate (see test test_closer_to_cgi_complex_multiple_with_realcaller)
                        if hasattr(value_to_return, 'calls_passing_urls'):
                            for c in value_to_return.calls_passing_urls:
                                c.value = evl
                        to_return.append(value_to_return)
                    else:
                        to_return.append(evl)
    return to_return

def evaluate_call(call, context=None, evaluation_params=None):
    """
    find the method (or function) which is the resolution of the call
    evaluate the return of that method (or function)    
    """


    if not evaluation_params:
        evaluation_params = EvaluationParams()


    if not hasattr(call, 'is_fake_call') and call.get_name() == 'find' and call.is_imported_from_framework=='lodash' and (evaluation_params.ast_node_expected or evaluation_params.dict_keys):
        return evaluate_lodash_find(call, context, evaluation_params)

    if hasattr(call, 'get_fullname') and not hasattr(call, 'is_fake_call') and call.get_fullname() == 'Object.assign':
        if evaluation_params.dict_expected or evaluation_params.dict_keys:
            new_eval_params = evaluation_params.copy()
            evls = evaluate_object_assign(call, context, new_eval_params)
            for key_found in new_eval_params.dict_keys_found:
                if not key_found in evaluation_params.dict_keys_found:
                    evaluation_params.dict_keys_found.add(key_found)
            return evls



    def join_bracket_items(call, expression, evaluation_params=None):
        if not evaluation_params:
            evaluation_params = EvaluationParams()

        if isinstance(expression, Bracket):
            try:
                # we just take the first evaluated value for each item
                values_list = [evaluate_with_context(item, context, evaluation_params=evaluation_params)[0] for item in expression.get_items()]
            except:
                log.debug("Problem evaluating the join bracket " + str(call))
                values_list = expression.extract_literal_items()

            parameters = call.get_argument(0)
            if parameters :
                array = parameters.children[0]
                key = None
                if str(array.get_type()) == "Token.Literal.String":
                    key = array.text[1]

                elif isinstance(array, Identifier):
                    idk =  evaluate_with_context(array, context, evaluation_params= evaluation_params)
                    if len(idk) == 1:
                        key = idk[0]
            if key:
                key_ast_nodes=None
                if isinstance(key, Value):
                    key_ast_nodes = key.ast_nodes
                    key = key.value
                if evaluation_params.with_trace:
                    res_value = key.join([value.value if isinstance(value, Value) else value for value in values_list])
                    res_value = handle_unknown_eval(res_value, evaluation_params)
                    result = Value(res_value)
                    for val in values_list:
                        if isinstance(val, Value):
                            result.ast_nodes.extend(val.ast_nodes)
                    if key_ast_nodes:
                        result.ast_nodes.extend(key_ast_nodes)
                else:
                    result = key.join(values_list)
                    result = handle_unknown_eval(result, evaluation_params)
                return result

    if (
            (isinstance(call, FunctionCall) and call.get_name() == "encodeURI") or
            (isinstance(call, MethodCall) and not hasattr(call, "is_fake_call") and call.get_fullname() == "Object.freeze")
    ):
         return  evaluate_with_context(call.get_argument(0), context= context, evaluation_params=evaluation_params)
    # is_fake_call attribute is used when we have a getter
    # we create a fake MethodCall node which is not part of the ast
    # the following should not be carried out in that case
    if is_method_call(call) and not hasattr(call, "is_fake_call"):
        name = call.get_name()
        if evaluation_params.ast_node_expected or evaluation_params.symbol_expected or evaluation_params.dict_expected:
            # specific case for bind, where we ignore the call `.bind()`
            if name == "bind":
                expression = call.get_expression()
                if not hasattr(expression, 'get_resolution'):
                    return
                resolution = expression.get_resolution()
                if evaluation_params.symbol_expected and isinstance(resolution, Symbol):
                    if evaluation_params.with_trace:
                        return [Value(resolution)]
                    else:
                        return [resolution]
            else:
                pass
        elif name == "join":
            try:
                expression = call.get_expression()
                if isinstance(expression, Identifier):
                    resolution = expression.get_resolution()
                    assigned_expression = resolution.get_assigned_expression()
                    result = join_bracket_items(call, assigned_expression, evaluation_params = evaluation_params)
                    if isinstance(result, Value):
                        result.ast_nodes.append(resolution.parent)
                    return [result]
                else:
                    return [join_bracket_items(call, expression, evaluation_params = evaluation_params)]

            except:
                pass
        elif name == "toLowerCase":
            expression = call.get_expression()
            if isinstance(expression, Identifier):
                strings1 = evaluate_in_block(expression, context=context,
                                            evaluation_params=evaluation_params)
            else:
                strings1 =  evaluate_with_context(expression, context=context, evaluation_params=evaluation_params)
            if evaluation_params.with_trace:
                for string1 in strings1:
                    string1.value = string1.value.lower()
                return strings1
            else:
                return [st.lower() for st in strings1 if isinstance(st, str)]

        # in theory replace and replaceAll are different
        elif name in  ["replace", 'replaceAll']:
            strings = []

            expression = call.get_expression()
            if isinstance(expression, Identifier):

                string1 = evaluate_in_block(expression, context = context, evaluation_params= evaluation_params)
            else:
                string1 =  evaluate_with_context(expression, context=context, evaluation_params=evaluation_params)

            try:
                string_to_replace =  evaluate_with_context(call.get_argument(0), context, evaluation_params= evaluation_params)[0]
                replacing_string =  evaluate_with_context(call.get_argument(1), context, evaluation_params= evaluation_params)[0]
                if evaluation_params.with_trace:
                    string_to_replace_ast_nodes = string_to_replace.ast_nodes
                    string_to_replace = string_to_replace.value
                    replacing_string_ast_nodes = replacing_string.ast_nodes
                    replacing_string = replacing_string.value
                for a_string in string1:
                    if evaluation_params.with_trace:
                        if isinstance(a_string, Value):
                            ast_nodes = a_string.ast_nodes
                            a_string = a_string.value
                            a_string = a_string.replace(string_to_replace, replacing_string)
                            strings.append(Value(a_string,ast_nodes+string_to_replace_ast_nodes+replacing_string_ast_nodes))
                        else:
                            strings.append(Value(a_string.replace(string_to_replace,replacing_string)))
                    else:
                        strings.append(a_string.replace(string_to_replace,replacing_string))

                return handle_unknown_eval(strings, evaluation_params)
            except:
                return handle_unknown_eval([], evaluation_params)
            pass
        elif name == "get":
            expression = call.get_expression()
            if hasattr(expression, 'get_resolution'):
                resol = expression.get_resolution()
                if hasattr(resol, 'assigned_map'):
                    try:
                        eval_param = EvaluationParams()
                        eval_param.max_duration = evaluation_params.max_duration
                        return evaluate_with_context(resol.assigned_map[evaluate_with_context(call.get_argument(0), context=EvaluationContext(), evaluation_params=eval_param)[0]], context=context, evaluation_params=evaluation_params)
                    except:
                        pass
        elif name == 'slice':
            return  evaluate_with_context(call.get_expression(), context=context, evaluation_params=evaluation_params)
        elif name == "concat":
            strings = []

            expression = call.get_expression()
            if isinstance(expression, Identifier):
                string1 = evaluate_in_block(expression, context=context, evaluation_params= evaluation_params)
            else:
                string1 =  evaluate_with_context(expression, context=context, evaluation_params=evaluation_params)
            string1 = remove_duplicates(string1, evaluation_params=evaluation_params)
            strings.append(string1)
            for arg in call.get_arguments():
                string2 =  evaluate_with_context(arg, context, evaluation_params=evaluation_params)
                string2 = remove_duplicates(string2, evaluation_params=evaluation_params)
                if string2 == []:
                    # default -> empty string
                    string2.append("")
                strings.append(string2)
            result = []

            if evaluation_params.with_trace:
                for product in itertools.product(*strings):
                    ast_nodes = []
                    for p in product:
                        if isinstance(p, str):
                            continue
                        ast_nodes.extend(p.ast_nodes)
                    val = "".join(tuple(val if isinstance(val,str) else val.value for val in product))
                    result.append(Value(val,ast_nodes))
            else:
                for product in itertools.product(*strings):
                    result.append("".join(product))

            return handle_unknown_eval(result, evaluation_params)

    resolution = call.get_resolution()
    if isinstance(resolution, Identifier):
        resolution = resolution.get_assigned_expression()
    if not resolution:
        if evaluation_params.url_expected and len(call.get_arguments())>0 and not isinstance(call.parent, Return):
            # we try to evaluate the first arg
            evals =  evaluate_with_context(call.get_argument(0), context, evaluation_params = evaluation_params)
            valid_evals = []
            for ev in evals:
                if hasattr(ev, "value") and "/" in ev.value:
                    valid_evals.append(ev)

            return handle_unknown_eval(valid_evals, evaluation_params)

        return handle_unknown_eval([], evaluation_params)

    if not hasattr(resolution, 'get_ast') and evaluation_params.ast_node_expected:
        if evaluation_params.with_trace:
            return [Value(resolution)]
        else:
            return [resolution]
    if isinstance(resolution, ExportedVariable):
        return  evaluate_with_context(resolution, context=context.copy(), evaluation_params=evaluation_params)
    if not hasattr(resolution, 'get_ast'):
        return []
    method = resolution.get_ast()

    # to do, there may be several returns
    if not method or not hasattr(method, 'get_returns'):
        return handle_unknown_eval([], evaluation_params)
    returns = method.get_returns()
    if not returns:
        if evaluation_params.symbol_expected and isinstance(resolution, Symbol):
            if evaluation_params.with_trace:
                return [Value(resolution)]
            else:
                return [resolution]
        return handle_unknown_eval([], evaluation_params)
    _return = returns[0]

    if isinstance(_return, Return):
        evaluation_params.from_call_stack.append(call)
        results =  evaluate_with_context(_return.get_expression(), context, evaluation_params)
        if is_unknown_evaluation(results, evaluation_params):
            results = evaluate_in_block(_return.get_expression(), context, evaluation_params)
        if len(evaluation_params.from_call_stack)>0:
            evaluation_params.from_call_stack = evaluation_params.from_call_stack[:-1]
    # direct output of arrow method : m = () => output
    else:
        evaluation_params.from_call_stack.append(call)
        results =  evaluate_with_context(_return, context, evaluation_params)
        evaluation_params.from_call_stack = evaluation_params.from_call_stack[:-1]
    if evaluation_params.with_trace:
        results = add_ast_node_to_values(results, _return,evaluation_params)

    if is_unknown_evaluation(results, evaluation_params):
        arg = call.get_argument(0)
        if arg:
            identifier = arg.get_identifier()
            if identifier and identifier.get_name().lower() in ['url', 'uri']:
                results =  evaluate_with_context(identifier, context, evaluation_params)
            else:
                results_tmp =  evaluate_with_context(identifier, context, evaluation_params)
                if any(["/" in val.value for val in results_tmp if hasattr(val, 'value')]):
                    results = results_tmp

    if is_unknown_evaluation(results, evaluation_params) and evaluation_params.url_expected:
        if (any([uri in call.get_name().lower() for uri in ['uri', 'url']])):
            results = evaluate_first_arg(call, context, evaluation_params)
    return results

def evaluate_first_arg(call, context=None, evaluation_params=None):
    arg = call.get_argument(0)
    if not isinstance(arg, Argument) or len(arg.children)<1:
        return handle_unknown_eval([], evaluation_params)
    first_child = arg.children[0]
    if first_child == '...':
        if len(arg.children)<2:
            return handle_unknown_eval([], evaluation_params)
        first_child = arg.children[1]
        if isinstance(first_child, FunctionCall) and first_child.get_name()=='coerceArray':
            first_child = first_child.get_argument(0)

    return  evaluate_with_context(first_child, context, evaluation_params)


def evaluate_in_block(identifier, context=None, evaluation_params=None):
    """
    Evaluates an identifier within a block of statements
    """
    if not evaluation_params:
        evaluation_params = EvaluationParams()

    try:
        resolution = identifier.get_resolution()
        if not resolution:
            return []

        # we do not want to handle block when evaluating ast or symbol
        if isinstance(resolution, ExportedVariable) or not evaluation_params.evaluate_in_block:
            return  evaluate_with_context(resolution.get_ast(), context, evaluation_params)



        # check for updated values along the block
        # @todo: start from resolution statement
        enclosing_block = resolution.parent.parent  # TODO: -> get_enclosing_block
        resolved_identifier = resolution


        limit_line = identifier.get_begin_line()
        limit_column = identifier.get_begin_column()
        try:
            parent = identifier.parent
            while True:
                if parent.get_begin_line()< enclosing_block.get_begin_line():
                    break
                if isinstance(parent, (If, SwitchCase)):
                    limit_line = parent.get_begin_line()
                    limit_column = parent.get_begin_column()
                    break
                parent = parent.parent
        except AttributeError:
            pass


        for sub_node in enclosing_block.get_sub_nodes():
            if sub_node.get_begin_line()<resolved_identifier.get_begin_line():
                continue
            if sub_node.get_begin_line()> limit_line:
                break
            elif sub_node.get_begin_line() == limit_line and sub_node.get_begin_column()>= limit_column:
                break
            if isinstance(sub_node, Assignment):
                assig = sub_node
                if assig.get_begin_line() > identifier.get_begin_line():
                    break
                left_identifier = assig.get_left_expression()
                if not isinstance(left_identifier, Identifier):
                    continue
                name = left_identifier.get_name()
                if name == identifier.get_name():
                    if identifier == left_identifier:
                        break
                    right_expr = assig.get_right_expression()
                    if isinstance(right_expr, MethodCall) and (right_expr.get_expression() == identifier or
                            right_expr.get_root_expression()==identifier):
                        break

                    resolved_identifier = left_identifier
            elif isinstance(sub_node, MethodCall):
                expr = sub_node.get_expression()
                if not isinstance(expr, Identifier) or expr.get_name() != identifier.get_name():
                    continue
                values =  evaluate_with_context(sub_node, context, evaluation_params)
                if evaluation_params.with_trace:
                    add_ast_node_to_values(values, sub_node, evaluation_params)
                return values
        results =  evaluate_with_context(resolved_identifier, context, evaluation_params)

        # we check for switches
        for child in enclosing_block.get_children():
            if child.get_begin_line()>limit_line:
                break
            elif child.get_begin_line() == limit_line and limit_column:
                break
            if isinstance(child, (If, SwitchCase)):
                extra_values = evaluate_bifurcation_block(identifier, child, context=context, evaluation_params=evaluation_params)
                if extra_values:
                    results.extend(extra_values)
        return results

    except AttributeError:
        pass

    return []

def add_ast_node_to_values(values, ast_node, evaluation_params = None):
    if evaluation_params is None or not evaluation_params.with_trace:
        return values
    new_values = []
    for value in values:
        if isinstance(value, Value):
            new_values.append(value)
            if not evaluation_params or (value.value != evaluation_params.charForUnknown):
                value.ast_nodes.append(ast_node)
        elif isinstance(value, str):
            if not value or (evaluation_params is not None and value == evaluation_params.charForUnknown):
                new_values.append(Value(value))
            else:
                new_values.append(Value(value, ast_node))
        # if we have a dict, we should return dict
        elif isinstance(value, dict):
            new_values.append(value)
    return new_values




def evaluate_curly_bracket(bracket, context=None, evaluation_params=None):
    """Return a TypeScript map as a python dictionary
    
    Limitations
    -----------
    Currently we return the dictionary with evaluated values 
    inside the dictionary, however we don't treat multiple-valued
    results. This also limits flexibility on the analysis
    of the returned object (missing semantic info if evaluation is empty)
    
    Nice to have
    ------------
    In the future we might delegate the evaluation of
    expressions inside the dictionary to the returned object, 
    by returning an enhanced dictionary:
        
        raw_result =  evaluate2(bracket)
        digested = raw_result.evaluate()
        
    Notes
    -----
    

    Notes
    -----
    (1) For the large majority of cases the use of quotes
    in object keys is optional (style choice):
        https://stackoverflow.com/questions/4348478/
    
    
    (2) Below I experiment (AZU) with a different idea for
    running through tokens, not necessarily optimal.
    """
    if not evaluation_params:
        evaluation_params = EvaluationParams()

    def nexttok(tokens):
        """Helper function to get next token in a list 
        and encapsulate error handling"""
        nonlocal i
        try:
            return tokens[i + 1]
        except IndexError:
            pass

    def prevtok(tokens):
        """Helper function to get previous token in a list 
        and encapsulate error handling"""
        nonlocal i
        try:
            return tokens[i - 1]
        except IndexError:
            pass

    result = OrderedDict()
    tokens = list(bracket.get_children())  # remove whitespaces & comments
    
    for i, token in enumerate(tokens):
        if token == ':':
            key = prevtok(tokens).text.strip("'")  # clean quotes
            key = key.strip('"')  # clean quotes
            values =  evaluate_with_context(nexttok(tokens), context, evaluation_params)
            try:
                # we take the first one
                value = values[0]
            except IndexError:
                value = None

            if (key is not None) and (value is not None):
                result[key] = value
    
    return [result]

def evaluate_bifurcation_block(identifier: Identifier, if_or_case_block, last_evaluated_block = None, context=None, evaluation_params=None):

    if not hasattr(evaluation_params, 'bifurcation_number'):
        evaluation_params_new = evaluation_params.copy()
        evaluation_params_new.bifurcation_number = 1
    else:
        evaluation_params_new = evaluation_params
        evaluation_params_new.bifurcation_number += 1
        if evaluation_params_new.bifurcation_number == 100:
            log.debug("Evaluation aborted: Too many bifurcations during evaluation.")
            return
        elif evaluation_params_new.bifurcation_number > 100:
            return

    evaluation = evaluate_bifurcation_block_sub(identifier.get_name(), if_or_case_block, last_evaluated_block, context, evaluation_params=evaluation_params_new)
    if evaluation_params_new.bifurcation_number > 100:
        return
    else:
        return evaluation

def evaluate_bifurcation_block_sub(variable_name, if_or_case_block, last_evaluated_block = None, context=None, evaluation_params=None):

    if not last_evaluated_block:
        seen_last_evaluated_block = True
    else:
        seen_last_evaluated_block = False
    new_values = []
    if isinstance(if_or_case_block, If):
        if not hasattr(evaluation_params, 'if_stack'):
            evaluation_params.if_stack = [if_or_case_block]
        elif if_or_case_block in evaluation_params.if_stack:
            return []
        for case in if_or_case_block.get_cases():
            if case == last_evaluated_block:
                seen_last_evaluated_block = True
                continue
            if seen_last_evaluated_block:
                current_new_values = []
                for statement in case.get_statements():
                    if not isinstance(statement, Assignment):
                        continue

                    left = statement.get_left_expression()
                    if left.get_name() == variable_name:

                        if statement.get_operator() == '=':
                            # overwrite with latest value
                            current_new_values =  evaluate_with_context(left, context, evaluation_params)
                        else:
                            current_new_values.extend(evaluate_with_context(left, context, evaluation_params))
                new_values.extend(current_new_values)
        if new_values:
            return new_values


    elif isinstance(if_or_case_block, SwitchCase):
        if not hasattr(evaluation_params, 'switch_stack'):
            evaluation_params.switch_stack = [if_or_case_block]
        elif if_or_case_block in evaluation_params.switch_stack:
            return []

        new_values = []
        for case in if_or_case_block.get_cases():
            new_values_loc = []
            if case == last_evaluated_block:
                seen_last_evaluated_block = True
                continue

            if seen_last_evaluated_block:

                for statement in case.get_statements():
                    if not isinstance(statement, Assignment):
                        continue

                    left = statement.get_left_expression()
                    if left.get_name() == variable_name and statement.get_operator()=='=':
                        # overwrite with latest value
                        new_values_loc =  evaluate_with_context(left, context, evaluation_params)
                    elif left.get_name() == variable_name and statement.get_operator()=='+=':

                        nb_values = 0
                        # overwrite with latest value
                        left_values =  evaluate_with_context(left, context, evaluation_params)
                        new_values_loc.extend(left_values)
            new_values.extend(new_values_loc)


        return new_values


def get_parameter_value_from_call(parameter, evaluation_params):
    """see tests test_function_call_using_param_... from test_evaluation_wtih_trace to see use case for this function"""
    try:
        current_callable = parameter.parent
        while not (is_function(current_callable) or is_method(current_callable)):
            current_callable = current_callable.parent
    except:
        return None

    for calling_ast in evaluation_params.from_call_stack[::-1]:
        if calling_ast in current_callable.get_calling_asts():
            return calling_ast
    return None

def get_identifiers(expression):
    """
    Get the identifiers an expression depends on
    """
    result = []
    
    if hasattr(expression, 'get_resolution'):
        resolution = expression.get_resolution()
        if resolution:
            result.append(expression.get_resolution())
        
    for node in expression.get_sub_nodes():
        result += get_identifiers(node)

    return result
    
def evaluate_list(bracket, context=None, evaluation_params=None):
    values = []
    for item in bracket.get_items():
        evls =  evaluate_with_context(item, context, evaluation_params)
        if not is_unknown_evaluation(evls, evaluation_params):
            values.extend(evls)

    return values

def evaluate_symbol(ast_node, evaluation_params:EvaluationParams):
    if not evaluation_params.symbol_expected:
        return

    symbol = None
    if hasattr(ast_node, 'symbol') and isinstance(ast_node.symbol, Symbol) and not isinstance(ast_node.symbol, SymbolNotSavedInKb):
        symbol = ast_node.symbol
    elif hasattr(ast_node, 'get_resolution'):
        resol = ast_node.get_resolution()
        if isinstance(resol, Symbol) and not isinstance(resol, symbols.Field) and not isinstance(resol, SymbolNotSavedInKb):
            symbol = resol
    if symbol:
        if evaluation_params.with_trace:
            return [Value(symbol)]
        else:
            return [symbol]
    return []

def evaluate_field(field_symbol, context, evaluation_params):
    results = []
    if hasattr(field_symbol.get_ast().get_identifier(), 'get_resolution') and field_symbol.get_ast().get_identifier().get_resolution():
        return evaluate_with_context(field_symbol.get_ast().get_identifier().get_resolution(), context, evaluation_params)
    if isinstance(field_symbol.get_ast(), ConstructorField):
        return evaluate_from_parameter(field_symbol.get_ast(), context, evaluation_params)
    evls = evaluate_with_context(field_symbol.get_ast().get_value(), context, evaluation_params)
    if not is_unknown_evaluation(evls, evaluation_params):
        for evl in evls:
            if evaluation_params.with_trace:
                if evl.value != '':
                    results.append(evl)
            else:
                if evl != '':
                    results.append(evl)
    if hasattr(field_symbol, 'possible_values'):
        for v in field_symbol.possible_values:
            if v in context.target_stack:
                continue
            try:
                if v.parent.parent.parent.get_name()=='constructor':
                    results = []
            except AttributeError:
                pass
        for v in field_symbol.possible_values:
            if v in context.target_stack:
                continue
            evls = evaluate_with_context(v, context, evaluation_params)
            if not is_unknown_evaluation(evls, evaluation_params):
                results.extend(evls)

    return results

def evaluate_identifier(identifier, context=None, evaluation_params=None):
    if not evaluation_params:
        evaluation_params = EvaluationParams()

    if isinstance(identifier.parent, ObjectCurlyBracket) and identifier in identifier.parent.get_key_identifiers():
        if not identifier.parent.get_dictionary()[identifier.get_name()] == identifier:
            evals = evaluate_with_context(identifier.parent.get_dictionary()[identifier.get_name()], context, evaluation_params)
            if not is_unknown_evaluation(evals, evaluation_params):
                return evals

    if evaluation_params.ast_node_expected and isinstance(identifier.get_resolution(), (symbols.Class, symbols.Method, symbols.Function)):
        return  evaluate_with_context(identifier.get_resolution().get_ast(), context, evaluation_params)

    if isinstance(identifier.get_resolution(), symbols.SourceFile) and evaluation_params.dict_expected:
        to_return = OrderedDict()
        for name, symbs in identifier.get_resolution().symbols.items():
            try:
                symb = symbs[0]
            except IndexError:
                continue
            if not hasattr(symb, 'get_ast'):
                continue
            if not hasattr(symb.get_ast(), 'is_exported') or not symb.get_ast().is_exported:
                continue
            to_return[name] = symb.get_ast()
        if to_return:
            return [to_return]


    if hasattr(identifier, 'possible_map_values'):
        evals = []
        for key_name in evaluation_params.dict_keys:
            if key_name in identifier.possible_map_values.keys():
                if not key_name in evaluation_params.dict_keys_found:
                    evaluation_params.dict_keys_found.add(key_name)
                for val in identifier.possible_map_values[key_name]:
                    extra_evals =  evaluate_with_context(val, context, evaluation_params)
                    if extra_evals:
                        evals.extend(extra_evals)
        if not is_unknown_evaluation(evals, evaluation_params):
            return evals

    if hasattr(identifier,"is_injected"):
        if identifier.get_resolution():
            return  evaluate_with_context(identifier.get_resolution(), context, evaluation_params)
    values = []
    if hasattr(identifier, "possible_values"):
        blanck_default_value = []
        for val in identifier.possible_values:
            if identifier in get_identifiers(val):
                # special case of x = ... + x
                # assignement where the variable depends on itself
                # generate a false unknown value so not really usefull
                # I prefer skipping
                continue
            values_evaluated =  evaluate_with_context(val, context, evaluation_params)
            values_evaluated = add_ast_node_to_values(values_evaluated, val, evaluation_params)
            if isinstance(val, Token) and val.text in ['""', "''"]:
                blanck_default_value = values_evaluated
            else:
                values.extend(values_evaluated)
        if values:
            return values

    parent = identifier.parent

    if isinstance(parent, Assignment):

        right = parent.get_right_expression()
        if identifier == right:
            if evaluation_params.ast_node_expected:
                if identifier.get_resolution():
                    return  evaluate_with_context(identifier.get_resolution(), context, evaluation_params)
            evls = evaluate_in_block(right, context, evaluation_params)
            if evls:
                return evls
        else:
            ev =   evaluate_with_context(right, context, evaluation_params)
            if isinstance(parent.parent, ObjectCurlyBracket):
                for e in ev:
                    if isinstance(e, Value):
                        e.is_default = True
            values.extend(ev)
            if evaluation_params.with_trace:
                values = add_ast_node_to_values(values, parent, evaluation_params)
            # consider ambiguity of values because
            # of if-then-else blocks
            try:
                enclosing_block = parent.parent
                if isinstance(enclosing_block, CurlyBracket):
                    enclosing_block = enclosing_block.parent
            except AttributeError:
                pass
            else:
                if isinstance(enclosing_block, IfThenElseBlock):
                    # needed to avoid recursion error:
                    # each (recursive) iteration it will search
                    # for the next block bringing new_values!
                    if_node = enclosing_block.parent
                    new_values = evaluate_bifurcation_block(identifier,if_node, enclosing_block, context, evaluation_params)
                    if new_values:
                        values.extend(new_values)

                elif isinstance(enclosing_block, Case):
                    # needed to avoid recursion error:
                    # each (recursive) iteration it will search
                    # for the next block bringing new_values!
                    seen_current_enclosing_block = False

                    switch_node = enclosing_block.parent.parent
                    new_values = evaluate_bifurcation_block(identifier,switch_node, enclosing_block, context, evaluation_params)
                    if new_values:
                        values.extend(new_values)


            operator = parent.get_operator()
            if operator == '+=':
                x = evaluate_in_block(identifier, context, evaluation_params)

                new_values = []
                if len(values)>100:
                    log.warning('Problem: to many values to combine')
                    return clean_evaluation_results([], evaluation_params)
                for product in itertools.product(x, values):
                    value = ""
                    ast_nodes=[]
                    for p in product:
                        if isinstance(p, str):
                            value += p
                        elif hasattr(p, 'value'):
                            value += p.value
                            ast_nodes.extend(p.ast_nodes)
                        else:
                            continue
                    if evaluation_params.with_trace:
                        value = Value(value, ast_nodes)

                    new_values.append(value)
                return new_values
            elif operator in ['||=', '&&=', '??=']:
                x = evaluate_in_block(identifier, context, evaluation_params)
                is_falsy=True
                for val in x:
                    if isinstance(val, Value) and val.value != '':
                        is_falsy = False
                    if isinstance(val, str) and val != '':
                        is_falsy = False

                if is_unknown_evaluation(x, evaluation_params):
                    is_falsy = True

                new_values = []
                if operator == '||=':
                    if is_falsy:
                        new_values = values
                    else:
                        new_values = x
                elif operator == '&&=':
                    if is_falsy:
                        new_values = x
                    else:
                        new_values = values
                elif operator == '??=':
                    if is_unknown_evaluation(x, evaluation_params):
                        new_values = values
                    else:
                        new_values = x
                return new_values

            if isinstance(parent.parent, ObjectCurlyBracket):
                eval = evaluate_identifier_in_object_destructuring(identifier, parent.parent, context= context, evaluation_params=evaluation_params)
                if eval:
                    values.extend(eval)

            return values
        
    elif isinstance(parent, Export) and not parent.is_default_export:
        expression = parent.get_value()
        return  evaluate_with_context(expression, context, evaluation_params)

    elif isinstance(parent, VariableDeclaration) or \
         (isinstance(parent, CurlyBracket) and isinstance(parent.parent, VariableDeclaration)) or \
         (isinstance(parent, Bracket) and isinstance(parent.parent, VariableDeclaration)):
    
        if isinstance(parent, CurlyBracket) or isinstance(parent, Bracket):
            parent = parent.parent

        if not identifier in parent.get_variables():
            # then it's the right_hand_side
            resolution = identifier.get_resolution()
            if resolution and not resolution == identifier:
                return  evaluate_with_context(identifier.get_resolution(), context, evaluation_params=evaluation_params)
            return []

        values =  evaluate_with_context(identifier.get_assigned_expression(), context, evaluation_params)
        if evaluation_params.with_trace:
            values = add_ast_node_to_values(values, parent, evaluation_params)
        if values:
            return values
        
    elif isinstance(parent, Parenthesis):
        block = parent.parent
        if isinstance(block, (MethodCall, FunctionCall, Instantiation)):
            return evaluate_in_block(identifier, context, evaluation_params)

    elif isinstance(parent, Parameter) and parent.get_identifier() == identifier:
        # we are evaluating a functionCall so we know where the value comes from
        return evaluate_from_parameter(parent, context, evaluation_params)
    elif isinstance(parent, ObjectCurlyBracket) and identifier in parent.get_key_identifiers() and isinstance(parent.parent, Parameter):
        return evaluate_identifier_in_object_destructuring(identifier, identifier.parent, context= context, evaluation_params=evaluation_params)

    # StringTemplate, BinaryOperations, ...
    resolution = identifier.get_resolution()
    if resolution and not identifier == resolution:
        evaluations = evaluate_with_context(resolution, context, evaluation_params)
        if hasattr(resolution, 'parent') and isinstance(resolution.parent, Parameter):
            eval_in_blocks = handle_changes_in_block(evaluations, parameter= resolution.parent, target=identifier, context=context, evaluation_params=evaluation_params)
            if is_unknown_evaluation(eval_in_blocks, evaluation_params):
                return evaluations
            else:
                return eval_in_blocks

        return evaluations

    values = []
    if hasattr(identifier, "possible_values"):
        blanck_default_value = []
        for val in identifier.possible_values:
            if identifier in get_identifiers(val):
                # special case of x = ... + x
                # assignement where the variable depends on itself
                # generate a false unknown value so not really usefull
                # I prefer skipping
                continue

            values_evaluated = evaluate_with_context(val, context, evaluation_params)
            values_evaluated = add_ast_node_to_values(values_evaluated, val, evaluation_params)
            if isinstance(val, Token) and val.text in ['""', "''"]:
                blanck_default_value = values_evaluated
            else:
                values.extend(values_evaluated)
        if values:
            return values

def handle_changes_in_block(evaluations, parameter: Parameter, target: Identifier, context, evaluation_params):
    callable = parameter.get_callable()
    if not callable:
        return
    enclosing_block = None
    for child in callable.children:
        if isinstance(child, CurlyBracket):
            enclosing_block = child
            break
    if not enclosing_block:
        return
    resolved_identifier = None
    for sub_node in get_interesting_sub_nodes(enclosing_block, target):
        if isinstance(sub_node, Assignment):
            if sub_node.get_end_line() >= target.get_begin_line():
                break
            left_identifier = sub_node.get_left_expression()
            if not isinstance(left_identifier, Identifier):
                continue
            name = left_identifier.get_name()
            if name == target.get_name():
                if target == left_identifier:
                    break
                right_expr = sub_node.get_right_expression()
                if isinstance(right_expr, MethodCall) and (right_expr.get_expression() == target or
                                                           right_expr.get_root_expression() == target):
                    break

                resolved_identifier = left_identifier
        elif isinstance(sub_node, MethodCall):
            expr = sub_node.get_expression()
            if not isinstance(expr, Identifier) or expr.get_name() != target.get_name():
                continue
            values =  evaluate_with_context(sub_node, context, evaluation_params)
            if evaluation_params.with_trace:
                add_ast_node_to_values(values, sub_node, evaluation_params)
            return values
    if resolved_identifier:
        return  evaluate_with_context(resolved_identifier, context, evaluation_params)



def get_interesting_sub_nodes(enclosing_block, identifier):

    interesting_nodes = [MethodCall, Assignment]
    if isinstance(enclosing_block, list):
        all_nodes = enclosing_block
    elif hasattr(enclosing_block, 'get_sub_nodes'):
        all_nodes = enclosing_block.get_sub_nodes()

    for sub_node in all_nodes:
        if sub_node.get_begin_line() > identifier.get_begin_line():
            break
        elif sub_node.get_begin_line() == identifier.get_begin_line() and sub_node.get_begin_column()>= identifier.get_begin_column():
            break
        if any([isinstance(sub_node, _type) for _type in interesting_nodes]):
            yield sub_node
        elif isinstance(sub_node, If):
            for case in sub_node.get_cases():
                yield from case.get_statements()


def evaluate_from_parameter(parameter:Parameter, context, evaluation_params):
    identifier = parameter.get_identifier()
    expression = identifier.get_assigned_expression()
    default_values = []
    results = []
    if expression and not identifier == expression:
        default_values = evaluate_with_context(expression, context, evaluation_params)
        if default_values and evaluation_params.with_trace:
            add_ast_node_to_values(default_values, parameter, evaluation_params)
    if default_values:
        for def_value in default_values:
            val = copy(def_value)
            results.append(val)
    calling_ast = get_parameter_value_from_call(parameter, evaluation_params)
    if calling_ast:
        if parameter.get_position() is None:
            return []
        return evaluate_with_context(calling_ast.get_argument(parameter.get_position()), context, evaluation_params)


    function = parameter.get_function_or_method_ast()
    if not function:
        log.debug("Warning: no function or method found for parameter: {} ".format(parameter))
        return []

    callers = function.get_calling_asts()
    if callers and parameter in function.get_parameters():
        position = function.get_parameters().index(parameter)

        for caller in callers:
            if hasattr(caller, 'is_function_call_part'):
                try:
                    param = caller.get_parameters()[position]
                except:
                    param = None
                if param:
                    if evaluation_params.with_trace:
                        _results = param.evaluate_with_trace(charForUnknown=evaluation_params.charForUnknown)
                        argument_values = [result if type(result) is str else Value(result.value, result.ast_nodes) for
                                           result in _results]
                        add_ast_node_to_values(argument_values, caller, evaluation_params)
                        add_ast_node_to_values(argument_values, parameter, evaluation_params)
                    else:
                        _results = param.evaluate(charForUnknown=evaluation_params.charForUnknown)
                        argument_values = [result if type(result) is str else Value(result.value, result.ast_nodes) for
                                           result in _results]
                    if evaluation_params.track_real_caller:
                        for value in argument_values:
                            if hasattr(value, "add_call_passing_urls"):
                                value.add_call_passing_urls(caller)
                    if argument_values:
                        results.extend(argument_values)
                continue

            if not hasattr(caller, 'get_enclosing_callable_ast') or caller.get_enclosing_callable_ast() == function:
                continue

            try:
                argument = caller.get_argument(position)
            except:
                argument = None
            if not argument:

                continue

            child = argument.children[0]
            # since we can have many caller we should take a copy of the context

            if isinstance(child, ObjectCurlyBracket) and not (
                    evaluation_params.dict_expected or evaluation_params.dict_keys):
                try:
                    child = child.get_dictionary()[identifier.get_name()]
                except:
                    pass
            argument_values = evaluate_with_context(child, context, evaluation_params)
            if evaluation_params.with_trace:
                add_ast_node_to_values(argument_values, caller, evaluation_params)
                add_ast_node_to_values(argument_values, parameter, evaluation_params)
            if evaluation_params.track_real_caller:
                for value in argument_values:
                    if hasattr(value, "add_call_passing_urls"):
                        value.add_call_passing_urls(caller)

            results.extend(argument_values)

    if results:
        return results

    if default_values:
        return default_values
    return []

def evaluate_identifier_in_object_destructuring(identifier, parent_object_c, context=None, evaluation_params=None):
    """
    :type identifier: Identifier
    :type parent_object_c:ObjectCurlyBracket
    """
    if not evaluation_params:
        evaluation_params = EvaluationParams()

    if not identifier in parent_object_c.get_key_identifiers():
        return

    if not isinstance(parent_object_c.parent, Parameter):
        return

    callable = parent_object_c.parent
    while not isinstance(callable, (Function, Method)):
        callable = callable.parent
        if not callable:
            return []

    i_param = 0
    for i_param, param in enumerate(callable.get_parameters()):
        if param == parent_object_c.parent:
            break
    evaluations = []
    for caller in callable.get_calling_asts():
        try:
            eval = evaluate_map(caller.get_argument(i_param), identifier.get_name(),  context, evaluation_params=evaluation_params)
        except:
            eval = []

        if evaluation_params.track_real_caller:
            for value in eval:
                value.add_call_passing_urls(caller)
        if evaluation_params.with_trace:
            for value in eval:
                value.ast_nodes.append(caller)
        evaluations.extend(eval)

    return evaluations

def evaluate_binary_or(operation, context=None, evaluation_params=None):
    if not evaluation_params:
        evaluation_params = EvaluationParams()

    left = operation.get_left_expression()


    if isinstance(left, Token) and str(left.type) == 'Token.Literal.String':
        return  evaluate_with_context(left, context=context, evaluation_params=evaluation_params)
    elif isinstance(left, Identifier):
        resol = left.get_resolution()
        if isinstance(resol, Identifier):
            assigned = resol.get_assigned_expression()
            if isinstance(assigned, Token) and str(assigned.type) == 'Token.Literal.String':
                return  evaluate_with_context(assigned, context=context, evaluation_params=evaluation_params)

    left_evals =  evaluate_with_context(left, context=context, evaluation_params=evaluation_params)
    right = operation.get_right_expression()
    right_evals =  evaluate_with_context(right, context=context, evaluation_params=evaluation_params)
    for ev in right_evals:
        if isinstance(ev, Value):
            ev.is_default = True

    return left_evals + right_evals

def count_max_words_in_evls(evls):
    max_words = 0
    for evl in evls:
        if isinstance(evl, Value):
            val = evl.value
        else:
            val = evl

        n = len(val.split())
        if n > max_words:
            max_words = n

    return max_words


def evaluate_binary_operation(operation, context=None, evaluation_params=None):
    """Evaluate binary operations.

    Limitations
    -----------
        Currently we only handle sum ("+") operator
    """
    if not evaluation_params:
        evaluation_params = EvaluationParams()

    operator = operation.get_operator()
    if operator in ['||', "??"]:
        return evaluate_binary_or(operation, context=context, evaluation_params=evaluation_params)
    if not operator == '+' or evaluation_params.ast_node_expected:
        return []

    left = operation.get_left_expression()

    left_evals =  evaluate_with_context(left, context=context, evaluation_params=evaluation_params)
    right = operation.get_right_expression()
    if evaluation_params.query_expected and not isinstance(right, (BinaryOperation, Token)):
        if len([sta for sta in context.target_stack if isinstance(sta, BinaryOperation)]) > 20 or count_max_words_in_evls(left_evals) > 100:
            log.warning('Too long an complex query. Shortening the evaluation')
            return left_evals
    right_evals =  evaluate_with_context(right, context=context, evaluation_params=evaluation_params)
    if len(right_evals)>10: # we remove the blanck evals from left_evals
        new_left_evals = []
        for leval in left_evals:
            if isinstance(leval, Value):
                if leval.value and leval.value.replace(' ', ''):
                    new_left_evals.append(leval)
            elif isinstance(leval, str):
                if leval and leval.replace(' ', ''):
                    new_left_evals.append(leval)
        if len(new_left_evals) != len(left_evals) and len(new_left_evals)>0:
            log.debug('During evaluation, too many combinations are found in concatenation, blanck values removed')
            left_evals = new_left_evals



    if len(right_evals)>200:
        log.debug('Too many evaluation values, some values will be omitted')
        right_evals = right_evals[:200]
    result = []
    evaluations = [right_evals, left_evals]
    if not all(evaluations) and any(evaluations):
        for evaluation in evaluations:
            if not evaluation:
                if evaluation_params.charForUnknown == None:
                    evaluation.append('')
                else:
                    evaluation.append(evaluation_params.charForUnknown)
    nb_values = 0
    for r_eval in right_evals:
        if nb_values > 500:
            break
        for l_eval in left_evals:
            #if not values_coming_from_same_branch(r_eval, l_eval):
            #    continue
            if (not r_eval == None and not l_eval == None
               and not( isinstance(r_eval, Value) and isinstance(l_eval, Value) and r_eval.value == l_eval.value and l_eval.ast_nodes and l_eval.ast_nodes == r_eval.ast_nodes  # this condition is added for some complicated concatenation with split see test_from_utina
                    )):
                value = Value.concat(l_eval, r_eval)
                if value:
                    nb_values += 1
                    if nb_values > 500:
                        break
                    result.append(value)

    return result


def evaluate_ternary_operation(operation, context=None, evaluation_params=None):
    if not evaluation_params:
        evaluation_params = EvaluationParams()

    result = []

    first =  evaluate_with_context(operation.get_first_value(), context, evaluation_params)

    if not is_unknown_evaluation(first, evaluation_params= evaluation_params):
        result.extend(first)


    # we check if we are sure that the condition is true
    cond = operation.get_condition()
    if isinstance(cond, Token) and str(cond.type) == 'Token.Literal.String':
        return result
    elif isinstance(cond, Identifier):
        resol = cond.get_resolution()
        if isinstance(resol, Identifier):
            assigned = resol.get_assigned_expression()
            if isinstance(assigned, Token) and str(assigned.type) == 'Token.Literal.String':
                return result

    second =  evaluate_with_context(operation.get_second_value(), context, evaluation_params)

    if not is_unknown_evaluation(second, evaluation_params= evaluation_params):
        for v in second:
            if not v in result:
                result.append(v)

    return result


def get_root_declaration(node, module):
    """
This method is deprecated. The evaluate with EvaluationParams(ast_node_expected=True)  should be used instead.
    """
    try:
        for evl in evaluate(node, evaluation_params=EvaluationParams(ast_node_expected=True)):

            return evl, get_module_from_node(evl)

        return None, None
    except:
        log.debug("Warning ! Could not get root declaration for node " + str(node) + " in file " + module.get_fullname())
        return None, None


def evaluate_key_values_for_objectcurlybracket(ast):
    to_return = []
    id = None
    stream = ast.get_children()
    key = None
    tok = next(stream)  # curly bra
    tok = next(stream)
    if isinstance(tok, Identifier):
        key = tok.get_name()
    elif isinstance(tok, Assignment):
        key = tok.get_left_expression().get_name()
    elif isinstance(tok, Bracket):
        evls = evaluate(tok.children[1])
        if evls:
            key = evls[0]

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
                    evls = evaluate(tok.children[1])
                    if evls:
                        key = evls[0]
            elif tok == ':':
                tok = next(stream)
                if not key:
                    break
                to_return.append((key, tok))
                key = None

        except StopIteration:
            break
    return to_return
