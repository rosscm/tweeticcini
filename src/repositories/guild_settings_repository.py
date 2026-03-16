import json

import aiosqlite

from src.db_function.readonly_db import connect_readonly
from src.repositories.notifier_repository import connect_writable


def normalize_keywords(value) -> list[str]:
    if not value:
        return []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    return []


def deserialize_keywords(raw_value: str | None) -> list[str]:
    if not raw_value:
        return []
    return normalize_keywords(json.loads(raw_value))


def serialize_keywords(value: list[str]) -> str | None:
    keywords = normalize_keywords(value)
    if not keywords:
        return None
    return json.dumps(keywords)


async def get_guild_settings_row(db_path, server_id: str):
    async with connect_readonly(db_path) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            '''
            SELECT force_everyone_default, keywords_triggering_everyone, keywords_excluded
            FROM guild_settings
            WHERE server_id = ?
            ''',
            (server_id,),
        ) as cursor:
            return await cursor.fetchone()


async def upsert_guild_settings(
    db_path,
    server_id: str,
    force_everyone_default: bool,
    keywords_triggering_everyone: list[str],
    keywords_excluded: list[str],
) -> None:
    async with await connect_writable(db_path) as db:
        await db.execute(
            '''
            INSERT INTO guild_settings (
                server_id,
                force_everyone_default,
                keywords_triggering_everyone,
                keywords_excluded
            ) VALUES (?, ?, ?, ?)
            ON CONFLICT(server_id) DO UPDATE SET
                force_everyone_default = excluded.force_everyone_default,
                keywords_triggering_everyone = excluded.keywords_triggering_everyone,
                keywords_excluded = excluded.keywords_excluded
            ''',
            (
                server_id,
                int(force_everyone_default),
                serialize_keywords(keywords_triggering_everyone),
                serialize_keywords(keywords_excluded),
            ),
        )
        await db.commit()


async def delete_guild_settings(db_path, server_id: str) -> int:
    async with await connect_writable(db_path) as db:
        cursor = await db.execute(
            'DELETE FROM guild_settings WHERE server_id = ?',
            (server_id,),
        )
        await db.commit()
        return cursor.rowcount
