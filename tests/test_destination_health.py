import logging
import sqlite3

import pytest

from src.notification.account_tracker import AccountTracker
from src.repositories.delivery_outbox_repository import (
    fail_open_deliveries_for_destination,
)
from src.repositories.notifier_repository import (
    pause_notification_delivery,
    resume_channel_deliveries,
)


def _tracker():
    tracker = object.__new__(AccountTracker)
    tracker.accounts_data = {}
    tracker.missing_session_tasks = set()
    return tracker


def test_missing_session_is_excluded_and_logged_once(caplog):
    tracker = _tracker()
    tracker.accounts_data = {
        'available-session': {},
    }

    configured, available, missing = (
        tracker._partition_configured_tasks(
            [
                ('Available', 'available-session'),
                ('PokemonRestocks', 'missing-session'),
            ]
        )
    )

    available_name = tracker._task_name(
        'Available',
        'available-session',
    )
    missing_name = tracker._task_name(
        'PokemonRestocks',
        'missing-session',
    )

    assert set(configured) == {
        available_name,
        missing_name,
    }
    assert set(available) == {
        available_name,
    }
    assert missing == {
        missing_name,
    }

    caplog.set_level(
        logging.WARNING,
        logger='src.notification.account_tracker',
    )

    tracker._update_missing_session_state(
        configured,
        missing,
    )
    tracker._update_missing_session_state(
        configured,
        missing,
    )

    messages = [
        record.getMessage()
        for record in caplog.records
        if 'suspended PokemonRestocks' in record.getMessage()
    ]
    assert len(messages) == 1


def test_missing_session_logs_recovery(caplog):
    tracker = _tracker()
    task_name = tracker._task_name(
        'PokemonRestocks',
        'restored-session',
    )
    tracker.missing_session_tasks = {
        task_name,
    }

    caplog.set_level(
        logging.INFO,
        logger='src.notification.account_tracker',
    )

    tracker._update_missing_session_state(
        {
            task_name: (
                'PokemonRestocks',
                'restored-session',
            ),
        },
        set(),
    )

    assert any(
        'resuming PokemonRestocks' in record.getMessage()
        for record in caplog.records
    )


@pytest.mark.parametrize(
    'message',
    [
        '403 Forbidden (error code: 50001): Missing Access',
        '403 Forbidden (error code: 50013): Missing Permissions',
        '404 Not Found (error code: 10003): Unknown Channel',
    ],
)
def test_channel_specific_errors_have_pause_reason(message):
    tracker = _tracker()
    assert tracker._delivery_pause_reason(
        Exception(message)
    ) is not None


@pytest.mark.parametrize(
    'message',
    [
        '429 Too Many Requests',
        '503 Service Unavailable',
        'connection timed out',
        'invalid form body',
    ],
)
def test_other_errors_do_not_pause_destination(message):
    tracker = _tracker()
    assert tracker._delivery_pause_reason(
        Exception(message)
    ) is None


@pytest.mark.asyncio
async def test_pause_resume_and_close_open_rows(tmp_path):
    db_path = tmp_path / 'test.db'

    with sqlite3.connect(db_path) as db:
        db.executescript(
            '''
            CREATE TABLE user (
                id TEXT PRIMARY KEY,
                username TEXT
            );

            CREATE TABLE notification (
                user_id TEXT,
                channel_id TEXT,
                enabled INTEGER DEFAULT 1,
                delivery_paused INTEGER DEFAULT 0,
                delivery_pause_reason TEXT,
                delivery_paused_at TEXT,
                PRIMARY KEY(user_id, channel_id)
            );

            CREATE TABLE delivery_outbox (
                id INTEGER PRIMARY KEY,
                source_username TEXT,
                channel_id TEXT,
                status TEXT,
                next_attempt_at TEXT,
                last_error TEXT,
                lease_token TEXT,
                lease_expires_at TEXT
            );

            INSERT INTO user VALUES (
                'u1',
                'sourceuser'
            );

            INSERT INTO notification (
                user_id,
                channel_id
            ) VALUES (
                'u1',
                'c1'
            );

            INSERT INTO delivery_outbox VALUES
                (
                    1,
                    'sourceuser',
                    'c1',
                    'pending',
                    NULL,
                    NULL,
                    NULL,
                    NULL
                ),
                (
                    2,
                    'sourceuser',
                    'c1',
                    'processing',
                    NULL,
                    NULL,
                    NULL,
                    NULL
                ),
                (
                    3,
                    'sourceuser',
                    'c2',
                    'pending',
                    NULL,
                    NULL,
                    NULL,
                    NULL
                );
            '''
        )

    assert await pause_notification_delivery(
        db_path,
        'sourceuser',
        'c1',
        'Missing access',
        '2026-07-17T20:00:00+00:00',
    )
    assert not await pause_notification_delivery(
        db_path,
        'sourceuser',
        'c1',
        'Missing access',
        '2026-07-17T20:01:00+00:00',
    )

    assert await fail_open_deliveries_for_destination(
        db_path,
        'sourceuser',
        'c1',
        'Missing access',
    ) == 2

    assert await resume_channel_deliveries(
        db_path,
        'c1',
    ) == 1

    with sqlite3.connect(db_path) as db:
        state = db.execute(
            '''
            SELECT
                delivery_paused,
                delivery_pause_reason,
                delivery_paused_at
            FROM notification
            WHERE channel_id = 'c1'
            '''
        ).fetchone()
        rows = db.execute(
            '''
            SELECT channel_id, status
            FROM delivery_outbox
            ORDER BY id
            '''
        ).fetchall()

    assert state == (
        0,
        None,
        None,
    )
    assert rows == [
        ('c1', 'failed'),
        ('c1', 'failed'),
        ('c2', 'pending'),
    ]
