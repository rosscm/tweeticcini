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
| `/add notifier`      | Add a monitored Twitter/X account to a channel           |
| `/remove notifier`   | Remove a monitored account from a channel                |
| `/list users`        | List monitored accounts configured in the current server |
| `/sync`              | Resync notifications after changing Twitter clients      |
| `/customize message` | Customize the notification message format                |

<details> <summary><strong>'/add notifier' parameters</strong></summary> <br>

| Parameter      | Type            | Description                                |
| -------------- | --------------- | ------------------------------------------ |
| `username`     | string          | Twitter/X username to monitor              |
| `channel`      | Discord channel | Channel where notifications will be sent   |
| `mention`      | Discord role    | Role to mention when sending notifications |
| `type`         | string          | Enable or disable retweets and quotes      |
| `media_type`   | string          | Filter by media-only or include all tweets |
| `account_used` | string          | Twitter client alias used for monitoring   |

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
TWITTER_TOKEN=ClientAlias:AuthToken
DATA_PATH=./data
DISCORD_CLIENT_ID=YourDiscordClientId
DISCORD_CLIENT_SECRET=YourDiscordClientSecret
DISCORD_REDIRECT_URI=http://localhost:8000/dashboard/callback
DASHBOARD_SESSION_SECRET=YourLongRandomSessionSecret
STRIPE_PUBLISHABLE_KEY=pk_test_replace_me
STRIPE_SECRET_KEY=sk_test_replace_me
STRIPE_WEBHOOK_SECRET=whsec_replace_me
STRIPE_PRICE_ID_PRO=price_replace_me
```

Multiple Twitter accounts can be defined by separating entries with commas.

Example:

`TWITTER_TOKEN=Account1:token1,Account2:token2`

Local vs production reminders:
- local dashboard OAuth should use `http://localhost:8000/dashboard/callback`
- production OAuth should use your real dashboard domain callback URL
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

The dashboard supports guild-scoped source management, alert rules, appearance overrides, billing scaffolding, and Discord OAuth login.

Run it locally with:

```bash
python3 -m uvicorn src.dashboard_api.app:app --host 0.0.0.0 --port 8000
```

Then open:

- `http://localhost:8000/dashboard`

Current dashboard scope:
- guild overview and runtime health
- tracked source management
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

## ✅ Production Checklist

Before switching from local/testing to a live deployment, verify:

- public site is published and shows product, pricing, support email, privacy, and terms
- Discord OAuth redirect URI is set to the live dashboard callback URL
- `DASHBOARD_SESSION_SECRET` is set to a strong random value
- bot and dashboard both use the intended persistent `DATA_PATH`
- Stripe keys are all live-mode values
- `STRIPE_PRICE_ID_PRO` is the live recurring Pro price
- Stripe webhook points to your live `POST /billing/webhook` endpoint
- webhook events include:
  - `checkout.session.completed`
  - `customer.subscription.updated`
  - `customer.subscription.deleted`
- `BOT_TOKEN` and `TWITTER_TOKEN` values are present on the live host
- dashboard login works through Discord OAuth on the live domain
- checkout creates a Stripe session from the live Billing page
- webhook delivery updates the server entitlement without a manual override
- test alerts can be sent from the dashboard into a real Discord channel

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

# 📜 License

This project is based on Tweetcord by Yuuzi261 and remains distributed under the MIT License.

All modifications and extensions in this repository are also distributed under the MIT License unless otherwise stated.

# ⚠️ Disclaimer

This bot interacts with Twitter/X using authenticated session tokens and third-party libraries. Users are responsible for complying with Twitter/X and Discord terms of service when deploying or distributing this software.
