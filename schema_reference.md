# IDL Schema Reference

Reference for the spec files capigen reads: one `metadata.yaml` and any number of
module YAML files. It matches `src/capigen/schema/metadata.schema.json` and
`module.schema.json`.

## Editor autocomplete

For inline validation and completion, point your editor at the schema. Editors that use
`yaml-language-server` (including the Red Hat YAML extension for VS Code) read a `$schema`
modeline in a comment at the top of the file. Pin the tag to the schema version your spec
targets.

```yaml
# metadata.yaml
# yaml-language-server: $schema=https://cdn.jsdelivr.net/gh/duckdb/capigen@v0.5.0/src/capigen/schema/metadata.schema.json
```

```yaml
# a module file
# yaml-language-server: $schema=https://cdn.jsdelivr.net/gh/duckdb/capigen@v0.5.0/src/capigen/schema/module.schema.json
```

Every schema change is at least a minor bump, so all patch tags in a `MAJOR.MINOR` line
carry the same schema. Pin to the first tag of the line: `v0.5.0` for schema `0.5`.

`raw.githubusercontent.com` serves the same files if you would rather not depend on
jsDelivr. Keep the path, change the host:

```
https://raw.githubusercontent.com/duckdb/capigen/v0.5.0/src/capigen/schema/module.schema.json
```

## Two conventions first

These two fields repeat across most constructs. They are documented here once and left
out of the per-construct tables below.

**`description`.** Optional string. Becomes a doc comment in the generated output. Every
construct in a module file accepts one.

**`lifecycle`.** Optional lifecycle history. A list of entries, newest first. The top
entry is the construct's current state. Each entry is `[state, version, date]`:

- `state`: names a state the spec declares (see `lifecycle_states` under metadata.yaml).
- `version`: `vX.Y.Z`.
- `date`: `YYYY-MM-DD`.

`lifecycle` is accepted on handles, callbacks, aliases, structs, enums, and functions.

```yaml
lifecycle:
  - ["frozen", "v1.5.4", "2026-05-18"]
```

The current state's visibility decides how the C adapter emits the construct: plainly,
behind a guard, or not at all. Cross-module validation checks each state name against
the declared states, and rejects a construct that references anything some guard
configuration compiles out while the construct itself remains present.

---

## metadata.yaml

Global settings shared by all modules.

| Field | Required | Description |
|---|---|---|
| `schema_version` | yes | Schema version this spec targets. `MAJOR.MINOR`. A legacy `MAJOR.MINOR.PATCH` is accepted and the patch is ignored. |
| `versions` | yes | The described API's known versions (`vX.Y.Z`). Validates `added` / `deprecated` on functions. The spec describes the API as of the latest of these. |
| `suffixes` | yes | ABI naming suffix per construct type. See below. |
| `primitives` | yes | Primitive type vocabulary. See below. |
| `prefix` | no | Prepended to every generated identifier. E.g. `duckdb_v2_` gives `duckdb_v2_open`. Uppercased for constants and enum values. |
| `lifecycle_states` | no | The lifecycle states constructs can be in, and how each renders. See below. Only declared states exist. |
| `options` | no | Adapter settings, keyed by adapter name (`c`, `bridge`, `extension`). Each adapter reads its own namespace. Schema-validated: a typo or an unknown namespace fails at load. See below. |

### suffixes

Three keys, all required: `handles`, `callbacks`, `aliases`. Each value is the suffix
for that construct (for example `_handle`, `_cb`, `_t`). The values are yours to choose.

### lifecycle_states

A map of state name to visibility. A construct's `lifecycle` entries must name
declared states. Gated visibilities carry their macro token:

```yaml
lifecycle_states:
  unstable:   {visibility: opt_in,  guard: LIB_API_UNSTABLE}
  stable:     {visibility: always}
  frozen:     {visibility: always}
  deprecated: {visibility: opt_out, guard: LIB_API_NO_DEPRECATED}
  removed:    {visibility: never}
```

| Visibility | Rendering | Guard |
|---|---|---|
| `always` | Always emitted. | forbidden |
| `opt_in` | Behind `#ifdef guard`. The consumer defines the macro to get it. | required |
| `opt_out` | Behind `#ifndef guard`. The consumer defines the macro to drop it. | required |
| `never` | Not emitted at all. | forbidden |

There is no built-in vocabulary. A spec declares every state it uses; without a
`lifecycle_states` block no states exist, and any `lifecycle` entry fails validation.
The block above is a conventional starting point, not a default.

The guard token lives on the state, so every adapter reads the same declaration. The
extension_header adapter gates appended members with the `unstable` state's guard and
requires that state to be `opt_in`. The bridge adapter defines every `opt_in` guard at
the top of the stub file, because the engine implements the full surface.

A function's legacy `deprecated` field gates with the `deprecated` state's guard, and
only when that state is declared with visibility `opt_out`. Without one, the field is
metadata only.

### primitives (list items)

