"""
Strava OAuth setup CLI. The read-side helpers (get_access_token, api_get,
latest_run, fetch_*) live in `runcoach.strava`; this script handles only the
one-time consent flow that writes the per-user token file.

Modes:
  --setup        Run the user-consent OAuth flow (opens a local server,
                 prints an authorize URL, captures the redirect, exchanges
                 code → tokens, writes {data_dir}/strava_token.json).
  --manual       Print the auth URL for a remote/mobile user — they open
                 it, authorize, paste the redirect URL back via --redirect-url.
  --redirect-url <url>
                 Complete the manual flow with the pasted redirect URL.
  (default)      Print the current valid access token (handy for ad-hoc curl).

Token file format ({data_dir}/strava_token.json):
  {
    "access_token":  "...",
    "refresh_token": "...",
    "expires_at":    1234567890,   // Unix epoch seconds
    "athlete":       { ... }
  }
"""

import argparse
import http.server
import os
import socketserver
import sys
import threading
import time
import urllib.parse
import webbrowser
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from runcoach.strava import (  # noqa: E402
    _token_file,
    complete_oauth,
    get_access_token,
)

AUTHORIZE_URL = "https://www.strava.com/oauth/authorize"
REDIRECT_PORT = 53682
REDIRECT_URI = f"http://localhost:{REDIRECT_PORT}"
SCOPE = "read,activity:read_all"


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

    print("Opening browser for Strava authorization...")
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

    print("Got authorization code, exchanging for tokens...")
    tokens = complete_oauth(_received["code"], user=user)
    athlete = tokens.get("athlete", {})
    name = f"{athlete.get('firstname', '')} {athlete.get('lastname', '')}".strip()
    print(f"Saved tokens to {token_file}")
    print(f"Authorized as: {name or '(unknown)'}")
    print(f"Access token expires at: {tokens.get('expires_at')}")
    user_flag = f" --user {user}" if user else ""
    print(f"\nNext: run `python tools/set_source.py strava{user_flag}` to make Strava the active source.")


def _manual_exchange(user: str | None = None):
    """Print the auth URL for a user to open on their device. They then paste
    the full redirect URL back via --redirect-url to finish the exchange."""
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
    """Exchange an authorization code from a pasted redirect URL for tokens."""
    parsed = urllib.parse.urlparse(redirect_url)
    params = urllib.parse.parse_qs(parsed.query)
    if "error" in params:
        print(f"ERROR: Strava returned error: {params['error'][0]}", file=sys.stderr)
        sys.exit(1)
    if "code" not in params:
        print("ERROR: No authorization code found in the URL.", file=sys.stderr)
        sys.exit(1)

    print("Exchanging authorization code for tokens...")
    tokens = complete_oauth(params["code"][0], user=user)

    athlete = tokens.get("athlete", {})
    name = f"{athlete.get('firstname', '')} {athlete.get('lastname', '')}".strip()
    print(f"Saved tokens to {_token_file(user)}")
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
