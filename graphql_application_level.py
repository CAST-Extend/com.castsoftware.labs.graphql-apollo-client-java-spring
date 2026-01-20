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
    
    def _get_parent(self, obj, application):
        """
        Get the parent object by extracting the parent name from the fullname.
        
        :param obj: The object whose parent we want to retrieve
        :param application: The application containing the object
        :return: The parent object or None if no parent is found
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
        """Link a client object to schema fields based on fieldsSelected property."""
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
                
                else:
                    # No match found - this is expected for most Java methods
                    debug('[GraphQL Application] No match for Java method: "' + method_name + '"')
                    not_matched += 1
                    
            except Exception as e:
                warning('[GraphQL Application] !!! ERROR linking Java method "' + java_method.get_name() + '": ' + str(e))
                debug('[GraphQL Application] ' + traceback.format_exc())
        
        info('[GraphQL Application] ========================================')
        info('[GraphQL Application] BACKEND LINKING SUMMARY: Created ' + str(links_created) + ' CALL links')
        info('[GraphQL Application]   - Query methods:    ' + str(queries_matched) + ' linked')
        info('[GraphQL Application]   - Mutation methods: ' + str(mutations_matched) + ' linked')
        info('[GraphQL Application]   - Not matched:      ' + str(not_matched) + ' (expected - most Java methods are not GraphQL resolvers)')
        info('[GraphQL Application] ========================================')

    def _link_frontend_to_backend(self, application):
        """
        Create CALL links between GraphQL Apollo hook requests and Java backend methods.
        
        ARCHITECTURE:
        React Component → (callLink) → GraphQLQueryRequest → (callLink) → JV_METHOD
                                              ↓ (useLink)
                                        GraphQLClientQuery
        
        The Apollo hook calls (GraphQLQueryRequest/MutationRequest) are what actually
        execute the GraphQL operations, so they should have the callLink to backend methods.
        
        Matching logic:
        - GraphQLQueryRequest uses fieldsSelected from its linked GraphQLClientQuery
        - Match fieldsSelected with Java method names
        - Example: Request → (fieldsSelected="users") → users() Java method
        
        Args:
            application: CAST Application object
        """
        info('[GraphQL Application] ========================================')
        info('[GraphQL Application] Starting frontend-to-backend link creation (APOLLO REQUESTS)')
        info('[GraphQL Application] ========================================')
        
        # Find all Apollo hook request objects - load properties in case we need them
        debug('[GraphQL Application] Searching for Apollo hook requests...')
        query_requests = [obj for obj in application.search_objects(load_properties=True) if obj.get_type() == 'GraphQLQueryRequest']
        lazy_query_requests = [obj for obj in application.search_objects(load_properties=True) if obj.get_type() == 'GraphQLLazyQueryRequest']
        mutation_requests = [obj for obj in application.search_objects(load_properties=True) if obj.get_type() == 'GraphQLMutationRequest']
        subscription_requests = [obj for obj in application.search_objects(load_properties=True) if obj.get_type() == 'GraphQLSubscriptionRequest']
        
        info('[GraphQL Application] Found ' + str(len(query_requests)) + ' GraphQLQueryRequest objects')
        info('[GraphQL Application] Found ' + str(len(lazy_query_requests)) + ' GraphQLLazyQueryRequest objects')
        info('[GraphQL Application] Found ' + str(len(mutation_requests)) + ' GraphQLMutationRequest objects')
        info('[GraphQL Application] Found ' + str(len(subscription_requests)) + ' GraphQLSubscriptionRequest objects')
        
        all_requests = query_requests + lazy_query_requests + mutation_requests + subscription_requests
        if len(all_requests) == 0:
            warning('[GraphQL Application] No Apollo hook requests found - nothing to link')
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
            # Reload the method with properties to get annotations
            reloaded = list(application.search_objects(name=method_name, category='JV_METHOD', load_properties=True))
            if reloaded:
                # Add all reloaded methods with this name (handles overloads)
                java_methods_by_name[method_name].extend(reloaded)
            else:
                # Fallback: keep the original method even without properties
                java_methods_by_name[method_name].append(method)
        
        info('[GraphQL Application] Java method index complete: ' + str(len(java_methods_by_name)) + ' unique method names')
        
        # Build index of GraphQLClient definitions by name for reverse lookup
        info('[GraphQL Application] Building client definition index...')
        client_definitions = {}
        for obj in application.search_objects(load_properties=True):
            obj_type = obj.get_type()
            if obj_type in ['GraphQLClientQuery', 'GraphQLClientMutation', 'GraphQLClientSubscription']:
                client_definitions[obj.get_fullname()] = obj
        info('[GraphQL Application] Client definition index complete: ' + str(len(client_definitions)) + ' definitions')
        
        info('[GraphQL Application] ----------------------------------------')
        info('[GraphQL Application] Matching Apollo requests to Java methods...')
        info('[GraphQL Application] ----------------------------------------')
        
        # Match Apollo hook requests to Java methods
        links_created = 0
        requests_matched = 0
        not_matched = 0
        multiple_matches = 0
        
        # Process all request types
        for request_obj in all_requests:
            try:
                request_name = request_obj.get_name()
                request_type = request_obj.get_type()
                info('[GraphQL Application] >>> Processing ' + request_type + ': "' + request_name + '"')
                
                # Step 1: Find the GraphQLClient definition this request uses (via useLink)
                fields_selected = None
                client_def = None
                
                # Get all outgoing useLinks from this request
                info('[GraphQL Application]   - Searching for useLinks from this request...')
                try:
                    # Application level API: use application.links().has_caller(request_obj)
                    outgoing_links = list(application.links().has_caller([request_obj]))
                    info('[GraphQL Application]   - Found ' + str(len(outgoing_links)) + ' total outgoing links')
                    
                    for idx, link in enumerate(outgoing_links):
                        # EnlightenLink API: use get_type_names() which returns a list like ['use']
                        link_types = link.get_type_names()
                        info('[GraphQL Application]   - Link ' + str(idx) + ': types=' + str(link_types))
                        
                        if 'use' in link_types:
                            linked_obj = link.get_callee()  # Get the target object (callee)
                            info('[GraphQL Application]     - useLink found! Target object: ' + str(linked_obj))
                            if linked_obj:
                                linked_type = linked_obj.get_type()
                                linked_name = linked_obj.get_name()
                                info('[GraphQL Application]     - Linked object type: ' + linked_type + ', name: "' + linked_name + '"')
                                
                                if linked_type in ['GraphQLClientQuery', 'GraphQLClientMutation', 'GraphQLClientSubscription']:
                                    client_def = linked_obj
                                    info('[GraphQL Application]   - ✓ Found linked client definition: "' + client_def.get_name() + '" [' + linked_type + ']')
                                    break
                except Exception as e:
                    warning('[GraphQL Application]   - ERROR traversing useLinks: ' + str(e))
                    import traceback
                    warning('[GraphQL Application]   - ' + traceback.format_exc())
                
                # Step 2: Extract fieldsSelected from the client definition
                if client_def:
                    info('[GraphQL Application]   - Extracting fieldsSelected from client definition...')
                    try:
                        # IMPORTANT: Re-fetch object with properties loaded
                        # Application level objects from links don't have properties loaded
                        obj_name = client_def.get_name()
                        obj_type = client_def.get_type()
                        reloaded_objs = list(application.search_objects(name=obj_name, category=obj_type, load_properties=True))
                        
                        if reloaded_objs:
                            client_def = reloaded_objs[0]
                            info('[GraphQL Application]   - Re-fetched client definition with properties loaded')
                        else:
                            warning('[GraphQL Application]   - Could not re-fetch client definition with properties')
                            client_def = None
                        
                        if client_def:
                            fields_selected_raw = client_def.get_property('GraphQL_Client_Definition.fieldsSelected')
                            if fields_selected_raw:
                                info('[GraphQL Application]   - Raw fieldsSelected: "' + str(fields_selected_raw) + '"')
                                # Parse comma-separated list of fields
                                fields = [f.strip() for f in str(fields_selected_raw).split(',')]
                                if fields:
                                    # Use the first field for matching (most common case)
                                    fields_selected = fields[0]
                                    info('[GraphQL Application]   - ✓ Using first field for matching: "' + fields_selected + '"')
                            else:
                                warning('[GraphQL Application]   - fieldsSelected property is empty or None')
                    except Exception as e:
                        warning('[GraphQL Application]   - ERROR getting fieldsSelected property: ' + str(e))
                else:
                    warning('[GraphQL Application]   - ✗ No client definition found via useLink')
                
                # Fallback: try to extract from request name (format: "useQuery:GET_USERS")
                if not fields_selected:
                    info('[GraphQL Application]   - No fieldsSelected found, trying name-based extraction as fallback...')
                    if ':' in request_name:
                        parts = request_name.split(':')
                        if len(parts) >= 2:
                            # Try to extract from variable name (last part)
                            var_name = parts[-1]
                            info('[GraphQL Application]   - Extracted variable name from request: "' + var_name + '"')
                            # This is a fallback, won't work for GET_USERS -> users mapping
                            info('[GraphQL Application]   - WARNING: Fallback won\'t work for camelCase mismatch (GET_USERS != users)')
                    else:
                        warning('[GraphQL Application]   - Cannot extract field name from request: "' + request_name + '"')
                
                # Step 3: Match with Java methods by field name
                if fields_selected and fields_selected in java_methods_by_name:
                    matched_methods = java_methods_by_name[fields_selected]
                    debug('[GraphQL Application]   - Found ' + str(len(matched_methods)) + ' candidate method(s) named "' + fields_selected + '"')
                    
                    # Filter methods using same logic as backend-to-schema linking
                    valid_methods = []
                    for java_method in matched_methods:
                        # Get parent class of the Java method
                        parent_class = self._get_parent(java_method, application)
                        
                        # Check if parent class has @Controller annotation
                        if not parent_class:
                            debug('[GraphQL Application]   - Skipping method (no parent class): ' + java_method.get_fullname())
                            continue
                        
                        parent_annotations = []
                        try:
                            parent_annotations = parent_class.get_property("CAST_Java_AnnotationMetrics.Annotation")
                        except:
                            pass
                        
                        has_controller = any('@Controller' in str(ann) for ann in parent_annotations) if parent_annotations else False
                        if not has_controller:
                            debug('[GraphQL Application]   - Skipping method (parent lacks @Controller): ' + java_method.get_fullname())
                            continue
                        
                        # Get method annotations
                        annotations = []
                        try:
                            annotations = java_method.get_property("CAST_Java_AnnotationMetrics.Annotation")
                        except:
                            pass
                        
                        # Check for correct GraphQL annotation based on request type
                        is_valid = False
                        if request_type in ['GraphQLQueryRequest', 'GraphQLLazyQueryRequest']:
                            has_query_mapping = any('@QueryMapping' in str(ann) for ann in annotations) if annotations else False
                            if has_query_mapping:
                                is_valid = True
                                debug('[GraphQL Application]   - ✓ Valid query resolver: ' + java_method.get_fullname())
                        elif request_type == 'GraphQLMutationRequest':
                            has_mutation_mapping = any('@MutationMapping' in str(ann) for ann in annotations) if annotations else False
                            if has_mutation_mapping:
                                is_valid = True
                                debug('[GraphQL Application]   - ✓ Valid mutation resolver: ' + java_method.get_fullname())
                        elif request_type == 'GraphQLSubscriptionRequest':
                            has_subscription_mapping = any('@SubscriptionMapping' in str(ann) for ann in annotations) if annotations else False
                            if has_subscription_mapping:
                                is_valid = True
                                debug('[GraphQL Application]   - ✓ Valid subscription resolver: ' + java_method.get_fullname())
                        
                        if is_valid:
                            valid_methods.append(java_method)
                        else:
                            debug('[GraphQL Application]   - Skipping method (no matching GraphQL annotation): ' + java_method.get_fullname())
                    
                    # Create links only to valid GraphQL resolvers
                    if valid_methods:
                        if len(valid_methods) > 1:
                            warning('[GraphQL Application] Multiple valid GraphQL resolvers found with name "' + fields_selected + '": ' + str(len(valid_methods)) + ' matches (linking to all)')
                            multiple_matches += 1
                        
                        # Create callLink from REQUEST to BACKEND METHOD
                        for java_method in valid_methods:
                            info('[GraphQL Application] >>> CREATING LINK: callLink')
                            info('[GraphQL Application]     FROM (request):  ' + str(request_obj.get_fullname()) + ' [' + request_type + ']')
                            info('[GraphQL Application]     TO (backend):    ' + str(java_method.get_fullname()) + ' [' + java_method.get_type() + ']')
                            info('[GraphQL Application]     MATCHED FIELD:   "' + fields_selected + '"')
                            create_link('callLink', request_obj, java_method)
                            links_created += 1
                        
                        requests_matched += 1
                    else:
                        debug('[GraphQL Application] No valid GraphQL resolvers found for field: "' + fields_selected + '" (found methods but none with correct annotations)')
                        not_matched += 1
                else:
                    debug('[GraphQL Application] No Java method match for request field: "' + str(fields_selected) + '"')
                    not_matched += 1
                    
            except Exception as e:
                warning('[GraphQL Application] !!! ERROR linking request "' + request_obj.get_name() + '": ' + str(e))
                debug('[GraphQL Application] ' + traceback.format_exc())
        
        info('[GraphQL Application] ========================================')
        info('[GraphQL Application] FRONTEND-BACKEND LINKING SUMMARY: Created ' + str(links_created) + ' CALL links')
        info('[GraphQL Application]   - Requests matched:     ' + str(requests_matched) + ' Apollo hooks linked to backend')
        info('[GraphQL Application]   - Not matched:          ' + str(not_matched))
        if multiple_matches > 0:
            info('[GraphQL Application]   - Multiple matches:     ' + str(multiple_matches) + ' requests linked to multiple methods')
        info('[GraphQL Application] ========================================')