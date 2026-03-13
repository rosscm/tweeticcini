import asyncio

from datetime import datetime, timezone

from src.settings import get_accounts as get_twitter_accounts


class LockManager:
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance.lock = asyncio.Lock()
        return cls._instance


def get_lock():
    return LockManager().lock


def bool_to_str(boo: bool):
    return '1' if boo else '0'


def str_to_bool(string: str):
    return False if string == '0' else True


def get_accounts():
    return get_twitter_accounts()


def get_utcnow():
    return datetime.now(timezone.utc).isoformat(timespec='seconds').replace('T', ' ')


def extract_first_line(text: str) -> str:
    lines = text.strip().splitlines()
    for line in lines:
        if line.strip() and not line.lower().startswith("http"):
            return line.strip()
    return ""
