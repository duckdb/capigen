"""C language adapter for capigen."""

from pathlib import Path

from jinja2 import Environment, FileSystemLoader, StrictUndefined

from ...states import resolve_states
from ...tools import apply_prefix, build_registry, version_key
from .comments import doc, prefixed
from .resolve import (
    add_enum_sentinels,
    resolve_c_options,
    resolve_modules,
    rewrite_doc_anchors,
)

_TEMPLATES_DIR = Path(__file__).parent / "templates"
OPTIONS_SCHEMA = Path(__file__).parent / "options.schema.json"


def _collect_renames(modules: list[dict], metadata: dict) -> list[dict]:
    """Former spellings to alias, newest rename first.

    A type aliases with a typedef and a function with a macro; both are gated
    below the version the rename landed in, so the old name is reachable exactly
    when the consumer targets a version that still had it.
    """
    prefix = metadata.get("prefix", "")
    suffixes = metadata.get("suffixes", {})
    type_kinds = ("handles", "structs", "enums", "aliases", "callbacks")
    # The old name has to be spelled the way that kind spells names, suffix and
    # all, or the alias would not match what the older header actually declared.
    registry = build_registry(modules, suffixes, prefix)
    ordered: list[tuple[tuple[int, ...], str, dict]] = []
    for mod in modules:
        for kind in type_kinds + ("functions",):
            for name, d in (mod.get(kind) or {}).items():
                rename = d.get("renamed_from")
                if not rename:
                    continue
                suffix = suffixes.get(kind, "")
                old_name = f"{apply_prefix(prefix, rename['name'])}{suffix}"
                new_name = registry.get(name, apply_prefix(prefix, name))
                key = version_key(rename["version"])
                ordered.append(
                    (
                        key,
                        old_name,
                        {
                            "old": old_name,
                            "new": new_name,
                            "version": rename["version"],
                            "args": ", ".join(str(n) for n in key),
                            "is_type": kind in type_kinds,
                        },
                    )
                )
    # newest rename first, so the most recent break reads at the top
    ordered.sort(key=lambda r: (r[0], r[1]), reverse=True)
    return [entry for _, _, entry in ordered]


def generate(
    modules: list[dict],
    metadata: dict,
    output_path: Path,
    options: dict | None = None,
) -> None:
    options = options or {}
    states = resolve_states(metadata)
    render_modules = resolve_modules(modules, metadata, options, states)
    c_opts = resolve_c_options(metadata, options, states)
    if options.get("emit_enum_max_member", True):
        add_enum_sentinels(render_modules)
    rewrite_doc_anchors(render_modules, modules, metadata)
    width = int(c_opts["comment_width"])

    def _c_doc(description: str, indent: str = "") -> str:
        return doc(description, indent, width)

    env = Environment(
        loader=FileSystemLoader(str(_TEMPLATES_DIR)),
        keep_trailing_newline=True,
        trim_blocks=True,
        lstrip_blocks=True,
        undefined=StrictUndefined,
    )
    env.filters["c_doc"] = _c_doc
    env.filters["c_lines"] = prefixed
    # Compatibility aliases for renamed constructs. Emitted once, in the C header:
    # the extension header includes it, and its own mapping macro chains through
    # the alias, so a renamed function resolves through the vtable either way.
    renames = _collect_renames(modules, metadata)

    template = env.get_template("header.h.j2")
    output = template.render(
        modules=render_modules,
        renames=renames,
        primitives=metadata.get("primitives", []),
        c_opts=c_opts,
    )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(output)
    print(f"Generated {output_path}")
