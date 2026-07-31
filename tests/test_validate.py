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

    def test_function_and_type_may_not_share_a_name(self, metadata, make_module):
        modules = [
            make_module("a", handles={"conn": {}}),
            make_module(
                "b",
                functions={
                    "conn": {
                        "return_type": "i32",
                        "return_pointer": 0,
                        "return_const": False,
                        "parameters": {},
                    },
                },
            ),
        ]
        errors = validate_semantics(modules, metadata)
        assert any("duplicated" in e and "conn" in e for e in errors)

    def test_constant_and_function_may_not_share_a_name(self, metadata, make_module):
        modules = [
            make_module("a", constants={"MAX": {"value": 8}}),
            make_module(
                "b",
                functions={
                    "MAX": {
                        "return_type": "i32",
                        "return_pointer": 0,
                        "return_const": False,
                        "parameters": {},
                    },
                },
            ),
        ]
        errors = validate_semantics(modules, metadata)
        assert any("duplicated" in e and "MAX" in e for e in errors)

    def test_duplicate_constant_across_modules(self, metadata, make_module):
        modules = [
            make_module("a", constants={"MAX": {"value": 8}}),
            make_module("b", constants={"MAX": {"value": 9}}),
        ]
        errors = validate_semantics(modules, metadata)
        assert any("duplicated" in e and "MAX" in e for e in errors)

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

    def test_valid_versions_accepted(self, metadata, make_module):
        modules = [
            make_module(
                "m",
                functions={
                    "duckdb_v2_func": _func(
                        lifecycle=[
                            ["deprecated", "v1.1.0", "2026-06-01"],
                            ["stable", "v1.0.0", "2026-01-01"],
                        ]
                    ),
                },
            ),
        ]
        errors = validate_semantics(modules, metadata)
        assert errors == []


UNSTABLE = [["unstable", "v1.0.0", "2026-01-01"]]


def _func(**overrides):
    func = {
        "return_type": "i32",
        "return_pointer": 0,
        "return_const": False,
        "parameters": {},
        "lifecycle": [["stable", "v1.0.0", "2026-01-01"]],
    }
    func.update(overrides)
    return func


