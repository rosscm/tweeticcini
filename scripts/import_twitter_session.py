import argparse
import asyncio
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.services.twitter_session_service import TwitterSessionService
from src.settings import get_accounts


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description='Import a legacy Twitter/X session into a server-owned Tweeticcini session.'
    )
    parser.add_argument('--server-id', required=True, help='Discord server ID to attach the session to')
    parser.add_argument('--label', required=True, help='Human-readable session label')
    parser.add_argument('--session-file', help='Path to a Tweety .tw_session file to import')
    parser.add_argument('--env-account', help='Legacy TWITTER_TOKEN account alias to import')
    parser.add_argument('--auth-token', help='Raw Twitter/X auth_token to import directly')
    return parser


def _resolve_session_input(args: argparse.Namespace) -> str:
    provided = [bool(args.session_file), bool(args.env_account), bool(args.auth_token)]
    if sum(provided) != 1:
        raise SystemExit('Choose exactly one of --session-file, --env-account, or --auth-token.')

    if args.session_file:
        path = Path(args.session_file)
        if not path.exists():
            raise SystemExit(f'Session file not found: {path}')
        return path.read_text().strip()

    if args.env_account:
        accounts = get_accounts()
        token = accounts.get(args.env_account)
        if not token:
            available = ', '.join(sorted(accounts)) or '(none)'
            raise SystemExit(f'Legacy env account not found: {args.env_account}. Available: {available}')
        return token.strip()

    return args.auth_token.strip()


async def _main_async(args: argparse.Namespace) -> None:
    session_input = _resolve_session_input(args)
    service = TwitterSessionService()
    record = await service.import_session(
        server_id=args.server_id,
        session_name=args.label,
        session_input=session_input,
    )
    print(f'Imported session "{record.session_name}" for server {record.server_id} as {record.client_key}.')
    print('The running bot should pick it up automatically on the next session monitor cycle.')


def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()
    asyncio.run(_main_async(args))


if __name__ == '__main__':
    main()
