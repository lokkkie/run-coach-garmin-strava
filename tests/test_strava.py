"""Tests for runcoach.strava — token storage/refresh, api_get with rate-limit
detection, latest_run selection. Network calls are mocked.

Run from project root:
  python -m unittest tests.test_strava -v
"""

import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


class TestApiGet(unittest.TestCase):

    def test_returns_json_on_success(self):
        from runcoach.strava import api_get
        fake_resp = mock.MagicMock()
        fake_resp.status_code = 200
        fake_resp.json.return_value = [{"id": 1}, {"id": 2}]
        with mock.patch("runcoach.strava.requests.get", return_value=fake_resp):
            self.assertEqual(api_get("/x", "token"), [{"id": 1}, {"id": 2}])

    def test_raises_strava_rate_limited_on_429(self):
        from runcoach.strava import api_get, StravaRateLimited
        fake_resp = mock.MagicMock()
        fake_resp.status_code = 429
        with mock.patch("runcoach.strava.requests.get", return_value=fake_resp):
            with self.assertRaises(StravaRateLimited):
                api_get("/x", "token")

    def test_rate_limited_is_subclass_of_runtime_error(self):
        """Legacy callers `except RuntimeError` must still catch the rate-limit
        case — preserved by making StravaRateLimited a RuntimeError subclass."""
        from runcoach.strava import StravaRateLimited
        self.assertTrue(issubclass(StravaRateLimited, RuntimeError))

    def test_passes_auth_header_and_params(self):
        from runcoach.strava import api_get
        fake_resp = mock.MagicMock()
        fake_resp.status_code = 200
        fake_resp.json.return_value = {}
        with mock.patch("runcoach.strava.requests.get", return_value=fake_resp) as m_get:
            api_get("/athlete/activities", "tok_abc", {"per_page": 5})
        call = m_get.call_args
        self.assertEqual(call.kwargs["headers"], {"Authorization": "Bearer tok_abc"})
        self.assertEqual(call.kwargs["params"], {"per_page": 5})


class TestLatestRun(unittest.TestCase):

    def test_returns_first_run(self):
        from runcoach.strava import latest_run
        with mock.patch("runcoach.strava.api_get") as m_api:
            m_api.return_value = [
                {"id": 1, "type": "Ride"},
                {"id": 2, "type": "Run", "name": "Morning"},
                {"id": 3, "type": "Run"},
            ]
            result = latest_run("token")
            self.assertEqual(result["id"], 2)

    def test_accepts_sport_type_run(self):
        """Strava transitioned activity classification: older activities have
        `type`, newer ones have `sport_type`. Both must qualify a run."""
        from runcoach.strava import latest_run
        with mock.patch("runcoach.strava.api_get") as m_api:
            m_api.return_value = [
                {"id": 1, "sport_type": "Run"},
            ]
            self.assertEqual(latest_run("token")["id"], 1)

    def test_returns_none_when_no_run(self):
        from runcoach.strava import latest_run
        with mock.patch("runcoach.strava.api_get") as m_api:
            m_api.return_value = [{"id": 1, "type": "Ride"}, {"id": 2, "type": "Swim"}]
            self.assertIsNone(latest_run("token"))


