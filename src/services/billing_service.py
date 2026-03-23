import os
from dataclasses import dataclass
from typing import Optional

PLAN_PRICE_ENV = {
    'pro': 'STRIPE_PRICE_ID_PRO',
}


@dataclass(frozen=True)
class StripeCheckoutContext:
    publishable_configured: bool
    secret_configured: bool
    webhook_configured: bool
    portal_configured: bool
    available_price_plans: list[str]


class BillingConfigurationError(Exception):
    pass


class BillingService:
    def __init__(self):
        self.secret_key = os.getenv('STRIPE_SECRET_KEY')
        self.publishable_key = os.getenv('STRIPE_PUBLISHABLE_KEY')
        self.webhook_secret = os.getenv('STRIPE_WEBHOOK_SECRET')
        self.portal_configured = bool(self.secret_key)

    @staticmethod
    def _load_stripe():
        try:
            import stripe  # type: ignore
        except ModuleNotFoundError as error:
            raise BillingConfigurationError('Stripe SDK is not installed; run `pip install -r requirements.txt`') from error
        return stripe

    def get_context(self) -> StripeCheckoutContext:
        return StripeCheckoutContext(
            publishable_configured=bool(self.publishable_key),
            secret_configured=bool(self.secret_key),
            webhook_configured=bool(self.webhook_secret),
            portal_configured=self.portal_configured,
            available_price_plans=[plan for plan, env_name in PLAN_PRICE_ENV.items() if os.getenv(env_name)],
        )

    def get_price_id_for_plan(self, plan: str) -> str:
        env_name = PLAN_PRICE_ENV.get(plan)
        if env_name is None:
            raise BillingConfigurationError(f'unsupported billing plan `{plan}`')
        price_id = os.getenv(env_name)
        if not price_id:
            raise BillingConfigurationError(f'missing required Stripe price env var `{env_name}`')
        return price_id

    def create_checkout_session(
        self,
        plan: str,
        guild_id: str,
        guild_name: str,
        discord_user_id: Optional[str],
        success_url: str,
        cancel_url: str,
    ) -> str:
        if not self.secret_key:
            raise BillingConfigurationError('Stripe secret key is not configured')
        stripe = self._load_stripe()
        stripe.api_key = self.secret_key
        price_id = self.get_price_id_for_plan(plan)
        session = stripe.checkout.Session.create(
            mode='subscription',
            success_url=success_url,
            cancel_url=cancel_url,
            line_items=[{'price': price_id, 'quantity': 1}],
            allow_promotion_codes=True,
            client_reference_id=guild_id,
            metadata={
                'guild_id': guild_id,
                'guild_name': guild_name,
                'discord_user_id': discord_user_id or '',
                'plan': plan,
            },
            subscription_data={
                'metadata': {
                    'guild_id': guild_id,
                    'guild_name': guild_name,
                    'discord_user_id': discord_user_id or '',
                    'plan': plan,
                }
            },
        )
        return str(session.url)

    def create_billing_portal_session(
        self,
        customer_id: str,
        return_url: str,
        subscription_id: Optional[str] = None,
    ) -> str:
        if not self.secret_key:
            raise BillingConfigurationError('Stripe secret key is not configured')
        stripe = self._load_stripe()
        stripe.api_key = self.secret_key
        session_kwargs = {
            'customer': customer_id,
            'return_url': return_url,
        }
        if subscription_id:
            session_kwargs['flow_data'] = {
                'type': 'subscription_cancel',
                'subscription_cancel': {
                    'subscription': subscription_id,
                },
                'after_completion': {
                    'type': 'redirect',
                    'redirect': {
                        'return_url': return_url,
                    },
                },
            }

        session = stripe.billing_portal.Session.create(**session_kwargs)
        return str(session.url)

    def construct_webhook_event(self, payload: bytes, signature: Optional[str]):
        if not self.secret_key or not self.webhook_secret:
            raise BillingConfigurationError('Stripe webhook configuration is incomplete')
        if not signature:
            raise BillingConfigurationError('missing Stripe signature header')
        stripe = self._load_stripe()
        stripe.api_key = self.secret_key
        return stripe.Webhook.construct_event(payload, signature, self.webhook_secret)
