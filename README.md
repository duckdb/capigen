# capigen

Declarative C ABI generator. Define an API surface in YAML, validate it against a versioned schema, and generate code.

capigen generates DuckDB's C API and extension headers. The API spec lives in the consuming repository, versioned with that project. This repository holds only the tool and its schema.

There are three distinct things in play:

- **The IDL schema** (`src/capigen/schema/`) JSON Schema files defining a valid API spec. It defines constructs (types, functions, enums, ...), their fields, and their allowed values. See [schema_reference.md](schema_reference.md) for the complete reference, including how spec authors wire it into their editor for inline validation ([Editor autocomplete](schema_reference.md#editor-autocomplete)).
- **capigen** (`src/capigen/`) validates a spec against the schema and can dispatch to a pluggable adapter for code generation.
- **Adapters** (`src/capigen/adapters/`) are pluggable code generators. capigen ships the `c` adapter (produces the C header), the `bridge` adapter (produces C++ stub skeletons for unimplemented functions), and the `extension_header` adapter (produces a versioned function-pointer-struct extension header). Additional adapters can be supplied as external Python modules.

The schema, capigen, and the adapters are versioned together. A schema change (new construct, new field) requires updating capigen and its adapters. An API spec is independent, adding a function only changes that consumer's YAML.

## Usage

Using the `c` adapter:

```bash
uv run capigen c --spec-dir /path/to/api_spec -o header.h
```

`--spec-dir` points at a directory containing `metadata.yaml` and the module YAMLs. To
use an external adapter, pass its import path:

```bash
uv run capigen my_package.my_adapter --spec-dir /path/to/api_spec -o output.rs
```

The adapter name resolves as a built-in (`capigen.adapters.<name>`) first, then as a
full module path.

```bash
uv run capigen --version           # package version (e.g. 0.4.0)
uv run capigen --schema-version    # supported schema version (e.g. 0.4)
```

## Project layout

```
src/capigen/
  __init__.py          # exposes __version__ and SCHEMA_VERSION
  __main__.py          # CLI entry point
  loader.py            # YAML loading, JSON Schema validation, schema_version check
  validate.py          # cross-module referential integrity checks
  tools.py             # module dependency ordering
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

## Versioning

The package version and the schema version are coupled: **`MAJOR.MINOR` of the package is the schema version; `PATCH` is tool-only.** A spec pins the language it is written against with a two-part `schema_version`:

```yaml
# metadata.yaml
schema_version: "0.4"
```

The loader accepts a spec when the majors match and the spec minor is at most the tool minor (an older spec is valid under a newer additive schema), and refuses otherwise with an actionable message. `capigen.SCHEMA_VERSION` is derived from the installed package version, so the two cannot drift.

| What changed                        | Version bump      |
|-------------------------------------|-------------------|
| Additive schema change (new field / construct) | minor |
| Breaking schema change (field removed/renamed, validation tightened) | major |
| Tool-only fix (rendering, bug fix), no schema delta | patch |

A consumer repo pins a compatible capigen (e.g. `capigen~=0.4.0`) and, because generated headers are typically committed and checked in CI, locks an exact version for reproducible output. See [RELEASING.md](RELEASING.md) for the full policy.

## Writing an adapter

An adapter is a Python module exposing:

```python
def generate(modules: list[dict], metadata: dict, output_path: Path) -> None
```

- `modules` is a list of validated spec dicts (defaults applied).
- `metadata` carries `primitives` (with C ABI type names), `suffixes` (naming conventions per construct), `versions`, `schema_version`, and any adapter `options`.
- Built-in adapters live under `capigen.adapters`.
- External adapters are any importable module with a `generate` function.
- Adapters may accept extra keyword parameters (e.g. `scan_dir`, `template`, `internal_out`, `invocation`). The CLI passes those a given adapter declares.

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
