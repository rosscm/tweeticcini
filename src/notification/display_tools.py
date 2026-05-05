import re

import aiohttp
import discord
from bs4 import BeautifulSoup
from tweety.types import Tweet

async def gen_embed(
    tweet: Tweet,
    use_fx_image: bool,
    use_legacy_logo: bool,
) -> list[discord.Embed]:
    author = tweet.author
    embed = discord.Embed(title=f'{author.name} {get_action(tweet, disable_quoted=True)} {get_tweet_type(tweet)}', description=tweet.text, url=tweet.url, color=0x1da0f2, timestamp=tweet.created_on)
    embed.set_author(name=f'{author.name} (@{author.username})', icon_url=author.profile_image_url_https, url=f'https://twitter.com/{author.username}')
    embed.set_thumbnail(url=re.sub(r'normal(?=\.jpg$)', '400x400', tweet.author.profile_image_url_https))
    footer_label = 'Twitter' if use_legacy_logo else 'X'
    embed.set_footer(text=footer_label, icon_url='attachment://footer.png')
    if len(tweet.media) == 1:
        embed.set_image(url=tweet.media[0].media_url_https)
        return [embed]
    elif len(tweet.media) > 1:
        if use_fx_image:
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.get(re.sub(r'twitter', r'fxtwitter', tweet.url)) as response:
                        raw = await response.text()
                image_meta = BeautifulSoup(raw, 'html.parser').find('meta', property='og:image')
                if image_meta and image_meta.get('content'):
                    embed.set_image(url=image_meta['content'])
                    return [embed]
            except Exception:
                pass

            embed.set_image(url=tweet.media[0].media_url_https)
            return [embed]
        else:
            imgs_embed = [discord.Embed(url=tweet.url).set_image(url=media.media_url_https) for media in tweet.media]
            imgs_embed.insert(0, embed)
            return imgs_embed
    return [embed]


def get_action(tweet: Tweet, disable_quoted: bool = False) -> str:
    if tweet.is_retweet:
        return 'retweeted'
    elif tweet.is_quoted and not disable_quoted:
        return 'quoted'
    else:
        return 'tweeted'


def get_tweet_type(tweet: Tweet) -> str:
    media = tweet.media
    if len(media) > 1:
        return f'{len(media)} photos'
    elif len(media) == 1:
        return f'a {media[0].type}'
    else:
        return 'a status'
