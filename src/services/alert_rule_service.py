from dataclasses import dataclass
from typing import Optional

from src.repositories.alert_rule_repository import (
    LEGACY_IMPORTED_ESCALATION_RULE,
    LEGACY_IMPORTED_EXCLUSION_RULE,
    deserialize_keywords,
    delete_alert_rule,
    get_alert_rule_count,
    get_alert_rule_names,
    get_matching_alert_rules,
    import_legacy_alert_rules_for_guild,
    list_alert_rules,
    migrate_legacy_alert_rules_for_existing_guilds,
    upsert_alert_rule,
)
from src.services.guild_settings_service import GuildSettingsService
from src.services.notifier_service import NotifierService
from src.settings import get_db_path


@dataclass(frozen=True)
class AlertDecision:
    should_exclude: bool
    should_force_everyone: bool
    matched_rule_name: Optional[str] = None


@dataclass(frozen=True)
class AlertRuleRecord:
    rule_name: str
    source_username: Optional[str]
    channel_id: Optional[str]
    priority: int
    trigger_keywords: list[str]
    exclude_keywords: list[str]
    escalation_mode: str


def _matches_phrase(text_lower: str, phrase: str) -> bool:
    words = phrase.lower().split()
    return bool(words) and all(word in text_lower for word in words)


def _matches_any(text: str, phrases: list[str]) -> bool:
    text_lower = text.lower()
    return any(_matches_phrase(text_lower, phrase) for phrase in phrases)


class AlertRuleService:
    def __init__(self, db_path=None):
        self.db_path = db_path or get_db_path()
        self.guild_settings_service = GuildSettingsService(self.db_path)
        self.notifier_service = NotifierService(self.db_path)

    async def resolve_alert_decision(
        self,
        server_id: str,
        channel_id: str,
        source_username: str,
        text: str,
    ) -> AlertDecision:
        should_force_everyone = False
        rules = await get_matching_alert_rules(self.db_path, server_id, channel_id, source_username)

        for rule in rules:
            exclude_keywords = deserialize_keywords(rule['exclude_keywords'])
            if exclude_keywords and _matches_any(text, exclude_keywords):
                return AlertDecision(
                    should_exclude=True,
                    should_force_everyone=False,
                    matched_rule_name=rule['rule_name'],
                )

            trigger_keywords = deserialize_keywords(rule['trigger_keywords'])
            force_everyone = rule['force_everyone']
            if force_everyone is not None:
                if not trigger_keywords or _matches_any(text, trigger_keywords):
                    should_force_everyone = bool(force_everyone)
                    return AlertDecision(
                        should_exclude=False,
                        should_force_everyone=should_force_everyone,
                        matched_rule_name=rule['rule_name'],
                    )

        return AlertDecision(
            should_exclude=False,
            should_force_everyone=should_force_everyone,
        )

    async def upsert_rule(
        self,
        server_id: str,
        rule_name: str,
        existing_rule_name: Optional[str],
        source_username: Optional[str],
        channel_id: Optional[str],
        priority: int,
        trigger_keywords: list[str],
        exclude_keywords: list[str],
        escalation_mode: str,
    ) -> None:
        presentation = await self.guild_settings_service.get_presentation_view(server_id)
        if source_username:
            tracked_sources = await self.notifier_service.list_dashboard_sources(server_id)
            tracked_source_usernames = {source.username.lower() for source in tracked_sources}
            if source_username.lower() not in tracked_source_usernames:
                raise ValueError(f'cannot create a rule for untracked source `{source_username}`')

        if escalation_mode == 'everyone' and not presentation.features.can_use_everyone_escalation:
            raise ValueError('`@everyone` escalation requires a paid plan')

        existing_names = await self.get_rule_names(server_id)
        comparison_rule_name = existing_rule_name or rule_name
        if rule_name != comparison_rule_name and rule_name in existing_names:
            raise ValueError(f'a rule named `{rule_name}` already exists in this guild')

        if comparison_rule_name not in existing_names:
            current_count = await get_alert_rule_count(self.db_path, server_id)
            if current_count >= presentation.features.max_rules:
                raise ValueError(f'plan limit reached: {presentation.features.max_rules} alert rules max for {presentation.plan}')

        existing_rules = await self.list_rules(server_id)
        trigger_total = len(trigger_keywords)
        exclude_total = len(exclude_keywords)
        for existing_rule in existing_rules:
            if existing_rule.rule_name == comparison_rule_name:
                continue
            trigger_total += len(existing_rule.trigger_keywords)
            exclude_total += len(existing_rule.exclude_keywords)

        if trigger_total > presentation.features.max_trigger_keywords_total:
            raise ValueError(
                f'plan limit reached: {presentation.features.max_trigger_keywords_total} total trigger keywords max for {presentation.plan}'
            )
        if exclude_total > presentation.features.max_exclude_keywords_total:
            raise ValueError(
                f'plan limit reached: {presentation.features.max_exclude_keywords_total} total exclusion keywords max for {presentation.plan}'
            )

        await upsert_alert_rule(
            self.db_path,
            server_id=server_id,
            rule_name=rule_name,
            existing_rule_name=existing_rule_name,
            source_username=source_username,
            channel_id=channel_id,
            priority=priority,
            trigger_keywords=trigger_keywords,
            exclude_keywords=exclude_keywords,
            force_everyone=self._escalation_mode_to_db_value(escalation_mode),
        )

    async def list_rules(self, server_id: str) -> list[AlertRuleRecord]:
        rows = await list_alert_rules(self.db_path, server_id)
        return [
            AlertRuleRecord(
                rule_name=row['rule_name'],
                source_username=row['source_username'],
                channel_id=row['channel_id'],
                priority=row['priority'],
                trigger_keywords=deserialize_keywords(row['trigger_keywords']),
                exclude_keywords=deserialize_keywords(row['exclude_keywords']),
                escalation_mode=self._db_value_to_escalation_mode(row['force_everyone']),
            )
            for row in rows
        ]

    async def get_rule_names(self, server_id: str) -> list[str]:
        return await get_alert_rule_names(self.db_path, server_id)

    async def delete_rule(self, server_id: str, rule_name: str) -> bool:
        return (await delete_alert_rule(self.db_path, server_id, rule_name)) > 0

    async def import_legacy_rules_for_guild(
        self,
        server_id: str,
        trigger_keywords: list[str],
        exclude_keywords: list[str],
    ) -> int:
        return await import_legacy_alert_rules_for_guild(
            self.db_path,
            server_id=server_id,
            trigger_keywords=trigger_keywords,
            exclude_keywords=exclude_keywords,
        )

    async def migrate_legacy_rules_for_existing_guilds(
        self,
        trigger_keywords: list[str],
        exclude_keywords: list[str],
    ) -> int:
        return await migrate_legacy_alert_rules_for_existing_guilds(
            self.db_path,
            trigger_keywords=trigger_keywords,
            exclude_keywords=exclude_keywords,
        )

    @staticmethod
    def is_legacy_imported_rule(rule_name: str) -> bool:
        return rule_name in {LEGACY_IMPORTED_EXCLUSION_RULE, LEGACY_IMPORTED_ESCALATION_RULE}

    @staticmethod
    def _escalation_mode_to_db_value(escalation_mode: str) -> Optional[int]:
        if escalation_mode == 'everyone':
            return 1
        return 0

    @staticmethod
    def _db_value_to_escalation_mode(force_everyone: Optional[int]) -> str:
        if force_everyone is None:
            return 'role_only'
        return 'everyone' if bool(force_everyone) else 'role_only'
