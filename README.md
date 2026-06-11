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
SUPPORT_SERVER_URL=https://discord.gg/yourinvite
TOP_GG_VOTE_URL=https://top.gg/bot/your-bot-id/vote
DASHBOARD_SESSION_SECRET=YourLongRandomSessionSecret
TWITTER_SESSION_SECRET=YourLongRandomSessionSecret
STRIPE_PUBLISHABLE_KEY=pk_test_replace_me
STRIPE_SECRET_KEY=sk_test_replace_me
STRIPE_WEBHOOK_SECRET=whsec_replace_me
STRIPE_PRICE_ID_PLUS=price_replace_me
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
- set `SUPPORT_SERVER_URL` if you want `/about` to show a `Support Server` button alongside `Open Dashboard`
- set `TOP_GG_VOTE_URL` if you want `/about` and `/vote` to show your top.gg voting link explicitly. If this is blank, Tweeticcini will fall back to `https://top.gg/bot/<DISCORD_CLIENT_ID>/vote`
- `TWITTER_SESSION_SECRET` should be set anywhere the dashboard or bot will read stored server sessions
- Stripe test keys and live keys must never be mixed with the wrong `price_...` or webhook secret
- the production bot and dashboard should share the same `DATA_PATH` target so billing, dashboard, and runtime changes land in one database

### Key Runtime Settings (configs.yml)

Important production parameters:
- `tweets_check_period`
- `plus_tweets_check_period`
- `free_tweets_check_period`
- `tweet_cache_limit`
- `max_tweets_per_source_cycle`
- `tweets_updater_retry_delay`
- `tasks_monitor_check_period`
- `auth_max_attempts`
- embed configuration
- keyword filtering rules
- `force_everyone_default`
- `keywords_triggering_everyone`
- `keywords_excluded`

> Avoid setting polling intervals too low to prevent rate limiting.

Polling behavior:
- `tweets_check_period` is the fast/default polling cadence used for Premium plans and fallback sessions
- `plus_tweets_check_period` is the mid-tier cadence used for Plus plans
- `free_tweets_check_period` is the slower long-term cadence used for Free servers
- if `plus_tweets_check_period` is omitted, Tweeticcini falls back to `45` seconds for Plus servers
- if `free_tweets_check_period` is omitted, Tweeticcini falls back to `90` seconds for Free servers
- `tweet_cache_limit` controls how many recently fetched notification tweets are kept in memory per Twitter/X session so source tasks do not miss items between polling cycles
- `max_tweets_per_source_cycle` controls how many new tweets are sent per monitored source each cycle; set to `1` to send only the latest tweet after downtime or noisy periods while still advancing past older missed tweets

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
- `STRIPE_PRICE_ID_PLUS`
- `STRIPE_PRICE_ID_PRO`

Current public pricing expects `STRIPE_PRICE_ID_PLUS` to point at the recurring Plus $4/month price and `STRIPE_PRICE_ID_PRO` to point at the recurring Premium $6.99/month price. The app still uses the internal `pro` plan key for Premium.

Recommended webhook events:

- `checkout.session.completed`
- `customer.subscription.updated`
- `customer.subscription.deleted`

Webhook endpoint:

- `POST /billing/webhook`

For local testing, Stripe must reach your machine through a public tunnel such as Cloudflare Tunnel or ngrok. For production, point Stripe directly at your real dashboard domain.

### Domain and DNS Notes

Current intended live layout:

- `tweeticcini.com` -> public marketing site on Cloudflare Pages
- `www.tweeticcini.com` -> public marketing site on Cloudflare Pages
- `app.tweeticcini.com` -> dashboard on the Pi through Cloudflare Tunnel

Real-world setup flow that worked:

1. Buy the domain at the registrar.
2. Add the domain to Cloudflare using the normal domain onboarding flow.
3. Let Cloudflare import the existing DNS records from the registrar.
4. Update the registrar nameservers to the two Cloudflare nameservers.
5. Wait for Cloudflare to show the domain as active.
6. Create a Cloudflare Pages project for the public site and connect the repo.
7. Set the production branch to `dev` and publish the static site from the `docs/` folder.
8. Add `tweeticcini.com` and `www.tweeticcini.com` as custom domains in Cloudflare Pages.
9. Keep DNS managed by Cloudflare.

Cloudflare account note:

- this setup currently uses Cloudflare sign-in through GitHub

Important distinction:

- registrar nameservers should point to Cloudflare
- Cloudflare Pages should own the public site hostnames inside Cloudflare DNS
- do not switch the registrar nameservers away from Cloudflare

For the public site in Cloudflare DNS:

- keep the existing MX and TXT records unless email or forwarding is intentionally being removed
- remove the old Porkbun web/parking records once the new records are ready
- let Cloudflare Pages create and manage the `tweeticcini.com` and `www` site records
- keep `app.tweeticcini.com` pointed at the dashboard tunnel separately

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
- `STRIPE_PRICE_ID_PLUS` is the live recurring Plus price
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

## 🌐 Cloudflare Pages

A minimal public-facing site for billing/onboarding lives in [docs/index.html](/Users/rossc10/projects/tweeticcini/docs/index.html) with companion privacy and terms pages in [docs/privacy.html](/Users/rossc10/projects/tweeticcini/docs/privacy.html) and [docs/terms.html](/Users/rossc10/projects/tweeticcini/docs/terms.html).

It is currently deployed with Cloudflare Pages using:

- production branch: `dev`
- framework preset: `None`
- path/output directory: `docs`

### Site Asset Notes

- The Discord app banner artwork was assembled manually in Kapwing.
- The support server welcome embed was assembled in Discohook.

# 🔖 Versioning

Tweeticcini now uses a shared top-level [VERSION](/Users/rossc10/projects/tweeticcini/VERSION) file as the source of truth for release versioning. The dashboard reads from this file directly, so updating it changes the version shown in the UI after restart.

To bump the version:

```bash
python3 scripts/bump_version.py patch
python3 scripts/bump_version.py minor
python3 scripts/bump_version.py major
```

To set an explicit version:

```bash
python3 scripts/bump_version.py --set 1.2.3
```

To create a tagged release commit at the same time:

```bash
python3 scripts/release_version.py patch
python3 scripts/release_version.py minor
python3 scripts/release_version.py --set 1.2.3
git push origin dev --follow-tags
```

Typical dashboard release workflow:

1. Bump the version with `python3 scripts/bump_version.py patch` (or `minor` / `major`).
2. Commit the version bump alongside the rest of your changes.
3. Push the branch with `git push origin dev`.
4. Pull on the Pi with `git pull origin dev`.
5. Restart the dashboard with `sudo systemctl restart tweeticcini-dashboard`.
6. Verify the new `vX.Y.Z` appears in the dashboard footer.

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