| Field | Required | Description |
|---|---|---|
| `name` | yes | Abstract name used in specs (e.g. `u32`, `opaque`, `char`). |
| `c_type` | yes | C type in the ABI (e.g. `uint32_t`, `void`). |
| `underlying` | no | If set, the header emits `typedef <underlying> <c_type>;` in its preamble. |

### options

Per-adapter rendering settings. What a construct *is* lives in the spec proper (types,
signatures, states); how an adapter *renders* it lives here. Guard tokens are not
options: they live on the state declarations.

`options.c`, all optional:

| Field | Default | Description |
|---|---|---|
| `comment_width` | `120` | Column budget deciding `//!` line vs `/*! */` block. |
| `export_macro` | `{PREFIX}C_API` | Symbol export/visibility macro on every declaration. |
| `extension_export_macro` | `{PREFIX}EXTENSION_API` | Export macro for extension entrypoints. |
| `deprecated_macro` | `{PREFIX}DEPRECATED` | Attribute macro name. |
| `emit_deprecated_attribute` | `false` | Put the attribute macro on deprecated declarations. Presence is the states' job; this only adds the compiler warning. |
| `typedef_guard_prefix` | `{PREFIX}TYPEDEF_` | Prefix of qualified-alias include guards. |
| `banner` | derived | Verbatim banner at the top of the header. |
| `handles` | `void_ptr` | `default_style` / `override_style`. See handle styles in `CLAUDE.md`. |
| `emit_enum_max_member` | `true` | Append the int-max sentinel to every enum. |
| `emit_v1_primitive_defs` | `false` | Emit the hand-rolled V1 preamble definitions. |
| `emit_arrow_defs` | `false` | Emit the Arrow C Data Interface structs in the preamble. |
| `emit_extension_api` | `false` | Emit the `duckdb_extension_access` struct. |

`options.bridge`, all optional: `stub_return` (default `{PREFIX}API_ERROR`),
`include_header` (header the stub file includes).

`options.extension`: `create_method`, `version_macro_prefix`, and `internal_include`
are required; `exclude_functions` is optional. The struct's version is derived from
the template's newest stable `// vX.Y.Z` region tag, never configured.

