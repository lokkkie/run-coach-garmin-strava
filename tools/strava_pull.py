"""
Pull a Strava activity (latest run by default) and produce run_analysis.json
in the same schema as analyze_fit.py — so all downstream code is source-agnostic.

Usage:
  python tools/strava_pull.py [--quiet] [--activity-id <ID>]

Output:
  .tmp/run_analysis.json     (full analysis)
  .tmp/run_log.json          (appended with source=strava)
"""

import argparse
import json
import sys
import time
from pathlib import Path

import requests
from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parent))
from strava_auth import get_access_token  # noqa: E402

PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(PROJECT_ROOT / ".env")


def _data_dir(user: str | None) -> Path:
    if user:
        return PROJECT_ROOT / "users" / user / "data"
    return PROJECT_ROOT / ".tmp"

API_BASE = "https://www.strava.com/api/v3"

HR_ZONE_BOUNDARIES = [0.50, 0.60, 0.70, 0.80, 0.90, 1.0]


def pace_from_speed(speed_m_per_s: float) -> str:
    if not speed_m_per_s or speed_m_per_s <= 0:
        return ""
    sec_per_km = 1000 / speed_m_per_s
    mins = int(sec_per_km // 60)
    secs = int(sec_per_km % 60)
    return f"{mins}:{secs:02d}"


def pace_from_distance_time(distance_m: float, time_s: float) -> str:
    if not distance_m or not time_s or distance_m <= 0 or time_s <= 0:
        return ""
    return pace_from_speed(distance_m / time_s)


def get_hr_zone(hr: float, max_hr: float) -> int:
    if not hr or not max_hr:
        return 0
    pct = hr / max_hr
    for i, boundary in enumerate(HR_ZONE_BOUNDARIES[1:], start=1):
        if pct <= boundary:
            return i
    return 5


# ──────────────────────────────────────────────────────────────────────
# Strava API calls
# ──────────────────────────────────────────────────────────────────────
def _api_get(path: str, token: str, params: dict | None = None) -> dict:
    resp = requests.get(
        f"{API_BASE}{path}",
        headers={"Authorization": f"Bearer {token}"},
        params=params,
        timeout=30,
    )
    if resp.status_code == 429:
        raise RuntimeError("Strava rate-limited (429)")
    resp.raise_for_status()
    return resp.json()


def fetch_latest_run_id(token: str) -> str:
    activities = _api_get("/athlete/activities", token, {"per_page": 5})
    for a in activities:
        if a.get("type") == "Run" or a.get("sport_type") == "Run":
            return str(a["id"])
    raise RuntimeError("No recent running activity found on Strava")


# ──────────────────────────────────────────────────────────────────────
# Schema mapping: Strava JSON → run_analysis.json
# ──────────────────────────────────────────────────────────────────────
def build_session(activity: dict) -> dict:
    distance_m = activity.get("distance") or 0
    elapsed_s = activity.get("elapsed_time") or 0
    max_speed = activity.get("max_speed") or 0
    avg_cadence = activity.get("average_cadence")  # single-foot cadence (per min)

    return {
        "distance_km": round(distance_m / 1000, 2),
        "duration_min": round(elapsed_s / 60, 1),
        "avg_pace": pace_from_distance_time(distance_m, elapsed_s),
        "max_pace": pace_from_speed(max_speed),
        "avg_hr": activity.get("average_heartrate"),
        "max_hr": activity.get("max_heartrate"),
        "avg_cadence_spm": (avg_cadence or 0) * 2 or None,
        "elevation_gain_m": activity.get("total_elevation_gain"),
        "calories": activity.get("calories"),
        "training_effect_aerobic": None,   # Strava doesn't provide
        "vo2max_estimate": None,           # Strava doesn't provide
    }


def build_patterns(streams: dict, max_hr: float | None) -> dict:
    hr_data = (streams.get("heartrate") or {}).get("data") or []
    velocity_data = (streams.get("velocity_smooth") or {}).get("data") or []

    cardiac_decoupling_pct = None
    if len(hr_data) >= 20:
        mid = len(hr_data) // 2
        first_avg = sum(hr_data[:mid]) / mid
        second_avg = sum(hr_data[mid:]) / (len(hr_data) - mid)
        if first_avg:
            cardiac_decoupling_pct = round(
                ((second_avg - first_avg) / first_avg) * 100, 1
            )

    pacing_discipline_pct = None
    if len(velocity_data) >= 10:
        early = velocity_data[: max(1, len(velocity_data) // 5)]
        avg_speed = sum(velocity_data) / len(velocity_data)
        early_avg = sum(early) / len(early)
        if avg_speed:
            pacing_discipline_pct = round(
                ((early_avg - avg_speed) / avg_speed) * 100, 1
            )

    hr_zone_distribution = {1: 0, 2: 0, 3: 0, 4: 0, 5: 0}
    if max_hr and hr_data:
        for hr in hr_data:
            zone = get_hr_zone(hr, max_hr)
            if 1 <= zone <= 5:
                hr_zone_distribution[zone] += 1
        total = len(hr_data)
        hr_zone_distribution = {
            z: round(c / total * 100, 1) for z, c in hr_zone_distribution.items()
        }

    return {
        "cardiac_decoupling_pct": cardiac_decoupling_pct,
        "pacing_discipline_pct": pacing_discipline_pct,
        "negative_split": None,  # filled in after lap parsing
        "hr_zone_distribution_pct": hr_zone_distribution,
    }


def build_laps(laps: list[dict]) -> tuple[list[dict], bool | None]:
    splits = []
    for i, lap in enumerate(laps, start=1):
        lap_dist = lap.get("distance") or 0
        lap_time = lap.get("elapsed_time") or 0
        avg_cad = lap.get("average_cadence")
        splits.append({
            "lap": i,
            "distance_km": round(lap_dist / 1000, 3),
            "duration_min": round(lap_time / 60, 2),
            "pace": pace_from_distance_time(lap_dist, lap_time),
            "avg_hr": lap.get("average_heartrate"),
            "max_hr": lap.get("max_heartrate"),
            "avg_cadence_spm": (avg_cad or 0) * 2 or None,
            "elevation_gain_m": lap.get("total_elevation_gain"),
        })

    negative_split = None
    if len(splits) >= 2:
        def pace_to_sec(p):
            try:
                m, s = p.split(":")
                return int(m) * 60 + int(s)
            except (ValueError, AttributeError):
                return None
        mid = len(splits) // 2
        first = list(filter(None, (pace_to_sec(s["pace"]) for s in splits[:mid])))
        second = list(filter(None, (pace_to_sec(s["pace"]) for s in splits[mid:])))
        if first and second:
            negative_split = (sum(second) / len(second)) < (sum(first) / len(first))

    return splits, negative_split


# ──────────────────────────────────────────────────────────────────────
# run_log.json append (mirrors analyze_fit.append_to_log)
# ──────────────────────────────────────────────────────────────────────
def append_to_log(analysis: dict, activity_id: str, log_file: Path):
    log = []
    if log_file.exists():
        with open(log_file, encoding="utf-8") as f:
            log = json.load(f)

    existing_ids = {str(e.get("activity_id", "")) for e in log if e.get("activity_id")}
    if str(activity_id) in existing_ids:
        return False  # already logged

    log.append({
        "activity_id": str(activity_id),
        "date": analysis["date"],
        "distance_km": analysis["session"]["distance_km"],
        "duration_min": analysis["session"]["duration_min"],
        "avg_pace": analysis["session"]["avg_pace"],
        "avg_hr": analysis["session"]["avg_hr"],
        "max_hr": analysis["session"]["max_hr"],
        "avg_cadence_spm": analysis["session"]["avg_cadence_spm"],
        "elevation_gain_m": analysis["session"]["elevation_gain_m"],
        "cardiac_decoupling_pct": analysis["patterns"]["cardiac_decoupling_pct"],
        "negative_split": analysis["patterns"]["negative_split"],
        "source": "strava",
    })
    log.sort(key=lambda r: r["date"])
    with open(log_file, "w", encoding="utf-8") as f:
        json.dump(log, f, indent=2)
    return True


# ──────────────────────────────────────────────────────────────────────
# Main
# ──────────────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description="Pull a Strava run and write run_analysis.json")
    parser.add_argument("--activity-id", default=None, help="Specific activity ID (default: latest run)")
    parser.add_argument("--quiet", action="store_true", help="Suppress non-error stdout")
    parser.add_argument("--user", default=None, help="User name for per-user data directory (e.g. Nicolas)")
    args = parser.parse_args()

    def info(msg):
        if not args.quiet:
            print(msg)

    data_dir = _data_dir(args.user)
    log_file = data_dir / "run_log.json"

    try:
        token = get_access_token(user=args.user)
    except RuntimeError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)

    activity_id = args.activity_id or fetch_latest_run_id(token)
    info(f"Fetching Strava activity {activity_id}...")

    activity = _api_get(f"/activities/{activity_id}", token)
    if activity.get("type") != "Run" and activity.get("sport_type") != "Run":
        print(f"ERROR: Activity {activity_id} is not a run", file=sys.stderr)
        sys.exit(1)

    streams = _api_get(
        f"/activities/{activity_id}/streams",
        token,
        params={
            "keys": "heartrate,velocity_smooth,cadence,altitude,time",
            "key_by_type": "true",
        },
    )
    laps = _api_get(f"/activities/{activity_id}/laps", token)

    date_str = activity.get("start_date_local", "")[:10] or "unknown"
    session = build_session(activity)
    patterns = build_patterns(streams, max_hr=session["max_hr"])
    lap_splits, negative_split = build_laps(laps)
    patterns["negative_split"] = negative_split

    analysis = {
        "date": date_str,
        "sport": "running",
        "source": "strava",
        "session": session,
        "patterns": patterns,
        "lap_splits": lap_splits,
    }

    out_file = data_dir / "run_analysis.json"
    data_dir.mkdir(parents=True, exist_ok=True)
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(analysis, f, indent=2)

    appended = append_to_log(analysis, activity_id, log_file)

    if args.quiet:
        print(f"OK {out_file}")
    else:
        s = analysis["session"]
        p = analysis["patterns"]
        print(f"Analysis saved to {out_file}")
        print(f"  Date: {date_str}")
        print(f"  Distance: {s['distance_km']} km  |  Duration: {s['duration_min']} min  |  Avg pace: {s['avg_pace']}")
        print(f"  Avg HR: {s['avg_hr']}  |  Max HR: {s['max_hr']}  |  Cadence: {s['avg_cadence_spm']} spm")
        print(f"  Cardiac decoupling: {p['cardiac_decoupling_pct']}%  |  Negative split: {p['negative_split']}")
        print(f"  Laps: {len(lap_splits)}")
        print(f"  Appended to run_log: {appended}")


if __name__ == "__main__":
    main()
