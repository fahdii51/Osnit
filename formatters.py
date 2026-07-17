"""Telegram message formatters for Instagram profile data."""

from typing import Any


def _escape_md(text: str) -> str:
    """Escape MarkdownV2 special characters."""
    special = r"_*[]()~`>#+-=|{}.!\\"
    result = []
    for ch in str(text):
        if ch in special:
            result.append(f"\\{ch}")
        else:
            result.append(ch)
    return "".join(result)


def _fmt(label: str, value: Any, bold_label: bool = True) -> str | None:
    """Format a single field line. Returns None if value is empty."""
    if value is None or value == "" or value == []:
        return None
    val_str = _escape_md(str(value))
    if bold_label:
        return f"*{_escape_md(label)}:* {val_str}"
    return f"{_escape_md(label)}: {val_str}"


def format_profile_info(info: dict, about: dict | None = None) -> str:
    """Format profile info as MarkdownV2 for Telegram.

    Args:
        info: User info dict from HikerAPI.
        about: Optional "about this account" data (country, date_joined, former_usernames).

    Returns:
        Formatted MarkdownV2 string.
    """
    lines: list[str] = []

    username = info.get("username", "unknown")
    full_name = info.get("full_name", "")

    lines.append(f"*Instagram Profile:* @{_escape_md(username)}")

    if full_name:
        lines.append(f"*Name:* {_escape_md(full_name)}")

    pk = info.get("pk") or info.get("pk_id")
    if pk:
        lines.append(f"*PK:* `{_escape_md(str(pk))}`")

    # About data
    if about:
        country = about.get("country")
        if country:
            lines.append(f"*Country:* {_escape_md(country)}")

        date_joined = about.get("date_joined") or about.get("date_joined_as_timestamp")
        if date_joined:
            lines.append(f"*Joined:* {_escape_md(str(date_joined))}")

        former_info = about.get("former_username_info")
        former = about.get("former_usernames") or (former_info.get("usernames", []) if isinstance(former_info, dict) else [])
        if former:
            if isinstance(former, list):
                names = ", ".join(
                    _escape_md(u.get("username", str(u)) if isinstance(u, dict) else str(u))
                    for u in former
                )
                lines.append(f"*Former usernames:* {names}")
            else:
                lines.append(f"*Former usernames:* {_escape_md(str(former))}")

    lines.append("")  # blank separator

    # Counts
    followers = info.get("follower_count", info.get("followers"))
    following = info.get("following_count", info.get("following"))
    posts = info.get("media_count", info.get("posts"))

    counts_parts = []
    if followers is not None:
        counts_parts.append(f"*Followers:* {_escape_md(_format_number(followers))}")
    if following is not None:
        counts_parts.append(f"*Following:* {_escape_md(_format_number(following))}")
    if posts is not None:
        counts_parts.append(f"*Posts:* {_escape_md(_format_number(posts))}")

    if counts_parts:
        lines.append(" \\| ".join(counts_parts))

    # Flags
    flags = []
    if info.get("is_verified"):
        flags.append("Verified")
    if info.get("is_private"):
        flags.append("Private")
    if info.get("is_business"):
        flags.append("Business")
    elif info.get("is_professional_account"):
        flags.append("Professional")

    if flags:
        lines.append(f"*Status:* {_escape_md(', '.join(flags))}")

    category = info.get("category_name") or info.get("category")
    if category:
        lines.append(f"*Category:* {_escape_md(category)}")

    lines.append("")  # blank separator

    # Bio
    bio = info.get("biography") or info.get("bio")
    if bio:
        lines.append(f"*Bio:*\n{_escape_md(bio)}")
        lines.append("")

    # Contact info
    email = info.get("public_email") or info.get("email")
    if email:
        lines.append(f"*Email:* {_escape_md(email)}")

    phone = info.get("public_phone_number") or info.get("contact_phone_number") or info.get("phone")
    if phone:
        lines.append(f"*Phone:* {_escape_md(phone)}")

    # External links
    external_url = info.get("external_url")
    if external_url:
        lines.append(f"*Link:* {_escape_md(external_url)}")

    bio_links = info.get("bio_links", [])
    if bio_links and isinstance(bio_links, list):
        for link in bio_links:
            if isinstance(link, dict):
                url = link.get("url", "")
                title = link.get("title", "")
                if url:
                    display = f"{title} - {url}" if title else url
                    lines.append(f"*Bio link:* {_escape_md(display)}")

    # Threads
    has_threads = (
        info.get("is_threads_user")
        or info.get("has_threads_profile")
        or info.get("third_party_downloads_enabled")
    )
    if has_threads:
        lines.append(f"*Threads:* {_escape_md('Yes')}")

    # Facebook
    fb_id = info.get("fbid_v2") or info.get("fbid") or info.get("fb_id")
    if fb_id:
        lines.append(f"*Facebook ID:* `{_escape_md(str(fb_id))}`")

    return "\n".join(lines)


def _format_number(n: int | float | str) -> str:
    """Format a number with commas for readability."""
    try:
        return f"{int(n):,}"
    except (ValueError, TypeError):
        return str(n)
