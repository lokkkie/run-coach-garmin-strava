"""
Fetch the last N nights of sleep + RHR + HRV from Garmin Connect and save as JSON.
Usage: python tools/garmin_fetch_sleep.py [--days 35] [--user Nicolas]
Output: {data_dir}/sleep_log.json
"""

import argparse
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from dotenv import load_dotenv
from garminconnect import Garmin

from garmin_auth import get_garmin_client, _data_dir

load_dotenv()


def parse_night(date_str: str, raw: dict) -> dict:
    """Normalize Garmin's sleep response into a flat per-night record.

    Garmin nests fields under 'dailySleepDTO' and reports HRV/RHR in adjacent
    blocks that may be missing on older watches — flatten and null-fill so
    consumers get a stable shape.
    """
    if not raw:
        return {"date": date_str, "reason": "no_data"}

    sleep_dto = raw.get("dailySleepDTO") or {}

    # Reject sleep windows that ended too recently to be considered final.
    sleep_end = sleep_dto.get("sleepEndTimestampGMT")
    if sleep_dto.get("sleepWindowConfirmationType") == "PRELIMINARY" or not sleep_end:
        if not sleep_dto.get("sleepTimeSeconds"):
            return {"date": date_str, "reason": "not_yet_recorded"}

    total_sec = sleep_dto.get("sleepTimeSeconds")
    if not total_sec:
        return {"date": date_str, "reason": "no_data"}

    def _min(seconds):
        return round(seconds / 60) if seconds else None

    rhr_block = raw.get("restingHeartRate") or sleep_dto.get("restingHeartRate")
    hrv_block = raw.get("hrvData") or {}
    hrv_avg = None
    if isinstance(hrv_block, dict):
        hrv_avg = (
            hrv_block.get("lastNightAvg")
            or hrv_block.get("avgOvernightHrv")
            or hrv_block.get("weeklyAvg")
        )

    sleep_score = None
    scores = sleep_dto.get("sleepScores") or {}
    if isinstance(scores, dict):
        overall = scores.get("overall") or {}
        sleep_score = overall.get("value") if isinstance(overall, dict) else overall

    return {
        "date": date_str,
        "total_sleep_minutes": _min(total_sec),
        "deep_sleep_minutes": _min(sleep_dto.get("deepSleepSeconds")),
        "light_sleep_minutes": _min(sleep_dto.get("lightSleepSeconds")),
        "rem_minutes": _min(sleep_dto.get("remSleepSeconds")),
        "awake_minutes": _min(sleep_dto.get("awakeSleepSeconds")),
        "sleep_score": sleep_score,
        "resting_hr_overnight": rhr_block if isinstance(rhr_block, int) else None,
        "hrv_overnight_avg": hrv_avg,
    }


def fetch_nights(client: Garmin, days: int) -> list[dict]:
    today = datetime.now(timezone.utc).date()
    nights: list[dict] = []

    for offset in range(days):
        target = today - timedelta(days=offset)
        date_str = target.strftime("%Y-%m-%d")

        if target == today:
            # Today's sleep is recorded against last night's date — skip the
            # in-progress entry to avoid mixing partial data.
            continue

        try:
            raw = client.get_sleep_data(date_str)
        except Exception as exc:
            print(f"  {date_str}: fetch failed ({exc.__class__.__name__})", file=sys.stderr)
            nights.append({"date": date_str, "reason": "fetch_error"})
            continue

        nights.append(parse_night(date_str, raw))

    return nights


def main():
    parser = argparse.ArgumentParser(description="Fetch Garmin nightly sleep / RHR / HRV as JSON")
    parser.add_argument(
        "--days",
        type=int,
        default=35,
        help="Number of nights to look back (default: 35 — covers 7d window + 28d baseline)",
    )
    parser.add_argument("--user", default=None, help="User name for per-user credentials and output path (e.g. Nicolas)")
    args = parser.parse_args()

    print("Logging in to Garmin Connect...")
    client = get_garmin_client(args.user)

    print(f"Fetching last {args.days} nights of sleep data...")
    nights = fetch_nights(client, args.days)
    nights.sort(key=lambda n: n["date"], reverse=True)

    output = {
        "fetched_date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "days_requested": args.days,
        "nights": nights,
    }

    out_file = _data_dir(args.user) / "sleep_log.json"
    out_file.parent.mkdir(parents=True, exist_ok=True)
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2)

    valid = sum(1 for n in nights if "total_sleep_minutes" in n)
    print(f"Saved {valid}/{len(nights)} nights with sleep data to {out_file}")


if __name__ == "__main__":
    main()
