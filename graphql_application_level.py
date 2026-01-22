# -*- coding: utf-8 -*-
"""
GraphQL Application Level Extension

This module implements the application-level processing for GraphQL.
It runs after all analyzer-level extensions have completed.

Key features:
- Create links between GraphQL client operations and GraphQL schema
- Create links from GraphQL schema fields to Java backend methods

Links created:
1. Client-to-Schema (USE links):
   - GraphQLClientQuery/Mutation/Subscription → GraphQLField
   - Based on 'fieldsSelected' property of client definitions
   
2. Schema-to-Backend (CALL links):
   - GraphQLField → JV_METHOD (Java)
   - Based on name matching and annotations (@QueryMapping, @MutationMapping)
   - Requires parent class to have @Controller annotation

Available APIs:
- self.application: Access to the Application object
- self.application.get_files(): Get all analyzed files
- self.application.search_objects(): Search for objects by type/name
- ReferenceFinder: Find references to strings in the knowledge base

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
    Creates cross-technology links between different GraphQL components.
    
    Available methods:
    - end_application(): Called once after analysis is complete
    
    Links created:
    - Client → Schema: Links GraphQL client operations to schema fields
    - Schema → Backend: Links GraphQL schema fields to Java backend methods
    
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
        Creates cross-technology links between GraphQL client operations,
        Java backend methods, and GraphQL schema objects.
        
        Links created:
        1. Client → Schema (USE links):
           - GraphQLClientQuery → GraphQLField (Query)
           - GraphQLClientMutation → GraphQLField (Mutation)
           - GraphQLClientSubscription → GraphQLField (Subscription)
           
        2. Schema → Backend (CALL links):
           - GraphQLField → JV_METHOD (annotated Java methods)
        
        Args:
            application: CAST Application object containing all analyzed objects
        """
        try:
            info('[GraphQL Application] Starting cross-technology link creation')
            
            # Create links between client operations and schema objects
            self._link_client_to_schema(application)
            
            # Create links from schema to backend methods
            self._link_schema_to_backend(application)
            
            info('[GraphQL Application] Cross-technology link creation complete')
            
        except Exception as e:
            warning('[GraphQL Application] Error in end_application: ' + str(e))
            debug('[GraphQL Application] ' + traceback.format_exc())
    
    def _get_parent(self, obj, application):
        """
        Get the parent object by extracting the parent name from the fullname.
        
        Used to verify if the parent class of a Java method has the @Controller
        annotation (required for GraphQL resolvers).
        
        Args:
            obj: The object whose parent we want to retrieve
            application: The application containing the object
            
        Returns:
            The parent object (Java class) or None if no parent is found
            
        Example:
            fullname: "com.example.demo.CorsConfig.corsFilter"
            → extracts "CorsConfig" and searches for corresponding JV_CLASS
        """
        fullname = obj.get_fullname()
        
        # Extract the parent name from the fullname
        # For example: "com.example.demo.CorsConfig.corsFilter" -> "CorsConfig"
        if '.' in fullname:
            parent_name = fullname.split('.')[-2]
            
            # Search for the parent object by name
            parent_obj = next((o for o in application.objects().load_property("CAST_Java_AnnotationMetrics.Annotation") if getattr(o, "name", None) == parent_name and getattr(getattr(o, "type", None), "name", None) == "JV_CLASS"), None)
            return parent_obj if parent_obj else (
                None
            )
        return None
    
    def _link_client_to_schema(self, application):
        """
        Create USE links between GraphQL client definitions and schema fields.
        
        Links GraphQLClientQuery/Mutation/Subscription objects to GraphQLField objects.
        
        Linking logic:
        - Retrieves all client objects (Query, Mutation, Subscription)
        - Builds an index of schema fields (Query, Mutation, Subscription types)
        - For each client object, extracts the 'fieldsSelected' property
        - Creates a USE link between client and each corresponding schema field
        
        Example:
            Client: GraphQLClientQuery with fieldsSelected="users,posts"
            → Creates 2 USE links to Query.users and Query.posts
        
        Args:
            application: CAST Application object
        """
        info('[GraphQL Application] ========================================')
        info('[GraphQL Application] Starting client-to-schema linking')
        info('[GraphQL Application] ========================================')
        
        # Use search_objects(load_properties=True) to load properties needed for linking
        client_queries = [obj for obj in application.search_objects(load_properties=True) if obj.get_type() == 'GraphQLClientQuery']
        client_mutations = [obj for obj in application.search_objects(load_properties=True) if obj.get_type() == 'GraphQLClientMutation']
        client_subscriptions = [obj for obj in application.search_objects(load_properties=True) if obj.get_type() == 'GraphQLClientSubscription']
        
        info('[GraphQL Application] Found ' + str(len(client_queries)) + ' GraphQLClientQuery objects')
        info('[GraphQL Application] Found ' + str(len(client_mutations)) + ' GraphQLClientMutation objects')
        info('[GraphQL Application] Found ' + str(len(client_subscriptions)) + ' GraphQLClientSubscription objects')
        
        total_clients = len(client_queries) + len(client_mutations) + len(client_subscriptions)
        if total_clients == 0:
            warning('[GraphQL Application] No client definitions found')
            return
        
        info('[GraphQL Application] Building schema field index...')
        schema_queries = {}
        schema_mutations = {}
        schema_subscriptions = {}
        
        graphql_types = [obj for obj in application.get_objects() if obj.get_type() == 'GraphQLType']
        
        for type_obj in graphql_types:
            type_name = type_obj.get_name()
            
            if type_name == 'Query':
                type_obj.load_children()
                for field_obj in type_obj.get_children():
                    if field_obj.get_type() == 'GraphQLField':
                        schema_queries[field_obj.get_name()] = field_obj
                        
            elif type_name == 'Mutation':
                type_obj.load_children()
                for field_obj in type_obj.get_children():
                    if field_obj.get_type() == 'GraphQLField':
                        schema_mutations[field_obj.get_name()] = field_obj
                        
            elif type_name == 'Subscription':
                type_obj.load_children()
                for field_obj in type_obj.get_children():
                    if field_obj.get_type() == 'GraphQLField':
                        schema_subscriptions[field_obj.get_name()] = field_obj
        
        info('[GraphQL Application] Schema index: ' + str(len(schema_queries)) + ' queries, ' + 
             str(len(schema_mutations)) + ' mutations, ' + str(len(schema_subscriptions)) + ' subscriptions')
        
        links_created = 0
        
        for client_obj in client_queries:
            links_created += self._link_client_to_fields(client_obj, schema_queries, 'Query')
        
        for client_obj in client_mutations:
            links_created += self._link_client_to_fields(client_obj, schema_mutations, 'Mutation')
        
        for client_obj in client_subscriptions:
            links_created += self._link_client_to_fields(client_obj, schema_subscriptions, 'Subscription')
        
        info('[GraphQL Application] ========================================')
        info('[GraphQL Application] Created ' + str(links_created) + ' USE links total')
        info('[GraphQL Application] ========================================')
    
    def _link_client_to_fields(self, client_obj, schema_fields, operation_type):
        """
        Link a client object to schema fields based on fieldsSelected property.
        
        Args:
            client_obj: GraphQL client object (Query/Mutation/Subscription)
            schema_fields: Dictionary {field_name: GraphQLField_object}
            operation_type: Operation type ('Query', 'Mutation', 'Subscription')
            
        Returns:
            Number of links created
            
        Note:
            The fieldsSelected property is stored as a comma-separated string
        """
        links_created = 0
        
        try:
            # Get the property value
            fields_selected_raw = client_obj.get_property('GraphQL_Client_Definition.fieldsSelected')
            info('[GraphQL Application] >>> Processing client object: ' + client_obj.get_name())
            info('[GraphQL Application]     Raw fieldsSelected property: ' + str(fields_selected_raw) + ' (type: ' + str(type(fields_selected_raw)) + ')')
            
            if not fields_selected_raw:
                warning('[GraphQL Application] No fieldsSelected for ' + client_obj.get_name())
                return 0
            
            # The property is saved as a comma-separated string, split it into a list
            if isinstance(fields_selected_raw, str):
                fields_selected = [f.strip() for f in fields_selected_raw.split(',')]
            else:
                fields_selected = fields_selected_raw
            
            info('[GraphQL Application]     Parsed fields: ' + str(fields_selected))
            
            for field_name in fields_selected:
                if field_name in schema_fields:
                    schema_obj = schema_fields[field_name]
                    info('[GraphQL Application] >>> LINK: ' + client_obj.get_name() + ' -> ' + 
                         operation_type + '.' + field_name)
                    create_link('useLink', client_obj, schema_obj)
                    links_created += 1
                else:
                    warning('[GraphQL Application] Field not found in schema: "' + field_name + '"')
        
        except Exception as e:
            warning('[GraphQL Application] Error linking: ' + str(e))
            debug(traceback.format_exc())
        
        return links_created

    def _link_schema_to_backend(self, application):
        """
        Create CALL links from GraphQL schema fields to Java backend methods.
        
        Uses name-based matching between Java method names and GraphQL field names,
        with annotation verification to reduce false positives.
        
        Link creation criteria:
        - Parent class must have @Controller annotation, AND
        - Method name must match a GraphQL field name, AND
        - Method must have the appropriate annotation:
          - @QueryMapping for Query fields
          - @MutationMapping for Mutation fields
          - @SubscriptionMapping for Subscription fields
        
        Architecture created:
            GraphQLField (Query.user) → (CALL) → JV_METHOD (user())
            GraphQLField (Mutation.createUser) → (CALL) → JV_METHOD (createUser())
            GraphQLField (Subscription.studentUpdated) → (CALL) → JV_METHOD (studentUpdated())
        
        Matching logic:
        - Java method "user" with @QueryMapping in @Controller class
          → GraphQL field "Query.user"
        - Java method "createUser" with @MutationMapping in @Controller class
          → GraphQL field "Mutation.createUser"
        - Java method "studentUpdated" with @SubscriptionMapping in @Controller class
          → GraphQL field "Subscription.studentUpdated"
        
        Args:
            application: CAST Application object containing all analyzed objects
        """
        info('[GraphQL Application] ========================================')
        info('[GraphQL Application] Starting schema-to-backend link creation')
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
        schema_subscriptions = {}
        
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
                    
            elif type_name == 'Subscription':
                info('[GraphQL Application] Found Subscription type: ' + str(type_obj.get_fullname()))
                type_obj.load_children()
                children = type_obj.get_children()
                debug('[GraphQL Application]   - Subscription type has ' + str(len(children)) + ' children')
                
                for field_obj in children:
                    if field_obj.get_type() == 'GraphQLField':
                        field_name = field_obj.get_name()
                        schema_subscriptions[field_name] = field_obj
                        info('[GraphQL Application]   - Indexed subscription field: "' + field_name + '" (fullname: ' + str(field_obj.get_fullname()) + ')')
                    else:
                        debug('[GraphQL Application]   - Skipping non-field child: ' + field_obj.get_type())
        
        info('[GraphQL Application] Schema index complete: ' + str(len(schema_queries)) + 
                ' query fields, ' + str(len(schema_mutations)) + ' mutation fields, ' + 
                str(len(schema_subscriptions)) + ' subscription fields')
        
        if len(schema_queries) == 0 and len(schema_mutations) == 0 and len(schema_subscriptions) == 0:
            warning('[GraphQL Application] No GraphQL schema fields found - nothing to link to')
            return
        
        info('[GraphQL Application] ----------------------------------------')
        info('[GraphQL Application] Matching Java methods to schema fields (by name)...')
        info('[GraphQL Application] ----------------------------------------')
        
        # Match Java methods to schema fields by name
        links_created = 0
        queries_matched = 0
        mutations_matched = 0
        subscriptions_matched = 0
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
                        info('[GraphQL Application] >>> CREATING LINK: callLink')
                        info('[GraphQL Application]     FROM (schema):  ' + str(schema_obj.get_fullname()) + ' [' + schema_obj.get_type() + ']')
                        info('[GraphQL Application]     TO (backend):   ' + str(java_method.get_fullname()) + ' [' + java_method.get_type() + ']')
                        info('[GraphQL Application]     ANNOTATION: ' + str([ann for ann in annotations if '@QueryMapping' in str(ann)]))
                        create_link('callLink', schema_obj, java_method)
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
                        info('[GraphQL Application] >>> CREATING LINK: callLink')
                        info('[GraphQL Application]     FROM (schema):  ' + str(schema_obj.get_fullname()) + ' [' + schema_obj.get_type() + ']')
                        info('[GraphQL Application]     TO (backend):   ' + str(java_method.get_fullname()) + ' [' + java_method.get_type() + ']')
                        info('[GraphQL Application]     ANNOTATION: ' + str([ann for ann in annotations if '@MutationMapping' in str(ann)]))
                        create_link('callLink', schema_obj, java_method)
                        links_created += 1
                        mutations_matched += 1
                    else:
                        debug('[GraphQL Application]   - Skipping: No @MutationMapping annotation found')
                
                # Try to match with Subscription fields
                elif method_name in schema_subscriptions:
                    # Check if method has @SubscriptionMapping annotation
                    has_subscription_mapping = any('@SubscriptionMapping' in str(ann) for ann in annotations) if annotations else False
                    
                    if has_subscription_mapping:
                        schema_obj = schema_subscriptions[method_name]
                        info('[GraphQL Application] >>> CREATING LINK: callLink')
                        info('[GraphQL Application]     FROM (schema):  ' + str(schema_obj.get_fullname()) + ' [' + schema_obj.get_type() + ']')
                        info('[GraphQL Application]     TO (backend):   ' + str(java_method.get_fullname()) + ' [' + java_method.get_type() + ']')
                        info('[GraphQL Application]     ANNOTATION: ' + str([ann for ann in annotations if '@SubscriptionMapping' in str(ann)]))
                        create_link('callLink', schema_obj, java_method)
                        links_created += 1
                        subscriptions_matched += 1
                    else:
                        debug('[GraphQL Application]   - Skipping: No @SubscriptionMapping annotation found')
                
                else:
                    # No match found - this is expected for most Java methods
                    debug('[GraphQL Application] No match for Java method: "' + method_name + '"')
                    not_matched += 1
                    
            except Exception as e:
                warning('[GraphQL Application] !!! ERROR linking Java method "' + java_method.get_name() + '": ' + str(e))
                debug('[GraphQL Application] ' + traceback.format_exc())
        
        info('[GraphQL Application] ========================================')
        info('[GraphQL Application] SCHEMA-BACKEND LINKING SUMMARY: Created ' + str(links_created) + ' CALL links')
        info('[GraphQL Application]   - Query methods:        ' + str(queries_matched) + ' linked')
        info('[GraphQL Application]   - Mutation methods:     ' + str(mutations_matched) + ' linked')
        info('[GraphQL Application]   - Subscription methods: ' + str(subscriptions_matched) + ' linked')
        info('[GraphQL Application]   - Not matched:          ' + str(not_matched) + ' (expected - most Java methods are not GraphQL resolvers)')
        info('[GraphQL Application] ========================================')