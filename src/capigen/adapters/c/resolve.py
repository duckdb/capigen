"""Resolve API spec dicts into C-specific render objects for Jinja2 templates."""

from ...anchors import rewrite_anchors
from ...states import State, current_state, resolve_states, version_macro_base
from ...tools import apply_prefix as _apply_prefix
from ...tools import build_registry as _build_registry
from ...tools import resolve_enum_values
from ...tools import version_key as _version_key
from .comments import DEFAULT_WIDTH
from .render import (
    CConstant,
    CEnum,
    CEnumValue,
    CField,
    CFuncPtr,
    CFuncPtrParam,
    CFunction,
    CModule,
    CParam,
    CRemoved,
    CStruct,
    CTypeDef,
    CUnionMember,
)


def _version_args(version: str) -> str:
    """A vX.Y.Z string as the argument list of a version-comparison macro."""
    return ", ".join(str(n) for n in _version_key(version))


def state_version(d: dict) -> str | None:
    """Version stamped on the construct's current lifecycle entry, if any."""
    lifecycle = d.get("lifecycle") or []
    if not lifecycle:
        return None
    entry = lifecycle[0]
    return entry[1] if len(entry) > 1 else None


def _with_history(description: str | None, d: dict) -> str:
    """Append the construct's lifecycle, oldest first, as a list of doc lines.

    The gate above a construct says what compiles it; this says why. Rendered
    through the ordinary description pipeline, so the list items keep their own
    lines and the comment form is chosen from the whole text.
    """
    entries = [e for e in (d.get("lifecycle") or []) if len(e) > 1]
    if not entries:
        return description or ""
    items = "\n".join(f"- {e[0]}: {e[1]}" for e in reversed(entries))
    history = f"history:\n{items}"
    text = (description or "").strip()
    return f"{text}\n\n{history}" if text else history


def _state_condition(state: State) -> str | None:
    """What must hold for a construct to be emitted while in this state."""
    if state.visibility in ("opt_in", "opt_out"):
        return state.allow_macro
    return None  # always: no condition


def _gating(d: dict, states: dict[str, State], gated: bool = True) -> tuple[bool, str]:
    """How a construct renders across versions: (omitted, guard directive).

    A lifecycle is a stack of dated transitions, newest first. Entry i governs
    the band from its own version up to the next newer one, so what gates a
    construct depends on the version the consumer targets, not only on the state
    it is in today. Each band contributes a term that is vacuously true outside
    itself, so the bands conjoin into a single `#if`.

    Only functions are gated (`gated=False` for everything else). A type is inert
    and unreachable without a function, so hiding it buys a consumer nothing while
    creating references that dangle at some target versions. Types still carry
    their lifecycle, which documents them and drives the `history:` comment; a
    `never` type is still omitted, since that says it is not part of the API at all.
    """
    entries = [e for e in (d.get("lifecycle") or []) if len(e) > 1]
    if not entries:
        return False, ""
    # Every declared state carries the spec's version macro, so this is empty only
    # when the spec declares no states at all — in which case no entry names a known
    # state and nothing can gate.
    macro = next((s.version_macro for s in states.values() if s.version_macro), "")
    if not macro:
        return False, ""
    floor = next((s.version_floor for s in states.values() if s.version_floor), None)

    # Removal is not version-relative. Deprecation is policy, but a removed
    # symbol is gone from the library a consumer links against, whatever version
    # it targets, so declaring it would only turn a compile error into a link one.
    current = states.get(entries[0][0])
    if current is not None and current.visibility == "never":
        return True, ""
    if not gated:
        return False, ""

    def at_least(v: str) -> str:
        return f"{macro}_AT_LEAST({_version_args(v)})"

    def below(v: str) -> str:
        return f"{macro}_BELOW({_version_args(v)})"

    terms: list[str] = []
    intro = entries[-1][1]
    # Below the oldest transition the construct did not exist. Skipped when no
    # legal target can be lower, so an always-true term is never emitted.
    if floor is None or _version_key(intro) > _version_key(floor):
        terms.append(at_least(intro))

    for i, entry in enumerate(entries):
        state = states.get(entry[0])
        if state is None:
            continue
        escapes: list[str] = []
        if i > 0:  # not the newest: this band ends where the next begins
            escapes.append(at_least(entries[i - 1][1]))
        if i < len(entries) - 1:  # not the oldest: `intro` already excludes below
            escapes.append(below(entry[1]))
        if state.visibility != "never":
            condition = _state_condition(state)
            if condition is None:
                continue  # visible unconditionally in this band
            escapes.append(condition)
        if not escapes:
            return True, ""  # removed, with no band in which it survives
        terms.append(escapes[0] if len(escapes) == 1 else f"({' || '.join(escapes)})")

    if not terms:
        return False, ""
    if len(terms) == 1:
        # A lone state condition is the classic form; keep it idiomatic.
        if terms[0].startswith("defined("):
            return False, f"#ifdef {terms[0][len('defined(') : -1]}"
        if terms[0].startswith("!defined("):
            return False, f"#ifndef {terms[0][len('!defined(') : -1]}"
    return False, f"#if {' && '.join(terms)}"


