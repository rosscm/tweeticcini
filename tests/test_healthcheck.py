import importlib
import signal
from contextlib import contextmanager

import pytest


@pytest.fixture
def base_env(monkeypatch, tmp_path):
    monkeypatch.setenv('DATA_PATH', str(tmp_path))
    monkeypatch.setenv('DASHBOARD_SESSION_SECRET', 'test-session-secret')
    monkeypatch.setenv('DISCORD_CLIENT_ID', '123')
    monkeypatch.setenv('DISCORD_CLIENT_SECRET', 'secret')
    monkeypatch.setenv('DISCORD_REDIRECT_URI', 'https://example.com/dashboard/callback')
    monkeypatch.setenv('APP_ENV', 'production')


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


def _load_dashboard_app():
    module = importlib.import_module('src.dashboard_api.app')
    return importlib.reload(module)


def _healthy_log_state() -> dict[str, object]:
    return {
        'bot_online_recently': True,
        'updater_error_count': 0,
        'delivery_error_count': 0,
        'dead_task_warning_count': 0,
        'updater_error_count_since_last_online': 0,
        'delivery_error_count_since_last_online': 0,
        'dead_task_warning_count_since_last_online': 0,
        'last_online_at': '2026-07-16 12:00',
    }


@pytest.mark.asyncio
async def test_healthcheck_excludes_inactive_historical_runtime_records(base_env, monkeypatch):
    module = _load_dashboard_app()
    monkeypatch.setattr(module, '_read_recent_log_health', _healthy_log_state)
    async def fake_list_runtime_client_statuses(_db_path):
        return [
            {
                'client_used': 'active-client',
                'last_poll_success_at': '2026-07-16T12:00:00+00:00',
                'last_notification_count': 2,
                'last_poll_error_at': None,
                'last_error_message': None,
            },
            {
                'client_used': 'removed-client',
                'last_poll_success_at': '2026-07-16T11:00:00+00:00',
                'last_notification_count': 9,
                'last_poll_error_at': None,
                'last_error_message': None,
            },
        ]

    monkeypatch.setattr(module, 'list_runtime_client_statuses', fake_list_runtime_client_statuses)

    async def fake_active_client_keys():
        return {'active-client'}

    monkeypatch.setattr(module.twitter_session_service, 'list_all_active_client_keys', fake_active_client_keys)

    with fail_after(5):
        response = await module.healthcheck()

    assert response['status'] == 'ok'
    assert response['twitter_session_count'] == 1
    assert response['healthy_twitter_session_count'] == 1
    assert 'runtime_client_statuses' not in response


@pytest.mark.asyncio
async def test_healthcheck_counts_recent_successful_active_session_as_healthy(base_env, monkeypatch):
    module = _load_dashboard_app()
    monkeypatch.setattr(module, '_read_recent_log_health', _healthy_log_state)
    async def fake_list_runtime_client_statuses(_db_path):
        return [
            {
                'client_used': 'active-client',
                'last_poll_success_at': '2026-07-16T12:30:00+00:00',
                'last_notification_count': 4,
                'last_poll_error_at': None,
                'last_error_message': None,
            }
        ]

    monkeypatch.setattr(module, 'list_runtime_client_statuses', fake_list_runtime_client_statuses)

    async def fake_active_client_keys():
        return {'active-client'}

    monkeypatch.setattr(module.twitter_session_service, 'list_all_active_client_keys', fake_active_client_keys)

    with fail_after(5):
        response = await module.healthcheck()

    assert response['twitter_session_count'] == 1
    assert response['healthy_twitter_session_count'] == 1


@pytest.mark.asyncio
async def test_healthcheck_marks_active_session_unhealthy_when_later_auth_error_exists(base_env, monkeypatch):
    module = _load_dashboard_app()
    monkeypatch.setattr(module, '_read_recent_log_health', _healthy_log_state)
    async def fake_list_runtime_client_statuses(_db_path):
        return [
            {
                'client_used': 'active-client',
                'last_poll_success_at': '2026-07-16T12:00:00+00:00',
                'last_notification_count': 1,
                'last_poll_error_at': '2026-07-16T12:05:00+00:00',
                'last_error_message': 'Twitter authentication failed',
            }
        ]

    monkeypatch.setattr(module, 'list_runtime_client_statuses', fake_list_runtime_client_statuses)

    async def fake_active_client_keys():
        return {'active-client'}

    monkeypatch.setattr(module.twitter_session_service, 'list_all_active_client_keys', fake_active_client_keys)

    with fail_after(5):
        response = await module.healthcheck()

    assert response['twitter_session_count'] == 1
    assert response['healthy_twitter_session_count'] == 0


@pytest.mark.asyncio
async def test_healthcheck_never_reports_more_healthy_sessions_than_total(base_env, monkeypatch):
    module = _load_dashboard_app()
    monkeypatch.setattr(module, '_read_recent_log_health', _healthy_log_state)
    async def fake_list_runtime_client_statuses(_db_path):
        return [
            {
                'client_used': 'active-client',
                'last_poll_success_at': '2026-07-16T12:00:00+00:00',
                'last_notification_count': 1,
                'last_poll_error_at': None,
                'last_error_message': None,
            },
            {
                'client_used': 'inactive-client',
                'last_poll_success_at': '2026-07-16T12:01:00+00:00',
                'last_notification_count': 1,
                'last_poll_error_at': None,
                'last_error_message': None,
            },
        ]

    monkeypatch.setattr(module, 'list_runtime_client_statuses', fake_list_runtime_client_statuses)

    async def fake_active_client_keys():
        return {'active-client'}

    monkeypatch.setattr(module.twitter_session_service, 'list_all_active_client_keys', fake_active_client_keys)

    with fail_after(5):
        response = await module.healthcheck()

    assert 0 <= response['healthy_twitter_session_count'] <= response['twitter_session_count']


@pytest.mark.asyncio
async def test_healthcheck_returns_ok_when_application_is_otherwise_healthy(base_env, monkeypatch):
    module = _load_dashboard_app()
    monkeypatch.setattr(module, '_read_recent_log_health', _healthy_log_state)
    async def fake_list_runtime_client_statuses(_db_path):
        return []

    monkeypatch.setattr(module, 'list_runtime_client_statuses', fake_list_runtime_client_statuses)

    async def fake_active_client_keys():
        return set()

    monkeypatch.setattr(module.twitter_session_service, 'list_all_active_client_keys', fake_active_client_keys)

    with fail_after(5):
        response = await module.healthcheck()

    assert response['status'] == 'ok'
    assert response['issues'] == []
    assert response['twitter_session_count'] == 0
    assert response['healthy_twitter_session_count'] == 0
    assert 'runtime_client_statuses' not in response
