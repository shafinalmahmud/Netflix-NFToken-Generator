"""
Telegram Bot - Netflix NFToken & ChatGPT Session Token Generator
===============================================================

Lets you generate tokens by pasting cookies directly in Telegram.

Setup
-----
1. Talk to @BotFather on Telegram to create a bot and get its token.
2. Set the token as an environment variable or edit BOT_TOKEN below.
3. Run: python bot.py

Usage
-----
  /start    - Welcome & instructions
  /netflix  - Generate a Netflix nftoken from a cookie
  /chatgpt  - Get a ChatGPT session / access token from a cookie
  /cancel   - Cancel the current operation
"""

import importlib.util
import json
import logging
import os
import re
import sys
import urllib.parse
from pathlib import Path

from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    ConversationHandler,
    MessageHandler,
    filters,
)

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

# Option A: set env TELEGRAM_BOT_TOKEN
# Option B: paste your token directly here (not recommended for sharing)
BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "YOUR_BOT_TOKEN_HERE")

# Directory this file lives in
BASE_DIR = Path(__file__).resolve().parent

# ---------------------------------------------------------------------------
# Import token-generator modules via importlib (handles hyphenated filenames)
# ---------------------------------------------------------------------------

def _load_module(filename, module_name):
    """Load a Python file as a module, even if its name has hyphens."""
    filepath = BASE_DIR / filename
    if not filepath.exists():
        raise ImportError(f"{filename} not found in {BASE_DIR}")
    spec = importlib.util.spec_from_file_location(module_name, filepath)
    mod = importlib.util.module_from_spec(spec)
    # Make symbols from this module importable within the loaded code
    sys.modules[module_name] = mod
    spec.loader.exec_module(mod)
    return mod


try:
    nf_mod = _load_module("nf-token-generator.py", "nf_token_generator")
    cg_mod = _load_module("chatgpt-token-generator.py", "chatgpt_token_generator")
    logger.info("Loaded token-generator modules successfully")
except ImportError as exc:
    logger.error("Failed to load modules: %s", exc)
    nf_mod = None
    cg_mod = None


# ---------------------------------------------------------------------------
# Shared helpers (mirror what the modules do, but with safety for Telegram)
# ---------------------------------------------------------------------------

# Netflix keys
NF_COOKIE_KEYS = ("NetflixId", "SecureNetflixId", "nfvdid", "OptanonConsent")
NF_REQUIRED = "NetflixId"

# ChatGPT keys
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


def _decode_cookie_value(value):
    if isinstance(value, str) and "%" in value:
        try:
            return urllib.parse.unquote(value)
        except Exception:
            return value
    return value


def parse_netscape_cookie_line(line):
    parts = line.strip().split("\t")
    if len(parts) >= 7:
        return {parts[5]: parts[6]}
    return {}


def extract_cookie_dict(text, cookie_keys):
    """Parse cookie text and return a dict, filtering for *cookie_keys*."""
    cookie_dict = {}

    # Netscape
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        cookie_dict.update(parse_netscape_cookie_line(line))

    # JSON
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        data = None

    if isinstance(data, list):
        for cookie in data:
            name = cookie.get("name")
            value = cookie.get("value")
            if name in cookie_keys and isinstance(value, str):
                cookie_dict[name] = _decode_cookie_value(value)
    elif isinstance(data, dict):
        if any(key in data for key in cookie_keys):
            for key in cookie_keys:
                value = data.get(key)
                if isinstance(value, str):
                    cookie_dict[key] = _decode_cookie_value(value)
        elif isinstance(data.get("cookies"), list):
            for cookie in data["cookies"]:
                name = cookie.get("name")
                value = cookie.get("value")
                if name in cookie_keys and isinstance(value, str):
                    cookie_dict[name] = _decode_cookie_value(value)

    # Raw regex fallback
    for key in cookie_keys:
        if key in cookie_dict:
            continue
        match = re.search(rf"(?<!\w){re.escape(key)}=([^;,\s]+)", text)
        if match:
            cookie_dict[key] = _decode_cookie_value(match.group(1))

    return cookie_dict


