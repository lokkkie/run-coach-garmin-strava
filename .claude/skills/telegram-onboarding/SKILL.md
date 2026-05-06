---
name: telegram-onboarding
description: Guides new users through the Telegram run coach bot setup. Always use this skill when /start is received in a Telegram session, when a user is connecting their fitness tracker for the first time, when they ask to start over, or when they have no coaching_state.json yet. Covers race goal collection, self-reported fitness baseline, Garmin or Strava platform auth, and a bot command walkthrough. Do not skip this skill for new users — it sets up the data foundation everything else depends on.
---

## Purpose

Walk a new user through three phases in one conversation thread. Keep each Telegram message short and focused — they're on a phone. Don't dump multiple questions in one go; pace the conversation naturally.

The three phases must happen in order:
1. **Goal + fitness baseline** — what they're training for and where they're starting from
2. **Platform setup** — connect Garmin or Strava so their run data can sync
3. **Command handoff** — brief summary of what the bot can do

---

## Phase 1: Running Goal

Open with a short, warm intro (2–3 sentences). Then ask about their target race. Collect these across 2–3 messages — don't list every question at once:

- Race name and distance (5K / 10K / half / full)
- Race date
- Target finish time — or "just finish" is a completely valid answer
- Any prior experience at this distance (rough finish time, or first time)

If `{data_dir}/fitness_baseline.json` already exists, skip Phase 1b — you already have their history.

### Phase 1b: Self-reported fitness baseline

Only run this if no baseline file exists yet. Ask these three questions in a single message:

> 1. Roughly how many km/week are you running right now?
> 2. What's a comfortable easy pace for you — or how long does 5km take you?
> 3. What's your longest run in the past month?

Once they answer, write `{data_dir}/fitness_baseline.json`:

```json
{
  "assessment_date": "YYYY-MM-DD",
  "source": "self-reported",
  "avg_weekly_km": <number>,
  "longest_run_km": <number>,
  "easy_pace_range": "<e.g. 7:00–8:00>",
  "fitness_level": "<beginner|intermediate|advanced>",
  "notes": "Self-reported at onboarding. Will be enriched once platform data syncs."
}
```

**Fitness level heuristic:**
- `beginner` — under 15 km/week, or running less than 6 months
- `intermediate` — 15–50 km/week, running 6+ months consistently
- `advanced` — over 50 km/week, or has completed a half or full marathon before

Derive `easy_pace_range` from their reported pace or 5km time. If they say "I run 5km in 35 minutes", that's a 7:00/km easy pace — use a ±45s band around it.

---

## Phase 2: Platform Setup

Ask: "Which app do you use to track your runs — **Garmin Connect** or **Strava**?"

### Garmin

Ask for their Garmin Connect email and password. Reassure them it's stored locally on the server and only used to sync their run data.

Once provided, run:
```bash
python tools/garmin_auth.py --save --user {user_name} --email <their_email> --password <their_password>
```

If login succeeds, then set it as the active source:
```bash
python tools/set_source.py garmin --user {user_name}
```

Tell them Garmin is connected and their runs will sync automatically.

If login fails, surface the error and let them retry or switch to Strava instead.

### Strava (two-step flow)

**Step 1 — Generate the auth URL:**
```bash
python tools/strava_auth.py --manual --user {user_name}
```

Read the URL from stdout and send it to the user as a tappable link:

> Tap this link to connect your Strava account: [URL]
>
> After you authorize, the page will show a connection error — that's expected. Copy the full URL from the address bar and paste it back here.

**Step 2 — Complete the exchange** (once they paste the redirect URL):
```bash
python tools/strava_auth.py --redirect-url "<their_pasted_url>" --user {user_name}
python tools/set_source.py strava --user {user_name}
```

Confirm with: "Strava connected ✓"

If either command fails, surface the error message and tell them to check `.env` for `STRAVA_CLIENT_ID` and `STRAVA_CLIENT_SECRET`.

### Neither / not sure

Record the preference for now and move on:
```json
// in {data_dir}/coaching_state.json
"data_source": "manual"
```

Let them know they can connect a platform later by messaging the bot.

---

## Phase 3: Command Summary

Once the platform step is done, send this closing message (use HTML — no Markdown):

```
<b>You're all set! Here's what I can do:</b>

/today — Today's prescribed training session
/week — Your full training week at a glance
/next — Next upcoming workout
/plan — Open your full plan in Google Sheets

Message me anytime to log a run, ask coaching questions, or adjust your plan.
```

Then transition naturally into plan generation: "Now let's build your plan for [race name]." Hand off to the running-coach skill to run the realism gate and generate the periodised training plan based on the goal you collected in Phase 1.

---

## Formatting rules

These apply to every message in this skill:

- HTML only: `<b>bold</b>`, `<i>italic</i>`, `<code>inline</code>` — never use `**`, `_`, or `#`
- Dates: always DD/MM/YY (e.g. 07/06/26), never YYYY-MM-DD or MM/DD
- No Markdown tables — use bullet lists with bold labels instead
- Keep each message under ~600 words so it reads cleanly on mobile
