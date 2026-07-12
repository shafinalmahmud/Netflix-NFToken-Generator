"""
ChatGPT Session Token Generator
================================
Generates a ChatGPT session/access token from a valid ChatGPT login cookie.

Usage:
  1. Run the script once to create chatgpt_input.txt
  2. Paste your ChatGPT cookie into chatgpt_input.txt
  3. Run again to get your session token

Supports raw cookie strings, Netscape format, and JSON cookie exports.
"""

import json
import os
import re
import sys
import urllib.parse
from datetime import datetime

import requests
from urllib3.exceptions import InsecureRequestWarning

# Windows cp1252 terminal cannot print JWTs with non-ASCII chars.
# Reconfigure stdout to UTF-8 so tokens render correctly.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# ──────────────────────────────────────────────────────────────────────
# Constants
# ──────────────────────────────────────────────────────────────────────

INPUT_FILE = "chatgpt_input.txt"

WATERMARK = (
    "https://github.com/harshitkamboj | "
    "website: harshitkamboj.in | "
    "discord: https://discord.gg/DYJFE9nu5X"
)

# Primary endpoint - returns session info when a valid cookie is supplied.
# Also works on chat.openai.com and openai.com if the cookie domain matches.
API_URL = "https://chatgpt.com/api/auth/session"

# Alternative domains to try if the primary fails (same path).
FALLBACK_DOMAINS = [
    "https://chat.openai.com/api/auth/session",
]

# Cookies recognised by the extractor.
# __Secure-next-auth.session-token is the critical one - it is the
# httpOnly, Secure session token issued by NextAuth.js on chatgpt.com.
# ChatGPT now uses chunked session tokens (suffixes .0, .1) for larger JWTs.
_SESSION_TOKEN_KEYS = [
    "__Secure-next-auth.session-token",       # without suffix (older format)
    "__Secure-next-auth.session-token.0",     # chunked format part 0 (newer)
    "__Secure-next-auth.session-token.1",     # chunked format part 1 (newer)
    "__Secure-next-auth.session-token.2",     # chunked format part 2 (reserved)
    "__Secure-next-auth.session-token.3",     # chunked format part 3 (reserved)
]

COOKIE_KEYS = tuple(_SESSION_TOKEN_KEYS) + (
    "__Secure-next-auth.callback-url",   # callback URL stored by NextAuth
    "__Host-next-auth.csrf-token",       # CSRF protection token
    "cf_clearance",                      # Cloudflare clearance (if behind CF)
)

# At least one of these must be present for the request to succeed.
REQUIRED_COOKIE = "__Secure-next-auth.session-token"

# Browser-like headers to mimic a real user agent.
BASE_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://chatgpt.com/",
    "Origin": "https://chatgpt.com",
    "Sec-Fetch-Site": "same-origin",
    "Sec-Fetch-Mode": "cors",
    "Sec-Fetch-Dest": "empty",
    "DNT": "1",
}

requests.packages.urllib3.disable_warnings(category=InsecureRequestWarning)


# ──────────────────────────────────────────────────────────────────────
# Input helpers  (mirrors nf-token-generator.py)
# ──────────────────────────────────────────────────────────────────────


def ensure_input_file():
    """Check that the input file exists and is non-empty.

    Returns the raw text content, or None if the file is missing/empty.
    """
    if not os.path.exists(INPUT_FILE):
        with open(INPUT_FILE, "w", encoding="utf-8") as fh:
            fh.write(
                "__Secure-next-auth.session-token=eyJ...; "
                "__Host-next-auth.csrf-token=...\n"
            )
        print(f"Created {INPUT_FILE}")
        print("Add your ChatGPT cookie and run again")
        return None

    with open(INPUT_FILE, "r", encoding="utf-8") as fh:
        content = fh.read().strip()

    if not content:
        print(f"{INPUT_FILE} is empty")
        print("Add your ChatGPT cookie and run again")
        return None

    return content


def parse_netscape_cookie_line(line):
    """Parse a single Netscape-format cookie line (tab-separated).

    Format: domain  flag  path  secure  expiry  name  value
    Returns {name: value} or {} on failure.
    """
    parts = line.strip().split("\t")
    if len(parts) >= 7:
        return {parts[5]: parts[6]}
    return {}


def _decode_cookie_value(value):
    """URL-decode a cookie value if it contains percent-encoding."""
    if isinstance(value, str) and "%" in value:
        try:
            return urllib.parse.unquote(value)
        except Exception:
            return value
    return value


