"""
Strava OAuth helper.

Two modes:
  --setup        Run the user-consent OAuth flow (opens a local server,
                 prints an authorize URL, captures the redirect, exchanges
                 code → tokens, writes .tmp/strava_token.json).

  Default       Library use: import and call get_access_token() to get a
                valid bearer token (auto-refreshes if expired).

Tokens file format (.tmp/strava_token.json):
  {
    "access_token":  "...",
    "refresh_token": "...",
    "expires_at":    1234567890,   // Unix epoch seconds
    "athlete":       { ... }
  }
"""

import argparse
import http.server
import json
import os
import socketserver
import sys
import threading
import time
import urllib.parse
import webbrowser
from pathlib import Path

import requests
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(PROJECT_ROOT / ".env")

TOKEN_URL = "https://www.strava.com/api/v3/oauth/token"


def _token_file(user: str | None = None) -> Path:
    if user:
        return PROJECT_ROOT / "users" / user / "data" / "strava_token.json"
    return PROJECT_ROOT / ".tmp" / "strava_token.json"
AUTHORIZE_URL = "https://www.strava.com/oauth/authorize"
REDIRECT_PORT = 53682
REDIRECT_URI = f"http://localhost:{REDIRECT_PORT}"
SCOPE = "read,activity:read_all"


def _load_tokens(token_file: Path) -> dict | None:
    if token_file.exists():
        with open(token_file, encoding="utf-8") as f:
            return json.load(f)
    return None


def _save_tokens(tokens: dict, token_file: Path):
    token_file.parent.mkdir(parents=True, exist_ok=True)
    with open(token_file, "w", encoding="utf-8") as f:
        json.dump(tokens, f, indent=2)


def _refresh(client_id: str, client_secret: str, refresh_token: str) -> dict:
    resp = requests.post(
        TOKEN_URL,
        data={
            "client_id": client_id,
            "client_secret": client_secret,
            "refresh_token": refresh_token,
            "grant_type": "refresh_token",
        },
        timeout=15,
    )
    resp.raise_for_status()
    return resp.json()


def get_access_token(user: str | None = None) -> str:
    """Public API: return a currently-valid access token, refreshing if needed."""
    client_id = os.getenv("STRAVA_CLIENT_ID")
    client_secret = os.getenv("STRAVA_CLIENT_SECRET")
    if not client_id or not client_secret:
        raise RuntimeError(
            "STRAVA_CLIENT_ID / STRAVA_CLIENT_SECRET missing in .env. "
            "Create an app at https://www.strava.com/settings/api"
        )

    token_file = _token_file(user)
    tokens = _load_tokens(token_file)
    if not tokens:
        raise RuntimeError(
            f"No Strava tokens at {token_file}. Run: python tools/strava_auth.py --setup"
            + (f" --user {user}" if user else "")
        )

    # Refresh if access token expires within 60 seconds
    if int(tokens.get("expires_at", 0)) - 60 < int(time.time()):
        new_tokens = _refresh(client_id, client_secret, tokens["refresh_token"])
        # Strava sometimes rotates the refresh_token — preserve athlete info
        new_tokens["athlete"] = tokens.get("athlete", new_tokens.get("athlete"))
        _save_tokens(new_tokens, token_file)
        tokens = new_tokens

    return tokens["access_token"]


# ──────────────────────────────────────────────────────────────────────
# --setup flow: run a tiny local HTTP server, capture the redirect
# ──────────────────────────────────────────────────────────────────────
_received: dict = {}


class _RedirectHandler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        params = urllib.parse.parse_qs(parsed.query)
        if "error" in params:
            _received["error"] = params["error"][0]
            self.send_response(400)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(
                f"<h1>Authorization failed: {params['error'][0]}</h1>".encode()
            )
        elif "code" in params:
            _received["code"] = params["code"][0]
            _received["scope"] = params.get("scope", [""])[0]
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(
                b"<html><body style='font-family:sans-serif;text-align:center;"
                b"padding:60px'><h1>&#10003; Strava authorized</h1>"
                b"<p>You can close this tab and return to the terminal.</p>"
                b"</body></html>"
            )
        else:
            self.send_response(400)
            self.end_headers()
            self.wfile.write(b"Missing code parameter")

    def log_message(self, format, *args):
        return  # silence default access log


