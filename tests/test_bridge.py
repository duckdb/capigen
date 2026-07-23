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
        "schema_version": "0.5",
        "versions": ["1.0.0"],
        "prefix": "duckdb_v2_",
        "lifecycle_states": {
            "unstable": {"visibility": "opt_in", "guard": "DUCKDB_V2_API_UNSTABLE"},
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
        ],
    }
    opts = {"stub_return": "DUCKDB_V2_ERROR_API"}
    opts.update(bridge_opts)
    meta["options"] = {"bridge": opts}
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
        "functions": {
            "ping": {
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


def test_missing_stub_return_errors_when_stubbing(tmp_path):
    """No universal error value exists; the expression must be configured."""
    meta = _metadata()
    del meta["options"]["bridge"]["stub_return"]
    with pytest.raises(ValueError, match="options.bridge.stub_return"):
        generate([_module()], meta, tmp_path / "stubs.cpp")


def test_missing_stub_return_ok_when_nothing_to_stub(tmp_path):
    scan_dir = tmp_path / "scan"
    scan_dir.mkdir()
    (scan_dir / "impl.cpp").write_text("int32_t duckdb_v2_ping(void) { return 0; }\n")
    meta = _metadata()
    del meta["options"]["bridge"]["stub_return"]
    output = tmp_path / "stubs.cpp"
    generate([_module()], meta, output, scan_dir=scan_dir)
    assert "// Not yet implemented" not in output.read_text()


def test_stub_return_override(tmp_path):
    output = tmp_path / "stubs.cpp"
    generate([_module()], _metadata(stub_return="MY_ERROR"), output)
    assert "return MY_ERROR;" in output.read_text()


def test_include_emitted_when_set(tmp_path):
    output = tmp_path / "stubs.cpp"
    generate([_module()], _metadata(include_header="my_internal.hpp"), output)
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
    generate([_module()], _metadata(include_header="my_internal.hpp"), output)
    text = output.read_text()
    assert (
        "#ifndef DUCKDB_V2_API_UNSTABLE\n#define DUCKDB_V2_API_UNSTABLE\n#endif" in text
    )
    assert text.index("#define DUCKDB_V2_API_UNSTABLE") < text.index(
        '#include "my_internal.hpp"'
    )


def test_every_opt_in_guard_defined(tmp_path):
    """Custom states with several opt-in guards: the stub file defines them all."""
    meta = _metadata()
    meta["lifecycle_states"] = {
        "unstable": {"visibility": "opt_in", "guard": "G_UNSTABLE"},
        "experimental": {"visibility": "opt_in", "guard": "G_EXPERIMENTAL"},
    }
    output = tmp_path / "stubs.cpp"
    generate([_module()], meta, output)
    text = output.read_text()
    assert "#define G_UNSTABLE" in text
    assert "#define G_EXPERIMENTAL" in text


def test_opt_out_guards_not_defined(tmp_path):
    """Defining an opt-out guard would strip deprecated declarations engine-side."""
    output = tmp_path / "stubs.cpp"
    generate([_module()], _metadata(), output)
    assert "DUCKDB_V2_API_NO_DEPRECATED" not in output.read_text()


def test_omitted_function_gets_no_stub(tmp_path):
    module = _module()
    module["functions"]["ping"]["lifecycle"] = [["removed", "v1.0.0", "2026-01-01"]]
    output = tmp_path / "stubs.cpp"
    generate([module], _metadata(), output)
    assert "duckdb_v2_ping" not in output.read_text()


@pytest.mark.skipif(shutil.which("cc") is None, reason="no C compiler available")
def test_stubs_compile_against_generated_header(tmp_path):
    """One generator run's artifacts are consistent: stubs see the guarded declarations."""
    metadata = load_metadata(TESTSPEC_DIR)
    modules = load_modules(TESTSPEC_DIR)
    metadata.setdefault("options", {})["bridge"] = {
        "include_header": "duckdb_v2.h",
        "stub_return": "DUCKDB_V2_API_ERROR",
    }

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
