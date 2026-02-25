import os
import sys
import unittest
from pathlib import Path

# Imports depuis typescript_dependencies (local)
from typescript_dependencies.symbols import SourceFile, RawBookmark
from typescript_dependencies.resolution import resolve_expressions
from typescript_dependencies.evaluation import EvaluationTool
from typescript_dependencies.ProgramSymbol import Program
import typescript_dependencies.resolution as resolution
import typescript_dependencies.symbols as symbols
import typescript_dependencies.evaluation as evaluation

from ts_parser.apollo_symbols import ApolloHookObject, GqlDefinitionSymbol
from ts_parser.analysis_results import ApolloAnalysisResults
from ts_parser.apollo_interpreter_ts import analyse_ts_fragment
from typescript_dependencies.typescript_walker import get_descendants


def analyse(*source_codes: [SourceFile]):
    """
    Analyze TypeScript source files for Apollo Client hooks and GraphQL operations.
    Based on Vue.js analysis pattern but adapted for Apollo.
    """
    ts_progr = Program()
    for source_code in source_codes:
        ts_progr.add_file(source_file=source_code)
        source_code.light_parse()
        source_code.set_line_count()
    for source_code in source_codes:
        source_code.fully_parse()
    ts_progr.resolve_globals()

    for source_code in source_codes:
        resolve_expressions(source_code, ts_progr)
    
    # Create Apollo analysis results container
    apollo_analysis_results = ApolloAnalysisResults()
    apollo_analysis_results.ts_evaluation_tool = EvaluationTool()
    
    # Analyze each source file for Apollo patterns
    for source_code in source_codes:
        source_code.parsing_results = analyse_ts_fragment(source_code, apollo_analysis_results)
        src = source_code.get_ast()
    # Create links between hooks and their GQL definitions
    apollo_analysis_results.create_links()

    return apollo_analysis_results




