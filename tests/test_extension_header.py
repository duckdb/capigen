"""Tests for the extension_header adapter (verify + append + derive)."""

import re
import shutil
import subprocess
from pathlib import Path

import pytest

from capigen.loader import load_metadata, load_modules
from capigen.validate import validate_semantics
from capigen.adapters.extension_header import generate

EXT_SPEC = Path(__file__).parent / "testspec" / "ext"
TEMPLATE = EXT_SPEC / "template.h.in"
EXT_OPTIONS = {
    "create_method": "CreateExtAPI",
    "version_macro_prefix": "EXT_API_VERSION",
    "internal_include": "ext.h",
    "exclude_functions": ["skipme"],
    "api_variable": "ext_api",
    "struct_typename": "ext_api",
}
HAS_CC = shutil.which("cc") is not None


def _load():
    return load_modules(EXT_SPEC), load_metadata(EXT_SPEC)


def _run(tmp_path, template_text=None):
    """Write a template, run generate against the ext fixture spec, return (consumer, internal)."""
    modules, metadata = _load()
    tmp_path.mkdir(parents=True, exist_ok=True)
    template = tmp_path / "template.h.in"
    template.write_text(
        template_text if template_text is not None else TEMPLATE.read_text()
    )
    consumer = tmp_path / "out.h"
    internal = tmp_path / "internal.hpp"
    generate(
        modules,
        metadata,
        consumer,
        template=template,
        internal_out=internal,
        options=EXT_OPTIONS,
    )
    return consumer.read_text(), internal.read_text()


def _fn(ret="i32", params=None, static_inline=False, lifecycle=None):
    """Build a minimal spec function dict. Every function must be dated."""
    return {
        "return_type": ret,
        "return_pointer": 0,
        "return_const": False,
        "static_inline": static_inline,
        "parameters": params or {},
        "lifecycle": lifecycle or [["stable", "v1.0.0", "2026-01-01"]],
    }


def _run_inline(tmp_path, functions, template_text, exclude=None):
    """Run generate against an inline single-module spec (full control over spec order)."""
    metadata = {
        "schema_version": "0.6",
        "prefix": "t_",
        "versions": ["v1.0.0"],
        "suffixes": {"handles": "", "callbacks": "", "aliases": ""},
        "primitives": [
            {"name": "void", "c_type": "void"},
            {"name": "i32", "c_type": "int32_t"},
        ],
        "lifecycle_states": {
            "unstable": {"visibility": "opt_in", "guard": "T_UNSTABLE"},
            "stable": {"visibility": "always"},
            "removed": {"visibility": "never"},
        },
    }
    options = {
        "create_method": "CreateT",
        "version_macro_prefix": "T_VERSION",
        "internal_include": "t.h",
        "exclude_functions": exclude or [],
        "api_variable": "t_api",
        "struct_typename": "t_api",
    }
    module = {
        "module": "m",
        "handles": {},
        "callbacks": {},
        "aliases": {},
        "structs": {},
        "enums": {},
        "constants": {},
        "functions": functions,
    }
    tmp_path.mkdir(parents=True, exist_ok=True)
    template = tmp_path / "t.in"
    template.write_text(template_text)
    consumer = tmp_path / "out.h"
    internal = tmp_path / "i.hpp"
    generate(
        [module],
        metadata,
        consumer,
        template=template,
        internal_out=internal,
        options=options,
    )
    return consumer.read_text(), internal.read_text()


# A minimal inline template: one stable member plus empty append markers.
def _inline_template(members=None, defines=None):
    """A skeleton. The struct body and the mappings are generated from the spec,
    so the arguments only document what the caller expects to appear."""
    return """#pragma once

typedef struct {
	// capigen:begin appended
	// capigen:end appended
} t_api;

#ifndef T_STATIC
// capigen:begin appended
// capigen:end appended
#endif // T_STATIC
"""


