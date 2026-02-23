from typescript_dependencies.typescript_parser.parser import Argument, MemberAccess, Identifier, Assignment, IfTernary, BinaryOperation, \
    ArrayAccess, Parameter, Instantiation, MethodCall, ObjectCurlyBracket, ArrowExpression, VariableDeclaration, Type, \
    WithParameters, ConstructorField, Class, FunctionCall, Function
import typescript_dependencies.symbols as symbols
from cast.analysers import log

class ResolutionParams:

    def __init__(self, heuristic=None, imported_names=None, resolution_interpreter=None, initial_target=None, save_resolution=False):
        self.heuristic = heuristic
        if not imported_names:
            self.imported_names = []
        else:
            self.imported_names = imported_names
        self.initial_target = initial_target
        self.resolution_interpreter = resolution_interpreter
        self.save_resolution = save_resolution

class ResolutionState:

    def __init__(self):
        self.seen_targets = []
        self.destructuring_attribute_name = None
        self.results = []

def save_resolution_and_caller(call_ast, resol, resolution_params):
    if not resolution_params.save_resolution:
        return
    if resol in call_ast._resolutions:
        return
    call_ast._resolutions.append(resol)
    if hasattr(resol, 'add_caller'):
        resol.add_caller(call_ast)
    if hasattr(resol, 'get_ast') and hasattr(resol.get_ast(), 'add_caller'):
        resol.get_ast().add_caller(call_ast)


def get_class_or_object_from_ast(ast):
    if not hasattr(ast, 'parent'):
        return
    parent = ast.parent
    count = 0
    while True:
        if isinstance(parent, Class):
            return parent.symbol
        elif isinstance(parent, ObjectCurlyBracket):
            return parent
        if not hasattr(parent, 'parent'):
            return
        parent = parent.parent
        count += 1
        if count > 200:
            return


def get_class_from_ast(ast):
    if not hasattr(ast, 'parent'):
        return
    parent = ast.parent
    count = 0
    while True:
        if isinstance(parent, Class):
            return parent.symbol
        if not hasattr(parent, 'parent'):
            return
        parent = parent.parent
        count += 1
        if count > 200:
            return

def resolves_to_callable(m_c):
    for resol in m_c.get_resolutions():
        if hasattr(resol, 'get_parent_symbol') and isinstance(resol.get_parent_symbol(), symbols.Class):
            return True
        if isinstance(resol, symbols.Function):
            return True

    return False

def intermediate_call_resolves_to_function(resolution, resolution_state):
    i = 0

    for intermediate_target in resolution_state.seen_targets[::-1]:
        if i > 5:
            break
        i+=1
        if isinstance(intermediate_target, (FunctionCall, MethodCall)) and hasattr(intermediate_target, 'get_resolutions') and resolution in intermediate_target.get_resolutions():
            return True

    return False

