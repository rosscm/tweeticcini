from dataclasses import dataclass
from typing import Optional

from src.db_function.guild_settings import (
    EffectiveGuildPresentationSettings,
    get_default_guild_presentation_settings,
)
from src.repositories.guild_entitlement_repository import (
    get_guild_entitlement_row,
    upsert_guild_entitlement,
)
from src.repositories.guild_settings_repository import (
    get_guild_settings_row,
    upsert_guild_settings,
)
from src.settings import get_db_path
from src.utils import get_utcnow


PLAN_FREE = 'free'
PLAN_PRO = 'pro'
SUPPORTED_PLANS = {PLAN_FREE, PLAN_PRO}
SUPPORTED_ENTITLEMENT_STATUSES = {'none', 'trialing', 'active', 'past_due', 'canceled'}


@dataclass(frozen=True)
class GuildPlanFeatures:
    max_twitter_sessions: int
    max_sources: int
    max_rules: int
    max_trigger_keywords_total: int
    max_exclude_keywords_total: int
    can_customize_presentation: bool
    can_customize_source_messages: bool
    can_use_everyone_escalation: bool


PLAN_FEATURES = {
    PLAN_FREE: GuildPlanFeatures(
        max_twitter_sessions=1,
        max_sources=3,
        max_rules=3,
        max_trigger_keywords_total=5,
        max_exclude_keywords_total=5,
        can_customize_presentation=False,
        can_customize_source_messages=False,
        can_use_everyone_escalation=False,
    ),
    PLAN_PRO: GuildPlanFeatures(
        max_twitter_sessions=5,
        max_sources=25,
        max_rules=50,
        max_trigger_keywords_total=150,
        max_exclude_keywords_total=500,
        can_customize_presentation=True,
        can_customize_source_messages=True,
        can_use_everyone_escalation=True,
    ),
}


@dataclass(frozen=True)
class GuildPresentationView:
    plan: str
    features: GuildPlanFeatures
    effective: EffectiveGuildPresentationSettings
    has_overrides: bool
    entitlement: 'GuildEntitlementView'


@dataclass(frozen=True)
class GuildEntitlementView:
    effective_plan: str
    plan_source: str
    entitlement_status: str
    subscribed_plan: Optional[str]
    manual_plan_override: Optional[str]
    billing_provider: Optional[str]
    external_customer_id: Optional[str]
    external_subscription_id: Optional[str]
    current_period_end: Optional[str]
    trial_ends_at: Optional[str]
    is_test: bool


