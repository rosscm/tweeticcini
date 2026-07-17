from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from src.notification.account_tracker import AccountTracker


def _tracker(
    *,
    max_per_cycle: int = 1,
    max_age_minutes: int = 15,
):
    tracker = object.__new__(AccountTracker)
    tracker.max_tweets_per_source_cycle = max_per_cycle
    tracker.max_tweet_backfill_age_minutes = max_age_minutes
    return tracker


def _tweet(tweet_id: str, created_on: datetime):
    return SimpleNamespace(
        id=tweet_id,
        created_on=created_on,
    )


def test_backlog_processes_oldest_recent_tweet_first():
    now = datetime(
        2026,
        7,
        17,
        16,
        0,
        tzinfo=timezone.utc,
    )
    tracker = _tracker(max_per_cycle=1)

    tweets = [
        _tweet('tweet-1', now - timedelta(minutes=3)),
        _tweet('tweet-2', now - timedelta(minutes=2)),
        _tweet('tweet-3', now - timedelta(minutes=1)),
    ]

    expired, selected, deferred = (
        tracker._select_tweets_for_cycle(tweets, now)
    )

    assert expired == []
    assert [tweet.id for tweet in selected] == ['tweet-1']
    assert [tweet.id for tweet in deferred] == [
        'tweet-2',
        'tweet-3',
    ]


def test_backlog_expires_old_tweets_without_selecting_them():
    now = datetime(
        2026,
        7,
        17,
        16,
        0,
        tzinfo=timezone.utc,
    )
    tracker = _tracker(
        max_per_cycle=1,
        max_age_minutes=15,
    )

    tweets = [
        _tweet('expired-1', now - timedelta(minutes=30)),
        _tweet('expired-2', now - timedelta(minutes=20)),
        _tweet('recent-1', now - timedelta(minutes=5)),
        _tweet('recent-2', now - timedelta(minutes=2)),
    ]

    expired, selected, deferred = (
        tracker._select_tweets_for_cycle(tweets, now)
    )

    assert [tweet.id for tweet in expired] == [
        'expired-1',
        'expired-2',
    ]
    assert [tweet.id for tweet in selected] == ['recent-1']
    assert [tweet.id for tweet in deferred] == ['recent-2']


def test_backlog_accepts_naive_timestamps_as_utc():
    now = datetime(
        2026,
        7,
        17,
        16,
        0,
        tzinfo=timezone.utc,
    )
    tracker = _tracker()

    tweets = [
        _tweet(
            'naive',
            datetime(2026, 7, 17, 15, 55),
        ),
    ]

    expired, selected, deferred = (
        tracker._select_tweets_for_cycle(tweets, now)
    )

    assert expired == []
    assert [tweet.id for tweet in selected] == ['naive']
    assert deferred == []
