"""Shared run-log append + dedup logic.

Both the Garmin (analyze_fit.py) and Strava (strava_pull.py) ingest paths
write to {data_dir}/run_log.json. Before this module they each had their own
copy of the logic with subtly different dedup semantics — string vs. int
activity_id matching, plus a split key in the Garmin path that mixed
"by activity_id" and "by date" lookups against disjoint subsets of the log,
so a run logged once with an activity_id and once without (legacy) wouldn't
collide. The unified function deduplicates on the stringified activity_id
only — activity_id is the authoritative key, dates aren't unique (AM+PM
runs same day), so the "fall back to date" branch was just a footgun.
"""

import json
from pathlib import Path


def load_run_log(data_dir: Path) -> list[dict]:
    """Return the list of entries in {data_dir}/run_log.json, or [] if missing."""
    log_file = data_dir / "run_log.json"
    if not log_file.exists():
        return []
    with open(log_file, encoding="utf-8") as f:
        return json.load(f)


def _build_entry(analysis: dict, activity_id: str, source: str) -> dict:
    """Project a full run_analysis dict into the lightweight log-entry schema.

    Same shape Garmin and Strava both produced before this refactor; the
    `source` field is now an explicit param instead of being hardcoded by
    each caller's copy of the function.
    """
    session = analysis["session"]
    patterns = analysis["patterns"]
    return {
        "activity_id": str(activity_id),
        "date": analysis["date"],
        "distance_km": session["distance_km"],
        "duration_min": session["duration_min"],
        "avg_pace": session["avg_pace"],
        "avg_hr": session["avg_hr"],
        "max_hr": session["max_hr"],
        "avg_cadence_spm": session["avg_cadence_spm"],
        "elevation_gain_m": session["elevation_gain_m"],
        "cardiac_decoupling_pct": patterns["cardiac_decoupling_pct"],
        "negative_split": patterns["negative_split"],
        "source": source,
    }


def append_run(
    analysis: dict,
    activity_id: str | int,
    data_dir: Path,
    source: str,
) -> bool:
    """Append a run to {data_dir}/run_log.json with dedup by activity_id.

    Returns True if the entry was appended, False if the activity_id was
    already present (caller decides what to log/print).

    `activity_id` is coerced to string both for storage and for dedup, so a
    Garmin int id (`12345678`) and a stringified version (`"12345678"`) of
    the same run won't both land in the log.
    """
    log_file = data_dir / "run_log.json"
    log = load_run_log(data_dir)

    aid = str(activity_id)
    existing_ids = {str(e.get("activity_id", "")) for e in log if e.get("activity_id")}
    if aid in existing_ids:
        return False

    log.append(_build_entry(analysis, aid, source))
    log.sort(key=lambda r: r["date"])
    data_dir.mkdir(parents=True, exist_ok=True)
    with open(log_file, "w", encoding="utf-8") as f:
        json.dump(log, f, indent=2)
    return True
