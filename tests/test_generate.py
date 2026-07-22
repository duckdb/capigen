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
        assert "#ifdef DUCKDB_V2_API_UNSTABLE" in content

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
            "error_groups": {},
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
            "error_groups": {},
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
            "summary": "Pings the database.",
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
            "error_groups": {},
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
    """The C adapter's macro names and banner come from options.c."""

    def _metadata(self, **c_opts):
        meta = {
            "schema_version": "0.2.0",
            "versions": ["1.0.0"],
            "prefix": "duckdb_v2_",
            "suffixes": {"handles": "_ptr", "callbacks": "_cb", "aliases": "_t"},
            "primitives": [
                {"name": "opaque", "c_type": "void"},
                {"name": "i32", "c_type": "int32_t"},
            ],
        }
        if c_opts:
            meta["options"] = {"c": c_opts}
        return meta

    def _module(self):
        return {
            "module": "m",
            "handles": {},
            "callbacks": {},
            "aliases": {},
            "structs": {},
            "enums": {},
            "constants": {},
            "error_groups": {},
            "functions": {
                "ping": {
                    "summary": "Ping",
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
            self._metadata(
                api_macro="MY_API",
                deprecated_macro="MY_DEPRECATED",
                banner="// custom banner",
            ),
            output,
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


class TestUnstableGating:
    """A construct whose current status is unstable renders behind an opt-in #ifdef."""

    def _metadata(self, **options):
        meta = {
            "schema_version": "0.4",
            "versions": ["1.0.0"],
            "prefix": "duckdb_v2_",
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
            "error_groups": {},
            "functions": {},
        }
        mod.update(overrides)
        return mod

    def _generate(self, module, metadata, tmp_path):
        output = tmp_path / "out.h"
        generate([module], metadata, output)
        return output.read_text()

    def test_unstable_handle_is_guarded(self, tmp_path):
        module = self._module(handles={"scratch": {"status": UNSTABLE}})
        content = self._generate(module, self._metadata(), tmp_path)
        assert (
            "#ifdef DUCKDB_V2_API_UNSTABLE\n"
            "typedef void* duckdb_v2_scratch_ptr;\n"
            "#endif" in content
        )

    def test_stable_handle_is_not_guarded(self, tmp_path):
        module = self._module(handles={"ctx": {}})
        content = self._generate(module, self._metadata(), tmp_path)
        assert "#ifdef DUCKDB_V2_API_UNSTABLE" not in content

    def test_guard_wraps_the_doc_comment(self, tmp_path):
        module = self._module(
            handles={"scratch": {"description": "Experimental.", "status": UNSTABLE}}
        )
        content = self._generate(module, self._metadata(), tmp_path)
        assert (
            "#ifdef DUCKDB_V2_API_UNSTABLE\n"
            "//! Experimental.\n"
            "typedef void* duckdb_v2_scratch_ptr;\n"
            "#endif" in content
        )

    def test_unstable_alias_is_guarded(self, tmp_path):
        module = self._module(
            aliases={"count": {"underlying": "u32", "status": UNSTABLE}}
        )
        content = self._generate(module, self._metadata(), tmp_path)
        assert (
            "#ifdef DUCKDB_V2_API_UNSTABLE\n"
            "typedef uint32_t duckdb_v2_count_t;\n"
            "#endif" in content
        )

    def test_unstable_enum_is_guarded(self, tmp_path):
        module = self._module(
            enums={"MODE": {"values": {"MODE_A": {"value": 0}}, "status": UNSTABLE}}
        )
        content = self._generate(module, self._metadata(), tmp_path)
        assert "#ifdef DUCKDB_V2_API_UNSTABLE\ntypedef enum DUCKDB_V2_MODE {" in content
        assert "} DUCKDB_V2_MODE;\n#endif" in content

    def test_unstable_callback_is_guarded(self, tmp_path):
        module = self._module(
            callbacks={
                "notify": {
                    "return_type": "opaque",
                    "return_pointer": 0,
                    "return_const": False,
                    "parameters": {},
                    "status": UNSTABLE,
                }
            }
        )
        content = self._generate(module, self._metadata(), tmp_path)
        assert (
            "#ifdef DUCKDB_V2_API_UNSTABLE\n"
            "typedef void (*duckdb_v2_notify_cb)(void);\n"
            "#endif" in content
        )

    def test_unstable_struct_guards_forward_declaration_and_body(self, tmp_path):
        module = self._module(
            structs={
                "point": {
                    "fields": [
                        {"name": "x", "type": "i32", "pointer": 0, "const": False}
                    ],
                    "status": UNSTABLE,
                }
            }
        )
        content = self._generate(module, self._metadata(), tmp_path)
        assert (
            "#ifdef DUCKDB_V2_API_UNSTABLE\n"
            "typedef struct duckdb_v2_point duckdb_v2_point;\n"
            "#endif" in content
        )
        assert "#ifdef DUCKDB_V2_API_UNSTABLE\nstruct duckdb_v2_point {" in content
        assert "};\n#endif" in content

    def test_unstable_function_is_guarded(self, tmp_path):
        module = self._module(
            functions={
                "poke": {
                    "summary": "Pokes.",
                    "return_type": "i32",
                    "return_pointer": 0,
                    "return_const": False,
                    "parameters": {},
                    "status": UNSTABLE,
                }
            }
        )
        content = self._generate(module, self._metadata(), tmp_path)
        assert "#ifdef DUCKDB_V2_API_UNSTABLE" in content
        declaration = content.split("#ifdef DUCKDB_V2_API_UNSTABLE", 1)[1]
        declaration = declaration.split("#endif", 1)[0]
        assert "duckdb_v2_poke(void);" in declaration

    def test_guard_token_from_extension_options(self, tmp_path):
        """options.extension.unstable_guard is shared, and the gate stays opt-in."""
        module = self._module(handles={"scratch": {"status": UNSTABLE}})
        content = self._generate(
            module,
            self._metadata(extension={"unstable_guard": "SHARED_UNSTABLE"}),
            tmp_path,
        )
        assert (
            "#ifdef SHARED_UNSTABLE\n"
            "typedef void* duckdb_v2_scratch_ptr;\n"
            "#endif" in content
        )

    def test_guard_token_from_c_options_wins(self, tmp_path):
        module = self._module(handles={"scratch": {"status": UNSTABLE}})
        content = self._generate(
            module,
            self._metadata(
                c={"unstable_guard": "C_UNSTABLE"},
                extension={"unstable_guard": "SHARED_UNSTABLE"},
            ),
            tmp_path,
        )
        assert "#ifdef C_UNSTABLE" in content
        assert "SHARED_UNSTABLE" not in content

    def test_unstable_qualified_alias_nests_typedef_guard(self, tmp_path):
        """The qualified alias's typedef guard nests inside the unstable guard."""
        module = self._module(
            aliases={
                "idx_t": {"underlying": "u32", "qualified": True, "status": UNSTABLE}
            }
        )
        content = self._generate(module, self._metadata(), tmp_path)
        assert (
            "#ifdef DUCKDB_V2_API_UNSTABLE\n"
            "#ifndef DUCKDB_V2_TYPEDEF_IDX_T\n"
            "#define DUCKDB_V2_TYPEDEF_IDX_T\n"
            "typedef uint32_t idx_t;\n"
            "#endif\n"
            "#endif" in content
        )

    def test_unstable_tagged_struct_handle_is_guarded(self, tmp_path):
        module = self._module(handles={"scratch": {"status": UNSTABLE}})
        content = self._generate(
            module,
            self._metadata(c={"handles": {"default_style": "tagged_struct"}}),
            tmp_path,
        )
        assert (
            "#ifdef DUCKDB_V2_API_UNSTABLE\ntypedef struct _duckdb_v2_scratch {"
            in content
        )
        assert "} * duckdb_v2_scratch_ptr;\n#endif" in content

    def test_unstable_and_deprecated_guards_nest(self, tmp_path):
        """Unstable wraps outside; deprecated nests inside; closed in reverse."""
        module = self._module(
            functions={
                "old_poke": {
                    "summary": "Pokes.",
                    "return_type": "i32",
                    "return_pointer": 0,
                    "return_const": False,
                    "parameters": {},
                    "deprecated": "1.0.0",
                    "status": UNSTABLE,
                }
            }
        )
        content = self._generate(module, self._metadata(), tmp_path)
        assert (
            "#ifdef DUCKDB_V2_API_UNSTABLE\n#ifndef DUCKDB_V2_API_NO_DEPRECATED"
            in content
        )
        assert "duckdb_v2_old_poke(void);\n#endif\n#endif" in content


class TestSchemaVersion:
    def test_missing_schema_version(self, tmp_path):
        """metadata.yaml without schema_version is rejected by JSON Schema validation."""
        spec = tmp_path / "spec"
        spec.mkdir()
        (spec / "metadata.yaml").write_text(
            "versions: ['1.0.0']\nprimitives: [opaque]\n"
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
            "int main(void) { duckdb_v2_scratch_ptr s = 0; return !!s; }\n"
        )

        without = subprocess.run(
            ["cc", "-fsyntax-only", "-xc", "-I", str(tmp_path), str(test_c)],
            capture_output=True,
            text=True,
        )
        assert without.returncode != 0, "unstable type visible without opt-in"

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
