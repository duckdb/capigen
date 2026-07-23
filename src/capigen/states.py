"""Lifecycle states: the spec-declared vocabulary and how each state renders.

A spec declares its supported states in metadata under `lifecycle_states`.
Each state carries a visibility, and guarded visibilities carry their macro
token. There is no built-in vocabulary: without a lifecycle_states block no
states exist, and any lifecycle entry then fails cross-module validation.
Guard tokens live here, on the state, so every adapter reads the same
declaration.
"""

from dataclasses import dataclass

VISIBILITIES = ("always", "opt_in", "opt_out", "never")


@dataclass(frozen=True)
class State:
    name: str
    visibility: str  # always | opt_in | opt_out | never
    guard: str = ""  # macro token, set for opt_in / opt_out


def resolve_states(metadata: dict) -> dict[str, State]:
    """The states a spec supports. Only declared states exist.

    Mirrors the schema's constraints so programmatic callers fail as loudly
    as the load path: the visibility must be known, and a guard is required
    for the gated visibilities and forbidden otherwise.
    """
    declared = metadata.get("lifecycle_states") or {}
    states: dict[str, State] = {}
    for name, s in declared.items():
        visibility = s.get("visibility")
        if visibility not in VISIBILITIES:
            raise ValueError(
                f"lifecycle state '{name}': unknown visibility {visibility!r} "
                f"(one of: {', '.join(VISIBILITIES)})"
            )
        guard = s.get("guard", "")
        if visibility in ("opt_in", "opt_out") and not guard:
            raise ValueError(
                f"lifecycle state '{name}': visibility '{visibility}' requires a guard"
            )
        if visibility in ("always", "never") and guard:
            raise ValueError(
                f"lifecycle state '{name}': visibility '{visibility}' forbids a guard"
            )
        states[name] = State(name, visibility, guard)
    return states


def current_state(d: dict) -> str | None:
    """Name of the top (current) lifecycle entry, or None without one."""
    lifecycle = d.get("lifecycle") or []
    return lifecycle[0][0] if lifecycle else None
