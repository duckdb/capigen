"""Language-agnostic cross-module referential integrity checks."""

from itertools import pairwise

from .anchors import find_anchors, find_malformed
from .states import current_state, resolve_states
from .tools import version_key

_STATE_BEARING = ("handles", "callbacks", "aliases", "structs", "enums", "functions")


def _walk_fields(context: str, fields: list, visit) -> None:
    """Call `visit(context, node)` on every field and union member, recursively."""
    for f in fields:
        fctx = f"{context}.{f['name']}"
        visit(fctx, f)
        for m in f.get("union", []):
            visit(f"{fctx}.{m['name']}", m)
            _walk_fields(f"{fctx}.{m['name']}", m["fields"], visit)
        _walk_fields(fctx, f.get("fields", []), visit)


def _check_lifecycle(
    where: str,
    lifecycle: list,
    states: dict,
    versions: set[str],
) -> list[str]:
    """A lifecycle stack is newest-first and moves forward through the states.

    Entries name declared states and known versions. Reading top (newest) to
    bottom, versions never increase and the declared order strictly decreases,
    so a construct cannot revisit a state or move backwards through them. Two
    transitions may share a version: stabilized and deprecated in one release.
    """
    errors: list[str] = []
    for entry in lifecycle:
        if entry[0] not in states:
            errors.append(
                f"{where}: unknown state '{entry[0]}' "
                f"(declared lifecycle states: {', '.join(sorted(states)) or 'none'})"
            )
        elif entry[1] not in versions:
            errors.append(f"{where}: unknown version '{entry[1]}' on '{entry[0]}'")

    known = [e for e in lifecycle if e[0] in states and e[1] in versions]
    for newer, older in pairwise(known):
        if version_key(newer[1]) < version_key(older[1]):
            errors.append(
                f"{where}: lifecycle is not newest-first, "
                f"'{newer[0]}' ({newer[1]}) precedes '{older[0]}' ({older[1]})"
            )
        a, b = states[newer[0]].order, states[older[0]].order
        if a is not None and b is not None and a <= b:
            errors.append(
                f"{where}: lifecycle does not move forward, "
                f"'{older[0]}' cannot be followed by '{newer[0]}'"
            )
    return errors


