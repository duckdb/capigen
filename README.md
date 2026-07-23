# capigen

Declarative C ABI generator. Define an API surface in YAML, validate it against a versioned schema, and generate code.

capigen generates DuckDB's C API and extension headers. The API spec lives in the consuming repository, versioned with that project. This repository holds only the tool and its schema.

There are three distinct things in play:

- **The IDL schema** (`src/capigen/schema/`) JSON Schema files defining a valid API spec. It defines constructs (types, functions, enums, ...), their fields, and their allowed values. See [schema_reference.md](schema_reference.md) for the complete reference, including how spec authors wire it into their editor for inline validation ([Editor autocomplete](schema_reference.md#editor-autocomplete)).
- **capigen** (`src/capigen/`) validates a spec against the schema and can dispatch to a pluggable adapter for code generation.
- **Adapters** (`src/capigen/adapters/`) are the code generators. capigen ships the `c` adapter (the C header), the `bridge` adapter (C++ stub skeletons for unimplemented functions), and the `extension_header` adapter (a versioned function-pointer-struct extension header). These are in-tree and versioned with the schema, because their output defines the contract.

The schema, capigen, and the adapters are versioned together. A schema change (new construct, new field) requires updating capigen and its adapters. An API spec is independent, adding a function only changes that consumer's YAML.

## Usage

Using the `c` adapter:

```bash
uv run capigen c --spec-dir /path/to/api_spec -o header.h
```

`--spec-dir` points at a directory containing `metadata.yaml` and the module YAMLs.
Adapter options live in `<spec-dir>/options/<adapter>.yaml` (override with
`--options PATH`) and are validated against the adapter's own schema before
generation. The adapter name resolves as a built-in under `capigen.adapters` first,
then as any importable module exposing `generate()`. The CLI is a thin runner
(load, validate, dispatch), so an out-of-tree generator can use it instead of
writing its own entry point.

```bash
uv run capigen --version           # package version (e.g. 0.5.0)
uv run capigen --schema-version    # supported schema version (e.g. 0.5)
```

## Project layout

```
src/capigen/
  __init__.py          # public API: load(), Spec, SpecError, __version__, SCHEMA_VERSION
  __main__.py          # CLI entry point
  spec.py              # capigen.load(): one-call load + validate, returns Spec
  anchors.py           # [[name]] cross-references in descriptions
  loader.py            # YAML loading, JSON Schema validation, schema_version check
  validate.py          # cross-module referential integrity checks
  states.py            # lifecycle state vocabulary
  tools.py             # shared spec utilities (ordering, enum numbering, versions)
  schema/              # the IDL schema (JSON Schema), versioned with capigen
    metadata.schema.json
    module.schema.json
  adapters/
    c/                 # C header adapter (resolve, render, templates)
    bridge/            # C++ stub-skeleton adapter
    extension_header/  # versioned extension function-pointer-struct adapter
tests/                 # pytest suite with a self-contained testspec fixture tree
schema_reference.md    # module-schema reference
```

## How it works

1. **Load** the spec (YAML), validate each file against the IDL schema (JSON Schema), and fill omitted fields from schema-declared defaults.
2. **Check compatibility** between the spec's declared `schema_version` and this capigen (see Versioning).
3. **Cross-module validation** of referential integrity (type references resolve, versions exist in metadata). This is the one thing JSON Schema cannot express, since it validates one file at a time.
4. **Adapter** resolves spec dicts into language-specific render objects, then renders templates and writes the output.

Steps 1-3 are language-agnostic; step 4 is the adapter's job.

## The contract

A capigen version plus a spec version fully determines the generated contract
artifacts. capigen's version pins the spec language: the schema, spec parsing and
validation, and the generation of the C header and the extension header. The spec is
versioned with its owner (for DuckDB: the duckdb repository), and the generated
`duckdb.h` and `duckdb_extension.h` are the real ABI contracts everything downstream
relies on.

ABI *stability* is not a property of that combination. The lifecycle states are the
mechanism; the stability promise (what freezes, what may disappear, when) is policy,
enforced in the spec owner's repository through its spec discipline and CI.

Language bindings (DuckDB.jl's Julia layer, a future Rust binding) are consumers of
the C ABI, not contracts themselves. Their generators live with the binding and read
the spec through capigen's public library surface. The front door is one call:

```python
import capigen

spec = capigen.load("path/to/api_spec")  # load + defaults + validation; raises if invalid
spec.modules          # validated module dicts
spec.metadata         # validated metadata
spec.states           # declared lifecycle states
spec.registry         # spec name -> C name
spec.latest_version   # the version the spec describes
```

Below it, the pieces are importable individually: `capigen.states`
(`resolve_states`, `current_state`) and `capigen.tools` (name registry, enum
numbering, alias chasing, version ordering, module ordering).

A binding generator pins `capigen~=X.Y` to read specs of that schema line; its
correctness oracle is the binding's own test suite against the real library.

## Versioning

The package version and the schema version are coupled: **`MAJOR.MINOR` of the package is the schema version; `PATCH` is tool-only.** A spec pins the language it is written against with a two-part `schema_version`:

```yaml
# metadata.yaml
schema_version: "0.5"
```

The loader accepts a spec when the majors match and the spec minor is at most the tool minor (an older spec is valid under a newer additive schema), and refuses otherwise with an actionable message. `capigen.SCHEMA_VERSION` is derived from the installed package version, so the two cannot drift.

| What changed                        | Version bump      |
|-------------------------------------|-------------------|
| Additive schema change (new field / construct) | minor |
| Breaking schema change (field removed/renamed, validation tightened) | major |
| Tool-only fix (rendering, bug fix), no schema delta | patch |

A consumer repo pins a compatible capigen (e.g. `capigen~=0.5.0`) and, because generated headers are typically committed and checked in CI, locks an exact version for reproducible output. See [RELEASING.md](RELEASING.md) for the full policy.

## Writing an adapter

An in-tree adapter is a module under `capigen.adapters` exposing:

```python
def generate(modules: list[dict], metadata: dict, output_path: Path) -> None
```

- `modules` is a list of validated spec dicts (defaults applied).
- `metadata` carries `primitives` (with C ABI type names), `suffixes` (naming conventions per construct), `versions`, `lifecycle_states`, and `schema_version`.
- Adapter options arrive separately via the `options` keyword argument. An adapter that takes options ships an `options.schema.json` in its directory and exports it as `OPTIONS_SCHEMA`; the CLI validates the options file against it.
- Adapters may accept extra keyword parameters (e.g. `scan_dir`, `template`, `internal_out`, `invocation`). The CLI passes those a given adapter declares.

In-tree is for contract-defining output (and engine tooling like the bridge). A
binding generator belongs in its binding's repository, built on the public library
surface above, with its configuration committed there.

## C adapter

The built-in C adapter lives in `src/capigen/adapters/c/` with three layers:

```
adapters/c/
  __init__.py    # entry point: wires resolve -> Jinja2 -> file
  resolve.py     # bridges spec dicts to C render objects
  render.py      # dataclass definitions for the template layer
  templates/     # Jinja2 templates that produce C code
```

It enforces a strict boundary between spec concepts and C output: `render.py` defines typed dataclasses (`CModule`, `CFunction`, `CTypeDef`, ...) that represent C-language concepts only; `resolve.py` is the only file that understands both spec structure and C semantics; `templates/` consume render objects and never see spec concepts.

`resolve.py` builds a registry mapping every declared type name to its C name. The resolution order is: primitives from `metadata.primitives`, then the registry (handles, callbacks, aliases, structs, enums), else raise. The registry is built once from all modules, so a type declared in one module is available to all others.

### Changing the C adapter when the schema changes

1. Update the schema (`module.schema.json`, and `metadata.schema.json` if relevant).
2. Update `render.py` with the new C output shape.
3. Update `resolve.py` with a `_resolve_*` function; register referenceable types in `_build_registry`.
4. Update templates.
5. Bump the schema version (this repo's package `MAJOR.MINOR`).
6. `uv run --group dev pytest`.

## Development

```bash
uv sync --group dev
uv run pre-commit install               # enable the hooks
uv run --group dev pytest               # run the test suite
uv build                                # build the wheel and sdist
```

Linting, formatting, and type checks run through pre-commit (ruff, ruff-format, ty). Run
them all at once with `uv run pre-commit run --all-files`.

CI runs pre-commit, the test suite (Python 3.12-3.14), and a build smoke check on every
push and pull request. Tagging `vX.Y.Z` publishes that version to PyPI via trusted
publishing (see [RELEASING.md](RELEASING.md)).
