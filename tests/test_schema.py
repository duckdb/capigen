"""Tests for module.schema.json validation (identifier rules, etc.)."""

import json
from pathlib import Path

import jsonschema
import pytest

SCHEMA = json.loads(
    (Path(__file__).parent.parent / "src/capigen/schema/module.schema.json").read_text()
)
METADATA_SCHEMA = json.loads(
    (
        Path(__file__).parent.parent / "src/capigen/schema/metadata.schema.json"
    ).read_text()
)


def _minimal_module(**overrides):
    mod = {"module": "test"}
    mod.update(overrides)
    return mod


class TestPropertyNameValidation:
    """The schema accepts any valid C identifier; rejects names that are not."""

    @pytest.mark.parametrize(
        "construct,entry",
        [
            ("handles", {"duckdb_conn": {}}),
            ("aliases", {"duckdb_idx": {"underlying": "u32"}}),
            ("structs", {"duckdb_date": {"fields": []}}),
            ("enums", {"DUCKDB_TYPE": {"values": {}}}),
            ("callbacks", {"duckdb_cb": {"return_type": "opaque"}}),
            ("constants", {"DUCKDB_MAX": {"value": 42}}),
            (
                "functions",
                {"duckdb_open": {"description": "test"}},
            ),
        ],
    )
    def test_non_v2_prefix_accepted(self, construct, entry):
        mod = _minimal_module(**{construct: entry})
        jsonschema.validate(mod, SCHEMA)  # should not raise

    @pytest.mark.parametrize(
        "construct,entry",
        [
            ("handles", {"duckdb_v2_conn": {}}),
            ("aliases", {"duckdb_v2_idx": {"underlying": "u32"}}),
            ("structs", {"duckdb_v2_date": {"fields": []}}),
            ("enums", {"DUCKDB_V2_TYPE": {"values": {}}}),
            ("callbacks", {"duckdb_v2_cb": {"return_type": "opaque"}}),
            ("constants", {"DUCKDB_V2_MAX": {"value": 42}}),
            (
                "functions",
                {"duckdb_v2_open": {"description": "test"}},
            ),
        ],
    )
    def test_v2_prefix_accepted(self, construct, entry):
        mod = _minimal_module(**{construct: entry})
        jsonschema.validate(mod, SCHEMA)  # should not raise

    @pytest.mark.parametrize(
        "construct,entry",
        [
            ("handles", {"1invalid": {}}),
            ("aliases", {"bad name": {"underlying": "u32"}}),
            ("structs", {"has-hyphen": {"fields": []}}),
            ("enums", {"": {"values": {}}}),
            ("constants", {"has space": {"value": 42}}),
        ],
    )
    def test_invalid_identifiers_rejected(self, construct, entry):
        mod = _minimal_module(**{construct: entry})
        with pytest.raises(jsonschema.ValidationError, match="does not match"):
            jsonschema.validate(mod, SCHEMA)


class TestStatusStateNames:
    """The schema accepts any identifier as a state; validate.py checks the name."""

    def test_custom_state_name_accepted(self):
        mod = _minimal_module(
            handles={"h": {"lifecycle": [["experimental", "v1.0.0", "2026-01-01"]]}}
        )
        jsonschema.validate(mod, SCHEMA)  # should not raise

    def test_invalid_state_identifier_rejected(self):
        mod = _minimal_module(
            handles={"h": {"lifecycle": [["not a name", "v1.0.0", "2026-01-01"]]}}
        )
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(mod, SCHEMA)


class TestMetadataStates:
    """The states block: mode is required; guard only for gated modes."""

    def _metadata(self, states):
        return {
            "schema_version": "0.5",
            "versions": ["v1.0.0"],
            "suffixes": {"handles": "_h", "callbacks": "_cb", "aliases": "_t"},
            "primitives": [{"name": "u32", "c_type": "uint32_t"}],
            "lifecycle_states": states,
        }

    def test_valid_states_accepted(self):
        states = {
            "unstable": {"visibility": "opt_in", "guard": "API_UNSTABLE"},
            "stable": {"visibility": "always"},
            "deprecated": {"visibility": "opt_out", "guard": "API_NO_DEPRECATED"},
            "removed": {"visibility": "never"},
        }
        jsonschema.validate(self._metadata(states), METADATA_SCHEMA)

    def test_mode_required(self):
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(self._metadata({"stable": {}}), METADATA_SCHEMA)

    def test_unknown_mode_rejected(self):
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(
                self._metadata({"stable": {"visibility": "hidden"}}), METADATA_SCHEMA
            )

    def test_opt_in_requires_guard(self):
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(
                self._metadata({"unstable": {"visibility": "opt_in"}}), METADATA_SCHEMA
            )

    def test_opt_out_requires_guard(self):
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(
                self._metadata({"deprecated": {"visibility": "opt_out"}}),
                METADATA_SCHEMA,
            )

    def test_visible_forbids_guard(self):
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(
                self._metadata({"stable": {"visibility": "always", "guard": "G"}}),
                METADATA_SCHEMA,
            )

    def test_state_name_must_be_identifier(self):
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(
                self._metadata({"my-state": {"visibility": "always"}}), METADATA_SCHEMA
            )

    def test_omit_forbids_guard(self):
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(
                self._metadata({"removed": {"visibility": "never", "guard": "G"}}),
                METADATA_SCHEMA,
            )