def _setup(user: str | None = None):
    client_id = os.getenv("STRAVA_CLIENT_ID")
    client_secret = os.getenv("STRAVA_CLIENT_SECRET")
    if not client_id or not client_secret:
        print(
            "ERROR: STRAVA_CLIENT_ID / STRAVA_CLIENT_SECRET missing in .env.\n"
            "Create an app at https://www.strava.com/settings/api first.",
            file=sys.stderr,
        )
        sys.exit(1)
    token_file = _token_file(user)

    auth_url = (
        f"{AUTHORIZE_URL}?client_id={client_id}"
        f"&response_type=code&redirect_uri={REDIRECT_URI}"
        f"&approval_prompt=auto&scope={SCOPE}"
    )

    httpd = socketserver.TCPServer(("localhost", REDIRECT_PORT), _RedirectHandler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()

    print(f"Opening browser for Strava authorization...")
    print(f"If the browser does not open, paste this URL manually:\n  {auth_url}\n")
    webbrowser.open(auth_url)

    timeout_at = time.time() + 300  # 5 minutes
    while "code" not in _received and "error" not in _received:
        if time.time() > timeout_at:
            httpd.shutdown()
            print("ERROR: Timed out waiting for browser authorization.", file=sys.stderr)
            sys.exit(1)
        time.sleep(0.3)

    httpd.shutdown()

    if "error" in _received:
        print(f"ERROR: Strava returned error: {_received['error']}", file=sys.stderr)
        sys.exit(1)

    code = _received["code"]
    print("Got authorization code, exchanging for tokens...")
    resp = requests.post(
        TOKEN_URL,
        data={
            "client_id": client_id,
            "client_secret": client_secret,
            "code": code,
            "grant_type": "authorization_code",
        },
        timeout=15,
    )
    resp.raise_for_status()
    tokens = resp.json()

    _save_tokens(tokens, token_file)
    athlete = tokens.get("athlete", {})
    name = f"{athlete.get('firstname', '')} {athlete.get('lastname', '')}".strip()
    print(f"Saved tokens to {token_file}")
    print(f"Authorized as: {name or '(unknown)'}")
    print(f"Access token expires at: {tokens.get('expires_at')}")
    user_flag = f" --user {user}" if user else ""
    print(f"\nNext: run `python tools/set_source.py strava{user_flag}` to make Strava the active source.")


def _manual_exchange(user: str | None = None):
    """
    Print the auth URL for the user to open on their device.
    Then accept the full redirect URL (pasted back) and extract the code.
    Useful when the redirect cannot reach localhost (e.g. remote/mobile users).
    """
    client_id = os.getenv("STRAVA_CLIENT_ID")
    client_secret = os.getenv("STRAVA_CLIENT_SECRET")
    if not client_id or not client_secret:
        print(
            "ERROR: STRAVA_CLIENT_ID / STRAVA_CLIENT_SECRET missing in .env.",
            file=sys.stderr,
        )
        sys.exit(1)

    auth_url = (
        f"{AUTHORIZE_URL}?client_id={client_id}"
        f"&response_type=code&redirect_uri={REDIRECT_URI}"
        f"&approval_prompt=force&scope={SCOPE}"
    )

    print(f"\nOpen this URL in a browser and log in with the Strava account to connect:\n\n  {auth_url}\n")
    print("After authorizing, the browser will show a connection error (expected).")
    print("Copy the full URL from the address bar, then re-run with --redirect-url <url>.\n")
    return auth_url


def _exchange_code(redirect_url: str, user: str | None = None):
    """Exchange an authorization code from a redirect URL for tokens."""
    client_id = os.getenv("STRAVA_CLIENT_ID")
    client_secret = os.getenv("STRAVA_CLIENT_SECRET")

    parsed = urllib.parse.urlparse(redirect_url)
    params = urllib.parse.parse_qs(parsed.query)
    if "error" in params:
        print(f"ERROR: Strava returned error: {params['error'][0]}", file=sys.stderr)
        sys.exit(1)
    if "code" not in params:
        print("ERROR: No authorization code found in the URL.", file=sys.stderr)
        sys.exit(1)

    code = params["code"][0]
    print("Exchanging authorization code for tokens...")
    resp = requests.post(
        TOKEN_URL,
        data={
            "client_id": client_id,
            "client_secret": client_secret,
            "code": code,
            "grant_type": "authorization_code",
        },
        timeout=15,
    )
    resp.raise_for_status()
    tokens = resp.json()

    token_file = _token_file(user)
    _save_tokens(tokens, token_file)
    athlete = tokens.get("athlete", {})
    name = f"{athlete.get('firstname', '')} {athlete.get('lastname', '')}".strip()
    print(f"Saved tokens to {token_file}")
    print(f"Authorized as: {name or '(unknown)'}")
    user_flag = f" --user {user}" if user else ""
    print(f"\nNext: run `python tools/set_source.py strava{user_flag}`")


def main():
    parser = argparse.ArgumentParser(description="Strava OAuth helper")
    parser.add_argument("--setup", action="store_true", help="Run the OAuth setup flow (browser-based, localhost redirect)")
    parser.add_argument("--manual", action="store_true", help="Print auth URL for remote/mobile users to open in their browser")
    parser.add_argument("--redirect-url", default=None, help="Full redirect URL from browser after Strava authorization (completes the manual flow)")
    parser.add_argument("--user", default=None, help="User name for per-user token storage (e.g. Nicolas)")
    args = parser.parse_args()

    if args.setup:
        _setup(user=args.user)
    elif args.manual:
        _manual_exchange(user=args.user)
    elif args.redirect_url:
        _exchange_code(args.redirect_url, user=args.user)
    else:
        # Default: print the current valid access token (useful for ad-hoc curl/testing)
        try:
            token = get_access_token(user=args.user)
            print(token)
        except RuntimeError as e:
            print(f"ERROR: {e}", file=sys.stderr)
            sys.exit(1)


if __name__ == "__main__":
    main()
