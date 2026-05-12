"""
Hourly polling check — detects new activities and prepares them for analysis.
Designed to run from Windows Task Scheduler. Exits silently when there's no new
activity for any user.

Per user, reads {data_dir}/coaching_state.json:data_source to pick Garmin
(default) or Strava. Override with --source garmin|strava for testing.

Garmin flow:
  1. Login to Garmin Connect (per-user credentials, or env fallback for owner),
     fetch latest activity.
  2. If new run: download .FIT to {data_dir}, run analyze_fit.py.
  3. Write {data_dir}/pending_analysis.json + send Telegram notification.

Strava flow:
  1. Call strava_latest_id.py --user <name> to get latest run ID.
  2. If new run: call strava_pull.py --user <name> to fetch + analyse.
  3. Write {data_dir}/pending_analysis.json + send Telegram notification.

Usage:
  python tools/polling_check.py                         # all users in allowlist
  python tools/polling_check.py --user Kevin            # one user
  python tools/polling_check.py --user Kevin --source strava
"""

import argparse
import json
import logging
import os
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from runcoach.paths import (  # noqa: E402
    PROJECT_ROOT,
    ALLOWLIST_PATH,
    data_dir_for,
    load_allowlist,
)
from runcoach.fit import extract_fit_bytes  # noqa: E402

QUIET = False

# A heartbeat gap longer than this means polling has been silent for a suspicious
# amount of time. Polling runs hourly, so 26h ≈ 26 missed cycles — well outside
# normal noise (battery, transient API failure) but tight enough to catch a
# multi-day Task Scheduler outage on the first resumed run.
HEARTBEAT_STALE_AFTER = timedelta(hours=26)


def log(msg: str):
    """Log with timestamp — useful when running under Task Scheduler."""
    if QUIET:
        return
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {msg}", flush=True)


def activity_in_run_log(data_dir: Path, activity_id: str) -> bool:
    """Source of truth for 'has this run been analyzed?' — reads run_log.json."""
    run_log = data_dir / "run_log.json"
    if not run_log.exists():
        return False
    try:
        with open(run_log, encoding="utf-8") as f:
            entries = json.load(f)
    except (json.JSONDecodeError, OSError):
        return False
    return any(str(e.get("activity_id", "")) == str(activity_id) for e in entries)


def set_last_analyzed_id(data_dir: Path, activity_id: str):
    """Convenience pointer; run_log.json is the canonical source."""
    data_dir.mkdir(parents=True, exist_ok=True)
    (data_dir / "last_analyzed_id.txt").write_text(activity_id, encoding="utf-8")


def read_heartbeat(data_dir: Path) -> datetime | None:
    """Read the last-successful-poll timestamp for a user, or None if absent/corrupt."""
    hb_file = data_dir / "polling_heartbeat.json"
    if not hb_file.exists():
        return None
    try:
        data = json.loads(hb_file.read_text(encoding="utf-8"))
        return datetime.fromisoformat(data["last_successful_poll"])
    except (json.JSONDecodeError, KeyError, ValueError, OSError):
        return None


def write_heartbeat(data_dir: Path, platform: str, now: datetime | None = None):
    """Record that this user's polling pipeline reached the platform successfully."""
    data_dir.mkdir(parents=True, exist_ok=True)
    ts = (now or datetime.now()).isoformat(timespec="seconds")
    (data_dir / "polling_heartbeat.json").write_text(
        json.dumps({"last_successful_poll": ts, "platform": platform}, indent=2),
        encoding="utf-8",
    )


def heartbeat_gap_hours(last: datetime | None, now: datetime | None = None) -> float | None:
    """Hours since the last successful poll, or None if no prior heartbeat."""
    if last is None:
        return None
    return (((now or datetime.now()) - last).total_seconds()) / 3600


def check_heartbeat_and_alert(user: dict, data_dir: Path, now: datetime | None = None):
    """If the user's last successful poll was longer ago than HEARTBEAT_STALE_AFTER,
    send a Telegram nudge so they know polling was silent. First-time-ever runs
    (no prior heartbeat) are not alerted on — there's nothing to compare against."""
    last = read_heartbeat(data_dir)
    gap_hours = heartbeat_gap_hours(last, now=now)
    if gap_hours is None:
        return
    threshold_hours = HEARTBEAT_STALE_AFTER.total_seconds() / 3600
    if gap_hours <= threshold_hours:
        return
    log(f"[{user['name']}] heartbeat gap: {gap_hours:.1f}h since last successful poll")
    send_telegram(
        f"⚠️ <b>Polling resumed after a gap</b>\n"
        f"Last successful check was <b>{gap_hours:.0f}h</b> ago. "
        f"If you didn't expect a quiet stretch (PC was on, network up), "
        f"check Task Scheduler history for failed runs.",
        user.get("chat_id"),
    )


