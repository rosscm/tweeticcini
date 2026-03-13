import discord
from discord import app_commands
from discord.ext import commands

from core.classes import Cog_Extension
from configs.load_configs import configs
from src.repositories.notifier_repository import (
    get_enabled_client_names,
    get_server_channel_ids,
    list_server_notifications,
)
from src.permission import ADMINISTRATOR
from src.utils import str_to_bool as stb
from src.discord_ui.pagination import Pagination
from src.settings import get_db_path

CHECK = '\u2705'
XMARK = '\u274C'
PSIZE = configs['users_list_pagination_size']
PCPOS = configs['users_list_page_counter_position'] if configs['users_list_page_counter_position'] in ['title', 'footer'] else 'title'


def symbol(value: str) -> str:
    return CHECK if stb(value) else XMARK


class ListUsers(Cog_Extension):

    list_group = app_commands.Group(name='list', description='List something', default_permissions=ADMINISTRATOR)

    @list_group.command(name='users')
    async def list_users(self, itn: discord.Interaction, account: str = '', channel: str = '') -> None:
        """Lists all exists notifier on your server.

        Parameters:
        account: str, optional
            The client name that you want to filter.
        channel: str, optional
            The channel name that you want to filter.
        """

        server_id = itn.guild_id

        user_channel_role_data = await list_server_notifications(get_db_path(), str(server_id), account, channel)

        formatted_data = [
            f"{i + 1}. ```{username}``` <#{channel_id}>{f' <@&{role_id}>' if role_id else ''} {symbol(enable_type[0])}retweet {symbol(enable_type[1])}quote {symbol(enable_media_type[0])}text {symbol(enable_media_type[1])}media, using {client_used}"
            for i, (username, channel_id, role_id, enable_type, enable_media_type, client_used) in enumerate(user_channel_role_data)
        ]

        async def get_page(page: int):
            offset = (page - 1) * PSIZE
            page_data = formatted_data[offset:offset + PSIZE]
            total_pages = Pagination.compute_total_pages(len(formatted_data), PSIZE)
            title = f"Notification List in __***{itn.guild.name}***__{f'  Page [{page}/{total_pages}]' if PCPOS == 'title' else ''}"
            descriptions = '***No users are registered on this server.***' if not formatted_data else "\n".join(page_data)
            embed = discord.Embed(title=title, description=descriptions, color=0x778899)
            if PCPOS == 'footer':
                embed.set_footer(text=f"Page {page} of {total_pages}")
            return embed, total_pages

        await Pagination(itn, get_page).navegate()

    @list_users.autocomplete('account')
    async def get_clients(self, itn: discord.Interaction, account: str) -> list[app_commands.Choice[str]]:
        client_used = await get_enabled_client_names(get_db_path())
        return [app_commands.Choice(name=row, value=row) for row in client_used if account.lower() in row.lower()]

    @list_users.autocomplete('channel')
    async def get_channel(self, itn: discord.Interaction, input_channel: str) -> list[app_commands.Choice[str]]:
        channel_ids = await get_server_channel_ids(get_db_path(), str(itn.guild_id))
        channel_list = [itn.guild.get_channel(int(channel_id)) for channel_id in channel_ids]
        return [app_commands.Choice(name=f'#{channel.name}', value=str(channel.id)) for channel in channel_list if channel is not None and input_channel.lower() in channel.name.lower()]


async def setup(bot: commands.Bot):
    await bot.add_cog(ListUsers(bot))
