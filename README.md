# Mage Telegram Bot

Python + Playwright bot that automates [Mage.space](https://www.mage.space) image generation via Telegram.

## Run (Docker)

```bash
cp .env.example .env   # set BOT_TOKEN, ADMIN_ID, ALLOWED_USER_IDS
docker build -t mage-bot .
docker run --env-file .env -p 7860:7860 mage-bot
```

## Required env

| Variable | Purpose |
|----------|---------|
| `BOT_TOKEN` | Telegram bot token |
| `ADMIN_ID` | Admin Telegram user id |
| `ALLOWED_USER_IDS` | Comma-separated allowed user ids |

See `.env.example` for pool / timeout knobs. Start with `NUM_WORKERS=2` on small hosts; Playwright needs RAM.

## Layout

| File | Role |
|------|------|
| `main.py` | Bot + Mage pipelines |
| `stm_client.py` | SecureTempMail login inbox API |
| `fingerprints.py` | Browser fingerprints |
| `prompt_templates.py` | Prompt templates |
| `ultra_max_absolute_v4.py` | Absolute prompt helpers |
| `session_manager.py` | Session pool helpers |
| `pa_bridge.py` | Optional webhook bridge helpers |
| `Dockerfile` | Playwright Python image |

## Deploy notes

- Needs a real container/VPS with enough RAM for Chromium (not static hosting / Parse cloud code).
- Port `7860` is used for health / webhook listen.
- Do not commit `.env`.
