from dataclasses import dataclass

from src.db_function.guild_settings import EffectiveGuildSettings, get_default_guild_settings
from src.repositories.guild_settings_repository import (
    delete_guild_settings,
    deserialize_keywords,
    get_guild_settings_row,
    upsert_guild_settings,
)
from src.settings import get_db_path


_UNSET = object()


@dataclass(frozen=True)
class GuildSettingsView:
    effective: EffectiveGuildSettings
    configured: EffectiveGuildSettings | None
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
        keywords_triggering_everyone=_UNSET,
        keywords_excluded=_UNSET,
    ) -> EffectiveGuildSettings:
        current = (await self.get_settings_view(server_id)).effective
        updated = EffectiveGuildSettings(
            force_everyone_default=current.force_everyone_default if force_everyone_default is _UNSET else bool(force_everyone_default),
            keywords_triggering_everyone=current.keywords_triggering_everyone if keywords_triggering_everyone is _UNSET else list(keywords_triggering_everyone),
            keywords_excluded=current.keywords_excluded if keywords_excluded is _UNSET else list(keywords_excluded),
        )
        await upsert_guild_settings(
            self.db_path,
            server_id=server_id,
            force_everyone_default=updated.force_everyone_default,
            keywords_triggering_everyone=updated.keywords_triggering_everyone,
            keywords_excluded=updated.keywords_excluded,
        )
        return updated

    async def bootstrap_from_legacy_defaults(self, server_id: str) -> tuple[EffectiveGuildSettings, bool]:
        current_view = await self.get_settings_view(server_id)
        if not current_view.uses_legacy_defaults:
            return current_view.effective, False

        await upsert_guild_settings(
            self.db_path,
            server_id=server_id,
            force_everyone_default=current_view.effective.force_everyone_default,
            keywords_triggering_everyone=current_view.effective.keywords_triggering_everyone,
            keywords_excluded=current_view.effective.keywords_excluded,
        )
        return current_view.effective, True

    async def reset_to_legacy_defaults(self, server_id: str) -> bool:
        return (await delete_guild_settings(self.db_path, server_id)) > 0

    async def _get_configured_settings(self, server_id: str) -> EffectiveGuildSettings | None:
        row = await get_guild_settings_row(self.db_path, server_id)
        if row is None:
            return None

        return EffectiveGuildSettings(
            force_everyone_default=bool(row['force_everyone_default']),
            keywords_triggering_everyone=deserialize_keywords(row['keywords_triggering_everyone']),
            keywords_excluded=deserialize_keywords(row['keywords_excluded']),
        )
