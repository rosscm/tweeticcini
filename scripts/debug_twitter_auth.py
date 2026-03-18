import argparse
import asyncio
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tweety import Twitter


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description='Debug Tweety Twitter/X auth by printing the raw self-user response.'
    )
    parser.add_argument('--client-name', default='tweeticcini', help='Tweety session/client name')
    parser.add_argument('--auth-token', help='Raw auth_token cookie value to test')
    parser.add_argument('--session-file', help='Path to a Tweety .tw_session file to test')
    return parser


async def _load_session_json(app: Twitter, session_file: Path) -> None:
    data = json.loads(session_file.read_text())
    cookies = data.get('cookies')
    if not isinstance(cookies, dict):
        raise SystemExit(f'{session_file} does not contain a Tweety cookies dict')
    app.request.cookies = cookies


async def _main_async(args: argparse.Namespace) -> None:
    app = Twitter(args.client_name)

    if args.session_file:
        await _load_session_json(app, Path(args.session_file))
    elif args.auth_token:
        app.request.cookies = {'auth_token': args.auth_token}
    else:
        if not app.session.logged_in:
            raise SystemExit('No auth source supplied and no logged-in Tweety session is available.')
        app.request.cookies = app.session.cookies_dict()

    request_data = app.request._builder.get_self_user()
    raw_response = await app.request.__get_response__(True, **request_data)

    print('status:', raw_response.status_code)
    print('url:', str(raw_response.url))
    print('headers:')
    interesting_headers = ['content-type', 'set-cookie', 'x-response-time', 'location']
    for key in interesting_headers:
        if key in raw_response.headers:
            value = raw_response.headers.get(key, '')
            if key == 'set-cookie':
                value = value[:300]
            print(f'  {key}: {value}')
    print()
    print('body preview:')
    body = raw_response.text
    print(body[:4000])


def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()
    asyncio.run(_main_async(args))


if __name__ == '__main__':
    main()
