# Operations (short)

## Boot checklist
1. Set `BOT_TOKEN`, `ADMIN_ID`, `ALLOWED_USER_IDS` in env.
2. Confirm outbound HTTPS to Telegram, Mage.space, SecureTempMail.
3. Watch logs for SecureTempMail reachability and session pool `ready=N`.

## Resource guide
- 1 worker ≈ 1 Chromium context — plan ~1–2 GB RAM each.
- Small container: `NUM_WORKERS=1` or `2`, matching `TARGET_POOL_SIZE`.
- Large VPS: raise workers/pool gradually.

## Timeouts
- Image: `GENERATION_ATTEMPT_TIMEOUT`
- Grok / GPT / Mango: `POSE_GENERATION_TIMEOUT`
- Video: `VIDEO_GENERATION_TIMEOUT`

## Data
Runtime writes under `data/` (sessions, temp images). Mount a volume if you need persistence across restarts.
