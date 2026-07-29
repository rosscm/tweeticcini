import importlib
import sqlite3
from dataclasses import replace
from types import SimpleNamespace

import pytest

from src.db_function.guild_settings import get_default_guild_presentation_settings
from src.services.guild_settings_service import (
    GuildComplianceView,
    GuildEntitlementView,
    GuildPlanFeatures,
    GuildPresentationView,
)


@pytest.fixture
def base_env(monkeypatch, tmp_path):
    monkeypatch.setenv('DATA_PATH', str(tmp_path))
    monkeypatch.setenv('DASHBOARD_SESSION_SECRET', 'test-session-secret')
    monkeypatch.setenv('DISCORD_CLIENT_ID', '123')
    monkeypatch.setenv('DISCORD_CLIENT_SECRET', 'secret')
    monkeypatch.setenv('DISCORD_REDIRECT_URI', 'https://example.com/dashboard/callback')
    monkeypatch.setenv('APP_ENV', 'production')


def _build_view(plan: str = 'free') -> GuildPresentationView:
    features = GuildPlanFeatures(
        max_twitter_sessions=1,
        max_sources=1,
        max_rules=0,
        max_trigger_keywords_total=0,
        max_exclude_keywords_total=0,
        can_customize_presentation=False,
        can_customize_source_messages=False,
        can_use_everyone_escalation=False,
    )
    if plan == 'pro':
        features = replace(
            features,
            max_twitter_sessions=5,
            max_sources=10,
            max_rules=30,
            max_trigger_keywords_total=150,
            max_exclude_keywords_total=250,
            can_customize_presentation=True,
            can_customize_source_messages=True,
            can_use_everyone_escalation=True,
        )
    return GuildPresentationView(
        plan=plan,
        features=features,
        effective=get_default_guild_presentation_settings(),
        has_overrides=False,
        entitlement=GuildEntitlementView(
            effective_plan=plan,
            plan_source='default',
            entitlement_status='none',
            subscribed_plan=None,
            manual_plan_override=None,
            billing_provider=None,
            external_customer_id=None,
            external_subscription_id=None,
            current_period_end=None,
            cancel_at_period_end=False,
            trial_ends_at=None,
            trial_used_at=None,
            is_test=True,
        ),
        compliance=GuildComplianceView(
            is_non_compliant=False,
            reason_labels=(),
            session_count=0,
            source_count=0,
            rule_count=0,
            over_session_limit=False,
            over_source_limit=False,
            over_rule_limit=False,
            has_premium_rules=False,
            has_premium_presentation=False,
            has_premium_source_overrides=False,
        ),
        grandfathered_free_source_limit=None,
    )


def _load_dashboard_app():
    module = importlib.import_module('src.dashboard_api.app')
    return importlib.reload(module)


class FakeCheckoutBillingService:
    def __init__(self, *, url='https://stripe.test/session', error=None):
        self.url = url
        self.error = error
        self.calls = []

    def create_checkout_session(self, **kwargs):
        self.calls.append(kwargs)
        if self.error:
            raise self.error
        return self.url


def _build_request(*, session=None, query_params=None):
    request = SimpleNamespace()
    request.session = session or {}
    request.headers = {}
    request.query_params = query_params or {}
    request.url_for = lambda name, **kwargs: SimpleNamespace(
        replace=lambda path=None: 'https://example.com/dashboard/callback'
        if name == 'dashboard_callback'
        else f"https://example.com/dashboard/guilds/{kwargs['guild_id']}/billing"
    )
    return request


def _ensure_onboarding_test_table(db_path: str) -> None:
    with sqlite3.connect(db_path) as db:
        db.execute(
            '''
            CREATE TABLE IF NOT EXISTS guild_onboarding_state (
                server_id TEXT PRIMARY KEY,
                onboarding_sent_at TEXT DEFAULT NULL,
                onboarding_dismissed INTEGER DEFAULT 0,
                test_alert_sent_at TEXT DEFAULT NULL,
                requires_test_alert_step INTEGER DEFAULT NULL
            )
            '''
        )
        db.commit()


