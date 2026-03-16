import os

import aiosqlite

from src.db_function.guild_settings import get_legacy_alert_settings, get_legacy_exclude_keywords, get_legacy_trigger_keywords
from src.log import setup_logger
from src.repositories.guild_settings_repository import migrate_legacy_guild_settings
from src.repositories.alert_rule_repository import migrate_legacy_alert_rules_for_existing_guilds
from src.settings import DB_FILENAME, get_data_path

log = setup_logger(__name__)


async def ensure_db_schema() -> str:
    data_path = get_data_path()
    if not os.path.exists(data_path):
        os.mkdir(data_path)

    db_path = data_path / DB_FILENAME
    db_created = not os.path.exists(db_path)

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
                force_everyone_default INTEGER DEFAULT NULL,
                keywords_triggering_everyone TEXT DEFAULT NULL,
                keywords_excluded TEXT DEFAULT NULL
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
        """)

        async with db.execute("PRAGMA table_info(notification)") as cursor:
            columns = {row[1] async for row in cursor}

        if 'force_everyone' not in columns:
            await db.execute('ALTER TABLE notification ADD COLUMN force_everyone INTEGER DEFAULT 0')
            log.info('added missing notification.force_everyone column')

        await db.commit()

    async with aiosqlite.connect(db_path) as db:
        async with db.execute(
            "SELECT value FROM app_meta WHERE key = 'legacy_alert_settings_migrated'"
        ) as cursor:
            settings_row = await cursor.fetchone()

        if settings_row is None:
            legacy_settings = get_legacy_alert_settings()
            migrated_servers = await migrate_legacy_guild_settings(
                db_path,
                force_everyone_default=legacy_settings.force_everyone_default,
                keywords_triggering_everyone=[],
                keywords_excluded=[],
            )
            await db.execute(
                "INSERT OR REPLACE INTO app_meta (key, value) VALUES ('legacy_alert_settings_migrated', '1')"
            )
            await db.commit()
            if migrated_servers:
                log.info(f'migrated legacy force_everyone defaults into guild settings for {migrated_servers} server(s)')

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
