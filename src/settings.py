from pathlib import Path
import os

from configs.load_configs import configs


DB_FILENAME = 'tracked_accounts.db'


def get_data_path() -> Path:
    return Path(os.getenv('DATA_PATH'))


def get_db_path() -> Path:
    return get_data_path() / DB_FILENAME


def get_accounts() -> dict[str, str]:
    accounts_str = os.getenv('TWITTER_TOKEN').strip(',')
    return {
        account.split(':', 1)[0]: account.split(':', 1)[1]
        for account in accounts_str.split(',')
        if account
    }


def get_default_message() -> str:
    return configs['default_message']
