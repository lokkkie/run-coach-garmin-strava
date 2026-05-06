# Race-Week Taper Protocols

## What a taper does

The taper is when you stop training and start recovering. Glycogen stores top up, micro-damage repairs, and the cumulative fatigue of the build washes out. **Fitness is preserved for ~14 days after stopping intense training**, which is why we can cut volume sharply in the final 1–2 weeks without losing capacity.

The taper does not build new fitness. Anything that wasn't ready by T-14 isn't going to be ready on race day. Trying to add work during the taper produces fatigue, not improvement.

## Volume reduction targets

| Distance | Taper duration | Volume cut from peak |
|----------|----------------|---------------------|
| 5K / 10K | 7 days | ~40% |
| Half | 10 days | ~50% |
| Marathon | 14 days | ~60% |

Volume cuts come from reducing run distance, not run frequency. **Keep the same run days** — frequency preserves neuromuscular patterning. Just make each run shorter.

## Intensity preservation

Cut volume but keep intensity in the program. Race-pace strides, short race-pace blocks, and one short tempo session in the taper window keep the legs sharp.

What's removed: long intervals, threshold runs over 20 min, mileage long runs.

## 5K / 10K taper (7 days)

### Sample week leading into Saturday race

| Day | Session | Distance |
|-----|---------|----------|
| Sun (T-6) | Easy | 60% of normal |
| Mon | Rest | — |
| Tue (T-4) | Race-pace work: 3 × 1 km @ race pace, full recovery | 7 km total |
| Wed | Easy | 6 km |
| Thu | Easy + 6 strides | 5 km |
| Fri | 20 min easy + 4 × 100m strides OR full rest | 3 km or 0 |
| Sat | RACE | 5–10 km |

## Half marathon taper (10 days)

### Sample two weeks leading into Sunday race

#### Week T-10 (10 days out)
| Day | Session | Distance |
|-----|---------|----------|
| Mon | Rest | — |
| Tue | Tempo: 4 km @ T pace + 2 km wu/cd | 6 km |
| Wed | Easy | 8 km |
| Thu | Intervals: 4 × 1 km @ I, 2 km wu/cd | 8 km |
| Fri | Rest | — |
| Sat | Easy | 6 km |
| Sun | Long: 14 km (down from 18 peak) | 14 km |

Weekly total: 42 km (down from ~60 km peak).

#### Race week
| Day | Session | Distance |
|-----|---------|----------|
| Mon | Rest | — |
| Tue | Race-pace: 3 km @ goal pace + 2 km wu/cd | 5 km |
| Wed | Easy | 5 km |
| Thu | Easy + 6 strides | 5 km |
| Fri | Rest | — |
| Sat | 20 min easy + 4 × 100m strides | 3 km |
| Sun | RACE | 21 km |

Race-week total: 18 km + race.

## Marathon taper (14 days)

### Three weeks leading into Sunday race

#### Week T-14 (last "real" week)
| Day | Session | Distance |
|-----|---------|----------|
| Mon | Rest | — |
| Tue | LT: 6 km @ LT in 12 km run | 12 km |
| Wed | Medium-long | 16 km (down from peak 22) |
| Thu | Recovery | 6 km |
| Fri | General aerobic | 9 km |
| Sat | Recovery | 5 km |
| Sun | Last long run: 24 km (down from peak 32) | 24 km |

Weekly total: 72 km (down from ~95 km peak).

#### Week T-7
| Day | Session | Distance |
|-----|---------|----------|
| Mon | Rest | — |
| Tue | LT-light: 3 km @ LT in 10 km run | 10 km |
| Wed | Easy | 10 km |
| Thu | Easy | 8 km |
| Fri | Rest | — |
| Sat | Easy | 6 km |
| Sun | Long: 16 km, last 4 km @ M | 16 km |

Weekly total: 50 km.

#### Race week (T-1 to T-6)
| Day | Session | Distance |
|-----|---------|----------|
| Mon | Rest | — |
| Tue | M-pace work: 4 × 1 km @ M, 2 km wu/cd | 7 km |
| Wed | Easy | 7 km |
| Thu | Easy + 4 strides | 5 km |
| Fri | Rest | — |
| Sat | 20 min easy + 4 × 100m strides | 3 km |
| Sun | RACE | 42 km |

Race-week total: 22 km + race.

## Day-before options

Both work — pick the one that calms Kevin's nerves:

- **20 min easy + 4 × 100m strides** — flushes legs, primes neuromuscular system, prevents the "stiff from sitting all day" feeling
- **Full rest** — for runners who feel tired by accumulated taper-week running and want to bank one more rest day

Default to the 20 min option unless Kevin has expressed otherwise. Store his preference in `coaching_state.json`.

## Race-day warmup

### 5K / 10K
- 15–20 min easy jog
- 4–5 dynamic mobility drills (leg swings, lunges)
- 4 × 100m strides at 5K pace, full recovery
- 5 min standing/walking, sip water
- To start line 5 min before gun

### Half marathon
- 10–15 min easy jog (some half-marathoners skip this entirely; it depends on Kevin)
- 3 × 100m strides at race pace
- To start line 10 min before gun

### Marathon
- No real warmup needed — first 5 km of the race is the warmup
- Walk 5–10 min before start to stay loose
- Dynamic mobility drills if standing in corral too long

## Race-day fueling cue

- **5K:** light snack 1–2 h before (banana, half a bagel)
- **10K:** small carb-focused breakfast 2 h before
- **Half:** carb-focused breakfast 2.5–3 h before; consider 1 gel at km 12
- **Marathon:** full pre-race meal 3 h before; gel every 5–7 km starting at km 8; sports drink at every aid station

## Race-day pacing

### Default cue: even or slight negative split

The most common race-day mistake is going out too fast in the first 5 km on adrenaline. Coach Kevin to:

- First km: **5–10 sec/km slower than goal pace** — let the field pull ahead, ignore them
- km 2–10 (5K) / km 2–18 (half) / km 2–32 (marathon): **goal pace exactly**
- Final segment: whatever's left in the tank

If Kevin has a specific pacing weakness from his cycle (e.g., often goes out too fast based on `pacing_discipline_pct` from run_log.json), make this cue explicit and tied to that history.

## Race-week sickness/injury decision tree

This is the exception to the race-week guard.

### Cold/flu in race week
- **Above the neck only** (runny nose, sore throat, no fever): proceed with reduced expectations
- **Below the neck** (chest, fever, body aches): DNS recommended. Quote: *"Racing through a chest infection risks myocarditis. The race is not worth that. Defer to the next cycle."*

### Tweak/strain in race week
- **Mild, no pain on warmup jog:** proceed; warmup will tell you more than rest will
- **Pain on warmup or during easy running:** DNS or DNF risk is high. Honest conversation: *"You're 80% on a bad day. Decide if 80% effort to a finish is worth it for this race specifically, or if defer is the better call."*

Never override Kevin's decision on race day. Surface the medical reasoning, then defer to him.

## Common mistakes

- **Cramming workouts in the taper.** "I missed last week, I'll do an extra interval session this week to make up." No — adds fatigue, won't add fitness.
- **Eating differently because "it's race week."** Stick to normal foods. Race-week is not the time to try new pre-run meals or supplements.
- **Sleeping in to "rest more."** Rest is good; circadian disruption is not. Keep normal sleep schedule.
- **Skipping the day-before run.** For most runners, a short shakeout helps. The "save the legs" instinct often produces stiff legs on race morning.
- **Adding mileage to feel less anxious.** Anxiety in taper week is a feature, not a bug. Don't run to fix it; do other things.
