"""Tests for runcoach.metrics — pace formatting and HR zone bucketing.
These were duplicated in 3+ tools before the package refactor.

Run from project root:
  python -m unittest tests.test_metrics -v
"""

import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


class TestPaceFromSpeed(unittest.TestCase):

    def test_normal_speed(self):
        from runcoach.metrics import pace_from_speed
        # 3.33 m/s ≈ 5:00/km
        self.assertEqual(pace_from_speed(3.33), "5:00")

    def test_pads_seconds(self):
        from runcoach.metrics import pace_from_speed
        # 4.0 m/s = 250 sec/km = 4:10/km
        self.assertEqual(pace_from_speed(4.0), "4:10")

    def test_zero_returns_empty(self):
        from runcoach.metrics import pace_from_speed
        self.assertEqual(pace_from_speed(0), "")

    def test_negative_returns_empty(self):
        """Negative speeds shouldn't crash — defensive against bad inputs."""
        from runcoach.metrics import pace_from_speed
        self.assertEqual(pace_from_speed(-1.0), "")

    def test_none_returns_empty(self):
        from runcoach.metrics import pace_from_speed
        self.assertEqual(pace_from_speed(None), "")


class TestPaceFromDistanceTime(unittest.TestCase):

    def test_normal(self):
        from runcoach.metrics import pace_from_distance_time
        # 10000m in 3000s = 5:00/km
        self.assertEqual(pace_from_distance_time(10000, 3000), "5:00")

    def test_zero_distance(self):
        from runcoach.metrics import pace_from_distance_time
        self.assertEqual(pace_from_distance_time(0, 100), "")

    def test_zero_time(self):
        from runcoach.metrics import pace_from_distance_time
        self.assertEqual(pace_from_distance_time(1000, 0), "")

    def test_none_values(self):
        from runcoach.metrics import pace_from_distance_time
        self.assertEqual(pace_from_distance_time(None, 100), "")
        self.assertEqual(pace_from_distance_time(100, None), "")


class TestPaceToSec(unittest.TestCase):

    def test_normal(self):
        from runcoach.metrics import pace_to_sec
        self.assertEqual(pace_to_sec("5:00"), 300)
        self.assertEqual(pace_to_sec("4:30"), 270)
        self.assertEqual(pace_to_sec("7:27"), 447)

    def test_malformed_returns_none(self):
        from runcoach.metrics import pace_to_sec
        self.assertIsNone(pace_to_sec("nope"))
        self.assertIsNone(pace_to_sec(""))
        self.assertIsNone(pace_to_sec(None))
        self.assertIsNone(pace_to_sec("5"))

    def test_roundtrip_loses_subsecond_precision(self):
        """Document the known precision loss — speed → pace string → seconds
        can drift by up to a second per roundtrip. Pin this so a future fix
        (keeping speed as float throughout) updates the test deliberately."""
        from runcoach.metrics import pace_from_speed, pace_to_sec
        # 1000/4.6 ≈ 217.39 sec/km → "3:37" → 217 sec back
        sec = pace_to_sec(pace_from_speed(4.6))
        self.assertEqual(sec, 217)  # loses 0.39s


class TestGetHrZone(unittest.TestCase):

    def test_zone_boundaries(self):
        """Boundaries are inclusive upper bounds: 60% lands in zone 1, not zone 2.
        Anchors the existing behavior; if HR_ZONE_BOUNDARIES semantics change,
        this test breaks loudly."""
        from runcoach.metrics import get_hr_zone
        max_hr = 200
        self.assertEqual(get_hr_zone(100, max_hr), 1)   # 50% — inside zone 1
        self.assertEqual(get_hr_zone(119, max_hr), 1)   # 59.5% — still zone 1
        self.assertEqual(get_hr_zone(120, max_hr), 1)   # 60% — upper bound of zone 1
        self.assertEqual(get_hr_zone(121, max_hr), 2)   # 60.5% — zone 2
        self.assertEqual(get_hr_zone(140, max_hr), 2)   # 70% — upper bound of zone 2
        self.assertEqual(get_hr_zone(141, max_hr), 3)   # 70.5% — zone 3
        self.assertEqual(get_hr_zone(160, max_hr), 3)   # 80% — upper bound of zone 3
        self.assertEqual(get_hr_zone(180, max_hr), 4)   # 90% — upper bound of zone 4
        self.assertEqual(get_hr_zone(200, max_hr), 5)   # 100% — zone 5
        self.assertEqual(get_hr_zone(220, max_hr), 5)   # above max — still zone 5

    def test_missing_inputs_return_zero(self):
        """0 means 'no zone determinable' — let callers distinguish from 'zone 1'."""
        from runcoach.metrics import get_hr_zone
        self.assertEqual(get_hr_zone(None, 200), 0)
        self.assertEqual(get_hr_zone(150, None), 0)
        self.assertEqual(get_hr_zone(0, 200), 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
