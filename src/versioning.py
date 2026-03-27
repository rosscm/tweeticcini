from pathlib import Path


VERSION_FILE = Path(__file__).resolve().parents[1] / 'VERSION'


def get_app_version() -> str:
    try:
        return VERSION_FILE.read_text(encoding='utf8').strip() or '0.0.0'
    except FileNotFoundError:
        return '0.0.0'