def resolve_recursively(target, resolution_params:ResolutionParams=None, resolution_state:ResolutionState=None):
    if resolution_state is None:
        resolution_state = ResolutionState()
    if resolution_params is None:
        resolution_params = ResolutionParams()
    if not resolution_params.initial_target:
        resolution_params.initial_target = target
    initial_target = resolution_params.initial_target
    if target in resolution_state.seen_targets:
        return
    else:
        resolution_state.seen_targets.append(target)

    if isinstance(initial_target, FunctionCall) and isinstance(target, (ArrowExpression, Function)) and hasattr(target, 'symbol'):
        target = target.symbol
    if isinstance(initial_target, FunctionCall) and isinstance(target, symbols.Function):
        # we need to check if this is an intermediate call (see test_function_in_return_of_an_arrow_function)
        if not intermediate_call_resolves_to_function(target, resolution_state):
            save_resolution_and_caller(initial_target, target, resolution_params)
            return

    if resolution_params.heuristic:
        if isinstance(resolution_params.heuristic, list):
            heuristics = resolution_params.heuristic
        else:
            heuristics = [resolution_params.heuristic]

        for heuristic in heuristics:
            try:
                result = heuristic(target, resolution_params, resolution_state)
            except:
                pass
            if result:
                break

    if isinstance(target, Argument):
        resolve_recursively(target.children[0], resolution_params, resolution_state)
    if isinstance(target, MemberAccess) and target.get_fullname().startswith('fakeexpr.'):
        resolution_state.destructuring_attribute_name = target.get_name()
        resolve_recursively(target.get_expression(), resolution_params, resolution_state)
        resolution_state.destructuring_attribute_name = None
        return
    if resolution_params.resolution_interpreter and isinstance(target,
                  Identifier) and target.get_begin_line() and initial_target.get_begin_line() < target.get_begin_line():
        if not any([isinstance(t, symbols.ExportedVariable) for t in resolution_state.seen_targets]):
            resolution_params.resolution_interpreter.start_Identifier(target)

    if isinstance(target, MemberAccess) and isinstance(target.parent,
                                                            Assignment) and target.parent.get_left_expression() == target:
        resolve_recursively(target.parent.get_right_expression(), resolution_params, resolution_state)
    if hasattr(target, 'attribute_functions') and initial_target.get_name() in target.attribute_functions:
        func = target.attribute_functions[initial_target.get_name()]
        if isinstance(func, symbols.Function):
            initial_target._resolutions.append(func)
            func.get_ast().add_caller(initial_target)
    elif isinstance(target, IfTernary):
        resolve_recursively(target.get_first_value(), resolution_params, resolution_state)
        resolve_recursively(target.get_second_value(), resolution_params, resolution_state)
    elif isinstance(target, BinaryOperation) and target.get_operator() == '||':
        resolve_recursively(target.get_left_expression(), resolution_params, resolution_state)
        if not initial_target._resolutions:
            resolve_recursively(target.get_right_expression(), resolution_params, resolution_state)

    elif isinstance(target, ArrayAccess):
        resolve_recursively(target.children[0], resolution_params, resolution_state)
    elif isinstance(target, Identifier) and isinstance(target.parent, Parameter):
        if isinstance(initial_target, FunctionCall):
            default_value = target.parent.get_value()
            if hasattr(default_value, 'symbol') and isinstance(default_value.symbol, symbols.Function):
                save_resolution_and_caller(initial_target, default_value.symbol, resolution_params)

        resolve_recursively(target.parent, resolution_params, resolution_state)

    elif isinstance(target, Instantiation) and target.get_resolution():
        resolve_recursively(target.get_resolution(), resolution_params, resolution_state)
    elif isinstance(target, symbols.NodeExport):
        if initial_target.get_name() in target.symbols:
            for func in target.symbols[initial_target.get_name()]:
                if isinstance(func, symbols.Function):
                    initial_target._resolutions.append(func)
                    func.get_ast().add_caller(initial_target)
    elif isinstance(target, symbols.Namespace):
        _func = target.get_function(initial_target.get_name())
        if _func:
            initial_target._resolutions.append(_func)
    elif isinstance(target, symbols.SourceFile):
        resolutions = target.get_symbols_from_export(initial_target.get_name())
        for resolution in resolutions:
            if hasattr(resolution.get_ast(), 'add_caller') and not isinstance(initial_target, MemberAccess):
                resolution.get_ast().add_caller(initial_target)
        if resolutions:
            initial_target._resolutions.extend(resolutions)
            return
    elif isinstance(target, symbols.ExportedVariable):
        resolve_recursively(target.get_ast(), resolution_params, resolution_state)
    elif isinstance(target, (symbols.Class, symbols.Interface)):
        if isinstance(initial_target, MemberAccess):
            is_set = initial_target.is_set()
            field_or_meth = target.get_field_or_meth(initial_target.get_name(), setter=is_set)
        else:
            field_or_meth = target.get_field_or_meth(initial_target.get_name())
        if isinstance(initial_target, MemberAccess):
            if field_or_meth and not field_or_meth in initial_target._resolutions and field_or_meth != initial_target:
                initial_target._resolutions.append(field_or_meth)
            if isinstance(field_or_meth, symbols.Method):
                if (is_set and field_or_meth.is_setter()) or (not is_set and field_or_meth.is_getter()):
                    field_or_meth.get_ast().add_caller(initial_target)

        elif isinstance(field_or_meth, symbols.Method):
            if not field_or_meth in initial_target._resolutions:
                initial_target._resolutions.append(field_or_meth)
                if isinstance(initial_target, MethodCall):
                    field_or_meth.get_ast().add_caller(initial_target)



    elif isinstance(target, ObjectCurlyBracket):
        resolve_when_expr_is_objcurlybra(target, resolution_params, resolution_state)

    elif isinstance(target, (symbols.Function, symbols.Method)):
        for type in target.get_ast().get_declared_return_types():
            resolve_recursively(type, resolution_params, resolution_state)
        for return_type in target.get_ast().get_declared_return_types():
            resolve_recursively(return_type, resolution_params, resolution_state)
        for ret in target.get_ast().get_returns():
            if not hasattr(ret, 'get_expression'):
                if isinstance(target.get_ast(), ArrowExpression):  # we do not necessarly have a return
                    resolve_recursively(ret, resolution_params, resolution_state)
                continue
            resolve_recursively(ret.get_expression(), resolution_params, resolution_state)
    elif target == 'this':
        class_or_object = get_class_or_object_from_ast(target)
        if isinstance(class_or_object, ObjectCurlyBracket) and (
                isinstance(class_or_object.parent, VariableDeclaration) or not get_class_from_ast(target)):
            resolve_recursively(class_or_object, resolution_params, resolution_state)

        if not resolves_to_callable(initial_target):
            class_or_object = get_class_from_ast(target)
            if class_or_object:
                resolve_recursively(class_or_object, resolution_params, resolution_state)
    elif target == 'super':
        _class = get_class_from_ast(target)
        if _class:
            resolutions = _class.find_method(initial_target.get_name(), with_super=True)
            for resolution in resolutions:
                resolution.get_ast().add_caller(initial_target)
            initial_target._resolutions = resolutions
            return
    elif hasattr(target, 'get_resolution') and target.get_resolution():
        resolve_recursively(target.get_resolution(), resolution_params, resolution_state )
    if hasattr(target, 'get_declaration') and target.get_declaration():
        resolve_recursively(target.get_declaration(), resolution_params, resolution_state)
    if isinstance(target, Type) and target.get_identifiers():
        for identifier in target.get_identifiers():
            resolve_recursively(identifier, resolution_params, resolution_state)
            if not isinstance(identifier, Identifier) or identifier.get_name() in ['this',
                                                                                   'any']:  # if we have this, we do not really know where we are
                continue
            if not identifier.get_resolution() and not identifier.get_name() in resolution_params.imported_names:  # if we have no idea where the identifier comes from, we prefer to create unsure links
                continue
            if hasattr(initial_target, 'get_expression'):
                if not hasattr(initial_target.get_expression(), 'possible_type_names'):
                    initial_target.get_expression().possible_type_names = [identifier.get_name()]
                elif not identifier.get_name() in initial_target.get_expression().possible_type_names:
                    initial_target.get_expression().possible_type_names.append(identifier.get_name())

    elif isinstance(target, Identifier) and isinstance(target.parent, ObjectCurlyBracket) and isinstance(target.parent.parent, Parameter):
        resolution_state.destructuring_attribute_name = target.get_name()
        resolve_recursively(target.parent.parent, resolution_params, resolution_state)
    elif isinstance(target, Parameter):
        resolve_from_parameter(target, resolution_params, resolution_state)
        if hasattr(initial_target, 'get_expression') and target.get_variable_type():
            resolve_recursively(target.get_variable_type(), resolution_params, resolution_state)
    elif isinstance(target, symbols.Field):
        # case of intected field
        if hasattr(target.get_ast(), 'get_resolutions'):
            for resol in target.get_ast().get_resolutions():
                resolve_recursively(resol, resolution_params, resolution_state)
        if not target.get_ast() in resolution_state.seen_targets:
            resolution_state.seen_targets.append(target.get_ast())
            resolve_from_parameter(target.get_ast(), resolution_params, resolution_state)
        if hasattr(target.get_ast(), 'get_variable_type') and target.get_ast().get_variable_type():
            resolve_recursively(target.get_ast().get_variable_type(), resolution_params, resolution_state)

        if hasattr(target, 'possible_values'):
            for p_v in target.possible_values:
                resolve_recursively(p_v, resolution_params, resolution_state)
        if hasattr(target.get_ast(), 'get_value') and target.get_ast().get_value():
            resolve_recursively(target.get_ast().get_value(), resolution_params, resolution_state)

    if hasattr(target, 'possible_values'):
        for possible_value in target.possible_values:
            resolve_recursively(possible_value, resolution_params, resolution_state)
    if isinstance(target, Identifier) and target.get_variable_type() and hasattr(initial_target, 'get_expression'):
        resolve_recursively(target.get_variable_type(), resolution_params, resolution_state)
    if not target == initial_target and hasattr(target, 'get_resolutions') and target.get_resolutions():
        for expr_resol in target.get_resolutions():
            resolve_recursively(expr_resol, resolution_params, resolution_state)

    if hasattr(target, 'possible_values_within_block'):
        for p_v in target.possible_values_within_block:
            resolve_recursively(p_v, resolution_params, resolution_state)
    if hasattr(target, 'get_assigned_expression') and target.get_assigned_expression():
        resolve_recursively(target.get_assigned_expression(), resolution_params, resolution_state)