class TestLifecycleReferences:
    """Only functions are gated, so a type is always there to be referenced.

    What still cannot be referenced is a construct that is emitted nowhere: a
    `never` state means the type is not part of the API at all.
    """

    GONE = [["removed", "v1.1.0", "2026-06-01"], ["stable", "v1.0.0", "2026-01-01"]]

    def test_stable_function_may_reference_unstable_handle(self, metadata, make_module):
        """The handle is emitted unconditionally, so nothing can dangle."""
        modules = [
            make_module("common", handles={"scratch": {"lifecycle": UNSTABLE}}),
            make_module(
                "api",
                functions={
                    "make": _func(return_type="scratch"),
                    "use": _func(
                        parameters={
                            "s": {"type": "scratch", "indirection": 0, "const": False}
                        }
                    ),
                },
            ),
        ]
        assert validate_semantics(modules, metadata) == []

    def test_unstable_function_may_reference_unstable_handle(
        self, metadata, make_module
    ):
        modules = [
            make_module("common", handles={"scratch": {"lifecycle": UNSTABLE}}),
            make_module(
                "api",
                functions={
                    "use": _func(
                        lifecycle=UNSTABLE,
                        parameters={
                            "s": {"type": "scratch", "indirection": 0, "const": False}
                        },
                    ),
                },
            ),
        ]
        assert validate_semantics(modules, metadata) == []

    def test_alias_struct_and_callback_may_reference_unstable_types(
        self, metadata, make_module
    ):
        """Every referrer kind: alias underlying, struct field (flat, union-nested
        and anonymous-nested), and a callback's return type and parameters."""
        modules = [
            make_module("common", handles={"scratch": {"lifecycle": UNSTABLE}}),
            make_module(
                "api",
                aliases={"mine": {"underlying": "scratch"}},
                structs={
                    "holder": {
                        "fields": [
                            {
                                "name": "s",
                                "type": "scratch",
                                "pointer": 0,
                                "const": False,
                            },
                            {
                                "name": "value",
                                "union": [
                                    {
                                        "name": "a",
                                        "fields": [{"name": "u", "type": "scratch"}],
                                    }
                                ],
                            },
                            {
                                "name": "inner",
                                "fields": [{"name": "n", "type": "scratch"}],
                            },
                        ],
                    }
                },
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
        assert validate_semantics(modules, metadata) == []

    def test_deprecated_function_may_reference_unstable_type(
        self, metadata, make_module
    ):
        status = [
            ["deprecated", "v1.1.0", "2026-06-01"],
            ["stable", "v1.0.0", "2026-01-01"],
        ]
        modules = [
            make_module("common", handles={"scratch": {"lifecycle": UNSTABLE}}),
            make_module(
                "api",
                functions={"old": _func(lifecycle=status, return_type="scratch")},
            ),
        ]
        assert validate_semantics(modules, metadata) == []

    def test_removed_type_is_still_rejected(self, metadata, make_module):
        """A `never` type is emitted nowhere, so a live referrer would not compile."""
        modules = [
            make_module("common", handles={"scratch": {"lifecycle": self.GONE}}),
            make_module("api", functions={"use": _func(return_type="scratch")}),
        ]
        errors = validate_semantics(modules, metadata)
        assert any(
            "references 'scratch' (state 'removed'), which is never emitted" in e
            for e in errors
        )

    def test_removed_type_in_a_struct_field_is_still_rejected(
        self, metadata, make_module
    ):
        modules = [
            make_module("common", handles={"scratch": {"lifecycle": self.GONE}}),
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
                        ]
                    }
                },
            ),
        ]
        errors = validate_semantics(modules, metadata)
        assert any("api::holder.s" in e and "never emitted" in e for e in errors)

    def test_stabilized_type_is_referenceable(self, metadata, make_module):
        status = [
            ["stable", "v1.1.0", "2026-06-01"],
            ["unstable", "v1.0.0", "2026-01-01"],
        ]
        modules = [
            make_module("common", handles={"scratch": {"lifecycle": status}}),
            make_module("api", functions={"use": _func(return_type="scratch")}),
        ]
        assert validate_semantics(modules, metadata) == []

    def test_function_may_not_predate_a_type_it_names(self, metadata, make_module):
        """A signature cannot involve a type that did not exist yet: the stamp is
        wrong, and a consumer targeting a version in between would get a
        declaration the library of that version never exported."""
        modules = [
            make_module(
                "common",
                handles={"later": {"lifecycle": [["stable", "v1.1.0", "2026-06-01"]]}},
            ),
            make_module(
                "api",
                functions={
                    "early": _func(
                        lifecycle=[["stable", "v1.0.0", "2026-01-01"]],
                        return_type="later",
                    )
                },
            ),
        ]
        errors = validate_semantics(modules, metadata)
        assert any(
            "introduced in v1.0.0 but references 'later', introduced later in v1.1.0"
            in e
            for e in errors
        )

    def test_handle_may_use_a_gated_cleanup_function(self, metadata, make_module):
        """The handle is always emitted; its destructor gates like any function."""
        modules = [
            make_module(
                "common",
                handles={"conn": {"cleanup_with": "destroy_conn"}},
                functions={"destroy_conn": _func(lifecycle=UNSTABLE)},
            ),
        ]
        assert validate_semantics(modules, metadata) == []

    def test_removed_cleanup_function_rejected(self, metadata, make_module):
        """A handle whose cleanup is gone leaves no way to free it."""
        modules = [
            make_module(
                "common",
                handles={"conn": {"cleanup_with": "destroy_conn"}},
                functions={"destroy_conn": _func(lifecycle=self.GONE)},
            ),
        ]
        errors = validate_semantics(modules, metadata)
        assert any(
            "common::conn" in e
            and "cleanup_with references 'destroy_conn' (state 'removed')" in e
            for e in errors
        )

    def test_prefixed_cleanup_with_resolves(self, metadata, make_module):
        """The real specs write prefixed names; resolution must still find them."""
        metadata["prefix"] = "duckdb_"
        modules = [
            make_module(
                "common",
                handles={"conn": {"cleanup_with": "duckdb_destroy_conn"}},
                functions={"destroy_conn": _func(lifecycle=self.GONE)},
            ),
        ]
        errors = validate_semantics(modules, metadata)
        assert any("cleanup_with references 'duckdb_destroy_conn'" in e for e in errors)

    def test_unknown_cleanup_with_rejected(self, metadata, make_module):
        modules = [
            make_module("common", handles={"conn": {"cleanup_with": "nonexistent"}}),
        ]
        errors = validate_semantics(modules, metadata)
        assert any(
            "cleanup_with names unknown function 'nonexistent'" in e for e in errors
        )

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
        assert validate_semantics(modules, metadata) == []


REMOVED = [["removed", "v1.1.0", "2026-06-01"], ["unstable", "v1.0.0", "2026-01-01"]]


