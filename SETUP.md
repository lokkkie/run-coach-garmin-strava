# Run Coach — Local Automation Setup

This guide sets up the always-on coaching system on your home PC:
- **Polling check** — hourly Garmin scan via Windows Task Scheduler
- **Telegram bridge** — long-running service so you can chat with Claude Code from your iPhone

Prerequisites: project already installed, dependencies installed (`pip install -r requirements.txt`), `.env` partially filled (Garmin + Google Sheets).

---

## 1. Telegram Bot Setup (5 min)

### Create the bot
1. Open Telegram → search **@BotFather** → send `/newbot`
2. Name: anything you want (`Kevin Run Coach`)
3. Username: must end in `bot` (e.g., `kevin_run_coach_bot`)
4. **Copy the token** BotFather sends — looks like `1234567890:ABCdefGHI...`

### Find your chat ID
1. Search for the bot you just made → send it any message (e.g., `hi`)
2. Open this URL in any browser, replacing `<TOKEN>` with the token from step above:
   ```
   https://api.telegram.org/bot<TOKEN>/getUpdates
   ```
3. Find `"chat":{"id": XXXXXXXXX, ...}` → that number is your chat ID

### Get your Anthropic API key
1. Go to https://console.anthropic.com/settings/keys
2. Create a new key → name it `Run Coach Telegram Bridge` → **copy it**

### Add all three to `.env`
Paste them into the placeholders:
```
ANTHROPIC_API_KEY=sk-ant-...
TELEGRAM_BOT_TOKEN=1234567890:ABCdefGHI...
TELEGRAM_CHAT_ID=987654321
```

### Test the notification path
```powershell
python tools\telegram_notify.py "Test from Run Coach"
```
You should get a message in Telegram. If not, double-check the token + chat ID.

---

## 2. Windows Task Scheduler — Hourly Polling (3 min)

1. Open **Task Scheduler** (Start menu → "Task Scheduler")
2. Right pane → **Create Task...** (NOT "Create Basic Task")

### General tab
- Name: `Run Coach - Hourly Polling`
- Description: `Checks Garmin Connect for new runs and queues them for analysis`
- ☑ Run whether user is logged on or not
- ☑ Run with highest privileges
- Configure for: Windows 11

### Triggers tab
- New...
- Begin the task: **On a schedule**
- Daily, start `5:00:00 AM`
- ☑ Repeat task every: **1 hour** for a duration of: **17 hours**
- ☑ Enabled
- OK

### Actions tab
- New...
- Action: **Start a program**
- Program/script: `C:\Users\Kevin Lok\AppData\Local\Programs\Python\Python310\python.exe`
- Add arguments: `tools\polling_check.py`
- Start in: `c:\sandbox\Agentic\Run Coach`
- OK

### Conditions tab
- ☐ Start the task only if the computer is on AC power (uncheck — you want it on battery too)
- ☐ Wake the computer to run this task (leave unchecked)

### Settings tab
- ☑ Allow task to be run on demand
- ☑ Stop the task if it runs longer than: 30 minutes
- If the task fails, restart every: 5 minutes, attempt up to: 2 times

Click OK → enter your Windows password if prompted.

### Verify
Right-click the task → **Run**. Check `.tmp/polling_check.log` (or look at last_analyzed_id.txt updating). Then it'll run hourly automatically.

---

## 3. Telegram Bridge — Auto-Start on Boot (5 min)

The bridge needs to run continuously so your bot is always responsive.

### Option A: Startup Folder (simplest)

1. Press `Win+R` → type `shell:startup` → Enter
2. This opens your Startup folder. Right-click → **New → Shortcut**
3. Location: paste this entire line:
   ```
   "C:\Users\Kevin Lok\AppData\Local\Programs\Python\Python310\pythonw.exe" "c:\sandbox\Agentic\Run Coach\tools\telegram_bridge.py"
   ```
   Note: `pythonw.exe` (not `python.exe`) runs without a console window.
4. Name: `Run Coach Telegram Bridge`
5. Click Finish

That shortcut will launch the bridge silently every time you log in.

### Option B: Task Scheduler (more robust — recommended if you reboot rarely)

Same steps as the polling task, but:
- Triggers: **At log on** of your user, no schedule
- Actions: program `pythonw.exe`, arguments `tools\telegram_bridge.py`, start in project dir
- Conditions: uncheck "Start only if on AC power"
- Settings: ☐ Stop the task if it runs longer than (uncheck — bridge runs forever)

### First start (manual)

You don't need to reboot to start it now. Just run:
```powershell
python tools\telegram_bridge.py
```
You should see `Bridge ready. Send messages to your bot.` Open Telegram on your phone, message your bot, and watch the response come back. Once confirmed, kill the manual run (Ctrl+C) and rely on auto-start.

---

## 4. Daily Flow (after setup)

```
You finish a run → Garmin auto-syncs (1–2 min)
                       ↓
   Within 1 hour → polling_check fires → detects new run → fetches FIT, parses
                       ↓
   You get a Telegram notification: "🏃 New run detected: 12 km @ 5:08/km..."
                       ↓
   You open Telegram → reply "analyze" (or "debrief" / "how was it")
                       ↓
   Bridge forwards to Claude → Claude reads pending_analysis.json, runs full
   post_run_analysis workflow, returns coaching debrief
                       ↓
   You read it on iPhone, reply with follow-ups if needed
```

You can also chat with the bot for anything else — weekly check-ins, plan questions, "what's tomorrow?", etc. It's a full Claude Code session in your project, accessible from anywhere.

---

## 5. Troubleshooting

**Polling task shows last run "Failed":**
- Open the task → History tab → look at the error
- Most common: 429 from Garmin. Tool exits silently in that case — not really a failure
- If credentials are wrong, the task fails fast. Re-run `tools\garmin_fetch_csv.py` manually to confirm Garmin login works

**Telegram notification not received:**
- `python tools\telegram_notify.py "test"` — does this work?
- Double-check `TELEGRAM_CHAT_ID` is the *number*, not a username
- Make sure you sent at least one message to the bot before grabbing chat ID

**Bridge doesn't respond:**
- Confirm the Python process is running: Task Manager → look for `pythonw.exe`
- Check `.env` has all three: `ANTHROPIC_API_KEY`, `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`
- Try manual run with `python tools\telegram_bridge.py` (not pythonw) so you see logs

**Bridge says "Unauthorized chat ID":**
- The chat ID in `.env` doesn't match the chat that's messaging the bot
- Bridge only responds to your personal chat ID for security

**Cost monitoring:**
Each Telegram conversation calls the Anthropic API. Monitor at https://console.anthropic.com/settings/usage. Typical post-run debrief = $0.10–0.30. Hourly polling = no API cost (it's a deterministic Python script).

---

## 6. Disabling / Pausing

- Pause polling: open Task Scheduler → right-click task → **Disable**
- Stop the bridge: close the `pythonw.exe` process in Task Manager (or remove it from startup folder)