def _find_session_token_key(cookie_dict):
    for key in CG_SESSION_TOKEN_KEYS:
        if key in cookie_dict:
            return key
    return None


# ---------------------------------------------------------------------------
# Core token-generation calls (delegates to the loaded modules)
# ---------------------------------------------------------------------------

def generate_netflix_token(cookie_text):
    """Return (token_url, expiry_str) or raise on failure."""
    cookie_dict = extract_cookie_dict(cookie_text, NF_COOKIE_KEYS)
    if not cookie_dict:
        raise ValueError("No valid Netflix cookie found.")
    if NF_REQUIRED not in cookie_dict:
        raise ValueError(
            f"Missing required cookie: {NF_REQUIRED}. "
            "Make sure your Netflix cookie includes NetflixId."
        )
    # Delegate to the loaded module
    if nf_mod is not None:
        token, expires = nf_mod.fetch_nftoken(cookie_dict)
        link = nf_mod.build_nftoken_link(token)
        expiry_str = nf_mod.format_expiry(expires)
    else:
        # Fallback (should not happen if module was loaded)
        raise RuntimeError("Netflix module not loaded.")
    return link, expiry_str


def generate_chatgpt_token(cookie_text):
    """Return (user_info_str, expiry_str, access_token) or raise."""
    cookie_dict = extract_cookie_dict(cookie_text, CG_COOKIE_KEYS)
    if not cookie_dict:
        raise ValueError("No valid ChatGPT cookie found.")
    session_key = _find_session_token_key(cookie_dict)
    if not session_key:
        raise ValueError(
            "Missing required cookie: __Secure-next-auth.session-token "
            "(or any suffixed variant)."
        )
    # Delegate to the loaded module
    if cg_mod is not None:
        user_info, expires, access_token = cg_mod.fetch_session(cookie_dict)
        user_str = cg_mod.format_user_info(user_info)
        expiry_str = cg_mod.format_expiry(expires)
    else:
        raise RuntimeError("ChatGPT module not loaded.")
    return user_str, expiry_str, access_token


# ---------------------------------------------------------------------------
# Telegram bot — Conversation states
# ---------------------------------------------------------------------------

(NETFLIX_WAIT_COOKIE, CHATGPT_WAIT_COOKIE) = range(2)

# In-memory user-data dictionary (simple; resets on restart)
# In production you'd use a persistent store, but this is fine for a local bot.
user_sessions: dict[int, str] = {}


async def start(update, context):
    """Send a welcome message with usage instructions."""
    text = (
        "\U0001f916 <b>Cookie → Token Bot</b>\n\n"
        "I turn session cookies into login tokens.\n\n"
        "<b>Commands:</b>\n"
        "\U0001f3f7 /netflix — Generate a Netflix nftoken\n"
        "\U0001f4ac /chatgpt — Get a ChatGPT session token\n"
        "\U0000274c /cancel — Cancel current operation\n\n"
        "<b>How to use:</b>\n"
        "1. Send /netflix or /chatgpt\n"
        "2. Paste your cookie (as raw text or JSON export)\n"
        "3. I'll reply with your token ✨\n\n"
        "Get your cookie from a browser extension like "
        "<i>Cookie-Editor</i> or <i>EditThisCookie</i>."
    )
    await update.message.reply_html(text)


async def help_command(update, context):
    await start(update, context)


async def netflix_start(update, context):
    """Start the Netflix cookie flow."""
    user_id = update.effective_user.id
    user_sessions[user_id] = "netflix"
    text = (
        "\U0001f3f7 <b>Netflix Token</b>\n\n"
        "Send me your Netflix cookie in any format:\n\n"
        "\U0001f4cb <b>Raw string:</b>\n"
        "<code>NetflixId=xxx; SecureNetflixId=xxx</code>\n\n"
        "\U0001f4ca <b>JSON array</b> (from Cookie-Editor):\n"
        "<code>[{\"name\": \"NetflixId\", \"value\": \"...\"}]</code>\n\n"
        "\U0001f4dd <b>JSON object:</b>\n"
        "<code>{\"NetflixId\": \"...\"}</code>\n\n"
        "Send /cancel to abort."
    )
    await update.message.reply_html(text)
    return NETFLIX_WAIT_COOKIE


