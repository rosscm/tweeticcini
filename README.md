<div align="center">

# Tweeticcini

A production-ready Discord bot for real-time Twitter/X notifications with advanced filtering and automation.

</div>

## 📝 Overview

Tweeticcini monitors selected Twitter/X accounts and delivers structured, filtered notifications directly to Discord channels.

This project extends the original [Tweetcord](https://github.com/Yuuzi261/Tweetcord) framework with additional filtering, automation, and production-focused deployment improvements.

Built for communities that require reliable, automated social monitoring without manual tracking.

## ✨ Core Features

- 🔄 Real-time tweet monitoring
- 🔐 Server-managed Twitter/X session authorization in the dashboard
- 🎯 Role-based mention targeting
- 🔎 Keyword include and exclude filtering
- 🔁 Retweet and quote filtering
- 🖼 Media-only filtering
- 🛠 Customizable notification templates
- ⏱ Configurable polling intervals
- 💾 Persistent database storage
- ⚙️ Systemd-friendly standalone deployment

## 💬 Commands
### Command Overview

| Command              | Description                                              |
| -------------------- | -------------------------------------------------------- |
| `/add notifier`      | Legacy add flow; dashboard monitors are preferred        |
| `/remove notifier`   | Remove a monitored account from a channel                |
| `/list users`        | List monitored accounts configured in the current server |
| `/sync`              | Legacy env-session sync helper                           |
| `/customize message` | Customize the notification message format                |

<details> <summary><strong>'/add notifier' parameters</strong></summary> <br>

| Parameter      | Type            | Description                                |
| -------------- | --------------- | ------------------------------------------ |
| `username`     | string          | Twitter/X username to monitor              |
| `channel`      | Discord channel | Channel where notifications will be sent   |
| `mention`      | Discord role    | Role to mention when sending notifications |
| `type`         | string          | Enable or disable retweets and quotes      |
| `media_type`   | string          | Filter by media-only or include all tweets |
| `account_used` | string          | Legacy Twitter client alias used for monitoring   |

</details>
<details> <summary><strong>'/remove notifier' parameters</strong></summary> <br>

| Parameter  | Type            | Description                               |
| ---------- | --------------- | ----------------------------------------- |
| `channel`  | Discord channel | Channel currently receiving notifications |
| `username` | string          | Twitter/X username to stop monitoring     |

</details>
<details> <summary><strong>'/list users' parameters</strong></summary> <br>

| Parameter | Type              | Description                    |
| --------- | ----------------- | ------------------------------ |
| `account` | string (optional) | Filter by Twitter client alias |
| `channel` | string (optional) | Filter by channel              |

</details>
<details> <summary><strong>'/customize message' parameters</strong></summary> 

| Parameter  | Type            | Description                        |
| ---------- | --------------- | ---------------------------------- |
| `channel`  | Discord channel | Channel for the customized message |
| `username` | string          | Twitter/X username to customize    |
| `default`  | boolean         | Revert to default message format   |

<br>

Supported variables for message formatting:

- `{action}` — tweeted, retweeted, or quoted
- `{author}` — display name of the poster
- `{mention}` — configured role mention
- `{url}` — link to the tweet

</details>

## ⚙️ Configuration
### Environment Variables

```
BOT_TOKEN=YourDiscordBotToken
DATA_PATH=./data
DISCORD_CLIENT_ID=YourDiscordClientId
DISCORD_CLIENT_SECRET=YourDiscordClientSecret
DISCORD_REDIRECT_URI=http://localhost:8000/dashboard/callback
DASHBOARD_BASE_URL=https://app.tweeticcini.com
DASHBOARD_SESSION_SECRET=YourLongRandomSessionSecret
TWITTER_SESSION_SECRET=YourLongRandomSessionSecret
STRIPE_PUBLISHABLE_KEY=pk_test_replace_me
STRIPE_SECRET_KEY=sk_test_replace_me
STRIPE_WEBHOOK_SECRET=whsec_replace_me
STRIPE_PRICE_ID_PRO=price_replace_me
```

Optional fallback only:

`TWITTER_TOKEN=Account1:token1,Account2:token2`

The current recommended flow is:
- connect Twitter/X sessions from the dashboard
- store them encrypted with `TWITTER_SESSION_SECRET`
- assign monitors to those connected sessions per server

Local vs production reminders:
- local dashboard OAuth should use `http://localhost:8000/dashboard/callback`
- production OAuth should use your real dashboard domain callback URL
- set `DASHBOARD_BASE_URL` to your public dashboard origin so the `/dashboard` slash command opens the public site instead of localhost
- `TWITTER_SESSION_SECRET` should be set anywhere the dashboard or bot will read stored server sessions
- Stripe test keys and live keys must never be mixed with the wrong `price_...` or webhook secret
- the production bot and dashboard should share the same `DATA_PATH` target so billing, dashboard, and runtime changes land in one database

### Key Runtime Settings (configs.yml)

Important production parameters:
- `tweets_check_period`
- `tweets_updater_retry_delay`
- `tasks_monitor_check_period`
- `auth_max_attempts`
- embed configuration
- keyword filtering rules
- `force_everyone_default`
- `keywords_triggering_everyone`
- `keywords_excluded`

> Avoid setting polling intervals too low to prevent rate limiting.

## 🖥 Dashboard

The dashboard supports server-scoped monitor management, Twitter/X session connection, alert rules, appearance overrides, billing scaffolding, and Discord OAuth login.

Run it locally with:

```bash
python3 -m uvicorn src.dashboard_api.app:app --host 0.0.0.0 --port 8000
```

Then open:

- `http://localhost:8000/dashboard`

Current dashboard scope:
- guild overview and runtime health
- connected Twitter/X sessions per server
- monitor management and session assignment
- source-specific alert rules
- appearance overrides
- billing and entitlement testing
- Discord OAuth server selection

One-time legacy keyword migration for already-configured servers can be run locally with:

```bash
python3 scripts/import_legacy_alert_rules.py
```

### Stripe Billing Setup

The billing page can create Stripe Checkout sessions, open the Stripe customer portal, and accept Stripe webhooks once these env vars are configured:

- `STRIPE_PUBLISHABLE_KEY`
- `STRIPE_SECRET_KEY`
- `STRIPE_WEBHOOK_SECRET`
- `STRIPE_PRICE_ID_PRO`

Recommended webhook events:

- `checkout.session.completed`
- `customer.subscription.updated`
- `customer.subscription.deleted`

Webhook endpoint:

- `POST /billing/webhook`

For local testing, Stripe must reach your machine through a public tunnel such as Cloudflare Tunnel or ngrok. For production, point Stripe directly at your real dashboard domain.

### Domain and DNS Notes

Current intended live layout:

- `tweeticcini.com` -> public marketing site on Netlify
- `app.tweeticcini.com` -> dashboard on the Pi through Cloudflare Tunnel

Real-world setup flow that worked:

1. Buy the domain at the registrar.
2. Add the domain to Cloudflare using the normal domain onboarding flow.
3. Let Cloudflare import the existing DNS records from the registrar.
4. Update the registrar nameservers to the two Cloudflare nameservers.
5. Wait for Cloudflare to show the domain as active.
6. In Netlify, add `tweeticcini.com` as the primary custom domain and `www.tweeticcini.com` as a redirecting alias.
7. Keep DNS managed by Cloudflare, not Netlify.

Cloudflare account note:

- this setup currently uses Cloudflare sign-in through GitHub

Important distinction:

- registrar nameservers should point to Cloudflare
- Netlify should be added as DNS records inside Cloudflare
- do not switch the registrar nameservers to Netlify DNS

For the public site in Cloudflare DNS:

- keep the existing MX and TXT records unless email or forwarding is intentionally being removed
- remove the old Porkbun web/parking records once the new records are ready
- use Netlify-directed records for the site hostnames

Netlify currently recommends:

- apex/root `tweeticcini.com` -> `apex-loadbalancer.netlify.com`
- `www.tweeticcini.com` -> `tweeticcini.netlify.app`

While verifying with Netlify:

- keep the Netlify records as `DNS only` in Cloudflare
- let Netlify finish DNS verification before worrying about extra Cloudflare proxy features

Once the dashboard subdomain is ready, point the tunnel route at the Pi dashboard service:

- `app.tweeticcini.com` -> `http://localhost:8080`

Then set:

- `DASHBOARD_BASE_URL=https://app.tweeticcini.com`
- `DISCORD_REDIRECT_URI=https://app.tweeticcini.com/dashboard/callback`

And add the same callback URL in the Discord Developer Portal.

## ✅ Production Checklist

Before switching from local/testing to a live deployment, verify:

- public site is published and shows product, pricing, support email, privacy, and terms
- Discord OAuth redirect URI is set to the live dashboard callback URL
- `DASHBOARD_SESSION_SECRET` is set to a strong random value
- `TWITTER_SESSION_SECRET` is set to a strong random value
- bot and dashboard both use the intended persistent `DATA_PATH`
- Stripe keys are all live-mode values
- `STRIPE_PRICE_ID_PRO` is the live recurring Pro price
- Stripe webhook points to your live `POST /billing/webhook` endpoint
- webhook events include:
  - `checkout.session.completed`
  - `customer.subscription.updated`
  - `customer.subscription.deleted`
- `BOT_TOKEN` is present on the live host
- at least one Twitter/X session can be connected through the dashboard for each server that should deliver alerts
- dashboard login works through Discord OAuth on the live domain
- checkout creates a Stripe session from the live Billing page
- webhook delivery updates the server entitlement without a manual override
- test alerts can be sent from the dashboard into a real Discord channel
- a newly connected Twitter/X session is picked up by the bot without a manual restart

Suggested first live rollout:

1. deploy the dashboard on a stable public URL
2. set the live Discord OAuth redirect URI
3. set live Stripe env vars and webhook
4. verify one server can subscribe and resolve to `pro`
5. only then invite broader users

## 🌐 GitHub Pages

A minimal public-facing site for billing/onboarding lives in [docs/index.html](/Users/rossc10/projects/tweeticcini/docs/index.html) with companion privacy and terms pages in [docs/privacy.html](/Users/rossc10/projects/tweeticcini/docs/privacy.html) and [docs/terms.html](/Users/rossc10/projects/tweeticcini/docs/terms.html).

To publish it with GitHub Pages, configure the repository Pages source to deploy from the `docs/` folder on your chosen branch.

# 🚀 Production Deployment

Tweeticcini is designed to run as a standalone service.

Recommended setup:
- Python 3.9+
- systemd service with automatic restart
- environment-based secret management
- persistent database storage
- structured logging

Clone and run locally:

```
git clone https://github.com/rosscm/tweeticcini.git
cd tweeticcini
python bot.py
```

### Example systemd services

Example unit files live in:

- [deploy/systemd/tweeticcini-bot.service](/Users/rossc10/projects/tweeticcini/deploy/systemd/tweeticcini-bot.service)
- [deploy/systemd/tweeticcini-dashboard.service](/Users/rossc10/projects/tweeticcini/deploy/systemd/tweeticcini-dashboard.service)

They assume:

- repo path: `/home/pi/Documents/GitHub/tweeticcini`
- venv path: `/home/pi/Documents/GitHub/tweeticcini/.venv`
- service user: `pi`
- dashboard port: `8080`
- shared env file: `/home/pi/Documents/GitHub/tweeticcini/.env`

Update those paths if your Pi layout differs.

### Install the services on the Pi

Copy the unit files into systemd:

```bash
sudo cp deploy/systemd/tweeticcini-bot.service /etc/systemd/system/
sudo cp deploy/systemd/tweeticcini-dashboard.service /etc/systemd/system/
sudo systemctl daemon-reload
```

Enable and start them:

```bash
sudo systemctl enable tweeticcini-bot
sudo systemctl enable tweeticcini-dashboard
sudo systemctl restart tweeticcini-bot
sudo systemctl restart tweeticcini-dashboard
```

Useful checks:

```bash
sudo systemctl status tweeticcini-bot
sudo systemctl status tweeticcini-dashboard
journalctl -u tweeticcini-bot -f
journalctl -u tweeticcini-dashboard -f
```

### Public dashboard stack on the Pi

For the public dashboard to stay live after reboots, all of these should be running:

- `tweeticcini-bot.service`
- `tweeticcini-dashboard.service`
- `cloudflared`

The typical flow is:

- `cloudflared` accepts public traffic for `https://app.tweeticcini.com`
- it forwards requests to `http://localhost:8080`
- `tweeticcini-dashboard.service` serves the FastAPI dashboard there
- `tweeticcini-bot.service` handles runtime polling and Discord delivery

### Optional self-healing watchdog on the Pi

If the Pi occasionally ends up in a state where the dashboard stops responding until you reboot, start with service-level recovery before full device reboots.

Tweeticcini already exposes a local health endpoint:

- `http://127.0.0.1:8080/health`

The sample watchdog in this repo:

- restarts `tweeticcini-dashboard.service` if `/health` stops responding
- restarts `cloudflared` if the dashboard still does not recover after a dashboard restart
- restarts `tweeticcini-bot.service` after repeated unhealthy bot-runtime checks

Files:

- [deploy/systemd/tweeticcini-healthcheck.sh](/Users/rossc10/projects/tweeticcini/deploy/systemd/tweeticcini-healthcheck.sh)
- [deploy/systemd/tweeticcini-healthcheck.service](/Users/rossc10/projects/tweeticcini/deploy/systemd/tweeticcini-healthcheck.service)
- [deploy/systemd/tweeticcini-healthcheck.timer](/Users/rossc10/projects/tweeticcini/deploy/systemd/tweeticcini-healthcheck.timer)

Install them on the Pi:

```bash
sudo cp deploy/systemd/tweeticcini-healthcheck.service /etc/systemd/system/
sudo cp deploy/systemd/tweeticcini-healthcheck.timer /etc/systemd/system/
sudo cp deploy/systemd/tweeticcini-healthcheck.sh /usr/local/bin/tweeticcini-healthcheck.sh
sudo chmod +x /usr/local/bin/tweeticcini-healthcheck.sh
sudo systemctl daemon-reload
sudo systemctl enable --now tweeticcini-healthcheck.timer
```

Check status:

```bash
systemctl status tweeticcini-healthcheck.timer
journalctl -u tweeticcini-healthcheck.service -f
```

This is intentionally conservative: it tries to restart only the affected service first. If you later decide you want an automatic Pi reboot after repeated failures, add that as a second stage after this lighter recovery path has had time to prove itself.

# 📜 License

This project is based on Tweetcord by Yuuzi261 and remains distributed under the MIT License.

All modifications and extensions in this repository are also distributed under the MIT License unless otherwise stated.

# ⚠️ Disclaimer

This bot interacts with Twitter/X using authenticated session tokens and third-party libraries. Users are responsible for complying with Twitter/X and Discord terms of service when deploying or distributing this software.
