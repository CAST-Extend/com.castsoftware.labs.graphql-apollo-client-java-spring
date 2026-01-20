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
        Utility function to print all properties of an object for debugging purposes.
        """
        print("\n=== Debug: All properties for {} ===".format(obj.get_fullname()))
        
        # Print loaded properties for the object
        if hasattr(obj, '_properties'):
            print("  Propriétés chargées:")
            for prop, value in obj._properties.items():
                print("    {} = {}".format(prop.name, value))
        
        # Print all available properties from the metamodel for the object's type
        print("  Propriétés disponibles pour le type {}:".format(obj.get_type()))
        for prop in obj.get_metamodel_type().properties:
            print("    - {}".format(prop.name))

    def test_localKb(self):
        # you should adapt with your local KB and application names
        # will work only once after analysis with cast-ms
        # because links to delete will be empty on second run.
        engine = create_engine("postgresql+pg8000://operator:***@localhost:2284/postgres")
        print("engine = {}".format(engine))
        server = Server(engine)
        print("server = {}".format(server))
        kb = server.get_schema('largegraphqlapp_local')
        application = kb.get_application('LargeGraphQLApp')
        print("type(app) = {}".format(type(application)))
        clientqueries = list(obj for obj in application.search_objects(load_properties=True) if obj.get_type() == 'GraphQLClientQuery')
        clientmutations = list(obj for obj in application.search_objects(load_properties=True) if obj.get_type() == 'GraphQLClientMutation')
        queryrequests = list(obj for obj in application.search_objects(load_properties=True) if obj.get_type() == 'GraphQLQueryRequest')
        mutationrequests = list(obj for obj in application.search_objects(load_properties=True) if obj.get_type() == 'GraphQLMutationRequest')
        reactJSFunctionComponents = list(obj for obj in application.search_objects(load_properties=True) if obj.get_type() == 'CAST_ReactJS_Function_Component')


        # print(clientqueries)
        # print(clientmutations)
        # query = clientqueries[0]
        # mutation = clientmutations[0]
        # queryrequest = queryrequests[0]
        # mutationrequest = mutationrequests[0]
        # reactJSFunctionComponent = reactJSFunctionComponents[0]
        # Fetch CAST_Java_AnnotationMetrics.Annotation for each method
        print("\n=== GraphQLClientQuery ===")
        for idx, request in enumerate(clientqueries, start=1):
            print("\n=== ClientQuery {} ===".format(idx))
            print("Name: {}".format(request.get_name()))

            # To get all properties for debugging:
            self.debug_print_all_object_properties(request)

        print("\n=== GraphQLClientMutation ===")
        for idx, request in enumerate(clientmutations, start=1):
            print("\n=== ClientMutation {} ===".format(idx))
            print("Name: {}".format(request.get_name()))

            # To get all properties for debugging:
            self.debug_print_all_object_properties(request)

        print("\n=== GraphQLQueryRequest ===")
        for idx, request in enumerate(queryrequests, start=1):
            print("\n=== QueryRequest {} ===".format(idx))
            print("Name: {}".format(request.get_name()))

            # To get all properties for debugging:
            self.debug_print_all_object_properties(request)

        print("\n=== GraphQLMutationRequest ===")
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
                                        if client_def.get_type() == 'GraphQLClientQuery':
                                            expected_annotation = '@QueryMapping'
                                        elif client_def.get_type() == 'GraphQLClientMutation':
                                            expected_annotation = '@MutationMapping'
                                        elif client_def.get_type() == 'GraphQLClientSubscription':
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

        # obj_wicket_1 = list(application.search_objects(name='goToHomePage', category="CAST_Wicket_EventHandler",
        #                                                load_properties=True))[0]
        # self.assertEqual(obj_wicket_1.get_fullname(),
        #                  "org.wicketTutorial.rolestrategy.admin.AdminOnlyPage.goToHomePage.Link.onClick")
        #
        # for cnt, o in enumerate(wicket_objs, start=1):
        #     print("(wicket_objs_cnt = {}) {}".format(cnt, o))
        #     pos = o.get_positions()
        #     print(pos)
        #
        # html_to_wicket_links = list(application.links().has_callee(wicket_objs).load_positions())
        # for cnt, l in enumerate(html_to_wicket_links, start=1):
        #     print("(html_to_wicket_links_cnt ={}) {}".format(cnt, l))
        #     pos = l.get_positions()
        #     print(pos)
        #
        # wicket_to_java_links = list(application.links().has_caller(wicket_objs).load_positions())
        # for cnt, l in enumerate(wicket_to_java_links, start=1):
        #     print("(wicket_to_java_links_cnt = {}) {}".format(cnt, l))
        #     pos = l.get_positions()
        #     print(pos)
        #
        # all_links = list(application.links().load_positions())
        # for cnt, l in enumerate(all_links, start=1):
        #     print("(all_links_cnt= {}) {}".format(cnt, l))
        #     pos = l.get_positions()
        #     print(pos)
