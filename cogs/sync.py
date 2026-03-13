import discord
from discord import app_commands
from discord.ext import commands

from core.classes import Cog_Extension
from src.log import setup_logger
from src.repositories.notifier_repository import get_all_user_client_map
from src.sync_db.sync_db import sync_db
from src.settings import get_db_path

log = setup_logger(__name__)


class Sync(Cog_Extension):

    @app_commands.default_permissions(administrator=True)
    @app_commands.command(name='sync')
    async def sync(self, itn: discord.Interaction):
        """To sync the notification of new Twitter account with database, use this command."""

        await itn.response.defer(ephemeral=True)

        follow_list = await get_all_user_client_map(get_db_path())

        self.bot.loop.create_task(sync_db(follow_list))

        await itn.followup.send('synchronizing in the background', ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(Sync(bot))
