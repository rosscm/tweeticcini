import os
import secrets
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional
from urllib.parse import urlencode

import aiohttp
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from starlette.middleware.sessions import SessionMiddleware
from starlette.templating import Jinja2Templates

from configs.load_configs import configs
from src.db_function.init_db import ensure_db_schema
from src.services.alert_rule_service import AlertRuleRecord, AlertRuleService
from src.services.guild_settings_service import GuildSettingsService, GuildPresentationView
from src.services.notifier_service import (
    AddNotifierRequest,
    AutoChangeClientDisabledError,
    DashboardSourceRecord,
    NotifierService,
    NotifierServiceError,
    PlanLimitExceededError,
    RemoveNotifierRequest,
    UserNotFoundError,
)
from src.settings import get_accounts


class AlertRuleResponse(BaseModel):
    rule_name: str
    source_username: Optional[str]
    channel_id: Optional[str]
    priority: int
    trigger_keywords: list[str]
    exclude_keywords: list[str]
    escalation_mode: str


class UpsertAlertRuleRequest(BaseModel):
    source_username: Optional[str] = None
    channel_id: Optional[str] = None
    priority: int = 0
    trigger_keywords: list[str] = Field(default_factory=list)
    exclude_keywords: list[str] = Field(default_factory=list)
    escalation_mode: str = 'role_only'


class DashboardSourceResponse(BaseModel):
    username: str
    client_used: str
    channel_id: str
    role_id: str
    enable_type: str
    media_type: str
    enable_type_label: str
    media_type_label: str
    has_custom_message: bool
    rule_count: int


class UpdateDashboardSourceRequest(BaseModel):
    role_id: str = ''
    enable_type: str = '11'
    media_type: str = '11'


class CreateDashboardSourceRequest(BaseModel):
    username: str
    channel_id: str
    role_id: str = ''
    enable_type: str = '11'
    media_type: str = '11'
    account_used: str


class UpdateDashboardSourceMessageRequest(BaseModel):
    customized_msg: str


class UpdateGuildPlanRequest(BaseModel):
    plan: str = 'free'


class UpdateGuildPresentationRequest(BaseModel):
    default_message: str
    emoji_auto_format: bool = True
    embed_type: str = 'built_in'
    built_in_fx_image: bool = True
    built_in_video_link_button: bool = False
    built_in_legacy_logo: bool = False
    fx_domain_name: str = 'fxtwitter'
    fx_original_url_button: bool = False

def _serialize_rule(rule: AlertRuleRecord) -> AlertRuleResponse:
    return AlertRuleResponse(
        rule_name=rule.rule_name,
        source_username=rule.source_username,
        channel_id=rule.channel_id,
        priority=rule.priority,
        trigger_keywords=rule.trigger_keywords,
        exclude_keywords=rule.exclude_keywords,
        escalation_mode=rule.escalation_mode,
    )


def _serialize_source(source: DashboardSourceRecord) -> DashboardSourceResponse:
    enable_type_label = {
        '11': 'All posts',
        '10': 'Tweets + retweets',
        '01': 'Tweets + quotes',
        '00': 'Tweets only',
    }.get(source.enable_type, source.enable_type)
    media_type_label = {
        '11': 'All media states',
        '10': 'No media',
        '01': 'Media only',
    }.get(source.media_type, source.media_type)
    return DashboardSourceResponse(
        username=source.username,
        client_used=source.client_used,
        channel_id=source.channel_id,
        role_id=source.role_id,
        enable_type=source.enable_type,
        media_type=source.media_type,
        enable_type_label=enable_type_label,
        media_type_label=media_type_label,
        has_custom_message=source.has_custom_message,
        rule_count=source.rule_count,
    )


def _serialize_bot_defaults() -> dict[str, object]:
    return {
        'activity_name': configs.get('activity_name', ''),
        'activity_type': configs.get('activity_type', ''),
        'tweets_check_period': configs.get('tweets_check_period'),
        'tweets_updater_retry_delay': configs.get('tweets_updater_retry_delay'),
        'tasks_monitor_check_period': configs.get('tasks_monitor_check_period'),
        'tasks_monitor_log_period': configs.get('tasks_monitor_log_period'),
        'auth_max_attempts': configs.get('auth_max_attempts'),
        'auto_change_client': configs.get('auto_change_client'),
        'auto_turn_off_notification': configs.get('auto_turn_off_notification'),
        'auto_unfollow': configs.get('auto_unfollow'),
        'emoji_auto_format': configs.get('emoji_auto_format'),
        'default_message': configs.get('default_message', '').strip(),
        'embed_type': configs.get('embed', {}).get('type', 'built_in'),
        'built_in_fx_image': configs.get('embed', {}).get('built_in', {}).get('fx_image'),
        'built_in_video_link_button': configs.get('embed', {}).get('built_in', {}).get('video_link_button'),
        'built_in_legacy_logo': configs.get('embed', {}).get('built_in', {}).get('legacy_logo'),
        'fx_domain_name': configs.get('embed', {}).get('fx_twitter', {}).get('domain_name'),
        'fx_original_url_button': configs.get('embed', {}).get('fx_twitter', {}).get('original_url_button'),
    }


