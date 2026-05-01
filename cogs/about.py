import os

import discord
from discord import app_commands
from discord.ext import commands

from configs.load_configs import configs
from core.classes import Cog_Extension
from cogs.dashboard import _get_dashboard_base_url, _get_top_gg_vote_url
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

    @staticmethod
    def _base_poll_interval() -> int:
        return max(int(configs.get('tweets_check_period', 12) or 12), 1)

    @classmethod
    def _free_poll_interval(cls) -> int:
        configured = max(int(configs.get('free_tweets_check_period', 90) or 90), 1)
        return max(configured, cls._base_poll_interval())

    @classmethod
    def _plus_poll_interval(cls) -> int:
        configured = max(int(configs.get('plus_tweets_check_period', 45) or 45), 1)
        return max(configured, cls._base_poll_interval())

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
        if presentation.plan == 'pro':
            plan_label = 'Premium'
            poll_interval = self._base_poll_interval()
        elif presentation.plan == 'plus':
            plan_label = 'Plus'
            poll_interval = self._plus_poll_interval()
        else:
            plan_label = 'Free'
            poll_interval = self._free_poll_interval()
        rule_setup_line = (
            'Rules: `Locked`'
            if presentation.features.max_rules == 0
            else f'Rules: `{len(rules)} / {presentation.features.max_rules}`'
        )
        plan_line = f'`{plan_label}` plan'
        if presentation.plan in {'pro', 'plus'}:
            if presentation.entitlement.entitlement_status == 'trialing':
                plan_line = f'`{plan_label}` trial'
            elif entitlement_source not in {'default', 'legacy'}:
                plan_line = f'`{plan_label}` plan via `{entitlement_source}`'
            elif entitlement_source == 'legacy':
                plan_line = f'`{plan_label}` plan via `legacy access`'

        embed = discord.Embed(
            title=itn.guild.name,
            description='📡 Keeping this server on top of the Twitter alerts it cares about.',
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
                f'Sessions: `{len(active_sessions)} / {presentation.features.max_twitter_sessions}`\n'
                f'Monitors: `{len(sources)} / {presentation.features.max_sources}`\n'
                f'{rule_setup_line}\n'
                f'Channels: `{destination_count}`'
            ),
            inline=True,
        )
        embed.add_field(
            name='Runtime',
            value=(
                f'Checks every `{poll_interval}s`\n'
                f'Connected in `{len(self.bot.guilds)}` server{"" if len(self.bot.guilds) == 1 else "s"}'
            ),
            inline=True,
        )
        if itn.guild.icon:
            embed.set_thumbnail(url=itn.guild.icon.url)
        embed.set_footer(
            text='Built with ❤️ by Pokaccini'
        )

        view = None
        base_url = _get_dashboard_base_url()
        support_server_url = os.getenv('SUPPORT_SERVER_URL', '').strip()
        vote_url = _get_top_gg_vote_url()
        if base_url or support_server_url or vote_url:
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
            if vote_url:
                view.add_item(
                    discord.ui.Button(
                        label='Vote on top.gg',
                        url=vote_url,
                    )
                )

        await itn.followup.send(embed=embed, view=view, ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(About(bot))
