"""Instagram OSINT Telegram Bot powered by HikerAPI."""

from __future__ import annotations

import asyncio
import json
import logging
import random
import re
import sys
from collections import Counter
from typing import Any

from aiogram import Bot, Dispatcher, Router, F
from aiogram.enums import ChatAction, ParseMode
from aiogram.types import (
    BufferedInputFile,
    InputMediaPhoto,
    InputMediaVideo,
    Message,
)
from hikerapi import AsyncClient

from config import BOT_TOKEN, HIKERAPI_TOKEN
from formatters import format_profile_info
from helpers import (
    extract_list,
    extract_cursor,
    extract_profile_pic,
    download_resource,
    download_resources,
)

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Bot setup
# ---------------------------------------------------------------------------
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()
router = Router()
dp.include_router(router)

hk = AsyncClient(token=HIKERAPI_TOKEN, timeout=30)

# In-memory target storage: user_id -> username
targets: dict[int, str] = {}

PROMO_MESSAGES = [
    "\u26a1 <a href='https://hikerapi.com/p/hsazcgym'>HikerAPI</a> \u2014 Fast Instagram API for developers",
    "\u26a1 <a href='https://lamatok.com/p/s6kl8mtn'>Lamatok</a> \u2014 Fast TikTok API for developers",
    "\u26a1 <a href='https://datalikers.com/p/1by27bwg'>Datalikers</a> \u2014 Instagram & TikTok data: datasets, MCP, low-cost API",
]

INSTO_PROMO = "\u2728 Prefer a CLI? <a href='https://github.com/subzeroid/insto'>insto</a> \u2014 same OSINT commands in your terminal"


