from dataclasses import dataclass
from typing import Optional

from src.db_function.guild_settings import (
    EffectiveGuildPresentationSettings,
    get_default_guild_presentation_settings,
)
from src.repositories.guild_settings_repository import (
    get_guild_settings_row,
    upsert_guild_settings,
)
from src.settings import get_db_path


PLAN_FREE = 'free'
PLAN_PRO = 'pro'
SUPPORTED_PLANS = {PLAN_FREE, PLAN_PRO}


@dataclass(frozen=True)
class GuildPlanFeatures:
    max_sources: int
    max_rules: int
    max_trigger_keywords_total: int
    max_exclude_keywords_total: int
    can_customize_presentation: bool


PLAN_FEATURES = {
    PLAN_FREE: GuildPlanFeatures(
        max_sources=3,
        max_rules=3,
        max_trigger_keywords_total=5,
        max_exclude_keywords_total=20,
        can_customize_presentation=False,
    ),
    PLAN_PRO: GuildPlanFeatures(
        max_sources=25,
        max_rules=50,
        max_trigger_keywords_total=150,
        max_exclude_keywords_total=500,
        can_customize_presentation=True,
    ),
}


@dataclass(frozen=True)
class GuildPresentationView:
    plan: str
    features: GuildPlanFeatures
    effective: EffectiveGuildPresentationSettings
    has_overrides: bool


class GuildSettingsService:
    def __init__(self, db_path=None):
        self.db_path = db_path or get_db_path()

    async def get_presentation_view(self, server_id: str) -> GuildPresentationView:
        row = await get_guild_settings_row(self.db_path, server_id)
        plan = self._normalize_plan(row['plan'] if row is not None else None)
        defaults = get_default_guild_presentation_settings()

        if row is None:
            return GuildPresentationView(
                plan=plan,
                features=PLAN_FEATURES[plan],
                effective=defaults,
                has_overrides=False,
            )

        effective = EffectiveGuildPresentationSettings(
            default_message=row['default_message_override'] or defaults.default_message,
            emoji_auto_format=defaults.emoji_auto_format if row['emoji_auto_format_override'] is None else bool(row['emoji_auto_format_override']),
            embed_type=row['embed_type_override'] or defaults.embed_type,
            built_in_fx_image=defaults.built_in_fx_image if row['built_in_fx_image_override'] is None else bool(row['built_in_fx_image_override']),
            built_in_video_link_button=defaults.built_in_video_link_button if row['built_in_video_link_button_override'] is None else bool(row['built_in_video_link_button_override']),
            built_in_legacy_logo=defaults.built_in_legacy_logo if row['built_in_legacy_logo_override'] is None else bool(row['built_in_legacy_logo_override']),
            fx_domain_name=row['fx_domain_name_override'] or defaults.fx_domain_name,
            fx_original_url_button=defaults.fx_original_url_button if row['fx_original_url_button_override'] is None else bool(row['fx_original_url_button_override']),
        )

        return GuildPresentationView(
            plan=plan,
            features=PLAN_FEATURES[plan],
            effective=effective,
            has_overrides=self._row_has_presentation_overrides(row),
        )

    async def set_plan(self, server_id: str, plan: str) -> GuildPresentationView:
        normalized_plan = self._normalize_plan(plan)
        row = await get_guild_settings_row(self.db_path, server_id)
        await upsert_guild_settings(
            self.db_path,
            server_id=server_id,
            plan=normalized_plan,
            default_message_override=row['default_message_override'] if row is not None else None,
            emoji_auto_format_override=row['emoji_auto_format_override'] if row is not None else None,
            embed_type_override=row['embed_type_override'] if row is not None else None,
            built_in_fx_image_override=row['built_in_fx_image_override'] if row is not None else None,
            built_in_video_link_button_override=row['built_in_video_link_button_override'] if row is not None else None,
            built_in_legacy_logo_override=row['built_in_legacy_logo_override'] if row is not None else None,
            fx_domain_name_override=row['fx_domain_name_override'] if row is not None else None,
            fx_original_url_button_override=row['fx_original_url_button_override'] if row is not None else None,
        )
        return await self.get_presentation_view(server_id)

    async def update_presentation(
        self,
        server_id: str,
        default_message: str,
        emoji_auto_format: bool,
        embed_type: str,
        built_in_fx_image: bool,
        built_in_video_link_button: bool,
        built_in_legacy_logo: bool,
        fx_domain_name: str,
        fx_original_url_button: bool,
    ) -> GuildPresentationView:
        current = await self.get_presentation_view(server_id)
        if not current.features.can_customize_presentation:
            raise ValueError('presentation customization requires a paid plan')

        defaults = get_default_guild_presentation_settings()
        sanitized_embed_type = embed_type if embed_type in {'built_in', 'fx_twitter'} else defaults.embed_type
        sanitized_fx_domain = fx_domain_name if fx_domain_name in {'fxtwitter', 'fixupx'} else defaults.fx_domain_name
        normalized_message = default_message.strip() or defaults.default_message

        await upsert_guild_settings(
            self.db_path,
            server_id=server_id,
            plan=current.plan,
            default_message_override=None if normalized_message == defaults.default_message else normalized_message,
            emoji_auto_format_override=None if emoji_auto_format == defaults.emoji_auto_format else int(emoji_auto_format),
            embed_type_override=None if sanitized_embed_type == defaults.embed_type else sanitized_embed_type,
            built_in_fx_image_override=None if built_in_fx_image == defaults.built_in_fx_image else int(built_in_fx_image),
            built_in_video_link_button_override=None if built_in_video_link_button == defaults.built_in_video_link_button else int(built_in_video_link_button),
            built_in_legacy_logo_override=None if built_in_legacy_logo == defaults.built_in_legacy_logo else int(built_in_legacy_logo),
            fx_domain_name_override=None if sanitized_fx_domain == defaults.fx_domain_name else sanitized_fx_domain,
            fx_original_url_button_override=None if fx_original_url_button == defaults.fx_original_url_button else int(fx_original_url_button),
        )
        return await self.get_presentation_view(server_id)

    @staticmethod
    def _normalize_plan(plan: Optional[str]) -> str:
        if plan in SUPPORTED_PLANS:
            return plan
        return PLAN_FREE

    @staticmethod
    def _row_has_presentation_overrides(row) -> bool:
        if row is None:
            return False
        return any(
            row[column] is not None
            for column in (
                'default_message_override',
                'emoji_auto_format_override',
                'embed_type_override',
                'built_in_fx_image_override',
                'built_in_video_link_button_override',
                'built_in_legacy_logo_override',
                'fx_domain_name_override',
                'fx_original_url_button_override',
            )
        )
