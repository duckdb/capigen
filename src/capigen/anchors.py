"""Verified cross-references inside descriptions.

An anchor is `[[name]]` in any description, where `name` is the bare spec name
of a declared construct. Double brackets are reserved for anchors: validation
rejects a bracket pair whose content is not a valid name, so a typo cannot
silently degrade to unverified prose. Each generator rewrites anchors to the
names it emits, through `rewrite_anchors`.
"""

import re
from collections.abc import Callable
from typing import overload

_NAME = r"[A-Za-z_][A-Za-z0-9_]*"
_ANCHOR = re.compile(rf"\[\[({_NAME})\]\]")
_BRACKETED = re.compile(r"\[\[(.*?)\]\]", re.DOTALL)


def find_anchors(text: str | None) -> list[str]:
    """Every anchor name in `text`, in order of appearance."""
    return _ANCHOR.findall(text or "")


def find_malformed(text: str | None) -> list[str]:
    """Every bracket pair whose content is not a valid anchor name."""
    return [m for m in _BRACKETED.findall(text or "") if not re.fullmatch(_NAME, m)]


@overload
def rewrite_anchors(text: str, render: Callable[[str], str]) -> str: ...
@overload
def rewrite_anchors(text: None, render: Callable[[str], str]) -> None: ...
def rewrite_anchors(text: str | None, render: Callable[[str], str]) -> str | None:
    """Replace each anchor with `render(name)`. None and "" pass through."""
    if not text:
        return text
    return _ANCHOR.sub(lambda m: render(m.group(1)), text)


__all__ = ["find_anchors", "find_malformed", "rewrite_anchors"]
