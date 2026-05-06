"""
Hourly polling check — detects new activities and prepares them for analysis.
Designed to run from Windows Task Scheduler. Exits silently when there's no new activity.

Reads coaching_state.json:data_source to pick Garmin (default) or Strava.
Override with --source garmin|strava for testing.

Garmin flow:
  1. Login to Garmin Connect, fetch latest activity
  2. If new run: download .FIT, run analyze_fit.py
  3. Write pending_analysis.json + send Telegram notification

Strava flow:
  1. Call strava_latest_id.py to get latest run ID
  2. If new run: call strava_pull.py to fetch + analyse
  3. Write pending_analysis.json + send Telegram notification

Usage: python tools/polling_check.py [--quiet] [--source garmin|strava]
"""

import argparse
import io
import json
import logging
import os
import subprocess
import sys
import zipfile
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

QUIET = False


def extract_fit_bytes(raw: bytes) -> bytes:
    """Garmin's ORIGINAL download format returns a ZIP containing the .FIT.
    If raw starts with the ZIP magic bytes, extract the first .fit member."""
    if raw[:4] == b"PK\x03\x04":
        with zipfile.ZipFile(io.BytesIO(raw)) as zf:
            fit_names = [n for n in zf.namelist() if n.lower().endswith(".fit")]
            if not fit_names:
                raise RuntimeError(
                    f"No .fit file in ZIP archive. Members: {zf.namelist()}"
                )
            return zf.read(fit_names[0])
    return raw


PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(PROJECT_ROOT / ".env")

TMP_DIR = PROJECT_ROOT / ".tmp"
LAST_ANALYZED_FILE = TMP_DIR / "last_analyzed_id.txt"   # legacy pointer; kept for backward compat
PENDING_FILE = TMP_DIR / "pending_analysis.json"
RUN_LOG_FILE = TMP_DIR / "run_log.json"
STATE_FILE = TMP_DIR / "coaching_state.json"


def log(msg: str):
    """Log with timestamp — useful when running under Task Scheduler."""
    if QUIET:
        return
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {msg}", flush=True)


def activity_in_run_log(activity_id: str) -> bool:
    """Source of truth for 'has this run been analyzed?' — reads run_log.json."""
    if not RUN_LOG_FILE.exists():
        return False
    try:
        with open(RUN_LOG_FILE, encoding="utf-8") as f:
            entries = json.load(f)
    except (json.JSONDecodeError, OSError):
        return False
    return any(str(e.get("activity_id", "")) == str(activity_id) for e in entries)


def set_last_analyzed_id(activity_id: str):
    """Convenience pointer; run_log.json is the canonical source."""
    TMP_DIR.mkdir(exist_ok=True)
    LAST_ANALYZED_FILE.write_text(activity_id, encoding="utf-8")


def send_telegram(message: str):
    """Best-effort Telegram notification. Silent failure if not configured."""
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        return
    try:
        import requests
        requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat_id, "text": message, "parse_mode": "Markdown"},
            timeout=10,
        )
    except Exception as e:
        log(f"Telegram notification failed: {e}")


def _get_data_source() -> str:
    """Read data_source from coaching_state.json. Defaults to 'garmin'."""
    if not STATE_FILE.exists():
        return "garmin"
    try:
        with open(STATE_FILE, encoding="utf-8") as f:
            state = json.load(f)
        return state.get("data_source", "garmin")
    except (json.JSONDecodeError, OSError):
        return "garmin"


def _post_ingest(activity_id: str, date_str: str):
    """Common post-ingest logic shared by both Garmin and Strava paths.
    Reads run_analysis.json, writes pending_analysis.json, notifies via Telegram."""
    analysis_file = TMP_DIR / "run_analysis.json"
    if not analysis_file.exists():
        log("WARN: run_analysis.json not produced.")
        return
    with open(analysis_file, encoding="utf-8") as f:
        analysis = json.load(f)

    pending = {
        "detected_at": datetime.now().isoformat(),
        "activity_id": activity_id,
        "date": date_str,
        "session_summary": {
            "distance_km": analysis["session"]["distance_km"],
            "duration_min": analysis["session"]["duration_min"],
            "avg_pace": analysis["session"]["avg_pace"],
            "avg_hr": analysis["session"]["avg_hr"],
            "max_hr": analysis["session"]["max_hr"],
            "cadence_spm": analysis["session"]["avg_cadence_spm"],
        },
        "analysis_complete": False,
    }
    PENDING_FILE.write_text(json.dumps(pending, indent=2), encoding="utf-8")
    log(f"Wrote {PENDING_FILE}")

    s = analysis["session"]
    source_label = analysis.get("source", "garmin").capitalize()
    notif = (
        f"🏃 *New run detected* ({source_label})\n"
        f"📅 {date_str}\n"
        f"📏 {s['distance_km']} km in {s['duration_min']} min\n"
        f"⚡ Avg pace: {s['avg_pace']}/km\n"
        f"❤️ Avg HR: {s['avg_hr']}  |  Max HR: {s['max_hr']}\n\n"
        f"Reply *analyze* for full coaching debrief."
    )
    send_telegram(notif)
    log("Telegram notification sent.")
    set_last_analyzed_id(activity_id)
    log("Done.")


