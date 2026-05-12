"""
Cheap helper: print the latest Strava run's activity_id and date.
Mirrors tools/garmin_latest_id.py for symmetry.

Usage:
  python tools/strava_latest_id.py
  python tools/strava_latest_id.py --user Nicolas
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
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from runcoach.strava import (  # noqa: E402
    StravaRateLimited,
    get_access_token,
    latest_run,
)


def main():
    parser = argparse.ArgumentParser(description="Print latest Strava run id/date/name")
    parser.add_argument("--user", default=None, help="User name for per-user Strava token")
    args = parser.parse_args()

    try:
        token = get_access_token(user=args.user)
    except RuntimeError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)

    try:
        activity = latest_run(token)
    except StravaRateLimited:
        print("Rate limited (429)", file=sys.stderr)
        sys.exit(2)

    if activity is None:
        print("No recent running activity found", file=sys.stderr)
        sys.exit(1)

    print(str(activity["id"]))
    print(activity.get("start_date_local", "")[:10])
    print(activity.get("name", ""))


if __name__ == "__main__":
    main()