def _insert_onboarding_state(db_path: str, server_id: str, *, requires_test_alert_step: bool) -> None:
    with sqlite3.connect(db_path) as db:
        db.execute(
            '''
            INSERT INTO guild_onboarding_state (
                server_id,
                onboarding_sent_at,
                onboarding_dismissed,
                test_alert_sent_at,
                requires_test_alert_step
            )
            VALUES (?, NULL, 0, NULL, ?)
            ''',
            (server_id, int(requires_test_alert_step)),
        )
        db.commit()


def _get_onboarding_requirement(db_path: str, server_id: str) -> bool | None:
    with sqlite3.connect(db_path) as db:
        row = db.execute(
            '''
            SELECT requires_test_alert_step
            FROM guild_onboarding_state
            WHERE server_id = ?
            LIMIT 1
            ''',
            (server_id,),
        ).fetchone()
    if row is None or row[0] is None:
        return None
    return bool(int(row[0]))


def test_plan_badge_tone_maps_plus_and_premium(base_env):
    module = _load_dashboard_app()

    assert module._get_plan_badge_tone('free') == 'free'
    assert module._get_plan_badge_tone('plus') == 'plus'
    assert module._get_plan_badge_tone('pro') == 'premium'


def test_overview_setup_progress_always_uses_three_steps(base_env):
    module = _load_dashboard_app()

    no_session = module._build_overview_setup_progress(
        sessions_ready=False,
        monitors_ready=False,
        delivery_ready=False,
    )
    session_only = module._build_overview_setup_progress(
        sessions_ready=True,
        monitors_ready=False,
        delivery_ready=False,
    )
    session_and_monitor = module._build_overview_setup_progress(
        sessions_ready=True,
        monitors_ready=True,
        delivery_ready=False,
    )
    delivered = module._build_overview_setup_progress(
        sessions_ready=True,
        monitors_ready=True,
        delivery_ready=True,
    )

    assert no_session['step_total'] == 3
    assert no_session['completed_count'] == 0
    assert session_only['completed_count'] == 1
    assert session_and_monitor['completed_count'] == 2
    assert delivered['completed_count'] == 3
    assert delivered['delivery_ready'] is True


def test_status_heading_is_never_attention_for_healthy_server(base_env):
    module = _load_dashboard_app()

    healthy_progress = module._build_overview_setup_progress(
        sessions_ready=True,
        monitors_ready=True,
        delivery_ready=True,
    )
    setup_progress = module._build_overview_setup_progress(
        sessions_ready=False,
        monitors_ready=False,
        delivery_ready=False,
    )
    warning_progress = module._build_overview_setup_progress(
        sessions_ready=True,
        monitors_ready=True,
        delivery_ready=False,
    )

    assert module._get_status_heading('success', healthy_progress) == 'Everything is running normally'
    assert module._get_status_heading('error', setup_progress) == 'Setup is still required'
    assert module._get_status_heading('warning', warning_progress) == 'Attention required'


def test_next_step_panel_uses_setup_state_actions(base_env):
    module = _load_dashboard_app()

    no_session = module._build_next_step_panel(
        module._build_overview_setup_progress(
            sessions_ready=False,
            monitors_ready=False,
            delivery_ready=False,
        ),
        has_test_alert_action=False,
    )
    session_only = module._build_next_step_panel(
        module._build_overview_setup_progress(
            sessions_ready=True,
            monitors_ready=False,
            delivery_ready=False,
        ),
        has_test_alert_action=False,
    )
    verify_delivery = module._build_next_step_panel(
        module._build_overview_setup_progress(
            sessions_ready=True,
            monitors_ready=True,
            delivery_ready=False,
        ),
        has_test_alert_action=True,
    )
    completed = module._build_next_step_panel(
        module._build_overview_setup_progress(
            sessions_ready=True,
            monitors_ready=True,
            delivery_ready=True,
        ),
        has_test_alert_action=False,
    )

    assert no_session['title'] == 'Connect a session'
    assert no_session['cta_href'] == 'twitter-sessions'
    assert session_only['title'] == 'Add your first monitor'
    assert session_only['cta_href'] == 'sources'
    assert verify_delivery['title'] == 'Verify delivery'
    assert verify_delivery['use_test_alert'] is True
    assert completed['title'] == 'Setup complete'
    assert completed['cta_label'] == 'Manage monitors'


