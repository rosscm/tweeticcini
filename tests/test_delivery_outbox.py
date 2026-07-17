import signal
from contextlib import contextmanager
from dataclasses import replace
from types import SimpleNamespace

import pytest
import asyncio
import aiosqlite
import sqlite3
from unittest.mock import AsyncMock

from src.db_function.guild_settings import get_default_guild_presentation_settings
from src.notification.account_tracker import AccountTracker
from src.repositories.delivery_outbox_repository import claim_due_deliveries, enqueue_delivery, list_due_deliveries
from src.services.guild_settings_service import (
    GuildComplianceView,
    GuildEntitlementView,
    GuildPlanFeatures,
    GuildPresentationView,
)
from src.settings import get_db_path


@pytest.fixture(autouse=True)
def reset_tracker_singleton():
    AccountTracker._instance = None
    yield
    AccountTracker._instance = None


@pytest.fixture
def env(monkeypatch, tmp_path):
    monkeypatch.setenv('DATA_PATH', str(tmp_path))


@contextmanager
def fail_after(seconds: int):
    def _handle_timeout(_signum, _frame):
        raise TimeoutError(f'test exceeded {seconds}s timeout')

    previous_handler = signal.signal(signal.SIGALRM, _handle_timeout)
    signal.setitimer(signal.ITIMER_REAL, seconds)
    try:
        yield
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous_handler)


async def ensure_outbox_test_schema():
    async with aiosqlite.connect(get_db_path()) as db:
        await db.executescript(
            """
            CREATE TABLE IF NOT EXISTS user (
                id TEXT PRIMARY KEY,
                username TEXT NOT NULL UNIQUE,
                enabled INTEGER DEFAULT 1
            );
            CREATE TABLE IF NOT EXISTS notification (
                user_id TEXT NOT NULL,
                channel_id TEXT NOT NULL,
                client_used TEXT DEFAULT NULL,
                enabled INTEGER DEFAULT 1,
                delivery_paused INTEGER NOT NULL DEFAULT 0,
                delivery_pause_reason TEXT DEFAULT NULL,
                delivery_paused_at TEXT DEFAULT NULL,
                PRIMARY KEY (user_id, channel_id)
            );
            CREATE TABLE IF NOT EXISTS delivery_outbox (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                tweet_id TEXT NOT NULL,
                source_user_id TEXT NOT NULL,
                source_username TEXT NOT NULL,
                client_used TEXT NOT NULL,
                server_id TEXT NOT NULL,
                channel_id TEXT NOT NULL,
                message_content TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                attempt_count INTEGER NOT NULL DEFAULT 0,
                next_attempt_at TEXT DEFAULT NULL,
                created_at TEXT DEFAULT NULL,
                delivered_at TEXT DEFAULT NULL,
                last_error TEXT DEFAULT NULL,
                last_attempt_at TEXT DEFAULT NULL,
                matched_rule_name TEXT DEFAULT NULL,
                lease_token TEXT DEFAULT NULL,
                lease_expires_at TEXT DEFAULT NULL
            );
            CREATE UNIQUE INDEX IF NOT EXISTS idx_delivery_outbox_tweet_channel
            ON delivery_outbox (tweet_id, channel_id);
            CREATE TABLE IF NOT EXISTS runtime_source_status (
                server_id TEXT NOT NULL,
                username TEXT NOT NULL,
                channel_id TEXT NOT NULL,
                last_delivery_success_at TEXT DEFAULT NULL,
                last_delivery_error_at TEXT DEFAULT NULL,
                last_error_message TEXT DEFAULT NULL,
                last_matched_rule_name TEXT DEFAULT NULL,
                last_delivery_url TEXT DEFAULT NULL,
                success_count INTEGER DEFAULT 0,
                error_count INTEGER DEFAULT 0,
                PRIMARY KEY(server_id, username, channel_id)
            );
            """
        )
        await db.commit()