class TestGetAccessToken(unittest.TestCase):

    def test_returns_stored_token_when_fresh(self):
        """If the stored token expires more than 60s from now, no refresh call.
        Anchors the "refresh only when stale" check."""
        from runcoach.strava import get_access_token
        with tempfile.TemporaryDirectory() as d:
            with mock.patch("runcoach.paths.PROJECT_ROOT", Path(d)), \
                 mock.patch.dict(os.environ, {"STRAVA_CLIENT_ID": "id", "STRAVA_CLIENT_SECRET": "sec"}, clear=True):
                cred_dir = Path(d) / "users" / "Alice" / "data"
                cred_dir.mkdir(parents=True)
                future = int(time.time()) + 3600  # 1 hour
                (cred_dir / "strava_token.json").write_text(json.dumps({
                    "access_token": "fresh_token", "refresh_token": "ref",
                    "expires_at": future, "athlete": {"firstname": "A"},
                }))
                with mock.patch("runcoach.strava.requests.post") as m_post:
                    self.assertEqual(get_access_token("Alice"), "fresh_token")
                self.assertEqual(m_post.call_count, 0,
                                 "Fresh token must not trigger refresh POST")

    def test_refreshes_when_within_60s_of_expiry(self):
        from runcoach.strava import get_access_token
        with tempfile.TemporaryDirectory() as d:
            with mock.patch("runcoach.paths.PROJECT_ROOT", Path(d)), \
                 mock.patch.dict(os.environ, {"STRAVA_CLIENT_ID": "id", "STRAVA_CLIENT_SECRET": "sec"}, clear=True):
                cred_dir = Path(d) / "users" / "Alice" / "data"
                cred_dir.mkdir(parents=True)
                near = int(time.time()) + 30  # 30s — within the 60s window
                (cred_dir / "strava_token.json").write_text(json.dumps({
                    "access_token": "stale", "refresh_token": "ref_old",
                    "expires_at": near, "athlete": {"firstname": "A"},
                }))
                fake_resp = mock.MagicMock()
                fake_resp.json.return_value = {
                    "access_token": "new_token", "refresh_token": "ref_new",
                    "expires_at": int(time.time()) + 7200,
                }
                fake_resp.raise_for_status = mock.MagicMock()
                with mock.patch("runcoach.strava.requests.post", return_value=fake_resp) as m_post:
                    self.assertEqual(get_access_token("Alice"), "new_token")
                    self.assertEqual(m_post.call_count, 1)

    def test_preserves_athlete_across_refresh(self):
        """Strava's refresh response usually omits athlete; the prior bundle's
        athlete info must carry over so downstream callers still see it."""
        from runcoach.strava import _load_tokens, get_access_token
        with tempfile.TemporaryDirectory() as d:
            with mock.patch("runcoach.paths.PROJECT_ROOT", Path(d)), \
                 mock.patch.dict(os.environ, {"STRAVA_CLIENT_ID": "id", "STRAVA_CLIENT_SECRET": "sec"}, clear=True):
                cred_dir = Path(d) / "users" / "Alice" / "data"
                cred_dir.mkdir(parents=True)
                token_path = cred_dir / "strava_token.json"
                token_path.write_text(json.dumps({
                    "access_token": "old", "refresh_token": "ref",
                    "expires_at": 0,  # forces refresh
                    "athlete": {"firstname": "Alice", "id": 42},
                }))
                fake_resp = mock.MagicMock()
                fake_resp.json.return_value = {
                    "access_token": "new", "refresh_token": "ref2",
                    "expires_at": int(time.time()) + 7200,
                    # athlete intentionally absent
                }
                fake_resp.raise_for_status = mock.MagicMock()
                with mock.patch("runcoach.strava.requests.post", return_value=fake_resp):
                    get_access_token("Alice")
                saved = _load_tokens(token_path)
                self.assertEqual(saved["athlete"], {"firstname": "Alice", "id": 42})

    def test_raises_when_token_file_missing(self):
        from runcoach.strava import get_access_token
        with tempfile.TemporaryDirectory() as d:
            with mock.patch("runcoach.paths.PROJECT_ROOT", Path(d)), \
                 mock.patch.dict(os.environ, {"STRAVA_CLIENT_ID": "id", "STRAVA_CLIENT_SECRET": "sec"}, clear=True):
                with self.assertRaises(RuntimeError):
                    get_access_token("Alice")

    def test_raises_when_client_id_missing(self):
        from runcoach.strava import get_access_token
        with mock.patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(RuntimeError) as cm:
                get_access_token(None)
            self.assertIn("STRAVA_CLIENT_ID", str(cm.exception))


if __name__ == "__main__":
    unittest.main(verbosity=2)