def _serialize_guild_presentation(view: GuildPresentationView) -> dict[str, object]:
    return {
        'plan': view.plan,
        'features': {
            'max_sources': view.features.max_sources,
            'max_rules': view.features.max_rules,
            'max_trigger_keywords_total': view.features.max_trigger_keywords_total,
            'max_exclude_keywords_total': view.features.max_exclude_keywords_total,
            'can_customize_presentation': view.features.can_customize_presentation,
        },
        'has_overrides': view.has_overrides,
        'effective': {
            'default_message': view.effective.default_message,
            'emoji_auto_format': view.effective.emoji_auto_format,
            'embed_type': view.effective.embed_type,
            'built_in_fx_image': view.effective.built_in_fx_image,
            'built_in_video_link_button': view.effective.built_in_video_link_button,
            'built_in_legacy_logo': view.effective.built_in_legacy_logo,
            'fx_domain_name': view.effective.fx_domain_name,
            'fx_original_url_button': view.effective.fx_original_url_button,
        },
    }


def _serialize_plan_usage(sources: list[DashboardSourceRecord], rules: list[AlertRuleRecord]) -> dict[str, int]:
    return {
        'source_count': len(sources),
        'rule_count': len(rules),
        'trigger_keyword_count': sum(len(rule.trigger_keywords) for rule in rules),
        'exclude_keyword_count': sum(len(rule.exclude_keywords) for rule in rules),
    }


def _get_discord_oauth_config() -> Optional[dict[str, str]]:
    client_id = os.getenv('DISCORD_CLIENT_ID')
    client_secret = os.getenv('DISCORD_CLIENT_SECRET')
    redirect_uri = os.getenv('DISCORD_REDIRECT_URI')
    if not client_id or not client_secret or not redirect_uri:
        return None
    return {
        'client_id': client_id,
        'client_secret': client_secret,
        'redirect_uri': redirect_uri,
    }


def _build_discord_login_url(state: str) -> Optional[str]:
    oauth = _get_discord_oauth_config()
    if oauth is None:
        return None
    query = urlencode(
        {
            'client_id': oauth['client_id'],
            'redirect_uri': oauth['redirect_uri'],
            'response_type': 'code',
            'scope': 'identify guilds',
            'prompt': 'consent',
            'state': state,
        }
    )
    return f'https://discord.com/api/oauth2/authorize?{query}'


def _get_manageable_guilds(guilds: list[dict[str, object]]) -> list[dict[str, object]]:
    manageable = []
    for guild in guilds:
        permissions = int(str(guild.get('permissions', '0')))
        if permissions & 0x8 or permissions & 0x20:
            manageable.append(guild)
    return sorted(manageable, key=lambda guild: str(guild.get('name', '')).lower())


def _get_session_user(request: Request) -> Optional[dict[str, object]]:
    return request.session.get('discord_user')


def _get_session_guilds(request: Request) -> list[dict[str, object]]:
    guilds = request.session.get('discord_guilds') or []
    if not isinstance(guilds, list):
        return []
    return guilds


def _require_guild_access(request: Request, guild_id: str) -> None:
    oauth = _get_discord_oauth_config()
    if oauth is None:
        return
    user = _get_session_user(request)
    if user is None:
        raise HTTPException(status_code=401, detail='sign in with Discord to access this dashboard')
    guild_ids = {str(guild.get('id')) for guild in _get_session_guilds(request)}
    if guild_id not in guild_ids:
        raise HTTPException(status_code=403, detail='you do not have dashboard access to this server')


