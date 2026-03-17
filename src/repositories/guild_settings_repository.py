import aiosqlite

from src.db_function.readonly_db import connect_readonly
from src.repositories.notifier_repository import connect_writable


async def get_guild_settings_row(db_path, server_id: str):
    async with connect_readonly(db_path) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            '''
            SELECT
                server_id,
                plan,
                default_message_override,
                bot_display_name_override,
                emoji_auto_format_override,
                embed_type_override,
                built_in_fx_image_override,
                built_in_video_link_button_override,
                built_in_legacy_logo_override,
                fx_domain_name_override,
                fx_original_url_button_override
            FROM guild_settings
            WHERE server_id = ?
            ''',
            (server_id,),
        ) as cursor:
            return await cursor.fetchone()


async def upsert_guild_settings(
    db_path,
    server_id: str,
    plan: str,
    default_message_override,
    bot_display_name_override,
    emoji_auto_format_override,
    embed_type_override,
    built_in_fx_image_override,
    built_in_video_link_button_override,
    built_in_legacy_logo_override,
    fx_domain_name_override,
    fx_original_url_button_override,
) -> None:
    async with connect_writable(db_path) as db:
        await db.execute(
            '''
            INSERT INTO guild_settings (
                server_id,
                plan,
                default_message_override,
                bot_display_name_override,
                emoji_auto_format_override,
                embed_type_override,
                built_in_fx_image_override,
                built_in_video_link_button_override,
                built_in_legacy_logo_override,
                fx_domain_name_override,
                fx_original_url_button_override
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(server_id) DO UPDATE SET
                plan = excluded.plan,
                default_message_override = excluded.default_message_override,
                bot_display_name_override = excluded.bot_display_name_override,
                emoji_auto_format_override = excluded.emoji_auto_format_override,
                embed_type_override = excluded.embed_type_override,
                built_in_fx_image_override = excluded.built_in_fx_image_override,
                built_in_video_link_button_override = excluded.built_in_video_link_button_override,
                built_in_legacy_logo_override = excluded.built_in_legacy_logo_override,
                fx_domain_name_override = excluded.fx_domain_name_override,
                fx_original_url_button_override = excluded.fx_original_url_button_override
            ''',
            (
                server_id,
                plan,
                default_message_override,
                bot_display_name_override,
                emoji_auto_format_override,
                embed_type_override,
                built_in_fx_image_override,
                built_in_video_link_button_override,
                built_in_legacy_logo_override,
                fx_domain_name_override,
                fx_original_url_button_override,
            ),
        )
        await db.commit()
