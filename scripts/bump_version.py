#!/usr/bin/env python3
import argparse
import re
from pathlib import Path
from typing import Optional


VERSION_FILE = Path(__file__).resolve().parents[1] / 'VERSION'
SEMVER_RE = re.compile(r'^(\d+)\.(\d+)\.(\d+)$')


def parse_version(value: str) -> tuple[int, int, int]:
    match = SEMVER_RE.fullmatch(value.strip())
    if not match:
        raise ValueError(f'invalid semantic version: {value!r}')
    return tuple(int(part) for part in match.groups())


def format_version(parts: tuple[int, int, int]) -> str:
    return f'{parts[0]}.{parts[1]}.{parts[2]}'


def bump_version(current: tuple[int, int, int], part: str) -> tuple[int, int, int]:
    major, minor, patch = current
    if part == 'major':
        return major + 1, 0, 0
    if part == 'minor':
        return major, minor + 1, 0
    return major, minor, patch + 1


def read_current_version() -> str:
    return VERSION_FILE.read_text(encoding='utf8').strip()


def write_version(new_version: str) -> None:
    VERSION_FILE.write_text(f'{new_version}\n', encoding='utf8')


def resolve_next_version(part: str = 'patch', set_version: Optional[str] = None) -> str:
    current = parse_version(read_current_version())
    if set_version:
        return format_version(parse_version(set_version))
    return format_version(bump_version(current, part))


def main() -> int:
    parser = argparse.ArgumentParser(description='Bump the project version in the VERSION file.')
    parser.add_argument('part', nargs='?', choices=('major', 'minor', 'patch'), default='patch')
    parser.add_argument('--set', dest='set_version', help='Set an explicit semantic version like 1.2.3')
    args = parser.parse_args()

    new_version = resolve_next_version(part=args.part, set_version=args.set_version)
    write_version(new_version)
    print(new_version)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