def _build_view() -> GuildPresentationView:
    features = GuildPlanFeatures(
        max_twitter_sessions=1,
        max_sources=1,
        max_rules=0,
        max_trigger_keywords_total=0,
        max_exclude_keywords_total=0,
        can_customize_presentation=False,
        can_customize_source_messages=False,
        can_use_everyone_escalation=False,
    )
    return GuildPresentationView(
        plan='free',
        features=replace(features, max_sources=5),
        effective=get_default_guild_presentation_settings(),
        has_overrides=False,
        entitlement=GuildEntitlementView(
            effective_plan='free',
            plan_source='default',
            entitlement_status='none',
            subscribed_plan=None,
            manual_plan_override=None,
            billing_provider=None,
            external_customer_id=None,
            external_subscription_id=None,
            current_period_end=None,
            cancel_at_period_end=False,
            trial_ends_at=None,
            trial_used_at=None,
            is_test=True,
        ),
        compliance=GuildComplianceView(
            is_non_compliant=False,
            reason_labels=(),
            session_count=0,
            source_count=0,
            rule_count=0,
            over_session_limit=False,
            over_source_limit=False,
            over_rule_limit=False,
            has_premium_rules=False,
            has_premium_presentation=False,
            has_premium_source_overrides=False,
        ),
        grandfathered_free_source_limit=None,
    )


class _DummyTask:
    def set_name(self, _name):
        return self


class _DummyLoop:
    def create_task(self, coro):
        coro.close()
        return _DummyTask()


class FakeChannel:
    def __init__(self, channel_id: int, *, error=None):
        self.id = channel_id
        self.guild = SimpleNamespace(id=999)
        self.error = error
        self.sent_messages = []
        self.history_messages = []

    async def send(self, **kwargs):
        if self.error:
            raise self.error
        self.sent_messages.append(kwargs)
        message = SimpleNamespace(
            nonce=kwargs.get('nonce'),
            author=SimpleNamespace(id=42),
        )
        self.history_messages.insert(0, message)
        return message

    def history(self, limit=25):
        async def _iterate():
            for message in self.history_messages[:limit]:
                yield message
        return _iterate()


class FakeBot:
    def __init__(self, channels):
        self.loop = _DummyLoop()
        self._channels = channels
        self.user = SimpleNamespace(id=42)

    def get_channel(self, channel_id: int):
        return self._channels.get(channel_id)

    async def fetch_channel(self, channel_id: int):
        channel = self._channels.get(channel_id)
        if channel is None:
            raise Exception('Unknown Channel')
        return channel


class FakeGuildSettingsService:
    async def get_presentation_view(self, _server_id: str):
        return _build_view()


async def _insert_outbox_row(channel_id: str, *, tweet_id: str = 'tweet-1'):
    async with aiosqlite.connect(get_db_path()) as db:
        async with db.cursor() as cursor:
            await enqueue_delivery(
                cursor,
                tweet_id=tweet_id,
                source_user_id='user-1',
                source_username='sourceuser',
                client_used='client-1',
                server_id='server-1',
                channel_id=channel_id,
                message_content='hello world',
                payload={
                    'tweet': {
                        'id': tweet_id,
                        'url': 'https://twitter.com/sourceuser/status/1',
                        'text': 'tweet body',
                        'created_on': '2026-07-16T00:00:00+00:00',
                        'is_retweet': False,
                        'is_quoted': False,
                        'author': {
                            'name': 'Source User',
                            'username': 'sourceuser',
                            'profile_image_url_https': 'https://example.com/avatar.jpg',
                        },
                        'media': [],
                    },
                    'support_prompt_text': None,
                    'support_prompt_url': None,
                },
                created_at='2026-07-16T00:00:00+00:00',
                matched_rule_name=None,
            )
            await db.commit()


