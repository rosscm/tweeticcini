import json
from typing import Optional

import aiosqlite

from src.db_function.readonly_db import connect_readonly
from src.repositories.notifier_repository import connect_writable

LEGACY_IMPORTED_EXCLUSION_RULE = '__legacy_imported_exclusions__'
LEGACY_IMPORTED_ESCALATION_RULE = '__legacy_imported_escalation__'


def normalize_keywords(value) -> list[str]:
    if not value:
        return []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    return []


def deserialize_keywords(raw_value: Optional[str]) -> list[str]:
    if not raw_value:
        return []
    return normalize_keywords(json.loads(raw_value))


def serialize_keywords(value: list[str]) -> Optional[str]:
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
    source_username: Optional[str],
    channel_id: Optional[str],
    priority: int,
    trigger_keywords: list[str],
    exclude_keywords: list[str],
    force_everyone: Optional[int],
) -> None:
    async with connect_writable(db_path) as db:
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
    async with connect_writable(db_path) as db:
        cursor = await db.execute(
            'DELETE FROM alert_rule WHERE server_id = ? AND rule_name = ?',
            (server_id, rule_name),
        )
        await db.commit()
        return cursor.rowcount


async def import_legacy_alert_rules_for_guild(
    db_path,
    server_id: str,
    trigger_keywords: list[str],
    exclude_keywords: list[str],
) -> int:
    changed = 0
    async with connect_writable(db_path) as db:
        if exclude_keywords:
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
                ) VALUES (?, ?, NULL, NULL, ?, NULL, ?, NULL)
                ON CONFLICT(server_id, rule_name) DO UPDATE SET
                    priority = excluded.priority,
                    exclude_keywords = excluded.exclude_keywords,
                    force_everyone = NULL,
                    enabled = 1
                ''',
                (
                    server_id,
                    LEGACY_IMPORTED_EXCLUSION_RULE,
                    1000,
                    serialize_keywords(exclude_keywords),
                ),
            )
            changed += 1

        if trigger_keywords:
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
                ) VALUES (?, ?, NULL, NULL, ?, ?, NULL, 1)
                ON CONFLICT(server_id, rule_name) DO UPDATE SET
                    priority = excluded.priority,
                    trigger_keywords = excluded.trigger_keywords,
                    force_everyone = 1,
                    enabled = 1
                ''',
                (
                    server_id,
                    LEGACY_IMPORTED_ESCALATION_RULE,
                    1000,
                    serialize_keywords(trigger_keywords),
                ),
            )
            changed += 1

        await db.commit()
    return changed


async def migrate_legacy_alert_rules_for_existing_guilds(
    db_path,
    trigger_keywords: list[str],
    exclude_keywords: list[str],
) -> int:
    async with connect_writable(db_path) as db:
        cursor = await db.execute(
            '''
            SELECT DISTINCT channel.server_id
            FROM channel
            JOIN notification ON notification.channel_id = channel.id
            WHERE notification.enabled = 1
            '''
        )
        server_ids = [row[0] for row in await cursor.fetchall()]
        await db.commit()

    changed = 0
    for server_id in server_ids:
        changed += await import_legacy_alert_rules_for_guild(
            db_path,
            server_id=server_id,
            trigger_keywords=trigger_keywords,
            exclude_keywords=exclude_keywords,
        )
    return changed
