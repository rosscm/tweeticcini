from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from starlette.templating import Jinja2Templates

from src.db_function.init_db import ensure_db_schema
from src.services.alert_rule_service import AlertRuleRecord, AlertRuleService


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
    escalation_mode: str = 'inherit'

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
    rules = await alert_rule_service.list_rules(guild_id)
    return templates.TemplateResponse(
        request=request,
        name='guild.html',
        context={
            'title': f'Guild {guild_id}',
            'guild_id': guild_id,
            'rules': [_serialize_rule(rule).model_dump() for rule in rules],
        },
    )


@app.get('/health')
async def healthcheck() -> dict[str, str]:
    return {'status': 'ok'}


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
