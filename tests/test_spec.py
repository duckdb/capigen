"""Tests for the capigen.load front door (spec.py)."""

from pathlib import Path

import pytest

import capigen

TESTSPEC_DIR = Path(__file__).parent / "testspec" / "v2"


class TestLoad:
    def test_load_returns_validated_spec(self):
        spec = capigen.load(TESTSPEC_DIR)
        assert spec.modules
        assert spec.metadata["prefix"] == "duckdb_v2_"
        assert spec.prefix == "duckdb_v2_"
        assert spec.schema_version == "0.5"

    def test_derived_views(self):
        spec = capigen.load(TESTSPEC_DIR)
        assert spec.latest_version == "v1.0.0"
        assert spec.states["unstable"].guard == "DUCKDB_V2_API_UNSTABLE"
        assert spec.registry["ctx"] == "duckdb_v2_ctx_ptr"

    def test_semantic_errors_raise_spec_error(self, tmp_path):
        (tmp_path / "metadata.yaml").write_text(
            'schema_version: "0.5"\n'
            'versions: ["v1.0.0"]\n'
            "lifecycle_states:\n"
            "  unstable: {visibility: opt_in, guard: G}\n"
            "suffixes: {handles: _h, callbacks: _cb, aliases: _t}\n"
            "primitives: [{name: i32, c_type: int32_t}]\n"
        )
        (tmp_path / "m.yaml").write_text(
            "module: m\n"
            "handles:\n"
            "  gadget:\n"
            '    lifecycle: [["unstable", "v1.0.0", "2026-01-01"]]\n'
            "functions:\n"
            "  use:\n"
            "    return_type: gadget\n"
        )
        with pytest.raises(capigen.SpecError, match="references 'gadget'") as exc:
            capigen.load(tmp_path)
        assert len(exc.value.errors) == 1

    def test_empty_versions_rejected_by_schema(self, tmp_path):
        import jsonschema

        (tmp_path / "metadata.yaml").write_text(
            'schema_version: "0.5"\n'
            "versions: []\n"
            "suffixes: {handles: _h, callbacks: _cb, aliases: _t}\n"
            "primitives: [{name: i32, c_type: int32_t}]\n"
        )
        with pytest.raises(jsonschema.ValidationError):
            capigen.load(tmp_path)
