const DEFAULT_STATUS_CODE = 503;
const DEFAULT_TITLE = 'Tweeticcini dashboard temporarily unavailable';
const DEFAULT_MESSAGE =
  'The dashboard is temporarily unavailable while Tweeticcini reconnects to the host system. Existing follows and settings remain intact.';
const DEFAULT_RETRY_AFTER = '300';
const DEFAULT_TIMEOUT_MS = 8000;

function acceptsHtml(request) {
  const accept = request.headers.get('accept') || '';
  return accept.includes('text/html');
}

function buildHtmlResponse(message, dashboardUrl) {
  const safeMessage = String(message);
  const safeDashboardUrl = String(dashboardUrl || 'https://app.tweeticcini.com/dashboard');

  return `<!DOCTYPE html>
<html lang="en">
  <head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>${DEFAULT_TITLE}</title>
    <style>
      :root {
        color-scheme: dark;
        --bg: #0a0d14;
        --panel: rgba(16, 22, 36, 0.94);
        --text: #f5f7fb;
        --muted: #c7d2ea;
        --border: rgba(146, 164, 204, 0.24);
        --accent: #59d0ff;
        --accent-secondary: #bd5fff;
      }
      * { box-sizing: border-box; }
      body {
        margin: 0;
        min-height: 100vh;
        display: grid;
        place-items: center;
        padding: 24px;
        font-family: ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
        background:
          radial-gradient(circle at top, rgba(89, 208, 255, 0.14), transparent 38%),
          linear-gradient(180deg, #0b1220, var(--bg));
        color: var(--text);
      }
      main {
        width: min(100%, 720px);
        padding: 28px;
        border: 1px solid var(--border);
        border-radius: 24px;
        background: var(--panel);
        box-shadow: 0 24px 60px rgba(3, 7, 18, 0.42);
      }
      .eyebrow {
        margin: 0 0 10px;
        color: var(--accent);
        font-size: 0.82rem;
        font-weight: 700;
        letter-spacing: 0.1em;
        text-transform: uppercase;
      }
      h1 {
        margin: 0;
        font-size: clamp(2rem, 4vw, 3rem);
        line-height: 1.02;
      }
      p {
        margin: 14px 0 0;
        color: var(--muted);
        line-height: 1.65;
      }
      .actions {
        display: flex;
        flex-wrap: wrap;
        gap: 12px;
        margin-top: 22px;
      }
      .button {
        display: inline-flex;
        align-items: center;
        justify-content: center;
        min-height: 46px;
        padding: 0 18px;
        border-radius: 999px;
        border: 1px solid transparent;
        color: #fff;
        font-weight: 700;
        text-decoration: none;
      }
      .button-primary {
        background: linear-gradient(135deg, var(--accent), var(--accent-secondary));
      }
      .button-secondary {
        background: rgba(255, 255, 255, 0.05);
        border-color: var(--border);
      }
    </style>
  </head>
  <body>
    <main>
      <p class="eyebrow">Tweeticcini status</p>
      <h1>${DEFAULT_TITLE}</h1>
      <p>${safeMessage}</p>
      <p>No action is needed on your end. Alerts and dashboard access will resume automatically once connectivity is restored.</p>
      <div class="actions">
        <a class="button button-primary" href="${safeDashboardUrl}">Try dashboard again</a>
        <a class="button button-secondary" href="https://tweeticcini.com">Open website</a>
      </div>
    </main>
  </body>
</html>`;
}

function buildOutageResponse(request, env, reason) {
  const message = env.MAINTENANCE_MESSAGE || DEFAULT_MESSAGE;
  const dashboardUrl = env.DASHBOARD_URL || new URL(request.url).origin + '/dashboard';
  const headers = {
    'Cache-Control': 'no-store',
    'Retry-After': env.RETRY_AFTER || DEFAULT_RETRY_AFTER,
  };

  if (!acceptsHtml(request)) {
    headers['Content-Type'] = 'application/json; charset=utf-8';
    return new Response(
      JSON.stringify({
        status: 'offline',
        reason,
        message,
        dashboard_url: dashboardUrl,
      }),
      {
        status: DEFAULT_STATUS_CODE,
        headers,
      },
    );
  }

  headers['Content-Type'] = 'text/html; charset=utf-8';
  return new Response(buildHtmlResponse(message, dashboardUrl), {
    status: DEFAULT_STATUS_CODE,
    headers,
  });
}

export default {
  async fetch(request, env) {
    if (env.MAINTENANCE_MODE === '1') {
      return buildOutageResponse(request, env, 'manual_maintenance');
    }

    const controller = new AbortController();
    const timeout = setTimeout(
      () => controller.abort(new Error('origin_timeout')),
      Number(env.ORIGIN_TIMEOUT_MS || DEFAULT_TIMEOUT_MS),
    );

    try {
      return await fetch(request, { signal: controller.signal });
    } catch (_error) {
      return buildOutageResponse(request, env, 'origin_unavailable');
    } finally {
      clearTimeout(timeout);
    }
  },
};
