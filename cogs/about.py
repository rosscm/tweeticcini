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

    @app_commands.command(name='about', description='Show a compact Tweeticcini summary for this server')
    async def about(self, itn: discord.Interaction):
        if itn.guild_id is None or itn.guild is None:
            await itn.response.send_message(
                'Use this command inside a server to see that server summary.',
                ephemeral=True,
            )
            return

        presentation = await self.guild_settings_service.get_presentation_view(str(itn.guild_id))
        sources = await self.notifier_service.list_dashboard_sources(str(itn.guild_id))
        rules = await self.alert_rule_service.list_rules(str(itn.guild_id))
        sessions = await self.twitter_session_service.list_server_sessions(str(itn.guild_id))

        active_sessions = [session for session in sessions if session.is_active and session.status == 'active']
        style_label = 'Headline-style' if presentation.effective.use_headline_message else 'Template'

        embed = discord.Embed(
            title='About Tweeticcini',
            description='A quick server snapshot for your current setup.',
            color=0x4F7CAC,
        )
        embed.add_field(
            name='Server',
            value=itn.guild.name,
            inline=True,
        )
        embed.add_field(
            name='Plan',
            value=presentation.plan.capitalize(),
            inline=True,
        )
        embed.add_field(
            name='Tweet checks',
            value=f"Every {configs['tweets_check_period']}s",
            inline=True,
        )
        embed.add_field(
            name='Monitors',
            value=f'{len(sources)} / {presentation.features.max_sources}',
            inline=True,
        )
        embed.add_field(
            name='Rules',
            value=f'{len(rules)} / {presentation.features.max_rules}',
            inline=True,
        )
        embed.add_field(
            name='Sessions',
            value=f'{len(active_sessions)} / {presentation.features.max_twitter_sessions}',
            inline=True,
        )
        embed.add_field(
            name='Default style',
            value=style_label,
            inline=True,
        )
        embed.add_field(
            name='Bot reach',
            value=f'{len(self.bot.guilds)} server{"" if len(self.bot.guilds) == 1 else "s"}',
            inline=True,
        )
        embed.add_field(
            name='Source',
            value='Dashboard-first setup',
            inline=True,
        )
        embed.set_footer(text='Use /dashboard for full setup and billing controls.')

        view = None
        base_url = _get_dashboard_base_url()
        if base_url:
            view = discord.ui.View()
            view.add_item(
                discord.ui.Button(
                    label='Open Dashboard',
                    url=f'{base_url}/dashboard?guild_id={itn.guild_id}',
                )
            )

        await itn.response.send_message(embed=embed, view=view, ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(About(bot))
