import signal
from contextlib import asynccontextmanager, contextmanager
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
    monkeypatch.delenv('ALLOW_UNAUTHENTICATED_DASHBOARD', raising=False)
    monkeypatch.delenv('DASHBOARD_INTERNAL_ADMIN_SECRET', raising=False)


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


class FakeGuildSettingsService:
    def __init__(self):
        self.override_calls = []
        self.entitlement_calls = []

    async def get_presentation_view(self, _guild_id: str) -> GuildPresentationView:
        return _build_view()

    async def get_entitlement_view(self, _guild_id: str) -> GuildEntitlementView:
        return _build_view().entitlement

    async def set_plan_override(self, guild_id: str, plan):
        self.override_calls.append((guild_id, plan))
        return _build_view(plan or 'free')

    async def set_subscription_entitlement(self, **kwargs):
        self.entitlement_calls.append(kwargs)
        return _build_view(kwargs.get('subscribed_plan') or 'free')


class FakeBillingService:
    def __init__(self, event=None):
        self.event = event or {}
        self.subscription_requests = []

    def construct_webhook_event(self, payload: bytes, signature: str):
        assert payload == b'{}'
        assert signature == 'sig'
        return self.event

    def get_subscription(self, subscription_id: str):
        self.subscription_requests.append(subscription_id)
        return {
            'status': 'active',
            'cancel_at_period_end': False,
            'current_period_end': 1_700_000_000,
            'trial_end': None,
        }


@contextmanager
def fail_after(seconds: int):
    def _handle_timeout(_signum, _frame):
        raise TimeoutError(f'test exceeded {seconds}s timeout')

    previous_handler = signal.signal(signal.SIGALRM, _handle_timeout)
    signal.setitimer(signal.ITIMER_REAL, seconds)
    try:
        yield
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous_handler)


def _disable_lifespan(app):
    @asynccontextmanager
    async def _noop_lifespan(_app):
        yield

    app.router.lifespan_context = _noop_lifespan


class FailingClientSession:
    def __init__(self, *args, **kwargs):
        raise AssertionError('unexpected network request in dashboard security test')


def _load_dashboard_app():
    import importlib

    module = importlib.import_module('src.dashboard_api.app')
    return importlib.reload(module)


def _build_request_test_app(module, monkeypatch):
    monkeypatch.setattr(module.aiohttp, 'ClientSession', FailingClientSession)
    app = module.create_app()
    _disable_lifespan(app)
    return app


def _build_request():
    return SimpleNamespace(session={}, headers={})


@pytest.mark.asyncio
async def test_production_with_complete_oauth_allows_managed_guild(base_env, monkeypatch):
    module = _load_dashboard_app()
    module.guild_settings_service = FakeGuildSettingsService()
    monkeypatch.setattr(module, '_get_session_user', lambda request: {'id': 'u1'})
    monkeypatch.setattr(module, '_get_session_guilds', lambda request: [{'id': 'guild-1'}])
    _build_request_test_app(module, monkeypatch)

    with fail_after(5):
        response = await module.get_guild_presentation(_build_request(), 'guild-1')

    assert response['plan'] == 'free'


def test_production_with_incomplete_oauth_fails_startup(base_env, monkeypatch):
    monkeypatch.delenv('DISCORD_CLIENT_SECRET', raising=False)
    module = _load_dashboard_app()

    with pytest.raises(RuntimeError, match='discord oauth configuration is incomplete'):
        with fail_after(5):
            module._validate_dashboard_auth_settings()


@pytest.mark.asyncio
async def test_development_with_explicit_bypass_enabled(base_env, monkeypatch):
    monkeypatch.setenv('APP_ENV', 'development')
    monkeypatch.setenv('ALLOW_UNAUTHENTICATED_DASHBOARD', 'true')
    monkeypatch.delenv('DISCORD_CLIENT_ID', raising=False)
    monkeypatch.delenv('DISCORD_CLIENT_SECRET', raising=False)
    monkeypatch.delenv('DISCORD_REDIRECT_URI', raising=False)
    module = _load_dashboard_app()
    module.guild_settings_service = FakeGuildSettingsService()
    _build_request_test_app(module, monkeypatch)

    with fail_after(5):
        response = await module.get_guild_presentation(_build_request(), 'guild-1')

    assert response['plan'] == 'free'


