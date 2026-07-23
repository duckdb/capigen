"""C language adapter for capigen."""

from pathlib import Path

from jinja2 import Environment, FileSystemLoader, StrictUndefined

from ...states import resolve_states
from .comments import doc, prefixed
from .resolve import add_enum_sentinels, resolve_c_options, resolve_modules

_TEMPLATES_DIR = Path(__file__).parent / "templates"
OPTIONS_SCHEMA = Path(__file__).parent / "options.schema.json"


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
    template = env.get_template("header.h.j2")
    output = template.render(
        modules=render_modules,
        primitives=metadata.get("primitives", []),
        c_opts=c_opts,
    )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(output)
    print(f"Generated {output_path}")
