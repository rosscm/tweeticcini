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
from src.repositories.alert_rule_repository import list_alert_rules
from src.repositories.notifier_repository import (
    clear_server_source_message_overrides,
    list_dashboard_sources,
)
from src.repositories.twitter_session_repository import list_server_twitter_sessions
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
        max_rules=2,
        max_trigger_keywords_total=5,
        max_exclude_keywords_total=15,
        can_customize_presentation=False,
        can_customize_source_messages=False,
        can_use_everyone_escalation=False,
    ),
    PLAN_PRO: GuildPlanFeatures(
        max_twitter_sessions=5,
        max_sources=25,
        max_rules=50,
        max_trigger_keywords_total=150,
        max_exclude_keywords_total=250,
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
    compliance: 'GuildComplianceView'


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
    cancel_at_period_end: bool
    trial_ends_at: Optional[str]
    trial_used_at: Optional[str]
    is_test: bool


@dataclass(frozen=True)
class GuildComplianceView:
    is_non_compliant: bool
    reason_labels: tuple[str, ...]
    session_count: int
    source_count: int
    rule_count: int
    over_session_limit: bool
    over_source_limit: bool
    over_rule_limit: bool
    has_premium_rules: bool
    has_premium_presentation: bool
    has_premium_source_overrides: bool


class GuildSettingsService:
    def __init__(self, db_path=None):
        self.db_path = db_path or get_db_path()

    async def get_presentation_view(self, server_id: str) -> GuildPresentationView:
        row = await get_guild_settings_row(self.db_path, server_id)
        entitlement = await self.get_entitlement_view(server_id)
        plan = entitlement.effective_plan
        defaults = get_default_guild_presentation_settings()
        compliance = await self.get_compliance_view(server_id, plan=plan, settings_row=row)

        if row is None:
            return GuildPresentationView(
                plan=plan,
                features=PLAN_FEATURES[plan],
                effective=defaults,
                has_overrides=False,
                entitlement=entitlement,
                compliance=compliance,
            )

        effective = EffectiveGuildPresentationSettings(
            default_message=row['default_message_override'] or defaults.default_message,
            use_headline_message=defaults.use_headline_message if row['use_headline_message_override'] is None else bool(row['use_headline_message_override']),
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
            compliance=compliance,
        )

    async def get_compliance_view(
        self,
        server_id: str,
        plan: Optional[str] = None,
        settings_row=None,
    ) -> GuildComplianceView:
        effective_plan = self._normalize_plan(plan)
        if effective_plan != PLAN_FREE:
            return GuildComplianceView(
                is_non_compliant=False,
                reason_labels=(),
                session_count=0,
                source_count=0,
                rule_count=0,
                over_session_limit=False,
                over_source_limit=False,
                over_rule_limit=False,
                has_premium_rules=False,
                has_premium_presentation=False,
                has_premium_source_overrides=False,
            )

        row = settings_row if settings_row is not None else await get_guild_settings_row(self.db_path, server_id)
        sessions = await list_server_twitter_sessions(self.db_path, server_id)
        sources = await list_dashboard_sources(self.db_path, server_id)
        rules = await list_alert_rules(self.db_path, server_id)

        active_rules = [rule for rule in rules if bool(rule['enabled'])]
        session_count = len([session for session in sessions if bool(session['is_active'])])
        source_count = len(sources)
        rule_count = len(active_rules)
        over_session_limit = session_count > PLAN_FEATURES[PLAN_FREE].max_twitter_sessions
        over_source_limit = source_count > PLAN_FEATURES[PLAN_FREE].max_sources
        over_rule_limit = rule_count > PLAN_FEATURES[PLAN_FREE].max_rules
        has_premium_rules = any(bool(rule['force_everyone']) for rule in active_rules)
        has_premium_presentation = self._row_has_presentation_overrides(row)
        has_premium_source_overrides = any(
            (source['customized_msg'] or '').strip() or source['use_headline_message_override'] is not None
            for source in sources
        )

        reason_labels: list[str] = []
        if over_session_limit:
            reason_labels.append('too many sessions')
        if over_source_limit:
            reason_labels.append('too many monitors')
        if over_rule_limit:
            reason_labels.append('too many rules')
        if has_premium_rules:
            reason_labels.append('premium rule escalation')
        if has_premium_presentation:
            reason_labels.append('premium appearance settings')
        if has_premium_source_overrides:
            reason_labels.append('premium monitor message settings')

        return GuildComplianceView(
            is_non_compliant=bool(reason_labels),
            reason_labels=tuple(reason_labels),
            session_count=session_count,
            source_count=source_count,
            rule_count=rule_count,
            over_session_limit=over_session_limit,
            over_source_limit=over_source_limit,
            over_rule_limit=over_rule_limit,
            has_premium_rules=has_premium_rules,
            has_premium_presentation=has_premium_presentation,
            has_premium_source_overrides=has_premium_source_overrides,
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
            cancel_at_period_end=entitlement['cancel_at_period_end'] if entitlement is not None else 0,
            trial_ends_at=entitlement['trial_ends_at'] if entitlement is not None else None,
            trial_used_at=entitlement['trial_used_at'] if entitlement is not None else None,
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
                use_headline_message_override=legacy_row['use_headline_message_override'] if legacy_row is not None else None,
                bot_display_name_override=legacy_row['bot_display_name_override'] if legacy_row is not None else None,
                emoji_auto_format_override=legacy_row['emoji_auto_format_override'] if legacy_row is not None else None,
                embed_type_override=legacy_row['embed_type_override'] if legacy_row is not None else None,
                built_in_fx_image_override=legacy_row['built_in_fx_image_override'] if legacy_row is not None else None,
                built_in_video_link_button_override=legacy_row['built_in_video_link_button_override'] if legacy_row is not None else None,
                built_in_legacy_logo_override=legacy_row['built_in_legacy_logo_override'] if legacy_row is not None else None,
                fx_domain_name_override=legacy_row['fx_domain_name_override'] if legacy_row is not None else None,
                fx_original_url_button_override=legacy_row['fx_original_url_button_override'] if legacy_row is not None else None,
            )
        presentation = await self.get_presentation_view(server_id)
        if presentation.plan == PLAN_FREE and (
            presentation.has_overrides or presentation.compliance.has_premium_source_overrides
        ):
            await self._clear_free_downgrade_overrides(server_id)
            presentation = await self.get_presentation_view(server_id)
        return presentation

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
                cancel_at_period_end=bool(row['cancel_at_period_end']),
                trial_ends_at=row['trial_ends_at'],
                trial_used_at=row['trial_used_at'],
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
                cancel_at_period_end=bool(row['cancel_at_period_end']),
                trial_ends_at=row['trial_ends_at'],
                trial_used_at=row['trial_used_at'],
                is_test=bool(row['is_test']),
            )

        if row is not None:
            return GuildEntitlementView(
                effective_plan=PLAN_FREE,
                plan_source='subscription',
                entitlement_status=row['entitlement_status'] if row['entitlement_status'] else 'none',
                subscribed_plan=row['subscribed_plan'],
                manual_plan_override=row['manual_plan_override'],
                billing_provider=row['billing_provider'],
                external_customer_id=row['external_customer_id'],
                external_subscription_id=row['external_subscription_id'],
                current_period_end=row['current_period_end'],
                cancel_at_period_end=bool(row['cancel_at_period_end']),
                trial_ends_at=row['trial_ends_at'],
                trial_used_at=row['trial_used_at'],
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
            cancel_at_period_end=bool(row['cancel_at_period_end']) if row is not None else False,
            trial_ends_at=row['trial_ends_at'] if row is not None else None,
            trial_used_at=row['trial_used_at'] if row is not None else None,
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
        cancel_at_period_end: Optional[bool] = None,
        trial_ends_at: Optional[str] = None,
        trial_used_at: Optional[str] = None,
        is_test: bool = False,
    ) -> GuildPresentationView:
        normalized_plan = None if subscribed_plan is None else self._normalize_plan(subscribed_plan)
        normalized_status = self._normalize_entitlement_status(entitlement_status)
        current = await get_guild_entitlement_row(self.db_path, server_id)
        resolved_trial_used_at = trial_used_at
        if resolved_trial_used_at is None:
            if current is not None and current['trial_used_at']:
                resolved_trial_used_at = current['trial_used_at']
            elif trial_ends_at or normalized_status == 'trialing':
                resolved_trial_used_at = get_utcnow()
        await upsert_guild_entitlement(
            self.db_path,
            server_id=server_id,
            subscribed_plan=normalized_plan,
            manual_plan_override=current['manual_plan_override'] if current is not None else None,
            entitlement_status=normalized_status,
            billing_provider=billing_provider,
            external_customer_id=external_customer_id if external_customer_id is not None else (current['external_customer_id'] if current is not None else None),
            external_subscription_id=external_subscription_id if external_subscription_id is not None else (current['external_subscription_id'] if current is not None else None),
            current_period_end=current_period_end if current_period_end is not None else (current['current_period_end'] if current is not None else None),
            cancel_at_period_end=(
                int(cancel_at_period_end)
                if cancel_at_period_end is not None
                else (current['cancel_at_period_end'] if current is not None else 0)
            ),
            trial_ends_at=trial_ends_at if trial_ends_at is not None else (current['trial_ends_at'] if current is not None else None),
            trial_used_at=resolved_trial_used_at,
            is_test=int(is_test),
            updated_at=get_utcnow(),
        )
        presentation = await self.get_presentation_view(server_id)
        if presentation.plan == PLAN_FREE and (
            presentation.has_overrides or presentation.compliance.has_premium_source_overrides
        ):
            await self._clear_free_downgrade_overrides(server_id)
            presentation = await self.get_presentation_view(server_id)
        return presentation

    async def update_presentation(
        self,
        server_id: str,
        default_message: str,
        use_headline_message: bool,
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
            use_headline_message_override=None if use_headline_message == defaults.use_headline_message else int(use_headline_message),
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
                'use_headline_message_override',
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

    async def _clear_free_downgrade_overrides(self, server_id: str) -> None:
        await clear_server_source_message_overrides(self.db_path, server_id)
        await self._clear_presentation_overrides(server_id)

    async def _clear_presentation_overrides(self, server_id: str) -> None:
        row = await get_guild_settings_row(self.db_path, server_id)
        if row is None:
            return
        await upsert_guild_settings(
            self.db_path,
            server_id=server_id,
            plan=PLAN_FREE,
            default_message_override=None,
            use_headline_message_override=None,
            bot_display_name_override=None,
            emoji_auto_format_override=None,
            embed_type_override=None,
            built_in_fx_image_override=None,
            built_in_video_link_button_override=None,
            built_in_legacy_logo_override=None,
            fx_domain_name_override=None,
            fx_original_url_button_override=None,
        )
