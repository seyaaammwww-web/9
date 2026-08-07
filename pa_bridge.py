"""PythonAnywhere bridge: WSGI webhook ingress ↔ always-on worker via file queue."""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent / "data"
DATA_DIR.mkdir(exist_ok=True)

QUEUE_PATH = DATA_DIR / "telegram_queue.jsonl"
HEALTH_PATH = DATA_DIR / "pa_health.json"

try:
    import fcntl  # Unix (PythonAnywhere)
except ImportError:  # pragma: no cover — Windows dev
    fcntl = None  # type: ignore


def _lock_ex(f) -> None:
    if fcntl is not None:
        fcntl.flock(f, fcntl.LOCK_EX)


def _lock_un(f) -> None:
    if fcntl is not None:
        fcntl.flock(f, fcntl.LOCK_UN)


def enqueue_telegram_update(update: dict) -> None:
    """Append one Telegram update JSON object (WSGI → always-on)."""
    line = json.dumps(update, separators=(",", ":"), ensure_ascii=False) + "\n"
    QUEUE_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(QUEUE_PATH, "a", encoding="utf-8") as f:
        _lock_ex(f)
        try:
            f.write(line)
            f.flush()
        finally:
            _lock_un(f)


def dequeue_telegram_updates(max_n: int = 20) -> list[dict]:
    """Read up to max_n updates and remove them from the queue atomically."""
    if not QUEUE_PATH.is_file():
        return []
    max_n = max(1, int(max_n))
    with open(QUEUE_PATH, "r+", encoding="utf-8") as f:
        _lock_ex(f)
        try:
            lines = f.readlines()
            if not lines:
                return []
            batch = lines[:max_n]
            rest = lines[max_n:]
            f.seek(0)
            f.truncate(0)
            if rest:
                f.writelines(rest)
            f.flush()
        finally:
            _lock_un(f)
    out: list[dict] = []
    for raw in batch:
        raw = raw.strip()
        if not raw:
            continue
        try:
            out.append(json.loads(raw))
        except json.JSONDecodeError:
            continue
    return out


def write_health_snapshot(body: str, *, content_type: str = "application/json", status: int = 200) -> None:
    """Always-on worker writes health; WSGI reads it."""
    payload = {
        "ts": time.time(),
        "status_code": status,
        "content_type": content_type,
        "body": body,
    }
    HEALTH_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = HEALTH_PATH.with_suffix(".tmp")
    text = json.dumps(payload, ensure_ascii=False)
    with open(tmp, "w", encoding="utf-8") as f:
        _lock_ex(f)
        try:
            f.write(text)
            f.flush()
        finally:
            _lock_un(f)
    tmp.replace(HEALTH_PATH)


def read_health_snapshot() -> dict | None:
    if not HEALTH_PATH.is_file():
        return None
    try:
        with open(HEALTH_PATH, "r", encoding="utf-8") as f:
            _lock_ex(f)
            try:
                text = f.read()
            finally:
                _lock_un(f)
        data = json.loads(text)
        return data if isinstance(data, dict) else None
    except Exception:
        return None


def default_health_body() -> str:
    host = os.getenv("PA_HOST", "moamed12.pythonanywhere.com").strip()
    return json.dumps(
        {
            "status": "starting",
            "host": host,
            "message": "always-on worker booting",
        }
    )
