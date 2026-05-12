"""
Shared Garmin credential helper and per-user session factory.

Library use:
    from garmin_auth import get_garmin_client
    from runcoach.paths import data_dir

CLI usage:
    python tools/garmin_auth.py --save  --user Nicolas --email x@x.com --password secret
    python tools/garmin_auth.py --verify --user Nicolas
"""

import argparse
import json
import os
import sys
from pathlib import Path

from garminconnect import Garmin

# Make runcoach importable when this file is invoked as `python tools/garmin_auth.py`.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from runcoach.paths import data_dir  # noqa: E402


def _credentials_file(user: str) -> Path:
    return data_dir(user) / "garmin_credentials.json"


def get_garmin_credentials(user: str | None) -> tuple[str, str]:
    """Return (email, password) for the given user.

    Lookup order:
      1. Per-user file at {data_dir}/garmin_credentials.json (preferred for
         multi-user setups; written by `garmin_auth.py --save --user ...`).
      2. GARMIN_EMAIL / GARMIN_PASSWORD env vars (the owner's legacy single-user
         path; remains the simplest way to run the bot for one person).
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
    """Save credentials to the user's data directory and validate by logging in."""
    cred_file = _credentials_file(user)
    cred_file.parent.mkdir(parents=True, exist_ok=True)

    print(f"Validating credentials by logging in to Garmin Connect...")
    try:
        client = Garmin(email, password)
        client.login()
    except Exception as e:
        print(f"ERROR: Login failed — {e}", file=sys.stderr)
        sys.exit(1)

    cred_file.write_text(json.dumps({"email": email, "password": password}, indent=2), encoding="utf-8")
    print(f"Credentials saved to {cred_file}")
    print(f"Login verified ✓")
    print(f"\nNext: run `python tools/set_source.py garmin --user {user}`")


def main():
    parser = argparse.ArgumentParser(description="Garmin credential manager")
    parser.add_argument("--save", action="store_true", help="Save and validate credentials for a user")
    parser.add_argument("--verify", action="store_true", help="Test login with stored credentials")
    parser.add_argument("--user", required=True, help="User name (e.g. Nicolas)")
    parser.add_argument("--email", default=None, help="Garmin Connect email (required with --save)")
    parser.add_argument("--password", default=None, help="Garmin Connect password (required with --save)")
    args = parser.parse_args()

    if args.save:
        if not args.email or not args.password:
            print("ERROR: --email and --password are required with --save", file=sys.stderr)
            sys.exit(1)
        save_garmin_credentials(args.email, args.password, args.user)

    elif args.verify:
        print(f"Testing Garmin login for {args.user}...")
        try:
            get_garmin_client(args.user)
            print("Login successful ✓")
        except SystemExit:
            raise
        except Exception as e:
            print(f"ERROR: Login failed — {e}", file=sys.stderr)
            sys.exit(1)

    else:
        parser.print_help()


if __name__ == "__main__":
    main()
