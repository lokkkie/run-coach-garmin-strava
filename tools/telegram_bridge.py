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
import re
import socket
import subprocess
import sys
import logging
from datetime import date, datetime, timezone
from pathlib import Path

# TLS trust: use the OS certificate store (Windows cert store / macOS Keychain /
# Linux system bundle) instead of httpx's built-in store. Required on Python 3.14
# + httpx 0.28 on Windows, where the default SSL context can't find a usable CA
# bundle and every Telegram request fails with CERTIFICATE_VERIFY_FAILED.
# Must run BEFORE httpx/telegram imports so they pick up the injected SSL context.
try:
    import truststore
    truststore.inject_into_ssl()
except ImportError:
    pass

from telegram import BotCommand, BotCommandScopeChat, Update
from telegram.constants import ChatAction, ParseMode
from telegram.error import BadRequest
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters

from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    ClaudeSDKClient,
    TextBlock,
)

# Resolve project root via runcoach.paths (__file__-based, cwd-independent).
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from runcoach.paths import PROJECT_ROOT, ALLOWLIST_PATH  # noqa: E402
from runcoach.telegram_format import MAX_TG_LEN, smart_split  # noqa: E402

# Allow importing sibling tools (sheets_read still lives in tools/).
sys.path.insert(0, str(PROJECT_ROOT / "tools"))
from sheets_read import read_sessions  # noqa: E402

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
log = logging.getLogger("telegram_bridge")

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")

CONTACT_LOG_PATH = PROJECT_ROOT / "users" / "contact_log.json"

_contact_log_lock = asyncio.Lock()
_allowlist_lock = asyncio.Lock()

# Sentinel exit code: tells bridge_supervisor.py to relaunch the bridge.
# Code 0 = clean shutdown (supervisor stops); any other code = crash (supervisor
# backs off and respawns). 42 specifically signals "intentional restart".
RESTART_EXIT_CODE = 42

# Singleton lock for the bridge itself. The supervisor uses 48733; the bridge
# uses 48734 so the two layers can lock independently. Without this, a stray
# `python tools/telegram_bridge.py` would happily run alongside the supervisor's
# child and both would poll Telegram's getUpdates, breaking each other's
# delivery (Telegram only delivers each update to one long-poll at a time, so
# replies become non-deterministic). Binding fails fast if another bridge is
# already alive.
BRIDGE_SINGLETON_PORT = 48734

_NAME_RE = re.compile(r"[A-Za-z0-9_-]+")


