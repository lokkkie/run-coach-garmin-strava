"""
Parse a Garmin .FIT file and extract structured session + lap metrics.
Usage: python tools/analyze_fit.py --file {data_dir}/run_YYYY-MM-DD.fit [--user Nicolas]
Output: {data_dir}/run_analysis.json

Also appends the run to {data_dir}/run_log.json (append-only benchmark history).
The actual FIT parsing is in `runcoach.fit.parse_fit`; this CLI just resolves
paths, writes the JSON output, and calls `runcoach.run_log.append_run`.
"""

import argparse
import json
import sys
from pathlib import Path

# Make runcoach importable when invoked as `python tools/analyze_fit.py`.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from runcoach.paths import data_dir as _data_dir  # noqa: E402
from runcoach.run_log import append_run  # noqa: E402
from runcoach.fit import parse_fit  # noqa: E402


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

    if not args.quiet:
        print(f"Analysis saved to {out_file}")
        s = analysis["session"]
        p = analysis["patterns"]
        print(f"  Date: {analysis['date']}")
        print(f"  Distance: {s['distance_km']} km  |  Duration: {s['duration_min']} min  |  Avg pace: {s['avg_pace']}")
        print(f"  Avg HR: {s['avg_hr']}  |  Max HR: {s['max_hr']}  |  Cadence: {s['avg_cadence_spm']} spm")
        print(f"  Cardiac decoupling: {p['cardiac_decoupling_pct']}%  |  Negative split: {p['negative_split']}")
        print(f"  Laps: {len(analysis['lap_splits'])}")

    if activity_id is None:
        # No activity_id means we can't dedup — skip run_log to keep it clean.
        msg = "Skipped run_log append: no activity_id available (pass --activity-id or write last_activity_id.txt)."
        if args.quiet:
            print(f"OK {out_file}")
            print(msg, file=sys.stderr)
        else:
            print(msg)
    else:
        appended = append_run(analysis, activity_id, data_dir, source="garmin")
        if args.quiet:
            print(f"OK {out_file}")
        else:
            log_path = data_dir / "run_log.json"
            print(f"  {'Appended to' if appended else 'Already in'} {log_path}")


if __name__ == "__main__":
    main()
