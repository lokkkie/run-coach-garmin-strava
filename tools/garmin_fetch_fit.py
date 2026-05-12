"""
Download the .FIT file for the latest (or a specific) Garmin running activity.
Usage:
  python tools/garmin_fetch_fit.py                        # latest running activity
  python tools/garmin_fetch_fit.py --activity-id 12345678
  python tools/garmin_fetch_fit.py --user Nicolas
Output: {data_dir}/run_YYYY-MM-DD.fit
        {data_dir}/last_activity_id.txt  (records the activity ID for downstream tools)
"""

import argparse
import io
import logging
import os
import sys
import zipfile
from pathlib import Path

from garminconnect import Garmin

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from runcoach.paths import data_dir as _data_dir  # noqa: E402
from garmin_auth import get_garmin_client  # noqa: E402

QUIET = False


def info(msg):
    if not QUIET:
        print(msg)


def extract_fit_bytes(raw: bytes) -> bytes:
    """Garmin's ORIGINAL download format returns a ZIP containing the .FIT.
    If raw starts with the ZIP magic bytes, extract the first .fit member.
    Otherwise (rare — older endpoints) return raw as-is."""
    if raw[:4] == b"PK\x03\x04":
        with zipfile.ZipFile(io.BytesIO(raw)) as zf:
            fit_names = [n for n in zf.namelist() if n.lower().endswith(".fit")]
            if not fit_names:
                raise RuntimeError(
                    f"No .fit file in ZIP archive. Members: {zf.namelist()}"
                )
            return zf.read(fit_names[0])
    return raw


def get_latest_run_id(client: Garmin) -> tuple[str, str]:
    """Return (activity_id, date_str) for the most recent running activity."""
    activities = client.get_activities(0, 10)
    for a in activities:
        if a.get("activityType", {}).get("typeKey", "") == "running":
            return str(a["activityId"]), a.get("startTimeLocal", "unknown")[:10]
    raise RuntimeError("No recent running activities found in the last 10 activities.")


def main():
    parser = argparse.ArgumentParser(description="Download Garmin .FIT file")
    parser.add_argument("--activity-id", type=str, default=None, help="Specific activity ID to download")
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

    data_dir = _data_dir(args.user)

    if args.activity_id:
        activity_id = args.activity_id
        details = client.get_activity(activity_id)
        date_str = details.get("summaryDTO", {}).get("startTimeLocal", "unknown")[:10]
    else:
        info("Finding latest running activity...")
        activity_id, date_str = get_latest_run_id(client)

    info(f"Downloading .FIT for activity {activity_id} ({date_str})...")
    raw = client.download_activity(activity_id, dl_fmt=client.ActivityDownloadFormat.ORIGINAL)
    fit_data = extract_fit_bytes(raw)

    data_dir.mkdir(parents=True, exist_ok=True)
    out_file = data_dir / f"run_{date_str}.fit"
    with open(out_file, "wb") as f:
        f.write(fit_data)

    # Record the activity ID and output path for downstream tools
    (data_dir / "last_activity_id.txt").write_text(f"{activity_id}\n{date_str}\n{out_file}\n")

    if QUIET:
        print(f"OK {activity_id} {out_file}")
    else:
        print(f"Saved {len(fit_data):,} bytes to {out_file}")
        print(f"Activity ID: {activity_id}")


if __name__ == "__main__":
    main()
