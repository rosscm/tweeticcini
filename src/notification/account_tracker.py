import asyncio
import re
import os
from datetime import datetime, timezone, timedelta
from types import SimpleNamespace
from typing import Optional

import sqlite3
import discord
from discord.ext import commands

from src.adapters.twitter_adapter import create_twitter_session
from configs.load_configs import configs
from src.repositories.notifier_repository import (
    connect_writable,
    get_user_by_username,
    pause_notification_delivery,
    update_user_latest_tweet_for_client,
)
from src.repositories.runtime_metrics_repository import (
    increment_server_support_prompt_counter_with_cursor,
    record_client_poll_error,
    record_client_poll_success,
    record_source_delivery_error,
    record_source_delivery_success,
)
from src.repositories.delivery_outbox_repository import (
    claim_due_deliveries,
    DeliveryOutboxRecord,
    enqueue_delivery,
    fail_open_deliveries_for_destination,
    mark_delivery_failed,
    mark_delivery_retry,
    mark_delivery_success,
)
from src.services.guild_settings_service import GuildSettingsService
from src.log import setup_logger
from src.services.alert_rule_service import AlertDecision, AlertRuleService
from src.notification.display_tools import gen_embed, get_action
from src.notification.get_tweets import get_tweets
from src.notification.utils import is_match_media_type, is_match_type
from src.services.twitter_session_service import TwitterSessionService
from src.settings import get_accounts, get_db_path
from src.utils import get_lock, extract_first_line


log = setup_logger(__name__)
lock = get_lock()


def _get_top_gg_vote_url() -> Optional[str]:
    explicit_url = os.getenv('TOP_GG_VOTE_URL', '').strip()
    if explicit_url:
        return explicit_url

    client_id = os.getenv('DISCORD_CLIENT_ID', '').strip()
    if not client_id:
        return None

    return f'https://top.gg/bot/{client_id}/vote'


def _get_donation_url() -> str:
    explicit_url = os.getenv('BUY_ME_A_COFFEE_URL', '').strip()
    return explicit_url or 'https://buymeacoffee.com/pokaccini'


def _get_force_everyone_support_prompt_url() -> Optional[str]:
    return _get_top_gg_vote_url()


def _get_managed_support_prompt_default_text() -> str:
    return "Enjoying Tweeticcini? Vote on top.gg! It would make Mocha's day 💛"


def _get_support_prompt_server_ids() -> set[str]:
    raw = os.getenv('SUPPORT_PROMPT_SERVER_IDS', '').strip()
    if not raw:
        return set()
    return {server_id.strip() for server_id in raw.split(',') if server_id.strip()}


def _get_managed_support_prompt_text() -> Optional[str]:
    return os.getenv('SUPPORT_PROMPT_MANAGED_SERVER_TEXT', '').strip() or None


def _get_support_prompt_channel_overrides() -> dict[str, set[str]]:
    raw = os.getenv('SUPPORT_PROMPT_CHANNEL_OVERRIDES', '').strip()
    if not raw:
        return {}

    overrides: dict[str, set[str]] = {}
    for pair in raw.split(','):
        value = pair.strip()
        if not value or ':' not in value:
            continue
        server_id, channel_id = value.split(':', 1)
        server_id = server_id.strip()
        channel_id = channel_id.strip()
        if not server_id or not channel_id:
            continue
        overrides.setdefault(server_id, set()).add(channel_id)
    return overrides


def build_notification_message(template: str, mention: str, tweet, url: str) -> str:
    author_name = getattr(tweet.author, 'name', getattr(tweet.author, 'username', 'Unknown'))
    values = {
        'action': get_action(tweet),
        'author': author_name,
        'mention': mention,
        'url': url,
    }
    return template.format_map(values).strip()


def build_headline_notification_message(mention: str, text: str, url: str) -> str:
    headline = extract_first_line(text)
    return f"{mention}{headline}: {url}" if headline else f"{mention}{url}"


def _tweet_snapshot(tweet) -> dict[str, object]:
    author = getattr(tweet, 'author', None)
    media = []
    for item in getattr(tweet, 'media', []) or []:
        media.append(
            {
                'type': getattr(item, 'type', None),
                'media_url_https': getattr(item, 'media_url_https', None),
                'expanded_url': getattr(item, 'expanded_url', None),
            }
        )
    return {
        'id': str(getattr(tweet, 'id', None) or getattr(tweet, 'tweet_id', None) or getattr(tweet, 'id_str', None) or getattr(tweet, 'url', '')),
        'url': getattr(tweet, 'url', ''),
        'text': (
            getattr(tweet, 'rawContent', None)
            or getattr(tweet, 'content', None)
            or getattr(tweet, 'text', None)
            or getattr(tweet, 'full_text', None)
            or ''
        ),
        'created_on': getattr(tweet, 'created_on', None).isoformat() if getattr(tweet, 'created_on', None) else None,
        'is_retweet': bool(getattr(tweet, 'is_retweet', False)),
        'is_quoted': bool(getattr(tweet, 'is_quoted', False)),
        'author': {
            'name': getattr(author, 'name', ''),
            'username': getattr(author, 'username', ''),
            'profile_image_url_https': getattr(author, 'profile_image_url_https', ''),
        },
        'media': media,
    }


