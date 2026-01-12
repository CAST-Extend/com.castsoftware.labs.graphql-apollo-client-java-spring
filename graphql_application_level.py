# -*- coding: utf-8 -*-
"""
GraphQL Application Level Extension

This module implements the application-level processing for GraphQL.
It runs after all analyzer-level extensions have completed.

Use cases for application-level processing:
- Cross-technology link creation (e.g., linking to databases, APIs)
- Post-analysis calculations and aggregations
- Quality rule implementations
- Custom report generation

The application level has access to:
- The complete knowledge base with all created objects
- Objects from other technologies analyzed in the same application
- Application-wide metadata and statistics

Python 3.4+ compatible.
"""

import cast_upgrade_1_6_23  # noqa: F401 - Required for CAST SDK compatibility
from cast.application import ApplicationLevelExtension, ReferenceFinder, create_link
from cast.application import open_source_file
from logging import info, debug, warning
import traceback


class GraphQLApplicationLevel(ApplicationLevelExtension):
    """
    GraphQL Application Level Extension.
    
    Called after all analyzer-level processing is complete.
    Use this for cross-technology analysis and post-processing.
    
    Available methods:
    - end_application(): Called once after all analysis is complete
    
    Available APIs:
    - self.application: Access to the Application object
    - self.application.get_files(): Get all analyzed files
    - self.application.search_objects(): Search for objects by type/name
    - ReferenceFinder: Find references to strings in the knowledge base
    """
    
    def end_application(self, application):
        """
        Called once after all analyzer-level extensions have completed.
        
        This is the entry point for application-level processing.
        Creates cross-technology links between GraphQL client operations
        and GraphQL schema objects.
        
        Args:
            application: CAST Application object
        """
        try:
            info('[GraphQL Application] Starting cross-technology link creation')
            
            # Create links between client operations and schema objects
            self._link_client_to_schema(application)
            
            # Create links between backend methods and schema objects
            self._link_backend_to_schema(application)
            
            # Create direct call links between frontend and backend
            self._link_frontend_to_backend(application)
            
            info('[GraphQL Application] Cross-technology link creation complete')
            
        except Exception as e:
            warning('[GraphQL Application] Error in end_application: ' + str(e))
            debug('[GraphQL Application] ' + traceback.format_exc())
    
    def _link_client_to_schema(self, application):
        """
        Create USE links between GraphQL client operations and schema objects.
        
        Finds all GraphQLClientQuery and GraphQLClientMutation objects,
        then links them to corresponding GraphQLQuery and GraphQLMutation
        objects from the schema.
        
        Args:
            application: CAST Application object
        """
        info('[GraphQL Application] ========================================')
        info('[GraphQL Application] Starting link creation process')
        info('[GraphQL Application] ========================================')
        
        # Find all client operations using get_objects() and filtering by type
        # get_objects() returns Object instances, get_type() returns the type name
        debug('[GraphQL Application] Searching for client operations...')
        client_queries = [obj for obj in application.get_objects() if obj.get_type() == 'GraphQLClientQuery']
        client_mutations = [obj for obj in application.get_objects() if obj.get_type() == 'GraphQLClientMutation']
    
    def _get_parent(self, obj, application):
        """
        Récupère le parent d'un objet en extrayant le nom du parent depuis le fullname.
        
        :param obj: L'objet dont on veut récupérer le parent
        :param application: L'application contenant l'objet
        :return: L'objet parent ou None si aucun parent n'est trouvé
        """
        fullname = obj.get_fullname()
        
        # Extract the parent name from the fullname
        # For example: "com.example.demo.CorsConfig.corsFilter" -> "CorsConfig"
        if '.' in fullname:
            parent_name = fullname.split('.')[-2]
            
            # Search for the parent object by name
            parents = list(application.get_objects_by_name(parent_name))
            if parents:
                return parents[0]
        
        return None
    
    def _link_client_to_schema(self, application):
        """
        Create USE links between GraphQL client operations and schema objects.
        
        Finds all GraphQLClientQuery and GraphQLClientMutation objects,
        then links them to corresponding GraphQLQuery and GraphQLMutation
        objects from the schema.
        
        Args:
            application: CAST Application object
        """
        info('[GraphQL Application] ========================================')
        info('[GraphQL Application] Starting link creation process')
        info('[GraphQL Application] ========================================')
        
        # Find all client operations using get_objects() and filtering by type
        # get_objects() returns Object instances, get_type() returns the type name
        debug('[GraphQL Application] Searching for client operations...')
        client_queries = [obj for obj in application.get_objects() if obj.get_type() == 'GraphQLClientQuery']
        client_mutations = [obj for obj in application.get_objects() if obj.get_type() == 'GraphQLClientMutation']
        
        info('[GraphQL Application] Found ' + str(len(client_queries)) + ' GraphQLClientQuery objects')
        for obj in client_queries:
            debug('[GraphQL Application]   - Client Query: "' + obj.get_name() + '" (fullname: ' + str(obj.get_fullname()) + ')')
        
        info('[GraphQL Application] Found ' + str(len(client_mutations)) + ' GraphQLClientMutation objects')
        for obj in client_mutations:
            debug('[GraphQL Application]   - Client Mutation: "' + obj.get_name() + '" (fullname: ' + str(obj.get_fullname()) + ')')
        
        total_clients = len(client_queries) + len(client_mutations)
        if total_clients == 0:
            warning('[GraphQL Application] No client operations found - nothing to link')
            return
        
        # Build index of schema objects for faster lookup
        # In GraphQL schema, Query and Mutation are GraphQLType objects
        # Their fields (user, users, createUser) are GraphQLField objects that are children
        info('[GraphQL Application] Building schema field index...')
        schema_queries = {}
        schema_mutations = {}
        
        # Find Query and Mutation types, then load their field children
        # Filter by type name using get_type()
        graphql_types = [obj for obj in application.get_objects() if obj.get_type() == 'GraphQLType']
        debug('[GraphQL Application] Found ' + str(len(graphql_types)) + ' GraphQLType objects')
        
        for type_obj in graphql_types:
            type_name = type_obj.get_name()
            debug('[GraphQL Application]   - Processing GraphQLType: "' + type_name + '"')
            
            if type_name == 'Query':
                info('[GraphQL Application] Found Query type: ' + str(type_obj.get_fullname()))
                # Load all children then filter by type
                type_obj.load_children()
                children = type_obj.get_children()
                debug('[GraphQL Application]   - Query type has ' + str(len(children)) + ' children')
                
                for field_obj in children:
                    if field_obj.get_type() == 'GraphQLField':
                        field_name = field_obj.get_name()
                        schema_queries[field_name] = field_obj
                        info('[GraphQL Application]   - Indexed query field: "' + field_name + '" (fullname: ' + str(field_obj.get_fullname()) + ')')
                    else:
                        debug('[GraphQL Application]   - Skipping non-field child: ' + field_obj.get_type())
                    
            elif type_name == 'Mutation':
                info('[GraphQL Application] Found Mutation type: ' + str(type_obj.get_fullname()))
                # Load all children then filter by type
                type_obj.load_children()
                children = type_obj.get_children()
                debug('[GraphQL Application]   - Mutation type has ' + str(len(children)) + ' children')
                
                for field_obj in children:
                    if field_obj.get_type() == 'GraphQLField':
                        field_name = field_obj.get_name()
                        schema_mutations[field_name] = field_obj
                        info('[GraphQL Application]   - Indexed mutation field: "' + field_name + '" (fullname: ' + str(field_obj.get_fullname()) + ')')
                    else:
                        debug('[GraphQL Application]   - Skipping non-field child: ' + field_obj.get_type())
        
        info('[GraphQL Application] Schema index complete: ' + str(len(schema_queries)) + 
                ' query fields, ' + str(len(schema_mutations)) + ' mutation fields')
        
        info('[GraphQL Application] ----------------------------------------')
        info('[GraphQL Application] Creating USE links for queries...')
        info('[GraphQL Application] ----------------------------------------')
        
        # Link client queries to schema queries
        # Object names are in format "query:fieldName" - we parse to extract fieldName
        links_created = 0
        queries_matched = 0
        queries_not_matched = 0
        
        for client_obj in client_queries:
            try:
                obj_name = client_obj.get_name()
                debug('[GraphQL Application] Processing client query: "' + obj_name + '"')
                
                # Parse "query:fieldName" to get fieldName
                if ':' in obj_name:
                    field_name = obj_name.split(':')[1]
                    debug('[GraphQL Application]   - Extracted field name: "' + field_name + '"')
                else:
                    field_name = obj_name
                    debug('[GraphQL Application]   - Using full name as field: "' + field_name + '"')
                
                if field_name and field_name in schema_queries:
                    schema_obj = schema_queries[field_name]
                    info('[GraphQL Application] >>> CREATING LINK: useLink')
                    info('[GraphQL Application]     FROM (client): ' + str(client_obj.get_fullname()) + ' [' + client_obj.get_type() + ']')
                    info('[GraphQL Application]     TO (schema):   ' + str(schema_obj.get_fullname()) + ' [' + schema_obj.get_type() + ']')
                    create_link('useLink', client_obj, schema_obj)
                    links_created += 1
                    queries_matched += 1
                else:
                    warning('[GraphQL Application] !!! NO MATCH FOUND for client query field: "' + str(field_name) + '"')
                    warning('[GraphQL Application]     Client object: ' + str(client_obj.get_fullname()))
                    warning('[GraphQL Application]     Available schema queries: ' + str(list(schema_queries.keys())))
                    queries_not_matched += 1
            except Exception as e:
                warning('[GraphQL Application] !!! ERROR linking query "' + client_obj.get_name() + '": ' + str(e))
                debug('[GraphQL Application] ' + traceback.format_exc())
        
        info('[GraphQL Application] Query linking complete: ' + str(queries_matched) + ' matched, ' + str(queries_not_matched) + ' not matched')
        
        info('[GraphQL Application] ----------------------------------------')
        info('[GraphQL Application] Creating USE links for mutations...')
        info('[GraphQL Application] ----------------------------------------')
        
        # Link client mutations to schema mutations
        # Object names are in format "mutation:fieldName" - we parse to extract fieldName
        mutations_matched = 0
        mutations_not_matched = 0
        
        for client_obj in client_mutations:
            try:
                obj_name = client_obj.get_name()
                debug('[GraphQL Application] Processing client mutation: "' + obj_name + '"')
                
                # Parse "mutation:fieldName" to get fieldName
                if ':' in obj_name:
                    field_name = obj_name.split(':')[1]
                    debug('[GraphQL Application]   - Extracted field name: "' + field_name + '"')
                else:
                    field_name = obj_name
                    debug('[GraphQL Application]   - Using full name as field: "' + field_name + '"')
                
                if field_name and field_name in schema_mutations:
                    schema_obj = schema_mutations[field_name]
                    info('[GraphQL Application] >>> CREATING LINK: useLink')
                    info('[GraphQL Application]     FROM (client): ' + str(client_obj.get_fullname()) + ' [' + client_obj.get_type() + ']')
                    info('[GraphQL Application]     TO (schema):   ' + str(schema_obj.get_fullname()) + ' [' + schema_obj.get_type() + ']')
                    create_link('useLink', client_obj, schema_obj)
                    links_created += 1
                    mutations_matched += 1
                else:
                    warning('[GraphQL Application] !!! NO MATCH FOUND for client mutation field: "' + str(field_name) + '"')
                    warning('[GraphQL Application]     Client object: ' + str(client_obj.get_fullname()))
                    warning('[GraphQL Application]     Available schema mutations: ' + str(list(schema_mutations.keys())))
                    mutations_not_matched += 1
            except Exception as e:
                warning('[GraphQL Application] !!! ERROR linking mutation "' + client_obj.get_name() + '": ' + str(e))
                debug('[GraphQL Application] ' + traceback.format_exc())
        
        info('[GraphQL Application] Mutation linking complete: ' + str(mutations_matched) + ' matched, ' + str(mutations_not_matched) + ' not matched')
        
        info('[GraphQL Application] ========================================')
        info('[GraphQL Application] SUMMARY: Created ' + str(links_created) + ' USE links total')
        info('[GraphQL Application]   - Queries:   ' + str(queries_matched) + ' linked, ' + str(queries_not_matched) + ' unmatched')
        info('[GraphQL Application]   - Mutations: ' + str(mutations_matched) + ' linked, ' + str(mutations_not_matched) + ' unmatched')
        info('[GraphQL Application] ========================================')

    def _link_backend_to_schema(self, application):
        """
        Create RELY ON links between Java backend methods and GraphQL schema fields.
        
        Uses name-based matching between Java method names and GraphQL field names,
        with annotation verification to reduce false positives.
        
        Only creates links when:
        - Parent class has @Controller annotation, AND
        - Method name matches a GraphQL field name, AND
        - Method has the appropriate annotation:
          - @QueryMapping for Query fields
          - @MutationMapping for Mutation fields
        
        Matching logic:
        - Java method "user" with @QueryMapping in a @Controller class → GraphQL field "Query.user"
        - Java method "createUser" with @MutationMapping in a @Controller class → GraphQL field "Mutation.createUser"
        
        Args:
            application: CAST Application object
        """
        info('[GraphQL Application] ========================================')
        info('[GraphQL Application] Starting backend-to-schema link creation')
        info('[GraphQL Application] ========================================')
        
        # Find all Java methods with properties loaded to check annotations
        debug('[GraphQL Application] Searching for Java methods...')
        java_methods = [obj for obj in application.search_objects(load_properties=True) if obj.get_type() == 'JV_METHOD']
        
        info('[GraphQL Application] Found ' + str(len(java_methods)) + ' JV_METHOD objects')
        if len(java_methods) > 20:
            debug('[GraphQL Application]   (Too many to list individually)')
        else:
            for obj in java_methods:
                debug('[GraphQL Application]   - Java Method: "' + obj.get_name() + '" (fullname: ' + str(obj.get_fullname()) + ')')
        
        if len(java_methods) == 0:
            warning('[GraphQL Application] No Java methods found - nothing to link')
            return
        
        # Build index of schema fields for faster lookup
        info('[GraphQL Application] Building schema field index...')
        schema_queries = {}
        schema_mutations = {}
        
        # Find Query and Mutation types, then load their field children
        graphql_types = [obj for obj in application.get_objects() if obj.get_type() == 'GraphQLType']
        debug('[GraphQL Application] Found ' + str(len(graphql_types)) + ' GraphQLType objects')
        
        for type_obj in graphql_types:
            type_name = type_obj.get_name()
            debug('[GraphQL Application]   - Processing GraphQLType: "' + type_name + '"')
            
            if type_name == 'Query':
                info('[GraphQL Application] Found Query type: ' + str(type_obj.get_fullname()))
                type_obj.load_children()
                children = type_obj.get_children()
                debug('[GraphQL Application]   - Query type has ' + str(len(children)) + ' children')
                
                for field_obj in children:
                    if field_obj.get_type() == 'GraphQLField':
                        field_name = field_obj.get_name()
                        schema_queries[field_name] = field_obj
                        info('[GraphQL Application]   - Indexed query field: "' + field_name + '" (fullname: ' + str(field_obj.get_fullname()) + ')')
                    else:
                        debug('[GraphQL Application]   - Skipping non-field child: ' + field_obj.get_type())
                    
            elif type_name == 'Mutation':
                info('[GraphQL Application] Found Mutation type: ' + str(type_obj.get_fullname()))
                type_obj.load_children()
                children = type_obj.get_children()
                debug('[GraphQL Application]   - Mutation type has ' + str(len(children)) + ' children')
                
                for field_obj in children:
                    if field_obj.get_type() == 'GraphQLField':
                        field_name = field_obj.get_name()
                        schema_mutations[field_name] = field_obj
                        info('[GraphQL Application]   - Indexed mutation field: "' + field_name + '" (fullname: ' + str(field_obj.get_fullname()) + ')')
                    else:
                        debug('[GraphQL Application]   - Skipping non-field child: ' + field_obj.get_type())
        
        info('[GraphQL Application] Schema index complete: ' + str(len(schema_queries)) + 
                ' query fields, ' + str(len(schema_mutations)) + ' mutation fields')
        
        if len(schema_queries) == 0 and len(schema_mutations) == 0:
            warning('[GraphQL Application] No GraphQL schema fields found - nothing to link to')
            return
        
        info('[GraphQL Application] ----------------------------------------')
        info('[GraphQL Application] Matching Java methods to schema fields (by name)...')
        info('[GraphQL Application] ----------------------------------------')
        
        # Match Java methods to schema fields by name
        links_created = 0
        queries_matched = 0
        mutations_matched = 0
        not_matched = 0
        
        for java_method in java_methods:
            try:
                method_name = java_method.get_name()
                debug('[GraphQL Application] Processing Java method: "' + method_name + '"')
                
                # Get parent class of the Java method
                parent_class = self._get_parent(java_method, application)
                
                # Check if parent class has @Controller annotation
                if parent_class:
                    debug('[GraphQL Application]   - Parent class: "' + parent_class.get_fullname() + '"')
                    parent_annotations = []
                    try:
                        parent_annotations = parent_class.get_property("CAST_Java_AnnotationMetrics.Annotation")
                        if parent_annotations:
                            debug('[GraphQL Application]   - Parent annotations: ' + str(parent_annotations))
                    except:
                        pass  # No annotations or property not loaded
                    
                    # Skip if parent class doesn't have @Controller annotation
                    has_controller = any('@Controller' in str(ann) for ann in parent_annotations) if parent_annotations else False
                    if not has_controller:
                        debug('[GraphQL Application]   - Skipping: Parent class does not have @Controller annotation')
                        continue
                else:
                    debug('[GraphQL Application]   - Warning: Could not find parent class, skipping method')
                    continue
                
                # Get method annotations to reduce false positives
                annotations = []
                try:
                    annotations = java_method.get_property("CAST_Java_AnnotationMetrics.Annotation")
                    if annotations:
                        debug('[GraphQL Application]   - Annotations: ' + str(annotations))
                except:
                    pass  # No annotations or property not loaded
                
                # Try to match with Query fields first
                if method_name in schema_queries:
                    # Check if method has @QueryMapping annotation
                    has_query_mapping = any('@QueryMapping' in str(ann) for ann in annotations) if annotations else False
                    
                    if has_query_mapping:
                        schema_obj = schema_queries[method_name]
                        info('[GraphQL Application] >>> CREATING LINK: relyonLink')
                        info('[GraphQL Application]     FROM (backend): ' + str(java_method.get_fullname()) + ' [' + java_method.get_type() + ']')
                        info('[GraphQL Application]     TO (schema):    ' + str(schema_obj.get_fullname()) + ' [' + schema_obj.get_type() + ']')
                        info('[GraphQL Application]     ANNOTATION: ' + str([ann for ann in annotations if '@QueryMapping' in str(ann)]))
                        create_link('relyonLink', java_method, schema_obj)
                        links_created += 1
                        queries_matched += 1
                    else:
                        debug('[GraphQL Application]   - Skipping: No @QueryMapping annotation found')
                
                # Try to match with Mutation fields
                elif method_name in schema_mutations:
                    # Check if method has @MutationMapping annotation
                    has_mutation_mapping = any('@MutationMapping' in str(ann) for ann in annotations) if annotations else False
                    
                    if has_mutation_mapping:
                        schema_obj = schema_mutations[method_name]
                        info('[GraphQL Application] >>> CREATING LINK: relyonLink')
                        info('[GraphQL Application]     FROM (backend): ' + str(java_method.get_fullname()) + ' [' + java_method.get_type() + ']')
                        info('[GraphQL Application]     TO (schema):    ' + str(schema_obj.get_fullname()) + ' [' + schema_obj.get_type() + ']')
                        info('[GraphQL Application]     ANNOTATION: ' + str([ann for ann in annotations if '@MutationMapping' in str(ann)]))
                        create_link('relyonLink', java_method, schema_obj)
                        links_created += 1
                        mutations_matched += 1
                    else:
                        debug('[GraphQL Application]   - Skipping: No @MutationMapping annotation found')
                
                else:
                    # No match found - this is expected for most Java methods
                    debug('[GraphQL Application] No match for Java method: "' + method_name + '"')
                    not_matched += 1
                    
            except Exception as e:
                warning('[GraphQL Application] !!! ERROR linking Java method "' + java_method.get_name() + '": ' + str(e))
                debug('[GraphQL Application] ' + traceback.format_exc())
        
        info('[GraphQL Application] ========================================')
        info('[GraphQL Application] BACKEND LINKING SUMMARY: Created ' + str(links_created) + ' RELY ON links')
        info('[GraphQL Application]   - Query methods:    ' + str(queries_matched) + ' linked')
        info('[GraphQL Application]   - Mutation methods: ' + str(mutations_matched) + ' linked')
        info('[GraphQL Application]   - Not matched:      ' + str(not_matched) + ' (expected - most Java methods are not GraphQL resolvers)')
        info('[GraphQL Application] ========================================')

    def _link_frontend_to_backend(self, application):
        """
        Create CALL links between GraphQL client operations and Java backend methods.
        
        NAIVE IMPLEMENTATION:
        Uses simple name-based matching between GraphQL client operation names 
        and Java method names. This may create false positives (linking unrelated 
        operations with methods that happen to have the same name).
        
        Client operation names are in format "query:real_name" or "mutation:real_name".
        We extract the real_name and match it directly with Java method names.
        
        Matching logic:
        - GraphQLClientQuery "query:user" → Java method "user"
        - GraphQLClientMutation "mutation:createUser" → Java method "createUser"
        
        Args:
            application: CAST Application object
        """
        info('[GraphQL Application] ========================================')
        info('[GraphQL Application] Starting frontend-to-backend link creation (NAIVE)')
        info('[GraphQL Application] ========================================')
        
        # Find all client operations
        debug('[GraphQL Application] Searching for client operations...')
        client_queries = [obj for obj in application.get_objects() if obj.get_type() == 'GraphQLClientQuery']
        client_mutations = [obj for obj in application.get_objects() if obj.get_type() == 'GraphQLClientMutation']
        
        info('[GraphQL Application] Found ' + str(len(client_queries)) + ' GraphQLClientQuery objects')
        info('[GraphQL Application] Found ' + str(len(client_mutations)) + ' GraphQLClientMutation objects')
        
        total_clients = len(client_queries) + len(client_mutations)
        if total_clients == 0:
            warning('[GraphQL Application] No client operations found - nothing to link')
            return
        
        # Find all Java methods
        debug('[GraphQL Application] Searching for Java methods...')
        java_methods = [obj for obj in application.get_objects() if obj.get_type() == 'JV_METHOD']
        
        info('[GraphQL Application] Found ' + str(len(java_methods)) + ' JV_METHOD objects')
        
        if len(java_methods) == 0:
            warning('[GraphQL Application] No Java methods found - nothing to link to')
            return
        
        # Build index of Java methods by name for faster lookup
        info('[GraphQL Application] Building Java method index...')
        java_methods_by_name = {}
        for method in java_methods:
            method_name = method.get_name()
            # Handle potential name collisions by storing as list
            if method_name not in java_methods_by_name:
                java_methods_by_name[method_name] = []
            java_methods_by_name[method_name].append(method)
        
        info('[GraphQL Application] Java method index complete: ' + str(len(java_methods_by_name)) + ' unique method names')
        
        info('[GraphQL Application] ----------------------------------------')
        info('[GraphQL Application] Matching client operations to Java methods (by name)...')
        info('[GraphQL Application] ----------------------------------------')
        
        # Match client operations to Java methods
        links_created = 0
        queries_matched = 0
        mutations_matched = 0
        not_matched = 0
        multiple_matches = 0
        
        # Process queries
        for client_obj in client_queries:
            try:
                obj_name = client_obj.get_name()
                debug('[GraphQL Application] Processing client query: "' + obj_name + '"')
                
                # Parse "query:real_name" to get real_name
                if ':' in obj_name:
                    real_name = obj_name.split(':')[1]
                    debug('[GraphQL Application]   - Extracted real name: "' + real_name + '"')
                else:
                    real_name = obj_name
                    debug('[GraphQL Application]   - Using full name as real name: "' + real_name + '"')
                
                if real_name and real_name in java_methods_by_name:
                    matched_methods = java_methods_by_name[real_name]
                    
                    if len(matched_methods) > 1:
                        warning('[GraphQL Application] Multiple Java methods found with name "' + real_name + '": ' + str(len(matched_methods)) + ' matches (linking to all)')
                        multiple_matches += 1
                    
                    # Create link to all matching methods (in case of overloads)
                    for java_method in matched_methods:
                        info('[GraphQL Application] >>> CREATING LINK: callLink')
                        info('[GraphQL Application]     FROM (frontend): ' + str(client_obj.get_fullname()) + ' [' + client_obj.get_type() + ']')
                        info('[GraphQL Application]     TO (backend):    ' + str(java_method.get_fullname()) + ' [' + java_method.get_type() + ']')
                        create_link('callLink', client_obj, java_method)
                        links_created += 1
                    
                    queries_matched += 1
                else:
                    debug('[GraphQL Application] No Java method match for client query: "' + real_name + '"')
                    not_matched += 1
                    
            except Exception as e:
                warning('[GraphQL Application] !!! ERROR linking client query "' + client_obj.get_name() + '": ' + str(e))
                debug('[GraphQL Application] ' + traceback.format_exc())
        
        # Process mutations
        for client_obj in client_mutations:
            try:
                obj_name = client_obj.get_name()
                debug('[GraphQL Application] Processing client mutation: "' + obj_name + '"')
                
                # Parse "mutation:real_name" to get real_name
                if ':' in obj_name:
                    real_name = obj_name.split(':')[1]
                    debug('[GraphQL Application]   - Extracted real name: "' + real_name + '"')
                else:
                    real_name = obj_name
                    debug('[GraphQL Application]   - Using full name as real name: "' + real_name + '"')
                
                if real_name and real_name in java_methods_by_name:
                    matched_methods = java_methods_by_name[real_name]
                    
                    if len(matched_methods) > 1:
                        warning('[GraphQL Application] Multiple Java methods found with name "' + real_name + '": ' + str(len(matched_methods)) + ' matches (linking to all)')
                        multiple_matches += 1
                    
                    # Create link to all matching methods (in case of overloads)
                    for java_method in matched_methods:
                        info('[GraphQL Application] >>> CREATING LINK: callLink')
                        info('[GraphQL Application]     FROM (frontend): ' + str(client_obj.get_fullname()) + ' [' + client_obj.get_type() + ']')
                        info('[GraphQL Application]     TO (backend):    ' + str(java_method.get_fullname()) + ' [' + java_method.get_type() + ']')
                        create_link('callLink', client_obj, java_method)
                        links_created += 1
                    
                    mutations_matched += 1
                else:
                    debug('[GraphQL Application] No Java method match for client mutation: "' + real_name + '"')
                    not_matched += 1
                    
            except Exception as e:
                warning('[GraphQL Application] !!! ERROR linking client mutation "' + client_obj.get_name() + '": ' + str(e))
                debug('[GraphQL Application] ' + traceback.format_exc())
        
        info('[GraphQL Application] ========================================')
        info('[GraphQL Application] FRONTEND-BACKEND LINKING SUMMARY: Created ' + str(links_created) + ' CALL links')
        info('[GraphQL Application]   - Query operations:     ' + str(queries_matched) + ' matched')
        info('[GraphQL Application]   - Mutation operations:  ' + str(mutations_matched) + ' matched')
        info('[GraphQL Application]   - Not matched:          ' + str(not_matched))
        if multiple_matches > 0:
            info('[GraphQL Application]   - Multiple matches:     ' + str(multiple_matches) + ' operations linked to multiple methods')
        info('[GraphQL Application] ========================================')