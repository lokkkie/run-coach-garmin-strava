"""
Long-running Telegram bridge to Claude Code via the Claude Agent SDK.
Run this as a service on Kevin's home PC. Receives messages from Telegram,
forwards them to a persistent Claude session in this project directory,
returns Claude's responses to Telegram.

Usage:
  python tools/telegram_bridge.py

Each authorized user gets their own persistent Claude session.
Sessions start lazily on first message and persist until process restart.

Required env vars (in .env):
  TELEGRAM_BOT_TOKEN          (from @BotFather)
  ANTHROPIC_API_KEY           (from https://console.anthropic.com/settings/keys)

Authorized users are managed in users/allowlist.json (up to 5 users).
Users with "owner": true may edit project code/files; others get coaching Q&A + plan commands.
"""

import asyncio
import json
import os
import sys
import logging
from datetime import date, datetime
from pathlib import Path

from dotenv import load_dotenv
from telegram import BotCommand, Update
from telegram.constants import ChatAction, ParseMode
from telegram.error import BadRequest
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters

from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    ClaudeSDKClient,
    TextBlock,
)

# Allow importing sibling tools
sys.path.insert(0, str(Path(__file__).resolve().parent))
from sheets_read import read_sessions  # noqa: E402

PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(PROJECT_ROOT / ".env")

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
log = logging.getLogger("telegram_bridge")

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")

MAX_TG_LEN = 4000  # Telegram per-message limit is 4096; leave headroom

ALLOWLIST_PATH = PROJECT_ROOT / "users" / "allowlist.json"


def load_allowlist() -> list[dict]:
    with open(ALLOWLIST_PATH, encoding="utf-8") as f:
        return json.load(f)["users"]


def get_user(chat_id: str) -> dict | None:
    for user in load_allowlist():
        if str(user["chat_id"]) == chat_id:
            return user
    return None


_TELEGRAM_FORMATTING = """
1. **Use HTML tags, not Markdown.** Telegram parses HTML, not Markdown.
   - Bold: <b>text</b>  (NEVER use **text** or __text__)
   - Italic: <i>text</i>  (NEVER use *text* or _text_)
   - Inline code: <code>text</code>
   - Code block: <pre>multiline text</pre>
   - Links: <a href="url">label</a>
   Escape any literal &lt;, &gt;, or &amp; characters in content.

2. **Never use Markdown tables (| cell | cell |).** They render as garbled text on phones.
   Convert tables to either:
   - A bulleted list with bold labels:
     • <b>Distance:</b> 10.02 km
     • <b>Avg pace:</b> 6:03/km
   - Or labeled key:value lines (one per line, no pipes).

3. **Date format: always DD/MM/YY.** Never YYYY-MM-DD, never MM-DD, never DD-MM.
   Examples: 30/04/26, 02/05/26, 07/06/26.

4. **No Markdown headers (#, ##, ###).** Use <b>Section Name</b> on its own line for headers.

5. **Optimize for phone screens.** Short paragraphs, clear sectioning, bullets over prose.
   End each section with a blank line so messages split cleanly at section boundaries.

6. **Keep responses focused.** A typical run debrief is ~600-1200 words split across 2 messages.
   If you have a long response, structure it so paragraph breaks line up with natural section
   boundaries — the bridge splits messages at paragraph breaks, not character cutoffs."""


