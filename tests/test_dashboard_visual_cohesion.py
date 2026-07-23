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
    assert 'Signed in as <strong>' not in html
    assert '>Choose a Server<' not in html
    assert 'This feature is available with Premium. Customize how Tweeticcini alerts appear in your Discord server' in html
    assert 'This feature is available with Premium. Use Rules to route matching posts to different channels' in html
    assert 'Explore Premium' in html
    assert 'Subscriptions and one-time support are separate.' in html
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