class TestStateDeclarations:
    """Status entries must name a declared state; references respect emission."""

    def test_unknown_state_rejected(self, metadata, make_module):
        status = [["experimental", "v1.0.0", "2026-01-01"]]
        modules = [make_module("m", handles={"h": {"lifecycle": status}})]
        errors = validate_semantics(modules, metadata)
        assert any("m::h" in e and "unknown state 'experimental'" in e for e in errors)

    def test_historic_entries_are_checked_too(self, metadata, make_module):
        status = [
            ["stable", "v1.1.0", "2026-06-01"],
            ["typo_state", "v1.0.0", "2026-01-01"],
        ]
        modules = [make_module("m", handles={"h": {"lifecycle": status}})]
        errors = validate_semantics(modules, metadata)
        assert any("unknown state 'typo_state'" in e for e in errors)

    def test_status_without_states_block_rejected(self, metadata, make_module):
        """No states declared means no states exist."""
        del metadata["lifecycle_states"]
        modules = [make_module("m", handles={"h": {"lifecycle": UNSTABLE}})]
        errors = validate_semantics(modules, metadata)
        assert any(
            "unknown state 'unstable'" in e and "declared lifecycle states: none" in e
            for e in errors
        )

    def test_declared_states_are_the_whole_vocabulary(self, metadata, make_module):
        metadata["lifecycle_states"] = {
            "experimental": {"visibility": "opt_in", "guard": "G"}
        }
        ok = [["experimental", "v1.0.0", "2026-01-01"]]
        bad = [["stable", "v1.0.0", "2026-01-01"]]
        modules = [
            make_module("m", handles={"h": {"lifecycle": ok}, "i": {"lifecycle": bad}})
        ]
        errors = validate_semantics(modules, metadata)
        assert not any("m::h" in e for e in errors)
        assert any("m::i" in e and "unknown state 'stable'" in e for e in errors)

    def test_visible_referencing_removed_type_rejected(self, metadata, make_module):
        modules = [
            make_module("common", handles={"gone": {"lifecycle": REMOVED}}),
            make_module("api", functions={"use": _func(return_type="gone")}),
        ]
        errors = validate_semantics(modules, metadata)
        assert any(
            "references 'gone' (state 'removed'), which is never emitted" in e
            for e in errors
        )

    def test_removed_referencing_removed_type_accepted(self, metadata, make_module):
        modules = [
            make_module("common", handles={"gone": {"lifecycle": REMOVED}}),
            make_module(
                "api",
                functions={"use": _func(lifecycle=REMOVED, return_type="gone")},
            ),
        ]
        assert validate_semantics(modules, metadata) == []

    def test_opt_in_types_under_different_guards_accepted(self, metadata, make_module):
        metadata["lifecycle_states"] = {
            "exp_a": {"visibility": "opt_in", "guard": "GUARD_A"},
            "exp_b": {"visibility": "opt_in", "guard": "GUARD_B"},
        }
        a = [["exp_a", "v1.0.0", "2026-01-01"]]
        b = [["exp_b", "v1.0.0", "2026-01-01"]]
        modules = [
            make_module("common", handles={"h": {"lifecycle": b}}),
            make_module(
                "api",
                functions={"use": _func(lifecycle=a, return_type="h")},
            ),
        ]
        # The handle is emitted unconditionally whatever its state, so a referrer
        # under a different opt-in guard cannot dangle.
        assert validate_semantics(modules, metadata) == []

    def test_same_guard_same_state_accepted(self, metadata, make_module):
        modules = [
            make_module("common", handles={"h": {"lifecycle": UNSTABLE}}),
            make_module(
                "api", functions={"use": _func(lifecycle=UNSTABLE, return_type="h")}
            ),
        ]
        assert validate_semantics(modules, metadata) == []

    def test_deprecated_status_referencing_deprecated_type_accepted(
        self, metadata, make_module
    ):
        """Both vanish under the same opt-out guard, so the reference is safe."""
        dep = [["deprecated", "v1.1.0", "2026-06-01"]]
        modules = [
            make_module("common", handles={"h": {"lifecycle": dep}}),
            make_module(
                "api", functions={"old": _func(lifecycle=dep, return_type="h")}
            ),
        ]
        assert validate_semantics(modules, metadata) == []

    def test_stable_referencing_deprecated_type_accepted(self, metadata, make_module):
        """A deprecated type is still emitted, so opting out cannot break a referrer."""
        dep = [
            ["deprecated", "v1.1.0", "2026-06-01"],
            ["stable", "v1.0.0", "2026-01-01"],
        ]
        modules = [
            make_module("common", handles={"h": {"lifecycle": dep}}),
            make_module("api", functions={"use": _func(return_type="h")}),
        ]
        assert validate_semantics(modules, metadata) == []


