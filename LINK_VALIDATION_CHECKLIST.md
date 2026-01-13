# Checklist de Validation des Liens Client-to-Schema

## Conditions à vérifier pour éviter les faux positifs/négatifs

### 1. **Unicité des noms de champs GraphQL**
- [ ] Vérifier qu'il n'existe qu'un seul `GraphQLField` avec un nom donné dans le type Query
- [ ] Vérifier qu'il n'existe qu'un seul `GraphQLField` avec un nom donné dans le type Mutation
- [ ] Si doublons détectés : logger un WARNING avec la liste des fichiers sources

**Implémentation suggérée :**
```python
# Au lieu de :
schema_queries[field_name] = field_obj

# Faire :
if field_name in schema_queries:
    warning('[GraphQL] DUPLICATE field "' + field_name + '" found in Query type')
    warning('[GraphQL]   Existing: ' + schema_queries[field_name].get_fullname())
    warning('[GraphQL]   New: ' + field_obj.get_fullname())
    # Stocker une liste au lieu d'un seul objet
    if not isinstance(schema_queries[field_name], list):
        schema_queries[field_name] = [schema_queries[field_name]]
    schema_queries[field_name].append(field_obj)
else:
    schema_queries[field_name] = field_obj
```

### 2. **Correspondance du fichier source**
- [ ] Extraire le fichier source du client GraphQL (via `get_position()` ou propriété)
- [ ] Extraire le fichier source du schéma GraphQL
- [ ] Vérifier que le client fait référence au bon fichier de schéma

**Méthodes possibles :**
```python
# Option 1 : Via position
client_file = client_obj.get_position().get_file()

# Option 2 : Via propriété parent
client_parent_file = client_obj.get_parent()  # Si c'est le fichier

# Option 3 : Parser le fullname
# "path/to/file.jsx.query:user" -> extraire "path/to/file.jsx"
```

### 3. **Vérification de l'import/référence explicite**
- [ ] Vérifier que le fichier client importe/référence le fichier schéma
- [ ] Checker les imports dans le fichier source (React: `import query from './schema.graphql'`)
- [ ] Utiliser `ReferenceFinder` pour chercher le nom du fichier schéma dans le client

**Exemple :**
```python
from cast.application import ReferenceFinder

# Chercher si le fichier client référence le schéma
finder = ReferenceFinder()
schema_filename = schema_obj.get_position().get_file().get_name()
references = finder.find_references(client_obj, schema_filename)
if not references:
    warning('[GraphQL] Client does not reference schema file: ' + schema_filename)
```

### 4. **Validation du type d'opération**
- [ ] Vérifier que `GraphQLClientQuery` ne se lie qu'aux champs de type `Query`
- [ ] Vérifier que `GraphQLClientMutation` ne se lie qu'aux champs de type `Mutation`
- [ ] Ne jamais croiser query ↔ mutation

**Déjà implémenté ✓** (le code actuel fait cette séparation)

### 5. **Vérification du contexte d'application**
- [ ] Si multi-applications : vérifier que client et schéma sont dans la même app
- [ ] Utiliser `application.get_application_name()` pour filtrer

### 6. **Gestion des alias GraphQL**
- [ ] Vérifier si le client utilise des alias dans sa requête
- [ ] Parser la requête GraphQL pour extraire le vrai nom du champ

**Exemple de requête avec alias :**
```graphql
query {
  currentUser: user {  # alias "currentUser" -> vrai nom "user"
    id
  }
}
```

### 7. **Validation des types de retour**
- [ ] (Optionnel, avancé) Comparer le type de retour attendu par le client avec le type défini dans le schéma
- [ ] Nécessite de parser les métadonnées de type sur les objets

### 8. **Gestion des fragments GraphQL**
- [ ] Vérifier que les fragments ne créent pas de fausses références
- [ ] Les fragments ne sont pas des opérations, ne doivent pas créer de liens

### 9. **Détection des schémas fédérés/modulaires**
- [ ] Identifier si le projet utilise Apollo Federation ou schémas multiples
- [ ] Dans ce cas, vérifier le bon sous-graphe

### 10. **Ordre de traitement des fichiers**
- [ ] S'assurer que tous les fichiers `.graphql`/`.graphqls`/`.gql` sont traités
- [ ] Logger l'ordre de découverte pour debugging

---

## Implémentation recommandée

### Version robuste de l'indexation :

