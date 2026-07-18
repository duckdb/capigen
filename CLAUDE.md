# Working on capigen

capigen is an engine-agnostic C ABI generator. It reads an API spec (YAML), validates it
against a versioned JSON Schema, and runs an adapter to produce output. See `README.md`
for the overview and `schema_reference.md` for the full spec-field reference.

This file is guidance for working on capigen itself.

## Commands

```bash
uv sync --group dev
uv run --group dev pytest                     # tests
uvx ruff check . && uvx ruff format --check .  # lint
uvx ty check src/capigen                       # type check
uv build                                       # wheel + sdist
uv run capigen c --spec-dir <dir> -o out.h     # run the C adapter
```

## Pre-commit

Use pre-commit to run the checks (ruff, ruff-format, ty) on each commit. Install the hooks
once per clone:

```bash
uv run pre-commit install
```

A repo that consumes capigen should run the generator from a pre-commit hook too, so its
committed output stays in sync with the spec.

## Repo map

```
src/capigen/
  __init__.py     # __version__, SCHEMA_VERSION
  __main__.py     # CLI
  loader.py       # load YAML, validate against JSON Schema, check schema_version
  validate.py     # cross-module referential integrity
  tools.py        # module dependency ordering
  schema/         # the IDL schema (JSON Schema)
  adapters/
    c/            # C header: resolve.py, render.py, templates/
    bridge/       # C++ stub skeletons for unimplemented functions
    extension_header/  # versioned function-pointer-struct header
tests/            # pytest, with a self-contained testspec fixture tree
```

## The pipeline

1. Load. Read the spec, validate each file against the schema, apply schema defaults.
2. Compatibility. Check the spec's `schema_version` against this tool (`loader.py`).
3. Cross-module validation. Type references resolve, versions exist. JSON Schema cannot
   do this, because it sees one file at a time.
4. Adapter. Resolve spec dicts into render objects, render templates, write output.

Steps 1 to 3 are adapter-agnostic. Step 4 is the adapter.

## Versioning

The package version and the schema version are coupled. `MAJOR.MINOR` of the package is
the schema version. `PATCH` is tool-only. `SCHEMA_VERSION` is derived from the installed
version, so the two cannot drift. A spec pins a two-part `schema_version`. See
`RELEASING.md` for the rules.

## Changing the schema or an adapter

1. Update the schema (`schema/module.schema.json`, and `metadata.schema.json` if needed).
2. Update the adapter. `render.py` for the output shape, `resolve.py` for spec to render
   objects (register new referenceable types in `_build_registry`), then `templates/`.
3. Update `schema_reference.md`.
4. Bump the version. Additive schema change is a minor. Breaking change is a major.
5. `uv run --group dev pytest`.

## Spec-language features

`schema_reference.md` is the field reference. This section covers behavior and gotchas
the field tables do not. Examples use a `lib_` prefix and a `_handle` suffix. Both come
from the consumer's `metadata.yaml`.

### Descriptions

`description` is accepted on most constructs (see `schema_reference.md` for the exact
list). The C adapter renders it as `//!` lines just above the generated `typedef`. A
multi-line description (a YAML block scalar with `|`) becomes one `//!` line per
non-empty input line, with leading and trailing whitespace stripped. An empty or
whitespace-only description emits nothing.

```yaml
handles:
  connection:
    description: A connection to a database.
```

```c
//! A connection to a database.
typedef void *lib_connection_handle;
```

The filter that emits these lines is `_c_line_comment` in
`src/capigen/adapters/c/__init__.py`. It is consumed by `_c_fragments/_type.j2` and
`_c_fragments/_struct.j2`.

### Prefix application

`metadata.yaml` declares a `prefix` that is prepended to every generated identifier.
Modules declare bare names. The generator applies the prefix.

Casing rules (`_apply_prefix` in `adapters/c/resolve.py`):

- For handles, callbacks, aliases, and structs, the prefix is applied as written if the
  bare name starts with a lowercase letter, and uppercased if it starts with an uppercase
  letter. So `connection` becomes `lib_connection_handle`, while `API_CALL` becomes
  `LIB_API_CALL_t`.
- For enums, constants, error groups, enum members, and error entries, the prefix is
  always uppercased. These are macro and member names by convention.

Setting `prefix: ""` (or omitting it) disables prefixing. Declared names become the C
names verbatim.

### Handle styles (void_ptr vs tagged_struct)

By default a handle is an opaque `void *` typedef:

```c
typedef void *lib_connection_handle;
```

Set the `tagged_struct` style for stronger type discipline. The compiler then refuses to
convert between unrelated handle types:

```c
typedef struct _lib_connection {
    void *internal_ptr;
} *lib_connection_handle;
```

Configure it under the C adapter's namespace in `metadata.yaml`:

```yaml
options:
  c:
    handles:
      default_style: tagged_struct   # void_ptr (default) or tagged_struct
      override_style:
        error_info: void_ptr         # keep this one a plain void*
```

`default_style` sets every handle. `override_style` maps a bare handle name to an
alternative. Only `void_ptr` is honored as an override; any other value inherits the
default. The schema validates only the top-level shape of `options`, so a typo under
`options.c.handles` is not caught. Verify by inspecting the output.

Changing a handle's style is an ABI break. The typedef name stays the same but the type
identity does not. Decide per handle when you introduce it.

### Qualified aliases

By default an alias gets the prefix and the alias suffix. Set `qualified: true` to emit
the key verbatim, with no prefix and no suffix:

```yaml
aliases:
  idx_t:
    underlying: u64
    qualified: true
```

```c
typedef uint64_t idx_t;
```

Use this for a name owned elsewhere (another header or an external library). Notes:

- A qualified alias still declares `underlying`. `qualified` only affects the left-hand
  side of the `typedef`.
- It is registered under its verbatim name. Other modules reference it by that name.
- The key is a C identifier, so it must match `^[A-Za-z_][A-Za-z0-9_]*$`.

## Comment and doc style

- Keep comments short. One short line as a rule. More than one line only in exceptional
  cases.
- Let the code carry the meaning. Too many large comments make code harder to read.
- Do not write a comment about how a change was made or which issue it fixes. For example,
  not "add +1 to fix an off-by-one". That goes in the commit message or the PR, not the
  code.
- Prose docs: short sentences, no em-dashes, DRY. Factor shared text out rather than
  repeat it.

## Other conventions

- Python: keep `ruff` and `ty` clean.
- The schema, capigen, and the adapters are versioned together. A consumer's spec is
  separate.