class TestAnchorValidation:
    """Pass 5: every [[name]] resolves, and never to a never-emitted target."""

    def _func(self, description=None, **extra):
        f = {
            "return_type": "i32",
            "return_pointer": 0,
            "return_const": False,
            "parameters": {},
            "lifecycle": [["stable", "v1.0.0", "2026-01-01"]],
        }
        if description is not None:
            f["description"] = description
        f.update(extra)
        return f

    def test_unknown_anchor_is_an_error(self, metadata, make_module):
        modules = [
            make_module("m", functions={"go": self._func("See [[nope]].")}),
        ]
        errors = validate_semantics(modules, metadata)
        assert any("m::go" in e and "unknown anchor '[[nope]]'" in e for e in errors)

    def test_anchor_to_never_state_target_is_an_error(self, metadata, make_module):
        modules = [
            make_module(
                "m",
                handles={
                    "old": {"lifecycle": [["removed", "v1.0.0", "2026-01-01"]]},
                },
                functions={"go": self._func("Replaces [[old]].")},
            ),
        ]
        errors = validate_semantics(modules, metadata)
        assert any(
            "m::go" in e and "[[old]]" in e and "never emitted" in e for e in errors
        )

    def test_anchor_to_unstable_target_is_legal(self, metadata, make_module):
        modules = [
            make_module(
                "m",
                handles={
                    "scratch": {"lifecycle": [["unstable", "v1.1.0", "2026-01-01"]]},
                },
                functions={"go": self._func("See [[scratch]].")},
            ),
        ]
        assert validate_semantics(modules, metadata) == []

    def test_anchor_targets_span_all_construct_kinds(self, metadata, make_module):
        modules = [
            make_module(
                "m",
                handles={"conn": {}},
                aliases={"size": {"underlying": "u64"}},
                structs={"box": {"fields": []}},
                enums={"MODE": {"values": {"A": {}}}},
                constants={"MAX": {"value": 8}},
                callbacks={
                    "notify": {
                        "return_type": "i32",
                        "return_pointer": 0,
                        "return_const": False,
                        "parameters": {},
                    }
                },
                functions={
                    "go": self._func(
                        "[[conn]] [[size]] [[box]] [[MODE]] [[MAX]] [[notify]] [[go]]"
                    )
                },
            ),
        ]
        assert validate_semantics(modules, metadata) == []

    def test_anchors_checked_in_nested_description_sites(self, metadata, make_module):
        modules = [
            make_module(
                "m",
                structs={
                    "box": {
                        "fields": [
                            {
                                "name": "u",
                                "union": [
                                    {
                                        "name": "a",
                                        "fields": [
                                            {
                                                "name": "leaf",
                                                "type": "i32",
                                                "description": "[[bad1]]",
                                            }
                                        ],
                                    }
                                ],
                            }
                        ]
                    }
                },
                enums={
                    "MODE": {"values": {"A": {"description": "[[bad2]]"}}},
                },
                functions={
                    "go": self._func(
                        return_description="[[bad3]]",
                        parameters={
                            "x": {
                                "type": "i32",
                                "indirection": 0,
                                "const": False,
                                "description": "[[bad4]]",
                            }
                        },
                    )
                },
            ),
        ]
        errors = validate_semantics(modules, metadata)
        for bad, ctx in [
            ("bad1", "m::box.u.a.leaf"),
            ("bad2", "m::MODE.A"),
            ("bad3", "m::go"),
            ("bad4", "m::go.x"),
        ]:
            assert any(ctx in e and f"[[{bad}]]" in e for e in errors), bad

    def test_malformed_brackets_are_errors(self, metadata, make_module):
        """Double brackets are reserved; a near-miss anchor must not rot silently."""
        for text in ("A [[0, 1]] range.", "See [[go()]].", "See [[ go]]."):
            modules = [
                make_module("m", functions={"go": self._func(text)}),
            ]
            errors = validate_semantics(modules, metadata)
            assert any("m::go" in e and "malformed anchor" in e for e in errors), text

    def test_plain_brackets_and_prose_are_fine(self, metadata, make_module):
        modules = [
            make_module("m", functions={"go": self._func("An array [0] and [x].")}),
        ]
        assert validate_semantics(modules, metadata) == []