def extract_cookie_dict(text):
    """Parse cookie text in any supported format into a name → value dict.

    Supports:
      * Raw ``key=value; key=value; ...`` strings
      * Netscape cookie-file format (tab-separated)
      * JSON array of cookie objects (e.g. from Cookie-Editor)
      * JSON dict with key-value pairs
      * JSON ``{cookies: [...]}`` wrapper
    """
    cookie_dict = {}

    # ── Netscape format ──────────────────────────────────────────
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        cookie_dict.update(parse_netscape_cookie_line(line))

    # ── JSON formats ─────────────────────────────────────────────
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        data = None

    if isinstance(data, list):
        # Array of {name, value, ...} objects (Cookie-Editor style)
        for cookie in data:
            name = cookie.get("name")
            value = cookie.get("value")
            if name in COOKIE_KEYS and isinstance(value, str):
                cookie_dict[name] = _decode_cookie_value(value)

    elif isinstance(data, dict):
        # Flat dict: {key: value, ...}
        if any(key in data for key in COOKIE_KEYS):
            for key in COOKIE_KEYS:
                value = data.get(key)
                if isinstance(value, str):
                    cookie_dict[key] = _decode_cookie_value(value)
        # {cookies: [...]} wrapper
        elif isinstance(data.get("cookies"), list):
            for cookie in data["cookies"]:
                name = cookie.get("name")
                value = cookie.get("value")
                if name in COOKIE_KEYS and isinstance(value, str):
                    cookie_dict[name] = _decode_cookie_value(value)

    # ── Fallback: raw regex extraction ───────────────────────────
    # Catches any recognised key=value that the JSON/Netscape
    # parsers might have missed (e.g. inline headers).
    for key in COOKIE_KEYS:
        if key in cookie_dict:
            continue
        match = re.search(rf"(?<!\w){re.escape(key)}=([^;,\s]+)", text)
        if match:
            cookie_dict[key] = _decode_cookie_value(match.group(1))

    return cookie_dict


# ──────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────


def _find_session_token_key(cookie_dict):
    """Find the actual session-token key in the cookie dict.

    ChatGPT now uses chunked session-token cookies (suffixes ``.0``, ``.1``)
    for larger JWTs.  Returns the exact key found (e.g.
    ``__Secure-next-auth.session-token.0``) or None if none match.
    """
    for key in _SESSION_TOKEN_KEYS:
        if key in cookie_dict:
            return key
    return None


def build_session_link(access_token):
    """Construct a plausible ChatGPT session link (purely informational)."""
    if access_token:
        # Show a truncated preview so the user can verify it looks right
        preview = access_token[:40] + "..." if len(access_token) > 40 else access_token
        return f"Access token: {preview}"
    return "No access token available"


# ──────────────────────────────────────────────────────────────────────
# API interaction
# ──────────────────────────────────────────────────────────────────────


def fetch_session(cookie_dict):
    """Call the ChatGPT session API and return (user_data, expires, access_token).

    Attempts the primary domain (chatgpt.com) first, then falls back to
    alternative domains if the cookie domain doesn't match.

    Returns
    -------
    tuple
        (user_info_dict, expires_timestamp_str, access_token_str_or_None)

    Raises
    ------
    ValueError
        If the required cookie is missing or the API returns an error.
    requests.RequestException
        If all domain attempts fail.
    """
    session_cookie_key = _find_session_token_key(cookie_dict)
    if not session_cookie_key:
        raise ValueError(
            f"Missing required cookie: {REQUIRED_COOKIE} "
            "(or any suffixed variant)"
        )

    # Build a list of URLs to try
    urls_to_try = [API_URL] + FALLBACK_DOMAINS

    last_error = None

    for url in urls_to_try:
        headers = dict(BASE_HEADERS)

        # Build the Cookie header from all recognised keys
        cookie_parts = []
        for key, val in cookie_dict.items():
            if key in COOKIE_KEYS:
                cookie_parts.append(f"{key}={val}")
        if cookie_parts:
            headers["Cookie"] = "; ".join(cookie_parts)

        # Update referer/origin to match the target domain
        domain = urllib.parse.urlparse(url).netloc
        base_origin = f"https://{domain}"
        headers["Referer"] = base_origin + "/"
        headers["Origin"] = base_origin

        try:
            response = requests.get(
                url,
                headers=headers,
                timeout=30,
                verify=False,  # same as Netflix module
            )

            # 200 = success; anything else → try next domain
            if response.status_code != 200:
                last_error = (
                    f"{url} returned HTTP {response.status_code}"
                )
                continue

            # Parse JSON response
            data = response.json()

            # Typical session response shape:
            # {
            #   "user": { "id": "...", "name": "...", "email": "...", "image": "..." },
            #   "expires": "2025-01-01T00:00:00.000Z",
            #   "accessToken": "..."  (present for cookie-based auth)
            # }
            user_info = data.get("user") or {}
            expires = data.get("expires")
            access_token = data.get("accessToken")

            # If the response has an 'error' field, treat it as a failure
            if data.get("error"):
                last_error = f"{url} returned an error: {data['error']}"
                continue

            # At minimum we expect either a user object or session expiry
            if not user_info and not expires and not access_token:
                last_error = (
                    f"{url} returned an unexpected response "
                    "(missing user, expires, and accessToken)"
                )
                continue

            # Success
            return user_info, expires, access_token

        except requests.RequestException as exc:
            last_error = f"{url} request failed: {exc}"
            continue

    # All domains exhausted
    if isinstance(last_error, str):
        raise requests.RequestException(last_error)
    raise requests.RequestException(
        "All ChatGPT session endpoints were unreachable"
    )


