# Workflow: Initial Fitness Assessment

## Objective
Establish Kevin's running baseline from the past 3 months of Garmin data. This one-time assessment informs the training plan's starting mileage, target paces, and appropriate weekly structure.

## When to Run
Once, at project start — before `generate_training_plan.md`.

## Required Inputs
- Garmin credentials in `.env` (`GARMIN_EMAIL`, `GARMIN_PASSWORD`)

## Steps

### Step 1 — Fetch run history
```bash
python tools/garmin_fetch_csv.py --days 90
```
Output: `.tmp/run_history.csv`

If the command fails with a 429 (rate limit), wait 60 seconds and retry once. If it fails with an auth error, check `.env` credentials.

### Step 2 — Read the CSV
Open `.tmp/run_history.csv` and analyze the following. If there are fewer than 5 runs, note this as a very early baseline.

**Weekly mileage:**
- Group runs by ISO week number
- Calculate total km per week
- Identify: average weekly km, peak weekly km, any cutback weeks

**Longest run:**
- Find the single longest run distance
- Note when it occurred (recent = good; 2+ months ago = fitness may have faded)

**Pace trend:**
- Compare avg pace of runs in weeks 1–4 vs. weeks 9–12 (most recent)
- Express as: improving / flat / declining
- Note whether runs were mostly easy effort (HR < 75% max) or harder

**Heart rate:**
- Average HR across all runs
- If max HR data exists, flag any runs where avg HR exceeded 85% max (potential overexertion)

**Consistency:**
- Count weeks with 0 runs (rest weeks or skipped)
- Count weeks with 3+ runs

**Cadence:**
- Average cadence across all runs
- Optimal is ≥160 spm; flag if consistently below

### Step 3 — Assess fitness level and starting point
Based on the data, determine:

| Metric | Beginner Starting Point |
|--------|------------------------|
| Weekly mileage | Match to Kevin's recent average, minimum 15 km/week |
| Long run | Start at 60–70% of current longest run |
| Target easy pace | Current avg pace + 15–30 sec/km (conversational effort) |
| Target tempo pace | Current avg pace − 15 sec/km |
| Estimated race pace | Based on pace trend; will refine as training progresses |

### Step 4 — Save baseline to file
Write the following JSON to `.tmp/fitness_baseline.json`:

```json
{
  "assessment_date": "YYYY-MM-DD",
  "weeks_analyzed": N,
  "total_runs": N,
  "avg_weekly_km": X,
  "peak_weekly_km": X,
  "longest_run_km": X,
  "avg_pace_min_per_km": "M:SS",
  "pace_trend": "improving | flat | declining",
  "avg_hr": X,
  "avg_cadence_spm": X,
  "consistency_weeks_with_runs": N,
  "starting_weekly_km": X,
  "starting_long_run_km": X,
  "easy_pace_target": "M:SS",
  "tempo_pace_target": "M:SS",
  "estimated_race_pace": "M:SS",
  "notes": "Free-text observations"
}
```

### Step 5 — Present assessment to Kevin
Summarize the findings in plain language:

- Current fitness level and what the data shows
- Strengths observed (consistency, improving pace, etc.)
- Areas to develop (cadence, aerobic base, long run distance, etc.)
- Recommended starting point for the training plan
- Ask Kevin: **"Does this look right? Do you want to adjust any of the starting targets before I generate the plan?"**

Wait for Kevin's confirmation or adjustments before proceeding to `generate_training_plan.md`.

## Edge Cases
- **Fewer than 5 runs in 90 days:** Note as returning/new runner. Start conservatively — 3 runs/week, short distances. Ask Kevin about any injury history.
- **Very fast pace for a beginner:** Data may include cycling or mixed activities. Cross-check activity names in CSV. Confirm with Kevin.
- **Missing HR data:** Some Garmin models or accessories may not record HR. Skip HR analysis; rely on pace only.
- **Garmin rate limit (429):** Wait 60 seconds, retry. Document in this workflow if it becomes a recurring issue.

## Output
- `.tmp/run_history.csv` — full 90-day activity history
- `.tmp/fitness_baseline.json` — structured baseline used by plan generation
- Plain-text assessment presented to Kevin
