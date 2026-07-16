import os
from typing import Optional
from urllib.parse import urlparse

def _get_dashboard_base_url() -> Optional[str]:
    explicit_url = os.getenv('DASHBOARD_BASE_URL', '').strip()
    if explicit_url:
        return explicit_url.rstrip('/')

    redirect_uri = os.getenv('DISCORD_REDIRECT_URI', '').strip()
    if not redirect_uri:
        return None

    parsed = urlparse(redirect_uri)
    if not parsed.scheme or not parsed.netloc:
        return None

    return f'{parsed.scheme}://{parsed.netloc}'


def _get_top_gg_vote_url() -> Optional[str]:
    explicit_url = os.getenv('TOP_GG_VOTE_URL', '').strip()
    if explicit_url:
        return explicit_url

    client_id = os.getenv('DISCORD_CLIENT_ID', '').strip()
    if not client_id:
        return None

    return f'https://top.gg/bot/{client_id}/vote'


def _get_buy_me_a_coffee_url() -> Optional[str]:
    explicit_url = os.getenv('BUY_ME_A_COFFEE_URL', '').strip()
    if explicit_url:
        return explicit_url
    return 'https://buymeacoffee.com/pokaccini'
