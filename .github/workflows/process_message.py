"""
GitHub Actions Telegram Bot — Message Processor
===============================================
Runs inside the Actions runner each time a Telegram message arrives.
Reads env vars set by the workflow and replies via the Telegram API.
"""

import importlib.util
import json
import os
import re
import sys
import urllib.parse
from pathlib import Path

import requests  # needed for GitHub API calls in state management

# ---------------------------------------------------------------------------
# Config from environment
# ---------------------------------------------------------------------------

CHAT_ID = os.environ.get("CHAT_ID", "")
MSG_TEXT = os.environ.get("MSG_TEXT", "").strip()
TG_BOT_TOKEN = os.environ.get("TG_BOT_TOKEN", "")

BASE_DIR = Path(__file__).resolve().parent.parent.parent  # repo root

# ── Commands ────────────────────────────────────────────────────────
CMD_START = "/start"
CMD_NETFLIX = "/netflix"
CMD_CHATGPT = "/chatgpt"
CMD_CANCEL = "/cancel"
CMD_HELP = "/help"

# ── Netflix keys ────────────────────────────────────────────────────
NF_COOKIE_KEYS = ("NetflixId", "SecureNetflixId", "nfvdid", "OptanonConsent")
NF_REQUIRED = "NetflixId"

# ── ChatGPT keys ────────────────────────────────────────────────────
CG_SESSION_TOKEN_KEYS = [
    "__Secure-next-auth.session-token",
    "__Secure-next-auth.session-token.0",
    "__Secure-next-auth.session-token.1",
    "__Secure-next-auth.session-token.2",
    "__Secure-next-auth.session-token.3",
]
CG_COOKIE_KEYS = tuple(CG_SESSION_TOKEN_KEYS) + (
    "__Secure-next-auth.callback-url",
    "__Host-next-auth.csrf-token",
    "cf_clearance",
)


# ---------------------------------------------------------------------------
# Load the existing modules
# ---------------------------------------------------------------------------

def _load_module(filename, module_name):
    filepath = BASE_DIR / filename
    if not filepath.exists():
        raise ImportError(f"{filename} not found")
    spec = importlib.util.spec_from_file_location(module_name, filepath)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = mod
    spec.loader.exec_module(mod)
    return mod


try:
    nf_mod = _load_module("nf-token-generator.py", "nf_tok_gh")
    cg_mod = _load_module("chatgpt-token-generator.py", "cg_tok_gh")
except ImportError as e:
    print(f"Failed to load modules: {e}")
    nf_mod = None
    cg_mod = None


# ---------------------------------------------------------------------------
# State management (via GitHub Variables API)
# ---------------------------------------------------------------------------

GH_TOKEN = os.environ.get("GH_TOKEN", "")
GH_REPO = "shafinalmahmud/Netflix-NFToken-Generator"


def _state_key():
    return f"tg_state_{CHAT_ID}"


def _gh_api(method, path, data=None):
    """Call the GitHub API with the repo-scoped PAT."""
    url = f"https://api.github.com{path}"
    headers = {
        "Authorization": f"Bearer {GH_TOKEN}",
        "Accept": "application/vnd.github+json",
        "User-Agent": "tg-bot-worker",
    }
    r = requests.request(method, url, headers=headers, json=data, timeout=10)
    if r.status_code >= 400 and r.status_code != 404:
        print(f"GitHub API {method} {path}: {r.status_code}")
    return r


def load_state():
    """Retrieve conversation state from GitHub repo variables."""
    if not GH_TOKEN:
        return None
    try:
        r = _gh_api("GET", f"/repos/{GH_REPO}/actions/variables/{_state_key()}")
        if r.status_code == 200:
            return json.loads(r.json().get("value", "null"))
    except Exception:
        pass
    return None


def save_state(state):
    """Persist conversation state to GitHub repo variables."""
    if not GH_TOKEN:
        return
    try:
        if state is not None:
            val = json.dumps(state)
            r = _gh_api("PATCH", f"/repos/{GH_REPO}/actions/variables/{_state_key()}", {"value": val})
            if r.status_code == 404:
                _gh_api("POST", f"/repos/{GH_REPO}/actions/variables", {"name": _state_key(), "value": val})
        else:
            _gh_api("DELETE", f"/repos/{GH_REPO}/actions/variables/{_state_key()}")
    except Exception as e:
        print(f"State save warning: {e}")


def clear_state():
    save_state(None)


# ---------------------------------------------------------------------------
# Cookie parsing (same logic as the existing modules)
# ---------------------------------------------------------------------------

def _decode_value(value):
    if isinstance(value, str) and "%" in value:
        try:
            return urllib.parse.unquote(value)
        except Exception:
            return value
    return value


def parse_netscape_line(line):
    parts = line.strip().split("\t")
    if len(parts) >= 7:
        return {parts[5]: parts[6]}
    return {}