def make_system_prompt(user_name: str, has_data_access: bool, data_dir: str, is_owner: bool = False) -> str:
    if has_data_access:
        opening = f"You are responding via Telegram on {user_name}'s mobile device."
    else:
        opening = (
            f"You are a running coach AI assistant chatting with {user_name} via Telegram. "
            f"You don't have access to their personal fitness data — provide general coaching "
            f"advice, training guidance, pacing, and race preparation."
        )
    data_block = (
        f"\n\n<data_directory>\n"
        f"All coaching state files for {user_name} live in `{data_dir}/` (relative to project root).\n"
        f"Use this path for: coaching_state.json, plan.json, fitness_baseline.json, run_log.json, etc.\n"
        f"When writing plans to Google Sheets call:\n"
        f"  python tools/sheets_write.py --plan {data_dir}/plan.json\n"
        f"Tab names must be prefixed with the user's name to avoid collisions, e.g.:\n"
        f'  "Plan - {user_name} - <RaceName> - <YYYY-MM-DD>"\n'
        f"</data_directory>"
    )
    permissions_block = "" if is_owner else (
        "\n\n<permissions>\n"
        "You do not have permission to create, edit, delete, or execute any files in this project directory.\n"
        "If asked to modify code or configuration, decline and explain that only project owners can make code changes.\n"
        "</permissions>"
    )
    return (
        f"<telegram_formatting>\n{opening} Strict formatting rules:\n{_TELEGRAM_FORMATTING}\n</telegram_formatting>"
        + data_block
        + permissions_block
    )


