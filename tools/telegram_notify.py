"""
Send a one-off Telegram message.
Used by polling_check.py (and ad-hoc by other scripts) to push notifications.

Usage:
  python tools/telegram_notify.py "Plan updated - new sub-1:50 pace targets"
  echo "Race week reminder" | python tools/telegram_notify.py
"""

import os
import sys
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import runcoach.paths  # noqa: F401, E402

TELEGRAM_API = "https://api.telegram.org/bot{token}/sendMessage"
MAX_LEN = 4000


def send(message: str, parse_mode: str = "Markdown"):
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        raise RuntimeError("TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID must be set in .env")

    # Telegram message length limit is 4096 — split if needed
    chunks = [message[i:i + MAX_LEN] for i in range(0, len(message), MAX_LEN)] or [""]
    for chunk in chunks:
        resp = requests.post(
            TELEGRAM_API.format(token=token),
            json={"chat_id": chat_id, "text": chunk, "parse_mode": parse_mode},
            timeout=15,
        )
        resp.raise_for_status()
    return len(chunks)


def main():
    if len(sys.argv) > 1:
        message = " ".join(sys.argv[1:])
    else:
        message = sys.stdin.read().strip()

    if not message:
        print("ERROR: no message provided (pass as args or stdin)", file=sys.stderr)
        sys.exit(1)

    n = send(message)
    print(f"Sent {n} message(s) to Telegram.")


if __name__ == "__main__":
    main()
