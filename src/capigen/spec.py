"""One-call loading of a validated spec.

`capigen.load(spec_dir)` is the front door for anything that consumes a spec:
the CLI, the in-tree adapters, and out-of-tree binding generators. It loads,
applies schema defaults, and runs cross-module validation in one step, so a
consumer cannot forget the validation and generate from a broken spec.
"""

from dataclasses import dataclass
from functools import cached_property
from pathlib import Path

from .loader import load_metadata, load_modules
from .states import State, resolve_states
from .tools import build_registry, version_key
from .validate import validate_semantics


class SpecError(Exception):
    """A spec failed cross-module validation. `errors` holds every message."""

    def __init__(self, errors: list[str]) -> None:
        super().__init__("\n".join(errors))
        self.errors = errors


@dataclass
class Spec:
    """A loaded, validated API spec, with the common derived views precomputed."""

    metadata: dict
    modules: list[dict]

    @property
    def schema_version(self) -> str:
        return self.metadata["schema_version"]

    @property
    def prefix(self) -> str:
        return self.metadata.get("prefix", "")

    @property
    def suffixes(self) -> dict:
        return self.metadata["suffixes"]

    @property
    def primitives(self) -> list[dict]:
        return self.metadata["primitives"]

    @property
    def versions(self) -> list[str]:
        return self.metadata["versions"]

    @cached_property
    def latest_version(self) -> str:
        """The spec describes the API as of this version (numeric max of versions)."""
        return max(self.versions, key=version_key)

    @cached_property
    def states(self) -> dict[str, State]:
        """The declared lifecycle states."""
        return resolve_states(self.metadata)

    @cached_property
    def registry(self) -> dict[str, str]:
        """Every declared spec name (and its prefixed form) mapped to its C name."""
        return build_registry(self.modules, self.suffixes, self.prefix)


def load(spec_dir: str | Path) -> Spec:
    """Load and validate the spec in `spec_dir`; raise on any invalid input.

    Schema violations raise jsonschema.ValidationError, an incompatible
    schema_version raises SchemaVersionError, and cross-module violations
    raise SpecError carrying every message.
    """
    spec_dir = Path(spec_dir)
    metadata = load_metadata(spec_dir)
    modules = load_modules(spec_dir)
    errors = validate_semantics(modules, metadata)
    if errors:
        raise SpecError(errors)
    return Spec(metadata=metadata, modules=modules)