async def chatgpt_start(update, context):
    """Start the ChatGPT cookie flow."""
    user_id = update.effective_user.id
    user_sessions[user_id] = "chatgpt"
    text = (
        "\U0001f4ac <b>ChatGPT Token</b>\n\n"
        "Send me your ChatGPT cookie in any format:\n\n"
        "\U0001f4cb <b>Raw string:</b>\n"
        "<code>__Secure-next-auth.session-token.0=eyJ...; __Secure-next-auth.session-token.1=...</code>\n\n"
        "\U0001f4ca <b>JSON array</b> (from Cookie-Editor):\n"
        "<code>[{\"name\": \"__Secure-next-auth.session-token.0\", \"value\": \"...\"}]</code>\n\n"
        "\U0001f4dd <b>JSON object:</b>\n"
        "<code>{\"__Secure-next-auth.session-token.0\": \"...\"}</code>\n\n"
        "Send /cancel to abort."
    )
    await update.message.reply_html(text)
    return CHATGPT_WAIT_COOKIE


async def cancel(update, context):
    """Cancel the current operation."""
    user_id = update.effective_user.id
    user_sessions.pop(user_id, None)
    await update.message.reply_text(
        "❌ Cancelled. Send /netflix or /chatgpt to start again."
    )
    return ConversationHandler.END


def _build_reply(text, max_len=4000):
    """Split a reply if it exceeds Telegram's character limit."""
    if len(text) <= max_len:
        return [text]
    parts = []
    while text:
        parts.append(text[:max_len])
        text = text[max_len:]
    return parts


async def handle_netflix_cookie(update, context):
    """Receive the Netflix cookie text and generate the token."""
    user_id = update.effective_user.id
    cookie_text = update.message.text.strip()
    user_sessions.pop(user_id, None)

    await update.message.reply_chat_action("typing")

    try:
        link, expiry = generate_netflix_token(cookie_text)
        reply = (
            "\U0001f3f7 <b>Netflix NFToken Generated</b>\n\n"
            f"\U0001f517 <b>Login URL:</b>\n"
            f"<code>{link}</code>\n\n"
            f"\U000023f3 <b>Expires:</b> {expiry}"
        )
        for part in _build_reply(reply):
            await update.message.reply_html(part, disable_web_page_preview=True)
        logger.info("Netflix token generated for user %s", user_id)
    except ValueError as exc:
        await update.message.reply_html(
            f"⚠️ <b>Error:</b> {exc}\n\n"
            "Make sure your cookie is valid and includes <code>NetflixId</code>."
        )
    except Exception as exc:
        logger.exception("Netflix generation failed")
        await update.message.reply_html(
            f"\U0001f4a5 <b>Request failed:</b> {exc}\n\n"
            "Possible causes:\n"
            "• The cookie is expired or invalid\n"
            "• Network issue\n"
            "• Netflix API blocked the request\n\n"
            "Try exporting a fresh cookie and try again."
        )

    return ConversationHandler.END


