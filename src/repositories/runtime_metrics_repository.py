from typing import Optional

from src.db_function.readonly_db import connect_readonly
from src.repositories.notifier_repository import connect_writable


def _normalize_message(message: str) -> str:
    return message.strip()[:300]


async def record_client_poll_success(db_path, client_used: str, notification_count: int, happened_at: str) -> None:
    async with connect_writable(db_path) as db:
        await db.execute(
            '''
            INSERT INTO runtime_client_status (
                client_used,
                last_poll_success_at,
                last_notification_count,
                last_poll_error_at,
                last_error_message
            ) VALUES (?, ?, ?, NULL, NULL)
            ON CONFLICT(client_used) DO UPDATE SET
                last_poll_success_at = excluded.last_poll_success_at,
                last_notification_count = excluded.last_notification_count,
                last_poll_error_at = NULL,
                last_error_message = NULL
            ''',
            (client_used, happened_at, notification_count),
        )
        await db.commit()


async def record_client_poll_error(db_path, client_used: str, error_message: str, happened_at: str) -> None:
    async with connect_writable(db_path) as db:
        await db.execute(
            '''
            INSERT INTO runtime_client_status (
                client_used,
                last_poll_success_at,
                last_notification_count,
                last_poll_error_at,
                last_error_message
            ) VALUES (?, NULL, 0, ?, ?)
            ON CONFLICT(client_used) DO UPDATE SET
                last_poll_error_at = excluded.last_poll_error_at,
                last_error_message = excluded.last_error_message
            ''',
            (client_used, happened_at, _normalize_message(error_message)),
        )
        await db.commit()


async def record_source_delivery_success(
    db_path,
    server_id: str,
    username: str,
    channel_id: str,
    delivery_url: str,
    matched_rule_name: Optional[str],
    happened_at: str,
) -> None:
    async with connect_writable(db_path) as db:
        await db.execute(
            '''
            INSERT INTO runtime_source_status (
                server_id,
                username,
                channel_id,
                last_delivery_success_at,
                last_delivery_error_at,
                last_error_message,
                last_matched_rule_name,
                last_delivery_url,
                success_count,
                error_count
            ) VALUES (?, ?, ?, ?, NULL, NULL, ?, ?, 1, 0)
            ON CONFLICT(server_id, username, channel_id) DO UPDATE SET
                last_delivery_success_at = excluded.last_delivery_success_at,
                last_error_message = NULL,
                last_delivery_error_at = NULL,
                last_matched_rule_name = excluded.last_matched_rule_name,
                last_delivery_url = excluded.last_delivery_url,
                success_count = runtime_source_status.success_count + 1
            ''',
            (server_id, username, channel_id, happened_at, matched_rule_name, delivery_url),
        )
        await db.commit()


async def record_source_delivery_error(
    db_path,
    server_id: str,
    username: str,
    channel_id: str,
    error_message: str,
    happened_at: str,
) -> None:
    async with connect_writable(db_path) as db:
        await db.execute(
            '''
            INSERT INTO runtime_source_status (
                server_id,
                username,
                channel_id,
                last_delivery_success_at,
                last_delivery_error_at,
                last_error_message,
                last_matched_rule_name,
                last_delivery_url,
                success_count,
                error_count
            ) VALUES (?, ?, ?, NULL, ?, ?, NULL, NULL, 0, 1)
            ON CONFLICT(server_id, username, channel_id) DO UPDATE SET
                last_delivery_error_at = excluded.last_delivery_error_at,
                last_error_message = excluded.last_error_message,
                error_count = runtime_source_status.error_count + 1
            ''',
            (server_id, username, channel_id, happened_at, _normalize_message(error_message)),
        )
        await db.commit()


async def prune_orphaned_runtime_source_statuses(db_path, server_id: str) -> int:
    async with connect_writable(db_path) as db:
        cursor = await db.execute(
            '''
            DELETE FROM runtime_source_status
            WHERE server_id = ?
              AND NOT EXISTS (
                SELECT 1
                FROM notification AS n
                JOIN channel AS c
                  ON c.id = n.channel_id
                JOIN user AS u
                  ON u.id = n.user_id
                WHERE c.server_id = runtime_source_status.server_id
                  AND c.id = runtime_source_status.channel_id
                  AND lower(u.username) = lower(runtime_source_status.username)
                  AND n.enabled = 1
              )
            ''',
            (server_id,),
        )
        await db.commit()
        return cursor.rowcount or 0