def _run_garmin():
    """Garmin polling path — login, fetch latest activity, download .FIT, analyse."""
    from garminconnect import Garmin

    email = os.getenv("GARMIN_EMAIL")
    password = os.getenv("GARMIN_PASSWORD")
    if not email or not password:
        print("ERROR: GARMIN_EMAIL / GARMIN_PASSWORD missing in .env", file=sys.stderr)
        sys.exit(1)

    log("Starting Garmin polling check...")

    try:
        client = Garmin(email, password)
        client.login()
    except Exception as e:
        msg = str(e)
        if "429" in msg or "rate limit" in msg.lower():
            log("Rate limited by Garmin (429). Will retry next hour.")
            sys.exit(0)
        log(f"Garmin login failed: {e}")
        sys.exit(2)

    try:
        activities = client.get_activities(0, 1)
    except Exception as e:
        log(f"Failed to fetch activities: {e}")
        sys.exit(2)

    if not activities:
        log("No activities found.")
        return

    latest = activities[0]
    if latest.get("activityType", {}).get("typeKey", "") != "running":
        log(f"Latest activity is not a run ({latest.get('activityName', '')}). Skipping.")
        return

    activity_id = str(latest["activityId"])
    date_str = latest.get("startTimeLocal", "")[:10] or "unknown"

    if activity_in_run_log(activity_id):
        log(f"Latest run ({activity_id}, {date_str}) already in run_log.json. Nothing to do.")
        set_last_analyzed_id(activity_id)
        return

    log(f"NEW run detected: activity_id={activity_id}, date={date_str}")

    try:
        raw = client.download_activity(
            activity_id, dl_fmt=client.ActivityDownloadFormat.ORIGINAL
        )
        fit_data = extract_fit_bytes(raw)
    except Exception as e:
        log(f"FIT download failed: {e}")
        sys.exit(2)

    fit_path = TMP_DIR / f"run_{date_str}.fit"
    TMP_DIR.mkdir(exist_ok=True)
    fit_path.write_bytes(fit_data)

    (TMP_DIR / "last_activity_id.txt").write_text(
        f"{activity_id}\n{date_str}\n{fit_path}\n", encoding="utf-8"
    )
    log(f"Saved {len(fit_data):,} bytes to {fit_path}")

    log("Running analyze_fit...")
    result = subprocess.run(
        [sys.executable, str(PROJECT_ROOT / "tools" / "analyze_fit.py"),
         "--file", str(fit_path), "--activity-id", activity_id, "--quiet"],
        capture_output=True, text=True, cwd=str(PROJECT_ROOT),
    )
    if result.returncode != 0:
        log(f"analyze_fit failed: {result.stderr}")
        sys.exit(2)
    log(result.stdout.strip())

    _post_ingest(activity_id, date_str)


def _run_strava():
    """Strava polling path — call strava_latest_id, dedup, call strava_pull if new."""
    log("Starting Strava polling check...")

    id_result = subprocess.run(
        [sys.executable, str(PROJECT_ROOT / "tools" / "strava_latest_id.py")],
        capture_output=True, text=True, cwd=str(PROJECT_ROOT),
    )
    if id_result.returncode == 2:
        log("Rate limited by Strava (429). Will retry next hour.")
        sys.exit(0)
    if id_result.returncode != 0:
        log(f"strava_latest_id failed: {id_result.stderr.strip()}")
        sys.exit(2)

    lines = id_result.stdout.strip().splitlines()
    if not lines:
        log("strava_latest_id returned no output.")
        return

    activity_id = lines[0].strip()
    date_str = lines[1].strip() if len(lines) > 1 else "unknown"
    name = lines[2].strip() if len(lines) > 2 else ""
    log(f"Latest Strava run: {activity_id} ({date_str}) — {name}")

    if activity_in_run_log(activity_id):
        log(f"Latest run ({activity_id}, {date_str}) already in run_log.json. Nothing to do.")
        set_last_analyzed_id(activity_id)
        return

    log(f"NEW run detected: activity_id={activity_id}, date={date_str}")

    pull_result = subprocess.run(
        [sys.executable, str(PROJECT_ROOT / "tools" / "strava_pull.py"),
         "--activity-id", activity_id, "--quiet"],
        capture_output=True, text=True, cwd=str(PROJECT_ROOT),
    )
    if pull_result.returncode != 0:
        log(f"strava_pull failed: {pull_result.stderr.strip()}")
        sys.exit(2)
    log(pull_result.stdout.strip())

    _post_ingest(activity_id, date_str)


def main():
    parser = argparse.ArgumentParser(description="Hourly polling check (Garmin or Strava)")
    parser.add_argument("--quiet", action="store_true", help="Suppress non-error stdout")
    parser.add_argument("--source", choices=["garmin", "strava"], default=None,
                        help="Override data source (default: read from coaching_state.json)")
    args = parser.parse_args()

    global QUIET
    QUIET = args.quiet
    if QUIET:
        for name in ("garminconnect", "garth", "urllib3"):
            logging.getLogger(name).setLevel(logging.ERROR)

    source = args.source or _get_data_source()
    log(f"Data source: {source}")

    if source == "strava":
        _run_strava()
    else:
        _run_garmin()


if __name__ == "__main__":
    main()
