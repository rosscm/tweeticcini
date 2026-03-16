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
from src.services.alert_rule_service import AlertRuleService
from src.services.guild_settings_service import GuildSettingsService
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
        self.alert_rule_service = AlertRuleService()
        self.guild_settings_service = GuildSettingsService()
        self.notifier_service = NotifierService()

    add_group = app_commands.Group(name='add', description='Add something', default_permissions=ADMINISTRATOR)
    remove_group = app_commands.Group(name='remove', description='Remove something', default_permissions=ADMINISTRATOR)
    customize_group = app_commands.Group(name='customize', description='Customize something', default_permissions=ADMINISTRATOR)
    rule_group = app_commands.Group(name='rule', description='Manage alert rules', default_permissions=ADMINISTRATOR)
    settings_group = app_commands.Group(name='settings', description='Manage server settings', default_permissions=ADMINISTRATOR)

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

    @rule_group.command(name='list')
    async def list_rules(self, itn: discord.Interaction):
        await itn.response.defer(ephemeral=True)
        rules = await self.alert_rule_service.list_rules(str(itn.guild_id))
        if not rules:
            await itn.followup.send('no alert rules configured for this server', ephemeral=True)
            return

        lines = []
        for rule in rules:
            scope = rule.source_username or 'all sources'
            channel = f' <#{rule.channel_id}>' if rule.channel_id else ''
            triggers = ', '.join(rule.trigger_keywords) if rule.trigger_keywords else 'none'
            excludes = ', '.join(rule.exclude_keywords) if rule.exclude_keywords else 'none'
            lines.append(
                f"**{rule.rule_name}**: source=`{scope}`{channel}, priority=`{rule.priority}`, escalation=`{rule.escalation_mode}`, triggers=`{triggers}`, excludes=`{excludes}`"
            )

        embed = discord.Embed(
            title=f'Alert Rules for {itn.guild.name}',
            description='\n'.join(lines),
            color=0x4f7cac,
        )
        await itn.followup.send(embed=embed, ephemeral=True)

    @rule_group.command(name='upsert')
    @app_commands.choices(
        escalation_mode=[
            app_commands.Choice(name='Inherit Guild Default', value='inherit'),
            app_commands.Choice(name='Force Everyone', value='everyone'),
            app_commands.Choice(name='Role Only', value='role_only'),
        ]
    )
    async def upsert_rule(
        self,
        itn: discord.Interaction,
        rule_name: str,
        source_username: str,
        escalation_mode: str = 'inherit',
        trigger_keywords: str = '',
        exclude_keywords: str = '',
        channel: discord.TextChannel = None,
        priority: app_commands.Range[int, -100, 100] = 0,
    ):
        await itn.response.defer(ephemeral=True)

        def parse_keywords(raw: str) -> list[str]:
            return [part.strip() for part in raw.split(',') if part.strip()]

        await self.alert_rule_service.upsert_rule(
            server_id=str(itn.guild_id),
            rule_name=rule_name,
            source_username=source_username.strip() or None,
            channel_id=str(channel.id) if channel is not None else None,
            priority=priority,
            trigger_keywords=parse_keywords(trigger_keywords),
            exclude_keywords=parse_keywords(exclude_keywords),
            escalation_mode=escalation_mode,
        )

        await itn.followup.send(f'upserted alert rule `{rule_name}`', ephemeral=True)

    @rule_group.command(name='remove')
    async def remove_rule(self, itn: discord.Interaction, rule_name: str):
        await itn.response.defer(ephemeral=True)
        deleted = await self.alert_rule_service.delete_rule(str(itn.guild_id), rule_name)
        if deleted:
            await itn.followup.send(f'removed alert rule `{rule_name}`', ephemeral=True)
        else:
            await itn.followup.send(f'could not find alert rule `{rule_name}`', ephemeral=True)

    @remove_rule.autocomplete('rule_name')
    async def autocomplete_rule_name(self, itn: discord.Interaction, rule_name: str) -> list[app_commands.Choice[str]]:
        names = await self.alert_rule_service.get_rule_names(str(itn.guild_id))
        return [app_commands.Choice(name=name, value=name) for name in names if rule_name.lower() in name.lower()]

    @settings_group.command(name='view')
    async def view_settings(self, itn: discord.Interaction):
        await itn.response.defer(ephemeral=True)
        settings_view = await self.guild_settings_service.get_settings_view(str(itn.guild_id))
        effective = settings_view.effective

        trigger_keywords = ', '.join(effective.keywords_triggering_everyone) if effective.keywords_triggering_everyone else 'none'
        exclude_keywords = ', '.join(effective.keywords_excluded) if effective.keywords_excluded else 'none'
        source = 'legacy configs.yml fallback' if settings_view.uses_legacy_defaults else 'guild database settings'

        embed = discord.Embed(
            title=f'Settings for {itn.guild.name}',
            color=0x708090,
        )
        embed.add_field(name='Source', value=source, inline=False)
        embed.add_field(name='force_everyone_default', value=str(effective.force_everyone_default), inline=False)
        embed.add_field(name='keywords_triggering_everyone', value=trigger_keywords[:1024], inline=False)
        embed.add_field(name='keywords_excluded', value=exclude_keywords[:1024], inline=False)
        await itn.followup.send(embed=embed, ephemeral=True)

    @settings_group.command(name='bootstrap_alerts')
    async def bootstrap_alerts(self, itn: discord.Interaction):
        await itn.response.defer(ephemeral=True)
        _, created = await self.guild_settings_service.bootstrap_from_legacy_defaults(str(itn.guild_id))
        if created:
            await itn.followup.send('copied the current legacy alert defaults into this server\'s database settings', ephemeral=True)
        else:
            await itn.followup.send('this server already has database-backed alert settings', ephemeral=True)

    @settings_group.command(name='set_force_everyone_default')
    async def set_force_everyone_default(self, itn: discord.Interaction, value: bool):
        await itn.response.defer(ephemeral=True)
        updated = await self.guild_settings_service.update_settings(
            str(itn.guild_id),
            force_everyone_default=value,
        )
        await itn.followup.send(
            f'updated `force_everyone_default` to `{updated.force_everyone_default}` for this server',
            ephemeral=True,
        )

    @settings_group.command(name='set_trigger_keywords')
    async def set_trigger_keywords(self, itn: discord.Interaction, keywords: str):
        await itn.response.defer(ephemeral=True)
        parsed = self._parse_keywords(keywords)
        await self.guild_settings_service.update_settings(
            str(itn.guild_id),
            keywords_triggering_everyone=parsed,
        )
        await itn.followup.send(
            f'updated trigger keywords for this server to: `{", ".join(parsed) if parsed else "none"}`',
            ephemeral=True,
        )

    @settings_group.command(name='set_exclude_keywords')
    async def set_exclude_keywords(self, itn: discord.Interaction, keywords: str):
        await itn.response.defer(ephemeral=True)
        parsed = self._parse_keywords(keywords)
        await self.guild_settings_service.update_settings(
            str(itn.guild_id),
            keywords_excluded=parsed,
        )
        await itn.followup.send(
            f'updated exclude keywords for this server to: `{", ".join(parsed) if parsed else "none"}`',
            ephemeral=True,
        )

    @settings_group.command(name='reset_alerts')
    async def reset_alerts(self, itn: discord.Interaction):
        await itn.response.defer(ephemeral=True)
        reset = await self.guild_settings_service.reset_to_legacy_defaults(str(itn.guild_id))
        if reset:
            await itn.followup.send('removed this server\'s database-backed alert settings and restored legacy fallback behavior', ephemeral=True)
        else:
            await itn.followup.send('this server was already using legacy fallback behavior', ephemeral=True)

    @staticmethod
    def _parse_keywords(raw: str) -> list[str]:
        return [part.strip() for part in raw.split(',') if part.strip()]


async def setup(bot: commands.Bot):
    await bot.add_cog(Notification(bot))
