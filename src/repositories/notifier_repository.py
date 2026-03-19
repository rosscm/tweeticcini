import aiosqlite
from contextlib import asynccontextmanager
from typing import Optional

from src.db_function.readonly_db import connect_readonly


async def get_user_by_username(cursor, username: str):
    await cursor.execute('SELECT * FROM user WHERE username = ?', (username,))
    return await cursor.fetchone()


async def ensure_channel(cursor, channel_id: str, server_id: str) -> None:
    await cursor.execute('INSERT OR IGNORE INTO channel VALUES (?, ?)', (channel_id, server_id))


async def upsert_notification(
    cursor,
    user_id: str,
    channel_id: str,
    client_used: str,
    role_id: str,
    enable_type: str,
    media_type: str,
    force_everyone: bool,
) -> None:
    await cursor.execute(
        '''
        INSERT OR REPLACE INTO notification
        (user_id, channel_id, client_used, role_id, enable_type, enable_media_type, force_everyone)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ''',
        (user_id, channel_id, client_used, role_id, enable_type, media_type, int(force_everyone)),
    )


async def insert_user(cursor, user_id: str, username: str, latest_tweet: str, client_used: str) -> None:
    await cursor.execute(
        'INSERT INTO user (id, username, lastest_tweet, client_used) VALUES (?, ?, ?, ?)',
        (user_id, username, latest_tweet, client_used),
    )


async def update_user_client(cursor, user_id: str, client_used: str) -> None:
    await cursor.execute('UPDATE user SET client_used = ? WHERE id = ?', (client_used, user_id))


async def set_user_enabled(cursor, user_id: str, enabled: bool) -> None:
    await cursor.execute('UPDATE user SET enabled = ? WHERE id = ?', (int(enabled), user_id))


async def get_channel_ids_for_server(cursor, server_id: str) -> list[str]:
    await cursor.execute('SELECT id FROM channel WHERE server_id = ?', (server_id,))
    rows = await cursor.fetchall()
    return [row['id'] for row in rows]


async def get_enabled_notifier_user_id(cursor, username: str, channel_id: str) -> Optional[str]:
    await cursor.execute(
        '''
        SELECT user_id
        FROM notification, user
        WHERE username = ? AND channel_id = ? AND user_id = id AND notification.enabled = 1
        ''',
        (username, channel_id),
    )
    row = await cursor.fetchone()
    return row['user_id'] if row is not None else None


async def get_enabled_notifier_user_id_for_server(cursor, username: str, server_id: str) -> Optional[str]:
    await cursor.execute(
        '''
        SELECT notification.user_id
        FROM notification
        JOIN user ON notification.user_id = user.id
        JOIN channel ON notification.channel_id = channel.id
        WHERE lower(user.username) = lower(?)
          AND channel.server_id = ?
          AND notification.enabled = 1
        LIMIT 1
        ''',
        (username, server_id),
    )
    row = await cursor.fetchone()
    return row['user_id'] if row is not None else None


async def disable_notification(cursor, user_id: str, channel_id: str) -> None:
    await cursor.execute(
        'UPDATE notification SET enabled = 0 WHERE user_id = ? AND channel_id = ?',
        (user_id, channel_id),
    )


async def get_active_notifications_for_user(cursor, user_id: str):
    await cursor.execute('SELECT user_id FROM notification WHERE user_id = ? AND enabled = 1', (user_id,))
    return await cursor.fetchall()


async def get_client_used_for_user(cursor, user_id: str) -> Optional[str]:
    await cursor.execute('SELECT client_used FROM user WHERE id = ?', (user_id,))
    row = await cursor.fetchone()
    return row['client_used'] if row is not None else None


async def reset_custom_message(cursor, user_id: str, channel_id: str) -> None:
    await cursor.execute(
        'UPDATE notification SET customized_msg = ? WHERE user_id = ? AND channel_id = ?',
        (None, user_id, channel_id),
    )


async def set_custom_message(cursor, user_id: str, channel_id: str, customized_msg: str) -> None:
    await cursor.execute(
        'UPDATE notification SET customized_msg = ? WHERE user_id = ? AND channel_id = ?',
        (customized_msg, user_id, channel_id),
    )


async def get_enabled_notifications_for_user(cursor, user_id: str):
    await cursor.execute('SELECT * FROM notification WHERE user_id = ? AND enabled = 1', (user_id,))
    return await cursor.fetchall()


async def get_enabled_notifications_for_user_client(cursor, user_id: str, client_used: str):
    await cursor.execute(
        'SELECT * FROM notification WHERE user_id = ? AND client_used = ? AND enabled = 1',
        (user_id, client_used),
    )
    return await cursor.fetchall()


async def update_user_latest_tweet(cursor, username: str, latest_tweet: str) -> None:
    await cursor.execute('UPDATE user SET lastest_tweet = ? WHERE username = ?', (latest_tweet, username))


async def get_enabled_user_client_pairs(db_path) -> list[tuple[str, str]]:
    async with connect_readonly(db_path) as db:
        async with db.execute(
            '''
            SELECT DISTINCT user.username, notification.client_used
            FROM user
            JOIN notification ON notification.user_id = user.id
            WHERE user.enabled = 1
              AND notification.enabled = 1
              AND notification.client_used IS NOT NULL
            ORDER BY user.username ASC, notification.client_used ASC
            '''
        ) as cursor:
            return [(row[0], row[1]) async for row in cursor]


async def get_all_user_client_map(db_path) -> dict[str, str]:
    async with connect_readonly(db_path) as db:
        async with db.execute('SELECT id, client_used FROM user') as cursor:
            return {row[0]: row[1] async for row in cursor}


