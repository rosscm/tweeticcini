# Production Hardening Rollout

## Scope

This change set hardens dashboard authorization, blocks unsafe manual billing overrides, makes notification delivery durable across Discord failures, moves one-time bot startup out of `on_ready`, tightens Twitter session-file permissions, and adds focused tests plus CI.

## New environment variables

- `APP_ENV`
  - Use `production` in production.
  - Default is treated as `production`.
- `ALLOW_UNAUTHENTICATED_DASHBOARD`
  - Default is disabled.
  - Only enable in explicit local development or test environments.
- `DASHBOARD_INTERNAL_ADMIN_SECRET`
  - Required only if you want manual plan or entitlement overrides through the dashboard API.
- `DELIVERY_OUTBOX_RETRY_BASE_SECONDS`
  - Optional. Default `30`.
- `DELIVERY_OUTBOX_RETRY_MAX_SECONDS`
  - Optional. Default `900`.
- `DELIVERY_OUTBOX_MAX_ATTEMPTS`
  - Optional. Default `5`.
- `DELIVERY_OUTBOX_POLL_SECONDS`
  - Optional. Default `15`.

## Before deployment

1. Back up the SQLite database.
2. Confirm `DASHBOARD_SESSION_SECRET` is set in production.
3. Confirm Discord OAuth settings are complete in production:
   - `DISCORD_CLIENT_ID`
   - `DISCORD_CLIENT_SECRET`
   - `DISCORD_REDIRECT_URI`
4. Decide whether manual dashboard overrides should exist in production.
   - If yes, set `DASHBOARD_INTERNAL_ADMIN_SECRET`.
   - If no, leave it unset and the override routes will stay unavailable.

## Database backup

With services stopped:

```bash
cp "$DATA_PATH/tracked_accounts.db" "$DATA_PATH/tracked_accounts.db.bak.$(date +%Y%m%d-%H%M%S)"
```

If the bot is still running, prefer a SQLite online backup:

```bash
sqlite3 "$DATA_PATH/tracked_accounts.db" ".backup '$DATA_PATH/tracked_accounts.db.bak.$(date +%Y%m%d-%H%M%S)'"
```

## Deployment steps

1. Pull the new code on the `dev` branch.
2. Install dependencies from `requirements.txt`.
3. Back up the database.
4. Restart the dashboard service.
5. Restart the bot service.
6. Confirm both services start cleanly.
7. Verify:
   - dashboard login works
   - Stripe webhook endpoint still updates entitlements
   - a test monitor enqueues and delivers alerts

## Restarts required

- `tweeticcini-dashboard.service`: yes
- `tweeticcini-bot.service`: yes

## Outbox rollout notes

- Existing checkpoints in `user_client_state` and `user.lastest_tweet` are preserved.
- The migration only adds the new `delivery_outbox` table and indexes.
- No existing checkpoint values are reset or deleted.
- Historical replay is avoided because polling still starts from the existing stored checkpoint.
- Duplicate notifications during rollout are limited by the unique outbox constraint on `tweet_id + channel_id`.

## Rollback

1. Stop the bot and dashboard services.
2. Restore the pre-deploy database backup if you need to discard new outbox rows or entitlement changes.
3. Revert the code to the previous commit.
4. Reinstall the previous dependency set if needed.
5. Restart the bot and dashboard services.

The migration is additive and idempotent, so rolling code back without restoring the database is also possible if you are comfortable leaving the new table in place.

## Remaining assumptions and risks

- The durable delivery queue stores a tweet snapshot that covers the fields currently needed for message rendering and embeds.
- Permanent Discord delivery failures are classified conservatively from Discord exception types and common error text.
- Retry timing is process-local and driven by the bot service; queued rows remain durable across bot restarts.
- CI assumes Python `3.11`.
