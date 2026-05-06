# Methodology: Jack Daniels (VDOT-based)

## The core idea

Daniels' system anchors all training paces to **VDOT** — a single number derived from a recent race performance that represents the runner's current fitness. Once you know VDOT, every training pace (Easy, Marathon, Threshold, Interval, Repetition) is determined from a lookup table.

This is the most precise of the four methodologies. It works when you have a reliable performance benchmark and the discipline to hit specific paces.

## When to use Daniels

- **Race targeting with a specific time goal** — Kevin wants sub-1:45 half, Daniels gives him exact paces to train at
- **Build phase, after base is established** (≥6 weeks consistent training)
- **8–16 weeks out from race day** — close enough that current fitness is stable, far enough that there's time to drive adaptation
- **When the runner's recent race or hard workout gives a good VDOT estimate** — without that, the paces are guesses

## When NOT to use Daniels

- No recent race or time trial → use 80/20 or MAF until there is one
- Returning from injury → MAF first, Daniels later
- The runner can't pace by feel and only has a watch with HR (no GPS pace) → use 80/20's HR zones instead

## Estimating VDOT

If Kevin has a recent race, use that. Otherwise, derive from `baseline.estimated_race_pace`:

- `estimated_race_pace` is approx 10K race pace
- Use the table below to find VDOT for that pace

### Abbreviated VDOT table (covers Kevin's likely range)

| VDOT | 5K time | 10K time | Half time | Marathon time |
|------|---------|----------|-----------|---------------|
| 35 | 25:12 | 52:17 | 1:55:55 | 4:00:43 |
| 38 | 23:25 | 48:34 | 1:47:33 | 3:43:07 |
| 40 | 22:19 | 46:14 | 1:42:24 | 3:32:23 |
| 42 | 21:18 | 44:06 | 1:37:42 | 3:22:33 |
| 45 | 19:57 | 41:21 | 1:31:35 | 3:09:51 |
| 48 | 18:46 | 38:55 | 1:26:11 | 2:58:47 |
| 50 | 18:05 | 37:31 | 1:23:00 | 2:52:13 |
| 52 | 17:27 | 36:13 | 1:20:08 | 2:46:14 |
| 55 | 16:35 | 34:24 | 1:16:12 | 2:38:05 |
| 58 | 15:48 | 32:46 | 1:12:37 | 2:30:36 |
| 60 | 15:18 | 31:43 | 1:10:17 | 2:25:48 |

Full table: https://runsmartproject.com/calculator/ (or *Daniels' Running Formula*, 4th ed., Chapter 5)

## Training paces from VDOT

| Pace | Effort | Use |
|------|--------|-----|
| **E** (Easy) | ~59–74% VO2max | Aerobic base, recovery, warmup/cooldown |
| **M** (Marathon) | ~75–84% VO2max | Marathon-specific blocks |
| **T** (Threshold) | ~83–88% VO2max | Lactate threshold, "comfortably hard" |
| **I** (Interval) | ~95–100% VO2max | VO2max development |
| **R** (Repetition) | faster than I | Speed/economy, neuromuscular |

### Sample paces at VDOT 42 (representative for Kevin's likely range)

| Pace | Per km | Per mile |
|------|--------|----------|
| E | 5:32–6:09 | 8:54–9:53 |
| M | 4:57 | 7:58 |
| T | 4:41 | 7:32 |
| I | 4:18 | 6:55 |
| R | 4:00 | 6:26 |

(Compute Kevin's actual paces from his VDOT — these are illustrative.)

## Classic workouts

### Threshold (T) — the workhorse

- **Tempo run:** 20–30 min continuous at T pace
- **Cruise intervals:** 3–5 × 1.5 km @ T, 60s easy jog recovery (total T time: 7–10 min)
- **Tempo + intervals:** 15 min @ T, 5 min easy, 4 × 400m @ I pace

T-pace work is the single highest-leverage session in the Daniels system. Kevin should never go more than 10 days during build/peak without one.

### Interval (I) — VO2max work

- **Standard:** 5–6 × 1 km @ I pace, 2–3 min recovery jog (total I time: 18–24 min)
- **800s:** 6–8 × 800m @ I pace, 90s–2 min recovery
- **Mile repeats:** 4 × 1600m @ I pace, 3 min recovery

Cap I-time per session at ~10% of weekly mileage in km terms (rough heuristic). E.g., on a 50 km/wk week, max ~5 km of I work per session.

### Marathon (M) — race-specific

- **M-pace tempo:** 60–90 min continuous at M pace (only in marathon plans)
- **M-pace blocks in long runs:** last 8–12 km of a 24 km long run at M pace

### Repetition (R) — speed/economy

- **Standard:** 8–12 × 200m @ R pace, full recovery
- **400s:** 6–8 × 400m @ R pace, full recovery

R work is surprisingly underused. It's not "speed for racing" — it's neuromuscular efficiency that makes T pace feel easier.

## Sample build week (VDOT 42, ~45 km)

| Day | Session | Distance | Pace |
|-----|---------|----------|------|
| Mon | Rest | — | — |
| Tue | T workout: 4 × 1.5 km T + 2 km wu/cd | 8 km | E + T |
| Wed | E | 7 km | E |
| Thu | I workout: 5 × 1 km I + 3 km wu/cd | 8 km | E + I |
| Fri | Rest | — | — |
| Sat | E | 6 km | E |
| Sun | Long | 16 km | E |

## VDOT recalibration

Re-estimate VDOT every 4–6 weeks if Kevin runs a tune-up race or hits a workout that suggests different fitness. Don't recalibrate after one good run — wait for a pattern. When VDOT changes, all paces shift; rebuild the plan's pace columns.

The post_run_analysis workflow flags time-trial-like efforts; if Kevin confirms it was a real effort, update VDOT here and regenerate plan paces.

## Common mistakes

- **Running E too fast.** If Kevin's E pace from the table is 5:45/km, run E at 5:45–6:15. Don't run E at 5:20 because "it feels fine."
- **Skipping the wu/cd math.** A "5 × 1 km I" workout is really 8–10 km when you include warmup + recovery + cooldown. Account for this in weekly volume.
- **Treating T pace as "race pace."** T is *threshold* pace, faster than half-marathon pace, slower than 10K pace. It's specifically the pace you can sustain for ~60 minutes if you had to.
