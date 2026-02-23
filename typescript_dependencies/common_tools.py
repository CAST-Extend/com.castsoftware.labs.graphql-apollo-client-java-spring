import re
from collections import OrderedDict, Callable
import traceback
import xml.etree.ElementTree as ET
from cast.analysers import log
import os

class ExtractMetamodel:
    def __init__(self):
        script_dir = os.path.dirname(os.path.abspath(__file__))
        file_path = os.path.join(script_dir, "configuration/Languages/TypeScript/TypeScriptMetaModel.xml")
        
        # Try to parse XML file, but continue if not found (for tests)
        try:
            self.tree = ET.parse(file_path)
            self.root = self.tree.getroot()
        except (FileNotFoundError, ET.ParseError) as e:
            log.info("TypeScriptMetaModel.xml not found or invalid, using hardcoded types only: %s" % str(e))
            self.tree = None
            self.root = None
        
        self.type_id_from_type_name = OrderedDict()
        self.type_id_from_type_name['CAST_HTML5_HTML_Fragment'] = '1020243'
        self.type_id_from_type_name['CAST_ReduxJS_ReducerHandler'] = '1020645'
        self.type_id_from_type_name['CAST_NodeJS_Azure_EventHub_Publisher'] = '1020621'
        self.type_id_from_type_name['CAST_NodeJS_Azure_Unknown_EventHub_Publisher'] = '1020622'
        self.type_id_from_type_name['CAST_NodeJS_Azure_EventHub_Receiver'] = '1020623'
        self.type_id_from_type_name['CAST_NodeJS_Azure_Unknown_EventHub_Receiver'] = '1020624'
        self.type_id_from_type_name['CAST_NodeJS_Azure_CallTo_Hub_Method'] = '1020632'
        self.type_id_from_type_name['CAST_NodeJS_Azure_CallTo_Unknown_Hub_Method'] = '1020633'
        self.type_id_from_type_name['CAST_NodeJS_Call_to_Azure_Function'] = '1020570'
        self.type_id_from_type_name['CAST_NodeJS_Call_to_Unknown_Azure_Function'] = '1020571'

        self.type_id_from_type_name['CAST_NodeJS_gRPC_Method'] = '1020642'

        self.type_id_from_type_name['CAST_NodeJS_CallTo_gRPC'] = '1020643'
        self.type_id_from_type_name['CAST_ReactJS_Component'] = '1020242'
        self.type_id_from_type_name['CAST_ReactJS_Redux_Form'] = '1020262'
        self.type_id_from_type_name['CAST_NodeJS_Email'] = '1020485'

        self.type_id_from_type_name['CAST_NodeJS_AWS_SNS_Publisher'] = '1020508'
        self.type_id_from_type_name['CAST_NodeJS_AWS_SNS_Unknown_Publisher'] = '1020510'

        self.type_id_from_type_name['CAST_NodeJS_AWS_SNS_Subscriber'] = '1020501'
        self.type_id_from_type_name['CAST_NodeJS_AWS_SNS_Unknown_Subscriber'] = '1020509'

        self._extract_data()

    def _extract_data(self):
        if self.root is not None:
            for type_elem in self.root.findall("type"):
                self.type_id_from_type_name[type_elem.get("name") ] = type_elem.get("id")

# Create a global instance
xml_data_instance = ExtractMetamodel()

# Function to get the data anywhere in the code
def get_type_id_from_type_name(type_name:str):
    try:
        return xml_data_instance.type_id_from_type_name[type_name]
    except KeyError:
        log.warning('Unknown type in the metamodel')
        log.warning(traceback.format_exc())

class DefaultOrderedDict(OrderedDict):
    # Source: http://stackoverflow.com/a/6190500/562769
    def __init__(self, default_factory=None, *a, **kw):
        if (default_factory is not None and
           not isinstance(default_factory, Callable)):
            raise TypeError('first argument must be callable')
        OrderedDict.__init__(self, *a, **kw)
        self.default_factory = default_factory

    def __getitem__(self, key):
        try:
            return OrderedDict.__getitem__(self, key)
        except KeyError:
            return self.__missing__(key)

    def __missing__(self, key):
        if self.default_factory is None:
            raise KeyError(key)
        self[key] = value = self.default_factory()
        return value

    def __reduce__(self):
        if self.default_factory is None:
            args = tuple()
        else:
            args = self.default_factory,
        return type(self), args, None, None, self.items()

    def copy(self):
        return self.__copy__()

    def __copy__(self):
        return type(self)(self.default_factory, self)

    def __deepcopy__(self, memo):
        import copy
        return type(self)(self.default_factory,
                          copy.deepcopy(self.items()))

    def __repr__(self):
        return 'OrderedDefaultDict(%s, %s)' % (self.default_factory,
                                               OrderedDict.__repr__(self))


def clean_url(value):
    # sanitize unknowns by these heuristics
    # (i)     {}b/c    ->  b/c
    # (ii)    a/{}b/c     -> a/{}/b/c
    #
    # the case with /b{}/ is handled by wbslinker
    #

    # remove protocol to simplify splitting by "/"
    protocol = None
    if "://" in value:
        protocol = value.split("://", 1)[0]
        value = value.split("://", 1)[1]

    new_value = ""
    add_ending_slash = value.endswith('/')
    parts = value.split("/")

    # (i)
    first = parts[0]
    part = None

    cond1 = first.startswith("{}")
    cond2 = first == "{}"
    cond3 = first.startswith('{}?')

    if cond1 and not (cond2 or cond3):
        part = first.split("}", 1)[1]  # remove leading "{}"
    if not part:
        part = first

    reg = re.compile(r'\\\${.*}', re.VERBOSE)
    part = reg.sub('{}',part)
    new_value += part

    # (ii)
    if len(parts) > 1:
        for part in parts[1:]:
            if not part:
                continue  # skip empty "" chain

            if part.startswith('{}') and not part == "{}":
                # insert a slash
                part = part.split("}", 1)[1]
                part = "{}/" + part
            new_value += "/" + reg.sub('{}',part)

    if add_ending_slash:
        new_value += "/"

    if protocol:
        new_value = protocol + "://" + new_value

    value = new_value
    if (value.startswith("{}") and
            len(value) > 2 and value[2] != "?"):
        value = value[2:]

    value = value.replace("}{", "")

    splited_value = value.split("/")
    value = ""
    question_mark_found = False
    for v in splited_value:
        if "?" in v:
            question_mark_found = True
        if "{}" in v and v != "{}" and not question_mark_found:
            value += v.replace("{}", "")
        else:
            value += v
        value += "/"
    value = value[:-1]
    return value