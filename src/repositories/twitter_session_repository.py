import aiosqlite

from src.db_function.readonly_db import connect_readonly
from src.repositories.notifier_repository import connect_writable


async def list_server_twitter_sessions(db_path, server_id: str):
    async with connect_readonly(db_path) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            '''
            SELECT
                server_id,
                session_name,
                client_key,
                status,
                last_validated_at,
                last_error_at,
                last_error_message,
                created_at,
                updated_at,
                is_active
            FROM server_twitter_session
            WHERE server_id = ?
              AND is_active = 1
            ORDER BY session_name ASC
            ''',
            (server_id,),
        ) as cursor:
            return await cursor.fetchall()


async def list_active_server_twitter_sessions(db_path):
    async with connect_readonly(db_path) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            '''
            SELECT
                server_id,
                session_name,
                client_key,
                encrypted_auth_token,
                status,
                last_validated_at,
                last_error_at,
                last_error_message,
                created_at,
                updated_at
            FROM server_twitter_session
            WHERE is_active = 1
            ORDER BY server_id ASC, session_name ASC
            '''
        ) as cursor:
            return await cursor.fetchall()


async def get_server_twitter_session(db_path, server_id: str, session_name: str):
    async with connect_readonly(db_path) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            '''
            SELECT
                server_id,
                session_name,
                client_key,
                encrypted_auth_token,
                status,
                last_validated_at,
                last_error_at,
                last_error_message,
                created_at,
                updated_at,
                is_active
            FROM server_twitter_session
            WHERE server_id = ? AND session_name = ?
            ''',
            (server_id, session_name),
        ) as cursor:
            return await cursor.fetchone()


async def list_server_twitter_session_keys(db_path, server_id: str) -> list[str]:
    async with connect_readonly(db_path) as db:
        async with db.execute(
            '''
            SELECT client_key
            FROM server_twitter_session
            WHERE server_id = ? AND is_active = 1 AND status = 'active'
            ORDER BY session_name ASC
            ''',
            (server_id,),
        ) as cursor:
            rows = await cursor.fetchall()
    return [str(row[0]) for row in rows]


async def list_all_server_twitter_session_keys(db_path) -> list[str]:
    async with connect_readonly(db_path) as db:
        async with db.execute(
            '''
            SELECT client_key
            FROM server_twitter_session
            WHERE is_active = 1
            '''
        ) as cursor:
            rows = await cursor.fetchall()
    return [str(row[0]) for row in rows]


async def upsert_server_twitter_session(
    db_path,
    server_id: str,
    session_name: str,
    client_key: str,
    encrypted_auth_token: str,
    status: str,
    last_validated_at,
    last_error_at,
    last_error_message,
    created_at,
    updated_at,
) -> None:
    async with connect_writable(db_path) as db:
        await db.execute(
            '''
            INSERT INTO server_twitter_session (
                server_id,
                session_name,
                client_key,
                encrypted_auth_token,
                status,
                last_validated_at,
                last_error_at,
                last_error_message,
                is_active,
                created_at,
                updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?)
            ON CONFLICT(server_id, session_name) DO UPDATE SET
                client_key = excluded.client_key,
                encrypted_auth_token = excluded.encrypted_auth_token,
                status = excluded.status,
                last_validated_at = excluded.last_validated_at,
                last_error_at = excluded.last_error_at,
                last_error_message = excluded.last_error_message,
                is_active = 1,
                updated_at = excluded.updated_at
            ''',
            (
                server_id,
                session_name,
                client_key,
                encrypted_auth_token,
                status,
                last_validated_at,
                last_error_at,
                last_error_message,
                created_at,
                updated_at,
            ),
        )
        await db.commit()


async def disable_server_twitter_session(db_path, server_id: str, session_name: str, updated_at) -> None:
    async with connect_writable(db_path) as db:
        await db.execute(
            '''
            UPDATE server_twitter_session
            SET is_active = 0,
                updated_at = ?
            WHERE server_id = ? AND session_name = ?
            ''',
            (updated_at, server_id, session_name),
        )
        await db.commit()


async def delete_server_twitter_session(db_path, server_id: str, session_name: str) -> None:
    async with connect_writable(db_path) as db:
        await db.execute(
            '''
            DELETE FROM server_twitter_session
            WHERE server_id = ? AND session_name = ?
            ''',
            (server_id, session_name),
        )
        await db.commit()
