import asyncio

from src.adapters.twitter_adapter import create_twitter_session
from src.log import setup_logger
from src.utils import get_accounts

log = setup_logger(__name__)


async def sync_db(follow_list: dict[str, str]) -> None:

    apps = {}
    for account_name, _ in get_accounts().items():
        app = create_twitter_session(account_name)
        await app.connect()
        apps[account_name] = app

    for user_id, client_used in follow_list.items():
        app = apps[client_used]
        await app.follow_user(user_id)
        await app.enable_user_notification(user_id)
        await asyncio.sleep(1)

    log.info('synchronization with database completed')
