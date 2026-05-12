"""Tests for the multi-user pivot in polling_check.py.

Run from project root:
  python -m unittest tests.test_polling_check -v
"""

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "tools"))


class TestActivityInRunLog(unittest.TestCase):
    """Per-user dedup: activity_in_run_log must read run_log.json from the user's
    data_dir, not a global .tmp/ path."""

    def test_returns_false_when_log_missing(self):
        import polling_check as pc
        with tempfile.TemporaryDirectory() as d:
            self.assertFalse(pc.activity_in_run_log(Path(d), "12345"))

    def test_returns_true_for_known_activity(self):
        import polling_check as pc
        with tempfile.TemporaryDirectory() as d:
            log_path = Path(d) / "run_log.json"
            log_path.write_text(json.dumps([
                {"activity_id": "111", "date": "2026-05-01"},
                {"activity_id": "222", "date": "2026-05-02"},
            ]))
            self.assertTrue(pc.activity_in_run_log(Path(d), "222"))
            self.assertTrue(pc.activity_in_run_log(Path(d), 222),
                            "Numeric activity_ids must match string-stored ones")

    def test_returns_false_for_unknown_activity(self):
        import polling_check as pc
        with tempfile.TemporaryDirectory() as d:
            log_path = Path(d) / "run_log.json"
            log_path.write_text(json.dumps([{"activity_id": "111", "date": "2026-05-01"}]))
            self.assertFalse(pc.activity_in_run_log(Path(d), "999"))

    def test_handles_corrupt_log(self):
        import polling_check as pc
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "run_log.json").write_text("not json {{{")
            self.assertFalse(pc.activity_in_run_log(Path(d), "111"))


class TestSetLastAnalyzedId(unittest.TestCase):
    """Pointer file must land in the user's data_dir, not a global location."""

    def test_writes_to_user_data_dir(self):
        import polling_check as pc
        with tempfile.TemporaryDirectory() as d:
            user_dir = Path(d) / "users" / "Alice" / "data"
            pc.set_last_analyzed_id(user_dir, "987654321")
            self.assertTrue((user_dir / "last_analyzed_id.txt").exists())
            self.assertEqual(
                (user_dir / "last_analyzed_id.txt").read_text(encoding="utf-8"),
                "987654321",
            )


class TestGetDataSource(unittest.TestCase):
    """Read data_source from the user's own coaching_state.json."""

    def test_defaults_to_garmin_when_missing(self):
        import polling_check as pc
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(pc.get_data_source(Path(d)), "garmin")

    def test_reads_strava_when_set(self):
        import polling_check as pc
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "coaching_state.json").write_text(json.dumps({"data_source": "strava"}))
            self.assertEqual(pc.get_data_source(Path(d)), "strava")

    def test_falls_back_on_corrupt_file(self):
        import polling_check as pc
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "coaching_state.json").write_text("garbage")
            self.assertEqual(pc.get_data_source(Path(d)), "garmin")


class TestSendTelegram(unittest.TestCase):
    """Notification must go to the per-user chat_id, not the env-var chat_id."""

    def test_uses_provided_chat_id(self):
        import polling_check as pc
        with mock.patch.dict(os.environ, {"TELEGRAM_BOT_TOKEN": "bot_token_123"}), \
             mock.patch("requests.post") as m_post:
            pc.send_telegram("hello", chat_id=657664020)

        self.assertEqual(m_post.call_count, 1)
        sent = m_post.call_args.kwargs["json"]
        self.assertEqual(sent["chat_id"], 657664020,
                         "send_telegram must use the chat_id arg, not env TELEGRAM_CHAT_ID")

    def test_silent_when_chat_id_missing(self):
        import polling_check as pc
        with mock.patch.dict(os.environ, {"TELEGRAM_BOT_TOKEN": "bot_token_123"}), \
             mock.patch("requests.post") as m_post:
            pc.send_telegram("hello", chat_id=None)
        self.assertEqual(m_post.call_count, 0)

    def test_silent_when_bot_token_missing(self):
        import polling_check as pc
        # Make sure no TELEGRAM_BOT_TOKEN leaks from the parent env.
        with mock.patch.dict(os.environ, {}, clear=True), \
             mock.patch("requests.post") as m_post:
            pc.send_telegram("hello", chat_id=123)
        self.assertEqual(m_post.call_count, 0)


