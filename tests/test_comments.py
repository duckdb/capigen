"""Comment rendering: paragraph unwrapping, prefixing, and comment form."""

from capigen.adapters.c.comments import doc, prefixed, unwrap


class TestUnwrap:
    """Line breaks inside a paragraph belong to the spec, not the header."""

    def test_joins_a_hard_wrapped_paragraph(self):
        assert unwrap("one two\nthree four\n") == ["one two three four"]

    def test_blank_line_separates_paragraphs(self):
        assert unwrap("one\ntwo\n\nthree\n") == ["one two", "", "three"]

    def test_collapses_repeated_blank_lines(self):
        assert unwrap("one\n\n\n\ntwo") == ["one", "", "two"]

    def test_strips_leading_and_trailing_blank_lines(self):
        assert unwrap("\n\n  one  \n\n") == ["one"]

    def test_empty_description_yields_no_lines(self):
        assert unwrap("") == []
        assert unwrap("   \n\t\n") == []

    def test_list_items_keep_their_own_lines_and_indent(self):
        text = "modes:\n  - FIRST: does a\n    thing\n  - SECOND: does\n    another\n"
        assert unwrap(text) == [
            "modes:",
            "  - FIRST: does a thing",
            "  - SECOND: does another",
        ]

    def test_dedent_after_a_list_starts_a_paragraph(self):
        text = "modes:\n  - FIRST: does a\n    thing\nAfterwards the list\nends.\n"
        assert unwrap(text) == [
            "modes:",
            "  - FIRST: does a thing",
            "Afterwards the list ends.",
        ]

    def test_numbered_and_starred_markers_are_list_items(self):
        text = "1. first\n2) second\n* third\n+ fourth\n"
        assert unwrap(text) == ["1. first", "2) second", "* third", "+ fourth"]


class TestDoc:
    """`//!` for a one-liner, `/*! ... */` once the comment spans lines."""

    def test_short_description_is_a_line_comment(self):
        assert doc("one two") == "//! one two"

    def test_hard_wrapped_but_short_description_is_a_line_comment(self):
        assert doc("one\ntwo") == "//! one two"

    def test_description_too_long_for_one_line_becomes_a_block(self):
        text = "word " * 40
        assert doc(text) == f"/*!\n * {text.strip()}\n */"

    def test_multiple_paragraphs_become_a_block(self):
        assert doc("one\n\ntwo") == "/*!\n * one\n *\n * two\n */"

    def test_width_decides_the_form(self):
        text = "a" * 40
        assert doc(text, width=44) == f"//! {text}"
        assert doc(text, width=43) == f"/*!\n * {text}\n */"

    def test_indent_applies_to_every_line(self):
        assert doc("one", "  ") == "  //! one"
        assert doc("one\n\ntwo", "  ") == "  /*!\n   * one\n   *\n   * two\n   */"

    def test_indent_counts_against_the_budget(self):
        text = "a" * 40
        assert doc(text, "  ", width=46) == f"  //! {text}"
        assert doc(text, "  ", width=45) == f"  /*!\n   * {text}\n   */"

    def test_empty_description_renders_nothing(self):
        assert doc("") == ""


class TestPrefixed:
    """Raw prefixed lines, for the pieces of a function's doc block."""

    def test_prefixes_each_line(self):
        assert prefixed("one\ntwo\n\nthree", " * ") == " * one two\n *\n * three"

    def test_blank_lines_have_no_trailing_whitespace(self):
        assert " * \n" not in prefixed("one\n\ntwo", " * ") + "\n"

    def test_empty_description_renders_nothing(self):
        assert prefixed("", " * ") == ""
