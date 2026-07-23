from src.notification.account_tracker import AccountTracker


def test_support_prompt_copy_and_url_stay_support_only(monkeypatch):
    monkeypatch.setenv('BUY_ME_A_COFFEE_URL', 'https://buymeacoffee.com/pokaccini')
    notifier = object.__new__(AccountTracker)
    notifier.support_prompt_server_ids = set()
    notifier.managed_support_prompt_text = None

    assert notifier._get_support_prompt_text('guild-1') == (
        '☕ Enjoying Tweeticcini? A small one-time contribution helps cover hosting and continued development.'
    )
