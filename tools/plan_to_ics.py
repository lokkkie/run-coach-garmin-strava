"""
Export a training plan (JSON) to an .ics calendar file.
This tool is run ONLY when explicitly requested — never auto-triggered by other workflows.

Usage:
  python tools/plan_to_ics.py                                # uses .tmp/plan.json
  python tools/plan_to_ics.py --plan .tmp/plan.json --output .tmp/training_plan.ics
"""

import argparse
import json
import uuid
from datetime import datetime, timedelta
from pathlib import Path

from icalendar import Calendar, Event


def build_summary(s):
    parts = [s.get("session_type", "Run")]
    dist = s.get("distance_km")
    if dist:
        parts.append(f"{dist} km")
    pace = s.get("pace_target")
    if pace:
        parts.append(f"@ {pace}/km")
    return " — ".join(parts) if len(parts) > 1 else parts[0]


def build_description(s):
    parts = []
    if s.get("description"):
        parts.append(s["description"])
    if s.get("hr_zone"):
        parts.append(f"HR Zone: {s['hr_zone']}")
    if s.get("notes"):
        parts.append(f"Notes: {s['notes']}")
    return "\n".join(parts)


def main():
    parser = argparse.ArgumentParser(description="Export plan.json to .ics calendar file")
    parser.add_argument("--plan", default=".tmp/plan.json")
    parser.add_argument("--output", default=".tmp/training_plan.ics")
    parser.add_argument("--include-rest", action="store_true",
                        help="Include rest days as calendar events")
    args = parser.parse_args()

    plan_path = Path(args.plan)
    if not plan_path.exists():
        raise FileNotFoundError(f"Plan file not found: {plan_path}")

    with open(plan_path, encoding="utf-8") as f:
        plan = json.load(f)

    cal = Calendar()
    cal.add("prodid", "-//Run Coach//runcoach.local//")
    cal.add("version", "2.0")
    cal.add("x-wr-calname", f"Training Plan - {plan['plan_metadata']['race_name']}")

    written = 0
    for s in plan["sessions"]:
        if s.get("session_type") == "Rest" and not args.include_rest:
            continue

        event = Event()
        event.add("summary", build_summary(s))
        event.add("description", build_description(s))

        d = datetime.strptime(s["date"], "%Y-%m-%d").date()
        event.add("dtstart", d)
        event.add("dtend", d + timedelta(days=1))
        event.add("uid", str(uuid.uuid4()))
        event.add("dtstamp", datetime.now())

        cal.add_component(event)
        written += 1

    output_path = Path(args.output)
    output_path.parent.mkdir(exist_ok=True)
    with open(output_path, "wb") as f:
        f.write(cal.to_ical())

    print(f"Wrote {written} sessions to {output_path}")
    print("Import:")
    print("  - Apple Calendar: drag the .ics file into the app")
    print("  - Google Calendar: Settings -> Import & Export -> Import")


if __name__ == "__main__":
    main()
