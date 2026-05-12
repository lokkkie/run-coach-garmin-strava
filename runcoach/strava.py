"""Strava API helpers: token refresh, generic GET, run/activity/streams/laps.

Read-side only — the OAuth setup flow (browser redirect, code exchange) still
lives in `tools/strava_auth.py` because it's tightly coupled to the CLI shape
(localhost server, browser launch, redirect URL parsing).

`get_access_token(user)` reads tokens from `{data_dir}/strava_token.json`,
auto-refreshes when expiring within 60 s, and persists rotated refresh tokens
back to disk. `api_get(path, token, params)` raises `StravaRateLimited` on
HTTP 429 so callers can back off cleanly. `latest_run(token)` returns the
most recent running activity dict from `/athlete/activities`, mirroring
`runcoach.garmin.latest_running_activity` for parity.
"""

import json
import os
import time
from pathlib import Path

import requests

from runcoach.paths import data_dir

API_BASE = "https://www.strava.com/api/v3"
TOKEN_URL = "https://www.strava.com/api/v3/oauth/token"


class StravaRateLimited(RuntimeError):
    """Raised when Strava responds with HTTP 429. Subclass of RuntimeError so
    existing `except RuntimeError` catches still work."""


def _token_file(user: str | None = None) -> Path:
    return data_dir(user) / "strava_token.json"


def _load_tokens(token_file: Path) -> dict | None:
    if not token_file.exists():
        return None
    with open(token_file, encoding="utf-8") as f:
        return json.load(f)


def _save_tokens(tokens: dict, token_file: Path) -> None:
    token_file.parent.mkdir(parents=True, exist_ok=True)
    with open(token_file, "w", encoding="utf-8") as f:
        json.dump(tokens, f, indent=2)


def _refresh_tokens(client_id: str, client_secret: str, refresh_token: str) -> dict:
    resp = requests.post(
        TOKEN_URL,
        data={
            "client_id": client_id,
            "client_secret": client_secret,
            "refresh_token": refresh_token,
            "grant_type": "refresh_token",
        },
        timeout=15,
    )
    resp.raise_for_status()
    return resp.json()


def complete_oauth(code: str, user: str | None = None) -> dict:
    """Exchange an OAuth authorization code for tokens and persist them to the
    user's token file at `{data_dir}/strava_token.json`. Returns the saved
    bundle (access_token, refresh_token, expires_at, athlete).

    Used by `tools/strava_auth.py` for both the localhost-redirect setup flow
    and the manual paste-the-redirect-URL flow — both paths converge here.
    Raises RuntimeError if STRAVA_CLIENT_ID / STRAVA_CLIENT_SECRET are missing.
    """
    client_id = os.getenv("STRAVA_CLIENT_ID")
    client_secret = os.getenv("STRAVA_CLIENT_SECRET")
    if not client_id or not client_secret:
        raise RuntimeError(
            "STRAVA_CLIENT_ID / STRAVA_CLIENT_SECRET missing in .env. "
            "Create an app at https://www.strava.com/settings/api"
        )

    resp = requests.post(
        TOKEN_URL,
        data={
            "client_id": client_id,
            "client_secret": client_secret,
            "code": code,
            "grant_type": "authorization_code",
        },
        timeout=15,
    )
    resp.raise_for_status()
    tokens = resp.json()

    _save_tokens(tokens, _token_file(user))
    return tokens


def get_access_token(user: str | None = None) -> str:
    """Return a currently-valid Strava access token for the given user.

    Refreshes the token if it expires within 60 seconds. Strava may rotate
    the refresh_token on refresh; the new bundle is persisted back to the
    token file. Athlete info is preserved across refresh responses that
    omit it.

    Raises RuntimeError if the user has no token file (needs onboarding) or
    if `STRAVA_CLIENT_ID` / `STRAVA_CLIENT_SECRET` are missing from .env.
    """
    client_id = os.getenv("STRAVA_CLIENT_ID")
    client_secret = os.getenv("STRAVA_CLIENT_SECRET")
    if not client_id or not client_secret:
        raise RuntimeError(
            "STRAVA_CLIENT_ID / STRAVA_CLIENT_SECRET missing in .env. "
            "Create an app at https://www.strava.com/settings/api"
        )

    token_file = _token_file(user)
    tokens = _load_tokens(token_file)
    if not tokens:
        user_flag = f" --user {user}" if user else ""
        raise RuntimeError(
            f"No Strava tokens at {token_file}. "
            f"Run: python tools/strava_auth.py --setup{user_flag}"
        )

    # Refresh if access token expires within 60 seconds.
    if int(tokens.get("expires_at", 0)) - 60 < int(time.time()):
        new_tokens = _refresh_tokens(client_id, client_secret, tokens["refresh_token"])
        # Strava sometimes rotates the refresh_token — preserve athlete info
        # from the original bundle if the refresh response omits it.
        new_tokens["athlete"] = tokens.get("athlete", new_tokens.get("athlete"))
        _save_tokens(new_tokens, token_file)
        tokens = new_tokens

    return tokens["access_token"]


def api_get(path: str, token: str, params: dict | None = None) -> dict | list:
    """GET a Strava API endpoint. `path` is appended to `API_BASE`.

    Raises `StravaRateLimited` on HTTP 429 (caller decides whether to back
    off and retry), or `requests.HTTPError` on other 4xx/5xx.
    """
    resp = requests.get(
        f"{API_BASE}{path}",
        headers={"Authorization": f"Bearer {token}"},
        params=params,
        timeout=30,
    )
    if resp.status_code == 429:
        raise StravaRateLimited("Strava rate-limited (429)")
    resp.raise_for_status()
    return resp.json()


def latest_run(token: str, per_page: int = 5) -> dict | None:
    """Return the most recent running activity from `/athlete/activities`,
    or None if none of the latest `per_page` activities is a Run.

    Same semantics as `runcoach.garmin.latest_running_activity` — search a
    small recent window, return the first match (or None).
    """
    activities = api_get("/athlete/activities", token, {"per_page": per_page})
    for a in activities:
        if a.get("type") == "Run" or a.get("sport_type") == "Run":
            return a
    return None


def fetch_activity(token: str, activity_id: str) -> dict:
    """GET /activities/<id> — full activity detail."""
    return api_get(f"/activities/{activity_id}", token)


def fetch_streams(token: str, activity_id: str) -> dict:
    """GET /activities/<id>/streams — per-sample HR / velocity / cadence /
    altitude / time data, keyed by stream type."""
    return api_get(
        f"/activities/{activity_id}/streams",
        token,
        params={
            "keys": "heartrate,velocity_smooth,cadence,altitude,time",
            "key_by_type": "true",
        },
    )


def fetch_laps(token: str, activity_id: str) -> list:
    """GET /activities/<id>/laps — per-lap splits."""
    return api_get(f"/activities/{activity_id}/laps", token)
