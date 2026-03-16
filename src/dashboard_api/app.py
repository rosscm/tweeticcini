from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from starlette.templating import Jinja2Templates

from src.db_function.init_db import ensure_db_schema
from src.services.alert_rule_service import AlertRuleRecord, AlertRuleService
from src.services.guild_settings_service import GuildSettingsService, GuildSettingsView


class GuildSettingsResponse(BaseModel):
    force_everyone_default: bool
    keywords_triggering_everyone: list[str]
    keywords_excluded: list[str]
    source: str


class UpdateGuildSettingsRequest(BaseModel):
    force_everyone_default: bool | None = None
    keywords_triggering_everyone: list[str] | None = None
    keywords_excluded: list[str] | None = None


class AlertRuleResponse(BaseModel):
    rule_name: str
    source_username: str | None
    channel_id: str | None
    priority: int
    trigger_keywords: list[str]
    exclude_keywords: list[str]
    escalation_mode: str


class UpsertAlertRuleRequest(BaseModel):
    source_username: str | None = None
    channel_id: str | None = None
    priority: int = 0
    trigger_keywords: list[str] = Field(default_factory=list)
    exclude_keywords: list[str] = Field(default_factory=list)
    escalation_mode: str = 'inherit'


def _serialize_guild_settings(view: GuildSettingsView) -> GuildSettingsResponse:
    return GuildSettingsResponse(
        force_everyone_default=view.effective.force_everyone_default,
        keywords_triggering_everyone=view.effective.keywords_triggering_everyone,
        keywords_excluded=view.effective.keywords_excluded,
        source='legacy_defaults' if view.uses_legacy_defaults else 'guild_override',
    )


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
app.mount('/dashboard/static', StaticFiles(directory=str(BASE_DIR / 'static')), name='dashboard_static')

guild_settings_service = GuildSettingsService()
alert_rule_service = AlertRuleService()


@app.get('/', include_in_schema=False)
async def root() -> RedirectResponse:
    return RedirectResponse(url='/dashboard')


@app.get('/dashboard', response_class=HTMLResponse, include_in_schema=False)
async def dashboard_home(request: Request):
    return templates.TemplateResponse(
        request=request,
        name='index.html',
        context={
            'title': 'Tweeticcini Dashboard',
        },
    )


@app.get('/dashboard/guilds/{guild_id}', response_class=HTMLResponse, include_in_schema=False)
async def dashboard_guild(request: Request, guild_id: str):
    settings_view = await guild_settings_service.get_settings_view(guild_id)
    rules = await alert_rule_service.list_rules(guild_id)
    return templates.TemplateResponse(
        request=request,
        name='guild.html',
        context={
            'title': f'Guild {guild_id}',
            'guild_id': guild_id,
            'settings': _serialize_guild_settings(settings_view).model_dump(),
            'rules': [_serialize_rule(rule).model_dump() for rule in rules],
        },
    )


@app.get('/health')
async def healthcheck() -> dict[str, str]:
    return {'status': 'ok'}


@app.get('/guilds/{guild_id}/settings', response_model=GuildSettingsResponse)
async def get_guild_settings(guild_id: str) -> GuildSettingsResponse:
    return _serialize_guild_settings(await guild_settings_service.get_settings_view(guild_id))


@app.put('/guilds/{guild_id}/settings', response_model=GuildSettingsResponse)
async def update_guild_settings(guild_id: str, request: UpdateGuildSettingsRequest) -> GuildSettingsResponse:
    kwargs = {}
    if request.force_everyone_default is not None:
        kwargs['force_everyone_default'] = request.force_everyone_default
    if request.keywords_triggering_everyone is not None:
        kwargs['keywords_triggering_everyone'] = request.keywords_triggering_everyone
    if request.keywords_excluded is not None:
        kwargs['keywords_excluded'] = request.keywords_excluded

    if kwargs:
        await guild_settings_service.update_settings(guild_id, **kwargs)
    return _serialize_guild_settings(await guild_settings_service.get_settings_view(guild_id))


@app.post('/guilds/{guild_id}/settings/bootstrap', response_model=GuildSettingsResponse)
async def bootstrap_guild_settings(guild_id: str) -> GuildSettingsResponse:
    await guild_settings_service.bootstrap_from_legacy_defaults(guild_id)
    return _serialize_guild_settings(await guild_settings_service.get_settings_view(guild_id))


@app.delete('/guilds/{guild_id}/settings')
async def reset_guild_settings(guild_id: str) -> dict[str, bool]:
    return {'reset': await guild_settings_service.reset_to_legacy_defaults(guild_id)}


@app.get('/guilds/{guild_id}/rules', response_model=list[AlertRuleResponse])
async def list_guild_rules(guild_id: str) -> list[AlertRuleResponse]:
    return [_serialize_rule(rule) for rule in await alert_rule_service.list_rules(guild_id)]


@app.put('/guilds/{guild_id}/rules/{rule_name}', response_model=AlertRuleResponse)
async def upsert_guild_rule(guild_id: str, rule_name: str, request: UpsertAlertRuleRequest) -> AlertRuleResponse:
    await alert_rule_service.upsert_rule(
        server_id=guild_id,
        rule_name=rule_name,
        source_username=request.source_username,
        channel_id=request.channel_id,
        priority=request.priority,
        trigger_keywords=request.trigger_keywords,
        exclude_keywords=request.exclude_keywords,
        escalation_mode=request.escalation_mode,
    )
    rules = await alert_rule_service.list_rules(guild_id)
    for rule in rules:
        if rule.rule_name == rule_name:
            return _serialize_rule(rule)
    raise RuntimeError(f'failed to load alert rule {rule_name} after upsert')


@app.delete('/guilds/{guild_id}/rules/{rule_name}')
async def delete_guild_rule(guild_id: str, rule_name: str) -> dict[str, bool]:
    return {'deleted': await alert_rule_service.delete_rule(guild_id, rule_name)}
