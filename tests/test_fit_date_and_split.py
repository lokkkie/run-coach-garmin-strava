"""Tests for the FIT timezone fix (#5) and HTML-tag-aware smart_split (#9).

Run from project root:
  python -m unittest tests.test_fit_date_and_split -v
"""

import sys
import unittest
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))               # for `runcoach.*`
sys.path.insert(0, str(PROJECT_ROOT / "tools"))     # for sibling `telegram_bridge`


class TestFitLocalDate(unittest.TestCase):
    """fit_local_date_str must return the local calendar date, not the UTC date,
    so the Garmin and Strava ingest paths agree on which day a run happened."""

    def test_late_evening_local_returns_local_date(self):
        """Run starts 23:30 local in UTC+8 → 15:30 UTC same day. Local date wins."""
        from runcoach.fit import fit_local_date_str
        session = {"start_time": datetime(2026, 5, 6, 15, 30)}
        activity = {"local_timestamp": datetime(2026, 5, 6, 23, 30)}
        self.assertEqual(fit_local_date_str(session, activity), "2026-05-06")

    def test_crosses_midnight_utc_returns_local_date(self):
        """Run starts 07:00 local in UTC+9 → 22:00 UTC the day before.
        Without the fix this returns 2026-05-05; with the fix it returns 2026-05-06."""
        from runcoach.fit import fit_local_date_str
        session = {"start_time": datetime(2026, 5, 5, 22, 0)}
        activity = {"local_timestamp": datetime(2026, 5, 6, 7, 0)}
        self.assertEqual(fit_local_date_str(session, activity), "2026-05-06")

    def test_falls_back_to_utc_when_local_missing(self):
        """If activity.local_timestamp is absent, fall back to session.start_time."""
        from runcoach.fit import fit_local_date_str
        session = {"start_time": datetime(2026, 5, 5, 22, 0)}
        activity = {}
        self.assertEqual(fit_local_date_str(session, activity), "2026-05-05")

    def test_falls_back_to_string_when_both_missing(self):
        """If neither is a datetime, coerce to string and slice to YYYY-MM-DD."""
        from runcoach.fit import fit_local_date_str
        self.assertEqual(fit_local_date_str({"start_time": "2026-05-05T12:00:00Z"}, {}), "2026-05-05")
        self.assertEqual(fit_local_date_str({}, {}), "None")


class TestSmartSplitHTML(unittest.TestCase):
    """smart_split must produce valid HTML in every chunk: never break inside a
    tag, and close+reopen tags that span chunk boundaries."""

    def test_plain_text_splits_at_paragraph(self):
        from telegram_bridge import smart_split
        body = "A" * 3000 + "\n\n" + "B" * 3000
        chunks = smart_split(body, max_len=4000)
        self.assertEqual(len(chunks), 2)
        self.assertTrue(chunks[0].startswith("A"))
        self.assertTrue(chunks[1].startswith("B"))

    def test_no_special_handling_when_tags_fit_in_one_chunk(self):
        from telegram_bridge import smart_split
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
        from telegram_bridge import smart_split
        # Body: <b>...3500 As...\n\n...1500 Bs...</b>tail
        # Paragraph break at ~3500 makes the first chunk close <b> early.
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
        from telegram_bridge import smart_split
        body = '<a href="https://example.com/very/long/path">' + ("L" * 3500) + "\n\n" + ("M" * 500) + "</a>after"
        chunks = smart_split(body, max_len=4000)
        self.assertGreaterEqual(len(chunks), 2)
        self.assertTrue(chunks[0].endswith("</a>"))
        self.assertTrue(chunks[1].startswith('<a href="https://example.com/very/long/path">'),
                        f"<a> must reopen with original href; got: {chunks[1][:60]!r}")

    def test_nested_tags_closed_in_reverse_reopened_in_order(self):
        """<pre><b>...</b></pre> spanning boundary: close </b></pre>, reopen <pre><b>."""
        from telegram_bridge import smart_split
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
        from telegram_bridge import smart_split
        # Construct a body where a newline lands inside <a href="...
        # by having the URL contain a \n at position ~2500 (artificial but
        # exercises the safety check).
        body = "A" * 2400 + "\n" + '<a href="' + "x" * 1200 + '">' + "B" * 1000
        chunks = smart_split(body, max_len=4000)
        for c in chunks:
            # No chunk should end with an unterminated < (i.e., have a '<' after
            # the last '>'). Allowed: chunks ending in valid '</a>' close tag.
            last_lt = c.rfind("<")
            last_gt = c.rfind(">")
            self.assertGreaterEqual(last_gt, last_lt,
                                    f"Chunk ends mid-tag: {c[-50:]!r}")

    def test_short_text_returns_one_chunk(self):
        from telegram_bridge import smart_split
        self.assertEqual(smart_split("hello world"), ["hello world"])

    def test_does_not_balance_closing_without_opening(self):
        """A stray </b> with no matching <b> in the chunk must not get auto-opened
        at the next chunk (that would generate spurious bold formatting)."""
        from telegram_bridge import smart_split
        body = ("A" * 3500) + "</b>\n\n" + ("B" * 4500)
        chunks = smart_split(body, max_len=4000)
        for c in chunks:
            self.assertNotIn("<b></b>", c)  # no spurious empty bold
        # Chunk 1 (the B-block) must not start with <b> we never opened.
        self.assertFalse(chunks[1].startswith("<b>"),
                         f"Should not reopen unmatched tag; chunk1 head: {chunks[1][:20]!r}")


if __name__ == "__main__":
    unittest.main(verbosity=2)