def test_development_with_bypass_disabled_fails_startup(base_env, monkeypatch):
    monkeypatch.setenv('APP_ENV', 'development')
    monkeypatch.delenv('DISCORD_CLIENT_ID', raising=False)
    monkeypatch.delenv('DISCORD_CLIENT_SECRET', raising=False)
    monkeypatch.delenv('DISCORD_REDIRECT_URI', raising=False)
    module = _load_dashboard_app()

    with pytest.raises(RuntimeError, match='discord oauth configuration is incomplete'):
        with fail_after(5):
            module._validate_dashboard_auth_settings()


@pytest.mark.asyncio
async def test_guild_admin_cannot_grant_paid_plan(base_env, monkeypatch):
    monkeypatch.setenv('DASHBOARD_INTERNAL_ADMIN_SECRET', 'internal-secret')
    module = _load_dashboard_app()
    fake_service = FakeGuildSettingsService()
    module.guild_settings_service = fake_service
    monkeypatch.setattr(module, '_get_session_user', lambda request: {'id': 'u1'})
    monkeypatch.setattr(module, '_get_session_guilds', lambda request: [{'id': 'guild-1'}])
    _build_request_test_app(module, monkeypatch)

    with pytest.raises(module.HTTPException) as error_info:
        with fail_after(5):
            await module.update_guild_plan(_build_request(), 'guild-1', module.UpdateGuildPlanRequest(plan='pro'))

    assert error_info.value.status_code == 403
    assert fake_service.override_calls == []


@pytest.mark.asyncio
async def test_internal_admin_can_override_plan(base_env, monkeypatch):
    monkeypatch.setenv('DASHBOARD_INTERNAL_ADMIN_SECRET', 'internal-secret')
    module = _load_dashboard_app()
    fake_service = FakeGuildSettingsService()
    module.guild_settings_service = fake_service
    monkeypatch.setattr(module, '_get_session_user', lambda request: {'id': 'u1'})
    monkeypatch.setattr(module, '_get_session_guilds', lambda request: [{'id': 'guild-1'}])
    _build_request_test_app(module, monkeypatch)
    request = _build_request()
    request.headers = {'x-tweeticcini-admin-secret': 'internal-secret'}

    with fail_after(5):
        response = await module.update_guild_plan(
            request,
            'guild-1',
            module.UpdateGuildPlanRequest(plan='pro'),
        )

    assert fake_service.override_calls == [('guild-1', 'pro')]
    assert response['plan'] == 'pro'


@pytest.mark.asyncio
async def test_stripe_webhook_updates_entitlement(base_env, monkeypatch):
    module = _load_dashboard_app()
    fake_service = FakeGuildSettingsService()
    fake_billing = FakeBillingService(
        event={
            'type': 'checkout.session.completed',
            'data': {
                'object': {
                    'client_reference_id': 'guild-1',
                    'customer': 'cus_123',
                    'subscription': 'sub_123',
                    'metadata': {'guild_id': 'guild-1', 'plan': 'pro'},
                }
            },
        }
    )
    module.guild_settings_service = fake_service
    module.billing_service = fake_billing
    _build_request_test_app(module, monkeypatch)

    class WebhookRequest:
        headers = {'stripe-signature': 'sig'}

        async def body(self):
            return b'{}'

    with fail_after(5):
        response = await module.stripe_billing_webhook(WebhookRequest())

    assert response == {'received': True}
    assert fake_billing.subscription_requests == ['sub_123']
    assert fake_service.entitlement_calls
    assert fake_service.entitlement_calls[0]['server_id'] == 'guild-1'
    assert fake_service.entitlement_calls[0]['subscribed_plan'] == 'pro'
    assert fake_service.entitlement_calls[0]['billing_provider'] == 'stripe'


@pytest.mark.asyncio
async def test_guild_access_denied_for_unmanaged_server(base_env, monkeypatch):
    module = _load_dashboard_app()
    module.guild_settings_service = FakeGuildSettingsService()
    monkeypatch.setattr(module, '_get_session_user', lambda request: {'id': 'u1'})
    monkeypatch.setattr(module, '_get_session_guilds', lambda request: [{'id': 'guild-2'}])
    _build_request_test_app(module, monkeypatch)

    with pytest.raises(module.HTTPException) as error_info:
        with fail_after(5):
            await module.get_guild_presentation(_build_request(), 'guild-1')

    assert error_info.value.status_code == 403
