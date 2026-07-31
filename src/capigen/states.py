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
    # Base name of the target-version macros (<base>_MAJOR, <base>_AT_LEAST, ...).
    # Spec-level and so identical on every state, for the same reason guards live
    # here: every adapter must gate against the same macro.
    version_macro: str = ""
    # Position in the lifecycle progression, low to high (unstable, stable,
    # deprecated, removed). A construct may only move forward through them.
    order: int | None = None
    # Oldest version a consumer can target. A construct introduced at or before
    # it needs no "did this exist yet" term, since no legal target predates it.
    version_floor: str = ""
    # Positive-polarity switch for a gated state: 1 to compile the surface in
    # this state, 0 to omit it. Gates read it directly, so opt-in and opt-out
    # read the same way round. `guard` only seeds its default.
    allow_macro: str = ""


def resolve_states(metadata: dict) -> dict[str, State]:
    """The states a spec supports. Only declared states exist.

    Mirrors the schema's constraints so programmatic callers fail as loudly
    as the load path: the visibility must be known, and a guard is required
    for the gated visibilities and forbidden otherwise.
    """
    declared = metadata.get("lifecycle_states") or {}
    version_macro = version_macro_base(metadata)
    floor = version_floor(metadata)
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
        allow = (
            f"{metadata.get('prefix', '').upper()}API_ALLOW_{name.upper()}"
            if visibility in ("opt_in", "opt_out")
            else ""
        )
        states[name] = State(
            name, visibility, guard, version_macro, s.get("order"), floor, allow
        )

    ordered = [st for st in states.values() if st.order is not None]
    if ordered and len(ordered) != len(states):
        missing = sorted(n for n, st in states.items() if st.order is None)
        raise ValueError(
            "lifecycle states: 'order' must be declared on all states or none, "
            f"missing on: {', '.join(missing)}"
        )
    seen: dict[int, str] = {}
    for st in ordered:
        assert st.order is not None
        if st.order in seen:
            raise ValueError(
                f"lifecycle states '{seen[st.order]}' and '{st.name}': "
                f"duplicate order {st.order}"
            )
        seen[st.order] = st.name
    return states


def version_floor(metadata: dict) -> str:
    """Oldest version declared by the spec, so the oldest a consumer may target."""
    versions = metadata.get("versions") or []
    if not versions:
        return ""
    return min(versions, key=lambda v: tuple(int(x) for x in v.lstrip("v").split(".")))


def version_macro_base(metadata: dict) -> str:
    """Base name of the target-version macros a spec gates against."""
    declared = metadata.get("version_macro")
    if declared:
        return declared
    return f"{metadata.get('prefix', '').upper()}API_VERSION"


def current_state(d: dict) -> str | None:
    """Name of the top (current) lifecycle entry, or None without one."""
    lifecycle = d.get("lifecycle") or []
    return lifecycle[0][0] if lifecycle else None
