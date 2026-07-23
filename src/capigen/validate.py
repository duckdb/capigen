"""Language-agnostic cross-module referential integrity checks."""

from .anchors import find_anchors, find_malformed
from .states import current_state, resolve_states

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

    # Pass 3: validate functions
    for mod in modules:
        module_name = mod["module"]

        for func_name, func in mod.get("functions", {}).items():
            if func.get("added") and func["added"] not in versions:
                errors.append(
                    f"{module_name}::{func_name}: "
                    f"Unknown 'added' version '{func['added']}'"
                )
            if func.get("deprecated") and func["deprecated"] not in versions:
                errors.append(
                    f"{module_name}::{func_name}: "
                    f"Unknown 'deprecated' version '{func['deprecated']}'"
                )
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

    # Pass 4: lifecycle. Every lifecycle entry names a declared state, and a
    # construct must not reference anything that some guard configuration
    # compiles out while the construct itself remains present.
    states = resolve_states(metadata)

    for mod in modules:
        module_name = mod["module"]
        for construct in _STATE_BEARING:
            for name, d in mod.get(construct, {}).items():
                for entry in d.get("lifecycle") or []:
                    if entry[0] not in states:
                        errors.append(
                            f"{module_name}::{name}: unknown state '{entry[0]}' "
                            f"(declared lifecycle states: {', '.join(sorted(states)) or 'none'})"
                        )

    def emission(d: dict, is_function: bool = False) -> frozenset | None:
        """The guard conditions under which a construct is emitted.

        A frozenset of (guard, must_be_defined) pairs; None means never
        emitted. Emission of one construct implies emission of another
        exactly when the other's conditions are a subset of its own.
        """
        name = current_state(d)
        state = states.get(name) if name else None
        if state is None or state.visibility == "always":
            cons = frozenset()
        elif state.visibility == "opt_in":
            cons = frozenset({(state.guard, True)})
        elif state.visibility == "opt_out":
            cons = frozenset({(state.guard, False)})
        else:  # never
            return None
        if is_function and d.get("deprecated") and name != "deprecated":
            dep = states.get("deprecated")
            if dep and dep.visibility == "opt_out":
                cons = cons | {(dep.guard, False)}
        return cons

    type_decl: dict[str, dict] = {}
    function_decl: dict[str, dict] = {}
    for mod in modules:
        for construct in ("handles", "callbacks", "aliases", "structs", "enums"):
            type_decl.update(mod.get(construct, {}))
        function_decl.update(mod.get("functions", {}))

    type_cons = {tname: emission(d) for tname, d in type_decl.items()}

    def check_type_ref(context: str, referrer_cons, type_name: str) -> None:
        target = type_decl.get(type_name)
        if target is None or referrer_cons is None:
            return  # a primitive, or a referrer that is never emitted
        target_cons = type_cons[type_name]
        if target_cons is None:
            errors.append(
                f"{context}: references '{type_name}' "
                f"(state '{current_state(target)}'), which is never emitted"
            )
        elif not target_cons <= referrer_cons:
            errors.append(
                f"{context}: references '{type_name}' "
                f"(state '{current_state(target)}'), which can be absent "
                "while the referrer is present"
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
            h_cons = emission(h)
            t_cons = emission(target, is_function=True)
            if h_cons is not None and (t_cons is None or not t_cons <= h_cons):
                errors.append(
                    f"{module_name}::{name}: cleanup_with references "
                    f"'{cw}' (state '{current_state(target)}'), "
                    "which can be absent while the handle is present"
                )

        for name, a in mod.get("aliases", {}).items():
            check_type_ref(f"{module_name}::{name}", emission(a), a["underlying"])

        for name, s in mod.get("structs", {}).items():
            cons = emission(s)

            def check_field_ref(fctx: str, node: dict, cons=cons) -> None:
                if "type" in node:
                    check_type_ref(fctx, cons, node["type"])

            _walk_fields(f"{module_name}::{name}", s.get("fields", []), check_field_ref)

        for name, cb in mod.get("callbacks", {}).items():
            cons = emission(cb)
            check_type_ref(f"{module_name}::{name}", cons, cb["return_type"])
            for pname, p in cb.get("parameters", {}).items():
                check_type_ref(f"{module_name}::{name}.{pname}", cons, p["type"])

        for func_name, func in mod.get("functions", {}).items():
            cons = emission(func, is_function=True)
            if func.get("return_type"):
                check_type_ref(f"{module_name}::{func_name}", cons, func["return_type"])
            for pname, p in func.get("parameters", {}).items():
                check_type_ref(f"{module_name}::{func_name}.{pname}", cons, p["type"])

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
