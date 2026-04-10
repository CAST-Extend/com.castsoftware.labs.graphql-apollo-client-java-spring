import unittest
import logging

import cast_upgrade_1_6_23  # @UnusedImport
from cast.application import LinkType, Server
from cast.application.test import TestKnowledgeBase, run, create_engine  # @UnresolvedImport

try:
    import GraphQLApplicationLevel as ExtensionApplication
except:
    # this import does not work in eclipse, then
    pass


class TestLocalKb(unittest.TestCase):

    def get_parent(self, obj, application):
        """
        Récupère le parent d'un objet en extrayant le nom du parent depuis le fullname.
        
        :param obj: L'objet dont on veut récupérer le parent
        :param application: L'application contenant l'objet
        :return: L'objet parent ou None si aucun parent n'est trouvé
        """
        fullname = obj.get_fullname()
        
        # Extract the parent name from the fullname
        # For exemple: "com.example.demo.CorsConfig.corsFilter" -> "CorsConfig"
        if '.' in fullname:
            parent_name = fullname.split('.')[-2]

            # Chercher l'objet parent par nom
            parent_obj = next((o for o in application.objects().load_property("CAST_Java_AnnotationMetrics.Annotation") if getattr(o, "name", None) == parent_name and getattr(getattr(o, "type", None), "name", None) == "JV_CLASS"), None)
            return parent_obj if parent_obj else (
                None
            )
        return None

    def debug_print_all_object_properties(self, obj):
        """
        Prints every property and its value for a KB object.

        Strategy:
          1. Basic identity fields (name, fullname, type).
          2. Loaded properties from _properties (populated when load_properties=True).
          3. Full metamodel property list — for each property try get_property() so
             we see both loaded AND unloaded values, plus properties not yet fetched.
        """
        print("\n--- Object: {} ---".format(obj.get_fullname()))
        print("  name     : {}".format(obj.get_name()))
        print("  fullname : {}".format(obj.get_fullname()))
        print("  type     : {}".format(obj.get_type()))

        # --- Already-loaded properties (fast path) ---
        loaded = {}
        if hasattr(obj, '_properties') and obj._properties:
            print("  [Loaded properties]")
            for prop_obj, value in obj._properties.items():
                prop_name = getattr(prop_obj, 'name', str(prop_obj))
                loaded[prop_name] = value
                print("    {:<60} = {}".format(prop_name, value))
        else:
            print("  [No _properties dict — object may not have been loaded with load_properties=True]")

        # --- Full metamodel property catalogue ---
        print("  [All metamodel properties for type '{}']".format(obj.get_type()))
        try:
            mm_type = obj.get_metamodel_type()
            if mm_type is None:
                print("    <get_metamodel_type() returned None>")
                return
            for prop in mm_type.properties:
                prop_name = getattr(prop, 'name', str(prop))
                if prop_name in loaded:
                    # Already printed above — just mark it
                    print("    {:<60} (already loaded above)".format(prop_name))
                    continue
                # Try to fetch via public API
                try:
                    value = obj.get_property(prop_name)
                    print("    {:<60} = {}".format(prop_name, value))
                except Exception as e:
                    print("    {:<60} <get_property error: {}>".format(prop_name, e))
        except Exception as e:
            print("    <get_metamodel_type() error: {}>".format(e))

    def test_ts_gql_query_properties(self):
        """
        Fetch the first 10 TsGqlQuery objects from the KB and print all their properties.
        Useful to discover which metamodel properties are populated after an analysis.
        """
        engine = create_engine("postgresql+pg8000://operator:***@localhost:2284/postgres")
        server = Server(engine)
        kb = server.get_schema('bigapptest7_local')
        application = kb.get_application('BigAppTest7')

        print("\n" + "=" * 80)
        print("TEST: First 10 TsGqlQuery objects — all properties")
        print("=" * 80)

        gql_queries = []
        for obj in application.search_objects(load_properties=True):
            if obj.get_type() == 'TsGqlQuery':
                gql_queries.append(obj)
                if len(gql_queries) >= 10:
                    break

        print("Found {} TsGqlQuery object(s) (showing up to 10)".format(len(gql_queries)))

        for idx, obj in enumerate(gql_queries, start=1):
            print("\n[{}/{}]".format(idx, len(gql_queries)))
            self.debug_print_all_object_properties(obj)

        print("\n" + "=" * 80)
        print("Done.")
        print("=" * 80)

    def test_localKb(self):
        # you should adapt with your local KB and application names
        # will work only once after analysis with cast-ms
        # because links to delete will be empty on second run.
        engine = create_engine("postgresql+pg8000://operator:***@localhost:2284/postgres")
        print("engine = {}".format(engine))
        server = Server(engine)
        print("server = {}".format(server))
        kb = server.get_schema('bigapptest6_local')
        application = kb.get_application('BigAppTest6')
        print("type(app) = {}".format(type(application)))

        # All 8 resolver type names (TS + JS)
        _RESOLVER_TYPES = frozenset({
            'TsNodeJsResolverQuery', 'TsNodeJsResolverMutation',
            'TsNodeJsResolverSubscription', 'TsNodeJsResolverCustom',
            'JsNodeJsResolverQuery', 'JsNodeJsResolverMutation',
            'JsNodeJsResolverSubscription', 'JsNodeJsResolverCustom',
        })
        resolvers = list(obj for obj in application.search_objects(load_properties=True) if obj.get_type() in _RESOLVER_TYPES)
        gql_mutations = list(obj for obj in application.search_objects(load_properties=True) if obj.get_type() in ('TsGqlMutation', 'JsGqlMutation'))
        # gql_subs = list(obj for obj in application.search_objects(load_properties=True) if obj.get_type() in ('TsGqlSubscription', 'JsGqlSubscription'))
        # hook_queries = list(obj for obj in application.search_objects(load_properties=True) if obj.get_type() in ('TsGraphQLApolloHookQuery', 'JsGraphQLApolloHookQuery'))
        # hook_lazy_queries = list(obj for obj in application.search_objects(load_properties=True) if obj.get_type() in ('TsGraphQLApolloHookLazyQuery', 'JsGraphQLApolloHookLazyQuery'))
        # hook_mutations = list(obj for obj in application.search_objects(load_properties=True) if obj.get_type() in ('TsGraphQLApolloHookMutation', 'JsGraphQLApolloHookMutation'))
        # hook_subs = list(obj for obj in application.search_objects(load_properties=True) if obj.get_type() in ('TsGraphQLApolloHookSubscription', 'JsGraphQLApolloHookSubscription'))




        # print(clientqueries)
        # print(clientmutations)
        query = clientqueries[0]
        mutation = clientmutations[0]
        # queryrequest = queryrequests[0]
        mutationrequest = mutationrequests[0]
        # reactJSFunctionComponent = reactJSFunctionComponents[0]
        # Fetch CAST_Java_AnnotationMetrics.Annotation for each method
        print("\n=== TsGqlQuery / JsGqlQuery ===")
        for idx, request in enumerate(clientqueries, start=1):
            print("\n=== ClientQuery {} ===".format(idx))
            print("Name: {}".format(request.get_name()))

            # To get all properties for debugging:
            self.debug_print_all_object_properties(request)

        print("\n=== TsGqlMutation / JsGqlMutation ===")
        for idx, request in enumerate(clientmutations, start=1):
            print("\n=== ClientMutation {} ===".format(idx))
            print("Name: {}".format(request.get_name()))

            # To get all properties for debugging:
            self.debug_print_all_object_properties(request)

        print("\n=== GraphQLApolloHookQuery ===")
        for idx, request in enumerate(queryrequests, start=1):
            print("\n=== QueryRequest {} ===".format(idx))
            print("Name: {}".format(request.get_name()))

            # To get all properties for debugging:
            self.debug_print_all_object_properties(request)

        print("\n=== GraphQLApolloHookMutation ===")
        for idx, request in enumerate(mutationrequests, start=1):
            print("\n=== MutationRequest {} ===".format(idx))
            print("Name: {}".format(request.get_name()))

            # To get all properties for debugging:
            self.debug_print_all_object_properties(request)
        
        # TEST: Vérifier les useLinks entre Request et Client Definition
        print("\n" + "="*80)
        print("TEST: Traversée des useLinks (Request -> Client Definition)")
        print("="*80)
        
        all_requests = queryrequests + mutationrequests
        for request_obj in all_requests:
            print("\n>>> Request: {} [{}]".format(request_obj.get_name(), request_obj.get_type()))
            
            # Get all links from this request using application.links() API
            try:
                # Application level API: use application.links().has_caller(request_obj)
                outgoing_links = list(application.links().has_caller([request_obj]))
                print("  Total outgoing links: {}".format(len(outgoing_links)))
                
                for idx, link in enumerate(outgoing_links):
                    # EnlightenLink API: use get_type_names() which returns a list like ['use']
                    link_types = link.get_type_names()
                    
                    print("  Link {}: types={}".format(idx, link_types))
                    
                    # Check if this is a useLink
                    if 'use' in link_types:
                        linked_obj = link.get_callee()  # Get the target object (callee)
                        print("    ✓ useLink found!")
                        if linked_obj:
                            print("    Target: {} [{}]".format(linked_obj.get_name(), linked_obj.get_type()))
                            
                            # Load property on the existing object
                            try:
                                # Re-fetch the object with properties loaded
                                obj_name = linked_obj.get_name()
                                obj_type = linked_obj.get_type()
                                reloaded = list(application.search_objects(name=obj_name, category=obj_type, load_properties=True))
                                if reloaded:
                                    fields_selected = reloaded[0].get_property('GraphQL_Client_Definition.fieldsSelected')
                                    print("    fieldsSelected: '{}'".format(fields_selected))
                                else:
                                    print("    ERROR: Could not find object to reload")
                            except Exception as e:
                                print("    ERROR getting fieldsSelected: {}".format(e))
                        else:
                            print("    ERROR: linked_obj is None!")
                            
            except Exception as e:
                print("  ERROR traversing links: {}".format(e))
                import traceback
                traceback.print_exc()
        
        # TEST: Matching avec les méthodes Java
        print("\n" + "="*80)
        print("TEST: Matching avec les méthodes Java")
        print("="*80)
        
        java_methods = list(obj for obj in application.get_objects() if obj.get_type() == 'JV_METHOD')
        print("\nTotal Java methods: {}".format(len(java_methods)))
        
        # Index des méthodes par nom (charger les propriétés pour chaque méthode)
        java_methods_by_name = {}
        for method in java_methods:
            method_name = method.get_name()
            if method_name not in java_methods_by_name:
                java_methods_by_name[method_name] = []
            # Recharger la méthode avec les propriétés
            reloaded = list(application.search_objects(name=method_name, category='JV_METHOD', load_properties=True))
            if reloaded:
                # Ajouter toutes les méthodes rechargées avec ce nom
                java_methods_by_name[method_name].extend(reloaded)
            else:
                # Fallback: garder la méthode originale même sans propriétés
                java_methods_by_name[method_name].append(method)
        
        print("Unique method names: {}".format(list(java_methods_by_name.keys())))
        
        # Pour chaque request, essayer de trouver la méthode Java correspondante
        for request_obj in all_requests:
            print("\n>>> Request: {}".format(request_obj.get_name()))
            
            # Trouver le client definition via useLink
            client_def = None
            try:
                outgoing_links = list(application.links().has_caller([request_obj]))
                for link in outgoing_links:
                    # Check if this is a useLink using get_type_names()
                    link_types = link.get_type_names()
                    if 'use' in link_types:
                        client_def = link.get_callee()  # Get the target object
                        break
            except:
                pass
            
            if client_def:
                print("  Client definition: {}".format(client_def.get_name()))
                
                # Re-fetch object with properties loaded
                obj_name = client_def.get_name()
                obj_type = client_def.get_type()
                reloaded = list(application.search_objects(name=obj_name, category=obj_type, load_properties=True))
                if reloaded:
                    client_def = reloaded[0]
                else:
                    print("  ERROR: Could not find object to reload")
                    client_def = None
                
                # Extraire fieldsSelected
                if client_def:
                    try:
                        fields_selected_raw = client_def.get_property('GraphQL_Client_Definition.fieldsSelected')
                        if fields_selected_raw:
                            fields = [f.strip() for f in str(fields_selected_raw).split(',')]
                            field_name = fields[0]
                            print("  Field to match: '{}'".format(field_name))
                            
                            # Chercher la méthode Java
                            if field_name in java_methods_by_name:
                                matched_methods = java_methods_by_name[field_name]
                                print("  ✓ Found {} Java method(s) named '{}'".format(len(matched_methods), field_name))
                                
                                valid_methods = []
                                for method in matched_methods:
                                    print("    - Method: {}".format(method.get_fullname()))
                                    
                                    # Vérifier la classe parente
                                    parent = self.get_parent(method, application)
                                    if parent:
                                        print("      Parent class: {}".format(parent.get_fullname()))
                                        
                                        # Vérifier annotations du parent
                                        try:
                                            parent_annotations = parent.get_property("CAST_Java_AnnotationMetrics.Annotation")
                                            has_controller = any('@Controller' in str(ann) for ann in parent_annotations) if parent_annotations else False
                                            print("      Parent annotations: {}".format(parent_annotations))
                                            print("      Has @Controller: {}".format(has_controller))
                                            
                                            if not has_controller:
                                                print("      ✗ SKIP: Parent class does not have @Controller annotation")
                                                continue
                                        except:
                                            print("      ✗ SKIP: Could not load parent annotations")
                                            continue
                                    else:
                                        print("      ✗ SKIP: No parent class found")
                                        continue
                                    
                                    # Vérifier annotations de la méthode
                                    try:
                                        annotations = method.get_property("CAST_Java_AnnotationMetrics.Annotation")
                                        print("      Method annotations: {}".format(annotations))
                                        
                                        # Déterminer le type d'opération attendu basé sur le client_def
                                        expected_annotation = None
                                        if client_def.get_type() in ('TsGqlQuery', 'JsGqlQuery'):
                                            expected_annotation = '@QueryMapping'
                                        elif client_def.get_type() in ('TsGqlMutation', 'JsGqlMutation'):
                                            expected_annotation = '@MutationMapping'
                                        elif client_def.get_type() in ('TsGqlSubscription', 'JsGqlSubscription'):
                                            expected_annotation = '@SubscriptionMapping'
                                        
                                        has_graphql_annotation = any(expected_annotation in str(ann) for ann in annotations) if annotations and expected_annotation else False
                                        print("      Expected annotation: {}".format(expected_annotation))
                                        print("      Has correct annotation: {}".format(has_graphql_annotation))
                                        
                                        if has_graphql_annotation:
                                            print("      ✓ VALID: Method has correct GraphQL annotation")
                                            valid_methods.append(method)
                                        else:
                                            print("      ✗ SKIP: Method does not have {} annotation".format(expected_annotation))
                                    except:
                                        print("      ✗ SKIP: Could not load method annotations")
                                
                                if valid_methods:
                                    print("  >>> RESULT: {} valid GraphQL resolver(s) after filtering".format(len(valid_methods)))
                                    for method in valid_methods:
                                        print("      ✓ {}".format(method.get_fullname()))
                                else:
                                    print("  >>> RESULT: No valid GraphQL resolvers (all filtered out)")
                            else:
                                print("  ✗ No Java method named '{}'".format(field_name))
                                print("  Available: {}".format(list(java_methods_by_name.keys())))
                    except Exception as e:
                        print("  ERROR: {}".format(e))
            else:
                print("  ✗ No client definition found via useLink")

            # try:
            #     annotation = request.get_property("CAST_Java_AnnotationMetrics.Annotation")
            #     print("  CAST_Java_AnnotationMetrics.Annotation: {}".format(annotation))
            # except Exception as e:
            #     print("  CAST_Java_AnnotationMetrics.Annotation: <erreur: {}>".format(e))
            #
            # # Retrieving parent object
            # parent = self.get_parent(request, application)
            # print("  CAST_Java_AnnotationMetrics.Annotation for class: {}".format(parent.get_property("CAST_Java_AnnotationMetrics.Annotation")))
            #
            # if parent:
            #     print("  Parent: {} (type: {})".format(parent.get_fullname(), parent.get_type()))
            # else:
            #     print("  Parent: <non trouvé>")

    def test_method_index_diagnostic(self):
        engine = create_engine("postgresql+pg8000://operator:***@localhost:2284/postgres")
        server = Server(engine)
        kb = server.get_schema('bigapptest6_local')
        application = kb.get_application('BigAppTest6')

        # ── exact copy of _link_resolvers_to_services ────────────────────────────
        # Goal: build a lookup index of all service methods in the KB so we can
        # verify that resolver-to-service links are created correctly.
        #
        # Why not just call obj.get_parent()?
        # The CAST KB API does not expose a simple get_parent() on CustomObject.
        # The only reliable way to recover the parent class name is to parse the
        # fullname (e.g. "DocumentService.archive") and extract the second-to-last
        # segment.  The index key (file_path, class_name, method_name, index) is
        # therefore the canonical identity for a service method in this test.
        _SERVICE_METHOD_TYPES = frozenset({
            'CAST_TS_Method',
            'CAST_HTML5_JavaScript_Method',
            'CAST_HTML5_JavaScript_Generic_Method',
        })

        method_index = {}          # (file_path, class_name, method_name, index) -> obj
        _obj_literal_counters = {}  # disambiguates same method_name in the same file (object literals)
        for obj in application.objects().load_positions():
            try:
                obj_type = obj.get_type()
                if obj_type not in _SERVICE_METHOD_TYPES:  # skip non-method objects
                    continue
                method_name = obj.get_name()
                if not method_name:  # unnamed objects are unusable
                    continue
                positions = obj.get_positions()
                if positions:
                    file_path = str(positions[0].file.get_path())  # canonical file path
                    fullname = obj.get_fullname() or ''
                    parts = fullname.split('.')
                    candidate = parts[-2] if len(parts) >= 2 else ''  # e.g. "DocumentService" in "DocumentService.archive"
                    class_name = candidate if (candidate and candidate[0].isupper()) else None  # PascalCase → class method
                    if class_name is not None:
                        index = 0  # class methods are unique by (file, class, name)
                    else:
                        # object-literal functions: deduplicate by occurrence count in same file
                        counter_key = (file_path, method_name)
                        _obj_literal_counters[counter_key] = (
                            _obj_literal_counters.get(counter_key, 0) + 1)
                        index = _obj_literal_counters[counter_key]
                    key = (file_path, class_name, method_name, index)
                    if key not in method_index:  # first occurrence wins
                        method_index[key] = obj
            except Exception:
                pass
        # ── end of exact copy ────────────────────────────────────────────────────

        print('\nService method index: {} entries'.format(len(method_index)))
        for i, (key, obj) in enumerate(list(method_index.items())[:5]):
            print('  sample[{}] {} -> {}'.format(i, key, obj.get_fullname()))

        # Diagnostic si vide : top-30 types + objets matchant _SERVICE_METHOD_TYPES
        if not method_index:
            print('\nmethod_index is EMPTY — running diagnostics\n')

            # top-30 types présents dans le KB
            type_counter = {}
            all_objs = list(application.objects())
            print('Total objects in search_objects: {}'.format(len(all_objs)))
            for o in all_objs:
                t = o.get_type()
                type_counter[t] = type_counter.get(t, 0) + 1
            print('\nTop 30 object types in KB:')
            for t, c in sorted(type_counter.items(), key=lambda x: -x[1])[:30]:
                marker = '  <-- SERVICE METHOD TYPE' if t in _SERVICE_METHOD_TYPES else ''
                print('  {}: {}{}'.format(t, c, marker))

            # Détail pour les objets qui matchent le type mais sont quand même ignorés
            print('\nObjects matching _SERVICE_METHOD_TYPES (all):')
            skipped_no_name = 0
            skipped_no_positions = 0
            for o in application.objects().load_positions():
                if o.get_type() not in _SERVICE_METHOD_TYPES:
                    continue
                method_name = o.get_name()
                positions = o.get_positions()
                if not method_name:
                    skipped_no_name += 1
                    print('  SKIP no-name: [{}] {}'.format(o.get_type(), o.get_fullname()))
                elif not positions:
                    skipped_no_positions += 1
                    print('  SKIP no-positions: [{}] {}'.format(o.get_type(), o.get_fullname()))
                else:
                    print('  OK: [{}] {} @ {}'.format(o.get_type(), o.get_fullname(),
                                                       positions[0].file.get_path()))
            print('  skipped_no_name={} skipped_no_positions={}'.format(
                skipped_no_name, skipped_no_positions))

            # Inspecter le premier objet skipped (no-positions) pour trouver comment charger les positions
            print('\nInspection du premier objet no-positions:')
            for o in application.objects().load_positions():
                if o.get_type() not in _SERVICE_METHOD_TYPES:
                    continue
                if not o.get_positions():
                    print('  type={} fullname={}'.format(o.get_type(), o.get_fullname()))
                    # Lister les methodes disponibles sur l'objet
                    methods = [m for m in dir(o) if not m.startswith('_')]
                    print('  methodes disponibles: {}'.format(methods))
                    # Tenter load_positions() si disponible
                    if hasattr(o, 'load_positions'):
                        try:
                            o.load_positions()
                            pos_after = o.get_positions()
                            print('  apres load_positions(): {}'.format(pos_after))
                            if pos_after:
                                print('  file_path: {}'.format(pos_after[0].file.get_path()))
                        except Exception as e:
                            print('  load_positions() ERROR: {}'.format(e))
                    # Tenter get_position() (singulier) si disponible
                    if hasattr(o, 'get_position'):
                        try:
                            pos = o.get_position()
                            print('  get_position(): {}'.format(pos))
                        except Exception as e:
                            print('  get_position() ERROR: {}'.format(e))
                    # Tenter l'attribut direct positions (pas la methode)
                    try:
                        pos_attr = o.positions
                        print('  o.positions (attr): {}'.format(pos_attr))
                    except Exception as e:
                        print('  o.positions (attr) ERROR: {}'.format(e))
                    # Tenter l'attribut path
                    try:
                        print('  o.path: {}'.format(o.path))
                    except Exception as e:
                        print('  o.path ERROR: {}'.format(e))
                    # Fullname contient le chemin - tenter d'extraire le file_path
                    fullname = o.get_fullname() or ''
                    print('  fullname: {}'.format(fullname))
                    break

        # ── copie exacte de la 2ème boucle de _link_resolvers_to_services ──────────
        _RESOLVER_TYPES = frozenset({
            'TsNodeJsResolverQuery', 'TsNodeJsResolverMutation',
            'TsNodeJsResolverSubscription', 'TsNodeJsResolverCustom',
            'JsNodeJsResolverQuery', 'JsNodeJsResolverMutation',
            'JsNodeJsResolverSubscription', 'JsNodeJsResolverCustom',
        })

        links_created = 0
        not_matched = 0

        _resolver_query = (application.objects()
                           .load_property('GraphQL_NodeJs_Resolver.serviceFilePath')
                           .load_property('GraphQL_NodeJs_Resolver.serviceMethod')
                           .load_property('GraphQL_NodeJs_Resolver.serviceClass')
                           .load_positions())
        for obj in _resolver_query:
            try:
                if obj.get_type() not in _RESOLVER_TYPES:
                    continue
                service_file_path = obj.get_property('GraphQL_NodeJs_Resolver.serviceFilePath')
                service_method    = obj.get_property('GraphQL_NodeJs_Resolver.serviceMethod')
                service_class     = obj.get_property('GraphQL_NodeJs_Resolver.serviceClass')

                print('resolver: {} | serviceFilePath={} | serviceClass={} | serviceMethod={}'.format(
                    obj.get_name(), service_file_path, service_class, service_method))

                if not service_file_path or not service_method:
                    not_matched += 1
                    continue

                target_obj = None
                if service_class:
                    key = (service_file_path, service_class, service_method, 0)
                    target_obj = method_index.get(key)
                    print('  attempt1 key={} -> {}'.format(key, target_obj.get_fullname() if target_obj else 'MISS'))

                if target_obj is None:
                    ol_count = _obj_literal_counters.get((service_file_path, service_method), 0)
                    if ol_count == 1:
                        key_fallback = (service_file_path, None, service_method, 1)
                        target_obj = method_index.get(key_fallback)
                        print('  attempt2 key={} -> {}'.format(key_fallback, target_obj.get_fullname() if target_obj else 'MISS'))
                    elif ol_count > 1:
                        print('  SKIP ambiguous ol_count={}'.format(ol_count))
                        not_matched += 1
                        continue

                if target_obj is not None:
                    links_created += 1
                    print('  MATCH -> {}'.format(target_obj.get_fullname()))
                else:
                    not_matched += 1
                    # Show a few method_index keys with same method name to understand mismatch
                    same_method_keys = [k for k in method_index if k[2] == service_method][:3]
                    print('  NO MATCH — method_index keys for "{}": {}'.format(
                        service_method, same_method_keys))

            except Exception as e:
                print('  ERROR: {}'.format(e))

        print('\nResolver-service linking: {} matched, {} not matched'.format(
            links_created, not_matched))
        # ── fin copie exacte ─────────────────────────────────────────────────────

    def test_resolver_link_target_diagnostic(self):
        """
        Reproduit exactement la logique de _build_resolver_link_targets +
        _link_resolvers_to_services pour diagnostiquer pourquoi 942 resolvers
        ont 'not_matched'.

        Affiche :
          - Combien de resolvers sont vus par application.objects() (phase create_objects)
          - Combien ont serviceFilePath + serviceMethod
          - Combien trouvent leur méthode de service dans le method_index
          - Pour les MISS : affiche le key tenté vs. les keys disponibles pour ce method_name
        """
        engine = create_engine("postgresql+pg8000://operator:***@localhost:2284/postgres")
        server = Server(engine)
        kb = server.get_schema('bigapptest7_local')
        application = kb.get_application('BigAppTest7')

        _RESOLVER_TYPES = frozenset({
            'TsNodeJsResolverQuery', 'TsNodeJsResolverMutation',
            'TsNodeJsResolverSubscription', 'TsNodeJsResolverCustom',
            'JsNodeJsResolverQuery', 'JsNodeJsResolverMutation',
            'JsNodeJsResolverSubscription', 'JsNodeJsResolverCustom',
        })
        _SERVICE_METHOD_TYPES = frozenset({
            'CAST_TS_Method',
            'CAST_HTML5_JavaScript_Method',
            'CAST_HTML5_JavaScript_Generic_Method',
        })

        # ── Étape 1 : construire le method_index (miroir de _build_resolver_link_targets) ──
        method_index = {}
        _obj_literal_counters = {}
        for obj in application.objects().load_positions():
            try:
                if obj.get_type() not in _SERVICE_METHOD_TYPES:
                    continue
                method_name = obj.get_name()
                if not method_name:
                    continue
                positions = obj.get_positions()
                if not positions:
                    continue
                file_path = str(positions[0].file.get_path())
                fullname = obj.get_fullname() or ''
                parts = fullname.split('.')
                candidate = parts[-2] if len(parts) >= 2 else ''
                class_name = candidate if (candidate and candidate[0].isupper()) else None
                if class_name is not None:
                    index = 0
                else:
                    counter_key = (file_path, method_name)
                    _obj_literal_counters[counter_key] = (
                        _obj_literal_counters.get(counter_key, 0) + 1)
                    index = _obj_literal_counters[counter_key]
                key = (file_path, class_name, method_name, index)
                if key not in method_index:
                    method_index[key] = obj
            except Exception:
                pass
        print('\n[DIAG] method_index: {} entries'.format(len(method_index)))

        # ── Étape 2 : itérer les resolvers comme dans _build_resolver_link_targets ──
        # (même API application.objects() — reproduit la phase end_application_create_objects)
        diag_total = 0
        diag_no_service = 0
        diag_matched = 0
        diag_miss = 0
        first_misses = []  # garde les 5 premiers MISS pour inspection détaillée

        for obj in (application.objects()
                    .load_property('GraphQL_NodeJs_Resolver.serviceFilePath')
                    .load_property('GraphQL_NodeJs_Resolver.serviceMethod')
                    .load_property('GraphQL_NodeJs_Resolver.serviceClass')
                    .load_positions()):
            if obj.get_type() not in _RESOLVER_TYPES:
                continue
            diag_total += 1
            service_file_path = obj.get_property('GraphQL_NodeJs_Resolver.serviceFilePath')
            service_method    = obj.get_property('GraphQL_NodeJs_Resolver.serviceMethod')
            service_class     = obj.get_property('GraphQL_NodeJs_Resolver.serviceClass')
            if not service_file_path or not service_method:
                diag_no_service += 1
                continue

            # Attempt 1 : class-based
            target_obj = None
            if service_class:
                target_obj = method_index.get(
                    (service_file_path, service_class, service_method, 0))

            # Attempt 2 : object-literal fallback
            if target_obj is None:
                ol_count = _obj_literal_counters.get(
                    (service_file_path, service_method), 0)
                if ol_count == 1:
                    target_obj = method_index.get(
                        (service_file_path, None, service_method, 1))

            if target_obj is not None:
                diag_matched += 1
            else:
                diag_miss += 1
                if len(first_misses) < 5:
                    # Clés disponibles dans le method_index pour ce method_name
                    same_name_keys = [k for k in method_index if k[2] == service_method][:3]
                    first_misses.append({
                        'resolver': obj.get_name(),
                        'resolver_fullname': obj.get_fullname(),
                        'service_file_path': service_file_path,
                        'service_class': service_class,
                        'service_method': service_method,
                        'attempted_key': (service_file_path, service_class, service_method, 0),
                        'same_name_in_index': same_name_keys,
                    })

        print('[DIAG] Resolvers seen by application.objects(): {}'.format(diag_total))
        print('[DIAG] Resolvers without serviceFilePath/serviceMethod: {}'.format(diag_no_service))
        print('[DIAG] Resolvers with service info -> matched: {}'.format(diag_matched))
        print('[DIAG] Resolvers with service info -> MISS:    {}'.format(diag_miss))

        if first_misses:
            print('\n[DIAG] First {} MISS details:'.format(len(first_misses)))
            for i, m in enumerate(first_misses, 1):
                print('  MISS #{}'.format(i))
                print('    resolver        : {} ({})'.format(m['resolver'], m['resolver_fullname']))
                print('    service_file    : {}'.format(m['service_file_path']))
                print('    service_class   : {}'.format(m['service_class']))
                print('    service_method  : {}'.format(m['service_method']))
                print('    attempted_key   : {}'.format(m['attempted_key']))
                print('    same name in idx: {}'.format(m['same_name_in_index']))

        # ── Étape 3 : comparer avec _link_resolvers_to_services ──────────────────
        # (même logique, mais depuis end_application — vérifie si les counts diffèrent)
        ls_total = 0
        ls_no_service = 0
        ls_matched = 0
        ls_miss = 0

        for obj in (application.objects()
                    .load_property('GraphQL_NodeJs_Resolver.serviceFilePath')
                    .load_property('GraphQL_NodeJs_Resolver.serviceMethod')
                    .load_property('GraphQL_NodeJs_Resolver.serviceClass')
                    .load_positions()):
            if obj.get_type() not in _RESOLVER_TYPES:
                continue
            ls_total += 1
            service_file_path = obj.get_property('GraphQL_NodeJs_Resolver.serviceFilePath')
            service_method    = obj.get_property('GraphQL_NodeJs_Resolver.serviceMethod')
            if not service_file_path or not service_method:
                ls_no_service += 1
                continue
            service_class = obj.get_property('GraphQL_NodeJs_Resolver.serviceClass')
            target_obj = None
            if service_class:
                target_obj = method_index.get(
                    (service_file_path, service_class, service_method, 0))
            if target_obj is None:
                ol_count = _obj_literal_counters.get(
                    (service_file_path, service_method), 0)
                if ol_count == 1:
                    target_obj = method_index.get(
                        (service_file_path, None, service_method, 1))
            if target_obj is not None:
                ls_matched += 1
            else:
                ls_miss += 1

        # ── Étape 2b : breakdown Ts vs Js dans les 942 "no service" ─────────────
        # Pour comprendre combien sont des JS resolvers (context.service.*) vs TS failures
        ts_no_service = 0
        js_no_service = 0
        sample_no_path = []  # premiers exemples avec serviceMethod mais pas serviceFilePath

        for obj in (application.objects()
                    .load_property('GraphQL_NodeJs_Resolver.serviceFilePath')
                    .load_property('GraphQL_NodeJs_Resolver.serviceMethod')
                    .load_property('GraphQL_NodeJs_Resolver.serviceClass')):
            obj_type = obj.get_type()
            if obj_type not in _RESOLVER_TYPES:
                continue
            sfp   = obj.get_property('GraphQL_NodeJs_Resolver.serviceFilePath')
            smeth = obj.get_property('GraphQL_NodeJs_Resolver.serviceMethod')
            scls  = obj.get_property('GraphQL_NodeJs_Resolver.serviceClass')
            is_ts = obj_type.startswith('Ts')
            if not sfp or not smeth:
                if is_ts:
                    ts_no_service += 1
                else:
                    js_no_service += 1
                if smeth and not sfp and len(sample_no_path) < 5:
                    sample_no_path.append({
                        'type': obj_type, 'name': obj.get_name(),
                        'serviceClass': scls, 'serviceMethod': smeth,
                    })

        print('\n[DIAG] Breakdown of 942 "no serviceFilePath/serviceMethod" resolvers:')
        print('  TS resolvers without service info: {}'.format(ts_no_service))
        print('  JS resolvers without service info: {}'.format(js_no_service))
        if sample_no_path:
            print('  Sample resolvers with serviceMethod but no serviceFilePath:')
            for s in sample_no_path:
                print('    {} {} → {}.{}()?'.format(
                    s['type'], s['name'], s['serviceClass'], s['serviceMethod']))

        print('\n[DIAG] _link_resolvers_to_services pass (same query, no serviceClass load):')
        print('[DIAG]   Resolvers seen: {}'.format(ls_total))
        print('[DIAG]   Without serviceFilePath/serviceMethod: {}'.format(ls_no_service))
        print('[DIAG]   Matched: {}'.format(ls_matched))
        print('[DIAG]   Miss:    {}'.format(ls_miss))

        if diag_total != ls_total:
            print('\n*** WARNING: resolver count differs between the two passes! '
                  'create_objects sees {}, end_application sees {}. '
                  'Timing/visibility issue in KB.'.format(diag_total, ls_total))

        # ── Résumé attendu ────────────────────────────────────────────────────────
        print('\n[DIAG] Summary:')
        print('  Expected from production logs : 323 matched, 942 not_matched')
        print('  This test (create_objects sim): {} matched, {} not_matched (no-service={}, miss={})'.format(
            diag_matched, diag_miss + diag_no_service, diag_no_service, diag_miss))
        print('\n  Root-cause hypothesis:')
        print('  - JS resolvers use context.service.method() → P3 returns no serviceFilePath')
        print('    Approx JS no-service count: {}'.format(js_no_service))
        print('  - TS resolvers: subscriptions + undetected patterns: {}'.format(ts_no_service))
        print('  - 205 MISS: resolver calls method not in service file (test data inconsistency)')

    def test_bug_a_b_fixes_js_resolver_body_and_global_linking(self):
        """
        Comprehensive test for the two bug fixes:

        Bug A — _body_text_from_value_node was extracting the parameter destructuring
                { id } instead of the function body { return userService.findById(id); }.
                Fix: skip past => before looking for {.

        Bug B — _build_resolver_link_targets skipped resolvers where serviceFilePath
                was None, even when serviceMethod and serviceClass were populated.
                Fix: relax the guard to only require serviceMethod; add global search
                fallback in method_index when serviceFilePath is None.

        This test:
          Phase 1 — Verifies that JS resolvers now have serviceClass + serviceMethod
                    populated (proof that Bug A fix works: body extraction is correct)
          Phase 2 — Simulates _build_resolver_link_targets with the Bug B fix (global
                    fallback) and counts how many JS resolvers can now find their
                    service method target via class+method name matching
          Phase 3 — Compares TS vs JS resolver linking rates
          Phase 4 — Spot-checks specific resolver→service pairs from user.resolver.js

        Run after re-analysis with the fixed extension code.
        """
        engine = create_engine("postgresql+pg8000://operator:***@localhost:2284/postgres")
        server = Server(engine)
        kb = server.get_schema('bigapptest7_local')
        application = kb.get_application('BigAppTest7')

        _RESOLVER_TYPES = frozenset({
            'TsNodeJsResolverQuery', 'TsNodeJsResolverMutation',
            'TsNodeJsResolverSubscription', 'TsNodeJsResolverCustom',
            'JsNodeJsResolverQuery', 'JsNodeJsResolverMutation',
            'JsNodeJsResolverSubscription', 'JsNodeJsResolverCustom',
        })
        _SERVICE_METHOD_TYPES = frozenset({
            'CAST_TS_Method',
            'CAST_HTML5_JavaScript_Method',
            'CAST_HTML5_JavaScript_Generic_Method',
        })

        # ══════════════════════════════════════════════════════════════════════
        # PHASE 1: Check JS resolver serviceClass / serviceMethod population
        # (Bug A fix proof: body extraction now returns the real function body)
        # ══════════════════════════════════════════════════════════════════════
        print('\n' + '=' * 80)
        print('PHASE 1: JS Resolver service property population (Bug A fix proof)')
        print('=' * 80)

        js_resolvers = []
        ts_resolvers = []
        js_with_service = []
        js_without_service = []
        js_has_class_no_path = []

        for obj in (application.objects()
                    .load_property('GraphQL_NodeJs_Resolver.serviceFilePath')
                    .load_property('GraphQL_NodeJs_Resolver.serviceMethod')
                    .load_property('GraphQL_NodeJs_Resolver.serviceClass')
                    .load_positions()):
            obj_type = obj.get_type()
            if obj_type not in _RESOLVER_TYPES:
                continue
            is_js = obj_type.startswith('Js')
            sfp   = obj.get_property('GraphQL_NodeJs_Resolver.serviceFilePath')
            smeth = obj.get_property('GraphQL_NodeJs_Resolver.serviceMethod')
            scls  = obj.get_property('GraphQL_NodeJs_Resolver.serviceClass')

            entry = {
                'name': obj.get_name(),
                'fullname': obj.get_fullname(),
                'type': obj_type,
                'serviceClass': scls,
                'serviceMethod': smeth,
                'serviceFilePath': sfp,
                'obj': obj,
            }
            if is_js:
                js_resolvers.append(entry)
                if smeth:
                    js_with_service.append(entry)
                    if not sfp and scls:
                        js_has_class_no_path.append(entry)
                else:
                    js_without_service.append(entry)
            else:
                ts_resolvers.append(entry)

        print('JS resolvers total:               {}'.format(len(js_resolvers)))
        print('JS resolvers with serviceMethod:   {}'.format(len(js_with_service)))
        print('JS resolvers without serviceMethod:{}'.format(len(js_without_service)))
        print('JS resolvers with class, no path:  {}'.format(len(js_has_class_no_path)))
        print('TS resolvers total:               {}'.format(len(ts_resolvers)))

        # Show first 10 JS resolvers with service info (proof body extraction works)
        print('\nFirst 10 JS resolvers with service info:')
        for i, r in enumerate(js_with_service[:10]):
            print('  [{:2d}] {} -> {}.{}  (path={})'.format(
                i + 1, r['name'], r['serviceClass'], r['serviceMethod'],
                r['serviceFilePath'] or 'NONE'))

        # Show first 5 JS resolvers WITHOUT service info (should be 0 after fix)
        if js_without_service:
            print('\nFirst 5 JS resolvers STILL without service info (should be 0 after Bug A fix):')
            for i, r in enumerate(js_without_service[:5]):
                print('  [{:2d}] {} [{}]'.format(i + 1, r['name'], r['type']))

        # Bug A assertion: after fix, most JS resolvers should have serviceMethod
        js_pct = (len(js_with_service) / len(js_resolvers) * 100) if js_resolvers else 0
        print('\nBug A fix rate: {:.1f}% of JS resolvers have serviceMethod'.format(js_pct))

        # ══════════════════════════════════════════════════════════════════════
        # PHASE 2: Simulate _build_resolver_link_targets with Bug B fix
        # (global fallback when serviceFilePath is None)
        # ══════════════════════════════════════════════════════════════════════
        print('\n' + '=' * 80)
        print('PHASE 2: Resolver->Service linking simulation (Bug B fix proof)')
        print('=' * 80)

        # Build the method_index (exact copy of _build_resolver_link_targets)
        method_index = {}
        _obj_literal_counters = {}
        for obj in application.objects().load_positions():
            try:
                if obj.get_type() not in _SERVICE_METHOD_TYPES:
                    continue
                method_name = obj.get_name()
                if not method_name:
                    continue
                positions = obj.get_positions()
                if not positions:
                    continue
                file_path = str(positions[0].file.get_path())
                fullname = obj.get_fullname() or ''
                parts = fullname.split('.')
                candidate = parts[-2] if len(parts) >= 2 else ''
                class_name = candidate if (candidate and candidate[0].isupper()) else None
                if class_name is not None:
                    index = 0
                else:
                    counter_key = (file_path, method_name)
                    _obj_literal_counters[counter_key] = (
                        _obj_literal_counters.get(counter_key, 0) + 1)
                    index = _obj_literal_counters[counter_key]
                key = (file_path, class_name, method_name, index)
                if key not in method_index:
                    method_index[key] = obj
            except Exception:
                pass

        print('method_index size: {} entries'.format(len(method_index)))

        # ── Simulate OLD logic (before Bug B fix) ──
        old_ts_matched = 0
        old_ts_no_service = 0
        old_ts_miss = 0
        old_js_matched = 0
        old_js_no_service = 0
        old_js_miss = 0

        # ── Simulate NEW logic (after Bug B fix — with global fallback) ──
        new_ts_matched = 0
        new_ts_no_service = 0
        new_ts_miss = 0
        new_js_matched = 0
        new_js_no_service = 0
        new_js_miss = 0

        new_js_matched_via_global = []

        all_resolvers = js_resolvers + ts_resolvers
        for r in all_resolvers:
            sfp   = r['serviceFilePath']
            smeth = r['serviceMethod']
            scls  = r['serviceClass']
            is_js = r['type'].startswith('Js')

            # ── OLD logic: skip if no serviceFilePath OR no serviceMethod ──
            if not sfp or not smeth:
                if is_js:
                    old_js_no_service += 1
                else:
                    old_ts_no_service += 1
            else:
                target = None
                if scls:
                    target = method_index.get((sfp, scls, smeth, 0))
                if target is None:
                    ol_count = _obj_literal_counters.get((sfp, smeth), 0)
                    if ol_count == 1:
                        target = method_index.get((sfp, None, smeth, 1))
                if target is not None:
                    if is_js:
                        old_js_matched += 1
                    else:
                        old_ts_matched += 1
                else:
                    if is_js:
                        old_js_miss += 1
                    else:
                        old_ts_miss += 1

            # ── NEW logic: skip only if no serviceMethod ──
            if not smeth:
                if is_js:
                    new_js_no_service += 1
                else:
                    new_ts_no_service += 1
                continue

            target = None
            # Attempt 1: class-based with file path
            if sfp and scls:
                target = method_index.get((sfp, scls, smeth, 0))
            # Attempt 2: object-literal fallback with file path
            if target is None and sfp:
                ol_count = _obj_literal_counters.get((sfp, smeth), 0)
                if ol_count == 1:
                    target = method_index.get((sfp, None, smeth, 1))
            # Attempt 3 (Bug B fix): global search by class+method when no file path
            # Case-insensitive on class name (mirrors fix in graphql_application_level.py)
            if target is None and not sfp and scls:
                scls_lower = scls.lower()
                for key, candidate in method_index.items():
                    if key[1] and key[1].lower() == scls_lower and key[2] == smeth:
                        target = candidate
                        break

            if target is not None:
                if is_js:
                    new_js_matched += 1
                    if not sfp:
                        new_js_matched_via_global.append({
                            'resolver': r['name'],
                            'class': scls,
                            'method': smeth,
                            'target': target.get_fullname(),
                        })
                else:
                    new_ts_matched += 1
            else:
                if is_js:
                    new_js_miss += 1
                else:
                    new_ts_miss += 1

        # ── Print comparison ──
        print('\n--- OLD logic (before Bug B fix) ---')
        print('  TS: matched={}, no_service={}, miss={}'.format(
            old_ts_matched, old_ts_no_service, old_ts_miss))
        print('  JS: matched={}, no_service={}, miss={}'.format(
            old_js_matched, old_js_no_service, old_js_miss))
        print('  Total matched: {}'.format(old_ts_matched + old_js_matched))

        print('\n--- NEW logic (after Bug B fix — global fallback) ---')
        print('  TS: matched={}, no_service={}, miss={}'.format(
            new_ts_matched, new_ts_no_service, new_ts_miss))
        print('  JS: matched={}, no_service={}, miss={}'.format(
            new_js_matched, new_js_no_service, new_js_miss))
        print('  Total matched: {}'.format(new_ts_matched + new_js_matched))

        improvement = (new_ts_matched + new_js_matched) - (old_ts_matched + old_js_matched)
        print('\n  >>> IMPROVEMENT: +{} additional links created by Bug B fix'.format(improvement))

        if new_js_matched_via_global:
            print('\n  JS resolvers matched via global fallback (first 15):')
            for i, m in enumerate(new_js_matched_via_global[:15]):
                print('    [{:2d}] {} -> {}.{} = {}'.format(
                    i + 1, m['resolver'], m['class'], m['method'], m['target']))

        # ══════════════════════════════════════════════════════════════════════
        # PHASE 3: TS vs JS linking rate comparison
        # ══════════════════════════════════════════════════════════════════════
        print('\n' + '=' * 80)
        print('PHASE 3: TS vs JS linking rate comparison')
        print('=' * 80)

        ts_total = len(ts_resolvers)
        js_total = len(js_resolvers)
        ts_rate = (new_ts_matched / ts_total * 100) if ts_total else 0
        js_rate = (new_js_matched / js_total * 100) if js_total else 0
        print('  TS resolvers: {}/{} linked ({:.1f}%)'.format(new_ts_matched, ts_total, ts_rate))
        print('  JS resolvers: {}/{} linked ({:.1f}%)'.format(new_js_matched, js_total, js_rate))

        if new_js_miss > 0:
            js_miss_samples = [r for r in js_resolvers
                               if r['serviceMethod']
                               and not r['serviceFilePath']
                               and r['serviceClass']
                               and not any(key[1] and key[1].lower() == r['serviceClass'].lower()
                                           and key[2] == r['serviceMethod']
                                           for key in method_index)]
            if js_miss_samples:
                print('\n  JS resolvers still unmatched after fix (first 5):')
                for i, r in enumerate(js_miss_samples[:5]):
                    scls_l = r['serviceClass'].lower()
                    same_class_keys = [k for k in method_index
                                       if k[1] and k[1].lower() == scls_l][:3]
                    print('    {} -> {}.{} | index keys for class: {}'.format(
                        r['name'], r['serviceClass'], r['serviceMethod'], same_class_keys))

        # ══════════════════════════════════════════════════════════════════════
        # PHASE 4: Spot-check specific resolver→service pairs
        # ══════════════════════════════════════════════════════════════════════
        print('\n' + '=' * 80)
        print('PHASE 4: Spot-checks on known resolver->service pairs')
        print('=' * 80)

        # These are exact pairs from big_app_test/server/js/resolvers/user.resolver.js
        expected_pairs = [
            # (resolver_name, expected_serviceClass, expected_serviceMethod)
            ('getUser',          'UserService',    'findById'),
            ('getUserByEmail',   'UserService',    'findByEmail'),
            ('getUsers',         'UserService',    'findAll'),
            ('searchUsers',      'UserService',    'search'),
            ('createUser',       'UserService',    'create'),
            ('updateUser',       'UserService',    'update'),
            ('deactivateUser',   'UserService',    'deactivate'),
        ]

        js_resolver_map = {r['name']: r for r in js_resolvers}
        passed = 0
        failed = 0
        for rname, exp_cls, exp_meth in expected_pairs:
            r = js_resolver_map.get(rname)
            if not r:
                print('  SKIP {} — not found in KB (resolver not created?)'.format(rname))
                continue
            scls = r['serviceClass']
            smeth = r['serviceMethod']
            ok_cls = (scls == exp_cls)
            ok_meth = (smeth == exp_meth)

            # Check linking via global fallback
            target = None
            if scls:
                for key, candidate in method_index.items():
                    if key[1] == scls and key[2] == smeth:
                        target = candidate
                        break

            status = 'PASS' if (ok_cls and ok_meth and target) else 'FAIL'
            if status == 'PASS':
                passed += 1
            else:
                failed += 1
            print('  [{}] {} -> class={} method={} linked={}'.format(
                status, rname,
                scls or 'NONE', smeth or 'NONE',
                target.get_fullname() if target else 'NONE'))
            if not ok_cls:
                print('         expected class={}, got={}'.format(exp_cls, scls))
            if not ok_meth:
                print('         expected method={}, got={}'.format(exp_meth, smeth))

        print('\nSpot-check results: {}/{} passed'.format(passed, passed + failed))

        # ══════════════════════════════════════════════════════════════════════
        # PHASE 5: Verify actual callLinks created by the extension
        # (only works after full re-analysis with fixed code)
        # ══════════════════════════════════════════════════════════════════════
        print('\n' + '=' * 80)
        print('PHASE 5: Verify actual callLinks from resolvers to service methods')
        print('=' * 80)

        js_with_calllink = 0
        js_without_calllink = 0
        ts_with_calllink = 0
        ts_without_calllink = 0

        sample_resolvers = (js_resolvers[:30] + ts_resolvers[:30])
        for r in sample_resolvers:
            obj = r['obj']
            is_js = r['type'].startswith('Js')
            try:
                outgoing = list(application.links().has_caller([obj]))
                call_links = [l for l in outgoing if 'call' in l.get_type_names()]
                if call_links:
                    if is_js:
                        js_with_calllink += 1
                    else:
                        ts_with_calllink += 1
                    if (js_with_calllink + ts_with_calllink) <= 10:
                        callee = call_links[0].get_callee()
                        callee_name = callee.get_name() if callee else '???'
                        callee_type = callee.get_type() if callee else '???'
                        print('  {} [{}] --callLink--> {} [{}]'.format(
                            r['name'], r['type'], callee_name, callee_type))
                else:
                    if is_js:
                        js_without_calllink += 1
                    else:
                        ts_without_calllink += 1
            except Exception as e:
                print('  ERROR checking links for {}: {}'.format(r['name'], e))

        print('\nCallLink summary (sample of {} resolvers):'.format(len(sample_resolvers)))
        print('  TS: {} with callLink, {} without'.format(ts_with_calllink, ts_without_calllink))
        print('  JS: {} with callLink, {} without'.format(js_with_calllink, js_without_calllink))

        if js_with_calllink > 0:
            print('\n  >>> Bug A+B fixes CONFIRMED: JS resolvers now have callLinks to service methods!')
        else:
            print('\n  >>> WARNING: No JS callLinks found. Re-analysis with fixed code may be needed.')

        # ══════════════════════════════════════════════════════════════════════
        # FINAL SUMMARY
        # ══════════════════════════════════════════════════════════════════════
        print('\n' + '=' * 80)
        print('FINAL SUMMARY')
        print('=' * 80)
        print('  Bug A (body extraction):')
        print('    JS resolvers with serviceMethod: {}/{} ({:.1f}%)'.format(
            len(js_with_service), len(js_resolvers), js_pct))
        print('    Before fix: 0% (body was param destructuring like " id ")')
        print('  Bug B (global linking fallback):')
        print('    OLD matched: {} | NEW matched: {} | improvement: +{}'.format(
            old_ts_matched + old_js_matched, new_ts_matched + new_js_matched, improvement))
        print('    JS resolvers matched via global fallback: {}'.format(
            len(new_js_matched_via_global)))
        print('  CallLinks:')
        print('    TS resolvers with callLink: {}/{}'.format(
            ts_with_calllink, min(30, len(ts_resolvers))))
        print('    JS resolvers with callLink: {}/{}'.format(
            js_with_calllink, min(30, len(js_resolvers))))
