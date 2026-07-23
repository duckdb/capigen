# Releasing capigen

capigen is published to PyPI. The package version and the IDL schema version are
coupled: **`MAJOR.MINOR` of the package is the schema version; `PATCH` is tool-only.**
The version pins the schema, spec parsing and validation, and C/extension header
generation; a capigen version plus a spec version determines the contract artifacts.
Out-of-tree binding generators pin `~=MAJOR.MINOR` for the library surface the same
way spec authors do for the schema.

## Version rules

- **major** (`X.0.0`): a breaking schema change. A field removed or renamed, semantics
  changed, or validation tightened so a previously valid spec now fails.
- **minor** (`0.Y.0`): an additive schema change (a new optional field, a new construct),
  or a tool feature that ships without a schema change (the schema version then advances
  with content-identical semantics, which is harmless under the compatibility rule).
- **patch** (`0.0.Z`): tool-only. No schema change. Generated output may still change
  (for example a rendering fix); when it does, the release notes must say so, because
  consumers see the diff at their next deliberate pin bump.

Adapter options are part of the schema contract. `metadata.schema.json` validates
every `options.<adapter>` namespace, so adding an option is a minor, removing or
renaming one is a major, and a patch never touches options.

The loader accepts a spec when the majors match and the spec minor is at most the tool
minor. So a newer capigen reads any older-minor spec within the same major, and a spec
that needs a newer schema is refused with an actionable message.

## Compatibility with consumers

A consumer repository (for example DuckDB) pins a compatible capigen, e.g.
`capigen~=0.4.0`, and locks an exact version for reproducible generated output. Because
generated headers are typically committed and verified in CI, the exact lock is what
keeps a patch release from silently changing committed output. Bumping the pin is a
deliberate consumer action.

## Maintenance branches

Each minor line has a maintenance branch (`0.N-maintenance`), cut on demand when `main`
has moved on and an older line needs a fix. A consumer on an older schema line pins
`~=0.N.0` and receives patch fixes from that branch without pulling in newer-schema
features.

## Release checklist

1. Update `version` in `pyproject.toml`. `SCHEMA_VERSION` follows automatically.
2. If the schema version changed, update the pinned schema-version tag in the docs (the
   editor-autocomplete URLs in `schema_reference.md`, which point at the first tag of the
   line).
3. `uv run pre-commit run --all-files`, `uv run --group dev pytest`, and `uv build`.
4. Commit, then tag `vX.Y.Z` and push the tag. The `release` workflow runs the tests,
   builds, and publishes to PyPI via trusted publishing (OIDC; no token).
5. Bump the pin in consumer repositories and regenerate their committed output.

## PyPI trusted publishing

Publishing uses a PyPI trusted publisher (OpenID Connect), so no API token is stored.
Before the first release, configure a pending publisher on PyPI for the `capigen`
project pointing at this repository, the `release.yml` workflow, and the `pypi`
environment. After that, tagging is all that is needed.
