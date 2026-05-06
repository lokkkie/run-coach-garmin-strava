# Adaptive Load Progression

## Why this matters

A static training plan written 12 weeks ago can't know how Kevin's body is responding *this* week. Two runners following the same plan from the same starting fitness will adapt at different rates — one might be ready for more by week 4, the other might already be flirting with overreaching. The coach has to read the body's response and dose the next week accordingly.

The principle: **performance signals (is the training working?) and recovery signals (is the body absorbing it?) together tell you whether to push, hold, or pull back.** Get either wrong and you either stall (under-dosing) or break (over-dosing). PBs come from controlled overload — repeated cycles of stress slightly beyond current capacity, followed by recovery that supercompensates. Adaptive progression is how the coach keeps that cycle aimed at the race goal.

## The signals — computed from `.tmp/run_log.json`

`run_log.json` is appended by `analyze_fit.py` after every run. Each entry has the metrics this skill needs. Signal computation uses the last 4 weeks (or current build phase, whichever is shorter and ≥ 3 weeks).

### 1. Pace at easy HR (4-week trend)

The single most informative aerobic-adaptation signal. Filter to runs where `avg_hr < 75% max_hr`, plot avg pace vs date, compute the slope.

- **🟢 Improving:** pace dropping ≥ 5 sec/km over 4 weeks at the same HR. The aerobic engine is getting bigger — same effort, more output. This is exactly what we want to see in a build phase.
- **🟡 Flat:** ±5 sec/km. Holding fitness; not building. Normal during cutback weeks or mid-block plateaus.
- **🔴 Declining:** pace rising ≥ 5 sec/km. Aerobic capacity contracting — overtraining, illness, undernutrition, or sleep deficit. Same effort buying less.

### 2. Cardiac decoupling (4-week trend)

`cardiac_decoupling_pct` from `analyze_fit.py` measures HR drift in the second half of long runs vs the first half. A steady aerobic base shows decoupling dropping over time.

- **🟢 Declining trend** (e.g., 8% → 4% over 4 weeks): aerobic efficiency improving.
- **🟡 Flat:** maintenance.
- **🔴 Rising trend:** runs are too hard for the current base, or accumulated fatigue is leaking into long runs.

### 3. VO2max estimate (4-week trend)

Garmin's `vo2max_estimate` is noisy week-to-week but the 4-week trend is meaningful. Build/peak phases should bend it upward.

### 4. Plan adherence

`completed_sessions / planned_sessions` over the last 4 weeks.

- **🟢 ≥ 90%:** plan and life are aligned.
- **🟡 70–89%:** missing some sessions. Could be schedule, could be early fatigue.
- **🔴 < 70%:** structural mismatch. The plan isn't matching Kevin's reality and needs adjusting — probably via the §9 matrix, possibly via methodology change.

### 5. Quality session execution

For prescribed tempo/interval/race-pace sessions: did Kevin hit the target paces? `sessions_within_3pct_of_target / total_quality_sessions` over 4 weeks.

- **🟢 ≥ 90%:** he can hit the work being asked.
- **🟡 70–89%:** struggling on some quality work. Paces may be slightly too aggressive, or recovery isn't supporting them.
- **🔴 < 70%:** prescribed paces are out of reach. Recalibrate from a recent time trial (see §10) before continuing.

## Aggregation rule (lives in §9 too)

Each signal lands in 🟢/🟡/🔴. Aggregate:
- **🟢 Strong** — 4+ signals green
- **🔴 Struggling** — 3+ signals red
- **🟡 Mixed** — anything else

Multiple signals must agree before pushing or pulling back hard. One bad signal could be noise; three saying the same thing isn't.

## The ACWR principle (why ≤10%/week matters)

Acute:Chronic Workload Ratio = (this week's volume) ÷ (4-week rolling average). Sports-medicine research shows injury risk spikes when ACWR exceeds 1.3.

If Kevin's 4-week avg is 50 km/wk, that's an absolute ceiling of 65 km the next week — and that's the *injury threshold*, not the recommended bump. The §6 rule of ≤10%/wk increase keeps ACWR comfortably below 1.15 even with consecutive build weeks.

The combined adjustment matrix's "Push +5–10%" works inside this envelope. **Never stack two consecutive +10% weeks** even if performance and recovery are both green — alternate +10% with hold or cutback weeks to keep ACWR sane. Stacking compounds risk faster than fitness.

## Worked examples

### Example 1 — Push week (🟢 perf + 🟢 recovery)

- pace_at_easy_hr: 5:35 → 5:25 /km (−10 sec/km, 4 weeks) — 🟢
- cardiac_decoupling: 8% → 5% — 🟢
- vo2max: 42 → 44 — 🟢
- plan_adherence: 95% — 🟢
- quality_execution: 92% — 🟢
- Recovery: avg sleep 7.6 h, RHR Δ +1, HRV Δ +2% — all 🟢

→ **Push.** Bump weekly volume 45 → 49 km (+9%, within ceiling). Add a 6th × 1 km interval to next Tuesday's quality session.

> *"Kevin, your pace at easy HR has come down 10 sec/km in the last month and recovery is green across the board — this is the moment to lean in. Adding 4 km this week and one extra interval Tuesday. We're tracking right at sub-1:45 pace."*

### Example 2 — Hold week (🟡 perf + 🟢 recovery)

- pace_at_easy_hr: flat, cardiac_decoupling: flat, vo2max: stable, adherence: 88%, quality: 95%
- Recovery: 🟢

→ **Hold load, monitor.** Volume stays. Don't add intensity.

> *"Adaptation has plateaued — that's normal mid-block. Recovery is good so we're not in trouble; let's give the current dose another 1–2 weeks before pushing."*

### Example 3 — Recovery week (🔴 perf + 🔴 recovery)

- pace_at_easy_hr: +8 sec/km — 🔴
- cardiac_decoupling: rising — 🔴
- vo2max: dropping — 🔴
- plan_adherence: 65% — 🔴
- Recovery: 6.2 h avg sleep, RHR Δ +6, HRV Δ −12%

→ **Recovery week: −25% volume, no quality.** Propose, don't impose:

> *"All five performance signals are red and recovery is showing classic overreaching markers — RHR up 6 bpm, HRV down 12%. We're not getting fitter from here, we're digging a hole. I'd cut next week to ~34 km of all easy running, no quality, and re-assess next Sunday. PB depends on absorbing the work, not just doing more — pushing through this week would set us back further."*

## Edge cases

- **< 4 weeks of run data:** not enough for trend lines. Performance flag is `insufficient_data`. The matrix doesn't apply — run the planned week unchanged and let data accumulate.
- **Time trial / race-effort detected by post_run_analysis:** if pace targets were updated, recompute trends going forward; don't apply the new pace target retroactively to old runs.
- **Just exited a cutback week:** low volume during cutback is expected and would look like a volume drop signal. Drop volume-based signals from the aggregation that one week.
- **Methodology change in the last 4 weeks:** trends may break across the transition. Bias the flag toward 🟡 until 3+ weeks of data accumulate on the new methodology. Don't make big adjustments off a noisy trend.
- **Single very-bad run dragging the average:** one-run anomalies are `post_run_analysis.md` territory. Look for *trends*, not single data points.
- **Race-week (T ≤ 14 days):** the matrix is OFF. Only the §11 taper protocol applies. Pushing or pulling load this close to race day is more anxiety than fitness.
