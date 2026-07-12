/**
 * CLOUDFLARE WORKER — Telegram Webhook → GitHub Actions Bridge
 * ============================================================
 *
 * What it does:
 *   Receives a Telegram update via webhook and forwards it to a GitHub
 *   repository using the repository_dispatch API.  This wakes up a
 *   GitHub Actions workflow that processes the message and replies.
 *
 * Deploy (free):
 *   1. Sign up at https://cloudflare.com (no credit card needed)
 *   2. Create a Worker and paste this script
 *   3. Set secrets (vars → secrets):
 *      - GH_PAT     — GitHub Personal Access Token (classic, repo scope)
 *      - GH_REPO    — "owner/repo-name" (e.g. "youruser/Netflix-NFToken-Generator")
 *   4. Set your Telegram bot webhook:
 *      curl "https://api.telegram.org/bot<TOKEN>/setWebhook?url=https://<worker>.workers.dev"
 */

// ── Configuration ─────────────────────────────────────────────────

// These are set as Worker secrets (not hardcoded).
// See "Settings → Variables → Secrets" in the Cloudflare dashboard.
const GH_PAT  = globalThis.GH_PAT  || "";   // GitHub token
const GH_REPO = globalThis.GH_REPO || "";    // "owner/repo"
const TG_BOT_TOKEN = globalThis.TG_BOT_TOKEN || "";

// ── Webhook handler ───────────────────────────────────────────────

export default {
  async fetch(request, env, ctx) {
    // Only accept POST from Telegram
    if (request.method !== "POST") {
      return new Response("Send POST", { status: 405 });
    }

    const pat   = env.GH_PAT  || GH_PAT;
    const repo  = env.GH_REPO || GH_REPO;
    const token = env.TG_BOT_TOKEN || TG_BOT_TOKEN;

    if (!pat || !repo || !token) {
      return new Response(
        "Worker not configured: missing GH_PAT, GH_REPO, or TG_BOT_TOKEN",
        { status: 500 }
      );
    }

    try {
      const update = await request.json();

      // Extract the message text and chat ID (we pass everything to GH)
      const msg     = update.message?.text || "";
      const chatId  = update.message?.chat?.id;
      const updateId = update.update_id;

      if (!chatId) {
        return new Response("Not a message update", { status: 200 });
      }

      // ── Dispatch to GitHub Actions ────────────────────────────
      const dispatchBody = {
        event_type: "telegram-message",
        client_payload: {
          chat_id: chatId,
          text: msg,
          update_id: updateId,
          from: update.message?.from,
          date: update.message?.date,
        },
      };

      const ghResp = await fetch(
        `https://api.github.com/repos/${repo}/dispatches`,
        {
          method: "POST",
          headers: {
            Authorization: `Bearer ${pat}`,
            Accept: "application/vnd.github+json",
            "User-Agent": "tg-bot-worker",
          },
          body: JSON.stringify(dispatchBody),
        }
      );

      if (!ghResp.ok) {
        const errText = await ghResp.text();
        // 422 usually means the event_type isn't registered yet —
        // the workflow .yml just needs to exist on the default branch.
        console.error(`GitHub API ${ghResp.status}: ${errText}`);
      }

      // Acknowledge Telegram immediately (don't make it retry)
      return new Response("OK", { status: 200 });
    } catch (err) {
      console.error("Worker error:", err);
      return new Response("OK", { status: 200 }); // always ack Telegram
    }
  },
};
