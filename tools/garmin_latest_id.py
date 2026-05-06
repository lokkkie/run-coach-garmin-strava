"""
Cheap helper: print the latest Garmin running activity's ID and date.
No FIT download, just metadata. Used by the bot's pre-check to decide
whether work is needed before invoking garmin_fetch_fit.py.

Usage: python tools/garmin_latest_id.py [--user Nicolas]
Output (3 lines, stdout):
  <activity_id>
  <YYYY-MM-DD>
  <activity_name>

Exit codes:
  0  success
  1  auth / config error
  2  rate-limited (429); caller should back off
"""

import argparse
import logging
import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from garminconnect import Garmin

from garmin_auth import get_garmin_client

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

# Quiet down the SSO/login chatter that garminconnect prints
for name in ("garminconnect", "garth", "urllib3"):
    logging.getLogger(name).setLevel(logging.ERROR)


def main():
    parser = argparse.ArgumentParser(description="Print latest Garmin running activity ID and date")
    parser.add_argument("--user", default=None, help="User name for per-user credentials (e.g. Nicolas)")
    args = parser.parse_args()

    try:
        client = get_garmin_client(args.user)
    except SystemExit:
        raise
    except Exception as e:
        msg = str(e)
        if "429" in msg or "rate limit" in msg.lower():
            print("Rate limited (429)", file=sys.stderr)
            sys.exit(2)
        print(f"Auth error: {e}", file=sys.stderr)
        sys.exit(1)

    try:
        activities = client.get_activities(0, 5)
    except Exception as e:
        print(f"Activity fetch failed: {e}", file=sys.stderr)
        sys.exit(1)

    # Find the most recent running activity (skip non-running entries)
    for a in activities:
        if a.get("activityType", {}).get("typeKey", "") == "running":
            print(str(a["activityId"]))
            print(a.get("startTimeLocal", "")[:10])
            print(a.get("activityName", ""))
            return

    print("No recent running activity found", file=sys.stderr)
    sys.exit(1)


if __name__ == "__main__":
    main()
