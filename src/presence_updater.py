import discord

from discord.ext import commands
from configs.load_configs import configs


async def update_presence(bot: commands.Bot):
    """
    Updates the bot's presence based on the number of connected Discord servers.
    """
    count = len(bot.guilds)
    presence_message = configs["activity_name"].format(count=str(count))
    await bot.change_presence(activity=discord.Activity(name=presence_message, type=getattr(discord.ActivityType, configs['activity_type'])))