async def _fetch_guild_resource_names(guild_id: str) -> dict[str, dict[str, str]]:
    bot_token = os.getenv('BOT_TOKEN')
    if not bot_token:
        return {'channels': {}, 'roles': {}}

    headers = {'Authorization': f'Bot {bot_token}'}
    channels: dict[str, str] = {}
    roles: dict[str, str] = {}

    async with aiohttp.ClientSession(headers=headers) as session:
        try:
            async with session.get(f'https://discord.com/api/v10/guilds/{guild_id}/channels') as response:
                if response.status < 400:
                    channel_rows = await response.json()
                    channels = {
                        str(channel.get('id')): str(channel.get('name'))
                        for channel in channel_rows
                        if channel.get('id') and channel.get('name')
                    }
        except Exception:
            channels = {}

        try:
            async with session.get(f'https://discord.com/api/v10/guilds/{guild_id}/roles') as response:
                if response.status < 400:
                    role_rows = await response.json()
                    roles = {
                        str(role.get('id')): str(role.get('name'))
                        for role in role_rows
                        if role.get('id') and role.get('name')
                    }
        except Exception:
            roles = {}

    return {'channels': channels, 'roles': roles}


@asynccontextmanager
async def lifespan(_app: FastAPI):
    await ensure_db_schema()
    yield


BASE_DIR = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(BASE_DIR / 'templates'))


app = FastAPI(
    title='Tweeticcini Dashboard API',
    version='0.1.0',
    lifespan=lifespan,
)
app.add_middleware(
    SessionMiddleware,
    secret_key=os.getenv('DASHBOARD_SESSION_SECRET', 'tweeticcini-dashboard-dev-secret'),
    same_site='lax',
    https_only=False,
)
app.mount('/dashboard/static', StaticFiles(directory=str(BASE_DIR / 'static')), name='dashboard_static')

alert_rule_service = AlertRuleService()
notifier_service = NotifierService()
guild_settings_service = GuildSettingsService()


@app.get('/', include_in_schema=False)
async def root() -> RedirectResponse:
    return RedirectResponse(url='/dashboard')


@app.get('/dashboard', response_class=HTMLResponse, include_in_schema=False)
async def dashboard_home(request: Request):
    state = secrets.token_urlsafe(24)
    request.session['discord_oauth_state'] = state
    return templates.TemplateResponse(
        request=request,
        name='index.html',
        context={
            'title': 'Tweeticcini Dashboard',
            'oauth_enabled': _get_discord_oauth_config() is not None,
            'discord_login_url': _build_discord_login_url(state),
            'discord_user': _get_session_user(request),
            'manageable_guilds': _get_session_guilds(request),
        },
    )


@app.get('/dashboard/login', include_in_schema=False)
async def dashboard_login(request: Request) -> RedirectResponse:
    state = secrets.token_urlsafe(24)
    request.session['discord_oauth_state'] = state
    login_url = _build_discord_login_url(state)
    if login_url is None:
        raise HTTPException(status_code=503, detail='discord oauth is not configured')
    return RedirectResponse(url=login_url)


@app.get('/dashboard/callback', include_in_schema=False)
async def dashboard_callback(request: Request, code: str, state: str) -> RedirectResponse:
    oauth = _get_discord_oauth_config()
    if oauth is None:
        raise HTTPException(status_code=503, detail='discord oauth is not configured')
    expected_state = request.session.pop('discord_oauth_state', None)
    if not expected_state or state != expected_state:
        raise HTTPException(status_code=400, detail='invalid oauth state')

    async with aiohttp.ClientSession() as session:
        async with session.post(
            'https://discord.com/api/oauth2/token',
            data={
                'client_id': oauth['client_id'],
                'client_secret': oauth['client_secret'],
                'grant_type': 'authorization_code',
                'code': code,
                'redirect_uri': oauth['redirect_uri'],
            },
            headers={'Content-Type': 'application/x-www-form-urlencoded'},
        ) as response:
            token_data = await response.json()
            if response.status >= 400:
                raise HTTPException(status_code=400, detail=f'discord oauth failed: {token_data}')

        headers = {'Authorization': f"Bearer {token_data['access_token']}"}
        async with session.get('https://discord.com/api/users/@me', headers=headers) as response:
            user_data = await response.json()
            if response.status >= 400:
                raise HTTPException(status_code=400, detail=f'failed to fetch discord user: {user_data}')

        async with session.get('https://discord.com/api/users/@me/guilds', headers=headers) as response:
            guilds_data = await response.json()
            if response.status >= 400:
                raise HTTPException(status_code=400, detail=f'failed to fetch discord guilds: {guilds_data}')

    manageable_guilds = _get_manageable_guilds(guilds_data)
    request.session['discord_user'] = {
        'id': user_data.get('id'),
        'username': user_data.get('username'),
        'global_name': user_data.get('global_name'),
    }
    request.session['discord_guilds'] = [
        {
            'id': guild.get('id'),
            'name': guild.get('name'),
            'icon': guild.get('icon'),
            'permissions': guild.get('permissions'),
            'owner': guild.get('owner'),
        }
        for guild in manageable_guilds
    ]
    return RedirectResponse(url='/dashboard')


