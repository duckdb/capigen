"""Tests for cross-module referential integrity (validate.py)."""

from capigen.validate import validate_semantics


class TestDuplicateDetection:
    def test_duplicate_handle_across_modules(self, metadata, make_module):
        modules = [
            make_module("a", handles={"duckdb_v2_my_handle": {}}),
            make_module("b", handles={"duckdb_v2_my_handle": {}}),
        ]
        errors = validate_semantics(modules, metadata)
        assert any("duplicated" in e and "duckdb_v2_my_handle" in e for e in errors)

    def test_duplicate_function_across_modules(self, metadata, make_module):
        modules = [
            make_module(
                "a",
                functions={
                    "duckdb_v2_do_thing": {
                        "summary": "x",
                        "return_type": "i32",
                        "return_pointer": 0,
                        "return_const": False,
                        "parameters": {},
                    },
                },
            ),
            make_module(
                "b",
                functions={
                    "duckdb_v2_do_thing": {
                        "summary": "y",
                        "return_type": "i32",
                        "return_pointer": 0,
                        "return_const": False,
                        "parameters": {},
                    },
                },
            ),
        ]
        errors = validate_semantics(modules, metadata)
        assert any("duplicated" in e and "duckdb_v2_do_thing" in e for e in errors)

    def test_duplicate_across_construct_types(self, metadata, make_module):
        modules = [
            make_module("a", handles={"duckdb_v2_clash": {}}),
            make_module("b", aliases={"duckdb_v2_clash": {"underlying": "u32"}}),
        ]
        errors = validate_semantics(modules, metadata)
        assert any("duplicated" in e and "duckdb_v2_clash" in e for e in errors)

    def test_no_errors_when_names_are_unique(self, metadata, make_module):
        modules = [
            make_module("a", handles={"duckdb_v2_handle_a": {}}),
            make_module("b", handles={"duckdb_v2_handle_b": {}}),
        ]
        errors = validate_semantics(modules, metadata)
        assert errors == []


class TestTypeReferences:
    def test_unknown_alias_underlying(self, metadata, make_module):
        modules = [
            make_module("m", aliases={"duckdb_v2_t": {"underlying": "nonexistent"}}),
        ]
        errors = validate_semantics(modules, metadata)
        assert any("Unknown underlying type 'nonexistent'" in e for e in errors)

    def test_alias_to_primitive(self, metadata, make_module):
        modules = [
            make_module("m", aliases={"duckdb_v2_my_int": {"underlying": "u32"}}),
        ]
        errors = validate_semantics(modules, metadata)
        assert errors == []

    def test_alias_to_handle(self, metadata, make_module):
        modules = [
            make_module("common", handles={"duckdb_v2_ctx": {}}),
            make_module(
                "m", aliases={"duckdb_v2_my_ctx": {"underlying": "duckdb_v2_ctx"}}
            ),
        ]
        errors = validate_semantics(modules, metadata)
        assert errors == []

    def test_unknown_struct_field_type(self, metadata, make_module):
        modules = [
            make_module(
                "m",
                structs={
                    "duckdb_v2_s": {
                        "fields": [
                            {
                                "name": "f",
                                "type": "nonexistent",
                                "pointer": 0,
                                "const": False,
                            }
                        ],
                    }
                },
            ),
        ]
        errors = validate_semantics(modules, metadata)
        assert any("Unknown field type 'nonexistent'" in e for e in errors)

    def test_cross_module_type_reference_is_valid(self, metadata, make_module):
        modules = [
            make_module("common", handles={"duckdb_v2_handle": {}}),
            make_module(
                "other",
                structs={
                    "duckdb_v2_s": {
                        "fields": [
                            {
                                "name": "h",
                                "type": "duckdb_v2_handle",
                                "pointer": 0,
                                "const": False,
                            }
                        ],
                    }
                },
            ),
        ]
        errors = validate_semantics(modules, metadata)
        assert errors == []

    def test_unknown_callback_param_type(self, metadata, make_module):
        modules = [
            make_module(
                "m",
                callbacks={
                    "duckdb_v2_cb": {
                        "return_type": "opaque",
                        "return_pointer": 0,
                        "return_const": False,
                        "parameters": {
                            "p": {
                                "type": "missing",
                                "indirection": 0,
                                "const": False,
                            }
                        },
                    }
                },
            ),
        ]
        errors = validate_semantics(modules, metadata)
        assert any("Unknown parameter type 'missing'" in e for e in errors)

    def test_unknown_callback_return_type(self, metadata, make_module):
        modules = [
            make_module(
                "m",
                callbacks={
                    "duckdb_v2_cb": {
                        "return_type": "missing",
                        "return_pointer": 0,
                        "return_const": False,
                        "parameters": {},
                    }
                },
            ),
        ]
        errors = validate_semantics(modules, metadata)
        assert any("Unknown return type 'missing'" in e for e in errors)


