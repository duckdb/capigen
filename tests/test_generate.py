"""Integration tests: round-trip generation and C compilation."""

import subprocess
import shutil
from pathlib import Path

import jsonschema
import pytest

from capigen.loader import load_metadata, load_modules
from capigen.validate import validate_semantics
from capigen.adapters.c import generate


REPO_ROOT = Path(__file__).parent.parent
TESTSPEC_DIR = Path(__file__).parent / "testspec" / "v2"


class TestRoundTrip:
    """Generate from the bundled test spec and verify the output is valid."""

    def test_generates_valid_header(self, tmp_path):
        metadata = load_metadata(TESTSPEC_DIR)
        modules = load_modules(TESTSPEC_DIR)

        errors = validate_semantics(modules, metadata)
        assert errors == [], f"Semantic validation errors: {errors}"

        output = tmp_path / "duckdb_v2.h"
        generate(modules, metadata, output)

        content = output.read_text()
        assert "duckdb_v2_open" in content
        assert "duckdb_v2_close" in content
        assert "duckdb_v2_ctx_ptr" in content
        assert "duckdb_v2_database_ptr" in content
        assert "DUCKDB_V2_TYPE" in content
        assert "DUCKDB_V2_API_ERROR" in content
        # The unstable constructs in the testspec render behind the opt-in guard.
        assert (
            "#if DUCKDB_V2_API_VERSION_AT_LEAST(1, 0, 0) && "
            "DUCKDB_V2_API_ALLOW_UNSTABLE" in content
        )
        # The removed function is not emitted at all.
        assert "duckdb_v2_legacy_open(" not in content
        # Every enum ends with the width-pinning sentinel.
        assert "DUCKDB_V2_TYPE_MAX_ENUM = 0x7FFFFFFF," in content

    def test_output_is_deterministic(self, tmp_path):
        """Running the generator twice produces identical output."""
        metadata = load_metadata(TESTSPEC_DIR)
        modules = load_modules(TESTSPEC_DIR)

        out1 = tmp_path / "first.h"
        out2 = tmp_path / "second.h"
        generate(modules, metadata, out1)
        generate(modules, metadata, out2)

        assert out1.read_text() == out2.read_text()


class TestInlineArrayStructRendering:
    """Struct fields with array_size render as C fixed-size arrays."""

    def _metadata(self):
        return {
            "schema_version": "0.2.0",
            "versions": ["1.0.0"],
            "suffixes": {"handles": "_ptr", "callbacks": "_cb", "aliases": "_t"},
            "primitives": [
                {"name": "opaque", "c_type": "void"},
                {"name": "char", "c_type": "char"},
                {"name": "u32", "c_type": "uint32_t"},
            ],
        }

    def _module(self):
        return {
            "module": "m",
            "handles": {},
            "callbacks": {},
            "aliases": {},
            "structs": {
                "duckdb_v2_err": {
                    "pointer_alias": False,
                    "fields": [
                        {
                            "name": "code",
                            "type": "u32",
                            "pointer": 0,
                            "const": False,
                        },
                        {
                            "name": "message",
                            "type": "char",
                            "pointer": 0,
                            "const": False,
                            "array_size": 64,
                        },
                    ],
                },
            },
            "enums": {},
            "constants": {},
            "functions": {},
        }

    def test_array_size_renders_bracket(self, tmp_path):
        output = tmp_path / "out.h"
        generate([self._module()], self._metadata(), output)
        content = output.read_text()
        # The array field should render with a bracketed size.
        assert "char message[64];" in content
        # The non-array field should not.
        assert "uint32_t code;" in content


