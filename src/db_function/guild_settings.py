import json
from dataclasses import dataclass

import aiosqlite

from configs.load_configs import configs
from src.settings import get_db_path


@dataclass(frozen=True)
class EffectiveGuildSettings:
    force_everyone_default: bool
    keywords_triggering_everyone: list[str]
    keywords_excluded: list[str]


def _normalize_keywords(value) -> list[str]:
    if not value:
        return []
    if isinstance(value, list):
        return [str(item) for item in value if str(item).strip()]
    return []


def get_default_guild_settings() -> EffectiveGuildSettings:
    return EffectiveGuildSettings(
        force_everyone_default=bool(configs.get('force_everyone_default', False)),
        keywords_triggering_everyone=_normalize_keywords(configs.get('keywords_triggering_everyone')),
        keywords_excluded=_normalize_keywords(configs.get('keywords_excluded')),
    )


async def get_effective_guild_settings(server_id: str) -> EffectiveGuildSettings:
    defaults = get_default_guild_settings()

    async with aiosqlite.connect(get_db_path()) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            '''
            SELECT force_everyone_default, keywords_triggering_everyone, keywords_excluded
            FROM guild_settings
            WHERE server_id = ?
            ''',
            (server_id,),
        ) as cursor:
            row = await cursor.fetchone()

    if row is None:
        return defaults

    trigger_keywords = defaults.keywords_triggering_everyone
    excluded_keywords = defaults.keywords_excluded

    if row['keywords_triggering_everyone']:
        trigger_keywords = _normalize_keywords(json.loads(row['keywords_triggering_everyone']))

    if row['keywords_excluded']:
        excluded_keywords = _normalize_keywords(json.loads(row['keywords_excluded']))

    force_everyone_default = defaults.force_everyone_default
    if row['force_everyone_default'] is not None:
        force_everyone_default = bool(row['force_everyone_default'])

    return EffectiveGuildSettings(
        force_everyone_default=force_everyone_default,
        keywords_triggering_everyone=trigger_keywords,
        keywords_excluded=excluded_keywords,
    )
