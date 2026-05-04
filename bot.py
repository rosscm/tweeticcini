import asyncio
import os
import sys
from datetime import datetime, timezone
from typing import Optional

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
from src.repositories.guild_onboarding_repository import mark_onboarding_sent, was_onboarding_sent
from src.settings import get_db_path

log = setup_logger(__name__)

load_dotenv()

intents = discord.Intents(guilds=True, messages=True, message_content=True, emojis=True)
bot = commands.Bot(command_prefix=configs['prefix'], intents=intents)
DEFAULT_COGS = ['dashboard', 'about']
account_tracker = None


def _can_send_in_channel(channel: discord.abc.GuildChannel, guild: discord.Guild) -> bool:
    if not isinstance(channel, discord.TextChannel):
        return False
    me = guild.me
    if me is None:
        return False
    permissions = channel.permissions_for(me)
    return permissions.view_channel and permissions.send_messages


def _pick_onboarding_channel(guild: discord.Guild) -> Optional[discord.TextChannel]:
    if guild.system_channel and _can_send_in_channel(guild.system_channel, guild):
        return guild.system_channel

    named_priority = ('general', 'welcome')
    for name in named_priority:
        for channel in guild.text_channels:
            if channel.name.lower() == name and _can_send_in_channel(channel, guild):
                return channel

    for channel in guild.text_channels:
        if _can_send_in_channel(channel, guild):
            return channel
    return None


def _build_onboarding_message() -> str:
    return (
        "Thanks for inviting Tweeticcini 👋\n"
        "Start with `/dashboard` to connect your Twitter session and choose which accounts this server should monitor.\n"
        "Use `/about` anytime for a quick setup and runtime check."
    )


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
    log.info(
        'cleaned up guild %s (%s) after removal: %s',
        guild.id,
        guild.name,
        summary,
    )


@bot.event
async def on_guild_join(guild: discord.Guild):
    db_path = get_db_path()
    server_id = str(guild.id)
    if await was_onboarding_sent(db_path, server_id):
        return

    channel = _pick_onboarding_channel(guild)
    if channel is None:
        log.warning('joined guild %s (%s) but found no sendable channel for onboarding', guild.id, guild.name)
        return

    try:
        await channel.send(_build_onboarding_message())
        await mark_onboarding_sent(
            db_path,
            server_id,
            datetime.now(timezone.utc).isoformat(timespec='seconds'),
        )
        log.info('posted onboarding prompt in guild %s (%s) channel %s', guild.id, guild.name, channel.id)
    except discord.Forbidden:
        log.warning('missing permission to post onboarding prompt in guild %s (%s)', guild.id, guild.name)
    except Exception as exc:
        log.error('failed to post onboarding prompt in guild %s (%s): %s', guild.id, guild.name, exc)


if __name__ == '__main__':
    bot.run(os.getenv('BOT_TOKEN'))
