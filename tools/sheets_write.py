"""
Push a training plan from plan.json into a Google Sheets tab.

Usage:
  python tools/sheets_write.py                        # uses .tmp/plan.json, tab name from metadata
  python tools/sheets_write.py --tab "Plan - HK Half - 2026-02-14"
  python tools/sheets_write.py --force                # overwrite if tab already exists
"""

import argparse
import json
import os
import sys
from pathlib import Path

from googleapiclient.discovery import build

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import runcoach.paths  # noqa: F401, E402
sys.path.insert(0, str(Path(__file__).resolve().parent))
from google_auth import get_credentials  # noqa: E402

HEADERS = [
    "Week", "Date", "Day", "Session Type", "Distance (km)",
    "Pace Target", "HR Zone", "Description", "Notes",
]


def get_sheet_meta(service, spreadsheet_id):
    return service.spreadsheets().get(spreadsheetId=spreadsheet_id).execute()


def existing_tab_names(meta):
    return [s["properties"]["title"] for s in meta["sheets"]]


def get_tab_id(meta, tab_name):
    for s in meta["sheets"]:
        if s["properties"]["title"] == tab_name:
            return s["properties"]["sheetId"]
    return None


def create_tab(service, spreadsheet_id, tab_name):
    body = {"requests": [{"addSheet": {"properties": {"title": tab_name}}}]}
    service.spreadsheets().batchUpdate(spreadsheetId=spreadsheet_id, body=body).execute()


def main():
    parser = argparse.ArgumentParser(description="Push training plan to Google Sheets")
    parser.add_argument("--plan", default=".tmp/plan.json", help="Path to plan.json")
    parser.add_argument("--tab", default=None, help="Tab name (default from plan metadata)")
    parser.add_argument("--force", action="store_true", help="Overwrite if tab exists")
    parser.add_argument("--quiet", action="store_true", help="Suppress non-error stdout")
    args = parser.parse_args()

    def info(msg):
        if not args.quiet:
            print(msg)

    spreadsheet_id = os.getenv("GOOGLE_SHEETS_SPREADSHEET_ID")
    if not spreadsheet_id:
        print("ERROR: GOOGLE_SHEETS_SPREADSHEET_ID must be set in .env", file=sys.stderr)
        sys.exit(1)

    plan_path = Path(args.plan)
    if not plan_path.exists():
        print(f"ERROR: Plan file not found: {plan_path}", file=sys.stderr)
        sys.exit(1)

    with open(plan_path, encoding="utf-8") as f:
        plan = json.load(f)

    meta_data = plan["plan_metadata"]
    tab_name = args.tab or f"Plan - {meta_data['race_name']} - {meta_data['race_date']}"
    tab_name = tab_name[:99]  # Sheets tab name limit

    info("Authorizing with Google...")
    creds = get_credentials()
    service = build("sheets", "v4", credentials=creds)

    info("Reading sheet metadata...")
    meta = get_sheet_meta(service, spreadsheet_id)

    if tab_name in existing_tab_names(meta):
        if not args.force:
            print(
                f'ERROR: Tab "{tab_name}" already exists. Use --force to overwrite.',
                file=sys.stderr,
            )
            sys.exit(2)
        info(f'Clearing existing tab "{tab_name}"...')
        service.spreadsheets().values().clear(
            spreadsheetId=spreadsheet_id, range=f"'{tab_name}'!A:I"
        ).execute()
    else:
        info(f'Creating new tab "{tab_name}"...')
        create_tab(service, spreadsheet_id, tab_name)
        meta = get_sheet_meta(service, spreadsheet_id)  # refresh to get new tab id

    rows = [HEADERS]
    for s in plan["sessions"]:
        rows.append([
            s.get("week", ""),
            s.get("date", ""),
            s.get("day", ""),
            s.get("session_type", ""),
            s.get("distance_km", ""),
            s.get("pace_target", ""),
            s.get("hr_zone", ""),
            s.get("description", ""),
            s.get("notes", ""),
        ])

    info(f"Writing {len(rows) - 1} sessions...")
    service.spreadsheets().values().update(
        spreadsheetId=spreadsheet_id,
        range=f"'{tab_name}'!A1",
        valueInputOption="USER_ENTERED",
        body={"values": rows},
    ).execute()

    tab_id = get_tab_id(meta, tab_name)
    format_requests = [
        {
            "updateSheetProperties": {
                "properties": {"sheetId": tab_id, "gridProperties": {"frozenRowCount": 1}},
                "fields": "gridProperties.frozenRowCount",
            }
        },
        {
            "repeatCell": {
                "range": {"sheetId": tab_id, "startRowIndex": 0, "endRowIndex": 1},
                "cell": {
                    "userEnteredFormat": {
                        "textFormat": {"bold": True},
                        "backgroundColor": {"red": 0.85, "green": 0.92, "blue": 0.98},
                    }
                },
                "fields": "userEnteredFormat.textFormat.bold,userEnteredFormat.backgroundColor",
            }
        },
        {
            "autoResizeDimensions": {
                "dimensions": {"sheetId": tab_id, "dimension": "COLUMNS",
                               "startIndex": 0, "endIndex": 9}
            }
        },
    ]
    service.spreadsheets().batchUpdate(
        spreadsheetId=spreadsheet_id, body={"requests": format_requests}
    ).execute()

    if args.quiet:
        print(f"OK {tab_name} {len(rows) - 1}")
    else:
        print(f'Done. Tab "{tab_name}" — {len(rows) - 1} sessions written.')
        print(f"Open: https://docs.google.com/spreadsheets/d/{spreadsheet_id}/edit")


if __name__ == "__main__":
    main()
