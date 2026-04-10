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
   - TsGqlQuery/TsGqlMutation/TsGqlSubscription (TypeScript) → GraphQLField
   - JsGqlQuery/JsGqlMutation/JsGqlSubscription (JavaScript) → GraphQLField
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
from cast.application import open_source_file, CustomObject
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
    
    def end_application_create_objects(self, application):
        """
        Called before end_application. Creates CustomObject stubs for:
        1. Resolver calls that could not be matched to a real service method.
        2. Schema fields referenced by client objects but not found in the schema.

        CAST only allows CustomObject creation during this phase, not during
        end_application where links are created.
        """
        self._resolver_link_targets = {}  # resolver_fullname → target KB obj (real or unresolved)
        self._unresolved_schema_fields = {}  # field_name → UnresolvedSchemaField CustomObject
        self._schema_resolver_stubs = {}    # (op_type, field_name, 'ts'|'js') → Unresolved* CustomObject
        try:
            self._build_resolver_link_targets(application)
        except Exception as e:
            warning('[GraphQL Application] Error in end_application_create_objects (resolvers): ' + str(e))
            debug('[GraphQL Application] ' + traceback.format_exc())
        try:
            self._build_unresolved_schema_fields(application)
        except Exception as e:
            warning('[GraphQL Application] Error in end_application_create_objects (schema fields): ' + str(e))
            debug('[GraphQL Application] ' + traceback.format_exc())
        # Links to custom objects (UnresolvedSchemaField) MUST be created here, not in end_application.
        # CAST only allows create_link on custom objects during end_application_create_objects.
        try:
            self._link_client_to_unresolved_fields(application)
        except Exception as e:
            warning('[GraphQL Application] Error in end_application_create_objects (unresolved links): ' + str(e))
            debug('[GraphQL Application] ' + traceback.format_exc())
        try:
            self._build_schema_resolver_stubs(application)
        except Exception as e:
            warning('[GraphQL Application] Error in end_application_create_objects (resolver stubs): ' + str(e))
            debug('[GraphQL Application] ' + traceback.format_exc())
        # All create_link calls must also happen here (not in end_application), per CAST API rules.
        # Order matters: link methods that depend on _build_* dicts come after those builds above.
        try:
            info('[GraphQL Application] Starting cross-technology link creation')
            self._link_client_to_schema(application)
            self._link_schema_to_backend(application)
            # _link_schema_to_nodejs_resolvers uses _schema_resolver_stubs (built above)
            self._link_schema_to_nodejs_resolvers(application)
            # _link_resolvers_to_services uses _resolver_link_targets (built by _build_resolver_link_targets above)
            self._link_resolvers_to_services(application)
            info('[GraphQL Application] Cross-technology link creation complete')
        except Exception as e:
            warning('[GraphQL Application] Error in end_application_create_objects (links): ' + str(e))
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

        Links TsGqlQuery/TsGqlMutation/TsGqlSubscription (TypeScript) and
        JsGqlQuery/JsGqlMutation/JsGqlSubscription (JavaScript) objects to
        GraphQLField objects from the schema.

        Linking logic:
        - One search_objects() call for efficiency, filtered into separate Ts/Js lists
        - Builds an index of schema fields (Query, Mutation, Subscription types)
        - For each client object, extracts the 'fieldsSelected' property
        - Creates a USE link between client and each corresponding schema field

        Example:
            Client: TsGqlQuery with fieldsSelected="users,posts"
            → Creates 2 USE links to Query.users and Query.posts

        Args:
            application: CAST Application object
        """
        info('[GraphQL Application] ========================================')
        info('[GraphQL Application] Starting client-to-schema linking')
        info('[GraphQL Application] ========================================')

        # Single search call for efficiency; split into separate Ts/Js lists per operation type
        all_objects = list(application.search_objects(load_properties=True))

        ts_client_queries       = [o for o in all_objects if o.get_type() == 'TsGqlQuery']
        js_client_queries       = [o for o in all_objects if o.get_type() == 'JsGqlQuery']
        ts_client_mutations     = [o for o in all_objects if o.get_type() == 'TsGqlMutation']
        js_client_mutations     = [o for o in all_objects if o.get_type() == 'JsGqlMutation']
        ts_client_subscriptions = [o for o in all_objects if o.get_type() == 'TsGqlSubscription']
        js_client_subscriptions = [o for o in all_objects if o.get_type() == 'JsGqlSubscription']

        info('[GraphQL Application] Found ' + str(len(ts_client_queries)) + ' TsGqlQuery, ' +
             str(len(js_client_queries)) + ' JsGqlQuery objects')
        info('[GraphQL Application] Found ' + str(len(ts_client_mutations)) + ' TsGqlMutation, ' +
             str(len(js_client_mutations)) + ' JsGqlMutation objects')
        info('[GraphQL Application] Found ' + str(len(ts_client_subscriptions)) + ' TsGqlSubscription, ' +
             str(len(js_client_subscriptions)) + ' JsGqlSubscription objects')

        total_clients = (len(ts_client_queries) + len(js_client_queries) +
                         len(ts_client_mutations) + len(js_client_mutations) +
                         len(ts_client_subscriptions) + len(js_client_subscriptions))
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

        for client_obj in ts_client_queries + js_client_queries:
            links_created += self._link_client_to_fields(client_obj, schema_queries, 'Query')

        for client_obj in ts_client_mutations + js_client_mutations:
            links_created += self._link_client_to_fields(client_obj, schema_mutations, 'Mutation')

        for client_obj in ts_client_subscriptions + js_client_subscriptions:
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
            The fieldsSelected property is stored as a comma-separated string.
            Unresolved field placeholders are pre-created in end_application_create_objects
            and stored in self._unresolved_schema_fields.
        """
        links_created = 0

        try:
            # Get the property value
            fields_selected_raw = client_obj.get_property('GraphQL_Client_Definition.fieldsSelected')

            if not fields_selected_raw:
                return 0

            # The property is saved as a comma-separated string, split it into a list
            if isinstance(fields_selected_raw, str):
                fields_selected = [f.strip() for f in fields_selected_raw.split(',')]
            else:
                fields_selected = fields_selected_raw

            for field_name in fields_selected:
                if field_name in schema_fields:
                    schema_obj = schema_fields[field_name]
                    create_link('useLink', client_obj, schema_obj)
                    links_created += 1
                else:
                    # Links to UnresolvedSchemaField are created in end_application_create_objects
                    # (_link_client_to_unresolved_fields), not here, because CAST requires
                    # create_link on custom objects to happen during that phase.
                    debug('[GraphQL Application] Field not in schema (handled as unresolved): "' + field_name + '"')

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
        java_methods = [obj for obj in application.search_objects(load_properties=True) if obj.get_type() == 'JV_METHOD']

        info('[GraphQL Application] Found ' + str(len(java_methods)) + ' JV_METHOD objects')
        
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

        for type_obj in graphql_types:
            type_name = type_obj.get_name()

            if type_name == 'Query':
                type_obj.load_children()
                for field_obj in type_obj.get_children():
                    if field_obj.get_type() == 'GraphQLField':
                        field_name = field_obj.get_name()
                        schema_queries[field_name] = field_obj

            elif type_name == 'Mutation':
                type_obj.load_children()
                for field_obj in type_obj.get_children():
                    if field_obj.get_type() == 'GraphQLField':
                        field_name = field_obj.get_name()
                        schema_mutations[field_name] = field_obj

            elif type_name == 'Subscription':
                type_obj.load_children()
                for field_obj in type_obj.get_children():
                    if field_obj.get_type() == 'GraphQLField':
                        field_name = field_obj.get_name()
                        schema_subscriptions[field_name] = field_obj
        
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

                # Get parent class of the Java method
                parent_class = self._get_parent(java_method, application)

                # Check if parent class has @Controller annotation
                if parent_class:
                    parent_annotations = []
                    try:
                        parent_annotations = parent_class.get_property("CAST_Java_AnnotationMetrics.Annotation")
                    except Exception as e:
                        debug('[GraphQL Application] Could not load parent class annotations: ' + str(e))

                    # Skip if parent class doesn't have @Controller annotation
                    has_controller = any('@Controller' in str(ann) for ann in parent_annotations) if parent_annotations else False
                    if not has_controller:
                        continue
                else:
                    continue

                # Get method annotations to reduce false positives
                annotations = []
                try:
                    annotations = java_method.get_property("CAST_Java_AnnotationMetrics.Annotation")
                except Exception as e:
                    debug('[GraphQL Application] Could not load method annotations: ' + str(e))
                
                # Try to match with Query fields first
                if method_name in schema_queries:
                    # Check if method has @QueryMapping annotation
                    has_query_mapping = any('@QueryMapping' in str(ann) for ann in annotations) if annotations else False

                    if has_query_mapping:
                        schema_obj = schema_queries[method_name]
                        create_link('callLink', schema_obj, java_method)
                        links_created += 1
                        queries_matched += 1

                # Try to match with Mutation fields
                elif method_name in schema_mutations:
                    # Check if method has @MutationMapping annotation
                    has_mutation_mapping = any('@MutationMapping' in str(ann) for ann in annotations) if annotations else False

                    if has_mutation_mapping:
                        schema_obj = schema_mutations[method_name]
                        create_link('callLink', schema_obj, java_method)
                        links_created += 1
                        mutations_matched += 1

                # Try to match with Subscription fields
                elif method_name in schema_subscriptions:
                    # Check if method has @SubscriptionMapping annotation
                    has_subscription_mapping = any('@SubscriptionMapping' in str(ann) for ann in annotations) if annotations else False

                    if has_subscription_mapping:
                        schema_obj = schema_subscriptions[method_name]
                        create_link('callLink', schema_obj, java_method)
                        links_created += 1
                        subscriptions_matched += 1

                else:
                    # No match found - this is expected for most Java methods
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

    # All 8 resolver type names (TS + JS)
    _RESOLVER_TYPES = frozenset({
        'TsNodeJsResolverQuery', 'TsNodeJsResolverMutation',
        'TsNodeJsResolverSubscription', 'TsNodeJsResolverCustom',
        'JsNodeJsResolverQuery', 'JsNodeJsResolverMutation',
        'JsNodeJsResolverSubscription', 'JsNodeJsResolverCustom',
    })

    # Service method types to index for resolver → service linking
    _SERVICE_METHOD_TYPES = frozenset({
        'CAST_TS_Method',
        'CAST_HTML5_JavaScript_Method',
        'CAST_HTML5_JavaScript_Generic_Method',
    })

    def _link_schema_to_nodejs_resolvers(self, application):
        """
        Create CALL links from GraphQL schema fields to Node.js resolver functions.

        Targets all 8 resolver types (Ts/JsNodeJsResolver{Query,Mutation,Subscription,Custom})
        created by graphql_nodejs_analyzer.py and graphql_typescript_analyzer.py.

        Matching logic:
          Resolver with operationType='Query'  + fieldName='users'
            → callLink ← GraphQLField 'users' under GraphQLType 'Query'
          Custom resolvers use operationType (e.g. 'User') to find the correct type.

        Link direction: GraphQLField -callLink-> Resolver

        Args:
            application: CAST Application object
        """
        info('[GraphQL Application] ========================================')
        info('[GraphQL Application] Starting schema-to-NodeJs resolver linking')
        info('[GraphQL Application] ========================================')

        # Find all resolver objects (all 8 types) with their properties loaded
        nodejs_resolvers = [
            obj for obj in application.search_objects(load_properties=True)
            if obj.get_type() in self._RESOLVER_TYPES
        ]

        info('[GraphQL Application] Found ' + str(len(nodejs_resolvers))
             + ' NodeJs resolver object(s)')

        if not nodejs_resolvers:
            info('[GraphQL Application] No NodeJs resolver objects — skipping')
            return

        # Build schema field index: {type_name: {field_name: GraphQLField_obj}}
        # Includes all GraphQL types (Query, Mutation, Subscription, AND custom types)
        schema_fields_by_type = {}  # e.g. {'Query': {'getUsers': obj}, 'User': {'posts': obj}}

        graphql_types = [obj for obj in application.get_objects()
                         if obj.get_type() == 'GraphQLType']

        for type_obj in graphql_types:
            type_name = type_obj.get_name()
            type_obj.load_children()
            fields_dict = {}
            for field_obj in type_obj.get_children():
                if field_obj.get_type() == 'GraphQLField':
                    fields_dict[field_obj.get_name()] = field_obj
            if fields_dict:
                if type_name not in schema_fields_by_type:
                    schema_fields_by_type[type_name] = {}
                schema_fields_by_type[type_name].update(fields_dict)

        total_fields = sum(len(v) for v in schema_fields_by_type.values())
        info('[GraphQL Application] Schema index: '
             + str(len(schema_fields_by_type)) + ' types, '
             + str(total_fields) + ' fields total')

        if not schema_fields_by_type:
            warning('[GraphQL Application] No GraphQL schema fields found — skipping')
            return

        # Match each resolver to its GraphQLField and create callLink
        links_created = 0
        matched_by_type = {}
        not_matched = 0

        for resolver_obj in nodejs_resolvers:
            try:
                op_type    = resolver_obj.get_property(
                    'GraphQL_NodeJs_Resolver.operationType')
                field_name = resolver_obj.get_property(
                    'GraphQL_NodeJs_Resolver.fieldName')

                if not op_type or not field_name:
                    not_matched += 1
                    continue

                type_fields = schema_fields_by_type.get(op_type)
                if type_fields and field_name in type_fields:
                    create_link('callLink', type_fields[field_name], resolver_obj)
                    links_created += 1
                    matched_by_type[op_type] = matched_by_type.get(op_type, 0) + 1
                else:
                    not_matched += 1
                    debug('[GraphQL Application] Resolver not matched: '
                          + str(op_type) + '.' + str(field_name))

            except Exception as e:
                warning('[GraphQL Application] Error linking resolver "'
                        + str(resolver_obj.get_name()) + '": ' + str(e))
                debug('[GraphQL Application] ' + traceback.format_exc())

        # Create callLinks from schema fields to their Unresolved resolver stubs
        # (pre-built in end_application_create_objects for fields with no matching resolver)
        stubs_linked = 0
        schema_resolver_stubs = getattr(self, '_schema_resolver_stubs', {})
        for stub_key, stub_obj in schema_resolver_stubs.items():
            op_type, field_name = stub_key[0], stub_key[1]
            type_fields = schema_fields_by_type.get(op_type, {})
            if field_name in type_fields:
                try:
                    create_link('callLink', type_fields[field_name], stub_obj)
                    stubs_linked += 1
                except Exception as e:
                    warning('[GraphQL Application] Error linking schema field to unresolved resolver "'
                            + op_type + '.' + field_name + '": ' + str(e))

        info('[GraphQL Application] ========================================')
        info('[GraphQL Application] SCHEMA-NODEJS LINKING SUMMARY: Created '
             + str(links_created) + ' CALL links')
        for op_type, count in sorted(matched_by_type.items()):
            info('[GraphQL Application]   - ' + op_type + ' resolvers: '
                 + str(count) + ' linked')
        info('[GraphQL Application]   - Not matched: '
             + str(not_matched) + ' (no corresponding GraphQLField found)')
        if stubs_linked:
            info('[GraphQL Application]   - Unresolved resolver stubs linked: '
                 + str(stubs_linked))
        info('[GraphQL Application] ========================================')

    def _link_client_to_unresolved_fields(self, application):
        """
        Called from end_application_create_objects, AFTER _build_unresolved_schema_fields.

        Creates useLink from each client GQL definition to its UnresolvedSchemaField stubs.
        Must run here (not in end_application) because CAST only allows create_link on
        custom objects during end_application_create_objects.
        """
        if not self._unresolved_schema_fields:
            return

        _CLIENT_TYPES = {
            'TsGqlQuery', 'JsGqlQuery',
            'TsGqlMutation', 'JsGqlMutation',
            'TsGqlSubscription', 'JsGqlSubscription',
        }

        links_created = 0
        for obj in (application.objects()
                    .has_type(list(_CLIENT_TYPES))
                    .load_property('GraphQL_Client_Definition.fieldsSelected')):
            raw = obj.get_property('GraphQL_Client_Definition.fieldsSelected')
            if not raw:
                continue
            for field_name in [f.strip() for f in raw.split(',')]:
                placeholder = self._unresolved_schema_fields.get(field_name)
                if placeholder is not None:
                    try:
                        create_link('useLink', obj, placeholder)
                        links_created += 1
                    except Exception as e:
                        warning('[GraphQL Application] create_link FAILED for UnresolvedSchemaField "'
                                + field_name + '": ' + str(e))

        info('[GraphQL Application] Created ' + str(links_created)
             + ' useLink(s) to UnresolvedSchemaField stubs')

    def _build_unresolved_schema_fields(self, application):
        """
        Called from end_application_create_objects.

        Builds self._unresolved_schema_fields = {field_name → UnresolvedSchemaField CustomObject}
        for every field referenced by a client object (via fieldsSelected) that is not
        present in the GraphQL schema.

        CustomObject.save() is only valid during end_application_create_objects.
        """
        _CLIENT_TYPES = {
            'TsGqlQuery', 'JsGqlQuery',
            'TsGqlMutation', 'JsGqlMutation',
            'TsGqlSubscription', 'JsGqlSubscription',
        }

        # Build schema field name set
        schema_field_names = set()
        for type_obj in application.get_objects():
            if type_obj.get_type() != 'GraphQLType':
                continue
            type_name = type_obj.get_name()
            if type_name not in ('Query', 'Mutation', 'Subscription'):
                continue
            type_obj.load_children()
            for field_obj in type_obj.get_children():
                if field_obj.get_type() == 'GraphQLField':
                    schema_field_names.add(field_obj.get_name())

        # Collect all missing field names across all client objects,
        # tracking the first referencing client object per field (to derive its source file).
        missing_field_first_obj = {}  # field_name → first client KB obj that references it
        for obj in (application.objects()
                    .has_type(list(_CLIENT_TYPES))
                    .load_property('GraphQL_Client_Definition.fieldsSelected')
                    .load_positions()):
            raw = obj.get_property('GraphQL_Client_Definition.fieldsSelected')
            if not raw:
                continue
            fields = [f.strip() for f in raw.split(',')]
            for field_name in fields:
                if field_name and field_name not in schema_field_names:
                    if field_name not in missing_field_first_obj:
                        missing_field_first_obj[field_name] = obj

        # Create one UnresolvedSchemaField CustomObject per missing field name.
        # Parent = source file of the first client object that references the field.
        # set_fullname() is called explicitly to avoid a crash when file.get_fullname() is None.
        for field_name, ref_obj in missing_field_first_obj.items():
            try:
                parent = None
                try:
                    positions = ref_obj.get_positions()
                    if positions:
                        parent = positions[0].file
                except Exception:
                    pass
                unresolved_obj = CustomObject()
                unresolved_obj.set_name(field_name)
                unresolved_obj.set_type('UnresolvedSchemaField')
                if parent is not None:
                    file_fn = parent.get_fullname() or str(parent.get_path())
                    if file_fn:
                        unresolved_obj.set_fullname(file_fn + '.' + field_name)
                    unresolved_obj.set_parent(parent)
                unresolved_obj.save()
                try:
                    if parent is not None and positions:
                        p = positions[0]
                        p.end_line = p.begin_line
                        unresolved_obj.save_position(p)
                except Exception:
                    pass
                self._unresolved_schema_fields[field_name] = unresolved_obj
                debug('[GraphQL Application] Created UnresolvedSchemaField: ' + field_name)
            except Exception as e:
                warning('[GraphQL Application] Could not create UnresolvedSchemaField "'
                        + field_name + '": ' + str(e))

        if self._unresolved_schema_fields:
            info('[GraphQL Application] Created ' + str(len(self._unresolved_schema_fields))
                 + ' UnresolvedSchemaField stub(s)')

    def _build_schema_resolver_stubs(self, application):
        """
        Called from end_application_create_objects.

        For each root schema field (Query/Mutation/Subscription) that has no matching
        NodeJS resolver in the KB, creates a TsUnresolvedNodeJsResolver or
        JsUnresolvedNodeJsResolver stub so that the link
            GraphQLField -callLink-> Unresolved*NodeJsResolver
        can be created in _link_schema_to_nodejs_resolvers.

        Only runs when the application contains at least one NodeJS resolver (Ts or Js).
        Ts and Js stubs are created independently: if the app has Ts resolvers but a
        given field has no Ts resolver, a TsUnresolvedNodeJsResolver is created for that
        field (same logic for Js).

        Populates self._schema_resolver_stubs:
            (op_type, field_name, 'ts'|'js') → CustomObject
        """
        _ROOT_TYPES = frozenset({'Query', 'Mutation', 'Subscription'})
        _TS_RESOLVER_TYPES = frozenset(t for t in self._RESOLVER_TYPES if t.startswith('Ts'))
        _JS_RESOLVER_TYPES = frozenset(t for t in self._RESOLVER_TYPES if t.startswith('Js'))

        # Build matched sets and detect language presence in one pass
        ts_matched = set()   # (op_type, field_name) covered by a Ts resolver
        js_matched = set()   # (op_type, field_name) covered by a Js resolver
        has_ts = False
        has_js = False

        for obj in (application.objects()
                    .load_property('GraphQL_NodeJs_Resolver.operationType')
                    .load_property('GraphQL_NodeJs_Resolver.fieldName')):
            obj_type = obj.get_type()
            op_type = obj.get_property('GraphQL_NodeJs_Resolver.operationType')
            field_name = obj.get_property('GraphQL_NodeJs_Resolver.fieldName')
            if not op_type or not field_name or op_type not in _ROOT_TYPES:
                continue
            if obj_type in _TS_RESOLVER_TYPES:
                has_ts = True
                ts_matched.add((op_type, field_name))
            elif obj_type in _JS_RESOLVER_TYPES:
                has_js = True
                js_matched.add((op_type, field_name))

        if not has_ts and not has_js:
            return  # No NodeJS resolvers in this application — nothing to do

        info('[GraphQL Application] Building schema resolver stubs '
             '(has_ts=' + str(has_ts) + ', has_js=' + str(has_js) + ')')

        # Iterate root schema fields and create stubs for any that are unmatched
        stubs_created = 0
        for type_obj in application.get_objects():
            if type_obj.get_type() != 'GraphQLType':
                continue
            type_name = type_obj.get_name()
            if type_name not in _ROOT_TYPES:
                continue
            type_obj.load_children()
            for field_obj in type_obj.get_children():
                if field_obj.get_type() != 'GraphQLField':
                    continue
                field_name = field_obj.get_name()

                if has_ts and (type_name, field_name) not in ts_matched:
                    try:
                        stub = CustomObject()
                        stub.set_name(field_name)
                        stub.set_type('TsUnresolvedNodeJsResolver')
                        # Use the schema file as parent (not field_obj) so that the
                        # callLink from field_obj → stub is not a parent→child link,
                        # which CAST Imaging would suppress from the callers view.
                        field_positions = []
                        try:
                            field_positions = field_obj.get_positions() or []
                        except Exception:
                            pass
                        stub_parent = field_positions[0].file if field_positions else type_obj
                        stub.set_parent(stub_parent)
                        stub.save()
                        try:
                            if field_positions:
                                fp = field_positions[0]
                                stub.save_position(fp)
                        except Exception:
                            pass
                        self._schema_resolver_stubs[(type_name, field_name, 'ts')] = stub
                        stubs_created += 1
                    except Exception as e:
                        warning('[GraphQL Application] Could not create TsUnresolvedNodeJsResolver for "'
                                + type_name + '.' + field_name + '": ' + str(e))

                if has_js and (type_name, field_name) not in js_matched:
                    try:
                        stub = CustomObject()
                        stub.set_name(field_name)
                        stub.set_type('JsUnresolvedNodeJsResolver')
                        field_positions = []
                        try:
                            field_positions = field_obj.get_positions() or []
                        except Exception:
                            pass
                        stub_parent = field_positions[0].file if field_positions else type_obj
                        stub.set_parent(stub_parent)
                        stub.save()
                        try:
                            if field_positions:
                                fp = field_positions[0]
                                stub.save_position(fp)
                        except Exception:
                            pass
                        self._schema_resolver_stubs[(type_name, field_name, 'js')] = stub
                        stubs_created += 1
                    except Exception as e:
                        warning('[GraphQL Application] Could not create JsUnresolvedNodeJsResolver for "'
                                + type_name + '.' + field_name + '": ' + str(e))

        if stubs_created:
            info('[GraphQL Application] Created ' + str(stubs_created)
                 + ' Unresolved NodeJS resolver stub(s)')

    def _build_resolver_link_targets(self, application):
        """
        Called from end_application_create_objects.

        Builds self._resolver_link_targets = {resolver_fullname → target_obj},
        where target_obj is either a real service KB object or a freshly created
        CustomObject (TsUnresolvedServiceMethod / JsUnresolvedServiceMethod).
        CustomObject.save() is only valid during end_application_create_objects.
        """
        # Build method index: (file_path, class_name_or_None, method_name, index) → KB object
        method_index = {}
        _obj_literal_counters = {}
        for obj in application.objects().load_positions():
            try:
                obj_type = obj.get_type()
                if obj_type not in self._SERVICE_METHOD_TYPES:
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

        info('[GraphQL Application] Service method index: '
             + str(len(method_index)) + ' entries (built in create_objects phase)')

        _resolver_query = (application.objects()
                           .load_property('GraphQL_NodeJs_Resolver.serviceFilePath')
                           .load_property('GraphQL_NodeJs_Resolver.serviceMethod')
                           .load_property('GraphQL_NodeJs_Resolver.serviceClass')
                           .load_positions())
        _diag_total = 0
        _diag_no_service = 0
        for obj in _resolver_query:
            try:
                if obj.get_type() not in self._RESOLVER_TYPES:
                    continue
                _diag_total += 1
                resolver_fullname = obj.get_fullname()
                service_file_path = obj.get_property('GraphQL_NodeJs_Resolver.serviceFilePath')
                service_method = obj.get_property('GraphQL_NodeJs_Resolver.serviceMethod')
                if not service_method:
                    _diag_no_service += 1
                    continue
                service_class = obj.get_property('GraphQL_NodeJs_Resolver.serviceClass')

                # Attempt 1: class-based match (with known file path)
                target_obj = None
                if service_file_path and service_class:
                    target_obj = method_index.get(
                        (service_file_path, service_class, service_method, 0))

                # Attempt 2: object-literal fallback (only if unambiguous)
                if target_obj is None and service_file_path:
                    ol_count = _obj_literal_counters.get(
                        (service_file_path, service_method), 0)
                    if ol_count == 1:
                        target_obj = method_index.get(
                            (service_file_path, None, service_method, 1))

                # Attempt 3: global search by class+method when file path is
                # unknown (e.g. JS resolvers using context-injected services
                # that are not imported — no serviceFilePath available).
                # Case-insensitive on class name: JS resolvers store camelCase
                # context keys (e.g. "userService") while method_index has
                # PascalCase class names (e.g. "UserService").
                if target_obj is None and not service_file_path and service_class:
                    sc_lower = service_class.lower()
                    for key, candidate in method_index.items():
                        if key[1] and key[1].lower() == sc_lower and key[2] == service_method:
                            target_obj = candidate
                            break

                if target_obj is None:
                    # Create unresolved placeholder — allowed here in create_objects phase
                    type_prefix = 'Ts' if obj.get_type().startswith('Ts') else 'Js'
                    unresolved_type = type_prefix + 'UnresolvedServiceMethod'
                    if service_class:
                        instance_name = service_class[0].lower() + service_class[1:]
                        unresolved_name = instance_name + '.' + service_method
                    else:
                        unresolved_name = service_method
                    try:
                        unresolved_obj = CustomObject()
                        unresolved_obj.set_name(unresolved_name)
                        unresolved_obj.set_type(unresolved_type)
                        # Use the resolver's source file as parent (not the resolver itself)
                        # so that callLink from resolver → stub is not a parent→child link,
                        # which CAST Imaging would suppress from the callers view.
                        resolver_positions = []
                        try:
                            resolver_positions = obj.get_positions() or []
                        except Exception:
                            pass
                        stub_parent = None
                        if resolver_positions:
                            try:
                                f = resolver_positions[0].file
                                if f is not None and f.get_fullname() is not None:
                                    stub_parent = f
                            except Exception:
                                pass
                        if stub_parent is None and obj.get_fullname() is not None:
                            stub_parent = obj
                        if stub_parent is None:
                            warning('[GraphQL Application] Skipping unresolved object "'
                                    + unresolved_name + '": no valid parent with fullname')
                            continue
                        unresolved_obj.set_parent(stub_parent)
                        unresolved_obj.save()
                        try:
                            if resolver_positions:
                                rp = resolver_positions[0]
                                unresolved_obj.save_position(rp)
                        except Exception:
                            pass
                        target_obj = unresolved_obj
                    except Exception as e:
                        warning('[GraphQL Application] Could not create unresolved object "'
                                + unresolved_name + '": ' + str(e))

                if target_obj is not None:
                    self._resolver_link_targets[resolver_fullname] = target_obj

            except Exception as e:
                warning('[GraphQL Application] Error building resolver link target: ' + str(e))

        info('[GraphQL Application] build_resolver_link_targets: '
             + str(_diag_total) + ' resolver(s) seen, '
             + str(_diag_no_service) + ' skipped (no serviceFilePath/serviceMethod), '
             + str(len(self._resolver_link_targets)) + ' stored in _resolver_link_targets')

    def _link_resolvers_to_services(self, application):
        """
        Create CALL links from Node.js resolver functions to service methods (or
        their unresolved placeholders pre-created in end_application_create_objects).
        """
        info('[GraphQL Application] ========================================')
        info('[GraphQL Application] Starting resolver-to-service linking')
        info('[GraphQL Application] ========================================')

        if not hasattr(self, '_resolver_link_targets'):
            warning('[GraphQL Application] _resolver_link_targets not initialised — skipping')
            return

        links_created = 0
        not_matched = 0

        _resolver_query = (application.objects()
                           .load_property('GraphQL_NodeJs_Resolver.serviceFilePath')
                           .load_property('GraphQL_NodeJs_Resolver.serviceMethod')
                           .load_positions())
        for obj in _resolver_query:
            try:
                if obj.get_type() not in self._RESOLVER_TYPES:
                    continue
                service_file_path = obj.get_property('GraphQL_NodeJs_Resolver.serviceFilePath')
                service_method = obj.get_property('GraphQL_NodeJs_Resolver.serviceMethod')
                if not service_file_path or not service_method:
                    not_matched += 1
                    continue

                target_obj = self._resolver_link_targets.get(obj.get_fullname())
                if target_obj is not None:
                    create_link('callLink', obj, target_obj)
                    links_created += 1
                else:
                    not_matched += 1
                    debug('[GraphQL Application] No target for resolver: '
                          + str(obj.get_fullname()))

            except Exception as e:
                warning('[GraphQL Application] Error in resolver→service link: ' + str(e))

        info('[GraphQL Application] ========================================')
        info('[GraphQL Application] RESOLVER-SERVICE LINKING SUMMARY: '
             + str(links_created) + ' CALL links created')
        info('[GraphQL Application]   - Service methods not found/missing: '
             + str(not_matched))
        info('[GraphQL Application] ========================================')