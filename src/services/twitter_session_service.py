import base64
import hashlib
import json
import os
import re
import secrets
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from src.adapters.twitter_adapter import create_twitter_session
from src.log import setup_logger
from src.repositories.twitter_session_repository import (
    delete_server_twitter_session,
    get_server_twitter_session,
    list_active_server_twitter_sessions,
    list_all_server_twitter_session_keys,
    list_server_twitter_session_keys,
    list_server_twitter_sessions,
    upsert_server_twitter_session,
)
from src.settings import get_db_path, get_twitter_session_path
from src.utils import get_utcnow

log = setup_logger(__name__)


class TwitterSessionServiceError(Exception):
    pass


class TwitterSessionSecretMissingError(TwitterSessionServiceError):
    pass


class TwitterSessionValidationError(TwitterSessionServiceError):
    pass


class TwitterSessionPlanLimitError(TwitterSessionValidationError):
    pass


class TwitterSessionDuplicateNameError(TwitterSessionValidationError):
    pass


@dataclass(frozen=True)
class ServerTwitterSessionRecord:
    server_id: str
    session_name: str
    client_key: str
    status: str
    last_validated_at: Optional[str]
    last_error_at: Optional[str]
    last_error_message: Optional[str]
    created_at: Optional[str]
    updated_at: Optional[str]
    is_active: bool


@dataclass(frozen=True)
class TwitterSessionAuthRecord:
    server_id: str
    session_name: str
    client_key: str
    auth_mode: str
    credential: str


