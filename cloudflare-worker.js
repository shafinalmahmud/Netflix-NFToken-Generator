/**
 * CLOUDFLARE WORKER — Telegram Webhook → GitHub Actions Bridge
 * ============================================================
 *
 * Receives a Telegram update via webhook and forwards it to a GitHub
 * repository using the repository_dispatch API.
 *
 * For large messages (exceeding Telegram's 4 KB limit), text is stored in
 * a GitHub Actions variable first, then referenced by key in the dispatch.
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

/**
 * Minify JSON text to save payload size.
 */
function minifyText(text) {
  if (!text) return text;
  const t = text.trim();
  if (t.startsWith("[") || t.startsWith("{")) {
    try {
      return JSON.stringify(JSON.parse(t));
    } catch {
      return text;
    }
  }
  return text;
}

/**
 * Store a large text value in a GitHub Actions variable and return its key.
 * Variables have a 48 KB limit, much larger than the 10 KB dispatch payload cap.
 */
async function storeInGitHubVariable(text, chatId, pat, repo) {
  const varName = `tg_d_${chatId}`;
  const baseUrl = `https://api.github.com/repos/${repo}/actions/variables`;
  const headers = {
    Authorization: `Bearer ${pat}`,
    Accept: "application/vnd.github+json",
    "User-Agent": "tg-bot-worker",
    "Content-Type": "application/json",
  };

  // Check if variable already exists
  const getResp = await fetch(`${baseUrl}/${varName}`, {
    method: "GET",
    headers: headers,
  });

  let resp;
  if (getResp.status === 404) {
    // Create new variable
    resp = await fetch(baseUrl, {
      method: "POST",
      headers: headers,
      body: JSON.stringify({ name: varName, value: text }),
    });
  } else {
    // Update existing variable
    resp = await fetch(`${baseUrl}/${varName}`, {
      method: "PATCH",
      headers: headers,
      body: JSON.stringify({ name: varName, value: text }),
    });
  }

  if (!resp.ok && resp.status !== 204) {
    const err = await resp.text().catch(() => "unknown");
    console.error(`GitHub variable API error: ${resp.status} ${err}`);
    // Fall through — dispatch the raw text even if variable storage fails
    return null;
  }

  return varName;
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
    const rawText = update.message?.text || "";
    const text = minifyText(rawText);

    if (!chatId) {
      return new Response("OK", { status: 200 });
    }

    let dispatchText = text;

    // If text is large, store in GitHub variable and pass reference key
    // (GitHub's API limit is 10 KB for the entire client_payload)
    if (text.length > 3000) {
      const varName = await storeInGitHubVariable(text, chatId, pat, repo);
      if (varName) {
        dispatchText = `__VAR__${varName}`;
      }
      // If variable storage failed, dispatchText stays as the raw text (best-effort)
    }

    // Forward to GitHub Actions via repository_dispatch
    const dispatchBody = {
      event_type: "telegram-message",
      client_payload: {
        chat_id: chatId,
        text: dispatchText,
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
