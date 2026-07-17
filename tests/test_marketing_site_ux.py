from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


def test_server_count_fallback_copy_replaces_broken_dash():
    html = (REPO_ROOT / 'docs' / 'index.html').read_text(encoding='utf8')

    assert 'Trusted by Discord communities for round-the-clock alert monitoring.' in html
    assert 'proof-primary--count" hidden' in html
    assert '—</span> active servers' not in html
    assert html.count('class="proof-line"') == 1


def test_pricing_cta_links_include_plan_preselection():
    html = (REPO_ROOT / 'docs' / 'index.html').read_text(encoding='utf8')

    assert 'Add to Discord' in html
    assert 'href="https://discord.com/oauth2/authorize?client_id=1385046979662581780&amp;scope=bot%20applications.commands&amp;permissions=0"' not in html
    assert 'href="https://discord.com/oauth2/authorize?client_id=1385046979662581780&scope=bot%20applications.commands&permissions=0"' in html
    assert 'href="https://app.tweeticcini.com/dashboard?plan=plus"' in html
    assert 'href="https://app.tweeticcini.com/dashboard?plan=pro"' in html
    assert html.count('>Start Trial<') == 2
    assert 'aria-label="Start Plus trial"' in html
    assert 'aria-label="Start Premium trial"' in html
    assert 'Get started' in html


def test_marketing_seo_pages_use_shortened_add_to_discord_label():
    setup_html = (REPO_ROOT / 'docs' / 'how-to-send-twitter-alerts-to-discord.html').read_text(encoding='utf8')
    overview_html = (REPO_ROOT / 'docs' / 'twitter-alerts-for-discord.html').read_text(encoding='utf8')

    assert 'Add Tweeticcini to Discord' not in setup_html
    assert 'Add Tweeticcini to Discord' not in overview_html
    assert '>Add to Discord<' in setup_html
    assert '>Add to Discord<' in overview_html


def test_marketing_site_includes_nav_and_faq_trust_sections():
    html = (REPO_ROOT / 'docs' / 'index.html').read_text(encoding='utf8')

    for label in ['Features', 'Pricing', 'Setup', 'FAQ', 'Support']:
        assert f'>{label}<' in html

    assert 'Why Tweeticcini asks for a Twitter/X session' in html
    assert 'What Discord permissions do I need?' in html
    assert 'How do trials, cancellation, and billing work?' in html
    assert 'Tweeticcini is built and maintained by one developer.' in html


def test_reduced_motion_rules_exist_for_public_and_dashboard_css():
    public_css = (REPO_ROOT / 'docs' / 'styles.css').read_text(encoding='utf8')
    dashboard_css = (REPO_ROOT / 'src' / 'dashboard_api' / 'static' / 'dashboard.css').read_text(encoding='utf8')

    assert '@media (prefers-reduced-motion: reduce)' in public_css
    assert '@media (prefers-reduced-motion: reduce)' in dashboard_css


def test_hero_content_appears_in_requested_order_and_social_proof_heading():
    html = (REPO_ROOT / 'docs' / 'index.html').read_text(encoding='utf8')

    title_index = html.index('<div class="site-brand-name">Twitter alert routing for Discord</div>')
    headline_index = html.index('Never miss high-value drops, updates, and announcements in Discord.')
    proof_index = html.index('Trusted by Discord communities')
    lede_index = html.index('Tweeticcini turns noisy Twitter/X feeds into actionable Discord alerts')

    assert title_index < headline_index < proof_index < lede_index


def test_support_labels_are_destination_specific_on_marketing_site():
    html = (REPO_ROOT / 'docs' / 'index.html').read_text(encoding='utf8')

    assert 'Join Support Server' in html
    assert 'Vote on Top.gg' in html
    assert 'Buy Me a Coffee' in html
    assert '>Support Server<' not in html


def test_support_labels_are_destination_specific_in_dashboard_templates():
    guild_html = (REPO_ROOT / 'src' / 'dashboard_api' / 'templates' / 'guild.html').read_text(encoding='utf8')
    index_html = (REPO_ROOT / 'src' / 'dashboard_api' / 'templates' / 'index.html').read_text(encoding='utf8')
    access_denied_html = (REPO_ROOT / 'src' / 'dashboard_api' / 'templates' / 'access_denied.html').read_text(encoding='utf8')

    for html in [guild_html, index_html, access_denied_html]:
        assert 'Join Support Server' in html
        assert 'Vote on Top.gg' in html
        assert 'Buy Me a Coffee' in html
        assert 'Vote on top.gg' not in html


def test_no_generic_support_button_label_remains_in_discord_views():
    about_py = (REPO_ROOT / 'cogs' / 'about.py').read_text(encoding='utf8')
    dashboard_py = (REPO_ROOT / 'cogs' / 'dashboard.py').read_text(encoding='utf8')

    assert "label='Support'" not in about_py
    assert 'Vote on Top.gg' in about_py
    assert 'Join Support Server' in about_py
    assert 'Open Dashboard' in about_py
    assert "@app_commands.command(name='vote'" not in dashboard_py
