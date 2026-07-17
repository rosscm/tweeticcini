import json
import secrets
from dataclasses import dataclass
from typing import Optional

import aiosqlite

from src.db_function.readonly_db import connect_readonly
from src.repositories.notifier_repository import connect_writable


@dataclass(frozen=True)
class DeliveryOutboxRecord:
    id: int
    tweet_id: str
    source_user_id: str
    source_username: str
    client_used: str
    server_id: str
    channel_id: str
    message_content: str
    payload: dict
    status: str
    attempt_count: int
    next_attempt_at: Optional[str]
    created_at: Optional[str]
    delivered_at: Optional[str]
    last_error: Optional[str]
    last_attempt_at: Optional[str]
    matched_rule_name: Optional[str]
    lease_token: Optional[str]
    lease_expires_at: Optional[str]


async def enqueue_delivery(
    cursor,
    *,
    tweet_id: str,
    source_user_id: str,
    source_username: str,
    client_used: str,
    server_id: str,
    channel_id: str,
    message_content: str,
    payload: dict,
    created_at: str,
    matched_rule_name: Optional[str],
) -> bool:
    await cursor.execute(
        '''
        INSERT OR IGNORE INTO delivery_outbox (
            tweet_id,
            source_user_id,
            source_username,
            client_used,
            server_id,
            channel_id,
            message_content,
            payload_json,
            status,
            attempt_count,
            next_attempt_at,
            created_at,
            delivered_at,
            last_error,
            last_attempt_at,
            matched_rule_name
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'pending', 0, ?, ?, NULL, NULL, NULL, ?)
        ''',
        (
            tweet_id,
            source_user_id,
            source_username,
            client_used,
            server_id,
            channel_id,
            message_content,
            json.dumps(payload, separators=(',', ':')),
            created_at,
            created_at,
            matched_rule_name,
        ),
    )
    return cursor.rowcount > 0


def _row_to_record(row) -> DeliveryOutboxRecord:
    return DeliveryOutboxRecord(
        id=int(row['id']),
        tweet_id=str(row['tweet_id']),
        source_user_id=str(row['source_user_id']),
        source_username=str(row['source_username']),
        client_used=str(row['client_used']),
        server_id=str(row['server_id']),
        channel_id=str(row['channel_id']),
        message_content=str(row['message_content']),
        payload=json.loads(row['payload_json']),
        status=str(row['status']),
        attempt_count=int(row['attempt_count'] or 0),
        next_attempt_at=row['next_attempt_at'],
        created_at=row['created_at'],
        delivered_at=row['delivered_at'],
        last_error=row['last_error'],
        last_attempt_at=row['last_attempt_at'],
        matched_rule_name=row['matched_rule_name'],
        lease_token=row['lease_token'],
        lease_expires_at=row['lease_expires_at'],
    )


async def claim_due_deliveries(db_path, due_at: str, *, lease_expires_at: str, limit: int = 100) -> list[DeliveryOutboxRecord]:
    lease_token = secrets.token_hex(16)
    async with connect_writable(db_path) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            '''
            SELECT id
            FROM delivery_outbox
            WHERE (
                status = 'pending'
                AND (next_attempt_at IS NULL OR next_attempt_at <= ?)
            ) OR (
                status = 'processing'
                AND lease_expires_at IS NOT NULL
                AND lease_expires_at <= ?
            )
            ORDER BY created_at ASC, id ASC
            LIMIT ?
            ''',
            (due_at, due_at, limit),
        ) as cursor:
            ids = [int(row['id']) async for row in cursor]
        if not ids:
            return []

        placeholders = ','.join('?' for _ in ids)
        await db.execute(
            f'''
            UPDATE delivery_outbox
            SET status = 'processing',
                lease_token = ?,
                lease_expires_at = ?
            WHERE id IN ({placeholders})
              AND (
                status = 'pending'
                OR (
                    status = 'processing'
                    AND lease_expires_at IS NOT NULL
                    AND lease_expires_at <= ?
                )
              )
            ''',
            (lease_token, lease_expires_at, *ids, due_at),
        )
        await db.commit()

        async with db.execute(
            '''
            SELECT
                id,
                tweet_id,
                source_user_id,
                source_username,
                client_used,
                server_id,
                channel_id,
                message_content,
                payload_json,
                status,
                attempt_count,
                next_attempt_at,
                created_at,
                delivered_at,
                last_error,
                last_attempt_at,
                matched_rule_name,
                lease_token,
                lease_expires_at
            FROM delivery_outbox
            WHERE lease_token = ?
              AND status = 'processing'
            ORDER BY created_at ASC, id ASC
            ''',
            (lease_token,),
        ) as cursor:
            rows = await cursor.fetchall()
    return [_row_to_record(row) for row in rows]