def _default_banner(prefix: str) -> str:
    """Build a generic header banner, using an uppercased prefix as the name."""
    rule = f"//==={'-' * 70}===//"
    name = prefix.strip("_").upper() or "GENERATED"
    return "\n".join(
        [
            rule,
            "//",
            f"//                         {name}",
            "//",
            "//",
            rule,
            "//",
            "// !!!!!!!",
            "// WARNING: this file is autogenerated, manual changes will be overwritten",
            "// !!!!!!!",
        ]
    )


def resolve_c_options(
    metadata: dict,
    options: dict | None = None,
    states: dict[str, State] | None = None,
) -> dict:
    """Resolve C-adapter macro names, banner, and the comment column budget."""
    prefix = metadata.get("prefix", "")
    uprefix = prefix.upper()
    c = options or {}
    if states is None:
        states = resolve_states(metadata)
    return {
        # Only decides `//!` line vs `/*! ... */` block; wrapping is the formatter's.
        "comment_width": c.get("comment_width", DEFAULT_WIDTH),
        "export_macro": c.get("export_macro", f"{uprefix}C_API"),
        "extension_export_macro": c.get(
            "extension_export_macro", f"{uprefix}EXTENSION_API"
        ),
        "deprecated_macro": c.get("deprecated_macro", f"{uprefix}DEPRECATED"),
        "emit_deprecated_attribute": bool(c.get("emit_deprecated_attribute", False)),
        "typedef_guard_prefix": c.get("typedef_guard_prefix", f"{uprefix}TYPEDEF_"),
        "banner": c.get("banner", _default_banner(prefix)),
        "emit_v1_primitive_defs": bool(c.get("emit_v1_primitive_defs", False)),
        "emit_arrow_defs": bool(c.get("emit_arrow_defs", False)),
        "emit_extension_api": bool(c.get("emit_extension_api", False)),
        # Constructs gate on the version the consumer targets, not only on state.
        # Spec-level, so this adapter and the extension header agree.
        "version_macro": version_macro_base(metadata),
        "default_version": _default_target(metadata),
        "gated_states": [
            {
                "allow": st.allow_macro,
                "guard": st.guard,
                "default": "0" if st.visibility == "opt_in" else "1",
                "legacy": "1" if st.visibility == "opt_in" else "0",
                "name": st.name,
            }
            for st in states.values()
            if st.allow_macro
        ],
    }


def _default_target(metadata: dict) -> tuple[int, int, int]:
    """The version a translation unit targets unless it says otherwise: the latest known."""
    versions = metadata.get("versions") or []
    if not versions:
        raise ValueError(
            "gating on version requires a non-empty 'versions' list in metadata"
        )
    major, minor, patch = _version_key(max(versions, key=_version_key))
    return major, minor, patch


def resolve_modules(
    modules: list[dict],
    metadata: dict,
    options: dict | None = None,
    states: dict[str, State] | None = None,
) -> list[CModule]:
    """Transform validated API spec dicts into typed C render objects.

    `options` is the C adapter's options dict; other adapters that only need
    the function view may omit it. Pass `states` to reuse an already resolved
    vocabulary.
    """
    primitives = {p["name"]: p["c_type"] for p in metadata["primitives"]}
    suffixes = metadata["suffixes"]
    prefix = metadata.get("prefix", "")
    if states is None:
        states = resolve_states(metadata)
    c_options = options or {}
    handle_opts = c_options.get("handles", {})
    handle_style = handle_opts.get("default_style", "void_ptr")
    void_ptr_handles = frozenset(
        name
        for name, style in handle_opts.get("override_style", {}).items()
        if style == "void_ptr"
    )
    registry = _build_registry(modules, suffixes, prefix)
    return [
        _resolve_module(
            mod,
            registry,
            primitives,
            suffixes,
            states,
            prefix,
            handle_style,
            void_ptr_handles,
        )
        for mod in modules
    ]


