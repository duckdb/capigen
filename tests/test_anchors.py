"""The anchor parser: [[name]] is an anchor, anything else is prose."""

from capigen.anchors import find_anchors, find_malformed, rewrite_anchors


class TestFindAnchors:
    def test_finds_anchors_in_order(self):
        assert find_anchors("See [[close]] and [[connection]].") == [
            "close",
            "connection",
        ]

    def test_non_identifier_brackets_are_prose(self):
        assert find_anchors("a [[0, 1]] range, [[two words]], [[]]") == []

    def test_underscore_and_digits_allowed(self):
        assert find_anchors("[[_private]] [[idx_t2]]") == ["_private", "idx_t2"]

    def test_leading_digit_is_prose(self):
        assert find_anchors("[[2fast]]") == []

    def test_none_and_empty(self):
        assert find_anchors(None) == []
        assert find_anchors("") == []


class TestRewriteAnchors:
    def test_rewrites_each_anchor(self):
        out = rewrite_anchors("Prefer [[close]] over [[reset]].", lambda n: f"x_{n}")
        assert out == "Prefer x_close over x_reset."

    def test_prose_brackets_untouched(self):
        text = "a [[0, 1]] range"
        assert rewrite_anchors(text, lambda n: "NEVER") == text

    def test_callback_receives_bare_name(self):
        seen = []
        rewrite_anchors("[[close]]", lambda n: seen.append(n) or n)
        assert seen == ["close"]


class TestFindMalformed:
    def test_near_miss_anchors_are_malformed(self):
        assert find_malformed("a [[0, 1]] b [[two words]] c [[go()]] d [[]]") == [
            "0, 1",
            "two words",
            "go()",
            "",
        ]

    def test_valid_anchors_are_not_malformed(self):
        assert find_malformed("See [[close]] and [[conn]].") == []

    def test_plain_text_and_single_brackets_are_fine(self):
        assert find_malformed("an array [0], a link [x](y)") == []

    def test_none_and_empty(self):
        assert find_malformed(None) == []
        assert find_malformed("") == []


class TestRewriteNoneHandling:
    def test_none_passes_through(self):
        assert rewrite_anchors(None, lambda n: n) is None

    def test_empty_passes_through(self):
        assert rewrite_anchors("", lambda n: n) == ""
