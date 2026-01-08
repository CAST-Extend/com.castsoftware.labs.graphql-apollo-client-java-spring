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
from cast.application import ApplicationLevelExtension, ReferenceFinder
from cast.application import open_source_file
import traceback


class GraphQLApplicationExtension(ApplicationLevelExtension):
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
            from cast.analysers import log
            from cast.application import create_link
            
            log.info('[GraphQL Application] Starting cross-technology link creation')
            
            # Create links between client operations and schema objects
            self._link_client_to_schema(application)
            
            log.info('[GraphQL Application] Cross-technology link creation complete')
            
        except Exception as e:
            from cast.analysers import log
            log.warning('[GraphQL Application] Error in end_application: ' + str(e))
            log.debug('[GraphQL Application] ' + traceback.format_exc())
    
    def _link_client_to_schema(self, application):
        """
        Create USE links between GraphQL client operations and schema objects.
        
        Finds all GraphQLClientQuery and GraphQLClientMutation objects,
        then links them to corresponding GraphQLQuery and GraphQLMutation
        objects from the schema.
        
        Args:
            application: CAST Application object
        """
        from cast.analysers import log
        from cast.application import create_link
        
        # Find all client operations
        client_queries = list(application.objects().has_type('GraphQLClientQuery'))
        client_mutations = list(application.objects().has_type('GraphQLClientMutation'))
        
        total_clients = len(client_queries) + len(client_mutations)
        if total_clients == 0:
            log.debug('[GraphQL Application] No client operations found')
            return
        
        log.info('[GraphQL Application] Found ' + str(total_clients) + ' client operations to link')
        
        # Build index of schema objects for faster lookup
        # In GraphQL schema, Query and Mutation are GraphQLType objects
        # Their fields (user, users, createUser) are GraphQLField objects that are children
        schema_queries = {}
        schema_mutations = {}
        
        # Find the Query and Mutation type objects
        query_type = None
        mutation_type = None
        
        for obj in application.objects().has_type('GraphQLType'):
            obj_name = obj.get_name()
            if obj_name == 'Query':
                query_type = obj
                log.debug('[GraphQL Application] Found Query type: ' + str(obj.get_fullname()))
            elif obj_name == 'Mutation':
                mutation_type = obj
                log.debug('[GraphQL Application] Found Mutation type: ' + str(obj.get_fullname()))
        
        # Now find all GraphQLField objects and check their parent
        for obj in application.objects().has_type('GraphQLField'):
            field_name = obj.get_name()
            parent = obj.get_parent()
            
            if parent:
                # Check if this field belongs to Query or Mutation type
                if query_type and parent.get_guid() == query_type.get_guid():
                    schema_queries[field_name] = obj
                    log.debug('[GraphQL Application] Indexed query field: ' + field_name)
                elif mutation_type and parent.get_guid() == mutation_type.get_guid():
                    schema_mutations[field_name] = obj
                    log.debug('[GraphQL Application] Indexed mutation field: ' + field_name)
        
        log.info('[GraphQL Application] Schema index: ' + str(len(schema_queries)) + 
                ' query fields, ' + str(len(schema_mutations)) + ' mutation fields')
        
        # Link client queries to schema queries
        # Object names are in format "query:fieldName" - we parse to extract fieldName
        links_created = 0
        for client_obj in client_queries:
            try:
                obj_name = client_obj.get_name()
                # Parse "query:fieldName" to get fieldName
                if ':' in obj_name:
                    field_name = obj_name.split(':')[1]
                else:
                    field_name = obj_name
                
                if field_name and field_name in schema_queries:
                    schema_obj = schema_queries[field_name]
                    create_link('useLink', client_obj, schema_obj)
                    links_created += 1
                    log.debug('[GraphQL Application] Linked client query to schema: ' + field_name)
                else:
                    log.debug('[GraphQL Application] No schema query found for: ' + str(field_name))
            except Exception as e:
                log.warning('[GraphQL Application] Error linking query: ' + str(e))
        
        # Link client mutations to schema mutations
        # Object names are in format "mutation:fieldName" - we parse to extract fieldName
        for client_obj in client_mutations:
            try:
                obj_name = client_obj.get_name()
                # Parse "mutation:fieldName" to get fieldName
                if ':' in obj_name:
                    field_name = obj_name.split(':')[1]
                else:
                    field_name = obj_name
                
                if field_name and field_name in schema_mutations:
                    schema_obj = schema_mutations[field_name]
                    create_link('useLink', client_obj, schema_obj)
                    links_created += 1
                    log.debug('[GraphQL Application] Linked client mutation to schema: ' + field_name)
                else:
                    log.debug('[GraphQL Application] No schema mutation found for: ' + str(field_name))
            except Exception as e:
                log.warning('[GraphQL Application] Error linking mutation: ' + str(e))
        
        log.info('[GraphQL Application] Created ' + str(links_created) + ' USE links')
    
    # =========================================================================
    # HELPER METHODS - Extend as needed
    # =========================================================================
    
    def find_objects_by_type(self, application, object_type):
        """
        Find all objects of a specific type.
        
        Args:
            application: CAST Application object
            object_type (str): Object type to search for
            
        Returns:
            list: Objects matching the type
        """
        try:
            return list(application.search_objects(category=object_type))
        except Exception as e:
            return []
    
    def find_objects_by_name(self, application, name_pattern):
        """
        Find objects matching a name pattern.
        
        Args:
            application: CAST Application object
            name_pattern (str): Name or pattern to search for
            
        Returns:
            list: Objects matching the name
        """
        try:
            return list(application.search_objects(name=name_pattern))
        except Exception as e:
            return []
    
    def create_cross_technology_link(self, source_obj, target_obj, link_type='callLink'):
        """
        Create a link between objects from different technologies.
        
        Args:
            source_obj: Source CAST object
            target_obj: Target CAST object
            link_type (str): Type of link to create (default: 'callLink')
            
        Returns:
            bool: True if link was created successfully
        """
        try:
            from cast.application import create_link
            create_link(link_type, source_obj, target_obj)
            return True
        except Exception as e:
            return False
