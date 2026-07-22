"""Comment rendering for the C adapter.

Descriptions in a spec are prose. Line breaks inside a paragraph belong to the
YAML source, not to the generated header, so they are collapsed into one line
per paragraph. Line length is left to the consumer's C formatter, which reflows
a comment correctly as long as every line carries the comment prefix.

A description that fits on one line renders as `//!`. Anything longer renders as
a `/*! ... */` block, so a comment spanning several lines reads as one comment.
"""

from __future__ import annotations

import re

DEFAULT_WIDTH = 120

# A list item stays on its own line: "- text", "* text", "1. text", "2) text".
_LIST_ITEM = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s+")

_LINE_PREFIX = "//! "


def unwrap(description: str) -> list[str]:
    """Collapse a description into one line per paragraph, list item, or break.

    A line joins the line in progress unless a blank line, a list marker, or a
    dedent out of the open list item starts a new one.
    """
    lines: list[str] = []
    item_indent: int | None = None  # indent of the open list item, if any

    for line in description.strip().splitlines():
        stripped = line.strip()
        indent = len(line) - len(line.lstrip())

        if not stripped:
            item_indent = None
            if lines and lines[-1]:
                lines.append("")
            continue

        if _LIST_ITEM.match(line):
            item_indent = indent
            lines.append(line[:indent] + stripped)
        elif (
            lines
            and lines[-1]
            and not (item_indent is not None and indent <= item_indent)
        ):
            lines[-1] += " " + stripped
        else:
            item_indent = None
            lines.append(line[:indent] + stripped)

    while lines and not lines[-1]:
        lines.pop()
    return lines


def prefixed(description: str, prefix: str) -> str:
    """Render a description as comment lines, each carrying `prefix`."""
    return "\n".join((prefix + line).rstrip() for line in unwrap(description))


def doc(description: str, indent: str = "", width: int = DEFAULT_WIDTH) -> str:
    """Render a description as a `//!` line, or a `/*! ... */` block if longer."""
    lines = unwrap(description)
    if not lines:
        return ""
    if len(lines) == 1 and len(indent) + len(_LINE_PREFIX) + len(lines[0]) <= width:
        return f"{indent}{_LINE_PREFIX}{lines[0]}"
    body = [f"{indent}/*!"]
    body += [f"{indent} * {line}".rstrip() for line in lines]
    body.append(f"{indent} */")
    return "\n".join(body)
