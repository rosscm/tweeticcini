from pathlib import Path
import re


REPO_ROOT = Path(__file__).resolve().parents[1]


def test_homepage_uses_requested_section_order():
    html = (REPO_ROOT / 'docs' / 'index.html').read_text(encoding='utf8')

    hero_index = html.index('class="hero-section"')
    workflow_index = html.index('id="workflow"')
    proof_index = html.index('Real Discord Delivery')
    spotlight_index = html.index('Dashboard Spotlight')
    how_index = html.index('id="how-it-works"')
    pricing_index = html.index('id="pricing"')
    faq_index = html.index('id="faq"')
    final_cta_index = html.index('id="get-started"')
    support_index = html.index('class="section-band support-section"')
    footer_index = html.index('<footer class="site-footer">')

    assert hero_index < workflow_index < proof_index < spotlight_index < how_index < pricing_index < support_index < faq_index < final_cta_index < footer_index


def test_header_navigation_uses_requested_labels_and_links():
    html = (REPO_ROOT / 'docs' / 'index.html').read_text(encoding='utf8')

    for label in ['Features', 'How It Works', 'Pricing', 'FAQ', 'Get Started', 'Add to Discord', 'Open Dashboard']:
        assert f'>{label}<' in html


def test_server_count_fallback_remains_safe_and_numeric_claim_starts_hidden():
    html = (REPO_ROOT / 'docs' / 'index.html').read_text(encoding='utf8')
    js = (REPO_ROOT / 'docs' / 'site.js').read_text(encoding='utf8')

    assert '>Trusted by Discord communities<' in html
    assert 'proof-primary--count" hidden' in html
    assert 'data-service-notice' in html
    assert "fetch('https://app.tweeticcini.com/public/stats'" in js
    assert "fetch('https://app.tweeticcini.com/public/status'" in js
    assert "window.localStorage.getItem('tweeticcini_server_count')" in js
    assert 'showFallback();' in js
    assert "notice.hidden = false;" in js
    assert "node.setAttribute('aria-hidden', 'true');" in js


def test_workflow_demo_contains_accessible_controls_and_live_preview():
    html = (REPO_ROOT / 'docs' / 'index.html').read_text(encoding='utf8')
    js = (REPO_ROOT / 'docs' / 'site.js').read_text(encoding='utf8')

    for label in [
        'Monitored account',
        'Source post',
        'Keyword filter',
        'Media requirement',
        'Destination channel',
        'Role mention',
        'Priority',
        'Alert style',
    ]:
        assert label in html

    assert 'Discord alert preview' in html
    assert 'aria-live="polite"' in html
    assert 'See how a post becomes the right Discord alert.' in html
    assert 'This demonstration uses fictional accounts and server settings.' in html
    assert "form.addEventListener('input', render);" in js
    assert "form.addEventListener('change', render);" in js


def test_dashboard_spotlight_uses_requested_tabs():
    html = (REPO_ROOT / 'docs' / 'index.html').read_text(encoding='utf8')
    js = (REPO_ROOT / 'docs' / 'site.js').read_text(encoding='utf8')

    for label in ['Sessions', 'Monitors', 'Rules', 'Appearance', 'Premium']:
        assert f'>{label}</button>' in html

    assert 'role="tablist"' in html
    assert 'role="tab"' in html
    assert 'role="tabpanel"' in html
    assert "event.key !== 'ArrowRight' && event.key !== 'ArrowLeft'" in js


def test_pricing_cta_links_preserve_plan_preselection_and_labels():
    html = (REPO_ROOT / 'docs' / 'index.html').read_text(encoding='utf8')

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


def test_faq_and_support_copy_remain_present():
    html = (REPO_ROOT / 'docs' / 'index.html').read_text(encoding='utf8')

    assert 'Why is a Twitter/X session required?' in html
    assert 'What Discord permissions do I need?' in html
    assert 'How do trials, cancellation, and billing work?' in html
    assert 'Help keep Tweeticcini running' in html
    assert 'Tweeticcini is independently built and maintained. One-time support helps cover hosting and continued development. 🩷' in html
    assert '“Love what you built! Keep it going!”' in html
    assert '— Tweeticcini supporter' in html
    assert 'https://img.buymeacoffee.com/button-api/?text=Buy%20me%20a%20booster%20pack' in html
    assert 'emoji=%F0%9F%83%8F' in html
    assert 'font_family=Bree' in html
    assert html.count('https://img.buymeacoffee.com/button-api/?text=Buy%20me%20a%20booster%20pack') == 1
    assert 'button.prod.min.js' not in html
    assert 'cdnjs.buymeacoffee.com' not in html
    assert 'https://www.buymeacoffee.com/pokaccini' in html
    assert '🃏 Buy me a booster pack' in html
    assert 'Start free, then upgrade when your server needs more speed or control.' in html