def _acquire_bridge_lock(port: int = BRIDGE_SINGLETON_PORT) -> socket.socket | None:
    """Bind 127.0.0.1:`port` for this bridge's lifetime.
    Returns the socket on success, None if another bridge already holds it.
    Caller must keep the socket alive — closing releases the lock.
    Mirrors `bridge_supervisor.acquire_singleton_lock`; both layers lock
    independently so a direct bridge launch is also rejected, not just a
    direct second supervisor launch."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    # Deliberately NOT setting SO_REUSEADDR — bind must fail if another bridge
    # is already bound, which is the entire point of this lock.
    try:
        sock.bind(("127.0.0.1", port))
        sock.listen(1)
        return sock
    except OSError:
        sock.close()
        return None


def load_allowlist() -> list[dict]:
    with open(ALLOWLIST_PATH, encoding="utf-8") as f:
        return json.load(f)["users"]


def save_allowlist(users: list[dict]) -> None:
    """Atomic rewrite of allowlist.json (.tmp + replace, same pattern as contact_log)."""
    ALLOWLIST_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = ALLOWLIST_PATH.with_suffix(".json.tmp")
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump({"users": users}, f, indent=2, ensure_ascii=False)
    tmp_path.replace(ALLOWLIST_PATH)


def get_user(chat_id: str) -> dict | None:
    for user in load_allowlist():
        if str(user["chat_id"]) == chat_id:
            return user
    return None


async def record_contact(update: Update, command: str | None = None) -> None:
    """Update the contact log with metadata for whoever sent this update.

    Tracks every chat that reaches the bot — authorized or not — so we have a
    record of who has tried to interact for future expansion of access. Stored
    at users/contact_log.json (gitignored). Lock-serialized; the file is
    rewritten atomically via a .tmp + replace.
    """
    if update.effective_user is None or update.effective_chat is None:
        return

    user = update.effective_user
    chat_id = str(update.effective_chat.id)
    now_iso = datetime.now(timezone.utc).isoformat(timespec="seconds")
    authorized = get_user(chat_id) is not None

    async with _contact_log_lock:
        if CONTACT_LOG_PATH.exists():
            try:
                with open(CONTACT_LOG_PATH, encoding="utf-8") as f:
                    data = json.load(f)
            except (json.JSONDecodeError, OSError):
                data = {"contacts": []}
        else:
            CONTACT_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
            data = {"contacts": []}

        contacts = data.setdefault("contacts", [])
        record = next((c for c in contacts if c.get("chat_id") == chat_id), None)
        if record is None:
            record = {
                "chat_id": chat_id,
                "user_id": user.id,
                "first_seen": now_iso,
                "message_count": 0,
                "command_count": 0,
            }
            contacts.append(record)

        record["username"] = user.username
        record["first_name"] = user.first_name
        record["last_name"] = user.last_name
        record["language_code"] = user.language_code
        record["is_bot"] = user.is_bot
        record["last_seen"] = now_iso
        record["authorized"] = authorized
        if command:
            record["command_count"] = record.get("command_count", 0) + 1
            record["last_command"] = command
        else:
            record["message_count"] = record.get("message_count", 0) + 1

        tmp_path = CONTACT_LOG_PATH.with_suffix(".json.tmp")
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        tmp_path.replace(CONTACT_LOG_PATH)


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
# Tools blocked for non-owner sessions. These can write to the file system or
# execute arbitrary commands inside the project tree — owners only. Enforcing
# at the SDK level (not just via system prompt) so a prompt-injection attempt
# from a non-owner chat cannot reach Edit/Write/Bash even if it convinces the
# model to try.
NON_OWNER_DISALLOWED_TOOLS = [
    "Bash", "PowerShell", "Edit", "Write", "NotebookEdit", "Agent",
]


class ClaudeSession:
    """Wraps a ClaudeSDKClient kept alive for the bridge's lifetime."""
    def __init__(self, system_prompt: str, disallowed_tools: list[str] | None = None):
        self._system_prompt = system_prompt
        self._disallowed_tools = disallowed_tools or []
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
            disallowed_tools=list(self._disallowed_tools),
        )
        self.client = ClaudeSDKClient(options=options)
        await self.client.__aenter__()
        log.info(
            "Claude session started in %s (disallowed_tools=%s)",
            PROJECT_ROOT, self._disallowed_tools or "[]",
        )

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
        is_owner = bool(user.get("owner"))
        prompt = make_system_prompt(user["name"], has_data, user.get("data_dir", ".tmp"), is_owner)
        disallowed = [] if is_owner else NON_OWNER_DISALLOWED_TOOLS
        session = ClaudeSession(prompt, disallowed_tools=disallowed)
        await session.start()
        log.info("Started Claude session for %s (%s, owner=%s)", user["name"], chat_id, is_owner)
        claude_sessions[chat_id] = session
    return claude_sessions[chat_id]


# ──────────────────────────────────────────────────────────────────────
# Slash command helpers (bypass Claude — pure Sheets reads, zero token cost)
# ──────────────────────────────────────────────────────────────────────
def is_authorized(update: Update) -> bool:
    return (update.effective_chat is not None
            and get_user(str(update.effective_chat.id)) is not None)