STRUCT_SAMPLE = """typedef struct {
#if V > 0 || (V == 0 && P >= 0) // v1.0.0
	int32_t (*a_open)(const char *p);
	void (*a_cb_setter)(void (*cb)(int32_t x, int32_t y), void *data);
	void (*a_noop)(void);
#endif
#if V > 1 || (V == 1 && P >= 0) // v1.1.0
	int32_t (*a_more)(int32_t x);
#endif
// group two
#ifdef GUARD
	// a stray comment inside the region
	int64_t (*a_wrapped)(int32_t first,
	                     int32_t second);
#endif
} sample_api_t;
"""


class TestAppend:
    def test_renders_in_both_regions(self, tmp_path):
        consumer, _ = _run(tmp_path)
        # The struct member is unconditional...
        assert "\tvoid (*ext_extra_one)(ext_db db);" in consumer
        # ...and the switch the C header uses gates the macro instead.
        assert (
            "#if EXT_API_ALLOW_UNSTABLE\n"
            "#define ext_extra_one ext_api.ext_extra_one\n"
            "#endif" in consumer
        )
        # Define region append.
        assert "#define ext_extra_one ext_api.ext_extra_one" in consumer
        assert "#define ext_extra_two ext_api.ext_extra_two" in consumer

    def test_struct_bands_are_contiguous_runs(self, tmp_path):
        """One gate per band, wrapping a run; the not-yet-stable tail comes last."""
        consumer, _ = _run(tmp_path)
        region = consumer[consumer.index("// capigen:begin appended") :]
        region = region[: region.index("// capigen:end appended")]
        # the floor band needs no gate at all
        assert region.index("ext_open") < region.index("#if")
        # exactly two gated regions: the v1.1.0 band and the unstable tail
        assert region.count("#if ") == 2 and region.count("#endif") == 2
        assert "#if EXT_API_VERSION_AT_LEAST(1, 1, 0)" in region
        assert region.index("EXT_API_VERSION_AT_LEAST") < region.index(
            "EXT_API_ALLOW_UNSTABLE"
        )

    def test_unstable_tail_is_last(self, tmp_path):
        _, internal = _run(tmp_path)
        struct = internal[
            internal.index("typedef struct") : internal.index("} ext_api;")
        ]
        names = re.findall(r"\(\*(\w+)\)", struct)
        assert names[-3:] == ["ext_flush", "ext_get_kind", "ext_extra_one"]

    def test_zero_param_append_renders_void(self, tmp_path):
        consumer, _ = _run(tmp_path)
        assert "int32_t (*ext_extra_two)(void);" in consumer

    def test_excluded_function_skipped(self, tmp_path):
        consumer, internal = _run(tmp_path)
        assert "ext_skipme" not in consumer
        assert "ext_skipme" not in internal

    def test_append_order_deterministic(self, tmp_path):
        c1, i1 = _run(tmp_path / "a")
        c2, i2 = _run(tmp_path / "b")
        assert c1 == c2
        assert i1 == i2

    def test_appended_members_at_end_of_engine_struct(self, tmp_path):
        _, internal = _run(tmp_path)
        struct = internal[
            internal.index("typedef struct") : internal.index("} ext_api;")
        ]
        names = re.findall(r"\(\*(\w+)\)", struct)
        assert names[-2:] == ["ext_get_kind", "ext_extra_one"]

    def test_appended_members_at_end_of_create_method(self, tmp_path):
        _, internal = _run(tmp_path)
        assigns = re.findall(r"result\.(\w+) =", internal)
        assert assigns[-2:] == ["ext_get_kind", "ext_extra_one"]