async def get_last_tweet_at(db_path, username: str):
    async with connect_readonly(db_path) as db:
        async with db.execute('SELECT lastest_tweet FROM user WHERE username = ?', (username,)) as cursor:
            row = await cursor.fetchone()
    return row[0]


async def list_server_notifications(db_path, server_id: str, account: str = '', channel_id: str = ''):
    async with connect_readonly(db_path) as db:
        async with db.execute(
            '''
            SELECT user.username, channel.id, notification.role_id, notification.enable_type, notification.enable_media_type, notification.client_used
            FROM user
            JOIN notification
            ON user.id = notification.user_id
            JOIN channel
            ON notification.channel_id = channel.id
            WHERE channel.server_id = ? AND notification.enabled = 1
            AND (notification.client_used = ? OR '' = ?)
            AND (channel.id = ? OR '' = ?)
            ''',
            (server_id, account, account, channel_id, channel_id),
        ) as cursor:
            return await cursor.fetchall()


async def count_dashboard_sources(db_path, server_id: str) -> int:
    async with connect_readonly(db_path) as db:
        async with db.execute(
            '''
            SELECT COUNT(*)
            FROM notification
            JOIN channel ON notification.channel_id = channel.id
            WHERE channel.server_id = ?
              AND notification.enabled = 1
            ''',
            (server_id,),
        ) as cursor:
            row = await cursor.fetchone()
    return int(row[0] or 0)


async def list_dashboard_sources(db_path, server_id: str):
    async with connect_readonly(db_path) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            '''
            SELECT
                user.username,
                notification.client_used,
                channel.id AS channel_id,
                notification.role_id,
                notification.enable_type,
                notification.enable_media_type,
                notification.customized_msg,
                COUNT(alert_rule.id) AS rule_count
            FROM user
            JOIN notification ON user.id = notification.user_id
            JOIN channel ON notification.channel_id = channel.id
            LEFT JOIN alert_rule
              ON alert_rule.server_id = channel.server_id
             AND alert_rule.enabled = 1
             AND (
                alert_rule.source_username IS NULL
                OR lower(alert_rule.source_username) = lower(user.username)
             )
             AND (
                alert_rule.channel_id IS NULL
                OR alert_rule.channel_id = channel.id
             )
            WHERE channel.server_id = ?
              AND notification.enabled = 1
            GROUP BY
                user.username,
                notification.client_used,
                channel.id,
                notification.role_id,
                notification.enable_type,
                notification.enable_media_type,
                notification.customized_msg
            ORDER BY user.username ASC, channel.id ASC
            ''',
            (server_id,),
        ) as cursor:
            return await cursor.fetchall()


async def update_notification_settings(
    db_path,
    username: str,
    channel_id: str,
    client_used: str,
    role_id: str,
    enable_type: str,
    media_type: str,
) -> bool:
    async with connect_writable(db_path) as db:
        cursor = await db.execute(
            '''
            UPDATE notification
            SET client_used = ?, role_id = ?, enable_type = ?, enable_media_type = ?
            WHERE channel_id = ?
              AND user_id = (SELECT id FROM user WHERE username = ?)
            ''',
            (client_used, role_id, enable_type, media_type, channel_id, username),
        )
        await db.commit()
        return cursor.rowcount > 0


async def get_dashboard_source_message(db_path, username: str, channel_id: str) -> Optional[str]:
    async with connect_readonly(db_path) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            '''
            SELECT notification.customized_msg
            FROM notification
            JOIN user ON user.id = notification.user_id
            WHERE user.username = ?
              AND notification.channel_id = ?
              AND notification.enabled = 1
            ''',
            (username, channel_id),
        ) as cursor:
            row = await cursor.fetchone()
    if row is None:
        return None
    return row['customized_msg']


async def get_enabled_client_names(db_path) -> list[str]:
    async with connect_readonly(db_path) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            '''
            SELECT notification.client_used
            FROM notification
            JOIN user ON user.id = notification.user_id
            WHERE user.enabled = 1
              AND notification.enabled = 1
              AND notification.client_used IS NOT NULL
            '''
        ) as cursor:
            return list({row['client_used'] async for row in cursor})


async def get_server_channel_ids(db_path, server_id: str) -> list[str]:
    async with connect_readonly(db_path) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute('SELECT id FROM channel WHERE server_id = ?', (server_id,)) as cursor:
            return [row['id'] async for row in cursor]


async def get_active_channel_ids_for_server(db_path, server_id: str) -> list[str]:
    async with connect_readonly(db_path) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            '''
            SELECT c.id
            FROM channel AS c
            WHERE c.server_id = ?
            AND EXISTS (
                SELECT 1
                FROM notification AS n
                WHERE n.channel_id = c.id
                AND n.enabled = 1
            )
            ''',
            (server_id,),
        ) as cursor:
            return [row['id'] async for row in cursor]


async def get_enabled_usernames_for_channel(db_path, channel_id: str) -> list[str]:
    async with connect_readonly(db_path) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            '''
            SELECT user.username
            FROM user
            JOIN notification ON user.id = notification.user_id
            WHERE notification.channel_id = ? AND notification.enabled = 1
            ''',
            (channel_id,),
        ) as cursor:
            return [row['username'] async for row in cursor]


@asynccontextmanager
async def connect_writable(db_path):
    async with aiosqlite.connect(db_path, timeout=30) as db:
        await db.execute('PRAGMA journal_mode = WAL')
        await db.execute('PRAGMA synchronous = NORMAL')
        await db.execute('PRAGMA busy_timeout = 30000')
        await db.execute('PRAGMA count_changes = OFF')
        db.row_factory = aiosqlite.Row
        yield db
