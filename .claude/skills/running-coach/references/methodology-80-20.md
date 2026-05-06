# Methodology: 80/20 Polarized Training

## The core idea

Spend ~80% of training time at low intensity (easy/aerobic) and ~20% at high intensity (threshold/intervals). Almost nothing in the "moderate" middle zone. This avoids the "grey zone" trap where runs are too hard to build aerobic base efficiently and too easy to drive lactate-threshold improvements.

Stephen Seiler's research found this distribution among elite endurance athletes across many sports. It's not a fad — it's how the bodies that win behave.

## When to use 80/20

- **Base building blocks** — when aerobic capacity is the limiter
- **Returning runners** rebuilding from a layoff (after an initial MAF block if needed)
- **Runners stuck in the grey zone** — chronically running everything at "comfortably hard" pace and not improving
- **Simpler structure** — Kevin doesn't want to memorize Daniels paces or chase MAF heart rates
- **As the foundation underneath a Daniels build** — 80/20 isn't really opposed to Daniels; Daniels' easy/long runs are zone 1–2 and the threshold work is zone 4–5. The ratio applies even within Daniels plans.

## When NOT to use 80/20

- Race-specific peak phases where race-pace work needs to happen at moderate intensity (5K/10K race pace lives in the grey zone). Those phases need a different distribution.
- Marathon peak weeks with long runs containing race-pace blocks — those *will* push the moderate zone, and that's fine for race-specific adaptation.

## HR zones (using Garmin's 5-zone model)

Compute zones from baseline `avg_hr` and `max_hr` (or estimate `max_hr = 220 − age` if missing).

| Zone | % max HR | Feel | 80/20 bucket |
|------|----------|------|--------------|
| Z1 | 50–60% | Recovery, conversational easily | Easy (low) |
| Z2 | 60–70% | Easy aerobic, can hold conversation | Easy (low) |
| Z3 | 70–80% | "Comfortably hard," sentences not paragraphs | **Avoid (grey zone)** |
| Z4 | 80–90% | Threshold, can speak only short phrases | Hard (high) |
| Z5 | 90–100% | Intervals, no talking | Hard (high) |

**The rule:** ~80% of weekly running time in Z1–Z2, ~20% in Z4–Z5, ~0% deliberately in Z3. Z3 happens incidentally on hilly easy runs or warmups; that's fine. Don't *plan* Z3 sessions during a polarized block.

## Pace anchoring (when HR isn't reliable)

Use `baseline.easy_pace_target` for Z1–Z2 runs. For Z4 work, use `baseline.tempo_pace_target` minus 5–10 sec/km for short intervals.

## Key sessions

### Easy run

- Distance: 5–12 km depending on phase
- Pace: `easy_pace_target`, HR Z1–Z2
- Cue: *"If you can't talk in full sentences, slow down."*
- Frequency: 3–5×/week during 80/20 blocks

### Long run

- Distance: progressive, capped per §6 of SKILL.md
- Pace: `easy_pace_target` + 0–10 sec/km (slightly slower than weekday easy)
- HR: Z1–Z2 throughout; if it drifts to Z3 in the final 30 min, that's cardiac decoupling — flag it
- Frequency: 1×/week, weekend

### Threshold session (the "20%")

- Format options:
  - **Continuous tempo:** 3–6 km at threshold pace (Z4)
  - **Cruise intervals:** 3–5 × 1.5 km at threshold pace, 60–90s recovery jog
  - **Long intervals:** 4–5 × 1 km at slightly faster than threshold (low Z5), 2–3 min recovery
- Frequency: 1×/week during base, 2×/week in build (one tempo, one interval)

### Strides

- Format: 6–8 × 100m at 5K race effort (high Z5), full recovery between
- Purpose: neuromuscular sharpness, doesn't add fatigue
- Frequency: 1–2×/week, tacked onto easy runs
- Don't count strides toward the 20% — they're too short to register

## Sample week (base phase, 4 days, ~30 km)

| Day | Session | Distance | Pace/HR |
|-----|---------|----------|---------|
| Mon | Rest | — | — |
| Tue | Easy | 6 km | Z1–Z2 |
| Wed | Threshold (cruise intervals) | 4 × 1.5 km @ tempo + 1 km wu/cd | Z4 with Z2 recovery |
| Thu | Easy | 6 km + 6 strides | Z1–Z2 |
| Fri | Rest | — | — |
| Sat | Easy | 6 km | Z1–Z2 |
| Sun | Long | 11 km | Z1–Z2 |

Time-in-zone check: if Tuesday/Thursday/Saturday/Sunday are all Z1–Z2 (~75 min × 4 = 300 min) and Wednesday's quality work is ~25 min in Z4 + 25 min Z1–Z2, the polarized split lands around 89% / 11%. Push the threshold session longer or add another quality day to reach the full 20%.

## Common mistakes

- **Easy runs too fast.** Most runners run easy runs at 75–85% max HR (Z3) and call it easy. Slow down — easy means easy.
- **Quality runs too easy.** When you slow easy runs down, the temptation is to make quality runs only "moderate" too. Threshold should feel hard.
- **Counting warmup/cooldown as "easy."** They are easy, but if Kevin runs 8 km easy + 4 km tempo + 1 km cooldown, that's 13 km with 4 km hard — about 30% intensity. That's not 80/20.
