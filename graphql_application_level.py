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
        Use this method to:
        - Create cross-technology links
        - Perform post-analysis calculations
        - Generate custom reports
        - Implement quality rules
        
        Args:
            application: CAST Application object providing access to:
                - get_files(): All analyzed files
                - search_objects(category=None, name=None): Find objects
                - objects(): Iterate over all objects
        
        Example: Creating cross-technology links
        
            # Find all GraphQL programs
            programs = application.search_objects(category='GraphQLProgram')
            
            # Find database tables
            tables = application.search_objects(category='Table')
            
            # Create links based on naming conventions or patterns
            for program in programs:
                for table in tables:
                    if table.get_name() in program.get_name():
                        # create_link(...)
                        pass
        """
        # TODO: Implement cross-technology analysis here
        # This is intentionally minimal - extend as needed
        pass
    
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
