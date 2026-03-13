from tweety import Twitter


class TwitterSessionAdapter:
    def __init__(self, client_name: str):
        self.client_name = client_name
        self._client = Twitter(client_name)

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


def create_twitter_session(client_name: str) -> TwitterSessionAdapter:
    return TwitterSessionAdapter(client_name)
