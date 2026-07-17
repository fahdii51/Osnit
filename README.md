# Instagram OSINT Telegram Bot

Telegram bot for gathering open-source intelligence on any public Instagram account. Profile data, social graph, media, contact info, content analysis — all in one place.

## Commands

| Command | Description |
|---------|-------------|
| `/target username` | Set current target |
| `/info` | Full profile info + account age, country, former usernames |
| `/propic` | Download HD profile picture |
| `/stories` | Download current stories |
| `/highlights` | List highlight reels |
| `/posts` | Download recent posts (up to 12) |
| `/reels` | Download recent reels (up to 10) |
| `/tagged` | Download tagged posts (up to 10) |
| `/followers` | List followers (first 50) |
| `/followings` | List following (first 50) |
| `/mutuals` | Find mutual followers |
| `/similar` | Find similar/related accounts |
| `/email` | Extract public email |
| `/phone` | Extract public phone |
| `/locations` | Extract locations from posts |
| `/hashtags` | Extract hashtags from posts |
| `/mentions` | Extract mentions from posts |
| `/export` | Export full profile data as JSON |

All commands accept an optional `username` argument. If omitted, the current `/target` is used.

---

## Build Your Own Instagram OSINT Tool

This bot is powered by **[HikerAPI](https://hikerapi.com)** — the most complete Instagram API for OSINT, analytics, and automation.

### Get 100 Free API Requests

**[Sign up with this link](https://hikerapi.com/p/hsazcgym)** and get **100 free requests** — no credit card, no commitment. Enough to prototype your own OSINT tool or research project.

What makes HikerAPI perfect for OSINT:

- **Profile intelligence** — full profile data, account age, country, former usernames
- **Social graph** — followers, following, mutuals, similar accounts
- **Contact extraction** — public emails, phone numbers, linked accounts
- **Content analysis** — locations, hashtags, mentions, tagged users
- **Media access** — stories, highlights, posts, reels in full resolution
- **Production-ready** — 99.9% uptime, no rate limits on paid plans

> **[Start with 100 free requests](https://hikerapi.com/p/hsazcgym)**

---

## Setup

1. Get a Telegram bot token from [@BotFather](https://t.me/BotFather)
2. Get a HikerAPI key — **[100 free requests here](https://hikerapi.com/p/hsazcgym)**
3. Copy `default.env` to `.env` and fill in your tokens
4. Run:
   ```bash
   docker compose up -d --build
   ```

   Or locally:
   ```bash
   pip install -r requirements.txt
   python bot.py
   ```
