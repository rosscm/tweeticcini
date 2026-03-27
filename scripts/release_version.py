#!/usr/bin/env python3
import argparse
import subprocess
import sys
from pathlib import Path

from bump_version import resolve_next_version, write_version


REPO_ROOT = Path(__file__).resolve().parents[1]


def run_git(*args: str) -> str:
    result = subprocess.run(
        ['git', *args],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def ensure_clean_version_file() -> None:
    status = run_git('status', '--short', '--', 'VERSION')
    if status:
        raise SystemExit('VERSION has uncommitted changes. Commit or discard them before releasing.')


def main() -> int:
    parser = argparse.ArgumentParser(
        description='Bump VERSION, create a release commit, and tag it.'
    )
    parser.add_argument('part', nargs='?', choices=('major', 'minor', 'patch'), default='patch')
    parser.add_argument('--set', dest='set_version', help='Set an explicit semantic version like 1.2.3')
    parser.add_argument('--message', dest='message', help='Optional custom commit message')
    parser.add_argument('--tag-message', dest='tag_message', help='Optional annotated tag message')
    parser.add_argument(
        '--no-commit',
        action='store_true',
        help='Only update VERSION and print the new version without creating a commit or tag.',
    )
    args = parser.parse_args()

    ensure_clean_version_file()
    new_version = resolve_next_version(part=args.part, set_version=args.set_version)
    write_version(new_version)

    if args.no_commit:
        print(new_version)
        return 0

    tag_name = f'v{new_version}'
    commit_message = args.message or f'Release {tag_name}'
    tag_message = args.tag_message or commit_message

    try:
        run_git('add', 'VERSION')
        run_git('commit', '-m', commit_message)
        run_git('tag', '-a', tag_name, '-m', tag_message)
    except subprocess.CalledProcessError as error:
        sys.stderr.write(error.stderr or error.stdout or str(error))
        raise SystemExit(error.returncode)

    print(new_version)
    print(f'Created commit and tag {tag_name}')
    print('Next: git push origin dev --follow-tags')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
