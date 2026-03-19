import asyncio
import sys
import re
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
    update_user_latest_tweet,
)
from src.repositories.runtime_metrics_repository import (
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
from src.settings import get_accounts, get_db_path, get_default_message
from src.utils import get_lock, extract_first_line


log = setup_logger(__name__)
lock = get_lock()


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
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.accounts_data = get_accounts()
        self.db_path = get_db_path()
        self.alert_rule_service = AlertRuleService(self.db_path)
        self.guild_settings_service = GuildSettingsService(self.db_path)
        self.twitter_session_service = TwitterSessionService(self.db_path)
        self.tweets = {}
        self.tasksMonitorLogAt = datetime.now(timezone.utc) - timedelta(hours=configs['tasks_monitor_log_period'])
        bot.loop.create_task(self.setup_tasks())

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
        self.accounts_data = latest_accounts
        for account_name in latest_accounts.keys():
            self.tweets.setdefault(account_name, [])

        active_task_names = {task.get_name() for task in asyncio.all_tasks()}
        for account_name, account_config in latest_accounts.items():
            if f'TweetsUpdater_{account_name}' in active_task_names:
                continue
            try:
                app = await self._authenticate_account(account_name, account_config)
                self.bot.loop.create_task(self.tweetsUpdater(app)).set_name(f'TweetsUpdater_{account_name}')
                log.info(f'loaded Twitter/X session {account_name} without bot restart')
            except Exception:
                if exit_on_failure:
                    sys.exit(1)
                log.error(f'skipping unavailable Twitter/X session {account_name} until it can authenticate successfully')

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

        for username, client_used in usernames_and_clients:
            if client_used not in self.tweets:
                log.warning(f'skipping task for {username}; Twitter/X session {client_used} is not available')
                continue
            self.bot.loop.create_task(self.notification(username, client_used)).set_name(self._task_name(username, client_used))
        self.bot.loop.create_task(self.tasksMonitor()).set_name('TasksMonitor')

    async def notification(self, username: str, client_used: str):
        while True:
            await asyncio.sleep(configs['tweets_check_period'])

            lastest_tweets = await get_tweets(self.tweets[client_used], username)
            if lastest_tweets is None:
                continue

            async with aiosqlite.connect(self.db_path) as db:
                db.row_factory = aiosqlite.Row
                async with db.cursor() as cursor:
                    user = await get_user_by_username(cursor, username)
                    async with lock:
                        await update_user_latest_tweet(cursor, username, str(lastest_tweets[-1].created_on))
                        await db.commit()

                    for tweet in lastest_tweets:
                        notifications = await get_enabled_notifications_for_user_client(cursor, user['id'], client_used)
                        for data in notifications:
                            channel = self.bot.get_channel(int(data['channel_id']))
                            if channel is not None and is_match_type(tweet, data['enable_type']) and is_match_media_type(tweet, data['enable_media_type']):
                                try:
                                    presentation = await self.guild_settings_service.get_presentation_view(str(channel.guild.id))
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

                                    log.info(f"new tweet from {username}: {preview or '[no text]'}")

                                    alert_decision = await self.alert_rule_service.resolve_alert_decision(
                                        server_id=str(channel.guild.id),
                                        channel_id=str(channel.id),
                                        source_username=username,
                                        text=text,
                                    )
                                    if alert_decision.should_exclude:
                                        keyword_detail = ''
                                        if alert_decision.matched_keywords:
                                            keyword_detail = f" (keywords: {', '.join(alert_decision.matched_keywords)})"
                                        if alert_decision.matched_rule_name:
                                            log.info(
                                                f"excluded tweet from {username} via rule {alert_decision.matched_rule_name}{keyword_detail}: {preview or '[no text]'}"
                                            )
                                        else:
                                            log.info(f"excluded tweet from {username}{keyword_detail}: {preview or '[no text]'}")
                                        continue

                                    if alert_decision.should_force_everyone:
                                        keyword_detail = ''
                                        if alert_decision.matched_keywords:
                                            keyword_detail = f" (keywords: {', '.join(alert_decision.matched_keywords)})"
                                        if alert_decision.matched_rule_name:
                                            log.info(
                                                f"pinging everyone for {username} via rule {alert_decision.matched_rule_name}{keyword_detail}: {preview or '[no text]'}"
                                            )
                                        else:
                                            log.info(f"pinging everyone for {username}{keyword_detail}: {preview or '[no text]'}")
                                        mention = "@everyone "

                                    custom_template = data['customized_msg']
                                    default_template = presentation.effective.default_message
                                    uses_server_message_override = default_template.strip() != get_default_message().strip()

                                    if custom_template:
                                        try:
                                            msg = build_notification_message(custom_template, mention, tweet, url)
                                        except KeyError as e:
                                            log.warning(f'invalid message template placeholder {e} for {username}, falling back to headline message')
                                            msg = build_headline_notification_message(mention, text, url)
                                    elif uses_server_message_override:
                                        try:
                                            msg = build_notification_message(default_template, mention, tweet, url)
                                        except KeyError as e:
                                            log.warning(f'invalid default message template placeholder {e} for {username}, falling back to headline message')
                                            msg = build_headline_notification_message(mention, text, url)
                                    else:
                                        msg = build_headline_notification_message(mention, text, url)

                                    if presentation.effective.emoji_auto_format:
                                        msg = re.sub(r':([a-zA-Z0-9_]+):', lambda m: replace_emoji(m, channel.guild), msg)

                                    if not msg:
                                        msg = build_headline_notification_message(mention, text, url)

                                    if presentation.effective.embed_type == 'fx_twitter':
                                        await channel.send(content=msg, view=view)
                                    else:
                                        footer = 'twitter.png' if presentation.effective.built_in_legacy_logo else 'x.png'
                                        file = discord.File(f'images/{footer}', filename='footer.png')
                                        await channel.send(
                                            content=msg,
                                            file=file,
                                            embeds=await gen_embed(
                                                tweet,
                                                use_fx_image=presentation.effective.built_in_fx_image,
                                                use_legacy_logo=presentation.effective.built_in_legacy_logo,
                                            ),
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
                                    if not isinstance(e, discord.errors.Forbidden):
                                        log.error(f'an error occurred at {channel.mention} while sending notification: {e}')

    async def tweetsUpdater(self, app):
        updater_name = asyncio.current_task().get_name().split('_', 1)[1]
        while True:
            try:
                self.tweets[updater_name] = await app.get_tweet_notifications()
                await record_client_poll_success(
                    self.db_path,
                    updater_name,
                    len(self.tweets[updater_name]),
                    datetime.now(timezone.utc).isoformat(timespec='seconds'),
                )
                await asyncio.sleep(configs['tweets_check_period'])
            except Exception as e:
                await record_client_poll_error(
                    self.db_path,
                    updater_name,
                    str(e),
                    datetime.now(timezone.utc).isoformat(timespec='seconds'),
                )
                log.error(f'{e} (task : tweets updater {updater_name})')
                log.exception('tweets updater failure details')
                log.error(f"an unexpected error occurred, try again in {configs['tweets_updater_retry_delay']} minutes")
                await asyncio.sleep(configs['tweets_updater_retry_delay'] * 60)

    async def tasksMonitor(self):
        while True:
            await self._ensure_twitter_updaters()
            users_and_clients = await self.twitter_session_service_pairs()
            expected_tasks = {self._task_name(username, client_used): (username, client_used) for username, client_used in users_and_clients}
            taskSet = {task.get_name() for task in asyncio.all_tasks()}
            aliveTasks = taskSet & set(expected_tasks.keys())

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
        self.bot.loop.create_task(self.notification(username, client_used)).set_name(self._task_name(username, client_used))
        log.info(f'new task {username} added successfully using {client_used}')

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
