from src.db_function.readonly_db import connect_readonly
from src.repositories.notifier_repository import connect_writable


async def mark_bot_runtime_error(db_path, error_message: str, happened_at: str) -> None:
    async with connect_writable(db_path) as db:
        await db.execute(
            '''
            INSERT INTO bot_runtime_health (
                singleton_id,
                state,
                last_error_message,
                last_error_at
            ) VALUES (1, 'error', ?, ?)
            ON CONFLICT(singleton_id) DO UPDATE SET
                state = 'error',
                last_error_message = excluded.last_error_message,
                last_error_at = excluded.last_error_at
            ''',
            (str(error_message).strip()[:300], happened_at),
        )
        await db.commit()


async def mark_bot_runtime_recovered(db_path, happened_at: str) -> None:
    async with connect_writable(db_path) as db:
        await db.execute(
            '''
            INSERT INTO bot_runtime_health (
                singleton_id,
                state,
                last_error_message,
                last_error_at,
                last_recovered_at
            ) VALUES (1, 'healthy', NULL, NULL, ?)
            ON CONFLICT(singleton_id) DO UPDATE SET
                state = 'healthy',
                last_error_message = NULL,
                last_error_at = NULL,
                last_recovered_at = excluded.last_recovered_at
            ''',
            (happened_at,),
        )
        await db.commit()


async def get_bot_runtime_health(db_path):
    async with connect_readonly(db_path) as db:
        async with db.execute(
            '''
            SELECT state, last_error_message, last_error_at, last_recovered_at
            FROM bot_runtime_health
            WHERE singleton_id = 1
            LIMIT 1
            '''
        ) as cursor:
            row = await cursor.fetchone()
    if row is None:
        return None
    return {
        'state': row[0],
        'last_error_message': row[1],
        'last_error_at': row[2],
        'last_recovered_at': row[3],
    }
