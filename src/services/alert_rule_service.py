from dataclasses import dataclass

from src.db_function.guild_settings import EffectiveGuildSettings
from src.repositories.alert_rule_repository import (
    deserialize_keywords,
    delete_alert_rule,
    get_alert_rule_names,
    get_matching_alert_rules,
    list_alert_rules,
    upsert_alert_rule,
)
from src.settings import get_db_path


@dataclass(frozen=True)
class AlertDecision:
    should_exclude: bool
    should_force_everyone: bool
    matched_rule_name: str | None = None


@dataclass(frozen=True)
class AlertRuleRecord:
    rule_name: str
    source_username: str | None
    channel_id: str | None
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

    async def resolve_alert_decision(
        self,
        server_id: str,
        channel_id: str,
        source_username: str,
        text: str,
        default_force_everyone: bool,
        guild_settings: EffectiveGuildSettings,
    ) -> AlertDecision:
        if self._is_excluded_by_guild_settings(text, guild_settings):
            return AlertDecision(
                should_exclude=True,
                should_force_everyone=False,
            )

        should_force_everyone = default_force_everyone and self._matches_guild_trigger(text, guild_settings)
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
        source_username: str | None,
        channel_id: str | None,
        priority: int,
        trigger_keywords: list[str],
        exclude_keywords: list[str],
        escalation_mode: str,
    ) -> None:
        await upsert_alert_rule(
            self.db_path,
            server_id=server_id,
            rule_name=rule_name,
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

    @staticmethod
    def _is_excluded_by_guild_settings(text: str, guild_settings: EffectiveGuildSettings) -> bool:
        return _matches_any(text, guild_settings.keywords_excluded)

    @staticmethod
    def _matches_guild_trigger(text: str, guild_settings: EffectiveGuildSettings) -> bool:
        return _matches_any(text, guild_settings.keywords_triggering_everyone)

    @staticmethod
    def _escalation_mode_to_db_value(escalation_mode: str) -> int | None:
        if escalation_mode == 'inherit':
            return None
        if escalation_mode == 'everyone':
            return 1
        return 0

    @staticmethod
    def _db_value_to_escalation_mode(force_everyone: int | None) -> str:
        if force_everyone is None:
            return 'inherit'
        return 'everyone' if bool(force_everyone) else 'role_only'
