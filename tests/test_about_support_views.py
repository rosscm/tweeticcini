from cogs.about import SUPPORT_RESPONSE_TEXT, _build_about_view, _build_support_view


def test_about_view_focuses_on_management_actions():
    view = _build_about_view(
        dashboard_url='https://app.tweeticcini.com/dashboard?guild_id=1',
        support_server_url='https://discord.gg/example',
    )

    assert view is not None
    assert [item.label for item in view.children] == [
        'Open Dashboard',
        'Join Support Server',
    ]
    assert all(item.label not in {'Manage Plan', 'Upgrade'} for item in view.children)


def test_support_view_contains_vote_and_donation_links():
    view = _build_support_view(
        support_server_url='https://discord.gg/example',
        vote_url='https://top.gg/bot/123/vote',
        support_url='https://buymeacoffee.com/pokaccini',
    )

    assert view is not None
    assert [item.label for item in view.children] == [
        'Join Support Server',
        'Vote on Top.gg',
        'Buy Me a Coffee',
    ]


def test_support_copy_is_warm_and_includes_heart():
    assert 'Join Support Server' not in SUPPORT_RESPONSE_TEXT
    assert 'voting' in SUPPORT_RESPONSE_TEXT
    assert 'buying me a coffee' in SUPPORT_RESPONSE_TEXT
    assert '❤️' in SUPPORT_RESPONSE_TEXT
