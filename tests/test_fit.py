"""Tests for runcoach.fit — extract_fit_bytes, semicircles_to_degrees,
fit_local_date_str, and parse_fit against a real FIT file.

The parse_fit test uses one of Kevin's actual runs (committed in
users/Kevin/data/run_*.fit — well, the FIT files themselves are gitignored
as transient data, but kept in the working tree for smoke-testing). If the
sample file is absent (fresh clone), the parse_fit tests are skipped.

Run from project root:
  python -m unittest tests.test_fit -v
"""

import io
import sys
import unittest
import zipfile
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

SAMPLE_FIT = PROJECT_ROOT / "users" / "Kevin" / "data" / "run_2026-05-06.fit"


class TestExtractFitBytes(unittest.TestCase):

    def test_passes_raw_fit_through(self):
        """Some older Garmin endpoints return a raw .fit (no zip wrapper).
        extract_fit_bytes must return those bytes unchanged."""
        from runcoach.fit import extract_fit_bytes
        raw = b"\x0e\x10\x52\x08...not a zip..."
        self.assertEqual(extract_fit_bytes(raw), raw)

    def test_extracts_from_zip(self):
        """The ORIGINAL download format is a zip containing one .fit member.
        Build one in memory and verify extract_fit_bytes returns the .fit body."""
        from runcoach.fit import extract_fit_bytes
        fit_body = b"\x0e\x10\x52\x08FITBODY\x00\x00\x00"
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("12345.fit", fit_body)
        zipped = buf.getvalue()
        self.assertEqual(extract_fit_bytes(zipped), fit_body)

    def test_raises_when_zip_has_no_fit(self):
        from runcoach.fit import extract_fit_bytes
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("readme.txt", b"hello")
        with self.assertRaises(RuntimeError):
            extract_fit_bytes(buf.getvalue())


class TestSemicirclesToDegrees(unittest.TestCase):

    def test_none(self):
        from runcoach.fit import semicircles_to_degrees
        self.assertIsNone(semicircles_to_degrees(None))

    def test_known_conversion(self):
        """2**31 semicircles = 180 degrees (by definition)."""
        from runcoach.fit import semicircles_to_degrees
        self.assertAlmostEqual(semicircles_to_degrees(2**31), 180.0, places=6)
        self.assertAlmostEqual(semicircles_to_degrees(0), 0.0, places=6)


class TestFitLocalDateStr(unittest.TestCase):
    """Re-tests the timezone-bug fix — duplicating the test from
    test_fit_date_and_split.py because fit_local_date_str moved out of
    analyze_fit into runcoach.fit and the old test imports the old location."""

    def test_prefers_local_timestamp(self):
        from runcoach.fit import fit_local_date_str
        session = {"start_time": datetime(2026, 5, 5, 22, 0)}  # UTC: 5 May
        activity = {"local_timestamp": datetime(2026, 5, 6, 7, 0)}  # local: 6 May
        self.assertEqual(fit_local_date_str(session, activity), "2026-05-06")

    def test_falls_back_to_utc(self):
        from runcoach.fit import fit_local_date_str
        session = {"start_time": datetime(2026, 5, 5, 22, 0)}
        self.assertEqual(fit_local_date_str(session, {}), "2026-05-05")


@unittest.skipUnless(SAMPLE_FIT.exists(),
                     f"Sample FIT not present at {SAMPLE_FIT} (regenerated on next polling cycle)")
class TestParseFitRealFile(unittest.TestCase):
    """parse_fit against one of Kevin's actual runs. The values are hard-coded
    so any silent change to the parsing logic — schema or arithmetic — fails
    here loudly rather than corrupting downstream coaching data."""

    def test_session_summary_matches_expected(self):
        from runcoach.fit import parse_fit
        result = parse_fit(SAMPLE_FIT)
        self.assertEqual(result["date"], "2026-05-06")
        self.assertEqual(result["sport"], "running")
        self.assertEqual(result["session"]["distance_km"], 10.02)
        self.assertEqual(result["session"]["avg_pace"], "7:27")
        self.assertEqual(result["session"]["avg_hr"], 146)
        self.assertEqual(result["session"]["max_hr"], 156)

    def test_schema_keys_present(self):
        from runcoach.fit import parse_fit
        result = parse_fit(SAMPLE_FIT)
        self.assertEqual(set(result.keys()), {"date", "sport", "session", "patterns", "lap_splits"})
        self.assertIn("hr_zone_distribution_pct", result["patterns"])
        self.assertIn("cardiac_decoupling_pct", result["patterns"])
        self.assertIn("negative_split", result["patterns"])
        self.assertIn("pacing_discipline_pct", result["patterns"])

    def test_laps_are_lists_with_pace(self):
        from runcoach.fit import parse_fit
        result = parse_fit(SAMPLE_FIT)
        self.assertGreater(len(result["lap_splits"]), 0)
        for lap in result["lap_splits"]:
            self.assertIn("pace", lap)
            self.assertIn("distance_km", lap)


if __name__ == "__main__":
    unittest.main(verbosity=2)
