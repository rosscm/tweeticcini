from typing import Optional

from src.repositories.notifier_repository import get_last_tweet_at
from src.settings import get_db_path
from tweety.types import Tweet

from src.notification.date_comparator import date_comparator


async def get_tweets(tweets: list[Tweet], username: str) -> Optional[list[Tweet]]:
    last_tweet_at = await get_last_tweet_at(get_db_path(), username)

    tweets = [tweet for tweet in tweets if tweet.author.username == username and date_comparator(tweet.created_on, last_tweet_at) == 1]

    if tweets != []:
        return sorted(tweets, key=lambda x: x.created_on)
    else:
        return None