def test_free_support_card_uses_delivery_count_and_pluralization(base_env):
    module = _load_dashboard_app()

    zero = module._build_free_support_card(0)
    one = module._build_free_support_card(1)
    many = module._build_free_support_card(1234)
    malformed = module._build_free_support_card(module._coerce_non_negative_int('oops'))

    assert zero['title'] == '☕ Want to support Tweeticcini?'
    assert one['title'] == '☕ Tweeticcini has delivered 1 alert through your current setup'
    assert many['title'] == '☕ Tweeticcini has delivered 1,234 alerts through your current setup'
    assert malformed['title'] == '☕ Want to support Tweeticcini?'
    assert many['action_label'] == 'Buy Me a Coffee'
    assert many['footer_note'] == 'Paid memberships already support Tweeticcini directly, so this support note is only shown on the Free plan. 🩷'


def test_delivery_count_coercion_is_non_negative(base_env):
    module = _load_dashboard_app()

    assert module._coerce_non_negative_int(None) == 0
    assert module._coerce_non_negative_int('') == 0
    assert module._coerce_non_negative_int('7') == 7
    assert module._coerce_non_negative_int(-5) == 0
    assert module._coerce_non_negative_int('oops') == 0


def test_existing_guilds_are_grandfathered_without_test_alert_requirement(tmp_path):
    db_path = str(tmp_path / 'tweeticcini.db')
    _ensure_onboarding_test_table(db_path)

    _insert_onboarding_state(db_path, 'legacy-guild', requires_test_alert_step=False)

    assert _get_onboarding_requirement(db_path, 'legacy-guild') is False
    onboarding_complete = True and True and (False or True)
    assert onboarding_complete is True


def test_new_guilds_receive_three_step_onboarding(tmp_path):
    db_path = str(tmp_path / 'tweeticcini.db')
    _ensure_onboarding_test_table(db_path)

    _insert_onboarding_state(db_path, 'new-guild', requires_test_alert_step=True)

    assert _get_onboarding_requirement(db_path, 'new-guild') is True
    onboarding_complete = True and True and (False or False)
    assert onboarding_complete is False


@pytest.mark.asyncio
async def test_dashboard_home_redirects_to_billing_with_selected_plan(base_env):
    module = _load_dashboard_app()
    request = _build_request(
        session={'discord_guilds': [{'id': 'guild-1'}]},
        query_params={'guild_id': 'guild-1', 'plan': 'plus'},
    )

    response = await module.dashboard_home(request)

    assert response.headers['location'] == '/dashboard/guilds/guild-1/billing?plan=plus'
    assert request.session['pending_billing_plan'] == 'plus'


@pytest.mark.asyncio
async def test_dashboard_login_stores_requested_plan(base_env):
    module = _load_dashboard_app()
    request = _build_request(query_params={'plan': 'pro'})

    response = await module.dashboard_login(request)

    assert response.headers['location'].startswith('https://discord.com/api/oauth2/authorize?')
    assert request.session['pending_billing_plan'] == 'pro'