def send_telegram(message: str, chat_id: str | int | None):
    """Best-effort Telegram notification. Silent failure if not configured."""
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not token or chat_id is None:
        return
    try:
        import requests
        requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat_id, "text": message, "parse_mode": "HTML"},
            timeout=10,
        )
    except Exception as e:
        log(f"Telegram notification failed: {e}")


def get_data_source(data_dir: Path) -> str:
    """Read data_source from {data_dir}/coaching_state.json. Defaults to 'garmin'."""
    state_file = data_dir / "coaching_state.json"
    if not state_file.exists():
        return "garmin"
    try:
        with open(state_file, encoding="utf-8") as f:
            state = json.load(f)
        return state.get("data_source", "garmin")
    except (json.JSONDecodeError, OSError):
        return "garmin"


def _post_ingest(user: dict, data_dir: Path, activity_id: str, date_str: str):
    """Common post-ingest logic shared by both Garmin and Strava paths.
    Reads run_analysis.json, writes pending_analysis.json, notifies via Telegram."""
    analysis_file = data_dir / "run_analysis.json"
    if not analysis_file.exists():
        log(f"[{user['name']}] WARN: run_analysis.json not produced.")
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
    pending_file = data_dir / "pending_analysis.json"
    pending_file.write_text(json.dumps(pending, indent=2), encoding="utf-8")
    log(f"[{user['name']}] Wrote {pending_file}")

    s = analysis["session"]
    source_label = analysis.get("source", "garmin").capitalize()
    notif = (
        f"🏃 <b>New run detected</b> ({source_label})\n"
        f"📅 {date_str}\n"
        f"📏 {s['distance_km']} km in {s['duration_min']} min\n"
        f"⚡ Avg pace: {s['avg_pace']}/km\n"
        f"❤️ Avg HR: {s['avg_hr']}  |  Max HR: {s['max_hr']}\n\n"
        f"Reply <i>analyze</i> for full coaching debrief."
    )
    send_telegram(notif, user.get("chat_id"))
    log(f"[{user['name']}] Telegram notification sent.")
    set_last_analyzed_id(data_dir, activity_id)


def _run_garmin(user: dict, data_dir: Path):
    """Garmin polling path — login, fetch latest activity, download .FIT, analyse."""
    # Import lazily so users without garminconnect installed can still run the
    # Strava-only path.
    sys.path.insert(0, str(PROJECT_ROOT / "tools"))
    from garmin_auth import get_garmin_client  # noqa: E402

    name = user["name"]
    log(f"[{name}] Starting Garmin polling check...")

    try:
        client = get_garmin_client(name)
    except SystemExit:
        # garmin_auth already logged the error; skip this user, don't kill the loop.
        log(f"[{name}] Garmin credentials unavailable; skipping.")
        return
    except Exception as e:
        msg = str(e)
        if "429" in msg or "rate limit" in msg.lower():
            log(f"[{name}] Rate limited by Garmin (429). Will retry next hour.")
            return
        log(f"[{name}] Garmin login failed: {e}")
        return

    try:
        activities = client.get_activities(0, 1)
    except Exception as e:
        log(f"[{name}] Failed to fetch activities: {e}")
        return

    # We talked to Garmin successfully — pipeline is alive. Record the heartbeat
    # even if there's no new run to analyse.
    write_heartbeat(data_dir, platform="garmin")

    if not activities:
        log(f"[{name}] No activities found.")
        return

    latest = activities[0]
    if latest.get("activityType", {}).get("typeKey", "") != "running":
        log(f"[{name}] Latest activity is not a run ({latest.get('activityName', '')}). Skipping.")
        return

    activity_id = str(latest["activityId"])
    date_str = latest.get("startTimeLocal", "")[:10] or "unknown"

    if activity_in_run_log(data_dir, activity_id):
        log(f"[{name}] Latest run ({activity_id}, {date_str}) already in run_log.json. Nothing to do.")
        set_last_analyzed_id(data_dir, activity_id)
        return

    log(f"[{name}] NEW run detected: activity_id={activity_id}, date={date_str}")

    try:
        raw = client.download_activity(
            activity_id, dl_fmt=client.ActivityDownloadFormat.ORIGINAL
        )
        fit_data = extract_fit_bytes(raw)
    except Exception as e:
        log(f"[{name}] FIT download failed: {e}")
        return

    data_dir.mkdir(parents=True, exist_ok=True)
    fit_path = data_dir / f"run_{date_str}.fit"
    fit_path.write_bytes(fit_data)

    (data_dir / "last_activity_id.txt").write_text(
        f"{activity_id}\n{date_str}\n{fit_path}\n", encoding="utf-8"
    )
    log(f"[{name}] Saved {len(fit_data):,} bytes to {fit_path}")

    log(f"[{name}] Running analyze_fit...")
    result = subprocess.run(
        [sys.executable, str(PROJECT_ROOT / "tools" / "analyze_fit.py"),
         "--file", str(fit_path), "--activity-id", activity_id,
         "--user", name, "--quiet"],
        capture_output=True, text=True, cwd=str(PROJECT_ROOT),
    )
    if result.returncode != 0:
        log(f"[{name}] analyze_fit failed: {result.stderr}")
        return
    log(f"[{name}] {result.stdout.strip()}")

    _post_ingest(user, data_dir, activity_id, date_str)


