from dataclasses import dataclass
from typing import Optional

from src.adapters.twitter_adapter import create_twitter_session
from configs.load_configs import configs
from src.log import setup_logger
from src.repositories.notifier_repository import (
    count_dashboard_sources,
    connect_writable,
    disable_notification,
    ensure_channel,
    get_active_channel_ids_for_server,
    get_active_notifications_for_user,
    get_dashboard_source_message,
    get_channel_ids_for_server,
    get_client_used_for_user,
    get_enabled_notifier_user_id,
    get_enabled_user_client_map,
    get_enabled_usernames_for_channel,
    get_user_by_username,
    insert_user,
    list_dashboard_sources,
    reset_custom_message as reset_notification_custom_message,
    set_custom_message as set_notification_custom_message,
    set_user_enabled,
    update_notification_settings,
    update_user_client,
    upsert_notification,
)
from src.services.guild_settings_service import GuildSettingsService
from src.services.twitter_session_service import TwitterSessionService
from src.settings import get_db_path
from src.utils import get_lock, get_utcnow

log = setup_logger(__name__)
lock = get_lock()


@dataclass(frozen=True)
class AddNotifierRequest:
    username: str
    server_id: str
    channel_id: str
    role_id: str
    enable_type: str
    media_type: str
    account_used: str
    force_everyone: bool


@dataclass(frozen=True)
class AddNotifierResult:
    created_or_reactivated: bool
    task_client_used: Optional[str]
    response_message: str


@dataclass(frozen=True)
class RemoveNotifierRequest:
    username: str
    server_id: str
    channel_id: str
    guild_name: str


@dataclass(frozen=True)
class RemoveNotifierResult:
    removed: bool
    removed_last_notifier: bool
    client_used: Optional[str]
    response_message: str


@dataclass(frozen=True)
class DashboardSourceRecord:
    username: str
    client_used: str
    channel_id: str
    role_id: str
    enable_type: str
    media_type: str
    has_custom_message: bool
    rule_count: int


@dataclass(frozen=True)
class DashboardSourceMessageRecord:
    username: str
    channel_id: str
    customized_msg: Optional[str]


class NotifierServiceError(Exception):
    pass


class UserNotFoundError(NotifierServiceError):
    pass


class AutoChangeClientDisabledError(NotifierServiceError):
    pass


class ChannelNotTrackedError(NotifierServiceError):
    pass


class PlanLimitExceededError(NotifierServiceError):
    pass


class TwitterSessionRequiredError(NotifierServiceError):
    pass


