"""Tests for runcoach.garmin — credential lookup, rate-limit detection,
latest-running-activity selection, and FIT download.

The network-touching helpers (`get_garmin_client`, `download_fit`) are
covered via mocks; real Garmin login is exercised by the smoke-test path
(`python tools/polling_check.py --user Kevin`) rather than here.

Run from project root:
  python -m unittest tests.test_garmin -v
"""

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


class TestIsRateLimitError(unittest.TestCase):

    def test_detects_429_in_message(self):
        from runcoach.garmin import is_rate_limit_error
        self.assertTrue(is_rate_limit_error(Exception("HTTP 429 Too Many Requests")))

    def test_detects_rate_limit_phrase(self):
        from runcoach.garmin import is_rate_limit_error
        self.assertTrue(is_rate_limit_error(Exception("garmin sso rate limit hit")))

    def test_case_insensitive(self):
        from runcoach.garmin import is_rate_limit_error
        self.assertTrue(is_rate_limit_error(Exception("Rate Limit exceeded")))

    def test_unrelated_error_is_false(self):
        from runcoach.garmin import is_rate_limit_error
        self.assertFalse(is_rate_limit_error(Exception("invalid credentials")))
        self.assertFalse(is_rate_limit_error(Exception("network unreachable")))


class TestLatestRunningActivity(unittest.TestCase):

    def _make_client(self, activities):
        client = mock.MagicMock()
        client.get_activities.return_value = activities
        return client

    def test_returns_first_running_activity(self):
        from runcoach.garmin import latest_running_activity
        client = self._make_client([
            {"activityId": 1, "activityType": {"typeKey": "cycling"}},
            {"activityId": 2, "activityType": {"typeKey": "running"}, "activityName": "Morning run"},
            {"activityId": 3, "activityType": {"typeKey": "running"}},
        ])
        result = latest_running_activity(client)
        self.assertEqual(result["activityId"], 2,
                         "Must return the first running activity (most recent), not the second")

    def test_returns_none_when_no_runs(self):
        from runcoach.garmin import latest_running_activity
        client = self._make_client([
            {"activityId": 1, "activityType": {"typeKey": "cycling"}},
            {"activityId": 2, "activityType": {"typeKey": "swimming"}},
        ])
        self.assertIsNone(latest_running_activity(client))

    def test_returns_none_on_empty_response(self):
        from runcoach.garmin import latest_running_activity
        client = self._make_client([])
        self.assertIsNone(latest_running_activity(client))

    def test_search_count_passed_through(self):
        from runcoach.garmin import latest_running_activity
        client = self._make_client([{"activityId": 1, "activityType": {"typeKey": "running"}}])
        latest_running_activity(client, search_count=25)
        client.get_activities.assert_called_once_with(0, 25)

    def test_handles_missing_activity_type(self):
        from runcoach.garmin import latest_running_activity
        client = self._make_client([
            {"activityId": 1},  # no activityType at all
            {"activityId": 2, "activityType": {"typeKey": "running"}},
        ])
        self.assertEqual(latest_running_activity(client)["activityId"], 2)


class TestDownloadFit(unittest.TestCase):
    """download_fit must call client.download_activity with the ORIGINAL format
    enum, then strip the ZIP wrapper via runcoach.fit.extract_fit_bytes."""

    def test_extracts_zip_wrapped_fit(self):
        import io
        import zipfile
        from runcoach.garmin import download_fit

        fit_body = b"\x0e\x10\x52\x08FITPAYLOAD"
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("1.fit", fit_body)
        zipped = buf.getvalue()

        client = mock.MagicMock()
        client.download_activity.return_value = zipped
        # Match the enum access pattern used by the real client.
        client.ActivityDownloadFormat.ORIGINAL = "ORIGINAL"

        result = download_fit(client, "12345")

        client.download_activity.assert_called_once_with("12345", dl_fmt="ORIGINAL")
        self.assertEqual(result, fit_body)

    def test_passes_raw_fit_through(self):
        """If Garmin ever returns raw FIT (no zip wrapper), download_fit must
        still hand back the bytes unchanged — relies on extract_fit_bytes."""
        from runcoach.garmin import download_fit
        raw = b"\x0e\x10\x52\x08...not a zip..."
        client = mock.MagicMock()
        client.download_activity.return_value = raw
        client.ActivityDownloadFormat.ORIGINAL = "ORIGINAL"
        self.assertEqual(download_fit(client, "X"), raw)


class TestGetGarminCredentials(unittest.TestCase):
    """Lookup order: per-user JSON file → env vars → exit(1).
    Pins the legacy single-user .env fallback for the owner."""

    def test_reads_per_user_file(self):
        from runcoach.garmin import get_garmin_credentials
        with tempfile.TemporaryDirectory() as d:
            with mock.patch("runcoach.paths.PROJECT_ROOT", Path(d)):
                cred_dir = Path(d) / "users" / "Alice" / "data"
                cred_dir.mkdir(parents=True)
                (cred_dir / "garmin_credentials.json").write_text(
                    json.dumps({"email": "a@x.com", "password": "secret"})
                )
                # Clear env so we know the file is what won.
                with mock.patch.dict(os.environ, {}, clear=True):
                    self.assertEqual(get_garmin_credentials("Alice"), ("a@x.com", "secret"))

    def test_falls_back_to_env_when_file_missing(self):
        from runcoach.garmin import get_garmin_credentials
        with tempfile.TemporaryDirectory() as d:
            with mock.patch("runcoach.paths.PROJECT_ROOT", Path(d)), \
                 mock.patch.dict(os.environ, {"GARMIN_EMAIL": "k@x.com", "GARMIN_PASSWORD": "pw"}, clear=True):
                self.assertEqual(get_garmin_credentials("Alice"), ("k@x.com", "pw"))

    def test_env_used_when_no_user(self):
        from runcoach.garmin import get_garmin_credentials
        with mock.patch.dict(os.environ, {"GARMIN_EMAIL": "k@x.com", "GARMIN_PASSWORD": "pw"}, clear=True):
            self.assertEqual(get_garmin_credentials(None), ("k@x.com", "pw"))

    def test_exits_when_no_credentials_anywhere(self):
        from runcoach.garmin import get_garmin_credentials
        with tempfile.TemporaryDirectory() as d:
            with mock.patch("runcoach.paths.PROJECT_ROOT", Path(d)), \
                 mock.patch.dict(os.environ, {}, clear=True):
                with self.assertRaises(SystemExit) as cm:
                    get_garmin_credentials("Alice")
                self.assertNotEqual(cm.exception.code, 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