class TestFunctionValidation:
    def test_unknown_param_type(self, metadata, make_module):
        modules = [
            make_module(
                "m",
                functions={
                    "duckdb_v2_func": {
                        "summary": "test",
                        "return_type": "i32",
                        "return_pointer": 0,
                        "return_const": False,
                        "parameters": {
                            "p": {
                                "type": "missing",
                                "indirection": 0,
                                "const": False,
                            }
                        },
                    },
                },
            ),
        ]
        errors = validate_semantics(modules, metadata)
        assert any("Unknown parameter type 'missing'" in e for e in errors)

    def test_unknown_return_type(self, metadata, make_module):
        modules = [
            make_module(
                "m",
                functions={
                    "duckdb_v2_func": {
                        "summary": "test",
                        "return_type": "missing",
                        "return_pointer": 0,
                        "return_const": False,
                        "parameters": {},
                    },
                },
            ),
        ]
        errors = validate_semantics(modules, metadata)
        assert any("Unknown return type 'missing'" in e for e in errors)

    def test_unknown_added_version(self, metadata, make_module):
        modules = [
            make_module(
                "m",
                functions={
                    "duckdb_v2_func": {
                        "summary": "test",
                        "return_type": "i32",
                        "return_pointer": 0,
                        "return_const": False,
                        "parameters": {},
                        "added": "9.9.9",
                    },
                },
            ),
        ]
        errors = validate_semantics(modules, metadata)
        assert any("Unknown 'added' version '9.9.9'" in e for e in errors)

    def test_unknown_deprecated_version(self, metadata, make_module):
        modules = [
            make_module(
                "m",
                functions={
                    "duckdb_v2_func": {
                        "summary": "test",
                        "return_type": "i32",
                        "return_pointer": 0,
                        "return_const": False,
                        "parameters": {},
                        "deprecated": "9.9.9",
                    },
                },
            ),
        ]
        errors = validate_semantics(modules, metadata)
        assert any("Unknown 'deprecated' version '9.9.9'" in e for e in errors)

    def test_valid_versions_accepted(self, metadata, make_module):
        modules = [
            make_module(
                "m",
                functions={
                    "duckdb_v2_func": {
                        "summary": "test",
                        "return_type": "i32",
                        "return_pointer": 0,
                        "return_const": False,
                        "parameters": {},
                        "added": "1.0.0",
                        "deprecated": "1.1.0",
                    },
                },
            ),
        ]
        errors = validate_semantics(modules, metadata)
        assert errors == []


UNSTABLE = [["unstable", "v1.0.0", "2026-01-01"]]


def _func(**overrides):
    func = {
        "summary": "test",
        "return_type": "i32",
        "return_pointer": 0,
        "return_const": False,
        "parameters": {},
    }
    func.update(overrides)
    return func


