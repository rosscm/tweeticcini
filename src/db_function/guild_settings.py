from dataclasses import dataclass

from configs.load_configs import configs
from src.repositories.guild_settings_repository import deserialize_keywords, get_guild_settings_row
from src.settings import get_db_path


@dataclass(frozen=True)
class EffectiveGuildSettings:
    force_everyone_default: bool


def _normalize_keywords(value) -> list[str]:
    if not value:
        return []
    if isinstance(value, list):
        return [str(item) for item in value if str(item).strip()]
    return []


def get_default_guild_settings() -> EffectiveGuildSettings:
    return EffectiveGuildSettings(
        force_everyone_default=bool(configs.get('force_everyone_default', False)),
    )


def get_legacy_alert_settings() -> EffectiveGuildSettings:
    return EffectiveGuildSettings(
        force_everyone_default=bool(configs.get('force_everyone_default', False)),
    )


def get_legacy_trigger_keywords() -> list[str]:
    return _normalize_keywords(configs.get('keywords_triggering_everyone'))


def get_legacy_exclude_keywords() -> list[str]:
    return _normalize_keywords(configs.get('keywords_excluded'))


async def get_effective_guild_settings(server_id: str) -> EffectiveGuildSettings:
    defaults = get_default_guild_settings()
    row = await get_guild_settings_row(get_db_path(), server_id)

    if row is None:
        return defaults

    force_everyone_default = defaults.force_everyone_default
    if row['force_everyone_default'] is not None:
        force_everyone_default = bool(row['force_everyone_default'])

    return EffectiveGuildSettings(
        force_everyone_default=force_everyone_default,
    )