def _run_strava(user: dict, data_dir: Path):
    """Strava polling path — call strava_latest_id, dedup, call strava_pull if new."""
    name = user["name"]
    log(f"[{name}] Starting Strava polling check...")

    id_result = subprocess.run(
        [sys.executable, str(PROJECT_ROOT / "tools" / "strava_latest_id.py"),
         "--user", name],
        capture_output=True, text=True, cwd=str(PROJECT_ROOT),
    )
    if id_result.returncode == 2:
        log(f"[{name}] Rate limited by Strava (429). Will retry next hour.")
        return
    if id_result.returncode != 0:
        log(f"[{name}] strava_latest_id failed: {id_result.stderr.strip()}")
        return

    lines = id_result.stdout.strip().splitlines()
    if not lines:
        log(f"[{name}] strava_latest_id returned no output.")
        return

    # We talked to Strava successfully — pipeline is alive.
    write_heartbeat(data_dir, platform="strava")

    activity_id = lines[0].strip()
    date_str = lines[1].strip() if len(lines) > 1 else "unknown"
    activity_name = lines[2].strip() if len(lines) > 2 else ""
    log(f"[{name}] Latest Strava run: {activity_id} ({date_str}) — {activity_name}")

    if activity_in_run_log(data_dir, activity_id):
        log(f"[{name}] Latest run ({activity_id}, {date_str}) already in run_log.json. Nothing to do.")
        set_last_analyzed_id(data_dir, activity_id)
        return

    log(f"[{name}] NEW run detected: activity_id={activity_id}, date={date_str}")

    pull_result = subprocess.run(
        [sys.executable, str(PROJECT_ROOT / "tools" / "strava_pull.py"),
         "--activity-id", activity_id, "--user", name, "--quiet"],
        capture_output=True, text=True, cwd=str(PROJECT_ROOT),
    )
    if pull_result.returncode != 0:
        log(f"[{name}] strava_pull failed: {pull_result.stderr.strip()}")
        return
    log(f"[{name}] {pull_result.stdout.strip()}")

    _post_ingest(user, data_dir, activity_id, date_str)


def poll_user(user: dict, source_override: str | None):
    """Poll a single user. Errors are logged but don't propagate — one user's
    bad credentials or rate limit shouldn't abort the rest of the loop."""
    data_dir = data_dir_for(user)
    check_heartbeat_and_alert(user, data_dir)
    source = source_override or get_data_source(data_dir)
    log(f"[{user['name']}] data_source: {source}")

    if source == "strava":
        _run_strava(user, data_dir)
    elif source == "garmin":
        _run_garmin(user, data_dir)
    elif source == "manual":
        log(f"[{user['name']}] data_source=manual — skipping (user is on manual logging).")
    else:
        log(f"[{user['name']}] unknown data_source: {source!r} — skipping.")


def main():
    parser = argparse.ArgumentParser(description="Hourly polling check (Garmin or Strava)")
    parser.add_argument("--quiet", action="store_true", help="Suppress non-error stdout")
    parser.add_argument("--source", choices=["garmin", "strava"], default=None,
                        help="Override data source (default: read from each user's coaching_state.json)")
    parser.add_argument("--user", default=None,
                        help="Poll only this user (default: iterate every user in allowlist)")
    args = parser.parse_args()

    global QUIET
    QUIET = args.quiet
    if QUIET:
        for name in ("garminconnect", "garth", "urllib3"):
            logging.getLogger(name).setLevel(logging.ERROR)

    allowlist = load_allowlist()
    if args.user:
        users = [u for u in allowlist if u["name"] == args.user]
        if not users:
            print(f"ERROR: user '{args.user}' not in allowlist", file=sys.stderr)
            sys.exit(1)
    else:
        users = allowlist

    for user in users:
        try:
            poll_user(user, args.source)
        except Exception as e:
            log(f"[{user.get('name', '?')}] polling failed: {e}")
            # next user
    log("Done.")


if __name__ == "__main__":
    main()