async def _insert_notification_destination(
    channel_id: str,
    *,
    username: str = "sourceuser",
    client_used: str = "client-1",
) -> None:
    async with aiosqlite.connect(get_db_path()) as db:
        await db.execute(
            """
            INSERT OR IGNORE INTO user (
                id,
                username,
                enabled
            )
            VALUES (?, ?, 1)
            """,
            (
                f"user-{username}",
                username,
            ),
        )

        await db.execute(
            """
            INSERT OR REPLACE INTO notification (
                user_id,
                channel_id,
                client_used,
                enabled,
                delivery_paused,
                delivery_pause_reason,
                delivery_paused_at
            )
            VALUES (?, ?, ?, 1, 0, NULL, NULL)
            """,
            (
                f"user-{username}",
                str(channel_id),
                client_used,
            ),
        )

        await db.commit()


@pytest.mark.asyncio
async def test_delivery_outbox_deduplicates_same_tweet_channel(env):
    with fail_after(20):
        await ensure_outbox_test_schema()
        await _insert_outbox_row('100', tweet_id='tweet-dup')
        await _insert_outbox_row('100', tweet_id='tweet-dup')

        due = await list_due_deliveries(get_db_path(), '2030-01-01T00:00:00+00:00')
    assert len(due) == 1


@pytest.mark.asyncio
async def test_delivery_outbox_success_marks_delivered(env):
    await ensure_outbox_test_schema()
    await _insert_outbox_row('101')
    tracker = AccountTracker(FakeBot({101: FakeChannel(101)}))
    tracker.guild_settings_service = FakeGuildSettingsService()

    await tracker.process_delivery_outbox()

    due = await list_due_deliveries(get_db_path(), '2030-01-01T00:00:00+00:00')
    assert [row.status for row in due] == ['delivered']


@pytest.mark.asyncio
async def test_delivery_outbox_retries_then_succeeds(env):
    await ensure_outbox_test_schema()
    channel = FakeChannel(102, error=Exception('503 service unavailable (error code: 0)'))
    await _insert_outbox_row('102')
    tracker = AccountTracker(FakeBot({102: channel}))
    tracker.guild_settings_service = FakeGuildSettingsService()
    tracker._retry_delay_seconds = lambda attempt: 0

    await tracker.process_delivery_outbox()
    due = await list_due_deliveries(get_db_path(), '2030-01-01T00:00:00+00:00')
    assert len(due) == 1
    assert due[0].attempt_count == 1
    assert due[0].status == 'pending'

    channel.error = None
    await tracker.process_delivery_outbox()
    due = await list_due_deliveries(get_db_path(), '2030-01-01T00:00:00+00:00')
    assert [row.status for row in due] == ['delivered']
    assert len(channel.sent_messages) == 1


@pytest.mark.asyncio
async def test_delivery_outbox_handles_one_failed_channel_and_one_success(env):
    await ensure_outbox_test_schema()
    await _insert_notification_destination("202")
    await _insert_outbox_row('201', tweet_id='tweet-a')
    await _insert_outbox_row('202', tweet_id='tweet-b')
    tracker = AccountTracker(
        FakeBot(
            {
                201: FakeChannel(201),
            }
        )
    )
    tracker.guild_settings_service = FakeGuildSettingsService()

    await tracker.process_delivery_outbox()

    due = await list_due_deliveries(get_db_path(), '2030-01-01T00:00:00+00:00')
    assert len(due) == 2

    async with aiosqlite.connect(get_db_path()) as db:
        async with db.execute("SELECT status, channel_id FROM delivery_outbox ORDER BY channel_id ASC") as cursor:
            rows = await cursor.fetchall()
    assert rows == [('delivered', '201'), ('failed', '202')]


@pytest.mark.asyncio
async def test_delivery_outbox_survives_restart(env):
    await ensure_outbox_test_schema()
    await _insert_outbox_row('301')

    first_tracker = AccountTracker(FakeBot({}))
    first_tracker.guild_settings_service = FakeGuildSettingsService()
    AccountTracker._instance = None

    second_tracker = AccountTracker(FakeBot({301: FakeChannel(301)}))
    second_tracker.guild_settings_service = FakeGuildSettingsService()
    await second_tracker.process_delivery_outbox()

    due = await list_due_deliveries(get_db_path(), '2030-01-01T00:00:00+00:00')
    assert [row.status for row in due] == ['delivered']


