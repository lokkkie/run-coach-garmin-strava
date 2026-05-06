"""
Switch the active data source between Garmin (default) and Strava.
Updates `.tmp/coaching_state.json:data_source`.

Usage:
  python tools/set_source.py garmin
  python tools/set_source.py strava
  python tools/set_source.py            # show current value
"""

import argparse
import json
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(PROJECT_ROOT / ".env")


def _data_dir(user: str | None) -> Path:
    if user:
        return PROJECT_ROOT / "users" / user / "data"
    return PROJECT_ROOT / ".tmp"


def _load_state(state_file: Path) -> dict:
    if not state_file.exists():
        return {}
    with open(state_file, encoding="utf-8") as f:
        return json.load(f)


def _save_state(state: dict, state_file: Path):
    state_file.parent.mkdir(parents=True, exist_ok=True)
    with open(state_file, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2)


def _validate_garmin(user: str | None) -> str | None:
    if user:
        cred_file = PROJECT_ROOT / "users" / user / "data" / "garmin_credentials.json"
        if not cred_file.exists():
            return (
                f"No Garmin credentials for {user} at {cred_file}.\n"
                f"  Run: python tools/garmin_auth.py --save --user {user} --email <email> --password <password>"
            )
        return None
    if not os.getenv("GARMIN_EMAIL") or not os.getenv("GARMIN_PASSWORD"):
        return "GARMIN_EMAIL / GARMIN_PASSWORD missing in .env"
    return None


def _validate_strava(token_file: Path) -> str | None:
    if not os.getenv("STRAVA_CLIENT_ID") or not os.getenv("STRAVA_CLIENT_SECRET"):
        return (
            "STRAVA_CLIENT_ID / STRAVA_CLIENT_SECRET missing in .env.\n"
            "  1. Create app at https://www.strava.com/settings/api\n"
            "  2. Paste IDs into .env"
        )
    if not token_file.exists():
        return (
            f"No Strava tokens at {token_file}.\n"
            "  Run: python tools/strava_auth.py --setup"
        )
    return None


def main():
    parser = argparse.ArgumentParser(description="Set active data source")
    parser.add_argument("source", nargs="?", choices=["garmin", "strava"], help="Data source to activate")
    parser.add_argument("--user", default=None, help="User name for per-user state (e.g. Nicolas)")
    args = parser.parse_args()

    data_dir = _data_dir(args.user)
    state_file = data_dir / "coaching_state.json"
    token_file = data_dir / "strava_token.json"

    if args.source is None:
        state = _load_state(state_file)
        current = state.get("data_source", "garmin")
        print(f"Current data_source: {current}")
        return

    target = args.source
    err = _validate_garmin(args.user) if target == "garmin" else _validate_strava(token_file)
    if err:
        print(f"ERROR: cannot set source to {target}.\n  {err}", file=sys.stderr)
        sys.exit(1)

    state = _load_state(state_file)
    previous = state.get("data_source", "garmin")
    state["data_source"] = target
    _save_state(state, state_file)
    print(f"data_source: {previous} -> {target}")


if __name__ == "__main__":
    main()