def extract_cookies(text, cookie_keys):
    """Parse text in raw / JSON / Netscape format, filter by *cookie_keys*."""
    d = {}
    # Netscape
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        d.update(parse_netscape_line(line))
    # JSON
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        data = None
    if isinstance(data, list):
        for c in data:
            name, value = c.get("name"), c.get("value")
            if name in cookie_keys and isinstance(value, str):
                d[name] = _decode_value(value)
    elif isinstance(data, dict):
        if any(k in data for k in cookie_keys):
            for k in cookie_keys:
                v = data.get(k)
                if isinstance(v, str):
                    d[k] = _decode_value(v)
        elif isinstance(data.get("cookies"), list):
            for c in data["cookies"]:
                name, value = c.get("name"), c.get("value")
                if name in cookie_keys and isinstance(value, str):
                    d[name] = _decode_value(value)
    # Regex fallback
    for key in cookie_keys:
        if key in d:
            continue
        m = re.search(rf"(?<!\w){re.escape(key)}=([^;,\s]+)", text)
        if m:
            d[key] = _decode_value(m.group(1))
    return d


def _find_session_key(d):
    for k in CG_SESSION_TOKEN_KEYS:
        if k in d:
            return k
    return None


# ---------------------------------------------------------------------------
# Telegram API helpers
# ---------------------------------------------------------------------------

def tg_send(text, parse_mode="HTML"):
    """Send a message via Telegram Bot API."""
    payload = {
        "chat_id": CHAT_ID,
        "text": text,
        "parse_mode": parse_mode,
        "disable_web_page_preview": True,
    }
    # Split if too long
    if len(text) > 4000:
        payload.pop("parse_mode", None)
        for i in range(0, len(text), 4000):
            p2 = dict(payload, text=text[i : i + 4000])
            _tg_call(p2)
        return
    _tg_call(payload)


def _tg_call(payload):
    import requests
    try:
        requests.post(
            f"https://api.telegram.org/bot{TG_BOT_TOKEN}/sendMessage",
            json=payload,
            timeout=15,
        )
    except Exception as e:
        print(f"Telegram send error: {e}")


def tg_typing():
    """Show 'typing' indicator."""
    import requests
    try:
        requests.post(
            f"https://api.telegram.org/bot{TG_BOT_TOKEN}/sendChatAction",
            json={"chat_id": CHAT_ID, "action": "typing"},
            timeout=5,
        )
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Processing logic
# ---------------------------------------------------------------------------

def process_netflix(cookie_text):
    """Generate Netflix nftoken and return a reply string."""
    cookie_dict = extract_cookies(cookie_text, NF_COOKIE_KEYS)
    if not cookie_dict:
        return "⚠️ No valid Netflix cookie found.\n\nSend /netflix for instructions."
    if NF_REQUIRED not in cookie_dict:
        return f"⚠️ Missing required cookie: {NF_REQUIRED}"

    if nf_mod is None:
        return "💥 Netflix module not available."

    token, expires = nf_mod.fetch_nftoken(cookie_dict)
    link = nf_mod.build_nftoken_link(token)
    expiry_str = nf_mod.format_expiry(expires)

    return (
        "🎬 <b>Netflix NFToken Generated</b>\n\n"
        f"🔗 <b>Login URL:</b>\n<code>{link}</code>\n\n"
        f"⏳ <b>Expires:</b> {expiry_str}"
    )


def process_chatgpt(cookie_text):
    """Get ChatGPT session and return a reply string."""
    cookie_dict = extract_cookies(cookie_text, CG_COOKIE_KEYS)
    if not cookie_dict:
        return "⚠️ No valid ChatGPT cookie found.\n\nSend /chatgpt for instructions."
    session_key = _find_session_key(cookie_dict)
    if not session_key:
        return "⚠️ Missing __Secure-next-auth.session-token"

    if cg_mod is None:
        return "💥 ChatGPT module not available."

    user_info, expires, access_token = cg_mod.fetch_session(cookie_dict)
    user_str = cg_mod.format_user_info(user_info)
    expiry_str = cg_mod.format_expiry(expires)

    reply = (
        "💬 <b>ChatGPT Session Retrieved</b>\n\n"
        f"👤 <b>User:</b>\n{user_str}\n\n"
        f"⏳ <b>Expires:</b> {expiry_str}\n"
    )
    if access_token:
        preview = access_token[:60] + "..." if len(access_token) > 60 else access_token
        reply += f"\n🔑 <b>Access Token:</b>\n<code>{preview}</code>"
    return reply, access_token


# ---------------------------------------------------------------------------
# Message router
# ---------------------------------------------------------------------------

def handle_message():
    """Main logic — decide what to do based on message text and state."""
    text = MSG_TEXT

    # ── Commands ────────────────────────────────────────────────
    if text.startswith("/"):
        clear_state()
        tg_typing()
        reply = handle_command(text)
        if reply:
            tg_send(reply)
        return

    # ── Plain text → check saved state ──────────────────────────
    state = load_state()
    if state:
        mode = state.get("mode")
        if mode == "netflix":
            return handle_netflix_cookie(text)
        elif mode == "chatgpt":
            return handle_chatgpt_cookie(text)

    # ── No state, no command → try auto-detect ──────────────────
    tg_typing()
    reply = auto_detect(text)
    if reply:
        tg_send(reply)
    return


