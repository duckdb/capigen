"""Tests for the bridge adapter (C++ stub generation)."""

import shutil
import subprocess
from pathlib import Path

import pytest

from capigen.adapters.bridge import generate
from capigen.adapters.c import generate as generate_header
from capigen.loader import load_metadata, load_modules

TESTSPEC_DIR = Path(__file__).parent / "testspec" / "v2"


def _metadata(**bridge_opts):
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
    if bridge_opts:
        meta["options"] = {"bridge": bridge_opts}
    return meta


def _module():
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


def test_zero_param_stub_renders_void(tmp_path):
    output = tmp_path / "stubs.cpp"
    generate([_module()], _metadata(), output)
    assert "duckdb_v2_ping(void)" in output.read_text()


def test_stub_return_defaults_from_prefix(tmp_path):
    output = tmp_path / "stubs.cpp"
    generate([_module()], _metadata(), output)
    assert "return DUCKDB_V2_API_ERROR;" in output.read_text()


def test_stub_return_override(tmp_path):
    output = tmp_path / "stubs.cpp"
    generate([_module()], _metadata(stub_return="MY_ERROR"), output)
    assert "return MY_ERROR;" in output.read_text()


def test_include_emitted_when_set(tmp_path):
    output = tmp_path / "stubs.cpp"
    generate([_module()], _metadata(include="my_internal.hpp"), output)
    assert '#include "my_internal.hpp"' in output.read_text()


def test_include_absent_by_default(tmp_path):
    output = tmp_path / "stubs.cpp"
    generate([_module()], _metadata(), output)
    assert "#include" not in output.read_text()


def test_invocation_comment(tmp_path):
    output = tmp_path / "stubs.cpp"
    generate([_module()], _metadata(), output, invocation="capigen bridge -o x.cpp")
    assert "// Re-run: capigen bridge -o x.cpp" in output.read_text()


def test_scan_prefix_derived_from_metadata(tmp_path):
    scan_dir = tmp_path / "scan"
    scan_dir.mkdir()
    (scan_dir / "impl.cpp").write_text("int32_t duckdb_v2_ping(void) { return 0; }\n")
    output = tmp_path / "stubs.cpp"
    generate([_module()], _metadata(), output, scan_dir=scan_dir)
    # The already-implemented function is detected and no stub is emitted for it.
    assert "// Not yet implemented" not in output.read_text()


def test_unstable_guard_defined_before_include(tmp_path):
    """The stub file is engine-side, so it opts in to the full API surface itself."""
    output = tmp_path / "stubs.cpp"
    generate([_module()], _metadata(include="my_internal.hpp"), output)
    text = output.read_text()
    assert (
        "#ifndef DUCKDB_V2_API_UNSTABLE\n#define DUCKDB_V2_API_UNSTABLE\n#endif" in text
    )
    assert text.index("#define DUCKDB_V2_API_UNSTABLE") < text.index(
        '#include "my_internal.hpp"'
    )


@pytest.mark.skipif(shutil.which("cc") is None, reason="no C compiler available")
def test_stubs_compile_against_generated_header(tmp_path):
    """One generator run's artifacts are consistent: stubs see the guarded declarations."""
    metadata = load_metadata(TESTSPEC_DIR)
    modules = load_modules(TESTSPEC_DIR)
    metadata.setdefault("options", {})["bridge"] = {"include": "duckdb_v2.h"}

    generate_header(modules, metadata, tmp_path / "duckdb_v2.h")
    stubs = tmp_path / "stubs.cpp"
    generate(modules, metadata, stubs)

    result = subprocess.run(
        ["cc", "-fsyntax-only", "-xc++", "-I", str(tmp_path), str(stubs)],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, (
        f"Stubs failed to compile against the header:\n{result.stderr}"
    )