async def handle_chatgpt_cookie(update, context):
    """Receive the ChatGPT cookie text and generate the session."""
    user_id = update.effective_user.id
    cookie_text = update.message.text.strip()
    user_sessions.pop(user_id, None)

    await update.message.reply_chat_action("typing")

    try:
        user_str, expiry, access_token = generate_chatgpt_token(cookie_text)
        reply = (
            "\U0001f4ac <b>ChatGPT Session Retrieved</b>\n\n"
            f"\U0001f464 <b>User Info:</b>\n"
            f"{user_str}\n\n"
            f"\U000023f3 <b>Expires:</b> {expiry}\n"
        )
        if access_token:
            # Show a preview + the full token in a code block
            preview = access_token[:60] + "..." if len(access_token) > 60 else access_token
            reply += f"\n\U0001f511 <b>Access Token:</b>\n<code>{preview}</code>\n\n"
            reply += (
                "<i>The full token has been sent in a second message.</i>"
            )
        for part in _build_reply(reply):
            await update.message.reply_html(part, disable_web_page_preview=True)

        # Send full token separately (it's long and may break formatting)
        if access_token:
            await update.message.reply_text(
                f"\U0001f511 Full Access Token:\n\n{access_token}"
            )

        logger.info("ChatGPT session retrieved for user %s", user_id)
    except ValueError as exc:
        await update.message.reply_html(
            f"⚠️ <b>Error:</b> {exc}\n\n"
            "Make sure your cookie includes "
            "<code>__Secure-next-auth.session-token.0</code> or "
            "<code>__Secure-next-auth.session-token</code>."
        )
    except Exception as exc:
        logger.exception("ChatGPT session retrieval failed")
        await update.message.reply_html(
            f"\U0001f4a5 <b>Request failed:</b> {exc}\n\n"
            "Possible causes:\n"
            "• The cookie is expired or invalid\n"
            "• The cookie domain doesn't match chatgpt.com\n"
            "• Cloudflare / rate-limiting\n"
            "• Network issue\n\n"
            "Try exporting a fresh cookie from https://chatgpt.com and try again."
        )

    return ConversationHandler.END


async def fallback_handler(update, context):
    """Handle messages when no conversation is active."""
    text = (
        "Send a command first:\n"
        "/netflix — Netflix nftoken\n"
        "/chatgpt — ChatGPT session token\n"
        "/help — Show instructions"
    )
    await update.message.reply_text(text)


async def post_init(application):
    """Log when the bot starts."""
    logger.info("Bot started. Press Ctrl+C to stop.")


async def error_handler(update, context):
    """Log all errors."""
    logger.error("Update %s caused error %s", update, context.error)


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def main():
    if BOT_TOKEN == "YOUR_BOT_TOKEN_HERE":
        print("=" * 60)
        print("  BOT TOKEN NOT CONFIGURED")
        print("=" * 60)
        print()
        print("To use this bot you need a Telegram bot token:")
        print()
        print("  1. Open Telegram and search for @BotFather")
        print("  2. Send /newbot and follow the prompts")
        print("  3. Copy the token and set it:")
        print()
        print("     Option A — Environment variable:")
        print("       set TELEGRAM_BOT_TOKEN=123456:ABC-DEF1234ghI...")
        print("       python bot.py")
        print()
        print("     Option B — Edit bot.py:")
        print("       Change BOT_TOKEN = 'YOUR_BOT_TOKEN_HERE'")
        print()
        sys.exit(1)

    # Build application
    app = (
        Application.builder()
        .token(BOT_TOKEN)
        .post_init(post_init)
        .build()
    )

    # ── Netflix conversation ──────────────────────────────────────
    netflix_conv = ConversationHandler(
        entry_points=[CommandHandler("netflix", netflix_start)],
        states={
            NETFLIX_WAIT_COOKIE: [
                MessageHandler(
                    filters.TEXT & ~filters.COMMAND,
                    handle_netflix_cookie,
                ),
            ],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
        name="netflix_conv",
        persistent=False,
    )

    # ── ChatGPT conversation ──────────────────────────────────────
    chatgpt_conv = ConversationHandler(
        entry_points=[CommandHandler("chatgpt", chatgpt_start)],
        states={
            CHATGPT_WAIT_COOKIE: [
                MessageHandler(
                    filters.TEXT & ~filters.COMMAND,
                    handle_chatgpt_cookie,
                ),
            ],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
        name="chatgpt_conv",
        persistent=False,
    )

    # ── Register handlers ─────────────────────────────────────────
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(netflix_conv)
    app.add_handler(chatgpt_conv)
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, fallback_handler))
    app.add_error_handler(error_handler)

    # ── Start polling ─────────────────────────────────────────────
    print("Bot is running... Press Ctrl+C to stop.")
    app.run_polling(allowed_updates=["messages"])


if __name__ == "__main__":
    main()