def resolve_when_expr_is_objcurlybra(object_curly_bra, resolution_params, resolution_state):
    if resolution_state.destructuring_attribute_name:
        _dict = object_curly_bra.get_dictionary()
        if resolution_state.destructuring_attribute_name in _dict:
            resolve_recursively(_dict[resolution_state.destructuring_attribute_name], resolution_params, resolution_state)
    initial_target = resolution_params.initial_target
    meth = object_curly_bra.get_method_symbol_by_name(initial_target.get_name())
    if isinstance(meth, (symbols.Method, symbols.Function)) and not meth in initial_target._resolutions:
        initial_target._resolutions.append(meth)
        meth.get_ast().add_caller(initial_target)
        return
    if not isinstance(initial_target, MethodCall):
        return
    target_dict = object_curly_bra.get_dictionary()
    if not initial_target.get_name() in target_dict:
        return
    if hasattr(target_dict[initial_target.get_name()], 'get_resolution') and target_dict[initial_target.get_name()].get_resolution():
        func = target_dict[initial_target.get_name()].get_resolution()
        if isinstance(func, symbols.Function):
            initial_target._resolutions.append(func)
            func.get_ast().add_caller(initial_target)


def resolve_from_parameter(param_initial_target, resolution_params:ResolutionParams, resolution_state:ResolutionState):

    if not isinstance(param_initial_target, (ConstructorField, Parameter)):
        return
    parent = param_initial_target.parent
    while True:
        if isinstance(parent, WithParameters):
            break
        if not hasattr(parent, 'parent'):
            return
        parent = parent.parent

    caller = parent
    i_param = None
    for i, param in enumerate(caller.get_parameters()):
        if param==param_initial_target:
            i_param = i
            break
    if i_param == None:
        log.warning('Param not found')
        return

    for calling_ast in caller.get_calling_asts():
        if not hasattr(calling_ast, 'get_argument'):
            continue
        resolve_recursively(calling_ast.get_argument(i_param), resolution_params, resolution_state)

