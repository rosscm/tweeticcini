import discord
from discord import app_commands
from discord.ext import commands

from configs.load_configs import configs
from core.classes import Cog_Extension
from src.discord_ui.modal import CustomizeMsgModal
from src.log import setup_logger
from src.notification.account_tracker import AccountTracker
from src.permission import ADMINISTRATOR
from src.presence_updater import update_presence
from src.services.notifier_service import (
    AddNotifierRequest,
    AutoChangeClientDisabledError,
    ChannelNotTrackedError,
    NotifierService,
    NotifierServiceError,
    RemoveNotifierRequest,
    UserNotFoundError,
)
from src.utils import get_accounts

log = setup_logger(__name__)


class UnknownChannel:
    def __init__(self, name: str, id: int):
        self.name = name
        self.id = id
        self.mention = f'<#{id}>'


class Notification(Cog_Extension):
    def __init__(self, bot):
        super().__init__(bot)
        self.account_tracker = AccountTracker(bot)
        self.notifier_service = NotifierService()

    add_group = app_commands.Group(name='add', description='Add something', default_permissions=ADMINISTRATOR)
    remove_group = app_commands.Group(name='remove', description='Remove something', default_permissions=ADMINISTRATOR)
    customize_group = app_commands.Group(name='customize', description='Customize something', default_permissions=ADMINISTRATOR)

    @add_group.command(name='notifier')
    @app_commands.choices(
        enable_type=[app_commands.Choice(name='All (default)', value='11'), app_commands.Choice(name='Tweet & Retweet Only', value='10'), app_commands.Choice(name='Tweet & Quote Only', value='01'), app_commands.Choice(name='Tweet Only', value='00')],
        media_type=[app_commands.Choice(name='All (default)', value='11'), app_commands.Choice(name='No Media', value='10'), app_commands.Choice(name='Media Only', value='01')],
        account_used=[app_commands.Choice(name=account_name, value=account_name) for account_name, _ in get_accounts().items()]
    )
    @app_commands.rename(enable_type='type')
    @app_commands.describe(
        username="Twitter username to track",
        channel="Channel where notifications are sent",
        mention="Role to mention in the notification",
        enable_type="Tweet/Retweet/Quote filtering",
        media_type="Media presence filter",
        account_used="Twitter session to use",
        force_everyone="Mention @everyone when tweet matches keywords"
    )
    async def notifier(
        self,
        itn: discord.Interaction,
        username: str,
        channel: discord.TextChannel,
        mention: discord.Role = None,
        enable_type: str = '11',
        media_type: str = '11',
        account_used: str = list(get_accounts().keys())[0],
        force_everyone: bool = False,
    ):
        """Add a twitter user to specific channel on your server."""

        await itn.response.defer(ephemeral=True)

        request = AddNotifierRequest(
            username=username,
            server_id=str(channel.guild.id),
            channel_id=str(channel.id),
            role_id=str(mention.id) if mention is not None else '',
            enable_type=enable_type,
            media_type=media_type,
            account_used=account_used,
            force_everyone=force_everyone,
        )

        try:
            result = await self.notifier_service.add_notifier(request)
        except UserNotFoundError:
            await itn.followup.send(f'user {username} not found', ephemeral=True)
            return
        except AutoChangeClientDisabledError:
            await itn.followup.send(
                f'user {username} already exists under {account_used}. No changes due to `auto_change_client` setting',
                ephemeral=True,
            )
            return
        except NotifierServiceError:
            await itn.followup.send('failed to add notifier, please try again later.', ephemeral=True)
            return

        if result.created_or_reactivated:
            await self.account_tracker.addTask(username, result.task_client_used)
            await update_presence(self.bot)

        await itn.followup.send(result.response_message, ephemeral=True)

    @remove_group.command(name='notifier')
    @app_commands.rename(channel_id='channel')
    async def r_notifier(self, itn: discord.Interaction, channel_id: str, username: str):
        """Remove a notifier on your server.

        Parameters
        -----------
        channel_id: str
            The channel id which is set to delivers notifications.
        username: str
            The username of the twitter user you want to turn off notifications for.
        """

        channel = itn.guild.get_channel(int(channel_id))
        if channel is None:
            channel = UnknownChannel('unknown', int(channel_id))
        await itn.response.defer(ephemeral=True)

        request = RemoveNotifierRequest(
            username=username,
            server_id=str(itn.guild_id),
            channel_id=str(channel.id),
            guild_name=str(itn.guild.name),
        )

        try:
            result = await self.notifier_service.remove_notifier(request)
        except ChannelNotTrackedError:
            await itn.followup.send(f'can\'t find channel {channel.mention} in {str(itn.guild.name)}!', ephemeral=True)
            return
        except NotifierServiceError:
            await itn.followup.send('failed to remove notifier, please try again later.', ephemeral=True)
            return

        if result.removed_last_notifier:
            await self.account_tracker.removeTask(username)
            if result.client_used and (configs['auto_unfollow'] or configs['auto_turn_off_notification']):
                await self.notifier_service.disable_remote_notification(username, result.client_used)
            await update_presence(self.bot)

        await itn.followup.send(result.response_message, ephemeral=True)

    @customize_group.command(name='message')
    @app_commands.rename(channel_id='channel')
    async def customize_message(self, itn: discord.Interaction, channel_id: str, username: str, default: bool = False):
        """Set customized messages for notification.

        Parameters
        -----------
        channel_id: discord.TextChannel
            The channel id which set to delivers notifications.
        username: str
            The username of the twitter user you want to set customized message.
        default: bool
            Whether to use default setting.
        """
        channel = itn.guild.get_channel(int(channel_id))
        if channel is None:
            channel = UnknownChannel('unknown', int(channel_id))
        user_id = await self.notifier_service.get_enabled_notifier_user_id(username, str(channel.id))
        if user_id is None:
            await itn.response.send_message(f'can\'t find notifier {username} in {channel.mention}!', ephemeral=True)
            return

        if default:
            await itn.response.defer(ephemeral=True)
            await self.notifier_service.reset_custom_message(user_id, str(channel.id))
            await itn.followup.send('successfully restored to default settings', ephemeral=True)
        else:
            modal = CustomizeMsgModal(user_id, username, channel)
            await itn.response.send_modal(modal)

    @r_notifier.autocomplete('channel_id')
    async def get_channels_for_r_notifier(self, itn: discord.Interaction, input_channel: str) -> list[app_commands.Choice[str]]:
        return await self._fetch_tracked_channels(itn, input_channel, include_unknown=True)

    @customize_message.autocomplete('channel_id')
    async def get_channels_for_customize_message(self, itn: discord.Interaction, input_channel: str) -> list[app_commands.Choice[str]]:
        return await self._fetch_tracked_channels(itn, input_channel, include_unknown=False)

    async def _fetch_tracked_channels(self, itn: discord.Integration, input_channel: str, include_unknown: bool):
        channel_ids = await self.notifier_service.get_active_channel_ids_for_server(str(itn.guild_id))
        result = []
        for channel_id in channel_ids:
            channel = itn.guild.get_channel(int(channel_id))
            if channel:
                result.append(channel)
            elif include_unknown:
                result.append(UnknownChannel('unknown', int(channel_id)))
        return [app_commands.Choice(name=f'# {channel.name}', value=str(channel.id)) if isinstance(channel, discord.TextChannel) else
                app_commands.Choice(name=f'# unknown ({channel.id})', value=str(channel.id))
                for channel in result if input_channel.lower().replace("#", "") in channel.name.lower()]

    @r_notifier.autocomplete('username')
    @customize_message.autocomplete('username')
    async def get_enabled_users(self, itn: discord.Interaction, username: str) -> list[app_commands.Choice[str]]:
        selected_channel_id = itn.data['options'][0]['options'][0]['value']
        if selected_channel_id is None:
            return []

        users = await self.notifier_service.get_enabled_usernames_for_channel(selected_channel_id)
        return [app_commands.Choice(name=row, value=row) for row in users if username.lower() in row.lower()]


async def setup(bot: commands.Bot):
    await bot.add_cog(Notification(bot))
