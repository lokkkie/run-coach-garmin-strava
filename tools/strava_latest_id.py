"""
Cheap helper: print the latest Strava run's activity_id and date.
Mirrors tools/garmin_latest_id.py for symmetry.

Usage: python tools/strava_latest_id.py
Output (3 lines, stdout):
  <activity_id>
  <YYYY-MM-DD>
  <activity_name>

Exit codes:
  0  success
  1  auth / config error
  2  rate-limited (429); caller should back off
"""

import sys
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent))
from strava_auth import get_access_token  # noqa: E402

API_URL = "https://www.strava.com/api/v3/athlete/activities"


def main():
    try:
        token = get_access_token()
    except RuntimeError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)

    try:
        resp = requests.get(
            API_URL,
            headers={"Authorization": f"Bearer {token}"},
            params={"per_page": 5, "page": 1},
            timeout=20,
        )
    except requests.RequestException as e:
        print(f"ERROR: Strava request failed: {e}", file=sys.stderr)
        sys.exit(1)

    if resp.status_code == 429:
        print("Rate limited (429)", file=sys.stderr)
        sys.exit(2)
    if not resp.ok:
        print(f"ERROR: Strava {resp.status_code}: {resp.text}", file=sys.stderr)
        sys.exit(1)

    activities = resp.json()
    for a in activities:
        if a.get("type") == "Run" or a.get("sport_type") == "Run":
            print(str(a["id"]))
            print(a.get("start_date_local", "")[:10])
            print(a.get("name", ""))
            return

    print("No recent running activity found", file=sys.stderr)
    sys.exit(1)


if __name__ == "__main__":
    main()
