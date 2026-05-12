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
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from runcoach.garmin import (  # noqa: E402
    get_garmin_client,
    is_rate_limit_error,
    latest_running_activity,
)

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
        if is_rate_limit_error(e):
            print("Rate limited (429)", file=sys.stderr)
            sys.exit(2)
        print(f"Auth error: {e}", file=sys.stderr)
        sys.exit(1)

    try:
        activity = latest_running_activity(client, search_count=5)
    except Exception as e:
        print(f"Activity fetch failed: {e}", file=sys.stderr)
        sys.exit(1)

    if activity is None:
        print("No recent running activity found", file=sys.stderr)
        sys.exit(1)

    print(str(activity["activityId"]))
    print(activity.get("startTimeLocal", "")[:10])
    print(activity.get("activityName", ""))


if __name__ == "__main__":
    main()