def smart_split(text: str, max_len: int = MAX_TG_LEN) -> list[str]:
    """Split text into chunks <= max_len, preferring breaks at natural boundaries.
    Priority: paragraph (\\n\\n) > line (\\n) > sentence end > hard cut."""
    chunks: list[str] = []
    remaining = text.strip()
    while len(remaining) > max_len:
        window = remaining[:max_len]
        # Try break points in priority order; require the break to be in the latter
        # half of the window so we don't produce tiny chunks.
        candidates = [
            (window.rfind("\n\n"), 2),    # paragraph break
            (window.rfind("\n"), 1),       # line break
            (window.rfind(". "), 2),       # sentence end
            (window.rfind("! "), 2),
            (window.rfind("? "), 2),
            (window.rfind(".\n"), 2),
            (window.rfind("!\n"), 2),
            (window.rfind("?\n"), 2),
        ]
        # Pick the latest viable break (largest index above the half-mark)
        viable = [(idx, skip) for idx, skip in candidates if idx >= max_len // 2]
        if viable:
            idx, skip = max(viable, key=lambda x: x[0])
            chunk = remaining[:idx + (1 if skip == 2 and remaining[idx] in ".!?" else 0)]
            chunks.append(chunk.rstrip())
            remaining = remaining[idx + skip:].lstrip()
        else:
            # No natural break — hard cut at max_len
            chunks.append(remaining[:max_len])
            remaining = remaining[max_len:].lstrip()
    if remaining:
        chunks.append(remaining)
    return chunks


async def send_with_fallback(message_obj, text: str):
    """Try sending as HTML; if Telegram rejects (parse error), fall back to plain text."""
    try:
        await message_obj.reply_text(text, parse_mode=ParseMode.HTML)
    except BadRequest as e:
        log.warning("HTML parse failed (%s); falling back to plain text.", e)
        await message_obj.reply_text(text)


# ──────────────────────────────────────────────────────────────────────
# Per-user Claude sessions
# ──────────────────────────────────────────────────────────────────────
class ClaudeSession:
    """Wraps a ClaudeSDKClient kept alive for the bridge's lifetime."""
    def __init__(self, system_prompt: str):
        self._system_prompt = system_prompt
        self.client: ClaudeSDKClient | None = None
        self._lock = asyncio.Lock()

    async def start(self):
        options = ClaudeAgentOptions(
            cwd=str(PROJECT_ROOT),
            permission_mode="bypassPermissions",
            system_prompt={
                "type": "preset",
                "preset": "claude_code",
                "append": self._system_prompt,
            },
        )
        self.client = ClaudeSDKClient(options=options)
        await self.client.__aenter__()
        log.info("Claude session started in %s", PROJECT_ROOT)

    async def stop(self):
        if self.client is not None:
            await self.client.__aexit__(None, None, None)
            self.client = None

    async def query(self, message: str) -> str:
        """Send a message; collect and return all text blocks from the response."""
        if self.client is None:
            raise RuntimeError("Claude session not started.")
        async with self._lock:  # serialize messages — one in flight at a time
            await self.client.query(message)
            chunks: list[str] = []
            async for response in self.client.receive_response():
                if isinstance(response, AssistantMessage):
                    for block in response.content:
                        if isinstance(block, TextBlock):
                            chunks.append(block.text)
            return "\n".join(chunks).strip() or "(no response)"


claude_sessions: dict[str, ClaudeSession] = {}


async def get_or_create_session(chat_id: str, user: dict) -> ClaudeSession:
    if chat_id not in claude_sessions:
        has_data = "data_dir" in user
        prompt = make_system_prompt(user["name"], has_data, user.get("data_dir", ".tmp"), user.get("owner", False))
        session = ClaudeSession(prompt)
        await session.start()
        log.info("Started Claude session for %s (%s)", user["name"], chat_id)
        claude_sessions[chat_id] = session
    return claude_sessions[chat_id]


# ──────────────────────────────────────────────────────────────────────
# Slash command helpers (bypass Claude — pure Sheets reads, zero token cost)
# ──────────────────────────────────────────────────────────────────────
def is_authorized(update: Update) -> bool:
    return (update.effective_chat is not None
            and get_user(str(update.effective_chat.id)) is not None)


def get_plan_tab(user: dict) -> str:
    """Read the active plan tab name from the user's coaching_state.json."""
    state_file = PROJECT_ROOT / user["data_dir"] / "coaching_state.json"
    with open(state_file, encoding="utf-8") as f:
        state = json.load(f)
    return state["plan_sheet_tab"]


def to_dd_mm_yy(date_str: str) -> str:
    """YYYY-MM-DD → DD/MM/YY."""
    if not date_str:
        return "?"
    try:
        return datetime.strptime(date_str, "%Y-%m-%d").strftime("%d/%m/%y")
    except ValueError:
        return date_str


def fmt_session_full(s: dict, header: str) -> str:
    """One session, detailed HTML view."""
    lines = [f"<b>{header}</b>", ""]
    lines.append(f"📅 <b>{to_dd_mm_yy(s.get('date', ''))}</b> ({s.get('day', '?')})")

    if s.get("session_type") == "Rest":
        lines.append("🛌 Rest day")
        return "\n".join(lines)

    lines.append(f"<b>Type:</b> {s.get('session_type', '?')}")
    if s.get("distance_km"):
        lines.append(f"<b>Distance:</b> {s['distance_km']} km")
    if s.get("pace_target"):
        lines.append(f"<b>Pace:</b> {s['pace_target']}/km")
    if s.get("hr_zone"):
        lines.append(f"<b>HR Zone:</b> {s['hr_zone']}")
    if s.get("description"):
        lines.append(f"<b>Description:</b> {s['description']}")
    if s.get("notes"):
        lines.append(f"<b>Notes:</b> {s['notes']}")
    return "\n".join(lines)


def fmt_session_compact(s: dict) -> str:
    """One session, single-line for week summary."""
    pretty = to_dd_mm_yy(s.get("date", ""))
    day = s.get("day", "?")
    stype = s.get("session_type", "?")
    if stype == "Rest":
        return f"<b>{pretty} ({day}):</b> 🛌 Rest"
    line = f"<b>{pretty} ({day}):</b> {stype}"
    if s.get("distance_km"):
        line += f" — {s['distance_km']} km"
    if s.get("pace_target"):
        line += f" @ {s['pace_target']}"
    return line


def find_current_week(all_sessions: list[dict], today_iso: str) -> int | None:
    """Return the week number that contains today, or the most recent past week."""
    if not all_sessions:
        return None
    same_day = [s for s in all_sessions if s.get("date") == today_iso]
    if same_day:
        return same_day[0].get("week")
    past = [s for s in all_sessions if s.get("date") and s["date"] <= today_iso]
    if past:
        return past[-1].get("week")
    # Plan starts in the future
    return all_sessions[0].get("week")


# ──────────────────────────────────────────────────────────────────────
# Slash command handlers
# ──────────────────────────────────────────────────────────────────────
async def cmd_today(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update):
        return
    user = get_user(str(update.effective_chat.id))
    today_iso = date.today().isoformat()
    try:
        tab = get_plan_tab(user)
        sessions = await asyncio.to_thread(read_sessions, tab, None, today_iso)
    except Exception as e:
        log.exception("/today failed")
        await update.message.reply_text(f"⚠️ Couldn't fetch today's plan: {e}")
        return

    if not sessions:
        msg = f"📅 No session scheduled for {to_dd_mm_yy(today_iso)}."
    else:
        msg = fmt_session_full(sessions[0], header="🏃 Today's Session")
    await send_with_fallback(update.message, msg)
    log.info("/today served")


async def cmd_week(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update):
        return
    user = get_user(str(update.effective_chat.id))
    today_iso = date.today().isoformat()
    try:
        tab = get_plan_tab(user)
        all_sessions = await asyncio.to_thread(read_sessions, tab, None, None)
    except Exception as e:
        log.exception("/week failed")
        await update.message.reply_text(f"⚠️ Couldn't fetch this week's plan: {e}")
        return

    week_num = find_current_week(all_sessions, today_iso)
    if week_num is None:
        await send_with_fallback(update.message, "📅 No plan loaded.")
        return

    week_sessions = [s for s in all_sessions if s.get("week") == week_num]
    if not week_sessions:
        await send_with_fallback(update.message, f"📅 No sessions in week {week_num}.")
        return

    parts = [f"<b>📅 Training Week {week_num}</b>", ""]
    for s in week_sessions:
        parts.append(fmt_session_compact(s))
    await send_with_fallback(update.message, "\n".join(parts))
    log.info("/week served (week %s)", week_num)


async def cmd_next(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update):
        return
    user = get_user(str(update.effective_chat.id))
    today_iso = date.today().isoformat()
    try:
        tab = get_plan_tab(user)
        all_sessions = await asyncio.to_thread(read_sessions, tab, None, None)
    except Exception as e:
        log.exception("/next failed")
        await update.message.reply_text(f"⚠️ Couldn't fetch upcoming plan: {e}")
        return

    future = [
        s for s in all_sessions
        if s.get("date") and s["date"] > today_iso
        and s.get("session_type") != "Rest"
    ]
    if not future:
        msg = "📅 No upcoming non-rest sessions in the plan."
    else:
        msg = fmt_session_full(future[0], header="⏭️ Next Session")
    await send_with_fallback(update.message, msg)
    log.info("/next served")


async def cmd_plan(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update):
        return
    user = get_user(str(update.effective_chat.id))
    spreadsheet_id = os.getenv("GOOGLE_SHEETS_SPREADSHEET_ID")
    try:
        tab = get_plan_tab(user)
    except Exception:
        tab = "(unknown)"
    url = f"https://docs.google.com/spreadsheets/d/{spreadsheet_id}/edit"
    msg = (
        f"<b>📋 Full Training Plan</b>\n\n"
        f"<b>Tab:</b> {tab}\n\n"
        f'<a href="{url}">Open in Google Sheets ↗</a>'
    )
    await send_with_fallback(update.message, msg)
    log.info("/plan served")


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Onboarding command — triggers the running-coach skill's goal intake flow."""
    if not is_authorized(update):
        await update.message.reply_text("You're not authorized to use this bot.")
        return
    chat_id = str(update.effective_chat.id)
    user = get_user(chat_id)
    onboarding_msg = (
        f"Hi! I'm {user['name']} and I'd like to start working with you as my running coach. "
        "Please introduce yourself and help me get started — I want to build a training plan for a target race."
    )
    ack = await update.message.reply_text("🤔 Thinking...")
    typing_task = asyncio.create_task(keep_typing(context.bot, chat_id))
    try:
        session = await get_or_create_session(chat_id, user)
        response = await session.query(onboarding_msg)
    except Exception as e:
        log.exception("/start failed")
        typing_task.cancel()
        try:
            await ack.edit_text(f"⚠️ Bridge error: {e}")
        except Exception:
            await update.message.reply_text(f"⚠️ Bridge error: {e}")
        return
    finally:
        typing_task.cancel()
    try:
        await ack.delete()
    except Exception:
        pass
    chunks = smart_split(response, MAX_TG_LEN)
    for chunk in chunks:
        await send_with_fallback(update.message, chunk)
    log.info("/start onboarding served for %s", user["name"])


# ──────────────────────────────────────────────────────────────────────
# Generic chat handlers (forward to Claude session)
# ──────────────────────────────────────────────────────────────────────
async def keep_typing(bot, chat_id: str):
    """Re-fire the typing indicator every 4 seconds (Telegram clears it after ~5s)."""
    try:
        while True:
            await bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)
            await asyncio.sleep(4)
    except asyncio.CancelledError:
        pass


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message is None or update.effective_chat is None:
        return

    chat_id = str(update.effective_chat.id)
    user = get_user(chat_id)
    if user is None:
        log.warning("Rejected message from unauthorized chat: %s", chat_id)
        await update.message.reply_text("You're not authorized to use this bot.")
        return

    user_text = update.message.text or ""
    log.info("Received from %s: %s", user["name"], user_text[:200])

    # Immediate acknowledgement so the user sees their message landed
    ack = await update.message.reply_text("🤔 Thinking...")
    # Persistent typing indicator until Claude responds
    typing_task = asyncio.create_task(keep_typing(context.bot, chat_id))

    try:
        session = await get_or_create_session(chat_id, user)
        response = await session.query(user_text)
    except Exception as e:
        log.exception("Claude query failed")
        typing_task.cancel()
        try:
            await ack.edit_text(f"⚠️ Bridge error: {e}")
        except Exception:
            await update.message.reply_text(f"⚠️ Bridge error: {e}")
        return
    finally:
        typing_task.cancel()

    # Replace the "Thinking" placeholder with the real response
    try:
        await ack.delete()
    except Exception:
        pass  # ack may have been deleted already; not fatal

    chunks = smart_split(response, MAX_TG_LEN)
    for chunk in chunks:
        await send_with_fallback(update.message, chunk)

    log.info("Sent response (%d chars in %d message(s))", len(response), len(chunks))