def is_owner(update: Update) -> bool:
    """True iff the chat belongs to a user with `owner: true` in the allowlist."""
    if update.effective_chat is None:
        return False
    user = get_user(str(update.effective_chat.id))
    return bool(user and user.get("owner"))


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
    await record_contact(update, command="today")
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
    await record_contact(update, command="week")
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
    await record_contact(update, command="next")
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
    await record_contact(update, command="plan")
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
    await record_contact(update, command="start")
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
# Owner-only admin commands
#
# These are NOT registered in set_my_commands, so they don't appear in
# Telegram's slash-command menu. They still work when typed directly.
# Non-owners get no reply at all so the commands' existence isn't leaked
# (unauthorized users probing slash commands see total silence, exactly
# like sending a normal message would).
# ──────────────────────────────────────────────────────────────────────
async def cmd_contacts(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """List recent contacts. Default: pending (unauthorized) only. Pass `all` to dump everyone."""
    await record_contact(update, command="contacts")
    if not is_owner(update):
        return

    args = context.args or []
    show_all = bool(args) and args[0].lower() == "all"

    if not CONTACT_LOG_PATH.exists():
        await update.message.reply_text("(contact log is empty)")
        return
    try:
        with open(CONTACT_LOG_PATH, encoding="utf-8") as f:
            contacts = json.load(f).get("contacts", [])
    except (json.JSONDecodeError, OSError) as e:
        await update.message.reply_text(f"⚠️ Couldn't read contact log: {e}")
        return

    if not show_all:
        contacts = [c for c in contacts if not c.get("authorized")]
    contacts.sort(key=lambda c: c.get("last_seen", ""), reverse=True)

    if not contacts:
        await update.message.reply_text(
            "No pending contacts." if not show_all else "No contacts on record."
        )
        return

    header_label = "All contacts" if show_all else "Pending contacts"
    lines = [f"<b>📇 {header_label} ({len(contacts)})</b>", ""]
    for c in contacts[:30]:
        first = (c.get("first_name") or "").strip()
        last = (c.get("last_name") or "").strip()
        display = (f"{first} {last}".strip()
                   or c.get("username")
                   or "?")
        badge = "✅" if c.get("authorized") else "⏳"
        lines.append(f"{badge} <code>{c.get('chat_id', '?')}</code> · <b>{display}</b>")
        extras = []
        if c.get("username"):
            extras.append(f"@{c['username']}")
        extras.append(f"msgs={c.get('message_count', 0)}")
        extras.append(f"cmds={c.get('command_count', 0)}")
        last_seen = (c.get("last_seen") or "")[:16]
        if last_seen:
            extras.append(f"last={last_seen}")
        lines.append("    " + " · ".join(extras))
    if len(contacts) > 30:
        lines.append(f"\n…and {len(contacts) - 30} more.")
    if not show_all:
        lines.append("\n<i>Use</i> <code>/contacts all</code> <i>to see everyone, including authorized users.</i>")

    await send_with_fallback(update.message, "\n".join(lines))
    log.info("/contacts served (%s, %d entries)", "all" if show_all else "pending", len(contacts))


async def cmd_allow(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Add a chat_id to the allowlist. Usage: /allow <chat_id> <name>"""
    await record_contact(update, command="allow")
    if not is_owner(update):
        return

    args = context.args or []
    if len(args) < 2:
        await send_with_fallback(
            update.message,
            "Usage: <code>/allow &lt;chat_id&gt; &lt;name&gt;</code>\n"
            "Example: <code>/allow 123456789 Alice</code>",
        )
        return

    target_chat_id_str = args[0].strip()
    name = args[1].strip()

    try:
        target_chat_id = int(target_chat_id_str)
    except ValueError:
        await update.message.reply_text(f"Invalid chat_id: {target_chat_id_str}")
        return

    # Name becomes a directory under users/, so reject anything that isn't a plain identifier.
    if not _NAME_RE.fullmatch(name):
        await update.message.reply_text(
            f"Invalid name '{name}'. Use only letters, digits, underscore, or hyphen."
        )
        return

    async with _allowlist_lock:
        users = load_allowlist()
        existing = next((u for u in users if str(u["chat_id"]) == target_chat_id_str), None)
        if existing:
            await send_with_fallback(
                update.message,
                f"⚠️ chat_id <code>{target_chat_id}</code> is already authorized as "
                f"<b>{existing['name']}</b>.",
            )
            return
        if any(u["name"].lower() == name.lower() for u in users):
            await update.message.reply_text(
                f"⚠️ name '{name}' is already in use. Pick another."
            )
            return

        data_dir = f"users/{name}/data"
        users.append({
            "name": name,
            "chat_id": target_chat_id,
            "owner": False,
            "data_dir": data_dir,
        })
        save_allowlist(users)

    (PROJECT_ROOT / data_dir).mkdir(parents=True, exist_ok=True)

    await send_with_fallback(
        update.message,
        f"✅ Added <b>{name}</b> (<code>{target_chat_id}</code>) to the allowlist.\n"
        f"Data dir: <code>{data_dir}</code>\n\n"
        f"<i>They can now message the bot and run /start to begin onboarding.</i>",
    )
    log.info("Owner added user %s (chat_id=%s)", name, target_chat_id)


async def cmd_revoke(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Remove a chat_id from the allowlist. Usage: /revoke <chat_id>"""
    await record_contact(update, command="revoke")
    if not is_owner(update):
        return

    args = context.args or []
    if not args:
        await send_with_fallback(
            update.message,
            "Usage: <code>/revoke &lt;chat_id&gt;</code>",
        )
        return

    target_chat_id_str = args[0].strip()

    async with _allowlist_lock:
        users = load_allowlist()
        target = next((u for u in users if str(u["chat_id"]) == target_chat_id_str), None)
        if target is None:
            await update.message.reply_text(
                f"chat_id {target_chat_id_str} is not on the allowlist."
            )
            return
        # Safety rail: never strip the last remaining owner — that would lock
        # everyone out of admin commands until allowlist.json is hand-edited.
        if target.get("owner"):
            remaining_owners = sum(
                1 for u in users
                if u.get("owner") and str(u["chat_id"]) != target_chat_id_str
            )
            if remaining_owners == 0:
                await update.message.reply_text(
                    "❌ Refusing to revoke the last remaining owner. "
                    "Promote another user to owner in allowlist.json first."
                )
                return
        new_users = [u for u in users if str(u["chat_id"]) != target_chat_id_str]
        save_allowlist(new_users)

    # If the revoked user has a live Claude session in memory, tear it down so
    # any in-flight or queued messages from them stop being processed.
    session = claude_sessions.pop(target_chat_id_str, None)
    if session is not None:
        try:
            await session.stop()
        except Exception:
            log.exception("Failed to stop revoked user's Claude session cleanly")

    await send_with_fallback(
        update.message,
        f"🚫 Revoked <b>{target['name']}</b> (<code>{target_chat_id_str}</code>). "
        f"Data dir <code>{target.get('data_dir', '?')}</code> was left in place.",
    )
    log.info("Owner revoked user %s (chat_id=%s)", target["name"], target_chat_id_str)


async def cmd_restart(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Restart the bridge. Uses supervisor exit-code-42 if BRIDGE_SUPERVISED=1,
    otherwise falls back to spawning a detached child and exiting."""
    await record_contact(update, command="restart")
    if not is_owner(update):
        return

    supervised = os.getenv("BRIDGE_SUPERVISED") == "1"

    if supervised:
        await update.message.reply_text("🔄 Restarting bridge…")
        log.info("Owner triggered /restart (supervised). Will exit with code %d.", RESTART_EXIT_CODE)

        async def _exit_supervised():
            # Small delay so the reply has time to leave Telegram before the
            # process dies. os._exit is intentional — we want a hard exit
            # that the supervisor can detect via exit code, not a SystemExit
            # that the asyncio event loop might swallow.
            await asyncio.sleep(1)
            os._exit(RESTART_EXIT_CODE)

        asyncio.create_task(_exit_supervised())
        return

    # Unsupervised fallback: spawn a detached child running the bridge again,
    # then exit cleanly. Brief race window where both processes call Telegram's
    # getUpdates and one gets bumped — usually self-resolving but not as clean
    # as the supervisor path. Recommend switching startup to bridge_supervisor.
    await send_with_fallback(
        update.message,
        "🔄 Restarting bridge (no supervisor detected — using self-relaunch).\n\n"
        "<i>For cleaner restarts and crash recovery, switch your startup config to "
        "<code>tools/bridge_supervisor.py</code>.</i>",
    )
    log.info("Owner triggered /restart (unsupervised). Spawning detached child.")

    async def _exit_self_relaunch():
        await asyncio.sleep(1)
        try:
            python_exe = sys.executable
            popen_kwargs: dict = {"close_fds": True}
            if os.name == "nt":
                # Prefer pythonw.exe so the relaunched bridge doesn't open a console window
                pythonw = Path(python_exe).with_name("pythonw.exe")
                if pythonw.exists():
                    python_exe = str(pythonw)
                popen_kwargs["creationflags"] = (
                    subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
                )
            else:
                popen_kwargs["start_new_session"] = True
            subprocess.Popen(
                [python_exe, str(Path(__file__).resolve())],
                cwd=str(PROJECT_ROOT),
                **popen_kwargs,
            )
        except Exception:
            log.exception("Self-relaunch failed; exiting anyway.")
        os._exit(0)

    asyncio.create_task(_exit_self_relaunch())


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

    await record_contact(update)

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


PUBLIC_COMMANDS = [
    BotCommand("start", "Begin your coaching journey"),
    BotCommand("today", "Today's prescribed session"),
    BotCommand("week", "This week's full plan"),
    BotCommand("next", "Next scheduled run"),
    BotCommand("plan", "Open the full plan in Google Sheets"),
]

ADMIN_COMMANDS = [
    BotCommand("contacts", "List pending contacts"),
    BotCommand("allow", "Allow a chat_id: /allow <chat_id> <name>"),
    BotCommand("revoke", "Revoke a chat_id: /revoke <chat_id>"),
    BotCommand("restart", "Restart the bridge"),
]


async def post_init(app: Application):
    """Validate config and register slash commands on startup.

    Public commands go to the default scope (visible to everyone).
    Admin commands are layered on top via per-owner BotCommandScopeChat,
    so each owner sees the full menu in their slash dropdown while
    non-owners only see the public commands.
    """
    if not ALLOWLIST_PATH.exists():
        raise FileNotFoundError(f"Allowlist not found: {ALLOWLIST_PATH}")
    users = load_allowlist()
    log.info("Allowlist loaded: %s", [u["name"] for u in users])

    await app.bot.set_my_commands(PUBLIC_COMMANDS)

    owners = [u for u in users if u.get("owner")]
    for owner in owners:
        try:
            await app.bot.set_my_commands(
                PUBLIC_COMMANDS + ADMIN_COMMANDS,
                scope=BotCommandScopeChat(chat_id=int(owner["chat_id"])),
            )
            log.info("Admin commands scoped to owner %s (%s)", owner["name"], owner["chat_id"])
        except Exception:
            log.exception(
                "Failed to set admin command scope for owner %s", owner.get("name")
            )

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

    # Bridge-level singleton lock. Refuses to start if another bridge already
    # holds the port — prevents two bridges from polling Telegram concurrently.
    # Held by reference for the lifetime of main(); the OS releases it on exit.
    lock_sock = _acquire_bridge_lock()
    if lock_sock is None:
        log.error(
            "Another telegram_bridge is already running on this machine "
            "(port %d in use). Exiting to avoid Telegram getUpdates conflicts. "
            "If you want this bridge instead, kill the existing one first.",
            BRIDGE_SINGLETON_PORT,
        )
        sys.exit(1)
    log.info("Bridge singleton lock acquired on 127.0.0.1:%d", BRIDGE_SINGLETON_PORT)

    app = (
        Application.builder()
        .token(TELEGRAM_BOT_TOKEN)
        .post_init(post_init)
        .post_shutdown(post_shutdown)
        .build()
    )
    # Slash commands (public — appear in Telegram's slash menu)
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("today", cmd_today))
    app.add_handler(CommandHandler("week", cmd_week))
    app.add_handler(CommandHandler("next", cmd_next))
    app.add_handler(CommandHandler("plan", cmd_plan))
    # Owner-only admin commands (intentionally not in set_my_commands —
    # not advertised in the public slash menu, but still work when typed)
    app.add_handler(CommandHandler("contacts", cmd_contacts))
    app.add_handler(CommandHandler("allow", cmd_allow))
    app.add_handler(CommandHandler("revoke", cmd_revoke))
    app.add_handler(CommandHandler("restart", cmd_restart))
    # Fall-through: anything not a command goes to Claude
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    log.info("Starting Telegram bridge (project: %s)", PROJECT_ROOT)
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