async def list_due_deliveries(db_path, due_at: str, limit: int = 100) -> list[DeliveryOutboxRecord]:
    async with connect_readonly(db_path) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            '''
            SELECT
                id,
                tweet_id,
                source_user_id,
                source_username,
                client_used,
                server_id,
                channel_id,
                message_content,
                payload_json,
                status,
                attempt_count,
                next_attempt_at,
                created_at,
                delivered_at,
                last_error,
                last_attempt_at,
                matched_rule_name,
                lease_token,
                lease_expires_at
            FROM delivery_outbox
            WHERE status IN ('pending', 'processing', 'failed', 'delivered')
              AND (next_attempt_at IS NULL OR next_attempt_at <= ? OR next_attempt_at IS NOT NULL)
            ORDER BY created_at ASC, id ASC
            LIMIT ?
            ''',
            (due_at, limit),
        ) as cursor:
            rows = await cursor.fetchall()
    return [_row_to_record(row) for row in rows]


async def mark_delivery_success(db_path, delivery_id: int, lease_token: str, delivered_at: str) -> None:
    async with connect_writable(db_path) as db:
        await db.execute(
            '''
            UPDATE delivery_outbox
            SET status = 'delivered',
                delivered_at = ?,
                next_attempt_at = NULL,
                last_error = NULL,
                last_attempt_at = ?,
                lease_token = NULL,
                lease_expires_at = NULL
            WHERE id = ?
              AND status = 'processing'
              AND lease_token = ?
            ''',
            (delivered_at, delivered_at, delivery_id, lease_token),
        )
        await db.commit()


async def mark_delivery_retry(db_path, delivery_id: int, lease_token: str, *, attempted_at: str, next_attempt_at: str, last_error: str) -> None:
    async with connect_writable(db_path) as db:
        await db.execute(
            '''
            UPDATE delivery_outbox
            SET status = 'pending',
                attempt_count = attempt_count + 1,
                next_attempt_at = ?,
                last_error = ?,
                last_attempt_at = ?,
                lease_token = NULL,
                lease_expires_at = NULL
            WHERE id = ?
              AND status = 'processing'
              AND lease_token = ?
            ''',
            (next_attempt_at, last_error, attempted_at, delivery_id, lease_token),
        )
        await db.commit()


async def mark_delivery_failed(db_path, delivery_id: int, lease_token: str, *, attempted_at: str, last_error: str) -> None:
    async with connect_writable(db_path) as db:
        await db.execute(
            '''
            UPDATE delivery_outbox
            SET status = 'failed',
                attempt_count = attempt_count + 1,
                next_attempt_at = NULL,
                last_error = ?,
                last_attempt_at = ?,
                lease_token = NULL,
                lease_expires_at = NULL
            WHERE id = ?
              AND status = 'processing'
              AND lease_token = ?
            ''',
            (last_error, attempted_at, delivery_id, lease_token),
        )
        await db.commit()


async def fail_open_deliveries_for_destination(
    db_path,
    source_username: str,
    channel_id: str,
    last_error: str,
) -> int:
    async with connect_writable(db_path) as db:
        cursor = await db.execute(
            '''
            UPDATE delivery_outbox
            SET status = 'failed',
                next_attempt_at = NULL,
                last_error = ?,
                lease_token = NULL,
                lease_expires_at = NULL
            WHERE lower(source_username) = lower(?)
              AND channel_id = ?
              AND status NOT IN ('delivered', 'failed')
            ''',
            (
                last_error[:500],
                source_username,
                str(channel_id),
            ),
        )
        await db.commit()
        return int(cursor.rowcount)
