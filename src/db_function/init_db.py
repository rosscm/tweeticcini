import os

import aiosqlite

from src.db_function.guild_settings import get_legacy_exclude_keywords, get_legacy_trigger_keywords
from src.log import setup_logger
from src.repositories.alert_rule_repository import migrate_legacy_alert_rules_for_existing_guilds
from src.settings import DB_FILENAME, get_data_path

log = setup_logger(__name__)


async def ensure_db_schema() -> str:
    data_path = get_data_path()
    if not os.path.exists(data_path):
        os.mkdir(data_path)

    db_path = data_path / DB_FILENAME
    legacy_root_db = DB_FILENAME
    db_created = not os.path.exists(db_path)

    if os.path.exists(legacy_root_db) and os.path.abspath(legacy_root_db) != os.path.abspath(db_path):
        log.warning(
            f'found a second database file at {legacy_root_db}; active database is {db_path}. '
            'Consider archiving the stray file to avoid editing the wrong copy.'
        )

    async with aiosqlite.connect(db_path) as db:
        await db.executescript("""
            CREATE TABLE IF NOT EXISTS user (id TEXT PRIMARY KEY, username TEXT, lastest_tweet TEXT, client_used TEXT, enabled INTEGER DEFAULT 1);
            CREATE TABLE IF NOT EXISTS channel (id TEXT PRIMARY KEY, server_id TEXT);
            CREATE TABLE IF NOT EXISTS notification (
                user_id TEXT,
                channel_id TEXT,
                role_id TEXT,
                enabled INTEGER DEFAULT 1,
                enable_type TEXT DEFAULT 11,
                enable_media_type TEXT DEFAULT 11,
                customized_msg TEXT DEFAULT NULL,
                force_everyone INTEGER DEFAULT 0,
                FOREIGN KEY (user_id) REFERENCES user (id),
                FOREIGN KEY (channel_id) REFERENCES channel (id),
                PRIMARY KEY(user_id, channel_id)
            );
            CREATE TABLE IF NOT EXISTS guild_settings (
                server_id TEXT PRIMARY KEY,
                plan TEXT DEFAULT 'free',
                default_message_override TEXT DEFAULT NULL,
                emoji_auto_format_override INTEGER DEFAULT NULL,
                bot_display_name_override TEXT DEFAULT NULL,
                embed_type_override TEXT DEFAULT NULL,
                built_in_fx_image_override INTEGER DEFAULT NULL,
                built_in_video_link_button_override INTEGER DEFAULT NULL,
                built_in_legacy_logo_override INTEGER DEFAULT NULL,
                fx_domain_name_override TEXT DEFAULT NULL,
                fx_original_url_button_override INTEGER DEFAULT NULL
            );
            CREATE TABLE IF NOT EXISTS guild_entitlement (
                server_id TEXT PRIMARY KEY,
                subscribed_plan TEXT DEFAULT NULL,
                manual_plan_override TEXT DEFAULT NULL,
                entitlement_status TEXT DEFAULT 'none',
                billing_provider TEXT DEFAULT NULL,
                external_customer_id TEXT DEFAULT NULL,
                external_subscription_id TEXT DEFAULT NULL,
                current_period_end TEXT DEFAULT NULL,
                trial_ends_at TEXT DEFAULT NULL,
                is_test INTEGER DEFAULT 1,
                updated_at TEXT DEFAULT NULL
            );
            CREATE TABLE IF NOT EXISTS app_meta (
                key TEXT PRIMARY KEY,
                value TEXT DEFAULT NULL
            );
            CREATE TABLE IF NOT EXISTS alert_rule (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                server_id TEXT NOT NULL,
                rule_name TEXT NOT NULL,
                source_username TEXT DEFAULT NULL,
                channel_id TEXT DEFAULT NULL,
                enabled INTEGER DEFAULT 1,
                priority INTEGER DEFAULT 0,
                trigger_keywords TEXT DEFAULT NULL,
                exclude_keywords TEXT DEFAULT NULL,
                force_everyone INTEGER DEFAULT NULL
            );
            CREATE UNIQUE INDEX IF NOT EXISTS idx_alert_rule_server_name
            ON alert_rule (server_id, rule_name);
            CREATE TABLE IF NOT EXISTS runtime_client_status (
                client_used TEXT PRIMARY KEY,
                last_poll_success_at TEXT DEFAULT NULL,
                last_notification_count INTEGER DEFAULT 0,
                last_poll_error_at TEXT DEFAULT NULL,
                last_error_message TEXT DEFAULT NULL
            );
            CREATE TABLE IF NOT EXISTS runtime_source_status (
                server_id TEXT NOT NULL,
                username TEXT NOT NULL,
                channel_id TEXT NOT NULL,
                last_delivery_success_at TEXT DEFAULT NULL,
                last_delivery_error_at TEXT DEFAULT NULL,
                last_error_message TEXT DEFAULT NULL,
                last_matched_rule_name TEXT DEFAULT NULL,
                last_delivery_url TEXT DEFAULT NULL,
                success_count INTEGER DEFAULT 0,
                error_count INTEGER DEFAULT 0,
                PRIMARY KEY(server_id, username, channel_id)
            );
        """)

        async with db.execute("PRAGMA table_info(notification)") as cursor:
            columns = {row[1] async for row in cursor}

        if 'force_everyone' not in columns:
            await db.execute('ALTER TABLE notification ADD COLUMN force_everyone INTEGER DEFAULT 0')
            log.info('added missing notification.force_everyone column')

        async with db.execute("PRAGMA table_info(guild_settings)") as cursor:
            guild_columns = {row[1] async for row in cursor}

        guild_column_definitions = {
            'plan': "TEXT DEFAULT 'free'",
            'default_message_override': 'TEXT DEFAULT NULL',
            'bot_display_name_override': 'TEXT DEFAULT NULL',
            'emoji_auto_format_override': 'INTEGER DEFAULT NULL',
            'embed_type_override': 'TEXT DEFAULT NULL',
            'built_in_fx_image_override': 'INTEGER DEFAULT NULL',
            'built_in_video_link_button_override': 'INTEGER DEFAULT NULL',
            'built_in_legacy_logo_override': 'INTEGER DEFAULT NULL',
            'fx_domain_name_override': 'TEXT DEFAULT NULL',
            'fx_original_url_button_override': 'INTEGER DEFAULT NULL',
        }
        for column_name, definition in guild_column_definitions.items():
            if column_name not in guild_columns:
                await db.execute(f'ALTER TABLE guild_settings ADD COLUMN {column_name} {definition}')
                log.info(f'added missing guild_settings.{column_name} column')

        await db.commit()

    async with aiosqlite.connect(db_path) as db:
        async with db.execute(
            "SELECT value FROM app_meta WHERE key = 'legacy_alert_rules_migrated'"
        ) as cursor:
            rules_row = await cursor.fetchone()

        if rules_row is None:
            migrated_rules = await migrate_legacy_alert_rules_for_existing_guilds(
                db_path,
                trigger_keywords=get_legacy_trigger_keywords(),
                exclude_keywords=get_legacy_exclude_keywords(),
            )
            await db.execute(
                "INSERT OR REPLACE INTO app_meta (key, value) VALUES ('legacy_alert_rules_migrated', '1')"
            )
            await db.commit()
            if migrated_rules:
                log.info(f'migrated legacy keyword rules into alert rules for {migrated_rules} server(s)')

    if db_created:
        log.info('database file not found, a blank database file has been created')

    return db_path


async def init_db():
    await ensure_db_schema()