@app.get('/dashboard/logout', include_in_schema=False)
async def dashboard_logout(request: Request) -> RedirectResponse:
    request.session.clear()
    return RedirectResponse(url='/dashboard')


@app.get('/dashboard/guilds/{guild_id}', response_class=HTMLResponse, include_in_schema=False)
async def dashboard_guild(request: Request, guild_id: str):
    _require_guild_access(request, guild_id)
    rules = await alert_rule_service.list_rules(guild_id)
    sources = await notifier_service.list_dashboard_sources(guild_id)
    guild_presentation = await guild_settings_service.get_presentation_view(guild_id)
    usage = _serialize_plan_usage(sources, rules)
    resource_names = await _fetch_guild_resource_names(guild_id)
    return templates.TemplateResponse(
        request=request,
        name='guild.html',
        context={
            'title': f'Guild {guild_id}',
            'guild_id': guild_id,
            'discord_user': _get_session_user(request),
            'bot_defaults': _serialize_bot_defaults(),
            'guild_presentation': _serialize_guild_presentation(guild_presentation),
            'plan_usage': usage,
            'available_accounts': list(get_accounts().keys()),
            'channel_names': resource_names['channels'],
            'role_names': resource_names['roles'],
            'sources': [_serialize_source(source).model_dump() for source in sources],
            'rules': [_serialize_rule(rule).model_dump() for rule in rules],
        },
    )


@app.get('/health')
async def healthcheck() -> dict[str, str]:
    return {'status': 'ok'}


@app.get('/guilds/{guild_id}/rules', response_model=list[AlertRuleResponse])
async def list_guild_rules(request: Request, guild_id: str) -> list[AlertRuleResponse]:
    _require_guild_access(request, guild_id)
    return [_serialize_rule(rule) for rule in await alert_rule_service.list_rules(guild_id)]


@app.get('/guilds/{guild_id}/sources', response_model=list[DashboardSourceResponse])
async def list_guild_sources(request: Request, guild_id: str) -> list[DashboardSourceResponse]:
    _require_guild_access(request, guild_id)
    return [_serialize_source(source) for source in await notifier_service.list_dashboard_sources(guild_id)]


@app.post('/guilds/{guild_id}/sources', response_model=DashboardSourceResponse)
async def create_guild_source(request: Request, guild_id: str, source_request: CreateDashboardSourceRequest) -> DashboardSourceResponse:
    _require_guild_access(request, guild_id)
    try:
        await notifier_service.add_notifier(
            AddNotifierRequest(
                username=source_request.username,
                server_id=guild_id,
                channel_id=source_request.channel_id,
                role_id=source_request.role_id,
                enable_type=source_request.enable_type,
                media_type=source_request.media_type,
                account_used=source_request.account_used,
                force_everyone=False,
            )
        )
    except UserNotFoundError as error:
        raise HTTPException(status_code=404, detail='twitter/x user not found') from error
    except AutoChangeClientDisabledError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    except PlanLimitExceededError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    except NotifierServiceError as error:
        raise HTTPException(status_code=500, detail='failed to add source') from error

    sources = await notifier_service.list_dashboard_sources(guild_id)
    for source in sources:
        if source.username.lower() == source_request.username.lower() and source.channel_id == source_request.channel_id:
            return _serialize_source(source)
    raise RuntimeError(f'failed to load source {source_request.username} in channel {source_request.channel_id} after create')


@app.get('/guilds/{guild_id}/presentation')
async def get_guild_presentation(request: Request, guild_id: str) -> dict[str, object]:
    _require_guild_access(request, guild_id)
    return _serialize_guild_presentation(await guild_settings_service.get_presentation_view(guild_id))


@app.put('/guilds/{guild_id}/plan')
async def update_guild_plan(request: Request, guild_id: str, plan_request: UpdateGuildPlanRequest) -> dict[str, object]:
    _require_guild_access(request, guild_id)
    return _serialize_guild_presentation(await guild_settings_service.set_plan(guild_id, plan_request.plan))


