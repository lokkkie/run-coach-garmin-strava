"""
Fetch personal records (PRs) from Garmin Connect and save as JSON.
Usage: python tools/garmin_fetch_prs.py [--quiet] [--user Nicolas]
Output: {data_dir}/personal_records.json
"""

import argparse
import json
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from garminconnect import Garmin

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from runcoach.paths import data_dir as _data_dir  # noqa: E402
from runcoach.garmin import get_garmin_client  # noqa: E402

QUIET = False


def info(msg):
    if not QUIET:
        print(msg)


# Garmin's PR typeId mapping for running. Unknown ids are passed through
# with a generic label so we never silently drop a record.
RUNNING_PR_LABELS = {
    1: "1k",
    2: "1mi",
    3: "5k",
    4: "10k",
    5: "half_marathon",
    6: "marathon",
    7: "longest_run_km",
    8: "longest_ride_km",
    12: "fastest_50k",
    13: "fastest_100k",
}

# Type ids whose value is a duration (seconds) vs a distance (meters).
DISTANCE_TYPE_IDS = {7, 8}


def fmt_time(seconds: float) -> str:
    """Convert seconds → H:MM:SS or M:SS string."""
    if seconds is None:
        return None
    s = int(round(seconds))
    h, rem = divmod(s, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def parse_record(raw: dict) -> dict:
    type_id = raw.get("typeId")
    label = RUNNING_PR_LABELS.get(type_id, f"type_{type_id}")
    value = raw.get("value")
    activity_id = raw.get("activityId")
    start_str = (
        raw.get("actStartDateTimeInGMTFormatted")
        or raw.get("prStartTimeGmtFormatted")
        or raw.get("activityStartDateTimeLocalFormatted")
    )

    record = {
        "label": label,
        "type_id": type_id,
        "activity_id": activity_id,
        "activity_name": raw.get("activityName"),
        "date": start_str[:10] if isinstance(start_str, str) else None,
    }

    if type_id in DISTANCE_TYPE_IDS:
        # value is in meters
        record["distance_km"] = round(value / 1000, 2) if value else None
    else:
        # value is in seconds
        record["time_seconds"] = round(value, 1) if value else None
        record["time"] = fmt_time(value)

    return record


def main():
    parser = argparse.ArgumentParser(description="Fetch Garmin personal records as JSON")
    parser.add_argument("--quiet", action="store_true", help="Suppress non-error stdout")
    parser.add_argument("--user", default=None, help="User name for per-user credentials and output path (e.g. Nicolas)")
    args = parser.parse_args()

    global QUIET
    QUIET = args.quiet
    if QUIET:
        for name in ("garminconnect", "garth", "urllib3"):
            logging.getLogger(name).setLevel(logging.ERROR)

    info("Logging in to Garmin Connect...")
    client = get_garmin_client(args.user)

    info("Fetching personal records...")
    raw_records = client.get_personal_record()

    records = [parse_record(r) for r in raw_records if r.get("value")]
    # Filter to well-known running PR types only. Garmin returns some
    # ambiguous types (14/15/16) that look like cumulative stats rather than
    # race-pace PRs — drop them rather than confuse downstream consumers.
    running_records = [r for r in records if r["type_id"] in RUNNING_PR_LABELS]
    running_records.sort(key=lambda r: r["type_id"] if r["type_id"] else 999)

    output = {
        "fetched_date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "records": running_records,
    }

    out_file = _data_dir(args.user) / "personal_records.json"
    out_file.parent.mkdir(parents=True, exist_ok=True)
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2)

    if QUIET:
        print(f"OK {len(running_records)} records {out_file}")
    else:
        print(f"Saved {len(running_records)} personal records to {out_file}")
        for r in running_records:
            label = r["label"]
            if "time" in r:
                print(f"  {label}: {r['time']} ({r.get('date')})")
            else:
                print(f"  {label}: {r.get('distance_km')} km ({r.get('date')})")


if __name__ == "__main__":
    main()
