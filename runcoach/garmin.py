"""Garmin Connect helpers: credentials, login, activity fetching, FIT download.

`get_garmin_client(user)` returns a logged-in `garminconnect.Garmin` client;
`latest_running_activity(client)` returns the most recent running activity
dict (or None); `download_fit(client, activity_id)` returns FIT bytes with
the ZIP wrapper already stripped. `is_rate_limit_error(exc)` encapsulates
the 429 message-string match — Garmin's library doesn't expose a typed
exception for this, so the convention lives here in one place.

The CLI for credential management (`--save`, `--verify`) lives in
`tools/garmin_auth.py`, which is a thin wrapper around this module.
"""

import json
import os
import sys
from pathlib import Path

from garminconnect import Garmin

from runcoach.fit import extract_fit_bytes
from runcoach.paths import data_dir


def _credentials_file(user: str) -> Path:
    return data_dir(user) / "garmin_credentials.json"


def get_garmin_credentials(user: str | None) -> tuple[str, str]:
    """Return (email, password) for the given user.

    Lookup order:
      1. Per-user file at {data_dir}/garmin_credentials.json (preferred for
         multi-user setups; written by `garmin_auth.py --save --user ...`).
      2. GARMIN_EMAIL / GARMIN_PASSWORD env vars (the owner's legacy single-user
         path; remains the simplest way to run the bot for one person).

    Prints to stderr and `sys.exit(1)`s on failure — callers that need to
    survive missing credentials (e.g. polling_check iterating all users)
    must catch `SystemExit`.
    """
    if user:
        cred_file = _credentials_file(user)
        if cred_file.exists():
            with open(cred_file, encoding="utf-8") as f:
                creds = json.load(f)
            return creds["email"], creds["password"]

    email = os.getenv("GARMIN_EMAIL")
    password = os.getenv("GARMIN_PASSWORD")
    if email and password:
        return email, password

    if user:
        print(
            f"ERROR: No Garmin credentials for {user}. "
            f"Either set GARMIN_EMAIL/GARMIN_PASSWORD in .env or run:\n"
            f"  python tools/garmin_auth.py --save --user {user} --email <email> --password <password>",
            file=sys.stderr,
        )
    else:
        print("ERROR: GARMIN_EMAIL and GARMIN_PASSWORD must be set in .env", file=sys.stderr)
    sys.exit(1)


def get_garmin_client(user: str | None) -> Garmin:
    """Create and return a logged-in Garmin client for the given user."""
    email, password = get_garmin_credentials(user)
    client = Garmin(email, password)
    client.login()
    return client


def save_garmin_credentials(email: str, password: str, user: str) -> None:
    """Validate credentials by logging in, then write them to the user's data
    directory. Prints status and exits non-zero on login failure."""
    cred_file = _credentials_file(user)
    cred_file.parent.mkdir(parents=True, exist_ok=True)

    print("Validating credentials by logging in to Garmin Connect...")
    try:
        client = Garmin(email, password)
        client.login()
    except Exception as e:
        print(f"ERROR: Login failed — {e}", file=sys.stderr)
        sys.exit(1)

    cred_file.write_text(
        json.dumps({"email": email, "password": password}, indent=2),
        encoding="utf-8",
    )
    print(f"Credentials saved to {cred_file}")
    print("Login verified ✓")
    print(f"\nNext: run `python tools/set_source.py garmin --user {user}`")


def is_rate_limit_error(exc: BaseException) -> bool:
    """True if `exc` looks like a Garmin Connect rate-limit (HTTP 429).

    Garmin's Python client doesn't expose a typed exception for this, so we
    pattern-match on the message string. Centralized here so the heuristic
    can evolve in one place if Garmin changes their error format.
    """
    msg = str(exc).lower()
    return "429" in msg or "rate limit" in msg


def latest_running_activity(client: Garmin, search_count: int = 10) -> dict | None:
    """Return the most recent running activity from Garmin Connect, or None if
    none of the last `search_count` activities is a run.

    `search_count` defaults to 10 — small enough that one API call covers
    "the latest run" even when a cycling commute happens to be in slot 0,
    large enough to dodge a single non-running entry.
    """
    activities = client.get_activities(0, search_count)
    for a in activities:
        if a.get("activityType", {}).get("typeKey", "") == "running":
            return a
    return None


def download_fit(client: Garmin, activity_id: str) -> bytes:
    """Download a FIT file from Garmin Connect (ORIGINAL format, ZIP-wrapped)
    and return the raw FIT bytes with the ZIP stripped off."""
    raw = client.download_activity(
        activity_id, dl_fmt=client.ActivityDownloadFormat.ORIGINAL
    )
    return extract_fit_bytes(raw)
