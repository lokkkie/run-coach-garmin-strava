"""Tests for runcoach.telegram_format.smart_split — HTML-tag-aware text splitting.

Run from project root:
  python -m unittest tests.test_telegram_format -v
"""

import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


class TestSmartSplitHTML(unittest.TestCase):
    """smart_split must produce valid HTML in every chunk: never break inside a
    tag, and close+reopen tags that span chunk boundaries."""

    def test_plain_text_splits_at_paragraph(self):
        from runcoach.telegram_format import smart_split
        body = "A" * 3000 + "\n\n" + "B" * 3000
        chunks = smart_split(body, max_len=4000)
        self.assertEqual(len(chunks), 2)
        self.assertTrue(chunks[0].startswith("A"))
        self.assertTrue(chunks[1].startswith("B"))

    def test_short_text_returns_one_chunk(self):
        from runcoach.telegram_format import smart_split
        self.assertEqual(smart_split("hello world"), ["hello world"])

    def test_no_special_handling_when_tags_fit_in_one_chunk(self):
        from runcoach.telegram_format import smart_split
        body = "<b>" + ("x" * 100) + "</b>\n\n" + "y" * 4000
        chunks = smart_split(body, max_len=4000)
        # Tag is entirely in chunk 0; no need to inject close/reopen.
        self.assertEqual(len(chunks), 2)
        self.assertIn("<b>", chunks[0])
        self.assertIn("</b>", chunks[0])
        self.assertNotIn("<b>", chunks[1])

    def test_bold_spanning_boundary_closes_and_reopens(self):
        """<b> opened in chunk N, closing </b> only in chunk N+1 — must wrap
        the boundary so each chunk is valid HTML on its own."""
        from runcoach.telegram_format import smart_split
        body = "<b>" + ("A" * 3500) + "\n\n" + ("B" * 500) + "</b>tail"
        chunks = smart_split(body, max_len=4000)
        self.assertGreaterEqual(len(chunks), 2)
        self.assertTrue(chunks[0].endswith("</b>"),
                        f"chunk 0 must close <b> before boundary; got tail: {chunks[0][-20:]!r}")
        self.assertTrue(chunks[1].startswith("<b>"),
                        f"chunk 1 must reopen <b>; got head: {chunks[1][:20]!r}")

    def test_anchor_attributes_preserved_on_reopen(self):
        """A long <a href="url">label</a> spanning a boundary must reopen with
        the same href, not bare <a>."""
        from runcoach.telegram_format import smart_split
        body = '<a href="https://example.com/very/long/path">' + ("L" * 3500) + "\n\n" + ("M" * 500) + "</a>after"
        chunks = smart_split(body, max_len=4000)
        self.assertGreaterEqual(len(chunks), 2)
        self.assertTrue(chunks[0].endswith("</a>"))
        self.assertTrue(chunks[1].startswith('<a href="https://example.com/very/long/path">'),
                        f"<a> must reopen with original href; got: {chunks[1][:60]!r}")

    def test_nested_tags_closed_in_reverse_reopened_in_order(self):
        """<pre><b>...</b></pre> spanning boundary: close </b></pre>, reopen <pre><b>."""
        from runcoach.telegram_format import smart_split
        body = "<pre><b>" + ("X" * 3500) + "\n\n" + ("Y" * 500) + "</b></pre>"
        chunks = smart_split(body, max_len=4000)
        self.assertGreaterEqual(len(chunks), 2)
        self.assertTrue(chunks[0].endswith("</b></pre>"),
                        f"close inner before outer; got: {chunks[0][-30:]!r}")
        self.assertTrue(chunks[1].startswith("<pre><b>"),
                        f"reopen outer before inner; got: {chunks[1][:30]!r}")

    def test_split_inside_tag_is_pushed_outside(self):
        """If the only candidate landing in the latter half is inside a tag,
        smart_split must back off to a safer break."""
        from runcoach.telegram_format import smart_split
        body = "A" * 2400 + "\n" + '<a href="' + "x" * 1200 + '">' + "B" * 1000
        chunks = smart_split(body, max_len=4000)
        for c in chunks:
            last_lt = c.rfind("<")
            last_gt = c.rfind(">")
            self.assertGreaterEqual(last_gt, last_lt,
                                    f"Chunk ends mid-tag: {c[-50:]!r}")

    def test_does_not_balance_closing_without_opening(self):
        """A stray </b> with no matching <b> in the chunk must not get auto-opened
        at the next chunk (that would generate spurious bold formatting)."""
        from runcoach.telegram_format import smart_split
        body = ("A" * 3500) + "</b>\n\n" + ("B" * 4500)
        chunks = smart_split(body, max_len=4000)
        for c in chunks:
            self.assertNotIn("<b></b>", c)  # no spurious empty bold
        self.assertFalse(chunks[1].startswith("<b>"),
                         f"Should not reopen unmatched tag; chunk1 head: {chunks[1][:20]!r}")


class TestTagHelpers(unittest.TestCase):
    """Coverage for the lower-level _open_tags_at and _split_is_inside_tag — they
    underpin smart_split's correctness and are worth pinning directly."""

    def test_open_tags_empty_text(self):
        from runcoach.telegram_format import _open_tags_at
        self.assertEqual(_open_tags_at(""), [])

    def test_open_tags_balanced(self):
        from runcoach.telegram_format import _open_tags_at
        self.assertEqual(_open_tags_at("<b>foo</b>"), [])

    def test_open_tags_unbalanced_returns_stack(self):
        from runcoach.telegram_format import _open_tags_at
        result = _open_tags_at("<b>foo")
        self.assertEqual(result, [("b", "")])

    def test_open_tags_preserves_attributes(self):
        from runcoach.telegram_format import _open_tags_at
        result = _open_tags_at('<a href="https://x.com">link')
        self.assertEqual(result, [("a", ' href="https://x.com"')])

    def test_open_tags_ignores_non_telegram_tags(self):
        from runcoach.telegram_format import _open_tags_at
        # <em> isn't in _TELEGRAM_HTML_TAGS — wait, actually it is.
        # Use a truly unsupported one: <div>.
        self.assertEqual(_open_tags_at("<div>foo"), [])

    def test_split_inside_tag_true_when_mid_tag(self):
        from runcoach.telegram_format import _split_is_inside_tag
        # "<b>foo": idx=1 is inside "<b>" (between < and >)
        self.assertTrue(_split_is_inside_tag("<b>foo", 1))

    def test_split_inside_tag_false_when_outside(self):
        from runcoach.telegram_format import _split_is_inside_tag
        # "<b>foo": idx=4 is past the ">"
        self.assertFalse(_split_is_inside_tag("<b>foo", 4))


if __name__ == "__main__":
    unittest.main(verbosity=2)