class GuildSettingsService:
    def __init__(self, db_path=None):
        self.db_path = db_path or get_db_path()

    async def get_presentation_view(self, server_id: str) -> GuildPresentationView:
        row = await get_guild_settings_row(self.db_path, server_id)
        entitlement = await self.get_entitlement_view(server_id)
        plan = entitlement.effective_plan
        defaults = get_default_guild_presentation_settings()

        if row is None:
            return GuildPresentationView(
                plan=plan,
                features=PLAN_FEATURES[plan],
                effective=defaults,
                has_overrides=False,
                entitlement=entitlement,
            )

        effective = EffectiveGuildPresentationSettings(
            default_message=row['default_message_override'] or defaults.default_message,
            bot_display_name=row['bot_display_name_override'] or defaults.bot_display_name,
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
            entitlement=entitlement,
        )

    async def set_plan_override(self, server_id: str, plan: Optional[str]) -> GuildPresentationView:
        normalized_override = None if plan is None else self._normalize_plan(plan)
        entitlement = await get_guild_entitlement_row(self.db_path, server_id)
        legacy_row = await get_guild_settings_row(self.db_path, server_id)
        await upsert_guild_entitlement(
            self.db_path,
            server_id=server_id,
            subscribed_plan=entitlement['subscribed_plan'] if entitlement is not None else None,
            manual_plan_override=normalized_override,
            entitlement_status=entitlement['entitlement_status'] if entitlement is not None else 'none',
            billing_provider=entitlement['billing_provider'] if entitlement is not None else None,
            external_customer_id=entitlement['external_customer_id'] if entitlement is not None else None,
            external_subscription_id=entitlement['external_subscription_id'] if entitlement is not None else None,
            current_period_end=entitlement['current_period_end'] if entitlement is not None else None,
            trial_ends_at=entitlement['trial_ends_at'] if entitlement is not None else None,
            is_test=entitlement['is_test'] if entitlement is not None else 1,
            updated_at=get_utcnow(),
        )

        # Keep legacy plan in sync during the transition so older codepaths and local data stay coherent.
        if legacy_row is not None or normalized_override is not None:
            await upsert_guild_settings(
                self.db_path,
                server_id=server_id,
                plan=normalized_override or PLAN_FREE,
                default_message_override=legacy_row['default_message_override'] if legacy_row is not None else None,
                bot_display_name_override=legacy_row['bot_display_name_override'] if legacy_row is not None else None,
                emoji_auto_format_override=legacy_row['emoji_auto_format_override'] if legacy_row is not None else None,
                embed_type_override=legacy_row['embed_type_override'] if legacy_row is not None else None,
                built_in_fx_image_override=legacy_row['built_in_fx_image_override'] if legacy_row is not None else None,
                built_in_video_link_button_override=legacy_row['built_in_video_link_button_override'] if legacy_row is not None else None,
                built_in_legacy_logo_override=legacy_row['built_in_legacy_logo_override'] if legacy_row is not None else None,
                fx_domain_name_override=legacy_row['fx_domain_name_override'] if legacy_row is not None else None,
                fx_original_url_button_override=legacy_row['fx_original_url_button_override'] if legacy_row is not None else None,
            )
        return await self.get_presentation_view(server_id)

    async def set_plan(self, server_id: str, plan: str) -> GuildPresentationView:
        normalized_plan = self._normalize_plan(plan)
        return await self.set_plan_override(server_id, normalized_plan)

    async def get_entitlement_view(self, server_id: str) -> GuildEntitlementView:
        row = await get_guild_entitlement_row(self.db_path, server_id)
        legacy_row = await get_guild_settings_row(self.db_path, server_id)

        if row is not None and row['manual_plan_override'] in SUPPORTED_PLANS:
            return GuildEntitlementView(
                effective_plan=row['manual_plan_override'],
                plan_source='manual_override',
                entitlement_status=row['entitlement_status'] or 'none',
                subscribed_plan=row['subscribed_plan'],
                manual_plan_override=row['manual_plan_override'],
                billing_provider=row['billing_provider'],
                external_customer_id=row['external_customer_id'],
                external_subscription_id=row['external_subscription_id'],
                current_period_end=row['current_period_end'],
                trial_ends_at=row['trial_ends_at'],
                is_test=bool(row['is_test']),
            )

        if row is not None and row['subscribed_plan'] in SUPPORTED_PLANS and (row['entitlement_status'] in {'active', 'trialing'}):
            return GuildEntitlementView(
                effective_plan=row['subscribed_plan'],
                plan_source='subscription',
                entitlement_status=row['entitlement_status'],
                subscribed_plan=row['subscribed_plan'],
                manual_plan_override=row['manual_plan_override'],
                billing_provider=row['billing_provider'],
                external_customer_id=row['external_customer_id'],
                external_subscription_id=row['external_subscription_id'],
                current_period_end=row['current_period_end'],
                trial_ends_at=row['trial_ends_at'],
                is_test=bool(row['is_test']),
            )

        legacy_plan = self._normalize_plan(legacy_row['plan'] if legacy_row is not None else None)
        plan_source = 'legacy' if legacy_row is not None and legacy_row['plan'] in SUPPORTED_PLANS else 'default'
        return GuildEntitlementView(
            effective_plan=legacy_plan,
            plan_source=plan_source,
            entitlement_status=row['entitlement_status'] if row is not None and row['entitlement_status'] else 'none',
            subscribed_plan=row['subscribed_plan'] if row is not None else None,
            manual_plan_override=row['manual_plan_override'] if row is not None else None,
            billing_provider=row['billing_provider'] if row is not None else None,
            external_customer_id=row['external_customer_id'] if row is not None else None,
            external_subscription_id=row['external_subscription_id'] if row is not None else None,
            current_period_end=row['current_period_end'] if row is not None else None,
            trial_ends_at=row['trial_ends_at'] if row is not None else None,
            is_test=bool(row['is_test']) if row is not None else True,
        )

    async def set_subscription_entitlement(
        self,
        server_id: str,
        subscribed_plan: Optional[str],
        entitlement_status: str,
        billing_provider: Optional[str] = None,
        external_customer_id: Optional[str] = None,
        external_subscription_id: Optional[str] = None,
        current_period_end: Optional[str] = None,
        trial_ends_at: Optional[str] = None,
        is_test: bool = False,
    ) -> GuildPresentationView:
        normalized_plan = None if subscribed_plan is None else self._normalize_plan(subscribed_plan)
        normalized_status = self._normalize_entitlement_status(entitlement_status)
        current = await get_guild_entitlement_row(self.db_path, server_id)
        await upsert_guild_entitlement(
            self.db_path,
            server_id=server_id,
            subscribed_plan=normalized_plan,
            manual_plan_override=current['manual_plan_override'] if current is not None else None,
            entitlement_status=normalized_status,
            billing_provider=billing_provider,
            external_customer_id=external_customer_id if external_customer_id is not None else (current['external_customer_id'] if current is not None else None),
            external_subscription_id=external_subscription_id if external_subscription_id is not None else (current['external_subscription_id'] if current is not None else None),
            current_period_end=current_period_end,
            trial_ends_at=trial_ends_at,
            is_test=int(is_test),
            updated_at=get_utcnow(),
        )
        return await self.get_presentation_view(server_id)

    async def update_presentation(
        self,
        server_id: str,
        default_message: str,
        bot_display_name: str,
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
        normalized_bot_display_name = bot_display_name.strip()

        await upsert_guild_settings(
            self.db_path,
            server_id=server_id,
            plan=current.plan,
            default_message_override=None if normalized_message == defaults.default_message else normalized_message,
            bot_display_name_override=normalized_bot_display_name or None,
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
    def _normalize_entitlement_status(status: Optional[str]) -> str:
        if status in SUPPORTED_ENTITLEMENT_STATUSES:
            return str(status)
        return 'none'

    @staticmethod
    def _row_has_presentation_overrides(row) -> bool:
        if row is None:
            return False
        return any(
            row[column] is not None
            for column in (
                'default_message_override',
                'bot_display_name_override',
                'emoji_auto_format_override',
                'embed_type_override',
                'built_in_fx_image_override',
                'built_in_video_link_button_override',
                'built_in_legacy_logo_override',
                'fx_domain_name_override',
                'fx_original_url_button_override',
            )
        )
