from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


def _read(relative_path: str) -> str:
    return (REPO_ROOT / relative_path).read_text(encoding="utf8")


def test_dashboard_entry_page_uses_dashboard_resource_topbar_and_server_state_copy():
    html = _read("src/dashboard_api/templates/index.html")

    assert 'dashboard-topbar' in html
    assert 'Bot Overview' in html
    assert 'Add to Discord' in html
    assert 'Signed in with Discord' in html
    assert 'No manageable servers found yet.' in html
    assert 'Open dashboard and manage alerts' in html


def test_access_denied_page_explains_next_steps():
    html = _read("src/dashboard_api/templates/access_denied.html")

    assert 'What you can do next' in html
    assert 'Return to Server Selection' in html
    assert 'Make sure Tweeticcini is installed in the server' in html


def test_guild_dashboard_uses_updated_locked_feature_and_support_copy():
    html = _read("src/dashboard_api/templates/guild.html")

    assert 'app-header' in html
    assert 'Change server' in html
    assert 'Setup Progress' in html
    assert 'Manage monitors' in html
    assert 'What needs attention' not in html
    assert 'Start here:' not in html
    assert '>Plan Usage<' not in html
    assert 'Next Step' in html
    assert 'data-announcement-id="plans-2026"' in html
    assert 'data-announcement-banner' in html
    assert 'data-announcement-dismiss' in html
    assert 'Signed in as <strong>' not in html
    assert '>Choose a Server<' not in html
    assert 'plan-badge--{{ plan_badge_tone }}' in html
    assert 'data-announcement-storage-key="tweeticcini_announcement_plans_2026_dismissed"' in html
    assert 'type="button" class="button-secondary notice-dismiss"' in html
    assert 'href="/dashboard/guilds/{{ guild_id }}/twitter-sessions"' in html
    assert 'href="/dashboard/guilds/{{ guild_id }}/sources"' in html
    assert 'id="next-step-send-test-alert"' in html
    assert 'This feature is available with Premium. Customize how Tweeticcini alerts appear in your Discord server' in html
    assert 'embed behaviour' in html
    assert 'This feature is available with Premium. Use Rules to route matching posts to different channels, suppress unwanted content, and control which roles are mentioned.' in html
    assert 'Explore Premium' in html
    assert 'Need more from Tweeticcini?' in html
    assert '{{ free_support_card.title }}' in html
    assert '{{ free_support_card.body }}' in html
    assert 'data-name="bmc-button"' in html
    assert 'data-text="Buy me a booster pack"' in html
    assert html.count('data-name="bmc-button"') == 1
    assert '<noscript>' in html
    assert '{{ free_support_card.action_label }}' not in html
    assert '{{ free_support_card.footer_note }}' in html
    assert '“Love what you built! Keep it going!”' not in html
    assert 'Tweeticcini supporter' not in html
    assert 'Your Free monitor is already in use' in html
    assert 'Compare plans, check trial status, and manage billing details.' in html
    assert 'sidebar-summary-list' not in html
    assert 'Configure sessions, monitors, and delivery behavior for this server without leaving the dashboard.' not in html


def test_dashboard_css_adds_topbar_summary_and_focus_tokens():
    css = _read("src/dashboard_api/static/dashboard.css")

    assert '--focus-ring:' in css
    assert '.dashboard-topbar' in css
    assert '.app-header' in css
    assert '.sidebar-server-row' in css
    assert '.notice--announcement-compact' in css
    assert '.site-footer-inner' in css
    assert '.footer-links-grid' in css
    assert '.plan-badge--premium' in css
    assert '.plan-badge--plus' in css
    assert '.plan-badge--free' in css
    assert '@media (prefers-reduced-motion: reduce)' in css


def test_dashboard_footer_uses_grouped_site_style_links():
    html = _read("src/dashboard_api/templates/guild.html")

    assert 'site-footer' in html
    assert 'site-footer-inner' in html
    assert 'footer-links-grid' in html
    assert '>Product<' in html
    assert '>Trust and Support<' in html
    assert '>Community<' in html
    assert 'Twitter alert routing for Discord' in html
