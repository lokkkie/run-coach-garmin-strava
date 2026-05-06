# Post-Run Analysis — Protocols & Templates

Detailed pattern thresholds and the debrief output template. Read this only when interpreting the deeper coaching signals or formatting the final response — the main `post_run_analysis.md` workflow links here on demand.

## Pattern Thresholds

### Cardiac decoupling (`cardiac_decoupling_pct`)
- **< 5%** — Good aerobic efficiency. Note as positive.
- **5–10%** — Moderate drift. Acceptable for long runs; flag for tempo/interval runs.
- **> 10%** — High decoupling. Run was too hard for current aerobic base. Recommend more easy running.

### Pacing discipline (`pacing_discipline_pct`)
- **Negative** — Went out slower than average (good — conservative start).
- **0–5% faster than avg** — Acceptable.
- **> 10% faster than avg** — Too fast start. Explain the cost of early anaerobic effort and recommend even-pace or negative split strategy.

### Negative split (`negative_split`)
- **True** — Second half faster. Excellent pacing and fitness signal. Praise this.
- **False** — Positive split. Common for beginners; coach on holding back early.

### Fatigue signals (from lap data)
- Pace decay in final laps (slowing > 10% vs. first laps) → fitness limit reached.
- HR spike in final laps with pace drop → glycogen depletion or overheating.
- Cadence drop below 155 spm in later laps → fatigue. Recommend drills.

### Cadence (`avg_cadence_spm`)
- **≥ 170 spm** — Excellent.
- **160–169** — Good.
- **< 160** — Flag. Recommend cadence drills (metronome running, shorter stride).

## Debrief Output Template

Use this structure for the run debrief returned to the user. HTML formatting (Telegram bridge will render it). Dates in DD/MM/YY.

```
🏃 <b>Run Debrief — DD/MM/YY</b>

<b>📊 Session</b>
• Distance: X km (planned: X km)
• Pace: M:SS/km (planned: M:SS–M:SS)
• HR: avg X / max X (Zone Z)
• Cadence: X spm

<b>📈 Patterns</b>
• Pacing: [even / positive split / negative split] — [brief interpretation]
• Cardiac decoupling: X% — [brief interpretation]
• Fatigue signals: [none / pace decay in final 2 km / etc.]

<b>🏆 Records</b>
[List any PRs set, or "No new PRs — trending toward [record] in X more runs"]

<b>📋 Next Session</b>
• [DD/MM/YY]: [Workout type] — [distance + pace targets]
• Coaching cue: [one specific actionable tip]

[If plan change recommended]
⚠️ <b>Recommendation</b>: [proposed change] — want me to update the plan?
```

## Edge Cases

- **Run not yet synced** — Garmin sync can take 5–10 minutes after finishing. Wait and retry the FIT fetch.
- **Incomplete FIT file** (workout stopped early, GPS lost) — Parse what's available; note incomplete data in debrief.
- **Very short run (< 2 km)** — Likely a warmup or aborted run. Ask Kevin: "Was this a full session or just a warmup?"
- **Pace much faster than usual (> 30 sec/km faster)** — Could be a race or time trial. Ask Kevin: "This looks like a race effort — want me to use this for updated pace targets?"
