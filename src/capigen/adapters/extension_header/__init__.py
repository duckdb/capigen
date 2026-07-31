"""Extension header adapter: generate the function-pointer struct from the spec.

One invocation produces two lockstep outputs: the consumer header (a template
skeleton with the struct and mapping regions filled) and the engine-side header
(the ungated struct plus a create method assigning every member). The two must be
generated together; a divergence between them is silent memory corruption.

The spec is the source of ABI order: `offset` pins a member laid down before
there was a rule, and everything else follows by introduction date then name.

The struct itself carries no conditionals. Only functions are gated, and a
member's signature therefore only ever names types that are always emitted, so
every member is always declarable. The gate goes on the indirection macro
instead: a name resolves for an extension exactly when it resolves for any other
consumer, while the layout is invariant by construction rather than by matching
placeholder sizes. A removed function keeps its slot too, so the offsets after it
do not shift; it simply loses its macro, and the engine leaves the slot null.
"""

import re
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, StrictUndefined

from ...states import resolve_states, version_macro_base
from ...tools import version_key
from ..c.render import CFunction
from ..c.resolve import resolve_modules

_TEMPLATES_DIR = Path(__file__).parent / "templates"
OPTIONS_SCHEMA = Path(__file__).parent / "options.schema.json"

_BEGIN = "// capigen:begin appended"
_END = "// capigen:end appended"


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


def _version_args(version: str) -> str:
    """A vX.Y.Z string as the argument list of a version-comparison macro."""
    return ", ".join(str(n) for n in version_key(version))


def _render_decl(name: str, func: CFunction) -> str:
    """Render a function-pointer struct member declaration for a spec function."""
    if func.parameters:
        params = ", ".join(f"{p.c_decl} {p.name}" for p in func.parameters.values())
    else:
        params = "void"
    return f"{func.return_c} (*{name})({params})"


# ---------------------------------------------------------------------------
# Generation
# ---------------------------------------------------------------------------


def _stabilized(spec: dict) -> str | None:
    """The version a function was first publicly promised, or None if still unstable.

    A slot is frozen by stabilization, not by introduction: while a function is
    unstable it is only reachable from an exact-version-locked build, so its slot
    can still move. The oldest non-unstable entry is therefore the band.
    """
    lifecycle = spec.get("lifecycle") or []
    if not lifecycle:
        # validate_semantics rejects this; reaching it means generation was run
        # on an unvalidated spec, and guessing a band would misplace a slot.
        raise ValueError("function has no lifecycle, so its ABI slot is undefined")
    promised = [e for e in reversed(lifecycle) if e[0] != "unstable"]
    return promised[0][1] if promised else None


def _band(spec: dict, floor: str) -> str | None:
    """The version whose engine first shipped this slot, or None for the unstable tail.

    Clamped to `floor`: the struct did not exist before then, so no slot can.
    """
    stable = _stabilized(spec)
    if stable is None:
        return None  # still unstable: it belongs in the tail
    if version_key(stable) <= version_key(floor):
        return floor
    return stable


def _members_from_spec(
    modules: list[dict],
    func_by_name: dict,
    prefix: str,
    exclude: set,
    floor: str,
) -> list[tuple[str, str, str, str | None]]:
    """The struct's members in ABI order, as (name, declaration, macro gate, band).

    Order is (band, offset, date, name), so members group into contiguous bands and
    the not-yet-stable ones land last. `offset` reproduces the order laid down
    before there was a rule; within a band it is the only thing that matters.
    """
    entries = []
    for mod in modules:
        for bare, spec in (mod.get("functions") or {}).items():
            name = prefix + bare
            func = func_by_name.get(name)
            if func is None or func.static_inline:
                continue
            if bare in exclude or name in exclude:
                continue
            entries.append((name, func, _band(spec, floor)))
    entries.sort(key=_vtable_order(modules, prefix, floor))
    return [(n, _render_decl(n, f), f.guard_directive, b) for n, f, b in entries]


def _fill_markers(text: str, struct_block: str, define_block: str) -> str:
    """Replace the content between the two append marker pairs (struct first, defines second)."""
    pattern = re.compile(
        rf"([ \t]*{re.escape(_BEGIN)}\n)(.*?)([ \t]*{re.escape(_END)})", re.DOTALL
    )
    blocks = iter([struct_block, define_block])

    def replace(match: re.Match) -> str:
        return match.group(1) + next(blocks) + match.group(3)

    filled, count = pattern.subn(replace, text)
    if count != 2:
        raise ValueError(f"expected exactly 2 append marker pairs, found {count}")
    return filled


