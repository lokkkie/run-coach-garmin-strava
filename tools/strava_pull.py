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
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from runcoach.paths import data_dir as _data_dir  # noqa: E402
from runcoach.run_log import append_run  # noqa: E402
from runcoach.metrics import (  # noqa: E402
    get_hr_zone,
    pace_from_distance_time,
    pace_from_speed,
    pace_to_sec,
)
from runcoach.strava import (  # noqa: E402
    fetch_activity,
    fetch_laps,
    fetch_streams,
    get_access_token,
    latest_run,
)


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
        mid = len(splits) // 2
        first = list(filter(None, (pace_to_sec(s["pace"]) for s in splits[:mid])))
        second = list(filter(None, (pace_to_sec(s["pace"]) for s in splits[mid:])))
        if first and second:
            negative_split = (sum(second) / len(second)) < (sum(first) / len(first))

    return splits, negative_split


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

    try:
        token = get_access_token(user=args.user)
    except RuntimeError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)

    if args.activity_id:
        activity_id = args.activity_id
    else:
        latest = latest_run(token)
        if latest is None:
            print("ERROR: No recent running activity found on Strava", file=sys.stderr)
            sys.exit(1)
        activity_id = str(latest["id"])
    info(f"Fetching Strava activity {activity_id}...")

    activity = fetch_activity(token, activity_id)
    if activity.get("type") != "Run" and activity.get("sport_type") != "Run":
        print(f"ERROR: Activity {activity_id} is not a run", file=sys.stderr)
        sys.exit(1)

    streams = fetch_streams(token, activity_id)
    laps = fetch_laps(token, activity_id)

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

    appended = append_run(analysis, activity_id, data_dir, source="strava")

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
