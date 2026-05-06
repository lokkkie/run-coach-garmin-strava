# Methodology: MAF (Maffetone Method)

## The core idea

Phil Maffetone's method is **heart-rate-capped aerobic training**. All running stays below a calculated HR ceiling (the "MAF HR"), which targets the upper edge of pure aerobic metabolism. The thesis: most runners spend too much time too hard, never developing the aerobic engine that powers everything else. Cap the HR, run "frustratingly slow" for 8–16 weeks, watch pace at MAF HR drop dramatically.

MAF is the most patient methodology in this toolkit. It's also the most reliable way to recover from overtraining or injury.

## The 180-formula

```
MAF HR = 180 − age + adjustments
```

Adjustments:
- **−10** if recovering from major illness/injury, on regular medication, or chronically overtrained
- **−5** if injured, regressing, or getting more than 2 colds/year
- **0** if training consistently for 2+ years without injury
- **+5** if training competitively for 2+ years with steady improvement and no issues

For Kevin (assume 30 years old, no major issues, intermediate runner): 180 − 30 + 0 = **150 bpm MAF HR**.

Verify against `baseline.avg_hr`. If avg_hr on easy runs is already > 150, the runner is grey-zoning easy runs and MAF will feel painfully slow at first. That's expected — and it's exactly the problem MAF solves.

## When to use MAF

- **Returning from injury** — first 2–4 weeks regardless of where the macrocycle was
- **Very deconditioned baseline** — `consistency_weeks_with_runs < 6` or `pace_trend = declining`
- **Chronic cardiac decoupling > 10%** in `run_log.json` over multiple runs — clear signal of inadequate aerobic base
- **Explicit aerobic-first request** — Kevin wants to "build the engine"
- **Off-season block** — 4–6 weeks of MAF after a race cycle to reset before the next build

## When NOT to use MAF

- **< 8 weeks before a target race** — MAF takes 8+ weeks to show benefits; not enough time
- **Peak phase of any race-targeted plan** — race pace work doesn't happen at MAF HR
- **Runner unwilling to slow down** — MAF requires discipline that some runners refuse; if Kevin says "this is too slow, I hate it" by week 2, switch methodologies

## The MAF test

Run a fixed distance (5 km is standard) at exactly MAF HR every 2–4 weeks. Track average pace.

- **Pace dropping over time** = aerobic adaptation working, MAF is paying off
- **Pace flat for 4+ weeks** = aerobic plateau, time to add intensity (move out of pure MAF)
- **Pace rising** = overtraining, life stress, sleep deficit, or illness coming on

The MAF test is the diagnostic that tells you when to leave MAF and progress to 80/20 or Daniels.

## Sample MAF block (4 weeks, transitioning from injury return)

### Week 1 (return week)
| Day | Session | Distance | HR cap |
|-----|---------|----------|--------|
| Mon | Rest | — | — |
| Tue | Easy | 4 km | MAF |
| Wed | Rest | — | — |
| Thu | Easy | 4 km | MAF |
| Fri | Rest | — | — |
| Sat | Easy | 5 km | MAF |
| Sun | Rest | — | — |

### Week 2
Build to 4 days/week, 5–6 km each.

### Week 3
| Day | Session | Distance | HR cap |
|-----|---------|----------|--------|
| Mon | Rest | — | — |
| Tue | Easy | 6 km | MAF |
| Wed | Easy | 5 km | MAF |
| Thu | MAF test | 5 km | MAF (record pace) |
| Fri | Rest | — | — |
| Sat | Easy | 6 km | MAF |
| Sun | Long | 10 km | MAF |

### Week 4
Increase long run to 12 km, total weekly volume ~32 km. Test again at end of block.

## What MAF feels like

- Heart rate ceiling forces walking on uphills (this is correct, not a failure)
- Pace at MAF HR will be 60–90 sec/km slower than usual easy pace at first
- After 6–8 weeks, pace at MAF HR drops 30–60 sec/km — that's the adaptation signal
- "Bored, frustrated, and itching to run faster" is the standard mid-block emotional experience

Kevin will want to bail by week 3. Hold the line. Tell him: *"This is the part that works. The slowness is doing the work. We add intensity once you've earned the aerobic base back — usually around week 6."*

## Transitioning out of MAF

Once the MAF test pace has improved meaningfully (≥30 sec/km drop) and is plateauing:

1. Add 1×/week strides (6 × 100m, full recovery — these don't violate MAF in a meaningful way because they're too short to spike average HR)
2. Following week, add 1×/week threshold work (start with 3 × 1 km @ T pace from Daniels VDOT estimate)
3. Continue MAF on remaining easy days

This is the natural bridge to 80/20 or Daniels build.

## Common mistakes

- **Cheating the HR cap.** MAF only works if Kevin honors it. "I let it go to 155 on the hill" undermines the entire block.
- **Quitting too early.** First 2 weeks feel awful. Adaptation begins around week 4–5. Don't bail at week 3.
- **MAF during a race build.** MAF and race-specific work are incompatible — you can't run intervals at MAF HR. Use MAF *between* race builds, not inside them.
- **Ignoring rising MAF test pace.** If MAF test pace rises across two consecutive tests, something is wrong (sleep, stress, undernutrition, illness). Don't add volume to "push through" — investigate the underlying cause.