def handle_command(text):
    """Handle a command message. Returns a reply string to send, or delegates to cookie handlers."""
    cmd = text.split()[0].lower()

    if cmd in (CMD_START, CMD_HELP):
        return (
            "🤖 <b>Cookie → Token Bot</b>\n\n"
            "I turn session cookies into login tokens.\n\n"
            "<b>Commands:</b>\n"
            "🎬 /netflix — Generate a Netflix nftoken\n"
            "💬 /chatgpt — Get a ChatGPT session token\n"
            "❌ /cancel — Reset\n\n"
            "<b>How to use:</b>\n"
            "1. Send /netflix or /chatgpt\n"
            "2. I'll ask for your cookie\n"
            "3. Paste the cookie → I reply with the token\n\n"
            "Or send everything in one message:\n"
            "<code>/netflix NetflixId=xxx; SecureNetflixId=xxx</code>"
        )

    if cmd == CMD_NETFLIX:
        # Check if the cookie was included in the same message
        rest = text[len(CMD_NETFLIX):].strip()
        if rest:
            return handle_netflix_cookie(rest)
        # Otherwise store state and wait
        save_state({"mode": "netflix"})
        return (
            "🎬 Send me your <b>Netflix cookie</b> in any format:\n\n"
            "<code>NetflixId=xxx; SecureNetflixId=xxx</code>\n\n"
            "Or a JSON export from Cookie-Editor.\n"
            "Send /cancel to abort."
        )

    if cmd == CMD_CHATGPT:
        rest = text[len(CMD_CHATGPT):].strip()
        if rest:
            return handle_chatgpt_cookie(rest)
        save_state({"mode": "chatgpt"})
        return (
            "💬 Send me your <b>ChatGPT cookie</b> in any format:\n\n"
            "<code>__Secure-next-auth.session-token.0=eyJ...</code>\n\n"
            "Or a JSON export from Cookie-Editor.\n"
            "Send /cancel to abort."
        )

    if cmd == CMD_CANCEL:
        return "❌ Cancelled. Send /netflix or /chatgpt to start again."

    return "Unknown command. Try /start, /netflix, or /chatgpt."


def handle_netflix_cookie(cookie_text):
    clear_state()
    tg_typing()
    try:
        result = process_netflix(cookie_text)
        # Send access token separately if present for ChatGPT (but this is Netflix)
        if isinstance(result, tuple):
            msg, extra = result
            tg_send(msg)
            if extra:
                tg_send(f"🔑 <b>Full Access Token:</b>\n{extra}")
        else:
            tg_send(result)
    except Exception as e:
        print(f"Netflix error: {e}")
        tg_send(
            "💥 <b>Request failed.</b>\n\n"
            "• The cookie may be expired\n"
            "• Netflix API may be blocking\n\n"
            "Try a fresh cookie export."
        )


def handle_chatgpt_cookie(cookie_text):
    clear_state()
    tg_typing()
    try:
        result = process_chatgpt(cookie_text)
        if isinstance(result, tuple):
            msg, extra = result
            tg_send(msg)
            if extra:
                tg_send(f"🔑 <b>Full Access Token:</b>\n{extra}")
        else:
            tg_send(result)
    except Exception as e:
        print(f"ChatGPT error: {e}")
        tg_send(
            "💥 <b>Request failed.</b>\n\n"
            "• The cookie may be expired\n"
            "• Cloudflare may be blocking\n\n"
            "Try a fresh cookie export from https://chatgpt.com"
        )


def auto_detect(text):
    """Try to guess the service from the cookie content."""
    has_nf = any(k in text for k in NF_COOKIE_KEYS)
    has_cg = any(k in text for k in CG_SESSION_TOKEN_KEYS)

    if has_nf and not has_cg:
        clear_state()
        tg_typing()
        try:
            result = process_netflix(text)
            msg = result[0] if isinstance(result, tuple) else result
            tg_send(msg)
        except Exception as e:
            print(f"Auto Netflix error: {e}")
            tg_send("Could not process Netflix cookie. Try /netflix for help.")
        return

    if has_cg:
        clear_state()
        tg_typing()
        try:
            result = process_chatgpt(text)
            if isinstance(result, tuple):
                msg, extra = result
                tg_send(msg)
                if extra:
                    tg_send(f"🔑 Full Access Token:\n{extra}")
            else:
                tg_send(result)
        except Exception as e:
            print(f"Auto ChatGPT error: {e}")
            tg_send("Could not process ChatGPT cookie. Try /chatgpt for help.")
        return

    # Nothing recognised
    tg_send(
        "🤷 I don't recognise this as a Netflix or ChatGPT cookie.\n\n"
        "Send /netflix or /chatgpt to get started."
    )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    if not TG_BOT_TOKEN or not CHAT_ID:
        print("Missing TG_BOT_TOKEN or CHAT_ID — running from env?")
        sys.exit(0)
    handle_message()
