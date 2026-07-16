import asyncio
import os
from datetime import datetime, timezone

import aiosqlite
import discord
from discord import app_commands
from discord.ext import commands
from dotenv import load_dotenv

from configs.load_configs import configs
from src.checker import check_configs, check_env, check_db, check_upgrade
from src.db_function.init_db import ensure_db_schema
from src.db_function.repair_db import auto_repair_mismatched_clients
from src.presence_updater import update_presence
from src.log import setup_logger
from src.notification.account_tracker import AccountTracker
from src.repositories.guild_cleanup_repository import cleanup_guild_data
from src.repositories.bot_runtime_health_repository import mark_bot_runtime_error, mark_bot_runtime_recovered
from src.settings import get_db_path

log = setup_logger(__name__)

load_dotenv()

intents = discord.Intents(guilds=True, messages=True, emojis=True)
DEFAULT_COGS = ['about']
account_tracker = None


async def _persist_connected_server_count() -> None:
    async with aiosqlite.connect(get_db_path()) as db:
        await db.execute(
            "INSERT OR REPLACE INTO app_meta (key, value) VALUES ('connected_servers_count', ?)",
            (str(len(bot.guilds)),),
        )
        await db.execute(
            "INSERT OR REPLACE INTO app_meta (key, value) VALUES ('connected_servers_count_updated_at', ?)",
            (datetime.now(timezone.utc).isoformat(timespec='seconds'),),
        )
        await db.commit()


class TweeticciniBot(commands.Bot):
    def __init__(self):
        super().__init__(command_prefix=configs['prefix'], intents=intents)
        self._startup_complete = False

    async def setup_hook(self):
        global account_tracker
        if self._startup_complete:
            return

        await ensure_db_schema()
        check_upgrade()

        if not check_env():
            raise RuntimeError('incomplete environment variables detected')

        if not check_configs(configs):
            raise RuntimeError('incomplete configs file detected')

        invalid_clients = await check_db()
        if invalid_clients:
            log.warning('detected environment variable undefined client name in database')
            if configs['auto_repair_mismatched_clients']:
                await auto_repair_mismatched_clients(invalid_clients)
                log.info('automatically replaced mismatched client names with the first configured client name')
            else:
                log.warning('set auto_repair_mismatched_clients to true in configs to automatically fix this error or manually update the database or environment variables')
        else:
            log.info('database check passed')

        self.tree.on_error = on_tree_error
        for cog_name in DEFAULT_COGS:
            if f'cogs.{cog_name}' not in self.extensions:
                await self.load_extension(f'cogs.{cog_name}')

        if account_tracker is None:
            account_tracker = AccountTracker(self)

        slash = await self.tree.sync()
        log.info(f'synced {len(slash)} slash commands')
        self._startup_complete = True


bot = TweeticciniBot()


@bot.event
async def on_ready():
    log.info(f'{bot.user} is online')
    await mark_bot_runtime_recovered(
        get_db_path(),
        datetime.now(timezone.utc).isoformat(timespec='seconds'),
    )
    await _persist_connected_server_count()
    await update_presence(bot)


@bot.event
async def on_tree_error(itn: discord.Interaction, error: app_commands.AppCommandError):
    message = str(error)
    try:
        if itn.response.is_done():
            await itn.followup.send(message, ephemeral=True)
        else:
            await itn.response.send_message(message, ephemeral=True)
    except (discord.NotFound, discord.HTTPException):
        pass

    if 'Unknown interaction' in message:
        return

    log.warning(f'an error occurred but was handled by the tree error handler, error message : {error}')


@bot.event
async def on_command_error(ctx: commands.context.Context, error: commands.errors.CommandError):
    if isinstance(error, commands.errors.CommandNotFound):
        return
    else:
        await ctx.send(error)
    log.warning(f'an error occurred but was handled by the command error handler, error message : {error}')


@bot.event
async def on_guild_remove(guild: discord.Guild):
    summary = await cleanup_guild_data(get_db_path(), str(guild.id))
    await _persist_connected_server_count()
    log.info(
        'cleaned up guild %s (%s) after removal: %s',
        guild.id,
        guild.name,
        summary,
    )


@bot.event
async def on_guild_join(_guild: discord.Guild):
    await _persist_connected_server_count()


if __name__ == '__main__':
    try:
        bot.run(os.getenv('BOT_TOKEN'))
    except Exception as exc:
        try:
            asyncio.run(
                mark_bot_runtime_error(
                    get_db_path(),
                    str(exc),
                    datetime.now(timezone.utc).isoformat(timespec='seconds'),
                )
            )
        except Exception:
            pass
        raise
