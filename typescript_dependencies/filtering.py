"""
Utilities for file filtering
"""
import os
from cast.application import open_source_file


def inside_folder(path, target_folders):
    """
    Return True if a folder name in path matches
    a given folder in target_folders
    """
    for folder in target_folders:
        if folder in path:
            dirname = os.path.dirname(path)
            if folder in dirname:
                while True:
                    dirname, path_folder = os.path.split(dirname)

                    if not path_folder:
                        return False

                    if path_folder == folder:
                        return True
    return False


def is_unit_test(path):
    condition1 = path.endswith(('.spec.ts', '-spec.ts', '_spec.ts',
                                '.spec.tsx', '-spec.tsx', '_spec.tsx',
                                '.spec.cts', '-spec.cts', '_spec.cts',
                                '.spec.mts', '-spec.mts', '_spec.mts',))
    condition2 = inside_folder(path, ['e2e', 'e2e-app', 'e2e-bdd'])
    
    return any((condition1, condition2))


def is_external_module(path):
    return inside_folder(path, ['node_modules'])


def is_declaration_file(path):
    return path.endswith(('.d.ts', '.d.tsx', '.d.cts', '.d.mts'))


def imports_unit_test_framework(path):
    """
    Detects whether a file imports a unit-test framework.
    """

    unit_test_declarations = [
        "import 'jest-enzyme'",
        ]

    with open_source_file(path) as f:
        for raw_line in f:
            line = raw_line.strip()
            
            if not line:
                continue    # blank line
            if line.startswith(('//', '*', '/*', '*/')):
                continue    # comment line
            
            if not line.startswith('import'):
                return False
            
            for import_line in unit_test_declarations:
                if line.startswith(import_line):
                    return True

def get_closest_path(ref_path, possible_matches):
    """
    :type ref_path; str
    :type possible_matches: list(str)
    return the first (in alphabeltical order) best path
    """
    return get_closest_pathes(ref_path, possible_matches)[0]

def get_closest_pathes(ref_path, possible_matches):
    """
    :type ref_path; str
    :type possible_matches: list(str)
    """

    # so the ones which have the longest match (starting from the root path) should be considered
    splitted_import_path = os.path.normpath(ref_path).split(os.sep)
    best_relative_matches = []
    length_best_math = 0
    for possible_match in possible_matches:
        sp_match = possible_match.split(os.sep)
        i = 0
        while True:
            try:
                if sp_match[i] != splitted_import_path[i]:
                    break
            except IndexError:
                break
            i += 1
        if i > length_best_math:
            length_best_math = i
            best_relative_matches = [possible_match]
        elif i == length_best_math:
            best_relative_matches.append(possible_match)

    # we sort the possible_matches alphabetically to remove randomness in case several files match the path
    return sorted(best_relative_matches)