class TestAdapterOptionSchemas:
    """Each adapter ships a strict schema for its options file."""

    C = json.loads(
        (
            Path(__file__).parent.parent / "src/capigen/adapters/c/options.schema.json"
        ).read_text()
    )
    BRIDGE = json.loads(
        (
            Path(__file__).parent.parent
            / "src/capigen/adapters/bridge/options.schema.json"
        ).read_text()
    )
    EXT = json.loads(
        (
            Path(__file__).parent.parent
            / "src/capigen/adapters/extension_header/options.schema.json"
        ).read_text()
    )

    def test_valid_c_options_accepted(self):
        jsonschema.validate(
            {
                "comment_width": 120,
                "export_macro": "LIB_C_API",
                "emit_deprecated_attribute": True,
                "banner": "// banner",
                "handles": {
                    "default_style": "tagged_struct",
                    "override_style": {"task_state": "void_ptr"},
                },
                "emit_enum_max_member": False,
            },
            self.C,
        )

    def test_typo_in_c_options_rejected(self):
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate({"comment_widht": 120}, self.C)

    @pytest.mark.parametrize("dead", ["unstable_guard", "no_deprecated_guard"])
    def test_dead_guard_token_options_rejected(self, dead):
        """Guard tokens live on states; the old options are schema errors."""
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate({dead: "SOME_TOKEN"}, self.C)

    def test_deprecated_encoding_is_gone(self):
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate({"deprecated_encoding": "none"}, self.C)

    def test_bad_handle_style_rejected(self):
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate({"handles": {"default_style": "fancy"}}, self.C)

    def test_valid_bridge_options_accepted(self):
        jsonschema.validate(
            {"stub_return": "LIB_ERROR", "include_header": "internal.hpp"},
            self.BRIDGE,
        )

    def test_extension_requires_its_fields(self):
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate({"create_method": "CreateAPI"}, self.EXT)

    def test_valid_extension_options_accepted(self):
        jsonschema.validate(
            {
                "create_method": "CreateAPI",
                "version_macro_prefix": "LIB_API_VERSION",
                "internal_include": "lib.h",
                "exclude_functions": ["skipme"],
            },
            self.EXT,
        )

    def test_metadata_rejects_an_options_block(self):
        """metadata.yaml is pure spec; adapter options live in options/<adapter>.yaml."""
        meta = {
            "schema_version": "0.5",
            "versions": ["v1.0.0"],
            "suffixes": {"handles": "_h", "callbacks": "_cb", "aliases": "_t"},
            "primitives": [{"name": "u32", "c_type": "uint32_t"}],
            "options": {"c": {"comment_width": 120}},
        }
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(meta, METADATA_SCHEMA)


class TestSummaryRemoved:
    """description is the only doc field; the old summary field is rejected."""

    def test_summary_rejected(self):
        mod = _minimal_module(functions={"duckdb_v2_open": {"summary": "gone"}})
        with pytest.raises(jsonschema.ValidationError, match="summary"):
            jsonschema.validate(mod, SCHEMA)

    def test_function_without_doc_fields_accepted(self):
        mod = _minimal_module(functions={"duckdb_v2_open": {}})
        jsonschema.validate(mod, SCHEMA)  # should not raise


class TestQualifiedAliases:
    """aliases with qualified:true are emitted verbatim — no prefix or suffix applied."""

    def test_qualified_alias_accepted(self):
        mod = _minimal_module(
            aliases={"sel_t": {"underlying": "u32", "qualified": True}}
        )
        jsonschema.validate(mod, SCHEMA)  # should not raise

    def test_qualified_alias_invalid_identifier_rejected(self):
        mod = _minimal_module(
            aliases={"1bad": {"underlying": "u32", "qualified": True}}
        )
        with pytest.raises(jsonschema.ValidationError, match="does not match"):
            jsonschema.validate(mod, SCHEMA)

    def test_qualified_alias_missing_underlying_rejected(self):
        mod = _minimal_module(aliases={"sel_t": {"qualified": True}})
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(mod, SCHEMA)