def _is_tagged_struct(
    name: str, handle_style: str, void_ptr_handles: frozenset[str]
) -> bool:
    return handle_style == "tagged_struct" and name not in void_ptr_handles


# ---------------------------------------------------------------------------
# C name resolution
# ---------------------------------------------------------------------------


def _resolve_c_name(
    symbol: str,
    registry: dict[str, str],
    primitives: dict[str, str],
    context: str,
) -> str:
    """Resolve a spec symbol name to its C type string."""
    if symbol in primitives:
        return primitives[symbol]
    if symbol in registry:
        return registry[symbol]
    raise ValueError(f"{context}: unknown type '{symbol}'")


def _format_c_type(base: str, pointer: int = 0, is_const: bool = False) -> str:
    prefix = "const " if is_const else ""
    return f"{prefix}{base}{'*' * pointer}"


# ---------------------------------------------------------------------------
# Per-module resolution
# ---------------------------------------------------------------------------


_REMOVABLE = (
    ("handles", "handle"),
    ("aliases", "alias"),
    ("structs", "struct"),
    ("enums", "enum"),
    ("callbacks", "callback"),
    ("functions", "function"),
)


def _resolve_removed(
    mod: dict, states: dict[str, State], registry: dict[str, str], prefix: str
) -> list[CRemoved]:
    """Constructs that no longer exist, kept as tombstones.

    A removed construct is not declared at any target version, because the
    symbol is gone from the library a consumer links against. Recording it
    still tells a reader what the name used to be and when it went away.
    """
    out: list[CRemoved] = []
    for key, kind in _REMOVABLE:
        for name, d in (mod.get(key) or {}).items():
            state = states.get(current_state(d) or "")
            if state is None or state.visibility != "never":
                continue
            out.append(
                CRemoved(
                    name=registry.get(name) or _apply_prefix(prefix, name),
                    version=state_version(d) or "",
                    kind=kind,
                )
            )
    return out


def _resolve_module(
    mod: dict,
    registry: dict[str, str],
    primitives: dict[str, str],
    suffixes: dict[str, str],
    states: dict[str, State],
    prefix: str = "",
    handle_style: str = "void_ptr",
    void_ptr_handles: frozenset[str] = frozenset(),
) -> CModule:
    uprefix = prefix.upper()
    return CModule(
        name=mod["module"],
        removed=_resolve_removed(mod, states, registry, prefix),
        types=(
            [
                _resolve_handle(
                    name,
                    h,
                    suffixes,
                    states,
                    prefix,
                    _is_tagged_struct(name, handle_style, void_ptr_handles),
                )
                for name, h in mod.get("handles", {}).items()
            ]
            + [
                _resolve_alias(name, a, registry, primitives, suffixes, states, prefix)
                for name, a in mod.get("aliases", {}).items()
            ]
        ),
        structs=[
            _resolve_struct(name, s, registry, primitives, suffixes, states, prefix)
            for name, s in mod.get("structs", {}).items()
        ],
        enums=[
            _resolve_enum(name, e, states, prefix)
            for name, e in mod.get("enums", {}).items()
        ],
        constants=[
            CConstant(
                name=f"{uprefix}{name}",
                value=c["value"],
                description=c.get("description", ""),
            )
            for name, c in mod.get("constants", {}).items()
        ],
        function_ptrs=[
            _resolve_callback(name, cb, registry, primitives, suffixes, states, prefix)
            for name, cb in mod.get("callbacks", {}).items()
        ],
        functions={
            f"{prefix}{fname}": _resolve_function(
                f"{prefix}{fname}", func, registry, primitives, states
            )
            for fname, func in mod.get("functions", {}).items()
        },
    )


def _resolve_handle(
    name: str,
    h: dict,
    suffixes: dict[str, str],
    states: dict[str, State],
    prefix: str = "",
    tagged_struct: bool = False,
) -> CTypeDef:
    prefixed = _apply_prefix(prefix, name)
    omitted, guard_directive = _gating(h, states, gated=False)
    return CTypeDef(
        name=prefixed,
        canonical_name=f"{prefixed}{suffixes['handles']}",
        base="void",
        is_pointer=True,
        tagged_struct=tagged_struct,
        description=_with_history(h.get("description"), h),
        omitted=omitted,
        guard_directive=guard_directive,
    )


