import argparse
import json
from pathlib import Path
from typing import Any


REQUIRED_COOKIE_NAMES = (
    'auth_token',
    'ct0',
    'guest_id',
    'guest_id_ads',
    'guest_id_marketing',
    'personalization_id',
    'twid',
)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description='Rebuild a Tweety .tw_session file from a browser cookie export.'
    )
    parser.add_argument('--cookie-export', required=True, help='Path to the Cookie-Editor JSON export')
    parser.add_argument(
        '--session-file',
        default='tweeticcini.tw_session',
        help='Target Tweety session file to update (default: tweeticcini.tw_session)',
    )
    parser.add_argument(
        '--backup',
        action='store_true',
        help='Write a .bak backup of the existing session file before replacing it',
    )
    return parser


def _load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text())
    except json.JSONDecodeError as exc:
        raise SystemExit(f'Invalid JSON in {path}: {exc}') from exc


def _iter_cookie_rows(export_data: Any):
    if isinstance(export_data, list):
        return export_data
    if isinstance(export_data, dict):
        if isinstance(export_data.get('cookies'), list):
            return export_data['cookies']
        if isinstance(export_data.get('data'), list):
            return export_data['data']
    raise SystemExit('Unsupported cookie export format. Expected a Cookie-Editor JSON export.')


def _extract_cookie_map(export_data: Any) -> dict[str, str]:
    cookie_map: dict[str, str] = {}
    for row in _iter_cookie_rows(export_data):
        if not isinstance(row, dict):
            continue
        name = row.get('name')
        value = row.get('value')
        domain = str(row.get('domain', ''))
        if not isinstance(name, str) or value is None:
            continue
        if 'x.com' not in domain and domain not in ('', '.x.com'):
            continue
        if name in REQUIRED_COOKIE_NAMES:
            cookie_map[name] = str(value)
    missing = [name for name in REQUIRED_COOKIE_NAMES if name not in cookie_map]
    if missing:
        raise SystemExit(f'Cookie export is missing required x.com cookie(s): {", ".join(missing)}')
    return cookie_map


def main() -> None:
    args = _build_parser().parse_args()
    cookie_export_path = Path(args.cookie_export)
    session_file_path = Path(args.session_file)

    if not cookie_export_path.exists():
        raise SystemExit(f'Cookie export not found: {cookie_export_path}')
    if not session_file_path.exists():
        raise SystemExit(f'Tweety session file not found: {session_file_path}')

    export_data = _load_json(cookie_export_path)
    session_data = _load_json(session_file_path)

    if not isinstance(session_data, dict) or not isinstance(session_data.get('user'), dict):
        raise SystemExit(f'{session_file_path} does not look like a Tweety session file.')

    cookie_map = _extract_cookie_map(export_data)
    rebuilt = {
        'cookies': cookie_map,
        'user': session_data['user'],
    }

    if args.backup:
        backup_path = session_file_path.with_suffix(session_file_path.suffix + '.bak')
        backup_path.write_text(session_file_path.read_text())
        print(f'Wrote backup to {backup_path}')

    session_file_path.write_text(json.dumps(rebuilt))
    print(f'Rebuilt {session_file_path} with {len(cookie_map)} cookies from {cookie_export_path}.')


if __name__ == '__main__':
    main()
