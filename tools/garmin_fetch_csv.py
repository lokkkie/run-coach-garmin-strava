"""
Fetch the last N days of running activities from Garmin Connect and save as CSV.
Usage: python tools/garmin_fetch_csv.py [--days 90] [--user Nicolas]
Output: {data_dir}/run_history.csv
"""

import argparse
import csv
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from dotenv import load_dotenv
from garminconnect import Garmin

from garmin_auth import get_garmin_client, _data_dir

load_dotenv()

FIELDNAMES = [
    "date",
    "activity_id",
    "activity_name",
    "distance_km",
    "duration_min",
    "avg_pace_min_per_km",
    "avg_hr",
    "max_hr",
    "avg_cadence",
    "elevation_gain_m",
    "calories",
    "training_effect_aerobic",
]


def pace_from_speed(speed_m_per_s: float) -> str:
    """Convert m/s to mm:ss per km string. Returns '' if speed is 0."""
    if not speed_m_per_s:
        return ""
    sec_per_km = 1000 / speed_m_per_s
    mins = int(sec_per_km // 60)
    secs = int(sec_per_km % 60)
    return f"{mins}:{secs:02d}"


def fetch_activities(client: Garmin, days: int) -> list[dict]:
    start_date = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%d")
    end_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    print(f"Fetching activities from {start_date} to {end_date}...")
    activities = client.get_activities_by_date(start_date, end_date, "running")
    print(f"Found {len(activities)} running activities.")
    return activities


def parse_activity(raw: dict) -> dict:
    distance_m = raw.get("distance") or 0
    duration_s = raw.get("duration") or 0
    speed = raw.get("averageSpeed") or 0

    return {
        "date": raw.get("startTimeLocal", "")[:10],
        "activity_id": raw.get("activityId", ""),
        "activity_name": raw.get("activityName", ""),
        "distance_km": round(distance_m / 1000, 2) if distance_m else "",
        "duration_min": round(duration_s / 60, 1) if duration_s else "",
        "avg_pace_min_per_km": pace_from_speed(speed),
        "avg_hr": raw.get("averageHR", ""),
        "max_hr": raw.get("maxHR", ""),
        "avg_cadence": raw.get("averageRunningCadenceInStepsPerMinute", ""),
        "elevation_gain_m": raw.get("elevationGain", ""),
        "calories": raw.get("calories", ""),
        "training_effect_aerobic": raw.get("aerobicTrainingEffect", ""),
    }


def main():
    parser = argparse.ArgumentParser(description="Fetch Garmin running history as CSV")
    parser.add_argument("--days", type=int, default=90, help="Number of days to look back (default: 90)")
    parser.add_argument("--user", default=None, help="User name for per-user credentials and output path (e.g. Nicolas)")
    args = parser.parse_args()

    print("Logging in to Garmin Connect...")
    client = get_garmin_client(args.user)

    activities = fetch_activities(client, args.days)
    rows = [parse_activity(a) for a in activities]
    rows.sort(key=lambda r: r["date"])

    out_file = _data_dir(args.user) / "run_history.csv"
    out_file.parent.mkdir(parents=True, exist_ok=True)
    with open(out_file, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDNAMES)
        writer.writeheader()
        writer.writerows(rows)

    print(f"Saved {len(rows)} activities to {out_file}")


if __name__ == "__main__":
    main()
