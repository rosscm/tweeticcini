from dataclasses import dataclass
from typing import Optional

from src.db_function.guild_settings import (
    EffectiveGuildSettings,
    get_default_guild_settings,
    get_legacy_alert_settings,
    get_legacy_exclude_keywords,
    get_legacy_trigger_keywords,
)
from src.repositories.alert_rule_repository import import_legacy_alert_rules_for_guild
from src.repositories.guild_settings_repository import (
    delete_guild_settings,
    get_guild_settings_row,
    upsert_guild_settings,
)
from src.settings import get_db_path


_UNSET = object()


@dataclass(frozen=True)
class GuildSettingsView:
    effective: EffectiveGuildSettings
    configured: Optional[EffectiveGuildSettings]
    uses_legacy_defaults: bool


class GuildSettingsService:
    def __init__(self, db_path=None):
        self.db_path = db_path or get_db_path()

    async def get_settings_view(self, server_id: str) -> GuildSettingsView:
        configured = await self._get_configured_settings(server_id)
        if configured is None:
            return GuildSettingsView(
                effective=get_default_guild_settings(),
                configured=None,
                uses_legacy_defaults=True,
            )

        return GuildSettingsView(
            effective=configured,
            configured=configured,
            uses_legacy_defaults=False,
        )

    async def update_settings(
        self,
        server_id: str,
        force_everyone_default=_UNSET,
    ) -> EffectiveGuildSettings:
        current = (await self.get_settings_view(server_id)).effective
        updated = EffectiveGuildSettings(
            force_everyone_default=current.force_everyone_default if force_everyone_default is _UNSET else bool(force_everyone_default),
        )
        await upsert_guild_settings(
            self.db_path,
            server_id=server_id,
            force_everyone_default=updated.force_everyone_default,
            keywords_triggering_everyone=[],
            keywords_excluded=[],
        )
        return updated

    async def bootstrap_from_legacy_defaults(self, server_id: str) -> tuple[EffectiveGuildSettings, bool]:
        current_view = await self.get_settings_view(server_id)
        legacy_settings = get_legacy_alert_settings()
        imported_rules = await import_legacy_alert_rules_for_guild(
            self.db_path,
            server_id=server_id,
            trigger_keywords=get_legacy_trigger_keywords(),
            exclude_keywords=get_legacy_exclude_keywords(),
        )
        created_settings = False
        if current_view.uses_legacy_defaults:
            await upsert_guild_settings(
                self.db_path,
                server_id=server_id,
                force_everyone_default=legacy_settings.force_everyone_default,
                keywords_triggering_everyone=[],
                keywords_excluded=[],
            )
            created_settings = True
        return legacy_settings, created_settings or bool(imported_rules)

    async def reset_to_legacy_defaults(self, server_id: str) -> bool:
        return (await delete_guild_settings(self.db_path, server_id)) > 0

    async def _get_configured_settings(self, server_id: str) -> Optional[EffectiveGuildSettings]:
        row = await get_guild_settings_row(self.db_path, server_id)
        if row is None:
            return None

        return EffectiveGuildSettings(
            force_everyone_default=bool(row['force_everyone_default']),
        )

    @staticmethod
    def get_legacy_trigger_keywords() -> list[str]:
        return get_legacy_trigger_keywords()

    @staticmethod
    def get_legacy_exclude_keywords() -> list[str]:
        return get_legacy_exclude_keywords()
