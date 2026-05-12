"""FIT file helpers — extraction from Garmin's zipped originals, semicircle
GPS coordinate conversion, local-timestamp date resolution, and the full
per-run parser that produces a `run_analysis.json`-shaped dict.

Strava's ingest path uses `runcoach.metrics` directly (no FIT involved); the
Garmin path goes through here.
"""

import io
import zipfile
from datetime import datetime
from pathlib import Path

import fitparse

from runcoach.metrics import get_hr_zone, pace_from_speed, pace_to_sec


def extract_fit_bytes(raw: bytes) -> bytes:
    """Garmin's ORIGINAL download format returns a ZIP containing the `.FIT`.
    If `raw` starts with the ZIP magic bytes, extract the first .fit member.
    Otherwise (rare; older endpoints) return raw as-is."""
    if raw[:4] == b"PK\x03\x04":
        with zipfile.ZipFile(io.BytesIO(raw)) as zf:
            fit_names = [n for n in zf.namelist() if n.lower().endswith(".fit")]
            if not fit_names:
                raise RuntimeError(
                    f"No .fit file in ZIP archive. Members: {zf.namelist()}"
                )
            return zf.read(fit_names[0])
    return raw


def semicircles_to_degrees(val) -> float | None:
    """Convert Garmin's semicircle GPS units to decimal degrees."""
    if val is None:
        return None
    return val * (180 / 2**31)


def fit_local_date_str(session: dict, activity: dict) -> str:
    """Return the local YYYY-MM-DD date for a FIT-parsed run.

    Prefer `activity.local_timestamp` over `session.start_time` (which is UTC).
    For runs starting late-evening local time in eastward time zones (Asia/Tokyo
    UTC+9, etc.), the UTC date is one day earlier than the runner's local date,
    which disagrees with Garmin Connect's `startTimeLocal` and Strava's
    `start_date_local`. Using `local_timestamp` keeps both ingest paths in sync.
    """
    local_dt = activity.get("local_timestamp")
    if isinstance(local_dt, datetime):
        return local_dt.strftime("%Y-%m-%d")
    start_time = session.get("start_time")
    if isinstance(start_time, datetime):
        return start_time.strftime("%Y-%m-%d")
    return str(start_time)[:10]


def parse_fit(fit_path: Path) -> dict:
    """Parse a FIT file into the canonical run-analysis schema.

    Returns a dict with `date`, `sport`, `session`, `patterns`, `lap_splits`
    keys — the same shape the Strava ingest path produces. The downstream
    `runcoach.run_log.append_run` then projects this into the lighter
    run_log.json entry shape.
    """
    fitfile = fitparse.FitFile(str(fit_path))

    session: dict = {}
    activity: dict = {}  # carries local_timestamp; session.start_time is UTC
    laps: list[dict] = []
    records: list[dict] = []  # per-second data points

    for message in fitfile.get_messages():
        name = message.name
        data = {f.name: f.value for f in message}

        if name == "session":
            session = data
        elif name == "activity":
            activity = data
        elif name == "lap":
            laps.append(data)
        elif name == "record":
            records.append(data)

    # --- Session summary ---
    sport = str(session.get("sport", "")).lower()
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
    hr_zone_distribution: dict[int, float] = {1: 0, 2: 0, 3: 0, 4: 0, 5: 0}
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

    # Detect negative split (second half faster than first). Note: pace strings
    # round to whole seconds, so this loses sub-second precision — flagged in
    # the project review as a candidate for refactor to keep speed as float
    # throughout.
    negative_split = None
    if len(lap_splits) >= 2:
        mid = len(lap_splits) // 2
        first_paces = [l["pace"] for l in lap_splits[:mid] if l["pace"]]
        second_paces = [l["pace"] for l in lap_splits[mid:] if l["pace"]]
        first_avg = sum(filter(None, map(pace_to_sec, first_paces))) / len(first_paces) if first_paces else None
        second_avg = sum(filter(None, map(pace_to_sec, second_paces))) / len(second_paces) if second_paces else None
        if first_avg and second_avg:
            negative_split = second_avg < first_avg  # True = sped up

    return {
        "date": fit_local_date_str(session, activity),
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
