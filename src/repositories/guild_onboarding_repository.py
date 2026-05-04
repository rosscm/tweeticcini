from src.db_function.readonly_db import connect_readonly
from src.repositories.notifier_repository import connect_writable


async def was_onboarding_sent(db_path, server_id: str) -> bool:
    async with connect_readonly(db_path) as db:
        async with db.execute(
            '''
            SELECT 1
            FROM guild_onboarding_state
            WHERE server_id = ?
            LIMIT 1
            ''',
            (server_id,),
        ) as cursor:
            row = await cursor.fetchone()
    return row is not None


async def mark_onboarding_sent(db_path, server_id: str, sent_at: str) -> None:
    async with connect_writable(db_path) as db:
        await db.execute(
            '''
            INSERT INTO guild_onboarding_state (server_id, onboarding_sent_at)
            VALUES (?, ?)
            ON CONFLICT(server_id) DO UPDATE SET onboarding_sent_at = excluded.onboarding_sent_at
            ''',
            (server_id, sent_at),
        )
        await db.commit()