def validate_semantics(modules: list[dict], metadata: dict) -> list[str]:
    """Validate cross-module constraints. Returns list of error strings."""
    errors: list[str] = []

    primitives = {p["name"] for p in metadata["primitives"]}
    versions = set(metadata["versions"])
    prefix = metadata.get("prefix", "")

    # Pass 1: collect all declared constructs. A bare name is unique across
    # every construct kind, so a name identifies exactly one construct.
    all_types: dict[str, str] = {}  # name → module
    all_functions: dict[str, str] = {}
    declared: dict[str, str] = {}  # every kind, for duplicate detection

    for mod in modules:
        module_name = mod["module"]

        for construct in (
            "handles",
            "callbacks",
            "aliases",
            "structs",
            "enums",
            "constants",
            "functions",
        ):
            for name in mod.get(construct, {}):
                if name in declared:
                    errors.append(
                        f"{module_name}::{name}: Name '{name}' is duplicated "
                        f"(first in '{declared[name]}')"
                    )
                declared[name] = module_name
                if construct == "functions":
                    all_functions[name] = module_name
                elif construct != "constants":
                    all_types[name] = module_name

    def is_valid_type(name: str) -> bool:
        return name in primitives or name in all_types

    # Pass 2: validate type references
    for mod in modules:
        module_name = mod["module"]

        for name, a in mod.get("aliases", {}).items():
            if not is_valid_type(a["underlying"]):
                errors.append(
                    f"{module_name}::{name}: Unknown underlying type '{a['underlying']}'"
                )

        def check_field_type(fctx: str, node: dict) -> None:
            if "type" in node and not is_valid_type(node["type"]):
                errors.append(f"{fctx}: Unknown field type '{node['type']}'")

        for name, s in mod.get("structs", {}).items():
            _walk_fields(
                f"{module_name}::{name}", s.get("fields", []), check_field_type
            )

        for name, cb in mod.get("callbacks", {}).items():
            if not is_valid_type(cb["return_type"]):
                errors.append(
                    f"{module_name}::{name}: Unknown return type '{cb['return_type']}'"
                )
            for pname, p in cb.get("parameters", {}).items():
                if not is_valid_type(p["type"]):
                    errors.append(
                        f"{module_name}::{name}.{pname}: "
                        f"Unknown parameter type '{p['type']}'"
                    )

    # Pass 3c: a rename names a version and frees its old spelling. The alias is
    # only emitted below that version, so the old name must not also belong to a
    # live construct, and two constructs cannot claim the same former name.
    former: dict[str, str] = {}
    for mod in modules:
        for kind in _STATE_BEARING:
            for name, d in mod.get(kind, {}).items():
                rename = d.get("renamed_from")
                if not rename:
                    continue
                where = f"{mod['module']}::{name}"
                if rename["version"] not in versions:
                    errors.append(
                        f"{where}: renamed_from names unknown version "
                        f"'{rename['version']}'"
                    )
                old_name = rename["name"]
                if old_name in declared:
                    errors.append(
                        f"{where}: renamed_from '{old_name}' is also a live construct "
                        f"in '{declared[old_name]}'"
                    )
                if old_name in former:
                    errors.append(
                        f"{where}: former name '{old_name}' is already claimed by "
                        f"'{former[old_name]}'"
                    )
                else:
                    former[old_name] = name

    # Pass 3b: every function must date itself. The extension struct places a slot
    # by the version the function was promised in, so an undated function has no
    # defined position and would silently land wherever the sort happened to put it.
    for mod in modules:
        for func_name, func in mod.get("functions", {}).items():
            if not (func.get("lifecycle") or []):
                errors.append(
                    f"{mod['module']}::{func_name}: function has no lifecycle; "
                    "every function must declare when it was introduced"
                )

    # Pass 3a: a frozen ABI offset identifies one slot, so it cannot be shared.
    offsets: dict[int, str] = {}
    for mod in modules:
        for func_name, func in mod.get("functions", {}).items():
            offset = func.get("offset")
            if offset is None:
                continue
            if offset in offsets:
                errors.append(
                    f"{mod['module']}::{func_name}: offset {offset} is already "
                    f"taken by '{offsets[offset]}'"
                )
            else:
                offsets[offset] = func_name

    # Pass 3: validate functions
    for mod in modules:
        module_name = mod["module"]

        for func_name, func in mod.get("functions", {}).items():
            if not is_valid_type(func["return_type"]):
                errors.append(
                    f"{module_name}::{func_name}: "
                    f"Unknown return type '{func['return_type']}'"
                )
            for pname, p in func.get("parameters", {}).items():
                if not is_valid_type(p["type"]):
                    errors.append(
                        f"{module_name}::{func_name}.{pname}: "
                        f"Unknown parameter type '{p['type']}'"
                    )

    # Pass 4: lifecycle. Every lifecycle entry names a declared state, no construct
    # references something emitted nowhere, and nothing is stamped older than a type
    # in its own signature.
    states = resolve_states(metadata)

    for mod in modules:
        module_name = mod["module"]
        for construct in _STATE_BEARING:
            for name, d in mod.get(construct, {}).items():
                errors.extend(
                    _check_lifecycle(
                        f"{module_name}::{name}",
                        d.get("lifecycle") or [],
                        states,
                        versions,
                    )
                )

    def omitted(d: dict) -> bool:
        """Whether a construct is emitted nowhere, in any configuration.

        The only such case is a `never` state. Gated constructs are still emitted
        under some configuration, and a reference to one cannot dangle: only
        functions gate, and nothing may reference a function.
        """
        state = states.get(current_state(d) or "")
        return state is not None and state.visibility == "never"

    type_decl: dict[str, dict] = {}
    function_decl: dict[str, dict] = {}
    for mod in modules:
        for construct in ("handles", "callbacks", "aliases", "structs", "enums"):
            type_decl.update(mod.get(construct, {}))
        function_decl.update(mod.get("functions", {}))

    def introduced(d: dict) -> str | None:
        """The version a construct first appeared in: the oldest lifecycle entry."""
        lifecycle = d.get("lifecycle") or []
        return lifecycle[-1][1] if lifecycle else None

    type_intro = {tname: introduced(d) for tname, d in type_decl.items()}

    def check_type_ref(
        context: str,
        referrer_omitted: bool,
        type_name: str,
        referrer_intro: str | None = None,
    ) -> None:
        target = type_decl.get(type_name)
        if target is None or referrer_omitted:
            return  # a primitive, or a referrer that is never emitted
        if omitted(target):
            errors.append(
                f"{context}: references '{type_name}' "
                f"(state '{current_state(target)}'), which is never emitted"
            )
        # The same containment in the version dimension. A function stamped older
        # than a type in its own signature is mis-stamped: the signature described
        # here cannot be the one that version shipped. A consumer targeting a
        # version in between would get the declaration but not the matching symbol.
        target_intro = type_intro[type_name]
        if (
            referrer_intro
            and target_intro
            and version_key(target_intro) > version_key(referrer_intro)
        ):
            errors.append(
                f"{context}: introduced in {referrer_intro} but references "
                f"'{type_name}', introduced later in {target_intro}"
            )

    for mod in modules:
        module_name = mod["module"]

        for name, h in mod.get("handles", {}).items():
            cw = h.get("cleanup_with")
            if not cw:
                continue
            # The spec may write the bare name or the generated (prefixed) one.
            target = function_decl.get(cw)
            if target is None and prefix and cw.startswith(prefix):
                target = function_decl.get(cw[len(prefix) :])
            if target is None:
                errors.append(
                    f"{module_name}::{name}: cleanup_with names unknown function '{cw}'"
                )
                continue
            # A handle is always emitted while its destructor is gated like any
            # other function, so the two cannot be required to coincide. What must
            # hold is that the destructor still exists at all: a handle whose
            # cleanup was removed leaves no way to free it.
            if not omitted(h) and omitted(target):
                errors.append(
                    f"{module_name}::{name}: cleanup_with references "
                    f"'{cw}' (state '{current_state(target)}'), which is never emitted"
                )

        for name, a in mod.get("aliases", {}).items():
            check_type_ref(
                f"{module_name}::{name}", omitted(a), a["underlying"], introduced(a)
            )

        for name, s in mod.get("structs", {}).items():
            cons = omitted(s)

            def check_field_ref(
                fctx: str, node: dict, cons=cons, intro=introduced(s)
            ) -> None:
                if "type" in node:
                    check_type_ref(fctx, cons, node["type"], intro)

            _walk_fields(f"{module_name}::{name}", s.get("fields", []), check_field_ref)

        for name, cb in mod.get("callbacks", {}).items():
            cons = omitted(cb)
            check_type_ref(
                f"{module_name}::{name}", cons, cb["return_type"], introduced(cb)
            )
            for pname, p in cb.get("parameters", {}).items():
                check_type_ref(
                    f"{module_name}::{name}.{pname}", cons, p["type"], introduced(cb)
                )

        for func_name, func in mod.get("functions", {}).items():
            cons = omitted(func)
            if func.get("return_type"):
                check_type_ref(
                    f"{module_name}::{func_name}",
                    cons,
                    func["return_type"],
                    introduced(func),
                )
            for pname, p in func.get("parameters", {}).items():
                check_type_ref(
                    f"{module_name}::{func_name}.{pname}",
                    cons,
                    p["type"],
                    introduced(func),
                )

    # Pass 5: description anchors. Every [[name]] resolves to a declared
    # construct, and never to one that no guard configuration emits.
    anchor_decl: dict[str, dict] = {**type_decl, **function_decl}
    for mod in modules:
        anchor_decl.update(mod.get("constants", {}))

    def check_anchors(context: str, text: str | None) -> None:
        for bad in find_malformed(text):
            errors.append(
                f"{context}: malformed anchor '[[{bad}]]' (double brackets are "
                "reserved for anchors, and the content is not a valid name)"
            )
        for a in find_anchors(text):
            target = anchor_decl.get(a)
            if target is None:
                errors.append(f"{context}: unknown anchor '[[{a}]]'")
                continue
            sname = current_state(target)
            state = states.get(sname) if sname else None
            if state is not None and state.visibility == "never":
                errors.append(
                    f"{context}: anchor '[[{a}]]' targets a construct "
                    f"(state '{sname}') that is never emitted"
                )

    def check_field_anchor(fctx: str, node: dict) -> None:
        check_anchors(fctx, node.get("description"))

    for mod in modules:
        module_name = mod["module"]

        for construct in ("handles", "aliases", "constants"):
            for name, d in mod.get(construct, {}).items():
                check_anchors(f"{module_name}::{name}", d.get("description"))

        for name, cb in mod.get("callbacks", {}).items():
            check_anchors(f"{module_name}::{name}", cb.get("description"))
            for pname, p in cb.get("parameters", {}).items():
                check_anchors(f"{module_name}::{name}.{pname}", p.get("description"))

        for name, s in mod.get("structs", {}).items():
            check_anchors(f"{module_name}::{name}", s.get("description"))
            _walk_fields(
                f"{module_name}::{name}", s.get("fields", []), check_field_anchor
            )

        for name, e in mod.get("enums", {}).items():
            check_anchors(f"{module_name}::{name}", e.get("description"))
            for vname, v in e.get("values", {}).items():
                check_anchors(f"{module_name}::{name}.{vname}", v.get("description"))

        for func_name, func in mod.get("functions", {}).items():
            check_anchors(f"{module_name}::{func_name}", func.get("description"))
            check_anchors(f"{module_name}::{func_name}", func.get("return_description"))
            for pname, p in func.get("parameters", {}).items():
                check_anchors(
                    f"{module_name}::{func_name}.{pname}", p.get("description")
                )

    return errors