async def increment_server_support_prompt_counter_with_cursor(
    cursor,
    server_id: str,
    happened_at: str,
    threshold: int = 20,
) -> bool:
    await cursor.execute(
        '''
        SELECT delivered_alerts_since_prompt, last_prompt_at
        FROM server_support_prompt_state
        WHERE server_id = ?
        ''',
        (server_id,),
    )
    row = await cursor.fetchone()

    current_count = int(row[0]) if row and row[0] is not None else 0
    next_count = current_count + 1
    should_prompt = next_count >= threshold

    delivered_alerts_since_prompt = 0 if should_prompt else next_count
    last_prompt_at = (
        happened_at
        if should_prompt
        else (row[1] if row and row[1] is not None else None)
    )

    await cursor.execute(
        '''
        INSERT INTO server_support_prompt_state (
            server_id,
            delivered_alerts_since_prompt,
            last_prompt_at
        )
        VALUES (?, ?, ?)
        ON CONFLICT(server_id) DO UPDATE SET
            delivered_alerts_since_prompt =
                excluded.delivered_alerts_since_prompt,
            last_prompt_at = excluded.last_prompt_at
        ''',
        (
            server_id,
            delivered_alerts_since_prompt,
            last_prompt_at,
        ),
    )

    return should_prompt


async def increment_server_support_prompt_counter(
    db_path,
    server_id: str,
    happened_at: str,
    threshold: int = 20,
) -> bool:
    async with connect_writable(db_path) as db:
        async with db.cursor() as cursor:
            should_prompt = (
                await increment_server_support_prompt_counter_with_cursor(
                    cursor,
                    server_id,
                    happened_at,
                    threshold,
                )
            )

        await db.commit()
        return should_prompt


async def get_server_support_prompt_counter(db_path, server_id: str) -> int:
    async with connect_readonly(db_path) as db:
        async with db.execute(
            '''
            SELECT delivered_alerts_since_prompt
            FROM server_support_prompt_state
            WHERE server_id = ?
            ''',
            (server_id,),
        ) as cursor:
            row = await cursor.fetchone()
    if row is None or row[0] is None:
        return 0
    return int(row[0])


async def list_runtime_client_statuses(db_path) -> list[dict[str, object]]:
    async with connect_readonly(db_path) as db:
        db.row_factory = None
        async with db.execute(
            '''
            SELECT
                client_used,
                last_poll_success_at,
                last_notification_count,
                last_poll_error_at,
                last_error_message
            FROM runtime_client_status
            ORDER BY client_used ASC
            '''
        ) as cursor:
            rows = await cursor.fetchall()
    return [
        {
            'client_used': row[0],
            'last_poll_success_at': row[1],
            'last_notification_count': row[2],
            'last_poll_error_at': row[3],
            'last_error_message': row[4],
        }
        for row in rows
    ]


async def get_runtime_source_status_map(db_path, server_id: str) -> dict[tuple[str, str], dict[str, object]]:
    async with connect_readonly(db_path) as db:
        db.row_factory = None
        async with db.execute(
            '''
            SELECT
                username,
                channel_id,
                last_delivery_success_at,
                last_delivery_error_at,
                last_error_message,
                last_matched_rule_name,
                last_delivery_url,
                success_count,
                error_count
            FROM runtime_source_status
            WHERE server_id = ?
            ''',
            (server_id,),
        ) as cursor:
            rows = await cursor.fetchall()
    return {
        (str(row[0]).lower(), str(row[1])): {
            'last_delivery_success_at': row[2],
            'last_delivery_error_at': row[3],
            'last_error_message': row[4],
            'last_matched_rule_name': row[5],
            'last_delivery_url': row[6],
            'success_count': row[7] or 0,
            'error_count': row[8] or 0,
        }
        for row in rows
    }