async def post_init(app: Application):
    """Validate config and register slash commands on startup."""
    if not ALLOWLIST_PATH.exists():
        raise FileNotFoundError(f"Allowlist not found: {ALLOWLIST_PATH}")
    users = load_allowlist()
    log.info("Allowlist loaded: %s", [u["name"] for u in users])
    # Register the slash command menu so they appear in Telegram's UI
    await app.bot.set_my_commands([
        BotCommand("start", "Begin your coaching journey"),
        BotCommand("today", "Today's prescribed session"),
        BotCommand("week", "This week's full plan"),
        BotCommand("next", "Next scheduled run"),
        BotCommand("plan", "Open the full plan in Google Sheets"),
    ])
    log.info("Bridge ready. Slash commands registered. Sessions start lazily on first message.")


async def post_shutdown(app: Application):
    """Cleanly close all user Claude sessions on shutdown."""
    for session in claude_sessions.values():
        await session.stop()
    log.info("Bridge stopped (%d session(s) closed).", len(claude_sessions))


# ──────────────────────────────────────────────────────────────────────
# Main
# ──────────────────────────────────────────────────────────────────────
def main():
    missing = [v for v in ("TELEGRAM_BOT_TOKEN", "ANTHROPIC_API_KEY")
               if not os.getenv(v)]
    if missing:
        print(f"ERROR: missing env vars in .env: {', '.join(missing)}", file=sys.stderr)
        sys.exit(1)

    app = (
        Application.builder()
        .token(TELEGRAM_BOT_TOKEN)
        .post_init(post_init)
        .post_shutdown(post_shutdown)
        .build()
    )
    # Slash commands
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("today", cmd_today))
    app.add_handler(CommandHandler("week", cmd_week))
    app.add_handler(CommandHandler("next", cmd_next))
    app.add_handler(CommandHandler("plan", cmd_plan))
    # Fall-through: anything not a command goes to Claude
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    log.info("Starting Telegram bridge (project: %s)", PROJECT_ROOT)
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