class TestUnionStructRendering:
    """A field carrying `union`/`fields` renders as an anonymous union/struct."""

    def _metadata(self):
        return {
            "schema_version": "0.2.0",
            "versions": ["1.0.0"],
            "suffixes": {"handles": "_ptr", "callbacks": "_cb", "aliases": "_t"},
            "primitives": [
                {"name": "char", "c_type": "char"},
                {"name": "u32", "c_type": "uint32_t"},
            ],
        }

    def _module(self):
        return {
            "module": "m",
            "handles": {},
            "callbacks": {},
            "aliases": {},
            "structs": {
                "duckdb_v2_string": {
                    "pointer_alias": False,
                    "fields": [
                        {
                            "name": "value",
                            "union": [
                                {
                                    "name": "pointer",
                                    "fields": [
                                        {"name": "length", "type": "u32"},
                                        {
                                            "name": "prefix",
                                            "type": "char",
                                            "array_size": 4,
                                        },
                                        {"name": "ptr", "type": "char", "pointer": 1},
                                    ],
                                },
                                {
                                    "name": "inlined",
                                    "fields": [
                                        {"name": "length", "type": "u32"},
                                        {
                                            "name": "inlined",
                                            "type": "char",
                                            "array_size": 12,
                                        },
                                    ],
                                },
                            ],
                        },
                    ],
                },
            },
            "enums": {},
            "constants": {},
            "functions": {},
        }

    def test_struct_description_attaches_to_definition(self, tmp_path):
        """The docstring belongs on the struct body, not the forward declaration."""
        module = self._module()
        module["structs"]["duckdb_v2_string"]["description"] = "An inlinable string."
        output = tmp_path / "out.h"
        generate([module], self._metadata(), output)
        content = output.read_text()
        assert "//! An inlinable string.\nstruct duckdb_v2_string {" in content
        assert (
            "//! An inlinable string.\ntypedef struct duckdb_v2_string" not in content
        )

    def test_union_struct_renders(self, tmp_path):
        output = tmp_path / "out.h"
        generate([self._module()], self._metadata(), output)
        content = output.read_text()
        # Anonymous union wrapping two anonymous member structs.
        assert "union {" in content
        assert "} value;" in content
        assert "} pointer;" in content
        assert "} inlined;" in content
        # Leaf fields inside the members resolve their types normally.
        assert "uint32_t length;" in content
        assert "char prefix[4];" in content
        assert "char* ptr;" in content
        assert "char inlined[12];" in content
        # The struct is forward-declared, then its body defines the named struct.
        assert "typedef struct duckdb_v2_string duckdb_v2_string;" in content
        assert "struct duckdb_v2_string {" in content

    def test_union_struct_is_deterministic(self, tmp_path):
        out1 = tmp_path / "a.h"
        out2 = tmp_path / "b.h"
        generate([self._module()], self._metadata(), out1)
        generate([self._module()], self._metadata(), out2)
        assert out1.read_text() == out2.read_text()

    def test_union_member_description_renders(self, tmp_path):
        module = self._module()
        members = module["structs"]["duckdb_v2_string"]["fields"][0]["union"]
        members[0]["description"] = "out-of-line form"
        output = tmp_path / "out.h"
        generate([module], self._metadata(), output)
        content = output.read_text()
        assert "//! out-of-line form" in content