class TwitterSessionService:
    def __init__(self, db_path=None):
        self.db_path = db_path or get_db_path()

    async def list_server_sessions(self, server_id: str) -> list[ServerTwitterSessionRecord]:
        rows = await list_server_twitter_sessions(self.db_path, server_id)
        return [
            ServerTwitterSessionRecord(
                server_id=str(row['server_id']),
                session_name=str(row['session_name']),
                client_key=str(row['client_key']),
                status=str(row['status']),
                last_validated_at=row['last_validated_at'],
                last_error_at=row['last_error_at'],
                last_error_message=row['last_error_message'],
                created_at=row['created_at'],
                updated_at=row['updated_at'],
                is_active=bool(row['is_active']),
            )
            for row in rows
        ]

    async def list_server_delivery_options(self, server_id: str) -> list[dict[str, str]]:
        sessions = await self.list_server_sessions(server_id)
        return [
            {
                'client_key': session.client_key,
                'session_name': session.session_name,
            }
            for session in sessions
            if session.is_active and session.status == 'active'
        ]

    async def list_server_twitter_session_keys(self, server_id: str) -> list[str]:
        return await list_server_twitter_session_keys(self.db_path, server_id)

    async def list_all_server_twitter_session_keys(self) -> list[str]:
        return await list_all_server_twitter_session_keys(self.db_path)

    async def list_all_active_auth_records(self) -> list[TwitterSessionAuthRecord]:
        rows = await list_active_server_twitter_sessions(self.db_path)
        records: list[TwitterSessionAuthRecord] = []
        for row in rows:
            if str(row['status']) != 'active':
                continue
            auth_mode, credential = self._decode_stored_secret(str(row['encrypted_auth_token']))
            records.append(
                TwitterSessionAuthRecord(
                    server_id=str(row['server_id']),
                    session_name=str(row['session_name']),
                    client_key=str(row['client_key']),
                    auth_mode=auth_mode,
                    credential=credential,
                )
            )
        return records

    async def list_all_active_session_records(self) -> list[ServerTwitterSessionRecord]:
        rows = await list_active_server_twitter_sessions(self.db_path)
        return [
            ServerTwitterSessionRecord(
                server_id=str(row['server_id']),
                session_name=str(row['session_name']),
                client_key=str(row['client_key']),
                status=str(row['status']),
                last_validated_at=row['last_validated_at'],
                last_error_at=row['last_error_at'],
                last_error_message=row['last_error_message'],
                created_at=row['created_at'],
                updated_at=row['updated_at'],
                is_active=True,
            )
            for row in rows
        ]

    async def list_all_active_client_keys(self) -> set[str]:
        rows = await list_active_server_twitter_sessions(self.db_path)
        return {str(row['client_key']) for row in rows if bool(row['is_active'])}

    async def server_has_delivery_session(self, server_id: str) -> bool:
        return bool(await list_server_twitter_session_keys(self.db_path, server_id))

    async def connect_session(self, server_id: str, session_name: str, auth_token: str) -> ServerTwitterSessionRecord:
        normalized_name = self._normalize_session_name(session_name)
        normalized_input = auth_token.strip()
        if not normalized_input:
            raise TwitterSessionValidationError('Twitter/X session input is required')
        await self._assert_session_name_available(server_id, normalized_name)
        if await self._would_exceed_session_limit(server_id, normalized_name):
            from src.services.guild_settings_service import GuildSettingsService

            presentation = await GuildSettingsService(self.db_path).get_presentation_view(server_id)
            raise TwitterSessionPlanLimitError(
                f'{presentation.plan.capitalize()} includes {presentation.features.max_twitter_sessions} Twitter/X session'
                f"{'' if presentation.features.max_twitter_sessions == 1 else 's'}. Upgrade to add more."
            )

        client_key = self._build_client_key(server_id, normalized_name)
        await self._assert_client_key_available(server_id, normalized_name, client_key)
        try:
            stored_secret = await self._authorize_and_capture_secret(client_key, normalized_input)
        except Exception as exc:
            log.warning(f'failed to authorize twitter session for server {server_id} ({normalized_name}): {type(exc).__name__}: {exc}')
            raise TwitterSessionValidationError('Unable to authorize this Twitter/X session. Double-check the auth token and try again.') from exc

        existing = await get_server_twitter_session(self.db_path, server_id, normalized_name)
        now = get_utcnow()
        await upsert_server_twitter_session(
            self.db_path,
            server_id=server_id,
            session_name=normalized_name,
            client_key=client_key,
            encrypted_auth_token=self._encrypt_token(stored_secret),
            status='active',
            last_validated_at=now,
            last_error_at=None,
            last_error_message=None,
            created_at=existing['created_at'] if existing is not None else now,
            updated_at=now,
        )
        refreshed = await get_server_twitter_session(self.db_path, server_id, normalized_name)
        return ServerTwitterSessionRecord(
            server_id=str(refreshed['server_id']),
            session_name=str(refreshed['session_name']),
            client_key=str(refreshed['client_key']),
            status=str(refreshed['status']),
            last_validated_at=refreshed['last_validated_at'],
            last_error_at=refreshed['last_error_at'],
            last_error_message=refreshed['last_error_message'],
            created_at=refreshed['created_at'],
            updated_at=refreshed['updated_at'],
            is_active=bool(refreshed['is_active']),
        )

    async def import_session(self, server_id: str, session_name: str, session_input: str) -> ServerTwitterSessionRecord:
        normalized_name = self._normalize_session_name(session_name)
        normalized_input = session_input.strip()
        if not normalized_input:
            raise TwitterSessionValidationError('Twitter/X session input is required')
        await self._assert_session_name_available(server_id, normalized_name)

        client_key = self._build_client_key(server_id, normalized_name)
        await self._assert_client_key_available(server_id, normalized_name, client_key)
        stored_secret = self._normalize_import_secret(normalized_input)
        if stored_secret.startswith('session_json:'):
            _, session_payload = stored_secret.split(':', 1)
            self._write_session_file(client_key, session_payload)

        return await self._upsert_session_record(
            server_id=server_id,
            session_name=normalized_name,
            client_key=client_key,
            stored_secret=stored_secret,
        )

    async def remove_session(self, server_id: str, session_name: str) -> None:
        normalized_name = self._normalize_session_name(session_name)
        client_key = self._build_client_key(server_id, normalized_name)
        await delete_server_twitter_session(self.db_path, server_id, normalized_name)
        session_file = self._session_file_path(client_key)
        if session_file.exists():
            session_file.unlink()

    async def _upsert_session_record(
        self,
        server_id: str,
        session_name: str,
        client_key: str,
        stored_secret: str,
    ) -> ServerTwitterSessionRecord:
        existing = await get_server_twitter_session(self.db_path, server_id, session_name)
        now = get_utcnow()
        await upsert_server_twitter_session(
            self.db_path,
            server_id=server_id,
            session_name=session_name,
            client_key=client_key,
            encrypted_auth_token=self._encrypt_token(stored_secret),
            status='active',
            last_validated_at=now,
            last_error_at=None,
            last_error_message=None,
            created_at=existing['created_at'] if existing is not None else now,
            updated_at=now,
        )
        refreshed = await get_server_twitter_session(self.db_path, server_id, session_name)
        return ServerTwitterSessionRecord(
            server_id=str(refreshed['server_id']),
            session_name=str(refreshed['session_name']),
            client_key=str(refreshed['client_key']),
            status=str(refreshed['status']),
            last_validated_at=refreshed['last_validated_at'],
            last_error_at=refreshed['last_error_at'],
            last_error_message=refreshed['last_error_message'],
            created_at=refreshed['created_at'],
            updated_at=refreshed['updated_at'],
            is_active=bool(refreshed['is_active']),
        )

    def _fernet(self):
        try:
            from cryptography.fernet import Fernet
        except ImportError as exc:
            raise TwitterSessionSecretMissingError(
                'Install the dashboard dependencies before connecting Twitter/X sessions.'
            ) from exc
        secret = os.getenv('TWITTER_SESSION_SECRET') or os.getenv('DASHBOARD_SESSION_SECRET')
        if not secret:
            raise TwitterSessionSecretMissingError(
                'Twitter session storage is not configured. Set TWITTER_SESSION_SECRET or reuse DASHBOARD_SESSION_SECRET.'
            )
        digest = hashlib.sha256(secret.encode('utf-8')).digest()
        return Fernet(base64.urlsafe_b64encode(digest))

    def _encrypt_token(self, auth_token: str) -> str:
        return self._fernet().encrypt(auth_token.encode('utf-8')).decode('utf-8')

    def _decrypt_token(self, encrypted_auth_token: str) -> str:
        try:
            from cryptography.fernet import InvalidToken
        except ImportError as exc:
            raise TwitterSessionSecretMissingError(
                'Install the dashboard dependencies before loading Twitter/X sessions.'
            ) from exc
        try:
            return self._fernet().decrypt(encrypted_auth_token.encode('utf-8')).decode('utf-8')
        except InvalidToken as exc:
            raise TwitterSessionSecretMissingError('Unable to decrypt stored Twitter/X sessions with the current secret.') from exc

    async def _authorize_and_capture_secret(self, client_key: str, credential_input: str) -> str:
        if self._looks_like_session_payload(credential_input):
            session_payload = self._normalize_session_payload(credential_input)
            self._write_session_file(client_key, session_payload)
            app = create_twitter_session(client_key)
            await app.connect()
            return f'session_json:{session_payload}'

        # Bootstrap the cookie into a fresh Tweety session file first, then store
        # the resulting full session JSON for the server-specific client key.
        bootstrap_client_key = self._build_bootstrap_client_key()
        bootstrap_path = self._session_file_path(bootstrap_client_key)
        if bootstrap_path.exists():
            bootstrap_path.unlink()

        try:
            app = create_twitter_session(bootstrap_client_key)
            await app.load_auth_token(credential_input)
            session_payload = self._read_session_file(bootstrap_client_key)
        finally:
            if bootstrap_path.exists():
                bootstrap_path.unlink()
        if session_payload:
            self._write_session_file(client_key, session_payload)
            return f'session_json:{session_payload}'
        return f'auth_token:{credential_input}'

    def _normalize_import_secret(self, credential_input: str) -> str:
        if self._looks_like_session_payload(credential_input):
            session_payload = self._normalize_session_payload(credential_input)
            return f'session_json:{session_payload}'
        return f'auth_token:{credential_input}'

    def _decode_stored_secret(self, encrypted_auth_token: str) -> tuple[str, str]:
        decrypted = self._decrypt_token(encrypted_auth_token)
        if decrypted.startswith('session_json:'):
            return 'session_json', decrypted[len('session_json:'):]
        if decrypted.startswith('auth_token:'):
            return 'auth_token', decrypted[len('auth_token:'):]
        return 'auth_token', decrypted

    @staticmethod
    def _looks_like_session_payload(credential_input: str) -> bool:
        return credential_input.lstrip().startswith('{')

    @staticmethod
    def _normalize_session_payload(session_payload: str) -> str:
        try:
            parsed = json.loads(session_payload)
        except json.JSONDecodeError as exc:
            raise TwitterSessionValidationError('The pasted session data is not valid JSON.') from exc
        if not isinstance(parsed, dict) or 'cookies' not in parsed:
            raise TwitterSessionValidationError('The pasted session data does not look like a Tweety session file.')
        return json.dumps(parsed)

    @staticmethod
    def _session_file_path(client_key: str) -> Path:
        return get_twitter_session_path(client_key)

    def _write_session_file(self, client_key: str, session_payload: str) -> None:
        self._session_file_path(client_key).write_text(session_payload)

    def _read_session_file(self, client_key: str) -> Optional[str]:
        path = self._session_file_path(client_key)
        if not path.exists():
            return None
        return path.read_text()

    @staticmethod
    def _normalize_session_name(session_name: str) -> str:
        cleaned = re.sub(r'\s+', ' ', session_name.strip())
        if not cleaned:
            raise TwitterSessionValidationError('Session name is required')
        return cleaned[:60]

    @staticmethod
    def _build_client_key(server_id: str, session_name: str) -> str:
        slug = re.sub(r'[^a-z0-9]+', '-', session_name.lower()).strip('-') or 'session'
        return f'server-{server_id}-{slug}'

    @staticmethod
    def _build_bootstrap_client_key() -> str:
        return f'tweeticcini-bootstrap-{secrets.token_hex(6)}'

    async def _would_exceed_session_limit(self, server_id: str, session_name: str) -> bool:
        existing = await get_server_twitter_session(self.db_path, server_id, session_name)
        if existing is not None and bool(existing['is_active']):
            return False

        from src.services.guild_settings_service import GuildSettingsService

        presentation = await GuildSettingsService(self.db_path).get_presentation_view(server_id)
        sessions = await self.list_server_sessions(server_id)
        return len(sessions) >= presentation.features.max_twitter_sessions

    async def _assert_session_name_available(self, server_id: str, session_name: str) -> None:
        existing = await get_server_twitter_session(self.db_path, server_id, session_name)
        if existing is not None and bool(existing['is_active']):
            raise TwitterSessionDuplicateNameError(
                'That session label is already in use on this server. Choose a different label instead.'
            )

    async def _assert_client_key_available(self, server_id: str, session_name: str, client_key: str) -> None:
        existing = await get_server_twitter_session(self.db_path, server_id, session_name)
        if existing is not None and str(existing['client_key']) == client_key:
            return
        if client_key in await list_all_server_twitter_session_keys(self.db_path):
            raise TwitterSessionDuplicateNameError(
                'That session label is too similar to an existing one. Choose a more distinct label.'
            )
