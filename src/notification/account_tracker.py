import asyncio
import sys
import re
from datetime import datetime, timezone, timedelta

import aiosqlite
import discord
from discord.ext import commands

from src.adapters.twitter_adapter import create_twitter_session
from configs.load_configs import configs
from src.repositories.notifier_repository import (
    get_enabled_notifications_for_user,
    get_enabled_user_client_map,
    get_user_by_username,
    update_user_latest_tweet,
)
from src.services.guild_settings_service import GuildSettingsService
from src.log import setup_logger
from src.services.alert_rule_service import AlertRuleService
from src.notification.display_tools import gen_embed, get_action
from src.notification.get_tweets import get_tweets
from src.notification.utils import is_match_media_type, is_match_type, replace_emoji
from src.settings import get_accounts, get_db_path
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

class AccountTracker():
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.accounts_data = get_accounts()
        self.db_path = get_db_path()
        self.alert_rule_service = AlertRuleService(self.db_path)
        self.guild_settings_service = GuildSettingsService(self.db_path)
        self.tweets = {account_name: [] for account_name in self.accounts_data.keys()}
        self.tasksMonitorLogAt = datetime.now(timezone.utc) - timedelta(hours=configs['tasks_monitor_log_period'])
        bot.loop.create_task(self.setup_tasks())

    async def setup_tasks(self):
        async def authenticate_account(account_name, account_token):
            app = create_twitter_session(account_name)
            max_attempts = configs['auth_max_attempts']
            for attempt in range(max_attempts):
                try:
                    await app.load_auth_token(account_token)
                    return app
                except Exception as e:
                    log.error(f"Authentication failed for account: {account_name} [Attempt {attempt + 1}/{max_attempts}]")
                    if attempt < max_attempts - 1:
                        await asyncio.sleep(5)
                    else:
                        log.error(f"Persistent authentication failure for account {account_name}")
                        raise

        for account_name, account_token in self.accounts_data.items():
            try:
                app = await authenticate_account(account_name, account_token)
                self.bot.loop.create_task(self.tweetsUpdater(app)).set_name(f'TweetsUpdater_{account_name}')
            except Exception:
                sys.exit(1)

        usernames_and_clients = await get_enabled_user_client_map(self.db_path)

        for username, client_used in usernames_and_clients.items():
            self.bot.loop.create_task(self.notification(username, client_used)).set_name(username)
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
                        log.info(f'find a new tweet from {username}')
                        notifications = await get_enabled_notifications_for_user(cursor, user['id'])
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
                                        log.info(f"[DEBUG] tweet.rawContent missing. Falling back to tweet.content: {getattr(tweet, 'content', None)}")
                                        text = getattr(tweet, 'content', None) or ''

                                    alert_decision = await self.alert_rule_service.resolve_alert_decision(
                                        server_id=str(channel.guild.id),
                                        channel_id=str(channel.id),
                                        source_username=username,
                                        text=text,
                                    )
                                    if alert_decision.should_exclude:
                                        log.info(f"[DEBUG] Tweet excluded by keyword filter: {text}")
                                        continue

                                    log.info(f"[DEBUG] Evaluating @everyone condition for {username} in channel {channel.id}")
                                    log.info(f"[DEBUG] tweet content: {text}")
                                    log.info(f"[DEBUG] matched_rule = {alert_decision.matched_rule_name}")

                                    if alert_decision.should_force_everyone:
                                        mention = "@everyone "
                                        log.info(f"[DEBUG] @everyone mention triggered for tweet: {tweet.url}")

                                    template = data['customized_msg'] or presentation.effective.default_message
                                    try:
                                        msg = build_notification_message(template, mention, tweet, url)
                                    except KeyError as e:
                                        log.warning(f'invalid message template placeholder {e} for {username}, falling back to default message')
                                        msg = build_notification_message(presentation.effective.default_message, mention, tweet, url)

                                    if presentation.effective.emoji_auto_format:
                                        msg = re.sub(r':([a-zA-Z0-9_]+):', lambda m: replace_emoji(m, channel.guild), msg)

                                    if not msg:
                                        headline = extract_first_line(text)
                                        msg = f"{mention}{headline}: {url}" if headline else f"{mention}{url}"

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

                                except Exception as e:
                                    if not isinstance(e, discord.errors.Forbidden):
                                        log.error(f'an error occurred at {channel.mention} while sending notification: {e}')

    async def tweetsUpdater(self, app):
        updater_name = asyncio.current_task().get_name().split('_', 1)[1]
        while True:
            try:
                self.tweets[updater_name] = await app.get_tweet_notifications()
                await asyncio.sleep(configs['tweets_check_period'])
            except Exception as e:
                log.error(f'{e} (task : tweets updater {updater_name})')
                log.error(f"an unexpected error occurred, try again in {configs['tweets_updater_retry_delay']} minutes")
                await asyncio.sleep(configs['tweets_updater_retry_delay'] * 60)

    async def tasksMonitor(self):
        while True:
            users_and_clients = await get_enabled_user_client_map(self.db_path)
            taskSet = {task.get_name() for task in asyncio.all_tasks()}
            users = {username for username, _ in users_and_clients.items()}
            aliveTasks = taskSet & users

            if aliveTasks != users:
                deadTasks = list(users - aliveTasks)
                log.warning(f'dead tasks : {deadTasks}')
                for deadTask in deadTasks:
                    self.bot.loop.create_task(self.notification(deadTask, users_and_clients[deadTask])).set_name(deadTask)
                    log.info(f'restart {deadTask} successfully using {users_and_clients[deadTask]}')

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

    async def addTask(self, username: str, client_used: str):
        self.bot.loop.create_task(self.notification(username, client_used)).set_name(username)
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
            if task.get_name() == username:
                try:
                    log.info(f'existing task {username} has been closed') if task.cancel() else log.info(f'existing task {username} failed to close')
                except Exception as e:
                    log.warning(f'removeTask : {e}')

        self.bot.loop.create_task(self.tasksMonitor()).set_name('TasksMonitor')
        log.info('new TasksMonitor has been started')