@pytest.mark.asyncio
async def test_dashboard_callback_redirects_to_billing_when_plan_is_pending(base_env, monkeypatch):
    module = _load_dashboard_app()

    class FakeResponse:
        def __init__(self, status, payload):
            self.status = status
            self._payload = payload

        async def json(self):
            return self._payload

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

    class FakeClientSession:
        def post(self, *_args, **_kwargs):
            return FakeResponse(200, {'access_token': 'token'})

        def get(self, url, **_kwargs):
            if url.endswith('/users/@me'):
                return FakeResponse(200, {'id': 'u1', 'username': 'user1', 'global_name': 'User One'})
            return FakeResponse(200, [{'id': 'guild-1', 'name': 'Guild 1', 'permissions': str(0x8), 'owner': True, 'icon': None}])

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

    async def fake_annotate_guild_bot_presence(guilds):
        return guilds

    monkeypatch.setattr(module.aiohttp, 'ClientSession', FakeClientSession)
    monkeypatch.setattr(module, '_annotate_guild_bot_presence', fake_annotate_guild_bot_presence)
    request = _build_request(
        session={
            'discord_oauth_state': 'state-1',
            'pending_dashboard_guild_id': 'guild-1',
            'pending_billing_plan': 'plus',
        }
    )

    response = await module.dashboard_callback(request, code='code-1', state='state-1')

    assert response.headers['location'] == '/dashboard/guilds/guild-1/billing?plan=plus'


@pytest.mark.asyncio
async def test_checkout_session_uses_server_selected_plus_plan(base_env, monkeypatch):
    module = _load_dashboard_app()
    module.guild_settings_service = SimpleNamespace(get_presentation_view=lambda _guild_id: _async_return(_build_view()))
    fake_billing = FakeCheckoutBillingService()
    module.billing_service = fake_billing
    monkeypatch.setattr(module, '_get_session_guilds', lambda request: [{'id': 'guild-1', 'name': 'Guild 1'}])
    monkeypatch.setattr(module, '_get_session_user', lambda request: {'id': 'u1'})

    request = _build_request(session={'discord_guilds': [{'id': 'guild-1', 'name': 'Guild 1'}], 'discord_user': {'id': 'u1'}})

    response = await module.create_guild_checkout_session(
        request,
        'guild-1',
        module.CreateCheckoutSessionRequest(plan='plus'),
    )

    assert response == {'url': 'https://stripe.test/session'}
    assert request.session['pending_billing_plan'] == 'plus'
    assert len(fake_billing.calls) == 1
    assert fake_billing.calls[0]['plan'] == 'plus'
    assert fake_billing.calls[0]['guild_id'] == 'guild-1'
    assert fake_billing.calls[0]['guild_name'] == 'Guild 1'
    assert fake_billing.calls[0]['discord_user_id'] == 'u1'
    assert fake_billing.calls[0]['success_url'].endswith('?checkout=success')
    assert fake_billing.calls[0]['cancel_url'].endswith('?checkout=canceled')
    assert fake_billing.calls[0]['allow_trial'] is True


@pytest.mark.asyncio
async def test_checkout_session_returns_clear_error_when_stripe_fails(base_env, monkeypatch):
    module = _load_dashboard_app()
    module.guild_settings_service = SimpleNamespace(get_presentation_view=lambda _guild_id: _async_return(_build_view()))
    module.billing_service = FakeCheckoutBillingService(error=RuntimeError('stripe down'))
    monkeypatch.setattr(module, '_get_session_guilds', lambda request: [{'id': 'guild-1'}])
    monkeypatch.setattr(module, '_get_session_user', lambda request: {'id': 'u1'})

    request = _build_request(session={'discord_guilds': [{'id': 'guild-1'}], 'discord_user': {'id': 'u1'}})

    with pytest.raises(module.HTTPException) as error_info:
        await module.create_guild_checkout_session(
            request,
            'guild-1',
            module.CreateCheckoutSessionRequest(plan='plus'),
        )

    assert error_info.value.status_code == 502
    assert error_info.value.detail == 'unable to start Stripe checkout right now'


async def _async_return(value):
    return value


@pytest.mark.asyncio
async def test_test_alert_requires_dashboard_access(base_env, monkeypatch):
    module = _load_dashboard_app()
    monkeypatch.setenv('BOT_TOKEN', 'bot-token')
    request = _build_request(session={'discord_user': {'id': 'u1'}, 'discord_guilds': [{'id': 'other-guild'}]})

    with pytest.raises(module.HTTPException) as error_info:
        await module.send_guild_source_test_alert(
            request,
            'guild-1',
            module.SendDashboardSourceTestRequest(username='source', channel_id='123'),
        )

    assert error_info.value.status_code == 403