def _vtable_order(modules: list[dict], prefix: str, floor: str):
    """Sort key for the function-pointer struct.

    Band first, so a band is a contiguous run the header can gate with one `#if`
    and truncating at a target version yields exactly the prefix that version's
    engine shipped. Not-yet-stable members sort last, into the tail. Within a
    band, an explicit `offset` reproduces the order laid down before there was a
    rule; everything else follows oldest first, ties broken by name.
    """
    index: dict[str, tuple] = {}
    for mod in modules:
        for name, func in (mod.get("functions") or {}).items():
            lifecycle = [e for e in (func.get("lifecycle") or []) if len(e) > 2]
            introduced = lifecycle[-1][2] if lifecycle else ""
            index[name] = (func.get("offset"), introduced, _band(func, floor))

    def key(entry: tuple) -> tuple:
        name = entry[0]
        bare = name[len(prefix) :] if name.startswith(prefix) else name
        pos, introduced, band = index.get(bare, (None, "", floor))
        # the tail sorts after every band
        rank = (1, ()) if band is None else (0, version_key(band))
        if pos is not None:
            return (rank, 0, pos, "")
        return (rank, 1, introduced, name)

    return key


def generate(
    modules: list[dict],
    metadata: dict,
    output_path: Path,
    template: Path | None = None,
    internal_out: Path | None = None,
    invocation: str | None = None,
    options: dict | None = None,
) -> None:
    """Verify the template struct against the spec, then write both lockstep headers."""
    if template is None:
        raise ValueError("extension_header adapter requires --template")
    if internal_out is None:
        raise ValueError("extension_header adapter requires --internal-out")

    opts = options or {}
    if not opts:
        raise ValueError(
            "extension_header requires an options file (create_method, "
            "struct_typename, version_macro_prefix, internal_include)"
        )
    create_method = opts["create_method"]
    version_macro_prefix = opts["version_macro_prefix"]
    internal_include = opts["internal_include"]
    exclude = set(opts.get("exclude_functions", []))
    prefix = metadata.get("prefix", "")
    # The version whose engine first shipped this struct. Nothing can predate it.
    floor = opts.get("version_floor") or min(metadata["versions"], key=version_key)
    vmacro = version_macro_base(metadata)
    allow_unstable = next(
        (
            st.allow_macro
            for st in resolve_states(metadata).values()
            if st.name == "unstable" and st.allow_macro
        ),
        "",
    )

    template_text = Path(template).read_text()
    typename = opts["struct_typename"]
    api_var = opts.get("api_variable", f"{prefix}ext_api")
    # The struct describes the API as of the spec's newest version.
    api_version = max(metadata["versions"], key=version_key).lstrip("v")

    render_modules = resolve_modules(modules, metadata)
    func_by_name: dict[str, CFunction] = {}
    for mod in render_modules:
        func_by_name.update(mod.functions)

    members = _members_from_spec(modules, func_by_name, prefix, exclude, floor)
    names = [n for n, _, _, _ in members]
    duplicates = sorted({n for n in names if names.count(n) > 1})
    if duplicates:
        raise ValueError(f"struct member(s) declared more than once: {duplicates}")

    # The struct is banded: one gate per band, wrapping a contiguous run, so
    # truncating at a target version yields exactly that version's prefix. The
    # not-yet-stable tail is gated on the switch instead, because it only exists
    # for a build locked to this exact engine.
    struct_lines: list[str] = []
    define_lines: list[str] = []
    current_band: str | None = floor
    open_gate = False
    for name, decl, gate, band in members:
        if band != current_band:
            if open_gate:
                struct_lines.append("#endif")
            if band is None:
                if not allow_unstable:
                    raise ValueError(
                        "spec has not-yet-stable functions but declares no "
                        "opt-in 'unstable' lifecycle state to gate them with"
                    )
                struct_lines.append(f"#if {allow_unstable}")
            else:
                struct_lines.append(f"#if {vmacro}_AT_LEAST({_version_args(band)})")
            open_gate = True
            current_band = band
        struct_lines.append(f"\t{decl};")
        omitted = (f := func_by_name.get(name)) is not None and f.omitted
        if omitted:
            # Removed: the slot survives, the name must not resolve.
            continue
        mapping = f"#define {name} {api_var}.{name}"
        define_lines += [gate, mapping, "#endif"] if gate else [mapping]
    if open_gate:
        struct_lines.append("#endif")

    consumer = _fill_markers(
        template_text, "\n".join(struct_lines) + "\n", "\n".join(define_lines) + "\n"
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(consumer)

    # Engine-side header: derived from the extracted order plus appends.
    major, minor, patch = api_version.lstrip("v").split(".")  # regions store bare X.Y.Z
    env = Environment(
        loader=FileSystemLoader(str(_TEMPLATES_DIR)),
        keep_trailing_newline=True,
        trim_blocks=True,
        lstrip_blocks=True,
        undefined=StrictUndefined,
    )
    # A removed function keeps its slot; the engine has no symbol for it.
    assignments = [
        (n, "nullptr" if (f := func_by_name.get(n)) and f.omitted else n) for n in names
    ]
    internal = env.get_template("internal.hpp.j2").render(
        include=internal_include,
        typename=typename,
        create_method=create_method,
        version_macro_prefix=version_macro_prefix,
        major=major,
        minor=minor,
        patch=patch,
        api_version=api_version,
        members=[decl for _, decl, _, _ in members],
        assignments=assignments,
    )
    internal_out = Path(internal_out)
    internal_out.parent.mkdir(parents=True, exist_ok=True)
    internal_out.write_text(internal)

    print(f"Generated {output_path} and {internal_out} ({len(members)} members)")
