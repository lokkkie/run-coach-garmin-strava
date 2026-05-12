"""Tests for runcoach.run_log — the unified append-with-dedup module that
replaced the two diverging copies in analyze_fit.py and strava_pull.py.

Run from project root:
  python -m unittest tests.test_run_log -v
"""

import json
import sys
import tempfile
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


def _make_analysis(date="2026-05-13", distance=10.0) -> dict:
    """Build a minimal analysis dict in the shape append_run expects."""
    return {
        "date": date,
        "session": {
            "distance_km": distance,
            "duration_min": 50.0,
            "avg_pace": "5:00",
            "avg_hr": 150,
            "max_hr": 170,
            "avg_cadence_spm": 172,
            "elevation_gain_m": 50,
        },
        "patterns": {
            "cardiac_decoupling_pct": 3.5,
            "negative_split": True,
        },
    }


class TestLoadRunLog(unittest.TestCase):

    def test_returns_empty_when_file_missing(self):
        from runcoach.run_log import load_run_log
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(load_run_log(Path(d)), [])

    def test_reads_existing_log(self):
        from runcoach.run_log import load_run_log
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "run_log.json").write_text(
                json.dumps([{"activity_id": "111", "date": "2026-05-01"}])
            )
            entries = load_run_log(Path(d))
            self.assertEqual(len(entries), 1)
            self.assertEqual(entries[0]["activity_id"], "111")


class TestAppendRun(unittest.TestCase):

    def test_appends_to_empty_log(self):
        from runcoach.run_log import append_run, load_run_log
        with tempfile.TemporaryDirectory() as d:
            data_dir = Path(d)
            result = append_run(_make_analysis(), "12345", data_dir, source="garmin")
            self.assertTrue(result)
            entries = load_run_log(data_dir)
            self.assertEqual(len(entries), 1)
            self.assertEqual(entries[0]["activity_id"], "12345")
            self.assertEqual(entries[0]["source"], "garmin")
            self.assertEqual(entries[0]["distance_km"], 10.0)

    def test_creates_data_dir_if_missing(self):
        from runcoach.run_log import append_run
        with tempfile.TemporaryDirectory() as d:
            data_dir = Path(d) / "fresh" / "data"  # doesn't exist
            append_run(_make_analysis(), "12345", data_dir, source="garmin")
            self.assertTrue((data_dir / "run_log.json").exists())

    def test_dedup_returns_false_for_known_id(self):
        from runcoach.run_log import append_run, load_run_log
        with tempfile.TemporaryDirectory() as d:
            data_dir = Path(d)
            append_run(_make_analysis(), "12345", data_dir, source="garmin")
            result = append_run(_make_analysis(), "12345", data_dir, source="garmin")
            self.assertFalse(result)
            self.assertEqual(len(load_run_log(data_dir)), 1)

    def test_dedup_works_across_str_int_activity_ids(self):
        """A run logged with int activity_id and re-attempted with str (or vice
        versa) must dedup. Pre-refactor analyze_fit didn't coerce, so this
        case slipped through and the same run could appear twice."""
        from runcoach.run_log import append_run, load_run_log
        with tempfile.TemporaryDirectory() as d:
            data_dir = Path(d)
            append_run(_make_analysis(), 12345, data_dir, source="garmin")
            result = append_run(_make_analysis(), "12345", data_dir, source="garmin")
            self.assertFalse(result)
            self.assertEqual(len(load_run_log(data_dir)), 1)

    def test_stores_activity_id_as_string(self):
        """Even if passed an int, the stored activity_id must be a string —
        that's how the rest of the system (polling_check, dedup checks)
        compares against it."""
        from runcoach.run_log import append_run, load_run_log
        with tempfile.TemporaryDirectory() as d:
            data_dir = Path(d)
            append_run(_make_analysis(), 12345, data_dir, source="garmin")
            self.assertEqual(load_run_log(data_dir)[0]["activity_id"], "12345")

    def test_sorts_by_date(self):
        from runcoach.run_log import append_run, load_run_log
        with tempfile.TemporaryDirectory() as d:
            data_dir = Path(d)
            append_run(_make_analysis(date="2026-05-15"), "B", data_dir, source="garmin")
            append_run(_make_analysis(date="2026-05-10"), "A", data_dir, source="garmin")
            append_run(_make_analysis(date="2026-05-20"), "C", data_dir, source="garmin")
            dates = [e["date"] for e in load_run_log(data_dir)]
            self.assertEqual(dates, ["2026-05-10", "2026-05-15", "2026-05-20"])

    def test_source_field_is_passed_through(self):
        from runcoach.run_log import append_run, load_run_log
        with tempfile.TemporaryDirectory() as d:
            data_dir = Path(d)
            append_run(_make_analysis(), "111", data_dir, source="strava")
            entry = load_run_log(data_dir)[0]
            self.assertEqual(entry["source"], "strava")

    def test_entry_has_full_schema(self):
        """The schema is the contract for downstream tools (running-coach
        skill, post-run-analysis, sheets writer). Lock it down."""
        from runcoach.run_log import append_run, load_run_log
        with tempfile.TemporaryDirectory() as d:
            data_dir = Path(d)
            append_run(_make_analysis(), "111", data_dir, source="garmin")
            entry = load_run_log(data_dir)[0]
            expected_keys = {
                "activity_id", "date", "distance_km", "duration_min", "avg_pace",
                "avg_hr", "max_hr", "avg_cadence_spm", "elevation_gain_m",
                "cardiac_decoupling_pct", "negative_split", "source",
            }
            self.assertEqual(set(entry.keys()), expected_keys)


if __name__ == "__main__":
    unittest.main(verbosity=2)
