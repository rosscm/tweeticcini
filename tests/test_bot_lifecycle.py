import importlib

import pytest
from cogs.about import About


@pytest.mark.asyncio
async def test_setup_hook_only_initializes_once(monkeypatch):
    module = importlib.import_module('bot')
    module = importlib.reload(module)

    load_calls = []
    sync_calls = []
    tracker_calls = []

    async def fake_ensure_db_schema():
        return None

    async def fake_check_db():
        return set()

    async def fake_load_extension(name: str):
        load_calls.append(name)

    async def fake_sync():
        sync_calls.append(True)
        return ['cmd']

    class FakeTracker:
        def __init__(self, bot):
            tracker_calls.append(bot)

    monkeypatch.setattr(module, 'ensure_db_schema', fake_ensure_db_schema)
    monkeypatch.setattr(module, 'check_upgrade', lambda: None)
    monkeypatch.setattr(module, 'check_env', lambda: True)
    monkeypatch.setattr(module, 'check_configs', lambda configs: True)
    monkeypatch.setattr(module, 'check_db', fake_check_db)
    monkeypatch.setattr(module, 'AccountTracker', FakeTracker)
    monkeypatch.setattr(module.bot, 'load_extension', fake_load_extension)
    monkeypatch.setattr(module.bot.tree, 'sync', fake_sync)

    await module.bot.setup_hook()
    await module.bot.setup_hook()

    assert load_calls == ['cogs.about']
    assert len(sync_calls) == 1
    assert len(tracker_calls) == 1


@pytest.mark.asyncio
async def test_on_ready_is_reconnect_safe(monkeypatch):
    module = importlib.import_module('bot')
    module = importlib.reload(module)

    presence_calls = []
    persist_calls = []
    recovered_calls = []
    load_calls = []

    async def fake_mark_bot_runtime_recovered(*args, **kwargs):
        recovered_calls.append((args, kwargs))

    async def fake_persist():
        persist_calls.append(True)

    async def fake_update_presence(_bot):
        presence_calls.append(True)

    async def fake_load_extension(name: str):
        load_calls.append(name)

    monkeypatch.setattr(module, 'mark_bot_runtime_recovered', fake_mark_bot_runtime_recovered)
    monkeypatch.setattr(module, '_persist_connected_server_count', fake_persist)
    monkeypatch.setattr(module, 'update_presence', fake_update_presence)
    monkeypatch.setattr(module.bot, 'load_extension', fake_load_extension)

    await module.on_ready()
    await module.on_ready()

    assert len(recovered_calls) == 2
    assert len(persist_calls) == 2
    assert len(presence_calls) == 2
    assert load_calls == []


def test_registered_slash_command_set_is_exact():
    command_names = {command.name for command in About.__cog_app_commands__}

    assert command_names == {'about', 'support'}
    assert 'dashboard' not in command_names
    assert 'vote' not in command_names
    assert 'add' not in command_names
    assert 'remove' not in command_names
    assert 'customize' not in command_names
    assert 'rule' not in command_names
    assert 'list' not in command_names
    assert 'sync' not in command_names