async def send_promo(message: Message) -> None:
    text = random.choice(PROMO_MESSAGES)
    if random.random() < 0.2:
        text += f"\n{INSTO_PROMO}"
    await message.answer(
        text,
        parse_mode=ParseMode.HTML,
        disable_web_page_preview=True,
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _sanitize(s: str) -> str:
    """Remove surrogate characters that break urllib/aiohttp."""
    return s.encode("utf-8", errors="ignore").decode("utf-8")


def resolve_username(message: Message) -> str | None:
    text = message.text or ""
    parts = text.strip().split(maxsplit=1)
    if len(parts) > 1:
        return _sanitize(parts[1].lstrip("@").strip())
    return targets.get(message.from_user.id)


async def send_no_target(message: Message) -> None:
    await message.answer(
        "No target set\\. Use `/target username` or pass a username as argument\\.",
        parse_mode=ParseMode.MARKDOWN_V2,
    )


async def handle_api_error(message: Message, e: Exception, username: str) -> None:
    msg = str(e).lower()
    if "not found" in msg or "404" in msg:
        await message.answer(f"User not found: @{username}")
    elif "403" in msg or "private" in msg:
        await message.answer(f"This account is private: @{username}")
    else:
        logger.exception("API error for @%s: %s", username, e)
        await message.answer("Failed to fetch data, try again later.")


async def get_user_info(username: str) -> tuple[dict, str | int | None]:
    """Fetch user info, return (info_dict, pk)."""
    result = await hk.user_by_username_v2(username)
    info = result.get("user", result) if isinstance(result, dict) else result
    pk = info.get("pk") or info.get("pk_id") or info.get("id") if isinstance(info, dict) else None
    return info, pk


import functools


def with_username(func):
    """Decorator: resolve username, show typing, fetch user info, handle errors."""
    @functools.wraps(func)
    async def wrapper(message: Message) -> None:
        username = resolve_username(message)
        if not username:
            return await send_no_target(message)
        await bot.send_chat_action(message.chat.id, ChatAction.TYPING)
        try:
            info, pk = await get_user_info(username)
            await func(message, username, info, pk)
            await send_promo(message)
        except Exception as e:
            await handle_api_error(message, e, username)
    return wrapper


def with_pk(func):
    """Decorator: like with_username but also requires pk."""
    @functools.wraps(func)
    async def wrapper(message: Message) -> None:
        username = resolve_username(message)
        if not username:
            return await send_no_target(message)
        await bot.send_chat_action(message.chat.id, ChatAction.TYPING)
        try:
            info, pk = await get_user_info(username)
            if not pk:
                await message.answer(f"Could not resolve PK for @{username}.")
                return
            await func(message, username, info, str(pk))
            await send_promo(message)
        except Exception as e:
            await handle_api_error(message, e, username)
    return wrapper


async def send_media_group(
    message: Message, media_list: list[dict], caption: str, username: str,
) -> None:
    if not media_list:
        await message.answer(f"No media found for @{username}.")
        return

    wait_msg = await message.answer(f"Downloading {len(media_list)} item(s)...")
    downloaded = await download_resources(media_list, HIKERAPI_TOKEN)

    if not downloaded:
        await wait_msg.delete()
        await message.answer(f"Could not download any media for @{username}.")
        return

    for idx in range(0, len(downloaded), 10):
        group = downloaded[idx : idx + 10]
        media_group = []
        for pk, url, content, content_type in group:
            size_mb = len(content) / (1024 * 1024)
            try:
                if "video" in content_type:
                    if size_mb > 50:
                        await message.answer(f"Video too large ({size_mb:.1f}MB):\n{url}")
                        continue
                    media_group.append(InputMediaVideo(media=BufferedInputFile(content, filename=f"{pk}.mp4")))
                else:
                    if size_mb > 10:
                        await message.answer(f"Image too large ({size_mb:.1f}MB):\n{url}")
                        continue
                    media_group.append(InputMediaPhoto(media=BufferedInputFile(content, filename=f"{pk}.jpg")))
            except Exception as exc:
                logger.warning("Error preparing media %s: %s", pk, exc)

        if not media_group:
            continue
        if idx == 0 and media_group:
            media_group[0].caption = caption

        try:
            await message.answer_media_group(media=media_group)
        except Exception as exc:
            if "too large" in str(exc).lower():
                urls_text = "\n".join(item[1] for item in group)
                await message.answer(f"Media too large for Telegram:\n{urls_text}")
            else:
                logger.exception("Failed to send media group: %s", exc)

    try:
        await wait_msg.delete()
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Command handlers
# ---------------------------------------------------------------------------

@router.message(F.text.startswith("/start"))
async def cmd_start(message: Message) -> None:
    text = (
        "\U0001f50d <b>Welcome to Instagram OSINT Bot!</b>\n\n"
        "Gather intelligence on any public Instagram account.\n\n"
        "Use <code>/target username</code> to set a target, then run any command.\n"
        "Or pass a username directly: <code>/info username</code>\n\n"
        "Type /help to see all available commands."
    )
    await message.answer(text, parse_mode=ParseMode.HTML)


@router.message(F.text.startswith("/help"))
async def cmd_help(message: Message) -> None:
    text = (
        "<b>Available Commands:</b>\n\n"
        "\U0001f3af <b>Target</b>\n"
        "<code>/target username</code> - Set current target\n\n"
        "\U0001f4ca <b>Profile Intel</b>\n"
        "<code>/info</code> - Full profile info + about data\n"
        "<code>/propic</code> - Download HD profile picture\n"
        "<code>/email</code> - Extract public email\n"
        "<code>/phone</code> - Extract public phone\n"
        "<code>/export</code> - Export profile data as JSON\n\n"
        "\U0001f4f8 <b>Media</b>\n"
        "<code>/stories</code> - Download current stories\n"
        "<code>/highlights</code> - List highlight reels\n"
        "<code>/posts</code> - Download recent posts (up to 12)\n"
        "<code>/reels</code> - Download recent reels (up to 10)\n"
        "<code>/tagged</code> - Download tagged posts (up to 10)\n\n"
        "\U0001f465 <b>Network</b>\n"
        "<code>/followers</code> - List followers (first 50)\n"
        "<code>/followings</code> - List following (first 50)\n"
        "<code>/mutuals</code> - Find mutual followers\n"
        "<code>/similar</code> - Find similar accounts\n\n"
        "\U0001f4cd <b>Content Analysis</b>\n"
        "<code>/locations</code> - Extract locations from posts\n"
        "<code>/hashtags</code> - Extract hashtags from posts\n"
        "<code>/mentions</code> - Extract mentions from posts\n\n"
        "<i>All commands accept an optional username argument.\n"
        "If omitted, the current /target is used.</i>"
    )
    await message.answer(text, parse_mode=ParseMode.HTML)


@router.message(F.text.startswith("/target"))
async def cmd_target(message: Message) -> None:
    text = (message.text or "").strip()
    parts = text.split(maxsplit=1)
    if len(parts) < 2:
        current = targets.get(message.from_user.id)
        if current:
            await message.answer(f"Current target: @{current}\nUse /target username to change.")
        else:
            await message.answer("Usage: /target username")
        return
    username = parts[1].lstrip("@").strip()
    targets[message.from_user.id] = username
    await message.answer(f"Target set: @{username}")


@router.message(F.text.startswith("/info"))
async def cmd_info(message: Message) -> None:
    username = resolve_username(message)
    if not username:
        return await send_no_target(message)
    await bot.send_chat_action(message.chat.id, ChatAction.TYPING)
    try:
        info, pk = await get_user_info(username)
        about: dict = {}
        if pk:
            try:
                about = await hk.user_about_v1(str(pk))
                if not isinstance(about, dict):
                    about = {}
            except Exception:
                pass
        text = format_profile_info(info, about)
        await message.answer(text, parse_mode=ParseMode.MARKDOWN_V2)
        await send_promo(message)
    except Exception as e:
        await handle_api_error(message, e, username)


@router.message(F.text.startswith("/propic"))
async def cmd_propic(message: Message) -> None:
    username = resolve_username(message)
    if not username:
        return await send_no_target(message)
    await bot.send_chat_action(message.chat.id, ChatAction.TYPING)
    try:
        info, _ = await get_user_info(username)
        pic_url = extract_profile_pic(info)
        if not pic_url:
            await message.answer(f"No profile picture found for @{username}.")
            return
        content = await download_resource(pic_url, hk)
        photo = BufferedInputFile(content, filename=f"{username}_propic.jpg")
        await message.answer_photo(photo=photo, caption=f"Profile picture: @{username}")
        await send_promo(message)
    except Exception as e:
        await handle_api_error(message, e, username)


@router.message(F.text.startswith("/stories"))
async def cmd_stories(message: Message) -> None:
    username = resolve_username(message)
    if not username:
        return await send_no_target(message)
    await bot.send_chat_action(message.chat.id, ChatAction.TYPING)
    try:
        info, pk = await get_user_info(username)
        if not pk:
            await message.answer(f"Could not resolve PK for @{username}.")
            return
        result = await hk.user_stories_v2(str(pk))
        stories = extract_list(result, ("items",), ("reel", "items"))
        if not stories:
            await message.answer(f"No active stories for @{username}.")
            return
        await send_media_group(message, stories, f"Stories: @{username}", username)
        await send_promo(message)
    except Exception as e:
        await handle_api_error(message, e, username)


@router.message(F.text.startswith("/highlights"))
async def cmd_highlights(message: Message) -> None:
    username = resolve_username(message)
    if not username:
        return await send_no_target(message)
    await bot.send_chat_action(message.chat.id, ChatAction.TYPING)
    try:
        info, pk = await get_user_info(username)
        if not pk:
            await message.answer(f"Could not resolve PK for @{username}.")
            return
        result = await hk.user_highlights_v2(str(pk))
        highlights = extract_list(result, ("items",), ("response", "tray"), ("tray",))
        if not highlights:
            await message.answer(f"No highlights found for @{username}.")
            return
        lines = [f"Highlights for @{username}:\n"]
        for i, hl in enumerate(highlights, 1):
            title = hl.get("title", "Untitled")
            count = hl.get("media_count", hl.get("item_count", "?"))
            lines.append(f"{i}. {title} ({count} items)")
        await message.answer("\n".join(lines))
        await send_promo(message)
    except Exception as e:
        await handle_api_error(message, e, username)


@router.message(F.text.startswith("/posts"))
async def cmd_posts(message: Message) -> None:
    username = resolve_username(message)
    if not username:
        return await send_no_target(message)
    await bot.send_chat_action(message.chat.id, ChatAction.TYPING)
    try:
        info, pk = await get_user_info(username)
        if not pk:
            await message.answer(f"Could not resolve PK for @{username}.")
            return
        result = await hk.user_medias_chunk_v1(str(pk))
        if isinstance(result, (tuple, list)) and len(result) == 2 and isinstance(result[0], list):
            posts = result[0]
        elif isinstance(result, list):
            posts = result
        elif isinstance(result, dict):
            posts = extract_list(result, ("items",), ("response", "items"))
        else:
            posts = []
        await send_media_group(message, posts[:12], f"Recent posts: @{username}", username)
        await send_promo(message)
    except Exception as e:
        await handle_api_error(message, e, username)


@router.message(F.text.startswith("/reels"))
async def cmd_reels(message: Message) -> None:
    username = resolve_username(message)
    if not username:
        return await send_no_target(message)
    await bot.send_chat_action(message.chat.id, ChatAction.TYPING)
    try:
        info, pk = await get_user_info(username)
        if not pk:
            await message.answer(f"Could not resolve PK for @{username}.")
            return
        result = await hk.user_clips_chunk_v1(str(pk))
        if isinstance(result, (tuple, list)) and len(result) == 2 and isinstance(result[0], list):
            reels = result[0]
        elif isinstance(result, list):
            reels = result
        elif isinstance(result, dict):
            reels = extract_list(result, ("items",), ("response", "items"))
        else:
            reels = []
        # Unwrap clips
        unwrapped = []
        for item in reels:
            if isinstance(item, dict) and "media" in item and not item.get("media_type"):
                unwrapped.append(item["media"])
            else:
                unwrapped.append(item)
        await send_media_group(message, unwrapped[:10], f"Recent reels: @{username}", username)
        await send_promo(message)
    except Exception as e:
        await handle_api_error(message, e, username)


@router.message(F.text.startswith("/tagged"))
async def cmd_tagged(message: Message) -> None:
    username = resolve_username(message)
    if not username:
        return await send_no_target(message)
    await bot.send_chat_action(message.chat.id, ChatAction.TYPING)
    try:
        info, pk = await get_user_info(username)
        if not pk:
            await message.answer(f"Could not resolve PK for @{username}.")
            return
        result = await hk.user_tag_medias_v2(str(pk))
        tagged = extract_list(result, ("items",), ("response", "items"))
        await send_media_group(message, tagged[:10], f"Tagged posts: @{username}", username)
        await send_promo(message)
    except Exception as e:
        await handle_api_error(message, e, username)


def _format_user_list(title: str, username: str, users: list) -> str:
    lines = [f"{title} @{username} ({len(users)}):\n"]
    for u in users[:50]:
        uname = u.get("username", "?")
        fname = u.get("full_name", "")
        verified = " \u2713" if u.get("is_verified") else ""
        line = f"@{uname}{verified}"
        if fname:
            line += f" ({fname})"
        lines.append(line)
    text = "\n".join(lines)
    if len(text) > 4000:
        text = text[:4000] + "\n..."
    return text


def _extract_users(result) -> list:
    if isinstance(result, list):
        return result
    return extract_list(result, ("users",), ("response", "users"))


def _extract_posts(result) -> list:
    if isinstance(result, (tuple, list)) and len(result) == 2 and isinstance(result[0], list):
        return result[0]
    if isinstance(result, list):
        return result
    if isinstance(result, dict):
        return extract_list(result, ("items",), ("response", "items"))
    return []


def _get_caption_text(post: dict) -> str:
    cap = post.get("caption")
    text = cap.get("text", "") if isinstance(cap, dict) else (cap if isinstance(cap, str) else "")
    return text or post.get("caption_text", "")


async def _get_about(pk) -> dict:
    try:
        about = await hk.user_about_v1(str(pk))
        return about if isinstance(about, dict) else {}
    except Exception:
        return {}


@router.message(F.text.startswith("/info"))
@with_username
async def cmd_info(message: Message, username: str, info: dict, pk) -> None:
    about = await _get_about(pk) if pk else {}
    text = format_profile_info(info, about)
    await message.answer(text, parse_mode=ParseMode.MARKDOWN_V2)


@router.message(F.text.startswith("/propic"))
@with_username
async def cmd_propic(message: Message, username: str, info: dict, pk) -> None:
    pic_url = extract_profile_pic(info)
    if not pic_url:
        await message.answer(f"No profile picture found for @{username}.")
        return
    content = await download_resource(pic_url, hk)
    photo = BufferedInputFile(content, filename=f"{username}_propic.jpg")
    await message.answer_photo(photo=photo, caption=f"Profile picture: @{username}")


@router.message(F.text.startswith("/stories"))
@with_pk
async def cmd_stories(message: Message, username: str, info: dict, pk: str) -> None:
    result = await hk.user_stories_v2(pk)
    stories = extract_list(result, ("items",), ("reel", "items"))
    if not stories:
        await message.answer(f"No active stories for @{username}.")
        return
    await send_media_group(message, stories, f"Stories: @{username}", username)


@router.message(F.text.startswith("/highlights"))
@with_pk
async def cmd_highlights(message: Message, username: str, info: dict, pk: str) -> None:
    result = await hk.user_highlights_v2(pk)
    highlights = extract_list(result, ("items",), ("response", "tray"), ("tray",))
    if not highlights:
        await message.answer(f"No highlights found for @{username}.")
        return
    lines = [f"Highlights for @{username}:\n"]
    for i, hl in enumerate(highlights, 1):
        title = hl.get("title", "Untitled")
        count = hl.get("media_count", hl.get("item_count", "?"))
        lines.append(f"{i}. {title} ({count} items)")
    await message.answer("\n".join(lines))


@router.message(F.text.startswith("/posts"))
@with_pk
async def cmd_posts(message: Message, username: str, info: dict, pk: str) -> None:
    result = await hk.user_medias_chunk_v1(pk)
    posts = _extract_posts(result)
    await send_media_group(message, posts[:12], f"Recent posts: @{username}", username)


@router.message(F.text.startswith("/reels"))
@with_pk
async def cmd_reels(message: Message, username: str, info: dict, pk: str) -> None:
    result = await hk.user_clips_chunk_v1(pk)
    reels = _extract_posts(result)
    unwrapped = []
    for item in reels:
        if isinstance(item, dict) and "media" in item and not item.get("media_type"):
            unwrapped.append(item["media"])
        else:
            unwrapped.append(item)
    await send_media_group(message, unwrapped[:10], f"Recent reels: @{username}", username)


@router.message(F.text.startswith("/tagged"))
@with_pk
async def cmd_tagged(message: Message, username: str, info: dict, pk: str) -> None:
    result = await hk.user_tag_medias_v2(pk)
    tagged = extract_list(result, ("items",), ("response", "items"))
    await send_media_group(message, tagged[:10], f"Tagged posts: @{username}", username)


@router.message(F.text.startswith("/followers"))
@with_pk
async def cmd_followers(message: Message, username: str, info: dict, pk: str) -> None:
    result = await hk.user_followers_v2(pk, amount=50)
    users = _extract_users(result)
    if not users:
        await message.answer(f"No followers data for @{username}.")
        return
    await message.answer(_format_user_list("Followers of", username, users))


@router.message(F.text.startswith("/followings"))
@with_pk
async def cmd_followings(message: Message, username: str, info: dict, pk: str) -> None:
    result = await hk.user_following_v2(pk, amount=50)
    users = _extract_users(result)
    if not users:
        await message.answer(f"No following data for @{username}.")
        return
    await message.answer(_format_user_list("Following by", username, users))


@router.message(F.text.startswith("/mutuals"))
@with_pk
async def cmd_mutuals(message: Message, username: str, info: dict, pk: str) -> None:
    wait_msg = await message.answer("Fetching followers and following...")
    r_followers, r_following = await asyncio.gather(
        hk.user_followers_v2(pk, amount=200),
        hk.user_following_v2(pk, amount=200),
    )
    followers = _extract_users(r_followers)
    following = _extract_users(r_following)
    follower_pks = {u.get("pk") or u.get("id") for u in followers if isinstance(u, dict)}
    following_pks = {u.get("pk") or u.get("id") for u in following if isinstance(u, dict)}
    mutual_pks = follower_pks & following_pks
    mutual_pks.discard(None)
    all_users = {(u.get("pk") or u.get("id")): u for u in followers + following if isinstance(u, dict)}
    try:
        await wait_msg.delete()
    except Exception:
        pass
    if not mutual_pks:
        await message.answer(f"No mutual followers found for @{username}.")
        return
    lines = [f"Mutual followers of @{username} ({len(mutual_pks)}):\n"]
    for mpk in sorted(mutual_pks, key=lambda x: str(x)):
        u = all_users.get(mpk, {})
        uname = u.get("username", "?")
        fname = u.get("full_name", "")
        verified = " \u2713" if u.get("is_verified") else ""
        line = f"@{uname}{verified}"
        if fname:
            line += f" ({fname})"
        lines.append(line)
    text = "\n".join(lines)
    if len(text) > 4000:
        text = text[:4000] + "\n..."
    await message.answer(text)


@router.message(F.text.startswith("/similar"))
@with_pk
async def cmd_similar(message: Message, username: str, info: dict, pk: str) -> None:
    result = await hk.user_suggested_profiles_v2(pk)
    similar = _extract_users(result)
    if not similar:
        await message.answer(f"No similar accounts found for @{username}.")
        return
    lines = [f"Similar accounts to @{username}:\n"]
    for acc in similar[:30]:
        if isinstance(acc, dict):
            node = acc.get("node", acc)
            uname = node.get("username", "?")
            fname = node.get("full_name", "")
            verified = " \u2713" if node.get("is_verified") else ""
            line = f"@{uname}{verified}"
            if fname:
                line += f" ({fname})"
            lines.append(line)
    text = "\n".join(lines)
    if len(text) > 4000:
        text = text[:4000] + "\n..."
    await message.answer(text)


@router.message(F.text.startswith("/email"))
@with_username
async def cmd_email(message: Message, username: str, info: dict, pk) -> None:
    email = info.get("public_email") or info.get("email")
    if email:
        await message.answer(f"Email for @{username}: {email}")
    else:
        await message.answer(f"No public email found for @{username}.")


@router.message(F.text.startswith("/phone"))
@with_username
async def cmd_phone(message: Message, username: str, info: dict, pk) -> None:
    phone = info.get("public_phone_number") or info.get("contact_phone_number") or info.get("phone")
    if phone:
        await message.answer(f"Phone for @{username}: {phone}")
    else:
        await message.answer(f"No public phone found for @{username}.")


@router.message(F.text.startswith("/locations"))
@with_pk
async def cmd_locations(message: Message, username: str, info: dict, pk: str) -> None:
    posts = _extract_posts(await hk.user_medias_chunk_v1(pk))
    seen: set[str] = set()
    locations: list[dict] = []
    for post in posts:
        loc = post.get("location")
        if not isinstance(loc, dict):
            continue
        name = loc.get("name") or loc.get("short_name", "")
        if not name or name in seen:
            continue
        seen.add(name)
        locations.append(loc)
    if not locations:
        await message.answer(f"No locations found in posts by @{username}.")
        return
    lines = [f"Locations from @{username}'s posts ({len(locations)}):\n"]
    for loc in locations:
        name = loc.get("name", "Unknown")
        city = loc.get("city", "")
        lat, lng = loc.get("lat"), loc.get("lng")
        line = f"\U0001f4cd {name}"
        if city:
            line += f" ({city})"
        if lat is not None and lng is not None:
            line += f" [{lat}, {lng}]"
        lines.append(line)
    text = "\n".join(lines)
    if len(text) > 4000:
        text = text[:4000] + "\n..."
    await message.answer(text)


@router.message(F.text.startswith("/hashtags"))
@with_pk
async def cmd_hashtags(message: Message, username: str, info: dict, pk: str) -> None:
    posts = _extract_posts(await hk.user_medias_chunk_v1(pk))
    counter: Counter[str] = Counter()
    for post in posts:
        counter.update(re.findall(r"#(\w+)", _get_caption_text(post)))
    if not counter:
        await message.answer(f"No hashtags found in posts by @{username}.")
        return
    lines = [f"Hashtags from @{username}'s posts ({len(counter)} unique):\n"]
    for tag, count in counter.most_common(50):
        lines.append(f"#{tag} ({count})")
    text = "\n".join(lines)
    if len(text) > 4000:
        text = text[:4000] + "\n..."
    await message.answer(text)


@router.message(F.text.startswith("/mentions"))
@with_pk
async def cmd_mentions(message: Message, username: str, info: dict, pk: str) -> None:
    posts = _extract_posts(await hk.user_medias_chunk_v1(pk))
    counter: Counter[str] = Counter()
    for post in posts:
        counter.update(re.findall(r"@([\w.]+)", _get_caption_text(post)))
        usertags = post.get("usertags", {})
        if isinstance(usertags, dict):
            for tagged_user in usertags.get("in", []):
                if isinstance(tagged_user, dict):
                    tuser = tagged_user.get("user", {})
                    if isinstance(tuser, dict) and tuser.get("username"):
                        counter[tuser["username"]] += 1
    if not counter:
        await message.answer(f"No mentions found in posts by @{username}.")
        return
    lines = [f"Mentions from @{username}'s posts ({len(counter)} unique):\n"]
    for mention, count in counter.most_common(50):
        lines.append(f"@{mention} ({count})")
    text = "\n".join(lines)
    if len(text) > 4000:
        text = text[:4000] + "\n..."
    await message.answer(text)


@router.message(F.text.startswith("/export"))
@with_username
async def cmd_export(message: Message, username: str, info: dict, pk) -> None:
    about = await _get_about(pk) if pk else {}
    export_data = {"username": username, "profile": info, "about": about}
    json_str = json.dumps(export_data, indent=2, ensure_ascii=False, default=str)
    doc = BufferedInputFile(json_str.encode("utf-8"), filename=f"{username}_osint.json")
    await message.answer_document(document=doc, caption=f"OSINT export for @{username}")


# ---------------------------------------------------------------------------
# Error handler
# ---------------------------------------------------------------------------

from aiogram.types import ErrorEvent


@dp.errors()
async def global_error_handler(event: ErrorEvent):
    logger.error("Unhandled error: %s", event.exception, exc_info=True)
    return True  # suppress, keep polling


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

async def main() -> None:
    logger.info("Starting Instagram OSINT bot...")
    try:
        await dp.start_polling(bot)
    finally:
        await hk.aclose()
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
