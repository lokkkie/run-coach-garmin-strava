"""Wire certifi's CA bundle into the project so HTTPS calls verify correctly.

The standalone Python 3.14 build in AppData has no CA roots, so every outbound
HTTPS request fails with CERTIFICATE_VERIFY_FAILED. This script:

  1. Confirms certifi is installed and locates its cacert.pem.
  2. Adds SSL_CERT_FILE and REQUESTS_CA_BUNDLE to .env (idempotent).
  3. Verifies the fix by hitting api.telegram.org and connect.garmin.com.

Usage:
    python tools/ssl_setup.py
"""

import os
import ssl
import sys
import urllib.request
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
ENV_FILE = PROJECT_ROOT / ".env"

ENV_KEYS = ("SSL_CERT_FILE", "REQUESTS_CA_BUNDLE")
TEST_URLS = ("https://api.telegram.org", "https://connect.garmin.com")


def locate_cacert() -> Path:
    try:
        import certifi
    except ImportError:
        print("ERROR: certifi not installed. Run: python -m pip install --upgrade certifi", file=sys.stderr)
        sys.exit(1)
    path = Path(certifi.where())
    if not path.exists():
        print(f"ERROR: certifi reports {path} but file is missing.", file=sys.stderr)
        sys.exit(1)
    return path


def upsert_env(cacert: Path) -> None:
    lines = ENV_FILE.read_text(encoding="utf-8").splitlines() if ENV_FILE.exists() else []
    existing = {line.split("=", 1)[0]: i for i, line in enumerate(lines) if "=" in line and not line.lstrip().startswith("#")}
    target = str(cacert)
    changed = False
    for key in ENV_KEYS:
        new_line = f"{key}={target}"
        if key in existing:
            if lines[existing[key]] != new_line:
                lines[existing[key]] = new_line
                changed = True
        else:
            lines.append(new_line)
            changed = True
    if changed:
        ENV_FILE.write_text("\n".join(lines) + "\n", encoding="utf-8")
        print(f"Updated {ENV_FILE} with {', '.join(ENV_KEYS)}")
    else:
        print(f"{ENV_FILE} already has correct {', '.join(ENV_KEYS)} entries")


def verify(cacert: Path) -> None:
    os.environ["SSL_CERT_FILE"] = str(cacert)
    os.environ["REQUESTS_CA_BUNDLE"] = str(cacert)
    ctx = ssl.create_default_context(cafile=str(cacert))
    for url in TEST_URLS:
        try:
            with urllib.request.urlopen(url, context=ctx, timeout=10) as resp:
                print(f"OK  {url} -> HTTP {resp.status}")
        except Exception as e:
            print(f"FAIL {url} -> {e}", file=sys.stderr)
            sys.exit(1)


def main() -> None:
    cacert = locate_cacert()
    print(f"certifi cacert.pem: {cacert}")
    upsert_env(cacert)
    print("Verifying HTTPS reachability...")
    verify(cacert)
    print("\nDone. Restart the Telegram bridge so it picks up the new env vars.")


if __name__ == "__main__":
    main()
