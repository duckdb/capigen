"""Reusable spec utilities shared by capigen and its adapters."""


def handle_dependencies(modules: list[dict]) -> dict[str, set[str]]:
    """Return the handle dependency graph.

    A handle X is said to depend on handle Y if any function with
    ``belongs_to: X`` references Y via a parameter type or return type
    (excluding self-references to X).

    Every handle appears as a key, even if it has no dependencies. The
    returned sets contain only handle names (not primitives or aliases).
    """
    handles: set[str] = set()
    for mod in modules:
        handles.update(mod.get("handles", {}).keys())

    deps: dict[str, set[str]] = {h: set() for h in handles}

    for mod in modules:
        for func in mod.get("functions", {}).values():
            owner = func.get("belongs_to")
            if owner not in handles:
                continue

            for param in func.get("parameters", {}).values():
                t = param.get("type")
                if t in handles and t != owner:
                    deps[owner].add(t)

            rt = func.get("return_type")
            if rt in handles and rt != owner:
                deps[owner].add(rt)

    return deps


def topo_sort_handles(modules: list[dict]) -> list[str]:
    """Topologically sort handles so dependencies precede dependents.

    Uses Kahn's algorithm with alphabetical tie-breaking for deterministic
    output. Raises ``ValueError`` on cycles, listing the handles involved.
    """
    deps = handle_dependencies(modules)
    remaining: dict[str, set[str]] = {h: set(d) for h, d in deps.items()}
    result: list[str] = []

    while remaining:
        ready = sorted(h for h, d in remaining.items() if not d)
        if not ready:
            raise ValueError(f"Cycle detected among handles: {sorted(remaining)}")
        for h in ready:
            result.append(h)
            del remaining[h]
        for d in remaining.values():
            d.difference_update(ready)

    return result


def sort_modules_by_deps(modules: list[dict]) -> list[dict]:
    """Sort modules so that type declarations precede cross-module references.

    Builds a module-level dependency graph: module M depends on module N if M
    references a type (handle, alias, struct, enum, or callback) declared in N.
    Uses Kahn's algorithm with alphabetical tie-breaking for determinism.
    Raises ``ValueError`` on cycles.
    """
    decl: dict[str, str] = {}
    for mod in modules:
        mname = mod["module"]
        for section in (
            "handles",
            "aliases",
            "qualified_aliases",
            "structs",
            "enums",
            "callbacks",
        ):
            for name in mod.get(section, {}):
                decl[name] = mname

    def _refs(mod: dict) -> set[str]:
        out: set[str] = set()
        for func in mod.get("functions", {}).values():
            out.add(func.get("return_type", ""))
            for p in func.get("parameters", {}).values():
                out.add(p.get("type", ""))
        for s in mod.get("structs", {}).values():
            for f in s.get("fields", []):
                out.add(f.get("type", ""))
        for cb in mod.get("callbacks", {}).values():
            out.add(cb.get("return_type", ""))
            for p in cb.get("parameters", {}).values():
                out.add(p.get("type", ""))
        for a in mod.get("aliases", {}).values():
            out.add(a.get("underlying", ""))
        return out

    mod_by_name = {mod["module"]: mod for mod in modules}
    deps: dict[str, set[str]] = {mod["module"]: set() for mod in modules}
    for mod in modules:
        mname = mod["module"]
        for tname in _refs(mod):
            declaring = decl.get(tname)
            if declaring and declaring != mname:
                deps[mname].add(declaring)

    remaining = {m: set(d) for m, d in deps.items()}
    result: list[str] = []
    while remaining:
        ready = sorted(m for m, d in remaining.items() if not d)
        if not ready:
            raise ValueError(f"Cycle detected among modules: {sorted(remaining)}")
        for m in ready:
            result.append(m)
            del remaining[m]
        for d in remaining.values():
            d.difference_update(ready)

    return [mod_by_name[m] for m in result]


def apply_prefix(prefix: str, name: str) -> str:
    """Prepend the prefix, uppercasing it when the name starts uppercase."""
    if name and name[0].isupper():
        return f"{prefix.upper()}{name}"
    return f"{prefix}{name}"


def build_registry(
    modules: list[dict], suffixes: dict[str, str], prefix: str = ""
) -> dict[str, str]:
    """Map every declared spec name (and its prefixed form) to its C type name."""
    registry: dict[str, str] = {}

    for mod in modules:
        for name in mod.get("handles", {}):
            canonical = f"{apply_prefix(prefix, name)}{suffixes['handles']}"
            registry[name] = canonical
            registry[canonical] = canonical

        for name in mod.get("callbacks", {}):
            canonical = f"{apply_prefix(prefix, name)}{suffixes['callbacks']}"
            registry[name] = canonical
            registry[canonical] = canonical

        for name, a in mod.get("aliases", {}).items():
            if a.get("qualified"):
                registry[name] = name
            else:
                canonical = f"{apply_prefix(prefix, name)}{suffixes['aliases']}"
                registry[name] = canonical
                registry[canonical] = canonical

        for name, s in mod.get("structs", {}).items():
            prefixed = apply_prefix(prefix, name)
            if s.get("pointer_alias"):
                alias = f"{prefixed}{suffixes['aliases']}"
            else:
                alias = prefixed
            registry[name] = alias
            registry[prefixed] = alias
            if alias != prefixed:
                registry[alias] = alias

        for name in mod.get("enums", {}):
            prefixed = apply_prefix(prefix, name)
            registry[name] = prefixed
            registry[prefixed] = prefixed

    return registry


def chase(mapping: dict, key):
    """Follow a mapping until a key is absent or a cycle closes."""
    seen = set()
    while key in mapping and key not in seen:
        seen.add(key)
        key = mapping[key]
    return key


def resolve_enum_values(enum: dict) -> list[tuple[str, int]]:
    """Auto-number enum members: sequential from 0, reset on an explicit value."""
    values = []
    current = 0
    for vname, entry in enum["values"].items():
        if entry.get("value") is not None:
            current = entry["value"]
        values.append((vname, current))
        current += 1
    return values


def version_key(version: str) -> tuple[int, ...]:
    """Numeric sort key for a vX.Y.Z string (leading v optional)."""
    return tuple(int(x) for x in version.lstrip("v").split("."))


__all__ = [
    "apply_prefix",
    "build_registry",
    "chase",
    "handle_dependencies",
    "resolve_enum_values",
    "sort_modules_by_deps",
    "topo_sort_handles",
    "version_key",
]
