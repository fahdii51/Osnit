# CLAUDE.md - Development Guide

## Project Overview
Instagram OSINT Telegram bot using aiogram 3.22 + HikerAPI SDK.

## Architecture
- `bot.py` - Main entry point. Aiogram Router with all command handlers. In-memory dict for target tracking.
- `helpers.py` - Response parsing helpers (extract_list, extract_cursor, extract_profile_pic) + CDN download functions.
- `formatters.py` - MarkdownV2 message formatting for Telegram.
- `config.py` - Environment variable loading.

## Key Patterns
- All SDK calls use hikerapi AsyncClient — natively async, no thread wrapping needed.
- Media downloads use async httpx directly.
- Target resolution: command arg > stored target > error hint.
- Error mapping: "not found" -> NotFoundError, 403 -> PrivateAccountError, else -> ClientError.
- Media sending: download via `download_resources()`, send as Telegram media groups (max 10 per group), fallback to URLs on TelegramEntityTooLarge.
- Pagination: posts/reels use chunk endpoints with max 2 pages.

## Running
```bash
cp default.env .env  # fill in BOT_TOKEN and HIKERAPI_TOKEN
pip install -r requirements.txt
python bot.py
```

## Docker
```bash
docker compose up -d --build
```

## Dependencies
- aiogram 3.22.0 - Telegram bot framework
- httpx 0.28.1 - Async HTTP client for media downloads
- hikerapi >= 1.7.3 - HikerAPI Python SDK
