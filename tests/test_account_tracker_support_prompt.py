from src.notification.account_tracker import (
    AccountTracker,
    _get_donation_url,
    _get_managed_support_prompt_default_text,
    _get_force_everyone_support_prompt_url,
)


def test_support_prompt_copy_and_url_stay_support_only(monkeypatch):
    monkeypatch.setenv('BUY_ME_A_COFFEE_URL', 'https://buymeacoffee.com/pokaccini')
    notifier = object.__new__(AccountTracker)
    notifier.support_prompt_server_ids = set()
    notifier.managed_support_prompt_text = None

    assert notifier._get_support_prompt_text('guild-1') == (
        '☕ Enjoying Tweeticcini? A small one-time contribution helps me cover hosting and keep the bot running. 🩷'
    )
    assert notifier._get_support_prompt_url('guild-1') == 'https://buymeacoffee.com/pokaccini'


def test_force_everyone_support_prompt_uses_vote_url_not_donation(monkeypatch):
    monkeypatch.setenv('DISCORD_CLIENT_ID', '1385046979662581780')
    monkeypatch.setenv('BUY_ME_A_COFFEE_URL', 'https://buymeacoffee.com/pokaccini')
    notifier = object.__new__(AccountTracker)
    notifier.support_prompt_server_ids = {'guild-1'}
    notifier.managed_support_prompt_text = 'managed vote copy'

    assert _get_force_everyone_support_prompt_url() == 'https://top.gg/bot/1385046979662581780/vote'
    assert _get_force_everyone_support_prompt_url() != _get_donation_url()
    assert notifier._get_support_prompt_text('guild-1') == 'managed vote copy'
    assert notifier._get_support_prompt_url('guild-1') == 'https://top.gg/bot/1385046979662581780/vote'


def test_managed_support_prompt_defaults_to_existing_vote_copy(monkeypatch):
    monkeypatch.setenv('DISCORD_CLIENT_ID', '1385046979662581780')
    notifier = object.__new__(AccountTracker)
    notifier.support_prompt_server_ids = {'guild-1'}
    notifier.managed_support_prompt_text = None

    assert notifier._get_support_prompt_text('guild-1') == _get_managed_support_prompt_default_text()
    assert notifier._get_support_prompt_url('guild-1') == 'https://top.gg/bot/1385046979662581780/vote'
