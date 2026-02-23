import typescript_dependencies.resolution as resolution
try:
    import cast_upgrade_1_6_17 # @UnusedImport
except ImportError:
    try:
        import cast_upgrade_1_6_23 # @UnusedImport - fallback to newer version
    except ImportError:
        pass  # Not critical for basic usage
import os
import statistics
import traceback
import json
from collections import OrderedDict
from typescript_dependencies.common_tools import DefaultOrderedDict
from typescript_dependencies.symbols import AWSDynamoDBTableCaller, NoSQLConnection, RawBookmark, AWSDynamoDBEndpoint, AWSDynamoDBTable, \
    NoSQLCollection, SourceFile, Builtin
from typescript_dependencies.typescript_parser.light_parser import Node, Token
from cast.application import open_source_file
from cast.analysers import log, create_link, Bookmark


def return_none(self):
    return None


def return_empty_list(self):
    return []


class Program:
    """
    A typescript program (a collection of files)

    Some files are not interesting.

    when we have :
      folder/toto.ts
      folder/toto.d.ts <-- 'header' file, not to be analyzed

    when we have :
      folder/toto.d.ts  <-- 'header' file of an external library, not interesting (or at least external code)
      folder/toto.js
    """

    def __init__(self):
        self.files = OrderedDict()
        self.project = None
        self.__methods = OrderedDict()
        self.__classes = OrderedDict()
        self.s3Buckets = OrderedDict()
        self.typeORMConnections = OrderedDict()
        self.pathmapping = False
        self.import_redirection = OrderedDict()
        # statistics
        self.nbNgComponents = 0
        self.nbExternalMetadata = 0
        self.nbAngularHtmlFragments = 0
        self.nbNgHttpServices = 0
        self.nbNgDirectives = 0
        self.metamodel_counters = {
            'CAST_TS_Class': 0,
            'CAST_TS_Function': 0,
            'CAST_TS_SourceCode': 0,
            'CAST_TS_Method': 0,
            'CAST_TS_Namespace': 0,
        }
        self.nbTSXfiles = 0
        self.nbTSfiles = 0
        self.nbCTSfiles = 0
        self.nbMTSfiles = 0
        self.nbMethodCalls = 0
        self.nbResolvedMethodCalls = 0
        self.nbAmbiguouslyResolvedMethodCalls = 0
        self.nbFunctionCalls = 0
        self.nbResolvedFunctionCalls = 0
        self.nbAmbiguouslyResolvedFunctionCalls = 0
        self.sequelize_models = OrderedDict()
        self.noSQL_connections = []
        self.noSQL_collections = []
        self.missing_files = []
        self.package_json_files = []
        self.node_packages = OrderedDict()

        self.ng_EntryFile_by_dir = OrderedDict()
        self.window_object = OrderedDict()
        # APIs
        self.imported_APIs = {
            'HttpClientModule': False,
            'HttpModule': False,
            'HttpClient': False,
            'Http': False,
        }

        self.frameworks_used = {
            'Angular': False,
            'Express': False,
            'Mongoose': False,
            'AWSSDK': False,
            'React': False,
            'Sequelize': False,
            'TypeORM': False,
            'axios': False,
            'fastify': False,
            'redux': False,
            'mongodb': False,
            'nestjs': False,
            'request': False,
            'nodemailer': False,
            'sendgridmail': False,
            'azureBlob': False,
            'azureServiceBus': False,
            'azureEventHubs': False,
            'azureSignalR': False,
            'azureFunction': False,
            'azureCosmosDB': False,
            'gcpBigTable': False,
            'gcpCloudStorage': False,
            'gcpPubSub': False,
            'loopback': False,
            'gRPC': False,
            'NgRx': False,
            'RxJS': False,
            'Tedious': False,
            'Prisma': False
        }

        self.frameworks_importpath = {
            'Angular': ['angular', 'angular2'],
            'Express': 'express',
            'Mongoose': 'mongoose',
            'mongodb': 'mongodb',
            'AWSSDK': 'aws-sdk',
            'React': 'react',
            'Sequelize': ['sequelize', 'sequelize-typescript'],
            'TypeORM': 'typeorm',
            'axios': ['axios', '@nestjs/axios', 'vue-axios'],
            'fastify': 'fastify',
            'nestjs': 'nestjs',
            'request': ['request', 'request-promise-native', 'request-promise', 'request-promise-any'],
            'nodemailer': 'nodemailer',
            'sendgridmail': '@sendgrid/mail',
            'azureBlob': ['@azure/storage-blob', 'azure-storage'],
            'azureCosmosDB': '@azure/cosmos',
            'azureServiceBus': ['@azure/service-bus', '@azure/sb', 'azure-sb'],
            'azureEventHubs': ['@azure/event-hubs'],
            'azureSignalR': ['@microsoft/signalr', '@aspnet/signalr'],
            'azureFunction': ['durable-functions', '@azure/functions'],
            'gcpBigTable': '@google-cloud/bigtable',
            'gcpCloudStorage': '@google-cloud/storage',
            'gcpPubSub': '@google-cloud/pubsub',
            'loopback': ['@loopback/rest', '@loopback/openapi-v3'],
            'gRPC': ['grpc', '@grpc/grpc-js'],
            'NgRx': ['@ngrx/store', '@ngrx/effects'],
            'redux': ['@reduxjs/toolkit', 'react-redux', 'redux', 'redux-saga/effects', 'redux-actions', '@angular-redux/store'],
            'RxJS': 'rxjs/ajax',
            'Tedious': 'tedious',
            'Prisma': '@prisma/client'
        }

        self.dependenciesVersionsByDirname = OrderedDict()
        self.config_maps = []
        self.aws_lambda_files = []
        self.angular_providers = OrderedDict()
        self.dynamodb_endpoints = OrderedDict()
        self.dynamodb_tables = OrderedDict()
        self.aws_sns_publishings = DefaultOrderedDict(list)
        self.aws_sns_subscriptions = DefaultOrderedDict(list)
        self.aws_sns_topics = OrderedDict()
        self.lambda_dispatchers = []
        self.ngrx_actions_by_id = OrderedDict()
        self.redux_actions_by_name = OrderedDict()
        self.redux_prop_name_to_action = DefaultOrderedDict(list)
        self.redux_components = []
        self.saved_redux_action_handlers_by_fullname = OrderedDict()  # key = action_name, value = kb_symbol
        self.ngrx_unresolved_effects = []
        self.components_by_selector = OrderedDict()
        self.angular_event_emitters = DefaultOrderedDict(list)
        setattr(Token, 'get_resolution', return_none)
        setattr(Token, 'get_resolutions', return_empty_list)

        self.builtins_folder = None

        self.builtin_types = {
            "AggregateError": None,
            "Array": None,
            "ArrayBuffer": None,
            "AsyncFunction": None,
            "AsyncGenerator": None,
            "AsyncGeneratorFunction": None,
            "AsyncIterator": None,
            "Atomics": None,
            "BigInt": None,
            "BigInt64Array": None,
            "BigUint64Array": None,
            "Boolean": None,
            "DataView": None,
            "Date": None,
            "Error": None,
            "EvalError": None,
            "FinalizationRegistry": None,
            "Float32Array": None,
            "Float64Array": None,
            "Function": None,
            "Generator": None,
            "GeneratorFunction": None,
            "Infinity": None,
            "Int16Array": None,
            "Int32Array": None,
            "Int8Array": None,
            "InternalError": None,
            "Intl": None,
            "Iterator": None,
            "JSON": None,
            "Map": None,
            "Math": None,
            "NaN": None,
            "Number": None,
            "Object": None,
            "Promise": None,
            "Proxy": None,
            "RangeError": None,
            "ReferenceError": None,
            "Reflect": None,
            "RegExp": None,
            "Set": None,
            "SharedArrayBuffer": None,
            "String": None,
            "Symbol": None,
            "SyntaxError": None,
            "TypeError": None,
            "URIError": None,
            "Uint16Array": None,
            "Uint32Array": None,
            "Uint8Array": None,
            "Uint8ClampedArray": None,
            "WeakMap": None,
            "WeakRef": None,
            "WeakSet": None,
        }
        self.json_files = OrderedDict()
        self.vueaxios_instances = []

    def get_or_create_builtin_type(self, builtin_name):
        """
        Given a builtin object name, return it's Builtin object or create it if it doesn't exist.
        """
        if builtin_name not in self.builtin_types.keys():
            return
        builtin = self.builtin_types[builtin_name]
        if builtin is None:
            builtin = Builtin(name=builtin_name, parent=self.builtins_folder)
            builtin.save()
            self.builtin_types[builtin_name] = builtin

        return builtin

    def get_or_create_mongodb_connection(self, url):
        if not url or url == "<Unknown>":
            url = "Unknown_MongoDB_Connection"
        for connection in self.noSQL_connections:
            if (url == connection.name and
                    connection.metamodel_type in ['CAST_NodeJS_MongoDB_Connection',
                                                  'CAST_NodeJS_Unknown_MongoDB_Connection']):
                return connection
        if url == "Unknown_MongoDB_Connection":
            metamodel_type = 'CAST_NodeJS_Unknown_MongoDB_Connection'
        else:
            metamodel_type = 'CAST_NodeJS_MongoDB_Connection'
        log.debug("Creating MongoDB Connection " + url)
        connection = NoSQLConnection(url, metamodel_type, self.project)
        connection.save()
        self.noSQL_connections.append(connection)

        return connection

    def add_bookmark_to_dynamodb_table(self, table_name: str, endpoint_name: str, ast: Node, module):
        """
        :param ast : ast for the bookmark
        :param module : SourceFile for the bookmark
        """
        if not endpoint_name:
            endpoint_name = 'Default Endpoint'
        table = self.get_or_create_dynamodb_table(table_name, endpoint_name)
        table.raw_bookmarks.append(RawBookmark(ast, module))

    def add_caller_to_dynamodb_table(self, table_name: str, endpoint_name: str, caller, link_type: str, ast: Node,
                                     module, triggeredby=None):
        """
        :param ast : ast for the bookmark
        :param module : SourceFile for the bookmark
        """
        if not endpoint_name:
            endpoint_name = 'Default Endpoint'
            endpoint = self.get_or_create_dynamodb_endpoint(endpoint_name, module)
        table = self.get_or_create_dynamodb_table(table_name, endpoint_name)
        table.callers.append(AWSDynamoDBTableCaller(caller, ast, module, link_type, triggeredby=triggeredby))

    def add_bookmark_to_dynamodb_endpoint(self, endpoint_name, ast, module=None):
        if not module:
            module = resolution.get_module_from_node(ast)
        if endpoint_name in self.dynamodb_endpoints.keys():
            endpoint = self.dynamodb_endpoints[endpoint_name]
        else:
            endpoint = AWSDynamoDBEndpoint(endpoint_name, module)
            self.dynamodb_endpoints[endpoint_name] = endpoint
        # if endpoint_name != 'Default Endpoint':
        endpoint.raw_bookmarks.append(RawBookmark(ast, module))

        return endpoint

    def get_or_create_dynamodb_endpoint(self, endpoint_name, module):
        if endpoint_name in self.dynamodb_endpoints.keys():
            endpoint = self.dynamodb_endpoints[endpoint_name]
        else:
            endpoint = AWSDynamoDBEndpoint(endpoint_name, module)
            self.dynamodb_endpoints[endpoint_name] = endpoint

        return endpoint

    def get_or_create_dynamodb_table(self, table_name, endpoint_name):
        if (table_name, endpoint_name) in self.dynamodb_tables.keys():
            return self.dynamodb_tables[(table_name, endpoint_name)]
        else:
            table = AWSDynamoDBTable(table_name, endpoint_name)
            self.dynamodb_tables[(table_name, endpoint_name)] = table
            return table

    def get_or_create_mongodb_collection(self, name, connection_name):
        metamodel_type = 'CAST_NodeJS_MongoDB_Collection'
        connection = self.get_or_create_mongodb_connection(connection_name)
        for collection in self.noSQL_collections:
            if (collection.name == name and collection.metamodel_type == metamodel_type and
                (collection.get_connection_name() == connection.name or
                 (connection_name == "<Unknown>" and collection.get_connection_name() == "Unknown_MongoDB_Connection"))
            ):
                return collection
        log.debug("Creating MongoDB Collection " + name)
        collection = NoSQLCollection(name, metamodel_type, connection)
        self.noSQL_collections.append(collection)
        collection.save()

        return collection

    def add_bookmark_to_mongodb_collection(self, collection_name, connection_name, bookmark):
        collection = self.get_or_create_mongodb_collection(collection_name, connection_name)
        collection.get_kb_object().save_position(bookmark)

        return collection

    def add_bookmark_to_mongodb_connection(self, connection_name, bookmark):
        connection = self.get_or_create_mongodb_connection(connection_name)
        connection.get_kb_object().save_position(bookmark)

        return connection

    def create_link_to_mongodb_collection(self, link_type, caller, collection_name, connection_name, bookmark):
        collection = self.get_or_create_mongodb_collection(collection_name, connection_name)
        return create_link(link_type,
                           caller.get_kb_object(),
                           collection.get_kb_object(),
                           bookmark)

    def add_file(self, _file=None, source_file=None):
        """
        :param _file: cast.application.File
        :param source_file: SourceFile  (in case of tests)
        """
        if _file:
            _file._program = self
            path = _file.get_path()
            source_file = SourceFile(path, _file)
            self.files[path] = source_file
            if not self.project:
                try:
                    self.project = _file.get_project()
                except AttributeError:
                    # for unittests
                    pass
        else:
            # for unit tests
            path = source_file.get_path()
            self.files[path] = source_file

        source_file._program = self
        return source_file

    def get_interesting_files(self):
        for path, source_file in self.files.items():
            if path.endswith('.d.ts'):
                continue
            yield source_file

    def get_index_files(self):
        for source_file in self.files.values():
            if source_file.get_name() in ('index.ts', 'index.tsx', 'index.cts', 'index.mts'):
                yield source_file

    def get_config_files(self):
        for source_file in self.files.values():
            if source_file.get_name() in ('config.ts', 'config.tsx', 'config.cts', 'config.mts'):
                yield source_file

    def calculate_stats(self):
        for module in self.get_interesting_files():
            statistics.calculate(module, self)


    def add_class(self, _class):

        name = _class.get_name()
        if name in self.__classes and not _class in self.__classes[name]:
            self.__classes[name].append(_class)
        else:
            self.__classes[name] = [_class]

    def get_classes_by_name(self, name):
        """
        Get all method having name.
        """
        try:
            return self.__classes[name]
        except:
            return OrderedDict()

    def add_method(self, method):
        name = method.get_name()
        if name in self.__methods and method not in self.__methods[name]:
            self.__methods[name].append(method)
        else:
            self.__methods[name] = [method]

    def get_method_by_name(self, name):
        """
        Get all method having name.
        """
        try:
            return self.__methods[name]
        except:
            return OrderedDict()

    def handle_package_json(self, module):
        if isinstance(module.get_text(), str):
            # unittests
            json_content = json.loads(module.get_text())
        else:
            try:
                json_content = json.loads(module.get_text().read())
            except:
                log.debug("Problem loading json file " + module.get_fullname())
                return

        # Get versions from package.json
        filename = module.get_fullname()
        if 'engines' in json_content:
            if 'node' in json_content['engines']:
                node_version = json_content['engines']['node']
                parent_dir = os.path.dirname(filename)
                bm = Bookmark(module.get_file(), 1, 1, 1, 1)

                try:
                    engines_found = False
                    node_found = False
                    with open_source_file(filename) as infile:
                        for nLine, line in enumerate(infile, 1):
                            if '"engines"' in line:
                                engines_found = True
                                if '"node"' in line:
                                    node_found = True
                            elif engines_found:
                                if '"node"' in line:
                                    node_found = True
                            if node_found:
                                index = line.find("node")
                                index_begin = line.find('"', index + 6)
                                if index_begin:
                                    index_end = line.find('"', index_begin + 1)
                                else:
                                    index_end = -1
                                if index_end > 0:
                                    bm = Bookmark(module.get_file(), nLine, index_begin + 2, nLine, index_end + 1)
                                break
                except:
                    log.warning('Problem analyzing ' + filename)
                    log.debug(traceback.format_exc())

                self.dependenciesVersionsByDirname[parent_dir] = {'node_version': node_version.strip(),
                                                                  'node_version_position': bm}
                log.info('NodeJS version (' + str(node_version) + ') found in ' + module.get_path())

        # Handle more package.json
        if "node_modules" in module.get_path():
            return

        try:
            base_package_name = json_content['name']
        except KeyError:
            return

        main = None
        try:
            main = json_content['main']
            if not isinstance(main, str):
                main = None
        except KeyError:
            pass

        exports = None
        if 'exports' in json_content:
            exports = json_content['exports']
            if not isinstance(main, str):
                main = None

        entry_file = None
        try:
            entry_file = json_content['ngPackage']['lib']['entryFile']
            if not isinstance(entry_file, str):
                entry_file = None
        except KeyError:
            pass

        base_entry_path = os.path.dirname(module.get_path())
        entry_paths_by_package_name = OrderedDict()
        if entry_file:
            entry_paths_by_package_name[base_package_name] = os.path.normpath(entry_file)
        # we consider
        elif exports:
            if isinstance(exports, str):
                exports = {'.': exports}
            for base, entry_path in exports.items():
                if isinstance(entry_path, str):
                    entry_paths_by_package_name[base.replace('.', base_package_name)] = os.path.normpath(entry_path)
        elif main:
            entry_paths_by_package_name[base_package_name] = os.path.normpath(main)
        else:
            entry_paths_by_package_name[base_package_name] = base_entry_path

        for package_name, entry_path in entry_paths_by_package_name.items():
            for ext in ['.ts', '.js', '.mts', '.cts', '.tsx', '.jsx', '.mtsx', '.ctsx']:
                if entry_path.endswith(ext):
                    entry_path = entry_path[:-len(ext)]
                    break

            # there might be some redirection of the EntryFile in a ng-package.json. These should be handled.
            # see test test_angular_packages
            if entry_path in self.ng_EntryFile_by_dir:
                entry_path = self.ng_EntryFile_by_dir[entry_path]

            # we check if we find the entry module:
            entry_module = self.find_module(module, entry_path)
            if not entry_module and 'dist' in entry_path:
                entry_module = self.find_module(module, entry_path.replace('dist', 'src'))

            if entry_module:
                self.node_packages[package_name] = entry_module

    def resolve_globals(self):
        """
        Resolve imports and inheritance
        """
        for source_file in self.package_json_files:
            try:
                self.handle_package_json(source_file)
            except:
                log.warning("Problem analyzing the json file : " + source_file.get_name())
                log.warning(traceback.format_exc())

        for module in self.get_interesting_files():

            try:
                resolution.resolve_globals(module, self)
            except:
                path = module.get_file().get_path()
                log.warning("Problem during global resolution in file {}".format(path))
                log.warning(traceback.format_exc())

    def find_modules_poorly_evaluated_path(self, from_module, path):
        """
        This is for when the path is poorly evaluated.
        """
        # we support this only for relative paths
        if not (path.startswith('.') or path.startswith('/')):
            return
        # we only support
        if not path.endswith("{}"):
            log.debug("Finding modules from a poorly evaluated path work only if the non evaluated part is at the end")
            return

        path = path[:-2]
        folder = from_module.get_path()
        folder, local = os.path.split(folder)
        candidate = os.path.normpath(os.path.join(folder, path))

        matching_files = []
        for f_path, file in self.files.items():
            if not f_path.startswith(candidate):
                continue
            if os.path.join(candidate, os.path.basename(f_path)) == f_path:
                matching_files.append(file)

        return matching_files

    def find_module(self, from_module, path):
        """
        Search the module with path referenced in another module
        :param from_module: SourceFile
        @see https://www.typescriptlang.org/docs/handbook/module-resolution.html
        """

        folder = from_module.get_path()
        folder, local = os.path.split(folder)
        path_ini = path
        # we first check if we resolve to a json file
        file_path = os.path.normpath(os.path.join(folder, path_ini))
        if file_path in self.json_files:
            json_file = self.json_files[file_path]
            # we need to parse the json_file if it was not parsed
            if not hasattr(json_file, '_ast') or not json_file._ast:
                json_file.fully_parse()
                json_file.refine_parsing_for_json()
            # we need to
            return json_file

        # if a path to a directory is provided, typescript will search for index.ts files within the directory
        for ext in ['.js', '.ts', '.tsx', '.mts', '.cts']:
            if path.endswith(ext):
                path = path.replace(ext, '')
                break

        path_ini = path
        for ext in ['.js', '.ts', '.tsx', '/index.ts', '/index.tsx', '.mts', '.cts', '/index.mts', '/index.cts']:
            path = path_ini + ext
            folder = from_module.get_path()
            # relative versus non-relative
            if path.startswith('.') or path.startswith('/'):
                # relative import
                folder, local = os.path.split(folder)
                candidate = os.path.normpath(os.path.join(folder, path))
                try:
                    file = self.files[candidate]
                except KeyError:
                    if candidate in self.import_redirection:
                        file = self.import_redirection[candidate]
                    else:
                        continue
                if candidate.endswith("environment.ts"):
                    # here we mimic the behavior of Angular
                    # ( http://tattoocoder.com/angular-cli-using-the-environment-option/ )
                    # when overriding behind-the-scenes the variable
                    # values from the default 'environment.ts' file with
                    # the production environment ones.
                    # TODO: search for production files within this folder
                    #    when missing 'environment.prod.ts'
                    folder, _ = os.path.split(candidate)
                    overriden = os.path.join(folder, 'environment.prod.ts')
                    try:
                        return self.files[overriden]
                    except KeyError:
                        pass
                    # warn user if the environment file
                    # used is not for production.
                    try:
                        # it can be an open file or a string (unit-test)
                        # here we wrap text recovering by a try-except to avoid forcing
                        # usage of 'text' keyword in unit-tests with fake paths
                        text = file.get_text()
                    except FileNotFoundError:
                        pass
                    else:
                        is_for_production = False
                        for line in text:
                            if line.lstrip().startswith('//'):
                                continue
                            if 'production: true' in line:
                                is_for_production = True
                                break
                        if not is_for_production:
                            log.warning("Loaded environment file is not declared for production code: " + candidate)

                return file
            else:
                # non relative
                stop = False
                while not stop:
                    folder, local = os.path.split(folder)
                    candidate = os.path.normpath(os.path.join(folder, path))

                    try:
                        return self.files[candidate]
                    except:
                        if candidate in self.import_redirection:
                            file = self.import_redirection[candidate]

                    if not local:
                        stop = True

        if path.startswith('.') or path.startswith('/'):
            file_path = os.path.normpath(os.path.join(folder, path_ini))
            if file_path not in self.missing_files:
                self.missing_files.append(file_path)