class TestEngineSide:
    def test_member_order_equals_template_plus_appends(self, tmp_path):
        _, internal = _run(tmp_path)
        struct = internal[
            internal.index("typedef struct") : internal.index("} ext_api;")
        ]
        names = re.findall(r"\(\*(\w+)\)", struct)
        assert names == [
            "ext_open",
            "ext_close",
            "ext_version",
            "ext_extra_two",
            "ext_flush",
            "ext_get_kind",
            "ext_extra_one",
        ]

    def test_every_member_assigned_in_create_method(self, tmp_path):
        _, internal = _run(tmp_path)
        struct = internal[
            internal.index("typedef struct") : internal.index("} ext_api;")
        ]
        members = re.findall(r"\(\*(\w+)\)", struct)
        assigns = set(re.findall(r"result\.(\w+) =", internal))
        assert set(members) == assigns

    def test_version_defines(self, tmp_path):
        _, internal = _run(tmp_path)
        assert "#define EXT_API_VERSION_MAJOR 1" in internal
        assert "#define EXT_API_VERSION_MINOR 1" in internal
        assert "#define EXT_API_VERSION_PATCH 0" in internal
        assert '#define EXT_API_VERSION_STRING "v1.1.0"' in internal

    def test_version_banner_present(self, tmp_path):
        _, internal = _run(tmp_path)
        assert "// v1.1.0" in internal

    def test_full_member_line_rendered(self, tmp_path):
        # A name-preserving signature mangle must be caught: assert the full line.
        _, internal = _run(tmp_path)
        assert "\tint32_t (*ext_open)(const char* path, ext_db* out_db);" in internal
        assert "\tconst char* (*ext_version)(void);" in internal

    def test_byte_stable_across_two_runs(self, tmp_path):
        _, i1 = _run(tmp_path / "a")
        _, i2 = _run(tmp_path / "b")
        assert i1 == i2

    def test_matches_checked_in_golden(self, tmp_path):
        # Byte-for-byte against committed expected output: a dropped blank line or a
        # mutated include in internal.hpp.j2 fails here, not just a name regex.
        consumer, internal = _run(tmp_path)
        assert consumer == (EXT_SPEC / "expected_consumer.h").read_text()
        assert internal == (EXT_SPEC / "expected_internal.hpp").read_text()


class TestEndToEnd:
    def test_rerun_is_byte_identical(self, tmp_path):
        c1, i1 = _run(tmp_path / "a")
        c2, i2 = _run(tmp_path / "b")
        assert c1 == c2
        assert i1 == i2

    def test_fixture_validates(self):
        modules, metadata = _load()
        assert validate_semantics(modules, metadata) == []


