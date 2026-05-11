"""
Supervisor wrapper for the Telegram bridge.

Runs tools/telegram_bridge.py in a loop with these semantics:
  - exit code 0   → clean intentional shutdown, supervisor stops
  - exit code 42  → /restart was requested, respawn immediately
  - any other     → crash, log it and respawn after CRASH_BACKOFF_SECONDS

Sets BRIDGE_SUPERVISED=1 in the child's env so the bridge knows it can
exit-to-restart instead of falling back to its self-relaunch path.

Usage:
  python tools/bridge_supervisor.py
  pythonw tools/bridge_supervisor.py     # Windows: no console window

This is the recommended way to run the bridge in production. Without the
supervisor, /restart still works (via detached self-relaunch) but with a
brief race where both processes briefly poll Telegram.
"""

import logging
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
BRIDGE_SCRIPT = PROJECT_ROOT / "tools" / "telegram_bridge.py"
RESTART_EXIT_CODE = 42
CRASH_BACKOFF_SECONDS = 5

# Singleton lock: bind a localhost TCP port for the supervisor's lifetime.
# If the bind fails, another supervisor is already running and we exit.
# Chosen via "Telegram coach" letters → arbitrary high port; collisions with
# real services are vanishingly unlikely. The OS releases the port the moment
# this process dies — no stale lockfile or PID-tracking required.
SINGLETON_PORT = 48733

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
log = logging.getLogger("bridge_supervisor")


def acquire_singleton_lock() -> socket.socket | None:
    """Bind 127.0.0.1:SINGLETON_PORT for the supervisor's lifetime.
    Returns the socket on success, None if another supervisor already holds it.
    Caller must keep the socket alive (don't close it) — closing releases the lock."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    # Deliberately NOT setting SO_REUSEADDR — we want bind to fail if another
    # supervisor is already bound, which is the entire point of this lock.
    try:
        sock.bind(("127.0.0.1", SINGLETON_PORT))
        sock.listen(1)
        return sock
    except OSError:
        sock.close()
        return None


def main() -> int:
    if not BRIDGE_SCRIPT.exists():
        log.error("Bridge script not found: %s", BRIDGE_SCRIPT)
        return 1

    lock_sock = acquire_singleton_lock()
    if lock_sock is None:
        log.error(
            "Another bridge_supervisor is already running on this machine "
            "(port %d in use). Exiting to avoid Telegram getUpdates conflicts.",
            SINGLETON_PORT,
        )
        return 1
    log.info("Singleton lock acquired on 127.0.0.1:%d", SINGLETON_PORT)

    log.info("Supervisor starting. Bridge: %s", BRIDGE_SCRIPT)
    log.info("Using interpreter: %s", sys.executable)

    while True:
        env = os.environ.copy()
        env["BRIDGE_SUPERVISED"] = "1"

        try:
            result = subprocess.run(
                [sys.executable, str(BRIDGE_SCRIPT)],
                cwd=str(PROJECT_ROOT),
                env=env,
            )
        except KeyboardInterrupt:
            log.info("Supervisor received KeyboardInterrupt. Exiting.")
            return 0
        except Exception:
            log.exception("Supervisor failed to launch bridge. Backing off.")
            try:
                time.sleep(CRASH_BACKOFF_SECONDS)
                continue
            except KeyboardInterrupt:
                return 0

        code = result.returncode
        if code == 0:
            log.info("Bridge exited cleanly (code 0). Supervisor stopping.")
            return 0
        if code == RESTART_EXIT_CODE:
            log.info("Bridge requested restart (code %d). Respawning immediately.", code)
            continue
        log.warning(
            "Bridge crashed with exit code %d. Respawning in %ds.",
            code, CRASH_BACKOFF_SECONDS,
        )
        try:
            time.sleep(CRASH_BACKOFF_SECONDS)
        except KeyboardInterrupt:
            log.info("Supervisor interrupted during backoff. Exiting.")
            return 0


if __name__ == "__main__":
    sys.exit(main())
