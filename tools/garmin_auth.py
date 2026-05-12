"""
CLI for Garmin Connect credential management. The actual library logic lives
in `runcoach.garmin`; this script just wraps it for shell invocation.

CLI usage:
    python tools/garmin_auth.py --save  --user Nicolas --email x@x.com --password secret
    python tools/garmin_auth.py --verify --user Nicolas
"""

import argparse
import sys
from pathlib import Path

# Make runcoach importable when invoked as `python tools/garmin_auth.py`.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from runcoach.garmin import (  # noqa: E402
    get_garmin_client,
    save_garmin_credentials,
)


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
