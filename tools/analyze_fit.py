"""
Parse a Garmin .FIT file and extract structured session + lap metrics.
Usage: python tools/analyze_fit.py --file .tmp/run_YYYY-MM-DD.fit [--user Nicolas]
Output: {data_dir}/run_analysis.json

Also appends the run to {data_dir}/run_log.json (append-only benchmark history).
"""

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

import fitparse

from garmin_auth import _data_dir


# Garmin HR zone boundaries (% of max HR). Adjust if Kevin's max HR is known.
# Zones: 1=Recovery, 2=Aerobic base, 3=Aerobic, 4=Threshold, 5=VO2max
HR_ZONE_BOUNDARIES = [0.50, 0.60, 0.70, 0.80, 0.90, 1.0]


def pace_from_speed(speed_m_per_s: float) -> str:
    """Convert m/s to mm:ss per km string."""
    if not speed_m_per_s or speed_m_per_s <= 0:
        return ""
    sec_per_km = 1000 / speed_m_per_s
    mins = int(sec_per_km // 60)
    secs = int(sec_per_km % 60)
    return f"{mins}:{secs:02d}"


def semicircles_to_degrees(val) -> float | None:
    if val is None:
        return None
    return val * (180 / 2**31)


def get_hr_zone(hr: float, max_hr: float) -> int:
    """Return HR zone 1–5 given a heart rate and max HR."""
    if not hr or not max_hr:
        return 0
    pct = hr / max_hr
    for i, boundary in enumerate(HR_ZONE_BOUNDARIES[1:], start=1):
        if pct <= boundary:
            return i
    return 5


def parse_fit(fit_path: Path) -> dict:
    fitfile = fitparse.FitFile(str(fit_path))

    session = {}
    laps = []
    records = []  # per-second data points

    for message in fitfile.get_messages():
        name = message.name
        data = {f.name: f.value for f in message}

        if name == "session":
            session = data
        elif name == "lap":
            laps.append(data)
        elif name == "record":
            records.append(data)

    # --- Session summary ---
    sport = str(session.get("sport", "")).lower()
    start_time = session.get("start_time")
    total_distance_m = session.get("total_distance") or 0
    total_elapsed_s = session.get("total_elapsed_time") or 0
    avg_speed = session.get("avg_speed") or session.get("enhanced_avg_speed") or 0
    # Fallback: derive avg_speed from total distance / time if FIT didn't store it
    if not avg_speed and total_distance_m and total_elapsed_s:
        avg_speed = total_distance_m / total_elapsed_s
    max_speed = session.get("max_speed") or session.get("enhanced_max_speed") or 0
    avg_hr = session.get("avg_heart_rate")
    max_hr = session.get("max_heart_rate")
    avg_cadence = session.get("avg_running_cadence")  # steps/min (single foot); ×2 for full cadence
    total_ascent = session.get("total_ascent")
    total_calories = session.get("total_calories")
    training_effect = session.get("total_training_effect")
    vo2max = session.get("estimated_running_vo2_max") or session.get("vo2_max_value")

    # Cardiac decoupling: compare avg HR first half vs. second half of records
    hr_records = [r.get("heart_rate") for r in records if r.get("heart_rate")]
    pace_records = [r.get("speed") or r.get("enhanced_speed") for r in records if (r.get("speed") or r.get("enhanced_speed"))]

    cardiac_decoupling_pct = None
    if len(hr_records) >= 20:
        mid = len(hr_records) // 2
        first_half_avg = sum(hr_records[:mid]) / mid
        second_half_avg = sum(hr_records[mid:]) / (len(hr_records) - mid)
        if first_half_avg:
            cardiac_decoupling_pct = round(((second_half_avg - first_half_avg) / first_half_avg) * 100, 1)

    # Pacing discipline: compare first-km pace vs. overall avg pace
    pacing_discipline = None
    if len(pace_records) >= 10:
        # Approximate: first 20% of records
        early_slice = pace_records[: max(1, len(pace_records) // 5)]
        early_avg_speed = sum(s for s in early_slice if s) / len(early_slice)
        if early_avg_speed and avg_speed:
            # Positive = went out faster than average (common mistake)
            pacing_discipline = round(((early_avg_speed - avg_speed) / avg_speed) * 100, 1)

    # HR zone distribution (requires max_hr)
    hr_zone_distribution = {1: 0, 2: 0, 3: 0, 4: 0, 5: 0}
    if max_hr and hr_records:
        for hr in hr_records:
            zone = get_hr_zone(hr, max_hr)
            if 1 <= zone <= 5:
                hr_zone_distribution[zone] += 1
        total = len(hr_records)
        hr_zone_distribution = {z: round(c / total * 100, 1) for z, c in hr_zone_distribution.items()}

    # --- Lap splits ---
    lap_splits = []
    for i, lap in enumerate(laps, start=1):
        lap_dist = lap.get("total_distance") or 0
        lap_time = lap.get("total_elapsed_time") or 0
        lap_speed = lap.get("avg_speed") or lap.get("enhanced_avg_speed") or 0
        lap_splits.append({
            "lap": i,
            "distance_km": round(lap_dist / 1000, 3),
            "duration_min": round(lap_time / 60, 2),
            "pace": pace_from_speed(lap_speed),
            "avg_hr": lap.get("avg_heart_rate"),
            "max_hr": lap.get("max_heart_rate"),
            "avg_cadence_spm": (lap.get("avg_running_cadence") or 0) * 2 or None,
            "elevation_gain_m": lap.get("total_ascent"),
        })

    # Detect negative split (second half faster than first)
    negative_split = None
    if len(lap_splits) >= 2:
        mid = len(lap_splits) // 2
        first_paces = [l["pace"] for l in lap_splits[:mid] if l["pace"]]
        second_paces = [l["pace"] for l in lap_splits[mid:] if l["pace"]]
        # Lower pace string = faster; compare numerically
        def pace_to_sec(p):
            try:
                m, s = p.split(":")
                return int(m) * 60 + int(s)
            except Exception:
                return None
        first_avg = sum(filter(None, map(pace_to_sec, first_paces))) / len(first_paces) if first_paces else None
        second_avg = sum(filter(None, map(pace_to_sec, second_paces))) / len(second_paces) if second_paces else None
        if first_avg and second_avg:
            negative_split = second_avg < first_avg  # True = sped up

    date_str = (start_time.strftime("%Y-%m-%d") if isinstance(start_time, datetime) else str(start_time)[:10])

    result = {
        "date": date_str,
        "sport": sport,
        "session": {
            "distance_km": round(total_distance_m / 1000, 2),
            "duration_min": round(total_elapsed_s / 60, 1),
            "avg_pace": pace_from_speed(avg_speed),
            "max_pace": pace_from_speed(max_speed),
            "avg_hr": avg_hr,
            "max_hr": max_hr,
            "avg_cadence_spm": (avg_cadence or 0) * 2 or None,
            "elevation_gain_m": total_ascent,
            "calories": total_calories,
            "training_effect_aerobic": training_effect,
            "vo2max_estimate": vo2max,
        },
        "patterns": {
            "cardiac_decoupling_pct": cardiac_decoupling_pct,
            "pacing_discipline_pct": pacing_discipline,
            "negative_split": negative_split,
            "hr_zone_distribution_pct": hr_zone_distribution,
        },
        "lap_splits": lap_splits,
    }

    return result


def load_run_log(data_dir: Path) -> list[dict]:
    log_file = data_dir / "run_log.json"
    if log_file.exists():
        with open(log_file, encoding="utf-8") as f:
            return json.load(f)
    return []


def append_to_log(run: dict, data_dir: Path, activity_id: str | None = None):
    log_file = data_dir / "run_log.json"
    log = load_run_log(data_dir)
    existing_ids = {r.get("activity_id") for r in log if r.get("activity_id")}
    existing_dates = {r["date"] for r in log if not r.get("activity_id")}

    is_duplicate = (activity_id and activity_id in existing_ids) or \
                   (not activity_id and run["date"] in existing_dates)

    if not is_duplicate:
        log.append({
            "activity_id": activity_id,
            "date": run["date"],
            "distance_km": run["session"]["distance_km"],
            "duration_min": run["session"]["duration_min"],
            "avg_pace": run["session"]["avg_pace"],
            "avg_hr": run["session"]["avg_hr"],
            "max_hr": run["session"]["max_hr"],
            "avg_cadence_spm": run["session"]["avg_cadence_spm"],
            "elevation_gain_m": run["session"]["elevation_gain_m"],
            "cardiac_decoupling_pct": run["patterns"]["cardiac_decoupling_pct"],
            "negative_split": run["patterns"]["negative_split"],
            "source": "garmin",
        })
        log.sort(key=lambda r: r["date"])
        with open(log_file, "w", encoding="utf-8") as f:
            json.dump(log, f, indent=2)
        print(f"Appended run to {log_file} ({len(log)} total entries).")
    else:
        print(f"Run already in log — skipping append.")


def read_last_activity_id(data_dir: Path) -> str | None:
    """Read activity_id from {data_dir}/last_activity_id.txt (line 1) if it exists."""
    f = data_dir / "last_activity_id.txt"
    if not f.exists():
        return None
    lines = f.read_text(encoding="utf-8").strip().splitlines()
    return lines[0] if lines else None


def main():
    parser = argparse.ArgumentParser(description="Parse a Garmin .FIT file into structured metrics")
    parser.add_argument("--file", type=str, default=None, help="Path to .FIT file (default: latest in data_dir/)")
    parser.add_argument("--activity-id", type=str, default=None, help="Garmin activity ID (default: from data_dir/last_activity_id.txt)")
    parser.add_argument("--quiet", action="store_true", help="Suppress verbose stdout (still prints errors)")
    parser.add_argument("--user", default=None, help="User name for per-user data directory (e.g. Nicolas)")
    args = parser.parse_args()

    data_dir = _data_dir(args.user)

    def info(msg):
        if not args.quiet:
            print(msg)

    if args.file:
        fit_path = Path(args.file)
    else:
        fit_files = sorted(data_dir.glob("run_*.fit"))
        if not fit_files:
            raise FileNotFoundError(f"No .fit files found in {data_dir}/. Run garmin_fetch_fit.py first.")
        fit_path = fit_files[-1]
        info(f"Using latest .FIT file: {fit_path}")

    if not fit_path.exists():
        raise FileNotFoundError(f"File not found: {fit_path}")

    info(f"Parsing {fit_path}...")
    analysis = parse_fit(fit_path)

    out_file = data_dir / "run_analysis.json"
    data_dir.mkdir(parents=True, exist_ok=True)
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(analysis, f, indent=2)

    activity_id = args.activity_id or read_last_activity_id(data_dir)

    if args.quiet:
        print(f"OK {out_file}")
        import io as _io, contextlib
        buf = _io.StringIO()
        with contextlib.redirect_stdout(buf):
            append_to_log(analysis, data_dir, activity_id=activity_id)
    else:
        print(f"Analysis saved to {out_file}")
        s = analysis["session"]
        p = analysis["patterns"]
        print(f"  Date: {analysis['date']}")
        print(f"  Distance: {s['distance_km']} km  |  Duration: {s['duration_min']} min  |  Avg pace: {s['avg_pace']}")
        print(f"  Avg HR: {s['avg_hr']}  |  Max HR: {s['max_hr']}  |  Cadence: {s['avg_cadence_spm']} spm")
        print(f"  Cardiac decoupling: {p['cardiac_decoupling_pct']}%  |  Negative split: {p['negative_split']}")
        print(f"  Laps: {len(analysis['lap_splits'])}")
        append_to_log(analysis, data_dir, activity_id=activity_id)


if __name__ == "__main__":
    main()
