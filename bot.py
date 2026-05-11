import asyncio
import os
import sys
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

intents = discord.Intents(guilds=True, messages=True, message_content=True, emojis=True)
bot = commands.Bot(command_prefix=configs['prefix'], intents=intents)
DEFAULT_COGS = ['dashboard', 'about']
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


@bot.event
async def on_ready():
    global account_tracker
    await ensure_db_schema()
        
    check_upgrade()
        
    if not check_env():
        log.warning('incomplete environment variables detected, will retry in 30 seconds')
        await asyncio.sleep(30)
        load_dotenv()
        
    if not check_configs(configs):
        log.warning('incomplete configs file detected, will retry in 30 seconds')
        await asyncio.sleep(30)
        os.execv(sys.executable, ['python'] + sys.argv)
        
    invalid_clients = await check_db()
    if invalid_clients:
        log.warning('detected environment variable undefined client name in database')
        if configs['auto_repair_mismatched_clients']:
            await auto_repair_mismatched_clients(invalid_clients)
            log.info('automatically replace mismatched client names with the first client name in the environment variable, use the sync slash command in discord to ensure notifications are turned on')
        else:
            log.warning('set auto_repair_mismatched_clients to true in configs to automatically fix this error or manually update the database or environment variables')
    else:
        log.info('database check passed')

    if account_tracker is None:
        account_tracker = AccountTracker(bot)

    await mark_bot_runtime_recovered(
        get_db_path(),
        datetime.now(timezone.utc).isoformat(timespec='seconds'),
    )
    await _persist_connected_server_count()

    await update_presence(bot)

    bot.tree.on_error = on_tree_error

    for cog_name in DEFAULT_COGS:
        await bot.load_extension(f'cogs.{cog_name}')
    log.info(f'{bot.user} is online')
    slash = await bot.tree.sync()
    log.info(f'synced {len(slash)} slash commands')


@bot.command()
@commands.is_owner()
async def load(ctx: commands.context.Context, extension):
    await bot.load_extension(f'cogs.{extension}')
    await ctx.send(f'Loaded {extension} done.')


@bot.command()
@commands.is_owner()
async def unload(ctx: commands.context.Context, extension):
    await bot.unload_extension(f'cogs.{extension}')
    await ctx.send(f'Un - Loaded {extension} done.')


@bot.command()
@commands.is_owner()
async def reload(ctx: commands.context.Context, extension):
    await bot.reload_extension(f'cogs.{extension}')
    await ctx.send(f'Re - Loaded {extension} done.')


@bot.command()
@commands.is_owner()
async def download_log(ctx: commands.context.Context):
    message = await ctx.send(file=discord.File('console.log'))
    await message.delete(delay=15)


@bot.command()
@commands.is_owner()
async def download_data(ctx: commands.context.Context):
    message = await ctx.send(file=discord.File(get_db_path()))
    await message.delete(delay=15)


@bot.command()
@commands.is_owner()
async def upload_data(ctx: commands.context.Context):
    raw = await [attachment for attachment in ctx.message.attachments if attachment.filename[-3:] == '.db'][0].read()
    with open(get_db_path(), 'wb') as wbf:
        wbf.write(raw)
    message = await ctx.send('successfully uploaded data')
    await message.delete(delay=5)


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