def _tweet_from_snapshot(snapshot: dict[str, object]):
    author = snapshot.get('author') or {}
    created_on = snapshot.get('created_on')
    media = [
        SimpleNamespace(
            type=item.get('type'),
            media_url_https=item.get('media_url_https'),
            expanded_url=item.get('expanded_url'),
        )
        for item in (snapshot.get('media') or [])
    ]
    return SimpleNamespace(
        id=snapshot.get('id'),
        url=snapshot.get('url'),
        text=snapshot.get('text') or '',
        rawContent=snapshot.get('text') or '',
        content=snapshot.get('text') or '',
        full_text=snapshot.get('text') or '',
        created_on=datetime.fromisoformat(created_on) if created_on else datetime.now(timezone.utc),
        is_retweet=bool(snapshot.get('is_retweet')),
        is_quoted=bool(snapshot.get('is_quoted')),
        media=media,
        author=SimpleNamespace(
            name=author.get('name', ''),
            username=author.get('username', ''),
            profile_image_url_https=author.get('profile_image_url_https', ''),
        ),
    )

class AccountTracker():
    _instance = None

    def __new__(cls, bot: commands.Bot):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self, bot: commands.Bot):
        if self._initialized:
            return
        self._initialized = True
        self.bot = bot
        self.accounts_data = get_accounts()
        self.db_path = get_db_path()
        self.alert_rule_service = AlertRuleService(self.db_path)
        self.guild_settings_service = GuildSettingsService(self.db_path)
        self.twitter_session_service = TwitterSessionService(self.db_path)
        self.tweets = {}
        self.poll_error_states: dict[str, str] = {}
        self.client_poll_intervals: dict[str, int] = {}
        self.auth_retry_after: dict[str, datetime] = {}
        self.missing_session_tasks: set[str] = set()
        self.tasksMonitorLogAt = datetime.now(timezone.utc) - timedelta(hours=configs['tasks_monitor_log_period'])
        self.support_prompt_server_ids = _get_support_prompt_server_ids()
        self.support_prompt_channel_overrides = _get_support_prompt_channel_overrides()
        self.managed_support_prompt_text = _get_managed_support_prompt_text()
        self.support_prompt_threshold = 20
        self.tweet_cache_limit = max(int(configs.get('tweet_cache_limit', 500) or 500), 1)
        self.max_tweets_per_source_cycle = max(int(configs.get('max_tweets_per_source_cycle', 1) or 1), 1)
        self.max_tweet_backfill_age_minutes = max(int(configs.get('max_tweet_backfill_age_minutes', 15) or 15), 1)
        self.db_lock_retry_attempts = max(int(configs.get('db_lock_retry_attempts', 3) or 3), 1)
        self.db_lock_retry_base_seconds = max(float(configs.get('db_lock_retry_base_seconds', 0.25) or 0.25), 0.05)
        self.delivery_outbox_retry_base_seconds = max(int(os.getenv('DELIVERY_OUTBOX_RETRY_BASE_SECONDS', '30') or 30), 1)
        self.delivery_outbox_retry_max_seconds = max(int(os.getenv('DELIVERY_OUTBOX_RETRY_MAX_SECONDS', '900') or 900), 1)
        self.delivery_outbox_max_attempts = max(int(os.getenv('DELIVERY_OUTBOX_MAX_ATTEMPTS', '5') or 5), 1)
        self.delivery_outbox_poll_seconds = max(int(os.getenv('DELIVERY_OUTBOX_POLL_SECONDS', '15') or 15), 1)
        self.delivery_outbox_lease_seconds = max(int(os.getenv('DELIVERY_OUTBOX_LEASE_SECONDS', '120') or 120), 30)
        bot.loop.create_task(self.setup_tasks())

    def _tweet_cache_key(self, tweet) -> str:
        for attr in ('id', 'tweet_id', 'id_str', 'url'):
            value = getattr(tweet, attr, None)
            if value:
                return str(value)
        author = getattr(getattr(tweet, 'author', None), 'username', '')
        text = (
            getattr(tweet, 'rawContent', None)
            or getattr(tweet, 'content', None)
            or getattr(tweet, 'text', None)
            or getattr(tweet, 'full_text', None)
            or ''
        )
        return f"{author}:{getattr(tweet, 'created_on', '')}:{text}"

    def _merge_tweet_cache(self, existing_tweets: list, fetched_tweets: list) -> list:
        merged = {self._tweet_cache_key(tweet): tweet for tweet in existing_tweets}
        for tweet in fetched_tweets:
            merged[self._tweet_cache_key(tweet)] = tweet
        return sorted(merged.values(), key=lambda tweet: tweet.created_on, reverse=True)[:self.tweet_cache_limit]

    @staticmethod
    def _base_poll_interval() -> int:
        return int(configs['tweets_check_period'])

    @classmethod
    def _free_poll_interval(cls) -> int:
        configured = int(configs.get('free_tweets_check_period', 120))
        return max(configured, cls._base_poll_interval())

    @classmethod
    def _plus_poll_interval(cls) -> int:
        configured = int(configs.get('plus_tweets_check_period', 45))
        return max(configured, cls._base_poll_interval())

    def _get_client_poll_interval(self, client_used: str) -> int:
        return self.client_poll_intervals.get(client_used, self._base_poll_interval())

    async def _refresh_client_poll_intervals(self) -> None:
        intervals: dict[str, int] = {}
        for session in await self.twitter_session_service.list_all_active_session_records():
            presentation = await self.guild_settings_service.get_presentation_view(session.server_id)
            if presentation.plan == 'free':
                interval = self._free_poll_interval()
            elif presentation.plan == 'plus':
                interval = self._plus_poll_interval()
            else:
                interval = self._base_poll_interval()
            intervals[session.client_key] = interval
        self.client_poll_intervals = intervals

    async def _load_available_accounts(self, required_clients: Optional[set[str]] = None) -> dict[str, str]:
        accounts = {
            account_name: {
                'mode': 'auth_token',
                'credential': account_token,
            }
            for account_name, account_token in get_accounts().items()
        }
        try:
            server_session_accounts = {
                record.client_key: {
                    'mode': record.auth_mode,
                    'credential': record.credential,
                }
                for record in await self.twitter_session_service.list_all_active_auth_records()
            }
        except Exception as exc:
            log.error(f'failed to load stored Twitter/X sessions: {exc}')
            server_session_accounts = {}
        combined_accounts = {**accounts, **server_session_accounts}
        if required_clients is None:
            return combined_accounts
        return {
            client_key: client_config
            for client_key, client_config in combined_accounts.items()
            if client_key in required_clients
        }

    async def _authenticate_account(self, account_name: str, account_config: dict[str, str]):
        app = create_twitter_session(account_name)
        max_attempts = configs['auth_max_attempts']
        for attempt in range(max_attempts):
            try:
                if account_config['mode'] == 'session_json':
                    self.twitter_session_service._write_session_file(account_name, account_config['credential'])
                    await app.connect()
                else:
                    await app.load_auth_token(account_config['credential'])
                return app
            except Exception:
                log.error(f"Authentication failed for account: {account_name} [Attempt {attempt + 1}/{max_attempts}]")
                if attempt < max_attempts - 1:
                    await asyncio.sleep(5)
                else:
                    log.error(f"Persistent authentication failure for account {account_name}")
                    raise

    async def _ensure_twitter_updaters(self, exit_on_failure: bool = False) -> None:
        required_clients = {client_used for _, client_used in await self.twitter_session_service_pairs()}
        latest_accounts = await self._load_available_accounts(required_clients)
        await self._refresh_client_poll_intervals()
        available_accounts: dict[str, dict[str, str]] = {}
        now = datetime.now(timezone.utc)
        cooldown_minutes = max(int(configs.get('auth_retry_cooldown_minutes', 15) or 15), 1)
        for account_name in latest_accounts.keys():
            self.tweets.setdefault(account_name, [])

        active_task_names = {task.get_name() for task in asyncio.all_tasks()}
        for account_name, account_config in latest_accounts.items():
            if f'TweetsUpdater_{account_name}' in active_task_names:
                available_accounts[account_name] = account_config
                continue
            retry_after = self.auth_retry_after.get(account_name)
            if retry_after is not None and now < retry_after:
                continue
            try:
                app = await self._authenticate_account(account_name, account_config)
                self.bot.loop.create_task(self.tweetsUpdater(app)).set_name(f'TweetsUpdater_{account_name}')
                log.info(f'loaded Twitter/X session {account_name} without bot restart')
                available_accounts[account_name] = account_config
                self.auth_retry_after.pop(account_name, None)
            except Exception:
                # Never let one bad session credential take the whole bot offline.
                self.auth_retry_after[account_name] = now + timedelta(minutes=cooldown_minutes)
                log.error(
                    f'skipping unavailable Twitter/X session {account_name} until it can authenticate successfully'
                )
                log.info(
                    f'next authentication retry for {account_name} in {cooldown_minutes} minute(s)'
                )

        # Keep monitoring focused on sessions that are currently running/healthy.
        self.accounts_data = available_accounts

        for task in asyncio.all_tasks():
            task_name = task.get_name()
            if not task_name.startswith('TweetsUpdater_'):
                continue
            account_name = task_name.split('_', 1)[1]
            if account_name in latest_accounts:
                continue
            try:
                task.cancel()
                log.info(f'removed tweets updater for inactive session {account_name}')
            except Exception as exc:
                log.warning(f'failed to remove tweets updater for {account_name}: {exc}')

    async def setup_tasks(self):
        await self._ensure_twitter_updaters(exit_on_failure=True)

        if not self.accounts_data:
            log.warning('no Twitter/X sessions are configured; tracked sources cannot poll until a session is connected')

        usernames_and_clients = await self.twitter_session_service_pairs()

        active_task_names = {task.get_name() for task in asyncio.all_tasks()}
        for username, client_used in usernames_and_clients:
            if client_used not in self.tweets:
                log.warning(f'skipping task for {username}; Twitter/X session {client_used} is not available')
                continue
            task_name = self._task_name(username, client_used)
            if task_name in active_task_names:
                continue
            self.bot.loop.create_task(self.notification(username, client_used)).set_name(task_name)
            active_task_names.add(task_name)
        if 'DeliveryOutboxProcessor' not in active_task_names:
            self.bot.loop.create_task(self.deliveryOutboxProcessor()).set_name('DeliveryOutboxProcessor')
        if 'TasksMonitor' not in active_task_names:
            self.bot.loop.create_task(self.tasksMonitor()).set_name('TasksMonitor')

    async def notification(self, username: str, client_used: str):
        while True:
            await asyncio.sleep(
                self._get_client_poll_interval(client_used)
            )

            try:
                latest_tweets = await get_tweets(
                    self.tweets[client_used],
                    username,
                    client_used,
                )

                if not latest_tweets:
                    continue

                log.debug(
                    f'found {len(latest_tweets)} new tweet(s) '
                    f'for {username} using {client_used}'
                )

                (
                    expired_tweets,
                    tweets_to_process,
                    deferred_tweets,
                ) = self._select_tweets_for_cycle(latest_tweets)

                if expired_tweets:
                    log.info(
                        f'skipping {len(expired_tweets)} stale tweet(s) '
                        f'for {username} using {client_used}; '
                        f'older than '
                        f'{self.max_tweet_backfill_age_minutes} minute(s)'
                    )

                if deferred_tweets:
                    log.info(
                        f'processing oldest '
                        f'{len(tweets_to_process)} recent tweet(s) '
                        f'for {username} using {client_used}; '
                        f'retaining {len(deferred_tweets)} newer tweet(s) '
                        f'for the next cycle'
                    )

                if tweets_to_process:
                    checkpoint_created_on = (
                        tweets_to_process[-1].created_on
                    )
                elif expired_tweets:
                    # All available tweets are too old. Move the checkpoint
                    # past them without creating stale alerts.
                    checkpoint_created_on = (
                        expired_tweets[-1].created_on
                    )
                else:
                    continue

                await self._enqueue_new_tweet_deliveries(
                    username,
                    client_used,
                    tweets_to_process,
                    checkpoint_created_on,
                )

            except asyncio.CancelledError:
                raise

            except sqlite3.OperationalError as exc:
                if 'database is locked' in str(exc).lower():
                    log.warning(
                        f'database remained locked while processing '
                        f'{username} using {client_used}; '
                        'checkpoint left unchanged for the next cycle'
                    )
                    continue

                log.exception(
                    f'SQLite failure while processing '
                    f'{username} using {client_used}'
                )

            except Exception:
                log.exception(
                    f'notification task error for '
                    f'{username} using {client_used}; '
                    'task will continue next cycle'
                )

    async def _enqueue_new_tweet_deliveries(
        self,
        username: str,
        client_used: str,
        tweets_to_process: list,
        checkpoint_created_on,
    ) -> None:
        for attempt in range(1, self.db_lock_retry_attempts + 1):
            try:
                await self._enqueue_new_tweet_deliveries_once(
                    username,
                    client_used,
                    tweets_to_process,
                    checkpoint_created_on,
                )
                return

            except sqlite3.OperationalError as exc:
                is_locked = 'database is locked' in str(exc).lower()

                if not is_locked:
                    raise

                if attempt >= self.db_lock_retry_attempts:
                    raise

                delay = min(
                    self.db_lock_retry_base_seconds
                    * (2 ** (attempt - 1)),
                    2.0,
                )

                log.warning(
                    f'database locked while enqueueing tweets for '
                    f'{username} using {client_used}; '
                    f'retrying in {delay:.2f}s '
                    f'({attempt}/{self.db_lock_retry_attempts})'
                )

                await asyncio.sleep(delay)


    async def _enqueue_new_tweet_deliveries_once(
        self,
        username: str,
        client_used: str,
        tweets_to_process: list,
        checkpoint_created_on,
    ) -> None:
        # Serialize these short enqueue/checkpoint transactions inside
        # this bot process.
        async with lock:
            async with connect_writable(self.db_path) as db:
                try:
                    # Acquire the write lock before evaluating destinations.
                    await db.execute('BEGIN IMMEDIATE')

                    async with db.cursor() as cursor:
                        user = await get_user_by_username(
                            cursor,
                            username,
                        )

                        if user is None:
                            await db.rollback()
                            return

                        await cursor.execute(
                            '''
                            SELECT notification.*, channel.server_id
                            FROM notification
                            JOIN channel
                                ON channel.id = notification.channel_id
                            WHERE notification.user_id = ?
                            AND notification.client_used = ?
                            AND notification.enabled = 1

                            AND COALESCE(notification.delivery_paused, 0) = 0
                            ''',
                            (user['id'], client_used),
                        )
                        notifications = await cursor.fetchall()

                        now = datetime.now(timezone.utc).isoformat(
                            timespec='seconds'
                        )

                        for tweet in tweets_to_process:
                            await self._enqueue_tweet_deliveries(
                                cursor,
                                user,
                                username,
                                client_used,
                                tweet,
                                notifications,
                                now,
                            )

                        await update_user_latest_tweet_for_client(
                            cursor,
                            username,
                            client_used,
                            str(checkpoint_created_on),
                        )

                    await db.commit()

                except Exception:
                    await db.rollback()
                    raise

    async def _enqueue_tweet_deliveries(self, cursor, user, username: str, client_used: str, tweet, notifications, created_at: str) -> None:
        log.debug(f'found {len(notifications)} notification target(s) for {username} using {client_used}')
        for data in notifications:
            matches_type = is_match_type(tweet, data['enable_type'])
            matches_media = is_match_media_type(tweet, data['enable_media_type'])
            if not matches_type or not matches_media:
                log.debug(
                    f"skipping {username} delivery to {data['channel_id']} using {client_used}: "
                    f"type_match={matches_type} media_match={matches_media}"
                )
                continue

            server_id = str(data['server_id'])
            presentation = await self.guild_settings_service.get_presentation_view(server_id)
            if presentation.plan == 'free' and presentation.compliance.is_non_compliant:
                log.debug(
                    f"skipping delivery for guild {server_id}: "
                    f"free-plan compliance required ({', '.join(presentation.compliance.reason_labels)})"
                )
                continue

            text = (
                getattr(tweet, 'rawContent', None)
                or getattr(tweet, 'content', None)
                or getattr(tweet, 'text', None)
                or getattr(tweet, 'full_text', None)
                or ''
            )
            preview = re.sub(r'\s+', ' ', text).strip()
            if len(preview) > 140:
                preview = f"{preview[:137]}..."
            log.debug(f"new tweet from {username}: {preview or '[no text]'}")

            if presentation.features.max_rules > 0:
                alert_decision = await self.alert_rule_service.resolve_alert_decision(
                    server_id=server_id,
                    channel_id=str(data['channel_id']),
                    source_username=username,
                    text=text,
                )
            else:
                alert_decision = AlertDecision(False, False)
            if alert_decision.should_force_everyone and not presentation.features.can_use_everyone_escalation:
                continue
            if alert_decision.should_exclude:
                continue

            mention = "@everyone " if alert_decision.should_force_everyone else (f"<@&{data['role_id']}> " if data['role_id'] else '')
            url = re.sub('twitter', presentation.effective.fx_domain_name, tweet.url) if presentation.effective.embed_type == 'fx_twitter' else tweet.url
            custom_template = data['customized_msg']
            default_template = presentation.effective.default_message
            use_headline_message_override = data['use_headline_message_override']
            effective_use_headline_message = (
                presentation.effective.use_headline_message
                if use_headline_message_override is None
                else bool(use_headline_message_override)
            )

            if custom_template:
                try:
                    msg = build_notification_message(custom_template, mention, tweet, url)
                except KeyError as exc:
                    log.warning(f'invalid message template placeholder {exc} for {username}, falling back to headline message')
                    msg = build_headline_notification_message(mention, text, url)
            elif effective_use_headline_message:
                msg = build_headline_notification_message(mention, text, url)
            else:
                try:
                    msg = build_notification_message(default_template, mention, tweet, url)
                except KeyError as exc:
                    log.warning(f'invalid default message template placeholder {exc} for {username}, falling back to headline message')
                    msg = build_headline_notification_message(mention, text, url)
            if not msg:
                msg = build_headline_notification_message(mention, text, url)

            support_prompt_text = None
            support_prompt_url = None
            if self._should_include_force_everyone_support_footer(server_id, bool(alert_decision.should_force_everyone)):
                support_prompt_url = self._get_support_prompt_url(server_id)
                if support_prompt_url:
                    support_prompt_text = self._get_support_prompt_text(server_id)
            elif await self._should_include_support_footer(cursor, server_id, presentation.plan, str(data['channel_id'])):
                support_prompt_text = self._get_support_prompt_text(server_id)
                support_prompt_url = self._get_support_prompt_url(server_id)
                if not support_prompt_url:
                    support_prompt_text = None

            payload = {
                'tweet': _tweet_snapshot(tweet),
                'support_prompt_text': support_prompt_text,
                'support_prompt_url': support_prompt_url,
            }
            tweet_id = payload['tweet']['id'] or self._tweet_cache_key(tweet)
            await enqueue_delivery(
                cursor,
                tweet_id=str(tweet_id),
                source_user_id=str(user['id']),
                source_username=username,
                client_used=client_used,
                server_id=server_id,
                channel_id=str(data['channel_id']),
                message_content=msg,
                payload=payload,
                created_at=created_at,
                matched_rule_name=alert_decision.matched_rule_name,
            )

    async def process_delivery_outbox(self, limit: int = 100) -> None:
        due_at = datetime.now(timezone.utc).isoformat(timespec='seconds')
        lease_expires_at = (datetime.now(timezone.utc) + timedelta(seconds=self.delivery_outbox_lease_seconds)).isoformat(timespec='seconds')
        for delivery in await claim_due_deliveries(self.db_path, due_at, lease_expires_at=lease_expires_at, limit=limit):
            await self._deliver_outbox_record(delivery)

    async def _deliver_outbox_record(self, delivery: DeliveryOutboxRecord) -> None:
        attempted_at = datetime.now(timezone.utc)
        try:
            channel = self.bot.get_channel(int(delivery.channel_id))
            if channel is None:
                channel = await self.bot.fetch_channel(int(delivery.channel_id))
            existing_message = await self._find_existing_delivery_message(channel, delivery)
            if existing_message is not None:
                delivered_at = attempted_at.isoformat(timespec='seconds')
                await mark_delivery_success(self.db_path, delivery.id, str(delivery.lease_token or ''), delivered_at)
                await record_source_delivery_success(
                    self.db_path,
                    delivery.server_id,
                    delivery.source_username,
                    delivery.channel_id,
                    str(delivery.payload['tweet'].get('url') or ''),
                    delivery.matched_rule_name,
                    delivered_at,
                )
                return
            presentation = await self.guild_settings_service.get_presentation_view(delivery.server_id)
            tweet = _tweet_from_snapshot(delivery.payload['tweet'])
            view = self._build_delivery_view(tweet, presentation)
            support_prompt_text = delivery.payload.get('support_prompt_text')
            support_prompt_url = delivery.payload.get('support_prompt_url')
            nonce = self._delivery_nonce(delivery)

            if presentation.effective.embed_type == 'fx_twitter':
                fx_embeds = []
                if support_prompt_url:
                    fx_embeds.append(
                        discord.Embed(
                            description=f'{support_prompt_text}\n{support_prompt_url}',
                            color=0xF6C453,
                        )
                    )
                send_kwargs = {'content': delivery.message_content, 'view': view, 'nonce': nonce}
                if fx_embeds:
                    send_kwargs['embeds'] = fx_embeds
                await channel.send(**send_kwargs)
            else:
                footer = 'twitter.png' if presentation.effective.built_in_legacy_logo else 'x.png'
                file = discord.File(f'images/{footer}', filename='footer.png')
                embeds = await gen_embed(
                    tweet,
                    use_fx_image=presentation.effective.built_in_fx_image,
                    use_legacy_logo=presentation.effective.built_in_legacy_logo,
                )
                if support_prompt_url:
                    embeds.append(
                        discord.Embed(
                            description=f'{support_prompt_text}\n{support_prompt_url}',
                            color=0xF6C453,
                        )
                    )
                await channel.send(content=delivery.message_content, file=file, embeds=embeds, view=view, nonce=nonce)

            delivered_at = attempted_at.isoformat(timespec='seconds')
            await mark_delivery_success(self.db_path, delivery.id, str(delivery.lease_token or ''), delivered_at)
            await record_source_delivery_success(
                self.db_path,
                delivery.server_id,
                delivery.source_username,
                delivery.channel_id,
                str(delivery.payload['tweet'].get('url') or ''),
                delivery.matched_rule_name,
                delivered_at,
            )
        except Exception as exc:
            error_text = str(exc)[:500]
            attempted_text = attempted_at.isoformat(timespec='seconds')
            await record_source_delivery_error(
                self.db_path,
                delivery.server_id,
                delivery.source_username,
                delivery.channel_id,
                error_text,
                attempted_text,
            )
            pause_reason = self._delivery_pause_reason(exc)
            if pause_reason is not None:
                await mark_delivery_failed(
                    self.db_path,
                    delivery.id,
                    str(delivery.lease_token or ''),
                    attempted_at=attempted_text,
                    last_error=error_text,
                )
                newly_paused = await pause_notification_delivery(
                    self.db_path,
                    delivery.source_username,
                    delivery.channel_id,
                    pause_reason,
                    attempted_text,
                )
                closed_count = (
                    await fail_open_deliveries_for_destination(
                        self.db_path,
                        delivery.source_username,
                        delivery.channel_id,
                        error_text,
                    )
                )
                if newly_paused:
                    log.warning(
                        f'paused delivery for '
                        f'{delivery.source_username} in channel '
                        f'{delivery.channel_id}: {pause_reason}; '
                        f'closed {closed_count} queued delivery row(s)'
                    )
                return

            if self._is_permanent_delivery_error(exc):
                await mark_delivery_failed(
                    self.db_path,
                    delivery.id,
                    str(delivery.lease_token or ''),
                    attempted_at=attempted_text,
                    last_error=error_text,
                )
                log.warning(
                    f'permanent one-message delivery failure for '
                    f'{delivery.source_username} in channel '
                    f'{delivery.channel_id}: {error_text}'
                )
                return
            if delivery.attempt_count + 1 >= self.delivery_outbox_max_attempts:
                await mark_delivery_failed(self.db_path, delivery.id, str(delivery.lease_token or ''), attempted_at=attempted_text, last_error=error_text)
                log.warning(f'exhausted delivery retries for {delivery.source_username} in channel {delivery.channel_id}: {error_text}')
                return

            next_attempt_at = (
                attempted_at + timedelta(seconds=self._retry_delay_seconds(delivery.attempt_count + 1))
            ).isoformat(timespec='seconds')
            await mark_delivery_retry(
                self.db_path,
                delivery.id,
                str(delivery.lease_token or ''),
                attempted_at=attempted_text,
                next_attempt_at=next_attempt_at,
                last_error=error_text,
            )
            log.warning(f'temporary delivery failure for {delivery.source_username} in channel {delivery.channel_id}: {error_text}')

    async def _find_existing_delivery_message(self, channel, delivery: DeliveryOutboxRecord):
        history = getattr(channel, 'history', None)
        if history is None:
            return None
        expected_nonce = self._delivery_nonce(delivery)
        bot_user_id = getattr(getattr(self.bot, 'user', None), 'id', None)
        async for message in history(limit=25):
            if getattr(message, 'nonce', None) != expected_nonce:
                continue
            if bot_user_id is None:
                return message
            if getattr(getattr(message, 'author', None), 'id', None) == bot_user_id:
                return message
        return None

    @staticmethod
    def _delivery_nonce(delivery: DeliveryOutboxRecord) -> str:
        return f'tweeticcini-outbox-{delivery.id}'

    def _build_delivery_view(self, tweet, presentation):
        if bool(tweet.media) and tweet.media[0].type == 'video' and presentation.effective.embed_type == 'built_in' and presentation.effective.built_in_video_link_button:
            view = discord.ui.View()
            view.add_item(discord.ui.Button(label='View Video', style=discord.ButtonStyle.link, url=tweet.media[0].expanded_url))
            return view
        if presentation.effective.embed_type == 'fx_twitter' and presentation.effective.fx_original_url_button:
            view = discord.ui.View()
            view.add_item(discord.ui.Button(label='View Original', style=discord.ButtonStyle.link, url=tweet.url))
            return view
        return None

    def _retry_delay_seconds(self, attempt_count: int) -> int:
        delay = self.delivery_outbox_retry_base_seconds * (2 ** max(attempt_count - 1, 0))
        return min(delay, self.delivery_outbox_retry_max_seconds)

    @staticmethod
    def _delivery_pause_reason(error: Exception) -> Optional[str]:
        error_code = getattr(error, 'code', None)
        message = str(error).lower()

        if isinstance(error, discord.NotFound):
            return 'This Discord channel no longer exists.'

        if isinstance(error, discord.Forbidden):
            if error_code == 50013 or 'missing permissions' in message:
                return (
                    'Tweeticcini is missing permission to send messages '
                    'or embeds in this Discord channel.'
                )
            return (
                'Tweeticcini no longer has access to this Discord channel.'
            )

        if (
            error_code == 50001
            or '50001' in message
            or 'missing access' in message
        ):
            return (
                'Tweeticcini no longer has access to this Discord channel.'
            )

        if (
            error_code == 50013
            or '50013' in message
            or 'missing permissions' in message
        ):
            return (
                'Tweeticcini is missing permission to send messages '
                'or embeds in this Discord channel.'
            )

        if (
            error_code == 10003
            or '10003' in message
            or 'unknown channel' in message
        ):
            return 'This Discord channel no longer exists.'

        return None

    def _is_permanent_delivery_error(self, error: Exception) -> bool:
        if isinstance(error, (discord.NotFound, discord.Forbidden)):
            return True
        message = str(error).lower()
        return (
            'unknown channel' in message
            or 'missing access' in message
            or 'missing permissions' in message
            or 'invalid form body' in message
            or 'categorychannel' in message
            or 'forumchannel' in message
        )

    def _is_support_prompt_eligible(self, server_id: str, presentation_plan: str, channel_id: str) -> bool:
        is_managed_server = server_id in self.support_prompt_server_ids
        is_free_server = presentation_plan == 'free'
        if not (is_free_server or is_managed_server):
            return False

        # Channel constraints are only enforced for explicitly managed servers.
        if is_managed_server:
            allowed_channels = self.support_prompt_channel_overrides.get(server_id)
            if allowed_channels is not None:
                return channel_id in allowed_channels
        return True

    def _get_support_prompt_text(self, server_id: str) -> str:
        if server_id in self.support_prompt_server_ids:
            return self.managed_support_prompt_text or _get_managed_support_prompt_default_text()
        return '☕ Enjoying Tweeticcini? A small one-time contribution helps me cover hosting and keep the bot running. 🩷'

    def _get_support_prompt_url(self, server_id: str) -> Optional[str]:
        if server_id in self.support_prompt_server_ids:
            return _get_top_gg_vote_url()
        return _get_donation_url()

    async def _should_include_support_footer(
        self,
        cursor,
        server_id: str,
        presentation_plan: str,
        channel_id: str,
    ) -> bool:
        if not self._is_support_prompt_eligible(
            server_id,
            presentation_plan,
            channel_id,
        ):
            return False

        return (
            await increment_server_support_prompt_counter_with_cursor(
                cursor,
                server_id,
                datetime.now(timezone.utc).isoformat(
                    timespec='seconds'
                ),
                threshold=self.support_prompt_threshold,
            )
        )

    def _should_include_force_everyone_support_footer(self, server_id: str, force_everyone: bool) -> bool:
        if not force_everyone:
            return False
        if not _get_top_gg_vote_url():
            return False
        return server_id in self.support_prompt_server_ids

    async def tweetsUpdater(self, app):
        updater_name = asyncio.current_task().get_name().split('_', 1)[1]
        while True:
            try:
                fetched_tweets = await app.get_tweet_notifications() or []
                self.tweets[updater_name] = self._merge_tweet_cache(
                    self.tweets.get(updater_name, []),
                    fetched_tweets,
                )
                if updater_name in self.poll_error_states:
                    last_error = self.poll_error_states.pop(updater_name)
                    log.info(f'tweets updater {updater_name} recovered after polling issue: {last_error}')
                await record_client_poll_success(
                    self.db_path,
                    updater_name,
                    len(fetched_tweets),
                    datetime.now(timezone.utc).isoformat(timespec='seconds'),
                )
                await asyncio.sleep(self._get_client_poll_interval(updater_name))
            except Exception as e:
                error_text = str(e)
                self.poll_error_states[updater_name] = error_text
                await record_client_poll_error(
                    self.db_path,
                    updater_name,
                    error_text,
                    datetime.now(timezone.utc).isoformat(timespec='seconds'),
                )
                if 'no healthy upstream' in error_text.lower():
                    log.warning(
                        f'tweets updater {updater_name} hit a transient upstream Twitter/Tweety error: '
                        f'{error_text}. Retrying in {configs["tweets_updater_retry_delay"]} minutes.'
                    )
                else:
                    log.error(f'{e} (task : tweets updater {updater_name})')
                    log.exception('tweets updater failure details')
                    log.error(f"an unexpected error occurred, try again in {configs['tweets_updater_retry_delay']} minutes")
                await asyncio.sleep(configs['tweets_updater_retry_delay'] * 60)

    async def deliveryOutboxProcessor(self):
        while True:
            try:
                await self.process_delivery_outbox()
            except Exception as exc:
                log.error(f'delivery outbox processor failure: {exc}')
            await asyncio.sleep(self.delivery_outbox_poll_seconds)

    def _partition_configured_tasks(
        self,
        configured_pairs: list[tuple[str, str]],
    ) -> tuple[
        dict[str, tuple[str, str]],
        dict[str, tuple[str, str]],
        set[str],
    ]:
        configured_tasks = {
            self._task_name(username, client_used): (
                username,
                client_used,
            )
            for username, client_used in configured_pairs
        }
        available_tasks = {
            task_name: pair
            for task_name, pair in configured_tasks.items()
            if pair[1] in self.accounts_data
        }
        missing_tasks = set(configured_tasks) - set(available_tasks)
        return configured_tasks, available_tasks, missing_tasks


    def _update_missing_session_state(
        self,
        configured_tasks: dict[str, tuple[str, str]],
        missing_tasks: set[str],
    ) -> None:
        newly_missing = missing_tasks - self.missing_session_tasks
        recovered = (
            self.missing_session_tasks - missing_tasks
        ) & set(configured_tasks)

        for task_name in sorted(newly_missing):
            username, client_used = configured_tasks[task_name]
            log.warning(
                f'suspended {username}; Twitter/X session '
                f'{client_used} is unavailable'
            )

        for task_name in sorted(recovered):
            username, client_used = configured_tasks[task_name]
            log.info(
                f'resuming {username}; Twitter/X session '
                f'{client_used} is available again'
            )

        self.missing_session_tasks = set(missing_tasks)

    async def tasksMonitor(self):
        while True:
            await self._ensure_twitter_updaters()
            users_and_clients = await self.twitter_session_service_pairs()
            (
                configured_tasks,
                expected_tasks,
                missing_tasks,
            ) = self._partition_configured_tasks(
                users_and_clients
            )
            self._update_missing_session_state(
                configured_tasks,
                missing_tasks,
            )
            all_tasks = list(asyncio.all_tasks())
            taskSet = {task.get_name() for task in all_tasks}
            aliveTasks = taskSet & set(expected_tasks.keys())
            staleTaskNames = [name for name in taskSet if '::' in name and name not in expected_tasks]
            task_name_groups: dict[str, list[asyncio.Task]] = {}

            for task in all_tasks:
                task_name = task.get_name()
                if '::' not in task_name:
                    continue
                task_name_groups.setdefault(task_name, []).append(task)

            for task in all_tasks:
                task_name = task.get_name()
                if task_name not in staleTaskNames:
                    continue
                try:
                    task.cancel()
                    log.info(f'removed stale task {task_name}')
                except Exception as e:
                    log.warning(f'failed to remove stale task {task_name}: {e}')

            # Keep only one notification task per username/client pair.
            for task_name, group in task_name_groups.items():
                if len(group) <= 1:
                    continue
                for duplicate in group[1:]:
                    try:
                        duplicate.cancel()
                        log.info(f'removed duplicate task {task_name}')
                    except Exception as e:
                        log.warning(f'failed to remove duplicate task {task_name}: {e}')

            if aliveTasks != set(expected_tasks.keys()):
                deadTasks = [expected_tasks[name] for name in (set(expected_tasks.keys()) - aliveTasks)]
                log.warning(f'dead tasks : {deadTasks}')
                for username, client_used in deadTasks:
                    self.bot.loop.create_task(self.notification(username, client_used)).set_name(self._task_name(username, client_used))
                    log.info(f'restart {username} successfully using {client_used}')

            for client in self.accounts_data.keys():
                if f'TweetsUpdater_{client}' not in taskSet:
                    log.warning(f'tweets updater {client} : dead')

            if 'DeliveryOutboxProcessor' not in taskSet:
                self.bot.loop.create_task(self.deliveryOutboxProcessor()).set_name('DeliveryOutboxProcessor')
                log.info('restarted delivery outbox processor')

            if (datetime.now(timezone.utc) - self.tasksMonitorLogAt).total_seconds() / 3600 >= configs['tasks_monitor_log_period']:
                log.info(f'alive tasks : {list(aliveTasks)}')
                for client in self.accounts_data.keys():
                    if f'TweetsUpdater_{client}' in taskSet:
                        log.info(f'tweets updater {client} : alive')
                self.tasksMonitorLogAt = datetime.now(timezone.utc)

            await asyncio.sleep(configs['tasks_monitor_check_period'] * 60)

    async def twitter_session_service_pairs(self) -> list[tuple[str, str]]:
        from src.services.notifier_service import NotifierService
        return await NotifierService(self.db_path).get_enabled_user_client_pairs()

    @staticmethod
    def _task_name(username: str, client_used: str) -> str:
        return f'{username}::{client_used}'

    async def addTask(self, username: str, client_used: str):
        task_name = self._task_name(username, client_used)
        if task_name not in {task.get_name() for task in asyncio.all_tasks()}:
            self.bot.loop.create_task(self.notification(username, client_used)).set_name(task_name)
            log.info(f'new task {username} added successfully using {client_used}')
        else:
            log.info(f'task {username} already exists using {client_used}, skipping duplicate add')

        for task in asyncio.all_tasks():
            if task.get_name() == 'TasksMonitor':
                try:
                    log.info('existing TasksMonitor has been closed') if task.cancel() else log.info('existing TasksMonitor failed to close')
                except Exception as e:
                    log.warning(f'addTask : {e}')

        self.bot.loop.create_task(self.tasksMonitor()).set_name('TasksMonitor')
        log.info('new TasksMonitor has been started')

    async def removeTask(self, username: str):
        for task in asyncio.all_tasks():
            if task.get_name() == 'TasksMonitor':
                try:
                    log.info('existing TasksMonitor has been closed') if task.cancel() else log.info('existing TasksMonitor failed to close')
                except Exception as e:
                    log.warning(f'removeTask : {e}')

        for task in asyncio.all_tasks():
            if task.get_name().startswith(f'{username}::'):
                try:
                    log.info(f'existing task {username} has been closed') if task.cancel() else log.info(f'existing task {username} failed to close')
                except Exception as e:
                    log.warning(f'removeTask : {e}')

        self.bot.loop.create_task(self.tasksMonitor()).set_name('TasksMonitor')
        log.info('new TasksMonitor has been started')

    @staticmethod
    def _tweet_created_at_utc(tweet) -> datetime:
        created_at = tweet.created_on

        if created_at.tzinfo is None:
            return created_at.replace(tzinfo=timezone.utc)

        return created_at.astimezone(timezone.utc)


    def _select_tweets_for_cycle(
        self,
        latest_tweets: list,
        now: Optional[datetime] = None,
    ) -> tuple[list, list, list]:
        current_time = now or datetime.now(timezone.utc)

        if current_time.tzinfo is None:
            current_time = current_time.replace(tzinfo=timezone.utc)
        else:
            current_time = current_time.astimezone(timezone.utc)

        cutoff = current_time - timedelta(
            minutes=self.max_tweet_backfill_age_minutes
        )

        expired_tweets = [
            tweet
            for tweet in latest_tweets
            if self._tweet_created_at_utc(tweet) < cutoff
        ]

        eligible_tweets = [
            tweet
            for tweet in latest_tweets
            if self._tweet_created_at_utc(tweet) >= cutoff
        ]

        tweets_to_process = eligible_tweets[
            : self.max_tweets_per_source_cycle
        ]

        deferred_tweets = eligible_tweets[
            len(tweets_to_process) :
        ]

        return expired_tweets, tweets_to_process, deferred_tweets