class NotifierService:
    def __init__(self, db_path=None):
        self.db_path = db_path or get_db_path()
        self.guild_settings_service = GuildSettingsService(self.db_path)
        self.twitter_session_service = TwitterSessionService(self.db_path)

    async def add_notifier(self, request: AddNotifierRequest) -> AddNotifierResult:
        valid_session_keys = set(await self.twitter_session_service.list_server_twitter_session_keys(request.server_id))
        if request.account_used not in valid_session_keys:
            raise TwitterSessionRequiredError(
                'Connect a Twitter/X session for this server before adding tracked accounts.'
            )

        async with connect_writable(self.db_path) as db:
            async with db.cursor() as cursor:
                try:
                    match_user = await get_user_by_username(cursor, request.username)
                    existing_notifier_user_id = await get_enabled_notifier_user_id(cursor, request.username, request.channel_id)

                    if existing_notifier_user_id is None:
                        presentation = await self.guild_settings_service.get_presentation_view(request.server_id)
                        source_count = await count_dashboard_sources(self.db_path, request.server_id)
                        if source_count >= presentation.features.max_sources:
                            raise PlanLimitExceededError(
                                f'plan limit reached: {presentation.features.max_sources} tracked sources max for {presentation.plan}'
                            )

                    if match_user is None or match_user['enabled'] == 0:
                        return await self._create_or_reactivate_notifier(db, cursor, match_user, request)

                    async with lock:
                        await db.execute('BEGIN')
                        await ensure_channel(cursor, request.channel_id, request.server_id)
                        await upsert_notification(
                            cursor,
                            match_user['id'],
                            request.channel_id,
                            request.role_id,
                            request.enable_type,
                            request.media_type,
                            request.force_everyone,
                        )
                        await db.commit()
                except NotifierServiceError:
                    await db.rollback()
                    raise
                except Exception as e:
                    await db.rollback()
                    log.error(f'an error occurred while adding notifier: {e}')
                    raise NotifierServiceError from e

        return AddNotifierResult(
            created_or_reactivated=False,
            task_client_used=None,
            response_message=(
                f'{request.username} already exists under {match_user["client_used"]}. '
                'Using the same account to deliver notifications'
            ),
        )

    async def remove_notifier(self, request: RemoveNotifierRequest) -> RemoveNotifierResult:
        async with connect_writable(self.db_path) as db:
            async with db.cursor() as cursor:
                try:
                    valid_ids = await get_channel_ids_for_server(cursor, request.server_id)
                    if request.channel_id not in valid_ids:
                        raise ChannelNotTrackedError(
                            f'can\'t find channel <#{request.channel_id}> in {request.guild_name}!'
                        )

                    user_id = await get_enabled_notifier_user_id(cursor, request.username, request.channel_id)
                    match_notifier = {'user_id': user_id} if user_id is not None else None
                    if match_notifier is None:
                        return RemoveNotifierResult(
                            removed=False,
                            removed_last_notifier=False,
                            client_used=None,
                            response_message=f"can't find notifier {request.username} in <#{request.channel_id}>!",
                        )

                    async with lock:
                        await db.execute('BEGIN')
                        await disable_notification(cursor, match_notifier['user_id'], request.channel_id)
                        active_notifiers = await get_active_notifications_for_user(cursor, match_notifier['user_id'])
                        if not active_notifiers:
                            await set_user_enabled(cursor, match_notifier['user_id'], False)
                        await db.commit()

                    client_used = None
                    if not active_notifiers:
                        client_used = await get_client_used_for_user(cursor, match_notifier['user_id'])
                except NotifierServiceError:
                    await db.rollback()
                    raise
                except Exception as e:
                    await db.rollback()
                    log.error(f'an error occurred while removing notifier: {e}')
                    raise NotifierServiceError from e

        return RemoveNotifierResult(
            removed=True,
            removed_last_notifier=not active_notifiers,
            client_used=client_used,
            response_message=f'successfully remove notifier of {request.username}!',
        )

    async def get_enabled_notifier_user_id(self, username: str, channel_id: str) -> Optional[str]:
        async with connect_writable(self.db_path) as db:
            async with db.cursor() as cursor:
                return await get_enabled_notifier_user_id(cursor, username, channel_id)

    async def reset_custom_message(self, user_id: str, channel_id: str) -> None:
        async with connect_writable(self.db_path) as db:
            async with db.cursor() as cursor:
                async with lock:
                    await reset_notification_custom_message(cursor, user_id, channel_id)
                    await db.commit()

    async def get_dashboard_source_message(self, username: str, channel_id: str) -> Optional[DashboardSourceMessageRecord]:
        customized_msg = await get_dashboard_source_message(self.db_path, username, channel_id)
        if customized_msg is None:
            return None
        return DashboardSourceMessageRecord(
            username=username,
            channel_id=channel_id,
            customized_msg=customized_msg,
        )

    async def set_dashboard_source_message(self, server_id: str, username: str, channel_id: str, customized_msg: str) -> bool:
        presentation = await self.guild_settings_service.get_presentation_view(server_id)
        if not presentation.features.can_customize_source_messages:
            raise ValueError('custom account messages require the Pro plan')
        async with connect_writable(self.db_path) as db:
            async with db.cursor() as cursor:
                user_id = await get_enabled_notifier_user_id(cursor, username, channel_id)
                if user_id is None:
                    return False
                async with lock:
                    await set_notification_custom_message(cursor, user_id, channel_id, customized_msg)
                    await db.commit()
        return True

    async def reset_dashboard_source_message(self, server_id: str, username: str, channel_id: str) -> bool:
        presentation = await self.guild_settings_service.get_presentation_view(server_id)
        if not presentation.features.can_customize_source_messages:
            raise ValueError('custom account messages require the Pro plan')
        async with connect_writable(self.db_path) as db:
            async with db.cursor() as cursor:
                user_id = await get_enabled_notifier_user_id(cursor, username, channel_id)
                if user_id is None:
                    return False
                async with lock:
                    await reset_notification_custom_message(cursor, user_id, channel_id)
                    await db.commit()
        return True

    async def disable_remote_notification(self, username: str, client_used: str) -> None:
        app = create_twitter_session(client_used)
        await app.connect()
        target_user = await app.get_user_info(username)

        if configs['auto_unfollow']:
            status = await app.unfollow_user(target_user)
            log.info(f'successfully unfollowed {username}') if status else log.warning(f'unable to unfollow {username}')
        else:
            status = await app.disable_user_notification(target_user)
            log.info(f'successfully turned off notification for {username}') if status else log.warning(f'unable to turn off notifications for {username}')

    async def get_active_channel_ids_for_server(self, server_id: str) -> list[str]:
        return await get_active_channel_ids_for_server(self.db_path, server_id)

    async def get_enabled_usernames_for_channel(self, channel_id: str) -> list[str]:
        return await get_enabled_usernames_for_channel(self.db_path, channel_id)

    async def get_enabled_user_client_map(self) -> dict[str, str]:
        return await get_enabled_user_client_map(self.db_path)

    async def list_dashboard_sources(self, server_id: str) -> list[DashboardSourceRecord]:
        rows = await list_dashboard_sources(self.db_path, server_id)
        return [
            DashboardSourceRecord(
                username=row['username'],
                client_used=row['client_used'],
                channel_id=row['channel_id'],
                role_id=row['role_id'] or '',
                enable_type=row['enable_type'],
                media_type=row['enable_media_type'],
                has_custom_message=bool(row['customized_msg']),
                rule_count=int(row['rule_count'] or 0),
            )
            for row in rows
        ]

    async def update_dashboard_source(
        self,
        username: str,
        channel_id: str,
        role_id: str,
        enable_type: str,
        media_type: str,
    ) -> bool:
        return await update_notification_settings(
            self.db_path,
            username=username,
            channel_id=channel_id,
            role_id=role_id,
            enable_type=enable_type,
            media_type=media_type,
        )

    async def _create_or_reactivate_notifier(self, db, cursor, match_user, request: AddNotifierRequest) -> AddNotifierResult:
        app = create_twitter_session(request.account_used)
        await app.connect()
        try:
            target_user = await app.get_user_info(request.username)
        except Exception as e:
            raise UserNotFoundError from e

        if match_user is None:
            async with lock:
                await db.execute('BEGIN')
                await insert_user(cursor, str(target_user.id), request.username, get_utcnow(), request.account_used)
                await ensure_channel(cursor, request.channel_id, request.server_id)
                await upsert_notification(
                    cursor,
                    str(target_user.id),
                    request.channel_id,
                    request.role_id,
                    request.enable_type,
                    request.media_type,
                    request.force_everyone,
                )
                await db.commit()
        else:
            is_changed_client = await self._handle_existing_user_client(match_user, request)

            async with lock:
                await db.execute('BEGIN')
                if is_changed_client:
                    await update_user_client(cursor, match_user['id'], request.account_used)
                await ensure_channel(cursor, request.channel_id, request.server_id)
                await upsert_notification(
                    cursor,
                    match_user['id'],
                    request.channel_id,
                    request.role_id,
                    request.enable_type,
                    request.media_type,
                    request.force_everyone,
                )
                await set_user_enabled(cursor, match_user['id'], True)
                await db.commit()

        await app.follow_user(target_user)
        status = await app.enable_user_notification(target_user)
        if status:
            log.info(f'successfully turned on notification for {request.username}')
        else:
            log.warning(f'unable to turn on notification for {request.username}')

        return AddNotifierResult(
            created_or_reactivated=True,
            task_client_used=request.account_used,
            response_message=f'successfully add notifier of {request.username} under {request.account_used}!',
        )

    async def _handle_existing_user_client(self, match_user, request: AddNotifierRequest) -> bool:
        if match_user['client_used'] == request.account_used:
            return False

        if not configs['auto_change_client']:
            raise AutoChangeClientDisabledError

        if configs['auto_unfollow'] or configs['auto_turn_off_notification']:
            old_client_used = match_user['client_used']
            old_app = create_twitter_session(old_client_used)
            await old_app.connect()
            target_user = await old_app.get_user_info(request.username)

            if configs['auto_unfollow']:
                status = await old_app.unfollow_user(target_user)
                log.info(f'successfully unfollowed {request.username} (due to client change)') if status else log.warning(f'unable to unfollow {request.username}')
            else:
                status = await old_app.disable_user_notification(target_user)
                log.info(f'successfully turned off notification for {request.username} (due to client change)') if status else log.warning(f'unable to turn off notifications for {request.username}')

        return True
