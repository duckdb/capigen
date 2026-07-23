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
  spec.py         # capigen.load(): one-call load + validate, returns Spec
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

capigen's version pins the contract machinery: the schema, spec parsing and
validation, and the C header and extension header generation. capigen version plus
spec version equals the contract. ABI stability itself is duckdb-repo policy,
enforced there through spec discipline; the lifecycle states are only the mechanism.
Binding generators (DuckDB.jl's Julia layer) live with their bindings and consume
the public library surface (loader, validate, states, tools).

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
list). The C adapter renders it just above the construct it documents. An empty or
whitespace-only description emits nothing.

A description is prose, so its line breaks are the spec's, not the header's. A
multi-line description (a YAML block scalar with `|`) is collapsed to one line per
paragraph. A blank line separates paragraphs, and a list item (`- `, `* `, `1. `) keeps
its own line until the text dedents out of it.

A description that fits on one line renders as `//!`. Anything longer renders as a
`/*! ... */` block, so a comment spanning several lines reads as one comment:

```yaml
handles:
  connection:
    description: A connection to a database.
  cursor:
    description: |
      A cursor over a result.

      Destroy it before the connection.
```

```c
//! A connection to a database.
typedef void *lib_connection_ptr;

/*!
 * A cursor over a result.
 *
 * Destroy it before the connection.
 */
typedef void *lib_cursor_ptr;
```

Line length is not the generator's business beyond choosing between those two forms.
It emits one long line per paragraph, and every line carries its comment prefix, which
is what lets a C formatter (`clang-format` and friends) reflow the comment to the
consumer's column limit. Emitting a bare continuation line instead would strand it
outside the comment, where no formatter can recover it.

`options.c.comment_width` (default 120) is the column budget the form is chosen against.
Set it to the consumer's formatter limit.

The same rules apply to every documented construct: a typedef, an enum and its members,
a constant, an error code, a struct and its fields, a callback, a function. A documented
entry is preceded by a blank line, so a comment always reads as belonging to what
follows it, never to what precedes it. The exception is the first entry inside a `{}`
body, which follows its opener directly.

`src/capigen/adapters/c/comments.py` holds this logic and is exposed to the templates as
the `c_doc` filter (a description, indent-aware) and the `c_lines` filter (raw prefixed
lines, for the pieces of a function's `/*! ... */` block).

An `[[anchor]]` in a description names another construct by its bare spec name.
Validation checks it resolves and that double brackets hold nothing else
(`validate.py`, pass 5). The C adapter rewrites anchors as a post-step
(`rewrite_doc_anchors`, like the enum sentinel), before the comment form is chosen,
so the resolved length decides `//!` versus block. The parser lives in
`src/capigen/anchors.py`; binding generators use its `rewrite_anchors` with their own
name mapping. The rules are in `schema_reference.md`.

### Prefix application

`metadata.yaml` declares a `prefix` that is prepended to every generated identifier.
Modules declare bare names. The generator applies the prefix.

Casing rules (`_apply_prefix` in `adapters/c/resolve.py`):

- For handles, callbacks, aliases, and structs, the prefix is applied as written if the
  bare name starts with a lowercase letter, and uppercased if it starts with an uppercase
  letter. So `connection` becomes `lib_connection_handle`, while `API_CALL` becomes
  `LIB_API_CALL_t`.
- For enums, constants, and enum members, the prefix is
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

Configure it in the C adapter's options file (`options/c.yaml` next to the spec's
`metadata.yaml`):

```yaml
handles:
  default_style: tagged_struct   # void_ptr (default) or tagged_struct
  override_style:
    error_info: void_ptr         # keep this one a plain void*
```

`default_style` sets every handle. `override_style` maps a bare handle name to an
alternative. Only `void_ptr` is honored as an override; any other value inherits the
default. Each adapter's options file is validated against the adapter's own strict
schema before generation, so a typo fails at load.

Changing a handle's style is an ABI break. The typedef name stays the same but the type
identity does not. Decide per handle when you introduce it.

### Lifecycle states

A construct's current state is the top entry of its `lifecycle` stack. The state's
visibility decides how the C adapter emits the construct. `src/capigen/states.py` resolves the declared
states; `schema_reference.md` documents the `lifecycle_states` block and the
visibility table.

There is no built-in vocabulary: a spec declares every state it uses under
`lifecycle_states` in metadata, and guard tokens live on the state declaration, not
in adapter options.
The conventional block gates `unstable` opt-in (`#ifdef LIB_API_UNSTABLE`) and
`deprecated` opt-out (`#ifndef LIB_API_NO_DEPRECATED`), keeps `stable` and `frozen`
visible, and omits `removed`.

```c
#ifdef LIB_API_UNSTABLE
//! An experimental scratch buffer.
typedef void *lib_scratch_ptr;
#endif
```

Gating applies to every construct that accepts `lifecycle`. A struct's forward declaration
and its definition are both guarded. An omitted construct disappears from the header
entirely.

Cross-module validation enforces one invariant: a construct may reference a type only
if every guard configuration that emits the construct also emits the type. So a visible
construct cannot reference an unstable or removed type, opt-in constructs can only
reference opt-in types under the same guard, and only omitted constructs reference
omitted types.
The check covers alias underlyings, struct fields, signatures, and a handle's
`cleanup_with`.

Per-adapter behavior:

- The bridge adapter defines every opt-in guard at the top of the stub file, because
  the engine implements the full surface. Omitted functions get no stub.
- The extension_header adapter gates appended members with the `unstable` state's guard
  and requires that state to be opt-in. Omitted functions are never appended, but a
  frozen template member whose function is now removed keeps its slot, so the vtable
  ABI never shifts.
- A function with the legacy `deprecated` field (no status) still gates with the
  deprecated state's guard via the template's own `#ifndef` wrap. The gate fires
  only when the declared states include an opt-out `deprecated` state, so the
  rendered guards always match what validation modeled.
- The old token options (`unstable_guard`, `no_deprecated_guard`) fail the C
  adapter's options schema, never silently ignored.

The division of labor is strict: what a construct is, and whether it is emitted, is
spec-level (types, signatures, states) and lives in metadata.yaml and the modules.
How an adapter renders it lives in that adapter's options file
(`options/<adapter>.yaml` next to the spec), validated against the adapter's own
schema. No option changes emission, so validation's emission model is exact.
`emit_deprecated_attribute` only adds the compiler warning attribute to deprecated
declarations; dropping a construct is spelled `{visibility: never}` on its state.

### Enum width pinning

The C adapter appends `<ENUM>_MAX_ENUM = 0x7FFFFFFF` as the last member of every enum.
The int-max member stops compilers from shrinking the underlying type (for example
under `-fshort-enums`), so struct layout and call signatures stay fixed. It pins a
floor, not an exact type. The value must stay int-max: pre-C23, an enum constant must
fit in `int`. Disable with `options.c.emit_enum_max_member: false`. A spec member named
exactly `<ENUM>_MAX_ENUM` is a resolve error.

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