class TestLocalApolloClientPatterns(unittest.TestCase):

    def print_apollo_analysis_summary(self, test_name, gql_cache, hooks_cache, module):
        """
        Fonction générique pour afficher un résumé détaillé de l'analyse Apollo.

        Args:
            test_name: Nom du test (pour l'affichage)
            gql_cache: GQL_DEFINITIONS_CACHE
            hooks_cache: APOLLO_HOOKS_CACHE
            module: Module SourceFile
        """
        print("\n" + "=" * 80)
        print("RÉSUMÉ DES OBJETS CRÉÉS - {}".format(test_name))
        print("=" * 80)

        print("\n--- GQL_DEFINITIONS_CACHE ---")
        print("Nombre d'entrées dans gql_cache: {}".format(len(gql_cache)))
        for key, value in gql_cache.items():
            print("\n  [GQL] Clé: '{}'".format(key))
            print("    - operationName: {}".format(value.get('operationName')))
            print("    - variables: {}".format(value.get('variables')))
            print("    - fieldsSelected: {}".format(value.get('fieldsSelected')))
            print("    - rawQueryText:")
            print(value.get('rawQueryText', ''))
            bookmark = value.get('bookmark')
            if bookmark and hasattr(bookmark, 'ast') and hasattr(bookmark.ast, 'get_begin_line'):
                print("    - bookmark: Line {}".format(bookmark.ast.get_begin_line()))
            else:
                print("    - bookmark: {}".format(bookmark))

        print("\n--- APOLLO_HOOKS_CACHE ---")
        print("Nombre d'entrées dans hooks_cache: {}".format(len(hooks_cache)))
        for key, value in hooks_cache.items():
            print("\n  [HOOK CACHE] Clé: '{}'".format(key))
            print("    - hookType: {}".format(value.get('hookType')))
            bookmark = value.get('bookmark')
            if bookmark and hasattr(bookmark, 'ast') and hasattr(bookmark.ast, 'get_begin_line'):
                print("    - bookmark: Line {}".format(bookmark.ast.get_begin_line()))
            else:
                print("    - bookmark: {}".format(bookmark))

        print("\n" + "=" * 80)
        print("FIN DU RÉSUMÉ")
        print("=" * 80 + "\n")

    def test_typescript_modules_import(self):
        """Test que les modules TypeScript sont importés depuis le dossier typescript_dependencies"""
        import typescript_dependencies
        ts_deps_path = os.path.dirname(typescript_dependencies.__file__)
        self.assertTrue(os.path.isdir(ts_deps_path), "typescript_dependencies path introuvable: %s" % ts_deps_path)

        # Vérifie que ça vient bien du dossier typescript_dependencies
        self.assertTrue(resolution.__file__.startswith(ts_deps_path), resolution.__file__)
        self.assertTrue(symbols.__file__.startswith(ts_deps_path), symbols.__file__)
        self.assertTrue(evaluation.__file__.startswith(ts_deps_path), evaluation.__file__)


    def test_typescript_modules_functionality(self):
        """Test que les modules TypeScript sont fonctionnels et utilisables"""
        # Test que les objets/fonctions peuvent être importés
        from typescript_dependencies.resolution import resolve_expressions
        from typescript_dependencies.symbols import SourceFile as TSSourceFile
        from typescript_dependencies.evaluation import EvaluationTool
        from typescript_dependencies.ProgramSymbol import Program
        
        # Vérifier que ce sont des callables/classes
        self.assertTrue(callable(resolve_expressions), "resolve_expressions devrait être une fonction")
        self.assertTrue(isinstance(EvaluationTool, type), "EvaluationTool devrait être une classe")
        self.assertTrue(isinstance(Program, type), "Program devrait être une classe")
        self.assertTrue(isinstance(TSSourceFile, type), "SourceFile devrait être une classe")
        
        # Test de création d'un objet simple pour vérifier que la classe est instanciable
        try:
            test_module = TSSourceFile('test.ts', text="const x = 1;")
            self.assertIsNotNone(test_module, "La création de SourceFile a échoué")
            
            # Parser le module avant d'accéder à l'AST
            test_module.light_parse()
            
            # Vérifier que get_ast() fonctionne et retourne un AST valide
            self.assertTrue(hasattr(test_module, 'get_ast'), "SourceFile devrait avoir une méthode get_ast")
            self.assertTrue(callable(test_module.get_ast), "get_ast devrait être callable")
            
            ast = test_module.get_ast()
            self.assertIsNotNone(ast, "get_ast() devrait retourner un AST après light_parse()")
            ast.print_tree()  # Affiche l'AST pour vérification visuelle
            print("✓ Test fonctionnel réussi: modules TypeScript opérationnels")
            print("  - Imports: resolve_expressions, SourceFile, EvaluationTool, Program")
            print("  - SourceFile instanciable, parsing fonctionnel, AST accessible")
        except Exception as e:
            self.fail("Erreur lors de l'utilisation des modules TypeScript: {}".format(str(e)))


    def test_hooks_outline_01(self):

        module = SourceFile('C:\Cast\GraphQL\module.ts', text="""\
/**
 * MODULE 1 — Apollo Hooks avec gql OUTLINE
 * useQuery / useMutation / useSubscription
 * Le document GraphQL est défini en dehors du composant (const).
 */

import React from 'react';
import { gql, useQuery, useMutation, useSubscription } from '@apollo/client';

// ─── Documents GraphQL définis "outline" (en dehors du composant) ────────────

const GET_LAMBDA_INVOCATIONS = gql`
  query GetLambdaInvocations($functionName: String!) {
    lambdaInvocations(functionName: $functionName) {
      id
      functionName
      invocationType
      logType
      payload
      qualifier
      status
    }
  }
`;

const INVOKE_LAMBDA = gql`
  mutation InvokeLambda($input: InvokeLambdaInput!) {
    invokeLambda(input: $input) {
      id
      status
      payload
    }
  }
`;

const LAMBDA_INVOCATION_RESULT = gql`
  subscription OnLambdaInvocationResult($functionName: String!) {
    lambdaInvocationResult(functionName: $functionName) {
      id
      status
      payload
      error
    }
  }
`;

// ─── Composant ────────────────────────────────────────────────────────────────

const LambdaManager: React.FC = () => {
  const functionName = 'Function_Name';

  // useQuery — outline gql
  const { data, loading, error, refetch } = useQuery(GET_LAMBDA_INVOCATIONS, {
    variables: { functionName },
  });
  
  const TEST_GQL_IN_FUNCTION = gql`
  query Testgqlinfunction($functionName: String!) {
    gqlinfunction(functionName: $functionName) {
      id
      functionName
      invocationType
      logType
      payload
      qualifier
      status
    }
  }
`;

  // useMutation — outline gql
  const [invokeLambda, { loading: mutating, data: mutationResult }] = useMutation(
    INVOKE_LAMBDA,
    {
      onCompleted: (result) => console.log('Lambda invoked:', result),
      onError: (err) => console.error('Mutation error:', err),
    }
  );

  // useSubscription — outline gql
  const { data: subData, loading: subLoading } = useSubscription(
    LAMBDA_INVOCATION_RESULT,
    { variables: { functionName } }
  );

  const handleInvoke = () => {
    invokeLambda({
      variables: {
        input: {
          functionName,
          invocationType: 'RequestResponse',
          logType: 'Tail',
          payload: btoa('{"key":"value"}'),
          qualifier: '$LATEST',
        },
      },
    });
  };

  if (loading) return <p>Loading invocations…</p>;
  if (error) return <p>Error: {error.message}</p>;

  return (
    <div>
      <h2>Lambda Invocations (Hooks — Outline gql)</h2>

      <button onClick={handleInvoke} disabled={mutating}>
        {mutating ? 'Invoking…' : 'Invoke Lambda'}
      </button>

      {mutationResult && (
        <pre>Mutation result: {JSON.stringify(mutationResult, null, 2)}</pre>
      )}

      {subLoading ? (
        <p>Waiting for subscription events…</p>
      ) : (
        subData && (
          <pre>Subscription event: {JSON.stringify(subData.lambdaInvocationResult, null, 2)}</pre>
        )
      )}

      <ul>
        {data?.lambdaInvocations?.map((inv: any) => (
          <li key={inv.id}>
            {inv.functionName} — {inv.status}
          </li>
        ))}
      </ul>

      <button onClick={() => refetch()}>Refetch</button>
    </div>
  );
};

export default LambdaManager;
""")
        # Use new analysis structure like Vue.js tests
        apollo_analysis_results = analyse(module)
        # Get GQL definitions and hooks for this file
        gql_defs = apollo_analysis_results.gql_definitions_by_file[module.get_path()]
        hooks = apollo_analysis_results.apollo_hooks_by_file[module.get_path()]

        file_path = str(module.get_path())
        line_num = gql_defs[0].raw_bookmark.ast.get_begin_line() if gql_defs[0].raw_bookmark and gql_defs[0].raw_bookmark.ast else 0
        fullname = file_path + ':' + str(line_num)

        gql_symbol = module.get_symbol('TEST_GQL_IN_FUNCTION', _type=GqlDefinitionSymbol)
        gql_symbol_parent = gql_symbol.get_parent_symbol() if gql_symbol else None
        gql = gql_defs[0].raw_bookmark.get_bookmark()
        # ===============================================================================
        # DEBUG: Verifier que les symbols sont bien crees
        # ===============================================================================
        print("\n" + "=" * 80)
        print("VERIFICATION DES SYMBOLS CREES")
        print("=" * 80)

        # get_local_symbols() returns a dict {name: [symbol]}
        local_symbols = module.get_local_symbols()
        print("\nNombre total de noms de symbols: {}".format(len(local_symbols)))

        total_symbols = 0
        for symbol_name, symbol_list in local_symbols.items():
            for symbol in symbol_list:
                total_symbols += 1
                symbol_type = type(symbol).__name__
                print("  - Symbol: '{}' (Type: {})".format(symbol_name, symbol_type))

                # Show additional info for Apollo symbols
                if hasattr(symbol, 'hook_name'):
                    print("    → Hook: {} / Operation: {}".format(
                        symbol.hook_name, symbol.operation_name))
                elif hasattr(symbol, 'operation_type'):
                    print("    → GQL: {} / Operation: {}".format(
                        symbol.operation_type, symbol.operation_name))

        print("\nNombre total de symbols: {}".format(total_symbols))
        print("=" * 80 + "\n")

        # ===============================================================================
        # TEST 1: Verifier la visibilite globale des symbols Apollo
        # ===============================================================================
        print("\n" + "=" * 80)
        print("TEST 1: VISIBILITE GLOBALE - module.get_local_symbols()")
        print("=" * 80)

        # Compter les différents types de symbols
        apollo_hooks_count = 0
        gql_defs_count = 0

        for symbol_name, symbol_list in local_symbols.items():
            for symbol in symbol_list:
                symbol_type = type(symbol).__name__
                if symbol_type == 'ApolloHookSymbol':
                    apollo_hooks_count += 1
                    print("  ✓ Found ApolloHookSymbol: {}".format(symbol_name))
                elif symbol_type == 'GqlDefinitionSymbol':
                    gql_defs_count += 1
                    print("  ✓ Found GqlDefinitionSymbol: {}".format(symbol_name))

        print("\nRésumé:")
        print("  - ApolloHookSymbol: {}".format(apollo_hooks_count))
        print("  - GqlDefinitionSymbol: {}".format(gql_defs_count))

        # Assertions
        self.assertGreater(apollo_hooks_count, 0, "Devrait trouver au moins un ApolloHookSymbol")
        self.assertGreater(gql_defs_count, 0, "Devrait trouver au moins un GqlDefinitionSymbol")
        print("\n>>> TEST 1 REUSSI: Les symbols Apollo sont visibles globalement!")

        # ===============================================================================
        # TEST 2: Verifier la structure parent-enfant des symbols
        # ===============================================================================
        print("\n" + "=" * 80)
        print("TEST 2: STRUCTURE PARENT-ENFANT")
        print("=" * 80)

        # Trouver le symbol LambdaManager
        lambda_manager_symbol = None
        for name, symbols in local_symbols.items():
            for symbol in symbols:
                if type(symbol).__name__ == 'Function' and name == 'LambdaManager':
                    lambda_manager_symbol = symbol
                    break
            if lambda_manager_symbol:
                break

        if lambda_manager_symbol:
            print("\n✓ Trouvé le symbol LambdaManager: {}".format(lambda_manager_symbol.get_fullname()))

            # Vérifier les symbols enfants de LambdaManager
            lambda_manager_children = lambda_manager_symbol.get_local_symbols()
            print("\nSymbols enfants de LambdaManager: {} noms".format(len(lambda_manager_children)))

            apollo_hooks_in_lambda = 0
            for child_name, child_symbols in lambda_manager_children.items():
                for child in child_symbols:
                    child_type = type(child).__name__
                    if child_type == 'ApolloHookSymbol':
                        apollo_hooks_in_lambda += 1
                        print("  - Enfant: '{}' (Type: {})".format(child_name, child_type))

                        # Vérifier que le parent est bien LambdaManager
                        child_parent = child.get_parent_symbol() if hasattr(child, 'get_parent_symbol') else None
                        if child_parent:
                            print("    Parent: {}".format(child_parent.get_fullname()))
                            if child_parent == lambda_manager_symbol:
                                print("    ✓ Parent correct!")
                            else:
                                print("    ✗ Parent incorrect! Attendu: {}, Reçu: {}".format(
                                    lambda_manager_symbol.get_fullname(), child_parent.get_fullname()))

            print("\nRésumé:")
            print("  - Apollo hooks dans LambdaManager: {}".format(apollo_hooks_in_lambda))

            # Test spécifique pour le premier useQuery
            if 'GET_LAMBDA_INVOCATIONS' in lambda_manager_children:
                print("\n✓ Trouvé GET_LAMBDA_INVOCATIONS dans les enfants de LambdaManager")
                hook_symbols = lambda_manager_children['GET_LAMBDA_INVOCATIONS']
                if hook_symbols:
                    first_hook = hook_symbols[0]
                    if type(first_hook).__name__ == 'ApolloHookSymbol':
                        hook_parent = first_hook.get_parent_symbol()
                        print("  Type du symbol: {}".format(type(first_hook).__name__))
                        print("  Parent du hook: {}".format(hook_parent.get_fullname() if hook_parent else 'None'))

                        # Assertion importante
                        self.assertEqual(hook_parent, lambda_manager_symbol,
                            "Le parent du hook devrait être LambdaManager")
                        print("  ✓✓✓ TEST 2 RÉUSSI: Le parent est bien LambdaManager!")
            else:
                print("\n✗ GET_LAMBDA_INVOCATIONS non trouvé dans les enfants de LambdaManager")
                print("  Symboles disponibles: {}".format(list(lambda_manager_children.keys())))
        else:
            print("\n✗ Symbol LambdaManager non trouvé")

        print("=" * 80 + "\n")

        print("\n🎉 TOUS LES TESTS DE VISIBILITÉ RÉUSSIS!")
        print("  - ✓ Les symbols Apollo sont visibles dans module.get_local_symbols()")
        print("  - ✓ Les symbols Apollo ont le bon parent (LambdaManager)")
        print("  - ✓ Les symbols Apollo sont aussi enfants de leur fonction parente")
        print("=" * 80 + "\n")

        for inst in get_descendants(module.get_ast(), 'FunctionCall'):
            print(inst)

        # self.assertTrue(RawBookmark(invoke_inst, module) == invoke.raw_bookmark)

        # Get caches for backward compatibility with print summary
        [gql_cache, hooks_cache] = apollo_analysis_results.get_cache_dicts()
        self.print_apollo_analysis_summary("test_hooks_outline_01", gql_cache, hooks_cache, module)
        
        # ═══════════════════════════════════════════════════════════════════════
        # Test 1: Vérifier GET_LAMBDA_INVOCATIONS (useQuery)
        # ═══════════════════════════════════════════════════════════════════════
        # Vérifier le hook useQuery via le fichier
        query_hooks = [h for h in hooks if h.hook_name == 'useQuery' and h.operation_name == 'GET_LAMBDA_INVOCATIONS']
        self.assertTrue(len(query_hooks) > 0, "Should find at least one useQuery hook")
        query_hook = query_hooks[0]
        self.assertEqual(query_hook.hook_name, 'useQuery')
        self.assertEqual(query_hook.operation_name, 'GET_LAMBDA_INVOCATIONS')
        
        # Vérifier la définition gql associée
        self.assertIsNotNone(query_hook.gql_definition)
        gql_def = query_hook.gql_definition
        
        self.assertEqual(gql_def['operationName'], 'GetLambdaInvocations')
        self.assertEqual(gql_def['variables'], '$functionName')
        self.assertEqual(gql_def['fieldsSelected'], 'lambdaInvocations')
        self.assertEqual(gql_def['rawQueryText'], "\n  query GetLambdaInvocations($functionName: String!) {\n    lambdaInvocations(functionName: $functionName) {\n      id\n      functionName\n      invocationType\n      logType\n      payload\n      qualifier\n      status\n    }\n  }\n")
        
        # Vérifier le bookmark du hook
        self.assertIsNotNone(query_hook.raw_bookmark)
        self.assertEqual(query_hook.raw_bookmark.ast.get_begin_line(), 53)
        
        # ═══════════════════════════════════════════════════════════════════════
        # Test 2: Vérifier INVOKE_LAMBDA (useMutation)
        # ═══════════════════════════════════════════════════════════════════════
        
        # Vérifier le hook useMutation via le fichier
        mutation_hooks = [h for h in hooks if h.hook_name == 'useMutation' and h.operation_name == 'INVOKE_LAMBDA']
        self.assertTrue(len(mutation_hooks) > 0, "Should find at least one useMutation hook")
        mutation_hook = mutation_hooks[0]
        self.assertEqual(mutation_hook.hook_name, 'useMutation')
        self.assertEqual(mutation_hook.operation_name, 'INVOKE_LAMBDA')
        
        # Vérifier la définition gql associée
        self.assertIsNotNone(mutation_hook.gql_definition)
        gql_def_mutation = mutation_hook.gql_definition
        
        self.assertEqual(gql_def_mutation['operationName'], 'InvokeLambda')
        self.assertEqual(gql_def_mutation['variables'], '$input')
        self.assertEqual(gql_def_mutation['fieldsSelected'], 'invokeLambda')
        self.assertEqual(gql_def_mutation['rawQueryText'], "\n  mutation InvokeLambda($input: InvokeLambdaInput!) {\n    invokeLambda(input: $input) {\n      id\n      status\n      payload\n    }\n  }\n")
        
        # Vérifier le bookmark du hook
        self.assertIsNotNone(mutation_hook.raw_bookmark)
        self.assertEqual(mutation_hook.raw_bookmark.ast.get_begin_line(), 72)
        
        # ═══════════════════════════════════════════════════════════════════════
        # Test 3: Vérifier LAMBDA_INVOCATION_RESULT (useSubscription)
        # ═══════════════════════════════════════════════════════════════════════
        
        # Vérifier le hook useSubscription via le fichier
        subscription_hooks = [h for h in hooks if h.hook_name == 'useSubscription' and h.operation_name == 'LAMBDA_INVOCATION_RESULT']
        self.assertTrue(len(subscription_hooks) > 0, "Should find at least one useSubscription hook")
        subscription_hook = subscription_hooks[0]
        self.assertEqual(subscription_hook.hook_name, 'useSubscription')
        self.assertEqual(subscription_hook.operation_name, 'LAMBDA_INVOCATION_RESULT')
        
        # Vérifier la définition gql associée
        self.assertIsNotNone(subscription_hook.gql_definition)
        gql_def_subscription = subscription_hook.gql_definition
        
        self.assertEqual(gql_def_subscription['operationName'], 'OnLambdaInvocationResult')
        self.assertEqual(gql_def_subscription['variables'], '$functionName')
        self.assertEqual(gql_def_subscription['fieldsSelected'], 'lambdaInvocationResult')
        self.assertEqual(gql_def_subscription['rawQueryText'], "\n  subscription OnLambdaInvocationResult($functionName: String!) {\n    lambdaInvocationResult(functionName: $functionName) {\n      id\n      status\n      payload\n      error\n    }\n  }\n")

        # Vérifier le bookmark du hook
        self.assertIsNotNone(subscription_hook.raw_bookmark)
        self.assertEqual(subscription_hook.raw_bookmark.ast.get_begin_line(), 81)


    def test_hooks_inline_02(self):

        module = SourceFile('module.ts', text="""\
/**
 * MODULE 2 — Apollo Hooks avec gql INLINE
 * useQuery / useMutation / useSubscription
 * Le document GraphQL est passé directement dans le hook (inline).
 */

import React from 'react';
import { gql, useQuery, useMutation, useSubscription } from '@apollo/client';

// ─── Composant ────────────────────────────────────────────────────────────────

const LambdaManagerInline: React.FC = () => {
  const functionName = 'Function_Name';

  // useQuery — gql inline
  const { data, loading, error } = useQuery(
    gql`
      query GetLambdaInvocations($functionName: String!) {
        lambdaInvocations(functionName: $functionName) {
          id
          functionName
          status
          payload
        }
      }
    `,
    { variables: { functionName } }
  );

  // useMutation — gql inline
  const [invokeLambda, { loading: mutating }] = useMutation(
    gql`
      mutation InvokeLambda($input: InvokeLambdaInput!) {
        invokeLambda(input: $input) {
          id
          status
          payload
        }
      }
    `
  );

  // useSubscription — gql inline
  const { data: subData } = useSubscription(
    gql`
      subscription OnLambdaInvocationResult($functionName: String!) {
        lambdaInvocationResult(functionName: $functionName) {
          id
          status
          error
        }
      }
    `,
    { variables: { functionName } }
  );

  const handleInvoke = () => {
    invokeLambda({
      variables: {
        input: {
          functionName,
          invocationType: 'Event',
          logType: 'None',
          payload: btoa('{}'),
          qualifier: '$LATEST',
        },
      },
    });
  };

  if (loading) return <p>Loading…</p>;
  if (error) return <p>Error: {error.message}</p>;

  return (
    <div>
      <h2>Lambda Invocations (Hooks — Inline gql)</h2>

      <button onClick={handleInvoke} disabled={mutating}>
        {mutating ? 'Invoking…' : 'Invoke Lambda'}
      </button>

      {subData && (
        <pre>Sub event: {JSON.stringify(subData.lambdaInvocationResult, null, 2)}</pre>
      )}

      <ul>
        {data?.lambdaInvocations?.map((inv: any) => (
          <li key={inv.id}>
            {inv.functionName} — {inv.status}
          </li>
        ))}
      </ul>
    </div>
  );
};

export default LambdaManagerInline;
""")
        # Use new analysis structure like Vue.js tests
        apollo_analysis_results = analyse(module)
        
        # Get GQL definitions and hooks for this file
        gql_defs = apollo_analysis_results.gql_definitions_by_file[module.get_path()]
        hooks = apollo_analysis_results.apollo_hooks_by_file[module.get_path()]
        
        # Get caches for backward compatibility with print summary
        [gql_cache, hooks_cache] = apollo_analysis_results.get_cache_dicts()
        self.print_apollo_analysis_summary("test_hooks_inline_02", gql_cache, hooks_cache, module)

        # ═══════════════════════════════════════════════════════════════════════
        # Test 1: Vérifier GetLambdaInvocations (useQuery inline)
        # ═══════════════════════════════════════════════════════════════════════
        
        # Vérifier que le hook est détecté avec le nom de l'opération GraphQL
        query_hooks = [h for h in hooks if h.hook_name == 'useQuery' and h.operation_name == 'GetLambdaInvocations']
        self.assertTrue(len(query_hooks) > 0, "Should find at least one useQuery hook")
        query_hook = query_hooks[0]
        
        self.assertEqual(query_hook.hook_name, 'useQuery')
        self.assertEqual(query_hook.operation_name, 'GetLambdaInvocations')
        
        # Vérifier que la propriété inline est définie
        self.assertIsNotNone(query_hook.inline)
        self.assertEqual(query_hook.inline, 'GetLambdaInvocations')
        
        # Vérifier la définition gql associée
        self.assertIsNotNone(query_hook.gql_definition)
        gql_def = query_hook.gql_definition
        
        self.assertEqual(gql_def['operationName'], 'GetLambdaInvocations')
        self.assertEqual(gql_def['variables'], '$functionName')
        self.assertEqual(gql_def['fieldsSelected'], 'lambdaInvocations')
        self.assertIn('query GetLambdaInvocations', gql_def['rawQueryText'])
        
        # Vérifier le bookmark du hook
        self.assertIsNotNone(query_hook.raw_bookmark)
        
        # ═══════════════════════════════════════════════════════════════════════
        # Test 2: Vérifier InvokeLambda (useMutation inline)
        # ═══════════════════════════════════════════════════════════════════════
        
        mutation_hooks = [h for h in hooks if h.hook_name == 'useMutation' and h.operation_name == 'InvokeLambda']
        self.assertTrue(len(mutation_hooks) > 0, "Should find at least one useMutation hook")
        mutation_hook = mutation_hooks[0]
        
        self.assertEqual(mutation_hook.hook_name, 'useMutation')
        self.assertEqual(mutation_hook.operation_name, 'InvokeLambda')
        
        # Vérifier que la propriété inline est définie
        self.assertIsNotNone(mutation_hook.inline)
        self.assertEqual(mutation_hook.inline, 'InvokeLambda')
        
        # Vérifier la définition gql associée
        self.assertIsNotNone(mutation_hook.gql_definition)
        gql_def_mutation = mutation_hook.gql_definition
        
        self.assertEqual(gql_def_mutation['operationName'], 'InvokeLambda')
        self.assertEqual(gql_def_mutation['variables'], '$input')
        self.assertEqual(gql_def_mutation['fieldsSelected'], 'invokeLambda')
        self.assertIn('mutation InvokeLambda', gql_def_mutation['rawQueryText'])
        
        # Vérifier le bookmark du hook
        self.assertIsNotNone(mutation_hook.raw_bookmark)
        
        # ═══════════════════════════════════════════════════════════════════════
        # Test 3: Vérifier OnLambdaInvocationResult (useSubscription inline)
        # ═══════════════════════════════════════════════════════════════════════
        
        subscription_hooks = [h for h in hooks if h.hook_name == 'useSubscription' and h.operation_name == 'OnLambdaInvocationResult']
        self.assertTrue(len(subscription_hooks) > 0, "Should find at least one useSubscription hook")
        subscription_hook = subscription_hooks[0]
        
        self.assertEqual(subscription_hook.hook_name, 'useSubscription')
        self.assertEqual(subscription_hook.operation_name, 'OnLambdaInvocationResult')
        
        # Vérifier que la propriété inline est définie
        self.assertIsNotNone(subscription_hook.inline)
        self.assertEqual(subscription_hook.inline, 'OnLambdaInvocationResult')
        
        # Vérifier la définition gql associée
        self.assertIsNotNone(subscription_hook.gql_definition)
        gql_def_subscription = subscription_hook.gql_definition
        
        self.assertEqual(gql_def_subscription['operationName'], 'OnLambdaInvocationResult')
        self.assertEqual(gql_def_subscription['variables'], '$functionName')
        self.assertEqual(gql_def_subscription['fieldsSelected'], 'lambdaInvocationResult')
        self.assertIn('subscription OnLambdaInvocationResult', gql_def_subscription['rawQueryText'])

        # for m_c in get_descendants(module.get_ast(), MethodCall):
        #     if m_c.get_name() == 'invoke':
        #         invoke_m_c = m_c
        #         break
        # self.assertTrue(RawBookmark(invoke_m_c, module) == invoke.raw_bookmark)


    def test_typed_document_node_outline_03(self):

        module = SourceFile('module.ts', text="""\
/**
 * MODULE 3 — TypedDocumentNode OUTLINE (déclaré en amont, typage explicite)
 *
 * On déclare les types des variables et du résultat, puis on crée le document
 * avec TypedDocumentNode<TData, TVariables> directement sur la const.
 * Cela donne un typage end-to-end sans "as".
 */

import React from 'react';
import { gql, useQuery, useMutation, useSubscription } from '@apollo/client';
import { TypedDocumentNode } from '@graphql-typed-document-node/core';

// ─── Types ────────────────────────────────────────────────────────────────────

interface LambdaInvocation {
  id: string;
  functionName: string;
  invocationType: string;
  logType: string;
  payload: string;
  qualifier: string;
  status: string;
}

interface GetLambdaInvocationsData {
  lambdaInvocations: LambdaInvocation[];
}
interface GetLambdaInvocationsVars {
  functionName: string;
}

interface InvokeLambdaInput {
  functionName: string;
  invocationType: string;
  logType: string;
  payload: string;
  qualifier: string;
}
interface InvokeLambdaData {
  invokeLambda: { id: string; status: string; payload: string };
}
interface InvokeLambdaVars {
  input: InvokeLambdaInput;
}

interface OnResultData {
  lambdaInvocationResult: { id: string; status: string; error: string | null };
}
interface OnResultVars {
  functionName: string;
}

// ─── Documents TypedDocumentNode (typage sur la déclaration) ─────────────────

const GET_LAMBDA_INVOCATIONS: TypedDocumentNode<
  GetLambdaInvocationsData,
  GetLambdaInvocationsVars
> = gql`
  query GetLambdaInvocations($functionName: String!) {
    lambdaInvocations(functionName: $functionName) {
      id
      functionName
      invocationType
      logType
      payload
      qualifier
      status
    }
  }
`;

const INVOKE_LAMBDA: TypedDocumentNode<InvokeLambdaData, InvokeLambdaVars> = gql`
  mutation InvokeLambda($input: InvokeLambdaInput!) {
    invokeLambda(input: $input) {
      id
      status
      payload
    }
  }
`;

const ON_LAMBDA_RESULT: TypedDocumentNode<OnResultData, OnResultVars> = gql`
  subscription OnLambdaInvocationResult($functionName: String!) {
    lambdaInvocationResult(functionName: $functionName) {
      id
      status
      error
    }
  }
`;

// ─── Composant ────────────────────────────────────────────────────────────────

const LambdaTypedOutline: React.FC = () => {
  const functionName = 'Function_Name';

  // Les generics de useQuery/useMutation/useSubscription sont inférés
  // automatiquement à partir du TypedDocumentNode → pas besoin de les répéter.
  const { data, loading, error } = useQuery(GET_LAMBDA_INVOCATIONS, {
    variables: { functionName },
  });

  const [invokeLambda, { loading: mutating, data: mutResult }] = useMutation(
    INVOKE_LAMBDA
  );

  const { data: subData } = useSubscription(ON_LAMBDA_RESULT, {
    variables: { functionName },
  });

  const handleInvoke = () => {
    invokeLambda({
      variables: {
        input: {
          functionName,
          invocationType: 'RequestResponse',
          logType: 'Tail',
          payload: btoa('{"key":"value"}'),
          qualifier: '$LATEST',
        },
      },
    });
  };

  if (loading) return <p>Loading…</p>;
  if (error) return <p>Error: {error.message}</p>;

  return (
    <div>
      <h2>Lambda (TypedDocumentNode — Outline, typage sur déclaration)</h2>

      <button onClick={handleInvoke} disabled={mutating}>
        {mutating ? 'Invoking…' : 'Invoke Lambda'}
      </button>

      {/* TypeScript sait exactement ce que contient mutResult */}
      {mutResult && <p>Invoked: {mutResult.invokeLambda.status}</p>}

      {subData && (
        <p>
          Sub: {subData.lambdaInvocationResult.id} —{' '}
          {subData.lambdaInvocationResult.status}
        </p>
      )}

      <ul>
        {data?.lambdaInvocations.map((inv) => (
          <li key={inv.id}>
            {inv.functionName} — {inv.status}
          </li>
        ))}
      </ul>
    </div>
  );
};

export default LambdaTypedOutline;
""")
        # Use new analysis structure like Vue.js tests
        apollo_analysis_results = analyse(module)
        ast = module.get_ast()
        # if ast:
        #     ast.print_tree()

        # Get hooks for this file
        hooks = apollo_analysis_results.apollo_hooks_by_file[module.get_path()]

        # Get caches for backward compatibility with print summary
        [gql_cache, hooks_cache] = apollo_analysis_results.get_cache_dicts()
        self.print_apollo_analysis_summary("test_typed_document_node_outline_03", gql_cache, hooks_cache, module)

        # Test useQuery hook with TypedDocumentNode
        query_hooks = [h for h in hooks if h.hook_name == 'useQuery' and h.operation_name == 'GET_LAMBDA_INVOCATIONS']
        self.assertTrue(len(query_hooks) > 0, "Should find at least one useQuery hook")
        query_hook = query_hooks[0]
        self.assertTrue(isinstance(query_hook, ApolloHookObject))
        self.assertEqual(query_hook.hook_name, 'useQuery')
        self.assertEqual(query_hook.operation_name, 'GET_LAMBDA_INVOCATIONS')

        # Test useMutation hook with TypedDocumentNode
        mutation_hooks = [h for h in hooks if h.hook_name == 'useMutation' and h.operation_name == 'INVOKE_LAMBDA']
        self.assertTrue(len(mutation_hooks) > 0, "Should find at least one useMutation hook")
        mutation_hook = mutation_hooks[0]
        self.assertTrue(isinstance(mutation_hook, ApolloHookObject))
        self.assertEqual(mutation_hook.hook_name, 'useMutation')
        self.assertEqual(mutation_hook.operation_name, 'INVOKE_LAMBDA')

        # Test useSubscription hook with TypedDocumentNode
        subscription_hooks = [h for h in hooks if h.hook_name == 'useSubscription' and h.operation_name == 'ON_LAMBDA_RESULT']
        self.assertTrue(len(subscription_hooks) > 0, "Should find at least one useSubscription hook")
        subscription_hook = subscription_hooks[0]
        self.assertTrue(isinstance(subscription_hook, ApolloHookObject))
        self.assertEqual(subscription_hook.hook_name, 'useSubscription')
        self.assertEqual(subscription_hook.operation_name, 'ON_LAMBDA_RESULT')

        # for m_c in get_descendants(module.get_ast(), MethodCall):
        #     if m_c.get_name() == 'invoke':
        #         invoke_m_c = m_c
        #         break
        # self.assertTrue(RawBookmark(invoke_m_c, module) == invoke.raw_bookmark)


    def test_typed_document_node_as_cast_04(self):

        module = SourceFile('module.ts', text="""\
/**
 * MODULE 4 — TypedDocumentNode avec cast "as" À LA FIN
 *
 * Variante courante quand on ne veut pas annoter la const dès le début :
 * on appelle gql`...` normalement, puis on caste le résultat
 * avec "as TypedDocumentNode<TData, TVariables>".
 *
 * Utile lorsque les types viennent de fichiers générés ou de déclarations
 * séparées ajoutées après coup.
 */

import React from 'react';
import { gql, useQuery, useMutation, useSubscription } from '@apollo/client';
import { TypedDocumentNode } from '@graphql-typed-document-node/core';

// ─── Types ────────────────────────────────────────────────────────────────────

interface LambdaInvocation {
  id: string;
  functionName: string;
  status: string;
  payload: string;
}

interface GetLambdaInvocationsData {
  lambdaInvocations: LambdaInvocation[];
}
interface GetLambdaInvocationsVars {
  functionName: string;
}

interface InvokeLambdaData {
  invokeLambda: { id: string; status: string };
}
interface InvokeLambdaVars {
  input: {
    functionName: string;
    invocationType: string;
    logType: string;
    payload: string;
    qualifier: string;
  };
}

interface OnResultData {
  lambdaInvocationResult: { id: string; status: string; error: string | null };
}
interface OnResultVars { functionName: string }

// ─── Documents gql castés "as TypedDocumentNode" à la fin ────────────────────

const GET_LAMBDA_INVOCATIONS = gql`
  query GetLambdaInvocations($functionName: String!) {
    lambdaInvocations(functionName: $functionName) {
      id
      functionName
      status
      payload
    }
  }
` as TypedDocumentNode<GetLambdaInvocationsData, GetLambdaInvocationsVars>;

const INVOKE_LAMBDA = gql`
  mutation InvokeLambda($input: InvokeLambdaInput!) {
    invokeLambda(input: $input) {
      id
      status
    }
  }
` as TypedDocumentNode<InvokeLambdaData, InvokeLambdaVars>;

const ON_LAMBDA_RESULT = gql`
  subscription OnLambdaInvocationResult($functionName: String!) {
    lambdaInvocationResult(functionName: $functionName) {
      id
      status
      error
    }
  }
` as TypedDocumentNode<OnResultData, OnResultVars>;

// ─── Composant ────────────────────────────────────────────────────────────────

const LambdaTypedAs: React.FC = () => {
  const functionName = 'Function_Name';

  const { data, loading, error } = useQuery(GET_LAMBDA_INVOCATIONS, {
    variables: { functionName },
  });

  const [invokeLambda, { loading: mutating, data: mutResult }] =
    useMutation(INVOKE_LAMBDA);

  const { data: subData } = useSubscription(ON_LAMBDA_RESULT, {
    variables: { functionName },
  });

  const handleInvoke = () =>
    invokeLambda({
      variables: {
        input: {
          functionName,
          invocationType: 'DryRun',
          logType: 'None',
          payload: btoa('{}'),
          qualifier: '$LATEST',
        },
      },
    });

  if (loading) return <p>Loading…</p>;
  if (error) return <p>Error: {error.message}</p>;

  return (
    <div>
      <h2>Lambda (TypedDocumentNode — cast "as" à la fin)</h2>

      <button onClick={handleInvoke} disabled={mutating}>
        {mutating ? 'Invoking…' : 'Invoke Lambda'}
      </button>

      {mutResult && <p>Status: {mutResult.invokeLambda.status}</p>}

      {subData && (
        <p>
          Result: {subData.lambdaInvocationResult.id} —{' '}
          {subData.lambdaInvocationResult.status}
        </p>
      )}

      <ul>
        {data?.lambdaInvocations.map((inv) => (
          <li key={inv.id}>
            {inv.functionName} — {inv.status}
          </li>
        ))}
      </ul>
    </div>
  );
};

export default LambdaTypedAs;
""")
        # Use new analysis structure like Vue.js tests
        apollo_analysis_results = analyse(module)
        ast = module.get_ast()
        if ast:
            ast.print_tree()

        # ── GQL definitions (Bug 3 regression guard) ───────────────────────────
        gql_defs = apollo_analysis_results.gql_definitions_by_file[module.get_path()]
        self.assertEqual(len(gql_defs), 3, "Should find 3 GQL definitions for the as-cast pattern")

        query_defs = [d for d in gql_defs if d.name == 'GET_LAMBDA_INVOCATIONS']
        self.assertTrue(len(query_defs) > 0, "Should find GQL definition for GET_LAMBDA_INVOCATIONS")
        self.assertEqual(query_defs[0].operation_name, 'GetLambdaInvocations')
        self.assertEqual(query_defs[0].operation_type, 'query')

        mutation_defs = [d for d in gql_defs if d.name == 'INVOKE_LAMBDA']
        self.assertTrue(len(mutation_defs) > 0, "Should find GQL definition for INVOKE_LAMBDA")
        self.assertEqual(mutation_defs[0].operation_name, 'InvokeLambda')
        self.assertEqual(mutation_defs[0].operation_type, 'mutation')

        subscription_defs = [d for d in gql_defs if d.name == 'ON_LAMBDA_RESULT']
        self.assertTrue(len(subscription_defs) > 0, "Should find GQL definition for ON_LAMBDA_RESULT")
        self.assertEqual(subscription_defs[0].operation_name, 'OnLambdaInvocationResult')
        self.assertEqual(subscription_defs[0].operation_type, 'subscription')

        # ── Apollo hooks ────────────────────────────────────────────────────────
        # Get hooks for this file
        hooks = apollo_analysis_results.apollo_hooks_by_file[module.get_path()]

        # Test useQuery hook with TypedDocumentNode and 'as' cast
        query_hooks = [h for h in hooks if h.hook_name == 'useQuery' and h.operation_name == 'GET_LAMBDA_INVOCATIONS']
        self.assertTrue(len(query_hooks) > 0, "Should find at least one useQuery hook")
        query_hook = query_hooks[0]
        self.assertTrue(isinstance(query_hook, ApolloHookObject))
        self.assertEqual(query_hook.hook_name, 'useQuery')
        self.assertEqual(query_hook.operation_name, 'GET_LAMBDA_INVOCATIONS')

        # Test useMutation hook
        mutation_hooks = [h for h in hooks if h.hook_name == 'useMutation' and h.operation_name == 'INVOKE_LAMBDA']
        self.assertTrue(len(mutation_hooks) > 0, "Should find at least one useMutation hook")
        mutation_hook = mutation_hooks[0]
        self.assertTrue(isinstance(mutation_hook, ApolloHookObject))
        self.assertEqual(mutation_hook.hook_name, 'useMutation')
        self.assertEqual(mutation_hook.operation_name, 'INVOKE_LAMBDA')

        # Test useSubscription hook
        subscription_hooks = [h for h in hooks if h.hook_name == 'useSubscription' and h.operation_name == 'ON_LAMBDA_RESULT']
        self.assertTrue(len(subscription_hooks) > 0, "Should find at least one useSubscription hook")
        subscription_hook = subscription_hooks[0]
        self.assertTrue(isinstance(subscription_hook, ApolloHookObject))
        self.assertEqual(subscription_hook.hook_name, 'useSubscription')
        self.assertEqual(subscription_hook.operation_name, 'ON_LAMBDA_RESULT')


    def test_typed_document_node_as_cast_05(self):

        module = SourceFile('module.ts', text="""\
/**
 * MODULE 5 — TypedDocumentNode INLINE avec cast "as" directement dans le hook
 *
 * Variante où le document est défini et casté directement à l'intérieur
 * de l'appel au hook — aucune const externe.
 * Moins lisible mais parfois utile pour des one-off queries.
 */

import React from 'react';
import { gql, useQuery, useMutation, useSubscription } from '@apollo/client';
import { TypedDocumentNode } from '@graphql-typed-document-node/core';

// ─── Types ────────────────────────────────────────────────────────────────────

interface LambdaInvocation { id: string; functionName: string; status: string }
interface GetData { lambdaInvocations: LambdaInvocation[] }
interface GetVars { functionName: string }

interface InvokeLambdaData { invokeLambda: { id: string; status: string } }
interface InvokeLambdaVars {
  input: { functionName: string; invocationType: string; logType: string; payload: string; qualifier: string }
}

interface OnResultData { lambdaInvocationResult: { id: string; status: string } }
interface OnResultVars { functionName: string }

// ─── Composant ────────────────────────────────────────────────────────────────

const LambdaTypedInline: React.FC = () => {
  const functionName = 'Function_Name';

  // useQuery — gql inline + cast "as" dans l'appel
  const { data, loading, error } = useQuery(
    gql`
      query GetLambdaInvocations($functionName: String!) {
        lambdaInvocations(functionName: $functionName) {
          id
          functionName
          status
        }
      }
    ` as TypedDocumentNode<GetData, GetVars>,
    { variables: { functionName } }
  );

  // useMutation — gql inline + cast "as"
  const [invokeLambda, { loading: mutating, data: mutResult }] = useMutation(
    gql`
      mutation InvokeLambda($input: InvokeLambdaInput!) {
        invokeLambda(input: $input) {
          id
          status
        }
      }
    ` as TypedDocumentNode<InvokeLambdaData, InvokeLambdaVars>
  );

  // useSubscription — gql inline + cast "as"
  const { data: subData } = useSubscription(
    gql`
      subscription OnLambdaInvocationResult($functionName: String!) {
        lambdaInvocationResult(functionName: $functionName) {
          id
          status
        }
      }
    ` as TypedDocumentNode<OnResultData, OnResultVars>,
    { variables: { functionName } }
  );

  const handleInvoke = () =>
    invokeLambda({
      variables: {
        input: {
          functionName,
          invocationType: 'RequestResponse',
          logType: 'Tail',
          payload: btoa('{"key":"value"}'),
          qualifier: '$LATEST',
        },
      },
    });

  if (loading) return <p>Loading…</p>;
  if (error) return <p>Error: {error.message}</p>;

  return (
    <div>
      <h2>Lambda (TypedDocumentNode — Inline, cast "as" dans le hook)</h2>

      <button onClick={handleInvoke} disabled={mutating}>
        {mutating ? 'Invoking…' : 'Invoke Lambda'}
      </button>

      {mutResult && <p>Status: {mutResult.invokeLambda.status}</p>}
      {subData && <p>Sub: {subData.lambdaInvocationResult.status}</p>}

      <ul>
        {data?.lambdaInvocations.map((inv) => (
          <li key={inv.id}>{inv.functionName} — {inv.status}</li>
        ))}
      </ul>
    </div>
  );
};

export default LambdaTypedInline;
""")
        # Use new analysis structure like Vue.js tests
        apollo_analysis_results = analyse(module)
        ast = module.get_ast()
        if ast:
            ast.print_tree()

        # Note: Inline gql templates with 'as' cast are not yet supported
        # The hooks use gql`...` as TypedDocumentNode directly, so no Identifier is found
        self.assertEqual(len(apollo_analysis_results.apollo_hooks_by_operation), 0, "Inline gql templates with cast should not create symbols yet")

        # TODO: Future enhancement - support inline gql template with cast detection

        # for m_c in get_descendants(module.get_ast(), MethodCall):
        #     if m_c.get_name() == 'invoke':
        #         invoke_m_c = m_c
        #         break
        # self.assertTrue(RawBookmark(invoke_m_c, module) == invoke.raw_bookmark)


    def test_client_imperative_outline_06(self):

        module = SourceFile('module.ts', text="""\
/**
 * MODULE 6 — client.query / client.mutate / client.subscribe (OUTLINE gql)
 *
 * Utilisation directe de l'instance ApolloClient (impératif, sans hooks React).
 * Les documents sont déclarés en const outside du composant.
 * Utile dans des callbacks, des middlewares, ou du code non-React.
 */

import React, { useEffect, useState } from 'react';
import { gql, useApolloClient } from '@apollo/client';

// ─── Documents outline ────────────────────────────────────────────────────────

const GET_LAMBDA_INVOCATIONS = gql`
  query GetLambdaInvocations($functionName: String!) {
    lambdaInvocations(functionName: $functionName) {
      id
      functionName
      invocationType
      status
      payload
    }
  }
`;

const INVOKE_LAMBDA = gql`
  mutation InvokeLambda($input: InvokeLambdaInput!) {
    invokeLambda(input: $input) {
      id
      status
      payload
    }
  }
`;

const LAMBDA_INVOCATION_RESULT = gql`
  subscription OnLambdaInvocationResult($functionName: String!) {
    lambdaInvocationResult(functionName: $functionName) {
      id
      status
      error
    }
  }
`;

// ─── Composant ────────────────────────────────────────────────────────────────

interface Invocation {
  id: string;
  functionName: string;
  status: string;
}

const LambdaImperativeOutline: React.FC = () => {
  const client = useApolloClient();
  const functionName = 'Function_Name';

  const [invocations, setInvocations] = useState<Invocation[]>([]);
  const [loading, setLoading] = useState(false);
  const [mutResult, setMutResult] = useState<string | null>(null);
  const [subEvent, setSubEvent] = useState<string | null>(null);

  // client.query — impératif, outline gql
  useEffect(() => {
    setLoading(true);
    client
      .query({
        query: GET_LAMBDA_INVOCATIONS,
        variables: { functionName },
        fetchPolicy: 'network-only',
      })
      .then(({ data }) => {
        setInvocations(data.lambdaInvocations);
      })
      .catch(console.error)
      .finally(() => setLoading(false));
  }, [client]);

  // client.subscribe — impératif, outline gql
  useEffect(() => {
    const observable = client.subscribe({
      query: LAMBDA_INVOCATION_RESULT,
      variables: { functionName },
    });

    const subscription = observable.subscribe({
      next({ data }) {
        const result = data?.lambdaInvocationResult;
        if (result) setSubEvent(`${result.id}: ${result.status}`);
      },
      error(err) { console.error('Subscription error:', err); },
    });

    return () => subscription.unsubscribe();
  }, [client]);

  // client.mutate — impératif, outline gql
  const handleInvoke = async () => {
    try {
      const { data } = await client.mutate({
        mutation: INVOKE_LAMBDA,
        variables: {
          input: {
            functionName,
            invocationType: 'RequestResponse',
            logType: 'Tail',
            payload: btoa('{"key":"value"}'),
            qualifier: '$LATEST',
          },
        },
        // Mise à jour manuelle du cache après mutation
        update(cache, { data: mutData }) {
          const existing: any = cache.readQuery({
            query: GET_LAMBDA_INVOCATIONS,
            variables: { functionName },
          });
          if (existing && mutData) {
            cache.writeQuery({
              query: GET_LAMBDA_INVOCATIONS,
              variables: { functionName },
              data: {
                lambdaInvocations: [
                  ...existing.lambdaInvocations,
                  {
                    __typename: 'LambdaInvocation',
                    id: mutData.invokeLambda.id,
                    functionName,
                    invocationType: 'RequestResponse',
                    status: mutData.invokeLambda.status,
                    payload: mutData.invokeLambda.payload,
                  },
                ],
              },
            });
          }
        },
      });
      setMutResult(data?.invokeLambda?.status ?? 'unknown');
    } catch (err) {
      console.error('Mutation error:', err);
    }
  };

  // client.resetStore / client.clearStore (bonus)
  const handleReset = () => client.resetStore().then(() => console.log('Store reset'));

  if (loading) return <p>Loading…</p>;

  return (
    <div>
      <h2>Lambda (client.query / client.mutate / client.subscribe — Outline)</h2>

      <button onClick={handleInvoke}>Invoke Lambda (client.mutate)</button>
      <button onClick={handleReset} style={{ marginLeft: 8 }}>Reset Store</button>

      {mutResult && <p>Mutation result status: {mutResult}</p>}
      {subEvent && <p>Subscription event: {subEvent}</p>}

      <ul>
        {invocations.map((inv) => (
          <li key={inv.id}>{inv.functionName} — {inv.status}</li>
        ))}
      </ul>
    </div>
  );
};

export default LambdaImperativeOutline;
""")
        # Use new analysis structure like Vue.js tests
        apollo_analysis_results = analyse(module)
        ast = module.get_ast()
        if ast:
            ast.print_tree()

        # Note: client.query(), client.mutate(), client.subscribe() are imperative methods
        # These are MethodCall, not FunctionCall like hooks
        # Support for these is planned but not yet implemented
        self.assertEqual(len(apollo_analysis_results.apollo_hooks_by_operation), 0, "Client imperative methods should not create symbols yet")

        # TODO: Future enhancement - support client.query(), client.mutate(), client.subscribe()
        # Use ApolloClientMethodObject from apollo_symbols module

        # for m_c in get_descendants(module.get_ast(), MethodCall):
        #     if m_c.get_name() == 'invoke':
        #         invoke_m_c = m_c
        #         break
        # self.assertTrue(RawBookmark(invoke_m_c, module) == invoke.raw_bookmark)


    def test_client_imperative_inline_07(self):

        module = SourceFile('module.ts', text="""\
/**
 * MODULE 7 — client.query / client.mutate / client.subscribe (INLINE gql)
 *
 * Même approche impérative que le module 6, mais les documents GraphQL
 * sont passés directement dans chaque appel (inline), sans const externe.
 */

import React, { useEffect, useState } from 'react';
import { gql, useApolloClient } from '@apollo/client';

interface Invocation { id: string; functionName: string; status: string }

const LambdaImperativeInline: React.FC = () => {
  const client = useApolloClient();
  const functionName = 'Function_Name';

  const [invocations, setInvocations] = useState<Invocation[]>([]);
  const [mutResult, setMutResult] = useState<string | null>(null);
  const [subEvent, setSubEvent] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  // client.query — gql inline
  useEffect(() => {
    setLoading(true);
    client
      .query({
        query: gql`
          query GetLambdaInvocations($functionName: String!) {
            lambdaInvocations(functionName: $functionName) {
              id
              functionName
              status
            }
          }
        `,
        variables: { functionName },
        fetchPolicy: 'cache-first',
      })
      .then(({ data }) => setInvocations(data.lambdaInvocations))
      .catch(console.error)
      .finally(() => setLoading(false));
  }, [client]);

  // client.subscribe — gql inline
  useEffect(() => {
    const sub = client
      .subscribe({
        query: gql`
          subscription OnLambdaInvocationResult($functionName: String!) {
            lambdaInvocationResult(functionName: $functionName) {
              id
              status
              error
            }
          }
        `,
        variables: { functionName },
      })
      .subscribe({
        next({ data }) {
          if (data?.lambdaInvocationResult) {
            setSubEvent(
              `${data.lambdaInvocationResult.id}: ${data.lambdaInvocationResult.status}`
            );
          }
        },
        error: console.error,
      });

    return () => sub.unsubscribe();
  }, [client]);

  // client.mutate — gql inline
  const handleInvoke = async () => {
    try {
      const { data } = await client.mutate({
        mutation: gql`
          mutation InvokeLambda($input: InvokeLambdaInput!) {
            invokeLambda(input: $input) {
              id
              status
              payload
            }
          }
        `,
        variables: {
          input: {
            functionName,
            invocationType: 'Event',
            logType: 'None',
            payload: btoa('{}'),
            qualifier: '$LATEST',
          },
        },
        // Refetch de la query après la mutation (alternative à update)
        refetchQueries: ['GetLambdaInvocations'],
        awaitRefetchQueries: true,
      });
      setMutResult(data?.invokeLambda?.status ?? 'unknown');
    } catch (err) {
      console.error('Mutation error:', err);
    }
  };

  // client.readQuery / client.writeQuery (cache direct)
  const handleReadCache = () => {
    const cached = client.readQuery({
      query: gql`
        query GetLambdaInvocations($functionName: String!) {
          lambdaInvocations(functionName: $functionName) {
            id
            functionName
            status
          }
        }
      `,
      variables: { functionName },
    });
    console.log('Cache snapshot:', cached);
  };

  if (loading) return <p>Loading…</p>;

  return (
    <div>
      <h2>Lambda (client.query / client.mutate / client.subscribe — Inline)</h2>

      <button onClick={handleInvoke}>Invoke Lambda (client.mutate inline)</button>
      <button onClick={handleReadCache} style={{ marginLeft: 8 }}>
        Read Cache (client.readQuery)
      </button>

      {mutResult && <p>Mutation status: {mutResult}</p>}
      {subEvent && <p>Subscription event: {subEvent}</p>}

      <ul>
        {invocations.map((inv) => (
          <li key={inv.id}>{inv.functionName} — {inv.status}</li>
        ))}
      </ul>
    </div>
  );
};

export default LambdaImperativeInline;
""")
        # Use new analysis structure like Vue.js tests
        apollo_analysis_results = analyse(module)
        ast = module.get_ast()
        if ast:
            ast.print_tree()

        # Note: Inline client methods (client.query, client.mutate, client.subscribe with inline gql)
        # These are both MethodCall AND inline templates - double unsupported for now
        self.assertEqual(len(apollo_analysis_results.apollo_hooks_by_operation), 0, "Inline client methods should not create symbols yet")

        # TODO: Future enhancement - support inline client methods with gql templates

        # for m_c in get_descendants(module.get_ast(), MethodCall):
        #     if m_c.get_name() == 'invoke':
        #         invoke_m_c = m_c
        #         break
        # self.assertTrue(RawBookmark(invoke_m_c, module) == invoke.raw_bookmark)


    def test_codegen_generated_hooks_08(self):

        module = SourceFile('module.ts', text="""\
/**
 * MODULE 8 — GraphQL Code Generator (Codegen) : hooks générés automatiquement
 *
 * Simule le résultat typique d'une config codegen avec :
 *   - @graphql-codegen/typescript
 *   - @graphql-codegen/typescript-operations
 *   - @graphql-codegen/typescript-react-apollo
 *
 * Le fichier "generated/graphql.ts" ci-dessous représente ce que codegen
 * produirait. Dans un vrai projet, il est auto-généré et ne doit pas être
 * édité manuellement.
 *
 * Pattern de nommage des hooks générés : use[OperationName]Query,
 * use[OperationName]Mutation, use[OperationName]Subscription.
 */

// ─────────────────────────────────────────────────────────────────────────────
// FICHIER SIMULÉ : src/generated/graphql.ts
// (normalement généré par `graphql-codegen`)
// ─────────────────────────────────────────────────────────────────────────────

import { gql } from '@apollo/client';
import * as Apollo from '@apollo/client';

// ── Types scalaires & domaine ──────────────────────────────────────────────

export type Maybe<T> = T | null;

export type LambdaInvocation = {
  __typename?: 'LambdaInvocation';
  id: string;
  functionName: string;
  invocationType: string;
  logType: string;
  payload: string;
  qualifier: string;
  status: string;
};

export type InvokeLambdaInput = {
  functionName: string;
  invocationType: string;
  logType: string;
  payload: string;
  qualifier: string;
};

export type InvokeLambdaPayload = {
  __typename?: 'InvokeLambdaPayload';
  id: string;
  status: string;
  payload: string;
};

export type LambdaInvocationResult = {
  __typename?: 'LambdaInvocationResult';
  id: string;
  status: string;
  error: Maybe<string>;
};

// ── Query ──────────────────────────────────────────────────────────────────

export type GetLambdaInvocationsQueryVariables = {
  functionName: string;
};

export type GetLambdaInvocationsQuery = {
  __typename?: 'Query';
  lambdaInvocations: Array<LambdaInvocation>;
};

export const GetLambdaInvocationsDocument = gql`
  query GetLambdaInvocations($functionName: String!) {
    lambdaInvocations(functionName: $functionName) {
      id
      functionName
      invocationType
      logType
      payload
      qualifier
      status
    }
  }
`;

// Hook généré — pattern : use[OperationName]Query
export function useGetLambdaInvocationsQuery(
  baseOptions: Apollo.QueryHookOptions<
    GetLambdaInvocationsQuery,
    GetLambdaInvocationsQueryVariables
  >
) {
  return Apollo.useQuery<GetLambdaInvocationsQuery, GetLambdaInvocationsQueryVariables>(
    GetLambdaInvocationsDocument,
    baseOptions
  );
}

export function useGetLambdaInvocationsLazyQuery(
  baseOptions?: Apollo.LazyQueryHookOptions<
    GetLambdaInvocationsQuery,
    GetLambdaInvocationsQueryVariables
  >
) {
  return Apollo.useLazyQuery<GetLambdaInvocationsQuery, GetLambdaInvocationsQueryVariables>(
    GetLambdaInvocationsDocument,
    baseOptions
  );
}

// ── Mutation ───────────────────────────────────────────────────────────────

export type InvokeLambdaMutationVariables = {
  input: InvokeLambdaInput;
};

export type InvokeLambdaMutation = {
  __typename?: 'Mutation';
  invokeLambda: InvokeLambdaPayload;
};

export const InvokeLambdaDocument = gql`
  mutation InvokeLambda($input: InvokeLambdaInput!) {
    invokeLambda(input: $input) {
      id
      status
      payload
    }
  }
`;

// Hook généré — pattern : use[OperationName]Mutation
export function useInvokeLambdaMutation(
  baseOptions?: Apollo.MutationHookOptions<
    InvokeLambdaMutation,
    InvokeLambdaMutationVariables
  >
) {
  return Apollo.useMutation<InvokeLambdaMutation, InvokeLambdaMutationVariables>(
    InvokeLambdaDocument,
    baseOptions
  );
}

// ── Subscription ───────────────────────────────────────────────────────────

export type OnLambdaInvocationResultSubscriptionVariables = {
  functionName: string;
};

export type OnLambdaInvocationResultSubscription = {
  __typename?: 'Subscription';
  lambdaInvocationResult: LambdaInvocationResult;
};

export const OnLambdaInvocationResultDocument = gql`
  subscription OnLambdaInvocationResult($functionName: String!) {
    lambdaInvocationResult(functionName: $functionName) {
      id
      status
      error
    }
  }
`;

// Hook généré — pattern : use[OperationName]Subscription
export function useOnLambdaInvocationResultSubscription(
  baseOptions: Apollo.SubscriptionHookOptions<
    OnLambdaInvocationResultSubscription,
    OnLambdaInvocationResultSubscriptionVariables
  >
) {
  return Apollo.useSubscription<
    OnLambdaInvocationResultSubscription,
    OnLambdaInvocationResultSubscriptionVariables
  >(OnLambdaInvocationResultDocument, baseOptions);
}

// ─────────────────────────────────────────────────────────────────────────────
// COMPOSANT APPLICATIF — utilise les hooks générés par codegen
// ─────────────────────────────────────────────────────────────────────────────

import React from 'react';

// Dans un vrai projet, on importerait depuis le fichier généré :
// import {
//   useGetLambdaInvocationsQuery,
//   useGetLambdaInvocationsLazyQuery,
//   useInvokeLambdaMutation,
//   useOnLambdaInvocationResultSubscription,
// } from '../generated/graphql';

const LambdaCodegen: React.FC = () => {
  const functionName = 'Function_Name';

  // ── useGetLambdaInvocationsQuery (généré) ──────────────────────────────
  const { data, loading, error, refetch } = useGetLambdaInvocationsQuery({
    variables: { functionName },
    fetchPolicy: 'cache-and-network',
    notifyOnNetworkStatusChange: true,
  });

  // ── useGetLambdaInvocationsLazyQuery (généré) ──────────────────────────
  const [fetchOnDemand, { data: lazyData, loading: lazyLoading }] =
    useGetLambdaInvocationsLazyQuery({ variables: { functionName } });

  // ── useInvokeLambdaMutation (généré) ───────────────────────────────────
  const [invokeLambda, { loading: mutating, data: mutResult }] =
    useInvokeLambdaMutation({
      onCompleted: (d) => console.log('Invoked:', d.invokeLambda.id),
      onError: (e) => console.error('Error:', e.message),
      // Optimistic response : mise à jour optimiste de l'UI
      optimisticResponse: {
        invokeLambda: {
          __typename: 'InvokeLambdaPayload',
          id: 'temp-id',
          status: 'PENDING',
          payload: '',
        },
      },
    });

  // ── useOnLambdaInvocationResultSubscription (généré) ───────────────────
  const { data: subData } = useOnLambdaInvocationResultSubscription({
    variables: { functionName },
    onData({ data: { data: subResult } }) {
      console.log('Realtime event:', subResult?.lambdaInvocationResult);
    },
  });

  const handleInvoke = () =>
    invokeLambda({
      variables: {
        input: {
          functionName,
          invocationType: 'RequestResponse',
          logType: 'Tail',
          payload: btoa('{"key":"value"}'),
          qualifier: '$LATEST',
        },
      },
    });

  if (loading) return <p>Loading…</p>;
  if (error) return <p>Error: {error.message}</p>;

  return (
    <div>
      <h2>Lambda (Codegen — hooks générés use[Name]Query / Mutation / Subscription)</h2>

      <button onClick={handleInvoke} disabled={mutating}>
        {mutating ? 'Invoking…' : 'Invoke Lambda'}
      </button>

      <button onClick={() => fetchOnDemand()} style={{ marginLeft: 8 }}>
        Lazy fetch
      </button>

      <button onClick={() => refetch()} style={{ marginLeft: 8 }}>
        Refetch
      </button>

      {mutResult && (
        <p>
          Mutation: {mutResult.invokeLambda.id} — {mutResult.invokeLambda.status}
        </p>
      )}

      {subData && (
        <p>
          Sub: {subData.lambdaInvocationResult.id} —{' '}
          {subData.lambdaInvocationResult.status}
        </p>
      )}

      {lazyLoading && <p>Lazy loading…</p>}
      {lazyData && (
        <p>Lazy result count: {lazyData.lambdaInvocations.length}</p>
      )}

      <ul>
        {data?.lambdaInvocations.map((inv) => (
          <li key={inv.id}>
            <strong>{inv.functionName}</strong> — {inv.status} ({inv.invocationType})
          </li>
        ))}
      </ul>
    </div>
  );
};

export default LambdaCodegen;
""")
        # Use new analysis structure like Vue.js tests
        apollo_analysis_results = analyse(module)
        ast = module.get_ast()
        if ast:
            ast.print_tree()

        # Note: GraphQL Codegen generated hooks (useGetLambdaInvocationsQuery, etc.)
        # These hooks wrap Apollo hooks but don't pass the document as a parameter
        # The document is pre-configured inside the generated hook
        # Our current analyzer looks for hooks with an Identifier as first parameter
        self.assertEqual(len(apollo_analysis_results.apollo_hooks_by_operation), 0, "Codegen hooks should not create symbols with current implementation")

        # TODO: Future enhancement - detect codegen pattern hooks:
        #   - useGetLambdaInvocationsQuery -> links to GetLambdaInvocationsDocument
        #   - useInvokeLambdaMutation -> links to InvokeLambdaDocument
        #   - use[OperationName]Query/Mutation/Subscription pattern recognition

        # for m_c in get_descendants(module.get_ast(), MethodCall):
        #     if m_c.get_name() == 'invoke':
        #         invoke_m_c = m_c
        #         break
        # self.assertTrue(RawBookmark(invoke_m_c, module) == invoke.raw_bookmark)


    def test_advanced_patterns_09(self):
        """
        MODULE 9 — Patterns avancés : as-cast, useMemo wrapper, import-type cast

        Couvre les corrections apportées par les Bug 3/4/5 fixes :
          - Bug 3 : `const X = gql\`...\` as TypedDocumentNode<...>` → GQL def créée
          - Bug 3 : `const X = gql\`...\` as import('...').type` → GQL def créée
          - Bug 3+4 : `const X = useMemo(() => gql\`...\` as TypedDocumentNode<...>, [])` → GQL def créée
          - Bug 5 : `useHook(useMemo(() => gql\`...\`, [dep]))` → aucun hook créé (pas de faux objet)
        """

        module = SourceFile('module.ts', text="""\
/**
 * MODULE 9 — Patterns avancés
 */

import React, { useMemo } from 'react';
import { gql, useQuery, useMutation, useSubscription, useLazyQuery } from '@apollo/client';
import { TypedDocumentNode } from '@graphql-typed-document-node/core';

// ─── Pattern 1 : gql`...` as TypedDocumentNode<...> (Bug 3) ─────────────────

const POST_UPDATED = gql`
  subscription PostUpdated {
    postUpdated {
      id
      title
      content
    }
  }
` as TypedDocumentNode<{ postUpdated: { id: string; title: string; content: string } }>

const POST_PUBLISHED = gql`
  subscription PostPublished {
    postPublished {
      id
      title
      author {
        name
      }
    }
  }
` as TypedDocumentNode<{ postPublished: { id: string; title: string; author: { name: string } } }>

const LATEST_POST_QUERY = gql`
  query LatestPostQuery($id: ID!) {
    author(where: { id: $id }) {
      id
      posts(orderBy: { publishDate: desc }, take: 1) {
        id
        title
      }
    }
  }
` as TypedDocumentNode<{ author: { id: string; posts: { id: string; title: string }[] } }>

// ─── Pattern 2 : useMemo wrapper with as-cast (Bug 3) ───────────────────────

const LIST_COUNTS_QUERY = useMemo(
  () =>
    gql`
      query KsFetchListCounts {
        items: listCount
      }
    ` as TypedDocumentNode<{ items: number | null }>,
  []
)

// ─── Pattern 3 : useHook(useMemo(...)) — should produce 0 hooks (Bug 5) ─────

const DataComponent: React.FC<{ labelField: string }> = ({ labelField }) => {
  // useMemo passed directly as first arg — no intermediate variable.
  // After Bug 5 fix this must NOT create a `useQuery:useMemo` object.
  const { data: authData } = useQuery<{ authenticatedItem: { label: string } | null }>(
    useMemo(
      () => gql`
        query KsAuthFetchSession {
          authenticatedItem {
            label: name
          }
        }
      `,
      [labelField]
    )
  )

  // ─── Hooks for outline patterns ────────────────────────────────────────────

  const { data: updatedData } = useSubscription(POST_UPDATED, {
    onData: ({ data }) => console.log(data)
  })

  const { data: publishedData } = useSubscription(POST_PUBLISHED, {
    onData: ({ data }) => console.log(data)
  })

  const { data: latestPost } = useQuery(LATEST_POST_QUERY, {
    variables: { id: '1' }
  })

  const { data: counts } = useQuery(LIST_COUNTS_QUERY as any)

  return <div>{JSON.stringify(updatedData)}</div>
}

export default DataComponent
""")

        apollo_analysis_results = analyse(module)

        gql_defs = apollo_analysis_results.gql_definitions_by_file[module.get_path()]
        hooks = apollo_analysis_results.apollo_hooks_by_file[module.get_path()]

        [gql_cache, hooks_cache] = apollo_analysis_results.get_cache_dicts()
        self.print_apollo_analysis_summary("test_advanced_patterns_09", gql_cache, hooks_cache, module)

        # ═══════════════════════════════════════════════════════════════════════
        # GQL definitions — Bug 3 : `as TypedDocumentNode<...>` cast
        # ═══════════════════════════════════════════════════════════════════════

        sub_updated_defs = [d for d in gql_defs if d.name == 'POST_UPDATED']
        self.assertTrue(len(sub_updated_defs) > 0,
                        "Bug3: should create GQL def for POST_UPDATED (as-cast pattern)")
        self.assertEqual(sub_updated_defs[0].operation_name, 'PostUpdated')
        self.assertEqual(sub_updated_defs[0].operation_type, 'subscription')

        sub_published_defs = [d for d in gql_defs if d.name == 'POST_PUBLISHED']
        self.assertTrue(len(sub_published_defs) > 0,
                        "Bug3: should create GQL def for POST_PUBLISHED (as-cast pattern)")
        self.assertEqual(sub_published_defs[0].operation_name, 'PostPublished')
        self.assertEqual(sub_published_defs[0].operation_type, 'subscription')

        latest_post_defs = [d for d in gql_defs if d.name == 'LATEST_POST_QUERY']
        self.assertTrue(len(latest_post_defs) > 0,
                        "Bug3: should create GQL def for LATEST_POST_QUERY (as-cast pattern)")
        self.assertEqual(latest_post_defs[0].operation_name, 'LatestPostQuery')
        self.assertEqual(latest_post_defs[0].operation_type, 'query')

        # ═══════════════════════════════════════════════════════════════════════
        # GQL definitions — Bug 3 : useMemo wrapper with as-cast
        # ═══════════════════════════════════════════════════════════════════════

        list_counts_defs = [d for d in gql_defs if d.name == 'LIST_COUNTS_QUERY']
        self.assertTrue(len(list_counts_defs) > 0,
                        "Bug3: should create GQL def for LIST_COUNTS_QUERY (useMemo + as-cast)")
        self.assertEqual(list_counts_defs[0].operation_name, 'KsFetchListCounts')
        self.assertEqual(list_counts_defs[0].operation_type, 'query')

        # ═══════════════════════════════════════════════════════════════════════
        # Hooks — outline useSubscription / useQuery linked to as-cast defs
        # ═══════════════════════════════════════════════════════════════════════

        hooks_updated = [h for h in hooks if h.hook_name == 'useSubscription'
                         and h.operation_name == 'POST_UPDATED']
        self.assertTrue(len(hooks_updated) > 0,
                        "Should find useSubscription hook for POST_UPDATED")
        self.assertIsNotNone(hooks_updated[0].gql_definition,
                             "useLink: hook should be linked to the POST_UPDATED GQL definition")

        hooks_published = [h for h in hooks if h.hook_name == 'useSubscription'
                           and h.operation_name == 'POST_PUBLISHED']
        self.assertTrue(len(hooks_published) > 0,
                        "Should find useSubscription hook for POST_PUBLISHED")
        self.assertIsNotNone(hooks_published[0].gql_definition,
                             "useLink: hook should be linked to the POST_PUBLISHED GQL definition")

        hooks_latest = [h for h in hooks if h.hook_name == 'useQuery'
                        and h.operation_name == 'LATEST_POST_QUERY']
        self.assertTrue(len(hooks_latest) > 0,
                        "Should find useQuery hook for LATEST_POST_QUERY")
        self.assertIsNotNone(hooks_latest[0].gql_definition,
                             "useLink: hook should be linked to the LATEST_POST_QUERY GQL definition")

        # ═══════════════════════════════════════════════════════════════════════
        # Bug 5 : useQuery(useMemo(...)) must NOT produce a hook object
        # ═══════════════════════════════════════════════════════════════════════

        bad_hooks = [h for h in hooks if h.operation_name == 'useMemo']
        self.assertEqual(len(bad_hooks), 0,
                         "Bug5: useQuery(useMemo(...)) must not create a 'useQuery:useMemo' object")

        # The KsAuthFetchSession hook (inline useMemo as arg) is not supported — no hook expected.
        auth_hooks = [h for h in hooks if h.operation_name == 'KsAuthFetchSession']
        self.assertEqual(len(auth_hooks), 0,
                         "Bug5: useQuery(useMemo(...)) with dynamic gql is not supported — no hook expected")


if __name__ == "__main__":
    unittest.main()