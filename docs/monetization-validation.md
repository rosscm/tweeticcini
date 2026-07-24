# Monetization Validation

## Prerequisites

- Stripe is in test mode.
- Test Stripe product and price IDs are configured.
- The webhook endpoint is reachable from Stripe.
- `STRIPE_WEBHOOK_SECRET` is configured.
- A Free test server is available.
- The tester can manage that server in Discord.
- No production customer or payment data is used.

## Plus Trial

1. Open the dashboard for a Free test server.
2. Begin the existing trial flow.
3. Confirm Stripe shows the Plus plan.
4. Confirm the displayed price is correct.
5. Confirm the trial period is seven days.
6. Complete checkout with a Stripe test payment method.
7. Confirm checkout returns to the expected billing dashboard route.
8. Confirm the webhook applies Plus entitlement.
9. Confirm the dashboard displays Plus.
10. Confirm Plus monitor limits and polling behaviour.
11. Confirm Premium-only features remain unavailable.

## Premium Subscription

1. Begin Premium checkout from a Free or otherwise eligible test server.
2. Confirm Stripe shows the Premium plan and correct price.
3. Complete checkout.
4. Confirm the webhook applies Premium entitlement.
5. Confirm Premium monitor limits.
6. Confirm Rules unlock.
7. Confirm paid appearance features unlock.
8. Confirm the sidebar and dashboard display Premium correctly.

## Customer Portal And Cancellation

1. Open Manage subscription.
2. Confirm the correct Stripe customer portal opens.
3. Schedule cancellation at period end.
4. Confirm the dashboard reflects the expected cancellation state if shown.
5. Confirm paid entitlement remains active until the intended end date.
6. Confirm downgrade occurs when the subscription ends.
7. Confirm the server returns to the correct Free limits.

## Payment-State Handling

Verify handling for:

- past-due subscriptions;
- failed renewal;
- unpaid status;
- subscription deletion;
- immediate cancellation where supported.

Confirm paid access does not remain indefinitely after the intended downgrade path.

## Webhook Safety

Confirm:

- invalid webhook signatures are rejected;
- replaying an already processed event does not duplicate entitlement changes where idempotency applies;
- unsupported event types are ignored safely;
- malformed metadata does not grant access;
- unknown guilds do not cause application failure;
- webhook failures produce useful logs without exposing secrets.

## Buy Me a Coffee

Confirm:

- the link opens the intended external page;
- it is clearly separate from paid subscriptions;
- it does not imply that a donation grants Plus or Premium access.
