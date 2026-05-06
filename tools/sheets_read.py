"""
Read a training plan (full or filtered) from Google Sheets.
Outputs JSON to stdout for downstream tools / workflows.

Usage:
  python tools/sheets_read.py --tab "Plan - HK Half - 2026-02-14"
  python tools/sheets_read.py --tab "..." --week 3
  python tools/sheets_read.py --tab "..." --date 2026-05-19
"""

import argparse
import json
import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from googleapiclient.discovery import build

sys.path.insert(0, str(Path(__file__).resolve().parent))
from google_auth import get_credentials

load_dotenv()


def parse_session(row, headers):
    row = list(row) + [""] * (len(headers) - len(row))

    def num(v):
        try:
            return float(v)
        except (ValueError, TypeError):
            return 0

    def int_or_none(v):
        try:
            return int(v)
        except (ValueError, TypeError):
            return None

    return {
        "week": int_or_none(row[0]),
        "date": row[1],
        "day": row[2],
        "session_type": row[3],
        "distance_km": num(row[4]),
        "pace_target": row[5],
        "hr_zone": row[6],
        "description": row[7],
        "notes": row[8],
    }


def read_sessions(tab: str, week: int | None = None, date: str | None = None) -> list[dict]:
    """Read training plan rows from Google Sheets, optionally filtered.
    Reusable by other tools (e.g., telegram_bridge.py)."""
    spreadsheet_id = os.getenv("GOOGLE_SHEETS_SPREADSHEET_ID")
    if not spreadsheet_id:
        raise RuntimeError("GOOGLE_SHEETS_SPREADSHEET_ID must be set in .env")

    creds = get_credentials()
    service = build("sheets", "v4", credentials=creds)

    result = (
        service.spreadsheets()
        .values()
        .get(spreadsheetId=spreadsheet_id, range=f"'{tab}'!A:I")
        .execute()
    )
    values = result.get("values", [])
    if not values:
        return []

    headers = values[0]
    sessions = [parse_session(row, headers) for row in values[1:]]
    if week is not None:
        sessions = [s for s in sessions if s["week"] == week]
    if date is not None:
        sessions = [s for s in sessions if s["date"] == date]
    return sessions


def main():
    parser = argparse.ArgumentParser(description="Read training plan from Google Sheets")
    parser.add_argument("--tab", required=True, help="Tab name to read")
    parser.add_argument("--week", type=int, default=None, help="Filter to a specific week")
    parser.add_argument("--date", default=None, help="Filter to a specific date (YYYY-MM-DD)")
    args = parser.parse_args()

    try:
        sessions = read_sessions(args.tab, week=args.week, date=args.date)
    except RuntimeError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)

    print(json.dumps(sessions, indent=2))


if __name__ == "__main__":
    main()
