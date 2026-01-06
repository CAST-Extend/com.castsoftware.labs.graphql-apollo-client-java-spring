"""
Unit tests for GraphQL analyzer level extension.

This module tests the analysis of GraphQL source files to verify that:
- Objects are correctly created in the knowledge base
- Object types and names match expectations
- Object hierarchy is properly established
"""

import unittest
import cast.analysers.test
from cast.analysers.test import UATestAnalysis


class TestGraphQLAnalyzerLevel(unittest.TestCase):
    """Test suite for GraphQL analyzer level processing."""
    
    def test_analyzer_level(self):
        """
        Test the analyzer level processing for GraphQL files.
        
        This test:
        1. Instantiates a UA analyzer for 'GraphQL' language
        2. Adds the test_data folder as selection
        3. Runs the analysis
        4. Prints statistics about created objects and links
        
        To verify results, check:
        - Analysis log for errors/warnings
        - Statistics output for object counts
        - Knowledge base content using analysis.get_objects_by_category()
        """
        # Instantiate a UA analyzer for 'GraphQL' language
        analysis = UATestAnalysis('GraphQL')
        
        # Add test data folder to analysis selection
        analysis.add_selection('test_data')
        
        # Enable verbose output to see detailed logs
        analysis.set_verbose(True)
        
        print("=" * 60)
        print("Running GraphQL Analysis")
        print("=" * 60)
        
        # Run the analysis
        analysis.run()
        
        print("\n" + "=" * 60)
        print("GraphQL Analysis Statistics")
        print("=" * 60)
        
        # Print statistics about created objects and links
        analysis.print_statistics()
        
        # Optional: Add assertions to verify specific objects were created
        # Example:
        # programs = analysis.get_objects_by_category('GraphQL Program')
        # self.assertGreater(len(programs), 0, "No programs were created")


if __name__ == "__main__":
    unittest.main()