import os
import shutil
import json
from typing import Optional

from tweety import Twitter

from src.adapters.tweety_compat import apply_tweety_compat_patch
from src.settings import get_legacy_twitter_session_path, get_twitter_session_path


if os.getenv('DISABLE_TWEETY_COMPAT', '').lower() not in {'1', 'true', 'yes'}:
    apply_tweety_compat_patch()


class TwitterSessionAdapter:
    def __init__(self, client_name: str):
        self.client_name = client_name
        session_path = get_twitter_session_path(client_name)
        legacy_path = get_legacy_twitter_session_path(client_name)
        if legacy_path.exists() and not session_path.exists():
            session_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(legacy_path), str(session_path))
        self._client = Twitter(str(session_path))

    async def connect(self) -> None:
        await self._client.connect()

    async def load_auth_token(self, auth_token: str):
        return await self._client.load_auth_token(auth_token)

    async def get_user_info(self, username: str):
        return await self._client.get_user_info(username)

    async def get_tweet_notifications(self):
        return await self._client.get_tweet_notifications()

    async def follow_user(self, target):
        return await self._client.follow_user(target)

    async def enable_user_notification(self, target):
        return await self._client.enable_user_notification(target)

    async def disable_user_notification(self, target):
        return await self._client.disable_user_notification(target)

    async def unfollow_user(self, target):
        return await self._client.unfollow_user(target)

    def get_authenticated_user_identity(self) -> tuple[Optional[str], Optional[str]]:
        session_path = get_twitter_session_path(self.client_name)
        if not session_path.exists():
            return None, None

        try:
            payload = json.loads(session_path.read_text())
        except Exception:
            return None, None

        user = payload.get('user') or {}
        user_id = user.get('id') or user.get('rest_id')
        username = user.get('username') or user.get('screen_name')
        return (
            str(user_id).strip() if user_id else None,
            str(username).strip() if username else None,
        )


def create_twitter_session(client_name: str) -> TwitterSessionAdapter:
    return TwitterSessionAdapter(client_name)
