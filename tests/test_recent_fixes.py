"""Tests for the three fixes applied in this session.

Run from project root:
  python -m unittest tests.test_recent_fixes -v
"""

import asyncio
import json
import os
import sys
import unittest
from pathlib import Path
from unittest import mock

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "tools"))


class TestStravaAuthSingleExchange(unittest.TestCase):
    """Fix #1: _exchange_code must POST to Strava's token endpoint exactly once."""

    def test_exchange_code_posts_once(self):
        with mock.patch.dict(os.environ, {
            "STRAVA_CLIENT_ID": "fake_id",
            "STRAVA_CLIENT_SECRET": "fake_secret",
        }):
            import strava_auth  # imported lazily so the env patch is in effect

            fake_resp = mock.MagicMock()
            fake_resp.json.return_value = {
                "access_token": "AT", "refresh_token": "RT",
                "expires_at": 9999999999, "athlete": {"firstname": "Test"},
            }
            fake_resp.raise_for_status = mock.MagicMock()

            with mock.patch.object(strava_auth.requests, "post", return_value=fake_resp) as m_post, \
                 mock.patch.object(strava_auth, "_save_tokens") as m_save:
                strava_auth._exchange_code(
                    "http://localhost:53682/?code=abc123&scope=read",
                    user="TestUser",
                )

            self.assertEqual(m_post.call_count, 1,
                             f"Expected exactly 1 POST to Strava token endpoint, got {m_post.call_count}")
            self.assertEqual(m_save.call_count, 1,
                             f"Expected exactly 1 token-file write, got {m_save.call_count}")


class TestNonOwnerToolRestriction(unittest.TestCase):
    """Fix #2: non-owner Telegram sessions must have dangerous tools disallowed at the SDK layer."""

    def test_constant_includes_dangerous_tools(self):
        import telegram_bridge as tb
        # The denylist should at minimum prevent shell execution and file writes.
        for tool in ("Bash", "Edit", "Write", "NotebookEdit", "Agent"):
            self.assertIn(tool, tb.NON_OWNER_DISALLOWED_TOOLS,
                          f"{tool} must be in NON_OWNER_DISALLOWED_TOOLS — it can write/execute")

    def test_session_default_disallowed_empty(self):
        import telegram_bridge as tb
        s = tb.ClaudeSession("prompt")
        self.assertEqual(s._disallowed_tools, [],
                         "Default ClaudeSession must not restrict tools (owner path)")

    def test_session_stores_disallowed_list(self):
        import telegram_bridge as tb
        s = tb.ClaudeSession("prompt", disallowed_tools=tb.NON_OWNER_DISALLOWED_TOOLS)
        self.assertEqual(s._disallowed_tools, tb.NON_OWNER_DISALLOWED_TOOLS)

    def test_session_start_passes_disallowed_to_sdk(self):
        """ClaudeAgentOptions must receive the disallowed_tools list when start() runs."""
        import telegram_bridge as tb

        captured: dict = {}

        class FakeClient:
            def __init__(self, options):
                captured["options"] = options

            async def __aenter__(self): return self
            async def __aexit__(self, *a): pass

        with mock.patch.object(tb, "ClaudeSDKClient", FakeClient):
            s = tb.ClaudeSession("prompt", disallowed_tools=["Bash", "Edit"])
            asyncio.run(s.start())

        opts = captured["options"]
        self.assertEqual(list(opts.disallowed_tools), ["Bash", "Edit"])

    def test_get_or_create_session_owner_vs_non_owner(self):
        """get_or_create_session must apply the denylist iff the user is non-owner."""
        import telegram_bridge as tb

        captured: list[dict] = []

        class FakeClient:
            def __init__(self, options):
                captured.append({"disallowed": list(options.disallowed_tools)})

            async def __aenter__(self): return self
            async def __aexit__(self, *a): pass

        async def run_both():
            tb.claude_sessions.clear()
            with mock.patch.object(tb, "ClaudeSDKClient", FakeClient):
                await tb.get_or_create_session("1", {
                    "name": "Owner", "chat_id": 1, "owner": True, "data_dir": ".tmp",
                })
                await tb.get_or_create_session("2", {
                    "name": "Guest", "chat_id": 2, "owner": False, "data_dir": "users/Guest/data",
                })
            tb.claude_sessions.clear()

        asyncio.run(run_both())

        self.assertEqual(captured[0]["disallowed"], [],
                         "Owner session must have no tool restrictions")
        self.assertEqual(captured[1]["disallowed"], tb.NON_OWNER_DISALLOWED_TOOLS,
                         "Non-owner session must apply the full denylist")


class TestBaselineSchemaAlignment(unittest.TestCase):
    """Fix #3: onboarding skill must produce all keys the running-coach skill requires."""

    # Field names listed as required in running-coach SKILL.md §4
    REQUIRED_KEYS = [
        "starting_weekly_km", "peak_weekly_km", "longest_run_km",
        "easy_pace_target", "tempo_pace_target", "estimated_race_pace",
        "pace_trend", "avg_hr", "avg_cadence_spm", "consistency_weeks_with_runs",
    ]

    def test_onboarding_schema_has_all_required_keys(self):
        path = PROJECT_ROOT / ".claude" / "skills" / "telegram-onboarding" / "SKILL.md"
        text = path.read_text(encoding="utf-8")
        for key in self.REQUIRED_KEYS:
            self.assertIn(f'"{key}"', text,
                          f'Onboarding schema is missing required key "{key}"')

    def test_onboarding_schema_marks_source_self_reported(self):
        path = PROJECT_ROOT / ".claude" / "skills" / "telegram-onboarding" / "SKILL.md"
        text = path.read_text(encoding="utf-8")
        self.assertIn('"source": "self-reported"', text,
                      "Onboarding schema must include source: self-reported")

    def test_running_coach_handles_self_reported(self):
        path = PROJECT_ROOT / ".claude" / "skills" / "running-coach" / "SKILL.md"
        text = path.read_text(encoding="utf-8")
        self.assertIn('source == "self-reported"', text,
                      "Running-coach SKILL.md must branch on source == self-reported baselines")

    def test_onboarding_canonical_block_is_valid_json_template(self):
        """The JSON block in onboarding (with placeholders stripped) parses as JSON
        with all required keys present at the top level."""
        path = PROJECT_ROOT / ".claude" / "skills" / "telegram-onboarding" / "SKILL.md"
        text = path.read_text(encoding="utf-8")

        # Find the first ```json ... ``` fenced block in the file.
        marker_start = text.find("```json")
        self.assertGreater(marker_start, -1, "No ```json block found in onboarding SKILL.md")
        block_start = text.find("\n", marker_start) + 1
        block_end = text.find("```", block_start)
        block = text[block_start:block_end]

        # Replace placeholders so the block parses as real JSON. The template uses
        # both `"<...>"` (placeholder for string-typed fields, already quoted) and
        # `<...>` (placeholder for numeric fields). Collapse both to `null`, which is
        # a valid JSON literal in either position.
        import re
        sanitized = re.sub(r'"?<[^>]+>"?', "null", block)

        try:
            parsed = json.loads(sanitized)
        except json.JSONDecodeError as e:
            self.fail(f"Onboarding JSON template is not parseable after placeholder substitution: {e}\n---\n{sanitized}")

        for key in self.REQUIRED_KEYS:
            self.assertIn(key, parsed, f"Parsed onboarding schema missing required key: {key}")


if __name__ == "__main__":
    unittest.main(verbosity=2)
