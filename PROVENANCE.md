# Provenance of `typescript_dependencies/`

This document records where the code under `typescript_dependencies/` comes from, what was
changed locally, and how much of it this extension actually needs. It exists because that
directory is **not original work of this extension**.

Last reviewed: 2026-09-02.

---

## Origin

`typescript_dependencies/` is a copy of the internal modules of CAST's own analyzers:

| Source | Evidence |
|---|---|
| `com.castsoftware.typescript` | `symbols.py`, `evaluation.py`, `resolution.py`, `resolution_links_to_js.py`, `resolve_recursively.py`, `resolution_tools.py`, `ProgramSymbol.py`, `typescript_parser/` |
| `com.castsoftware.vuejs` | `typescript_walker.py` — its own header states *"Copied from com.castsoftware.vuejs for use in GraphQL extension"* |
| CAST `light_parser` | `typescript_parser/light_parser/__init__.py` — header *"Created on 30 oct. 2014, @author: MRO"* |

The copy was taken in **February 2026** (file dates 2026-02-22, `resolution.py` 2026-02-26).
The exact source extension versions were not recorded at the time — this is a gap: without them,
the copy cannot be diffed against upstream or refreshed reliably.

Content that has nothing to do with GraphQL is included, which confirms these are whole upstream
modules rather than extracted helpers — for example database link resolution
(`symbols.py:5269`, `external_link.find_objects(self.name, 'Database Table')`) and AWS Lambda ARN
handling (`symbols.py:5986`, `arn2name4lambda`).

## Size

| | Files | Lines |
|---|---|---|
| Python modules | 16 | 23 315 |
| Native binaries | 2 | — |

The two binaries are `typescript_parser/light_parser/boost_python-vc120-mt-1_55.dll` (260 KB, PE32+
x86-64) and `typescript_parser/light_parser/utility_functions.pyd` (109 KB). **Both link against
`python34.dll`**, so they only load on a CPython 3.4 host. `splitter.py:29-33` provides a
pure-Python fallback, so a version mismatch degrades performance instead of breaking the
analysis. Note that `utility_functions.pyd` is **not tracked in git** while the `.dll` is: a fresh
clone therefore produces a package without the native splitter.

## Local modifications

The copy is **not pristine** and cannot be swapped one-for-one with an upstream version:

- `symbols.py:4-10` — a `try/except` chain was added to fall back from `cast_upgrade_1_6_17` to
  `cast_upgrade_1_6_23`, then to `pass` ("Not critical for tests").

Any other divergence from upstream is unknown, since the source version was not recorded.

## How much of it is actually needed

Measured on 2026-09-02 by static analysis of the extension's own runtime modules
(`graphql_*.py`, `ts_parser/*.py`; `tests/` excluded).

**Direct import surface — 6 modules, 9 names:**

| Imported name | From | Real uses in the runtime path |
|---|---|---|
| `get_descendants`, `is_ts_node_type`, `is_ts_symbol_type`, `Walker` | `typescript_walker` | **19** — genuinely required |
| `Symbol` | `symbols` | **5** — base class of `ApolloHookSymbol` and `GqlDefinitionSymbol` |
| `Token` | `typescript_parser.light_parser` | **1** — a single `isinstance` check (see caveat below) |
| `EvaluationTool` | `evaluation` | **1** — instantiated, but the resulting `ts_evaluate` callable is **never invoked** |
| `SourceFile` | `symbols` | **0** — imported, never used |
| `Program` | `ProgramSymbol` | **0** — imported, never used |
| `resolve_expressions` | `resolution` | **0** — imported, never used |

**At module level, 23 281 of the 23 315 lines are transitively reachable** — importing `Symbol`
pulls in `symbols.py`, which pulls in `typescript_parser/parser.py`, which pulls in the rest.
No file can be deleted while `symbols.py` is imported. The size is therefore driven by exactly
**one** dependency: the `Symbol` base class.

**Consequence:** the only module this extension truly needs at analysis time is
`typescript_walker.py` (98 lines, no internal imports — `is_ts_node_type` works by comparing
`str(type(node))`, not by `isinstance`). The remaining ~23 200 lines are pulled in by the `Symbol`
base class, an unused evaluator, and three dead imports.

The full parser **is** genuinely required by `tests/test_ts.py`, which parses TypeScript source
in isolation (`light_parse()`, `fully_parse()`, `Program()`, `resolve_expressions`) with no CAST
analyzer to do it. So the honest classification of this directory is a **test dependency that is
currently also shipped in the package**.

### Caveat on `Token`

`ts_parser/apollo_interpreter_ts.py:670` uses `isinstance(child, Token)` where `Token` is the
**vendored** class. During a real analysis the AST comes from the *installed* TypeScript
extension, whose tokens are instances of `typescript_parser.light_parser.Token` — a different
class object from `typescript_dependencies.typescript_parser.light_parser.Token`. That
`isinstance` therefore returns `False` in production, and the code silently falls back to its
regex-based "Method 2" extraction.

`typescript_walker.is_ts_node_type` avoids exactly this trap by string-comparing the type path
against **both** namespaces (`typescript_parser.parser.X` *and*
`typescript_dependencies.typescript_parser.parser.X`), which shows the problem was already known
for node types. The `Token` check was not given the same treatment.

---

## Open questions

1. **Licensing.** This repository is published under LGPL v3
   (`licenses/COPYING.LESSER.txt`, referenced by `plugin.nuspec`) in the public `CAST-Extend`
   GitHub organisation, and it redistributes CAST-authored analyzer source and a compiled CAST
   binary. Whether that is acceptable is a CAST-internal decision, not a technical one, and it
   should be confirmed before any publication on CAST Extend.
2. **Version drift.** The copy is from February 2026. If the installed
   `com.castsoftware.typescript` has changed its AST or symbol structures since, this extension
   can stop detecting anything — and because the whole import block of
   `ts_parser/apollo_interpreter_ts.py` is wrapped in a bare `try/except`, it would do so
   silently.
3. **Reduction.** Replacing the `Symbol` base class (either with a minimal local class, or by
   importing the installed extension's top-level `symbols` module at runtime) would allow the
   shipped copy to shrink to `typescript_walker.py` and keep the full parser as a test-only
   dependency, excluded from the package.
