import aiosqlite

from src.repositories.twitter_session_repository import list_all_server_twitter_session_keys
from src.settings import get_accounts, get_db_path

async def auto_repair_mismatched_clients(invalid_clients: set[str]):
    available_clients = list(get_accounts())
    if not available_clients:
        available_clients = await list_all_server_twitter_session_keys(get_db_path())
    if not available_clients:
        return

    default_client = available_clients[0]
    
    async with aiosqlite.connect(get_db_path()) as db:
        async with db.execute(
            '''
            SELECT rowid, client_used
            FROM notification
            WHERE enabled = 1
              AND client_used IS NOT NULL
              AND client_used != ''
            '''
        ) as cursor:
            rows = await cursor.fetchall()
            updates = [(default_client, row_id) for row_id, client_used in rows if client_used in invalid_clients]
            
            if updates:
                await db.executemany('UPDATE notification SET client_used = ? WHERE rowid = ?', updates)
                await db.commit()