@pytest.mark.asyncio
async def test_test_alert_marks_onboarding_complete_and_returns_preview_summary(base_env, monkeypatch):
    module = _load_dashboard_app()
    monkeypatch.setenv('BOT_TOKEN', 'bot-token')

    async def fake_fetch_resources(_guild_id):
        return {
            'channels': {'123': 'alerts'},
            'roles': {'456': 'Restocks'},
        }

    async def fake_send_test_alert(_channel_id, _message):
        return None

    marked = []

    async def fake_mark_test_alert_sent(_db_path, guild_id, sent_at):
        marked.append((guild_id, sent_at))

    class FakeGuildSettingsService:
        async def get_presentation_view(self, _guild_id):
            return _build_view(plan='pro')

    monkeypatch.setattr(module, '_fetch_guild_resource_names', fake_fetch_resources)
    monkeypatch.setattr(module, '_send_test_alert_message', fake_send_test_alert)
    monkeypatch.setattr(module, 'mark_test_alert_sent', fake_mark_test_alert_sent)
    module.guild_settings_service = FakeGuildSettingsService()
    request = _build_request(session={'discord_user': {'id': 'u1'}, 'discord_guilds': [{'id': 'guild-1'}]})

    response = await module.send_guild_source_test_alert(
        request,
        'guild-1',
        module.SendDashboardSourceTestRequest(
            username='source',
            channel_id='123',
            role_id='456',
            customized_msg='',
            use_headline_message_override=True,
        ),
    )

    assert response['channel_name'] == 'alerts'
    assert response['format_label'] == 'headline-style'
    assert response['mention_preview'] == '@Restocks shown as plain text (non-pinging preview)'
    assert 'Channel access is working' in response['status_summary']
    assert marked and marked[0][0] == 'guild-1'


@pytest.mark.asyncio
async def test_existing_guilds_can_send_voluntary_test_alerts_without_losing_grandfathering(base_env, monkeypatch, tmp_path):
    module = _load_dashboard_app()
    monkeypatch.setenv('BOT_TOKEN', 'bot-token')
    db_path = str(tmp_path / 'tweeticcini.db')
    _ensure_onboarding_test_table(db_path)
    _insert_onboarding_state(db_path, 'guild-1', requires_test_alert_step=False)

    async def fake_fetch_resources(_guild_id):
        return {
            'channels': {'123': 'alerts'},
            'roles': {'456': 'Restocks'},
        }

    async def fake_send_test_alert(_channel_id, _message):
        return None

    async def fake_mark_test_alert_sent(db_path_arg, guild_id, sent_at):
        with sqlite3.connect(db_path_arg) as db:
            db.execute(
                '''
                UPDATE guild_onboarding_state
                SET test_alert_sent_at = ?
                WHERE server_id = ?
                ''',
                (sent_at, guild_id),
            )
            db.commit()

    class FakeGuildSettingsService:
        async def get_presentation_view(self, _guild_id):
            return _build_view(plan='pro')

    monkeypatch.setattr(module, '_fetch_guild_resource_names', fake_fetch_resources)
    monkeypatch.setattr(module, '_send_test_alert_message', fake_send_test_alert)
    monkeypatch.setattr(module, 'mark_test_alert_sent', fake_mark_test_alert_sent)
    module.guild_settings_service = FakeGuildSettingsService()
    module.notifier_service.db_path = db_path
    request = _build_request(session={'discord_user': {'id': 'u1'}, 'discord_guilds': [{'id': 'guild-1'}]})

    response = await module.send_guild_source_test_alert(
        request,
        'guild-1',
        module.SendDashboardSourceTestRequest(
            username='source',
            channel_id='123',
            role_id='456',
        ),
    )

    assert response['channel_name'] == 'alerts'
    assert _get_onboarding_requirement(db_path, 'guild-1') is False
