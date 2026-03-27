import os

import discord
from discord import app_commands
from discord.ext import commands

from configs.load_configs import configs
from core.classes import Cog_Extension
from cogs.dashboard import _get_dashboard_base_url
from src.services.alert_rule_service import AlertRuleService
from src.services.guild_settings_service import GuildSettingsService
from src.services.notifier_service import NotifierService
from src.services.twitter_session_service import TwitterSessionService


class About(Cog_Extension):
    def __init__(self, bot):
        super().__init__(bot)
        self.guild_settings_service = GuildSettingsService()
        self.notifier_service = NotifierService()
        self.alert_rule_service = AlertRuleService()
        self.twitter_session_service = TwitterSessionService()

    @app_commands.command(name='about', description='Show a compact summary for this server')
    async def about(self, itn: discord.Interaction):
        if itn.guild_id is None or itn.guild is None:
            await itn.response.send_message(
                'Use this command inside a server to see that server summary.',
                ephemeral=True,
            )
            return

        await itn.response.defer(ephemeral=True)

        presentation = await self.guild_settings_service.get_presentation_view(str(itn.guild_id))
        sources = await self.notifier_service.list_dashboard_sources(str(itn.guild_id))
        rules = await self.alert_rule_service.list_rules(str(itn.guild_id))
        sessions = await self.twitter_session_service.list_server_sessions(str(itn.guild_id))

        active_sessions = [session for session in sessions if session.is_active and session.status == 'active']
        destination_count = len({source.channel_id for source in sources})
        style_label = 'Headline-style' if presentation.effective.use_headline_message else 'Template'
        entitlement_source = presentation.entitlement.plan_source.replace('_', ' ')
        plan_label = 'Premium' if presentation.plan == 'pro' else 'Free'
        plan_line = f'`{plan_label}` plan'
        if presentation.plan == 'pro':
            if presentation.entitlement.entitlement_status == 'trialing':
                plan_line = '`Premium` trial'
            elif entitlement_source not in {'default', 'legacy'}:
                plan_line = f'`Premium` plan via `{entitlement_source}`'
            elif entitlement_source == 'legacy':
                plan_line = '`Premium` plan via `legacy access`'

        embed = discord.Embed(
            title=itn.guild.name,
            description='📡 Keeping this server on top of the Twitter/X alerts it cares about.',
            color=0x4F7CAC,
        )
        embed.add_field(
            name='Plan & Style',
            value=(
                f'{plan_line}\n'
                f'`{style_label}` delivery style'
            ),
            inline=True,
        )
        embed.add_field(
            name='Setup',
            value=(
                f'Monitors: `{len(sources)} / {presentation.features.max_sources}`\n'
                f'Rules: `{len(rules)} / {presentation.features.max_rules}`\n'
                f'Sessions: `{len(active_sessions)} / {presentation.features.max_twitter_sessions}`\n'
                f'Channels: `{destination_count}`'
            ),
            inline=True,
        )
        if itn.guild.icon:
            embed.set_thumbnail(url=itn.guild.icon.url)
        embed.set_footer(
            text=(
                f'Built with ❤️ by Pokaccini • '
                f'Checks every {configs["tweets_check_period"]}s • '
                f'Connected in {len(self.bot.guilds)} server{"" if len(self.bot.guilds) == 1 else "s"}'
            )
        )

        view = None
        base_url = _get_dashboard_base_url()
        support_server_url = os.getenv('SUPPORT_SERVER_URL', '').strip()
        if base_url or support_server_url:
            view = discord.ui.View()
            if base_url:
                view.add_item(
                    discord.ui.Button(
                        label='Open Dashboard',
                        url=f'{base_url}/dashboard?guild_id={itn.guild_id}',
                    )
                )
            if support_server_url:
                view.add_item(
                    discord.ui.Button(
                        label='Support Server',
                        url=support_server_url,
                    )
                )

        await itn.followup.send(embed=embed, view=view, ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(About(bot))