class TestDataDirFor(unittest.TestCase):
    """data_dir_for must resolve user.data_dir relative to PROJECT_ROOT."""

    def test_resolves_relative_to_project_root(self):
        import polling_check as pc
        user = {"name": "Alice", "data_dir": "users/Alice/data"}
        expected = pc.PROJECT_ROOT / "users" / "Alice" / "data"
        self.assertEqual(pc.data_dir_for(user), expected)


class TestMainLoopFilter(unittest.TestCase):
    """main() must respect --user and not propagate per-user failures."""

    def test_user_flag_polls_only_that_user(self):
        import polling_check as pc
        fake_allowlist = [
            {"name": "Alice", "chat_id": 1, "data_dir": "users/Alice/data"},
            {"name": "Bob", "chat_id": 2, "data_dir": "users/Bob/data"},
        ]
        polled: list[str] = []

        with mock.patch.object(pc, "load_allowlist", return_value=fake_allowlist), \
             mock.patch.object(pc, "poll_user", side_effect=lambda u, s: polled.append(u["name"])), \
             mock.patch.object(sys, "argv", ["polling_check.py", "--user", "Alice"]):
            pc.main()

        self.assertEqual(polled, ["Alice"],
                         "--user Alice must only poll Alice, not Bob")

    def test_no_user_flag_iterates_everyone(self):
        import polling_check as pc
        fake_allowlist = [
            {"name": "Alice", "chat_id": 1, "data_dir": "users/Alice/data"},
            {"name": "Bob", "chat_id": 2, "data_dir": "users/Bob/data"},
        ]
        polled: list[str] = []

        with mock.patch.object(pc, "load_allowlist", return_value=fake_allowlist), \
             mock.patch.object(pc, "poll_user", side_effect=lambda u, s: polled.append(u["name"])), \
             mock.patch.object(sys, "argv", ["polling_check.py"]):
            pc.main()

        self.assertEqual(polled, ["Alice", "Bob"])

    def test_one_users_exception_does_not_abort_loop(self):
        import polling_check as pc
        fake_allowlist = [
            {"name": "Alice", "chat_id": 1, "data_dir": "users/Alice/data"},
            {"name": "Bob", "chat_id": 2, "data_dir": "users/Bob/data"},
            {"name": "Carol", "chat_id": 3, "data_dir": "users/Carol/data"},
        ]
        polled: list[str] = []

        def faulty_poll(user, source):
            if user["name"] == "Bob":
                raise RuntimeError("Bob's Garmin creds are bad")
            polled.append(user["name"])

        with mock.patch.object(pc, "load_allowlist", return_value=fake_allowlist), \
             mock.patch.object(pc, "poll_user", side_effect=faulty_poll), \
             mock.patch.object(sys, "argv", ["polling_check.py"]):
            pc.main()

        self.assertEqual(polled, ["Alice", "Carol"],
                         "Bob's exception must not abort polling of Carol")

    def test_unknown_user_exits_nonzero(self):
        import polling_check as pc
        fake_allowlist = [{"name": "Alice", "chat_id": 1, "data_dir": "users/Alice/data"}]
        with mock.patch.object(pc, "load_allowlist", return_value=fake_allowlist), \
             mock.patch.object(sys, "argv", ["polling_check.py", "--user", "Nobody"]):
            with self.assertRaises(SystemExit) as cm:
                pc.main()
            self.assertNotEqual(cm.exception.code, 0)


class TestAllowlistKevinDataDir(unittest.TestCase):
    """Kevin's data_dir in allowlist.json must point to users/Kevin/data, not .tmp."""

    def test_kevin_no_longer_in_tmp(self):
        path = PROJECT_ROOT / "users" / "allowlist.json"
        users = json.loads(path.read_text(encoding="utf-8"))["users"]
        kevin = next(u for u in users if u["name"] == "Kevin")
        self.assertEqual(kevin["data_dir"], "users/Kevin/data",
                         "Owner's data_dir must be migrated out of .tmp/")
        self.assertTrue(kevin.get("owner"), "Kevin must remain the owner")


if __name__ == "__main__":
    unittest.main(verbosity=2)
