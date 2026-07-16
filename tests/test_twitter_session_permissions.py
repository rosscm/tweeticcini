import os
import stat

import pytest

import src.services.twitter_session_service as twitter_session_service_module
from src.services.twitter_session_service import TwitterSessionService
from src.settings import get_twitter_session_dir, get_twitter_session_path


def test_session_files_are_written_atomically_with_restricted_permissions(monkeypatch, tmp_path):
    monkeypatch.setenv('DATA_PATH', str(tmp_path))
    service = TwitterSessionService()

    session_dir = get_twitter_session_dir()
    stale_tmp = session_dir / 'client-1.tw_session.stale.tmp'
    stale_tmp.write_text('stale')

    service._write_session_file('client-1', '{"cookies": []}')

    session_path = get_twitter_session_path('client-1')
    assert session_path.exists()
    assert session_path.read_text() == '{"cookies": []}'
    assert not stale_tmp.exists()

    if os.name == 'posix':
        dir_mode = stat.S_IMODE(session_dir.stat().st_mode)
        file_mode = stat.S_IMODE(session_path.stat().st_mode)
        assert dir_mode == 0o700
        assert file_mode == 0o600
    else:
        pytest.skip('POSIX permission bits are not supported on this platform')


@pytest.mark.asyncio
async def test_list_all_active_client_keys_accepts_repository_rows_without_is_active(monkeypatch):
    async def fake_list_active_server_twitter_sessions(_db_path):
        return [
            {'client_key': 'client-a'},
            {'client_key': 'client-b'},
        ]

    monkeypatch.setattr(
        twitter_session_service_module,
        'list_active_server_twitter_sessions',
        fake_list_active_server_twitter_sessions,
    )

    keys = await TwitterSessionService().list_all_active_client_keys()

    assert keys == {'client-a', 'client-b'}