class TestPointerAliasStruct:
    """The struct tag and the pointer typedef are distinct names, so the
    forward declaration is valid C++ (a typedef may not redeclare a class
    name as a different type)."""

    def _metadata(self):
        return {
            "schema_version": "0.6",
            "versions": ["v1.0.0"],
            "prefix": "duckdb_v2_",
            "suffixes": {"handles": "_ptr", "callbacks": "_cb", "aliases": "_t"},
            "primitives": [{"name": "i32", "c_type": "int32_t"}],
        }

    def _module(self):
        return {
            "module": "m",
            "structs": {
                "box": {
                    "pointer_alias": True,
                    "fields": [
                        {"name": "val", "type": "i32", "pointer": 0, "const": False}
                    ],
                },
            },
        }

    def test_tag_and_typedef_are_distinct(self, tmp_path):
        output = tmp_path / "out.h"
        generate([self._module()], self._metadata(), output)
        content = output.read_text()
        assert "typedef struct duckdb_v2_box *duckdb_v2_box_t;" in content
        assert "struct duckdb_v2_box {" in content
        # Never the C++-invalid self-redeclaring form.
        assert "typedef struct duckdb_v2_box_t" not in content

    @pytest.mark.skipif(shutil.which("cc") is None, reason="no C compiler available")
    @pytest.mark.parametrize("lang", ["c", "c++"])
    def test_compiles_in_both_languages(self, tmp_path, lang):
        output = tmp_path / "out.h"
        generate([self._module()], self._metadata(), output)
        probe = tmp_path / ("probe.c" if lang == "c" else "probe.cpp")
        probe.write_text('#include "out.h"\nint main(void) { return 0; }\n')
        result = subprocess.run(
            ["cc", "-fsyntax-only", f"-x{lang}", "-I", str(tmp_path), str(probe)],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, result.stderr


class TestDescriptionRendering:
    """Descriptions render as prefixed comment lines, one per paragraph."""

    def _metadata(self):
        return {
            "schema_version": "0.2.0",
            "versions": ["1.0.0"],
            "prefix": "duckdb_v2_",
            "suffixes": {"handles": "_ptr", "callbacks": "_cb", "aliases": "_t"},
            "primitives": [
                {"name": "opaque", "c_type": "void"},
                {"name": "i32", "c_type": "int32_t"},
            ],
        }

    def _module(
        self, handle_description="A connection\nto a database.", **func_overrides
    ):
        func = {
            "return_type": "i32",
            "return_pointer": 0,
            "return_const": False,
            "parameters": {},
        }
        func.update(func_overrides)
        return {
            "module": "m",
            "handles": {"conn": {"description": handle_description}},
            "callbacks": {},
            "aliases": {},
            "structs": {},
            "enums": {},
            "constants": {},
            "functions": {"ping": func},
        }

    def test_hard_wrapped_description_becomes_one_line_comment(self, tmp_path):
        output = tmp_path / "out.h"
        generate([self._module()], self._metadata(), output)
        assert "//! A connection to a database.\n" in output.read_text()

    def test_multi_paragraph_description_becomes_a_block(self, tmp_path):
        output = tmp_path / "out.h"
        generate(
            [self._module("A connection.\n\nDestroy it.")], self._metadata(), output
        )
        assert "/*!\n * A connection.\n *\n * Destroy it.\n */\n" in output.read_text()

    def test_a_documented_entry_is_separated_from_the_previous_one(self, tmp_path):
        """Same rule everywhere: a doc comment never butts the entry above it."""
        module = self._module()
        module["constants"] = {
            "FIRST": {"value": 1, "description": "The first."},
            "SECOND": {"value": 2, "description": "The second."},
        }
        module["enums"] = {
            "MODE": {
                "values": {
                    "MODE_A": {"value": 0, "description": "Mode a."},
                    "MODE_B": {"value": 1, "description": "Mode b."},
                }
            }
        }
        output = tmp_path / "out.h"
        generate([module], self._metadata(), output)
        content = output.read_text()
        assert "#define DUCKDB_V2_FIRST 1\n\n//! The second." in content
        assert "DUCKDB_V2_MODE_A = 0,\n\n  //! Mode b." in content
        # Inside a braced body the first entry still follows the opener directly.
        assert "typedef enum DUCKDB_V2_MODE {\n  //! Mode a." in content

    def test_every_doc_comment_line_carries_a_prefix(self, tmp_path):
        """A C formatter can only reflow a comment whose lines are all prefixed."""
        output = tmp_path / "out.h"
        generate(
            [
                self._module(
                    description="Long prose\nwrapped in the spec.",
                    parameters={
                        "x": {
                            "type": "i32",
                            "indirection": 0,
                            "const": False,
                            "description": "A parameter\nwith a wrapped description.",
                        }
                    },
                )
            ],
            self._metadata(),
            output,
        )
        block = output.read_text().split("/*!")[-1].split("*/")[0]
        assert [
            line
            for line in block.splitlines()
            if line.strip() and not line.startswith(" *")
        ] == []
        assert " * Long prose wrapped in the spec." in block
        assert " * @param x A parameter with a wrapped description." in block


class TestMacroOptions:
    """The C adapter's macro names and banner come from its options file."""

    def _metadata(self):
        return {
            "schema_version": "0.6",
            "versions": ["v1.0.0"],
            "prefix": "duckdb_v2_",
            "suffixes": {"handles": "_ptr", "callbacks": "_cb", "aliases": "_t"},
            "primitives": [
                {"name": "opaque", "c_type": "void"},
                {"name": "i32", "c_type": "int32_t"},
            ],
        }

    def _module(self):
        return {
            "module": "m",
            "functions": {
                "ping": {
                    "return_type": "i32",
                    "return_pointer": 0,
                    "return_const": False,
                    "parameters": {},
                },
            },
        }

    def test_defaults_derived_from_prefix(self, tmp_path):
        output = tmp_path / "out.h"
        generate([self._module()], self._metadata(), output)
        content = output.read_text()
        assert "#ifndef DUCKDB_V2_C_API" in content
        assert "#ifndef DUCKDB_V2_EXTENSION_API" in content
        assert "#define DUCKDB_V2_DEPRECATED" in content

    def test_explicit_macros_honored(self, tmp_path):
        output = tmp_path / "out.h"
        generate(
            [self._module()],
            self._metadata(),
            output,
            options={
                "export_macro": "MY_API",
                "deprecated_macro": "MY_DEPRECATED",
                "banner": "// custom banner",
            },
        )
        content = output.read_text()
        assert "MY_API" in content
        assert "#define MY_DEPRECATED" in content
        assert "// custom banner" in content
        assert "DUCKDB_C_API" not in content

    def test_zero_param_function_renders_void(self, tmp_path):
        output = tmp_path / "out.h"
        generate([self._module()], self._metadata(), output)
        content = output.read_text()
        assert "duckdb_v2_ping(void);" in content


UNSTABLE = [["unstable", "v1.0.0", "2026-01-01"]]


def _dep_gate(major: int, minor: int, patch: int) -> str:
    """The opt-out directive for something deprecated in the given version."""
    return (
        "#if !defined(DUCKDB_V2_API_NO_DEPRECATED) || "
        f"DUCKDB_V2_API_VERSION_BELOW({major}, {minor}, {patch})"
    )


class TestUnstableGating:
    """A construct whose current status is unstable renders behind an opt-in #ifdef."""

    def _metadata(self, **options):
        meta = {
            "schema_version": "0.6",
            "versions": ["1.0.0"],
            "prefix": "duckdb_v2_",
            "lifecycle_states": {
                "unstable": {"visibility": "opt_in", "guard": "DUCKDB_V2_API_UNSTABLE"},
                "stable": {"visibility": "always"},
                "deprecated": {
                    "visibility": "opt_out",
                    "guard": "DUCKDB_V2_API_NO_DEPRECATED",
                },
                "removed": {"visibility": "never"},
            },
            "suffixes": {"handles": "_ptr", "callbacks": "_cb", "aliases": "_t"},
            "primitives": [
                {"name": "opaque", "c_type": "void"},
                {"name": "i32", "c_type": "int32_t"},
                {"name": "u32", "c_type": "uint32_t"},
            ],
        }
        if options:
            meta["options"] = options
        return meta

    def _module(self, **overrides):
        mod = {
            "module": "m",
            "handles": {},
            "callbacks": {},
            "aliases": {},
            "structs": {},
            "enums": {},
            "constants": {},
            "functions": {},
        }
        mod.update(overrides)
        return mod

    def _generate(self, module, metadata, tmp_path, options=None):
        output = tmp_path / "out.h"
        generate([module], metadata, output, options=options)
        return output.read_text()

    def test_unstable_handle_is_not_guarded(self, tmp_path):
        """Only functions gate; the type keeps its history comment and no #if."""
        module = self._module(handles={"scratch": {"lifecycle": UNSTABLE}})
        content = self._generate(module, self._metadata(), tmp_path)
        assert (
            "/*!\n"
            " * history:\n"
            " * - unstable: v1.0.0\n"
            " */\n"
            "typedef void* duckdb_v2_scratch_ptr;" in content
        )
        assert "#if DUCKDB_V2_API_ALLOW_UNSTABLE" not in content

    def test_stable_handle_is_not_guarded(self, tmp_path):
        module = self._module(handles={"ctx": {}})
        content = self._generate(module, self._metadata(), tmp_path)
        assert "#if DUCKDB_V2_API_ALLOW_UNSTABLE" not in content

    def test_guard_wraps_the_doc_comment(self, tmp_path):
        module = self._module(
            functions={
                "poke": {
                    "description": "Experimental.",
                    "return_type": "i32",
                    "return_pointer": 0,
                    "return_const": False,
                    "parameters": {},
                    "lifecycle": UNSTABLE,
                }
            }
        )
        content = self._generate(module, self._metadata(), tmp_path)
        assert (
            "#if DUCKDB_V2_API_ALLOW_UNSTABLE\n"
            "/*!\n"
            " * Experimental.\n"
            " *\n"
            " * history:\n"
            " * - unstable: v1.0.0\n"
            " *\n"
            " * @return int32_t\n"
            " */\n"
            "DUCKDB_V2_C_API int32_t duckdb_v2_poke(void);\n"
            "#endif" in content
        )

    def test_unstable_alias_is_not_guarded(self, tmp_path):
        module = self._module(
            aliases={"count": {"underlying": "u32", "lifecycle": UNSTABLE}}
        )
        content = self._generate(module, self._metadata(), tmp_path)
        assert (
            "/*!\n"
            " * history:\n"
            " * - unstable: v1.0.0\n"
            " */\n"
            "typedef uint32_t duckdb_v2_count_t;" in content
        )
        assert "#if DUCKDB_V2_API_ALLOW_UNSTABLE" not in content

    def test_unstable_enum_is_not_guarded(self, tmp_path):
        module = self._module(
            enums={"MODE": {"values": {"MODE_A": {"value": 0}}, "lifecycle": UNSTABLE}}
        )
        content = self._generate(module, self._metadata(), tmp_path)
        assert (
            "/*!\n * history:\n * - unstable: v1.0.0\n */\ntypedef enum DUCKDB_V2_MODE {"
            in content
        )
        assert "#if DUCKDB_V2_API_ALLOW_UNSTABLE" not in content

    def test_unstable_callback_is_not_guarded(self, tmp_path):
        module = self._module(
            callbacks={
                "notify": {
                    "return_type": "opaque",
                    "return_pointer": 0,
                    "return_const": False,
                    "parameters": {},
                    "lifecycle": UNSTABLE,
                }
            }
        )
        content = self._generate(module, self._metadata(), tmp_path)
        assert (
            "/*!\n"
            " * history:\n"
            " * - unstable: v1.0.0\n"
            " */\n"
            "typedef void (*duckdb_v2_notify_cb)(void);" in content
        )
        assert "#if DUCKDB_V2_API_ALLOW_UNSTABLE" not in content

    def test_unstable_struct_guards_neither_declaration_nor_body(self, tmp_path):
        module = self._module(
            structs={
                "point": {
                    "fields": [
                        {"name": "x", "type": "i32", "pointer": 0, "const": False}
                    ],
                    "lifecycle": UNSTABLE,
                }
            }
        )
        content = self._generate(module, self._metadata(), tmp_path)
        assert "typedef struct duckdb_v2_point duckdb_v2_point;" in content
        assert (
            "/*!\n * history:\n * - unstable: v1.0.0\n */\nstruct duckdb_v2_point {"
            in content
        )
        assert "#if DUCKDB_V2_API_ALLOW_UNSTABLE" not in content

    def test_unstable_function_is_guarded(self, tmp_path):
        module = self._module(
            functions={
                "poke": {
                    "return_type": "i32",
                    "return_pointer": 0,
                    "return_const": False,
                    "parameters": {},
                    "lifecycle": UNSTABLE,
                }
            }
        )
        content = self._generate(module, self._metadata(), tmp_path)
        assert "#if DUCKDB_V2_API_ALLOW_UNSTABLE" in content
        declaration = content.split("#if DUCKDB_V2_API_ALLOW_UNSTABLE", 1)[1]
        declaration = declaration.split("#endif", 1)[0]
        assert "duckdb_v2_poke(void);" in declaration

    def test_guard_token_from_declared_states(self, tmp_path):
        """A declared states block supplies the guard token, and stays opt-in."""
        meta = self._metadata()
        meta["lifecycle_states"] = {
            "unstable": {"visibility": "opt_in", "guard": "MY_UNSTABLE"}
        }
        module = self._module(
            functions={
                "poke": {
                    "return_type": "i32",
                    "return_pointer": 0,
                    "return_const": False,
                    "parameters": {},
                    "lifecycle": UNSTABLE,
                }
            }
        )
        content = self._generate(module, meta, tmp_path)
        assert "#if DUCKDB_V2_API_ALLOW_UNSTABLE" in content
        # the declared token still seeds the switch's default
        assert "#ifdef MY_UNSTABLE\n#define DUCKDB_V2_API_ALLOW_UNSTABLE 1" in content

    def test_removed_handle_is_not_declared_but_is_recorded(self, tmp_path):
        status = [["removed", "v1.0.0", "2026-01-01"]]
        module = self._module(handles={"gone": {"lifecycle": status}})
        content = self._generate(module, self._metadata(), tmp_path)
        assert "typedef void* duckdb_v2_gone_ptr;" not in content
        assert "REMOVED IN v1.0.0" in content
        assert "duckdb_v2_gone_ptr" in content  # named only inside the tombstone

    def test_removed_function_is_not_declared_but_is_recorded(self, tmp_path):
        status = [["removed", "v1.0.0", "2026-01-01"]]
        module = self._module(
            functions={
                "old_open": {
                    "return_type": "i32",
                    "return_pointer": 0,
                    "return_const": False,
                    "parameters": {},
                    "lifecycle": status,
                }
            }
        )
        content = self._generate(module, self._metadata(), tmp_path)
        assert "duckdb_v2_old_open(" not in content
        assert "REMOVED IN v1.0.0" in content

    def test_deprecated_handle_gets_no_guard(self, tmp_path):
        """Even an opt_out type renders plainly: only functions gate."""
        status = [["deprecated", "v1.1.0", "2026-06-01"]]
        module = self._module(handles={"legacy": {"lifecycle": status}})
        content = self._generate(module, self._metadata(), tmp_path)
        assert (
            "/*!\n"
            " * history:\n"
            " * - deprecated: v1.1.0\n"
            " */\n"
            "typedef void* duckdb_v2_legacy_ptr;" in content
        )
        assert "DUCKDB_V2_API_ALLOW_DEPRECATED\n" not in content

    def _deprecated_module(self):
        func = {
            "return_type": "i32",
            "return_pointer": 0,
            "return_const": False,
            "parameters": {},
            "lifecycle": [["deprecated", "v1.0.0", "2026-01-01"]],
        }
        return self._module(functions={"old_poke": func})

    def test_deprecated_function_gated_and_emitted(self, tmp_path):
        """One gate, and the declaration is always emitted."""
        module = self._deprecated_module()
        content = self._generate(module, self._metadata(), tmp_path)
        assert (
            content.count("#if DUCKDB_V2_API_ALLOW_DEPRECATED") == 1
            and "duckdb_v2_old_poke(void);" in content
        )
        # No attribute on the declaration by default; the preamble #define stays.
        assert "DUCKDB_V2_C_API DUCKDB_V2_DEPRECATED" not in content

    def test_emit_deprecated_attribute_adds_macro_inside_gate(self, tmp_path):
        module = self._deprecated_module()
        content = self._generate(
            module,
            self._metadata(),
            tmp_path,
            options={"emit_deprecated_attribute": True},
        )
        gated = content.split("#if DUCKDB_V2_API_ALLOW_DEPRECATED", 1)[1]
        gated = gated.split("#endif", 1)[0]
        assert "DUCKDB_V2_DEPRECATED" in gated

    def test_anchor_resolved_in_header(self, tmp_path):
        module = self._module(
            handles={"conn": {"description": "Close with [[go]]."}},
            functions={
                "go": {
                    "description": "Closes a [[conn]].",
                    "return_type": "i32",
                    "return_pointer": 0,
                    "return_const": False,
                    "parameters": {},
                }
            },
        )
        content = self._generate(module, self._metadata(), tmp_path)
        assert "Close with duckdb_v2_go()." in content
        assert "Closes a duckdb_v2_conn_ptr." in content

    def test_comment_form_chosen_after_anchor_rewrite(self, tmp_path):
        """The resolved name decides line length, not the anchor spelling."""
        desc = "See [[a_rather_long_handle_name]]."
        module = self._module(
            handles={
                "a_rather_long_handle_name": {},
                "conn": {"description": desc},
            },
        )
        width = len("//! ") + len(desc)  # fits as spelled, not once resolved
        content = self._generate(
            module, self._metadata(), tmp_path, options={"comment_width": width}
        )
        assert "/*!\n * See duckdb_v2_a_rather_long_handle_name_ptr.\n */" in content

    def test_enum_max_sentinel_disabled_by_option(self, tmp_path):
        module = self._module(enums={"MODE": {"values": {"MODE_A": {"value": 0}}}})
        content = self._generate(
            module, self._metadata(), tmp_path, options={"emit_enum_max_member": False}
        )
        assert "MAX_ENUM" not in content

    def test_enum_max_sentinel_rendered(self, tmp_path):
        module = self._module(enums={"MODE": {"values": {"MODE_A": {"value": 0}}}})
        content = self._generate(module, self._metadata(), tmp_path)
        assert "DUCKDB_V2_MODE_MAX_ENUM = 0x7FFFFFFF,\n} DUCKDB_V2_MODE;" in content

    def test_unstable_qualified_alias_keeps_only_its_typedef_guard(self, tmp_path):
        """The typedef include-guard stays; no lifecycle guard wraps it."""
        module = self._module(
            aliases={
                "idx_t": {"underlying": "u32", "qualified": True, "lifecycle": UNSTABLE}
            }
        )
        content = self._generate(module, self._metadata(), tmp_path)
        assert (
            "/*!\n"
            " * history:\n"
            " * - unstable: v1.0.0\n"
            " */\n"
            "#ifndef DUCKDB_V2_TYPEDEF_IDX_T\n"
            "#define DUCKDB_V2_TYPEDEF_IDX_T\n"
            "typedef uint32_t idx_t;\n"
            "#endif" in content
        )
        assert "#if DUCKDB_V2_API_ALLOW_UNSTABLE" not in content

    def test_unstable_tagged_struct_handle_is_not_guarded(self, tmp_path):
        module = self._module(handles={"scratch": {"lifecycle": UNSTABLE}})
        content = self._generate(
            module,
            self._metadata(),
            tmp_path,
            options={"handles": {"default_style": "tagged_struct"}},
        )
        assert (
            "/*!\n * history:\n * - unstable: v1.0.0\n */\ntypedef struct _duckdb_v2_scratch {"
            in content
        )
        assert "#if DUCKDB_V2_API_ALLOW_UNSTABLE" not in content


class TestRenames:
    """A renamed construct keeps its old spelling for targets that still had it."""

    def _meta(self):
        return {
            "schema_version": "0.6",
            "versions": ["v1.0.0", "v1.4.0"],
            "prefix": "duckdb_v2_",
            "lifecycle_states": {"stable": {"visibility": "always"}},
            "suffixes": {"handles": "_ptr", "callbacks": "_cb", "aliases": "_t"},
            "primitives": [{"name": "i32", "c_type": "int32_t"}],
        }

    def _mod(self):
        return {
            "module": "m",
            "handles": {
                "bignum": {
                    "lifecycle": [["stable", "v1.0.0", "2025-01-01"]],
                    "renamed_from": {"name": "varint", "version": "v1.4.0"},
                }
            },
            "callbacks": {},
            "aliases": {},
            "structs": {},
            "enums": {},
            "constants": {},
            "functions": {
                "get_bignum": {
                    "return_type": "i32",
                    "return_pointer": 0,
                    "return_const": False,
                    "parameters": {},
                    "lifecycle": [["stable", "v1.0.0", "2025-01-01"]],
                    "renamed_from": {"name": "get_varint", "version": "v1.4.0"},
                }
            },
        }

    def _gen(self, tmp_path):
        out = tmp_path / "out.h"
        generate([self._mod()], self._meta(), out)
        return out.read_text()

    def test_function_alias_is_a_macro_below_the_rename(self, tmp_path):
        content = self._gen(tmp_path)
        assert (
            "#if DUCKDB_V2_API_VERSION_BELOW(1, 4, 0)\n"
            "//! Renamed to duckdb_v2_get_bignum in v1.4.0.\n"
            "#define duckdb_v2_get_varint duckdb_v2_get_bignum\n"
            "#endif" in content
        )

    def test_type_alias_is_a_typedef(self, tmp_path):
        content = self._gen(tmp_path)
        assert "typedef duckdb_v2_bignum_ptr duckdb_v2_varint_ptr;" in content

    def test_no_section_without_renames(self, tmp_path):
        mod = self._mod()
        del mod["handles"]["bignum"]["renamed_from"]
        del mod["functions"]["get_bignum"]["renamed_from"]
        out = tmp_path / "out.h"
        generate([mod], self._meta(), out)
        assert "Renamed constructs" not in out.read_text()


class TestRenameValidation:
    def _modules(self, old_name="varint", version="v1.4.0", extra=None):
        mod = {
            "module": "m",
            "handles": {
                "bignum": {
                    "lifecycle": [["stable", "v1.0.0", "2025-01-01"]],
                    "renamed_from": {"name": old_name, "version": version},
                }
            },
            "callbacks": {},
            "aliases": {},
            "structs": {},
            "enums": {},
            "constants": {},
            "functions": {},
        }
        if extra:
            mod["handles"].update(extra)
        return [mod]

    def _meta(self):
        return {
            "schema_version": "0.6",
            "versions": ["v1.0.0", "v1.4.0"],
            "prefix": "",
            "lifecycle_states": {"stable": {"visibility": "always"}},
            "suffixes": {"handles": "", "callbacks": "", "aliases": ""},
            "primitives": [{"name": "i32", "c_type": "int32_t"}],
        }

    def test_valid_rename_accepted(self):
        assert validate_semantics(self._modules(), self._meta()) == []

    def test_unknown_version_rejected(self):
        errors = validate_semantics(self._modules(version="v9.9.9"), self._meta())
        assert any("renamed_from names unknown version" in e for e in errors)

    def test_old_name_colliding_with_a_live_construct_rejected(self):
        """Reviving a name that still means something else would be ambiguous."""
        live = {"varint": {"lifecycle": [["stable", "v1.0.0", "2025-01-01"]]}}
        errors = validate_semantics(self._modules(extra=live), self._meta())
        assert any("is also a live construct" in e for e in errors)


class TestVersionGating:
    """Constructs gate on the version a translation unit targets, not only on state."""

    def _meta(self, **extra):
        meta = {
            "schema_version": "0.6",
            "versions": ["v1.2.0", "v1.5.6"],
            "prefix": "duckdb_v2_",
            "lifecycle_states": {
                "unstable": {"visibility": "opt_in", "guard": "DUCKDB_V2_API_UNSTABLE"},
                "stable": {"visibility": "always"},
                "deprecated": {
                    "visibility": "opt_out",
                    "guard": "DUCKDB_V2_API_NO_DEPRECATED",
                },
            },
            "suffixes": {"handles": "_ptr", "callbacks": "_cb", "aliases": "_t"},
            "primitives": [{"name": "i32", "c_type": "int32_t"}],
        }
        meta.update(extra)
        return meta

    def _mod(self, lifecycle):
        # Only functions gate, so the carrier has to be one.
        return {
            "module": "m",
            "handles": {},
            "callbacks": {},
            "aliases": {},
            "structs": {},
            "enums": {},
            "constants": {},
            "functions": {
                "thing": {
                    "return_type": "i32",
                    "return_pointer": 0,
                    "return_const": False,
                    "parameters": {},
                    "lifecycle": lifecycle,
                }
            },
        }

    def _gen(self, meta, module, tmp_path):
        out = tmp_path / "out.h"
        generate([module], meta, out)
        return out.read_text()

    def test_target_defaults_to_the_latest_declared_version(self, tmp_path):
        content = self._gen(
            self._meta(), self._mod([["stable", "v1.2.0", "2025-01-01"]]), tmp_path
        )
        assert "#define DUCKDB_V2_API_VERSION_MAJOR 1" in content
        assert "#define DUCKDB_V2_API_VERSION_MINOR 5" in content
        assert "#define DUCKDB_V2_API_VERSION_PATCH 6" in content

    def test_all_or_none_guard_is_emitted(self, tmp_path):
        content = self._gen(
            self._meta(), self._mod([["stable", "v1.2.0", "2025-01-01"]]), tmp_path
        )
        assert "#error" in content and "all or none" in content

    def test_comparison_macros_are_emitted(self, tmp_path):
        content = self._gen(
            self._meta(), self._mod([["stable", "v1.2.0", "2025-01-01"]]), tmp_path
        )
        assert "#define DUCKDB_V2_API_VERSION_AT_LEAST(x, y, z)" in content
        assert "#define DUCKDB_V2_API_VERSION_BELOW(x, y, z)" in content

    def test_deprecation_is_relative_to_the_target(self, tmp_path):
        """Deprecated after the target means not yet deprecated, so opt-out must not hide it."""
        content = self._gen(
            self._meta(),
            self._mod(
                [
                    ["deprecated", "v1.5.6", "2026-07-30"],
                    ["stable", "v1.2.0", "2025-01-01"],
                ]
            ),
            tmp_path,
        )
        assert (
            "#if (DUCKDB_V2_API_VERSION_BELOW(1, 5, 6) || "
            "DUCKDB_V2_API_ALLOW_DEPRECATED)" in content
        )

    def test_stable_construct_is_ungated(self, tmp_path):
        content = self._gen(
            self._meta(), self._mod([["stable", "v1.2.0", "2025-01-01"]]), tmp_path
        )
        body = content.split("General type definitions")[1]
        assert "duckdb_v2_thing(void);" in body
        assert "DUCKDB_V2_API_NO_DEPRECATED" not in body

    def test_unstable_still_gates_on_the_guard_alone(self, tmp_path):
        content = self._gen(
            self._meta(), self._mod([["unstable", "v1.2.0", "2025-01-01"]]), tmp_path
        )
        assert "#if DUCKDB_V2_API_ALLOW_UNSTABLE" in content

    def test_version_macro_name_is_spec_level(self, tmp_path):
        """metadata.version_macro renames the macros and every gate that uses them."""
        meta = self._meta(version_macro="MY_VER")
        content = self._gen(
            meta,
            self._mod(
                [
                    ["deprecated", "v1.5.6", "2026-07-30"],
                    ["stable", "v1.2.0", "2025-01-01"],
                ]
            ),
            tmp_path,
        )
        assert "#define MY_VER_AT_LEAST(x, y, z)" in content
        assert "MY_VER_BELOW(1, 5, 6)" in content
        assert "DUCKDB_V2_API_VERSION_AT_LEAST" not in content


class TestSchemaVersion:
    def test_missing_schema_version(self, tmp_path):
        """metadata.yaml without schema_version is rejected by JSON Schema validation."""
        spec = tmp_path / "spec"
        spec.mkdir()
        (spec / "metadata.yaml").write_text(
            "version: ['1.0.0']\nprimitives: [opaque]\n"
        )
        with pytest.raises(jsonschema.ValidationError, match="schema_version"):
            load_metadata(spec)

    def test_schema_version_present(self):
        """The bundled test spec has a schema_version field."""
        metadata = load_metadata(TESTSPEC_DIR)
        assert "schema_version" in metadata


HAS_CC = shutil.which("cc") is not None


@pytest.mark.skipif(not HAS_CC, reason="no C compiler available")
class TestCompile:
    """Verify the generated header is syntactically valid C."""

    def test_header_compiles_as_c(self, tmp_path):
        metadata = load_metadata(TESTSPEC_DIR)
        modules = load_modules(TESTSPEC_DIR)
        output = tmp_path / "duckdb_v2.h"
        generate(modules, metadata, output)

        test_c = tmp_path / "test.c"
        test_c.write_text('#include "duckdb_v2.h"\nint main(void) { return 0; }\n')

        result = subprocess.run(
            ["cc", "-fsyntax-only", "-xc", "-I", str(tmp_path), str(test_c)],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, f"Header failed to compile:\n{result.stderr}"

    def test_unstable_api_requires_optin(self, tmp_path):
        """Unstable declarations exist only when the consumer defines the guard."""
        metadata = load_metadata(TESTSPEC_DIR)
        modules = load_modules(TESTSPEC_DIR)
        output = tmp_path / "duckdb_v2.h"
        generate(modules, metadata, output)

        test_c = tmp_path / "test.c"
        test_c.write_text(
            '#include "duckdb_v2.h"\n'
            "int main(void) { return (int)duckdb_v2_scratch_create(0, 0); }\n"
        )

        without = subprocess.run(
            ["cc", "-fsyntax-only", "-xc", "-I", str(tmp_path), str(test_c)],
            capture_output=True,
            text=True,
        )
        assert without.returncode != 0, "unstable function visible without opt-in"

        with_optin = subprocess.run(
            [
                "cc",
                "-fsyntax-only",
                "-xc",
                "-DDUCKDB_V2_API_UNSTABLE",
                "-I",
                str(tmp_path),
                str(test_c),
            ],
            capture_output=True,
            text=True,
        )
        assert with_optin.returncode == 0, (
            f"Header failed to compile with opt-in:\n{with_optin.stderr}"
        )

    def test_header_compiles_as_cpp(self, tmp_path):
        metadata = load_metadata(TESTSPEC_DIR)
        modules = load_modules(TESTSPEC_DIR)
        output = tmp_path / "duckdb_v2.h"
        generate(modules, metadata, output)

        test_cpp = tmp_path / "test.cpp"
        test_cpp.write_text('#include "duckdb_v2.h"\nint main() { return 0; }\n')

        result = subprocess.run(
            ["cc", "-fsyntax-only", "-xc++", "-I", str(tmp_path), str(test_cpp)],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, (
            f"Header failed to compile as C++:\n{result.stderr}"
        )

    def test_header_compiles_as_cpp_with_unstable_optin(self, tmp_path):
        """The guarded region must be valid C++ too, or every opted-in C++ consumer breaks."""
        metadata = load_metadata(TESTSPEC_DIR)
        modules = load_modules(TESTSPEC_DIR)
        output = tmp_path / "duckdb_v2.h"
        generate(modules, metadata, output)

        test_cpp = tmp_path / "test.cpp"
        test_cpp.write_text('#include "duckdb_v2.h"\nint main() { return 0; }\n')

        result = subprocess.run(
            [
                "cc",
                "-fsyntax-only",
                "-xc++",
                "-DDUCKDB_V2_API_UNSTABLE",
                "-I",
                str(tmp_path),
                str(test_cpp),
            ],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, (
            f"Guarded region failed to compile as C++:\n{result.stderr}"
        )
