"""Project paths, env loading, and allowlist helpers.

One place to resolve PROJECT_ROOT, the per-user data directory, and the
allowlist file — replaces the per-tool `_data_dir` definitions that used to
drift between scripts.
"""

import json
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT: Path = Path(__file__).resolve().parent.parent

ALLOWLIST_PATH: Path = PROJECT_ROOT / "users" / "allowlist.json"

# Load .env once on import. python-dotenv is a no-op if already loaded, so it's
# safe for tools to also call load_dotenv() defensively.
load_dotenv(PROJECT_ROOT / ".env")


def data_dir(user_name: str | None) -> Path:
    """Return the per-user data directory by name (convention: users/<name>/data/).

    Falls back to `.tmp/` when no user_name is given — that path is now
    reserved for transient process scratch (bridge logs, in-flight FIT
    files) rather than user state. New code should always supply user_name.
    """
    if user_name:
        return PROJECT_ROOT / "users" / user_name / "data"
    return PROJECT_ROOT / ".tmp"


def data_dir_for(user: dict) -> Path:
    """Return the data directory specified by an allowlist user entry.

    Use this instead of `data_dir(name)` when iterating over `load_allowlist()`
    so the allowlist's `data_dir` field stays authoritative even for users
    whose path doesn't match the default convention.
    """
    return PROJECT_ROOT / user["data_dir"]


def load_allowlist() -> list[dict]:
    """Parse users/allowlist.json. Raises if the file is missing or malformed
    — a corrupt allowlist is a hard error, not a soft fallback."""
    with open(ALLOWLIST_PATH, encoding="utf-8") as f:
        return json.load(f)["users"]
