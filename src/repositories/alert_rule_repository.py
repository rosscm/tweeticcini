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


async def get_matching_alert_rules(
    db_path,
    server_id: str,
    channel_id: str,
    source_username: str,
):
    async with connect_readonly(db_path) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            '''
            SELECT *
            FROM alert_rule
            WHERE server_id = ?
              AND enabled = 1
              AND (source_username IS NULL OR source_username = ?)
              AND (channel_id IS NULL OR channel_id = ?)
            ORDER BY priority DESC, id ASC
            ''',
            (server_id, source_username, channel_id),
        ) as cursor:
            return await cursor.fetchall()


async def list_alert_rules(db_path, server_id: str):
    async with connect_readonly(db_path) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            '''
            SELECT *
            FROM alert_rule
            WHERE server_id = ?
            ORDER BY priority DESC, id ASC
            ''',
            (server_id,),
        ) as cursor:
            return await cursor.fetchall()


async def get_alert_rule_names(db_path, server_id: str) -> list[str]:
    async with connect_readonly(db_path) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            'SELECT rule_name FROM alert_rule WHERE server_id = ? ORDER BY rule_name ASC',
            (server_id,),
        ) as cursor:
            return [row['rule_name'] async for row in cursor]


async def upsert_alert_rule(
    db_path,
    server_id: str,
    rule_name: str,
    source_username: str | None,
    channel_id: str | None,
    priority: int,
    trigger_keywords: list[str],
    exclude_keywords: list[str],
    force_everyone: int | None,
) -> None:
    async with await connect_writable(db_path) as db:
        await db.execute(
            '''
            INSERT INTO alert_rule (
                server_id,
                rule_name,
                source_username,
                channel_id,
                priority,
                trigger_keywords,
                exclude_keywords,
                force_everyone
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(server_id, rule_name) DO UPDATE SET
                source_username = excluded.source_username,
                channel_id = excluded.channel_id,
                priority = excluded.priority,
                trigger_keywords = excluded.trigger_keywords,
                exclude_keywords = excluded.exclude_keywords,
                force_everyone = excluded.force_everyone,
                enabled = 1
            ''',
            (
                server_id,
                rule_name,
                source_username,
                channel_id,
                priority,
                serialize_keywords(trigger_keywords),
                serialize_keywords(exclude_keywords),
                force_everyone,
            ),
        )
        await db.commit()


async def delete_alert_rule(db_path, server_id: str, rule_name: str) -> int:
    async with await connect_writable(db_path) as db:
        cursor = await db.execute(
            'DELETE FROM alert_rule WHERE server_id = ? AND rule_name = ?',
            (server_id, rule_name),
        )
        await db.commit()
        return cursor.rowcount