class TestUnstableReferences:
    """A symbol that is not unstable must not reference an unstable type."""

    def test_stable_function_param_rejects_unstable_handle(self, metadata, make_module):
        modules = [
            make_module("common", handles={"scratch": {"status": UNSTABLE}}),
            make_module(
                "api",
                functions={
                    "use": _func(
                        parameters={
                            "s": {"type": "scratch", "indirection": 0, "const": False}
                        }
                    ),
                },
            ),
        ]
        errors = validate_semantics(modules, metadata)
        assert any(
            "api::use.s" in e and "references unstable type 'scratch'" in e
            for e in errors
        )

    def test_stable_function_return_rejects_unstable_handle(
        self, metadata, make_module
    ):
        modules = [
            make_module("common", handles={"scratch": {"status": UNSTABLE}}),
            make_module("api", functions={"make": _func(return_type="scratch")}),
        ]
        errors = validate_semantics(modules, metadata)
        assert any("references unstable type 'scratch'" in e for e in errors)

    def test_unstable_function_may_reference_unstable_handle(
        self, metadata, make_module
    ):
        modules = [
            make_module("common", handles={"scratch": {"status": UNSTABLE}}),
            make_module(
                "api",
                functions={
                    "use": _func(
                        status=UNSTABLE,
                        parameters={
                            "s": {"type": "scratch", "indirection": 0, "const": False}
                        },
                    ),
                },
            ),
        ]
        errors = validate_semantics(modules, metadata)
        assert errors == []

    def test_stable_alias_rejects_unstable_underlying(self, metadata, make_module):
        modules = [
            make_module("common", handles={"scratch": {"status": UNSTABLE}}),
            make_module("api", aliases={"mine": {"underlying": "scratch"}}),
        ]
        errors = validate_semantics(modules, metadata)
        assert any(
            "api::mine" in e and "references unstable type 'scratch'" in e
            for e in errors
        )

    def test_unstable_alias_may_reference_unstable_underlying(
        self, metadata, make_module
    ):
        modules = [
            make_module("common", handles={"scratch": {"status": UNSTABLE}}),
            make_module(
                "api",
                aliases={"mine": {"underlying": "scratch", "status": UNSTABLE}},
            ),
        ]
        errors = validate_semantics(modules, metadata)
        assert errors == []

    def test_stable_struct_field_rejects_unstable_type(self, metadata, make_module):
        modules = [
            make_module("common", handles={"scratch": {"status": UNSTABLE}}),
            make_module(
                "api",
                structs={
                    "holder": {
                        "fields": [
                            {
                                "name": "s",
                                "type": "scratch",
                                "pointer": 0,
                                "const": False,
                            }
                        ],
                    }
                },
            ),
        ]
        errors = validate_semantics(modules, metadata)
        assert any(
            "api::holder.s" in e and "references unstable type 'scratch'" in e
            for e in errors
        )

    def test_stable_struct_nested_field_rejects_unstable_type(
        self, metadata, make_module
    ):
        modules = [
            make_module("common", handles={"scratch": {"status": UNSTABLE}}),
            make_module(
                "api",
                structs={
                    "holder": {
                        "fields": [
                            {
                                "name": "value",
                                "union": [
                                    {
                                        "name": "a",
                                        "fields": [{"name": "s", "type": "scratch"}],
                                    }
                                ],
                            }
                        ],
                    }
                },
            ),
        ]
        errors = validate_semantics(modules, metadata)
        assert any("references unstable type 'scratch'" in e for e in errors)

    def test_stable_callback_rejects_unstable_types(self, metadata, make_module):
        modules = [
            make_module("common", handles={"scratch": {"status": UNSTABLE}}),
            make_module(
                "api",
                callbacks={
                    "notify": {
                        "return_type": "scratch",
                        "return_pointer": 0,
                        "return_const": False,
                        "parameters": {
                            "s": {"type": "scratch", "indirection": 0, "const": False}
                        },
                    }
                },
            ),
        ]
        errors = validate_semantics(modules, metadata)
        assert (
            len([e for e in errors if "references unstable type 'scratch'" in e]) == 2
        )

    def test_deprecated_function_rejects_unstable_type(self, metadata, make_module):
        """Deprecated is compiled by default (opt-out), unstable is not (opt-in)."""
        status = [
            ["deprecated", "v1.1.0", "2026-06-01"],
            ["stable", "v1.0.0", "2026-01-01"],
        ]
        modules = [
            make_module("common", handles={"scratch": {"status": UNSTABLE}}),
            make_module(
                "api",
                functions={"old": _func(status=status, return_type="scratch")},
            ),
        ]
        errors = validate_semantics(modules, metadata)
        assert any("references unstable type 'scratch'" in e for e in errors)

    def test_stabilized_type_is_referenceable(self, metadata, make_module):
        """A type whose current status is stable no longer gates its referrers."""
        status = [
            ["stable", "v1.1.0", "2026-06-01"],
            ["unstable", "v1.0.0", "2026-01-01"],
        ]
        modules = [
            make_module("common", handles={"scratch": {"status": status}}),
            make_module("api", functions={"use": _func(return_type="scratch")}),
        ]
        errors = validate_semantics(modules, metadata)
        assert errors == []

    def test_stable_struct_anonymous_nested_field_rejects_unstable_type(
        self, metadata, make_module
    ):
        """The anonymous-struct branch (`fields`, not `union`) recurses too."""
        modules = [
            make_module("common", handles={"scratch": {"status": UNSTABLE}}),
            make_module(
                "api",
                structs={
                    "holder": {
                        "fields": [
                            {
                                "name": "inner",
                                "fields": [{"name": "s", "type": "scratch"}],
                            }
                        ],
                    }
                },
            ),
        ]
        errors = validate_semantics(modules, metadata)
        assert any("references unstable type 'scratch'" in e for e in errors)

    def test_stable_handle_rejects_unstable_cleanup_function(
        self, metadata, make_module
    ):
        """A visible handle must not point at a guarded-out destroy function."""
        modules = [
            make_module(
                "common",
                handles={"conn": {"cleanup_with": "destroy_conn"}},
                functions={"destroy_conn": _func(status=UNSTABLE)},
            ),
        ]
        errors = validate_semantics(modules, metadata)
        assert any(
            "common::conn" in e
            and "cleanup_with references unstable function 'destroy_conn'" in e
            for e in errors
        )

    def test_unstable_handle_may_use_unstable_cleanup_function(
        self, metadata, make_module
    ):
        modules = [
            make_module(
                "common",
                handles={"conn": {"cleanup_with": "destroy_conn", "status": UNSTABLE}},
                functions={"destroy_conn": _func(status=UNSTABLE)},
            ),
        ]
        errors = validate_semantics(modules, metadata)
        assert errors == []

    def test_stable_handle_with_stable_cleanup_function_is_fine(
        self, metadata, make_module
    ):
        modules = [
            make_module(
                "common",
                handles={"conn": {"cleanup_with": "destroy_conn"}},
                functions={"destroy_conn": _func()},
            ),
        ]
        errors = validate_semantics(modules, metadata)
        assert errors == []
