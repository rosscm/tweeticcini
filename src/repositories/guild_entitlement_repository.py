import aiosqlite

from src.db_function.readonly_db import connect_readonly
from src.repositories.notifier_repository import connect_writable


async def get_guild_entitlement_row(db_path, server_id: str):
    async with connect_readonly(db_path) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            '''
            SELECT
                server_id,
                subscribed_plan,
                manual_plan_override,
                entitlement_status,
                billing_provider,
                external_customer_id,
                external_subscription_id,
                current_period_end,
                cancel_at_period_end,
                trial_ends_at,
                is_test,
                updated_at
            FROM guild_entitlement
            WHERE server_id = ?
            ''',
            (server_id,),
        ) as cursor:
            return await cursor.fetchone()


async def upsert_guild_entitlement(
    db_path,
    server_id: str,
    subscribed_plan,
    manual_plan_override,
    entitlement_status: str,
    billing_provider,
    external_customer_id,
    external_subscription_id,
    current_period_end,
    cancel_at_period_end,
    trial_ends_at,
    is_test: int,
    updated_at,
) -> None:
    async with connect_writable(db_path) as db:
        await db.execute(
            '''
            INSERT INTO guild_entitlement (
                server_id,
                subscribed_plan,
                manual_plan_override,
                entitlement_status,
                billing_provider,
                external_customer_id,
                external_subscription_id,
                current_period_end,
                cancel_at_period_end,
                trial_ends_at,
                is_test,
                updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(server_id) DO UPDATE SET
                subscribed_plan = excluded.subscribed_plan,
                manual_plan_override = excluded.manual_plan_override,
                entitlement_status = excluded.entitlement_status,
                billing_provider = excluded.billing_provider,
                external_customer_id = excluded.external_customer_id,
                external_subscription_id = excluded.external_subscription_id,
                current_period_end = excluded.current_period_end,
                cancel_at_period_end = excluded.cancel_at_period_end,
                trial_ends_at = excluded.trial_ends_at,
                is_test = excluded.is_test,
                updated_at = excluded.updated_at
            ''',
            (
                server_id,
                subscribed_plan,
                manual_plan_override,
                entitlement_status,
                billing_provider,
                external_customer_id,
                external_subscription_id,
                current_period_end,
                cancel_at_period_end,
                trial_ends_at,
                is_test,
                updated_at,
            ),
        )
        await db.commit()
