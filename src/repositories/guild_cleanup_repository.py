from src.repositories.notifier_repository import connect_writable
from src.settings import get_legacy_twitter_session_path, get_twitter_session_path


async def cleanup_guild_data(db_path, server_id: str) -> dict[str, int]:
    async with connect_writable(db_path) as db:
        async with db.execute(
            'SELECT client_key FROM server_twitter_session WHERE server_id = ?',
            (server_id,),
        ) as cursor:
            client_keys = [str(row[0]) for row in await cursor.fetchall()]

        async with db.execute(
            'SELECT id FROM channel WHERE server_id = ?',
            (server_id,),
        ) as cursor:
            channel_ids = [str(row[0]) for row in await cursor.fetchall()]

        notification_count = 0
        channel_count = 0
        if channel_ids:
            placeholders = ','.join('?' for _ in channel_ids)
            cursor = await db.execute(
                f'DELETE FROM notification WHERE channel_id IN ({placeholders})',
                tuple(channel_ids),
            )
            notification_count = cursor.rowcount
            cursor = await db.execute(
                f'DELETE FROM channel WHERE id IN ({placeholders})',
                tuple(channel_ids),
            )
            channel_count = cursor.rowcount

        runtime_client_count = 0
        user_client_state_count = 0
        if client_keys:
            placeholders = ','.join('?' for _ in client_keys)
            cursor = await db.execute(
                f'DELETE FROM runtime_client_status WHERE client_used IN ({placeholders})',
                tuple(client_keys),
            )
            runtime_client_count = cursor.rowcount
            cursor = await db.execute(
                f'DELETE FROM user_client_state WHERE client_used IN ({placeholders})',
                tuple(client_keys),
            )
            user_client_state_count = cursor.rowcount

        cursor = await db.execute(
            'DELETE FROM runtime_source_status WHERE server_id = ?',
            (server_id,),
        )
        runtime_source_count = cursor.rowcount

        cursor = await db.execute(
            'DELETE FROM alert_rule WHERE server_id = ?',
            (server_id,),
        )
        alert_rule_count = cursor.rowcount

        cursor = await db.execute(
            'DELETE FROM guild_settings WHERE server_id = ?',
            (server_id,),
        )
        guild_settings_count = cursor.rowcount

        cursor = await db.execute(
            'DELETE FROM guild_entitlement WHERE server_id = ?',
            (server_id,),
        )
        guild_entitlement_count = cursor.rowcount

        guild_onboarding_count = 0
        cursor = await db.execute(
            'DELETE FROM guild_onboarding_state WHERE server_id = ?',
            (server_id,),
        )
        guild_onboarding_count = cursor.rowcount

        cursor = await db.execute(
            'DELETE FROM server_twitter_session WHERE server_id = ?',
            (server_id,),
        )
        twitter_session_count = cursor.rowcount

        cursor = await db.execute(
            '''
            DELETE FROM user
            WHERE id NOT IN (
                SELECT DISTINCT user_id
                FROM notification
            )
            '''
        )
        orphan_user_count = cursor.rowcount

        await db.commit()

    session_file_count = 0
    for client_key in client_keys:
        for session_path in (get_twitter_session_path(client_key), get_legacy_twitter_session_path(client_key)):
            if session_path.exists():
                session_path.unlink()
                session_file_count += 1

    return {
        'notifications': notification_count,
        'channels': channel_count,
        'runtime_clients': runtime_client_count,
        'user_client_states': user_client_state_count,
        'runtime_sources': runtime_source_count,
        'alert_rules': alert_rule_count,
        'guild_settings': guild_settings_count,
        'guild_entitlements': guild_entitlement_count,
        'guild_onboarding': guild_onboarding_count,
        'twitter_sessions': twitter_session_count,
        'session_files': session_file_count,
        'orphan_users': orphan_user_count,
    }