@app.put('/guilds/{guild_id}/presentation')
async def update_guild_presentation(
    request: Request,
    guild_id: str,
    presentation_request: UpdateGuildPresentationRequest,
) -> dict[str, object]:
    _require_guild_access(request, guild_id)
    try:
        return _serialize_guild_presentation(
            await guild_settings_service.update_presentation(
                server_id=guild_id,
                default_message=presentation_request.default_message,
                emoji_auto_format=presentation_request.emoji_auto_format,
                embed_type=presentation_request.embed_type,
                built_in_fx_image=presentation_request.built_in_fx_image,
                built_in_video_link_button=presentation_request.built_in_video_link_button,
                built_in_legacy_logo=presentation_request.built_in_legacy_logo,
                fx_domain_name=presentation_request.fx_domain_name,
                fx_original_url_button=presentation_request.fx_original_url_button,
            )
        )
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@app.put('/guilds/{guild_id}/sources/{username}/{channel_id}', response_model=DashboardSourceResponse)
async def update_guild_source(
    request: Request,
    guild_id: str,
    username: str,
    channel_id: str,
    source_request: UpdateDashboardSourceRequest,
) -> DashboardSourceResponse:
    _require_guild_access(request, guild_id)
    updated = await notifier_service.update_dashboard_source(
        username=username,
        channel_id=channel_id,
        role_id=source_request.role_id,
        enable_type=source_request.enable_type,
        media_type=source_request.media_type,
    )
    if not updated:
        raise RuntimeError(f'failed to update source {username} in channel {channel_id}')

    sources = await notifier_service.list_dashboard_sources(guild_id)
    for source in sources:
        if source.username == username and source.channel_id == channel_id:
            return _serialize_source(source)
    raise RuntimeError(f'failed to load source {username} in channel {channel_id} after update')


@app.get('/guilds/{guild_id}/sources/{username}/{channel_id}/message')
async def get_guild_source_message(request: Request, guild_id: str, username: str, channel_id: str) -> dict[str, object]:
    _require_guild_access(request, guild_id)
    record = await notifier_service.get_dashboard_source_message(username, channel_id)
    return {
        'guild_id': guild_id,
        'username': username,
        'channel_id': channel_id,
        'customized_msg': None if record is None else record.customized_msg,
    }


@app.put('/guilds/{guild_id}/sources/{username}/{channel_id}/message')
async def update_guild_source_message(
    request: Request,
    guild_id: str,
    username: str,
    channel_id: str,
    message_request: UpdateDashboardSourceMessageRequest,
) -> dict[str, object]:
    _require_guild_access(request, guild_id)
    updated = await notifier_service.set_dashboard_source_message(
        username=username,
        channel_id=channel_id,
        customized_msg=message_request.customized_msg,
    )
    if not updated:
        raise HTTPException(status_code=404, detail='source not found')
    return {
        'guild_id': guild_id,
        'username': username,
        'channel_id': channel_id,
        'customized_msg': message_request.customized_msg,
    }


@app.delete('/guilds/{guild_id}/sources/{username}/{channel_id}/message')
async def delete_guild_source_message(request: Request, guild_id: str, username: str, channel_id: str) -> dict[str, bool]:
    _require_guild_access(request, guild_id)
    reset = await notifier_service.reset_dashboard_source_message(username, channel_id)
    if not reset:
        raise HTTPException(status_code=404, detail='source not found')
    return {'reset': True}


@app.delete('/guilds/{guild_id}/sources/{username}/{channel_id}')
async def delete_guild_source(request: Request, guild_id: str, username: str, channel_id: str) -> dict[str, bool]:
    _require_guild_access(request, guild_id)
    result = await notifier_service.remove_notifier(
        RemoveNotifierRequest(
            username=username,
            server_id=guild_id,
            channel_id=channel_id,
            guild_name=guild_id,
        )
    )
    return {'deleted': result.removed}


@app.put('/guilds/{guild_id}/rules/{rule_name}', response_model=AlertRuleResponse)
async def upsert_guild_rule(request: Request, guild_id: str, rule_name: str, rule_request: UpsertAlertRuleRequest) -> AlertRuleResponse:
    _require_guild_access(request, guild_id)
    try:
        await alert_rule_service.upsert_rule(
            server_id=guild_id,
            rule_name=rule_name,
            source_username=rule_request.source_username,
            channel_id=rule_request.channel_id,
            priority=rule_request.priority,
            trigger_keywords=rule_request.trigger_keywords,
            exclude_keywords=rule_request.exclude_keywords,
            escalation_mode=rule_request.escalation_mode,
        )
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    rules = await alert_rule_service.list_rules(guild_id)
    for rule in rules:
        if rule.rule_name == rule_name:
            return _serialize_rule(rule)
    raise RuntimeError(f'failed to load alert rule {rule_name} after upsert')


@app.delete('/guilds/{guild_id}/rules/{rule_name}')
async def delete_guild_rule(request: Request, guild_id: str, rule_name: str) -> dict[str, bool]:
    _require_guild_access(request, guild_id)
    return {'deleted': await alert_rule_service.delete_rule(guild_id, rule_name)}
