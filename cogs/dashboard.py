import os
from typing import Optional
from urllib.parse import urlparse

import discord
from discord import app_commands
from discord.ext import commands

from core.classes import Cog_Extension


def _get_dashboard_base_url() -> Optional[str]:
    explicit_url = os.getenv('DASHBOARD_BASE_URL', '').strip()
    if explicit_url:
        return explicit_url.rstrip('/')

    redirect_uri = os.getenv('DISCORD_REDIRECT_URI', '').strip()
    if not redirect_uri:
        return None

    parsed = urlparse(redirect_uri)
    if not parsed.scheme or not parsed.netloc:
        return None

    return f'{parsed.scheme}://{parsed.netloc}'


class Dashboard(Cog_Extension):
    @app_commands.default_permissions(administrator=True)
    @app_commands.command(name='dashboard', description='Get a link to the configuration dashboard')
    async def dashboard(self, itn: discord.Interaction):
        base_url = _get_dashboard_base_url()
        if not base_url:
            await itn.response.send_message(
                'The dashboard URL is not configured yet. Set `DASHBOARD_BASE_URL` or `DISCORD_REDIRECT_URI` first.',
                ephemeral=True,
            )
            return

        if itn.guild_id is None:
            await itn.response.send_message(
                'Use this command inside a server to open that server dashboard.',
                ephemeral=True,
            )
            return

        dashboard_url = f'{base_url}/dashboard?guild_id={itn.guild_id}'
        view = discord.ui.View()
        view.add_item(discord.ui.Button(label='Open Dashboard', url=dashboard_url))

        await itn.response.send_message(ephemeral=True, view=view)


async def setup(bot: commands.Bot):
    await bot.add_cog(Dashboard(bot))
