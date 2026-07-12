/**
 * CLOUDFLARE WORKER — Telegram Webhook → GitHub Actions Bridge
 * ============================================================
 *
 * Receives a Telegram update via webhook and forwards it to a GitHub
 * repository using the repository_dispatch API.
 *
 * Deploy:
 *   1. Set env vars in Cloudflare dashboard (not hardcoded):
 *      - GH_PAT     — GitHub Personal Access Token (classic, repo scope)
 *      - GH_REPO    — "owner/repo-name" (e.g. "youruser/Netflix-NFToken-Generator")
 *      - TG_BOT_TOKEN — Telegram bot token
 *   2. Set your Telegram bot webhook:
 *      curl "https://api.telegram.org/bot<TOKEN>/setWebhook?url=https://<worker>.workers.dev"
 */

// ── Secrets are injected via Cloudflare environment variables ──────
// Set these in the Cloudflare dashboard: Workers → your worker → Settings → Variables
// GH_PAT, GH_REPO, TG_BOT_TOKEN

addEventListener("fetch", (event) => {
  event.respondWith(handleRequest(event.request));
});

async function handleRequest(request) {
  // Only accept POST for webhook
  if (request.method === "POST") {
    return handleWebhook(request);
  }

  // GET returns a simple status page
  return new Response("Telegram bot relay is running.", {
    headers: { "Content-Type": "text/plain" },
  });
}

async function handleWebhook(request) {
  const pat = globalThis.GH_PAT;
  const repo = globalThis.GH_REPO;
  const token = globalThis.TG_BOT_TOKEN;

  if (!pat || !repo || !token) {
    console.error("Missing secrets: GH_PAT, GH_REPO, or TG_BOT_TOKEN");
    return new Response("OK", { status: 200 });
  }

  try {
    const update = await request.json();
    const chatId = update.message?.chat?.id;
    const text = update.message?.text || "";
    const updateId = update.update_id;

    if (!chatId) {
      return new Response("OK", { status: 200 });
    }

    // Forward to GitHub Actions via repository_dispatch
    const dispatchBody = {
      event_type: "telegram-message",
      client_payload: {
        chat_id: chatId,
        text: text,
        update_id: updateId,
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
      console.error(`GitHub API ${ghResp.status}: ${errText}`);
    }

    return new Response("OK", { status: 200 });
  } catch (err) {
    console.error("Worker error:", err);
    return new Response("OK", { status: 200 });
  }
}
