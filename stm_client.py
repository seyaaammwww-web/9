"""Async HTTP client for SecureTempMail free inbox API (Mage login)."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import httpx

log = logging.getLogger("stm_client")

STM_BASE = "https://www.securetempmail.com"
STM_API = f"{STM_BASE}/api"
STM_SITE = f"{STM_BASE}/disposable-email"
STM_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)


def _headers(token: str | None = None) -> dict[str, str]:
    h = {
        "User-Agent": STM_UA,
        "Accept": "application/json",
        "Accept-Language": "en-US,en;q=0.9",
        "Origin": STM_BASE,
        "Referer": STM_SITE,
    }
    # Frontend does not send Bearer; keep token optional for future/premium paths.
    if token:
        h["Authorization"] = f"Bearer {token}"
    return h


async def _request(
    method: str,
    url: str,
    *,
    token: str | None = None,
    json_body: dict | None = None,
    timeout: float = 20.0,
    retries: int = 3,
) -> httpx.Response:
    last_exc: Exception | None = None
    for attempt in range(retries):
        try:
            async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
                r = await client.request(
                    method,
                    url,
                    headers=_headers(token),
                    json=json_body,
                )
            # Soft-retry transient 404/429/5xx (STM occasionally blips under fast poll).
            if r.status_code in (404, 429, 500, 502, 503, 504) and attempt < retries - 1:
                await asyncio.sleep(0.35 * (attempt + 1))
                continue
            return r
        except Exception as e:
            last_exc = e
            if attempt < retries - 1:
                await asyncio.sleep(0.35 * (attempt + 1))
                continue
            raise
    if last_exc:
        raise last_exc
    raise RuntimeError("SecureTempMail request failed")


async def create_mailbox(*, ttl_minutes: int = 60, timeout: float = 20.0) -> dict[str, Any]:
    """
    Create a disposable inbox.
    Returns dict with: id, address, token, ...
    """
    r = await _request(
        "POST",
        f"{STM_API}/inbox",
        json_body={"ttlMinutes": ttl_minutes},
        timeout=timeout,
    )
    r.raise_for_status()
    data = r.json()
    address = data.get("address") or data.get("email") or data.get("email_address")
    inbox_id = data.get("id") or data.get("inbox_id")
    token = data.get("token") or data.get("read_token")
    if not address or "@" not in str(address):
        raise RuntimeError(f"SecureTempMail did not return address: {repr(data)[:300]}")
    if not inbox_id or not token:
        raise RuntimeError(f"SecureTempMail missing id/token: {repr(data)[:300]}")
    return {
        "id": str(inbox_id),
        "address": str(address),
        "token": str(token),
        "raw": data,
    }


async def list_messages(
    inbox_id: str,
    token: str,
    *,
    timeout: float = 20.0,
) -> list[dict[str, Any]]:
    r = await _request(
        "GET",
        f"{STM_API}/inbox/{inbox_id}/messages",
        token=token,
        timeout=timeout,
    )
    r.raise_for_status()
    data = r.json()
    if isinstance(data, list):
        return [m for m in data if isinstance(m, dict)]
    for key in ("messages", "data", "emails", "items"):
        val = data.get(key) if isinstance(data, dict) else None
        if isinstance(val, list):
            return [m for m in val if isinstance(m, dict)]
    return []


async def get_message(
    inbox_id: str,
    token: str,
    message_id: str,
    *,
    timeout: float = 20.0,
) -> dict[str, Any]:
    r = await _request(
        "GET",
        f"{STM_API}/inbox/{inbox_id}/messages/{message_id}",
        token=token,
        timeout=timeout,
    )
    r.raise_for_status()
    data = r.json()
    if isinstance(data, dict) and isinstance(data.get("message"), dict):
        return data["message"]
    if isinstance(data, dict):
        return data
    raise RuntimeError(f"Unexpected message payload: {type(data)}")


async def delete_inbox(inbox_id: str, token: str, *, timeout: float = 15.0) -> None:
    try:
        await _request(
            "DELETE",
            f"{STM_API}/inbox/{inbox_id}",
            token=token,
            timeout=timeout,
            retries=1,
        )
    except Exception as e:
        log.debug("SecureTempMail delete inbox failed: %s", e)