```python
def _build_schema_index_safe(self, application):
    """
    Build schema index with duplicate detection and file tracking.
    
    Returns:
        tuple: (schema_queries, schema_mutations, warnings)
        - schema_queries: dict[str, list[Object]] - field name -> list of field objects
        - schema_mutations: dict[str, list[Object]]
        - warnings: list[str] - warnings about duplicates
    """
    schema_queries = {}
    schema_mutations = {}
    warnings_list = []
    
    graphql_types = [obj for obj in application.get_objects() if obj.get_type() == 'GraphQLType']
    
    for type_obj in graphql_types:
        type_name = type_obj.get_name()
        
        if type_name not in ['Query', 'Mutation']:
            continue
        
        type_obj.load_children()
        children = type_obj.get_children()
        target_dict = schema_queries if type_name == 'Query' else schema_mutations
        
        for field_obj in children:
            if field_obj.get_type() != 'GraphQLField':
                continue
            
            field_name = field_obj.get_name()
            
            # Détection de doublons
            if field_name in target_dict:
                existing = target_dict[field_name]
                if not isinstance(existing, list):
                    target_dict[field_name] = [existing]
                target_dict[field_name].append(field_obj)
                
                # Warning avec fichiers sources
                msg = 'DUPLICATE field "' + field_name + '" in ' + type_name + ' type: '
                msg += str(len(target_dict[field_name])) + ' definitions found'
                warnings_list.append(msg)
            else:
                target_dict[field_name] = field_obj
    
    return schema_queries, schema_mutations, warnings_list
```

### Version robuste du matching :

```python
def _match_client_to_schema_safe(self, client_obj, schema_dict, operation_type):
    """
    Safe matching with file verification.
    
    Args:
        client_obj: GraphQLClientQuery or GraphQLClientMutation
        schema_dict: dict of schema fields (can contain lists if duplicates)
        operation_type: 'query' or 'mutation' for logging
    
    Returns:
        list[Object]: List of schema objects to link to (empty if no match)
    """
    obj_name = client_obj.get_name()
    
    # Extract field name from "query:fieldName" or "mutation:fieldName"
    if ':' in obj_name:
        field_name = obj_name.split(':')[1]
    else:
        field_name = obj_name
    
    if not field_name or field_name not in schema_dict:
        return []  # No match
    
    schema_candidates = schema_dict[field_name]
    
    # Normalize to list
    if not isinstance(schema_candidates, list):
        schema_candidates = [schema_candidates]
    
    # If only one candidate, no ambiguity
    if len(schema_candidates) == 1:
        return schema_candidates
    
    # Multiple candidates: try to disambiguate by file reference
    try:
        client_file = client_obj.get_position().get_file()
        client_file_path = client_file.get_path()
        
        # Check which schema file is referenced by the client file
        best_matches = []
        for schema_obj in schema_candidates:
            schema_file = schema_obj.get_position().get_file()
            schema_file_name = schema_file.get_name()
            
            # Use ReferenceFinder to check if client references this schema
            finder = ReferenceFinder()
            refs = finder.find_references_in_file(client_file, schema_file_name)
            
            if refs:
                best_matches.append(schema_obj)
        
        if len(best_matches) == 1:
            return best_matches  # Unique match found via reference
        elif len(best_matches) > 1:
            warning('[GraphQL] Multiple schema files referenced for field "' + field_name + '"')
            return best_matches  # Link to all referenced schemas
        else:
            # No reference found, but we have candidates
            warning('[GraphQL] Cannot disambiguate field "' + field_name + '" - no file reference found')
            return schema_candidates  # Link to all candidates (risky but complete)
    
    except Exception as e:
        warning('[GraphQL] Error during file verification: ' + str(e))
        return schema_candidates  # Fallback to all candidates
```

---

## Tests à effectuer

### Test 1 : Schéma unique, pas de doublons
✓ Comportement attendu : liens 1:1 exacts

### Test 2 : Deux fichiers schéma avec field `user`
```
schema1.graphqls:
  type Query { user: User }

schema2.graphqls:
  type Query { user: User }
```
⚠️ Comportement attendu : WARNING de doublon, liens vers les deux ou désambiguïsation par import

### Test 3 : Client avec alias
```javascript
query {
  currentUser: user { id }
}
```
⚠️ Vérifier que le parsing extrait "user" et non "currentUser"

### Test 4 : Fragment GraphQL
```javascript
fragment UserFields on User { id, name }
```
✓ Ne doit pas créer de lien (ce n'est pas une opération)

### Test 5 : Schema fédéré (Apollo)
⚠️ Vérifier la gestion des sous-graphes

---

## Priorités d'implémentation

1. **CRITIQUE** : Détecter et gérer les doublons de champs (stockage en liste)
2. **IMPORTANT** : Vérifier la correspondance fichier client ↔ fichier schéma
3. **UTILE** : Valider les imports/références explicites
4. **AVANCÉ** : Parser les alias et fragments
5. **OPTIONNEL** : Validation des types de retour
