# Workflow: Post-Run Analysis

> **Note:** This workflow is also implemented as the `post-run-analysis` subagent (`.claude/agents/post-run-analysis.md`), pinned to Sonnet 4.6 to keep per-debrief cost ~5x lower than running on Opus. Single-run debriefs route there automatically. This file remains the human-readable SOP and the source of truth for the steps.

## Objective
Pull the latest Garmin run, compare it to the prescribed session, identify performance patterns, benchmark against history, and prescribe the next session. Surface plan-change recommendations to Kevin without auto-applying them.

## Required Inputs
- Active data source credentials in `.env` (Garmin or Strava — whichever is set in `coaching_state.json:data_source`)
- `GOOGLE_SHEETS_SPREADSHEET_ID` in `.env`
- A completed run synced to the active source (Garmin Connect or Strava)

> **Source note:** `polling_check.py` and the pre-check steps below default to the Garmin path. If `data_source` is `"strava"`, use `strava_latest_id.py` / `strava_pull.py` in place of `garmin_latest_id.py` / `garmin_fetch_fit.py` + `analyze_fit.py`. All subsequent steps are source-agnostic (both paths produce the same `.tmp/run_analysis.json` schema).

## Tool Conventions
All tool calls in this workflow use `--quiet` by default — they emit a single-line `OK ...` summary plus error info. Drop `--quiet` only when manually debugging.

---

## Step 0 — Pre-check (cache hit?)
Check whether the latest Garmin run is already in our log. If so, skip Steps 1–2 entirely.

```bash
python tools/garmin_latest_id.py
```
Output (3 lines): `<activity_id>` / `<YYYY-MM-DD>` / `<activity_name>`. Exit 2 = rate-limited (back off, abort).

Then check `.tmp/run_log.json`:
```bash
python -c "import json,sys; aid=sys.argv[1]; d=json.load(open('.tmp/run_log.json')); print('HIT' if any(str(e.get('activity_id',''))==aid for e in d) else 'MISS')" <ACTIVITY_ID>
```

- **HIT** → activity already analyzed. Skip Steps 1 and 2. Read `.tmp/run_analysis.json` directly (it holds the most recent full analysis). Proceed to Step 3.
- **MISS** → new run. Proceed to Step 1.

---

## Step 1 — Pull FIT file (only on MISS)
```bash
python tools/garmin_fetch_fit.py --quiet
```
Output: `OK <activity_id> <path>`. Failures: 429 → wait 60s and retry once; auth error → check `.env`.

## Step 2 — Parse FIT (only on MISS)
```bash
python tools/analyze_fit.py --quiet
```
Output: `OK .tmp/run_analysis.json`. Read that JSON to get the session summary, patterns, and lap splits.

## Step 3 — Compare vs prescribed
Read `coaching_state.json` for the active `plan_sheet_tab`. Then fetch only today's session:

```bash
python tools/sheets_read.py --tab "<plan_sheet_tab>" --date <YYYY-MM-DD>
```
Returns one row of JSON. Compare actual vs planned distance, pace, HR zone, duration. Flag deviations > 15% on distance or > 30 sec/km on pace.

## Step 4 — Identify patterns
From `run_analysis.json` patterns + lap splits, assess: cardiac decoupling, pacing discipline, negative split, fatigue signals, cadence. **Threshold definitions and tier interpretations live in `workflows/references/post_run_protocols.md` — read that file only when you need the specific cutoffs; otherwise apply standard running-coaching judgment.**

## Step 5 — Benchmark against history
Read `.tmp/run_log.json`. Check for PRs (longest, fastest at this distance, best decoupling). Compare avg pace and HR trend over the last 4 weeks. Praise PRs and surface trajectory.

## Step 6 — Prescribe next session
Generate a recommendation for Kevin.

**Standard case:** confirm next scheduled session + one specific coaching cue tied to today's run.

**Plan-change candidate** (significant deviation, multi-day fatigue, injury signal):
1. State the observation.
2. Propose the specific change.
3. Ask Kevin: "Want me to update the plan?"
4. Only run `python tools/sheets_write.py --force --quiet` after Kevin confirms.

**Never auto-modify the plan.**

## Step 7 — Calendar export (explicit-only)
Do NOT run `plan_to_ics.py` unless Kevin explicitly asks. The plan lives in Google Sheets.

---

## Output
Use the debrief template in `workflows/references/post_run_protocols.md`. HTML formatting (the Telegram bridge renders it). Dates in DD/MM/YY.
