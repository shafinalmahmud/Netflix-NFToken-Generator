"""
PythonAnywhere Webhook Relay
============================
Tiny Flask app that receives Telegram updates and forwards them to
GitHub Actions via repository_dispatch.

How to deploy on PythonAnywhere (free, no credit card):
  1. Sign up at https://pythonanywhere.com (email only)
  2. Go to Web tab → Add a new web app → Manual Config → Python 3.12
  3. Go to Files tab → Upload this file as "relay.py"
  4. Go to Web tab → WSGI configuration file → edit to point at relay.py
  5. Go to Web tab → Environment variables → add:
     GH_TOKEN = &lt;your-github-classic-pat-with-repo-scope&gt;
     GH_REPO  = yourusername/Netflix-NFToken-Generator
  6. Reload the web app → copy your URL (https://yourname.pythonanywhere.com)
  7. Set Telegram webhook:
     https://api.telegram.org/bot&lt;your-bot-token&gt;/setWebhook?url=https://yourname.pythonanywhere.com/webhook
"""

import os
import sys

from flask import Flask, jsonify, request
import requests

app = Flask(__name__)

GH_TOKEN = os.environ.get("GH_TOKEN", "")
GH_REPO = os.environ.get("GH_REPO", "")


@app.route("/webhook", methods=["POST"])
def webhook():
    """Receive Telegram update and forward to GitHub Actions."""
    update = request.json
    if not update:
        return jsonify({"ok": False}), 400

    chat_id = (update.get("message") or {}).get("chat", {}).get("id")
    text = (update.get("message") or {}).get("text", "")
    update_id = update.get("update_id")

    if not chat_id or not GH_TOKEN or not GH_REPO:
        return jsonify({"ok": True})  # always ack Telegram

    try:
        resp = requests.post(
            f"https://api.github.com/repos/{GH_REPO}/dispatches",
            headers={
                "Authorization": f"Bearer {GH_TOKEN}",
                "Accept": "application/vnd.github+json",
                "User-Agent": "pa-relay/1.0",
            },
            json={
                "event_type": "telegram-message",
                "client_payload": {
                    "chat_id": chat_id,
                    "text": text,
                    "update_id": update_id,
                },
            },
            timeout=15,
        )
        print(f"GitHub API: {resp.status_code}")
    except Exception as exc:
        print(f"Relay error: {exc}")

    return jsonify({"ok": True})


@app.route("/", methods=["GET"])
def index():
    return "✅ Telegram webhook relay is running."


# ── For PythonAnywhere WSGI ─────────────────────────────────────────
application = app

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)