def _resolve_alias(
    name: str,
    a: dict,
    registry: dict[str, str],
    primitives: dict[str, str],
    suffixes: dict[str, str],
    states: dict[str, State],
    prefix: str = "",
) -> CTypeDef:
    base = _resolve_c_name(a["underlying"], registry, primitives, f"Alias '{name}'")
    omitted, guard_directive = _gating(a, states, gated=False)
    if a.get("qualified"):
        return CTypeDef(
            name=name,
            canonical_name=name,
            base=base,
            is_pointer=False,
            is_qualified=True,
            description=_with_history(a.get("description"), a),
            omitted=omitted,
            guard_directive=guard_directive,
        )
    prefixed = _apply_prefix(prefix, name)
    return CTypeDef(
        name=prefixed,
        canonical_name=f"{prefixed}{suffixes['aliases']}",
        base=base,
        is_pointer=False,
        description=_with_history(a.get("description"), a),
        omitted=omitted,
        guard_directive=guard_directive,
    )


def _resolve_field(
    f: dict,
    registry: dict[str, str],
    primitives: dict[str, str],
    context: str,
) -> CField:
    """Resolve one struct field: a leaf, an anonymous struct, or an anonymous union."""
    if "union" in f:
        return CField(
            name=f["name"],
            description=f.get("description", ""),
            union_members=[
                CUnionMember(
                    name=m["name"],
                    fields=[
                        _resolve_field(mf, registry, primitives, context)
                        for mf in m["fields"]
                    ],
                    description=m.get("description", ""),
                )
                for m in f["union"]
            ],
        )
    if "fields" in f:
        return CField(
            name=f["name"],
            description=f.get("description", ""),
            nested_fields=[
                _resolve_field(nf, registry, primitives, context) for nf in f["fields"]
            ],
        )
    base = _resolve_c_name(
        f["type"], registry, primitives, f"{context} field '{f['name']}'"
    )
    return CField(
        name=f["name"],
        base=base,
        pointer=f.get("pointer", 0),
        const=f.get("const", False),
        array_size=f.get("array_size"),
        description=f.get("description", ""),
    )


def _resolve_struct(
    name: str,
    s: dict,
    registry: dict[str, str],
    primitives: dict[str, str],
    suffixes: dict[str, str],
    states: dict[str, State],
    prefix: str = "",
) -> CStruct:
    prefixed = _apply_prefix(prefix, name)
    if s.get("pointer_alias"):
        alias = f"{prefixed}{suffixes['aliases']}"
    else:
        alias = prefixed

    fields = [
        _resolve_field(f, registry, primitives, f"Struct '{name}'")
        for f in s.get("fields", [])
    ]

    omitted, guard_directive = _gating(s, states, gated=False)
    return CStruct(
        name=prefixed,
        template_alias=alias,
        pointer_alias=s.get("pointer_alias", False),
        fields=fields,
        description=_with_history(s.get("description"), s),
        omitted=omitted,
        guard_directive=guard_directive,
    )


def _resolve_callback(
    name: str,
    cb: dict,
    registry: dict[str, str],
    primitives: dict[str, str],
    suffixes: dict[str, str],
    states: dict[str, State],
    prefix: str = "",
) -> CFuncPtr:
    prefixed = _apply_prefix(prefix, name)
    alias = f"{prefixed}{suffixes['callbacks']}"

    params = []
    for pname, p in cb.get("parameters", {}).items():
        base = _resolve_c_name(
            p["type"], registry, primitives, f"Callback '{name}' param '{pname}'"
        )
        params.append(
            CFuncPtrParam(
                name=pname,
                base=base,
                pointer=p["indirection"],
                const=p["const"],
            )
        )

    omitted, guard_directive = _gating(cb, states, gated=False)
    return CFuncPtr(
        name=prefixed,
        template_alias=alias,
        return_base=_resolve_c_name(
            cb["return_type"], registry, primitives, f"Callback '{name}' return"
        ),
        return_pointer=cb["return_pointer"],
        return_const=cb["return_const"],
        params=params,
        description=_with_history(cb.get("description"), cb),
        omitted=omitted,
        guard_directive=guard_directive,
    )


def _resolve_function(
    fname: str,
    func: dict,
    registry: dict[str, str],
    primitives: dict[str, str],
    states: dict[str, State],
) -> CFunction:
    params: dict[str, CParam] = {}
    for pname, p in func["parameters"].items():
        base = _resolve_c_name(
            p["type"], registry, primitives, f"Function '{fname}' param '{pname}'"
        )
        c_decl = _format_c_type(base, p["indirection"], p["const"])
        params[pname] = CParam(
            name=pname,
            c_decl=c_decl,
            description=p.get("description") or None,
        )

    return_base = _resolve_c_name(
        func["return_type"], registry, primitives, f"Function '{fname}' return"
    )
    return_c = _format_c_type(return_base, func["return_pointer"], func["return_const"])

    deprecated = state_version(func) if current_state(func) == "deprecated" else None

    omitted, guard_directive = _gating(func, states)

    return CFunction(
        name=fname,
        description=_with_history(func.get("description"), func) or None,
        deprecated=deprecated,
        return_c=return_c,
        static_inline=bool(func.get("static_inline", False)),
        omitted=omitted,
        guard_directive=guard_directive,
        parameters=params,
    )


