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
```

Multiple Twitter accounts can be defined by separating entries with commas.

Example:

`TWITTER_TOKEN=Account1:token1,Account2:token2`

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

## 🖥 Dashboard Prototype

An internal dashboard prototype is available for guild-scoped alert configuration.

Run it locally with:

```bash
uvicorn src.dashboard_api.app:app --host 0.0.0.0 --port 8000
```

Then open:

- `http://localhost:8000/dashboard`

Current dashboard scope:
- guild alert defaults
- source-specific alert rules
- legacy-to-guild bootstrap flow

Current limitation:
- no Discord OAuth yet; this is an internal/admin-only prototype

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