# ──────────────────────────────────────────────────────────────────────
# Output formatting
# ──────────────────────────────────────────────────────────────────────


def format_expiry(expires):
    """Convert an ISO-8601 expiry string to a human-readable date."""
    if not isinstance(expires, str) or not expires:
        return "Unknown / Session (no fixed expiry)"
    try:
        dt = datetime.fromisoformat(expires.replace("Z", "+00:00"))
        return dt.strftime("%Y-%m-%d %H:%M:%S UTC")
    except (ValueError, AttributeError):
        return str(expires)


def format_user_info(user_info):
    """Pretty-print the user object returned by the session endpoint."""
    if not user_info:
        return "  (no user info returned)"

    lines = []
    for field in ("name", "email", "id", "image", "picture"):
        val = user_info.get(field)
        if val:
            lines.append(f"  {field}: {val}")
    return "\n".join(lines) if lines else "  (no user info returned)"


# ──────────────────────────────────────────────────────────────────────
# Entry point
# ──────────────────────────────────────────────────────────────────────


def main():
    print(WATERMARK)
    print()

    # 1. Read cookie from input file
    raw_cookie = ensure_input_file()
    if raw_cookie is None:
        return

    # 2. Parse cookie into structured dict
    cookie_dict = extract_cookie_dict(raw_cookie)
    if not cookie_dict:
        print("No valid ChatGPT cookie found in", INPUT_FILE)
        print()
        return

    session_token_key = _find_session_token_key(cookie_dict)
    if not session_token_key:
        print(f"Missing required cookie: {REQUIRED_COOKIE}")
        print(
            "Make sure your cookie export contains the "
            "__Secure-next-auth.session-token field."
        )
        print()
        return

    print(f"[OK] Found session token: {session_token_key}")
    extra = set(cookie_dict) - set(_SESSION_TOKEN_KEYS)
    if extra:
        print(f"      Additional cookies: {', '.join(sorted(extra))}")
    print()

    # 3. Fetch session from ChatGPT API
    try:
        user_info, expires, access_token = fetch_session(cookie_dict)

        print("─" * 50)
        print("ChatGPT Session")
        print("─" * 50)

        print()
        print("User Info:")
        print(format_user_info(user_info))

        print()
        print("Expires :", format_expiry(expires))

        if access_token:
            print()
            print("Access Token:")
            print(f"  {access_token}")
            print()
            print("Token Preview :", build_session_link(access_token))
        else:
            print()
            print("Note: No accessToken was returned. The session cookie")
            print("      is valid, but the API did not issue a bearer token.")
            print("      This can happen with certain account types.")

        print()
        print("─" * 50)
        print("[OK] Session retrieval complete")

    except requests.RequestException as exc:
        print("Request failed:", str(exc))
        print()
        print("Possible causes:")
        print("  * The cookie is expired or invalid")
        print(f"  * The cookie domain doesn't match {API_URL}")
        print("  * Cloudflare/rate-limiting is blocking the request")
        print("  * Network connectivity issue")
        print()
        print("Tip: Try exporting a fresh cookie from your browser")
        print("     while logged in at https://chatgpt.com")
    except ValueError as exc:
        print("Failed:", str(exc))
    finally:
        print()
        print(WATERMARK)


if __name__ == "__main__":
    main()
