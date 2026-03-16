import asyncio

from src.db_function.guild_settings import get_legacy_exclude_keywords, get_legacy_trigger_keywords
from src.repositories.alert_rule_repository import migrate_legacy_alert_rules_for_existing_guilds
from src.settings import get_db_path


async def main() -> None:
    changed = await migrate_legacy_alert_rules_for_existing_guilds(
        get_db_path(),
        trigger_keywords=get_legacy_trigger_keywords(),
        exclude_keywords=get_legacy_exclude_keywords(),
    )
    print(f'imported legacy alert rules for {changed} guild rule set(s)')


if __name__ == '__main__':
    asyncio.run(main())
