# Google Sheets — Plan Schema

## Tab naming convention

`Plan - <RaceName> - <YYYY-MM-DD>`

Examples:
- `Plan - HK Half - 2026-02-14`
- `Plan - Tokyo Marathon - 2027-03-07`
- `Plan - HK Half - archived-2025-10-15` (after archive)

One tab per plan. Never silently overwrite — see SKILL.md §8 existing-plan guard.

## Column schema

| Column | Type | Required | Notes |
|--------|------|----------|-------|
| A: Week | Integer | Yes | Plan week number, starts at 1 |
| B: Date | Date (YYYY-MM-DD) | Yes | Calendar date of session |
| C: Day | Text | Yes | Day name (Mon, Tue, ...) — derived from Date for readability |
| D: Session Type | Text | Yes | One of: Easy, Long, Tempo, Intervals, Repetition, Race-Pace, Recovery, Rest, Strides, Race |
| E: Distance (km) | Number | Yes | 0 if Rest |
| F: Pace Target | Text | No | Format `M:SS` or range `M:SS–M:SS`; empty if HR-only or rest |
| G: HR Zone | Text | No | Z1, Z2, Z1–Z2, Z4, etc.; empty if pace-only or rest |
| H: Description | Text | Yes | One-line description (e.g., "4 × 1km @ T pace, 60s jog recovery") |
| I: Notes | Text | No | Free text — coaching cue, fueling note, "if knee flares, swap to easy" |

## `.tmp/plan.json` schema

The skill writes this JSON before pushing to Sheets. `tools/sheets_write.py` reads it and writes the rows.

```json
{
  "plan_metadata": {
    "race_name": "HK Half Marathon",
    "race_distance_km": 21.0975,
    "race_date": "2026-02-14",
    "target_time": "1:45:00",
    "methodology_choices": [
      { "weeks": "1-6", "method": "80-20", "phase": "base" },
      { "weeks": "7-12", "method": "daniels", "phase": "build" },
      { "weeks": "13-14", "method": "daniels", "phase": "peak" },
      { "weeks": "15-16", "method": "taper", "phase": "taper" }
    ],
    "generated_date": "2025-10-30",
    "baseline_used": ".tmp/fitness_baseline.json"
  },
  "sessions": [
    {
      "week": 1,
      "date": "2025-11-03",
      "day": "Mon",
      "session_type": "Rest",
      "distance_km": 0,
      "pace_target": "",
      "hr_zone": "",
      "description": "Rest day",
      "notes": ""
    },
    {
      "week": 1,
      "date": "2025-11-04",
      "day": "Tue",
      "session_type": "Easy",
      "distance_km": 6,
      "pace_target": "5:45–6:15",
      "hr_zone": "Z1–Z2",
      "description": "Easy aerobic, conversational",
      "notes": "First week — keep it controlled"
    }
  ]
}
```

## Header row

Row 1 is the header. Match column order exactly. Bold + frozen.

## Conditional formatting (suggested — Kevin can apply manually if `tools/sheets_write.py` doesn't set them)

| Rule | Range | Format |
|------|-------|--------|
| Session Type = "Long" | Column D | Light green background |
| Session Type IN ("Tempo", "Intervals", "Race-Pace") | Column D | Light orange background |
| Session Type = "Rest" | Column D | Grey text, no background |
| Session Type = "Race" | Row | Bold, light blue background |
| Date = TODAY() | Column B | Yellow background (highlights "today") |
| Date < TODAY() AND Session Type ≠ "Rest" | Column E | Strikethrough (visually marks completed sessions) |

## Formulas (optional — only if Kevin wants summary metrics in the sheet)

### Weekly mileage total
At the bottom of each week's block, or in a side panel:
```
=SUMIF(A:A, <week_number>, E:E)
```

### Quality session count this week
```
=COUNTIFS(A:A, <week_number>, D:D, "Tempo") + COUNTIFS(A:A, <week_number>, D:D, "Intervals")
```

### Days until race
On a "Plan Summary" sheet:
```
=DATEDIF(TODAY(), <race_date_cell>, "D")
```

## Update behavior

When Kevin completes a run, `post_run_analysis.md` may want to mark it complete or annotate the Notes column. That's that workflow's job, not this skill's. The plan tab is the source of truth for *prescribed* sessions; actual results live in `.tmp/run_log.json` and Garmin Connect.

When this skill revises the plan, replace only the affected rows. Keep the rest of the plan intact. If a phase shift moves multiple weeks, replace all sessions in those weeks atomically (don't leave partial state).