class TestParameterKind:
    """The `kind` field on Parameter accepts IN/IN_TRANSFER/OUT/OUT_BORROW."""

    def _func_with_kind(self, kind):
        return _minimal_module(
            functions={
                "duckdb_v2_f": {
                    "parameters": {
                        "p": {
                            "type": "char",
                            "indirection": 1,
                            "kind": kind,
                        }
                    },
                }
            }
        )

    @pytest.mark.parametrize("kind", ["IN", "IN_TRANSFER", "OUT", "OUT_BORROW"])
    def test_valid_values_accepted(self, kind):
        jsonschema.validate(self._func_with_kind(kind), SCHEMA)

    @pytest.mark.parametrize("kind", ["in", "out", "shared", "INOUT"])
    def test_invalid_value_rejected(self, kind):
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(self._func_with_kind(kind), SCHEMA)

    def test_default_is_IN(self):
        """When omitted, apply_defaults() fills kind with 'IN'."""
        from capigen.loader import apply_defaults

        mod = _minimal_module(
            functions={
                "duckdb_v2_f": {
                    "parameters": {"p": {"type": "char", "indirection": 1}},
                }
            }
        )
        apply_defaults(mod, SCHEMA)
        param = mod["functions"]["duckdb_v2_f"]["parameters"]["p"]
        assert param["kind"] == "IN"


class TestStructFieldArraySize:
    """Struct fields may declare array_size for inline fixed-size arrays."""

    def _struct_with_field(self, field):
        return _minimal_module(
            structs={
                "duckdb_v2_s": {
                    "fields": [{"name": "x", "type": "char", **field}],
                }
            }
        )

    def test_array_size_accepted(self):
        mod = self._struct_with_field({"array_size": 256})
        jsonschema.validate(mod, SCHEMA)  # should not raise

    def test_array_size_with_pointer_rejected(self):
        mod = self._struct_with_field({"array_size": 256, "pointer": 1})
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(mod, SCHEMA)

    def test_array_size_zero_rejected(self):
        mod = self._struct_with_field({"array_size": 0})
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(mod, SCHEMA)

    def test_array_size_negative_rejected(self):
        mod = self._struct_with_field({"array_size": -1})
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(mod, SCHEMA)

    def test_array_size_optional(self):
        """Fields without array_size still validate."""
        mod = self._struct_with_field({"pointer": 1})
        jsonschema.validate(mod, SCHEMA)  # should not raise


class TestStructFieldAggregates:
    """Struct fields may be a leaf (type), a nested struct (fields), or a union."""

    def _struct(self, field):
        return _minimal_module(structs={"duckdb_v2_s": {"fields": [field]}})

    def test_nested_struct_field_accepted(self):
        mod = self._struct(
            {
                "name": "inner",
                "fields": [
                    {"name": "a", "type": "u32"},
                    {"name": "b", "type": "char", "pointer": 1},
                ],
            }
        )
        jsonschema.validate(mod, SCHEMA)  # should not raise

    def test_union_field_accepted(self):
        mod = self._struct(
            {
                "name": "value",
                "union": [
                    {
                        "name": "pointer",
                        "fields": [
                            {"name": "length", "type": "u32"},
                            {"name": "prefix", "type": "char", "array_size": 4},
                        ],
                    },
                    {
                        "name": "inlined",
                        "fields": [
                            {"name": "inlined", "type": "char", "array_size": 12}
                        ],
                    },
                ],
            }
        )
        jsonschema.validate(mod, SCHEMA)  # should not raise

    def test_field_without_type_or_aggregate_rejected(self):
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(self._struct({"name": "x"}), SCHEMA)

    def test_field_with_type_and_fields_rejected(self):
        bad = {"name": "x", "type": "u32", "fields": [{"name": "a", "type": "u32"}]}
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(self._struct(bad), SCHEMA)

    def test_field_with_type_and_union_rejected(self):
        bad = {
            "name": "x",
            "type": "u32",
            "union": [{"name": "m", "fields": [{"name": "a", "type": "u32"}]}],
        }
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(self._struct(bad), SCHEMA)

    def test_union_member_missing_fields_rejected(self):
        bad = {"name": "value", "union": [{"name": "pointer"}]}
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(self._struct(bad), SCHEMA)

    def test_nested_struct_with_leaf_attr_rejected(self):
        bad = {"name": "inner", "fields": [{"name": "a", "type": "u32"}], "pointer": 1}
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(self._struct(bad), SCHEMA)

    def test_union_with_leaf_attr_rejected(self):
        bad = {
            "name": "value",
            "union": [{"name": "m", "fields": [{"name": "a", "type": "u32"}]}],
            "array_size": 4,
        }
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(self._struct(bad), SCHEMA)

    def test_union_member_description_accepted(self):
        mod = self._struct(
            {
                "name": "value",
                "union": [
                    {
                        "name": "pointer",
                        "description": "out-of-line form",
                        "fields": [{"name": "length", "type": "u32"}],
                    }
                ],
            }
        )
        jsonschema.validate(mod, SCHEMA)  # should not raise
