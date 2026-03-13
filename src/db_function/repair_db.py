import aiosqlite

from src.settings import get_accounts, get_db_path

async def auto_repair_mismatched_clients(invalid_clients: set[str]):
    default_client = next(iter(get_accounts()))
    
    async with aiosqlite.connect(get_db_path()) as db:
        async with db.execute('SELECT id, client_used FROM user') as cursor:
            rows = await cursor.fetchall()
            updates = [(default_client, user_id) for user_id, client_used in rows if client_used in invalid_clients]
            
            if updates:
                await db.executemany('UPDATE user SET client_used = ? WHERE id = ?', updates)
                await db.commit()
