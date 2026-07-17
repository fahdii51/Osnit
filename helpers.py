"""Helpers for hikerapi AsyncClient responses and CDN downloads."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import httpx

logger = logging.getLogger(__name__)


def extract_list(result: Any, *paths: tuple[str, ...]) -> list:
    """Extract a list from a potentially nested API response."""
    if isinstance(result, list):
        return result
    if not isinstance(result, dict):
        return []

    for path in paths:
        obj = result
        try:
            for key in path:
                obj = obj[key]
            if isinstance(obj, list):
                return obj
        except (KeyError, TypeError, IndexError):
            continue

    if "response" in result and isinstance(result["response"], dict):
        inner = result["response"]
        if isinstance(inner, list):
            return inner
        for path in paths:
            obj = inner
            try:
                for key in path:
                    obj = obj[key]
                if isinstance(obj, list):
                    return obj
            except (KeyError, TypeError, IndexError):
                continue

    return []


def extract_cursor(result: Any) -> str | None:
    """Extract pagination cursor from response."""
    if not isinstance(result, dict):
        return None
    for key in ("next_page_id", "page_id", "next_max_id", "cursor"):
        val = result.get(key)
        if val:
            return str(val)
    resp = result.get("response")
    if isinstance(resp, dict):
        for key in ("next_page_id", "page_id", "next_max_id", "cursor"):
            val = resp.get(key)
            if val:
                return str(val)
    return None


def extract_profile_pic(user_info: dict) -> str | None:
    """Extract best-quality profile picture URL."""
    hd = user_info.get("hd_profile_pic_url_info", {})
    if isinstance(hd, dict) and hd.get("url"):
        return hd["url"]
    for key in ("profile_pic_url_hd", "hd_profile_pic_url", "profile_pic_url"):
        url = user_info.get(key)
        if url:
            return url
    hd_versions = user_info.get("hd_profile_pic_versions")
    if isinstance(hd_versions, list) and hd_versions:
        return hd_versions[-1].get("url")
    return None


# ---------------------------------------------------------------------------
# CDN download helpers
# ---------------------------------------------------------------------------

async def download_resource(url: str, hk_client=None) -> bytes:
    """Download a single resource. Uses hikerapi save_media if client provided."""
    if hk_client:
        return await hk_client.save_media(url)
    # fallback — direct httpx
    async with httpx.AsyncClient(timeout=120, follow_redirects=True) as http:
        resp = await http.get(url)
        resp.raise_for_status()
        return resp.content


async def download_resources(
    media_list: list[dict],
    hk_token: str,
) -> list[tuple[str, str, bytes, str]]:
    """Download media resources. Returns list of (pk, url, bytes, content_type)."""

    async def _fetch_one(
        http: httpx.AsyncClient, url: str, pk: str, content_type: str, attempt: int = 0,
    ) -> tuple[str, str, bytes, str] | None:
        try:
            resp = await http.get(url)
            resp.raise_for_status()
            return (pk, url, resp.content, content_type)
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 403 and attempt < 3:
                fresh_url = await _refresh_media_url(http, pk, hk_token, content_type)
                if fresh_url and fresh_url != url:
                    return await _fetch_one(http, fresh_url, pk, content_type, attempt + 1)
            logger.warning("Failed to download %s (attempt %d): %s", url[:80], attempt, exc)
            return None
        except Exception as exc:
            logger.warning("Download error for %s: %s", url[:80], exc)
            return None

    tasks: list = []
    async with httpx.AsyncClient(timeout=120, follow_redirects=True) as http:
        for media in media_list:
            media_type = media.get("media_type", 1)
            media_pk = str(media.get("pk", media.get("id", "")))

            if media_type == 8:
                resources = media.get("resources", media.get("carousel_media", []))
                for res in resources if isinstance(resources, list) else []:
                    vid = _get_video_url(res)
                    if vid:
                        tasks.append(_fetch_one(http, vid, media_pk, "video/mp4"))
                    else:
                        thumb = _get_thumbnail_url(res)
                        if thumb:
                            tasks.append(_fetch_one(http, thumb, media_pk, "image/jpeg"))
            elif media_type == 2:
                vid = _get_video_url(media)
                if vid:
                    tasks.append(_fetch_one(http, vid, media_pk, "video/mp4"))
            else:
                thumb = _get_thumbnail_url(media)
                if thumb:
                    tasks.append(_fetch_one(http, thumb, media_pk, "image/jpeg"))

        results = await asyncio.gather(*tasks, return_exceptions=True)

    return [r for r in results if isinstance(r, tuple)]


def _get_video_url(media: dict) -> str | None:
    url = media.get("video_url")
    if url:
        return url
    versions = media.get("video_versions")
    if isinstance(versions, list) and versions:
        return versions[0].get("url")
    return None


def _get_thumbnail_url(media: dict) -> str | None:
    url = media.get("thumbnail_url") or media.get("display_url")
    if url:
        return url
    iv2 = media.get("image_versions2")
    candidates = iv2.get("candidates", []) if isinstance(iv2, dict) else []
    if isinstance(candidates, list) and candidates:
        return candidates[0].get("url")
    return media.get("thumbnail_src")


async def _refresh_media_url(
    http: httpx.AsyncClient, media_pk: str, token: str, content_type: str,
) -> str | None:
    try:
        resp = await http.get(
            "https://api.hikerapi.com/v1/media/by/id",
            params={"id": media_pk},
            headers={"x-access-key": token},
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
        media = data if isinstance(data, dict) else {}
        if "response" in media:
            media = media["response"]
        if "video" in content_type:
            return _get_video_url(media)
        return _get_thumbnail_url(media)
    except Exception:
        return None