def _resolve_enum(
    name: str,
    enum: dict,
    states: dict[str, State],
    prefix: str = "",
) -> CEnum:
    """Auto-number enum values via the shared helper."""
    uprefix = prefix.upper()
    c_name = _apply_prefix(prefix, name)
    resolved_values = {
        f"{uprefix}{vname}": CEnumValue(
            value=value,
            description=enum["values"][vname].get("description", ""),
        )
        for vname, value in resolve_enum_values(enum)
    }

    omitted, guard_directive = _gating(enum, states, gated=False)
    return CEnum(
        name=c_name,
        description=_with_history(enum.get("description"), enum),
        values=resolved_values,
        omitted=omitted,
        guard_directive=guard_directive,
    )


def add_enum_sentinels(render_modules: list[CModule]) -> None:
    """Append the int-max sentinel to every emitted enum.

    The sentinel pins the underlying type to at least 32 bits, so the ABI
    stops depending on compiler flags like -fshort-enums. This is C-header
    policy: only the C adapter applies it, so the other adapters never see
    sentinel members or the collision check.
    """
    for mod in render_modules:
        for enum in mod.enums:
            if enum.omitted:
                continue
            sentinel = f"{enum.name.upper()}_MAX_ENUM"
            if sentinel in enum.values:
                raise ValueError(
                    f"Enum '{enum.name}': member '{sentinel}' collides with "
                    "the generated max-value sentinel"
                )
            enum.values[sentinel] = CEnumValue(value="0x7FFFFFFF")


def rewrite_doc_anchors(
    render_modules: list[CModule], modules: list[dict], metadata: dict
) -> None:
    """Replace [[name]] in every description with the generated C name.

    C-prose policy, applied by the C adapter as a post-step: the other
    adapters render no descriptions, so they never rewrite and never raise.
    """
    prefix = metadata.get("prefix", "")
    registry = _build_registry(modules, metadata["suffixes"], prefix)
    names = _anchor_names(modules, registry, prefix)
    for rmod in render_modules:
        _rewrite_module_docs(rmod, names)


def _anchor_names(
    modules: list[dict], registry: dict[str, str], prefix: str
) -> dict[str, str]:
    """What each anchorable bare spec name renders as in C prose."""
    uprefix = prefix.upper()
    names: dict[str, str] = {}
    for mod in modules:
        for construct in ("handles", "callbacks", "aliases", "structs", "enums"):
            for name in mod.get(construct, {}):
                names[name] = registry[name]
        for name in mod.get("constants", {}):
            names[name] = f"{uprefix}{name}"
        for name in mod.get("functions", {}):
            names[name] = f"{prefix}{name}()"
    return names


def _rewrite_module_docs(rmod: CModule, names: dict[str, str]) -> None:
    def render(name: str) -> str:
        if name not in names:
            raise ValueError(
                f"Module '{rmod.name}': description anchor "
                f"'[[{name}]]' does not resolve"
            )
        return names[name]

    def rw_fields(fields: list[CField]) -> None:
        for f in fields:
            f.description = rewrite_anchors(f.description, render)
            for m in f.union_members or []:
                m.description = rewrite_anchors(m.description, render)
                rw_fields(m.fields)
            rw_fields(f.nested_fields or [])

    for t in rmod.types:
        t.description = rewrite_anchors(t.description, render)
    for s in rmod.structs:
        s.description = rewrite_anchors(s.description, render)
        rw_fields(s.fields)
    for e in rmod.enums:
        e.description = rewrite_anchors(e.description, render)
        for v in e.values.values():
            v.description = rewrite_anchors(v.description, render)
    for c in rmod.constants:
        c.description = rewrite_anchors(c.description, render)
    for fp in rmod.function_ptrs:
        fp.description = rewrite_anchors(fp.description, render)
    for fn in rmod.functions.values():
        fn.description = rewrite_anchors(fn.description, render)
        for p in fn.parameters.values():
            p.description = rewrite_anchors(p.description, render)
