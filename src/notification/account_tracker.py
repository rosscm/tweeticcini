import asyncio
import re
import os
from datetime import datetime, timezone, timedelta
from typing import Optional

import aiosqlite
import discord
from discord.ext import commands

from src.adapters.twitter_adapter import create_twitter_session
from configs.load_configs import configs
from src.repositories.notifier_repository import (
    get_enabled_notifications_for_user_client,
    get_user_by_username,
    update_user_latest_tweet_for_client,
)
from src.repositories.runtime_metrics_repository import (
    increment_server_support_prompt_counter,
    record_client_poll_error,
    record_client_poll_success,
    record_source_delivery_error,
    record_source_delivery_success,
)
from src.services.guild_settings_service import GuildSettingsService
from src.log import setup_logger
from src.services.alert_rule_service import AlertRuleService
from src.notification.display_tools import gen_embed, get_action
from src.notification.get_tweets import get_tweets
from src.notification.utils import is_match_media_type, is_match_type, replace_emoji
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


def _get_support_prompt_server_ids() -> set[str]:
    raw = os.getenv('SUPPORT_PROMPT_SERVER_IDS', '').strip()
    if not raw:
        return set()
    return {server_id.strip() for server_id in raw.split(',') if server_id.strip()}


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
        self.tasksMonitorLogAt = datetime.now(timezone.utc) - timedelta(hours=configs['tasks_monitor_log_period'])
        self.support_prompt_server_ids = _get_support_prompt_server_ids()
        self.support_prompt_channel_overrides = _get_support_prompt_channel_overrides()
        self.support_prompt_threshold = 20
        self.tweet_cache_limit = max(int(configs.get('tweet_cache_limit', 500) or 500), 1)
        self.max_tweets_per_source_cycle = max(int(configs.get('max_tweets_per_source_cycle', 1) or 1), 1)
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
        configured = int(configs.get('free_tweets_check_period', 90))
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
        self.bot.loop.create_task(self.tasksMonitor()).set_name('TasksMonitor')

    async def notification(self, username: str, client_used: str):
        while True:
            await asyncio.sleep(self._get_client_poll_interval(client_used))

            lastest_tweets = await get_tweets(self.tweets[client_used], username, client_used)
            if lastest_tweets is None:
                continue

            log.debug(f'found {len(lastest_tweets)} new tweet(s) for {username} using {client_used}')
            tweets_to_send = lastest_tweets[-self.max_tweets_per_source_cycle:]
            skipped_tweets_count = len(lastest_tweets) - len(tweets_to_send)
            if skipped_tweets_count:
                log.info(
                    f'skipping {skipped_tweets_count} older tweet(s) for {username} using {client_used}; '
                    f'sending latest {len(tweets_to_send)} only'
                )
            async with aiosqlite.connect(self.db_path) as db:
                db.row_factory = aiosqlite.Row
                async with db.cursor() as cursor:
                    user = await get_user_by_username(cursor, username)
                    async with lock:
                        await update_user_latest_tweet_for_client(
                            cursor,
                            username,
                            client_used,
                            str(lastest_tweets[-1].created_on),
                        )
                        await db.commit()

                    for tweet in tweets_to_send:
                        notifications = await get_enabled_notifications_for_user_client(cursor, user['id'], client_used)
                        log.debug(f'found {len(notifications)} notification target(s) for {username} using {client_used}')
                        for data in notifications:
                            channel = self.bot.get_channel(int(data['channel_id']))
                            if channel is None:
                                try:
                                    channel = await self.bot.fetch_channel(int(data['channel_id']))
                                except Exception as exc:
                                    log.warning(
                                        f"unable to resolve channel {data['channel_id']} for {username} using {client_used}: {exc}"
                                    )
                                    continue

                            matches_type = is_match_type(tweet, data['enable_type'])
                            matches_media = is_match_media_type(tweet, data['enable_media_type'])
                            if not matches_type or not matches_media:
                                log.debug(
                                    f"skipping {username} delivery to {data['channel_id']} using {client_used}: "
                                    f"type_match={matches_type} media_match={matches_media}"
                                )
                                continue

                            if channel is not None:
                                try:
                                    presentation = await self.guild_settings_service.get_presentation_view(str(channel.guild.id))
                                    log.debug(
                                        f"delivery compliance check for guild {channel.guild.id}: "
                                        f"plan={presentation.plan} "
                                        f"non_compliant={presentation.compliance.is_non_compliant} "
                                        f"reasons={list(presentation.compliance.reason_labels)}"
                                    )
                                    if presentation.plan == 'free' and presentation.compliance.is_non_compliant:
                                        log.debug(
                                            f"skipping delivery for guild {channel.guild.id}: "
                                            f"free-plan compliance required ({', '.join(presentation.compliance.reason_labels)})"
                                        )
                                        continue
                                    url = re.sub('twitter', presentation.effective.fx_domain_name, tweet.url) if presentation.effective.embed_type == 'fx_twitter' else tweet.url
                                    view, create_view = None, False
                                    if bool(tweet.media) and tweet.media[0].type == 'video' and presentation.effective.embed_type == 'built_in' and presentation.effective.built_in_video_link_button:
                                        create_view = True
                                        button_label, button_url = 'View Video', tweet.media[0].expanded_url
                                    elif presentation.effective.embed_type == 'fx_twitter' and presentation.effective.fx_original_url_button:
                                        create_view = True
                                        button_label, button_url = 'View Original', tweet.url

                                    if create_view:
                                        view = discord.ui.View()
                                        view.add_item(discord.ui.Button(label=button_label, style=discord.ButtonStyle.link, url=button_url))

                                    role = channel.guild.get_role(int(data['role_id'])) if data['role_id'] else None
                                    mention = f"{role.mention} " if role is not None else ''

                                    text = (
                                        getattr(tweet, 'rawContent', None)
                                        or getattr(tweet, 'content', None)
                                        or getattr(tweet, 'text', None)
                                        or getattr(tweet, 'full_text', None)
                                        or ''
                                    )
                                    if not text:
                                        text = getattr(tweet, 'content', None) or ''

                                    preview = re.sub(r'\s+', ' ', text).strip()
                                    if len(preview) > 140:
                                        preview = f"{preview[:137]}..."

                                    log.debug(f"new tweet from {username}: {preview or '[no text]'}")

                                    alert_decision = await self.alert_rule_service.resolve_alert_decision(
                                        server_id=str(channel.guild.id),
                                        channel_id=str(channel.id),
                                        source_username=username,
                                        text=text,
                                    )
                                    if alert_decision.should_force_everyone and not presentation.features.can_use_everyone_escalation:
                                        matched_rule = f" via rule {alert_decision.matched_rule_name}" if alert_decision.matched_rule_name else ''
                                        log.debug(
                                            f"skipping delivery for guild {channel.guild.id}{matched_rule}: "
                                            'ping everyone rules require Premium'
                                        )
                                        continue
                                    if alert_decision.should_exclude:
                                        keyword_detail = ''
                                        if alert_decision.matched_keywords:
                                            keyword_detail = f" (keywords: {', '.join(alert_decision.matched_keywords)})"
                                        if alert_decision.matched_rule_name:
                                            log.debug(
                                                f"excluded tweet from {username} via rule {alert_decision.matched_rule_name}{keyword_detail}: {preview or '[no text]'}"
                                            )
                                        else:
                                            log.debug(f"excluded tweet from {username}{keyword_detail}: {preview or '[no text]'}")
                                        continue

                                    if alert_decision.should_force_everyone:
                                        keyword_detail = ''
                                        if alert_decision.matched_keywords:
                                            keyword_detail = f" (keywords: {', '.join(alert_decision.matched_keywords)})"
                                        if alert_decision.matched_rule_name:
                                            log.debug(
                                                f"pinging everyone for {username} via rule {alert_decision.matched_rule_name}{keyword_detail}: {preview or '[no text]'}"
                                            )
                                        else:
                                            log.debug(f"pinging everyone for {username}{keyword_detail}: {preview or '[no text]'}")
                                        mention = "@everyone "

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
                                        except KeyError as e:
                                            log.warning(f'invalid message template placeholder {e} for {username}, falling back to headline message')
                                            msg = build_headline_notification_message(mention, text, url)
                                    elif effective_use_headline_message:
                                        msg = build_headline_notification_message(mention, text, url)
                                    else:
                                        try:
                                            msg = build_notification_message(default_template, mention, tweet, url)
                                        except KeyError as e:
                                            log.warning(f'invalid default message template placeholder {e} for {username}, falling back to headline message')
                                            msg = build_headline_notification_message(mention, text, url)

                                    if presentation.effective.emoji_auto_format:
                                        msg = re.sub(r':([a-zA-Z0-9_]+):', lambda m: replace_emoji(m, channel.guild), msg)

                                    if not msg:
                                        msg = build_headline_notification_message(mention, text, url)

                                    should_include_support_footer = await self._should_include_support_footer(
                                        server_id=str(channel.guild.id),
                                        presentation_plan=presentation.plan,
                                        channel_id=str(channel.id),
                                    )
                                    should_include_force_everyone_support_footer = self._should_include_force_everyone_support_footer(
                                        server_id=str(channel.guild.id),
                                        force_everyone=bool(getattr(alert_decision, 'should_force_everyone', False)),
                                    )
                                    support_prompt_text = None
                                    support_prompt_url = None
                                    if should_include_support_footer or should_include_force_everyone_support_footer:
                                        vote_url = _get_top_gg_vote_url()
                                        if vote_url:
                                            support_prompt_text = 'Enjoying Tweeticcini? Vote on top.gg 💛'
                                            support_prompt_url = vote_url

                                    if presentation.effective.embed_type == 'fx_twitter':
                                        fx_embeds = []
                                        if support_prompt_url:
                                            fx_embeds.append(
                                                discord.Embed(
                                                    description=f'{support_prompt_text}\n{support_prompt_url}',
                                                    color=0xF6C453,
                                                )
                                            )
                                        send_kwargs = {'content': msg, 'view': view}
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
                                            support_embed = discord.Embed(
                                                description=f'{support_prompt_text}\n{support_prompt_url}',
                                                color=0xF6C453,
                                            )
                                            embeds.append(support_embed)
                                        await channel.send(
                                            content=msg,
                                            file=file,
                                            embeds=embeds,
                                            view=view,
                                        )
                                    await record_source_delivery_success(
                                        self.db_path,
                                        str(channel.guild.id),
                                        username,
                                        str(channel.id),
                                        tweet.url,
                                        alert_decision.matched_rule_name,
                                        datetime.now(timezone.utc).isoformat(timespec='seconds'),
                                    )
                                except Exception as e:
                                    if channel is not None:
                                        await record_source_delivery_error(
                                            self.db_path,
                                            str(channel.guild.id),
                                            username,
                                            str(channel.id),
                                            str(e),
                                            datetime.now(timezone.utc).isoformat(timespec='seconds'),
                                        )
                                    if isinstance(e, discord.errors.Forbidden):
                                        channel_label = channel.mention if channel is not None else f"channel {data['channel_id']}"
                                        log.warning(
                                            f'missing permission to send the full alert in {channel_label} for {username} using {client_used}: {e}'
                                        )
                                    else:
                                        channel_label = channel.mention if channel is not None else f"channel {data['channel_id']}"
                                        log.error(f'an error occurred at {channel_label} while sending notification: {e}')

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

    async def _should_include_support_footer(self, server_id: str, presentation_plan: str, channel_id: str) -> bool:
        vote_url = _get_top_gg_vote_url()
        if not vote_url:
            return False
        if not self._is_support_prompt_eligible(server_id, presentation_plan, channel_id):
            return False
        return await increment_server_support_prompt_counter(
            self.db_path,
            server_id,
            datetime.now(timezone.utc).isoformat(timespec='seconds'),
            threshold=self.support_prompt_threshold,
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

    async def tasksMonitor(self):
        while True:
            await self._ensure_twitter_updaters()
            users_and_clients = await self.twitter_session_service_pairs()
            expected_tasks = {self._task_name(username, client_used): (username, client_used) for username, client_used in users_and_clients}
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
                    if client_used not in self.tweets:
                        log.warning(f'skipping restart for {username}; Twitter/X session {client_used} is not available')
                        continue
                    self.bot.loop.create_task(self.notification(username, client_used)).set_name(self._task_name(username, client_used))
                    log.info(f'restart {username} successfully using {client_used}')

            for client in self.accounts_data.keys():
                if f'TweetsUpdater_{client}' not in taskSet:
                    log.warning(f'tweets updater {client} : dead')

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
