"""CLI entry point for capigen."""

import argparse
import importlib
import inspect
import sys
from pathlib import Path

import jsonschema

from . import SCHEMA_VERSION, __version__
from .loader import SchemaVersionError, load_options
from .spec import SpecError, load

_DEFAULT_SPEC_DIR = Path("api_spec/v2")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Declarative C API generator from YAML specs"
    )
    parser.add_argument("--version", action="version", version=__version__)
    parser.add_argument(
        "--schema-version",
        action="version",
        version=SCHEMA_VERSION,
        help="Print the supported spec schema version and exit",
    )
    parser.add_argument("adapter", help="Language adapter name (e.g. 'c')")
    parser.add_argument("--output", "-o", required=True, help="Output file path")
    parser.add_argument(
        "--spec-dir",
        default=str(_DEFAULT_SPEC_DIR),
        help=f"Path to spec directory containing metadata.yaml and module YAMLs (default: {_DEFAULT_SPEC_DIR})",
    )
    parser.add_argument(
        "--scan-dir",
        default=None,
        help="Directory to scan for already-implemented functions (bridge adapter only)",
    )
    parser.add_argument(
        "--template",
        default=None,
        help="Frozen template header to verify and append (extension_header adapter only)",
    )
    parser.add_argument(
        "--options",
        default=None,
        help="Adapter options file (default: <spec-dir>/options/<adapter>.yaml if present)",
    )
    parser.add_argument(
        "--internal-out",
        default=None,
        dest="internal_out",
        help="Path for the derived engine-side header (extension_header adapter only)",
    )
    args = parser.parse_args()

    spec_dir = Path(args.spec_dir)
    if not spec_dir.is_dir():
        print(f"Error: API spec directory not found: {spec_dir}", file=sys.stderr)
        sys.exit(1)

    # 1-3. Load, apply defaults, and validate in one step.
    try:
        spec = load(spec_dir)
    except SchemaVersionError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
    except jsonschema.ValidationError as e:
        print(f"\n--- SCHEMA VALIDATION ERROR ---\n{e.message}", file=sys.stderr)
        print("\nGeneration aborted.", file=sys.stderr)
        sys.exit(1)
    except SpecError as e:
        print("\n--- SEMANTIC VALIDATION ERRORS ---", file=sys.stderr)
        print(e, file=sys.stderr)
        print("\nGeneration aborted.", file=sys.stderr)
        sys.exit(1)

    # 4. Import the adapter: a built-in first, then any importable module
    # exposing generate(). The CLI is a thin runner either way.
    try:
        adapter = importlib.import_module(f"capigen.adapters.{args.adapter}")
    except ModuleNotFoundError as e:
        if e.name != f"capigen.adapters.{args.adapter}":
            raise  # a bug inside the built-in adapter, not an unknown name
        try:
            adapter = importlib.import_module(args.adapter)
        except ModuleNotFoundError as e2:
            unresolved = e2.name == args.adapter or args.adapter.startswith(
                f"{e2.name}."
            )
            if not unresolved:
                raise  # the module exists; its own imports failed
            import pkgutil

            import capigen.adapters

            available = ", ".join(
                sorted(m.name for m in pkgutil.iter_modules(capigen.adapters.__path__))
            )
            print(
                f"Error: cannot import adapter '{args.adapter}' "
                f"(built-ins: {available}; anything else must be an importable "
                "module exposing generate())",
                file=sys.stderr,
            )
            sys.exit(1)

    # Load and enforce the adapter's options file, if any.
    options_path = (
        Path(args.options)
        if args.options
        else spec_dir / "options" / f"{args.adapter}.yaml"
    )
    options = None
    if args.options and not options_path.is_file():
        print(f"Error: options file not found: {options_path}", file=sys.stderr)
        sys.exit(1)
    if options_path.is_file():
        schema_path = getattr(adapter, "OPTIONS_SCHEMA", None)
        if schema_path is None:
            print(
                f"Error: adapter '{args.adapter}' takes no options, "
                f"but {options_path} exists",
                file=sys.stderr,
            )
            sys.exit(1)
        try:
            options = load_options(options_path, schema_path)
        except jsonschema.ValidationError as e:
            print(
                f"\n--- SCHEMA VALIDATION ERROR in {options_path} ---\n{e.message}",
                file=sys.stderr,
            )
            print("\nGeneration aborted.", file=sys.stderr)
            sys.exit(1)

    output_path = Path(args.output)
    params = inspect.signature(adapter.generate).parameters
    # Anything the user supplied must be accepted by the adapter; a mismatch
    # is an error, never a silent drop.
    passthrough = {
        "options": options,
        "scan_dir": Path(args.scan_dir) if args.scan_dir is not None else None,
        "template": Path(args.template) if args.template is not None else None,
        "internal_out": (
            Path(args.internal_out) if args.internal_out is not None else None
        ),
    }
    extra_kwargs: dict = {}
    for name, value in passthrough.items():
        if value is None:
            continue
        if name not in params:
            print(
                f"Error: adapter '{args.adapter}' does not accept '{name}'",
                file=sys.stderr,
            )
            sys.exit(1)
        extra_kwargs[name] = value
    if "invocation" in params:
        extra_kwargs["invocation"] = "capigen " + " ".join(sys.argv[1:])
    adapter.generate(spec.modules, spec.metadata, output_path, **extra_kwargs)


if __name__ == "__main__":
    main()
