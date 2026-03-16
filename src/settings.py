import os
from pathlib import Path

from configs.load_configs import configs
from dotenv import load_dotenv


load_dotenv()


DB_FILENAME = 'tracked_accounts.db'


def get_data_path() -> Path:
    data_path = os.getenv('DATA_PATH')
    if data_path:
        return Path(data_path)
    return Path.cwd() / 'data'


def get_db_path() -> Path:
    return get_data_path() / DB_FILENAME


def get_accounts() -> dict[str, str]:
    accounts_env = os.getenv('TWITTER_TOKEN', '')
    accounts_str = accounts_env.strip(',')
    return {
        account.split(':', 1)[0]: account.split(':', 1)[1]
        for account in accounts_str.split(',')
        if account
    }


def get_default_message() -> str:
    return configs['default_message']
