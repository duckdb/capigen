"""Language-agnostic cross-module referential integrity checks."""


def _is_unstable(d: dict) -> bool:
    """True when the top (current) entry of the status stack is 'unstable'."""
    status = d.get("status") or []
    return bool(status) and status[0][0] == "unstable"


def validate_semantics(modules: list[dict], metadata: dict) -> list[str]:
    """Validate cross-module constraints. Returns list of error strings."""
    errors: list[str] = []

    primitives = {p["name"] for p in metadata["primitives"]}
    versions = set(metadata["versions"])

    # Pass 1: collect all declared symbols, detect duplicates
    all_types: dict[str, str] = {}  # name → module
    all_functions: dict[str, str] = {}

    for mod in modules:
        module_name = mod["module"]

        for construct in (
            "handles",
            "callbacks",
            "aliases",
            "structs",
            "enums",
        ):
            for name in mod.get(construct, {}):
                if name in all_types:
                    errors.append(
                        f"{module_name}::{name}: Type name '{name}' is duplicated "
                        f"(first in '{all_types[name]}')"
                    )
                all_types[name] = module_name

        for func_name in mod.get("functions", {}):
            if func_name in all_functions:
                errors.append(
                    f"{module_name}::{func_name}: Function name '{func_name}' is duplicated "
                    f"(first in '{all_functions[func_name]}')"
                )
            all_functions[func_name] = module_name

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

        def check_fields(struct_name: str, fields: list, mod_name: str) -> None:
            """Validate leaf field types; recurse into nested struct/union fields."""
            for f in fields:
                if "union" in f:
                    for m in f["union"]:
                        check_fields(struct_name, m["fields"], mod_name)
                elif "fields" in f:
                    check_fields(struct_name, f["fields"], mod_name)
                elif not is_valid_type(f["type"]):
                    errors.append(
                        f"{mod_name}::{struct_name}.{f['name']}: "
                        f"Unknown field type '{f['type']}'"
                    )

        for name, s in mod.get("structs", {}).items():
            check_fields(name, s.get("fields", []), module_name)

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

    # Pass 4: stability. An unstable declaration is compiled out unless the
    # consumer opts in, so a symbol that is not itself unstable must not
    # reference an unstable type.
    unstable_types: set[str] = set()
    unstable_functions: set[str] = set()
    for mod in modules:
        for construct in ("handles", "callbacks", "aliases", "structs", "enums"):
            for name, d in mod.get(construct, {}).items():
                if _is_unstable(d):
                    unstable_types.add(name)
        for name, func in mod.get("functions", {}).items():
            if _is_unstable(func):
                unstable_functions.add(name)

    def check_unstable_ref(context: str, type_name: str) -> None:
        if type_name in unstable_types:
            errors.append(
                f"{context}: references unstable type '{type_name}' "
                "but is not itself unstable"
            )

    def check_unstable_fields(context: str, fields: list) -> None:
        for f in fields:
            if "union" in f:
                for m in f["union"]:
                    check_unstable_fields(context, m["fields"])
            elif "fields" in f:
                check_unstable_fields(context, f["fields"])
            else:
                check_unstable_ref(f"{context}.{f['name']}", f["type"])

    for mod in modules:
        module_name = mod["module"]

        for name, h in mod.get("handles", {}).items():
            cleanup = h.get("cleanup_with")
            if cleanup in unstable_functions and not _is_unstable(h):
                errors.append(
                    f"{module_name}::{name}: cleanup_with references unstable "
                    f"function '{cleanup}' but is not itself unstable"
                )

        for name, a in mod.get("aliases", {}).items():
            if not _is_unstable(a):
                check_unstable_ref(f"{module_name}::{name}", a["underlying"])

        for name, s in mod.get("structs", {}).items():
            if not _is_unstable(s):
                check_unstable_fields(f"{module_name}::{name}", s.get("fields", []))

        for name, cb in mod.get("callbacks", {}).items():
            if _is_unstable(cb):
                continue
            check_unstable_ref(f"{module_name}::{name}", cb["return_type"])
            for pname, p in cb.get("parameters", {}).items():
                check_unstable_ref(f"{module_name}::{name}.{pname}", p["type"])

        for func_name, func in mod.get("functions", {}).items():
            if _is_unstable(func):
                continue
            if func.get("return_type"):
                check_unstable_ref(f"{module_name}::{func_name}", func["return_type"])
            for pname, p in func.get("parameters", {}).items():
                check_unstable_ref(f"{module_name}::{func_name}.{pname}", p["type"])

    return errors
