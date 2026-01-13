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
        kb = server.get_schema('graphqllinktest1_local')
        application = kb.get_application('GraphQLlinkTest1')
        print("type(app) = {}".format(type(application)))
        jv_methods = list(obj for obj in application.search_objects(load_properties=True) if obj.get_type() == 'JV_METHOD')
        jv_class = list(obj for obj in application.search_objects(load_properties=True) if obj.get_type() == 'JV_CLASS')

        print(jv_methods)

        # Fetch CAST_Java_AnnotationMetrics.Annotation for each method
        for idx, method in enumerate(jv_methods, start=1):
            print("\n=== Method {} ===".format(idx))
            print("Name: {}".format(method.get_fullname()))

            # To get all properties for debugging:
            # self.debug_print_all_object_properties(method)

            try:
                annotation = method.get_property("CAST_Java_AnnotationMetrics.Annotation")
                print("  CAST_Java_AnnotationMetrics.Annotation: {}".format(annotation))
            except Exception as e:
                print("  CAST_Java_AnnotationMetrics.Annotation: <erreur: {}>".format(e))
            
            # Retrieving parent object
            parent = self.get_parent(method, application)
            print("  CAST_Java_AnnotationMetrics.Annotation for class: {}".format(parent.get_property("CAST_Java_AnnotationMetrics.Annotation")))
            
            if parent:
                print("  Parent: {} (type: {})".format(parent.get_fullname(), parent.get_type()))
            else:
                print("  Parent: <non trouvé>")

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
