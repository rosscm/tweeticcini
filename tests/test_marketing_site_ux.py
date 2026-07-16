from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


def test_server_count_fallback_copy_replaces_broken_dash():
    html = (REPO_ROOT / 'docs' / 'index.html').read_text(encoding='utf8')

    assert 'Trusted by Discord communities for round-the-clock alert monitoring.' in html
    assert 'proof-primary--count" hidden' in html
    assert '—</span> active servers' not in html


def test_pricing_cta_links_include_plan_preselection():
    html = (REPO_ROOT / 'docs' / 'index.html').read_text(encoding='utf8')

    assert 'href="https://discord.com/oauth2/authorize?client_id=1385046979662581780&amp;scope=bot%20applications.commands&amp;permissions=0"' not in html
    assert 'href="https://discord.com/oauth2/authorize?client_id=1385046979662581780&scope=bot%20applications.commands&permissions=0"' in html
    assert 'href="https://app.tweeticcini.com/dashboard?plan=plus"' in html
    assert 'href="https://app.tweeticcini.com/dashboard?plan=pro"' in html


def test_marketing_site_includes_nav_and_faq_trust_sections():
    html = (REPO_ROOT / 'docs' / 'index.html').read_text(encoding='utf8')

    for label in ['Features', 'Pricing', 'Setup', 'FAQ', 'Support']:
        assert f'>{label}<' in html

    assert 'Why Tweeticcini asks for a Twitter/X session' in html
    assert 'What Discord permissions do I need?' in html
    assert 'How do trials, cancellation, and billing work?' in html


def test_reduced_motion_rules_exist_for_public_and_dashboard_css():
    public_css = (REPO_ROOT / 'docs' / 'styles.css').read_text(encoding='utf8')
    dashboard_css = (REPO_ROOT / 'src' / 'dashboard_api' / 'static' / 'dashboard.css').read_text(encoding='utf8')

    assert '@media (prefers-reduced-motion: reduce)' in public_css
    assert '@media (prefers-reduced-motion: reduce)' in dashboard_css