class TestStatesIntegration:
    """The appended-region guard comes from the declared unstable state."""

    def test_appended_region_uses_declared_guard(self, tmp_path):
        extra = _fn()
        extra["lifecycle"] = [["unstable", "v1.0.0", "2026-01-01"]]
        functions = {"base": _fn(), "extra": extra}
        template = _inline_template(["int32_t (*t_base)(void);"], ["t_base"])
        consumer, _ = _run_inline(tmp_path, functions, template)
        assert (
            "#if T_API_ALLOW_UNSTABLE\n#define t_extra t_api.t_extra\n#endif"
            in consumer
        )

    def test_omitted_function_keeps_a_slot_but_no_name(self, tmp_path):
        gone = _fn()
        gone["lifecycle"] = [["removed", "v1.0.0", "2026-01-01"]]
        functions = {"base": _fn(), "gone": gone, "extra": _fn()}
        template = _inline_template(["int32_t (*t_base)(void);"], ["t_base"])
        consumer, internal = _run_inline(tmp_path, functions, template)
        assert "int32_t (*t_gone)(void);" in consumer  # the slot survives
        assert "#define t_gone " not in consumer  # the name does not
        assert "result.t_gone = nullptr;" in internal
        assert "t_extra" in consumer

    def test_template_member_for_omitted_function_keeps_slot_as_nullptr(self, tmp_path):
        """A frozen ABI slot survives removal; its vanished symbol is not referenced."""
        gone = _fn()
        gone["lifecycle"] = [["removed", "v1.0.0", "2026-01-01"]]
        functions = {"base": _fn(), "gone": gone}
        template = _inline_template(
            ["int32_t (*t_base)(void);", "int32_t (*t_gone)(void);"],
            ["t_base", "t_gone"],
        )
        # Must not raise: the member still resolves against the spec.
        _, internal = _run_inline(tmp_path, functions, template)
        assert "int32_t (*t_gone)(void);" in internal  # the slot stays
        assert "result.t_gone = nullptr;" in internal  # the symbol does not
        assert "result.t_base = t_base;" in internal

    @pytest.mark.skipif(not HAS_CC, reason="no C compiler available")
    def test_internal_with_removed_member_compiles(self, tmp_path):
        """The engine header compiles although the removed symbol has no declaration."""
        gone = _fn()
        gone["lifecycle"] = [["removed", "v1.0.0", "2026-01-01"]]
        functions = {"base": _fn(), "gone": gone}
        template = _inline_template(
            ["int32_t (*t_base)(void);", "int32_t (*t_gone)(void);"],
            ["t_base", "t_gone"],
        )
        _run_inline(tmp_path, functions, template)
        # The prelude declares only the surviving function, like the real engine.
        (tmp_path / "t.h").write_text("#include <stdint.h>\nint32_t t_base(void);\n")
        probe = tmp_path / "probe.cpp"
        probe.write_text('#include "i.hpp"\n')
        result = subprocess.run(
            ["cc", "-fsyntax-only", "-xc++", "-I", str(tmp_path), str(probe)],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, result.stderr


class TestMissingArguments:
    def test_template_required(self, tmp_path):
        modules, metadata = _load()
        with pytest.raises(ValueError, match="--template"):
            generate(
                modules, metadata, tmp_path / "o.h", internal_out=tmp_path / "i.hpp"
            )

    def test_internal_out_required(self, tmp_path):
        modules, metadata = _load()
        with pytest.raises(ValueError, match="--internal-out"):
            generate(modules, metadata, tmp_path / "o.h", template=TEMPLATE)


class TestAppendOrder:
    """Appends are ordered by the spec's own facts, never by how its files are arranged."""

    def _struct_members(self, internal):
        struct = internal[internal.index("typedef struct") : internal.index("} t_api;")]
        return re.findall(r"\(\*(\w+)\)", struct)

    def test_undated_functions_append_by_name(self, tmp_path):
        """Spec order is [base, zeta, alpha]; with no dates, name decides.

        Reordering or resplitting the spec files must not move an ABI slot, so
        file arrangement is deliberately not part of the key.
        """
        functions = {"base": _fn(), "zeta": _fn(), "alpha": _fn()}
        template = _inline_template(["int32_t (*t_base)(void);"], ["t_base"])
        consumer, internal = _run_inline(tmp_path, functions, template)
        assert self._struct_members(internal) == ["t_alpha", "t_base", "t_zeta"]
        assert consumer.index("t_alpha") < consumer.index("t_zeta")

    def test_older_functions_append_first(self, tmp_path):
        """Introduction date outranks name, so a new function lands at the end."""
        early = _fn(lifecycle=[["stable", "v1.0.0", "2024-01-01"]])
        late = _fn(lifecycle=[["stable", "v1.0.0", "2026-01-01"]])
        base = _fn(lifecycle=[["stable", "v1.0.0", "2023-01-01"]])
        functions = {"base": base, "aaa_new": late, "zzz_old": early}
        template = _inline_template(["int32_t (*t_base)(void);"], ["t_base"])
        _, internal = _run_inline(tmp_path, functions, template)
        assert self._struct_members(internal) == ["t_base", "t_zzz_old", "t_aaa_new"]

    def test_offset_pins_a_member_ahead_of_the_rule(self, tmp_path):
        """An explicit offset reproduces an order laid down before the rule existed."""
        pinned = _fn()
        pinned["offset"] = 0
        functions = {"base": _fn(), "aaa": _fn(), "zzz": pinned}
        template = _inline_template(["int32_t (*t_base)(void);"], ["t_base"])
        _, internal = _run_inline(tmp_path, functions, template)
        assert self._struct_members(internal) == ["t_zzz", "t_aaa", "t_base"]


class TestRemovedKeepsItsSlot:
    """A removed function cannot vacate its slot, but must stop resolving."""

    def _spec(self):
        gone = _fn()
        gone["lifecycle"] = [["removed", "v1.0.0", "2026-01-01"]]
        return {"base": _fn(), "gone": gone}

    def _template(self):
        return _inline_template(
            ["int32_t (*t_base)(void);", "int32_t (*t_gone)(void);"],
            ["t_base", "t_gone"],
        )

    def test_slot_is_reserved_not_removed(self, tmp_path):
        consumer, internal = _run_inline(tmp_path, self._spec(), self._template())
        struct = internal[internal.index("typedef struct") : internal.index("} t_api;")]
        # the engine still has every slot, so the layout is unchanged
        assert re.findall(r"\(\*(\w+)\)", struct) == ["t_base", "t_gone"]
        # the consumer keeps the slot too, so nothing after it shifts
        assert "int32_t (*t_gone)(void);" in consumer

    def test_mapping_macro_is_dropped(self, tmp_path):
        consumer, _ = _run_inline(tmp_path, self._spec(), self._template())
        assert "#define t_gone " not in consumer
        assert "#define t_base " in consumer

    def test_engine_assigns_nullptr_to_the_slot(self, tmp_path):
        _, internal = _run_inline(tmp_path, self._spec(), self._template())
        assert "nullptr" in internal


class TestCompile:
    """Both generated fixture headers are syntactically valid."""

    PRELUDE = (
        "#include <stdint.h>\n"
        # duckdb.h supplies these; the fixture's stand-in must too
        "#define EXT_API_VERSION_MAJOR 1\n"
        "#define EXT_API_VERSION_MINOR 1\n"
        "#define EXT_API_VERSION_PATCH 0\n"
        "#define EXT_API_VERSION_AT_LEAST(x, y, z) "
        "(EXT_API_VERSION_MAJOR > (x) || (EXT_API_VERSION_MAJOR == (x) && "
        "(EXT_API_VERSION_MINOR > (y) || (EXT_API_VERSION_MINOR == (y) && "
        "EXT_API_VERSION_PATCH >= (z)))))\n"
        "typedef void *ext_db;\n"
        "typedef enum { EXT_KIND_A = 0, EXT_KIND_B = 1 } EXT_KIND;\n"
        "typedef EXT_KIND ext_kind;\n"
        "int32_t ext_open(const char *path, ext_db *out_db);\n"
        "void ext_close(ext_db db);\n"
        "const char *ext_version(void);\n"
        "int32_t ext_flush(ext_db db);\n"
        "ext_kind ext_get_kind(ext_db db);\n"
        "void ext_extra_one(ext_db db);\n"
        "int32_t ext_extra_two(void);\n"
    )

    def _compile(self, tmp_path, header, lang):
        (tmp_path / "ext.h").write_text(self.PRELUDE)
        src = tmp_path / f"probe.{'c' if lang == 'c' else 'cpp'}"
        src.write_text(f'#include "{header}"\n')
        result = subprocess.run(
            [
                "cc",
                "-fsyntax-only",
                f"-x{'c' if lang == 'c' else 'c++'}",
                "-I",
                str(tmp_path),
                str(src),
            ],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, result.stderr

    def test_consumer_compiles_as_c(self, tmp_path):
        _run(tmp_path)  # writes out.h + internal.hpp into tmp_path
        self._compile(tmp_path, "out.h", "c")

    def test_internal_compiles_as_cpp(self, tmp_path):
        _run(tmp_path)
        self._compile(tmp_path, "internal.hpp", "cpp")