Binding generators (for example DuckDB.jl's Julia generator) live with their
binding, not here, and carry their own configuration. They read the spec through
capigen's public library surface; see the capigen README.

---

## Module files

Each module describes one area of the API. Only `module` is required. Every other
section defaults to empty.

```yaml
module: database    # required
handles: {}
callbacks: {}
aliases: {}
structs: {}
enums: {}
constants: {}
error_groups: {}
functions: {}
```

The generated canonical name of a type is `prefix` + name + suffix. See the `prefix` and
`suffixes` fields above.

---

## handles

Opaque pointer types. The internals are hidden from consumers.

```yaml
handles:
  connection:
    description: A connection to a database.
    cleanup_with: disconnect
```

| Field | Required | Default | Description |
|---|---|---|---|
| `cleanup_with` | no | none | Name of the function that destroys this handle. |

Plus `description` and `lifecycle`.

---

## callbacks

Function pointer typedefs.

```yaml
callbacks:
  scalar_func_bind:
    return_type: opaque
    parameters:
      info:
        type: bind_info
```

| Field | Required | Default | Description |
|---|---|---|---|
| `return_type` | yes | none | Return type name (primitive or declared). |
| `return_pointer` | no | `0` | Pointer indirection on the return type. |
| `return_const` | no | `false` | Const-qualify the return type. |
| `parameters` | no | `{}` | Map of parameter name to Parameter. See below. |

Plus `description` and `lifecycle`.

---

## aliases

Named type aliases.

```yaml
aliases:
  error_code:
    underlying: u32
    description: "Full 32-bit error code."
```

| Field | Required | Default | Description |
|---|---|---|---|
| `underlying` | yes | none | The aliased type (primitive or declared). |
| `qualified` | no | `false` | If true, emit the key verbatim: no prefix, no suffix. Use for names owned elsewhere (e.g. `idx_t`, `sel_t`). |

Plus `description` and `lifecycle`.

---

## structs

Composite types with visible fields. Use `handles` for opaque types.

```yaml
structs:
  date:
    fields:
      - {name: days, type: i32}
```

| Field | Required | Default | Description |
|---|---|---|---|
| `pointer_alias` | no | `false` | Also emit a pointer typedef (name + aliases suffix). |
| `fields` | no | `[]` | Ordered list of struct fields. See below. |

Plus `description` and `lifecycle`.

### Struct field

A field is a **leaf** or an **aggregate**. A leaf sets `type`. An aggregate sets `fields`
(a nested struct) or `union` (a union of named members). Exactly one of `type`, `fields`,
or `union` is present.

| Field | Required | Default | Description |
|---|---|---|---|
| `name` | yes | none | Field name. |
| `type` | leaf | none | Type name (primitive or declared). |
| `pointer` | no | `0` | Pointer indirection. Leaf only. |
| `const` | no | `false` | Const-qualify the field. Leaf only. |
| `array_size` | no | none | Render as `name[N]`. Leaf only. Excludes `pointer > 0`. |
| `fields` | aggregate | none | Anonymous nested struct. Excludes `type` and `union`. |
| `union` | aggregate | none | Anonymous union of members. Excludes `type` and `fields`. |

A field accepts `description`. It does not accept `lifecycle`.

A union member has `name` (required), `fields` (required), and `description`.

```yaml
structs:
  string:
    fields:
      - name: value
        union:
          - name: pointer
            fields:
              - {name: length, type: u32}
              - {name: prefix, type: char, array_size: 4}
              - {name: ptr, type: char, pointer: 1}
          - name: inlined
            fields:
              - {name: length, type: u32}
              - {name: inlined, type: char, array_size: 12}
```

---

## enums

Enumerations with auto-numbered values.

```yaml
enums:
  TYPE:
    values:
      TYPE_INVALID: {value: 0, description: Invalid type}
      TYPE_BOOLEAN: {description: bool}
      TYPE_TINYINT: {}
```

| Field | Required | Default | Description |
|---|---|---|---|
| `values` | no | `{}` | Map of member name to value. Order sets auto-numbering. |

Plus `description` and `lifecycle`.

The C adapter appends `<ENUM_NAME>_MAX_ENUM = 0x7FFFFFFF` as the last member of every
enum. The int-max member pins the underlying type to at least 32 bits, so the ABI stops
depending on compiler flags like `-fshort-enums`. A spec member with that exact name is
an error. Disable globally with `options.c.emit_enum_max_member: false`.

### Enum value

| Field | Required | Default | Description |
|---|---|---|---|
| `value` | no | none | Explicit integer. If omitted, continues from the previous member. |

Plus `description`. No `lifecycle`.

---

## constants

Named compile-time values.

```yaml
constants:
  API_ERROR:
    value: "0xFFFFFFFF"
    description: Sentinel for an unspecified internal error.
```

| Field | Required | Default | Description |
|---|---|---|---|
| `value` | yes | none | Integer or string expression. |

Plus `description`. No `lifecycle`.

---

## error_groups

Hierarchical error codes. The full 32-bit value is `(group_id << 16) | code`.

```yaml
error_groups:
  IO:
    group_id: 0x0001
    description: Input/output errors.
    entries:
      ERROR_IO_FILE_NOT_FOUND:
        code: 0x0001
        description: File not found.
```

| Field | Required | Default | Description |
|---|---|---|---|
| `group_id` | yes | none | Upper 16 bits of the error code. |
| `entries` | yes | none | Map of error name to entry. |

Plus `description`. No `lifecycle`.

### Error entry

| Field | Required | Default | Description |
|---|---|---|---|
| `code` | yes | none | Lower 16 bits of the error code. |

Plus `description`. No `lifecycle`.

---

## functions

API function declarations.

```yaml
functions:
  open:
    description: Open a database at the given path.
    role: constructor
    belongs_to: database
    parameters:
      path:
        type: char
        indirection: 1
        const: true
        description: Path to the database file.
      out_database:
        type: database
        indirection: 1
        kind: OUT
        description: The opened database.
    return_type: API_CALL
    added: "1.2.0"
```

| Field | Required | Default | Description |
|---|---|---|---|
| `role` | no | `method` | One of `constructor`, `destructor`, `getter`, `setter`, `method`. |
| `belongs_to` | no | none | The type this function operates on. |
| `parameters` | no | `{}` | Map of parameter name to Parameter. Order sets the signature. |
| `return_type` | no | none | Return type name (declared type, alias, or primitive). |
| `return_pointer` | no | `0` | Pointer indirection on the return type. |
| `return_const` | no | `false` | Const-qualify the return type. |
| `return_description` | no | none | Description of the return value. |
| `added` | no | none | API version when introduced (`vX.Y.Z`, from `versions`). |
| `deprecated` | no | none | API version when deprecated (`vX.Y.Z`, from `versions`). |
| `static_inline` | no | `false` | Emit as a `static inline` in the header. |

Plus `description` and `lifecycle`.

---

## Parameter

Used by `functions` and `callbacks`.

| Field | Required | Default | Description |
|---|---|---|---|
| `type` | yes | none | Type name (primitive or declared). |
| `indirection` | no | `0` | Pointer level. 0 is by value, 1 is a pointer, 2 is pointer-to-pointer. |
| `const` | no | `false` | Const-qualify the parameter. |
| `kind` | no | `IN` | Direction and ownership. See below. |

Plus `description`.

### kind

`kind` combines direction and ownership into one value. Only these four combinations are
meaningful.

| Value | Direction | Ownership | Meaning |
|---|---|---|---|
| `IN` | input | borrowed | Callee reads it. Caller keeps ownership. |
| `IN_TRANSFER` | input | transferred | Callee takes ownership. Caller must not free. |
| `OUT` | output | owned | Callee writes it. Caller frees or destroys it. |
| `OUT_BORROW` | output | borrowed | Callee returns a pointer into its own state. Caller must not free. Valid while the owning object lives. |

`OUT` and `OUT_BORROW` require `indirection >= 1`.
