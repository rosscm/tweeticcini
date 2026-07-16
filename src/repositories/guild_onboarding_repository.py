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
            INSERT INTO guild_onboarding_state (server_id, onboarding_sent_at, onboarding_dismissed, test_alert_sent_at, requires_test_alert_step)
            VALUES (?, ?, 0, NULL, 1)
            ON CONFLICT(server_id) DO UPDATE SET onboarding_sent_at = excluded.onboarding_sent_at
            ''',
            (server_id, sent_at),
        )
        await db.commit()


async def is_onboarding_dismissed(db_path, server_id: str) -> bool:
    async with connect_readonly(db_path) as db:
        async with db.execute(
            '''
            SELECT onboarding_dismissed
            FROM guild_onboarding_state
            WHERE server_id = ?
            LIMIT 1
            ''',
            (server_id,),
        ) as cursor:
            row = await cursor.fetchone()
    return bool(row and int(row[0] or 0))


async def set_onboarding_dismissed(db_path, server_id: str, dismissed: bool) -> None:
    async with connect_writable(db_path) as db:
        await db.execute(
            '''
            INSERT INTO guild_onboarding_state (server_id, onboarding_sent_at, onboarding_dismissed, test_alert_sent_at, requires_test_alert_step)
            VALUES (?, NULL, ?, NULL, 1)
            ON CONFLICT(server_id) DO UPDATE SET onboarding_dismissed = excluded.onboarding_dismissed
            ''',
            (server_id, int(dismissed)),
        )
        await db.commit()


async def get_test_alert_sent_at(db_path, server_id: str) -> str | None:
    async with connect_readonly(db_path) as db:
        async with db.execute(
            '''
            SELECT test_alert_sent_at
            FROM guild_onboarding_state
            WHERE server_id = ?
            LIMIT 1
            ''',
            (server_id,),
        ) as cursor:
            row = await cursor.fetchone()
    if row is None:
        return None
    return str(row[0]) if row[0] else None


async def get_requires_test_alert_step(db_path, server_id: str) -> bool | None:
    async with connect_readonly(db_path) as db:
        async with db.execute(
            '''
            SELECT requires_test_alert_step
            FROM guild_onboarding_state
            WHERE server_id = ?
            LIMIT 1
            ''',
            (server_id,),
        ) as cursor:
            row = await cursor.fetchone()
    if row is None or row[0] is None:
        return None
    return bool(int(row[0] or 0))


async def ensure_onboarding_state(db_path, server_id: str, *, requires_test_alert_step: bool) -> None:
    async with connect_writable(db_path) as db:
        await db.execute(
            '''
            INSERT OR IGNORE INTO guild_onboarding_state (
                server_id,
                onboarding_sent_at,
                onboarding_dismissed,
                test_alert_sent_at,
                requires_test_alert_step
            )
            VALUES (?, NULL, 0, NULL, ?)
            ''',
            (server_id, int(requires_test_alert_step)),
        )
        await db.commit()


async def mark_test_alert_sent(db_path, server_id: str, sent_at: str) -> None:
    async with connect_writable(db_path) as db:
        await db.execute(
            '''
            INSERT INTO guild_onboarding_state (server_id, onboarding_sent_at, onboarding_dismissed, test_alert_sent_at, requires_test_alert_step)
            VALUES (?, NULL, 0, ?, 1)
            ON CONFLICT(server_id) DO UPDATE SET
                onboarding_dismissed = 0,
                test_alert_sent_at = excluded.test_alert_sent_at
            ''',
            (server_id, sent_at),
        )
        await db.commit()