def test_support_section_csp_and_layout_use_image_embed_only():
    html = (REPO_ROOT / 'docs' / 'index.html').read_text(encoding='utf8')
    css = (REPO_ROOT / 'docs' / 'styles.css').read_text(encoding='utf8')
    js = (REPO_ROOT / 'docs' / 'site.js').read_text(encoding='utf8')

    assert "img-src 'self' data: https://img.buymeacoffee.com" in html
    assert 'https://app.tweeticcini.com' in html
    assert 'cdnjs.buymeacoffee.com' not in html
    assert '.pricing-section,' in css
    assert '.support-section,' in css
    assert '.faq-section {' in css
    assert 'padding: 30px;' in css
    assert '.support-note--wide' in css
    assert 'grid-template-columns: minmax(0, 1.2fr) auto minmax(220px, 0.9fr);' in css
    assert 'class="bmc-embed"' in html
    assert '&amp;emoji=%F0%9F%83%8F&amp;slug=pokaccini' in html
    assert 'class="button button-small bmc-fallback-link"' in html
    assert '>🃏 Buy me a booster pack</a>' in html
    assert '.bmc-embed-image' in css
    assert 'max-width: 100%;' in css
    assert 'max-width: 640px;' not in css
    assert '.support-note,\n.proof-notes .support-card,' not in css
    assert '.signal-card,\n.support-note {' not in css
    assert '.support-note .bmc-embed {' in css
    assert 'display: block;' in css
    assert 'width: fit-content;' in css
    assert 'margin-block: 24px;' in css
    assert 'order: 2;' in css
    assert 'visibility: hidden;' not in css
    mobile_embed_rule = re.search(r"\.support-note \.bmc-embed \{([^}]*)\}", css, re.MULTILINE)
    assert mobile_embed_rule is not None
    assert 'display: none;' not in mobile_embed_rule.group(1)
    assert '.bmc-embed-link {\n  display: inline-block;' in css
    assert '.bmc-fallback-link {\n  display: none;' in css
    assert '.bmc-embed--fallback-only .bmc-embed-link' in css
    assert '.bmc-embed--fallback-only .bmc-fallback-link' in css
    assert "const embed = document.querySelector('.bmc-embed');" in js
    assert "const isIOS = /iPad|iPhone|iPod/.test(userAgent)" in js
    assert "platform === 'MacIntel' && window.navigator.maxTouchPoints > 1" in js
    assert "embed.classList.add('bmc-embed--fallback-only');" in js
    assert "image.addEventListener('error', showFallbackButton, { once: true });" in js
    assert 'if (image.complete && image.naturalWidth === 0)' in js


def test_real_discord_delivery_image_has_desktop_constraint_and_mobile_fallback():
    css = (REPO_ROOT / 'docs' / 'styles.css').read_text(encoding='utf8')

    assert 'grid-template-columns: minmax(0, 520px) minmax(320px, 1fr);' in css
    assert '.proof-image-shell' in css
    assert 'max-width: 520px;' in css
    assert '.proof-image {' in css
    assert 'object-fit: contain;' in css
    assert '@media (max-width: 1100px)' in css
    assert '.proof-layout {' in css


def test_support_links_and_footer_resources_remain_destination_specific():
    html = (REPO_ROOT / 'docs' / 'index.html').read_text(encoding='utf8')

    assert 'footer-links-grid' in html
    assert '>Product<' in html
    assert '>Trust and Support<' in html
    assert '>Community<' in html
    assert 'Twitter alert routing for Discord' in html
    assert 'Support Server' in html
    assert 'Vote on Top.gg' in html
    assert 'Buy Me a Coffee' in html
    assert html.count('>Support<') == 1


def test_reduced_motion_rules_exist_for_public_and_dashboard_css():
    public_css = (REPO_ROOT / 'docs' / 'styles.css').read_text(encoding='utf8')
    dashboard_css = (REPO_ROOT / 'src' / 'dashboard_api' / 'static' / 'dashboard.css').read_text(encoding='utf8')

    assert '@media (prefers-reduced-motion: reduce)' in public_css
    assert '@media (prefers-reduced-motion: reduce)' in dashboard_css
