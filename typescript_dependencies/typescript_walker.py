"""
TypeScript Walker utilities for AST traversal
Copied from com.castsoftware.vuejs for use in GraphQL extension
"""


class Walker:
    """
    Walk an AST.

    Usage :
    - register interpreters.
    - if they have methods :

        start_<node type>(self, node)
        end_<node type>(self, node)

    then they will be called...
    """

    def __init__(self):
        self.interpreters = []

    def register_interpreter(self, interpreter):
        self.interpreters.append(interpreter)

    def on_end(self):
        for interpreter in self.interpreters:
            if hasattr(interpreter, 'on_end'):
                interpreter.on_end()

    def walk(self, stream):
        """
        walk a stream and broadcast to interpreters
        """
        for element in stream:

            if hasattr(element, 'get_children'):
                name = type(element).__name__

                # call the start
                for interpreter in self.interpreters:
                    if hasattr(interpreter, 'start_' + name):
                        getattr(interpreter, 'start_' + name)(element)

                # recurse
                self.walk(element.get_children())

                # call the ends
                for interpreter in self.interpreters:
                    if hasattr(interpreter, 'end_' + name):
                        getattr(interpreter, 'end_' + name)(element)


def get_descendants(node, kind:str):
    """
    Get all descendants of a node of a certain kind
    """

    result = []
    for sub_node in node.get_sub_nodes():
        if is_ts_node_type(sub_node, kind):
            result.append(sub_node)

        result += get_descendants(sub_node, kind)

    return result


def is_ts_node_type(node:any, typename:str):
    type_str = str(type(node))
    # Support both old and new import paths
    if (type_str == "<class 'typescript_parser.parser." + typename + "'>" or
        type_str == "<class 'typescript_dependencies.typescript_parser.parser." + typename + "'>"):
        return True

    return False


def is_ts_symbol_type_single(obj:any, symbol_name:str):
    type_str = str(type(obj))
    # Support both old and new import paths
    if (type_str == "<class 'symbols." + symbol_name + "'>" or
        type_str == "<class 'typescript_dependencies.symbols." + symbol_name + "'>"):
        return True

    return False


def is_ts_symbol_type(obj:any, symbol_name:[str]):
    if isinstance(symbol_name, str):
        return is_ts_symbol_type_single(obj, symbol_name)
    elif isinstance(symbol_name, list):
        for s_n in symbol_name:
            if is_ts_symbol_type_single(obj, s_n):
                return True

    return False