@pytest.mark.asyncio
async def test_delivery_outbox_claims_rows_atomically_with_leases(env):
    await ensure_outbox_test_schema()
    await _insert_outbox_row('401', tweet_id='tweet-401')

    first_claim = await claim_due_deliveries(
        get_db_path(),
        '2030-01-01T00:00:00+00:00',
        lease_expires_at='2030-01-01T00:02:00+00:00',
    )
    second_claim = await claim_due_deliveries(
        get_db_path(),
        '2030-01-01T00:00:00+00:00',
        lease_expires_at='2030-01-01T00:02:00+00:00',
    )

    assert len(first_claim) == 1
    assert second_claim == []


@pytest.mark.asyncio
async def test_delivery_outbox_reuses_existing_nonce_after_crash(env):
    await ensure_outbox_test_schema()
    channel = FakeChannel(402)
    await _insert_outbox_row('402', tweet_id='tweet-402')
    tracker = AccountTracker(FakeBot({402: channel}))
    tracker.guild_settings_service = FakeGuildSettingsService()

    claimed = await claim_due_deliveries(
        get_db_path(),
        '2030-01-01T00:00:00+00:00',
        lease_expires_at='2030-01-01T00:02:00+00:00',
    )
    assert len(claimed) == 1
    delivery = claimed[0]
    channel.history_messages.append(
        SimpleNamespace(
            nonce=tracker._delivery_nonce(delivery),
            author=SimpleNamespace(id=42),
        )
    )
    await tracker._deliver_outbox_record(delivery)

    due = await list_due_deliveries(get_db_path(), '2030-01-01T00:00:00+00:00')
    assert [row.status for row in due] == ['delivered']
    assert channel.sent_messages == []

@pytest.mark.asyncio
async def test_enqueue_retries_transient_database_lock(
    env,
    monkeypatch,
):
    tracker = AccountTracker(FakeBot({}))
    tracker.db_lock_retry_attempts = 3
    tracker.db_lock_retry_base_seconds = 0.01

    calls = 0

    async def fake_enqueue_once(*_args, **_kwargs):
        nonlocal calls
        calls += 1

        if calls < 3:
            raise sqlite3.OperationalError(
                'database is locked'
            )

    sleep_mock = AsyncMock()

    monkeypatch.setattr(
        tracker,
        '_enqueue_new_tweet_deliveries_once',
        fake_enqueue_once,
    )
    monkeypatch.setattr(
        asyncio,
        'sleep',
        sleep_mock,
    )

    await tracker._enqueue_new_tweet_deliveries(
        'CeladonCA',
        'client-1',
        [],
        '2026-07-17 16:00:00+00:00',
    )

    assert calls == 3
    assert sleep_mock.await_count == 2

@pytest.mark.asyncio
async def test_enqueue_lock_exhaustion_preserves_failure(
    env,
    monkeypatch,
):
    tracker = AccountTracker(FakeBot({}))
    tracker.db_lock_retry_attempts = 2
    tracker.db_lock_retry_base_seconds = 0.01

    async def always_locked(*_args, **_kwargs):
        raise sqlite3.OperationalError(
            'database is locked'
        )

    monkeypatch.setattr(
        tracker,
        '_enqueue_new_tweet_deliveries_once',
        always_locked,
    )
    monkeypatch.setattr(
        asyncio,
        'sleep',
        AsyncMock(),
    )

    with pytest.raises(
        sqlite3.OperationalError,
        match='database is locked',
    ):
        await tracker._enqueue_new_tweet_deliveries(
            'CeladonCA',
            'client-1',
            [],
            '2026-07-17 16:00:00+00:00',
        )
