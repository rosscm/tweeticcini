from dataclasses import dataclass

from configs.load_configs import configs


@dataclass(frozen=True)
class EffectiveGuildPresentationSettings:
    default_message: str
    bot_display_name: str
    emoji_auto_format: bool
    embed_type: str
    built_in_fx_image: bool
    built_in_video_link_button: bool
    built_in_legacy_logo: bool
    fx_domain_name: str
    fx_original_url_button: bool


def _normalize_embed_type(value) -> str:
    return value if value in {'built_in', 'fx_twitter'} else 'built_in'


def _normalize_fx_domain(value) -> str:
    return value if value in {'fxtwitter', 'fixupx'} else 'fxtwitter'


def get_default_guild_presentation_settings() -> EffectiveGuildPresentationSettings:
    embed = configs.get('embed', {})
    built_in = embed.get('built_in', {})
    fx_twitter = embed.get('fx_twitter', {})
    return EffectiveGuildPresentationSettings(
        default_message=configs.get('default_message', '').strip(),
        bot_display_name='',
        emoji_auto_format=bool(configs.get('emoji_auto_format', False)),
        embed_type=_normalize_embed_type(embed.get('type', 'built_in')),
        built_in_fx_image=bool(built_in.get('fx_image', True)),
        built_in_video_link_button=bool(built_in.get('video_link_button', False)),
        built_in_legacy_logo=bool(built_in.get('legacy_logo', False)),
        fx_domain_name=_normalize_fx_domain(fx_twitter.get('domain_name', 'fxtwitter')),
        fx_original_url_button=bool(fx_twitter.get('original_url_button', False)),
    )


def get_legacy_trigger_keywords() -> list[str]:
    values = configs.get('keywords_triggering_everyone') or []
    return [str(value).strip() for value in values if str(value).strip()]


def get_legacy_exclude_keywords() -> list[str]:
    values = configs.get('keywords_excluded') or []
    return [str(value).strip() for value in values if str(value).strip()]
