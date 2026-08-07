# -*- coding: utf-8 -*-
"""
Mage.space Auto-Generator Telegram Bot  (v3 – production hardened)
──────────────────────────────────────────────────────────────────
Fixes in v3:
  • Multi-worker support (NUM_WORKERS parallel generators)
  • Per-worker session isolation (no shared mutable state)
  • Bounded queue with user-facing "busy" message
  • Per-user rate limiting
  • Download retry with exponential backoff
  • Periodic temp-file cleanup
  • Browser context recycled every N accounts
  • Pre-count images to avoid grabbing wrong result
  • Smart error classification (network vs auth)
  • ConversationHandler timeout
  • Generic error messages to users
"""

import asyncio
import base64
import hashlib
import io
import logging
import os
import signal
import requests
import shutil
import warnings
from pathlib import Path
from telegram.warnings import PTBUserWarning
from functools import wraps
from typing import Awaitable, Callable, TypeVar, Any, Optional

T = TypeVar('T')


def _load_dotenv() -> None:
    """Load .env into os.environ without overriding variables already set."""
    env_path = Path(__file__).resolve().parent / ".env"
    if not env_path.is_file():
        return
    for raw_line in env_path.read_text(encoding="utf-8-sig").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip().lstrip("\ufeff")
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


_load_dotenv()

# Suppress PTBUserWarning to avoid spamming the log with 'per_message=False' warning
warnings.filterwarnings("ignore", category=PTBUserWarning)

import mimetypes
import json
import random
import re
import secrets
import tempfile
import threading
import time
import traceback
from dataclasses import dataclass, field
import socket
from typing import Optional
from PIL import Image
import uuid
import html

# ── IPv4 Monkeypatch for HF Spaces ────────────────────────────────────────────
# Hugging Face Spaces often blackholes IPv6 traffic, causing httpx to hang on
# connect for 30+ seconds. Forcing IPv4 globally for Python sockets fixes this.
# Only apply if running on HF Spaces to avoid side effects in other environments.
if os.getenv("SPACE_ID") or os.getenv("HF_SPACE"):  # Only on HF Spaces
    _orig_getaddrinfo = socket.getaddrinfo
    _IPV4_EXEMPT_SUFFIXES = (".workers.dev",)

    def _ipv4_getaddrinfo(host, port, family=0, type=0, proto=0, flags=0):
        host_str = str(host or "")
        if any(host_str.endswith(suffix) for suffix in _IPV4_EXEMPT_SUFFIXES):
            return _orig_getaddrinfo(host, port, family, type, proto, flags)
        try:
            result = _orig_getaddrinfo(host, port, socket.AF_INET, type, proto, flags)
            return result
        except Exception:
            # Fallback to original behavior if IPv4-only fails
            return _orig_getaddrinfo(host, port, family, type, proto, flags)
    
    socket.getaddrinfo = _ipv4_getaddrinfo
    log_startup = logging.getLogger("MageBot")
    log_startup.info("✅ IPv4-only socket mode enabled for HF Spaces")
else:
    log_startup = logging.getLogger("MageBot")
# ──────────────────────────────────────────────────────────────────────────────

import httpx
from aiohttp import web
from playwright.async_api import (
    async_playwright, Page, Browser, BrowserContext, Playwright,
    TimeoutError as PWTimeout, Locator
)
from telegram import Update, InputFile, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.error import NetworkError, TimedOut, Conflict
from telegram.ext import (
    Application, CommandHandler, MessageHandler, filters, ContextTypes,
    ConversationHandler, CallbackQueryHandler
)

from ultra_max_absolute_v4 import (
    build_absolute_prompt,
    absolute_nsfw_evasion,
    absolute_paste_prompt,
)

# Optional session manager — initialized after config constants below
SessionManager = None
try:
    from session_manager import SessionManager as _SessionManager
    SessionManager = _SessionManager
except Exception:
    pass

from fingerprints import (
    BrowserFingerprint,
    build_stealth_init_script,
    get_http_client_profile,
    get_worker_fingerprint,
    inbound_hook_base_path,
    maildev_http_headers,
    public_health_payload,
)

from prompt_templates import (
    PROMPT_TEMPLATE_CATEGORIES,
    get_mode_keyboard,
    get_bulk_done_keyboard,
    get_prompt_mode_keyboard,
    get_category_keyboard,
    get_template_keyboard,
    get_template_prompt,
    get_random_template,
    get_video_prompt_keyboard,
    get_video_prompt,
    get_video_prompt_texts,
    get_default_video_prompt,
    get_guava_version_keyboard,
)
from stm_client import STM_BASE, STM_SITE
from stm_client import create_mailbox as stm_create_mailbox
from stm_client import get_message as stm_get_message
from stm_client import list_messages as stm_list_messages

acct_manager = None

# ── Config ────────────────────────────────────────────────────────────────────
BOT_TOKEN       = os.getenv("BOT_TOKEN", "")
ADMIN_ID        = int(os.getenv("ADMIN_ID", "2074492017"))  # Primary admin
_on_hf = bool(os.getenv("SPACE_ID") or os.getenv("HF_SPACE"))
_on_pa = (
    os.getenv("PYTHONANYWHERE", "").strip().lower() in ("1", "true", "yes", "on")
    or bool(os.getenv("PA_HOST", "").strip())
)
_on_railway = os.getenv("RAILWAY_ENVIRONMENT_ID") is not None
_on_cloud = _on_hf or _on_pa or _on_railway
FRESH_POOL_ON_BOOT = os.getenv(
    "FRESH_POOL_ON_BOOT", "1" if not _on_cloud else "0",
).lower() in ("1", "true", "yes", "on")
LIVE_ONLY_POOL = os.getenv(
    "LIVE_ONLY_POOL", "1" if FRESH_POOL_ON_BOOT else "0",
).lower() in ("1", "true", "yes", "on")
ALLOWED_USER_IDS: set[int] = {ADMIN_ID}
_allowed_env = os.getenv("ALLOWED_USER_IDS", "").strip()
if _allowed_env:
    ALLOWED_USER_IDS = {int(x.strip()) for x in _allowed_env.split(",") if x.strip() and x.strip() != "1110660310"}
# Each allowed user gets a dedicated worker + pre-warmed browser + session pool slot
USER_WORKER_MAP: dict[int, int] = {uid: idx for idx, uid in enumerate(sorted(ALLOWED_USER_IDS))}
WORKER_USER_MAP: dict[int, int] = {v: k for k, v in USER_WORKER_MAP.items()}
MULTI_USER_ISOLATION = len(ALLOWED_USER_IDS) > 1
STRICT_QUEUE_USER_IDS: set[int] = set()
_strict_env = os.getenv("STRICT_QUEUE_USER_IDS", "").strip()
if _strict_env:
    STRICT_QUEUE_USER_IDS = {int(x.strip()) for x in _strict_env.split(",") if x.strip() and x.strip() != "1110660310"}
ADMIN_GROUP_ID  = os.getenv("ADMIN_GROUP_ID")
_default_workers = "1"
NUM_WORKERS     = int(os.getenv("NUM_WORKERS", _default_workers))
MAX_QUEUE       = int(os.getenv("MAX_QUEUE", "200"))
COOLDOWN_USER_IDS: set[int] = set()
_cooldown_users_env = os.getenv("COOLDOWN_USER_IDS", "").strip()
if _cooldown_users_env:
    COOLDOWN_USER_IDS = {int(x.strip()) for x in _cooldown_users_env.split(",") if x.strip() and x.strip() != "1110660310"}
COOLDOWN_SECONDS = int(os.getenv("USER_COOLDOWN", "0"))
MAILDEV_URL = "https://www.securetempmail.com/disposable-email"  # SecureTempMail (replaces 1secmail)
MAILDEV_API_URL = "https://www.securetempmail.com/api"  # free public inbox API
MAILDEV_PROXY_URL = os.getenv("MAILDEV_PROXY_URL", "").strip().rstrip("/")  # unused; kept for env compat
_MAILDEV_PROXY_HEALTHY = False  # always False — no proxy needed for catchtempmail
_MAILDEV_CURL_CFFI_HEALTHY = False  # always False — catchtempmail needs no curl_cffi
_curl_maildev_session = None  # unused

try:
    from curl_cffi.requests import AsyncSession as _CurlAsyncSession
except ImportError:
    _CurlAsyncSession = None


def _maildev_use_curl_cffi() -> bool:
    """catchtempmail needs no curl_cffi — always False."""
    return False


def _maildev_http_api_ok() -> bool:
    """catchtempmail REST API is always reachable via plain httpx — always True."""
    return True


def _maildev_is_gas_proxy(url: str) -> bool:
    return "script.google.com" in (url or "")


def _maildev_is_ephemeral_proxy(url: str) -> bool:
    """PC-hosted quick tunnels — die when the machine sleeps or the tunnel stops."""
    lowered = (url or "").lower()
    return any(
        host in lowered
        for host in (
            "trycloudflare.com",
            "ngrok.io",
            "ngrok-free.app",
            "loca.lt",
            "serveo.net",
            "localhost.run",
            "bore.pub",
        )
    )


def _maildev_build_proxy_url(proxy: str, relative_path: str, *, cache_bust: bool = False) -> str:
    rel = relative_path.lstrip("/")
    if _maildev_is_gas_proxy(proxy):
        q = f"path={rel}"
        if cache_bust:
            q += f"&_={int(time.time() * 1000)}"
        return f"{proxy}?{q}"
    suffix = f"?_={int(time.time() * 1000)}" if cache_bust else ""
    return f"{proxy}/{rel}{suffix}"


def _maildev_proxy_url() -> str:
    """catchtempmail needs no proxy — always empty."""
    return ""


def _maildev_prefer_proxy() -> bool:
    """catchtempmail needs no proxy — always False."""
    return False
_MAILDEV_ADJECTIVES = (
    "proud", "glad", "warm", "flashy", "ebullient", "benevolent", "stout", "quiet",
    "swift", "bright", "gentle", "clever", "nimble", "calm", "bold", "merry",
)
_MAILDEV_NOUNS = (
    "cruet", "jute", "library", "cubit", "haunch", "willet", "inbox", "mailbox",
    "letter", "parcel", "packet", "scroll", "ledger", "cache", "socket", "relay",
)
_BUILDER_FP = get_worker_fingerprint(-1)
_MAILDEV_UA = _BUILDER_FP.user_agent
_HTTP_CLIENT_PROFILE = get_http_client_profile()
STEALTH_LOG = os.getenv("STEALTH_LOG", "1" if _on_cloud else "0").lower() in ("1", "true", "yes", "on")
STEALTH_PUBLIC_FACE = os.getenv(
    "STEALTH_PUBLIC_FACE", "1" if _on_cloud else "0"
).lower() in ("1", "true", "yes", "on")


def _maildev_headers() -> dict[str, str]:
    return maildev_http_headers(_BUILDER_FP)


_MAILDEV_HTTP_HEADERS = _maildev_headers()
_MAILDEV_HTTP_TIMEOUT = httpx.Timeout(30.0 if _on_hf else 15.0, connect=20.0 if _on_hf else 8.0)
_MAILDEV_PROXY_RETRIES = 4 if _on_hf else 3
_MAILDEV_PROXY_RETRY_DELAYS = (1.0, 2.0, 3.0) if _on_hf else (1.0, 2.0)


def _brief_exc(exc: BaseException) -> str:
    text = str(exc).strip()
    name = type(exc).__name__
    return f"{name}({text})" if text else name


def _truthy_env(name: str) -> bool:
    return os.getenv(name, "").strip().lower() in ("1", "true", "yes", "on")


def _falsey_env(name: str) -> bool:
    return os.getenv(name, "").strip().lower() in ("0", "false", "no", "off")


class _StealthLogFilter(logging.Filter):
    """Redact product names, tokens, and webhook URLs from HF Space logs."""

    _TOKEN_RE = re.compile(r"(bot\d+:[A-Za-z0-9_-]{20,}|hf_[A-Za-z0-9]{20,})")
    _URL_RE = re.compile(r"https?://[^\s\"']+")
    _TERM_MAP = (
        (re.compile(r"\btelegram\b", re.I), "ingress"),
        (re.compile(r"\bmage\.space\b", re.I), "upstream"),
        (re.compile(r"\bmaildev\b", re.I), "mailbox"),
        (re.compile(r"\b(guava|grok|kiwi|gpt)\b", re.I), "model"),
        (re.compile(r"\bbot\b", re.I), "service"),
        (re.compile(r"\bplaywright\b", re.I), "browser"),
    )

    def filter(self, record: logging.LogRecord) -> bool:
        if not STEALTH_LOG:
            return True
        try:
            msg = record.getMessage()
        except Exception:
            return True
        msg = self._TOKEN_RE.sub("***", msg)
        msg = self._URL_RE.sub("[endpoint]", msg)
        for pattern, repl in self._TERM_MAP:
            msg = pattern.sub(repl, msg)
        record.msg = msg
        record.args = ()
        return True


def _stealth_log_url(url: str) -> str:
    """Log-safe URL — host only, no path secrets."""
    if not STEALTH_LOG or not url:
        return url or ""
    try:
        host = url.split("://", 1)[-1].split("/", 1)[0]
        return f"[endpoint]/{host}"
    except Exception:
        return "[endpoint]"


# ── Robustness Utilities: Timeout, Retry, Circuit Breaker ─────────────────────

def async_timeout(seconds: float) -> Callable:
    """Decorator to add timeout to async functions to prevent hangs."""
    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        @wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> T:
            try:
                return await asyncio.wait_for(func(*args, **kwargs), timeout=seconds)
            except asyncio.TimeoutError:
                raise TimeoutError(f"{func.__name__} timed out after {seconds}s")
        return wrapper
    return decorator


class CircuitBreaker:
    """Circuit breaker to prevent cascading failures from repeated errors."""
    def __init__(self, failure_threshold: int = 5, recovery_timeout: float = 60.0):
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.failure_count = 0
        self.last_failure_time = None
        self.state = "closed"  # closed, open, half-open
        self._lock = asyncio.Lock()
    
    async def call(self, func: Callable[..., "Awaitable[T]"], *args: Any, **kwargs: Any) -> T:
        async with self._lock:
            if self.state == "open":
                if time.time() - (self.last_failure_time or 0) > self.recovery_timeout:
                    self.state = "half-open"
                    log.info("Circuit breaker entering half-open state")
                else:
                    raise RuntimeError("Circuit breaker is OPEN - calls blocked")
        
        try:
            result = await func(*args, **kwargs)
            async with self._lock:
                self.failure_count = 0
                self.state = "closed"
            return result
        except Exception as e:
            async with self._lock:
                self.failure_count += 1
                self.last_failure_time = time.time()
                if self.failure_count >= self.failure_threshold:
                    self.state = "open"
                    log.warning(f"Circuit breaker OPEN after {self.failure_count} failures")
            raise


async def retry_with_backoff(
    func: Callable[..., "Awaitable[T]"],
    *args: Any,
    max_retries: int = 3,
    base_delay: float = 1.0,
    max_delay: float = 30.0,
    backoff_factor: float = 2.0,
    **kwargs: Any
) -> T:
    """Retry async function with exponential backoff for transient failures."""
    last_exception: Optional[Exception] = None
    for attempt in range(max_retries + 1):
        try:
            return await func(*args, **kwargs)
        except Exception as e:
            last_exception = e
            if attempt == max_retries:
                break
            delay = min(base_delay * (backoff_factor ** attempt), max_delay)
            log.warning(f"Retry {attempt + 1}/{max_retries} after {delay:.1f}s: {e}")
            await asyncio.sleep(delay)
    raise last_exception  # type: ignore[misc]  # always set after ≥1 iteration


# Global circuit breakers for critical operations
_maildev_circuit_breaker = CircuitBreaker(failure_threshold=3, recovery_timeout=30.0)
_mage_api_circuit_breaker = CircuitBreaker(failure_threshold=5, recovery_timeout=60.0)
_browser_circuit_breaker = CircuitBreaker(failure_threshold=3, recovery_timeout=45.0)


# ── Deadlock Detection and Safe Lock Wrapper ───────────────────────────────────

async def safe_lock_acquire(lock: asyncio.Lock, timeout: float = 30.0, context: str = "lock") -> bool:
    """Acquire lock with timeout to prevent deadlocks. Returns True if acquired."""
    try:
        await asyncio.wait_for(lock.acquire(), timeout=timeout)
        return True
    except asyncio.TimeoutError:
        log.error("⚠️ Deadlock detected: %s not acquired after %ds", context, timeout)
        return False


def safe_lock_release(lock: asyncio.Lock) -> None:
    """Safely release lock without raising if not held."""
    try:
        lock.release()
    except Exception:
        pass


# ── Worker Health Check System ─────────────────────────────────────────────────

_worker_health_status: dict[int, dict] = {}  # worker_id -> {last_check, healthy, failures}
_worker_health_lock = asyncio.Lock()


async def _worker_health_check(worker_id: int, session: "WorkerSession") -> dict:
    """Perform health check on a worker session."""
    health = {
        "worker_id": worker_id,
        "timestamp": time.time(),
        "healthy": True,
        "issues": [],
    }
    
    # Check browser page
    if session.mage_page:
        if not await _validate_browser_page(session.mage_page, worker_id):
            health["healthy"] = False
            health["issues"].append("browser_page_invalid")
    
    # Check context (BrowserContext has no is_closed(); probe via pages)
    if session.ctx:
        try:
            _ = session.ctx.pages  # raises if context is closed
        except Exception:
            health["healthy"] = False
            health["issues"].append("context_closed")
    
    # Check browser
    if session.browser and session.browser.is_connected() is False:
        health["healthy"] = False
        health["issues"].append("browser_disconnected")
    
    return health


async def _update_worker_health(worker_id: int, session: "WorkerSession") -> None:
    """Update worker health status."""
    async with _worker_health_lock:
        health = await _worker_health_check(worker_id, session)
        _worker_health_status[worker_id] = health
        if not health["healthy"]:
            log.warning("[W%d] Health check failed: %s", worker_id, health["issues"])


async def _get_worker_health(worker_id: int) -> dict:
    """Get current worker health status."""
    async with _worker_health_lock:
        return _worker_health_status.get(worker_id, {"healthy": True, "issues": []})

# ── Browser State Validation and Recovery ─────────────────────────────────────

async def _validate_browser_page(page: Page, worker_id: int = 0) -> bool:
    """Check if browser page is in a valid, responsive state."""
    if page.is_closed():
        return False
    try:
        # Quick connectivity check
        await page.evaluate("() => document.readyState")
        return True
    except Exception as e:
        log.warning("[W%d] Browser page validation failed: %s", worker_id, e)
        return False


async def _recover_browser_session(s: "WorkerSession", app: Optional[Application] = None, job: Optional["Job"] = None) -> bool:
    """Recover browser state: recreate context, then pool page, then fresh login."""
    log.warning("[W%d] Attempting browser session recovery...", s.worker_id)
    try:
        await _teardown_browser_stack(s)
        await asyncio.sleep(0.5)
        s.page_prepared_for_job = False
        s.live_prewarmed_guava = False
        s.mage_page = None

        if job and acct_manager is not None and TARGET_POOL_SIZE > 0:
            owner_uid = job.user_id
            pool_wait = min(POOL_ACQUIRE_WAIT, 8.0)
            t0 = time.time()
            acct = await _async_acquire_pooled_session(
                max_wait=pool_wait, owner_user_id=owner_uid
            )
            if acct:
                page = await _activate_pooled_session(s, acct, app, job)
                if page:
                    if job.pipeline == "posing":
                        await _ensure_posing_model_ready(page, s.worker_id)
                    elif job.pipeline == "gpt_image":
                        await _ensure_gpt_image_model_ready(page, s.worker_id)
                    elif job.pipeline == "mango3":
                        await _ensure_mango_3_model_ready(page, s.worker_id)
                    elif job.pipeline == "video":
                        await _ensure_video_model_ready(page, s.worker_id)
                    log.info(
                        "[W%d] ✅ Browser recovery via pool (%.1fs)",
                        s.worker_id, time.time() - t0,
                    )
                    return True

        if job and app is not None:
            try:
                page = await _setup_account(s, app, job)
                if page:
                    log.info("[W%d] ✅ Browser recovery via fresh login", s.worker_id)
                    return True
            except Exception as login_err:
                log.warning("[W%d] Recovery fresh login failed: %s", s.worker_id, login_err)

        await _ensure_ctx(s)
        s.mage_page = await _new_page(s)
        log.info("[W%d] ✅ Browser context recreated (empty page)", s.worker_id)
        return True
    except Exception as e:
        log.error("[W%d] ❌ Browser session recovery failed: %s", s.worker_id, e)
        return False


class _StageTimer:
    """Lightweight per-job stage timing — one summary line per job in logs."""

    _ORDER = (
        "pool_acquire", "session_activate", "model_ready",
        "upload", "send", "generate_wait", "download", "total",
    )

    def __init__(self, job_id: str, pipeline: str, worker_id: int = 0):
        self.job_id = job_id
        self.pipeline = pipeline
        self.worker_id = worker_id
        self._t0 = time.time()
        self._t = self._t0
        self.stages: dict[str, float] = {}

    def mark(self, name: str) -> None:
        now = time.time()
        self.stages[name] = round(now - self._t, 2)
        self._t = now

    def add(self, name: str, seconds: float) -> None:
        self.stages[name] = round(seconds, 2)

    def finish(self) -> None:
        self.stages["total"] = round(time.time() - self._t0, 2)

    def log_summary(self, *, success: bool = True) -> None:
        self.finish()
        parts = [f"{k}={self.stages[k]}s" for k in self._ORDER if k in self.stages]
        log.info(
            "[W%d] ⏱ Stage timing job=%s pipeline=%s success=%s %s",
            self.worker_id, self.job_id, self.pipeline, success, " ".join(parts),
        )


async def _safe_browser_operation(page: Page, operation: Callable, *args, worker_id: int = 0, **kwargs) -> Any:
    """Execute browser operation with validation and automatic recovery on failure."""
    if not await _validate_browser_page(page, worker_id):
        log.warning("[W%d] Browser page invalid before operation", worker_id)
        raise RuntimeError("Browser page is in invalid state")
    
    try:
        return await operation(page, *args, **kwargs)
    except Exception as e:
        log.warning("[W%d] Browser operation failed: %s", worker_id, e)
        raise


_STEALTH_INIT_SCRIPT = build_stealth_init_script(_BUILDER_FP)  # legacy fallback
_MAILDEV_SELECTORS = {
    "enter_inbox": 'button:has-text("Enter inbox")',
    "view_inbox": 'button:has-text("View Inbox")',
    "email_input": 'input.input-base, input[placeholder="null-inbox"]',
    "copy_email": 'button[title="Copy email address"]:not([disabled])',
    "refresh_inbox": '.tooltip[data-tip="Refresh"] button',
    "empty_inbox": 'text=Looks empty',
    "inbox_heading": 'h2:has-text("Inbox")',
}
MAGE_EMAIL_MAX_ATTEMPTS = int(os.getenv("MAGE_EMAIL_MAX_ATTEMPTS", "8"))
_MAGE_EMAIL_SENT_HINTS = (
    "sign-in link", "sign in link", "check your email",
    "verification link", "email sent", "we sent", "link sent", "sent you",
    "sent a sign", "email with a link",
)
_MAGE_EMAIL_REJECT_HINTS = (
    "disposable", "temporary email", "temp mail", "throwaway", "burner",
    "not accepted", "not allowed", "not permitted", "invalid email",
    "blocked", "use a different", "permanent email", "valid email",
    "disposable email", "email provider", "cannot use",
    "issue logging you in", "something's not right", "had an issue",
)
_MAGE_MAGIC_LINK_FAIL_HINTS = (
    "issue logging you in",
    "something's not right",
    "had an issue",
    "try again",
    "link expired",
    "invalid action code",
    "invalid oob",
)
_HREF_ATTR_RE = re.compile(r"""href\s*=\s*(?:"([^"]+)"|'([^']+)')""", re.I)
_MAGE_AUTH_URL_RE = re.compile(
    r"https?://(?:www\.)?mage\.space/__/auth/action\?[^\s\"'<>]+",
    re.I,
)
_FIREBASE_AUTH_URL_RE = re.compile(
    r"https?://[^/\s\"'<>]+\.firebaseapp\.com/__/auth/action\?[^\s\"'<>]+",
    re.I,
)
MAGE_ENTER      = "https://www.mage.space/explore?onboarding=1"
MAGE_EXPLORE    = "https://www.mage.space/explore"
MAGE_MODELS     = "https://www.mage.space/models"
GROK_MODEL_HREF = "/play/grok-image-quality-fast-mode-2f0e2deb8a66425b97e1044abb562a82"
GROK_PLAY_URL   = f"https://www.mage.space{GROK_MODEL_HREF}"
GROK_GEM_COST   = 75
KIWI_MODEL_HREF = "/play/kiwi-video-fast-mode-d3e73f28d68947078ebe9b268996323b"
KIWI_PLAY_URL   = f"https://www.mage.space{KIWI_MODEL_HREF}"
KIWI_GEM_COST   = 270
GUAVA_15_MODEL_HREF = "/play/guava-pro-15-fast-mode-54279f09c8844a96ac4f74c2717990c8"
GUAVA_15_PLAY_URL   = f"https://www.mage.space{GUAVA_15_MODEL_HREF}"
GUAVA_15_DISPLAY    = "Guava Pro 1.5 Fast Mode"
GUAVA_15_GEM_COST   = 79
GUAVA_DISPLAY       = "Guava Pro Fast Mode"
GPT_IMAGE_MODEL_HREF = "/play/gpt-image-2-fast-mode-2fe8da7ba60e44b387bb4fad642d5200"
GPT_IMAGE_PLAY_URL   = f"https://www.mage.space{GPT_IMAGE_MODEL_HREF}"
GPT_IMAGE_DISPLAY    = "GPT Image 2 Fast Mode"
MANGO_3_MODEL_HREF   = "/play/mango-3-fast-mode-c82fa4f268cc4f5b9279450250c1b3c2"
MANGO_3_PLAY_URL     = f"https://www.mage.space{MANGO_3_MODEL_HREF}"
MANGO_3_DISPLAY      = "Mango 3 Fast Mode"
# Kiwi video renders ~1-2 min after send; default wait allows 2 min + buffer
VIDEO_GENERATION_TIMEOUT = int(os.getenv("VIDEO_GENERATION_TIMEOUT", "180"))
MIN_POOL_GEMS   = int(os.getenv("MIN_POOL_GEMS", str(GROK_GEM_COST)))
ASPECTS         = ["16:9", "3:2", "5:4", "1:1", "4:5", "2:3", "9:16"]
DEF_ASPECT      = "1:1"
DATA_DIR        = Path(__file__).parent / "data"
DATA_DIR.mkdir(exist_ok=True)
JOB_REFS_DIR    = DATA_DIR / "job_refs"
JOB_REFS_DIR.mkdir(exist_ok=True)
MAILDEV_DEBUG_DIR = DATA_DIR / "debug"
MAILDEV_DEBUG_DIR.mkdir(exist_ok=True)

# Session pool — pre-warmed Mage sessions; dedicated builder replaces on consume
_default_pool = "1"
POOL_SIZE_PER_USER = int(os.getenv("POOL_SIZE_PER_USER", os.getenv("TARGET_POOL_SIZE", _default_pool)))
TARGET_POOL_SIZE   = POOL_SIZE_PER_USER * len(ALLOWED_USER_IDS) if MULTI_USER_ISOLATION else POOL_SIZE_PER_USER
_default_pool_acquire = "240" if FRESH_POOL_ON_BOOT and not _on_cloud else "12"
POOL_ACQUIRE_WAIT  = float(os.getenv("POOL_ACQUIRE_WAIT", _default_pool_acquire))
POOL_ACQUIRE_POLL_SEC = float(os.getenv("POOL_ACQUIRE_POLL_SEC", "0.15"))
_default_builder_grace = "120" if FRESH_POOL_ON_BOOT and not _on_cloud else "18"
POOL_BUILDER_GRACE = float(os.getenv("POOL_BUILDER_GRACE", _default_builder_grace))
_default_builder_pause = "1" if (_on_cloud or LIVE_ONLY_POOL) else "0"
BUILDER_PAUSE_DURING_JOBS = os.getenv(
    "BUILDER_PAUSE_DURING_JOBS", _default_builder_pause
).lower() in ("1", "true", "yes")
BUILDER_PAUSE_POLL_SEC = float(os.getenv("BUILDER_PAUSE_POLL_SEC", "1"))
# Only pause the session builder during jobs when the pool already has this many ready sessions.
# Lower values keep refilling pre-sessions under load (prevents pool drain → slow fresh logins).
_default_builder_pause_min = "1" if _on_cloud else "2"
BUILDER_PAUSE_MIN_READY = int(os.getenv("BUILDER_PAUSE_MIN_READY", _default_builder_pause_min))
QUEUE_STUCK_CHECK_SEC = int(os.getenv("QUEUE_STUCK_CHECK_SEC", "30"))
QUEUE_STATS_CLEANUP_SEC = int(os.getenv("QUEUE_STATS_CLEANUP_SEC", "300"))
WORKER_IDLE_POLL_SEC = float(os.getenv("WORKER_IDLE_POLL_SEC", "0.1"))
_default_builder_boot_delay = "15" if _on_hf else ("25" if not _on_cloud else "0")
BUILDER_BOOT_DELAY_SEC = float(os.getenv("BUILDER_BOOT_DELAY_SEC", _default_builder_boot_delay))
BUILDER_REJECTION_COOLDOWN_SEC = float(os.getenv("BUILDER_REJECTION_COOLDOWN_SEC", "3"))
POOL_BUILDER_GUAVA_ROUNDS = int(os.getenv("POOL_BUILDER_GUAVA_ROUNDS", "5"))
REFERENCE_PASTE_ATTEMPTS = int(os.getenv("REFERENCE_PASTE_ATTEMPTS", "5"))
REFERENCE_CDN_TIMEOUT_MS = int(os.getenv("REFERENCE_CDN_TIMEOUT_MS", "60000"))
REFERENCE_PASTE_WALL_SEC = int(os.getenv("REFERENCE_PASTE_WALL_SEC", "90"))
_default_fast_fail = "1" if _on_cloud else "0"
FAST_FAIL_NO_INDICATOR = os.getenv(
    "FAST_FAIL_NO_INDICATOR", _default_fast_fail
).lower() in ("1", "true", "yes")
_default_pipeline_attempts = "2" if _on_cloud else "4"
PIPELINE_MAX_ATTEMPTS = int(os.getenv("PIPELINE_MAX_ATTEMPTS", _default_pipeline_attempts))
_default_job_requeue = "1" if _on_cloud else "2"
JOB_MAX_REQUEUE = int(os.getenv("JOB_MAX_REQUEUE", _default_job_requeue))
_default_parallel_builders = "1" if _on_cloud else str(min(2, max(1, POOL_SIZE_PER_USER)))
PARALLEL_BUILDERS  = int(os.getenv("PARALLEL_BUILDERS", _default_parallel_builders))
_default_prewarm = "1"
PREWARM_WORKERS    = int(os.getenv("PREWARM_WORKERS", _default_prewarm))
PREWARM_STAGGER_SEC = float(os.getenv("PREWARM_STAGGER_SEC", "8" if _on_hf else ("0" if not _on_cloud else "6")))
MAX_LIVE_POOLED    = int(os.getenv("MAX_LIVE_POOLED", "1"))
PAGE_SETTLE_MS     = int(os.getenv("PAGE_SETTLE_MS", "150"))          # after navigation / model switch
PROMPTBAR_READY_MS = int(os.getenv("PROMPTBAR_READY_MS", "5000"))     # wait for editor+send, not aspect chip
RESULT_POLL_SEC    = float(os.getenv("RESULT_POLL_SEC", "0.4"))      # generation completion poll interval
if _on_railway:
    PARALLEL_BUILDERS = 1
    BUILDER_PAUSE_DURING_JOBS = True

# Pipeline timeouts (seconds) — aligned so outer limits never cut inner work short
_DEFAULT_SETUP_TIMEOUT = "180" if _on_hf else ("150" if _on_pa else "120")
SETUP_TIMEOUT      = int(os.getenv("SETUP_TIMEOUT", _DEFAULT_SETUP_TIMEOUT))
if SETUP_TIMEOUT < (POOL_ACQUIRE_WAIT + POOL_BUILDER_GRACE + 60):
    SETUP_TIMEOUT = int(POOL_ACQUIRE_WAIT + POOL_BUILDER_GRACE + 60)
GENERATION_TIMEOUT = int(os.getenv("GENERATION_TIMEOUT", "360"))
# Per-attempt cap — successful gens finish in ~25s; retry sooner on hung generations
GENERATION_ATTEMPT_TIMEOUT = int(os.getenv("GENERATION_ATTEMPT_TIMEOUT", "90"))
POSE_GENERATION_TIMEOUT = int(os.getenv("POSE_GENERATION_TIMEOUT", "180"))
BULK_GENERATION_TIMEOUT = int(
    os.getenv("BULK_GENERATION_TIMEOUT", str(GENERATION_ATTEMPT_TIMEOUT + 120))
)
BROWSER_REUSE_LIMIT = int(os.getenv("BROWSER_REUSE_LIMIT", "5"))
BULK_MAX_BROWSER_REUSE = int(os.getenv("BULK_MAX_BROWSER_REUSE", "30"))
BULK_GUAVA_REUSE = os.getenv("BULK_GUAVA_REUSE", "1").lower() in ("1", "true", "yes")
USE_ABSOLUTE_PROMPTS = os.getenv("USE_ABSOLUTE_PROMPTS", "1").lower() in ("1", "true", "yes")
WORKER_JOB_TIMEOUT = int(os.getenv("WORKER_JOB_TIMEOUT", str(SETUP_TIMEOUT + GENERATION_ATTEMPT_TIMEOUT * 3 + 60)))
_default_session_stale = str(max(900, WORKER_JOB_TIMEOUT + 180))
SESSION_STALE_SEC  = int(os.getenv("SESSION_STALE_SEC", _default_session_stale))

# Image quality — bot must not downscale references or override Mage generation settings by default
REFERENCE_MAX_DIM       = int(os.getenv("REFERENCE_MAX_DIM", "0"))          # 0 = keep full resolution
REFERENCE_JPEG_QUALITY  = int(os.getenv("REFERENCE_JPEG_QUALITY", "98"))    # letterbox save only
INJECT_GENERATION_PARAMS = os.getenv("INJECT_GENERATION_PARAMS", "0").lower() in ("1", "true", "yes")
SEND_AS_DOCUMENT        = os.getenv("SEND_AS_DOCUMENT", "0").lower() in ("1", "true", "yes")

_mailbox_lock = asyncio.Lock()
_builder_mailbox_locks: dict[int, asyncio.Lock] = {}
_session_build_queue: asyncio.Queue = asyncio.Queue(maxsize=50)  # big enough to queue many refills during bulk
_blocked_access_last_log: dict[int, float] = {}
BLOCKED_ACCESS_LOG_INTERVAL = 300.0
_builder_sessions: dict[int, "WorkerSession"] = {}  # per-builder — isolated from job workers
_builder_busy_count: int = 0  # concurrent session builds in flight
_builder_fail_streak: int = 0  # consecutive builder failures — drives retry backoff
_builder_last_maildev_warn: float = 0.0  # throttle repeated Maildev-down warnings
MIN_TELEGRAM_IMAGE_BYTES = 1024


@dataclass
class LivePooledBrowser:
    """In-memory browser kept hot after pool build — preserves Guava model picker state."""
    pw: Playwright
    browser: Browser
    ctx: BrowserContext
    page: Page
    gems: int


_live_pooled_sessions: dict[str, LivePooledBrowser] = {}
_live_pool_lock = asyncio.Lock()
_model_picker_lock = asyncio.Lock()  # one browser opens model UI at a time

# Initialize session manager now that paths/constants exist
if SessionManager is not None:
    try:
        acct_manager = SessionManager(
            data_dir=str(DATA_DIR / "sessions"),
            max_workers=max(2, PARALLEL_BUILDERS),
        )
        log_startup.info(
            "✅ Session manager ready (pool=%d total, %d/user, users=%s)",
            TARGET_POOL_SIZE, POOL_SIZE_PER_USER, sorted(ALLOWED_USER_IDS),
        )
        if MULTI_USER_ISOLATION:
            for uid, wid in sorted(USER_WORKER_MAP.items()):
                log_startup.info("👥 User %d → dedicated worker %d + own session pool", uid, wid)
    except Exception as _sm_err:
        log_startup.warning("⚠️ Session manager init failed: %s", _sm_err)
        acct_manager = None

def _validate_image_file(path: str) -> bool:
    """True when path is a readable image with minimum size."""
    try:
        if os.path.getsize(path) < MIN_TELEGRAM_IMAGE_BYTES:
            return False
        with Image.open(path) as img:
            img.verify()
        with Image.open(path) as img:
            img.load()
        return True
    except Exception:
        return False


def _repair_image_file(path: str) -> bool:
    """Re-encode a damaged Telegram download into a clean JPEG."""
    try:
        with Image.open(path) as img:
            img.load()
            rgb = img.convert("RGB")
        repaired = f"{path}.repair.jpg"
        _save_reference_image(rgb, repaired)
        os.replace(repaired, path)
        return _validate_image_file(path)
    except Exception as e:
        log.debug("Image repair failed for %s: %s", path, e)
        return False


def get_closest_aspect_ratio(image_path: str) -> str:
    """Reads image dimensions and maps mathematically to the closest supported aspect ratio."""
    try:
        with Image.open(image_path) as img:
            width, height = img.size
        
        ratio = width / height
        aspect_values = {
            "16:9": 16 / 9,   # 1.7778
            "3:2": 3 / 2,     # 1.5
            "5:4": 5 / 4,     # 1.25
            "1:1": 1.0,       # 1.0
            "4:5": 4 / 5,     # 0.8
            "2:3": 2 / 3,     # 0.6667
            "9:16": 9 / 16,   # 0.5625
        }
        
        closest_aspect = "1:1"
        min_diff = float("inf")
        for aspect, val in aspect_values.items():
            diff = abs(ratio - val)
            if diff < min_diff:
                min_diff = diff
                closest_aspect = aspect
                
        log.info("📐 Image dimensions: %dx%d (ratio: %.4f). Closest aspect ratio matched: %s", width, height, ratio, closest_aspect)
        return closest_aspect
    except Exception as e:
        log.error("❌ Failed to automatically detect aspect ratio: %s. Defaulting to 1:1", e)
        return "1:1"


def _save_reference_image(img: Image.Image, output_path: str) -> str:
    """Save reference with high JPEG quality (letterbox only — no extra processing)."""
    q = max(85, min(100, REFERENCE_JPEG_QUALITY))
    try:
        img.save(output_path, "JPEG", quality=q, subsampling=0)
    except TypeError:
        img.save(output_path, "JPEG", quality=q)
    return output_path


def add_black_borders_to_fit_aspect(image_path: str, target_aspect: str, output_path: str | None = None) -> str:
    """Letterbox with black borders to match aspect. No stretch. No downscale unless REFERENCE_MAX_DIM > 0."""
    try:
        if output_path is None:
            output_path = image_path.replace(".jpg", "_processed.jpg").replace(".png", "_processed.jpg")

        if hasattr(Image, "Resampling"):
            resample_filter = Image.Resampling.LANCZOS
        elif hasattr(Image, "LANCZOS"):
            resample_filter = Image.LANCZOS
        else:
            resample_filter = Image.ANTIALIAS

        with Image.open(image_path) as img:
            if img.mode != "RGB":
                img = img.convert("RGB")
            
            current_w, current_h = img.size
            orig_w, orig_h = current_w, current_h
            
            if current_w <= 0 or current_h <= 0:
                log.error("❌ Invalid image dimensions: %dx%d", current_w, current_h)
                return image_path
            
            if REFERENCE_MAX_DIM > 0 and max(current_w, current_h) > REFERENCE_MAX_DIM:
                cap = REFERENCE_MAX_DIM
                if current_w > current_h:
                    new_w = cap
                    new_h = int(current_h * (cap / current_w))
                else:
                    new_h = cap
                    new_w = int(current_w * (cap / current_h))
                log.info("📐 Downscaling reference (REFERENCE_MAX_DIM=%d): %dx%d → %dx%d",
                         cap, current_w, current_h, new_w, new_h)
                img = img.resize((new_w, new_h), resample_filter)
                current_w, current_h = new_w, new_h

            current_ratio = current_w / current_h
            
            # Parse target aspect with validation
            target_parts = target_aspect.split(":")
            if len(target_parts) != 2:
                log.error("❌ Invalid aspect format: %s (expected 'W:H')", target_aspect)
                if (current_w, current_h) == (orig_w, orig_h) and image_path.lower().endswith((".jpg", ".jpeg", ".png")):
                    return image_path
                return _save_reference_image(img, output_path)
            
            try:
                target_w, target_h = int(target_parts[0]), int(target_parts[1])
                if target_w <= 0 or target_h <= 0:
                    log.error("❌ Invalid target aspect values: %d:%d", target_w, target_h)
                    if (current_w, current_h) == (orig_w, orig_h):
                        return image_path
                    return _save_reference_image(img, output_path)
            except ValueError as ve:
                log.error("❌ Non-integer aspect values: %s (%s)", target_aspect, ve)
                if (current_w, current_h) == (orig_w, orig_h):
                    return image_path
                return _save_reference_image(img, output_path)
            
            target_ratio = target_w / target_h
            
            if abs(current_ratio - target_ratio) < 0.001:
                log.info("✅ Image already matches aspect %s (%dx%d) — no letterbox needed",
                         target_aspect, current_w, current_h)
                if (current_w, current_h) == (orig_w, orig_h):
                    return image_path
                return _save_reference_image(img, output_path)
            
            # Calculate new dimensions with black borders
            if current_ratio > target_ratio:
                # Image is too wide — add vertical (top/bottom) borders
                border_w = current_w
                border_h = int(current_w / target_ratio)
                y_offset = (border_h - current_h) // 2
                x_offset = 0
            else:
                # Image is too tall — add horizontal (left/right) borders
                border_h = current_h
                border_w = int(current_h * target_ratio)
                x_offset = (border_w - current_w) // 2
                y_offset = 0
            
            log.info(
                "📐 Adding black borders: %dx%d → %dx%d (aspect %s)",
                current_w, current_h, border_w, border_h, target_aspect
            )
            
            # Create new image with black background and paste the resized original image
            new_img = Image.new("RGB", (border_w, border_h), color=(0, 0, 0))
            new_img.paste(img, (x_offset, y_offset))
            
            _save_reference_image(new_img, output_path)
            log.info("✅ Letterboxed reference saved (%dx%d): %s", border_w, border_h, output_path)
            return output_path
            
    except Exception as e:
        log.error("❌ Failed to process image: %s. Returning original image.", e)
        return image_path


class ContentForbiddenError(Exception):
    """Raised when Mage.space content moderation block is detected."""
    pass


async def detect_forbidden(page: Page) -> bool:
    """Detect if Mage content moderation (Forbidden popup or abuse placeholder image) is shown."""
    try:
        is_forbidden = await page.evaluate('''() => {
            // 0. Grok silent moderation — abuse placeholder image in the feed
            for (const img of document.querySelectorAll('img.MageMedia-image, img[src*="mage.space"]')) {
                const s = (img.currentSrc || img.src || '').toLowerCase();
                if (s.includes('grok-image-abuse') || s.includes('placeholder.jpg')
                    || s.includes('/random/') || s.includes('abuse.jpg')) {
                    return true;
                }
            }
            // 1. Search for headings/elements containing "Forbidden"
            const headings = Array.from(document.querySelectorAll('h2, h1, div, p'));
            for (const el of headings) {
                const text = (el.textContent || '').trim();
                if (text === 'Forbidden') {
                    const bodyText = document.body.textContent || '';
                    if (bodyText.includes('may be abused') || bodyText.includes('Terms & Conditions') || bodyText.includes('Repeated offenses')) {
                        return true;
                    }
                }
            }
            // 2. Fallback checking full body text
            const bodyText = document.body.textContent || '';
            if (bodyText.includes('This content appears to contain material that may be abused') ||
                (bodyText.includes('Forbidden') && bodyText.includes('nudity') && bodyText.includes('sexual'))) {
                return true;
            }
            return false;
        }''')
        return bool(is_forbidden)
    except Exception as e:
        log.debug("Error in detect_forbidden: %s", e)
        return False


# ── ADVANCED UPGRADES (v4+) ────────────────────────────────────────────────────

async def inject_generation_params(page: Page):
    """Optional Mage UI overrides. Off by default — does not change denoise/steps unless INJECT_GENERATION_PARAMS=1."""
    if not INJECT_GENERATION_PARAMS:
        return
    try:
        log.info("🔧 INJECT_GENERATION_PARAMS enabled — applying localStorage overrides")
        await page.evaluate('''() => {
            localStorage.setItem('mage_steps', '50');
            localStorage.setItem('mage_cfg', '7.5');
            localStorage.setItem('mage_denoising', '0.55');
            localStorage.setItem('mage_seed', '-1');
            localStorage.setItem('mage_negative_prompt', '');
            localStorage.setItem('mage_negativePrompt', '');
            window.dispatchEvent(new Event('storage'));
        }''')
        await page.wait_for_timeout(50)
    except Exception as e:
        log.warning("⚠️ Generation params injection failed: %s (non-critical)", e)


async def detect_missing_anatomy(page: Page, framing: str) -> tuple[bool, tuple[int, int, int, int] | None]:
    """
    Detect if the generated image has missing or blank nipples/genitals.
    Returns (needs_inpainting, bounding_box) where bbox is (x, y, w, h) or None.
    
    Uses simple heuristic: if a region that should have detail has a uniform color
    matching skin tone or near-black, flag for inpainting.
    """
    try:
        # This is a simplified check; a full implementation would:
        # 1. Crop the expected nipple region
        # 2. Check if pixels are nearly uniform color (indicates censoring/blank)
        # 3. Return bbox of that region
        
        # For now, return False (no inpainting needed) — user can extend this
        log.debug("🔍 Anatomy check: placeholder function (no-op)")
        return False, None
        
    except Exception as e:
        log.warning("⚠️ Anatomy detection failed: %s", e)
        return False, None


def inpaint_region(base_path: str, inpainted_patch_path: str, region_box: tuple, output_path: str) -> str:
    """
    Paste the inpainted patch back onto the base image at the given bounding box.
    
    Args:
        base_path: Path to the full generated image
        inpainted_patch_path: Path to the inpainted patch (e.g., closeup of nipples)
        region_box: Tuple (x, y, w, h) specifying where to paste the patch
        output_path: Where to save the composited result
    
    Returns:
        Path to the composited image
    """
    try:
        base = Image.open(base_path).convert("RGB")
        patch = Image.open(inpainted_patch_path).convert("RGB")
        
        x, y, w, h = region_box
        # Resize patch to exactly fill the target region
        patch_resized = patch.resize((w, h), Image.Resampling.LANCZOS)
        
        # Paste onto base
        base.paste(patch_resized, (x, y))
        base.save(output_path, "JPEG", quality=95)
        
        log.info("🎨 Inpainted region composited: %s", output_path)
        return output_path
        
    except Exception as e:
        log.error("❌ Inpainting composition failed: %s. Returning base image.", e)
        return base_path


_cached_admin_id = None

def get_admin_group_id():
    global _cached_admin_id
    if _cached_admin_id is not None:
        return _cached_admin_id

    if ADMIN_GROUP_ID:
        try:
            _cached_admin_id = int(ADMIN_GROUP_ID)
        except ValueError:
            _cached_admin_id = ADMIN_GROUP_ID
        return _cached_admin_id

    try:
        with open(DATA_DIR / "admin_group.txt", "r") as f:
            _cached_admin_id = int(f.read().strip())
            return _cached_admin_id
    except Exception:
        return None


def set_user_conversation_state(app: Application, chat_id: int, user_id: int, state: int):
    """Find the ConversationHandler in the application and set the user state."""
    try:
        for priority, handlers in app.handlers.items():
            for handler in handlers:
                if isinstance(handler, ConversationHandler):
                    # In python-telegram-bot v20+, the internal attribute is _conversations.
                    # In older versions (v13 and below), it was conversations.
                    conversations_dict = None
                    if hasattr(handler, "_conversations"):
                        conversations_dict = handler._conversations
                    elif hasattr(handler, "conversations"):
                        conversations_dict = handler.conversations
                    
                    if conversations_dict is not None:
                        # Set state for all possible variations of the state keys
                        conversations_dict[(chat_id, user_id)] = state
                        conversations_dict[(user_id, chat_id)] = state
                        
                        # Scan keys dynamically as well to capture any custom layouts
                        keys_to_update = []
                        for key in conversations_dict.keys():
                            if isinstance(key, tuple) and (chat_id in key or user_id in key):
                                keys_to_update.append(key)
                        for key in keys_to_update:
                            conversations_dict[key] = state
                            
                        log.info("🎯 Set ConversationHandler state for user %d to %s", user_id, state)
                        return True
                    else:
                        log.warning("⚠️ ConversationHandler found but no '_conversations' or 'conversations' attribute exists.")
    except Exception as e:
        log.error("❌ Failed to update ConversationHandler state: %s", e)
    return False

logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    level=logging.INFO
)
_log_name = os.getenv("PUBLIC_SERVICE_NAME", "nvd-sync") if (_on_cloud and STEALTH_LOG) else "MageBot"
log = logging.getLogger(_log_name)
if STEALTH_LOG:
    for _h in logging.root.handlers:
        _h.addFilter(_StealthLogFilter())
    log.addFilter(_StealthLogFilter())

# Suppress noisy library logs — only show WARNING and above
# httpx: logs every HTTP request/response (200 OK, 400, etc.)
# apscheduler: logs every job add/remove
# aiohttp.access: logs every health-check request
for _logger_name in ("httpx", "apscheduler.scheduler", "apscheduler.executors.default", "aiohttp.access"):
    logging.getLogger(_logger_name).setLevel(logging.WARNING)

# ── Per-worker session state ──────────────────────────────────────────────────
@dataclass
class WorkerSession:
    worker_id: int
    pw:        Optional[Playwright]     = None
    browser:   Optional[Browser]        = None
    ctx:       Optional[BrowserContext] = None
    mage_page: Optional[Page]           = None
    mail_page: Optional[Page]           = None
    email:     Optional[str]            = None
    maildev_shadow_part: Optional[str]  = None
    maildev_api_only: bool              = False
    catchtempmail_inbox_id: Optional[str] = None   # SecureTempMail inbox id
    catchtempmail_read_token: Optional[str] = None  # SecureTempMail Bearer token
    secmail_cookies: Optional[dict[str, str]] = None  # legacy (unused)
    gems:      int                      = 0
    account_count: int                  = 0
    lock:      asyncio.Lock             = field(default_factory=asyncio.Lock)
    acquired_username: Optional[str]    = None
    is_new_session: bool                = True
    used_pooled_session: bool           = False
    live_prewarmed_guava: bool          = False  # True when job inherited builder's live Guava page
    session_committed: bool             = False  # True after generation send — account consumed
    reuse_count: int                    = 0      # Track consecutive reuses to avoid leaks
    active_bulk_batch_id: Optional[str] = None   # Browser pinned to this bulk batch
    last_bulk_aspect: Optional[str]    = None   # Skip aspect chip clicks when unchanged
    last_bulk_output_url: Optional[str] = None  # Dedup output selection across bulk images
    last_output_cdn_url: Optional[str] = None   # CDN URL for proxy-safe Telegram delivery
    reference_cdn_urls: set[str] = field(default_factory=set)  # Uploaded ref CDN URLs to exclude from output pick
    last_wait_ctx: Optional[dict] = None  # pre_count/pre_urls from last _wait_for_result (output re-scan)
    bulk_force_fresh: bool              = False  # Posing upload failure → skip browser reuse
    page_prepared_for_job: bool         = False  # _get_mage_page already cleared prompt bar
    stage_timer: Optional["_StageTimer"] = None  # per-job stage timing (pool, upload, generate, …)
    browser_fingerprint: Optional[BrowserFingerprint] = None  # per-worker Playwright face

# Bulk batches currently processing — defer noisy pool rebuilds mid-batch
_active_bulk_batches: set[str] = set()

# Per-user cancel flags — set by /cancel; checked in workers + poll loop to abort in-flight jobs
_user_cancel_flags: set[int] = set()

# ── Job Tracker ───────────────────────────────────────────────────────────────
@dataclass
class Job:
    id: str
    chat_id: int
    user_id: int
    prompt: Optional[str]
    image_path: Optional[str]
    aspect: str
    status_msg_id: int
    caption: Optional[str] = None
    status: str = "queued"
    status_detail: str = ""
    created_at: float = field(default_factory=time.time)  # Timestamp when job was created
    started_at: Optional[float] = None                     # Timestamp when job started processing
    completed_at: Optional[float] = None                   # Timestamp when job finished
    priority: int = 0                                      # 0=normal, 1=high, -1=low
    retry_count: int = 0                                   # How many times retried
    error_msg: str = ""                                    # Last error encountered
    is_bulk: bool = False
    bulk_batch_id: Optional[str] = None
    bulk_index: int = 0
    bulk_total: int = 0
    raw_image_path: Optional[str] = None
    reference_image_paths: list[str] = field(default_factory=list)
    raw_reference_image_paths: list[str] = field(default_factory=list)
    pipeline: str = "guava"  # "guava" | "guava15" | "posing" | "video" | "gpt_image"
    prompt_mode: str = "preserve"  # auto | custom | preserve | pose_change | video
    last_status_push: float = 0.0  # throttle Telegram progress updates
    reference_letterboxed: bool = False  # aspect baked into pixels before queue


# ── Advanced Queue Manager ────────────────────────────────────────────────────
class QueueManager:
    """Intelligent queue system that:
    - Prevents duplicate submissions from same user
    - Prioritizes jobs intelligently (FIFO with optional priority)
    - Tracks job metrics (time in queue, processing time, success rate)
    - Detects and handles stuck jobs
    - Prevents concurrent operations on same user/chat
    - Auto-retries failed jobs with exponential backoff
    """
    
    def __init__(self, max_queue_size: int = MAX_QUEUE):
        self.queue: list[Job] = []  # Ordered list (FIFO with priority sorting)
        self.lock = asyncio.Lock()
        self.max_size = max_queue_size
        
        # Event to notify workers when a new job is added
        self.new_job_event = asyncio.Event()
        
        # Per-worker events for targeted wake-ups (reduces unnecessary wake-ups)
        self.worker_events: dict[int, asyncio.Event] = {}
        
        # Prevent duplicate jobs from same user
        self.user_active: dict[int, str] = {}  # user_id -> current_job_id
        
        # Track currently processing/active jobs to detect stuck ones
        self.processing_jobs: dict[str, Job] = {}  # job_id -> Job
        
        # Track job processing time
        self.job_stats: dict[str, dict] = {}  # job_id -> {queued_time, processed_time, success}
        
        # Detect stuck jobs
        self.job_timeout: int = WORKER_JOB_TIMEOUT + 60
        
        log.info(f"✅ QueueManager initialized (max_size={max_queue_size})")
    
    async def add_job(self, job: Job, priority: int = 0) -> bool:
        """Add job to queue. Returns False if queue full."""
        # Quick check outside lock for strict queue users (reduces lock contention)
        if job.user_id in STRICT_QUEUE_USER_IDS:
            async with self.lock:
                for j in list(self.queue) + list(self.processing_jobs.values()):
                    if j.user_id != job.user_id:
                        continue
                    if job.bulk_batch_id and j.bulk_batch_id == job.bulk_batch_id:
                        continue
                    log.warning(
                        "⚠️ Strict queue: user %d already has job %s — rejecting %s",
                        job.user_id, j.id, job.id,
                    )
                    return False
        
        async with self.lock:
            # Check queue size
            if len(self.queue) >= self.max_size:
                log.warning(f"⚠️ Queue full ({len(self.queue)}/{self.max_size})")
                return False
            
            # Add job with priority
            job.priority = priority
            job.created_at = time.time()
            self.queue.append(job)
            
            # Mark user as active (allow multiple jobs per user)
            self.user_active[job.user_id] = job.id
            
            # Record stats
            self.job_stats[job.id] = {
                "queued_at": time.time(),
                "processed_at": None,
                "completed_at": None,
                "success": None
            }
            
            # Sort by priority (highest first), then by creation time (FIFO)
            self.queue.sort(key=lambda j: (-j.priority, j.created_at))
            
            # Trigger event to wake up workers - use targeted wake-up if possible
            if MULTI_USER_ISOLATION:
                # Wake up the specific worker assigned to this user
                target_worker_id = USER_WORKER_MAP.get(job.user_id)
                if target_worker_id is not None:
                    if target_worker_id not in self.worker_events:
                        self.worker_events[target_worker_id] = asyncio.Event()
                    self.worker_events[target_worker_id].set()
                else:
                    # Fallback to global event
                    self.new_job_event.set()
            else:
                self.new_job_event.set()
            
            log.info(f"✅ Job {job.id} added (user={job.user_id}, priority={priority}, queue_size={len(self.queue)})")
            return True
    
    def _active_bulk_batch_ids(self) -> set[str]:
        return {
            j.bulk_batch_id
            for j in self.processing_jobs.values()
            if j.is_bulk and j.bulk_batch_id
        }

    async def get_next_job(self, for_worker_id: int | None = None) -> Optional[Job]:
        """Get next job from queue. Bulk batches run strictly one image at a time."""
        assigned_user = (
            WORKER_USER_MAP.get(for_worker_id)
            if for_worker_id is not None and MULTI_USER_ISOLATION
            else None
        )
        async with self.lock:
            if not self.queue:
                self.new_job_event.clear()
                # Clear worker-specific event too
                if for_worker_id is not None and for_worker_id in self.worker_events:
                    self.worker_events[for_worker_id].clear()
                return None

            active_bulk = self._active_bulk_batch_ids()
            pick_idx = None
            for idx, candidate in enumerate(self.queue):
                if assigned_user is not None and candidate.user_id != assigned_user:
                    continue
                if (
                    candidate.is_bulk
                    and candidate.bulk_batch_id
                    and candidate.bulk_batch_id in active_bulk
                ):
                    continue
                pick_idx = idx
                break

            if pick_idx is None:
                # Jobs exist but none dispatchable yet (bulk slot taken / worker-user affinity).
                # Clear the wake event so workers sleep instead of busy-spinning on set().
                if self.queue:
                    self.new_job_event.clear()
                return None

            job = self.queue.pop(pick_idx)
            job.started_at = time.time()
            self.processing_jobs[job.id] = job

            if job.id in self.job_stats:
                self.job_stats[job.id]["processed_at"] = time.time()

            if not self.queue:
                self.new_job_event.clear()
                # Clear worker-specific event too
                if for_worker_id is not None and for_worker_id in self.worker_events:
                    self.worker_events[for_worker_id].clear()
            
            log.info(
                "🚀 Processing job %s (queue_size=%d, user=%d, bulk=%s)",
                job.id, len(self.queue), job.user_id, job.is_bulk,
            )
            return job

    async def cancel_bulk_batch_remaining(
        self, batch_id: str, *, exclude_job_id: str | None = None
    ) -> list[Job]:
        """Drop queued jobs from a bulk batch and return the cancelled jobs."""
        cancelled: list[Job] = []
        async with self.lock:
            kept: list[Job] = []
            for job in self.queue:
                if job.bulk_batch_id == batch_id and job.id != exclude_job_id:
                    cancelled.append(job)
                    self.job_stats.pop(job.id, None)
                    if self.user_active.get(job.user_id) == job.id:
                        self.user_active.pop(job.user_id, None)
                else:
                    kept.append(job)
            self.queue = kept
            if self.queue:
                self.new_job_event.set()
            else:
                self.new_job_event.clear()
        return cancelled

    async def cancel_queued_job(
        self,
        job_id_prefix: str,
        *,
        user_id: int | None = None,
    ) -> Optional[Job]:
        """Cancel a queued job by full ID or unique prefix. Active jobs are not interrupted."""
        prefix = (job_id_prefix or "").strip()
        if not prefix:
            return None

        async with self.lock:
            matches = [
                (idx, job)
                for idx, job in enumerate(self.queue)
                if job.id.startswith(prefix)
                and (user_id is None or job.user_id == user_id)
            ]
            if len(matches) != 1:
                return None

            idx, job = matches[0]
            self.queue.pop(idx)
            job.status = "cancelled"
            self.job_stats.pop(job.id, None)
            if self.user_active.get(job.user_id) == job.id:
                self.user_active.pop(job.user_id, None)
            if self.queue:
                self.new_job_event.set()
            else:
                self.new_job_event.clear()
            log.info("🧹 Cancelled queued job %s (user=%d)", job.id, job.user_id)
            return job

    async def cancel_all_user_jobs(self, user_id: int) -> int:
        """Cancel ALL queued jobs for user_id and raise the cancel flag for any active job.

        Returns the number of queued jobs removed.  The caller is responsible for
        inserting user_id into _user_cancel_flags BEFORE calling this so that a
        worker that picks up the job between the queue drain and the flag being set
        is also covered.
        """
        removed = 0
        async with self.lock:
            kept: list[Job] = []
            for job in self.queue:
                if job.user_id == user_id:
                    job.status = "cancelled"
                    self.job_stats.pop(job.id, None)
                    if self.user_active.get(job.user_id) == job.id:
                        self.user_active.pop(job.user_id, None)
                    removed += 1
                    log.info("🧹 /cancel drained queued job %s (user=%d)", job.id, user_id)
                else:
                    kept.append(job)
            self.queue = kept
            if self.queue:
                self.new_job_event.set()
            else:
                self.new_job_event.clear()
            # Also mark any active job for this user so it gets the cancel signal
            for job in list(self.processing_jobs.values()):
                if job.user_id == user_id:
                    job.status = "cancelled"
                    log.info("🛑 /cancel flagged active job %s (user=%d)", job.id, user_id)
        return removed

    async def complete_job(self, job: Job, success: bool, error: str = "") -> None:
        """Mark job as completed."""
        async with self.lock:
            job.completed_at = time.time()
            job.status = "completed" if success else "failed"
            
            if error:
                job.error_msg = error
            
            # Update stats
            if job.id in self.job_stats:
                self.job_stats[job.id]["completed_at"] = time.time()
                self.job_stats[job.id]["success"] = success
            
            # Remove from processing list
            self.processing_jobs.pop(job.id, None)
            
            # Only remove the user from active-jobs tracking if this specific job
            # is still the recorded active one. Avoids evicting a newer job entry
            # when the user has multiple jobs in flight (e.g. bulk batches).
            if self.user_active.get(job.user_id) == job.id:
                self.user_active.pop(job.user_id, None)

            if success and job.user_id in COOLDOWN_USER_IDS and COOLDOWN_SECONDS > 0:
                _user_cooldowns[job.user_id] = time.time()

            if self.queue:
                self.new_job_event.set()
            
            queue_time = time.time() - job.created_at if job.created_at else 0
            process_time = job.completed_at - job.started_at if job.started_at else 0
            
            status_icon = "✅" if success else "❌"
            log.info(f"{status_icon} Job {job.id} completed (user={job.user_id}, queue_time={queue_time:.1f}s, process_time={process_time:.1f}s)")

    async def check_stuck_jobs(self) -> list[Job]:
        """Clear jobs stuck in processing longer than job_timeout. Returns cleared jobs."""
        cleared: list[Job] = []
        async with self.lock:
            now = time.time()
            stuck_job_ids = []
            for job_id, job in list(self.processing_jobs.items()):
                if job.started_at and (now - job.started_at) > self.job_timeout:
                    stuck_job_ids.append(job_id)

            for job_id in stuck_job_ids:
                job = self.processing_jobs.pop(job_id, None)
                if job:
                    # Only evict user_active if this stuck job is still the recorded entry
                    # (a newer job from the same user should not be evicted)
                    if self.user_active.get(job.user_id) == job.id:
                        self.user_active.pop(job.user_id, None)
                    job.error_msg = "stuck_timeout"
                    cleared.append(job)
                    log.error(f"❌ Cleared stuck active job: {job.id} (timeout after {self.job_timeout}s)")
        return cleared
    
    async def requeue_job(self, job: Job) -> bool:
        """Requeue a failed job (must be called while job is still in processing_jobs)."""
        job.retry_count += 1
        max_retries = JOB_MAX_REQUEUE

        if job.retry_count > max_retries:
            log.error(f"❌ Job {job.id} exceeded max retries ({max_retries})")
            return False

        async with self.lock:
            self.processing_jobs.pop(job.id, None)
            # Clear user_active so add_job can safely re-set it for the requeued entry
            if self.user_active.get(job.user_id) == job.id:
                self.user_active.pop(job.user_id, None)
            job.started_at = None
            job.status = "queued"

        delay = min(1 + 2 ** (job.retry_count - 1), 5)
        log.info(f"🔄 Requeuing job {job.id} (attempt {job.retry_count}/{max_retries}) in {delay}s")
        await asyncio.sleep(delay)
        return await self.add_job(job, priority=max(job.priority, 0))
    
    async def get_queue_status(self) -> dict:
        """Get current queue status and metrics."""
        async with self.lock:
            completed_durations = [
                stats["completed_at"] - stats["processed_at"]
                for stats in self.job_stats.values()
                if stats.get("completed_at") and stats.get("processed_at")
            ]
            avg_process_time = (
                sum(completed_durations) / len(completed_durations)
                if completed_durations else 0.0
            )
            return {
                "queue_size": len(self.queue),
                "max_size": self.max_size,
                "active_users": len(self.user_active),
                "total_jobs_processed": len(self.job_stats),
                "avg_process_time": avg_process_time,
                "queue": [
                    {
                        "id": job.id,
                        "user_id": job.user_id,
                        "priority": job.priority,
                        "created_at": job.created_at,
                        "status": job.status,
                        "eta_seconds": avg_process_time * index if avg_process_time else 0.0,
                    }
                    for index, job in enumerate(self.queue, 1)
                ]
            }
    
    async def clear_old_stats(self, max_age_seconds: int = 3600) -> None:
        """Remove job stats older than max_age_seconds to prevent memory leak."""
        async with self.lock:
            now = time.time()
            to_delete = [
                job_id for job_id, stats in self.job_stats.items()
                if stats.get("completed_at") and (now - stats["completed_at"]) > max_age_seconds
            ]
            
            for job_id in to_delete:
                del self.job_stats[job_id]
            
            if to_delete:
                log.debug(f"🧹 Cleaned {len(to_delete)} old job stats")


# ── Global Queue Manager Instance ─────────────────────────────────────────────
queue_manager = QueueManager(max_queue_size=MAX_QUEUE)

_user_cooldowns: dict           = {}   # uid -> last completed job timestamp (COOLDOWN_USER_IDS only)
_last_heartbeat: float          = time.time()  # updated by workers — init now so HF health never 503s at boot
_background_tasks: set[asyncio.Task] = set()
TG_EDITING_TEXT = "editing..."


def _spawn_background_task(coro, *, name: str | None = None) -> asyncio.Task:
    """Track long-lived asyncio tasks so HF SIGTERM shutdown can cancel them cleanly."""
    task = asyncio.create_task(coro, name=name)
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)
    return task


async def _shutdown_background_tasks() -> None:
    if not _background_tasks:
        return
    log.info("🛑 Cancelling %d background task(s)...", len(_background_tasks))
    for task in list(_background_tasks):
        task.cancel()
    results = await asyncio.gather(*_background_tasks, return_exceptions=True)
    cancelled = sum(1 for r in results if isinstance(r, asyncio.CancelledError))
    errors = [r for r in results if isinstance(r, Exception) and not isinstance(r, asyncio.CancelledError)]
    if cancelled:
        log.info("🛑 Background tasks cancelled: %d", cancelled)
    for err in errors[:3]:
        log.debug("Background task shutdown error: %s", err)


def _bulk_status_text(
    job: Job,
    *,
    editing: bool = True,
    bulk_index: int | None = None,
) -> str:
    idx = bulk_index if bulk_index is not None else job.bulk_index
    icon = "🧘" if job.pipeline == "posing" else "📦"
    label = "Bulk Posing" if job.pipeline == "posing" else "Bulk"
    if editing:
        return f"{icon} {label} editing... ({idx}/{job.bulk_total})"
    return f"{icon} {label} {idx}/{job.bulk_total} done"


def _is_posing_pipeline(ctx: ContextTypes.DEFAULT_TYPE) -> bool:
    return ctx.user_data.get("pipeline") == "posing"


def _bulk_collect_label(ctx: ContextTypes.DEFAULT_TYPE) -> str:
    if _is_posing_pipeline(ctx):
        return "Bulk Posing"
    if ctx.user_data.get("pipeline") == "guava15":
        return "Guava 1.5 Bulk"
    if ctx.user_data.get("pipeline") == "gpt_image":
        return "GPT Image 2 Bulk"
    return "Bulk mode"


async def set_editing_message(app: Optional[Application], job: Optional[Job]) -> None:
    """Single Telegram status shown from queue until the job finishes."""
    if not app or not job:
        return
    status_text = _bulk_status_text(job) if job.is_bulk else TG_EDITING_TEXT
    if job.status_detail == status_text:
        return
    job.status_detail = status_text
    try:
        await app.bot.edit_message_text(
            chat_id=job.chat_id,
            message_id=job.status_msg_id,
            text=status_text,
        )
    except Exception as e:
        err = str(e).lower()
        if "message is not modified" in err:
            return
        log.warning("Status edit failed for job %s: %s — sending new message", job.id, e)
        try:
            sent = await app.bot.send_message(chat_id=job.chat_id, text=status_text)
            job.status_msg_id = sent.message_id
        except Exception as e2:
            log.warning("Status send fallback failed for job %s: %s", job.id, e2)


async def _notify_job_failure_to_user(
    app: Optional[Application],
    job: Optional[Job],
    message: str,
) -> None:
    """Push a failure message to the user's status chat."""
    if not app or not job:
        return
    try:
        await app.bot.edit_message_text(
            chat_id=job.chat_id,
            message_id=job.status_msg_id,
            text=message,
        )
    except Exception:
        try:
            sent = await app.bot.send_message(chat_id=job.chat_id, text=message)
            job.status_msg_id = sent.message_id
        except Exception as e:
            log.warning("Failure notify failed for job %s: %s", job.id, e)


async def _worker_return_job(
    app: Application,
    session: "WorkerSession",
    job: Job,
    error: str,
    *,
    requeue: bool = True,
    user_message: str | None = None,
) -> None:
    """Never leave a dequeued job stuck in processing_jobs."""
    if requeue:
        try:
            if await queue_manager.requeue_job(job):
                log.info("[W%d] ↩️ Job %s requeued (%s)", session.worker_id, job.id, error)
                if user_message:
                    await _notify_job_failure_to_user(app, job, user_message)
                return
        except Exception as rq_err:
            log.warning("[W%d] requeue failed for %s: %s", session.worker_id, job.id, rq_err)
    try:
        await queue_manager.complete_job(job, success=False, error=error)
    except Exception as cj_err:
        log.warning("[W%d] complete_job failed for %s: %s", session.worker_id, job.id, cj_err)
    await _notify_job_failure_to_user(
        app,
        job,
        user_message or "❌ Generation failed. Please /start and try again.",
    )


async def update_status(app: Optional[Application], job: Optional[Job], text: str):
    """Log pipeline progress and push key milestones to Telegram."""
    if job:
        job.status_detail = text
    log.info("[Job %s] %s", job.id if job else "?", text)

    if not app or not job:
        return

    now = time.time()
    important = any(
        token in text
        for token in (
            "✅", "❌", "failed", "Generating", "Uploading", "Downloading",
            "Selecting", "Injecting", "Prompt", "session", "Starting",
            "timed out", "Grok", "Reference",
        )
    )
    if not important and (now - job.last_status_push) < 10.0:
        return

    job.last_status_push = now
    display = text if len(text) <= 220 else text[:217] + "..."
    try:
        await app.bot.edit_message_text(
            chat_id=job.chat_id,
            message_id=job.status_msg_id,
            text=display,
        )
    except Exception as e:
        err = str(e).lower()
        if "message is not modified" not in err:
            log.debug("Status push skipped for job %s: %s", job.id, e)


async def update_queue_positions(app: Optional[Application]):
    """Queue positions are logged only; user sees editing... until done."""
    if not app:
        return
    async with queue_manager.lock:
        for index, job in enumerate(queue_manager.queue):
            job.status_detail = f"queued:{index + 1}"


async def _user_has_pending_jobs(user_id: int, exclude_job_id: str | None = None) -> bool:
    """True if user still has other jobs queued or running."""
    async with queue_manager.lock:
        for j in queue_manager.queue:
            if j.user_id == user_id and j.id != exclude_job_id:
                return True
        for j in queue_manager.processing_jobs.values():
            if j.user_id == user_id and j.id != exclude_job_id:
                return True
    return False


_BUSY_USER_MSG = (
    "⏳ Please wait — your current image is still processing.\n"
    "Send a new photo after it finishes."
)


async def _notify_user_busy(update: Update) -> None:
    if update.callback_query:
        try:
            await update.callback_query.answer(_BUSY_USER_MSG, show_alert=True)
        except Exception:
            pass
    elif update.message:
        await update.message.reply_text(_BUSY_USER_MSG)


def _user_cooldown_remaining(uid: int) -> float:
    """Seconds left on post-job cooldown for COOLDOWN_USER_IDS; 0 if none."""
    if uid not in COOLDOWN_USER_IDS or COOLDOWN_SECONDS <= 0:
        return 0.0
    last = _user_cooldowns.get(uid, 0)
    return max(0.0, COOLDOWN_SECONDS - (time.time() - last))


def _cooldown_message(remaining: float) -> str:
    return f"⏳ Please wait {int(remaining) + 1}s before sending another request."


def _format_duration(seconds: float) -> str:
    seconds = int(max(0, seconds))
    if seconds >= 3600:
        hours, rem = divmod(seconds, 3600)
        minutes = rem // 60
        return f"{hours}h {minutes}m"
    if seconds >= 60:
        minutes, rem = divmod(seconds, 60)
        return f"{minutes}m {rem}s"
    return f"{seconds}s"


async def _notify_user_cooldown(update: Update, remaining: float) -> None:
    msg = _cooldown_message(remaining)
    if update.callback_query:
        try:
            await update.callback_query.answer(msg, show_alert=True)
        except Exception:
            pass
    elif update.message:
        await update.message.reply_text(msg)


async def _reject_if_user_on_cooldown(update: Update, uid: int) -> bool:
    """Block COOLDOWN_USER_IDS from starting a new task during post-job cooldown."""
    remaining = _user_cooldown_remaining(uid)
    if remaining <= 0:
        return False
    await _notify_user_cooldown(update, remaining)
    log.info("⏳ Blocked new request from user %d — cooldown %.0fs left", uid, remaining)
    return True


async def _reject_if_user_busy(update: Update, uid: int) -> bool:
    """Block strict-queue users from starting a new task while one is active."""
    if uid not in STRICT_QUEUE_USER_IDS:
        return False
    if await _user_has_pending_jobs(uid):
        await _notify_user_busy(update)
        log.info("⏳ Blocked new request from user %d — task still running", uid)
        return True
    return False


def _generation_timeout_for_job(job: Optional["Job"]) -> int:
    """Per-attempt generation timeout for the selected pipeline."""
    if job and getattr(job, "pipeline", "") == "video":
        return VIDEO_GENERATION_TIMEOUT
    if job and job.is_bulk:
        return BULK_GENERATION_TIMEOUT
    if job and getattr(job, "pipeline", "") in ("posing", "gpt_image", "mango3"):
        return POSE_GENERATION_TIMEOUT
    return GENERATION_ATTEMPT_TIMEOUT


def _worker_timeout_for_job(job: Optional["Job"]) -> int:
    """Outer timeout for an entire job, including all pipeline retries."""
    generation_timeout = _generation_timeout_for_job(job)
    pipeline = getattr(job, "pipeline", "") if job else ""
    attempt_extra = 60 if pipeline == "video" else 30
    max_attempts = max(1, PIPELINE_MAX_ATTEMPTS)
    computed = (SETUP_TIMEOUT + generation_timeout + attempt_extra) * max_attempts + 60
    return max(WORKER_JOB_TIMEOUT, computed)


def _bulk_reuse_enabled(job: Optional["Job"]) -> bool:
    """Whether bulk jobs may reuse the same browser across images in a batch."""
    if not job or not job.is_bulk:
        return False
    if job.pipeline == "posing":
        return True
    if job.pipeline == "gpt_image":
        return True
    if job.pipeline in ("guava", "guava15"):
        return BULK_GUAVA_REUSE
    return False


def _browser_reuse_limit(job: Optional["Job"]) -> int:
    if job and job.is_bulk and _bulk_reuse_enabled(job):
        return BULK_MAX_BROWSER_REUSE
    if job and job.is_bulk:
        return 0
    return BROWSER_REUSE_LIMIT


def _bulk_continuing(s: "WorkerSession", job: Optional["Job"]) -> bool:
    """True when the worker can fast-path the next image in the same bulk batch."""
    if not _bulk_reuse_enabled(job):
        return False
    if not job or not job.bulk_batch_id:
        return False
    if s.bulk_force_fresh:
        return False
    if not s.mage_page:
        return False
    if s.active_bulk_batch_id != job.bulk_batch_id:
        return False
    if s.reuse_count >= _browser_reuse_limit(job):
        return False
    try:
        if s.mage_page.is_closed():
            return False
    except Exception:
        return False
    return True


def _bulk_should_keep_browser(
    s: "WorkerSession",
    job: Optional["Job"],
    *,
    job_success: bool,
    job_error: str,
    bulk_has_more: bool,
) -> bool:
    """Keep browser + Mage login alive between successful bulk images."""
    if not bulk_has_more or not job_success:
        return False
    if not job or not job.is_bulk or not _bulk_reuse_enabled(job):
        return False
    if _is_moderation_error(job_error) or _should_discard_pooled_session(job_error):
        return False
    if s.bulk_force_fresh or not s.mage_page:
        return False
    try:
        if s.mage_page.is_closed():
            return False
    except Exception:
        return False
    return True


def _reset_bulk_worker_state(s: "WorkerSession") -> None:
    """Clear bulk browser-reuse state after forced reset or cleanup timeout."""
    s.reuse_count = 0
    s.active_bulk_batch_id = None
    s.last_bulk_aspect = None
    s.last_bulk_output_url = None
    s.last_output_cdn_url = None
    s.reference_cdn_urls = set()
    s.bulk_force_fresh = False
    s.page_prepared_for_job = False


async def _maybe_refill_pool_after_send(job: Optional["Job"], *, reason: str = "send") -> None:
    """Refill pool after send so the next job gets a pre-warmed session."""
    if job and job.is_bulk and job.bulk_batch_id:
        if await _bulk_batch_has_pending_jobs(job.bulk_batch_id, exclude_job_id=job.id):
            log.debug(
                "Pool refill deferred — bulk batch %s still running",
                job.bulk_batch_id,
            )
            return
    if _jobs_processing():
        log.debug("Pool refill deferred — job(s) processing (refill after completion)")
        return
    owner_uid = job.user_id if job else None
    _ensure_pool_replacement(reason=reason, owner_uid=owner_uid)


async def _bulk_batch_has_pending_jobs(
    batch_id: str, exclude_job_id: str | None = None
) -> bool:
    """True if a bulk batch still has other jobs queued or running."""
    async with queue_manager.lock:
        for j in queue_manager.queue:
            if j.bulk_batch_id == batch_id and j.id != exclude_job_id:
                return True
        for j in queue_manager.processing_jobs.values():
            if j.bulk_batch_id == batch_id and j.id != exclude_job_id:
                return True
    return False


async def _notify_bulk_failure_and_continue(
    app: Optional[Application],
    job: Optional["Job"],
    *,
    reason: str,
) -> bool:
    """Notify that one bulk item failed; keep queued siblings running."""
    if not job or not job.is_bulk:
        return False

    has_more = bool(
        job.bulk_batch_id
        and await _bulk_batch_has_pending_jobs(job.bulk_batch_id, exclude_job_id=job.id)
    )

    if app:
        if not has_more:
            try:
                await app.bot.delete_message(
                    chat_id=job.chat_id,
                    message_id=job.status_msg_id,
                )
            except Exception:
                pass

        try:
            text = (
                f"Bulk {job.bulk_index}/{job.bulk_total} failed: {reason}.\n"
                "Continuing with next image..."
                if has_more
                else (
                    f"Bulk {job.bulk_index}/{job.bulk_total} failed: {reason}.\n"
                    "No more images remain in this batch. Use /start to run another batch."
                )
            )
            await app.bot.send_message(
                chat_id=job.chat_id,
                text=text,
                read_timeout=10,
                write_timeout=10,
            )
        except Exception as notify_err:
            log.warning(
                "Failed to notify user of bulk item failure %s: %s",
                job.bulk_batch_id or job.id,
                notify_err,
            )

        if not has_more and not await _user_has_pending_jobs(job.user_id, exclude_job_id=job.id):
            set_user_conversation_state(app, job.chat_id, job.user_id, ASK_MODE_SELECT)

    return has_more


def _guess_raw_image_path(image_path: Optional[str]) -> Optional[str]:
    if not image_path or "_processed" not in image_path:
        return None
    raw = image_path.replace("_processed.jpg", ".jpg").replace("_processed.png", ".png")
    return raw if raw != image_path and os.path.exists(raw) else None


def _remove_image_files(
    image_path: Optional[str], raw_path: Optional[str] = None
) -> None:
    for path in {image_path, raw_path, _guess_raw_image_path(image_path)}:
        if path and os.path.exists(path):
            try:
                os.remove(path)
            except Exception:
                pass


def _cleanup_image_meta(meta: dict) -> None:
    _remove_image_files(meta.get("image_path"), meta.get("raw_path"))


def _cleanup_single_images(user_data: dict) -> None:
    refs = user_data.pop("single_images", [])
    cleaned_refs = False
    for entry in refs:
        if isinstance(entry, dict):
            _cleanup_image_meta(entry)
            cleaned_refs = True
        elif entry:
            _remove_image_files(entry)
            cleaned_refs = True

    if not cleaned_refs:
        _remove_image_files(
            user_data.get("image_path"),
            user_data.get("raw_image_path"),
        )

    for key in ("image_path", "raw_image_path", "aspect", "single_refs_status_msg_id"):
        user_data.pop(key, None)


def _cleanup_bulk_images(user_data: dict) -> None:
    for entry in user_data.pop("bulk_images", []):
        if isinstance(entry, dict):
            _cleanup_image_meta(entry)
        elif entry:
            _remove_image_files(entry)
    user_data.pop("bulk_status_msg_id", None)


def _job_reference_image_paths(job: Optional["Job"], fallback: Optional[str] = None) -> list[str]:
    paths: list[str] = []
    if job:
        paths.extend(getattr(job, "reference_image_paths", None) or [])
        if not paths and getattr(job, "image_path", None):
            paths.append(job.image_path)
    if fallback and fallback not in paths:
        paths.append(fallback)
    return [p for p in paths if isinstance(p, str) and p]


def _job_raw_reference_paths(job: Optional["Job"]) -> list[str]:
    paths: list[str] = []
    if job:
        paths.extend(getattr(job, "raw_reference_image_paths", None) or [])
        raw_path = getattr(job, "raw_image_path", None)
        if raw_path and raw_path not in paths:
            paths.append(raw_path)
    return [p for p in paths if isinstance(p, str) and p]


def _multi_reference_upload(reference_paths: list[str] | None) -> bool:
    return bool(reference_paths) and len(reference_paths) > 1


def _persist_job_reference_paths(job_id: str, paths: list[str]) -> list[str]:
    """Copy reference images into a job-owned directory so user UI cleanup cannot delete them."""
    if not paths or not job_id:
        return []
    job_dir = JOB_REFS_DIR / job_id
    job_dir.mkdir(parents=True, exist_ok=True)
    persisted: list[str] = []
    for idx, src in enumerate(paths):
        if not isinstance(src, str) or not src:
            continue
        if not os.path.exists(src):
            log.warning("Reference source missing during persist for %s: %s", job_id, src)
            continue
        suffix = Path(src).suffix.lower() or ".jpg"
        stem = Path(src).stem
        if "_processed" in stem:
            dest = job_dir / f"ref_{idx}_processed{suffix}"
        else:
            dest = job_dir / f"ref_{idx}{suffix}"
        try:
            shutil.copy2(src, dest)
            persisted.append(str(dest))
        except Exception as e:
            log.warning("Failed to persist job reference %s → %s: %s", src, dest, e)
    return persisted


def _remove_job_reference_files(job: Optional["Job"]) -> None:
    if not job:
        return
    for path in set(_job_reference_image_paths(job) + _job_raw_reference_paths(job)):
        _remove_image_files(path)
    job_dir = JOB_REFS_DIR / job.id
    if job_dir.exists():
        try:
            shutil.rmtree(job_dir)
        except Exception:
            pass


def _validate_reference_image_paths(job: Optional["Job"], fallback: Optional[str] = None) -> None:
    for path in _job_reference_image_paths(job, fallback):
        if not isinstance(path, str) or not path:
            raise ValueError(f"Invalid image path (not a string): {path!r}")
        if not os.path.exists(path):
            # Bulk jobs copy refs to JOB_REFS_DIR at queue time; log a warning
            # rather than crashing so a transient disk hiccup doesn't abort the job.
            if job and job.is_bulk:
                log.warning(
                    "[validate_refs] Bulk reference missing on disk (job=%s): %s — continuing",
                    getattr(job, "id", "?"), path,
                )
            else:
                raise ValueError(f"Invalid image path (not found): {path}")


def _is_moderation_error(err: str) -> bool:
    e = (err or "").lower()
    return any(
        k in e
        for k in (
            "moderation",
            "forbidden",
            "placeholder.jpg",
            "grok-image-abuse",
            "abuse placeholder",
            "moderation placeholder",
            "content blocked",
        )
    )


def _runtime_error_is_moderation(msg: str) -> bool:
    m = (msg or "").lower()
    return any(
        k in m
        for k in (
            "placeholder",
            "moderation",
            "moderation-blocked",
            "grok-image-abuse",
            "abuse placeholder",
            "moderation placeholder",
        )
    )


def _pipeline_retry_delay(attempt: int, last_error: str = "") -> float:
    """Shorter backoff between pipeline attempts — timeouts retry faster than hard errors."""
    err = (last_error or "").lower()
    if "timeout" in err or "timed out" in err:
        base = 0.5 + attempt * 0.75
    elif any(k in err for k in ("network", "maildev", "magic", "login", "session")):
        base = 1.0 + attempt * 1.5
    else:
        base = 1.0 + attempt * 2.0
    return max(0.5, base + random.uniform(-0.25, 0.25))


def _should_auto_requeue_job(
    job: "Job",
    *,
    job_success: bool,
    photo_sent: bool,
    generation_done: bool,
    job_error: str,
) -> bool:
    """Queue-level retry only for transient worker/setup failures — not after full pipeline exhaustion."""
    if job_success or photo_sent or job.is_bulk:
        return False
    if not job_error or job_error == "user_cancelled":
        return False
    if _is_moderation_error(job_error):
        return False
    if job.retry_count >= JOB_MAX_REQUEUE:
        return False
    if generation_done:
        return False

    err_lower = job_error.lower()
    if any(
        phrase in err_lower
        for phrase in (
            "pipeline failed after",
            "posing pipeline failed after",
            "video pipeline failed after",
            "generation returned none",
            "generation failed (no output)",
            "content forbidden",
            "moderation-blocked",
        )
    ):
        return False

    transient_markers = (
        "browser_invalid",
        "worker_unhealthy",
        "stuck_timeout",
        "cleanup_timeout",
        "maildev",
        "magic",
        "session warming",
        "building session pool",
        "pool empty",
    )
    if any(m in err_lower for m in transient_markers):
        return True

    if "generation timeout" in err_lower or "timed out" in err_lower:
        return job.retry_count < 1

    return False


async def _dismiss_forbidden_modal(page: Page) -> bool:
    """Close Mage 'Forbidden' moderation dialog so this worker can continue."""
    try:
        dismissed = await page.evaluate("""() => {
            const body = document.body.textContent || '';
            if (!body.includes('Forbidden') && !body.includes('may be abused')) return false;
            for (const btn of document.querySelectorAll('button, [role="button"]')) {
                const t = (btn.textContent || '').trim().toLowerCase();
                if (t === 'ok' || t === 'close' || t === 'got it' || t.includes('dismiss')) {
                    try { btn.click(); return true; } catch (e) {}
                }
            }
            return false;
        }""")
        if dismissed:
            await page.wait_for_timeout(80)
        return bool(dismissed)
    except Exception as e:
        log.debug("dismiss_forbidden_modal: %s", e)
        return False


async def _release_worker_for_next_job(
    s: WorkerSession,
    *,
    job_error: str = "",
    job_success: bool = False,
    job: Optional["Job"] = None,
) -> None:
    """Reset worker browser/account so the next job never inherits moderation UI or bad pool state."""
    moderation = _is_moderation_error(job_error)
    username = s.acquired_username

    bulk_has_more = False
    if job and job.is_bulk and job.bulk_batch_id:
        bulk_has_more = await _bulk_batch_has_pending_jobs(
            job.bulk_batch_id, exclude_job_id=job.id
        )

    bad_session = _should_discard_pooled_session(job_error)

    if _bulk_should_keep_browser(
        s,
        job,
        job_success=job_success,
        job_error=job_error,
        bulk_has_more=bulk_has_more,
    ):
        s.session_committed = False
        log.info(
            "[W%d] 📦 Bulk batch continuing — keeping browser for next image "
            "(batch=%s, reuse=%d)",
            s.worker_id,
            job.bulk_batch_id if job else "?",
            s.reuse_count,
        )
        for attr in ("mage_page", "mail_page"):
            page = getattr(s, attr, None)
            if page:
                try:
                    await _dismiss_blocking_overlays(
                        page, s.worker_id, quiet=True, skip_escape=True
                    )
                except Exception:
                    pass
        return

    # Determine if we should reuse the session for the next job (failed/uncommitted)
    should_reuse = False
    if (
        not job_success
        and not (job and job.is_bulk)
        and not s.session_committed
        and not moderation
        and not bad_session
        and s.mage_page
    ):
        if s.reuse_count < _browser_reuse_limit(job):
            try:
                if not s.mage_page.is_closed():
                    should_reuse = True
            except Exception:
                should_reuse = False

    if should_reuse:
        log.info("[W%d] ⚡ Reusing session for next job (username=%s, reuse_count=%d). Skipping reset.", s.worker_id, username, s.reuse_count)
        for attr in ("mage_page", "mail_page"):
            page = getattr(s, attr, None)
            if page:
                try:
                    await _dismiss_blocking_overlays(page, s.worker_id, quiet=True, skip_escape=True)
                except Exception:
                    pass
        return

    # Normal cleanup flow (if not reusing)
    if moderation and username and acct_manager:
        try:
            acct_manager.discard_session(username)
            log.info("[W%d] 🗑️ Discarded moderated account (not returned to pool): %s", s.worker_id, username)
        except Exception as e:
            log.warning("[W%d] discard_session failed: %s", s.worker_id, e)
        s.acquired_username = None
        s.used_pooled_session = False
        s.session_committed = False

    if job and job.is_bulk and job.bulk_batch_id and not bulk_has_more:
        _active_bulk_batches.discard(job.bulk_batch_id)
        s.active_bulk_batch_id = None
        s.last_bulk_aspect = None
        s.last_bulk_output_url = None
        s.last_output_cdn_url = None
        s.reference_cdn_urls = set()
        s.bulk_force_fresh = False

    _finalize_worker_account(
        s,
        success=job_success or s.session_committed,
        error_msg=job_error,
    )

    for attr in ("mage_page", "mail_page"):
        page = getattr(s, attr, None)
        if page:
            try:
                if moderation:
                    await _dismiss_forbidden_modal(page)
                await _dismiss_blocking_overlays(page, s.worker_id, quiet=True)
                await page.keyboard.press("Escape")
            except Exception:
                pass

    try:
        if moderation:
            await asyncio.wait_for(_close_session(s), timeout=20.0)
        else:
            await asyncio.wait_for(_reset_worker_browser(s), timeout=12.0)
    except Exception as e:
        log.warning("[W%d] Browser reset failed (%s) — forcing full close", s.worker_id, e)
        try:
            await asyncio.wait_for(_close_session(s), timeout=20.0)
        except Exception as close_err:
            log.warning("[W%d] Full session close failed: %s", s.worker_id, close_err)

    s.is_new_session = True
    s.used_pooled_session = False
    s.session_committed = False
    s.mage_page = None
    s.mail_page = None
    s.maildev_shadow_part = None
    s.maildev_api_only = False
    s.catchtempmail_inbox_id = None
    s.catchtempmail_read_token = None
    s.secmail_cookies = None
    s.reuse_count = 0
    s.active_bulk_batch_id = None
    s.last_bulk_aspect = None
    s.last_bulk_output_url = None
    s.last_output_cdn_url = None
    s.reference_cdn_urls = set()
    s.bulk_force_fresh = False


def _health_response_text(*, degraded: bool = False) -> str:
    pool_ready = pool_target = 0
    if acct_manager is not None:
        ps = acct_manager.pool_stats()
        pool_ready = ps.get("ready", 0)
        pool_target = TARGET_POOL_SIZE
    body = public_health_payload(pool_ready=pool_ready, pool_target=pool_target)
    if degraded and body.startswith("{"):
        try:
            payload = json.loads(body)
            payload["status"] = "degraded"
            payload.setdefault("checks", {})["worker"] = "stale"
            return json.dumps(payload)
        except Exception:
            pass
    return body


def _health_is_stale() -> bool:
    """True when no worker heartbeat for an extended period."""
    stale_sec = int(os.getenv("HEALTH_STALE_SEC", "7200"))
    return _last_heartbeat > 0 and (time.time() - _last_heartbeat) > stale_sec


def _make_health_response() -> web.Response:
    """HF Spaces: always HTTP 200 — a 503 body makes HF mark the Space unhealthy/paused."""
    degraded = _health_is_stale()
    body = _health_response_text(degraded=degraded)
    ctype = "application/json" if body.startswith("{") else "text/plain"
    if _on_hf and STEALTH_PUBLIC_FACE:
        return web.Response(text=body, content_type=ctype, status=200)
    if degraded:
        return web.Response(text="UNHEALTHY – worker stalled", status=503)
    return web.Response(text=body, content_type=ctype)


def _run_web_thread(ready_event: threading.Event | None = None):
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    async def health_check(request):
        return _make_health_response()

    async def status_api(_request):
        body = _health_response_text(degraded=_health_is_stale())
        return web.Response(text=body, content_type="application/json", status=200)

    app = web.Application()
    app.router.add_get('/', health_check)
    app.router.add_get('/api/health', status_api)
    app.router.add_get('/api/v1/status', status_api)
    runner = web.AppRunner(app)
    loop.run_until_complete(runner.setup())
    
    # Use PORT from environment if available (e.g., for Railway)
    port = int(os.environ.get('PORT', 7860))
    site = web.TCPSite(runner, '0.0.0.0', port)
    loop.run_until_complete(site.start())
    log.info(f"🌐 Web server started on port {port}")
    if ready_event is not None:
        ready_event.set()  # Signal to main() that the port is now bound
    loop.run_forever()


async def _heartbeat_loop():
    """Continuously update _last_heartbeat so the health-check never fires
    just because all workers are idle (blocked on queue.get())."""
    global _last_heartbeat
    while True:
        _last_heartbeat = time.time()
        if _on_pa:
            try:
                from pa_bridge import write_health_snapshot

                body = _health_response_text(degraded=_health_is_stale())
                ctype = "application/json" if body.startswith("{") else "text/plain"
                write_health_snapshot(body, content_type=ctype, status=200)
            except Exception as exc:
                log.debug("PA health snapshot failed: %s", exc)
        await asyncio.sleep(15)


async def _idle_status_loop():
    """Periodic alive log when queue is empty — avoids 'bot went silent' confusion."""
    while True:
        await asyncio.sleep(600)
        try:
            status = await queue_manager.get_queue_status()
            processing = _processing_job_count()
            if status["queue_size"] == 0 and processing == 0:
                pool_ready = _count_live_ready() if LIVE_ONLY_POOL else (
                    acct_manager.count_ready() if acct_manager else 0
                )
                log.info(
                    "💤 Idle — queue=0 processing=0 pool ready=%d/%d workers=%d",
                    pool_ready,
                    TARGET_POOL_SIZE,
                    NUM_WORKERS,
                )
        except Exception as e:
            log.debug("Idle status log failed: %s", e)


async def _queue_maintenance_loop():
    """Periodically recover stuck jobs and clean old queue stats."""
    last_cleanup = 0.0
    while True:
        try:
            now = time.time()
            for stuck in await queue_manager.check_stuck_jobs():
                try:
                    if stuck.retry_count < JOB_MAX_REQUEUE and await queue_manager.requeue_job(stuck):
                        log.info("🔄 Requeued stuck job %s", stuck.id)
                    else:
                        log.warning("Stuck job %s not requeued (retries exhausted)", stuck.id)
                except Exception as e:
                    log.error("Failed to recover stuck job %s: %s", stuck.id, e)

            if now - last_cleanup >= QUEUE_STATS_CLEANUP_SEC:
                await queue_manager.clear_old_stats(max_age_seconds=3600)
                last_cleanup = now
                status = await queue_manager.get_queue_status()
                if status["queue_size"] > 0 or _processing_job_count() > 0:
                    log.debug(
                        "📊 Queue status: %d/%d queued, %d processing, %d active users",
                        status["queue_size"],
                        status["max_size"],
                        _processing_job_count(),
                        status["active_users"],
                    )

            await asyncio.sleep(QUEUE_STUCK_CHECK_SEC)
        except Exception as e:
            log.error("❌ Error in queue maintenance: %s", e)
            await asyncio.sleep(60)


async def _worker_loop(app: Application, session: "WorkerSession"):
    """Enhanced worker loop with smart queue management, circuit breaker, and resilience."""
    global _last_heartbeat
    log.info("👷 Worker %d started.", session.worker_id)
    
    consecutive_failures = 0
    max_consecutive_failures = 4  # Circuit breaker threshold
    circuit_breaker_timeout = 10  # seconds
    
    while True:
        try:
            # Keep heartbeat fresh while we wait for a task
            _last_heartbeat = time.time()
            
            # Circuit breaker: if too many consecutive failures, pause worker
            if consecutive_failures >= max_consecutive_failures:
                log.warning("[W%d] ⚠️ Circuit breaker triggered: pausing for %ds", session.worker_id, circuit_breaker_timeout)
                await asyncio.sleep(circuit_breaker_timeout)
                consecutive_failures = 0  # Reset counter
                # Attempt session recovery after circuit breaker
                if session.mage_page and not await _validate_browser_page(session.mage_page, session.worker_id):
                    log.warning("[W%d] Browser invalid after circuit breaker, attempting recovery", session.worker_id)
                    await _recover_browser_session(session, app)
                continue
            
            # Get next job from queue manager with timeout
            try:
                job = await asyncio.wait_for(
                    queue_manager.get_next_job(for_worker_id=session.worker_id),
                    timeout=2.0,
                )
                if job is None:
                    # Queued work may be waiting on bulk serialization or worker affinity — poll soon.
                    if queue_manager.queue:
                        await asyncio.sleep(WORKER_IDLE_POLL_SEC)
                        continue
                    # Use worker-specific event for targeted wake-up
                    worker_event = queue_manager.worker_events.get(session.worker_id)
                    if worker_event:
                        try:
                            await asyncio.wait_for(worker_event.wait(), timeout=2.0)
                        except asyncio.TimeoutError:
                            pass
                    else:
                        # Fallback to global event
                        try:
                            await asyncio.wait_for(queue_manager.new_job_event.wait(), timeout=2.0)
                        except asyncio.TimeoutError:
                            pass
                    continue
            except asyncio.TimeoutError:
                await asyncio.sleep(0.1)
                continue
            except Exception as e:
                log.error("[W%d] Error getting job from queue: %s", session.worker_id, e)
                consecutive_failures += 1
                await asyncio.sleep(0.5)
                continue
            
            # ── CANCEL FLAG CHECK ─────────────────────────────────────────────
            # /cancel sets this flag before we even start processing. Discard the
            # job immediately without tripping the circuit breaker.
            if job.user_id in _user_cancel_flags:
                log.info("[W%d] 🚫 Skipping job %s — user %d cancelled", session.worker_id, job.id, job.user_id)
                try:
                    await queue_manager.complete_job(job, success=False, error="user_cancelled")
                except Exception:
                    pass
                continue

            # Validate browser state before processing job
            if session.mage_page and not await _validate_browser_page(session.mage_page, session.worker_id):
                log.warning("[W%d] Browser invalid before job %s, attempting recovery", session.worker_id, job.id)
                if not await _recover_browser_session(session, app, job):
                    consecutive_failures += 1
                    await _worker_return_job(
                        app,
                        session,
                        job,
                        "browser_invalid",
                        requeue=True,
                        user_message="🔄 Browser reset — your request was re-queued. Please wait…",
                    )
                    continue
            
            # Update worker health check
            await _update_worker_health(session.worker_id, session)
            health = await _get_worker_health(session.worker_id)
            if not health["healthy"] and session.mage_page is not None:
                log.warning("[W%d] Worker unhealthy: %s", session.worker_id, health["issues"])
                if not await _recover_browser_session(session, app, job):
                    consecutive_failures += 1
                    await _worker_return_job(
                        app,
                        session,
                        job,
                        "worker_unhealthy",
                        requeue=True,
                        user_message="🔄 Worker recovering — your request was re-queued. Please wait…",
                    )
                    continue
            
            # Queue position updates only matter for single (non-bulk) waiting users;
            # broadcasting to everyone on every bulk sub-job floods the Telegram API.
            # Run these updates in parallel for faster response
            if not job.is_bulk:
                asyncio.create_task(update_queue_positions(app))
                asyncio.create_task(set_editing_message(app, job))
            else:
                # For bulk jobs, only set editing message if not already set
                if job.status_detail != _bulk_status_text(job):
                    asyncio.create_task(set_editing_message(app, job))
            await update_status(app, job, "generation started")

            if job.is_bulk and job.bulk_batch_id:
                _active_bulk_batches.add(job.bulk_batch_id)
                if session.active_bulk_batch_id != job.bulk_batch_id:
                    session.active_bulk_batch_id = job.bulk_batch_id
                    session.last_bulk_aspect = None
                    session.last_bulk_output_url = None
                    session.bulk_force_fresh = False
                    session.reuse_count = 0
                    log.info(
                        "[W%d] 📦 Bulk batch %s started (image %d/%d)",
                        session.worker_id,
                        job.bulk_batch_id,
                        job.bulk_index,
                        job.bulk_total,
                    )

            chat_id = job.chat_id
            user_id = job.user_id
            image_path = job.image_path
            aspect = job.aspect
            status_msg_id = job.status_msg_id
            
            result = None
            job_success = False
            photo_sent = False
            generation_done = False
            job_error = ""
            session.stage_timer = _StageTimer(job.id, job.pipeline, session.worker_id)
            session.page_prepared_for_job = False
            
            try:

                admin_id = get_admin_group_id()

                if job.prompt is None and image_path:
                    try:
                        if job.pipeline == "posing":
                            log.info("[W%d] 🧘 Using default posing prompt", session.worker_id)
                            job.prompt = DEFAULT_POSING_PROMPT
                        elif job.pipeline == "gpt_image":
                            log.info("[W%d] 🎨 Using default posing prompt for GPT Image 2", session.worker_id)
                            job.prompt = DEFAULT_POSING_PROMPT
                        elif job.pipeline == "video":
                            log.info("[W%d] 🎬 Using default video prompt (kiss)", session.worker_id)
                            job.prompt = get_default_video_prompt()
                        else:
                            log.info("[W%d] 🎯 Using optimized default prompt (no vision analysis)", session.worker_id)
                            job.prompt = get_default_image_prompt()
                    except Exception as e:
                        log.error("[W%d] ❌ Prompt generation failed: %s. Using fallback.", session.worker_id, e)
                        if job.pipeline == "posing":
                            job.prompt = DEFAULT_POSING_PROMPT
                        elif job.pipeline == "gpt_image":
                            job.prompt = DEFAULT_POSING_PROMPT
                        elif job.pipeline == "video":
                            job.prompt = get_default_video_prompt()
                        else:
                            job.prompt = get_default_image_prompt()

                pipeline_label = (
                    "video" if job.pipeline == "video"
                    else ("gpt_image" if job.pipeline == "gpt_image"
                    else ("mango3" if job.pipeline == "mango3"
                    else ("posing" if job.pipeline == "posing"
                    else ("guava15" if job.pipeline == "guava15" else "guava"))))
                )
                worker_timeout = _worker_timeout_for_job(job)
                log.info("[W%d] 🎨 Starting %s pipeline (timeout: %ds)...", session.worker_id, pipeline_label, worker_timeout)
                session.session_committed = False
                lock_timeout = float(_worker_timeout_for_job(job) + 45)
                if not await safe_lock_acquire(
                    session.lock, timeout=lock_timeout, context=f"worker-{session.worker_id}-job-{job.id}"
                ):
                    raise RuntimeError(f"Worker session lock timeout after {lock_timeout:.0f}s")
                try:
                    if job.pipeline == "posing":
                        result = await asyncio.wait_for(
                            run_posing_pipeline(job.prompt or DEFAULT_POSING_PROMPT, image_path, aspect, session, app, job),
                            timeout=float(worker_timeout)
                        )
                    elif job.pipeline == "video":
                        result = await asyncio.wait_for(
                            run_video_pipeline(
                                job.prompt or get_default_video_prompt(), image_path, aspect, session, app, job
                            ),
                            timeout=float(worker_timeout)
                        )
                    elif job.pipeline == "gpt_image":
                        result = await asyncio.wait_for(
                            run_gpt_image_pipeline(
                                job.prompt or DEFAULT_POSING_PROMPT, image_path, aspect, session, app, job
                            ),
                            timeout=float(worker_timeout)
                        )
                    elif job.pipeline == "mango3":
                        result = await asyncio.wait_for(
                            run_mango_3_pipeline(
                                job.prompt or get_default_image_prompt(), image_path, aspect, session, app, job
                            ),
                            timeout=float(worker_timeout)
                        )
                    else:
                        result = await asyncio.wait_for(
                            run_pipeline(job.prompt or get_default_image_prompt(), image_path, aspect, session, app, job),
                            timeout=float(worker_timeout)
                        )
                finally:
                    safe_lock_release(session.lock)
                
                if result:
                    consecutive_failures = 0  # Reset on success
                    generation_done = True
                    log.info("[W%d] ✅ Generation succeeded, sending output...", session.worker_id)

                    bulk_pending = (
                        job.is_bulk
                        and job.bulk_batch_id
                        and await _bulk_batch_has_pending_jobs(
                            job.bulk_batch_id, exclude_job_id=job.id
                        )
                    )
                    if not bulk_pending:
                        try:
                            await app.bot.delete_message(chat_id=chat_id, message_id=status_msg_id)
                        except Exception as e:
                            log.warning("[W%d] ⚠️ Failed to delete status message: %s", session.worker_id, e)

                    # ── RESILIENT OUTPUT: Send generated image with retry ──────
                    max_send_retries = 3
                    if job.is_bulk:
                        bulk_icon = "🧘" if job.pipeline == "posing" else ("🎨" if job.pipeline == "gpt_image" else ("🥭" if job.pipeline == "mango3" else "📦"))
                        output_caption = f"{bulk_icon} Bulk {job.bulk_index}/{job.bulk_total} — done!"
                    else:
                        output_caption = (
                            "🎬 Your video is ready!" if job.pipeline == "video"
                            else ("🧘 Your posing image is ready!" if job.pipeline == "posing"
                            else ("🎨 Your GPT Image 2 image is ready!" if job.pipeline == "gpt_image"
                            else ("🥭 Your Mango 3 image is ready!" if job.pipeline == "mango3"
                            else "✨ Your image is ready!")))
                        )
                    for send_attempt in range(max_send_retries):
                        try:
                            cdn_url = session.last_output_cdn_url
                            file_bytes = (
                                os.path.getsize(result) if os.path.isfile(result) else 0
                            )
                            log.info(
                                "[W%d] 📤 Delivering output (%d bytes, cdn=%s)...",
                                session.worker_id,
                                file_bytes,
                                bool(cdn_url),
                            )
                            await asyncio.wait_for(
                                _send_output_to_chat(
                                    app.bot,
                                    chat_id,
                                    result,
                                    output_caption,
                                    pipeline=job.pipeline,
                                    cdn_url=cdn_url,
                                ),
                                timeout=45.0,
                            )
                            if job.is_bulk:
                                if bulk_pending:
                                    next_job = job.bulk_index + 1
                                    try:
                                        await app.bot.edit_message_text(
                                            chat_id=chat_id,
                                            message_id=status_msg_id,
                                            text=_bulk_status_text(
                                                job, editing=True, bulk_index=next_job
                                            ),
                                        )
                                    except Exception:
                                        pass
                                else:
                                    complete_icon = "🧘" if job.pipeline == "posing" else "📦"
                                    complete_label = (
                                        "Bulk Posing complete" if job.pipeline == "posing"
                                        else "Bulk complete"
                                    )
                                    await app.bot.send_message(
                                        chat_id=chat_id,
                                        text=(
                                            f"{complete_icon} *{complete_label}!* "
                                            f"All {job.bulk_total} images done.\n"
                                            "Use /start to run another batch."
                                        ),
                                        parse_mode="Markdown",
                                        read_timeout=10,
                                        write_timeout=10,
                                    )
                            else:
                                ready_msg = (
                                    "🎬 Ready for the next one! Send another photo anytime."
                                    if job.pipeline == "video"
                                    else "📸 Ready for the next one! Send another photo anytime."
                                )
                                await app.bot.send_message(
                                    chat_id=chat_id,
                                    text=ready_msg,
                                    read_timeout=10,
                                    write_timeout=10,
                                )
                            log.info("[W%d] ✅ Output sent to user %d", session.worker_id, user_id)
                            if not await _user_has_pending_jobs(user_id, exclude_job_id=job.id):
                                if user_id in app.user_data:
                                    saved_pipeline = job.pipeline
                                    app.user_data[user_id].clear()
                                    app.user_data[user_id]["mode"] = "sending_photos"
                                    if saved_pipeline == "posing":
                                        app.user_data[user_id]["pipeline"] = "posing"
                                        app.user_data[user_id]["flow"] = "posing"
                                        app.user_data[user_id]["prompt"] = DEFAULT_POSING_PROMPT
                                    elif saved_pipeline == "video":
                                        app.user_data[user_id]["pipeline"] = "video"
                                        app.user_data[user_id]["flow"] = "video"
                                        if job.prompt:
                                            app.user_data[user_id]["prompt"] = job.prompt
                                    elif saved_pipeline == "gpt_image":
                                        app.user_data[user_id]["pipeline"] = "gpt_image"
                                        app.user_data[user_id]["flow"] = "gpt_image"
                                        app.user_data[user_id]["prompt"] = DEFAULT_POSING_PROMPT
                                    elif saved_pipeline == "guava15":
                                        app.user_data[user_id]["pipeline"] = "guava15"
                                        app.user_data[user_id]["flow"] = "guava15"
                                        app.user_data[user_id]["prompt"] = DEFAULT_IMAGE_PROMPT
                                    elif saved_pipeline == "mango3":
                                        app.user_data[user_id]["pipeline"] = "mango3"
                                        app.user_data[user_id]["flow"] = "mango3"
                                        app.user_data[user_id]["prompt"] = DEFAULT_IMAGE_PROMPT
                                    else:
                                        # guava (default)
                                        app.user_data[user_id]["pipeline"] = "guava"
                                        app.user_data[user_id]["prompt"] = DEFAULT_IMAGE_PROMPT
                                next_state = ASK_MODE_SELECT if job.is_bulk else ASK_IMAGE
                                set_user_conversation_state(app, chat_id, user_id, next_state)
                            photo_sent = True
                            job_success = True
                            break
                        except Exception as e:
                            if send_attempt < max_send_retries - 1:
                                log.warning("[W%d] ⚠️ Failed to send photo (attempt %d/%d): %s", session.worker_id, send_attempt + 1, max_send_retries, e)
                                await asyncio.sleep(2 ** send_attempt)  # Exponential backoff
                            else:
                                log.error("[W%d] ❌ Failed to send photo after %d attempts: %s", session.worker_id, max_send_retries, e)
                                job_error = f"Failed to send output: {str(e)[:100]}"
                                if generation_done:
                                    try:
                                        await app.bot.send_message(
                                            chat_id=chat_id,
                                            text=(
                                                "✅ Your image was generated but Telegram delivery failed. "
                                                "Please try /start — you will not be charged a duplicate generation."
                                            ),
                                            read_timeout=15,
                                            write_timeout=15,
                                        )
                                    except Exception:
                                        pass

                    # ── RESILIENT ADMIN NOTIFICATION ──────
                    if admin_id:
                        try:
                            caption = f"📤 User {user_id}"
                            if job.pipeline == "posing":
                                caption += "\n🧘 Posing"
                            elif job.pipeline == "gpt_image":
                                caption += "\n🎨 GPT Image 2"
                            elif job.pipeline == "video":
                                caption += "\n🎬 Video"
                            elif job.pipeline == "guava15":
                                caption += "\n🔵 Enhanced"
                            default_prompts = (
                                DEFAULT_IMAGE_PROMPT,
                                DEFAULT_POSING_PROMPT,
                                *get_video_prompt_texts(),
                            )
                            if job.prompt and job.prompt not in default_prompts:
                                caption += f"\n📝 Custom Prompt: {job.prompt}"
                            elif job.pipeline == "posing":
                                caption += "\n🤖 Mode: POSING AUTO"
                            elif job.pipeline == "gpt_image":
                                caption += "\n🤖 Mode: GPT IMAGE 2 AUTO"
                            elif job.pipeline == "video":
                                caption += "\n🤖 Mode: VIDEO (fixed template)"
                            else:
                                caption += "\n🤖 Mode: AUTO"
                            
                            # Truncate caption to fit Telegram's 1024-character caption limit
                            if len(caption) > 1000:
                                caption = caption[:997] + "..."
                            
                            out_payload = open(result, "rb")
                            if job.pipeline == "video":
                                await asyncio.wait_for(
                                    app.bot.send_video(
                                        chat_id=admin_id,
                                        video=out_payload,
                                        caption=caption,
                                        supports_streaming=True,
                                        read_timeout=30,
                                        write_timeout=30,
                                    ),
                                    timeout=60.0,
                                )
                            else:
                                await asyncio.wait_for(
                                    app.bot.send_photo(
                                        chat_id=admin_id,
                                        photo=out_payload,
                                        caption=caption,
                                        read_timeout=15,
                                        write_timeout=30,
                                    ),
                                    timeout=30.0,
                                )
                            log.info("[W%d] ✅ Output sent to admin group (user %d)", session.worker_id, user_id)
                        except Exception as admin_err:
                            log.warning("[W%d] ⚠️ Failed to send to admin: %s", session.worker_id, admin_err)
                else:
                    job_error = "Generation returned None"
                    consecutive_failures += 1
                    log.error("[W%d] ❌ Generation failed: %s", session.worker_id, job_error)
                    if job.is_bulk:
                        await _notify_bulk_failure_and_continue(
                            app,
                            job,
                            reason="generation failed",
                        )
                    else:
                        fail_label = (
                            "🎬 Video generation failed (no output)."
                            if job.pipeline == "video"
                            else ("🧘 Posing generation failed (no output)."
                            if job.pipeline == "posing"
                            else ("🎨 GPT Image 2 generation failed (no output)."
                            if job.pipeline == "gpt_image"
                            else "❌ Generation failed (no output)."))
                        )
                        await _notify_job_failure_to_user(
                            app,
                            job,
                            f"{fail_label}\nPlease /start and try again.",
                        )

            except ContentForbiddenError as exc:
                # Moderation is per-job — do not trip worker circuit breaker or block other workers
                job_error = "Content Moderation Blocked"
                log.warning("[W%d] 🛑 Content forbidden (isolated) user %d job %s: %s",
                            session.worker_id, user_id, job.id, exc)

                try:
                    if job.is_bulk:
                        await _notify_bulk_failure_and_continue(
                            app,
                            job,
                            reason="content blocked",
                        )
                    else:
                        keyboard = [
                            [InlineKeyboardButton("❌ Cancel & Upload New Photo", callback_data="moderation_cancel")]
                        ]
                        reply_markup = InlineKeyboardMarkup(keyboard)
                        warning_text = (
                            "⚠️ *Generation Failed: Content Blocked* ⚠️\n\n"
                            "The prompt was moderated by Mage.space (Forbidden content block detected).\n\n"
                            "✏️ *Please type a modified prompt to try again* (your reference photo is preserved!):\n"
                            "Or click below to cancel."
                        )
                        await app.bot.send_message(
                            chat_id=chat_id,
                            text=warning_text,
                            parse_mode="Markdown",
                            reply_markup=reply_markup,
                        )
                        if not await _user_has_pending_jobs(user_id, exclude_job_id=job.id):
                            set_user_conversation_state(app, chat_id, user_id, ASK_CUSTOM_PROMPT)
                except Exception as notify_err:
                    log.error("[W%d] ❌ Failed to notify user of forbidden block: %s", session.worker_id, notify_err)

            except asyncio.TimeoutError:
                consecutive_failures += 1
                timeout_limit = _worker_timeout_for_job(job)
                job_error = f"Generation timeout ({timeout_limit}s exceeded)"
                log.error("[W%d] ❌ Pipeline timeout: %s", session.worker_id, job_error)
                try:
                    if job.is_bulk:
                        await _notify_bulk_failure_and_continue(
                            app,
                            job,
                            reason="generation timed out",
                        )
                    else:
                        await app.bot.edit_message_text(
                            chat_id=chat_id,
                            message_id=status_msg_id,
                            text="⏱️ Generation took too long. Please try again.",
                        )
                except Exception:
                    try:
                        await app.bot.send_message(
                            chat_id=chat_id,
                            text="⏱️ Generation took too long. Please try again.",
                        )
                    except Exception:
                        pass

            except asyncio.CancelledError:
                # User pressed /cancel — clean abort, no error message, no circuit-breaker increment
                job_error = "user_cancelled"
                log.info("[W%d] 🚫 Job %s cancelled by user %d", session.worker_id, job.id, job.user_id)
                try:
                    await app.bot.send_message(
                        chat_id=chat_id,
                        text="✅ Cancelled. Use /start to begin a new generation.",
                        read_timeout=10,
                        write_timeout=10,
                    )
                except Exception:
                    pass

            except Exception as exc:
                consecutive_failures += 1
                job_error = str(exc)[:200]
                log.error("[W%d] ❌ Worker error: %s\n%s", session.worker_id, exc, traceback.format_exc())
                try:
                    if job.is_bulk:
                        await _notify_bulk_failure_and_continue(
                            app,
                            job,
                            reason="unexpected error",
                        )
                    else:
                        # Craft a specific error message based on the exception type
                        exc_lower = str(exc).lower()
                        if "mage login failed" in exc_lower or "magic" in exc_lower or "maildev" in exc_lower or "email" in exc_lower:
                            user_msg = (
                                "⏳ *Session warming up…*\n\n"
                                "The bot is preparing a fresh account. "
                                "Please retry in 15–30 seconds — it should work then!"
                            )
                        elif "pipeline failed after" in exc_lower:
                            pool_ready = _count_live_ready() if LIVE_ONLY_POOL else (
                                acct_manager.count_ready() if acct_manager else 0
                            )
                            pool_total = TARGET_POOL_SIZE
                            if pool_ready == 0:
                                user_msg = (
                                    "⏳ *Building session pool…*\n\n"
                                    f"The bot is warming up ({pool_ready}/{pool_total} sessions ready). "
                                    "Please retry in 30 seconds."
                                )
                            else:
                                user_msg = "❌ Generation failed. Please try /generate again."
                        elif "guava" in exc_lower or "model" in exc_lower:
                            user_msg = "🔄 Model selection failed. Please try /generate again in a moment."
                        elif "timeout" in exc_lower:
                            user_msg = "⏱️ Generation timed out. Please try /generate again."
                        else:
                            user_msg = "❌ Error occurred. Please try /generate again."
                        try:
                            await app.bot.edit_message_text(
                                chat_id=chat_id,
                                message_id=status_msg_id,
                                text=user_msg,
                                parse_mode="Markdown",
                            )
                        except Exception:
                            await app.bot.send_message(
                                chat_id=chat_id,
                                text=user_msg,
                                parse_mode="Markdown",
                            )
                except Exception:
                    try:
                        await app.bot.send_message(
                            chat_id=chat_id,
                            text="❌ Error occurred. Please try /generate again.",
                        )
                    except Exception:
                        pass
            
            finally:
                requeued = False
                if session.stage_timer:
                    session.stage_timer.log_summary(success=job_success)
                    session.stage_timer = None
                session.page_prepared_for_job = False
                # ── ISOLATED CLEANUP: hard ceiling so one bad job never freezes this worker ──
                async def _do_cleanup():
                    nonlocal requeued
                    try:
                        await asyncio.wait_for(
                            _release_worker_for_next_job(
                                session,
                                job_error=job_error,
                                job_success=job_success,
                                job=job,
                            ),
                            timeout=30.0,
                        )
                    except asyncio.TimeoutError:
                        log.warning("[W%d] ⚠️ _release_worker timed out for job %s — forcing reset", session.worker_id, job.id)
                        # Force-clear state so the next job starts clean
                        session.mage_page = None
                        session.mail_page = None
                        session.is_new_session = True
                        session.used_pooled_session = False
                        session.session_committed = False
                        _reset_bulk_worker_state(session)
                    except Exception as rel_err:
                        log.warning("[W%d] ⚠️ _release_worker error for job %s: %s", session.worker_id, job.id, rel_err)
                        session.mage_page = None
                        session.mail_page = None
                        session.is_new_session = True
                        session.used_pooled_session = False
                        session.session_committed = False
                        _reset_bulk_worker_state(session)

                    if _should_auto_requeue_job(
                        job,
                        job_success=job_success,
                        photo_sent=photo_sent,
                        generation_done=generation_done,
                        job_error=job_error,
                    ):
                        try:
                            requeued = await asyncio.wait_for(queue_manager.requeue_job(job), timeout=10.0)
                        except Exception:
                            requeued = False
                        if requeued:
                            log.info("[W%d] 🔄 Job %s auto-requeued", session.worker_id, job.id)
                            await set_editing_message(app, job)

                    if not requeued:
                        try:
                            await asyncio.wait_for(queue_manager.complete_job(job, success=job_success, error=job_error), timeout=5.0)
                        except Exception as cj_err:
                            log.warning("[W%d] complete_job failed for %s: %s", session.worker_id, job.id, cj_err)
                    else:
                        try:
                            async with queue_manager.lock:
                                queue_manager.processing_jobs.pop(job.id, None)
                        except Exception:
                            pass

                    if not requeued:
                        if job.is_bulk or not _is_moderation_error(job_error):
                            _remove_job_reference_files(job)
                        if result:
                            _remove_image_files(result)

                try:
                    await asyncio.wait_for(_do_cleanup(), timeout=35.0)
                except asyncio.TimeoutError:
                    log.error("[W%d] ❌ Full cleanup timed out for job %s — worker self-healing", session.worker_id, job.id)
                    # Guarantee queue entry is freed so the job doesn't stay stuck
                    try:
                        await queue_manager.complete_job(job, success=False, error="cleanup_timeout")
                    except Exception:
                        pass
                    session.mage_page = None
                    session.mail_page = None
                    session.is_new_session = True
                    session.used_pooled_session = False
                    session.session_committed = False
                    _reset_bulk_worker_state(session)
                except Exception as fin_err:
                    log.error("[W%d] Job cleanup error for %s: %s", session.worker_id, job.id, fin_err)
                    try:
                        await queue_manager.complete_job(job, success=False, error=job_error or "cleanup_failed")
                    except Exception:
                        pass
                    session.mage_page = None
                    session.mail_page = None
                    session.is_new_session = True
        
        except Exception as outer_exc:
            consecutive_failures += 1
            log.error("[W%d] ⚠️ Outer exception in worker loop: %s\n%s", session.worker_id, outer_exc, traceback.format_exc())
            if "job" in locals() and job is not None:
                try:
                    await queue_manager.complete_job(job, success=False, error=str(outer_exc)[:200])
                except Exception:
                    pass
            try:
                await _release_worker_for_next_job(
                    session,
                    job_error=str(outer_exc),
                    job=job if "job" in locals() else None,
                )
            except Exception:
                pass
            await asyncio.sleep(1)



# ── Browser helpers (per WorkerSession) ──────────────────────────────────────

@async_timeout(30.0)
async def _ensure_ctx(s: WorkerSession, storage_state_path: str | None = None) -> BrowserContext:
    """Return browser context. When storage_state_path is set, always create a fresh context."""
    recycle = (
        storage_state_path is None
        and s.ctx is not None
        and s.account_count > 0
        and s.account_count % 15 == 0
    )
    if storage_state_path or s.ctx is None or recycle:
        if s.ctx:
            try: await s.ctx.close()
            except Exception: pass
            s.ctx = None
        if recycle:
            if s.browser:
                try: await s.browser.close()
                except Exception: pass
                s.browser = None
            if s.pw:
                try: await s.pw.stop()
                except Exception: pass
                s.pw = None
        if s.pw is None:
            s.pw = await async_playwright().start()
        if s.browser is None:
            launch_args = [
                "--no-sandbox",
                "--disable-blink-features=AutomationControlled",
                "--disable-dev-shm-usage",
                "--disable-infobars",
            ]
            if _on_cloud:
                launch_args.extend([
                    "--disable-gpu",
                    "--disable-software-rasterizer",
                    "--disable-background-networking",
                    "--disable-default-apps",
                    "--no-first-run",
                    "--mute-audio",
                ])
            if _on_pa:
                launch_args.extend([
                    "--disable-gpu",
                    "--no-sandbox",
                    "--headless",
                ])
            if s.worker_id < 0:
                launch_args.extend([
                    "--disable-extensions",
                    "--disable-sync",
                    "--mute-audio",
                ])
            else:
                launch_args.append("--window-size=1400,900")
            launch_kwargs: dict = {"headless": True, "args": launch_args}
            if _on_pa:
                launch_kwargs["executable_path"] = "/usr/bin/chromium"
            s.browser = await s.pw.chromium.launch(**launch_kwargs)
        if s.browser_fingerprint is None:
            s.browser_fingerprint = get_worker_fingerprint(s.worker_id)
        fp = s.browser_fingerprint
        viewport = (
            {"width": 1280, "height": 720}
            if s.worker_id < 0 or _on_cloud
            else {"width": fp.viewport_width, "height": fp.viewport_height}
        )
        ctx_kwargs = dict(
            viewport=viewport,
            user_agent=fp.user_agent,
            locale=fp.locale,
            timezone_id=fp.timezone_id,
            extra_http_headers={
                "Accept-Language": f"{fp.languages[0]},{fp.languages[1] if len(fp.languages) > 1 else fp.languages[0]};q=0.9",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            },
            permissions=['clipboard-read', 'clipboard-write'],
        )
        if storage_state_path and os.path.exists(storage_state_path):
            ctx_kwargs["storage_state"] = storage_state_path
        s.ctx = await s.browser.new_context(**ctx_kwargs)
        await s.ctx.add_init_script(build_stealth_init_script(fp))
        log.info("[W%d] Browser context (re)created%s", s.worker_id, " with storage state" if storage_state_path else "")
    return s.ctx


async def _new_page(s: WorkerSession) -> Page:
    return await (await _ensure_ctx(s)).new_page()


async def _close_mail_page(s: WorkerSession):
    if s.mail_page:
        try: await s.mail_page.close()
        except Exception: pass
        s.mail_page = None


async def _staggered_prewarm(s: WorkerSession, delay_sec: float = 0) -> None:
    """Pre-warm a worker browser without blocking startup or tripping OOM on HF."""
    if delay_sec > 0:
        await asyncio.sleep(delay_sec)
    try:
        ok = await _pre_warm_session(s)
        if ok:
            log.info("[W%d] ✅ Browser pre-warmed", s.worker_id)
        else:
            log.warning("[W%d] ⚠️ Browser pre-warm failed (will cold-start on first job)", s.worker_id)
    except Exception as e:
        log.warning("[W%d] ⚠️ Browser pre-warm error: %s", s.worker_id, e)


async def _pre_warm_session(s: WorkerSession, app: Optional[Application] = None) -> bool:
    """Launch Playwright + browser in the background so the first job skips cold start."""
    try:
        await _ensure_ctx(s)
        return True
    except Exception as e:
        log.warning("[W%d] Browser pre-warm failed: %s", s.worker_id, e)
        return False


def _is_transient_page_error(exc: Exception) -> bool:
    """True when Playwright failed because the page navigated or closed mid-action."""
    msg = str(exc).lower()
    return any(
        token in msg
        for token in (
            "execution context was destroyed",
            "target closed",
            "frame was detached",
            "navigation",
            "context was destroyed",
        )
    )


async def _wait_explore_ready(
    page: Page,
    worker_id: int = 0,
    timeout_ms: int = 12_000,
    *,
    require_promptbar: bool = False,
    quiet: bool = False,
) -> bool:
    """Wait for explore/prompt-bar UI without racing hidden aspect-dropdown options.

    When require_promptbar=True (session builder), aspect chip alone is not enough —
    the model dropdown lives in the prompt bar and may load later.
    """
    promptbar_selectors = [
        "div.promptbar-textarea div.tiptap.ProseMirror",
        "button[data-variant='subtle'][data-size='compact-sm'][aria-haspopup='dialog']",
        "img[alt='Send']",
    ]
    relaxed_selectors = promptbar_selectors + ["button[aria-label*='aspect' i]"]
    selectors = promptbar_selectors if require_promptbar else relaxed_selectors
    deadline = time.time() + timeout_ms / 1000
    while time.time() < deadline:
        for sel in selectors:
            try:
                el = page.locator(sel).first
                if await el.count() > 0 and await el.is_visible():
                    log.info("[W%d] ✅ Explore UI ready (selector: %s)", worker_id, sel)
                    return True
            except Exception:
                pass
        if not require_promptbar:
            try:
                has_aspect_chip = await page.evaluate("""() => {
                    for (const b of document.querySelectorAll('button')) {
                        const t = (b.textContent || '').trim();
                        if (/^\\d+:\\d+$/.test(t) && b.offsetParent !== null) return true;
                    }
                    return false;
                }""")
                if has_aspect_chip:
                    log.info("[W%d] ✅ Explore UI ready (selector: visible aspect chip)", worker_id)
                    return True
            except Exception:
                pass
        await page.wait_for_timeout(150)
    if quiet:
        log.debug("[W%d] Explore UI not ready within %dms (will retry)", worker_id, timeout_ms)
    else:
        log.warning("[W%d] ⚠️ Explore UI not confirmed ready within %dms", worker_id, timeout_ms)
    return False


async def _validate_mage_session(page: Page, worker_id: int = 0, timeout_ms: int = 10_000) -> bool:
    """Return True when the page is authenticated on Mage explore/create UI."""
    try:
        url = page.url.lower()
        if "onboarding=1" in url or "/enter" in url:
            return False
        if "login" in url and "explore" not in url:
            return False
        login_input = page.locator("input[placeholder='me@email.com'], input[type='email']").first
        if await login_input.count() > 0 and await login_input.is_visible():
            return False
        return await _wait_explore_ready(page, worker_id, timeout_ms=timeout_ms)
    except Exception as e:
        log.debug("[W%d] Session validation failed: %s", worker_id, e)
        return False


async def _park_live_pooled(email: str, s: WorkerSession, gems: int) -> bool:
    """Keep the builder's live browser open so jobs inherit Guava without re-selecting."""
    if gems < MIN_POOL_GEMS:
        log.info(
            "🔥 Skipping live park for %s — gems below threshold (have %d, need %d)",
            email, gems, MIN_POOL_GEMS,
        )
        return False
    if not s.ctx or not s.mage_page:
        return False
    try:
        if s.mage_page.is_closed():
            return False
    except Exception:
        return False
    if s.pw is None or s.browser is None:
        return False
    if not await _guava_is_selected(s.mage_page, s.worker_id):
        log.debug("🔥 Skipping live park for %s — Guava not active in prompt bar", email)
        return False
    if not await _validate_mage_session(s.mage_page, s.worker_id, timeout_ms=5_000):
        log.debug("🔥 Skipping live park for %s — explore session not valid", email)
        return False

    async with _live_pool_lock:
        if MAX_LIVE_POOLED > 0 and len(_live_pooled_sessions) >= MAX_LIVE_POOLED:
            log.info(
                "🔥 Live pool at cap (%d) — skipping live park for %s (disk session still ready)",
                MAX_LIVE_POOLED, email,
            )
            return False
        _live_pooled_sessions[email] = LivePooledBrowser(
            pw=s.pw,
            browser=s.browser,
            ctx=s.ctx,
            page=s.mage_page,
            gems=gems,
        )
    s.pw = None
    s.browser = None
    s.ctx = None
    s.mage_page = None
    log.info("🔥 Live prewarmed browser parked for %s (Guava verified, gems=%d)", email, gems)
    return True


async def _take_live_pooled(email: str) -> Optional[LivePooledBrowser]:
    async with _live_pool_lock:
        return _live_pooled_sessions.pop(email, None)


async def _discard_live_pooled(email: str) -> None:
    live = await _take_live_pooled(email)
    if not live:
        return
    try:
        if not live.page.is_closed():
            await live.page.close()
    except Exception:
        pass
    try:
        await live.ctx.close()
    except Exception:
        pass
    try:
        await live.browser.close()
    except Exception:
        pass
    try:
        await live.pw.stop()
    except Exception:
        pass


def _get_builder_mailbox_lock(worker_id: int) -> asyncio.Lock:
    if worker_id >= 0:
        return _mailbox_lock
    if worker_id not in _builder_mailbox_locks:
        _builder_mailbox_locks[worker_id] = asyncio.Lock()
    return _builder_mailbox_locks[worker_id]


def _count_live_ready(owner_user_id: int | None = None) -> int:
    """Sessions with a live parked browser — the only kind jobs should use on localhost."""
    if acct_manager is None:
        return 0
    emails = list(_live_pooled_sessions.keys())
    count = 0
    with acct_manager._lock:
        for email in emails:
            acct = acct_manager._accounts.get(email)
            if acct and acct_manager._is_ready(acct, owner_user_id=owner_user_id):
                count += 1
    return count


def _pool_supply(owner_uid: int | None = None) -> int:
    """Live ready + in-flight builds + sessions held by active jobs."""
    if LIVE_ONLY_POOL:
        live = _count_live_ready(owner_uid)
    elif acct_manager is not None:
        live = (
            acct_manager.count_ready(owner_user_id=owner_uid)
            if owner_uid is not None
            else acct_manager.count_ready()
        )
    else:
        live = 0
    jobs_holding = _processing_job_count()
    return live + jobs_holding + _builder_busy_count + _session_build_queue.qsize()


def _pool_deficit(owner_uid: int | None = None) -> int:
    if acct_manager is None or POOL_SIZE_PER_USER <= 0:
        return 0
    target = POOL_SIZE_PER_USER if owner_uid is not None else TARGET_POOL_SIZE
    return max(0, target - _pool_supply(owner_uid))


async def _try_acquire_live_pooled_session(owner_user_id: int | None = None):
    """Acquire only when a live parked browser exists — never cold storage_state."""
    if acct_manager is None:
        return None
    emails = list(_live_pooled_sessions.keys())
    for email in emails:
        with acct_manager._lock:
            acct = acct_manager._accounts.get(email)
            if acct and acct_manager._is_ready(acct, owner_user_id=owner_user_id):
                acct.in_use = True
                acct.in_use_since = time.time()
                acct.save()
                return acct
    return None


async def _boot_fresh_pool_prep() -> None:
    """Discard every stale disk/live session and queue parallel fresh builds."""
    if acct_manager is None or TARGET_POOL_SIZE <= 0:
        return
    for email in list(_live_pooled_sessions.keys()):
        await _discard_live_pooled(email)
    purged = acct_manager.purge_all_sessions()
    log.info("🔄 Fresh pool boot: purged %d stale session(s) — building new pool", purged)
    for uid in sorted(ALLOWED_USER_IDS):
        _ensure_pool_replacement(
            reason="fresh-boot", owner_uid=uid, slots=POOL_SIZE_PER_USER,
        )


@async_timeout(15.0)
async def _teardown_browser_stack(s: WorkerSession) -> None:
    """Close pages/browser/playwright on a worker without touching account pool state."""
    if s.mage_page:
        try:
            await s.mage_page.close()
        except Exception:
            pass
        s.mage_page = None
    if s.mail_page:
        try:
            await s.mail_page.close()
        except Exception:
            pass
        s.mail_page = None
    if s.ctx:
        try:
            await s.ctx.close()
        except Exception:
            pass
        s.ctx = None
    if s.browser:
        try:
            await s.browser.close()
        except Exception:
            pass
        s.browser = None
    if s.pw:
        try:
            await s.pw.stop()
        except Exception:
            pass
        s.pw = None
    s.browser_fingerprint = None
    s.page_prepared_for_job = False


def _pool_replacement_pending() -> bool:
    """True when a session build is queued or actively running."""
    return _builder_busy_count > 0 or _session_build_queue.qsize() > 0


def _processing_job_count() -> int:
    """Jobs currently being executed by workers."""
    return len(queue_manager.processing_jobs)


def _active_job_count() -> int:
    """Jobs currently processing or queued."""
    return _processing_job_count() + len(queue_manager.queue)


def _jobs_active() -> bool:
    """True when the system has queued or in-flight user work (load signal)."""
    return _active_job_count() > 0


def _jobs_processing() -> bool:
    """True when workers are actively running pipelines (not merely queued)."""
    return _processing_job_count() > 0


def _builder_should_pause_for_jobs() -> bool:
    """Pause session builder during jobs only when the pool already has enough ready sessions.

    Without this guard, BUILDER_PAUSE_DURING_JOBS drains the pre-session pool under load and
    forces slow fresh Maildev logins for every new job.
    """
    if not BUILDER_PAUSE_DURING_JOBS:
        return False
    if not _jobs_processing():
        return False
    # Local live-only: never spin up fresh logins while a job holds the browser.
    if LIVE_ONLY_POOL and not _on_cloud:
        return True
    if acct_manager is None or TARGET_POOL_SIZE <= 0:
        return True
    ready = _count_live_ready() if LIVE_ONLY_POOL else acct_manager.count_ready()
    min_reserve = min(max(1, BUILDER_PAUSE_MIN_READY), TARGET_POOL_SIZE)
    if ready <= min_reserve:
        return False
    demand = _processing_job_count() + len(queue_manager.queue)
    # Keep refilling while ready sessions may be consumed by active workers
    if ready <= _processing_job_count():
        return False
    if ready < min(demand, TARGET_POOL_SIZE):
        return False
    return True


async def _wait_for_jobs_idle(*, poll_sec: float = BUILDER_PAUSE_POLL_SEC) -> None:
    """Block session builder while workers are executing jobs — queued-only work must not block pool refill."""
    while _builder_should_pause_for_jobs():
        log.debug(
            "🔧 Session builder paused — %d job(s) processing (%d queued, pool ready=%s)",
            _processing_job_count(),
            len(queue_manager.queue),
            acct_manager.count_ready() if acct_manager and not LIVE_ONLY_POOL else _count_live_ready(),
        )
        await asyncio.sleep(poll_sec)


def _user_needing_pool_session() -> int | None:
    """Return the Telegram user ID that needs a ready pooled session next."""
    if acct_manager is None or POOL_SIZE_PER_USER <= 0:
        return None
    if not MULTI_USER_ISOLATION:
        if _pool_deficit() <= 0:
            return None
        return next(iter(ALLOWED_USER_IDS), None)
    for uid in sorted(ALLOWED_USER_IDS):
        if _pool_deficit(uid) > 0:
            return uid
    return None


def _ensure_pool_replacement(*, reason: str = "consume", owner_uid: int | None = None, slots: int = 1) -> None:
    """Queue pool builds when below target — multiple slots allowed for parallel builders."""
    if acct_manager is None or TARGET_POOL_SIZE <= 0:
        return
    if owner_uid is None:
        owner_uid = _user_needing_pool_session()
    if owner_uid is None:
        return
    deficit = _pool_deficit(owner_uid)
    to_queue = min(max(1, slots), deficit) if slots > 0 else deficit
    if to_queue <= 0:
        return
    queued = 0
    for _ in range(to_queue):
        try:
            _session_build_queue.put_nowait(owner_uid)
            queued += 1
        except asyncio.QueueFull:
            break
    if not queued:
        return
    pending = _session_build_queue.qsize() + _builder_busy_count
    defer_note = ""
    if _builder_should_pause_for_jobs():
        defer_note = " (deferred — pool reserve OK, jobs processing)"
    ready = _count_live_ready() if LIVE_ONLY_POOL else acct_manager.count_ready()
    log.info(
        "🔧 Queued %d session build(s) for user %d (%s, ready=%d/%d, pending=%d)%s",
        queued, owner_uid, reason, ready, TARGET_POOL_SIZE, pending, defer_note,
    )


async def _async_acquire_pooled_session(
    max_wait: float = POOL_ACQUIRE_WAIT,
    owner_user_id: int | None = None,
):
    """Wait for a ready pooled session; extend deadline while builder is working.

    Polls at 250ms intervals (instead of 50ms) to avoid busy-spinning the event
    loop for up to 75 seconds when the pool is empty and a build is in progress.
    """
    if acct_manager is None:
        return None
    end = time.time() + max_wait
    extended = False
    extended_end = end + POOL_BUILDER_GRACE
    poll_sec = POOL_ACQUIRE_POLL_SEC
    while True:
        if LIVE_ONLY_POOL:
            acct = await _try_acquire_live_pooled_session(owner_user_id)
        else:
            acct = acct_manager.acquire_session(wait=0, owner_user_id=owner_user_id)
        if acct:
            return acct
        now = time.time()
        if now >= end:
            break
        if not extended and _pool_replacement_pending():
            end = extended_end
            extended = True
            poll_sec = min(poll_sec, 0.1)
            log.debug("🔧 Pool empty but builder active — extended acquire deadline by %.0fs", POOL_BUILDER_GRACE)
        await asyncio.sleep(poll_sec)
    if _pool_replacement_pending():
        ready = _count_live_ready() if LIVE_ONLY_POOL else acct_manager.count_ready()
        log.warning(
            "🔧 Pool acquire timed out (ready=%d/%d, builders_busy=%d, pending=%d)",
            ready, TARGET_POOL_SIZE, _builder_busy_count, _session_build_queue.qsize(),
        )
    return None


async def _activate_pooled_session(
    s: WorkerSession,
    acct,
    app: Optional[Application] = None,
    job: Optional[Job] = None,
) -> Page | None:
    """Hydrate a pre-built pooled session and return an authenticated Mage page."""
    storage = acct.storage_state_file
    if not storage or not os.path.exists(storage):
        if acct_manager:
            acct_manager.discard_session(acct.username)
        return None

    await update_status(app, job, "⚡ Using ready session...")

    await _teardown_browser_stack(s)
    s.live_prewarmed_guava = False

    try:
        live = await _take_live_pooled(acct.username)
        if live:
            s.pw = live.pw
            s.browser = live.browser
            s.ctx = live.ctx
            s.mage_page = live.page
            s.gems = live.gems or acct.gems
            page = live.page

            # Wake up the tab to resume JS execution context
            try:
                await page.bring_to_front()
            except Exception:
                pass

            # Dismiss overlays without Escape — parked tabs may collapse prompt bar on Escape
            try:
                await _dismiss_blocking_overlays(page, s.worker_id, quiet=True, skip_escape=True)
            except Exception:
                pass

            validated = await _validate_mage_session(page, s.worker_id, timeout_ms=4_000)
            if not validated:
                log.info("[W%d] Live session not validated on first try, attempting page reload...", s.worker_id)
                try:
                    await page.reload(wait_until="domcontentloaded", timeout=10_000)
                    await _dismiss_blocking_overlays(page, s.worker_id, quiet=True, skip_escape=True)
                    validated = await _validate_mage_session(page, s.worker_id, timeout_ms=6_000)
                except Exception as reload_err:
                    log.debug("[W%d] Live session reload failed: %s", s.worker_id, reload_err)

            if not validated:
                log.warning("[W%d] Live prewarmed session expired/invalid for %s — discarding", s.worker_id, acct.username)
                await _teardown_browser_stack(s)
                if acct_manager:
                    acct_manager.discard_session(acct.username)
                return None

            guava_dom = await _guava_is_selected(page, s.worker_id)
            s.mage_page = page
            s.email = acct.username
            s.acquired_username = acct.username
            s.used_pooled_session = True
            s.live_prewarmed_guava = guava_dom
            s.is_new_session = False
            s.reuse_count = 0
            await _wait_promptbar_ready(page, s.worker_id, timeout_ms=PROMPTBAR_READY_MS)
            log.info(
                "[W%d] ⚡ Activated live prewarmed session %s (guava_dom=%s, no restore)",
                s.worker_id, acct.username, guava_dom,
            )
            return page

        if LIVE_ONLY_POOL:
            log.debug(
                "[W%d] Live-only pool: no parked browser for %s — waiting for fresh build",
                s.worker_id, acct.username,
            )
            acct_manager.release_session(acct.username)
            return None

        # Cold path: no live browser (e.g. after restart) — restore cookies from disk.
        ctx = await _ensure_ctx(s, storage_state_path=str(storage))
        page = await ctx.new_page()
        await page.goto(MAGE_EXPLORE, wait_until="domcontentloaded", timeout=15_000)
        if not await _validate_mage_session(page, s.worker_id, timeout_ms=6_000):
            log.warning("[W%d] Pooled session expired for %s — discarding", s.worker_id, acct.username)
            try:
                await page.close()
            except Exception:
                pass
            if acct_manager:
                acct_manager.discard_session(acct.username)
            return None

        s.mage_page = page
        s.email = acct.username
        s.gems = acct.gems
        s.acquired_username = acct.username
        s.used_pooled_session = True
        s.is_new_session = False
        s.reuse_count = 0
        log.info(
            "[W%d] ⚡ Activated pooled session %s from storage_state (Guava will be selected if needed)",
            s.worker_id, acct.username,
        )
        if job and job.pipeline in ("guava", "guava15"):
            if job.pipeline == "guava15":
                if not await _guava_15_is_selected(page, s.worker_id):
                    try:
                        await _select_guava_15_fast_mode(page, s.worker_id)
                    except Exception:
                        pass
                if not await _guava_15_is_selected(page, s.worker_id):
                    log.warning("[W%d] Pooled session %s missing Guava 1.5 — discarding", s.worker_id, acct.username)
                    try:
                        await page.close()
                    except Exception:
                        pass
                    if acct_manager:
                        acct_manager.discard_session(acct.username)
                    return None
            elif not await _guava_is_selected(page, s.worker_id):
                if not await _ensure_guava_on_page(
                    page, s.worker_id, rounds=3, context=acct.username,
                ):
                    log.warning("[W%d] Pooled session %s missing Guava V1 — discarding", s.worker_id, acct.username)
                    try:
                        await page.close()
                    except Exception:
                        pass
                    if acct_manager:
                        acct_manager.discard_session(acct.username)
                    _ensure_pool_replacement(reason="bad-session")
                    return None
                s.live_prewarmed_guava = True
        await _wait_promptbar_ready(page, s.worker_id, timeout_ms=PROMPTBAR_READY_MS)
        return page
    except Exception as e:
        log.warning("[W%d] Pooled session activation failed for %s: %s", s.worker_id, acct.username, e)
        await _discard_live_pooled(acct.username)
        if acct_manager:
            acct_manager.discard_session(acct.username)
        return None


async def _save_session_to_pool(
    ctx: BrowserContext,
    email: str,
    gems: int,
    worker_id: int = 0,
    *,
    guava_ready: bool = False,
    in_use: bool = False,
    owner_user_id: int | None = None,
) -> bool:
    """Persist Playwright storage state + cookie metadata for fast pool reuse."""
    if acct_manager is None:
        return False
    if worker_id < 0 and gems < MIN_POOL_GEMS:
        log.warning(
            "[W%d] Rejecting pool save for %s — gems below threshold (have %d, need %d)",
            worker_id, email, gems, MIN_POOL_GEMS,
        )
        return False
    try:
        storage_path = acct_manager.storage_state_path(email)
        await ctx.storage_state(path=str(storage_path))

        playwright_cookies = await ctx.cookies()
        cookie_file = acct_manager.data_dir / f"{email}.json"
        req_session = requests.Session()
        jar = requests.cookies.RequestsCookieJar()
        for c in playwright_cookies:
            try:
                jar.set(c.get("name"), c.get("value"), domain=c.get("domain"), path=c.get("path"))
            except Exception:
                try:
                    jar.set(c.get("name"), c.get("value"))
                except Exception:
                    pass
        req_session.cookies = jar

        from session_manager import AccountSession
        acct = AccountSession(
            username=email,
            credentials={"username": email, "password": "temp_created"},
            session=req_session,
            cookie_file=cookie_file,
            storage_state_file=storage_path,
            last_refresh=time.time(),
            logged_in=True,
            in_use=in_use,
            in_use_since=time.time() if in_use else 0.0,
            gems=gems,
            guava_ready=guava_ready,
            owner_user_id=owner_user_id,
        )
        acct.save()
        with acct_manager._lock:
            acct_manager._accounts[email] = acct
        log.info(
            "[W%d] 💾 Saved pooled session for %s (storage_state=%s, guava=%s)",
            worker_id, email, storage_path.name, guava_ready,
        )
        return True
    except Exception as e:
        log.warning("[W%d] Failed to save session to pool: %s", worker_id, e)
        return False


def _get_builder_session(builder_id: int = 0) -> "WorkerSession":
    """Return a dedicated builder session — never shared with job workers."""
    worker_id = -(builder_id + 1)
    if worker_id not in _builder_sessions:
        _builder_sessions[worker_id] = WorkerSession(worker_id=worker_id)
    return _builder_sessions[worker_id]


async def _cleanup_builder_after_build(s: "WorkerSession") -> None:
    """Tear down builder pages only — keep its browser alive, never touch job workers."""
    await _close_mail_page(s)
    if s.mage_page:
        try:
            await s.mage_page.close()
        except Exception:
            pass
        s.mage_page = None
    s.email = None
    s.acquired_username = None
    s.used_pooled_session = False
    s.session_committed = False
    await asyncio.sleep(0)  # yield to job workers


def _should_discard_pooled_session(error_msg: str) -> bool:
    """Poisoned Mage sessions should not be returned to the pool."""
    e = (error_msg or "").lower()
    return any(
        k in e
        for k in (
            "guava pro fast mode not active",
            "guava pro 1.5",
            "kiwi video fast mode not active",
            "kiwi play workspace not active",
            "grok image quality fast mode not active",
            "grok play workspace not active",
            "guava_not_verified",
            "wrong model",
            "prompt bar shows",
            "aspect button",
            "aspect ratio",
            "model dropdown",
            "no dropdown found",
            "reference image not attached",
            "reference image not uploaded",
        )
    )


def _finalize_worker_account(
    s: WorkerSession,
    *,
    success: bool = False,
    error_msg: str = "",
):
    """Return consumed sessions to pool or discard them intelligently."""
    username = s.acquired_username
    s.acquired_username = None
    pooled = s.used_pooled_session
    committed = s.session_committed
    s.used_pooled_session = False
    s.session_committed = False

    if not username or acct_manager is None:
        return

    try:
        if success or committed:
            log.info("[W%d] 🗑️ Session consumed: %s", s.worker_id, username)
            acct_manager.mark_consumed(username)
            _ensure_pool_replacement(reason="consumed")
        elif pooled and _should_discard_pooled_session(error_msg):
            log.info(
                "[W%d] 🗑️ Discarding bad pooled session (not returned to pool): %s",
                s.worker_id,
                username,
            )
            acct_manager.discard_session(username)
            _ensure_pool_replacement(reason="bad-session")
        elif pooled:
            log.info("[W%d] ↩️ Returning unused pooled session: %s", s.worker_id, username)
            acct_manager.release_session(username, gems=s.gems)
        else:
            acct_manager.discard_session(username)
    except Exception as e:
        log.warning("[W%d] Session finalize error for %s: %s", s.worker_id, username, e)
        try:
            acct_manager.release_session(username)
        except Exception:
            pass


async def _handle_pipeline_retry_cleanup(
    s: WorkerSession,
    page: Page | None,
    *,
    last_error: str,
    pipeline_label: str = "",
) -> None:
    """Release account lock and re-park live browsers after a failed pipeline attempt."""
    repark_user = s.acquired_username if s.used_pooled_session else None
    repark_gems = s.gems
    was_pooled = s.used_pooled_session
    _finalize_worker_account(s, success=False, error_msg=last_error)
    s.session_committed = False
    if was_pooled and repark_user and LIVE_ONLY_POOL and s.mage_page and s.ctx:
        active_page = page or s.mage_page
        try:
            await active_page.goto(MAGE_EXPLORE, wait_until="domcontentloaded", timeout=12_000)
            await _dismiss_blocking_overlays(active_page, s.worker_id, quiet=True, skip_escape=True)
        except Exception:
            pass
        if await _park_live_pooled(repark_user, s, repark_gems or MIN_POOL_GEMS):
            log.info(
                "[W%d] 🔥 Re-parked live session after failed attempt: %s",
                s.worker_id, repark_user,
            )
        else:
            await _teardown_browser_stack(s)
    try:
        await asyncio.wait_for(_reset_worker_browser(s), timeout=15.0)
    except asyncio.TimeoutError:
        label = pipeline_label or "pipeline"
        log.warning("[W%d] ⚠️ _reset_worker_browser timed out between %s attempts", s.worker_id, label)
    except Exception as err:
        label = pipeline_label or "pipeline"
        log.warning("[W%d] ⚠️ _reset_worker_browser failed between %s attempts: %s", s.worker_id, label, err)
    if s.mage_page:
        try:
            await s.mage_page.close()
        except Exception:
            pass
        s.mage_page = None


async def _close_session(s: WorkerSession):
    """Close pages, context, browser, and playwright instance to release all resources and start clean."""
    log.info("[W%d] 🧹 Closing and releasing session resources...", s.worker_id)
    _finalize_worker_account(s)
    await _teardown_browser_stack(s)
    s.live_prewarmed_guava = False
    s.email = None
    s.gems = 0


async def _dismiss_blocking_overlays(page: Page, worker_id: int = 0, quiet: bool = False, skip_escape: bool = False):
    """Automatically find and dismiss/remove blocking modals and overlays.

    Enhanced to:
    - Wait for overlays to actually disappear (not just removed from DOM)
    - Re-check after interactions to catch reappearing overlays
    - Add extra waits for CSS animations to complete
    - Protect model picker popover from being destroyed
    - skip_escape: when True, skip the Escape keypress (e.g. when the
      model picker dropdown is open and Escape would close it)

    ⚠️ CRITICAL: This function presses Escape as its first action. If the
    model picker dropdown is currently open, calling this will CLOSE it.
    Use skip_escape=True when called from within the model selection flow,
    or better yet, don't call this function at all while the dropdown is open.
    """
    if not quiet:
        log.info("[W%d] 🛡️ Dismissing blocking overlays...%s", worker_id, " (skip_escape)" if skip_escape else "")

    # 0) Press Escape first — closes most modals/popovers instantly
    #    BUT: skip if the model picker dropdown might be open
    if not skip_escape:
        try:
            await page.keyboard.press("Escape")
            await page.wait_for_timeout(80)
        except Exception:
            pass
    else:
        # Even when skipping Escape, try to dismiss known overlay buttons
        # without closing the model picker
        try:
            await page.evaluate('''() => {
                // Only click dismiss buttons that are NOT inside a model picker
                const modelPicker = document.querySelector(
                    '[data-portal="true"] [class*="Popover-dropdown"], ' +
                    '[class*="Popover-dropdown"], ' +
                    'div[style*="cursor: pointer"]:has(p:has-text("Guava")), ' +
                    'div[style*="cursor: pointer"]:has(p:has-text("Mango")), ' +
                    'div[style*="cursor: pointer"]:has(p:has-text("Grok")), ' +
                    'div[style*="cursor: pointer"]:has(p:has-text("Kiwi"))'
                );
                const buttons = document.querySelectorAll('button, [role="button"]');
                for (const btn of buttons) {
                    // Skip if button is inside the model picker
                    if (modelPicker && modelPicker.contains(btn)) continue;
                    const txt = (btn.textContent || "").toLowerCase();
                    if (txt.includes("skip") || txt.includes("close") || txt.includes("got it") ||
                        txt.includes("dismiss") || txt.includes("accept") || txt.includes("agree")) {
                        try { btn.click(); } catch(e) {}
                    }
                }
            }''')
            await page.wait_for_timeout(80)
        except Exception:
            pass

    try:
        # Try to click standard dismiss buttons inside portals
        # But ONLY if they're NOT inside a model picker
        await page.evaluate('''() => {
            const portalButtons = document.querySelectorAll('[data-portal="true"] button, [data-portal="true"] [role="button"], button, [role="button"]');
            for (const btn of portalButtons) {
                // Skip buttons inside model picker popover
                const pickerParent = btn.closest('[class*="Popover-dropdown"]');
                if (pickerParent) continue;
                const txt = (btn.textContent || "").toLowerCase();
                if (txt.includes("skip") || txt.includes("close") || txt.includes("got it") || txt.includes("dismiss") || txt.includes("accept") || txt.includes("agree")) {
                    try { btn.click(); } catch(e) {}
                }
            }
        }''')
        await page.wait_for_timeout(100)
    except Exception as e:
        log.debug("[W%d] Overlay click dismiss failed: %s", worker_id, e)

    # Aggressively remove ALL portal and overlay elements unconditionally
    # BUT protect: aspect ratio picker, image dropzone, AND model picker
    removal_attempts = 0
    max_removal_attempts = 3
    while removal_attempts < max_removal_attempts:
        try:
            removed_count = await page.evaluate('''() => {
                let count = 0;
                // Helper: detect if an element is the model picker (dropdown/popover)
                function isModelPickerElement(el) {
                    // 1. Contains search input for models
                    if (el.querySelector('input[placeholder="Search models..."]')) return true;
                    // 2. Contains "Choose Image Model" header text
                    if (el.textContent && el.textContent.includes("Choose Image Model")) return true;
                    // 3. Has mage-Popover-dropdown class
                    if (el.classList && (el.classList.contains('mage-Popover-dropdown') ||
                        el.classList.contains('m_923dead6'))) return true;
                    // 4. Contains model names AND clickable items (open dropdown state)
                    if (el.textContent && /Guava|Mango|Grok|Kiwi|model|Fast Mode/i.test(el.textContent)) {
                        if (el.querySelector('button, [role="option"], [role="menuitem"], div[style*="cursor"], a[href="/advanced"]')) {
                            return true;
                        }
                    }
                    // 5. Contains an <a href="/advanced"> link (part of model picker)
                    if (el.querySelector('a[href="/advanced"]')) return true;
                    // 6. Contains Pro 1.5 / guava-pro image (advanced model picker)
                    if (el.querySelector('img[src*="guava-pro"]')) return true;
                    // 7. Contains "Select Model" button (model confirmation)
                    if (el.querySelector('button') && el.textContent && el.textContent.includes("Select Model")) return true;
                    return false;
                }

                // 1. Scan and remove portal roots
                document.querySelectorAll('[data-portal="true"]').forEach(el => {
                    const isAspect = el.textContent && (el.textContent.includes("Aspect Ratio") || /[0-9]+:[0-9]+/.test(el.textContent));
                    const isDropzone = el.querySelector('div.mage-Dropzone-root, input[type="file"]');
                    const isModelPicker = isModelPickerElement(el);
                    if (isAspect || isDropzone || isModelPicker) {
                        return;
                    }
                    // Check if it's a modal, overlay, dialog, popover, menu or covers the viewport
                    const rect = el.getBoundingClientRect();
                    const isFullScreen = rect.width > window.innerWidth * 0.8 && rect.height > window.innerHeight * 0.8;
                    const isModal = el.querySelector('[role="dialog"], [role="presentation"], [class*="Modal"], [class*="Overlay"], [class*="Dialog"], [class*="Popover-dropdown"], [class*="Menu-dropdown"]');
                    if (isModal || isFullScreen) {
                        el.remove();
                        count++;
                    }
                });

                // 2. Scan and remove standalone modals/dialogs/overlays directly in the body
                const selectors = [
                    '[role="dialog"]',
                    '.mantine-Modal-root',
                    '.mantine-Overlay-root',
                    '.mantine-Dialog-root',
                    '[class*="Modal-root"]',
                    '[class*="Overlay-root"]',
                    '[class*="Dialog-root"]'
                ];
                selectors.forEach(sel => {
                    document.querySelectorAll(sel).forEach(el => {
                        const isAspect = el.textContent && (el.textContent.includes("Aspect Ratio") || /[0-9]+:[0-9]+/.test(el.textContent));
                        const isDropzone = el.querySelector('div.mage-Dropzone-root, input[type="file"]');
                        const isModelPicker = isModelPickerElement(el);
                        if (isAspect || isDropzone || isModelPicker) {
                            return;
                        }
                        el.remove();
                        count++;
                    });
                });
                
                // Restore pointer events and overflow to body and html
                document.body.style.pointerEvents = 'auto';
                document.body.style.overflow = 'auto';
                document.documentElement.style.pointerEvents = 'auto';
                document.documentElement.style.overflow = 'auto';
                
                return count;
            }''')
            
            if removed_count > 0:
                if not quiet:
                    log.info("[W%d] 🛡️ Removed %d blocking overlay elements from DOM.", worker_id, removed_count)
                # Wait for CSS animations/transitions to complete
                await page.wait_for_timeout(80)
                removal_attempts += 1
            else:
                # No overlays found, we're done
                break
        except Exception as e:
            if _is_transient_page_error(e):
                log.debug("[W%d] Overlay removal paused (page navigating)", worker_id)
                await page.wait_for_timeout(200)
                continue
            log.warning("[W%d] Aggressive overlay removal failed: %s", worker_id, e)
            break
    
    # Final wait to let any remaining animations settle
    await page.wait_for_timeout(80)


async def _reset_worker_browser(s: WorkerSession):
    """Hard-reset browser state between pipeline retries, keeping context alive to preserve cache."""
    for attr in ("mage_page", "mail_page"):
        page = getattr(s, attr, None)
        if page:
            try: await page.close()
            except Exception: pass
            setattr(s, attr, None)
    if s.ctx:
        try:
            await s.ctx.clear_cookies()
        except Exception:
            pass


# Email integration is handled via SecureTempMail (see create_maildev_mailbox).


def _maildev_local_part_from_url(url: str) -> str | None:
    if "/inbox/" not in (url or ""):
        return None
    local_part = url.split("/inbox/")[-1].split("?")[0].split("#")[0].strip().strip("/")
    return local_part or None


def _maildev_generate_local_part() -> str:
    """Maildev accepts arbitrary inbox names — no /suggest API required."""
    return f"{random.choice(_MAILDEV_ADJECTIVES)}-{random.choice(_MAILDEV_NOUNS)}-{secrets.token_hex(3)}"


def _maildev_api_targets(relative_path: str, *, cache_bust: bool = False) -> list[str]:
    """catchtempmail: always direct, no proxy."""
    relative_path = relative_path.lstrip("/")
    suffix = f"?_={int(time.time() * 1000)}" if cache_bust else ""
    direct = f"{MAILDEV_API_URL}/{relative_path}{suffix}"
    return [direct]


def _maildev_http_targets(relative_path: str) -> list[str]:
    return _maildev_api_targets(relative_path)


def _maildev_api_label(url: str) -> str:
    if _maildev_is_gas_proxy(url) or (
        _maildev_proxy_url() and _maildev_is_gas_proxy(_maildev_proxy_url())
        and _maildev_proxy_url() in url
    ):
        return "GAS proxy"
    proxy = _maildev_proxy_url()
    if proxy and url.startswith(proxy):
        return "browser API proxy"
    return "browser API direct"


def _maildev_http_label(url: str) -> str:
    if _maildev_is_gas_proxy(url) or (
        _maildev_proxy_url() and url.startswith(_maildev_proxy_url())
    ):
        return "GAS proxy" if _maildev_is_gas_proxy(_maildev_proxy_url() or url) else "HTTP proxy"
    if _maildev_is_proxy_url(url):
        return "HTTP proxy"
    return "HTTP direct"


def _maildev_is_proxy_url(url: str) -> bool:
    proxy = _maildev_proxy_url()
    return bool(proxy and (url.startswith(proxy) or url.startswith(f"{proxy}?")))


def _maildev_is_direct_api_url(url: str) -> bool:
    return MAILDEV_API_URL in url or "securetempmail.com" in url


async def _maildev_curl_session():
    """catchtempmail needs no curl_cffi — always returns None."""
    return None


async def _maildev_http_get(
    url: str,
    worker_id: int,
    label: str,
    *,
    quiet: bool,
) -> httpx.Response | None:
    """GET with curl_cffi (HF), proxy retries, then httpx fallback."""
    if _maildev_use_curl_cffi() and _maildev_is_direct_api_url(url):
        try:
            session = await _maildev_curl_session()
            if session is not None:
                return await session.get(
                    url,
                    headers=_maildev_headers(),
                    timeout=30,
                )
        except Exception as curl_err:
            if not quiet:
                log.warning(
                    "[W%d] ⚠️ Maildev curl_cffi error for %s: %s",
                    worker_id, url, _brief_exc(curl_err),
                )
            else:
                log.debug(
                    "[W%d] Maildev curl_cffi error for %s: %s",
                    worker_id, url, _brief_exc(curl_err),
                )

    if _on_hf and _maildev_use_curl_cffi() and _maildev_is_proxy_url(url):
        return None

    is_proxy = _maildev_is_proxy_url(url)
    max_attempts = _MAILDEV_PROXY_RETRIES if is_proxy else 1
    last_err: BaseException | None = None
    for attempt in range(max_attempts):
        if attempt > 0:
            await asyncio.sleep(_MAILDEV_PROXY_RETRY_DELAYS[attempt - 1])
        try:
            async with httpx.AsyncClient(
                timeout=_MAILDEV_HTTP_TIMEOUT,
                headers=_maildev_headers(),
                follow_redirects=True,
            ) as client:
                return await client.get(url)
        except Exception as http_err:
            last_err = http_err
            if attempt < max_attempts - 1:
                if not quiet:
                    log.debug(
                        "[W%d] Maildev %s retry %d/%d for %s: %s",
                        worker_id, label, attempt + 1, max_attempts, url, _brief_exc(http_err),
                    )
                continue
            if not quiet:
                log.warning(
                    "[W%d] ⚠️ Maildev %s error for %s: %s",
                    worker_id, label, url, _brief_exc(http_err),
                )
    if last_err and quiet:
        log.debug(
            "[W%d] Maildev %s error for %s: %s",
            worker_id, label, url, _brief_exc(last_err),
        )
    return None


def _maildev_status_cf_blocked(status_out: list) -> bool:
    return any(entry.endswith(":403") or entry.endswith(":spa") for entry in status_out)


def _maildev_health_summary() -> dict:
    proxy = _maildev_proxy_url()
    configured = bool(MAILDEV_PROXY_URL)
    return {
        "proxy_configured": configured,
        "proxy_healthy": _MAILDEV_PROXY_HEALTHY,
        "curl_cffi_healthy": _MAILDEV_CURL_CFFI_HEALTHY,
        "http_api_ok": _maildev_http_api_ok(),
        "proxy_url": proxy or (MAILDEV_PROXY_URL if configured else "(none)"),
    }


def _maildev_is_spa_shell(body: str) -> bool:
    """catchtempmail API always returns JSON, never an HTML SPA shell."""
    text = (body or "").lstrip().lower()
    return text.startswith("<!doctype html") or (
        "<html" in text[:300] and "catchtempmail" in text[:2500]
    )


@async_timeout(30.0)
async def _maildev_http_json(
    relative_path: str,
    worker_id: int = 0,
    *,
    quiet: bool = False,
    source_out: list | None = None,
    cache_bust: bool = False,
    status_out: list | None = None,
) -> dict | list | None:
    relative_path = relative_path.lstrip("/")
    for url in _maildev_api_targets(relative_path, cache_bust=cache_bust):
        if _maildev_use_curl_cffi() and _maildev_is_direct_api_url(url):
            label = "curl_cffi"
        else:
            label = _maildev_http_label(url)
        try:
            r = await _maildev_http_get(url, worker_id, label, quiet=quiet)
            if r is None:
                if status_out is not None:
                    status_out.append(f"{relative_path}:error")
                continue
            if status_out is not None:
                if r.status_code != 200:
                    status_out.append(f"{relative_path}:{r.status_code}")
                elif _maildev_is_spa_shell(r.text):
                    status_out.append(f"{relative_path}:spa")
                else:
                    status_out.append(f"{relative_path}:200")
            if r.status_code == 200:
                if _maildev_is_spa_shell(r.text):
                    if not quiet:
                        log.debug("[W%d] Maildev %s SPA shell (not API JSON): %s", worker_id, label, url)
                    continue
                try:
                    data = r.json()
                except Exception:
                    if not quiet:
                        log.debug("[W%d] Maildev %s non-JSON 200: %s", worker_id, label, url)
                    continue
                if source_out is not None:
                    source_out.append(label)
                if not quiet:
                    log.debug("[W%d] Maildev %s OK: %s", worker_id, label, url)
                return data
            reason = _maildev_http_failure_reason(url, r.status_code, r.text)
            if not quiet:
                log.warning("[W%d] ⚠️ Maildev %s failed — %s", worker_id, label, reason)
        except Exception as http_err:
            if status_out is not None:
                status_out.append(f"{relative_path}:error")
            if not quiet:
                log.warning("[W%d] ⚠️ Maildev %s error for %s: %s", worker_id, label, url, _brief_exc(http_err))
    return None


async def _maildev_http_text(
    relative_path: str,
    worker_id: int = 0,
    *,
    quiet: bool = True,
    cache_bust: bool = False,
    status_out: list | None = None,
) -> str | None:
    """Fetch a non-JSON Maildev endpoint (e.g. email HTML body)."""
    relative_path = relative_path.lstrip("/")
    for url in _maildev_api_targets(relative_path, cache_bust=cache_bust):
        label = "HTTP proxy" if _maildev_is_proxy_url(url) else "HTTP direct"
        try:
            r = await _maildev_http_get(url, worker_id, label, quiet=quiet)
            if r is None:
                if status_out is not None:
                    status_out.append(f"{relative_path}:error")
                continue
            if status_out is not None:
                if r.status_code != 200:
                    status_out.append(f"{relative_path}:{r.status_code}")
                elif _maildev_is_spa_shell(r.text):
                    status_out.append(f"{relative_path}:spa")
                else:
                    status_out.append(f"{relative_path}:200")
            if r.status_code == 200 and r.text and not _maildev_is_spa_shell(r.text):
                if not quiet:
                    log.debug("[W%d] Maildev %s text OK: %s", worker_id, label, url)
                return r.text
            if not quiet:
                reason = _maildev_http_failure_reason(url, r.status_code, r.text)
                log.warning("[W%d] ⚠️ Maildev %s text failed — %s", worker_id, label, reason)
        except Exception as http_err:
            if status_out is not None:
                status_out.append(f"{relative_path}:error")
            if not quiet:
                log.warning("[W%d] ⚠️ Maildev %s text error for %s: %s", worker_id, label, url, _brief_exc(http_err))
    return None


def _maildev_extract_shadow_part(payload: dict) -> str | None:
    shadow = payload.get("shadowAddress")
    if isinstance(shadow, dict):
        local_part = shadow.get("localPart")
        if local_part:
            return str(local_part).strip()
    return None


def _maildev_emails_from_payload(payload: dict) -> list:
    emails = payload.get("emails")
    if isinstance(emails, list):
        return emails
    mailbox = payload.get("mailbox")
    if isinstance(mailbox, dict):
        nested = mailbox.get("emails")
        if isinstance(nested, list):
            return nested
    return []


async def _maildev_activate_inbox(s: "WorkerSession", local_part: str) -> dict | None:
    """Prime the Maildev inbox via API before Mage sends mail (official Maildev flow)."""
    async def _activate_impl() -> dict | None:
        payload = None
        if s.mail_page and _maildev_page_on_site(s.mail_page):
            payload = await _maildev_json_via_page(s.mail_page, f"inbox/{local_part}", worker_id=s.worker_id)
        if not isinstance(payload, dict):
            payload = await _maildev_http_json(f"inbox/{local_part}", s.worker_id, cache_bust=True)
        if not isinstance(payload, dict) and s.mail_page and not s.mail_page.is_closed():
            payload = await _maildev_fetch_inbox_payload(s.mail_page, local_part, s.worker_id)
        if isinstance(payload, dict):
            shadow = _maildev_extract_shadow_part(payload)
            if shadow:
                s.maildev_shadow_part = shadow
                log.info("[W%d] 📧 Maildev shadow inbox: %s@sh.maildev.dev", s.worker_id, shadow)
            return payload
        return None
    
    try:
        return await _maildev_circuit_breaker.call(_activate_impl)
    except RuntimeError as e:
        log.warning("[W%d] Maildev circuit breaker open, using fallback: %s", s.worker_id, e)
        return None


def _maildev_parse_suggest_response(data: dict) -> str | None:
    if not isinstance(data, dict):
        return None
    local_part = data.get("localPart")
    if local_part:
        return str(local_part).strip()
    mailbox = data.get("mailbox")
    if isinstance(mailbox, dict):
        local_part = mailbox.get("localPart")
        if local_part:
            return str(local_part).strip()
    return None


def _maildev_use_browser_api() -> bool:
    if _truthy_env("MAILDEV_BROWSER_API"):
        return True
    if _falsey_env("MAILDEV_BROWSER_API"):
        return False
    return bool(os.getenv("SPACE_ID") or os.getenv("HF_SPACE"))


def _maildev_is_cloudflare_block(status_code: int, body: str) -> bool:
    if status_code in (403, 429, 503):
        return True
    text = (body or "").lower()
    return "just a moment" in text or "cf-chl" in text or "cf-mitigated" in text


def _maildev_http_failure_reason(url: str, status_code: int, body: str) -> str:
    preview = (body or "").replace("\n", " ").strip()[:120]
    if status_code == 404 and _maildev_is_proxy_url(url):
        return f"proxy worker not deployed (404): {preview}"
    if _maildev_is_cloudflare_block(status_code, body):
        return f"Cloudflare block ({status_code}): {preview}"
    return f"HTTP {status_code}: {preview}"


async def _maildev_is_cf_challenge(page: Page) -> bool:
    """True when the page is still on a Cloudflare interstitial (not the Maildev SPA)."""
    try:
        title = (await page.title() or "").lower()
        if "just a moment" in title or "attention required" in title:
            return True
        html = (await page.content() or "")[:12_000].lower()
        return any(
            marker in html
            for marker in (
                "cf-challenge",
                "challenge-platform",
                "cf-turnstile",
                "checking your browser",
                "verify you are human",
                "cdn-cgi/challenge-platform",
            )
        )
    except Exception:
        return True


async def _maildev_inbox_ui_ready(page: Page) -> bool:
    """True when Maildev inbox UI is visible (not a CF challenge page)."""
    if await _maildev_is_cf_challenge(page):
        return False
    try:
        if await page.locator(_MAILDEV_SELECTORS["inbox_heading"]).first.is_visible():
            return True
        if await page.locator(_MAILDEV_SELECTORS["email_input"]).first.is_visible():
            return True
        if await page.locator(_MAILDEV_SELECTORS["enter_inbox"]).first.is_visible():
            return True
    except Exception:
        pass
    if _maildev_local_part_from_url(page.url):
        title = (await page.title() or "").lower()
        return "just a moment" not in title
    return False


async def _maildev_try_solve_cloudflare(page: Page, worker_id: int = 0) -> bool:
    """Nudge Cloudflare managed challenge; returns True when challenge UI is gone."""
    if not await _maildev_is_cf_challenge(page):
        return True
    for frame in page.frames:
        frame_url = frame.url or ""
        if "challenges.cloudflare.com" not in frame_url and "turnstile" not in frame_url:
            continue
        for sel in ('input[type="checkbox"]', "#challenge-stage", ".ctp-checkbox-label", "body"):
            try:
                loc = frame.locator(sel).first
                if await loc.count() > 0:
                    await loc.click(timeout=2_000)
                    await page.wait_for_timeout(800)
                    break
            except Exception:
                pass
    for sel in ("#challenge-stage", ".cf-turnstile", "#cf-turnstile"):
        try:
            loc = page.locator(sel).first
            if await loc.count() > 0 and await loc.is_visible():
                await loc.click(timeout=2_000)
                await page.wait_for_timeout(800)
        except Exception:
            pass
    await page.wait_for_timeout(400)
    cleared = not await _maildev_is_cf_challenge(page)
    if cleared and worker_id:
        log.debug("[W%d] Cloudflare challenge cleared", worker_id)
    return cleared


async def _maildev_spa_ready(page: Page, worker_id: int = 0) -> bool:
    """Maildev is usable: inbox UI visible or in-page API responds."""
    if await _maildev_is_cf_challenge(page):
        return False
    if await _maildev_inbox_ui_ready(page):
        return True
    if _maildev_page_on_site(page):
        data = await _maildev_in_page_fetch_json(
            page, f"{MAILDEV_API_URL}/inbox/suggest", worker_id=worker_id,
        )
        if isinstance(data, dict) and _maildev_parse_suggest_response(data):
            return True
    return False


async def _maildev_wait_cloudflare(page: Page, timeout_ms: int = 60_000, worker_id: int = 0) -> bool:
    """Wait for Cloudflare managed challenge to clear and the Maildev SPA to appear."""
    deadline = time.time() + (timeout_ms / 1000.0)
    while time.time() < deadline:
        await _maildev_try_solve_cloudflare(page, worker_id)
        if await _maildev_spa_ready(page, worker_id):
            return True
        await page.wait_for_timeout(1_000)

    await _maildev_try_solve_cloudflare(page, worker_id)
    return await _maildev_spa_ready(page, worker_id)


async def _maildev_goto_maildev(
    page: Page,
    url: str,
    worker_id: int = 0,
    *,
    cf_timeout_ms: int | None = None,
    reload_on_cf: bool = True,
) -> bool:
    if cf_timeout_ms is None:
        cf_timeout_ms = 90_000 if _on_hf else 45_000
    attempts = 2 if reload_on_cf else 1
    for nav_attempt in range(attempts):
        try:
            if nav_attempt == 0:
                await page.goto(url, wait_until="domcontentloaded", timeout=30_000)
            else:
                log.info("[W%d] 🔁 Reloading Maildev after Cloudflare wait (%s)", worker_id, url)
                await page.reload(wait_until="domcontentloaded", timeout=30_000)
        except Exception as nav_err:
            log.warning("[W%d] ⚠️ Maildev navigation issue for %s: %s", worker_id, url, nav_err)
        if await _maildev_wait_cloudflare(page, timeout_ms=cf_timeout_ms, worker_id=worker_id):
            try:
                await page.wait_for_selector("#app", timeout=8_000)
            except Exception:
                pass
            return True
    return False


@async_timeout(20.0)
async def _maildev_in_page_fetch_json(page: Page, url: str, *, worker_id: int = 0) -> dict | list | None:
    """Fetch catchtempmail JSON from browser context (kept for browser-fallback compat)."""
    try:
        data = await page.evaluate(
            """async (url) => {
                try {
                    const r = await fetch(url, {
                        credentials: "include",
                        headers: { "Accept": "application/json" },
                    });
                    if (!r.ok) return { __error: r.status };
                    return await r.json();
                } catch (e) {
                    return { __error: String(e) };
                }
            }""",
            url,
        )
        if isinstance(data, dict) and "__error" in data:
            log.debug("[W%d] catchtempmail in-page fetch %s failed: %s", worker_id, url, data["__error"])
            return None
        return data
    except Exception as exc:
        log.debug("[W%d] catchtempmail in-page fetch exception for %s: %s", worker_id, url, exc)
        return None


def _maildev_page_on_site(page: Page | None) -> bool:
    """SecureTempMail: browser page is never required — HTTP API always works."""
    try:
        return bool(page and not page.is_closed() and "securetempmail.com" in (page.url or ""))
    except Exception:
        return False


@async_timeout(25.0)
async def _maildev_browser_api_json(
    page: Page,
    relative_path: str,
    worker_id: int = 0,
    *,
    quiet: bool = False,
) -> dict | list | None:
    context_failed = False
    on_site = _maildev_page_on_site(page)

    if on_site:
        for url in _maildev_api_targets(relative_path):
            label = _maildev_api_label(url)
            data = await _maildev_in_page_fetch_json(page, url, worker_id=worker_id)
            if data is not None:
                if not quiet:
                    log.debug("[W%d] Maildev %s in-page OK: %s", worker_id, label, url)
                return data
            context_failed = True

    if _on_hf and on_site:
        return None

    for url in _maildev_api_targets(relative_path):
        label = _maildev_api_label(url)
        try:
            resp = await page.context.request.get(url, headers=_maildev_headers())
            body = await resp.text()
            if resp.ok:
                if not quiet:
                    log.debug("[W%d] Maildev %s OK: %s", worker_id, label, url)
                return await resp.json()
            context_failed = True
            reason = _maildev_http_failure_reason(url, resp.status, body)
            if not quiet:
                log.warning("[W%d] ⚠️ Maildev %s failed — %s", worker_id, label, reason)
        except Exception as req_err:
            context_failed = True
            if not quiet:
                level = log.warning if _maildev_is_proxy_url(url) else log.debug
                level(
                    "[W%d] ⚠️ Maildev %s error for %s: %s",
                    worker_id, label, url, _brief_exc(req_err),
                )

    if not on_site:
        for fallback_url in _maildev_api_targets(relative_path):
            label = _maildev_api_label(fallback_url)
            data = await _maildev_in_page_fetch_json(page, fallback_url)
            if data is not None:
                if not quiet:
                    log.debug("[W%d] Maildev %s in-page OK: %s", worker_id, label, fallback_url)
                return data
            if not quiet and not context_failed:
                log.warning(
                    "[W%d] ⚠️ Maildev in-page fetch failed for %s",
                    worker_id, fallback_url,
                )
            else:
                log.debug(
                    "[W%d] Maildev in-page fetch failed for %s",
                    worker_id, fallback_url,
                )
    return None


async def _maildev_suggest_via_browser(page: Page, worker_id: int = 0) -> str | None:
    async def _suggest_impl() -> str | None:
        if _maildev_page_on_site(page):
            direct_url = f"{MAILDEV_API_URL}/inbox/suggest"
            data = await _maildev_in_page_fetch_json(page, direct_url, worker_id=worker_id)
            if isinstance(data, dict):
                local_part = _maildev_parse_suggest_response(data)
                if local_part:
                    log.info(
                        "[W%d] 📧 Suggested email via browser (direct API): %s@maildev.dev",
                        worker_id, local_part,
                    )
                    return local_part
            proxy = _maildev_proxy_url()
            if proxy:
                proxy_url = f"{proxy}/inbox/suggest"
                data = await _maildev_in_page_fetch_json(page, proxy_url, worker_id=worker_id)
                if isinstance(data, dict):
                    local_part = _maildev_parse_suggest_response(data)
                    if local_part:
                        log.info(
                            "[W%d] 📧 Suggested email via browser (proxy): %s@maildev.dev",
                            worker_id, local_part,
                        )
                        return local_part
        data = await _maildev_browser_api_json(page, "inbox/suggest", worker_id, quiet=_MAILDEV_PROXY_HEALTHY)
        local_part = _maildev_parse_suggest_response(data) if isinstance(data, dict) else None
        if local_part:
            log.info("[W%d] 📧 Suggested email via browser API: %s@maildev.dev", worker_id, local_part)
        return local_part
    
    try:
        return await _maildev_circuit_breaker.call(_suggest_impl)
    except RuntimeError as e:
        log.warning("[W%d] Maildev circuit breaker open for suggest, using fallback: %s", worker_id, e)
        return None


async def _maildev_json_via_page(page: Page, relative_path: str, worker_id: int = 0) -> dict | list | None:
    """Fetch Maildev JSON using the browser session (bypasses datacenter Cloudflare blocks)."""
    rel = relative_path.lstrip("/")
    data = await _maildev_in_page_fetch_json(page, f"{MAILDEV_API_URL}/{rel}", worker_id=worker_id)
    if data is not None:
        return data
    proxy = _maildev_proxy_url()
    if proxy:
        return await _maildev_in_page_fetch_json(page, f"{proxy}/{rel}", worker_id=worker_id)
    return None


async def _maildev_fetch_inbox_payload(page: Page, local_part: str, worker_id: int = 0) -> dict | None:
    if _maildev_page_on_site(page):
        data = await _maildev_json_via_page(page, f"inbox/{local_part}", worker_id=worker_id)
        if isinstance(data, dict):
            return data
    data = await _maildev_browser_api_json(
        page, f"inbox/{local_part}", worker_id, quiet=_MAILDEV_PROXY_HEALTHY,
    )
    return data if isinstance(data, dict) else None


async def _maildev_suggest_local_part(
    worker_id: int = 0,
    max_attempts: int = 3,
    page: Page | None = None,
) -> str | None:
    if page is not None:
        for attempt in range(max_attempts):
            local_part = await _maildev_suggest_via_browser(page, worker_id)
            if local_part:
                return local_part
            extracted = await _maildev_extract_address(page, worker_id)
            if extracted[0]:
                return extracted[0]
            if attempt + 1 < max_attempts:
                await asyncio.sleep(1.0 * (attempt + 1))
        return None

    for attempt in range(max_attempts):
        data = await _maildev_http_json("inbox/suggest", worker_id)
        if isinstance(data, dict):
            local_part = _maildev_parse_suggest_response(data)
            if local_part:
                return local_part
            log.warning(
                "[W%d] ⚠️ Maildev suggest missing localPart (attempt %d/%d)",
                worker_id, attempt + 1, max_attempts,
            )
        if attempt + 1 < max_attempts:
            await asyncio.sleep(0.8 * (attempt + 1))
    return None


async def _maildev_wait_inbox_ready(page: Page, timeout_ms: int = 15_000) -> str | None:
    deadline = time.time() + (timeout_ms / 1000.0)
    local_part = _maildev_local_part_from_url(page.url)
    while time.time() < deadline:
        local_part = _maildev_local_part_from_url(page.url) or local_part
        if local_part:
            try:
                await page.wait_for_selector(_MAILDEV_SELECTORS["inbox_heading"], timeout=1_500)
            except Exception:
                pass
            try:
                val = await page.locator(_MAILDEV_SELECTORS["email_input"]).first.input_value()
                if val and val.strip() and val.strip() != "null-inbox":
                    return val.strip()
            except Exception:
                pass
            return local_part
        await page.wait_for_timeout(150)
    return _maildev_local_part_from_url(page.url)


async def _maildev_extract_address(page: Page, worker_id: int = 0) -> tuple[str | None, str | None]:
    local_part = _maildev_local_part_from_url(page.url)
    if local_part:
        email = f"{local_part}@maildev.dev"
        log.info("[W%d] 📧 Read local part from URL: %s", worker_id, local_part)
        return local_part, email

    try:
        email_input = page.locator(_MAILDEV_SELECTORS["email_input"]).first
        if await email_input.count() > 0:
            for _ in range(24):
                val = (await email_input.input_value() or "").strip()
                if val and val != "null-inbox":
                    local_part = val
                    email = f"{local_part}@maildev.dev"
                    log.info("[W%d] 📧 Read local part from input: %s", worker_id, local_part)
                    return local_part, email
                await page.wait_for_timeout(150)
    except Exception as input_err:
        log.debug("[W%d] Input extraction failed: %s", worker_id, input_err)

    try:
        copy_btn = page.locator(_MAILDEV_SELECTORS["copy_email"]).first
        if await copy_btn.count() > 0:
            await copy_btn.click()
            await page.wait_for_timeout(200)
            clipboard_val = (await page.evaluate("navigator.clipboard.readText()") or "").strip()
            if clipboard_val and "@maildev.dev" in clipboard_val:
                email = clipboard_val
                local_part = email.split("@")[0].strip()
                log.info("[W%d] 📧 Read email from clipboard: %s", worker_id, email)
                return local_part, email
    except Exception as clipboard_err:
        log.debug("[W%d] Clipboard extraction failed: %s", worker_id, clipboard_err)

    return None, None


async def _ensure_maildev_mail_page(s: "WorkerSession") -> Page | None:
    """Keep or recreate a Maildev tab for browser-API inbox polling."""
    if s.maildev_api_only:
        return None
    if s.mail_page and not s.mail_page.is_closed():
        return s.mail_page
    local_part = s.email.split("@")[0].strip() if s.email else None
    if not local_part:
        return None
    try:
        mail_page = await _new_page(s)
        inbox_url = f"{MAILDEV_URL}inbox/{local_part}"
        await _maildev_goto_maildev(
            mail_page, inbox_url, s.worker_id,
            cf_timeout_ms=15_000, reload_on_cf=False,
        )
        s.mail_page = mail_page
        return mail_page
    except Exception as page_err:
        log.debug("[W%d] Could not recreate Maildev page: %s", s.worker_id, page_err)
        return None


async def _log_maildev_connectivity() -> None:
    """Probe SecureTempMail API reachability at startup."""
    try:
        data = await stm_create_mailbox(ttl_minutes=10)
        log.info("📧 SecureTempMail API reachable — test inbox: %s", data.get("address", "?"))
    except Exception as e:
        log.warning("⚠️ SecureTempMail API probe failed: %s", _brief_exc(e))


async def _maildev_save_debug_snapshot(page: Page, worker_id: int, attempt: int, label: str = "fail"):
    try:
        MAILDEV_DEBUG_DIR.mkdir(parents=True, exist_ok=True)
        stem = f"maildev_{label}_w{worker_id}_a{attempt + 1}"
        png_path = MAILDEV_DEBUG_DIR / f"{stem}.png"
        html_path = MAILDEV_DEBUG_DIR / f"{stem}.html"
        await page.screenshot(path=str(png_path), full_page=True)
        html_path.write_text(await page.content(), encoding="utf-8")
        log.warning("[W%d] 📸 Maildev debug saved: %s", worker_id, png_path)
    except Exception as snap_err:
        log.debug("[W%d] Debug snapshot failed: %s", worker_id, snap_err)


async def _maildev_click_enter_inbox(page: Page, worker_id: int = 0) -> bool:
    for sel in (
        _MAILDEV_SELECTORS["enter_inbox"],
        'button.btn-primary:has-text("Enter inbox")',
        _MAILDEV_SELECTORS["view_inbox"],
    ):
        try:
            btn = page.locator(sel).first
            if await btn.count() > 0 and await btn.is_visible():
                await btn.click()
                log.info("[W%d] 📧 Clicked Maildev button (%s)", worker_id, sel)
                return True
        except Exception:
            pass
    return False


async def _maildev_open_inbox_via_browser(
    page: Page,
    worker_id: int = 0,
    *,
    skip_goto: bool = False,
) -> tuple[str | None, str | None]:
    if not skip_goto:
        if not await _maildev_goto_maildev(page, MAILDEV_URL, worker_id):
            return None, None

    api_local_part = await _maildev_suggest_via_browser(page, worker_id)
    if api_local_part:
        inbox_url = f"{MAILDEV_URL}inbox/{api_local_part}"
        if f"/inbox/{api_local_part}" not in page.url:
            await _maildev_goto_maildev(page, inbox_url, worker_id)
        local_part = await _maildev_wait_inbox_ready(page, timeout_ms=15_000)
        if local_part:
            return await _maildev_extract_address(page, worker_id)

    if not await _maildev_click_enter_inbox(page, worker_id):
        try:
            await page.wait_for_selector(_MAILDEV_SELECTORS["enter_inbox"], timeout=15_000)
            await page.locator(_MAILDEV_SELECTORS["enter_inbox"]).first.click()
        except Exception:
            pass

    try:
        await page.wait_for_url("**/inbox/**", timeout=20_000)
    except Exception:
        pass

    local_part = await _maildev_wait_inbox_ready(page, timeout_ms=15_000)
    if local_part:
        return await _maildev_extract_address(page, worker_id)

    if await _maildev_click_enter_inbox(page, worker_id):
        try:
            await page.wait_for_url("**/inbox/**", timeout=15_000)
        except Exception:
            pass
        local_part = await _maildev_wait_inbox_ready(page, timeout_ms=10_000)
        if local_part:
            return await _maildev_extract_address(page, worker_id)

    return None, None


async def _maildev_refresh_inbox_page(page: Page, local_part: str | None = None, worker_id: int = 0):
    clicked = False
    try:
        refresh_btn = page.locator(_MAILDEV_SELECTORS["refresh_inbox"]).first
        if await refresh_btn.count() > 0 and await refresh_btn.is_visible():
            await refresh_btn.click()
            clicked = True
            await page.wait_for_timeout(800)
    except Exception:
        pass
    if not clicked:
        try:
            if local_part:
                await _maildev_goto_maildev(page, f"{MAILDEV_URL}inbox/{local_part}", worker_id)
            else:
                await page.reload(wait_until="domcontentloaded", timeout=15_000)
                await _maildev_wait_cloudflare(page, timeout_ms=30_000, worker_id=worker_id)
            await page.wait_for_timeout(800)
        except Exception:
            pass


def _maildev_is_mage_email(email_obj: dict) -> bool:
    subject = str(email_obj.get("subject", ""))
    subject_lower = subject.lower()
    if "sign in to" in subject_lower and "mage" in subject_lower:
        return True
    if "mage" in subject_lower and ("sign in" in subject_lower or "login" in subject_lower):
        return True
    for key in ("from", "sender", "fromAddress", "headerfrom", "text", "html", "body", "content", "preview", "data"):
        val = email_obj.get(key)
        text = str(val).lower()
        if val and ("mage.space" in text or "noreply@mage.space" in text):
            return True
    combined = " ".join(str(v) for v in email_obj.values()).lower()
    return "mage.space" in combined or "noreply@mage.space" in combined


def _maildev_email_sort_key(email_obj: dict):
    for key in ("receivedAt", "time", "date", "createdAt", "timestamp"):
        val = email_obj.get(key)
        if val:
            return str(val)
    return ""


def _maildev_extract_email_id(email_obj: dict) -> str | None:
    """Resolve Maildev / catchtempmail API email id — avoid RFC message-id strings with '@'."""
    for key in ("id", "_id", "uid", "emailId", "message_id", "messageId", "email_id"):
        val = email_obj.get(key)
        if val is not None:
            candidate = str(val).strip()
            if candidate and "@" not in candidate and len(candidate) < 128:
                return candidate
    return None


def _maildev_unescape_html_chain(val: str, rounds: int = 4) -> str:
    """Decode nested HTML entities (e.g. &amp;amp; inside Maildev iframe srcdoc)."""
    out = val or ""
    for _ in range(rounds):
        nxt = html.unescape(out)
        if nxt == out:
            break
        out = nxt
    return out


def _maildev_is_magic_auth_url(url: str) -> bool:
    u = (url or "").lower()
    if "oobcode=" not in u:
        return False
    if "/__/auth/action" in u or "/auth/action" in u:
        return "mage.space" in u or "firebaseapp.com" in u
    return "mode=signin" in u and ("mage.space" in u or "firebaseapp.com" in u)


def _maildev_clean_magic_url(url: str) -> str:
    u = _maildev_unescape_html_chain((url or "").strip())
    u = u.strip("\"'<>")
    u = re.sub(r"[)\]}>.,;]+$", "", u)
    return u


def _maildev_collect_magic_candidates(val: str) -> list[str]:
    """Collect Mage Firebase auth URLs from email HTML/text (href-first)."""
    if not val:
        return []
    decoded = _maildev_unescape_html_chain(val)
    candidates: list[str] = []

    for match in _HREF_ATTR_RE.finditer(decoded):
        href = _maildev_clean_magic_url(match.group(1) or match.group(2) or "")
        if _maildev_is_magic_auth_url(href):
            candidates.append(href)

    for pattern in (_MAGE_AUTH_URL_RE, _FIREBASE_AUTH_URL_RE):
        for match in pattern.finditer(decoded):
            url = _maildev_clean_magic_url(match.group(0))
            if _maildev_is_magic_auth_url(url):
                candidates.append(url)

    # Deduplicate while preserving order; prefer full __/auth/action URLs with oobCode.
    seen: set[str] = set()
    ranked: list[str] = []
    for url in candidates:
        if url in seen:
            continue
        seen.add(url)
        ranked.append(url)
    ranked.sort(
        key=lambda u: (
            0 if "/__/auth/action" in u.lower() else 1,
            -len(u),
        ),
    )
    return ranked


def _maildev_find_magic_link_in_text(val: str) -> str | None:
    candidates = _maildev_collect_magic_candidates(val)
    return candidates[0] if candidates else None


def _maildev_find_magic_link_in_email(email_obj: dict) -> str | None:
    for key in ("html", "text", "body", "content", "html_body", "text_body", "body_html", "body_text", "body_preview", "htmlBody", "textBody", "preview", "snippet", "data"):
        val = email_obj.get(key)
        if isinstance(val, str):
            link = _maildev_find_magic_link_in_text(val)
            if link:
                return link
    for val in email_obj.values():
        if isinstance(val, str):
            link = _maildev_find_magic_link_in_text(val)
            if link:
                return link
        elif isinstance(val, (dict, list)):
            res = _maildev_find_magic_link_in_nested(val)
            if res:
                return res
    return None


def _maildev_find_magic_link_in_nested(d) -> str | None:
    if isinstance(d, str):
        return _maildev_find_magic_link_in_text(d)
    elif isinstance(d, dict):
        for val in d.values():
            res = _maildev_find_magic_link_in_nested(val)
            if res:
                return res
    elif isinstance(d, list):
        for val in d:
            res = _maildev_find_magic_link_in_nested(val)
            if res:
                return res
    return None


def _maildev_detail_json_paths(inbox_local_part: str, email_id: str) -> list[str]:
    """Hosted maildev.dev returns full email JSON at inbox/{localPart}/{emailId}."""
    return [
        f"inbox/{inbox_local_part}/{email_id}",
    ]


async def _maildev_fetch_email_detail(local_part: str, email_id: str, worker_id: int = 0) -> dict | None:
    for rel in _maildev_detail_json_paths(local_part, email_id):
        data = await _maildev_http_json(rel, worker_id, quiet=True, cache_bust=True)
        if isinstance(data, dict):
            return data
    return None


async def create_maildev_mailbox(s: WorkerSession) -> str:
    """Create a temporary email via SecureTempMail free API."""
    s.maildev_shadow_part = None
    s.maildev_api_only = True
    s.catchtempmail_inbox_id = None
    s.catchtempmail_read_token = None
    s.secmail_cookies = None

    log.info("[W%d] 📧 Creating SecureTempMail inbox...", s.worker_id)
    for attempt in range(3):
        try:
            data = await stm_create_mailbox(ttl_minutes=60)
            email = data["address"]
            s.email = email
            s.catchtempmail_inbox_id = data["id"]
            s.catchtempmail_read_token = data["token"]
            s.mail_page = None
            log.info(
                "[W%d] 📧 SecureTempMail inbox created: %s (id=%s)",
                s.worker_id, email, data["id"],
            )
            return email
        except Exception as e:
            log.warning(
                "[W%d] ⚠️ SecureTempMail inbox creation error (attempt %d/3): %s",
                s.worker_id, attempt + 1, _brief_exc(e),
            )
        if attempt < 2:
            await asyncio.sleep(0.4 * (attempt + 1))

    raise RuntimeError("Failed to create SecureTempMail inbox after 3 attempts")


async def _maildev_try_magic_from_payload(
    s: WorkerSession,
    payload: dict,
    inbox_local_part: str,
    mail_page: Page | None,
    warned_ids: set[str] | None = None,
) -> tuple[str, str] | None:
    """Return (magic_url, source_endpoint) or None — SecureTempMail message list/detail."""
    if warned_ids is None:
        warned_ids = set()

    messages = payload.get("messages")
    if not isinstance(messages, list):
        for key in ("data", "emails", "items", "results", "mails", "mail"):
            val = payload.get(key)
            if isinstance(val, list):
                messages = val
                break
    if isinstance(messages, list):
        email_list = [m for m in messages if isinstance(m, dict)]
    else:
        email_list = sorted(
            _maildev_emails_from_payload(payload), key=_maildev_email_sort_key, reverse=True
        )

    for email_obj in email_list:
        magic_url = _maildev_find_magic_link_in_email(email_obj)
        if magic_url:
            return magic_url, "list_payload"

        email_id = _maildev_extract_email_id(email_obj)
        endpoint_status: list[str] = []

        # Skip welcome noise; Mage mails need /messages/{id} for full HTML with oobCode.
        from_l = str(email_obj.get("fromAddress") or email_obj.get("from") or "").lower()
        is_welcome = "securetempmail.com" in from_l and "welcome" in from_l

        if (
            email_id
            and not is_welcome
            and s.catchtempmail_inbox_id
            and s.catchtempmail_read_token
        ):
            try:
                detail = await stm_get_message(
                    s.catchtempmail_inbox_id,
                    s.catchtempmail_read_token,
                    str(email_id),
                )
                magic_url = _maildev_find_magic_link_in_email(detail)
                if magic_url:
                    return magic_url, f"detail/{email_id}"
                endpoint_status.append("detail:200")
                if _maildev_is_mage_email(email_obj) or _maildev_is_mage_email(detail):
                    log.warning(
                        "[W%d] ⚠️ SecureTempMail detail 200 but no magic link — keys=%s id=%s",
                        s.worker_id,
                        sorted(detail.keys()) if isinstance(detail, dict) else type(detail).__name__,
                        email_id,
                    )
            except Exception as detail_err:
                log.debug("[W%d] SecureTempMail detail fetch failed: %s", s.worker_id, detail_err)
                endpoint_status.append("detail:error")
        elif email_id and not (s.catchtempmail_inbox_id and s.catchtempmail_read_token):
            for rel in _maildev_detail_json_paths(inbox_local_part, email_id):
                detail = await _maildev_http_json(
                    rel, s.worker_id, quiet=True, cache_bust=True, status_out=endpoint_status,
                )
                if isinstance(detail, dict):
                    magic_url = _maildev_find_magic_link_in_email(detail)
                    if magic_url:
                        return magic_url, rel

        if _maildev_is_mage_email(email_obj):
            warn_key = email_id or str(email_obj.get("subject", ""))[:80] or "mage"
            if warn_key not in warned_ids:
                warned_ids.add(warn_key)
                subject = str(email_obj.get("subject", ""))[:80]
                log.warning(
                    "[W%d] ⚠️ Mage email in inbox but no magic link — keys=%s id=%s subject=%r endpoints=%s",
                    s.worker_id,
                    sorted(email_obj.keys()),
                    email_id,
                    subject,
                    endpoint_status[:12] or ["no_id"],
                )
    return None


@async_timeout(75.0)
async def _fetch_magic_link_via_maildev(
    s: WorkerSession,
    max_attempts: int = 40,
    delay: float = 0.9,
    *,
    start_delay: float = 0.15,
) -> str | None:
    """Poll SecureTempMail inbox for the Mage magic link (fast early polls)."""
    inbox_id = s.catchtempmail_inbox_id
    token = s.catchtempmail_read_token
    local_part = s.email.split("@")[0].strip() if s.email else None
    current_delay = start_delay
    last_email_count = -1
    warned_ids: set[str] = set()

    if not inbox_id or not token:
        log.warning("[W%d] ⚠️ No SecureTempMail inbox id/token — cannot poll", s.worker_id)
        return None

    _raw_keys_logged = False

    for attempt in range(max_attempts):
        try:
            messages = await stm_list_messages(inbox_id, token)
            payload = {"messages": messages}
            total_emails = len(messages)

            if not _raw_keys_logged:
                _raw_keys_logged = True
                sample_keys = sorted(messages[0].keys()) if messages else []
                log.info(
                    "[W%d] 📬 SecureTempMail poll ready — sample msg keys: %s",
                    s.worker_id, sample_keys or "(empty)",
                )

            if total_emails != last_email_count and total_emails > 0:
                last_email_count = total_emails
                log.info(
                    "[W%d] 📬 SecureTempMail inbox has %d email(s), scanning for Mage link…",
                    s.worker_id, total_emails,
                )

            extracted = await _maildev_try_magic_from_payload(
                s, payload, local_part or (s.email or ""), None, warned_ids,
            )
            if extracted:
                magic_url, source = extracted
                log.info("[W%d] 📬 Magic link extracted from SecureTempMail (%s)!", s.worker_id, source)
                return magic_url

        except Exception as e:
            log.debug("[W%d] SecureTempMail poll error: %s", s.worker_id, _brief_exc(e))

        if attempt % 8 == 0 or attempt == max_attempts - 1:
            log.info(
                "[W%d] 📬 SecureTempMail poll (attempt %d/%d): %d email(s), no Mage link yet",
                s.worker_id, attempt + 1, max_attempts, max(last_email_count, 0),
            )

        await asyncio.sleep(current_delay)
        current_delay = min(current_delay + 0.15, delay)

    return None


async def rotate_maildev_mailbox(s: WorkerSession) -> str:
    """Get a new SecureTempMail address when Mage rejects the current one."""
    if s.mail_page:
        try:
            await s.mail_page.close()
        except Exception:
            pass
        s.mail_page = None
    s.maildev_shadow_part = None
    s.maildev_api_only = True
    s.catchtempmail_inbox_id = None
    s.catchtempmail_read_token = None
    s.secmail_cookies = None
    return await create_maildev_mailbox(s)



async def _mage_notification_text(page: Page) -> str:
    try:
        return await page.evaluate('''() => {
            const parts = [];
            const sel = [
                '.mage-Notifications-root',
                '.mage-Notification-title',
                '.mage-Notification-description',
                '.mage-Notification-body',
                '[class*="Notifications-root"]',
                '[class*="Notification-root"]',
                '[class*="Notification-title"]',
                '[class*="Notification-description"]',
            ];
            for (const s of sel) {
                document.querySelectorAll(s).forEach(el => {
                    const t = (el.textContent || '').trim();
                    if (t) parts.push(t);
                });
            }
            return parts.join(' | ');
        }''') or ""
    except Exception:
        return ""


def _normalize_magic_url(url: str) -> str:
    u = html.unescape(html.unescape((url or "").strip()))
    u = u.strip("\"'<>")
    u = re.sub(r"[)\]}>.,;]+$", "", u)
    return u


async def _mage_magic_link_auth_failed(page: Page) -> bool:
    text = (await _mage_notification_text(page)).lower()
    return any(h in text for h in _MAGE_MAGIC_LINK_FAIL_HINTS)


@async_timeout(30.0)
async def _wait_magic_link_auth(page: Page, worker_id: int = 0, timeout_ms: int = 28_000) -> bool:
    """Wait for Firebase magic-link sign-in to finish on the same tab that requested the email."""
    start = time.time()
    while (time.time() - start) * 1000 < timeout_ms:
        if await _mage_magic_link_auth_failed(page):
            note = await _mage_notification_text(page)
            log.warning("[W%d] ⛔ Magic link auth failed: %s", worker_id, note[:160])
            return False
        if await _validate_mage_session(page, worker_id, timeout_ms=4_000):
            return True
        await page.wait_for_timeout(200)
    if await _mage_magic_link_auth_failed(page):
        return False
    return await _validate_mage_session(page, worker_id, timeout_ms=6_000)


def _classify_mage_email_notification(text: str) -> str:
    t = (text or "").lower()
    if not t:
        return "unknown"
    if any(h in t for h in _MAGE_EMAIL_REJECT_HINTS):
        return "rejected"
    if any(h in t for h in _MAGE_EMAIL_SENT_HINTS):
        return "sent"
    return "unknown"


async def _open_mage_login_form(page: Page, worker_id: int = 0) -> None:
    await page.goto(MAGE_ENTER, wait_until="domcontentloaded", timeout=20_000)
    await _dismiss_blocking_overlays(page, worker_id)
    for _ in range(2):
        try:
            await page.wait_for_selector("input[placeholder='me@email.com']", timeout=5000)
            return
        except PWTimeout:
            pass
        try:
            await page.wait_for_selector("input[type='email']", timeout=3000)
            return
        except PWTimeout:
            pass

        await _dismiss_blocking_overlays(page, worker_id)
        for trigger in [
            "button:has-text('Log In')",
            "button:has-text('Sign In')",
            "a:has-text('Log In')",
            "a:has-text('Sign In')",
            "button:has-text('Start Generating')",
            "[aria-label*='login' i]",
            "[aria-label*='sign' i]",
        ]:
            try:
                btn = page.locator(trigger).first
                if await btn.count() > 0 and await btn.is_visible():
                    await stable_click(page, btn, timeout_ms=3000)
                    await page.wait_for_timeout(200)
                    break
            except Exception:
                pass

    # Last resort: hard reload login entry (clears half-authenticated magic-link state)
    await page.goto(MAGE_ENTER, wait_until="domcontentloaded", timeout=20_000)
    await _dismiss_blocking_overlays(page, worker_id)


async def _recycle_mage_login_page(s: WorkerSession, page: Page | None) -> Page:
    """Fresh login tab after a failed magic link — clears cookies so email form is reachable."""
    if page:
        try:
            if not page.is_closed():
                await page.close()
        except Exception:
            pass
    if s.ctx:
        try:
            await s.ctx.clear_cookies()
        except Exception:
            pass
    new_page = await _new_page(s)
    await _open_mage_login_form(new_page, s.worker_id)
    return new_page


async def _locate_mage_email_input(page: Page, worker_id: int = 0):
    for sel in ["input[placeholder='me@email.com']", "input[type='email']", "input[placeholder*='email' i]"]:
        try:
            el = page.locator(sel).first
            if await el.count() > 0 and await el.is_visible():
                return el
        except Exception:
            pass
    await _open_mage_login_form(page, worker_id)
    for sel in ["input[placeholder='me@email.com']", "input[type='email']", "input[placeholder*='email' i]"]:
        try:
            el = page.locator(sel).first
            if await el.count() > 0 and await el.is_visible():
                return el
        except Exception:
            pass
    try:
        await page.wait_for_selector("input[placeholder='me@email.com']", timeout=8_000)
        return page.locator("input[placeholder='me@email.com']").first
    except PWTimeout:
        try:
            await page.wait_for_selector("input[type='email']", timeout=5_000)
            return page.locator("input[type='email']").first
        except PWTimeout:
            log.warning("[W%d] ⚠️ Email input not found", worker_id)
            raise


async def _submit_mage_login_email(page: Page, email: str, worker_id: int = 0) -> str:
    """Submit email on Mage; return 'sent', 'rejected', or 'unknown'."""
    email_input = await _locate_mage_email_input(page, worker_id)
    await email_input.fill("")
    await email_input.fill(email)
    await page.keyboard.press("Enter")
    for _ in range(20):
        await page.wait_for_timeout(200)
        note = await _mage_notification_text(page)
        status = _classify_mage_email_notification(note)
        if status != "unknown":
            if note:
                log.info("[W%d] 📨 Mage notification (%s): %s", worker_id, status, note[:120])
            return status
        try:
            if await page.locator(".mage-Notification-title").count() > 0:
                status = _classify_mage_email_notification(await _mage_notification_text(page))
                if status != "unknown":
                    return status
        except Exception:
            pass
    return "unknown"


@async_timeout(100.0)
async def _mage_login_via_maildev(
    s: WorkerSession,
    app: Optional[Application] = None,
    job: Optional[Job] = None,
) -> tuple[str, Page]:
    """Log in via temp mail; open the magic link on the same tab that submitted the email."""
    mage_page = await _new_page(s)
    try:
        mailbox_lock = _get_builder_mailbox_lock(s.worker_id)

        async def _create_inbox() -> str:
            async with mailbox_lock:
                return await create_maildev_mailbox(s)

        # Parallel: open Mage form while creating SecureTempMail inbox.
        form_task = asyncio.create_task(_open_mage_login_form(mage_page, s.worker_id))
        inbox_task = asyncio.create_task(_create_inbox())
        try:
            await form_task
            email = await inbox_task
        except Exception:
            form_task.cancel()
            inbox_task.cancel()
            raise
        log.info("[W%d] 📧 Generated email: %s", s.worker_id, email)

        for attempt in range(MAGE_EMAIL_MAX_ATTEMPTS):
            if attempt > 0:
                await update_status(
                    app, job,
                    f"Login retry ({attempt + 1}/{MAGE_EMAIL_MAX_ATTEMPTS})…",
                )
                async with mailbox_lock:
                    email = await rotate_maildev_mailbox(s)
                log.info("[W%d] 📧 Retry email: %s", s.worker_id, email)
                mage_page = await _recycle_mage_login_page(s, mage_page)

            await update_status(app, job, "Sending verification link... ✉️")
            status = await _submit_mage_login_email(mage_page, email, s.worker_id)
            if status == "rejected":
                log.warning("[W%d] ⛔ Mage rejected %s — rotating mailbox", s.worker_id, email)
                if s.worker_id < 0 and BUILDER_REJECTION_COOLDOWN_SEC > 0:
                    await asyncio.sleep(BUILDER_REJECTION_COOLDOWN_SEC)
                continue

            await update_status(app, job, "Waiting for verification link... 📬")
            poll_attempts = 36 if status == "sent" else 28
            magic_url = await _fetch_magic_link_via_maildev(
                s, max_attempts=poll_attempts, delay=0.9, start_delay=0.15,
            )
            if not magic_url:
                late = _classify_mage_email_notification(await _mage_notification_text(mage_page))
                if late == "rejected":
                    log.warning("[W%d] ⛔ Mage rejected %s (late toast) — rotating", s.worker_id, email)
                    if s.worker_id < 0 and BUILDER_REJECTION_COOLDOWN_SEC > 0:
                        await asyncio.sleep(BUILDER_REJECTION_COOLDOWN_SEC)
                else:
                    log.warning(
                        "[W%d] ⚠️ No magic link for %s (attempt %d/%d)",
                        s.worker_id, email, attempt + 1, MAGE_EMAIL_MAX_ATTEMPTS,
                    )
                continue

            magic_url = _normalize_magic_url(magic_url)
            await update_status(app, job, "Verifying login link... 🔑")
            log.info("[W%d] 🔑 Opening magic link in login tab …", s.worker_id)
            try:
                await mage_page.goto(magic_url, wait_until="domcontentloaded", timeout=25_000)
            except Exception as nav_err:
                log.warning("[W%d] ⚠️ Magic link navigation: %s", s.worker_id, nav_err)

            if await _wait_magic_link_auth(mage_page, s.worker_id):
                log.info("[W%d] ✅ Magic link login OK for %s", s.worker_id, email)
                return email, mage_page

            log.warning(
                "[W%d] ⚠️ Magic link did not complete for %s — new email/link (attempt %d/%d)",
                s.worker_id, email, attempt + 1, MAGE_EMAIL_MAX_ATTEMPTS,
            )
            mage_page = await _recycle_mage_login_page(s, mage_page)

        raise RuntimeError(
            f"Mage login failed after {MAGE_EMAIL_MAX_ATTEMPTS} attempts "
            "(email block, missing link, or magic-link auth error)"
        )
    except Exception:
        try:
            await mage_page.close()
        except Exception:
            pass
        raise


async def _mage_magic_link_via_maildev(
    s: WorkerSession,
    app: Optional[Application] = None,
    job: Optional[Job] = None,
) -> tuple[str, str]:
    """Backward-compatible helper — prefer _mage_login_via_maildev (returns authenticated page)."""
    email, page = await _mage_login_via_maildev(s, app, job)
    return email, page.url


async def _apply_storage_state_to_context(ctx: BrowserContext, page: Page, storage_state_path: str):
    import json
    import os
    if not storage_state_path or not os.path.exists(storage_state_path):
        return
    try:
        with open(storage_state_path, 'r', encoding='utf-8') as f:
            state = json.load(f)
        
        await ctx.clear_cookies()
        try:
            await page.evaluate("() => { localStorage.clear(); sessionStorage.clear(); }")
        except Exception:
            pass
            
        if "cookies" in state:
            await ctx.add_cookies(state["cookies"])
            
        if "origins" in state:
            for origin_data in state["origins"]:
                if "mage.space" in origin_data.get("origin", ""):
                    ls = origin_data.get("localStorage", [])
                    for item in ls:
                        key = item.get("name")
                        val = item.get("value")
                        try:
                            await page.evaluate("([k, v]) => localStorage.setItem(k, v)", [key, val])
                        except Exception:
                            pass
    except Exception as e:
        log.warning("Failed to apply storage state to context: %s", e)


async def _setup_account(s: WorkerSession, app: Optional[Application] = None, job: Optional[Job] = None) -> Page:
    s.account_count += 1
    s.is_new_session = True
    s.used_pooled_session = False
    await _close_mail_page(s)

    email = None
    try:
        # ── Fresh email + magic link login (every job) ─────────────────────────────
        log.info("[W%d] 📧 Mailbox (account #%d) …", s.worker_id, s.account_count)
        await update_status(app, job, "Creating temporary email... 📧")

        # Force a fresh context to guarantee zero state carry-over
        if s.ctx:
            try: await s.ctx.close()
            except Exception: pass
            s.ctx = None
        await _ensure_ctx(s)
        email, page = await _mage_login_via_maildev(s, app, job)
        log.info("[W%d] ✅ Logged in via magic link: %s", s.worker_id, email)
        await page.wait_for_timeout(150)

        # Try to skip onboarding — give it more time to render
        onboarding_skipped = False
        for sel in ["text=Skip and explore", "a:has-text('Skip')", "text=Skip", "button:has-text('Skip')", "[role='button']:has-text('Skip')"]:
            try:
                el = page.locator(sel).first
                await el.wait_for(state="visible", timeout=5000)
                await stable_click(page, el, timeout_ms=3000)
                log.info("[W%d] ✅ Skipped onboarding", s.worker_id)
                onboarding_skipped = True
                await page.wait_for_timeout(150)
                break
            except Exception:
                pass

        if not onboarding_skipped:
            log.info("[W%d] ⏭️ No onboarding skip button found — navigating directly to /explore", s.worker_id)

        await _dismiss_blocking_overlays(page, s.worker_id)
        await _read_gems(s, page)
        log.info("[W%d] ✅ Logged in! %s  Gems: %d", s.worker_id, email, s.gems)

        is_posing = job and job.pipeline == "posing"
        is_video = job and job.pipeline == "video"
        if is_posing:
            try:
                log.info("[W%d] 🧘 Navigating to /models for posing (was: %s)…", s.worker_id, page.url[:80])
                await _navigate_to_posing_model(page, s.worker_id)
            except Exception as _nav_err:
                log.warning("[W%d] ⚠️ Post-login /models navigation failed: %s — retrying once", s.worker_id, _nav_err)
                try:
                    await _navigate_to_posing_model(page, s.worker_id)
                except Exception as _retry_err:
                    log.warning("[W%d] ⚠️ Post-login /models navigation retry also failed: %s", s.worker_id, _retry_err)
                    raise
        elif is_video:
            try:
                log.info("[W%d] 🎬 Navigating to /models for video (was: %s)…", s.worker_id, page.url[:80])
                await _navigate_to_video_model(page, s.worker_id)
            except Exception as _nav_err:
                log.warning("[W%d] ⚠️ Post-login Kiwi navigation failed: %s — retrying once", s.worker_id, _nav_err)
                try:
                    await _navigate_to_video_model(page, s.worker_id)
                except Exception as _retry_err:
                    log.warning("[W%d] ⚠️ Post-login Kiwi navigation retry also failed: %s", s.worker_id, _retry_err)
                    raise
        else:
            # ALWAYS navigate to /explore after login — even if the URL already contains
            # "explore", the onboarding redirect may leave us on /explore?onboarding=1
            # which doesn't have the prompt-bar UI. Forcing a clean /explore load guarantees
            # the full UI (aspect button, model picker, etc.) is present.
            try:
                log.info("[W%d] 🌐 Navigating to /explore after login (was: %s)…", s.worker_id, page.url[:80])
                await page.goto(MAGE_EXPLORE, wait_until="domcontentloaded", timeout=15_000)
                await _wait_explore_ready(page, s.worker_id, timeout_ms=15_000)
                await _dismiss_blocking_overlays(page, s.worker_id)
            except Exception as _nav_err:
                log.warning("[W%d] ⚠️ Post-login /explore navigation failed: %s — retrying once", s.worker_id, _nav_err)
                try:
                    await page.goto(MAGE_EXPLORE, wait_until="domcontentloaded", timeout=15_000)
                    await _wait_explore_ready(page, s.worker_id, timeout_ms=15_000)
                    await _dismiss_blocking_overlays(page, s.worker_id)
                except Exception as _retry_err:
                    log.warning("[W%d] ⚠️ Post-login /explore navigation retry also failed (non-critical): %s", s.worker_id, _retry_err)

        s.email     = email
        s.mage_page = page

        # Register session as in_use so no other worker steals it while this job runs
        if acct_manager is not None:
            ctx = await _ensure_ctx(s)
            owner_uid = job.user_id if job else WORKER_USER_MAP.get(s.worker_id)
            if await _save_session_to_pool(ctx, email, s.gems, s.worker_id, owner_user_id=owner_uid):
                s.acquired_username = email
                with acct_manager._lock:
                    acct = acct_manager._accounts.get(email)
                    if acct:
                        acct.in_use = True
                        acct.in_use_since = time.time()
                        acct.save()
                log.info("[W%d] 💾 Login registered (in_use) for finalize tracking", s.worker_id)

        return page

    finally:
        await _close_mail_page(s)



# ── Gem reader ────────────────────────────────────────────────────────────────

async def _read_gems(s: WorkerSession, page: Page):
    """Gems tracking disabled: sessions are used exactly once and discarded."""
    pass


async def _read_gems_remaining_detailed(page: Page) -> tuple[Optional[int], str]:
    """Return (gems, source) where source is 'promptbar', 'body', or 'failed'.

    Uses matchAll and returns the maximum value found — avoids false 0 reads
    when the page briefly shows a stale low count before welcome gems load."""
    try:
        result = await page.evaluate("""() => {
            function maxGemsFromText(text) {
                if (!text) return null;
                const matches = [...text.matchAll(/(\\d+)\\s*Gems?\\s*Remaining/gi)];
                if (!matches.length) return null;
                let max = 0;
                for (const m of matches) max = Math.max(max, parseInt(m[1], 10));
                return max > 0 ? max : null;
            }
            const bar = document.querySelector("[data-promptbar='true']");
            if (bar) {
                const g = maxGemsFromText(bar.innerText || "");
                if (g) return {gems: String(g), source: "promptbar"};
            }
            const g2 = maxGemsFromText(document.body.innerText || "");
            if (g2) return {gems: String(g2), source: "body"};
            return null;
        }""")
        if result:
            return int(result["gems"]), result["source"]
        return None, "failed"
    except Exception:
        return None, "failed"


async def _log_gems_debug_snippet(page: Page, worker_id: int = 0) -> None:
    """Log promptbar/body text around gem labels when pool gem read fails."""
    try:
        snippet = await page.evaluate("""() => {
            const bar = document.querySelector("[data-promptbar='true']");
            const barText = bar ? (bar.innerText || "").substring(0, 300) : "no promptbar";
            const body = document.body.innerText || "";
            const idx = body.toLowerCase().indexOf("gem");
            const bodySnippet = idx >= 0
                ? body.substring(Math.max(0, idx - 20), idx + 180)
                : "no gem text in body";
            return JSON.stringify({ promptbar: barText, bodyAroundGem: bodySnippet });
        }""")
        log.warning("[W%d] Gems debug snippet: %s", worker_id, snippet)
    except Exception as e:
        log.debug("[W%d] Gems debug snippet failed: %s", worker_id, e)


async def _read_pool_gems(page: Page, *, retries: int = 3) -> tuple[Optional[int], str]:
    """Read gems for pool builder with short retries after Explore UI is ready."""
    last_source = "failed"
    for attempt in range(retries):
        gems, source = await _read_gems_remaining_detailed(page)
        last_source = source
        if gems is not None:
            return gems, source
        if attempt < retries - 1:
            await page.wait_for_timeout(250)
    return None, last_source


@async_timeout(50.0)
async def _wait_for_pool_gems(
    page: Page,
    *,
    timeout_ms: int = 20_000,
    min_gems: int = MIN_POOL_GEMS,
    allow_reload: bool = True,
) -> tuple[Optional[int], str]:
    """Wait until gems text is visible, stable, and meets pool threshold.

    Treats gems==0 as not loaded yet. Requires two consecutive reads >= min_gems."""
    last_source = "failed"

    async def _poll_until(deadline: float) -> tuple[Optional[int], str]:
        nonlocal last_source
        stable_gems: Optional[int] = None
        while time.time() < deadline:
            gems, source = await _read_gems_remaining_detailed(page)
            last_source = source
            if gems is None or gems == 0 or gems < min_gems:
                stable_gems = None
                await page.wait_for_timeout(250)
                continue
            if stable_gems == gems:
                return gems, source
            stable_gems = gems
            await page.wait_for_timeout(250)
        gems, source = await _read_gems_remaining_detailed(page)
        last_source = source
        if gems is not None and gems >= min_gems:
            return gems, source
        return gems, source if gems is not None else last_source

    deadline = time.time() + timeout_ms / 1000
    gems, source = await _poll_until(deadline)
    if gems is not None and gems >= min_gems:
        return gems, source

    if allow_reload and (gems is None or gems == 0 or gems < min_gems):
        log.warning(
            "🔧 Session builder: gems not ready (have %s, need %d) — reloading explore once",
            gems, min_gems,
        )
        try:
            await page.reload(wait_until="domcontentloaded", timeout=15_000)
            await _dismiss_blocking_overlays(page, -1, quiet=True, skip_escape=True)
            await _wait_promptbar_ready(page, -1, timeout_ms=12_000)
        except Exception as reload_err:
            log.warning("🔧 Session builder: gems reload failed: %s", reload_err)
        deadline = time.time() + timeout_ms / 1000
        gems, source = await _poll_until(deadline)

    if gems is not None and gems >= min_gems:
        return gems, source
    return gems, source if gems is not None else last_source


async def _ensure_guava_on_page(
    page: Page,
    worker_id: int,
    *,
    rounds: int = 3,
    context: str = "",
) -> bool:
    """Retry Guava V1 selection with explore reloads until verified or rounds exhausted."""
    tag = f" ({context})" if context else ""
    for round_num in range(rounds):
        if round_num > 0:
            log.info(
                "[W%d] 🔄 Guava ensure round %d/%d%s",
                worker_id, round_num + 1, rounds, tag,
            )
            try:
                await page.goto(MAGE_EXPLORE, wait_until="domcontentloaded", timeout=20_000)
                await _wait_explore_ready(
                    page, worker_id, timeout_ms=25_000, require_promptbar=True, quiet=True,
                )
                await _dismiss_blocking_overlays(page, worker_id, quiet=True, skip_escape=True)
                await page.wait_for_timeout(1_000)
            except Exception as reload_err:
                log.debug("[W%d] Guava ensure reload failed: %s", worker_id, reload_err)

        if await _guava_is_selected(page, worker_id):
            return True
        if not await _wait_model_dropdown(page, worker_id, timeout_ms=20_000):
            continue
        try:
            await _select_guava_pro_fast(page, worker_id)
        except Exception as sel_err:
            log.debug("[W%d] Guava select round %d failed: %s", worker_id, round_num + 1, sel_err)
        if await _wait_for_guava_selected(page, worker_id, timeout_ms=12_000):
            return True

    return await _guava_is_selected(page, worker_id)


async def _build_new_session_in_background(
    owner_user_id: int | None = None,
    builder_id: int = 0,
) -> bool:
    """Build one Mage.space session for the pool on a dedicated builder (worker_id<0).

    Uses its own browser/mailbox — never touches job worker sessions or locks."""
    global _builder_busy_count
    worker_id = -(builder_id + 1)
    log.info(
        "🔧 Session builder #%d: starting replacement session (owner_user=%s)...",
        builder_id, owner_user_id,
    )
    s = _get_builder_session(builder_id)
    wid = s.worker_id
    _builder_busy_count += 1
    await asyncio.sleep(0)  # yield before heavy work so job workers stay responsive
    
    email = None
    try:
        if s.ctx:
            try:
                await s.ctx.close()
            except Exception:
                pass
            s.ctx = None
        await _ensure_ctx(s)
        
        try:
            email, page = await _mage_login_via_maildev(s)
        except Exception as e:
            log.error("🔧 Session builder: login failed: %s", e)
            await _teardown_browser_stack(s)
            return False
        await asyncio.sleep(0)
        log.info("🔧 Session builder: logged in as %s", email)
        s.mage_page = page
        await page.wait_for_timeout(150)
        
        # Skip onboarding — give it more time to render
        for sel in ["text=Skip and explore", "a:has-text('Skip')", "text=Skip", "button:has-text('Skip')", "[role='button']:has-text('Skip')"]:
            try:
                el = page.locator(sel).first
                await el.wait_for(state="visible", timeout=5000)
                await stable_click(page, el, timeout_ms=3000)
                await page.wait_for_timeout(150)
                break
            except Exception:
                pass
                
        await _dismiss_blocking_overlays(page, wid)
        
        explore_ready = False
        for explore_try in range(3):
            if explore_try > 0:
                log.info("🔧 Session builder: explore retry %d/3 for %s", explore_try + 1, email)
                try:
                    await page.goto(MAGE_EXPLORE, wait_until="domcontentloaded", timeout=20_000)
                except Exception as nav_err:
                    if _is_transient_page_error(nav_err):
                        log.debug("🔧 Session builder: explore nav interrupted on retry — settling")
                        await page.wait_for_timeout(1500)
                    else:
                        log.debug("🔧 Session builder: explore nav retry failed: %s", nav_err)
            else:
                try:
                    await page.goto(MAGE_EXPLORE, wait_until="domcontentloaded", timeout=15_000)
                except Exception as nav_err:
                    if _is_transient_page_error(nav_err):
                        log.debug("🔧 Session builder: explore nav interrupted — settling")
                        await page.wait_for_timeout(1500)
                    else:
                        raise

            timeout_ms = 18_000 + explore_try * 6_000
            if await _wait_explore_ready(
                page, wid, timeout_ms=timeout_ms, require_promptbar=True, quiet=explore_try == 0
            ):
                explore_ready = True
                break
            if explore_try < 2:
                try:
                    await page.reload(wait_until="domcontentloaded", timeout=15_000)
                except Exception as reload_err:
                    if not _is_transient_page_error(reload_err):
                        log.warning("🔧 Session builder: reload failed: %s", reload_err)

        if not explore_ready:
            log.warning(
                "🔧 Session builder: builder_abort_reason=explore_not_ready for %s",
                email,
            )
            await _teardown_browser_stack(s)
            return False
        await _dismiss_blocking_overlays(page, wid, quiet=True, skip_escape=True)

        initial_gems, gem_source = await _wait_for_pool_gems(page, timeout_ms=35_000)
        if initial_gems is None or initial_gems < MIN_POOL_GEMS:
            log.info("🔧 Session builder: gems still low — second explore reload for %s", email)
            try:
                await page.reload(wait_until="domcontentloaded", timeout=15_000)
                await _dismiss_blocking_overlays(page, wid, quiet=True, skip_escape=True)
                await _wait_explore_ready(page, wid, timeout_ms=20_000, require_promptbar=True, quiet=True)
            except Exception:
                pass
            initial_gems, gem_source = await _wait_for_pool_gems(
                page, timeout_ms=25_000, allow_reload=False,
            )
        if initial_gems is None or initial_gems < MIN_POOL_GEMS:
            await _log_gems_debug_snippet(page, wid)
            log.warning(
                "🔧 Session builder: builder_abort_reason=insufficient_gems "
                "(have %s, need %d, source=%s) for %s",
                initial_gems, MIN_POOL_GEMS, gem_source, email,
            )
            await _teardown_browser_stack(s)
            return False

        log.info(
            "🔧 Session builder: logged in %s, gems=%d (source=%s)",
            email, initial_gems, gem_source,
        )

        await _dismiss_blocking_overlays(page, wid, quiet=True, skip_escape=True)
        guava_ready = await _ensure_guava_on_page(
            page, wid, rounds=POOL_BUILDER_GUAVA_ROUNDS, context=email,
        )
        log.info("🔧 Session builder: Guava ready=%s for %s", guava_ready, email)

        if not guava_ready:
            log.warning(
                "🔧 Session builder: builder_abort_reason=guava_not_verified — rejecting %s",
                email,
            )
            await _teardown_browser_stack(s)
            return False
        if not await _validate_mage_session(page, wid, timeout_ms=8_000):
            log.warning(
                "🔧 Session builder: builder_abort_reason=invalid_session — rejecting %s",
                email,
            )
            await _teardown_browser_stack(s)
            return False

        ctx = await _ensure_ctx(s)
        # Hold in_use=True until live browser is parked — prevents workers stealing mid-handoff.
        if not await _save_session_to_pool(
            ctx, email, initial_gems, wid,
            guava_ready=True, in_use=True, owner_user_id=owner_user_id,
        ):
            log.error("🔧 Session builder: failed to save storage state for %s", email)
            await _teardown_browser_stack(s)
            return False

        if not await _park_live_pooled(email, s, initial_gems):
            async with _live_pool_lock:
                at_cap = MAX_LIVE_POOLED > 0 and len(_live_pooled_sessions) >= MAX_LIVE_POOLED
            if not at_cap:
                log.info(
                    "🔧 Session builder: disk session ready for %s (live park skipped)",
                    email,
                )

        if acct_manager is not None:
            with acct_manager._lock:
                acct = acct_manager._accounts.get(email)
                if acct:
                    acct.in_use = False
                    acct.in_use_since = 0.0
                    acct.save()

        live_ready = _count_live_ready() if LIVE_ONLY_POOL else (
            acct_manager.count_ready() if acct_manager else 0
        )
        log.info("🔧 Session builder: replacement ready for %s (pool %d/%d)",
                 email, live_ready, TARGET_POOL_SIZE)
        return True
        
    except Exception as e:
        log.error("🔧 Session builder: error: %s", e)
        await _teardown_browser_stack(s)
        return False
        
    finally:
        await _cleanup_builder_after_build(s)
        _builder_busy_count = max(0, _builder_busy_count - 1)


def _schedule_session_replacement() -> None:
    """Backward-compatible alias — always refill when pool is below target."""
    _ensure_pool_replacement(reason="send")


def _builder_retry_backoff(streak: int, *, maildev_down: bool) -> int:
    if maildev_down:
        return min(30 + streak * 5, 300)
    return min(2 ** streak, 8)


async def _delayed_builder_start(delay_sec: float, builder_id: int = 0) -> None:
    """Stagger session builder start after boot to reduce HF resource spike."""
    if delay_sec > 0:
        log.info(
            "🔧 Session builder #%d delayed %.0fs after boot (resource stagger)",
            builder_id, delay_sec,
        )
        await asyncio.sleep(delay_sec)
    await _dedicated_session_builder_loop(builder_id=builder_id)


async def _dedicated_session_builder_loop(builder_id: int = 0):
    """Dedicated builder worker — runs alongside job workers; parallel on localhost."""
    global _builder_fail_streak, _builder_last_maildev_warn
    if acct_manager is None:
        return
    log.info(
        "🔧 Dedicated session builder #%d started (target pool=%d)",
        builder_id, TARGET_POOL_SIZE,
    )
    while True:
        try:
            owner_uid = await _session_build_queue.get()
            if _pool_deficit(owner_uid) <= 0:
                log.debug("🔧 Builder #%d: pool full for user %d — skip build", builder_id, owner_uid)
            else:
                if _builder_should_pause_for_jobs():
                    ready = _count_live_ready() if LIVE_ONLY_POOL else acct_manager.count_ready()
                    log.info(
                        "🔧 Builder #%d: waiting for %d processing job(s) before building (pool ready=%d)…",
                        builder_id, _processing_job_count(), ready,
                    )
                await _wait_for_jobs_idle()
                ok = await _build_new_session_in_background(
                    owner_user_id=owner_uid, builder_id=builder_id,
                )
                if not ok:
                    _builder_fail_streak += 1
                    maildev_down = not _maildev_http_api_ok() and _on_hf
                    backoff = _builder_retry_backoff(_builder_fail_streak, maildev_down=maildev_down)
                    now = time.time()
                    if maildev_down and now - _builder_last_maildev_warn >= 300:
                        _builder_last_maildev_warn = now
                        log.error(
                            "🔧 Session pool cannot refill — Maildev API unreachable from HF "
                            "(streak=%d). Run scripts/setup_maildev_gas.ps1 then py deploy.py",
                            _builder_fail_streak,
                        )
                    elif not maildev_down or _builder_fail_streak <= 3:
                        log.warning(
                            "🔧 Session builder failed — retry in %ds (streak=%d)",
                            backoff, _builder_fail_streak,
                        )
                    else:
                        log.debug(
                            "🔧 Session builder failed — retry in %ds (streak=%d)",
                            backoff, _builder_fail_streak,
                        )
                    await asyncio.sleep(backoff)
                    _ensure_pool_replacement(reason="builder-retry")
                else:
                    _builder_fail_streak = 0
                    if _pool_deficit() > 0:
                        _ensure_pool_replacement(reason="builder-continue")
            _session_build_queue.task_done()
        except Exception as e:
            log.error("🔧 Dedicated builder loop error: %s", e)
            _builder_fail_streak += 1
            _ensure_pool_replacement(reason="builder-error")
            await asyncio.sleep(min(2 ** _builder_fail_streak, 10))


async def _pool_maintenance_loop():
    """Keep session pool healthy: recover stale locks, purge invalid entries, refill when low."""
    if acct_manager is None:
        return
    while True:
        try:
            ready = _count_live_ready() if LIVE_ONLY_POOL else acct_manager.count_ready()
            if (
                _pool_deficit() > 0
                and _builder_busy_count == 0
                and _session_build_queue.qsize() == 0
                and not _builder_should_pause_for_jobs()
            ):
                _ensure_pool_replacement(reason="maintenance")
            building = _builder_busy_count > 0 or _session_build_queue.qsize() > 0
            await asyncio.sleep(
                10 if building else (3 if ready == 0 else 15 if ready < TARGET_POOL_SIZE else 45)
            )
            # sweep and purge are synchronous — call directly
            recovered = acct_manager.sweep_stale_in_use(SESSION_STALE_SEC)
            purged = acct_manager.purge_invalid()
            stats = acct_manager.pool_stats()
            live_ready = _count_live_ready() if LIVE_ONLY_POOL else stats["ready"]
            if recovered or purged:
                log.info(
                    "🔧 Pool maintenance: recovered=%d purged=%d ready=%d/%d builders_busy=%d pending=%d",
                    recovered, purged, live_ready, TARGET_POOL_SIZE,
                    _builder_busy_count, _session_build_queue.qsize(),
                )
            elif live_ready < TARGET_POOL_SIZE and not building:
                log.info(
                    "🔧 Pool maintenance: recovered=%d purged=%d ready=%d/%d builders_busy=%d pending=%d",
                    recovered, purged, live_ready, TARGET_POOL_SIZE,
                    _builder_busy_count, _session_build_queue.qsize(),
                )
        except Exception as e:
            log.error("Pool maintenance error: %s", e)
            await asyncio.sleep(60)


# ── Get or refresh mage page ──────────────────────────────────────────────────

_CLEAR_PROMPTBAR_REFERENCE_JS = """() => {
    let prevSrc = "";
    const bar = document.querySelector("[data-promptbar='true']");
    const editor = document.querySelector("div.promptbar-textarea div.tiptap.ProseMirror");
    const refSrc = (img) => img && img.src && img.src.startsWith("http");
    if (bar) {
        for (const img of bar.querySelectorAll("img")) {
            if (img.alt === "Send") continue;
            if (refSrc(img)) { prevSrc = img.src; break; }
        }
    }
    if (!prevSrc && editor) {
        const img = editor.querySelector("img");
        if (refSrc(img)) prevSrc = img.src;
    }
    if (editor) {
        editor.querySelectorAll('img, [data-type="image"]').forEach((n) => n.remove());
        editor.focus();
        editor.dispatchEvent(new Event("input", { bubbles: true }));
    }
    if (bar) {
        bar.querySelectorAll('[data-type="image"]').forEach((n) => n.remove());
        for (const img of bar.querySelectorAll("img")) {
            if (img.alt !== "Send") img.remove();
        }
    }
    return prevSrc || "";
}"""


async def _clear_promptbar_reference(page: Page) -> str:
    """Remove stale reference images from the prompt bar; return previous ref src."""
    try:
        return str(await page.evaluate(_CLEAR_PROMPTBAR_REFERENCE_JS) or "")
    except Exception:
        return ""


async def _get_promptbar_reference_src(page: Page) -> str:
    try:
        return str(await page.evaluate("""() => {
            const bar = document.querySelector("[data-promptbar='true']");
            const okSrc = (src) => src && (
                src.startsWith("http") || src.startsWith("blob:")
            );
            if (bar) {
                for (const img of bar.querySelectorAll("img")) {
                    if (img.alt === "Send") continue;
                    if (okSrc(img.src)) return img.src;
                }
            }
            const editor = document.querySelector("div.promptbar-textarea div.tiptap.ProseMirror");
            if (editor) {
                const img = editor.querySelector("img");
                if (img && okSrc(img.src)) return img.src;
                if (editor.querySelectorAll('[data-type="image"]').length > 0) return "attached";
            }
            return "";
        }""") or "")
    except Exception:
        return ""


_PROMPTBAR_REFERENCE_COUNT_JS = """() => {
    const bar = document.querySelector("[data-promptbar='true']");
    const editor = document.querySelector("div.promptbar-textarea div.tiptap.ProseMirror");
    const seen = new Set();
    const add = (el) => {
        if (!el) return;
        if (el.tagName === "IMG" && el.alt === "Send") return;
        const img = el.tagName === "IMG" ? el : (el.querySelector ? el.querySelector("img") : null);
        if (img && img.alt === "Send") return;
        const src = img && img.src ? img.src : "";
        const key = src || (el.outerHTML || "").slice(0, 160);
        if (key) seen.add(key);
    };
    if (editor) {
        editor.querySelectorAll('img, [data-type="image"]').forEach(add);
    }
    if (bar) {
        bar.querySelectorAll(
            'img:not([alt="Send"]), [data-type="image"], [class*="reference"], [class*="thumbnail"], [class*="Reference"]'
        ).forEach(add);
    }
    return seen.size;
}"""


async def _count_promptbar_references(page: Page) -> int:
    try:
        return int(await page.evaluate(_PROMPTBAR_REFERENCE_COUNT_JS) or 0)
    except Exception:
        return 0


_PROMPTBAR_REFERENCE_SRCS_JS = """() => {
    const bar = document.querySelector("[data-promptbar='true']");
    const editor = document.querySelector("div.promptbar-textarea div.tiptap.ProseMirror");
    const seen = new Set();
    const refs = [];
    const add = (el) => {
        if (!el) return;
        if (el.tagName === "IMG" && el.alt === "Send") return;
        const img = el.tagName === "IMG" ? el : (el.querySelector ? el.querySelector("img") : null);
        if (img && img.alt === "Send") return;
        const src = img && img.src ? img.src : "";
        const key = src || (el.outerHTML || "").slice(0, 160);
        if (key && !seen.has(key)) {
            seen.add(key);
            refs.push(src || key);
        }
    };
    if (editor) {
        editor.querySelectorAll('img, [data-type="image"]').forEach(add);
    }
    if (bar) {
        bar.querySelectorAll(
            'img:not([alt="Send"]), [data-type="image"], [class*="reference"], [class*="thumbnail"], [class*="Reference"]'
        ).forEach(add);
    }
    return refs;
}"""


def _is_cdn_reference_src(src: str) -> bool:
    return bool(
        src
        and src.startswith("http")
        and ("cdn" in src or "uploads" in src or "mage.space" in src)
    )


async def _get_promptbar_reference_srcs(page: Page) -> list[str]:
    try:
        raw = await page.evaluate(_PROMPTBAR_REFERENCE_SRCS_JS) or []
        return [str(s) for s in raw if s]
    except Exception:
        return []


@async_timeout(50.0)
async def _wait_for_reference_count(page: Page, minimum: int, timeout_ms: int = 45_000) -> bool:
    deadline = time.time() + timeout_ms / 1000
    while time.time() < deadline:
        try:
            if await _count_promptbar_references(page) >= minimum:
                return True
        except Exception:
            pass
        await page.wait_for_timeout(450)
    return False


@async_timeout(50.0)
async def _wait_for_additional_reference(
    page: Page,
    known_srcs: list[str],
    before_count: int,
    timeout_ms: int = 45_000,
) -> str:
    """Wait until a new reference appears beyond known_srcs / before_count."""
    known = set(known_srcs or [])
    deadline = time.time() + timeout_ms / 1000
    while time.time() < deadline:
        try:
            current_srcs = await _get_promptbar_reference_srcs(page)
            count = await _count_promptbar_references(page)
            for src in current_srcs:
                if src not in known and (_is_cdn_reference_src(src) or src == "attached"):
                    if _is_cdn_reference_src(src):
                        return src
                    return "attached"
            if count > before_count:
                for src in current_srcs:
                    if src not in known:
                        return src if _is_cdn_reference_src(src) else "attached"
                return "attached"
            has_new_editor = await page.evaluate(
                """(known) => {
                    const editor = document.querySelector(
                        "div.promptbar-textarea div.tiptap.ProseMirror"
                    );
                    if (!editor) return false;
                    for (const node of editor.querySelectorAll('img, [data-type="image"]')) {
                        const img = node.tagName === "IMG" ? node : node.querySelector("img");
                        const src = img && img.src ? img.src : "";
                        if (src && src.startsWith("http") && !known.includes(src)) return true;
                        if (!src && node.getAttribute("data-type") === "image") return true;
                    }
                    return false;
                }""",
                list(known),
            )
            if has_new_editor:
                return "attached"
        except Exception as e:
            log.debug("Additional reference poll error: %s", e)
        await page.wait_for_timeout(450)
    try:
        now_count = await _count_promptbar_references(page)
    except Exception:
        now_count = -1
    log.debug(
        "Additional reference timeout (before_count=%d, known=%d, now_count=%s)",
        before_count, len(known), now_count,
    )
    return ""


async def _click_add_reference_button(page: Page, worker_id: int = 0) -> bool:
    """Click Mage prompt-bar + control to add another reference thumbnail."""
    try:
        clicked = await page.evaluate("""() => {
            const bar = document.querySelector("[data-promptbar='true']");
            if (!bar) return false;
            const refImgs = bar.querySelectorAll('img[class*="Image-root"]');
            if (refImgs.length > 0) {
                const refContainer = refImgs[refImgs.length - 1].closest("div");
                if (refContainer && refContainer.parentElement) {
                    for (const btn of refContainer.parentElement.querySelectorAll("button")) {
                        const t = (btn.innerText || btn.textContent || "").trim();
                        const label = (btn.getAttribute("aria-label") || "").toLowerCase();
                        if (t === "+" || t === "＋" || label.includes("add") || label.includes("upload")) {
                            btn.click();
                            return true;
                        }
                    }
                }
            }
            for (const btn of bar.querySelectorAll("button")) {
                const t = (btn.innerText || btn.textContent || "").trim();
                const label = (btn.getAttribute("aria-label") || "").toLowerCase();
                if (t === "+" || t === "＋" || label.includes("add image") || label.includes("add reference")) {
                    if (btn.offsetParent !== null) {
                        btn.click();
                        return true;
                    }
                }
            }
            return false;
        }""")
        if clicked:
            log.info("[W%d] ✅ Clicked add-reference (+) button", worker_id)
            await page.wait_for_timeout(150)
            return True
    except Exception as e:
        log.debug("[W%d] add-reference button click failed: %s", worker_id, e)

    # SVG/icon-aware "+" detection: mage.space may have replaced the text "+" with
    # an icon-only button. Try aria-label / title matching first.
    try:
        clicked_svg = await page.evaluate("""() => {
            const bar = document.querySelector("[data-promptbar='true']");
            if (!bar) return false;
            const match = (s) => /add|upload|reference|attach/i.test(s);
            for (const btn of bar.querySelectorAll("button")) {
                if (btn.offsetParent === null) continue;
                const t = (btn.innerText || btn.textContent || "").trim();
                if (t === "+" || t === "\uff0b") { btn.click(); return true; }
                const al = btn.getAttribute("aria-label") || "";
                const title = btn.getAttribute("title") || "";
                if (match(al) || match(title)) {
                    // avoid clicking the model picker / aspect / send buttons
                    if (/send|model|aspect|video|image|character|advanced|autocreate/i.test(t)) {
                        // "Reference" chip itself has aria-label containing "reference" — skip it
                        continue;
                    }
                    btn.click();
                    return true;
                }
                // small square icon button (no text, has svg)
                if (!t && btn.querySelector("svg") && btn.offsetParent !== null) {
                    const r = btn.getBoundingClientRect();
                    if (r.width > 0 && r.width <= 48 && r.height <= 48) {
                        btn.click();
                        return true;
                    }
                }
            }
            return false;
        }""")
        if clicked_svg:
            log.info("[W%d] ✅ Clicked add-reference (icon/aria-label match)", worker_id)
            await page.wait_for_timeout(150)
            return True
    except Exception as e:
        log.debug("[W%d] add-reference icon/aria detection failed: %s", worker_id, e)

    try:
        plus_btn = page.locator("[data-promptbar='true'] button").filter(
            has_text=re.compile(r"^\+$")
        ).first
        if await plus_btn.count() > 0 and await plus_btn.is_visible():
            await stable_click(page, plus_btn, timeout_ms=2_000)
            log.info("[W%d] ✅ Clicked add-reference (+) via locator", worker_id)
            await page.wait_for_timeout(150)
            return True
    except Exception as e:
        log.debug("[W%d] add-reference locator click failed: %s", worker_id, e)
    return False


async def _snapshot_reference_state(page: Page) -> tuple[list[str], int]:
    known_srcs = await _get_promptbar_reference_srcs(page)
    before_count = await _count_promptbar_references(page)
    return known_srcs, before_count


@async_timeout(30.0)
async def _wait_for_reference_changed(
    page: Page, before_ref: str, timeout_ms: int = 25_000
) -> bool:
    """Wait until a new reference is attached (src differs from before_ref)."""
    src = await _wait_for_mage_reference_ready(page, before_ref, timeout_ms=timeout_ms)
    return bool(src)


@async_timeout(50.0)
async def _wait_for_mage_reference_ready(
    page: Page,
    before_ref: str,
    timeout_ms: int = 45_000,
) -> str:
    """Wait for a NEW Mage CDN reference URL that stays stable (upload finished).

    Returns the confirmed src, or \"\" if upload did not complete in time.
    """
    deadline = time.time() + timeout_ms / 1000
    last_src = ""
    stable_hits = 0
    while time.time() < deadline:
        src = await _get_promptbar_reference_src(page)
        is_cdn = bool(
            src
            and (
                src == "attached"
                or src.startswith("blob:")
                or (
                    src.startswith("http")
                    and ("cdn" in src or "uploads" in src or "mage.space" in src)
                )
            )
        )
        is_new = bool(src and (not before_ref or src != before_ref))
        if src == "attached":
            if await _reference_attached_in_promptbar(page):
                stable_hits += 1
                if stable_hits >= 2:
                    return "attached"
            else:
                stable_hits = 0
                last_src = ""
        elif not is_cdn or not is_new:
            stable_hits = 0
            last_src = ""
        elif src == last_src:
            stable_hits += 1
            if stable_hits >= 2:
                loaded = await page.evaluate(
                    """(expected) => {
                        const check = (img) => img && img.src === expected
                            && img.complete && img.naturalWidth >= 32;
                        const bar = document.querySelector("[data-promptbar='true']");
                        if (bar) {
                            for (const img of bar.querySelectorAll("img")) {
                                if (img.alt === "Send") continue;
                                if (check(img)) return true;
                            }
                        }
                        const editor = document.querySelector(
                            "div.promptbar-textarea div.tiptap.ProseMirror"
                        );
                        if (editor) {
                            for (const img of editor.querySelectorAll("img")) {
                                if (check(img)) return true;
                            }
                        }
                        return false;
                    }""",
                    src,
                )
                if loaded:
                    return src
                log.debug("CDN src stable but image not loaded yet: %s", src[:120])
        else:
            last_src = src
            stable_hits = 1
        await page.wait_for_timeout(450)
    return ""


async def _bulk_fast_prepare_page(page: Page, worker_id: int = 0) -> None:
    """Minimal editor reset between bulk images — clear refs + text, skip heavy overlays."""
    try:
        await _clear_promptbar_reference(page)
        await page.evaluate("""() => {
            const el = document.querySelector("div.promptbar-textarea div.tiptap.ProseMirror");
            if (el) {
                el.focus();
                el.textContent = "";
                el.dispatchEvent(new Event("input", { bubbles: true }));
            }
        }""")
        close_thumb = page.locator("div.mage-Center-root button").first
        if await close_thumb.count() > 0 and await close_thumb.is_visible():
            await stable_click(page, close_thumb, timeout_ms=800)
        # Scroll to top so the next pre-count only sees freshly generated images,
        # not stale ones scrolled above the viewport.
        try:
            await page.evaluate("window.scrollTo(0, 0)")
        except Exception:
            pass
        # Brief settle wait for any CSS transitions / lazy-loaded images to resolve
        await page.wait_for_timeout(150)
    except Exception as e:
        log.debug("[W%d] Bulk fast prepare fallback: %s", worker_id, e)
        await _light_prepare_page(page, worker_id)


async def _light_prepare_page(page: Page, worker_id: int = 0) -> None:
    """Clear textarea, close lingering menus/modals, and prepare the page for the next job."""
    try:
        await _dismiss_blocking_overlays(page, worker_id, quiet=True, skip_escape=True)
        await page.wait_for_timeout(100)
        
        # Clear the tiptap ProseMirror editor
        try:
            await page.evaluate('''() => {
                const el = document.querySelector("div.promptbar-textarea div.tiptap.ProseMirror");
                if (el) {
                    el.focus();
                    el.textContent = "";
                    el.dispatchEvent(new Event("input", { bubbles: true }));
                }
            }''')
        except Exception as e:
            log.warning("[W%d] Light prepare: could not clear prompt bar: %s", worker_id, e)
            
        # If there is a lingering upload thumbnail, click to dismiss it
        try:
            close_thumb = page.locator("div.mage-Center-root button").first
            if await close_thumb.count() > 0 and await close_thumb.is_visible():
                await stable_click(page, close_thumb, timeout_ms=1000)
        except Exception:
            pass
    except Exception as e:
        log.warning("[W%d] _light_prepare_page error: %s", worker_id, e)


async def _ensure_posing_model_ready(page: Page, worker_id: int = 0) -> None:
    """Ensure Grok model is active on prompt bar."""
    if not await _grok_is_selected(page, worker_id):
        await _select_grok_image_quality_fast(page, worker_id)



async def _get_mage_page(s: WorkerSession, app: Optional[Application] = None, job: Optional[Job] = None) -> Page:
    is_posing = job and job.pipeline == "posing"
    is_video = job and job.pipeline == "video"
    is_guava15 = job and job.pipeline == "guava15"
    is_gpt_image = job and job.pipeline == "gpt_image"
    is_mango3 = job and job.pipeline == "mango3"
    pipeline_name = (
        "video" if is_video
        else ("gpt_image" if is_gpt_image
        else ("mango3" if is_mango3
        else ("posing" if is_posing
        else ("guava15" if is_guava15 else "guava"))))
    )

    max_reuse = _browser_reuse_limit(job)
    bulk_continue = bool(job and _bulk_continuing(s, job))
    s.page_prepared_for_job = False
    timer = s.stage_timer

    if s.mage_page:
        is_valid = False
        if bulk_continue or (not s.session_committed and s.reuse_count < max_reuse):
            try:
                if not s.mage_page.is_closed():
                    is_valid = await _validate_mage_session(s.mage_page, s.worker_id, timeout_ms=4_000)
            except Exception:
                is_valid = False
                
        if is_valid:
            s.reuse_count += 1
            log.info(
                "[W%d] ⚡ Reusing active browser page (reuse_count=%d/%d, gems=%d, bulk=%s)",
                s.worker_id, s.reuse_count, max_reuse, s.gems, bulk_continue,
            )
            # Switch play-model workspace before clearing editor (posing/video need Kiwi/Grok URL)
            if is_posing:
                await _ensure_posing_model_ready(s.mage_page, s.worker_id)
            elif is_gpt_image:
                await _ensure_gpt_image_model_ready(s.mage_page, s.worker_id)
            elif is_mango3:
                await _ensure_mango_3_model_ready(s.mage_page, s.worker_id)
            elif is_video:
                await _ensure_video_model_ready(s.mage_page, s.worker_id)
            elif is_guava15 and not await _guava_15_is_selected(s.mage_page, s.worker_id):
                await _ensure_guava_15_model_ready(s.mage_page, s.worker_id)
            if bulk_continue:
                log.info("[W%d] 📦 Bulk continue — fast prepare only", s.worker_id)
                await _bulk_fast_prepare_page(s.mage_page, s.worker_id)
            else:
                await _light_prepare_page(s.mage_page, s.worker_id)
            s.page_prepared_for_job = True
            if timer:
                timer.mark("session_activate")
            return s.mage_page
        else:
            log.info("[W%d] 🔄 Resetting page & session (committed=%s, reuse_count=%d)", s.worker_id, s.session_committed, s.reuse_count)
            try: await s.mage_page.close()
            except Exception: pass
            s.mage_page = None
            s.reuse_count = 0

    owner_uid = job.user_id if job else WORKER_USER_MAP.get(s.worker_id)
    if acct_manager is not None and TARGET_POOL_SIZE > 0 and not bulk_continue:
        pool_wait = POOL_ACQUIRE_WAIT
        if job and job.is_bulk and getattr(job, "bulk_index", 1) == 1:
            pool_wait = POOL_ACQUIRE_WAIT + POOL_BUILDER_GRACE
        pool_t0 = time.time()
        acct = await _async_acquire_pooled_session(
            max_wait=pool_wait, owner_user_id=owner_uid
        )
        if timer:
            timer.add("pool_acquire", time.time() - pool_t0)
        if acct:
            activate_t0 = time.time()
            page = await _activate_pooled_session(s, acct, app, job)
            if page:
                if timer:
                    timer.add("session_activate", time.time() - activate_t0)
                if is_posing:
                    log.info("[W%d] ⚡ Prewarmed session — switching to Grok for posing", s.worker_id)
                    await _ensure_posing_model_ready(page, s.worker_id)
                elif is_gpt_image:
                    log.info("[W%d] ⚡ Prewarmed session — switching to GPT Image 2", s.worker_id)
                    await _ensure_gpt_image_model_ready(page, s.worker_id)
                elif is_mango3:
                    log.info("[W%d] ⚡ Prewarmed session — switching to Mango 3", s.worker_id)
                    await _ensure_mango_3_model_ready(page, s.worker_id)
                elif is_video:
                    log.info("[W%d] ⚡ Prewarmed session — switching to Kiwi for video", s.worker_id)
                    await _ensure_video_model_ready(page, s.worker_id)
                elif is_guava15:
                    log.info("[W%d] ⚡ Prewarmed session — switching to Guava 1.5", s.worker_id)
                    if not await _guava_15_is_selected(page, s.worker_id):
                        await _ensure_guava_15_model_ready(page, s.worker_id)
                return page
            log.warning("[W%d] Pooled session activation failed — falling back to fresh login", s.worker_id)

    # Safety net on HF: if builder is actively running and email API is unreachable,
    # wait for the builder rather than attempting a doomed fresh-login.
    if _pool_replacement_pending() and not _maildev_http_api_ok() and _on_hf:
        log.warning(
            "[W%d] ⏳ Pool empty + Maildev unreachable on HF — waiting %ds for builder before fresh login attempt",
            s.worker_id, int(POOL_BUILDER_GRACE),
        )
        pool_t0 = time.time()
        acct = await _async_acquire_pooled_session(
            max_wait=POOL_BUILDER_GRACE, owner_user_id=owner_uid,
        )
        if timer and "pool_acquire" not in timer.stages:
            timer.add("pool_acquire", time.time() - pool_t0)
        if acct:
            activate_t0 = time.time()
            page = await _activate_pooled_session(s, acct, app, job)
            if page:
                if timer:
                    timer.add("session_activate", time.time() - activate_t0)
                return page
        log.warning("[W%d] ⚠️ Builder grace expired with no session — attempting fresh login anyway", s.worker_id)

    log.info("[W%d] 🔄 Fresh login (gems=%d, pipeline=%s) …", s.worker_id, s.gems, pipeline_name)
    fresh_t0 = time.time()
    page = await _setup_account(s, app, job)
    if timer:
        if "pool_acquire" not in timer.stages:
            timer.add("pool_acquire", 0.0)
        timer.add("session_activate", time.time() - fresh_t0)
    return page


async def stable_click(page: Page, locator: Locator, timeout_ms: int = 15000) -> bool:
    """Wait for the element to stop moving, sleep 200ms to let transitions settle, and click."""
    try:
        # Wait for the element to be visible first
        await locator.wait_for(state="visible", timeout=timeout_ms)
        
        # Poll bounding box to ensure stability
        prev_box = None
        start_time = time.time()
        while (time.time() - start_time) < (timeout_ms / 1000.0):
            box = await locator.bounding_box()
            if not box:
                await page.wait_for_timeout(80)
                continue
            if prev_box:
                # Check if coordinates/size changed
                diff = abs(box['x'] - prev_box['x']) + abs(box['y'] - prev_box['y']) + \
                       abs(box['width'] - prev_box['width']) + abs(box['height'] - prev_box['height'])
                if diff < 0.5:
                    break
            prev_box = box
            await page.wait_for_timeout(80)
            
        # Add 100ms sleep for CSS transitions to settle
        await page.wait_for_timeout(100)
        
        # Perform the click
        try:
            await locator.click(timeout=3000)
        except Exception:
            try:
                await locator.click(timeout=3000, force=True)
            except Exception:
                await locator.evaluate("el => el.click()")
        return True
    except Exception as e:
        log.warning("stable_click failed: %s", e)
        return False


async def click_button_by_text(page: Page, text: str, timeout_ms: int = 15000, parent_locator: Optional[Locator] = None) -> bool:
    """Resilient button finder and clicker that handles roles, text, patterns,
    and falls back to page-level searches or custom containers.
    """
    root = parent_locator if parent_locator is not None else page
    
    # Try various locator strategies in priority order
    selectors = [
        root.get_by_role("button", name=text, exact=True),
        root.get_by_role("button", name=text, exact=False),
        root.get_by_text(text, exact=True),
        root.get_by_text(text, exact=False),
        root.locator(f"button:has-text('{text}')"),
        root.locator(f"[role='button']:has-text('{text}')"),
        root.locator(f"button[title*='{text}' i]"),
        root.locator(f"button[aria-label*='{text}' i]"),
    ]
    
    for locator in selectors:
        try:
            count = await locator.count()
            for i in range(count):
                el = locator.nth(i)
                if await el.is_visible():
                    log.info("Found visible button with text '%s' using selector: %s", text, locator)
                    await el.scroll_into_view_if_needed(timeout=2000)
                    if await stable_click(page, el, timeout_ms=3000):
                        return True
        except Exception:
            pass
            
    # Page-level fallback in case parent container did not match
    if parent_locator is not None:
        log.info("Attempting page-level fallback for button '%s'", text)
        return await click_button_by_text(page, text, timeout_ms, parent_locator=None)
        
    return False


def _meta_reference_letterboxed(meta: dict) -> bool:
    if not isinstance(meta, dict):
        return False
    if meta.get("letterboxed"):
        return True
    path = meta.get("image_path") or ""
    return isinstance(path, str) and "_processed" in path


def _resolve_job_aspect(
    aspect: str | None,
    image_path: str | None = None,
    job: Optional["Job"] = None,
) -> str:
    """Normalize job aspect to a real Mage chip. Never leave 'auto'/invalid as 1:1 blindly when a ref exists."""
    if aspect in ASPECTS:
        return aspect
    job_aspect = getattr(job, "aspect", None) if job else None
    if job_aspect in ASPECTS:
        return job_aspect
    paths = _job_reference_image_paths(job, image_path)
    for path in paths:
        if path and os.path.exists(path):
            try:
                detected = get_closest_aspect_ratio(path)
                if detected in ASPECTS:
                    log.info("📐 Resolved invalid aspect %r → %s from reference", aspect, detected)
                    return detected
            except Exception:
                continue
    return DEF_ASPECT


def _reference_aspect_letterboxed(
    reference_paths: list[str],
    image_path: str | None = None,
    job: Optional["Job"] = None,
) -> bool:
    """True when references were pre-letterboxed before queue (aspect baked into pixels)."""
    if job and job.reference_letterboxed:
        return True
    paths = reference_paths or ([image_path] if image_path else [])
    return any(isinstance(p, str) and "_processed" in p for p in paths)



async def _click_aspect_option(page: Page, aspect: str) -> bool:
    """Click an aspect ratio option inside Mage portals or the prompt bar."""
    try:
        clicked = await page.evaluate(
            """(aspect) => {
                const match = (el) => (el.innerText || el.textContent || "").trim() === aspect;
                const tryClick = (root) => {
                    if (!root) return false;
                    for (const btn of root.querySelectorAll("button, [role='button'], [role='menuitem']")) {
                        if (match(btn)) {
                            btn.click();
                            return true;
                        }
                    }
                    return false;
                };
                const bar = document.querySelector("[data-promptbar='true']");
                if (tryClick(bar)) return true;
                for (const portal of document.querySelectorAll('[data-portal="true"]')) {
                    if (tryClick(portal)) return true;
                }
                for (const dialog of document.querySelectorAll('[role="dialog"]')) {
                    if (tryClick(dialog)) return true;
                }
                return false;
            }""",
            aspect,
        )
        return bool(clicked)
    except Exception:
        return False


async def _find_aspect_trigger(page: Page):
    """Locate the prompt-bar aspect ratio chip."""
    prompt_bar = page.locator("[data-promptbar='true']").first
    if await prompt_bar.count() == 0:
        return page.locator("button").filter(
            has_text=re.compile(r"1:1|4:5|9:16|16:9|2:3|3:2|5:4|Aspect")
        ).first
    return prompt_bar.locator("button").filter(
        has_text=re.compile(r"1:1|4:5|9:16|16:9|2:3|3:2|5:4|Aspect")
    ).first


async def _read_promptbar_aspect(page: Page) -> str:
    trigger = await _find_aspect_trigger(page)
    if await trigger.count() == 0:
        return ""
    return (await trigger.inner_text(timeout=2000) or "").strip()


_ASPECT_RATIO_RE = re.compile(r"^\d+:\d+$")


def _closest_aspect_from_list(desired: str, available: list[str]) -> str:
    """Return the aspect string from *available* whose numeric ratio is closest to *desired*."""
    def _ratio(s: str) -> float:
        try:
            w, h = s.split(":")
            return int(w) / int(h)
        except Exception:
            return 1.0

    target = _ratio(desired)
    return min(available, key=lambda a: abs(_ratio(a) - target))


async def _get_available_aspects(page: Page, worker_id: int = 0) -> list[str]:
    """Return the aspect chips currently visible in the open dropdown for this model.

    Scans the same DOM scope as _click_aspect_option (promptbar → portals → dialogs).
    Only returns strings matching \\d+:\\d+. Safe to call after the trigger is already
    open; returns an empty list (never raises) on any failure or timeout.
    """
    try:
        async def _read() -> list[str]:
            raw: list[str] = await page.evaluate("""() => {
                const RATIO_RE = /^\\d+:\\d+$/;
                const seen = new Set();
                const collect = (root) => {
                    if (!root) return;
                    for (const btn of root.querySelectorAll(
                            "button, [role='button'], [role='menuitem']")) {
                        const t = (btn.innerText || btn.textContent || "").trim();
                        if (RATIO_RE.test(t) && !seen.has(t)) seen.add(t);
                    }
                };
                collect(document.querySelector("[data-promptbar='true']"));
                document.querySelectorAll('[data-portal="true"]').forEach(collect);
                document.querySelectorAll('[role="dialog"]').forEach(collect);
                return Array.from(seen);
            }""")
            return [r for r in (raw or []) if _ASPECT_RATIO_RE.match(r)]

        chips = await asyncio.wait_for(_read(), timeout=3.0)
        if not chips:
            # Dropdown might not be open yet — try opening it first
            trigger = await _find_aspect_trigger(page)
            if await trigger.count() > 0:
                try:
                    await stable_click(page, trigger, timeout_ms=2000)
                    await page.wait_for_timeout(200)
                    chips = await asyncio.wait_for(_read(), timeout=2.0)
                except Exception:
                    pass
        log.debug("[W%d] 📐 Available aspects for current model: %s", worker_id, chips)
        return chips
    except asyncio.TimeoutError:
        log.warning("[W%d] ⚠️ Timed out reading available aspect chips — proceeding with partial list", worker_id)
        return []
    except Exception as e:
        log.warning("[W%d] ⚠️ Failed to read available aspect chips: %s", worker_id, e)
        return []


async def _set_aspect(page: Page, aspect: str, worker_id: int = 0):
    """Set the aspect ratio using precise Playwright locators.

    If the desired aspect chip is not available for the current model, falls back to
    the closest available chip by numeric ratio instead of crashing.
    """
    log.info("[W%d] 📐 Setting aspect ratio to %s...", worker_id, aspect)
    try:
        current_aspect = await _read_promptbar_aspect(page)
        if current_aspect == aspect:
            log.info("[W%d] 📐 Aspect ratio is already %s. Skipping aspect setting.", worker_id, aspect)
            return

        await _dismiss_blocking_overlays(page, worker_id, quiet=True, skip_escape=True)

        trigger = await _find_aspect_trigger(page)
        if await trigger.count() > 0:
            await stable_click(page, trigger, timeout_ms=3000)
            await page.wait_for_timeout(250)
        else:
            log.warning("[W%d] ⚠️ Aspect ratio trigger button not found.", worker_id)

        clicked = await _click_aspect_option(page, aspect)
        if not clicked:
            target = page.get_by_role("button", name=aspect, exact=True)
            if await target.count() > 0:
                for i in range(await target.count()):
                    el = target.nth(i)
                    if await el.is_visible():
                        await stable_click(page, el, timeout_ms=5000)
                        clicked = True
                        break
        if not clicked:
            fallback = page.locator("button").filter(has_text=re.compile(rf"^{re.escape(aspect)}$"))
            for i in range(await fallback.count()):
                el = fallback.nth(i)
                if await el.is_visible():
                    await stable_click(page, el, timeout_ms=5000)
                    clicked = True
                    break

        if not clicked:
            # Desired chip not found — discover what this model actually offers and use the closest
            available = await _get_available_aspects(page, worker_id)
            if not available:
                log.warning(
                    "[W%d] ⚠️ No aspect chips found in UI for current model — skipping aspect selection",
                    worker_id,
                )
                return
            if aspect in available:
                log.info("[W%d] ✅ Aspect %s is available — retrying click", worker_id, aspect)
                clicked = await _click_aspect_option(page, aspect)
                if not clicked:
                    log.warning("[W%d] ⚠️ Aspect %s retry click failed — skipping", worker_id, aspect)
                    return
            else:
                closest = _closest_aspect_from_list(aspect, available)
                log.info(
                    "[W%d] 📐 Desired aspect %s not available for this model; using closest available: %s",
                    worker_id, aspect, closest,
                )
                clicked = await _click_aspect_option(page, closest)
                if not clicked:
                    log.warning(
                        "[W%d] ⚠️ Closest aspect %s click failed — skipping aspect selection",
                        worker_id, closest,
                    )
                    return
                aspect = closest  # update so the verification below checks the right value

        await page.wait_for_timeout(150)
        current_aspect = await _read_promptbar_aspect(page)
        if current_aspect == aspect:
            log.info("[W%d] ✅ Aspect ratio successfully set to %s", worker_id, aspect)
        elif not clicked:
            # Should not reach here after the fallback path, but guard anyway
            log.warning(
                "[W%d] ⚠️ Aspect button %s not found (prompt bar shows %s) — skipping",
                worker_id, aspect, current_aspect or "unknown",
            )
        else:
            raise RuntimeError(
                f"Aspect ratio mismatch: requested {aspect}, prompt bar shows {current_aspect or 'unknown'}"
            )
    except Exception as e:
        log.warning("[W%d] ⚠️ Aspect set failed for %s: %s", worker_id, aspect, e)
        raise

async def _guava_is_selected(page: Page, worker_id: int = 0) -> bool:
    """Return True when V1 Guava Pro Fast Mode is active (not Guava Pro 1.5)."""
    try:
        model_text = (await _get_promptbar_model_text(page)).lower()
        if model_text:
            if "1.5" in model_text:
                log.debug("[W%d] Guava V1 NOT selected — prompt bar shows 1.5: '%s'", worker_id, model_text)
                return False
            if "guava" in model_text:
                log.debug("[W%d] Guava V1 verified via model dropdown: '%s'", worker_id, model_text)
                return True
            return False

        try:
            has_guava_v1 = await page.evaluate("""() => {
                const bar = document.querySelector("[data-promptbar='true']");
                if (!bar) return false;
                const t = (bar.innerText || bar.textContent || "").toLowerCase();
                return t.includes("guava pro fast") && !t.includes("1.5");
            }""")
            if has_guava_v1:
                return True
        except Exception:
            pass

        url = (page.url or "").lower()
        if "guava-pro-fast-mode" in url and "guava-pro-15" not in url:
            log.debug("[W%d] Guava V1 verified via URL: %s", worker_id, url[:80])
            return True

        selectors = [
            "button[data-variant='subtle'][data-size='compact-sm']:has-text('Guava Pro Fast')",
            "button:has-text('Guava Pro Fast Mode')",
        ]
        for sel in selectors:
            loc = page.locator(sel).first
            if await loc.count() > 0:
                try:
                    if await loc.is_visible():
                        text = (await loc.inner_text(timeout=2000)).lower()
                        if "guava" in text and "1.5" not in text:
                            return True
                except Exception:
                    continue
        return False
    except Exception as e:
        log.debug("[W%d] _guava_is_selected check failed: %s", worker_id, e)
        return False


@async_timeout(20.0)
async def _wait_for_guava_selected(
    page: Page, worker_id: int = 0, timeout_ms: int = 8_000
) -> bool:
    """Poll until Guava V1 is verified in the prompt bar."""
    deadline = time.time() + timeout_ms / 1000
    while time.time() < deadline:
        if await _guava_is_selected(page, worker_id):
            return True
        await page.wait_for_timeout(250)
    return await _guava_is_selected(page, worker_id)


async def _guava_15_is_selected(page: Page, worker_id: int = 0) -> bool:
    """Return True when Guava Pro 1.5 Fast Mode is the active prompt-bar model."""
    try:
        model_text = (await _get_promptbar_model_text(page)).lower()
        if model_text:
            if "1.5" in model_text or "guava pro 1.5" in model_text:
                log.debug("[W%d] Guava 1.5 verified via model dropdown: '%s'", worker_id, model_text)
                return True
            log.debug("[W%d] Guava 1.5 NOT selected — prompt bar model: '%s'", worker_id, model_text)
            return False

        selectors = [
            "[data-promptbar='true'] button:has-text('Guava Pro 1.5')",
            "button:has-text('Guava Pro 1.5 Fast Mode')",
        ]
        for sel in selectors:
            loc = page.locator(sel).first
            if await loc.count() > 0:
                try:
                    if await loc.is_visible():
                        text = (await loc.inner_text(timeout=2000)).lower()
                        if "1.5" in text and "guava" in text:
                            return True
                except Exception:
                    continue

        try:
            has_guava_15_text = await page.evaluate("""() => {
                const bar = document.querySelector("[data-promptbar='true']");
                if (!bar) return false;
                const t = (bar.innerText || bar.textContent || "").toLowerCase();
                return t.includes("guava pro 1.5") || t.includes("1.5 fast");
            }""")
            if has_guava_15_text:
                return True
        except Exception:
            pass

        url = (page.url or "").lower()
        if "guava-pro-15-fast-mode" in url:
            log.debug("[W%d] Guava 1.5 verified via URL: %s", worker_id, url[:80])
            return True

        return False
    except Exception as e:
        log.debug("[W%d] _guava_15_is_selected check failed: %s", worker_id, e)
        return False


async def _grok_is_selected(page: Page, worker_id: int = 0) -> bool:
    """Return True when Grok Image Quality is active (button, URL, or prompt bar text)."""
    try:
        # 1. Check actual dropdown button text first
        dropdown = await _find_model_dropdown(page)
        if await dropdown.count() > 0:
            text = (await dropdown.inner_text(timeout=2000) or "").lower()
            if "grok" in text:
                log.debug("[W%d] Grok verified via model dropdown text: '%s'", worker_id, text)
                return True
            if "guava" in text or "mango" in text:
                log.debug("[W%d] Grok NOT selected: model dropdown shows '%s'", worker_id, text)
                return False

        # 2. Check general button selectors with "Grok" text
        selectors = [
            "button[data-variant='subtle'][data-size='compact-sm']:has-text('Grok Image Quality')",
            "button:has-text('Grok Image Quality')",
            "button:has-text('Grok')",
        ]
        for sel in selectors:
            loc = page.locator(sel).first
            if await loc.count() > 0:
                try:
                    if await loc.is_visible():
                        text = (await loc.inner_text(timeout=2000)).lower()
                        if "grok" in text:
                            return True
                except Exception:
                    continue

        # 3. Check prompt bar text content as a backup
        try:
            has_grok_text = await page.evaluate("""() => {
                const bar = document.querySelector("[data-promptbar='true']");
                if (!bar) return false;
                const t = (bar.innerText || bar.textContent || "").toLowerCase();
                return t.includes("grok image quality");
            }""")
            if has_grok_text:
                return True
        except Exception:
            pass

        # 4. Fallback check for URL (cautious, only if button text isn't explicit)
        url = (page.url or "").lower()
        if "grok-image-quality-fast-mode" in url:
            log.debug("[W%d] Grok verified via URL: %s", worker_id, url[:80])
            return True

        return False
    except Exception as e:
        log.debug("[W%d] _grok_is_selected check failed: %s", worker_id, e)
        return False


async def _wait_promptbar_ready(page: Page, worker_id: int = 0, timeout_ms: int = 12_000) -> bool:
    """Wait for prompt-bar UI (editor + send button) without requiring aspect chip."""
    selectors = [
        "div.promptbar-textarea div.tiptap.ProseMirror",
        "img[alt='Send']",
    ]
    deadline = time.time() + timeout_ms / 1000
    while time.time() < deadline:
        for sel in selectors:
            try:
                el = page.locator(sel).first
                if await el.count() > 0 and await el.is_visible():
                    log.info("[W%d] ✅ Prompt bar ready (selector: %s)", worker_id, sel)
                    return True
            except Exception:
                pass
        await page.wait_for_timeout(150)
    log.warning("[W%d] ⚠️ Prompt bar not confirmed ready within %dms", worker_id, timeout_ms)
    return False


async def _select_grok_via_models_card(page: Page, worker_id: int = 0) -> bool:
    """Click Grok card on /models after grid loads. Returns True if navigation succeeded."""
    try:
        log.info("[W%d] Navigating to %s for Grok card", worker_id, MAGE_MODELS)
        await page.goto(MAGE_MODELS, wait_until="domcontentloaded", timeout=15_000)
        await _dismiss_blocking_overlays(page, worker_id, quiet=True)
        grok_title = page.get_by_text("Grok Image Quality Fast Mode").first
        await grok_title.wait_for(state="visible", timeout=12_000)
        card_selectors = [
            "div.mage-Card-root:has(p:has-text('Grok Image Quality Fast Mode'))",
            "div[style*='cursor: pointer']:has(p:has-text('Grok Image Quality Fast Mode'))",
            "p:has-text('Grok Image Quality Fast Mode')",
        ]
        for sel in card_selectors:
            card = page.locator(sel).first
            if await card.count() > 0:
                try:
                    await card.scroll_into_view_if_needed(timeout=3_000)
                    await page.wait_for_timeout(100)
                    log.info("[W%d] Clicking Grok card via %s", worker_id, sel)
                    await stable_click(page, card, timeout_ms=5_000)
                    await page.wait_for_timeout(400)
                    return True
                except PWTimeout:
                    log.warning("[W%d] Grok card not clickable via %s", worker_id, sel)
    except Exception as e:
        log.warning("[W%d] Grok card selection failed: %s", worker_id, e)
    return False


async def _select_grok_via_dropdown(page: Page, worker_id: int = 0) -> bool:
    """Click model dropdown and select Grok Image Quality Fast Mode."""
    log.info("[W%d] Clicking model dropdown to select Grok...", worker_id)
    return await _select_model_via_dropdown_robust(
        page,
        worker_id,
        exact_name="Grok Image Quality Fast Mode",
        name_prefixes=("Grok Image Quality", "Grok"),
        verify_fn=_grok_is_selected,
        probe_text="Grok",
    )


async def _select_grok_image_quality_fast(page: Page, worker_id: int = 0):
    """Select Grok Image Quality Fast Mode directly via dropdown on current Explore page."""
    log.info("[W%d] 🧘 Selecting Grok Image Quality Fast Mode (direct dropdown)...", worker_id)

    if await _grok_is_selected(page, worker_id):
        log.info("[W%d] ✅ Grok already active", worker_id)
        return

    try:
        await _dismiss_blocking_overlays(page, worker_id, quiet=True, skip_escape=True)
    except Exception:
        pass

    if await _select_grok_via_dropdown(page, worker_id):
        if await _grok_is_selected(page, worker_id):
            log.info("[W%d] ✅ Grok selected via dropdown", worker_id)
            return

    raise RuntimeError("Grok Image Quality Fast Mode not active after selection")



async def _navigate_to_posing_model(page: Page, worker_id: int = 0):
    """Navigate to /models and select Grok for posing pipeline."""
    await _select_grok_image_quality_fast(page, worker_id)


async def _create_with_this_visible(page: Page) -> bool:
    try:
        create_btn = page.locator("button:has-text('Create with this')").first
        return await create_btn.count() > 0 and await create_btn.is_visible()
    except Exception:
        return False


async def _wait_create_with_this_gone(
    page: Page, worker_id: int = 0, timeout_ms: int = 8_000
) -> bool:
    deadline = time.time() + timeout_ms / 1000
    while time.time() < deadline:
        if not await _create_with_this_visible(page):
            return True
        await page.wait_for_timeout(100)
    log.warning("[W%d] Create with this still visible after %dms", worker_id, timeout_ms)
    return False


async def _click_create_with_this_if_visible(page: Page, worker_id: int = 0) -> None:
    try:
        if not await _create_with_this_visible(page):
            return
        create_btn = page.locator("button:has-text('Create with this')").first
        log.info("[W%d] Found 'Create with this' button, clicking it to activate model...", worker_id)
        try:
            await stable_click(page, create_btn, timeout_ms=3_000)
            await page.wait_for_timeout(PAGE_SETTLE_MS)
        except Exception:
            pass
        # Force-remove the button from DOM if it's still visible after clicking
        # (on Grok/Kiwi play pages it's cosmetic and never self-dismisses)
        if await _create_with_this_visible(page):
            try:
                removed = await page.evaluate("""
                    () => {
                        let count = 0;
                        document.querySelectorAll("button").forEach(btn => {
                            if ((btn.innerText || btn.textContent || '').trim() === 'Create with this') {
                                btn.remove();
                                count++;
                            }
                        });
                        return count;
                    }
                """)
                if removed:
                    log.info("[W%d] ✅ Force-removed %d 'Create with this' button(s) from DOM", worker_id, removed)
            except Exception as _rm_err:
                log.debug("[W%d] Force-remove 'Create with this' failed: %s", worker_id, _rm_err)
        await _wait_create_with_this_gone(page, worker_id)
    except Exception as e:
        log.debug("[W%d] Clicking 'Create with this' failed/skipped: %s", worker_id, e)


async def _get_promptbar_model_text(page: Page) -> str:
    """Return the active model name shown in the prompt-bar model picker."""
    try:
        dropdown = await _find_model_dropdown(page)
        if await dropdown.count() > 0:
            return (await dropdown.inner_text(timeout=2000) or "").strip()
    except Exception:
        pass
    try:
        return await page.evaluate("""() => {
            const bar = document.querySelector("[data-promptbar='true']");
            if (!bar) return "";
            const btn = bar.querySelector(
                "button[data-variant='subtle'][data-size='compact-sm'][aria-haspopup='dialog']"
            );
            return btn ? (btn.innerText || btn.textContent || "").trim() : "";
        }""") or ""
    except Exception:
        return ""


async def _kiwi_is_selected(page: Page, worker_id: int = 0) -> bool:
    """Return True only when Kiwi Video Fast Mode is the active prompt-bar model."""
    try:
        model_text = (await _get_promptbar_model_text(page)).lower()
        if model_text:
            if "kiwi" in model_text:
                log.debug("[W%d] Kiwi verified via model dropdown: '%s'", worker_id, model_text)
                return True
            log.debug("[W%d] Kiwi NOT selected — prompt bar model: '%s'", worker_id, model_text)
            return False

        # Backup: any visible Kiwi model button inside the prompt bar
        selectors = [
            "[data-promptbar='true'] button[data-variant='subtle'][data-size='compact-sm']:has-text('Kiwi')",
            "[data-promptbar='true'] button:has-text('Kiwi Video Fast Mode')",
        ]
        for sel in selectors:
            loc = page.locator(sel).first
            if await loc.count() > 0:
                try:
                    if await loc.is_visible():
                        text = (await loc.inner_text(timeout=2000) or "").lower()
                        if "kiwi" in text:
                            return True
                except Exception:
                    continue

        try:
            has_kiwi_text = await page.evaluate("""() => {
                const bar = document.querySelector("[data-promptbar='true']");
                if (!bar) return false;
                const t = (bar.innerText || bar.textContent || "").toLowerCase();
                return t.includes("kiwi video");
            }""")
            if has_kiwi_text:
                return True
        except Exception:
            pass

        url = (page.url or "").lower()
        if "kiwi-video-fast-mode" in url:
            log.debug("[W%d] Kiwi verified via play URL: %s", worker_id, url[:80])
            return True

        return False
    except Exception as e:
        log.debug("[W%d] _kiwi_is_selected check failed: %s", worker_id, e)
        return False


async def _kiwi_queue_generation_active(page: Page) -> bool:
    """True when Kiwi video queue UI is visible (e.g. button text 'Generating: 1 / 10')."""
    try:
        return await page.evaluate("""() => {
            const isVisible = el => {
                if (!el) return false;
                const style = window.getComputedStyle(el);
                if (style.display === "none" || style.visibility === "hidden") return false;
                return el.offsetParent !== null || el.getClientRects().length > 0;
            };
            for (const btn of document.querySelectorAll("button")) {
                if (!isVisible(btn)) continue;
                const t = (btn.innerText || btn.textContent || "").trim();
                if (/^generating:\\s*\\d+\\s*\\/\\s*\\d+/i.test(t)) return true;
            }
            return false;
        }""")
    except Exception:
        return False


async def _ensure_kiwi_model_before_send(
    page: Page,
    worker_id: int = 0,
    *,
    image_paths: list[str] | None = None,
    prompt: str | None = None,
) -> None:
    """Verify Kiwi is active and the page is on the Kiwi play workspace before send."""
    url = (page.url or "").lower()
    if await _kiwi_is_selected(page, worker_id) and "kiwi-video-fast-mode" in url:
        log.info(
            "[W%d] ✅ Kiwi model confirmed in prompt bar: '%s'",
            worker_id,
            await _get_promptbar_model_text(page) or "Kiwi",
        )
        return

    model_text = await _get_promptbar_model_text(page)
    if await _kiwi_is_selected(page, worker_id) and "kiwi-video-fast-mode" not in url:
        log.warning(
            "[W%d] Kiwi selected but still on %s — opening play workspace",
            worker_id,
            (page.url or "")[:80],
        )
        await _ensure_kiwi_play_workspace(page, worker_id)
        return

    log.warning(
        "[W%d] Wrong model before video send: '%s' — re-selecting Kiwi",
        worker_id,
        model_text or "unknown",
    )
    for attempt in range(3):
        if await _select_kiwi_via_dropdown(page, worker_id):
            if await _kiwi_is_selected(page, worker_id):
                log.info(
                    "[W%d] ✅ Kiwi restored via dropdown (attempt %d): '%s'",
                    worker_id,
                    attempt + 1,
                    await _get_promptbar_model_text(page),
                )
                await _ensure_kiwi_play_workspace(page, worker_id)
                if image_paths and prompt and not await _reference_attached_in_promptbar(page):
                    for idx, image_path in enumerate(image_paths):
                        await _upload_image_video(
                            page,
                            image_path,
                            worker_id,
                            clear_existing=(idx == 0),
                        )
                    await _paste_prompt(page, prompt, worker_id, prompt_mode="video")
                return
        await page.wait_for_timeout(400)

    if image_paths and prompt:
        log.warning("[W%d] Dropdown failed — re-clicking Kiwi card and restoring editor", worker_id)
        await _select_kiwi_via_models_card(page, worker_id)
        await _ensure_kiwi_play_workspace(page, worker_id)
        await _wait_promptbar_ready(page, worker_id, timeout_ms=10_000)
        for idx, image_path in enumerate(image_paths):
            await _upload_image_video(
                page,
                image_path,
                worker_id,
                clear_existing=(idx == 0),
            )
        await _paste_prompt(page, prompt, worker_id, prompt_mode="video")
        if await _kiwi_is_selected(page, worker_id):
            log.info("[W%d] ✅ Kiwi restored via models card + re-upload", worker_id)
            return

    model_text = await _get_promptbar_model_text(page)
    raise RuntimeError(
        f"Kiwi Video Fast Mode not active before send (prompt bar shows: {model_text or 'unknown'})"
    )


async def _ensure_kiwi_play_workspace(page: Page, worker_id: int = 0) -> None:
    """Ensure Kiwi video model is selected directly via dropdown on current page."""
    await _ensure_video_tab_selected(page, worker_id)
    if not await _kiwi_is_selected(page, worker_id):
        log.info("[W%d] Kiwi not active on workspace — trying dropdown", worker_id)
        await _select_kiwi_via_dropdown(page, worker_id)
    if not await _kiwi_is_selected(page, worker_id):
        raise RuntimeError("Kiwi workspace not active after selection attempts")
    log.info("[W%d] ✅ Kiwi workspace ready", worker_id)


async def _ensure_grok_play_workspace(page: Page, worker_id: int = 0) -> None:
    """Ensure Grok model is selected directly via dropdown on current page."""
    if not await _grok_is_selected(page, worker_id):
        log.info("[W%d] Grok not active on workspace — trying dropdown", worker_id)
        await _select_grok_via_dropdown(page, worker_id)
    if not await _grok_is_selected(page, worker_id):
        raise RuntimeError("Grok workspace not active after selection attempts")
    await _ensure_image_tab_selected(page, worker_id)
    log.info("[W%d] ✅ Grok workspace ready", worker_id)


# ── GPT Image 2 Model Selection ──────────────────────────────────────────────

async def _gpt_image_is_selected(page: Page, worker_id: int = 0) -> bool:
    """Return True when GPT Image 2 Fast Mode is the active prompt-bar model."""
    try:
        model_text = (await _get_promptbar_model_text(page)).lower()
        if model_text:
            if "gpt image 2" in model_text:
                log.debug("[W%d] GPT Image 2 verified via model dropdown: '%s'", worker_id, model_text)
                return True
            log.debug("[W%d] GPT Image 2 NOT selected — prompt bar model: '%s'", worker_id, model_text)
            return False

        selectors = [
            "[data-promptbar='true'] button:has-text('GPT Image 2')",
            "button:has-text('GPT Image 2 Fast Mode')",
        ]
        for sel in selectors:
            loc = page.locator(sel).first
            if await loc.count() > 0:
                try:
                    if await loc.is_visible():
                        text = (await loc.inner_text(timeout=2000)).lower()
                        if "gpt image 2" in text:
                            return True
                except Exception:
                    continue

        try:
            has_gpt_image_text = await page.evaluate("""() => {
                const bar = document.querySelector("[data-promptbar='true']");
                if (!bar) return false;
                const t = (bar.innerText || bar.textContent || "").toLowerCase();
                return t.includes("gpt image 2");
            }""")
            if has_gpt_image_text:
                return True
        except Exception:
            pass

        url = (page.url or "").lower()
        if "gpt-image-2-fast-mode" in url:
            log.debug("[W%d] GPT Image 2 verified via URL: %s", worker_id, url[:80])
            return True

        return False
    except Exception as e:
        log.debug("[W%d] _gpt_image_is_selected check failed: %s", worker_id, e)
        return False


async def _select_gpt_image_via_dropdown(page: Page, worker_id: int = 0) -> bool:
    """Click model dropdown and select GPT Image 2 Fast Mode."""
    log.info("[W%d] Clicking model dropdown to select GPT Image 2...", worker_id)
    return await _select_model_via_dropdown_robust(
        page,
        worker_id,
        exact_name=GPT_IMAGE_DISPLAY,
        name_prefixes=("GPT Image 2", "GPT Image"),
        verify_fn=_gpt_image_is_selected,
        probe_text="GPT Image",
    )


async def _select_gpt_image_fast_mode(page: Page, worker_id: int = 0):
    """Select GPT Image 2 Fast Mode — navigate to play URL + dropdown fallback."""
    log.info("[W%d] 🎨 Selecting %s...", worker_id, GPT_IMAGE_DISPLAY)

    if await _gpt_image_is_selected(page, worker_id):
        log.info("[W%d] ✅ GPT Image 2 already active ('%s')", worker_id, await _get_promptbar_model_text(page))
        await _ensure_gpt_image_play_workspace(page, worker_id)
        return

    async with _model_picker_lock:
        try:
            await _dismiss_blocking_overlays(page, worker_id, quiet=True)
            await page.wait_for_timeout(200)
        except Exception:
            pass

        # Try direct play URL first
        try:
            log.info("[W%d] Direct GPT Image 2 URL: %s", worker_id, GPT_IMAGE_PLAY_URL)
            await page.goto(GPT_IMAGE_PLAY_URL, wait_until="domcontentloaded", timeout=15_000)
            await page.wait_for_timeout(800)
            await _wait_promptbar_ready(page, worker_id, timeout_ms=10_000)
            await _dismiss_blocking_overlays(page, worker_id, quiet=True)
            await page.wait_for_timeout(1000)
            await _click_create_with_this_if_visible(page, worker_id)

            if await _gpt_image_is_selected(page, worker_id):
                log.info(
                    "[W%d] ✅ GPT Image 2 selected via play URL ('%s')",
                    worker_id, await _get_promptbar_model_text(page),
                )
                return

            log.info("[W%d] Play URL loaded but dropdown not GPT Image 2. Trying dropdown...", worker_id)
            if await _select_gpt_image_via_dropdown(page, worker_id):
                if await _gpt_image_is_selected(page, worker_id):
                    log.info("[W%d] ✅ GPT Image 2 selected via dropdown on play page", worker_id)
                    return
        except Exception as e:
            log.warning("[W%d] Direct GPT Image 2 URL path failed: %s", worker_id, e)

        # Try dropdown on current page
        log.info("[W%d] 🔄 Trying direct dropdown selection on current page...", worker_id)
        if await _select_gpt_image_via_dropdown(page, worker_id):
            if await _gpt_image_is_selected(page, worker_id):
                log.info("[W%d] ✅ GPT Image 2 selected via direct dropdown", worker_id)
                return

    model_text = await _get_promptbar_model_text(page)
    raise RuntimeError(
        f"{GPT_IMAGE_DISPLAY} not active after selection (prompt bar shows: {model_text or 'unknown'})"
    )


async def _ensure_gpt_image_model_ready(page: Page, worker_id: int = 0) -> None:
    """Switch a logged-in page to GPT Image 2 (used after pooled session activation)."""
    url = (page.url or "").lower()
    if await _gpt_image_is_selected(page, worker_id) and "gpt-image-2-fast-mode" in url:
        return
    if not await _gpt_image_is_selected(page, worker_id):
        await _select_gpt_image_fast_mode(page, worker_id)
    await _ensure_gpt_image_play_workspace(page, worker_id)


async def _ensure_gpt_image_play_workspace(page: Page, worker_id: int = 0) -> None:
    """Open GPT Image 2 play page before reference upload."""
    url = (page.url or "").lower()
    if "gpt-image-2-fast-mode" in url and await _gpt_image_is_selected(page, worker_id):
        log.debug("[W%d] ✅ GPT Image 2 play workspace already active", worker_id)
        return
    if "gpt-image-2-fast-mode" not in url:
        log.info(
            "[W%d] 🎨 Opening GPT Image 2 play workspace before generation (was: %s)",
            worker_id,
            (page.url or "")[:100],
        )
        await page.goto(GPT_IMAGE_PLAY_URL, wait_until="domcontentloaded", timeout=15_000)
        await page.wait_for_timeout(PAGE_SETTLE_MS)
    await _wait_promptbar_ready(page, worker_id, timeout_ms=PROMPTBAR_READY_MS)
    await _dismiss_blocking_overlays(page, worker_id, quiet=True, skip_escape=True)
    await _click_create_with_this_if_visible(page, worker_id)
    if not await _gpt_image_is_selected(page, worker_id):
        await _select_gpt_image_via_dropdown(page, worker_id)


# ── Mango 3 Model Selection ──────────────────────────────────────────────────

async def _mango_3_is_selected(page: Page, worker_id: int = 0) -> bool:
    """Return True when Mango 3 Fast Mode is the active prompt-bar model (not Mango 2 / 3S)."""
    try:
        def _is_mango_3_label(text: str) -> bool:
            t = (text or "").lower()
            if not t:
                return False
            # Reject sibling models that also contain "mango"
            if "mango 3s" in t or "mango 2" in t or "mango 1" in t:
                return False
            return "mango 3" in t or "mango-3" in t

        model_text = (await _get_promptbar_model_text(page)).lower()
        if model_text:
            if _is_mango_3_label(model_text):
                log.debug("[W%d] Mango 3 verified via model dropdown: '%s'", worker_id, model_text)
                return True
            log.debug("[W%d] Mango 3 NOT selected — prompt bar model: '%s'", worker_id, model_text)
            return False

        selectors = [
            "[data-promptbar='true'] button:has-text('Mango 3')",
            "button:has-text('Mango 3 Fast Mode')",
            "button:has-text('Mango 3')",
        ]
        for sel in selectors:
            loc = page.locator(sel).first
            if await loc.count() > 0:
                try:
                    if await loc.is_visible():
                        text = (await loc.inner_text(timeout=2000) or "")
                        if _is_mango_3_label(text):
                            return True
                except Exception:
                    continue

        try:
            has_mango_text = await page.evaluate("""() => {
                const bar = document.querySelector("[data-promptbar='true']");
                if (!bar) return false;
                const t = (bar.innerText || bar.textContent || "").toLowerCase();
                if (t.includes("mango 3s") || t.includes("mango 2")) return false;
                return t.includes("mango 3");
            }""")
            if has_mango_text:
                return True
        except Exception:
            pass

        url = (page.url or "").lower()
        if "mango-3-fast-mode" in url and "mango-3s" not in url:
            log.debug("[W%d] Mango 3 verified via URL: %s", worker_id, url[:80])
            return True

        return False
    except Exception as e:
        log.debug("[W%d] _mango_3_is_selected check failed: %s", worker_id, e)
        return False


async def _select_mango_3_via_dropdown(page: Page, worker_id: int = 0) -> bool:
    """Click model dropdown and select Mango 3 Fast Mode."""
    log.info("[W%d] Clicking model dropdown to select Mango 3...", worker_id)
    return await _select_model_via_dropdown_robust(
        page,
        worker_id,
        exact_name=MANGO_3_DISPLAY,
        name_prefixes=("Mango 3 Fast Mode", "Mango 3 Fast", "Mango 3"),
        verify_fn=_mango_3_is_selected,
        probe_text="Mango 3",
    )


async def _select_mango_3_fast_mode(page: Page, worker_id: int = 0):
    """Select Mango 3 Fast Mode — direct URL or dropdown fallback."""
    log.info("[W%d] 🥭 Selecting %s...", worker_id, MANGO_3_DISPLAY)

    if await _mango_3_is_selected(page, worker_id):
        log.info("[W%d] ✅ Mango 3 already active ('%s')", worker_id, await _get_promptbar_model_text(page))
        await _ensure_mango_3_play_workspace(page, worker_id)
        return

    async with _model_picker_lock:
        try:
            await _dismiss_blocking_overlays(page, worker_id, quiet=True)
            await page.wait_for_timeout(200)
        except Exception:
            pass

        try:
            log.info("[W%d] Direct Mango 3 URL: %s", worker_id, MANGO_3_PLAY_URL)
            await page.goto(MANGO_3_PLAY_URL, wait_until="domcontentloaded", timeout=15_000)
            await page.wait_for_timeout(800)
            await _wait_promptbar_ready(page, worker_id, timeout_ms=10_000)
            await _dismiss_blocking_overlays(page, worker_id, quiet=True)
            await page.wait_for_timeout(1000)
            await _click_create_with_this_if_visible(page, worker_id)

            if await _mango_3_is_selected(page, worker_id):
                log.info(
                    "[W%d] ✅ Mango 3 selected via play URL ('%s')",
                    worker_id, await _get_promptbar_model_text(page),
                )
                return

            log.info("[W%d] Play URL loaded but dropdown not Mango 3. Trying dropdown...", worker_id)
            if await _select_mango_3_via_dropdown(page, worker_id):
                # Wait for the prompt bar to fully re-render with Mango 3 workspace
                await page.wait_for_timeout(1200)
                await _wait_promptbar_ready(page, worker_id, timeout_ms=10_000)
                await _dismiss_blocking_overlays(page, worker_id, quiet=True)
                if await _mango_3_is_selected(page, worker_id):
                    log.info("[W%d] ✅ Mango 3 selected via dropdown on play page", worker_id)
                    return
        except Exception as e:
            log.warning("[W%d] Direct Mango 3 URL path failed: %s", worker_id, e)

        log.info("[W%d] 🔄 Trying direct dropdown selection on current page...", worker_id)
        if await _select_mango_3_via_dropdown(page, worker_id):
            await page.wait_for_timeout(1200)
            await _wait_promptbar_ready(page, worker_id, timeout_ms=10_000)
            await _dismiss_blocking_overlays(page, worker_id, quiet=True)
            if await _mango_3_is_selected(page, worker_id):
                log.info("[W%d] ✅ Mango 3 selected via direct dropdown", worker_id)
                return

    model_text = await _get_promptbar_model_text(page)
    raise RuntimeError(
        f"{MANGO_3_DISPLAY} not active after selection (prompt bar shows: {model_text or 'unknown'})"
    )


async def _ensure_mango_3_model_ready(page: Page, worker_id: int = 0) -> None:
    """Switch a logged-in page to Mango 3."""
    url = (page.url or "").lower()
    on_mango3_play = "mango-3-fast-mode" in url and "mango-3s" not in url
    if await _mango_3_is_selected(page, worker_id) and on_mango3_play:
        return
    if not await _mango_3_is_selected(page, worker_id):
        await _select_mango_3_fast_mode(page, worker_id)
    await _ensure_mango_3_play_workspace(page, worker_id)


async def _ensure_mango_3_play_workspace(page: Page, worker_id: int = 0) -> None:
    """Open Mango 3 play page before generation/reference upload."""
    url = (page.url or "").lower()
    on_mango3_play = "mango-3-fast-mode" in url and "mango-3s" not in url
    if on_mango3_play and await _mango_3_is_selected(page, worker_id):
        log.debug("[W%d] ✅ Mango 3 play workspace already active", worker_id)
        # Still wait for promptbar to be fully ready
        await _wait_promptbar_ready(page, worker_id, timeout_ms=PROMPTBAR_READY_MS)
        return
    if not on_mango3_play:
        log.info(
            "[W%d] 🥭 Opening Mango 3 play workspace before generation (was: %s)",
            worker_id,
            (page.url or "")[:100],
        )
        await page.goto(MANGO_3_PLAY_URL, wait_until="domcontentloaded", timeout=15_000)
        await page.wait_for_timeout(PAGE_SETTLE_MS)
    await _wait_promptbar_ready(page, worker_id, timeout_ms=PROMPTBAR_READY_MS)
    await _dismiss_blocking_overlays(page, worker_id, quiet=True, skip_escape=True)
    await _click_create_with_this_if_visible(page, worker_id)
    # Extra settle — Mango 3 workspace needs more time to render aspect chip
    await page.wait_for_timeout(800)
    if not await _mango_3_is_selected(page, worker_id):
        await _select_mango_3_via_dropdown(page, worker_id)
        await page.wait_for_timeout(1000)
        await _wait_promptbar_ready(page, worker_id, timeout_ms=8_000)


async def _select_kiwi_via_models_card(page: Page, worker_id: int = 0) -> bool:
    """Click Kiwi card on /models after grid loads. Returns True if navigation succeeded."""
    try:
        log.info("[W%d] Navigating to %s for Kiwi card", worker_id, MAGE_MODELS)
        await page.goto(MAGE_MODELS, wait_until="domcontentloaded", timeout=15_000)
        await _dismiss_blocking_overlays(page, worker_id, quiet=True)
        kiwi_title = page.get_by_text("Kiwi Video Fast Mode").first
        await kiwi_title.wait_for(state="visible", timeout=12_000)
        card_selectors = [
            "div.mage-Card-root:has(p:has-text('Kiwi Video Fast Mode'))",
            "div[style*='cursor: pointer']:has(p:has-text('Kiwi Video Fast Mode'))",
            "p:has-text('Kiwi Video Fast Mode')",
        ]
        for sel in card_selectors:
            card = page.locator(sel).first
            if await card.count() > 0:
                try:
                    await card.scroll_into_view_if_needed(timeout=3_000)
                    await page.wait_for_timeout(200)
                    log.info("[W%d] Clicking Kiwi card via %s", worker_id, sel)
                    await stable_click(page, card, timeout_ms=5_000)
                    await page.wait_for_timeout(800)
                    return True
                except PWTimeout:
                    log.warning("[W%d] Kiwi card not clickable via %s", worker_id, sel)
    except Exception as e:
        log.warning("[W%d] Kiwi card selection failed: %s", worker_id, e)
    return False


async def _select_kiwi_via_dropdown(page: Page, worker_id: int = 0) -> bool:
    """Click prompt-bar model dropdown and select Kiwi Video Fast Mode."""
    log.info("[W%d] Clicking model dropdown to select Kiwi...", worker_id)
    return await _select_model_via_dropdown_robust(
        page,
        worker_id,
        exact_name="Kiwi Video Fast Mode",
        name_prefixes=("Kiwi Video", "Kiwi"),
        verify_fn=_kiwi_is_selected,
        probe_text="Kiwi",
    )


async def _select_kiwi_video_fast_mode(page: Page, worker_id: int = 0):
    """Select Kiwi Video Fast Mode directly via dropdown on current Explore page."""
    log.info("[W%d] 🎬 Selecting Kiwi Video Fast Mode (direct dropdown)...", worker_id)

    await _ensure_video_tab_selected(page, worker_id)

    if await _kiwi_is_selected(page, worker_id):
        log.info("[W%d] ✅ Kiwi already active", worker_id)
        return

    try:
        await _dismiss_blocking_overlays(page, worker_id, quiet=True, skip_escape=True)
    except Exception:
        pass

    if await _select_kiwi_via_dropdown(page, worker_id):
        if await _kiwi_is_selected(page, worker_id):
            log.info("[W%d] ✅ Kiwi selected via dropdown", worker_id)
            return

    model_text = await _get_promptbar_model_text(page)
    raise RuntimeError(
        f"Kiwi Video Fast Mode not active after selection (prompt bar shows: {model_text or 'unknown'})"
    )



async def _navigate_to_video_model(page: Page, worker_id: int = 0):
    """Navigate to /models and select Kiwi for video pipeline."""
    await _select_kiwi_video_fast_mode(page, worker_id)


async def _ensure_video_model_ready(page: Page, worker_id: int = 0) -> None:
    """Ensure Kiwi video model is active on prompt bar."""
    await _ensure_video_tab_selected(page, worker_id)
    if not await _kiwi_is_selected(page, worker_id):
        await _select_kiwi_video_fast_mode(page, worker_id)



async def _select_guava_15_via_models_card(page: Page, worker_id: int = 0) -> bool:
    """Click Guava Pro 1.5 card on /models after grid loads."""
    try:
        log.info("[W%d] Navigating to %s for Guava 1.5 card", worker_id, MAGE_MODELS)
        await page.goto(MAGE_MODELS, wait_until="domcontentloaded", timeout=15_000)
        await _dismiss_blocking_overlays(page, worker_id, quiet=True)
        guava_title = page.get_by_text(GUAVA_15_DISPLAY).first
        await guava_title.wait_for(state="visible", timeout=12_000)
        card_selectors = [
            f"div.mage-Card-root:has(p:has-text('{GUAVA_15_DISPLAY}'))",
            f"div[style*='cursor: pointer']:has(p:has-text('{GUAVA_15_DISPLAY}'))",
            f"p:has-text('{GUAVA_15_DISPLAY}')",
        ]
        for sel in card_selectors:
            card = page.locator(sel).first
            if await card.count() > 0:
                try:
                    await card.scroll_into_view_if_needed(timeout=3_000)
                    await page.wait_for_timeout(200)
                    log.info("[W%d] Clicking Guava 1.5 card via %s", worker_id, sel)
                    await stable_click(page, card, timeout_ms=5_000)
                    await page.wait_for_timeout(800)
                    return True
                except PWTimeout:
                    log.warning("[W%d] Guava 1.5 card not clickable via %s", worker_id, sel)
    except Exception as e:
        log.warning("[W%d] Guava 1.5 card selection failed: %s", worker_id, e)
    return False


async def _select_guava_15_via_dropdown(page: Page, worker_id: int = 0) -> bool:
    """Click model dropdown and select Guava Pro 1.5 Fast Mode."""
    try:
        await _dismiss_blocking_overlays(page, worker_id, quiet=True, skip_escape=True)
        await page.wait_for_timeout(200)

        model_dropdown = await _find_model_dropdown(page)
        if await model_dropdown.count() == 0:
            return False

        log.info("[W%d] Clicking model dropdown to select Guava 1.5...", worker_id)
        await stable_click(page, model_dropdown, timeout_ms=5_000)
        await page.wait_for_timeout(250)

        option_selectors = [
            f"div[style*='cursor: pointer']:has(p:text-is('{GUAVA_15_DISPLAY}'))",
            f"div[style*='cursor: pointer']:has(p:has-text('Guava Pro 1.5'))",
            f"p.mantine-focus-auto:has-text('{GUAVA_15_DISPLAY}')",
            f"p:has-text('{GUAVA_15_DISPLAY}')",
            "p:has-text('Guava Pro 1.5')",
        ]
        for sel in option_selectors:
            opt = page.locator(sel).first
            if await opt.count() > 0:
                try:
                    await opt.scroll_into_view_if_needed(timeout=2000)
                    log.info("[W%d] Clicking Guava 1.5 option via selector: %s", worker_id, sel)
                    await stable_click(page, opt, timeout_ms=5_000)
                    await page.wait_for_timeout(800)
                    if await _guava_15_is_selected(page, worker_id):
                        return True
                except Exception:
                    continue
        return False
    except Exception as e:
        log.warning("[W%d] Failed to select Guava 1.5 via dropdown: %s", worker_id, e)
        return False


async def _select_guava_15_fast_mode(page: Page, worker_id: int = 0):
    """Select Guava Pro 1.5 Fast Mode — /models card first, then play URL fallback."""
    log.info("[W%d] 🥭 Selecting %s...", worker_id, GUAVA_15_DISPLAY)

    if await _guava_15_is_selected(page, worker_id):
        log.info("[W%d] ✅ Guava 1.5 already active ('%s')", worker_id, await _get_promptbar_model_text(page))
        await _ensure_guava_15_play_workspace(page, worker_id)
        return

    async with _model_picker_lock:
        try:
            await _dismiss_blocking_overlays(page, worker_id, quiet=True)
            await page.wait_for_timeout(200)
        except Exception:
            pass

        if await _select_guava_15_via_models_card(page, worker_id):
            await _wait_promptbar_ready(page, worker_id, timeout_ms=10_000)
            await _dismiss_blocking_overlays(page, worker_id, quiet=True)
            await page.wait_for_timeout(1000)

            if await _guava_15_is_selected(page, worker_id):
                log.info(
                    "[W%d] ✅ Guava 1.5 selected via /models card ('%s')",
                    worker_id, await _get_promptbar_model_text(page),
                )
                await _ensure_guava_15_play_workspace(page, worker_id)
                return

            log.info("[W%d] Card clicked but Guava 1.5 not in dropdown. Trying dropdown selection...", worker_id)
            if await _select_guava_15_via_dropdown(page, worker_id):
                if await _guava_15_is_selected(page, worker_id):
                    log.info("[W%d] ✅ Guava 1.5 selected via dropdown after card click", worker_id)
                    return

        try:
            log.info("[W%d] Direct Guava 1.5 URL: %s", worker_id, GUAVA_15_PLAY_URL)
            await page.goto(GUAVA_15_PLAY_URL, wait_until="domcontentloaded", timeout=15_000)
            await page.wait_for_timeout(800)
            await _wait_promptbar_ready(page, worker_id, timeout_ms=10_000)
            await _dismiss_blocking_overlays(page, worker_id, quiet=True)
            await page.wait_for_timeout(1000)
            await _click_create_with_this_if_visible(page, worker_id)

            if await _guava_15_is_selected(page, worker_id):
                log.info(
                    "[W%d] ✅ Guava 1.5 selected via play URL ('%s')",
                    worker_id, await _get_promptbar_model_text(page),
                )
                return

            log.info("[W%d] Play URL loaded but dropdown not Guava 1.5. Trying dropdown...", worker_id)
            if await _select_guava_15_via_dropdown(page, worker_id):
                if await _guava_15_is_selected(page, worker_id):
                    log.info("[W%d] ✅ Guava 1.5 selected via dropdown on play page", worker_id)
                    return
        except Exception as e:
            log.warning("[W%d] Direct Guava 1.5 URL path failed: %s", worker_id, e)

        log.info("[W%d] 🔄 Trying direct dropdown selection on current page...", worker_id)
        if await _select_guava_15_via_dropdown(page, worker_id):
            if await _guava_15_is_selected(page, worker_id):
                log.info("[W%d] ✅ Guava 1.5 selected via direct dropdown", worker_id)
                return

    model_text = await _get_promptbar_model_text(page)
    raise RuntimeError(
        f"{GUAVA_15_DISPLAY} not active after selection (prompt bar shows: {model_text or 'unknown'})"
    )


async def _ensure_guava_15_model_ready(page: Page, worker_id: int = 0) -> None:
    """Switch a logged-in page to Guava Pro 1.5 (used after pooled session activation)."""
    url = (page.url or "").lower()
    if await _guava_15_is_selected(page, worker_id) and "guava-pro-15-fast-mode" in url:
        return
    if not await _guava_15_is_selected(page, worker_id):
        await _select_guava_15_fast_mode(page, worker_id)
    await _ensure_guava_15_play_workspace(page, worker_id)


async def _ensure_guava_15_play_workspace(page: Page, worker_id: int = 0) -> None:
    """Open Guava 1.5 play page before reference upload (paste fails on /models)."""
    url = (page.url or "").lower()
    if "guava-pro-15-fast-mode" in url and await _guava_15_is_selected(page, worker_id):
        log.debug("[W%d] ✅ Guava 1.5 play workspace already active", worker_id)
        return
    if "guava-pro-15-fast-mode" not in url:
        log.info(
            "[W%d] 🥭 Opening Guava 1.5 play workspace before generation (was: %s)",
            worker_id,
            (page.url or "")[:100],
        )
        await page.goto(GUAVA_15_PLAY_URL, wait_until="domcontentloaded", timeout=15_000)
        await page.wait_for_timeout(PAGE_SETTLE_MS)
    await _wait_promptbar_ready(page, worker_id, timeout_ms=PROMPTBAR_READY_MS)
    await _dismiss_blocking_overlays(page, worker_id, quiet=True, skip_escape=True)
    await _click_create_with_this_if_visible(page, worker_id)
    if not await _guava_15_is_selected(page, worker_id):
        await _select_guava_15_via_dropdown(page, worker_id)


async def _ensure_guava_v1_model_ready(page: Page, worker_id: int = 0) -> None:
    """Switch a logged-in page back to Guava Pro Fast Mode (V1) when reusing a V2 session."""
    if await _guava_is_selected(page, worker_id):
        await _ensure_guava_v1_explore_workspace(page, worker_id)
        return
    url = (page.url or "").lower()
    if (
        "guava-pro-15" in url
        or "/models" in url
        or await _guava_15_is_selected(page, worker_id)
    ):
        log.info("[W%d] 🥭 Resetting to explore before Guava V1 selection", worker_id)
        await page.goto(MAGE_EXPLORE, wait_until="domcontentloaded", timeout=15_000)
        await _wait_explore_ready(
            page, worker_id, timeout_ms=12_000, require_promptbar=True, quiet=True,
        )
        await _dismiss_blocking_overlays(page, worker_id, quiet=True, skip_escape=True)
    await _select_guava_pro_fast(page, worker_id)
    if not await _guava_is_selected(page, worker_id):
        if not await _wait_for_guava_selected(page, worker_id, timeout_ms=4_000):
            raise RuntimeError("Guava Pro Fast Mode not active after selection")
    await _ensure_guava_v1_explore_workspace(page, worker_id)


async def _ensure_guava_v1_explore_workspace(page: Page, worker_id: int = 0) -> None:
    """Ensure Guava V1 generation runs on /explore, not /models or 1.5 play URLs."""
    url = (page.url or "").lower()
    if "guava-pro-15" in url or "/models" in url:
        log.info(
            "[W%d] 🥭 Opening explore workspace for Guava V1 (was: %s)",
            worker_id,
            (page.url or "")[:100],
        )
        await page.goto(MAGE_EXPLORE, wait_until="domcontentloaded", timeout=15_000)
        await _wait_explore_ready(
            page, worker_id, timeout_ms=12_000, require_promptbar=True, quiet=True,
        )
        await _dismiss_blocking_overlays(page, worker_id, quiet=True, skip_escape=True)
        if not await _guava_is_selected(page, worker_id):
            await _select_guava_pro_fast(page, worker_id)
            if not await _wait_for_guava_selected(page, worker_id, timeout_ms=6_000):
                raise RuntimeError("Guava V1 not active on explore workspace")


async def _log_model_dropdown_content(page: Page, worker_id: int = 0) -> None:
    """Log Mantine model-picker dropdown text for debugging empty-dropdown failures."""
    try:
        dropdown_text = await page.evaluate("""() => {
            const btn = document.querySelector(
                'button[aria-haspopup="dialog"][aria-expanded="true"]'
            );
            if (btn) {
                const id = btn.getAttribute('aria-controls');
                if (id) {
                    const panel = document.getElementById(id);
                    if (panel && panel.textContent) return panel.textContent.substring(0, 500);
                }
            }
            const popover = document.querySelector('[data-portal="true"]');
            if (popover && popover.textContent) return popover.textContent.substring(0, 500);
            const dialog = document.querySelector('[role="dialog"]');
            if (dialog && dialog.textContent) return dialog.textContent.substring(0, 500);
            return 'no dropdown found';
        }""")
        log.info("[W%d] 🔍 Dropdown content: %s", worker_id, dropdown_text[:300])
    except Exception:
        pass


async def _wait_model_dropdown(
    page: Page,
    worker_id: int = 0,
    timeout_ms: int = 10_000,
) -> bool:
    """Wait until the prompt-bar model picker is visible and interactive."""
    deadline = time.time() + timeout_ms / 1000
    while time.time() < deadline:
        try:
            dropdown = await _find_model_dropdown(page)
            if await dropdown.count() > 0 and await dropdown.is_visible():
                return True
        except Exception:
            pass
        await page.wait_for_timeout(300)
    log.warning("[W%d] ⚠️ Model dropdown not visible within %dms", worker_id, timeout_ms)
    return False


async def _recover_explore_promptbar(page: Page, worker_id: int = 0) -> None:
    """Close model catalog overlays and return to /explore with prompt bar visible."""
    try:
        await page.keyboard.press("Escape")
        await page.wait_for_timeout(200)
        await page.keyboard.press("Escape")
    except Exception:
        pass
    try:
        await page.goto(MAGE_EXPLORE, wait_until="domcontentloaded", timeout=18_000)
        await _wait_explore_ready(
            page, worker_id, timeout_ms=14_000, require_promptbar=True, quiet=True,
        )
        await _dismiss_blocking_overlays(page, worker_id, quiet=True, skip_escape=True)
        await page.wait_for_timeout(400)
    except Exception as exc:
        log.debug("[W%d] explore promptbar recovery failed: %s", worker_id, exc)


async def _find_model_dropdown(page: Page) -> Locator:
    """Locate the prompt-bar model picker button (scoped to data-promptbar only)."""
    selectors = [
        "[data-promptbar='true'] button[data-variant='subtle'][data-size='compact-sm'][aria-haspopup='dialog']",
        "[data-promptbar='true'] button[aria-haspopup='dialog'][aria-controls]",
        "[data-promptbar='true'] button[aria-haspopup='dialog']",
    ]
    for sel in selectors:
        loc = page.locator(sel).first
        if await loc.count() > 0:
            try:
                if await loc.is_visible():
                    return loc
            except Exception:
                return loc
    # Full catalog may hide data-promptbar — any visible model picker on explore
    fallback = page.locator(
        "button[aria-haspopup='dialog'][data-variant='subtle'][data-size='compact-sm']"
    ).first
    if await fallback.count() > 0:
        try:
            if await fallback.is_visible():
                return fallback
        except Exception:
            return fallback
    return page.locator("[data-promptbar='true'] button[aria-haspopup='dialog']").first


async def _select_model_via_dropdown_robust(
    page: Page,
    worker_id: int,
    *,
    exact_name: str,
    name_prefixes: tuple[str, ...],
    verify_fn,
    probe_text: str,
    max_attempts: int = 3,
) -> bool:
    """Open model picker and select a model — same retry/scroll/JS path as Guava."""
    is_builder = worker_id < 0
    expand_timeouts = tuple(min(12_000, 2_000 + i * 2_000) for i in range(max_attempts))
    option_timeouts = tuple(min(10_000, 3_000 + i * 2_000) for i in range(max_attempts))

    for attempt in range(max_attempts):
        is_last = attempt == max_attempts - 1
        if attempt > 0:
            log.info(
                "[W%d] 🔄 %s dropdown retry %d/%d",
                worker_id, exact_name, attempt + 1, max_attempts,
            )
            try:
                await page.keyboard.press("Escape")
                await page.wait_for_timeout(200)
            except Exception:
                pass

        dropdown_opened = False
        try:
            await _dismiss_blocking_overlays(page, worker_id, quiet=True, skip_escape=True)
            model_dropdown = await _find_model_dropdown(page)
            if await model_dropdown.count() == 0:
                if attempt > 0:
                    await _recover_explore_promptbar(page, worker_id)
                    model_dropdown = await _find_model_dropdown(page)
                if await model_dropdown.count() == 0:
                    (log.warning if is_last else log.debug)(
                        "[W%d] %s dropdown open failed: picker not found", worker_id, exact_name,
                    )
                    continue
            await stable_click(page, model_dropdown, timeout_ms=5_000)
            try:
                await page.wait_for_selector(
                    'button[aria-haspopup="dialog"][aria-expanded="true"]',
                    state="visible",
                    timeout=expand_timeouts[attempt],
                )
            except PWTimeout:
                pass
            await page.wait_for_timeout(150 if attempt == 0 else 250)
            dropdown_opened = True
        except Exception as e:
            (log.warning if is_last else log.debug)(
                "[W%d] %s dropdown open failed: %s", worker_id, exact_name, e,
            )
            continue

        if not dropdown_opened:
            continue

        clicked = False
        try:
            probe = page.get_by_text(probe_text, exact=False)
            if await probe.count() == 0:
                await _expand_model_list_if_needed(page, worker_id, is_builder=is_builder)
                try:
                    await page.evaluate("""() => {
                        for (const p of document.querySelectorAll(
                            '[data-portal="true"], [role="dialog"]'
                        )) {
                            if (p) { p.scrollTop = 0; p.scrollTop = 120; p.scrollTop = 240; }
                        }
                    }""")
                except Exception:
                    pass
                try:
                    await page.wait_for_selector(
                        f"p:has-text('{probe_text}')",
                        state="visible",
                        timeout=12_000 if is_builder else 3_000,
                    )
                except PWTimeout:
                    pass

            option_selectors = [
                f"div[style*='cursor: pointer']:has(p:text-is('{exact_name}'))",
                *[f"div[style*='cursor: pointer']:has(p:has-text('{prefix}'))" for prefix in name_prefixes],
                f"p.mantine-focus-auto:has-text('{exact_name}')",
                f"p:has-text('{exact_name}')",
            ]
            model_option = page.locator("invalid").first
            for sel in option_selectors:
                candidate = page.locator(sel).first
                if await candidate.count() > 0:
                    model_option = candidate
                    break
            if await model_option.count() == 0:
                model_option = page.get_by_text(exact_name, exact=True).first

            if await model_option.count() > 0:
                try:
                    await model_option.wait_for(state="visible", timeout=option_timeouts[attempt])
                    await stable_click(page, model_option, timeout_ms=5_000)
                    await page.wait_for_timeout(PAGE_SETTLE_MS)
                    clicked = True
                except PWTimeout:
                    pass

            if not clicked:
                js_clicked = await page.evaluate(
                    """(args) => {
                        const { exactName, prefixes } = args;
                        const targets = [
                            ...document.querySelectorAll('div[style*="cursor: pointer"] p'),
                            ...document.querySelectorAll('[data-portal="true"] p'),
                            ...document.querySelectorAll('[role="dialog"] p'),
                        ];
                        for (const el of targets) {
                            const txt = (el.textContent || '').trim();
                            if (txt === exactName || prefixes.some(p => txt.startsWith(p))) {
                                const card = el.closest('div[style*="cursor: pointer"]') || el;
                                try { card.click(); } catch(e) { el.click(); }
                                return true;
                            }
                        }
                        return false;
                    }""",
                    {"exactName": exact_name, "prefixes": list(name_prefixes)},
                )
                if js_clicked:
                    await page.wait_for_timeout(PAGE_SETTLE_MS)
                    clicked = True

            if not clicked and is_last:
                await _log_model_dropdown_content(page, worker_id)
        except Exception as e:
            (log.warning if is_last else log.debug)(
                "[W%d] %s dropdown select failed: %s", worker_id, exact_name, e,
            )

        if await verify_fn(page, worker_id):
            log.info("[W%d] ✅ %s selected via dropdown", worker_id, exact_name)
            return True

        if attempt < max_attempts - 1:
            if is_builder:
                try:
                    await page.keyboard.press("Escape")
                    await page.wait_for_timeout(400)
                except Exception:
                    pass
            else:
                await _recover_explore_promptbar(page, worker_id)

    return await verify_fn(page, worker_id)


async def _select_guava_via_models_card(page: Page, worker_id: int = 0) -> bool:
    """Click Guava Pro Fast Mode card on /models after grid loads."""
    try:
        log.info("[W%d] Navigating to %s for Guava card", worker_id, MAGE_MODELS)
        await page.goto(MAGE_MODELS, wait_until="domcontentloaded", timeout=15_000)
        await _dismiss_blocking_overlays(page, worker_id, quiet=True)
        guava_title = page.get_by_text("Guava Pro", exact=False).first
        await guava_title.wait_for(state="visible", timeout=12_000)
        card_selectors = [
            f"div.mage-Card-root:has(p:has-text('{GUAVA_DISPLAY}'))",
            f"div[style*='cursor: pointer']:has(p:has-text('{GUAVA_DISPLAY}'))",
            f"div[style*='cursor: pointer']:has(p:has-text('Guava Pro'))",
            f"p:has-text('{GUAVA_DISPLAY}')",
        ]
        for sel in card_selectors:
            card = page.locator(sel).first
            if await card.count() > 0:
                try:
                    await card.scroll_into_view_if_needed(timeout=3_000)
                    await page.wait_for_timeout(200)
                    log.info("[W%d] Clicking Guava card via %s", worker_id, sel)
                    await stable_click(page, card, timeout_ms=5_000)
                    await page.wait_for_timeout(800)
                    if await _guava_is_selected(page, worker_id):
                        return True
                except PWTimeout:
                    log.warning("[W%d] Guava card not clickable via %s", worker_id, sel)
    except Exception as e:
        log.warning("[W%d] Guava card selection failed: %s", worker_id, e)
    return False


async def _expand_model_list_if_needed(page: Page, worker_id: int, *, is_builder: bool = False) -> bool:
    """Open the full model catalog when the dropdown only shows featured / collapsed entries."""
    view_all = page.get_by_text("View all models", exact=False).first
    if await view_all.count() == 0:
        return False
    try:
        if not await view_all.is_visible():
            return False
        log.info("[W%d] Expanding model list via 'View all models'", worker_id)
        await stable_click(page, view_all, timeout_ms=5_000)
        await page.wait_for_timeout(2_500 if is_builder else 800)
        try:
            await page.wait_for_selector(
                "p:has-text('Guava Pro')",
                state="visible",
                timeout=8_000 if is_builder else 4_000,
            )
        except PWTimeout:
            pass
        return True
    except Exception as exc:
        log.debug("[W%d] View-all-models expand failed: %s", worker_id, exc)
        return False


async def _select_guava_pro_fast(page: Page, worker_id: int = 0):
    """Select Guava Pro Fast Mode — builders prefer /models card; jobs use dropdown first."""
    log.info("[W%d] 🥭 Selecting Guava Pro Fast Mode (simplified)...", worker_id)

    if await _guava_is_selected(page, worker_id):
        log.info("[W%d] ✅ Guava already active in prompt bar", worker_id)
        return

    is_builder = worker_id < 0

    async with _model_picker_lock:
        try:
            await _dismiss_blocking_overlays(page, worker_id, quiet=True, skip_escape=True)
            await page.wait_for_timeout(200)
        except Exception:
            pass

        ok = await _select_model_via_dropdown_robust(
            page,
            worker_id,
            exact_name=GUAVA_DISPLAY,
            name_prefixes=("Guava Pro Fast", "Guava Pro"),
            verify_fn=_guava_is_selected,
            probe_text="Guava Pro",
            max_attempts=3,
        )
        if ok:
            try:
                await _dismiss_blocking_overlays(page, worker_id, quiet=True)
            except Exception:
                pass
            return

        if await _select_guava_via_models_card(page, worker_id):
            try:
                await page.goto(MAGE_EXPLORE, wait_until="domcontentloaded", timeout=15_000)
                await _wait_explore_ready(
                    page, worker_id, timeout_ms=12_000, require_promptbar=True, quiet=True,
                )
            except Exception:
                pass
            if await _guava_is_selected(page, worker_id):
                log.info("[W%d] ✅ Guava selected via /models card fallback", worker_id)
                return

    if not await _guava_is_selected(page, worker_id):
        raise RuntimeError("Guava Pro Fast Mode not active after selection")


_REFERENCE_ATTACHED_JS = """() => {
    const refSrc = (src) => src && (
        src.startsWith("blob:")
        || src.includes("cdn")
        || src.includes("uploads")
        || src.includes("mage.space")
    );
    const bar = document.querySelector("[data-promptbar='true']") || (() => {
        const editor = document.querySelector("div.tiptap");
        if (!editor) return null;
        return editor.closest("[class*='promptbar']") || editor.parentElement?.parentElement || editor.parentElement;
    })();
    if (!bar) return false;
    const editor = bar.querySelector("div.tiptap.ProseMirror");
    if (editor) {
        if (editor.querySelectorAll('img, [data-type="image"]').length > 0) return true;
    }
    // Uploaded reference thumbnail beside the + button (img.mage-Image-root)
    for (const img of bar.querySelectorAll('img[class*="Image-root"], img')) {
        if (img.alt === "Send") continue;
        if (refSrc(img.src)) return true;
    }
    for (const el of bar.querySelectorAll(
        '[data-type="image"], [class*="reference"], [class*="thumbnail"], [class*="Reference"]'
    )) {
        if (el.querySelector && el.querySelector("img[src]")) return true;
        if (el.tagName === "IMG" && refSrc(el.src)) return true;
    }
    if (bar.querySelector('[data-type="image"]')) return true;
    return false;
}"""

_EDITOR_REFERENCE_JS = """() => {
    const editor = document.querySelector("div.promptbar-textarea div.tiptap.ProseMirror");
    if (!editor) return false;
    return editor.querySelectorAll('img, [data-type="image"]').length > 0;
}"""


async def _editor_has_reference_image(page: Page) -> bool:
    try:
        return bool(await page.evaluate(_EDITOR_REFERENCE_JS))
    except Exception:
        return False


@async_timeout(50.0)
async def _wait_for_editor_reference(page: Page, timeout_ms: int = 45_000) -> bool:
    deadline = time.time() + timeout_ms / 1000
    while time.time() < deadline:
        if await _editor_has_reference_image(page):
            return True
        await page.wait_for_timeout(450)
    return False


async def _promptbar_media_tab_active(page: Page) -> Optional[str]:
    """Return 'image', 'video', or None when Image/Video tabs are absent."""
    try:
        return await page.evaluate("""() => {
            const bar = document.querySelector("[data-promptbar='true']");
            if (!bar) return null;
            const tabState = (name) => {
                for (const btn of bar.querySelectorAll("button")) {
                    const t = (btn.innerText || btn.textContent || "").trim();
                    if (t !== name) continue;
                    const aria = (btn.getAttribute("aria-selected") || "").toLowerCase();
                    if (aria === "true") return true;
                    if (aria === "false") return false;
                    const el = btn.querySelector("div") || btn;
                    const style = el.getAttribute("style") || "";
                    return style.includes("dark-5")
                        || style.includes("mantine-color-dark-5");
                }
                return null;
            };
            const imageActive = tabState("Image");
            const videoActive = tabState("Video");
            if (imageActive === null && videoActive === null) return null;
            if (imageActive) return "image";
            if (videoActive) return "video";
            return "unknown";
        }""")
    except Exception:
        return None


async def _click_promptbar_media_tab(page: Page, worker_id: int, tab_name: str) -> bool:
    """Click Image or Video tab in the prompt bar when visible."""
    try:
        bar = _promptbar_locator(page)
        tab_btn = bar.locator("button").filter(has_text=re.compile(rf"^{tab_name}$")).first
        if await tab_btn.count() == 0:
            tab_btn = bar.get_by_role("button", name=tab_name, exact=True).first
        if await tab_btn.count() > 0 and await tab_btn.is_visible():
            await stable_click(page, tab_btn, timeout_ms=3_000)
            await page.wait_for_timeout(150)
            log.info("[W%d] ✅ %s tab selected in prompt bar", worker_id, tab_name)
            return True
    except Exception as e:
        log.debug("[W%d] %s tab click failed: %s", worker_id, tab_name, e)
    return False


def _promptbar_locator(page: Page):
    """Locator scoped to the Mage prompt bar."""
    return page.locator("[data-promptbar='true']")


async def _ensure_image_tab_selected(page: Page, worker_id: int = 0) -> None:
    """Ensure the prompt bar Image tab is active (not Video)."""
    try:
        active = await _promptbar_media_tab_active(page)
        if active == "image":
            log.debug("[W%d] Image tab already active — skipping", worker_id)
            return
        url = (page.url or "").lower()
        on_play = "/play/" in url
        if active is None and not on_play:
            log.debug("[W%d] No Image/Video tabs — skipping", worker_id)
            return
        if active in ("video", "unknown") or (active is None and on_play):
            await _click_promptbar_media_tab(page, worker_id, "Image")
    except Exception as e:
        log.debug("[W%d] Image tab selection skipped: %s", worker_id, e)


async def _ensure_video_tab_selected(page: Page, worker_id: int = 0) -> None:
    """Ensure the prompt bar Video tab is active (not Image)."""
    try:
        active = await _promptbar_media_tab_active(page)
        if active == "video":
            log.debug("[W%d] Video tab already active — skipping", worker_id)
            return
        url = (page.url or "").lower()
        on_play = "/play/" in url or "kiwi" in url
        if active is None and not on_play:
            log.debug("[W%d] No Image/Video tabs — skipping", worker_id)
            return
        if active in ("image", "unknown") or (active is None and on_play):
            await _click_promptbar_media_tab(page, worker_id, "Video")
    except Exception as e:
        log.debug("[W%d] Video tab selection skipped: %s", worker_id, e)


async def _focus_prompt_editor(page: Page, worker_id: int = 0) -> None:
    """Focus the tiptap editor so send registers on the prompt bar."""
    sel = "div.promptbar-textarea div.tiptap.ProseMirror"
    ed = page.locator(sel).first
    await ed.wait_for(state="visible", timeout=8_000)
    await stable_click(page, ed, timeout_ms=3_000)
    await page.wait_for_timeout(150)


async def _focus_video_prompt_editor(page: Page, worker_id: int = 0) -> None:
    """Focus the tiptap editor so video send registers on the prompt bar."""
    await _focus_prompt_editor(page, worker_id)


async def _ensure_grok_reference_mode_selected(page: Page, worker_id: int = 0) -> None:
    """Grok posing requires the Reference chip — paste/file-input fails in Character mode."""
    url = (page.url or "").lower()
    if "grok-image-quality-fast-mode" not in url:
        return
    try:
        already = await page.evaluate("""() => {
            const btn = document.querySelector(
                "[data-promptbar='true'] button[data-reference-selector='true']"
            );
            if (!btn) return false;
            const aria = (btn.getAttribute("aria-selected") || "").toLowerCase();
            if (aria === "true") return true;
            const inner = btn.querySelector("div") || btn;
            const style = (inner.getAttribute("style") || btn.getAttribute("style") || "");
            return style.includes("dark-5") || style.includes("mantine-color-dark-5");
        }""")
        if already:
            log.debug("[W%d] Grok Reference chip already active", worker_id)
            return
        ref_btn = page.locator(
            "[data-promptbar='true'] button[data-reference-selector='true']"
        ).first
        if await ref_btn.count() == 0:
            ref_btn = page.locator("[data-promptbar='true'] button").filter(
                has_text=re.compile(r"^Reference$")
            ).first
        if await ref_btn.count() > 0 and await ref_btn.is_visible():
            await stable_click(page, ref_btn, timeout_ms=3_000)
            await page.wait_for_timeout(350)
            log.info("[W%d] ✅ Grok Reference mode selected", worker_id)
    except Exception as e:
        log.debug("[W%d] Grok Reference mode selection skipped: %s", worker_id, e)


async def _ensure_reference_mode_chip(page: Page, worker_id: int = 0) -> None:
    """Click Reference chip when ref is a thumbnail beside + but not inside the editor."""
    try:
        needs_chip = await page.evaluate("""() => {
            const bar = document.querySelector("[data-promptbar='true']");
            if (!bar) return false;
            const editor = bar.querySelector("div.tiptap.ProseMirror");
            const editorHasImage = editor
                && editor.querySelectorAll('img, [data-type="image"]').length > 0;
            if (editorHasImage) return false;
            const refSrc = (src) => src && (
                src.includes("cdn") || src.includes("uploads") || src.includes("mage.space")
            );
            for (const img of bar.querySelectorAll("img")) {
                if (img.alt === "Send") continue;
                if (refSrc(img.src)) return true;
            }
            return false;
        }""")
        if not needs_chip:
            return
        ref_btn = page.locator(
            "[data-promptbar='true'] button[data-reference-selector='true']"
        ).first
        if await ref_btn.count() > 0 and await ref_btn.is_visible():
            await stable_click(page, ref_btn, timeout_ms=2_000)
            log.info("[W%d] ✅ Clicked Reference mode chip", worker_id)
            await page.wait_for_timeout(200)
    except Exception as e:
        log.debug("[W%d] Reference chip click skipped: %s", worker_id, e)


async def _generation_prerequisites_ok(
    page: Page,
    worker_id: int = 0,
    *,
    needs_reference: bool = False,
    posing: bool = False,
    video: bool = False,
    trust_send: bool = False,
) -> tuple[bool, str]:
    # On Grok/Kiwi play workspace URLs the "Create with this" button is a persistent
    # cosmetic UI element that never self-dismisses — the model is active by virtue of
    # the URL alone, so skip this check to avoid a false-negative block.
    url = (page.url or "").lower()
    on_grok_play = "grok-image-quality-fast-mode" in url
    on_gpt_image_play = "gpt-image-2-fast-mode" in url
    on_kiwi_play = "kiwi-video-fast-mode" in url
    on_mango3_play = "mango-3-fast-mode" in url and "mango-3s" not in url
    on_play_workspace = on_grok_play or on_kiwi_play or on_gpt_image_play or on_mango3_play
    if await _create_with_this_visible(page):
        if on_play_workspace:
            log.debug(
                "[W%d] 'Create with this' still visible on play workspace — ignoring (model active via URL)",
                worker_id,
            )
        elif not (posing and (on_grok_play or on_gpt_image_play or on_mango3_play)) and not (video and on_kiwi_play):
            return False, "Create with this still visible — model not activated"
    try:
        editor_len = await page.evaluate("""() => {
            const ed = document.querySelector("div.promptbar-textarea div.tiptap.ProseMirror");
            return ed ? (ed.innerText || "").trim().length : 0;
        }""")
    except Exception:
        editor_len = 0
    if editor_len < 1:
        return False, f"Prompt editor empty (len={editor_len})"
    if needs_reference and not await _reference_attached_in_promptbar(page):
        return False, "Reference not attached in prompt bar"
    try:
        send_visible = await page.locator(
            "[data-promptbar='true'] div[style*='linear-gradient(135deg, #FFA94D']"
            ":has(img[alt='Send'])"
        ).first.is_visible()
    except Exception:
        send_visible = False
    if not send_visible:
        if trust_send:
            log.debug(
                "[W%d] Multi-ref trust send — skipping send-button visibility check",
                worker_id,
            )
        elif needs_reference and await _reference_attached_in_promptbar(page):
            log.debug(
                "[W%d] Send button not visible but reference attached — continuing",
                worker_id,
            )
        else:
            return False, "Promptbar send button not visible"
    return True, ""


async def _assert_generation_ready(
    page: Page,
    worker_id: int = 0,
    *,
    needs_reference: bool = False,
    posing: bool = False,
    video: bool = False,
    trust_send: bool = False,
) -> None:
    if await _create_with_this_visible(page):
        await _click_create_with_this_if_visible(page, worker_id)
    await _ensure_reference_mode_chip(page, worker_id)
    await _focus_prompt_editor(page, worker_id)
    ok, reason = await _generation_prerequisites_ok(
        page,
        worker_id,
        needs_reference=needs_reference,
        posing=posing,
        video=video,
        trust_send=trust_send,
    )
    if not ok:
        await _log_promptbar_debug(page, worker_id)
        raise RuntimeError(f"Not ready to send: {reason}")


async def _model_verified_on_play_page(
    page: Page,
    worker_id: int = 0,
    *,
    video_tab: bool = False,
    posing: bool = False,
) -> bool:
    url = (page.url or "").lower()
    if "/play/" not in url:
        return False
    if video_tab:
        return await _kiwi_is_selected(page, worker_id) and "kiwi-video-fast-mode" in url
    if posing:
        if "mango-3-fast-mode" in url and "mango-3s" not in url:
            return await _mango_3_is_selected(page, worker_id)
        return (
            await _grok_is_selected(page, worker_id)
            and "grok-image-quality-fast-mode" in url
        )
    return await _guava_is_selected(page, worker_id) or await _guava_15_is_selected(
        page, worker_id
    )


async def _ensure_reference_after_prompt(
    page: Page,
    worker_id: int,
    reference_paths: list[str],
    *,
    video: bool = False,
    posing: bool = False,
) -> None:
    if not reference_paths:
        return
    if await _reference_attached_in_promptbar(page):
        return
    log.warning("[W%d] Reference lost after prompt paste — re-uploading once", worker_id)
    skip_create = await _model_verified_on_play_page(
        page, worker_id, video_tab=video, posing=posing
    )
    for idx, ref_path in enumerate(reference_paths):
        if video:
            await _upload_image_video(
                page, ref_path, worker_id, clear_existing=(idx == 0),
                skip_create_with_this=skip_create,
            )
        elif posing:
            await _upload_image_posing(
                page, ref_path, worker_id, clear_existing=(idx == 0),
                skip_create_with_this=skip_create,
            )
        else:
            await _upload_image(
                page, ref_path, worker_id, clear_existing=(idx == 0),
                skip_create_with_this=skip_create,
            )
    await _assert_reference_attached(page, worker_id)


async def _reference_attached_in_promptbar(page: Page) -> bool:
    try:
        return bool(await page.evaluate(_REFERENCE_ATTACHED_JS))
    except Exception:
        return False


@async_timeout(50.0)
async def _wait_for_reference_attached(page: Page, timeout_ms: int = 45_000) -> bool:
    deadline = time.time() + timeout_ms / 1000
    while time.time() < deadline:
        if await _reference_attached_in_promptbar(page):
            return True
        await page.wait_for_timeout(450)
    return False


async def _assert_reference_attached(page: Page, worker_id: int = 0) -> None:
    if await _reference_attached_in_promptbar(page):
        return
    await _log_promptbar_debug(page, worker_id)
    raise RuntimeError("Reference image not attached in Mage prompt bar")


async def _ensure_video_reference_before_send(
    page: Page,
    image_paths: list[str],
    prompt: str,
    worker_id: int = 0,
) -> None:
    """Re-upload reference once if it was lost before send."""
    if await _reference_attached_in_promptbar(page):
        return
    log.warning("[W%d] Reference lost before video send — re-uploading once", worker_id)
    for idx, image_path in enumerate(image_paths):
        await _upload_image_video(
            page,
            image_path,
            worker_id,
            clear_existing=(idx == 0),
        )
    await _paste_prompt(page, prompt, worker_id, prompt_mode="video")
    await _assert_reference_attached(page, worker_id)
    log.info("[W%d] ✅ Reference re-attached before video send", worker_id)


async def _read_gems_remaining(page: Page) -> Optional[int]:
    gems, _source = await _read_gems_remaining_detailed(page)
    return gems


async def _check_grok_gems(page: Page, worker_id: int = 0) -> None:
    gems = await _read_gems_remaining(page)
    if gems is not None and gems < GROK_GEM_COST:
        raise RuntimeError(f"Insufficient gems for Grok (have {gems}, need {GROK_GEM_COST})")
    if gems is not None:
        log.info("[W%d] 💎 Gems remaining: %d (Grok costs %d)", worker_id, gems, GROK_GEM_COST)


async def _check_kiwi_gems(page: Page, worker_id: int = 0) -> None:
    gems = await _read_gems_remaining(page)
    if gems is not None and gems < KIWI_GEM_COST:
        raise RuntimeError(f"Insufficient gems for Kiwi (have {gems}, need {KIWI_GEM_COST})")
    if gems is not None:
        log.info("[W%d] 💎 Gems remaining: %d (Kiwi costs %d)", worker_id, gems, KIWI_GEM_COST)


async def _check_guava_15_gems(page: Page, worker_id: int = 0) -> None:
    gems = await _read_gems_remaining(page)
    if gems is not None and gems < GUAVA_15_GEM_COST:
        raise RuntimeError(
            f"Insufficient gems for Guava Pro 1.5 (have {gems}, need {GUAVA_15_GEM_COST})"
        )
    if gems is not None:
        log.info(
            "[W%d] 💎 Gems remaining: %d (Guava 1.5 costs %d)",
            worker_id, gems, GUAVA_15_GEM_COST,
        )


async def _log_promptbar_debug(page: Page, worker_id: int = 0) -> None:
    try:
        snippet = await page.evaluate("""() => {
            const bar = document.querySelector("[data-promptbar='true']");
            if (!bar) return "no promptbar";
            const editor = bar.querySelector("div.tiptap.ProseMirror");
            const gems = (bar.innerText || "").match(/\\d+\\s*Gems?\\s*Remaining/i);
            const editorHasImage = editor
                ? editor.querySelectorAll('img, [data-type="image"]').length > 0
                : false;
            const refSrc = (src) => src && (
                src.includes("cdn") || src.includes("uploads") || src.includes("mage.space")
            );
            let barRef = false;
            for (const img of bar.querySelectorAll("img")) {
                if (img.alt === "Send") continue;
                if (refSrc(img.src)) { barRef = true; break; }
            }
            return JSON.stringify({
                gems: gems ? gems[0] : "unknown",
                editorLen: editor ? (editor.innerText || "").length : 0,
                imgCount: bar.querySelectorAll("img").length,
                editorHasImage,
                barRef,
                hasImageNode: editorHasImage,
                url: location.pathname,
                createWithThisVisible: !!document.querySelector(
                    "button:not([style*='display: none'])"
                ) && [...document.querySelectorAll("button")].some(b => {
                    const t = (b.innerText || b.textContent || "").trim();
                    return t === "Create with this" && b.offsetParent !== null;
                }),
                sendEnabled: !!bar.querySelector(
                    "div[style*='linear-gradient(135deg, #FFA94D'] img[alt='Send']"
                ),
                promptbarText: (bar.innerText || "").slice(0, 120),
            });
        }""")
        log.error("[W%d] Prompt bar debug: %s", worker_id, snippet)
    except Exception as e:
        log.debug("[W%d] Prompt bar debug failed: %s", worker_id, e)


async def _dispatch_image_paste_to_editor(page: Page, img_b64: str, mime_type: str) -> None:
    await page.evaluate("""async (args) => {
        const { b64, mime } = args;
        const editor = document.querySelector("div.promptbar-textarea div.tiptap.ProseMirror");
        if (!editor) throw new Error("ProseMirror editor not found");
        const binaryStr = atob(b64);
        const bytes = new Uint8Array(binaryStr.length);
        for (let i = 0; i < binaryStr.length; i++) bytes[i] = binaryStr.charCodeAt(i);
        const blob = new Blob([bytes], { type: mime });
        const file = new File([blob], "reference.png", { type: mime });
        try {
            const clipboardItem = new ClipboardItem({ [mime]: blob });
            await navigator.clipboard.write([clipboardItem]);
        } catch (clipErr) {
            console.warn("clipboard.write failed, using synthetic paste:", clipErr);
        }
        editor.focus();
        const dt = new DataTransfer();
        dt.items.add(file);
        editor.dispatchEvent(new ClipboardEvent("paste", {
            bubbles: true, cancelable: true, clipboardData: dt,
        }));
        // tiptap image extension often listens to drop, not paste, for file uploads.
        // Dispatch dragover + drop on the editor with the same file.
        try {
            const dt2 = new DataTransfer();
            dt2.items.add(file);
            editor.dispatchEvent(new DragEvent("dragenter", {
                bubbles: true, cancelable: true, dataTransfer: dt2,
            }));
            editor.dispatchEvent(new DragEvent("dragover", {
                bubbles: true, cancelable: true, dataTransfer: dt2,
            }));
            const dt3 = new DataTransfer();
            dt3.items.add(file);
            editor.dispatchEvent(new DragEvent("drop", {
                bubbles: true, cancelable: true, dataTransfer: dt3,
            }));
        } catch (dropErr) {
            console.warn("synthetic drop dispatch failed:", dropErr);
        }
    }""", {"b64": img_b64, "mime": mime_type})


async def _confirm_reference_after_paste(
    page: Page,
    before_ref: str,
    *,
    cdn_timeout_ms: int = 30_000,
    attach_timeout_ms: int = 20_000,
) -> bool:
    """Confirm a new reference after paste — CDN URL preferred, editor attachment as fallback."""
    src = await _wait_for_mage_reference_ready(page, before_ref, timeout_ms=cdn_timeout_ms)
    if src:
        return True
    if not await _wait_for_reference_attached(page, timeout_ms=attach_timeout_ms):
        return False
    if not before_ref:
        return True
    new_src = await _get_promptbar_reference_src(page)
    if new_src and new_src != before_ref:
        return True
    return await _reference_attached_in_promptbar(page)


async def _upload_reference_via_file_input(
    page: Page,
    image_path: str,
    worker_id: int = 0,
    *,
    before_ref: str = "",
    clear_existing: bool = True,
) -> bool:
    """Fallback: upload reference via hidden file input or dropzone."""
    try:
        if clear_existing and await _count_promptbar_references(page) == 0:
            await _click_add_reference_button(page, worker_id)
            await page.wait_for_timeout(300)

        # Selector priority: promptbar-scoped first, then page-wide fallbacks.
        # mage.space has moved the hidden file input outside [data-promptbar] in
        # some revisions of the Grok play workspace, so we MUST scan the whole
        # document as a last resort.
        selectors = [
            "[data-promptbar='true'] input[type='file']",
            "[data-promptbar='true'] div.mage-Dropzone-root input[type='file']",
            "div.mage-Dropzone-root input[type='file']",
            "div[class*='ropzone'] input[type='file']",
            "div[class*='romptbar'] input[type='file']",
            "input[type='file'][accept*='image']",
            "input[type='file']",  # page-wide last resort
        ]
        file_input = None
        matched_sel = ""
        for sel in selectors:
            try:
                loc = page.locator(sel).first
                if await loc.count() > 0:
                    file_input = loc
                    matched_sel = sel
                    break
            except Exception:
                continue

        if file_input is None:
            await _click_add_reference_button(page, worker_id)
            await page.wait_for_timeout(400)
            for sel in selectors:
                try:
                    loc = page.locator(sel).first
                    if await loc.count() > 0:
                        file_input = loc
                        matched_sel = sel
                        break
                except Exception:
                    continue

        if file_input is None:
            # + may open a native file chooser without a persistent input in DOM
            try:
                async with page.expect_file_chooser(timeout=3_000) as fc_info:
                    await _click_add_reference_button(page, worker_id)
                file_chooser = await fc_info.value
                await file_chooser.set_files(image_path)
                log.info("[W%d]   File chooser upload dispatched", worker_id)
            except Exception as chooser_err:
                log.debug("[W%d] No file input/chooser for reference upload: %s", worker_id, chooser_err)
                return False
        else:
            await file_input.set_input_files(image_path)
            log.info("[W%d]   File input upload dispatched (selector=%s)", worker_id, matched_sel)

        if not clear_existing:
            await page.wait_for_timeout(500)
            log.info("[W%d] 📎 Additional reference file-input dispatched — trust mode", worker_id)
            return True

        cdn_timeout_ms, _ = _reference_paste_timeouts()
        return await _confirm_reference_after_paste(
            page,
            before_ref,
            cdn_timeout_ms=cdn_timeout_ms,
            attach_timeout_ms=min(25_000, cdn_timeout_ms),
        )
    except Exception as e:
        log.warning("[W%d] File input upload failed: %s", worker_id, e)
        return False


@async_timeout(20.0)
async def _wait_for_promptbar_editor(
    page: Page,
    worker_id: int = 0,
    *,
    timeout_per_attempt_ms: int = 5_000,
    max_attempts: int = 3,
) -> Optional[Locator]:
    """Wait for tiptap editor with retries (transient UI races after tab switch)."""
    sel = "div.promptbar-textarea div.tiptap.ProseMirror"
    for attempt in range(max_attempts):
        ed = page.locator(sel).first
        try:
            await ed.wait_for(state="visible", timeout=timeout_per_attempt_ms)
            log.info("  ✅ Editor visible on attempt %d", attempt + 1)
            return ed
        except Exception:
            if attempt < max_attempts - 1:
                log.info(
                    "  ⏳ Editor not visible yet (attempt %d/%d), retrying...",
                    attempt + 1, max_attempts,
                )
                await page.wait_for_timeout(200)
                await _dismiss_blocking_overlays(page, worker_id, quiet=True, skip_escape=True)
            else:
                log.warning("  ⚠️ Editor visibility timeout after %d attempts", max_attempts)
    return None


async def _prepare_reference_upload_page(
    page: Page,
    worker_id: int = 0,
    *,
    video_tab: bool = False,
    skip_create_with_this: bool = False,
    grok_reference_mode: bool = False,
) -> None:
    """Stabilize prompt bar before reference paste (shared by Guava/posing/video)."""
    if not skip_create_with_this:
        await _click_create_with_this_if_visible(page, worker_id)
    if grok_reference_mode:
        await _ensure_grok_reference_mode_selected(page, worker_id)
    if video_tab:
        await _ensure_video_tab_selected(page, worker_id)
    else:
        await _ensure_image_tab_selected(page, worker_id)
    await _wait_promptbar_ready(page, worker_id, timeout_ms=15_000)
    await _dismiss_blocking_overlays(page, worker_id, quiet=True, skip_escape=True)
    await page.wait_for_timeout(250)


async def _paste_reference_into_editor(
    page: Page,
    img_b64: str,
    mime_type: str,
    worker_id: int,
    *,
    video_tab: bool,
    max_paste_attempts: int = REFERENCE_PASTE_ATTEMPTS,
    clear_existing: bool = True,
    skip_tab_select: bool = False,
    skip_prepare: bool = False,
    image_path: str | None = None,
    grok_reference_mode: bool = False,
) -> bool:
    """Paste reference image on Image or Video tab; return True when tiptap has image node."""
    if grok_reference_mode:
        await _ensure_grok_reference_mode_selected(page, worker_id)
    if not skip_tab_select:
        if video_tab:
            await _ensure_video_tab_selected(page, worker_id)
        else:
            await _ensure_image_tab_selected(page, worker_id)
    if not skip_prepare:
        await _wait_promptbar_ready(page, worker_id, timeout_ms=15_000)
        await _dismiss_blocking_overlays(page, worker_id, quiet=True, skip_escape=True)
        await page.wait_for_timeout(300)

    before_ref = ""
    before_count = 0
    known_srcs: list[str] = []
    if clear_existing:
        before_ref = await _clear_promptbar_reference(page)
        if before_ref:
            log.info("  Cleared stale reference before paste: %s", before_ref[:80])
    else:
        before_ref = await _get_promptbar_reference_src(page)
        known_srcs, before_count = await _snapshot_reference_state(page)
        log.info(
            "  Append reference: before_count=%d, known_srcs=%d",
            before_count, len(known_srcs),
        )

    ed = await _wait_for_promptbar_editor(page, worker_id)
    if ed is None:
        log.warning("[W%d] ProseMirror editor not visible — trying file-input fallback", worker_id)
        if image_path and os.path.exists(image_path):
            return await _upload_reference_via_file_input(
                page, image_path, worker_id,
                before_ref=before_ref, clear_existing=clear_existing,
            )
        return False

    await stable_click(page, ed, timeout_ms=5_000)
    await page.wait_for_timeout(100)

    tab_label = "Video" if video_tab else "Image"
    cdn_timeout_ms, _ = _reference_paste_timeouts()
    paste_wall_deadline = time.time() + REFERENCE_PASTE_WALL_SEC
    if not clear_existing:
        max_paste_attempts = 1
    for paste_attempt in range(max_paste_attempts):
        if time.time() >= paste_wall_deadline:
            log.warning(
                "[W%d] Reference paste wall time exceeded (%ds)",
                worker_id, REFERENCE_PASTE_WALL_SEC,
            )
            break
        if paste_attempt > 0:
            if clear_existing:
                before_ref = await _clear_promptbar_reference(page)
            else:
                known_srcs, before_count = await _snapshot_reference_state(page)
            await page.wait_for_timeout(150)
            await _dismiss_blocking_overlays(page, worker_id, quiet=True, skip_escape=True)
            ed = await _wait_for_promptbar_editor(page, worker_id, max_attempts=1) or ed
            await stable_click(page, ed, timeout_ms=3_000)
            await page.wait_for_timeout(80)

        if not clear_existing and before_count >= 1:
            await _click_add_reference_button(page, worker_id)

        # Play-model / Grok Reference: paste-first on play workspaces (Grok/Kiwi).
        on_play_page = "/play/" in (page.url or "").lower()
        # File-input-first path kept commented — Grok posing works better via paste + Reference chip.
        # on_grok = "grok-image-quality-fast-mode" in (page.url or "").lower()
        # if (
        #     (video_tab or on_play_page or grok_reference_mode)
        #     and clear_existing
        #     and image_path
        #     and os.path.exists(image_path)
        # ):
        #     if grok_reference_mode or on_grok:
        #         await _ensure_grok_reference_mode_selected(page, worker_id)
        #         await _click_add_reference_button(page, worker_id)
        #         await page.wait_for_timeout(350)
        #     log.info(
        #         "  [%s tab] Trying file-input first (attempt %d/%d)...",
        #         tab_label, paste_attempt + 1, max_paste_attempts,
        #     )
        #     if await _upload_reference_via_file_input(
        #         page,
        #         image_path,
        #         worker_id,
        #         before_ref=before_ref,
        #         clear_existing=clear_existing,
        #     ):
        #         return True
        #
        # if grok_reference_mode and image_path and os.path.exists(image_path):
        #     log.info(
        #         "  [Grok Reference] Retrying + / file chooser (attempt %d/%d)...",
        #         paste_attempt + 1, max_paste_attempts,
        #     )
        #     try:
        #         async with page.expect_file_chooser(timeout=4_000) as fc_info:
        #             await _click_add_reference_button(page, worker_id)
        #         file_chooser = await fc_info.value
        #         await file_chooser.set_files(image_path)
        #         cdn_timeout_ms, _ = _reference_paste_timeouts()
        #         if await _confirm_reference_after_paste(
        #             page,
        #             before_ref,
        #             cdn_timeout_ms=cdn_timeout_ms,
        #             attach_timeout_ms=min(25_000, cdn_timeout_ms),
        #         ):
        #             return True
        #     except Exception as chooser_err:
        #         log.debug("[W%d] Grok file chooser upload failed: %s", worker_id, chooser_err)

        log.info("  [%s tab] Pasting image (attempt %d/%d)...", tab_label, paste_attempt + 1, max_paste_attempts)
        try:
            await _dispatch_image_paste_to_editor(page, img_b64, mime_type)
        except Exception as e:
            log.warning("  Synthetic paste failed: %s", e)
            try:
                await page.evaluate("""async (args) => {
                    const { b64, mime } = args;
                    const binaryStr = atob(b64);
                    const bytes = new Uint8Array(binaryStr.length);
                    for (let i = 0; i < binaryStr.length; i++) bytes[i] = binaryStr.charCodeAt(i);
                    const blob = new Blob([bytes], { type: mime });
                    await navigator.clipboard.write([new ClipboardItem({ [mime]: blob })]);
                }""", {"b64": img_b64, "mime": mime_type})
                await page.keyboard.press("Control+v")
            except Exception as e2:
                log.warning("  Ctrl+V fallback failed: %s", e2)

        if not clear_existing:
            if image_path and os.path.exists(image_path):
                if await _upload_reference_via_file_input(
                    page,
                    image_path,
                    worker_id,
                    before_ref=before_ref,
                    clear_existing=False,
                ):
                    log.info(
                        "[W%d] 📎 Additional reference via file-input — trust mode",
                        worker_id,
                    )
                    return True
            try:
                await _dispatch_image_paste_to_editor(page, img_b64, mime_type)
            except Exception as e:
                log.warning("  Additional ref paste failed: %s", e)
            await page.wait_for_timeout(500)
            log.info("[W%d] 📎 Additional reference pasted — trust mode (skip DOM check)", worker_id)
            return True

        confirmed = await _confirm_reference_after_paste(
            page,
            before_ref,
            cdn_timeout_ms=cdn_timeout_ms,
            attach_timeout_ms=min(25_000, cdn_timeout_ms),
        )
        if confirmed:
            return True

        if image_path and os.path.exists(image_path) and not video_tab and not on_play_page:
            log.info("  [%s tab] Trying file-input fallback (attempt %d/%d)...", tab_label, paste_attempt + 1, max_paste_attempts)
            if await _upload_reference_via_file_input(
                page,
                image_path,
                worker_id,
                before_ref=before_ref,
                clear_existing=clear_existing,
            ):
                return True

        log.warning("  Editor image not confirmed (attempt %d/%d)", paste_attempt + 1, max_paste_attempts)
        await _log_promptbar_debug(page, worker_id)
        # On the FINAL failed attempt, dump the full prompt bar HTML so we can
        # see what mage.space actually looks like and adjust selectors next run.
        if paste_attempt >= max_paste_attempts - 1:
            try:
                html_dump = await page.evaluate("""() => {
                    const bar = document.querySelector("[data-promptbar='true']");
                    if (!bar) return "(no promptbar element)";
                    return bar.outerHTML.slice(0, 4000);
                }""")
                log.error("[W%d] 🔍 PROMPT BAR HTML DUMP (final paste attempt failed):\n%s",
                          worker_id, html_dump)
                btn_dump = await page.evaluate("""() => {
                    const out = [];
                    for (const b of document.querySelectorAll("button")) {
                        if (b.offsetParent === null) continue;
                        const t = (b.innerText || b.textContent || "").trim().slice(0, 40);
                        const al = b.getAttribute("aria-label") || "";
                        const title = b.getAttribute("title") || "";
                        const r = b.getBoundingClientRect();
                        out.push({text: t, aria: al, title: title, w: Math.round(r.width), h: Math.round(r.height)});
                    }
                    return JSON.stringify(out.slice(0, 50));
                }""")
                log.error("[W%d] 🔍 VISIBLE BUTTONS DUMP: %s", worker_id, btn_dump)
                inp_dump = await page.evaluate("""() => {
                    const out = [];
                    for (const i of document.querySelectorAll("input")) {
                        out.push({type: i.type, accept: i.accept || "", name: i.name || "", id: i.id || "", visible: i.offsetParent !== null});
                    }
                    return JSON.stringify(out);
                }""")
                log.error("[W%d] 🔍 ALL INPUTS DUMP: %s", worker_id, inp_dump)
            except Exception as dump_err:
                log.warning("[W%d] DOM dump failed: %s", worker_id, dump_err)
        await stable_click(page, ed, timeout_ms=3_000)
        await page.wait_for_timeout(300)

    return False


async def _upload_image_posing(
    page: Page,
    image_path: str,
    worker_id: int = 0,
    job: Optional["Job"] = None,
    s: Optional["WorkerSession"] = None,
    clear_existing: bool = True,
    *,
    skip_create_with_this: bool | None = None,
):
    """Grok posing upload — same path as Guava, Image tab on play workspace."""
    log.info("📤 [posing] Uploading reference: %s", image_path)
    await _upload_image(
        page,
        image_path,
        worker_id,
        job=job,
        s=s,
        clear_existing=clear_existing,
        skip_create_with_this=skip_create_with_this,
        video_tab=False,
        grok_reference_mode=True,
    )
    img_src = await _get_promptbar_reference_src(page)
    log.info("✅ [posing] Reference attached in prompt bar: %s", img_src or "attached")


async def _upload_image_video(
    page: Page,
    image_path: str,
    worker_id: int = 0,
    *,
    clear_existing: bool = True,
    skip_create_with_this: bool | None = None,
):
    """Kiwi video upload — unified path with Video tab on play workspace."""
    log.info("📤 [video] Uploading reference: %s", image_path)
    await _upload_image(
        page,
        image_path,
        worker_id,
        clear_existing=clear_existing,
        skip_create_with_this=skip_create_with_this,
        video_tab=True,
    )
    img_src = await _get_promptbar_reference_src(page)
    log.info("✅ [video] Reference attached in prompt bar: %s", img_src or "attached")


def _reference_paste_timeouts() -> tuple[int, int]:
    """CDN timeout (ms) and max paste attempts — extended when system is loaded."""
    cdn_ms = REFERENCE_CDN_TIMEOUT_MS
    attempts = REFERENCE_PASTE_ATTEMPTS
    if _builder_busy_count > 0 or _jobs_processing():
        cdn_ms = min(cdn_ms + 20_000, 75_000)
    per_attempt_cap = max(15_000, (REFERENCE_PASTE_WALL_SEC * 1000) // max(attempts, 1))
    cdn_ms = min(cdn_ms, per_attempt_cap)
    return cdn_ms, attempts


def _pipeline_upload_budget(job: Optional["Job"], image_path: str | None) -> int:
    """Extra seconds for reference upload retries inside run_pipeline."""
    ref_paths = _job_reference_image_paths(job, image_path)
    if not ref_paths:
        return 0
    per_ref = 35
    return min(120, per_ref * len(ref_paths) + 30)


async def _upload_image(
    page: Page,
    image_path: str,
    worker_id: int = 0,
    job: Optional["Job"] = None,
    s: Optional["WorkerSession"] = None,
    clear_existing: bool = True,
    *,
    skip_create_with_this: bool | None = None,
    video_tab: bool = False,
    grok_reference_mode: bool = False,
):
    """Paste the reference image into the prompt bar (Guava / Grok / Kiwi)."""
    label = "video" if video_tab else "image"
    log.info("📤 [%s] Uploading reference: %s", label, image_path)

    try:
        with open(image_path, "rb") as f:
            img_bytes = f.read()
        img_b64 = base64.b64encode(img_bytes).decode("ascii")
        log.info("  Image read OK (%d bytes, b64 len=%d)", len(img_bytes), len(img_b64))
    except Exception as e:
        log.error("  ❌ Failed to read image file: %s", e)
        raise RuntimeError(f"Cannot read image file: {e}") from e

    mime_type = mimetypes.guess_type(image_path)[0] or "image/png"
    if not mime_type.startswith("image/"):
        mime_type = "image/png"
    log.info("  MIME type: %s", mime_type)

    url_lower = (page.url or "").lower()
    if skip_create_with_this is None:
        skip_create_with_this = await _model_verified_on_play_page(
            page, worker_id, video_tab=video_tab, posing=not video_tab and "/grok-" in url_lower
        )
    if grok_reference_mode is False and not video_tab and "grok-image-quality-fast-mode" in url_lower:
        grok_reference_mode = True

    await _prepare_reference_upload_page(
        page,
        worker_id,
        video_tab=video_tab,
        skip_create_with_this=skip_create_with_this,
        grok_reference_mode=grok_reference_mode,
    )

    ok = await _paste_reference_into_editor(
        page,
        img_b64,
        mime_type,
        worker_id,
        video_tab=video_tab,
        clear_existing=clear_existing,
        skip_tab_select=True,
        skip_prepare=True,
        image_path=image_path,
        grok_reference_mode=grok_reference_mode,
    )
    if not ok:
        await _log_promptbar_debug(page, worker_id)
        raise RuntimeError("Reference image not uploaded to Mage after paste retries")

    final_src = await _get_promptbar_reference_src(page)
    if final_src:
        log.info("✅ Image attached in prompt bar! src=%s", final_src[:120])
    elif not clear_existing:
        log.info("✅ Additional reference dispatched (trust mode)")
    else:
        log.info("✅ Image attached in prompt bar!")
    await page.wait_for_timeout(300)


async def _paste_prompt(page: Page, prompt: str, worker_id: int = 0, **kwargs):
    """Fill the contenteditable prompt box via clipboard paste.
    
    IMPORTANT: This function is image-safe — it NEVER deletes image nodes from the
    tiptap editor. Doing selectAll+delete here would wipe the uploaded reference image.
    Instead it clears only text content and positions the cursor AFTER any image node.
    """
    sel = "div.promptbar-textarea div.tiptap.ProseMirror"
    try:
        await _dismiss_blocking_overlays(page, worker_id, quiet=True, skip_escape=True)
        ed = page.locator(sel).first
        await stable_click(page, ed, timeout_ms=5000)
        await page.wait_for_timeout(200)

        # Remove ONLY text nodes — preserve any uploaded image nodes in the editor.
        # selectAll + delete would also delete the reference image, which is wrong.
        try:
            await page.evaluate('''() => {
                const el = document.querySelector("div.promptbar-textarea div.tiptap.ProseMirror");
                if (!el) return;
                el.focus();

                // Walk all text nodes that are NOT inside image/attachment wrappers and clear them
                const walker = document.createTreeWalker(el, NodeFilter.SHOW_TEXT, {
                    acceptNode: node => {
                        // Skip text inside image wrappers (data-type="image", contenteditable=false)
                        const inImg = node.parentElement &&
                            (node.parentElement.closest('[data-type="image"]') ||
                             node.parentElement.closest('[contenteditable="false"]') ||
                             node.parentElement.closest('img'));
                        return inImg ? NodeFilter.FILTER_REJECT : NodeFilter.FILTER_ACCEPT;
                    }
                });
                const textNodes = [];
                let node;
                while ((node = walker.nextNode())) textNodes.push(node);
                textNodes.forEach(n => { n.textContent = ""; });

                // Remove any empty <p> tags that have no image descendants
                el.querySelectorAll("p").forEach(p => {
                    const hasImg = p.querySelector("img, [data-type='image'], [contenteditable='false']");
                    if (!hasImg && !p.textContent.trim()) p.remove();
                });

                // Position cursor at very end of editor (after image node if present)
                const range = document.createRange();
                range.selectNodeContents(el);
                range.collapse(false);  // false = collapse to END
                const sel = window.getSelection();
                sel.removeAllRanges();
                sel.addRange(range);

                el.dispatchEvent(new Event("input", { bubbles: true }));
            }''')
        except Exception as js_err:
            log.warning("JS image-safe clear failed: %s", js_err)

        # Move keyboard cursor to end (safe fallback — does not delete image nodes)
        await page.keyboard.press("Control+End")
        await page.wait_for_timeout(100)

        # Copy prompt text to clipboard and paste after the image node
        await page.evaluate('async (text) => { await navigator.clipboard.writeText(text); }', prompt)
        await page.wait_for_timeout(100)
        await page.keyboard.press("Control+v")
        await page.wait_for_timeout(200)
        log.info("✅ Prompt pasted (image node preserved)")
    except Exception as e:
        log.error("❌ Prompt textarea not found or clipboard paste failed: %s", e)
        raise RuntimeError(f"Prompt entry failed: {e}")



async def _hit_send(page: Page, s: Optional["WorkerSession"] = None, *, promptbar_only: bool = False, video: bool = False):
    """Click the send button (orange gradient div with Send img) with robust retry logic.
    
    From click_details.txt:
    Send img: <img alt="Send" src="/_next/static/media/send.c437d44d.svg">
    Send div: <div style="flex-shrink:0;border-radius:8px;background:linear-gradient(135deg, #FFA94D 0%, #FFD5A9 100%);...">
    """
    worker_id = s.worker_id if s is not None else 0
    await _dismiss_blocking_overlays(page, worker_id)
    await page.wait_for_timeout(100)  # Let overlays settle
    
    # Multi-strategy send button selectors (in priority order)
    send_selectors = []
    if promptbar_only:
        send_selectors.extend([
            ("[data-promptbar='true'] div[style*='linear-gradient(135deg, #FFA94D']:has(img[alt='Send'])", "promptbar orange send"),
            ("[data-promptbar='true'] img[alt='Send']", "promptbar Send img"),
            ("[data-promptbar='true'] button:has(img[alt='Send'])", "promptbar button with Send"),
        ])
    send_selectors.extend([
        # Strategy 1: Direct orange gradient div containing Send img
        ("div[style*='linear-gradient(135deg, #FFA94D']:has(img[alt='Send'])", "orange gradient div with Send img"),
        # Strategy 2: Send image by alt text (primary)
        ("img[alt='Send']", "img alt='Send'"),
        # Strategy 3: Send image by src pattern
        ("img[src*='send']", "img with send in src"),
        # Strategy 4: Container div with Send img
        ("div:has(img[alt='Send'])", "div containing Send img"),
        # Strategy 5: Button containing Send
        ("button:has(img[alt='Send'])", "button containing Send img"),
        # Strategy 6: SVG-based send icon (fallback if HTML changes)
        ("svg[width='20'][height='20']:parent div[style*='orange'], div[style*='FFA94D']", "orange container with svg"),
    ])
    
    max_retries = 3
    for retry_attempt in range(max_retries):
        for selector, desc in send_selectors:
            try:
                btn = page.locator(selector).first
                count = await btn.count()
                if count > 0:
                    # Extra stability checks before clicking
                    try:
                        await btn.wait_for(state="visible", timeout=3000)
                        await page.wait_for_timeout(80)  # CSS animations
                        
                        # Focus the element first for better click reliability
                        try:
                            await btn.focus()
                        except Exception:
                            pass
                        
                        # Primary click attempt
                        await stable_click(page, btn, timeout_ms=5000)
                        log.info("✅ Sent via click on %s (retry %d/%d)", desc, retry_attempt + 1, max_retries)
                        if s:
                            s.session_committed = True
                        return
                    except Exception as click_err:
                        log.debug("Failed to click %s: %s", desc, click_err)
                        
                        # If primary click fails, try coordinate-based click on parent
                        try:
                            box = await btn.bounding_box()
                            if box:
                                center_x = box['x'] + box['width'] / 2
                                center_y = box['y'] + box['height'] / 2
                                await page.mouse.click(center_x, center_y)
                                log.info("✅ Sent via coordinate click on %s", desc)
                                if s:
                                    s.session_committed = True
                                return
                        except Exception as coord_err:
                            log.debug("Coordinate click also failed: %s", coord_err)
                        
                        continue
            except Exception as e:
                log.debug("Selector '%s' not found: %s", selector, e)
                continue
        
        if retry_attempt < max_retries - 1:
            log.warning("⚠️ Send button click failed (attempt %d/%d), retrying...", retry_attempt + 1, max_retries)
            await _dismiss_blocking_overlays(page, worker_id)
            await page.wait_for_timeout(150)
    
    # Fallback strategy 1: Tab + Enter to focus and send via textarea/input
    try:
        log.info("⌨️ Attempting Tab + Enter fallback...")
        await page.keyboard.press("Tab")
        await page.wait_for_timeout(100)
        await page.keyboard.press("Enter")
        log.info("✅ Used Tab + Enter to send (fallback)")
        if s:
            s.session_committed = True
        return
    except Exception as kb_err:
        log.debug("Tab + Enter failed: %s", kb_err)
    
    # Fallback strategy 2: Direct Enter
    try:
        log.info("⌨️ Attempting direct Enter...")
        await page.keyboard.press("Enter")
        log.info("✅ Used Enter to send (final fallback)")
        if s:
            s.session_committed = True
        return
    except Exception as kb_err:
        log.error("❌ All send strategies failed (click, coordinate, Tab+Enter, Enter): %s", kb_err)
        if s:
            s.session_committed = True  # Mark as committed anyway for cleanup
        raise RuntimeError("Failed to send prompt after %d attempts" % max_retries)

def _best_url_from_srcset(srcset: str | None, src: str | None) -> str | None:
    """Pick the largest candidate from an img srcset (full resolution when available)."""
    best_url, best_score = None, -1
    if srcset:
        for part in srcset.split(","):
            part = part.strip()
            if not part:
                continue
            bits = part.split()
            url = bits[0]
            weight = 1
            if len(bits) > 1:
                desc = bits[1].lower()
                if desc.endswith("w"):
                    try:
                        weight = int(desc[:-1])
                    except ValueError:
                        weight = 1
                elif desc.endswith("x"):
                    try:
                        weight = int(float(desc[:-1]) * 2000)
                    except ValueError:
                        weight = 2000
            if weight > best_score:
                best_score, best_url = weight, url
    if best_url:
        return best_url
    return src


_MODERATION_PLACEHOLDER_MARKERS = (
    "placeholder.jpg",
    "grok-image-abuse",
    "abuse.jpg",
    "/random/",
    "moderation-blocked",
    "content-blocked",
)


def _is_moderation_placeholder_url(url: str) -> bool:
    if not url:
        return False
    u = url.lower()
    return any(marker in u for marker in _MODERATION_PLACEHOLDER_MARKERS)


async def _scan_dom_moderation_placeholder(page: Page) -> str | None:
    """Return visible abuse/placeholder CDN URL, if any."""
    try:
        srcs = await page.evaluate("""() => {
            const out = [];
            document.querySelectorAll("img.MageMedia-image, img[src*='mage.space']").forEach(img => {
                const s = img.currentSrc || img.src || "";
                if (s) out.push(s);
            });
            return out;
        }""")
        for src in srcs or []:
            if _is_moderation_placeholder_url(src):
                return src
    except Exception:
        pass
    return None


async def _resolve_image_output_with_settle(
    page: Page,
    pre_count: int,
    worker_id: int,
    *,
    pre_urls: Optional[set[str]] = None,
    exclude_urls: Optional[set[str]] = None,
    max_rounds: int = 12,
) -> str | None:
    """Poll DOM for a valid creation URL — CDN embeds can lag behind the UI."""
    pre_urls = pre_urls or set()
    excluded = set(exclude_urls or set())
    for round_i in range(max_rounds):
        url = await _resolve_best_output_url(
            page, pre_count, worker_id,
            pre_urls=pre_urls,
            exclude_urls=excluded,
        )
        if url:
            if _is_moderation_placeholder_url(url):
                raise ContentForbiddenError("Moderation placeholder URL rejected")
            return url
        mod_url = await _scan_dom_moderation_placeholder(page)
        if mod_url and round_i >= 1:
            log.warning(
                "[W%d] 🛑 Moderation placeholder visible (no creation URL): %s",
                worker_id, mod_url[:90],
            )
            raise ContentForbiddenError("Grok abuse/moderation placeholder detected")
        await page.wait_for_timeout(350 if round_i < 4 else 500)
    mod_url = await _scan_dom_moderation_placeholder(page)
    if mod_url:
        raise ContentForbiddenError("Grok abuse/moderation placeholder detected")
    return None


async def _download_generation_result(
    s: WorkerSession,
    page: Page,
    url: str,
    reference_paths: list[str],
    *,
    pre_count: int = 0,
    pre_urls: Optional[set[str]] = None,
    exclude_urls: Optional[set[str]] = None,
) -> str:
    """Download output; if bytes match reference, re-scan DOM for the real creation."""
    pre_urls = pre_urls or set()
    excluded = set(exclude_urls or set())
    tried: set[str] = set()
    current = url
    for _ in range(4):
        if not current or current in tried:
            break
        tried.add(current)
        result = await _download_image(current)
        try:
            _assert_output_not_reference(result, reference_paths, s.worker_id)
            return result
        except RuntimeError:
            log.warning(
                "[W%d] Output matched reference — re-scanning for creation URL (excluded %s)",
                s.worker_id, current[:80],
            )
            try:
                os.unlink(result)
            except OSError:
                pass
            excluded.add(current)
            current = await _resolve_image_output_with_settle(
                page, pre_count, s.worker_id,
                pre_urls=pre_urls,
                exclude_urls=excluded,
                max_rounds=10,
            ) or ""
    raise RuntimeError("Downloaded output identical to reference — wrong CDN URL picked")


def is_valid_mage_output_url(url: str) -> bool:
    """Filter valid Mage generation output URLs (exclude reference uploads)."""
    if not url or not url.startswith("http"):
        return False
    url_lower = url.lower()
    if _is_moderation_placeholder_url(url):
        return False
    if any(keyword in url_lower for keyword in (
        "pixel.gif", "track", "analytics", "placeholder", "preview", "demo", "sample",
        "awsapprunner", "doubleclick", "google-analytics",
    )):
        return False
    if "/uploads/" in url_lower:
        return False
    # Reference uploads use bare /image/ paths; creations live under /creations/
    if "/image/" in url_lower and "/creations/" not in url_lower:
        return False
    try:
        from urllib.parse import urlparse
        parsed = urlparse(url)
        if "mage.space" not in parsed.netloc.lower():
            return False
    except Exception:
        return False
    return "/creations/" in url_lower or "/temp/" in url_lower


def _mage_output_url_score(url: str) -> int:
    """Prefer full generation CDN URLs over upload thumbnails."""
    u = (url or "").lower()
    if not u.startswith("http"):
        return -1
    if not is_valid_mage_output_url(url):
        return -10_000
    score = 0
    if "/creations/" in u:
        score += 1000
    if "/temp/" in u:
        score += 500
    if "thumb" in u or "preview" in u or "small" in u:
        score -= 500
    return score


async def _img_element_best_src(img_el) -> str:
    srcset = await img_el.get_attribute("srcset")
    src = await img_el.get_attribute("src") or ""
    return _best_url_from_srcset(srcset, src) or src


async def _resolve_best_output_url(
    page: Page,
    pre_count: int,
    worker_id: int = 0,
    exclude_url: str | None = None,
    *,
    pre_urls: Optional[set[str]] = None,
    exclude_urls: Optional[set[str]] = None,
) -> str | None:
    """Collect CDN URLs from new result images; prefer full /creations/ URLs and largest srcset."""
    pre_urls = pre_urls or set()
    excluded = set(exclude_urls or set())
    if exclude_url:
        excluded.add(exclude_url)

    candidates: list[str] = []
    for sel in (
        "img.MageMedia-image[data-load-state='loaded']",
        "img.MageMedia-image",
        "img[src*='cdn3.mage.space']",
        "img[src*='mage.space/temp']",
    ):
        try:
            imgs = await page.query_selector_all(sel)
            if pre_urls:
                slice_imgs = imgs
            elif pre_count and len(imgs) > pre_count:
                slice_imgs = imgs[pre_count:]
            elif pre_count:
                slice_imgs = []
            else:
                slice_imgs = imgs
            for img in slice_imgs:
                src = await _img_element_best_src(img)
                if not is_valid_mage_output_url(src) or src in candidates:
                    continue
                if src in excluded or src in pre_urls:
                    continue
                candidates.append(src)
        except Exception as e:
            log.debug("[W%d] URL scan '%s': %s", worker_id, sel, e)
    if not candidates:
        return None
    best = max(candidates, key=_mage_output_url_score)
    log.info(
        "[W%d] ✅ Full-res output URL (%d candidates): %s …",
        worker_id, len(candidates), best[:90],
    )
    return best


def is_valid_mage_video_url(url: str) -> bool:
    """Filter valid Mage video CDN URLs (exclude site previews and reference uploads)."""
    if not url or not url.startswith("http"):
        return False
    url_lower = url.lower()
    if any(keyword in url_lower for keyword in (
        "pixel.gif", "track", "analytics", "placeholder", "preview", "demo", "sample",
    )):
        return False
    if "/uploads/" in url_lower or "/image/" in url_lower:
        return False
    if ".mp4" not in url_lower and "/video/" not in url_lower:
        return False
    try:
        from urllib.parse import urlparse
        parsed = urlparse(url)
        if "mage.space" not in parsed.netloc.lower():
            return False
    except Exception:
        return False
    return "/creations/" in url_lower or "/temp/" in url_lower


def _mage_video_url_score(url: str) -> int:
    """Prefer freshly rendered creation URLs over any stale page embeds."""
    u = (url or "").lower()
    if not u.startswith("http"):
        return -1
    score = 0
    if "/creations/" in u and "/video/" in u:
        score += 1000
    if "/temp/" in u:
        score += 500
    if u.endswith(".mp4") or ".mp4?" in u:
        score += 100
    if "/uploads/" in u or "/image/" in u:
        score -= 10_000
    if any(k in u for k in ("preview", "demo", "sample", "placeholder")):
        score -= 10_000
    return score


async def _snapshot_video_urls(page: Page) -> set[str]:
    """Capture video CDN URLs already on the page before a new generation."""
    urls: set[str] = set()
    try:
        js_urls = await page.evaluate("""() => {
            const urls = [];
            document.querySelectorAll("video, video source, a[href*='.mp4']").forEach(el => {
                const u = el.src || el.href || el.getAttribute("src") || el.getAttribute("href") || "";
                if (u) urls.push(u);
            });
            return urls;
        }""")
        for src in js_urls or []:
            if src:
                urls.add(src)
    except Exception:
        pass
    return urls


async def _snapshot_image_urls(page: Page) -> set[str]:
    """Capture image CDN URLs already on the page before a new generation."""
    urls: set[str] = set()
    for sel in (
        "img.MageMedia-image",
        "[data-promptbar='true'] img",
        "div.promptbar-textarea div.tiptap.ProseMirror img",
    ):
        try:
            imgs = await page.query_selector_all(sel)
            for img in imgs:
                src = await _img_element_best_src(img)
                if src and src.startswith("http"):
                    urls.add(src)
        except Exception:
            pass
    return urls


async def _capture_reference_cdn_urls(page: Page, s: WorkerSession) -> None:
    """Store prompt-bar reference CDN URLs so output picker can exclude them."""
    urls: set[str] = set()
    for src in await _get_promptbar_reference_srcs(page):
        if src and src.startswith("http"):
            urls.add(src)
    s.reference_cdn_urls = urls


def _file_sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _output_matches_reference(result_path: str, reference_paths: list[str]) -> bool:
    """True when downloaded output bytes match any local reference file."""
    if not result_path or not os.path.isfile(result_path) or not reference_paths:
        return False
    try:
        out_hash = _file_sha256(result_path)
    except OSError:
        return False
    for ref_path in reference_paths:
        if not ref_path or not os.path.isfile(ref_path):
            continue
        try:
            if _file_sha256(ref_path) == out_hash:
                return True
        except OSError:
            continue
    return False


def _assert_output_not_reference(
    result_path: str, reference_paths: list[str], worker_id: int = 0
) -> None:
    if _output_matches_reference(result_path, reference_paths):
        log.error(
            "[W%d] Downloaded output identical to reference — wrong CDN URL picked",
            worker_id,
        )
        raise RuntimeError(
            "Downloaded output identical to reference — wrong CDN URL picked"
        )


async def _resolve_best_video_output_url(
    page: Page,
    worker_id: int = 0,
    *,
    pre_urls: Optional[set[str]] = None,
) -> str | None:
    """Collect NEW CDN URLs from video elements; prefer /creations/ outputs."""
    pre_urls = pre_urls or set()
    candidates: list[str] = []
    try:
        js_urls = await page.evaluate("""() => {
            const urls = [];
            document.querySelectorAll("video, video source, a[href*='.mp4']").forEach(el => {
                const u = el.src || el.href || el.getAttribute("src") || el.getAttribute("href") || "";
                if (u && u.includes("mage.space")) urls.push(u);
            });
            return urls;
        }""")
        for src in js_urls or []:
            if (
                is_valid_mage_video_url(src)
                and src not in candidates
                and src not in pre_urls
            ):
                candidates.append(src)
    except Exception as e:
        log.debug("[W%d] Video JS scan failed: %s", worker_id, e)

    for sel, attr in (
        ("video source[src*='mage.space']", "src"),
        ("video[src*='mage.space']", "src"),
        ("a[href*='.mp4']", "href"),
        ("a[href*='mage.space'][href*='/video/']", "href"),
    ):
        try:
            elements = await page.query_selector_all(sel)
            for el in elements:
                src = await el.get_attribute(attr) or ""
                if (
                    is_valid_mage_video_url(src)
                    and src not in candidates
                    and src not in pre_urls
                ):
                    candidates.append(src)
        except Exception as e:
            log.debug("[W%d] Video URL scan '%s': %s", worker_id, sel, e)

    if not candidates:
        return None
    best = max(candidates, key=_mage_video_url_score)
    log.info("[W%d] ✅ Video output URL (%d new candidates): %s …", worker_id, len(candidates), best[:90])
    return best


async def _send_output_to_chat(
    bot,
    chat_id: int,
    result_path: str,
    caption: str,
    *,
    pipeline: str = "guava",
    cdn_url: str | None = None,
) -> None:
    """Send result to chat. Prefers CDN URL (JSON through proxy); falls back to file upload."""
    cdn_ok = False
    if cdn_url:
        if pipeline == "video":
            cdn_ok = is_valid_mage_video_url(cdn_url)
        else:
            cdn_ok = is_valid_mage_output_url(cdn_url)
    if cdn_ok:
        log.info("📤 Sending output via CDN URL (proxy-safe)")
        try:
            if pipeline == "video":
                await bot.send_video(
                    chat_id=chat_id,
                    video=cdn_url,
                    caption=caption,
                    supports_streaming=True,
                    read_timeout=60,
                    write_timeout=60,
                )
            else:
                await bot.send_photo(
                    chat_id=chat_id,
                    photo=cdn_url,
                    caption=caption,
                    read_timeout=30,
                    write_timeout=60,
                )
            return
        except Exception as cdn_err:
            log.warning("CDN URL send failed (%s) — falling back to file upload", cdn_err)

    if not result_path or not os.path.isfile(result_path):
        raise FileNotFoundError(f"Output file missing: {result_path}")
    file_size = os.path.getsize(result_path)
    if file_size < MIN_TELEGRAM_IMAGE_BYTES:
        raise ValueError(
            f"Output file too small to send ({file_size} bytes): {result_path}"
        )

    filename = os.path.basename(result_path) or (
        "mage_output.mp4" if pipeline == "video" else "mage_output.jpg"
    )
    with open(result_path, "rb") as f:
        data = f.read()
    if len(data) < MIN_TELEGRAM_IMAGE_BYTES:
        raise ValueError(f"Output read empty or too small ({len(data)} bytes)")

    payload = InputFile(io.BytesIO(data), filename=filename)
    if pipeline == "video":
        await bot.send_video(
            chat_id=chat_id,
            video=payload,
            caption=caption,
            supports_streaming=True,
            read_timeout=60,
            write_timeout=60,
        )
    elif SEND_AS_DOCUMENT:
        await bot.send_document(
            chat_id=chat_id,
            document=payload,
            caption=caption,
            read_timeout=30,
            write_timeout=30,
        )
    else:
        try:
            await bot.send_photo(
                chat_id=chat_id,
                photo=payload,
                caption=caption,
                read_timeout=30,
                write_timeout=60,
            )
        except Exception as photo_err:
            msg = str(photo_err).lower()
            if "no photo" in msg or "wrong file" in msg or "file" in msg:
                log.warning("send_photo failed (%s) — retrying as document", photo_err)
                doc_payload = InputFile(io.BytesIO(data), filename=filename)
                await bot.send_document(
                    chat_id=chat_id,
                    document=doc_payload,
                    caption=caption,
                    read_timeout=30,
                    write_timeout=60,
                )
            else:
                raise


def is_valid_mage_image_url(url: str) -> bool:
    """Filter out tracking pixels, scripts, and non-image assets."""
    if not url or not url.startswith("http"):
        return False
    url_lower = url.lower()
    # Exclude tracking pixels / AWS App Runner / segment / analytic tracking gifs/scripts
    if any(keyword in url_lower for keyword in ["pixel.gif", "track", "analytics", "awsapprunner", "doubleclick", "google-analytics"]):
        return False
    try:
        from urllib.parse import urlparse
        parsed = urlparse(url)
        # Verify the domain belongs to mage or standard CDN
        if not any(domain in parsed.netloc.lower() for domain in ["mage.space", "images.unsplash.com", "githubusercontent.com"]):
            return False
    except Exception:
        pass
    return True


@async_timeout(250.0)
async def _wait_for_result(
    s: WorkerSession,
    page: Page,
    timeout_s: int = 240,
    *,
    posing: bool = False,
    video: bool = False,
    gems_before: Optional[int] = None,
    video_image_paths: Optional[list[str]] = None,
    video_prompt: Optional[str] = None,
    exclude_url: str | None = None,
    job: Optional["Job"] = None,
) -> str | None:
    """Wait until generation finishes, return the output CDN URL.
    Pre-counts images so we only grab the NEW one. Smart timeout & error handling."""
    log.info("[W%d] ⏳ Waiting for generation (up to %ds) …", s.worker_id, timeout_s)

    media_mode = posing or video
    if media_mode:
        await page.wait_for_timeout(400)

    pre_video_urls: set[str] = set()
    if video:
        pre_video_urls = await _snapshot_video_urls(page)
        log.debug("[W%d] Pre-gen video URL count: %d", s.worker_id, len(pre_video_urls))

    pre_image_urls: set[str] = set()
    if not video:
        pre_image_urls = await _snapshot_image_urls(page)
        log.debug("[W%d] Pre-gen image URL count: %d", s.worker_id, len(pre_image_urls))

    exclude_urls: set[str] = set(pre_image_urls)
    exclude_urls.update(s.reference_cdn_urls or set())
    if exclude_url:
        exclude_urls.add(exclude_url)

    # Pre-count images already on page before generation starts
    try:
        pre_imgs = await page.query_selector_all("img.MageMedia-image")
        pre_count = len(pre_imgs)
        log.debug("[W%d] Pre-gen image count: %d", s.worker_id, pre_count)
    except Exception as e:
        log.warning("[W%d] ⚠️ Could not pre-count images: %s", s.worker_id, e)
        pre_count = 0

    # ── Detect which button signals generation start ─────────────────────────
    # We probe each indicator separately so we know EXACTLY which one appeared.
    # This matters for the completion check: wait_for_selector(state="hidden")
    # on a comma-selector returns immediately if ANY selector is not present
    # (Playwright considers missing elements as already "hidden") — so we must
    # wait only for the specific button that is actually visible.
    GENERATION_INDICATORS = [
        "button:has-text('Generating')",
        "button:has-text('Cancel')",
        "div[role='progressbar']",
        ".generation-indicator",
        "span:has-text('Generating')",
    ]
    if video:
        GENERATION_INDICATORS = [
            "button:has-text('Generating:')",  # Kiwi queue: "Generating: 1 / 10"
            "[data-promptbar='true'] button:has-text('Rendering')",
            "[data-promptbar='true'] span:has-text('Rendering')",
            "[data-promptbar='true'] :has-text('Queued')",
            "[data-promptbar='true'] :has-text('Processing')",
        ]
    elif media_mode:
        # NOTE: Never use :has-text('Autocreate') — that is a permanent prompt-bar
        # chip, not a generation state. Matching it caused false "started then vanished"
        # failures on Mango 3 / Grok / GPT Image (indicator "gone" in <1s).
        GENERATION_INDICATORS = [
            "[data-promptbar='true'] button:has-text('Generating')",
            "[data-promptbar='true'] span:has-text('Generating')",
            "[data-promptbar='true'] button:has-text('Cancel')",
            "[data-promptbar='true'] :has-text('Creating')",
            "[data-promptbar='true'] :has-text('In queue')",
            "[data-promptbar='true'] div[role='progressbar']",
            *GENERATION_INDICATORS,
        ]
    active_indicator = None
    indicator_appeared_at: float | None = None

    max_detection_attempts = 3
    for attempt in range(max_detection_attempts):
        if attempt > 0:
            log.info("[W%d] 🔄 Re-checking indicators (attempt %d/%d)", s.worker_id, attempt + 1, max_detection_attempts)

        if video and await _kiwi_queue_generation_active(page):
            log.info("[W%d] 🔄 Video generation started — Kiwi queue UI", s.worker_id)
            active_indicator = "__kiwi_queue__"
            indicator_appeared_at = time.time()
            break

        for sel in GENERATION_INDICATORS:
            try:
                if media_mode:
                    sel_timeout = 5000 if attempt == 0 else 2000
                else:
                    sel_timeout = 1500 if attempt > 0 else (3000 if video else 2500)
                await page.wait_for_selector(sel, state="visible", timeout=sel_timeout)
                log.info("[W%d] 🔄 Generation started — indicator: %s", s.worker_id, sel)
                active_indicator = sel
                indicator_appeared_at = time.time()
                break
            except PWTimeout:
                log.debug("[W%d] Indicator '%s' not visible", s.worker_id, sel)

        if not active_indicator:
            try:
                cur_count = len(await page.query_selector_all("img.MageMedia-image"))
                if cur_count > pre_count:
                    log.info(
                        "[W%d] 🔄 Generation started — feed image count %d → %d",
                        s.worker_id, pre_count, cur_count,
                    )
                    active_indicator = "__feed_image__"
                    indicator_appeared_at = time.time()
            except Exception:
                pass

        if active_indicator:
            break

        if not active_indicator and media_mode:
            try:
                grok_started = await page.evaluate("""() => {
                    const bar = document.querySelector("[data-promptbar='true']");
                    if (!bar) return false;
                    const t = (bar.innerText || "").toLowerCase();
                    return t.includes("generating") || t.includes("creating")
                        || t.includes("rendering") || t.includes("queued")
                        || t.includes("processing");
                }""")
                if grok_started:
                    log.info("[W%d] 🔄 Generation started — prompt bar text", s.worker_id)
                    active_indicator = "__grok_promptbar_text__"
                    indicator_appeared_at = time.time()
                    break
            except Exception:
                pass

        if not active_indicator and gems_before is not None:
            try:
                gems_now = await _read_gems_remaining(page)
                if gems_now is not None and gems_now < gems_before:
                    log.info(
                        "[W%d] 🔄 Generation started — gems deducted (%d → %d)",
                        s.worker_id,
                        gems_before,
                        gems_now,
                    )
                    active_indicator = "__gems_deducted__"
                    indicator_appeared_at = time.time()
                    break
                cost_submitted = await page.evaluate("""(args) => {
                    const bar = document.querySelector("[data-promptbar='true']");
                    if (!bar) return false;
                    const t = bar.innerText || "";
                    const matches = [...t.matchAll(/(\\d+)\\s*Gems?\\s*Remaining/gi)];
                    if (!matches.length) return false;
                    let max = 0;
                    for (const m of matches) max = Math.max(max, parseInt(m[1], 10));
                    return max > 0 && max < args.gemsBefore;
                }""", {"gemsBefore": gems_before})
                if cost_submitted:
                    log.info(
                        "[W%d] 🔄 Generation started — gems dropped in promptbar",
                        s.worker_id,
                    )
                    active_indicator = "__gems_deducted__"
                    indicator_appeared_at = time.time()
                    break
            except Exception:
                pass

        if active_indicator:
            break

        if attempt < max_detection_attempts - 1:
            if FAST_FAIL_NO_INDICATOR:
                prereq_ok, prereq_reason = await _generation_prerequisites_ok(
                    page,
                    s.worker_id,
                    needs_reference=bool(video_image_paths),
                    posing=posing,
                    video=video,
                )
                # On play workspace URLs "Create with this" is cosmetic — never fast-fail on it
                _url_now = (page.url or "").lower()
                _on_play = (
                    "grok-image-quality-fast-mode" in _url_now
                    or "kiwi-video-fast-mode" in _url_now
                    or "gpt-image-2-fast-mode" in _url_now
                    or ("mango-3-fast-mode" in _url_now and "mango-3s" not in _url_now)
                )
                create_blocking = (
                    not _on_play and await _create_with_this_visible(page)
                )
                if not prereq_ok or create_blocking:
                    log.error(
                        "[W%d] Fast-fail: generation prerequisites failed (%s)",
                        s.worker_id,
                        prereq_reason if not prereq_ok else "Create with this visible",
                    )
                    break

            if video and await _kiwi_queue_generation_active(page):
                log.info(
                    "[W%d] 🔄 Video generation already running — Kiwi queue UI (skip send retry)",
                    s.worker_id,
                )
                active_indicator = "__kiwi_queue__"
                break

            log.warning("[W%d] ⚠️ No generation indicator seen (attempt %d/%d), retrying _hit_send...",
                       s.worker_id, attempt + 1, max_detection_attempts)
            if media_mode:
                await _log_promptbar_debug(page, s.worker_id)
            try:
                if video:
                    await _ensure_kiwi_model_before_send(
                        page,
                        s.worker_id,
                        image_paths=video_image_paths,
                        prompt=video_prompt,
                    )
                    if video_image_paths and not await _reference_attached_in_promptbar(page):
                        log.warning(
                            "[W%d] Reference missing before send retry — re-uploading",
                            s.worker_id,
                        )
                        for idx, image_path in enumerate(video_image_paths):
                            await _upload_image_video(
                                page,
                                image_path,
                                s.worker_id,
                                clear_existing=(idx == 0),
                            )
                        if video_prompt:
                            await _paste_prompt(page, video_prompt, s.worker_id, prompt_mode="video")
                    log.info(
                        "[W%d] Video send retry state: url=%s model='%s' barRef=%s",
                        s.worker_id,
                        (page.url or "")[:80],
                        await _get_promptbar_model_text(page),
                        await _reference_attached_in_promptbar(page),
                    )
                elif posing:
                    await _ensure_image_tab_selected(page, s.worker_id)
                    await _ensure_reference_mode_chip(page, s.worker_id)
                    await _focus_prompt_editor(page, s.worker_id)
                if video:
                    await _hit_send_video(page, s)
                else:
                    await _hit_send(page, s, promptbar_only=True)
                await page.wait_for_timeout(300 if not media_mode else 2_000)
            except Exception as e:
                log.error("[W%d] ❌ _hit_send retry failed: %s", s.worker_id, e)
        else:
            log.error("[W%d] ❌ No generation indicator appeared after %d retry attempts",
                     s.worker_id, max_detection_attempts)

    if not active_indicator:
        if video and await _kiwi_queue_generation_active(page):
            log.info("[W%d] 🔄 Video generation detected via emergency Kiwi queue check", s.worker_id)
            active_indicator = "__kiwi_queue__"
        else:
            if media_mode:
                await _log_promptbar_debug(page, s.worker_id)
            try:
                buttons = await page.query_selector_all("button")
                visible_buttons = []
                for btn in buttons:
                    try:
                        visible = await btn.evaluate("el => el.offsetParent !== null")
                        if visible:
                            text = await btn.inner_text()
                            visible_buttons.append(text)
                    except Exception:
                        pass
                log.error("[W%d] 🔍 Emergency check — visible buttons on page: %s", s.worker_id, visible_buttons)
            except Exception:
                pass
            raise RuntimeError("Generation never started — no indicator detected after %d attempts with fresh account retry" % max_detection_attempts)

    # Track whether the active indicator was short-lived (< 2s) — signals possible silent rejection
    _indicator_short_lived: bool = False

    try:
        # Wait for exactly the indicator that appeared to disappear, checking for forbidden content periodically
        start_time = time.time()
        poll_interval = RESULT_POLL_SEC
        max_wait_attempts = 0
        while time.time() - start_time < timeout_s:
            # ── CANCEL FLAG CHECK ── abort immediately if user pressed /cancel
            if job and job.user_id in _user_cancel_flags:
                log.info("[W%d] 🚫 Cancel flag detected in poll loop — aborting generation", s.worker_id)
                raise asyncio.CancelledError("user cancelled")

            elapsed = time.time() - start_time
            if elapsed > 15:
                poll_interval = min(poll_interval, 0.25)
            if elapsed > 45:
                poll_interval = min(poll_interval, 0.15)

            if await detect_forbidden(page):
                log.warning("[W%d] 🛑 Content forbidden modal detected during wait!", s.worker_id)
                raise ContentForbiddenError("Forbidden content detected (moderation block)")
            
            if active_indicator == "__gems_deducted__":
                try:
                    if video:
                        video_url = await _resolve_best_video_output_url(
                            page, s.worker_id, pre_urls=pre_video_urls,
                        )
                        if video_url:
                            log.info("[W%d] ✅ Video ready (gems-deducted path)", s.worker_id)
                            return video_url
                    else:
                        img_url = await _resolve_best_output_url(
                            page, pre_count, s.worker_id,
                            pre_urls=pre_image_urls,
                            exclude_urls=exclude_urls,
                        )
                        if img_url:
                            if _is_moderation_placeholder_url(img_url):
                                raise ContentForbiddenError("Moderation placeholder URL in gems-deducted path")
                            log.info("[W%d] ✅ Image ready (gems-deducted path)", s.worker_id)
                            return img_url
                except Exception:
                    pass
            elif active_indicator == "__kiwi_queue__":
                still_active = await _kiwi_queue_generation_active(page)
                if not still_active:
                    log.info("[W%d] ✅ Video generation finished (Kiwi queue cleared)", s.worker_id)
                    break
                if video:
                    try:
                        video_url = await _resolve_best_video_output_url(
                            page, s.worker_id, pre_urls=pre_video_urls,
                        )
                        if video_url:
                            log.info("[W%d] ✅ Video ready (Kiwi queue path)", s.worker_id)
                            return video_url
                    except Exception:
                        pass
            elif active_indicator == "__poll_output__":
                # Short-lived / false-positive indicator — keep scanning for result
                # (and latch onto a real Generating/Cancel indicator if it appears).
                try:
                    if video:
                        video_url = await _resolve_best_video_output_url(
                            page, s.worker_id, pre_urls=pre_video_urls,
                        )
                        if video_url:
                            log.info("[W%d] ✅ Video ready (poll-output path)", s.worker_id)
                            return video_url
                    else:
                        img_url = await _resolve_best_output_url(
                            page, pre_count, s.worker_id,
                            pre_urls=pre_image_urls,
                            exclude_urls=exclude_urls,
                        )
                        if img_url:
                            if _is_moderation_placeholder_url(img_url):
                                raise ContentForbiddenError("Moderation placeholder URL in poll-output path")
                            log.info("[W%d] ✅ Image ready (poll-output path)", s.worker_id)
                            return img_url
                except ContentForbiddenError:
                    raise
                except Exception:
                    pass
                try:
                    for sel in GENERATION_INDICATORS:
                        if "Autocreate" in sel:
                            continue
                        try:
                            if await page.locator(sel).first.is_visible():
                                log.info(
                                    "[W%d] 🔄 Latched real indicator after false-positive: %s",
                                    s.worker_id, sel,
                                )
                                active_indicator = sel
                                indicator_appeared_at = time.time()
                                break
                        except Exception:
                            continue
                except Exception:
                    pass
            elif active_indicator == "__grok_promptbar_text__":
                try:
                    still_generating = await page.evaluate("""() => {
                        const bar = document.querySelector("[data-promptbar='true']");
                        if (!bar) return false;
                        const t = (bar.innerText || "").toLowerCase();
                        return t.includes("generating") || t.includes("creating")
                            || t.includes("rendering") || t.includes("queued")
                            || t.includes("processing");
                    }""")
                except Exception:
                    still_generating = False
                if not still_generating:
                    log.info("[W%d] ✅ Generation finished (Grok prompt bar text cleared)", s.worker_id)
                    break
            elif active_indicator == "__feed_image__":
                if video:
                    try:
                        video_url = await _resolve_best_video_output_url(
                            page, s.worker_id, pre_urls=pre_video_urls,
                        )
                        if video_url:
                            log.info("[W%d] ✅ Video ready (feed image path)", s.worker_id)
                            return video_url
                    except Exception:
                        pass
                else:
                    try:
                        img_url = await _resolve_best_output_url(
                            page, pre_count, s.worker_id,
                            pre_urls=pre_image_urls,
                            exclude_urls=exclude_urls,
                        )
                        if img_url:
                            if _is_moderation_placeholder_url(img_url):
                                raise ContentForbiddenError("Moderation placeholder URL in feed-image path")
                            log.info("[W%d] ✅ Image ready (feed image path)", s.worker_id)
                            return img_url
                    except Exception:
                        pass
                try:
                    cur_count = len(await page.query_selector_all("img.MageMedia-image"))
                    if cur_count <= pre_count:
                        log.info("[W%d] ✅ Generation finished (feed image path)", s.worker_id)
                        break
                except Exception:
                    break
            else:
                try:
                    is_visible = await page.locator(active_indicator).is_visible()
                except Exception:
                    is_visible = False

                if not is_visible:
                    indicator_duration = (
                        time.time() - indicator_appeared_at
                        if indicator_appeared_at is not None else 99.0
                    )
                    if indicator_duration < 2.0:
                        log.warning(
                            "[W%d] ⚠️ Indicator '%s' vanished in %.2fs — possible silent rejection or false-positive"
                            " (keeping wait alive until timeout)",
                            s.worker_id, active_indicator, indicator_duration,
                        )
                        _indicator_short_lived = True
                        active_indicator = "__poll_output__"
                        continue
                    else:
                        log.info(
                            "[W%d] ✅ Generation finished (indicator gone: %s, duration=%.1fs)",
                            s.worker_id, active_indicator, indicator_duration,
                        )
                    break
            
            # Log progress every ~30s so long gens don't look stuck
            max_wait_attempts += 1
            elapsed = time.time() - start_time
            if max_wait_attempts % 10 == 0:
                log.debug("[W%d] ⏳ Generation still in progress (%.1fs elapsed, indicator still visible)", 
                         s.worker_id, elapsed)
            elif elapsed >= 30 and max_wait_attempts % 5 == 0:
                log.info("[W%d] ⏳ Still generating… %.0fs elapsed", s.worker_id, elapsed)
            
            await asyncio.sleep(poll_interval)
        else:
            raise PWTimeout("Generation timed out")
    except PWTimeout as e:
        log.error("[W%d] ❌ Generation timeout after %ds: %s", s.worker_id, timeout_s, e)
        raise RuntimeError(f"Generation timed out after {timeout_s}s — prompt may be too complex or server overloaded")

    await page.wait_for_timeout(400 if not video else PAGE_SETTLE_MS)
    try:
        await _read_gems(s, page)
    except Exception as e:
        log.warning("[W%d] ⚠️ Could not read gems: %s (non-critical)", s.worker_id, e)

    if video:
        best_url = await _resolve_best_video_output_url(
            page, s.worker_id, pre_urls=pre_video_urls,
        )
        if best_url:
            return best_url
        raise RuntimeError("No result video found in DOM — video may still be loading or generation failed silently")

    s.last_wait_ctx = {
        "pre_count": pre_count,
        "pre_urls": pre_image_urls,
        "exclude_urls": exclude_urls,
    }
    # If the indicator was suspiciously short-lived, poll longer — the CDN image may lag behind
    settle_rounds = 30 if _indicator_short_lived else 12
    if _indicator_short_lived:
        log.info(
            "[W%d] 🔄 Short-lived indicator — extended DOM settle (%d rounds)",
            s.worker_id, settle_rounds,
        )
        await page.wait_for_timeout(800)  # Extra settle before scanning

    best_url = await _resolve_image_output_with_settle(
        page, pre_count, s.worker_id,
        pre_urls=pre_image_urls,
        exclude_urls=exclude_urls,
        max_rounds=settle_rounds,
    )
    if best_url:
        return best_url

    if _indicator_short_lived:
        raise RuntimeError(
            "No result image found in DOM — indicator vanished instantly, likely a silent rejection or content block"
        )
    raise RuntimeError("No result image found in DOM — image may still be loading or generation failed silently")



# ── Download via httpx ────────────────────────────────────────────────────────

# Known content-moderation placeholders served by Mage when a generation is blocked
_MAGE_PLACEHOLDER_URL = "https://cdn3.mage.space/placeholder.jpg"
_MAGE_PLACEHOLDER_MAX_BYTES = 5_000   # placeholder is ~1119 bytes; real images are always larger

@async_timeout(60.0)
async def _download_image(url: str, retries: int = 3) -> str | None:
    """Download image with retry + exponential backoff.

    Raises ContentForbiddenError if the URL is a Mage moderation placeholder.
    """
    if _is_moderation_placeholder_url(url):
        raise ContentForbiddenError(
            "Mage returned moderation placeholder — content was blocked"
        )

    if not url or not isinstance(url, str):
        raise ValueError(f"Invalid URL for download: {url}")

    last_exc = None
    for attempt in range(retries):
        try:
            log.debug("🔽 Download attempt %d/%d: %s …", attempt + 1, retries, url[:100])
            
            async with httpx.AsyncClient(
                timeout=30,
                follow_redirects=True,
                headers={"Referer": "https://www.mage.space/"}
            ) as client:
                resp = await client.get(url)
                resp.raise_for_status()
                
                # Detect tiny placeholder payloads even if URL was rewritten by a CDN redirect
                if len(resp.content) <= _MAGE_PLACEHOLDER_MAX_BYTES:
                    raise ContentForbiddenError(
                        f"Downloaded image is suspiciously small ({len(resp.content)} bytes) — "
                        "likely a moderation placeholder"
                    )
                
                ext = ".jpg" if "jpg" in url.lower() else ".png"
                tmp = tempfile.NamedTemporaryFile(suffix=ext, delete=False, dir=DATA_DIR)
                tmp.write(resp.content)
                tmp.close()
                
                # Validate that the file was actually written
                if not os.path.exists(tmp.name) or os.path.getsize(tmp.name) == 0:
                    raise RuntimeError(f"File write failed or empty: {tmp.name}")
                
                nbytes = len(resp.content)
                log.info("✅ Downloaded %d bytes (%.1f KB) → %s", nbytes, nbytes / 1024, tmp.name)
                return tmp.name
                
        except ContentForbiddenError:
            raise   # propagate moderation blocks immediately (no retry)
        except RuntimeError:
            raise
        except httpx.HTTPStatusError as e:
            log.warning("HTTP error %d on attempt %d/%d: %s", e.response.status_code, attempt + 1, retries, e)
            last_exc = e
        except httpx.TimeoutException as e:
            log.warning("Timeout on attempt %d/%d: %s", attempt + 1, retries, e)
            last_exc = e
        except Exception as e:
            log.warning("Download attempt %d/%d failed: %s", attempt + 1, retries, e)
            last_exc = e
        
        if attempt < retries - 1:
            wait = 2 ** attempt  # 1s, 2s, 4s backoff
            log.debug("⏳ Retrying download in %ds…", wait)
            await asyncio.sleep(wait)
    
    raise RuntimeError(f"Download failed after {retries} attempts: {last_exc}")


async def _download_video(url: str, retries: int = 3) -> str | None:
    """Download video with retry + exponential backoff."""
    if not url or not isinstance(url, str):
        raise ValueError(f"Invalid URL for download: {url}")

    last_exc = None
    for attempt in range(retries):
        try:
            log.debug("🔽 Video download attempt %d/%d: %s …", attempt + 1, retries, url[:100])

            async with httpx.AsyncClient(
                timeout=90,
                follow_redirects=True,
                headers={"Referer": "https://www.mage.space/"}
            ) as client:
                resp = await client.get(url)
                resp.raise_for_status()

                if len(resp.content) < 10_000:
                    raise RuntimeError(
                        f"Downloaded video is suspiciously small ({len(resp.content)} bytes)"
                    )

                ext = ".mp4" if ".mp4" in url.lower() else ".mp4"
                tmp = tempfile.NamedTemporaryFile(suffix=ext, delete=False, dir=DATA_DIR)
                tmp.write(resp.content)
                tmp.close()

                if not os.path.exists(tmp.name) or os.path.getsize(tmp.name) == 0:
                    raise RuntimeError(f"File write failed or empty: {tmp.name}")

                nbytes = len(resp.content)
                log.info("✅ Downloaded video %d bytes (%.1f KB) → %s", nbytes, nbytes / 1024, tmp.name)
                return tmp.name

        except RuntimeError:
            raise
        except httpx.HTTPStatusError as e:
            log.warning("HTTP error %d on video attempt %d/%d: %s", e.response.status_code, attempt + 1, retries, e)
            last_exc = e
        except httpx.TimeoutException as e:
            log.warning("Timeout on video attempt %d/%d: %s", attempt + 1, retries, e)
            last_exc = e
        except Exception as e:
            log.warning("Video download attempt %d/%d failed: %s", attempt + 1, retries, e)
            last_exc = e

        if attempt < retries - 1:
            wait = 2 ** attempt
            log.debug("⏳ Retrying video download in %ds…", wait)
            await asyncio.sleep(wait)

    raise RuntimeError(f"Video download failed after {retries} attempts: {last_exc}")


# ── Full generation pipeline ──────────────────────────────────────────────────

async def _clear_workspace(page: Page):
    """Click Advanced -> Clear to clear previous reference images/inputs."""
    try:
        log.info("🧹 Clearing workspace before new generation...")

        await _dismiss_blocking_overlays(page)

        # 1) Click 'Advanced' (matches exact tag/href provided by user)
        try:
            advanced_btn = page.locator("a[href='/advanced'], a:has-text('Advanced')").first
            await stable_click(page, advanced_btn, timeout_ms=8000)
            log.debug("  ✅ Clicked 'Advanced' button")
        except Exception as e:
            log.warning("  ⚠️ Advanced button not found, proceeding anyway: %s", e)

        # 2) Wait for /advanced page to load (non-blocking)
        try:
            await page.wait_for_url("**/advanced", timeout=5000)
            log.debug("  ℹ️ Navigated to /advanced")
        except Exception:
            log.debug("  ⚠️ /advanced URL not confirmed, retrying with force navigation")
            try:
                await page.goto("https://www.mage.space/advanced", wait_until="domcontentloaded", timeout=10000)
            except Exception as e2:
                log.warning("  ⚠️ Could not navigate to /advanced: %s", e2)
        
        await page.wait_for_timeout(250)

        # 3) Click 'Clear' (matches exact tag/label provided by user)
        clear_found = False
        clear_selectors = [
            "span.mage-Button-label:has-text('Clear')",
            "button:has-text('Clear')",
            "[role='button']:has-text('Clear')",
        ]
        
        for sel in clear_selectors:
            try:
                clear_btn = page.locator(sel).first
                if await clear_btn.count() > 0:
                    await stable_click(page, clear_btn, timeout_ms=8000)
                    log.debug("  ✅ Clicked 'Clear' button via selector: %s", sel)
                    clear_found = True
                    break
            except Exception as e:
                log.debug("  Clear selector '%s' failed: %s", sel, e)
        
        if not clear_found:
            try:
                await stable_click(page, page.get_by_text("Clear", exact=True).first, timeout_ms=5000)
                log.debug("  ✅ Clicked 'Clear' button via text fallback")
                clear_found = True
            except Exception as e:
                log.warning("  ⚠️ 'Clear' button not found (non-critical): %s", e)
        
        await page.wait_for_timeout(250)

        # 4) Navigate back to home page to prepare for the generation
        try:
            await page.goto("https://www.mage.space/explore", wait_until="domcontentloaded", timeout=10000)
            log.debug("  ✅ Returned to /explore")
        except Exception as e:
            log.warning("  ⚠️ Could not return to /explore: %s (trying keyboard escape)", e)
            try:
                await page.keyboard.press("Escape")
                await page.wait_for_timeout(200)
            except Exception:
                pass

        log.info("✅ Workspace cleared successfully")

    except Exception as e:
        log.error("❌ Workspace clear failed: %s", e)
        raise


async def _generate(s: WorkerSession, page: Page, prompt: str, image_path: str | None, aspect: str, app: Optional[Application] = None, job: Optional[Job] = None) -> str | None:
    if not s.page_prepared_for_job:
        await _light_prepare_page(page, s.worker_id)
    s.reference_cdn_urls = set()

    # Validate inputs
    if not prompt or not isinstance(prompt, str) or not prompt.strip():
        raise ValueError(f"Invalid prompt: empty or wrong type ({type(prompt)})")
    aspect = _resolve_job_aspect(aspect, image_path, job)
    if image_path is not None and not isinstance(image_path, str):
        raise ValueError(f"Invalid image_path type: {type(image_path)}")
    reference_paths = _job_reference_image_paths(job, image_path)

    # Reference aspect + black borders are applied in got_image() before the job is queued.

    use_guava15 = job and job.pipeline == "guava15"
    if use_guava15:
        if await _guava_15_is_selected(page, s.worker_id):
            log.info("[W%d] ⚡ Guava 1.5 already selected — skipping model picker", s.worker_id)
        else:
            await update_status(app, job, "✨ Selecting enhanced model...")
            await _select_guava_15_fast_mode(page, s.worker_id)
            if not await _guava_15_is_selected(page, s.worker_id):
                raise RuntimeError(f"{GUAVA_15_DISPLAY} not active before generation")
            await update_status(app, job, "✅ Model ready")
        await _ensure_guava_15_play_workspace(page, s.worker_id)
    elif _bulk_continuing(s, job) and await _guava_is_selected(page, s.worker_id):
        log.info("[W%d] ⚡ Bulk continue — Guava V1 ready", s.worker_id)
    elif s.live_prewarmed_guava or await _guava_is_selected(page, s.worker_id):
        log.info("[W%d] ⚡ Guava already selected — skipping model picker", s.worker_id)
    else:
        await update_status(app, job, "⚡ Selecting model...")
        await _select_guava_pro_fast(page, s.worker_id)
        if not await _guava_is_selected(page, s.worker_id):
            raise RuntimeError("Guava Pro Fast Mode not active before generation")
        await update_status(app, job, "✅ Model ready")
    if s.stage_timer:
        s.stage_timer.mark("model_ready")

    await update_status(app, job, "📊 Setting aspect ratio...")
    log.info("[W%d] 📊 Setting aspect ratio to %s...", s.worker_id, aspect)
    if _bulk_continuing(s, job) and s.last_bulk_aspect == aspect:
        log.info(
            "[W%d] 📐 Skipping aspect UI (bulk continue, unchanged %s)",
            s.worker_id,
            aspect,
        )
    elif _reference_aspect_letterboxed(reference_paths, image_path, job):
        log.info(
            "[W%d] 📐 Skipping aspect UI (reference pre-letterboxed to %s)",
            s.worker_id,
            aspect,
        )
    else:
        try:
            await _set_aspect(page, aspect, s.worker_id)
            if job and job.is_bulk:
                s.last_bulk_aspect = aspect
        except Exception as e:
            log.error("❌ Aspect ratio setup failed: %s", e)
            raise

    # 2) Upload reference image if present
    if reference_paths:
        try:
            if len(reference_paths) > 1:
                log.info(
                    "[W%d] 📎 Uploading %d reference images (aspect=%s from first ref)",
                    s.worker_id, len(reference_paths), aspect,
                )
            await update_status(app, job, "📤 Uploading reference...")
            for idx, ref_path in enumerate(reference_paths):
                if len(reference_paths) > 1:
                    await update_status(
                        app, job,
                        f"📤 Uploading reference {idx + 1}/{len(reference_paths)}...",
                    )
                await _upload_image(
                    page,
                    ref_path,
                    s.worker_id,
                    job=job,
                    s=s,
                    clear_existing=(idx == 0),
                )
            if _multi_reference_upload(reference_paths):
                await _ensure_reference_mode_chip(page, s.worker_id)
                await page.wait_for_timeout(400)
            await update_status(app, job, "📤 Reference uploaded ✅")
            if not _multi_reference_upload(reference_paths):
                await _assert_reference_attached(page, s.worker_id)
            await _capture_reference_cdn_urls(page, s)
        except Exception as e:
            if job and job.is_bulk:
                s.bulk_force_fresh = True
            log.error("❌ Image upload failed: %s", e)
            raise
    if s.stage_timer:
        s.stage_timer.mark("upload")

    if INJECT_GENERATION_PARAMS:
        try:
            await inject_generation_params(page)
        except Exception as e:
            log.warning("⚠️ Generation params injection failed (non-critical): %s", e)

    try:
        await update_status(app, job, "✍️ Injecting prompt...")
        await _paste_prompt(page, prompt, s.worker_id, job=job)
        await update_status(app, job, "✍️ Prompt ready")
    except Exception as e:
        log.error("❌ Prompt paste failed: %s", e)
        raise

    gems_before = await _read_gems_remaining(page)
    if use_guava15:
        await _check_guava_15_gems(page, s.worker_id)

    if reference_paths and not _multi_reference_upload(reference_paths):
        await _ensure_reference_after_prompt(
            page, s.worker_id, reference_paths, video=False, posing=False
        )
        await _capture_reference_cdn_urls(page, s)

    multi_ref = _multi_reference_upload(reference_paths)
    try:
        await update_status(app, job, "🎨 Generating... (~30s)")
        if multi_ref:
            await _ensure_reference_mode_chip(page, s.worker_id)
            await page.wait_for_timeout(400)
        await _assert_generation_ready(
            page,
            s.worker_id,
            needs_reference=bool(reference_paths) and not multi_ref,
            trust_send=multi_ref,
        )
        await _hit_send(page, s, promptbar_only=True)

        await _maybe_refill_pool_after_send(job, reason="send")
        if s.stage_timer:
            s.stage_timer.mark("send")

        await update_status(app, job, "⏳ AI generating...")
        # Pass the PREVIOUS bulk result URL so _resolve_best_output_url skips it;
        # then immediately clear it so the next generation doesn't carry stale state.
        exclude = s.last_bulk_output_url if (job and job.is_bulk) else None
        s.last_bulk_output_url = None  # clear before wait so error paths don't reuse it
        url = await _wait_for_result(
            s, page, timeout_s=_generation_timeout_for_job(job),
            posing=use_guava15,
            gems_before=gems_before,
            exclude_url=exclude,
            job=job,
        )
        if job and job.is_bulk and url:
            s.last_bulk_output_url = url  # store for the NEXT bulk image
        s.last_output_cdn_url = url
        if s.stage_timer:
            s.stage_timer.mark("generate_wait")

        await update_status(app, job, "📥 Downloading generated result...")
        log.info("[W%d] 📥 Downloading result from CDN...", s.worker_id)
        wait_ctx = getattr(s, "last_wait_ctx", None) or {}
        result = await _download_generation_result(
            s, page, url, reference_paths,
            pre_count=wait_ctx.get("pre_count", 0),
            pre_urls=wait_ctx.get("pre_urls"),
            exclude_urls=wait_ctx.get("exclude_urls"),
        )
        if s.stage_timer:
            s.stage_timer.mark("download")

        await update_status(app, job, "✅ Generation complete! Processing output...")
        log.info("[W%d] ✅ Generation and download successful", s.worker_id)
    except Exception as e:
        log.error("❌ Generation/download failed: %s", e)
        raise

    return result


async def _generate_posing(s: WorkerSession, page: Page, prompt: str, image_path: str | None, aspect: str, app: Optional[Application] = None, job: Optional[Job] = None) -> str | None:
    """Grok posing — same upload/send flow as Guava on the Grok play workspace."""
    s.reference_cdn_urls = set()
    if not prompt or not isinstance(prompt, str) or not prompt.strip():
        raise ValueError(f"Invalid prompt: empty or wrong type ({type(prompt)})")
    aspect = _resolve_job_aspect(aspect, image_path, job)
    if image_path is not None and not isinstance(image_path, str):
        raise ValueError(f"Invalid image_path type: {type(image_path)}")
    reference_paths = _job_reference_image_paths(job, image_path)

    grok_bulk_ready = (
        _bulk_continuing(s, job)
        and await _grok_is_selected(page, s.worker_id)
    )
    if grok_bulk_ready:
        log.info("[W%d] ⚡ Bulk continue — Grok ready", s.worker_id)
    else:
        if not s.page_prepared_for_job:
            await _light_prepare_page(page, s.worker_id)
        await update_status(app, job, "🧘 Selecting Grok Image Quality...")
        await _ensure_posing_model_ready(page, s.worker_id)
        await update_status(app, job, "🧘 Grok model selected ✅")
    if s.stage_timer:
        s.stage_timer.mark("model_ready")

    # Set Aspect Ratio
    await update_status(app, job, "📊 Setting aspect ratio...")
    log.info("[W%d] 📊 Setting aspect ratio to %s...", s.worker_id, aspect)
    if _bulk_continuing(s, job) and s.last_bulk_aspect == aspect:
        log.info("[W%d] 📐 Skipping aspect UI (bulk continue, unchanged %s)", s.worker_id, aspect)
    elif _reference_aspect_letterboxed(reference_paths, image_path, job):
        log.info("[W%d] 📐 Skipping aspect UI (reference pre-letterboxed to %s)", s.worker_id, aspect)
    else:
        try:
            await _set_aspect(page, aspect, s.worker_id)
            if job and job.is_bulk:
                s.last_bulk_aspect = aspect
        except Exception as e:
            log.error("❌ Aspect ratio setup failed: %s", e)
            raise

    if reference_paths:
        try:
            await update_status(app, job, "📤 Uploading reference...")
            for idx, ref_path in enumerate(reference_paths):
                if len(reference_paths) > 1:
                    await update_status(
                        app, job,
                        f"📤 Uploading reference {idx + 1}/{len(reference_paths)}...",
                    )
                await _upload_image_posing(
                    page,
                    ref_path,
                    s.worker_id,
                    job=job,
                    s=s,
                    clear_existing=(idx == 0),
                )
            if _multi_reference_upload(reference_paths):
                await _ensure_grok_reference_mode_selected(page, s.worker_id)
                await page.wait_for_timeout(400)
            await update_status(app, job, "📤 Reference uploaded ✅")
            if not _multi_reference_upload(reference_paths):
                await _assert_reference_attached(page, s.worker_id)
            await _capture_reference_cdn_urls(page, s)
        except Exception as e:
            if job and job.is_bulk:
                s.bulk_force_fresh = True
            log.error("❌ Image upload failed: %s", e)
            raise
    if s.stage_timer:
        s.stage_timer.mark("upload")

    try:
        await update_status(app, job, "✍️ Injecting prompt...")
        await _paste_prompt(page, prompt, s.worker_id, job=job)
        await update_status(app, job, "✍️ Prompt ready")
    except Exception as e:
        log.error("❌ Prompt paste failed: %s", e)
        raise

    if reference_paths and not _multi_reference_upload(reference_paths):
        await _ensure_reference_after_prompt(
            page, s.worker_id, reference_paths, video=False, posing=True
        )
        await _capture_reference_cdn_urls(page, s)

    gems_before = await _read_gems_remaining(page)
    await _check_grok_gems(page, s.worker_id)

    multi_ref = _multi_reference_upload(reference_paths)
    try:
        await update_status(app, job, "🎨 Generating... (~30s)")
        await _focus_prompt_editor(page, s.worker_id)
        if multi_ref:
            await _ensure_grok_reference_mode_selected(page, s.worker_id)
            await _ensure_reference_mode_chip(page, s.worker_id)
            await page.wait_for_timeout(400)
        await _assert_generation_ready(
            page,
            s.worker_id,
            needs_reference=bool(reference_paths) and not multi_ref,
            posing=True,
            trust_send=multi_ref,
        )
        await _hit_send(page, s, promptbar_only=True)

        await _maybe_refill_pool_after_send(job, reason="send")
        if s.stage_timer:
            s.stage_timer.mark("send")

        await update_status(app, job, "⏳ AI generating...")
        exclude = s.last_bulk_output_url if (job and job.is_bulk) else None
        s.last_bulk_output_url = None
        url = await _wait_for_result(
            s, page, timeout_s=_generation_timeout_for_job(job), posing=True,
            gems_before=gems_before,
            exclude_url=exclude,
            job=job,
        )
        if job and job.is_bulk and url:
            s.last_bulk_output_url = url
        s.last_output_cdn_url = url
        if s.stage_timer:
            s.stage_timer.mark("generate_wait")

        await update_status(app, job, "📥 Downloading generated result...")
        log.info("[W%d] 📥 Downloading posing result from CDN...", s.worker_id)
        wait_ctx = getattr(s, "last_wait_ctx", None) or {}
        result = await _download_generation_result(
            s, page, url, reference_paths,
            pre_count=wait_ctx.get("pre_count", 0),
            pre_urls=wait_ctx.get("pre_urls"),
            exclude_urls=wait_ctx.get("exclude_urls"),
        )
        if s.stage_timer:
            s.stage_timer.mark("download")

        await update_status(app, job, "✅ Generation complete! Processing output...")
        log.info("[W%d] ✅ Posing generation and download successful", s.worker_id)
    except Exception as e:
        log.error("❌ Posing generation/download failed: %s", e)
        raise

    return result


async def _generate_gpt_image(s: WorkerSession, page: Page, prompt: str, image_path: str | None, aspect: str, app: Optional[Application] = None, job: Optional[Job] = None) -> str | None:
    """GPT Image 2 — Grok-style model selection + reference upload, with aspect ratio."""
    s.reference_cdn_urls = set()
    if not prompt or not isinstance(prompt, str) or not prompt.strip():
        raise ValueError(f"Invalid prompt: empty or wrong type ({type(prompt)})")
    aspect = _resolve_job_aspect(aspect, image_path, job)
    if image_path is not None and not isinstance(image_path, str):
        raise ValueError(f"Invalid image_path type: {type(image_path)}")
    reference_paths = _job_reference_image_paths(job, image_path)

    gpt_bulk_ready = (
        _bulk_continuing(s, job)
        and await _gpt_image_is_selected(page, s.worker_id)
    )
    if gpt_bulk_ready:
        log.info("[W%d] ⚡ GPT Image 2 already active — skipping model navigation", s.worker_id)
    else:
        if not s.page_prepared_for_job:
            await _light_prepare_page(page, s.worker_id)
        await update_status(app, job, "🎨 Selecting GPT Image 2 Fast Mode...")
        await _ensure_gpt_image_model_ready(page, s.worker_id)
        await update_status(app, job, "🎨 GPT Image 2 selected ✅")
    if s.stage_timer:
        s.stage_timer.mark("model_ready")

    # Set Aspect Ratio
    await update_status(app, job, "📊 Setting aspect ratio...")
    log.info("[W%d] 📊 Setting aspect ratio to %s...", s.worker_id, aspect)
    if _bulk_continuing(s, job) and s.last_bulk_aspect == aspect:
        log.info("[W%d] 📐 Skipping aspect UI (bulk continue, unchanged %s)", s.worker_id, aspect)
    elif _reference_aspect_letterboxed(reference_paths, image_path, job):
        log.info("[W%d] 📐 Skipping aspect UI (reference pre-letterboxed to %s)", s.worker_id, aspect)
    else:
        try:
            await _set_aspect(page, aspect, s.worker_id)
            if job and job.is_bulk:
                s.last_bulk_aspect = aspect
        except Exception as e:
            log.error("❌ Aspect ratio setup failed: %s", e)
            raise

    # Upload reference
    if reference_paths:
        try:
            if len(reference_paths) > 1:
                log.info(
                    "[W%d] 📎 Uploading %d reference images for GPT Image 2",
                    s.worker_id, len(reference_paths),
                )
            await update_status(app, job, "📤 Uploading reference...")
            for idx, ref_path in enumerate(reference_paths):
                if len(reference_paths) > 1:
                    await update_status(
                        app, job, f"📤 Uploading reference {idx + 1}/{len(reference_paths)}...",
                    )
                await _upload_image_posing(
                    page,
                    ref_path,
                    s.worker_id,
                    job=job,
                    s=s,
                    clear_existing=(idx == 0),
                    skip_create_with_this=gpt_bulk_ready,
                )
            if _multi_reference_upload(reference_paths):
                await _ensure_reference_mode_chip(page, s.worker_id)
                await page.wait_for_timeout(400)
            await update_status(app, job, "📤 Reference uploaded ✅")
            if not _multi_reference_upload(reference_paths):
                await _assert_reference_attached(page, s.worker_id)
            await _capture_reference_cdn_urls(page, s)
        except Exception as e:
            if job and job.is_bulk:
                s.bulk_force_fresh = True
            log.error("❌ GPT Image 2 reference upload failed: %s", e)
            raise
    if s.stage_timer:
        s.stage_timer.mark("upload")

    if INJECT_GENERATION_PARAMS:
        try:
            await inject_generation_params(page)
        except Exception as e:
            log.warning("⚠️ Generation params injection failed (non-critical): %s", e)

    try:
        await update_status(app, job, "✍️ Injecting prompt...")
        await _paste_prompt(page, prompt, s.worker_id, job=job)
        await update_status(app, job, "✍️ Prompt ready")
    except Exception as e:
        log.error("❌ Prompt paste failed: %s", e)
        raise

    gems_before = await _read_gems_remaining(page)

    if reference_paths and not _multi_reference_upload(reference_paths):
        await _ensure_reference_after_prompt(
            page, s.worker_id, reference_paths, video=False, posing=True
        )
        await _capture_reference_cdn_urls(page, s)

    multi_ref = _multi_reference_upload(reference_paths)
    try:
        await update_status(app, job, "🎨 Generating GPT Image 2... (~10s)")
        if multi_ref:
            await _ensure_reference_mode_chip(page, s.worker_id)
            await page.wait_for_timeout(400)
        await _assert_generation_ready(
            page,
            s.worker_id,
            needs_reference=bool(reference_paths) and not multi_ref,
            posing=True,
            trust_send=multi_ref,
        )
        await _hit_send(page, s, promptbar_only=True)

        await _maybe_refill_pool_after_send(job, reason="send")
        if s.stage_timer:
            s.stage_timer.mark("send")

        await update_status(app, job, "⏳ AI generating...")
        exclude = s.last_bulk_output_url if (job and job.is_bulk) else None
        s.last_bulk_output_url = None
        url = await _wait_for_result(
            s, page, timeout_s=_generation_timeout_for_job(job), posing=True,
            gems_before=gems_before,
            exclude_url=exclude,
            job=job,
        )
        if job and job.is_bulk and url:
            s.last_bulk_output_url = url
        s.last_output_cdn_url = url
        if s.stage_timer:
            s.stage_timer.mark("generate_wait")

        await update_status(app, job, "📥 Downloading generated result...")
        log.info("[W%d] 📥 Downloading GPT Image 2 result from CDN...", s.worker_id)
        wait_ctx = getattr(s, "last_wait_ctx", None) or {}
        result = await _download_generation_result(
            s, page, url, reference_paths,
            pre_count=wait_ctx.get("pre_count", 0),
            pre_urls=wait_ctx.get("pre_urls"),
            exclude_urls=wait_ctx.get("exclude_urls"),
        )
        if s.stage_timer:
            s.stage_timer.mark("download")

        await update_status(app, job, "✅ Generation complete! Processing output...")
        log.info("[W%d] ✅ GPT Image 2 generation and download successful", s.worker_id)
    except Exception as e:
        log.error("❌ GPT Image 2 generation/download failed: %s", e)
        raise

    return result


async def _hit_send_video(page: Page, s: "WorkerSession") -> None:
    """Send Kiwi video — promptbar-scoped send on Video tab."""
    await _ensure_video_tab_selected(page, s.worker_id)
    await _focus_prompt_editor(page, s.worker_id)
    await _ensure_reference_mode_chip(page, s.worker_id)
    await _hit_send(page, s, promptbar_only=True, video=True)


@async_timeout(300.0)
async def _generate_video(
    s: WorkerSession,
    page: Page,
    prompt: str,
    image_path: str | None,
    aspect: str,
    app: Optional[Application] = None,
    job: Optional[Job] = None,
) -> str | None:
    """Kiwi video — same upload/send rhythm as Guava on the Kiwi play workspace."""
    s.reference_cdn_urls = set()
    if not prompt or not isinstance(prompt, str) or not prompt.strip():
        raise ValueError(f"Invalid prompt: empty or wrong type ({type(prompt)})")
    aspect = _resolve_job_aspect(aspect, image_path, job)
    if image_path is not None and not isinstance(image_path, str):
        raise ValueError(f"Invalid image_path type: {type(image_path)}")

    reference_paths = _job_reference_image_paths(job, image_path)

    kiwi_ready = (
        await _kiwi_is_selected(page, s.worker_id)
    )
    if kiwi_ready:
        log.info("[W%d] ⚡ Kiwi already active — skipping model navigation", s.worker_id)
    else:
        if not s.page_prepared_for_job:
            await _light_prepare_page(page, s.worker_id)
        await update_status(app, job, "🎬 Selecting Kiwi Video Fast Mode...")
        await _ensure_video_model_ready(page, s.worker_id)
        await update_status(app, job, "🎬 Kiwi model selected ✅")
    if s.stage_timer:
        s.stage_timer.mark("model_ready")

    if reference_paths:
        try:
            await update_status(app, job, "📤 Uploading reference...")
            for idx, ref_path in enumerate(reference_paths):
                if len(reference_paths) > 1:
                    await update_status(
                        app, job,
                        f"📤 Uploading reference {idx + 1}/{len(reference_paths)}...",
                    )
                await _upload_image_video(
                    page,
                    ref_path,
                    s.worker_id,
                    clear_existing=(idx == 0),
                )
            await update_status(app, job, "📤 Reference uploaded ✅")
            if not _multi_reference_upload(reference_paths):
                await _assert_reference_attached(page, s.worker_id)
            await _capture_reference_cdn_urls(page, s)
        except Exception as e:
            log.error("❌ Image upload failed: %s", e)
            raise
    if s.stage_timer:
        s.stage_timer.mark("upload")

    try:
        await update_status(app, job, "✍️ Injecting prompt...")
        await _paste_prompt(page, prompt, s.worker_id, job=job, prompt_mode="video")
        await update_status(app, job, "✍️ Prompt ready")
    except Exception as e:
        log.error("❌ Prompt paste failed: %s", e)
        raise

    if reference_paths and not _multi_reference_upload(reference_paths):
        await _ensure_reference_after_prompt(
            page, s.worker_id, reference_paths, video=True, posing=False
        )
        await _capture_reference_cdn_urls(page, s)

    gems_before = await _read_gems_remaining(page)
    await _check_kiwi_gems(page, s.worker_id)

    multi_ref = _multi_reference_upload(reference_paths)
    try:
        await update_status(app, job, "🎬 Generating video... (~1-2 min)")
        if multi_ref:
            await _ensure_reference_mode_chip(page, s.worker_id)
            await page.wait_for_timeout(400)
        await _assert_generation_ready(
            page,
            s.worker_id,
            needs_reference=bool(reference_paths) and not multi_ref,
            video=True,
            trust_send=multi_ref,
        )
        await _hit_send_video(page, s)

        await _maybe_refill_pool_after_send(job, reason="send")
        if s.stage_timer:
            s.stage_timer.mark("send")

        await update_status(app, job, "⏳ AI generating video...")
        url = await _wait_for_result(
            s,
            page,
            timeout_s=VIDEO_GENERATION_TIMEOUT,
            posing=True,
            video=True,
            gems_before=gems_before,
            video_image_paths=reference_paths,
            video_prompt=prompt,
            job=job,
        )
        s.last_output_cdn_url = url
        if s.stage_timer:
            s.stage_timer.mark("generate_wait")

        await update_status(app, job, "📥 Downloading generated video...")
        log.info("[W%d] 📥 Downloading video result from CDN...", s.worker_id)
        result = await _download_video(url)
        if s.stage_timer:
            s.stage_timer.mark("download")

        await update_status(app, job, "✅ Video generation complete!")
        log.info("[W%d] ✅ Video generation and download successful", s.worker_id)
    except Exception as e:
        log.error("❌ Video generation/download failed: %s", e)
        raise

    return result


async def run_pipeline(prompt: str, image_path: str | None, aspect: str, s: WorkerSession, app: Optional[Application] = None, job: Optional[Job] = None) -> str | None:
    """Run pipeline with smart retry, timeout protection, and resilience.
    Every attempt uses a fresh account—on any error the session is fully closed and a new one is created."""
    
    # Validate inputs before starting
    if not prompt or not isinstance(prompt, str) or not prompt.strip():
        raise ValueError(f"Invalid prompt: {type(prompt)} / len={len(prompt) if isinstance(prompt, str) else 'N/A'}")
    aspect = _resolve_job_aspect(aspect, image_path, job)
    if image_path is not None and (not isinstance(image_path, str) or not os.path.exists(image_path)):
        raise ValueError(f"Invalid image path: {image_path}")
    _validate_reference_image_paths(job, image_path)
    
    max_attempts = PIPELINE_MAX_ATTEMPTS
    for attempt in range(max_attempts):
        page = None
        last_error = ""
        if attempt > 0:
            s.reuse_count = 0
            s.bulk_force_fresh = False
        try:
            log.info("[W%d] 🚀 Pipeline attempt %d/%d", s.worker_id, attempt + 1, max_attempts)
            page = await asyncio.wait_for(_get_mage_page(s, app, job), timeout=float(SETUP_TIMEOUT))

            upload_budget = _pipeline_upload_budget(job, image_path)
            result = await asyncio.wait_for(
                _generate(s, page, prompt, image_path, aspect, app, job),
                timeout=float(_generation_timeout_for_job(job) + 30 + upload_budget),
            )
            
            log.info("[W%d] ✅ Pipeline succeeded on attempt %d/%d", s.worker_id, attempt + 1, max_attempts)
            return result
            
        except asyncio.TimeoutError as exc:
            last_error = str(exc)
            log.warning("[W%d] ⏱️ Timeout on attempt %d/%d (page setup or generation)", s.worker_id, attempt + 1, max_attempts)
            
        except RuntimeError as exc:
            last_error = str(exc)
            msg = str(exc).lower()
            if _runtime_error_is_moderation(msg):
                log.warning("[W%d] 🛑 Moderation block (no retry): %s", s.worker_id, exc)
                raise ContentForbiddenError(str(exc)) from exc
            log.warning("[W%d] ⚠️ Known error on attempt %d/%d: %s", s.worker_id, attempt + 1, max_attempts, exc)
            
        except ContentForbiddenError:
            raise
            
        except ValueError as exc:
            # Input validation errors - don't retry, fail immediately
            log.error("[W%d] ❌ Validation error (won't retry): %s", s.worker_id, exc)
            raise

        except asyncio.CancelledError:
            # User pressed /cancel — propagate cleanly, no retry
            raise

        except Exception as exc:
            last_error = str(exc)
            # Unknown errors - log full trace
            log.error("[W%d] ❌ Unexpected error on attempt %d/%d: %s\n%s", 
                     s.worker_id, attempt + 1, max_attempts, exc, traceback.format_exc())
        
        if attempt < max_attempts - 1:
            await _handle_pipeline_retry_cleanup(s, page, last_error=last_error)
            base_wait = _pipeline_retry_delay(attempt, last_error)
            log.info("[W%d] ⏳ Retrying in %.1fs…", s.worker_id, base_wait)
            await asyncio.sleep(base_wait)
        else:
            log.error("[W%d] ❌ All %d attempts failed", s.worker_id, max_attempts)
            _finalize_worker_account(s, success=False, error_msg=last_error)
            # Close session after all attempts failed
            try:
                await asyncio.wait_for(_teardown_browser_stack(s), timeout=10.0)
            except Exception as e:
                log.warning("[W%d] ⚠️ Error tearing down session after failure: %s", s.worker_id, e)
            s.live_prewarmed_guava = False
            s.email = None
            s.gems = 0
            raise RuntimeError(f"Pipeline failed after {max_attempts} attempts")
    
    return None


async def run_posing_pipeline(prompt: str, image_path: str | None, aspect: str, s: WorkerSession, app: Optional[Application] = None, job: Optional[Job] = None) -> str | None:
    """Run Grok posing pipeline — same pasting/sending as Guava, with aspect ratio."""
    if not prompt or not isinstance(prompt, str) or not prompt.strip():
        raise ValueError(f"Invalid prompt: {type(prompt)} / len={len(prompt) if isinstance(prompt, str) else 'N/A'}")
    if image_path is not None and (not isinstance(image_path, str) or not os.path.exists(image_path)):
        raise ValueError(f"Invalid image path: {image_path}")
    _validate_reference_image_paths(job, image_path)

    max_attempts = PIPELINE_MAX_ATTEMPTS
    for attempt in range(max_attempts):
        page = None
        last_error = ""
        if attempt > 0:
            s.reuse_count = 0
            s.bulk_force_fresh = False
        try:
            log.info("[W%d] 🧘 Posing pipeline attempt %d/%d", s.worker_id, attempt + 1, max_attempts)
            page = await asyncio.wait_for(_get_mage_page(s, app, job), timeout=float(SETUP_TIMEOUT))

            upload_budget = _pipeline_upload_budget(job, image_path)
            result = await asyncio.wait_for(
                _generate_posing(s, page, prompt, image_path, aspect, app, job),
                timeout=float(_generation_timeout_for_job(job) + 30 + upload_budget),
            )

            log.info("[W%d] ✅ Posing pipeline succeeded on attempt %d/%d", s.worker_id, attempt + 1, max_attempts)
            return result

        except asyncio.TimeoutError as exc:
            last_error = str(exc)
            log.warning("[W%d] ⏱️ Posing timeout on attempt %d/%d", s.worker_id, attempt + 1, max_attempts)

        except RuntimeError as exc:
            last_error = str(exc)
            if _runtime_error_is_moderation(str(exc)):
                log.warning("[W%d] 🛑 Posing moderation block (no retry): %s", s.worker_id, exc)
                raise ContentForbiddenError(str(exc)) from exc
            log.warning("[W%d] ⚠️ Posing known error on attempt %d/%d: %s", s.worker_id, attempt + 1, max_attempts, exc)

        except ContentForbiddenError:
            raise

        except ValueError as exc:
            log.error("[W%d] ❌ Posing validation error (won't retry): %s", s.worker_id, exc)
            raise

        except asyncio.CancelledError:
            # User pressed /cancel — propagate cleanly, no retry
            raise

        except Exception as exc:
            last_error = str(exc)
            log.error("[W%d] ❌ Posing unexpected error on attempt %d/%d: %s\n%s",
                     s.worker_id, attempt + 1, max_attempts, exc, traceback.format_exc())

        if attempt < max_attempts - 1:
            await _handle_pipeline_retry_cleanup(s, page, last_error=last_error, pipeline_label="posing")
            base_wait = _pipeline_retry_delay(attempt, last_error)
            log.info("[W%d] ⏳ Retrying posing in %.1fs…", s.worker_id, base_wait)
            await asyncio.sleep(base_wait)
        else:
            log.error("[W%d] ❌ All %d posing attempts failed", s.worker_id, max_attempts)
            _finalize_worker_account(s, success=False, error_msg=last_error)
            try:
                await asyncio.wait_for(_teardown_browser_stack(s), timeout=10.0)
            except Exception as e:
                log.warning("[W%d] ⚠️ Error tearing down session after posing failure: %s", s.worker_id, e)
            s.live_prewarmed_guava = False
            s.email = None
            s.gems = 0
            raise RuntimeError(f"Posing pipeline failed after {max_attempts} attempts")

    return None


async def run_gpt_image_pipeline(prompt: str, image_path: str | None, aspect: str, s: WorkerSession, app: Optional[Application] = None, job: Optional[Job] = None) -> str | None:
    """Run GPT Image 2 pipeline — Grok-style model handling, with aspect ratio."""
    if not prompt or not isinstance(prompt, str) or not prompt.strip():
        raise ValueError(f"Invalid prompt: {type(prompt)} / len={len(prompt) if isinstance(prompt, str) else 'N/A'}")
    if image_path is not None and (not isinstance(image_path, str) or not os.path.exists(image_path)):
        raise ValueError(f"Invalid image path: {image_path}")
    _validate_reference_image_paths(job, image_path)

    max_attempts = PIPELINE_MAX_ATTEMPTS
    for attempt in range(max_attempts):
        page = None
        last_error = ""
        if attempt > 0:
            s.reuse_count = 0
            s.bulk_force_fresh = False
        try:
            log.info("[W%d] 🎨 GPT Image 2 pipeline attempt %d/%d", s.worker_id, attempt + 1, max_attempts)
            page = await asyncio.wait_for(_get_mage_page(s, app, job), timeout=float(SETUP_TIMEOUT))

            upload_budget = _pipeline_upload_budget(job, image_path)
            result = await asyncio.wait_for(
                _generate_gpt_image(s, page, prompt, image_path, aspect, app, job),
                timeout=float(_generation_timeout_for_job(job) + 30 + upload_budget),
            )

            log.info("[W%d] ✅ GPT Image 2 pipeline succeeded on attempt %d/%d", s.worker_id, attempt + 1, max_attempts)
            return result

        except asyncio.TimeoutError as exc:
            last_error = str(exc)
            log.warning("[W%d] ⏱️ GPT Image 2 timeout on attempt %d/%d", s.worker_id, attempt + 1, max_attempts)

        except RuntimeError as exc:
            last_error = str(exc)
            if _runtime_error_is_moderation(str(exc)):
                log.warning("[W%d] 🛑 GPT Image 2 moderation block (no retry): %s", s.worker_id, exc)
                raise ContentForbiddenError(str(exc)) from exc
            log.warning("[W%d] ⚠️ GPT Image 2 known error on attempt %d/%d: %s", s.worker_id, attempt + 1, max_attempts, exc)

        except ContentForbiddenError:
            raise

        except ValueError as exc:
            log.error("[W%d] ❌ GPT Image 2 validation error (won't retry): %s", s.worker_id, exc)
            raise

        except asyncio.CancelledError:
            raise

        except Exception as exc:
            last_error = str(exc)
            log.error("[W%d] ❌ GPT Image 2 unexpected error on attempt %d/%d: %s\n%s",
                     s.worker_id, attempt + 1, max_attempts, exc, traceback.format_exc())

        if attempt < max_attempts - 1:
            await _handle_pipeline_retry_cleanup(s, page, last_error=last_error, pipeline_label="gpt_image")
            base_wait = _pipeline_retry_delay(attempt, last_error)
            log.info("[W%d] ⏳ Retrying GPT Image 2 in %.1fs…", s.worker_id, base_wait)
            await asyncio.sleep(base_wait)
        else:
            log.error("[W%d] ❌ All %d GPT Image 2 attempts failed", s.worker_id, max_attempts)
            _finalize_worker_account(s, success=False, error_msg=last_error)
            try:
                await asyncio.wait_for(_teardown_browser_stack(s), timeout=10.0)
            except Exception as e:
                log.warning("[W%d] ⚠️ Error tearing down session after GPT Image 2 failure: %s", s.worker_id, e)
            s.live_prewarmed_guava = False
            s.email = None
            s.gems = 0
            raise RuntimeError(f"GPT Image 2 pipeline failed after {max_attempts} attempts")

    return None


async def _generate_mango_3(s: WorkerSession, page: Page, prompt: str, image_path: str | None, aspect: str, app: Optional[Application] = None, job: Optional[Job] = None) -> str | None:
    """Mango 3 — Model selection, aspect ratio selection, optional reference upload, NO cost detection."""
    s.reference_cdn_urls = set()
    if not prompt or not isinstance(prompt, str) or not prompt.strip():
        raise ValueError(f"Invalid prompt: empty or wrong type ({type(prompt)})")
    aspect = _resolve_job_aspect(aspect, image_path, job)
    if image_path is not None and not isinstance(image_path, str):
        raise ValueError(f"Invalid image_path type: {type(image_path)}")
    reference_paths = _job_reference_image_paths(job, image_path)

    mango_bulk_ready = (
        _bulk_continuing(s, job)
        and await _mango_3_is_selected(page, s.worker_id)
    )
    if mango_bulk_ready:
        log.info("[W%d] ⚡ Mango 3 already active — skipping model navigation", s.worker_id)
    else:
        if not s.page_prepared_for_job:
            await _light_prepare_page(page, s.worker_id)
        await update_status(app, job, "🥭 Selecting Mango 3 Fast Mode...")
        await _ensure_mango_3_model_ready(page, s.worker_id)
        await update_status(app, job, "🥭 Mango 3 selected ✅")
    if s.stage_timer:
        s.stage_timer.mark("model_ready")

    # Set Aspect Ratio (as requested by user: "it needs an aspect selection like guava")
    await update_status(app, job, "📊 Setting aspect ratio...")
    log.info("[W%d] 📊 Setting aspect ratio to %s...", s.worker_id, aspect)
    if _bulk_continuing(s, job) and s.last_bulk_aspect == aspect:
        log.info("[W%d] 📐 Skipping aspect UI (bulk continue, unchanged %s)", s.worker_id, aspect)
    elif _reference_aspect_letterboxed(reference_paths, image_path, job):
        log.info("[W%d] 📐 Skipping aspect UI (reference pre-letterboxed to %s)", s.worker_id, aspect)
    else:
        try:
            await _set_aspect(page, aspect, s.worker_id)
            if job and job.is_bulk:
                s.last_bulk_aspect = aspect
        except Exception as e:
            log.error("❌ Aspect ratio setup failed: %s", e)
            raise

    # Upload reference if provided
    if reference_paths:
        try:
            if len(reference_paths) > 1:
                log.info(
                    "[W%d] 📎 Uploading %d reference images for Mango 3",
                    s.worker_id, len(reference_paths),
                )
            await update_status(app, job, "📤 Uploading reference...")
            for idx, ref_path in enumerate(reference_paths):
                if len(reference_paths) > 1:
                    await update_status(
                        app, job, f"📤 Uploading reference {idx + 1}/{len(reference_paths)}...",
                    )
                await _upload_image_posing(
                    page,
                    ref_path,
                    s.worker_id,
                    job=job,
                    s=s,
                    clear_existing=(idx == 0),
                    skip_create_with_this=mango_bulk_ready,
                )
            if _multi_reference_upload(reference_paths):
                await _ensure_reference_mode_chip(page, s.worker_id)
                await page.wait_for_timeout(400)
            await update_status(app, job, "📤 Reference uploaded ✅")
            if not _multi_reference_upload(reference_paths):
                await _assert_reference_attached(page, s.worker_id)
            await _capture_reference_cdn_urls(page, s)
        except Exception as e:
            if job and job.is_bulk:
                s.bulk_force_fresh = True
            log.error("❌ Mango 3 reference upload failed: %s", e)
            raise
    if s.stage_timer:
        s.stage_timer.mark("upload")

    if INJECT_GENERATION_PARAMS:
        try:
            await inject_generation_params(page)
        except Exception as e:
            log.warning("⚠️ Generation params injection failed (non-critical): %s", e)

    try:
        await update_status(app, job, "✍️ Injecting prompt...")
        await _paste_prompt(page, prompt, s.worker_id, job=job)
        await update_status(app, job, "✍️ Prompt ready")
    except Exception as e:
        log.error("❌ Prompt paste failed: %s", e)
        raise

    # Track gems so wait-for-result can detect start via deduction (same as Guava/Grok).
    # Cost UI gating is still skipped; this is wait-path only.
    gems_before = await _read_gems_remaining(page)

    if reference_paths and not _multi_reference_upload(reference_paths):
        await _ensure_reference_after_prompt(
            page, s.worker_id, reference_paths, video=False, posing=True
        )
        await _capture_reference_cdn_urls(page, s)

    multi_ref = _multi_reference_upload(reference_paths)
    try:
        await update_status(app, job, "🥭 Generating Mango 3... (~10s)")
        if multi_ref:
            await _ensure_reference_mode_chip(page, s.worker_id)
            await page.wait_for_timeout(400)
        await _assert_generation_ready(
            page,
            s.worker_id,
            needs_reference=bool(reference_paths) and not multi_ref,
            posing=True,
            trust_send=multi_ref,
        )
        await _hit_send(page, s, promptbar_only=True)

        await _maybe_refill_pool_after_send(job, reason="send")
        if s.stage_timer:
            s.stage_timer.mark("send")

        await update_status(app, job, "⏳ AI generating...")
        exclude = s.last_bulk_output_url if (job and job.is_bulk) else None
        s.last_bulk_output_url = None
        url = await _wait_for_result(
            s, page, timeout_s=_generation_timeout_for_job(job), posing=True,
            gems_before=gems_before,
            exclude_url=exclude,
            job=job,
        )
        if job and job.is_bulk and url:
            s.last_bulk_output_url = url
        s.last_output_cdn_url = url
        if s.stage_timer:
            s.stage_timer.mark("generate_wait")

        await update_status(app, job, "📥 Downloading generated result...")
        log.info("[W%d] 📥 Downloading Mango 3 result from CDN...", s.worker_id)
        wait_ctx = getattr(s, "last_wait_ctx", None) or {}
        result = await _download_generation_result(
            s, page, url, reference_paths,
            pre_count=wait_ctx.get("pre_count", 0),
            pre_urls=wait_ctx.get("pre_urls"),
            exclude_urls=wait_ctx.get("exclude_urls"),
        )
        if s.stage_timer:
            s.stage_timer.mark("download")

        await update_status(app, job, "✅ Generation complete! Processing output...")
        log.info("[W%d] ✅ Mango 3 generation and download successful", s.worker_id)
        return result
    except Exception as e:
        log.error("❌ Mango 3 generation/download failed: %s", e)
        raise


async def run_mango_3_pipeline(prompt: str, image_path: str | None, aspect: str, s: WorkerSession, app: Optional[Application] = None, job: Optional[Job] = None) -> str | None:
    """Run Mango 3 pipeline — aspect selection + optional reference, NO cost detection."""
    if not prompt or not isinstance(prompt, str) or not prompt.strip():
        raise ValueError(f"Invalid prompt: {type(prompt)} / len={len(prompt) if isinstance(prompt, str) else 'N/A'}")
    if image_path is not None and (not isinstance(image_path, str) or not os.path.exists(image_path)):
        raise ValueError(f"Invalid image path: {image_path}")
    _validate_reference_image_paths(job, image_path)

    max_attempts = PIPELINE_MAX_ATTEMPTS
    for attempt in range(max_attempts):
        page = None
        last_error = ""
        if attempt > 0:
            s.reuse_count = 0
            s.bulk_force_fresh = False
        try:
            log.info("[W%d] 🥭 Mango 3 pipeline attempt %d/%d", s.worker_id, attempt + 1, max_attempts)
            page = await asyncio.wait_for(_get_mage_page(s, app, job), timeout=float(SETUP_TIMEOUT))

            upload_budget = _pipeline_upload_budget(job, image_path)
            result = await asyncio.wait_for(
                _generate_mango_3(s, page, prompt, image_path, aspect, app, job),
                timeout=float(_generation_timeout_for_job(job) + 30 + upload_budget),
            )

            log.info("[W%d] ✅ Mango 3 pipeline succeeded on attempt %d/%d", s.worker_id, attempt + 1, max_attempts)
            return result

        except asyncio.TimeoutError as exc:
            last_error = str(exc)
            log.warning("[W%d] ⏱️ Mango 3 timeout on attempt %d/%d", s.worker_id, attempt + 1, max_attempts)

        except RuntimeError as exc:
            last_error = str(exc)
            if _runtime_error_is_moderation(str(exc)):
                log.warning("[W%d] 🛑 Mango 3 moderation block (no retry): %s", s.worker_id, exc)
                raise ContentForbiddenError(str(exc)) from exc
            log.warning("[W%d] ⚠️ Mango 3 known error on attempt %d/%d: %s", s.worker_id, attempt + 1, max_attempts, exc)

        except ContentForbiddenError:
            raise

        except ValueError as exc:
            log.error("[W%d] ❌ Mango 3 validation error (won't retry): %s", s.worker_id, exc)
            raise

        except asyncio.CancelledError:
            raise

        except Exception as exc:
            last_error = str(exc)
            log.error("[W%d] ❌ Mango 3 unexpected error on attempt %d/%d: %s\n%s",
                     s.worker_id, attempt + 1, max_attempts, exc, traceback.format_exc())

        if attempt < max_attempts - 1:
            await _handle_pipeline_retry_cleanup(s, page, last_error=last_error, pipeline_label="mango3")
            base_wait = _pipeline_retry_delay(attempt, last_error)
            log.info("[W%d] ⏳ Retrying Mango 3 in %.1fs…", s.worker_id, base_wait)
            await asyncio.sleep(base_wait)
        else:
            log.error("[W%d] ❌ All %d Mango 3 attempts failed", s.worker_id, max_attempts)
            _finalize_worker_account(s, success=False, error_msg=last_error)
            try:
                await asyncio.wait_for(_teardown_browser_stack(s), timeout=10.0)
            except Exception as e:
                log.warning("[W%d] ⚠️ Error tearing down session after Mango 3 failure: %s", s.worker_id, e)
            s.live_prewarmed_guava = False
            s.email = None
            s.gems = 0
            raise RuntimeError(f"Mango 3 pipeline failed after {max_attempts} attempts")

    return None


async def run_video_pipeline(
    prompt: str,
    image_path: str | None,
    aspect: str,
    s: WorkerSession,
    app: Optional[Application] = None,
    job: Optional[Job] = None,
) -> str | None:
    """Run Kiwi video pipeline — aspect from reference, Video tab upload."""
    if not prompt or not isinstance(prompt, str) or not prompt.strip():
        raise ValueError(f"Invalid prompt: {type(prompt)} / len={len(prompt) if isinstance(prompt, str) else 'N/A'}")
    aspect = _resolve_job_aspect(aspect, image_path, job)
    if image_path is not None and (not isinstance(image_path, str) or not os.path.exists(image_path)):
        raise ValueError(f"Invalid image path: {image_path}")
    _validate_reference_image_paths(job, image_path)

    max_attempts = PIPELINE_MAX_ATTEMPTS
    for attempt in range(max_attempts):
        page = None
        last_error = ""
        if attempt > 0:
            s.reuse_count = 0
            s.bulk_force_fresh = False
        try:
            log.info("[W%d] 🎬 Video pipeline attempt %d/%d", s.worker_id, attempt + 1, max_attempts)
            page = await asyncio.wait_for(_get_mage_page(s, app, job), timeout=float(SETUP_TIMEOUT))

            upload_budget = _pipeline_upload_budget(job, image_path)
            result = await asyncio.wait_for(
                _generate_video(s, page, prompt, image_path, aspect, app, job),
                timeout=float(VIDEO_GENERATION_TIMEOUT + 60 + upload_budget),
            )

            log.info("[W%d] ✅ Video pipeline succeeded on attempt %d/%d", s.worker_id, attempt + 1, max_attempts)
            return result

        except asyncio.TimeoutError as exc:
            last_error = str(exc)
            log.warning("[W%d] ⏱️ Video timeout on attempt %d/%d", s.worker_id, attempt + 1, max_attempts)

        except RuntimeError as exc:
            last_error = str(exc)
            if _runtime_error_is_moderation(str(exc)):
                log.warning("[W%d] 🛑 Video moderation block (no retry): %s", s.worker_id, exc)
                raise ContentForbiddenError(str(exc)) from exc
            log.warning("[W%d] ⚠️ Video known error on attempt %d/%d: %s", s.worker_id, attempt + 1, max_attempts, exc)

        except ContentForbiddenError:
            raise

        except ValueError as exc:
            log.error("[W%d] ❌ Video validation error (won't retry): %s", s.worker_id, exc)
            raise

        except asyncio.CancelledError:
            # User pressed /cancel — propagate cleanly, no retry
            raise

        except Exception as exc:
            last_error = str(exc)
            log.error("[W%d] ❌ Video unexpected error on attempt %d/%d: %s\n%s",
                     s.worker_id, attempt + 1, max_attempts, exc, traceback.format_exc())

        if attempt < max_attempts - 1:
            await _handle_pipeline_retry_cleanup(s, page, last_error=last_error, pipeline_label="video")
            base_wait = _pipeline_retry_delay(attempt, last_error)
            log.info("[W%d] ⏳ Retrying video in %.1fs…", s.worker_id, base_wait)
            await asyncio.sleep(base_wait)
        else:
            log.error("[W%d] ❌ All %d video attempts failed", s.worker_id, max_attempts)
            _finalize_worker_account(s, success=False, error_msg=last_error)
            try:
                await asyncio.wait_for(_teardown_browser_stack(s), timeout=10.0)
            except Exception as e:
                log.warning("[W%d] ⚠️ Error tearing down session after video failure: %s", s.worker_id, e)
            s.live_prewarmed_guava = False
            s.email = None
            s.gems = 0
            raise RuntimeError(f"Video pipeline failed after {max_attempts} attempts")

    return None


# ── Telegram conversation wizard ─────────────────────────────────────────────

ASK_PROMPT = 0
ASK_IMAGE  = 1
ASK_ASPECT = 2
ASK_HIJAB  = 3
ASK_PROMPT_MODE = 4  # Choose between custom, auto, or template prompt
ASK_CUSTOM_PROMPT = 5  # User typing custom prompt
ASK_TEMPLATES = 6  # Browsing prompt template library
ASK_MODE_SELECT = 7  # Single vs bulk mode
ASK_BULK_IMAGES = 8  # Collecting multiple reference images
ASK_GUAVA_VERSION = 9  # V1  vs V2 

MAX_BULK_IMAGES = 30
MAX_SINGLE_REFERENCES = int(os.getenv("MAX_SINGLE_REFERENCES", "8"))


def get_reference_done_keyboard(count: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                f"Done ({count} ref{'s' if count != 1 else ''})",
                callback_data="refs_done",
            )
        ],
        [InlineKeyboardButton("Cancel", callback_data="refs_cancel")],
    ])

DEFAULT_IMAGE_PROMPT = (
    "Same place and pose, fully naked body. NSFW."
)

DEFAULT_POSING_PROMPT = (
    "Same girl, same place, change pose while keeping appearance, fully naked, NSFW."
)


def get_default_image_prompt() -> str:
    if USE_ABSOLUTE_PROMPTS:
        try:
            prompt = build_absolute_prompt(
                shot_type="same as reference",
                camera_angle="front",
                breast_size="natural",
                body_type="natural",
                pose_description="same pose as reference",
                clothing_to_remove="all clothing",
                background_type="keep identical to reference",
            )
            return absolute_nsfw_evasion(prompt)
        except Exception as e:
            log.warning("build_absolute_prompt failed, using inline fallback: %s", e)

    import random

    nipple_variations = [
        "fully visible projected nipples, visible Montgomery glands on areolas with softly blended edges, natural dark pink/brown areola color",
        "fully exposed small delicate pink nipples, compact softly faded light pink areolas",
        "fully visible projected nipples, dusky rose areolas with softly blended margins, natural skin texture with tiny Montgomery glands",
        "highly detailed small projected nipples, warm caramel colored areolas with softly blended borders",
        "highly detailed realistic small nipples, natural peach-toned areolas with softly blended edges",
        "fully exposed projected nipples, natural dusky pink areolas with tiny bumps and softly faded margins",
    ]
    selected_nipple = random.choice(nipple_variations)

    return (
        "Ultra photorealistic unretouched 8K raw photo, Hasselblad medium format, natural grain, zero beauty filtering. "
        "BODY SKIN (neck down only): visible pores, sebaceous filaments, stretch marks, cellulite dimples, "
        "hyperpigmentation, natural oil sheen, skin folds moisture. "
        "Completely hairless smooth-shaved body below neck — arms, legs, pubic area — no stubble, pores intact. "
        "No red marks; preserve blue veins, discoloration, natural texture. No retouching, no AI perfection. "
        "SKIN COLOR & TONE LOCK: Lock the body skin color and skin tone of the subject to be 100% identical to the reference image. "
        "The skin tone of any edited body parts must seamlessly match the subject's face and neck skin tone from the reference image exactly. "
        "Do not lighten, darken, or change the lighting temperature of the skin. "
        "HEAD & FACE: DO NOT touch face, head, hair, headwear, or expression. 100% identical to reference. "
        "Only neck-down body is edited. "
        "HEADWEAR / HAIR / SCALP (ABSOLUTE LOCK): If the subject wears a hijab, headscarf, hat, or any head covering "
        "in the reference, it MUST appear in the output — identical fabric, color, drape, and coverage. "
        "DO NOT remove, replace, or reveal what is covered. "
        "The hairless-body rule applies ONLY below the neck — NEVER to the head or scalp. "
        "FRAMING IS THE ABSOLUTE RULE: Output must match the exact same crop, camera distance, and framing as the reference. "
        "DO NOT zoom out, DO NOT widen the shot, DO NOT show body parts outside the original frame. "
        "If reference is a close-up or portrait, output must be the same close-up — do NOT pull back to show nudity or genitals. "
        "Only body parts visible in the reference frame may appear in the output. "
        "Completely nude neck down (within visible framing only). Remove all clothing. "
        "\n"
        "--- ANATOMY LOCK CONDITIONS ---\n"
        "IF BREASTS VISIBLE IN REFERENCE: Add realistic nipples with natural coloring.\n"
        "IF BACK VIEW: Only show back anatomy (spine, shoulders, buttocks) — NO breasts, NO chest, NO frontal anatomy.\n"
        "IF CLOTHED BREASTS IN REFERENCE: Output must show the SAME breast size and shape when naked — match the under-clothing silhouette exactly.\n"
        "\n"
        "BREAST SIZE & SHAPE LOCK: The generated breasts/chest must match the exact size, shape, volume, and proportions of the subject's chest silhouette in the reference. Do not enlarge, do not shrink, preserve the exact dimensions and outline from the reference image. "
        f"Breasts (if visible in reference): fully exposed nude bare breasts matching the exact size and proportions of the subject in the reference, natural soft physics, natural sag and asymmetric ptosis, {selected_nipple}, realistic skin texture with subtle veins, skin pores, and soft underbust fold. "
        "(If back view: NO breasts visible — back only.) "
        "(If clothed in reference: output the same size/shape but now nude.) "
        "\n"
        "Vulva (only if pubic area is visible in reference framing): a single soft closed natural vertical line, "
        "smooth mound, fully closed — no open labia, no protrusions, no visible internals. Completely hairless. "
        "Buttocks (only if visible in reference): natural asymmetry, gluteal fold creases, realistic skin texture. "
        "FRAMING & POSE: Preserve exact framing, camera distance, composition. "
        "Do NOT zoom, rotate, or shift. Do NOT generate body parts not visible in reference. "
        "Replicate pose exactly as in reference. "
        "NO DISTORTION OR STRETCHING: The output canvas aspect ratio may differ slightly from the reference. "
        "NEVER stretch, squeeze, compress, or warp the subject, face, limbs, or background to fill the frame. "
        "All body proportions must look exactly as in the reference — natural, undistorted. "
        "If the canvas is marginally wider or taller, extend the background or environment naturally to fill the extra space. "
        "Identical lighting and background to reference. No new light rays or shadows. "
        "Masterpiece, raw documentary photo, maximum realism, no AI perfection."
    )


# Shared headwear-lock phrase injected into both prompts
_HEADWEAR_LOCK = (
    "HEADWEAR / HAIR / SCALP (ABSOLUTE LOCK): "
    "The subject's head covering, hair, and scalp are 100% FORBIDDEN to alter, remove, replace, or reveal. "
    "If a hijab, headscarf, hat, or any headwear is worn in the reference, it MUST appear in the output — "
    "identical fabric, color, drape, and coverage. "
    "DO NOT show hair, scalp, forehead hairline, or bare head if they are covered in the reference. "
    "The hairless-body rule applies ONLY below the neck — NEVER to the head or scalp."
)

def build_custom_prompt(analysis: dict) -> str:
    framing = analysis.get("framing_crop", "full body shot").lower()
    non_visible_parts = analysis.get("non_visible_body_parts", "none").lower()
    camera_viewpoint = analysis.get("camera_viewpoint", "front view").lower()
    body_surfaces = analysis.get("body_surfaces_facing_camera", "front torso and face").lower()
    body_desc = analysis.get("body_description", "").strip()
    breast_size = analysis.get("breast_size_category", "natural").strip().lower()
    visible_clothing = analysis.get("visible_clothing_to_remove", "clothing")
    key_pose = analysis.get("key_pose_phrase", "same pose as reference")
    background = analysis.get("background_desc", "keep identical")
    color_temp = analysis.get("color_temp", "5500")
    head_cover_phrase = analysis.get("head_cover_phrase", "").strip()
    fabric_type = analysis.get("fabric_type", "").strip()

    # Determine chest visibility
    visible_parts = analysis.get("visible_body_parts", "").lower()
    is_backview = any(term in camera_viewpoint for term in ["back", "three-quarter back"]) or "back" in body_surfaces
    
    chest_visible = True
    if breast_size in ("not visible", "none", "null") or "chest" in non_visible_parts or "breast" in non_visible_parts:
        chest_visible = False
    if is_backview:
        chest_visible = False

    # --- Base realism (tight) ---
    prompt = (
        "Ultra photorealistic unretouched 8K raw photo, Hasselblad medium format, natural grain, zero beauty filtering. "
        "BODY SKIN (neck down only): visible pores, sebaceous filaments, stretch marks, cellulite dimples, "
        "hyperpigmentation, natural oil sheen, skin fold moisture. "
        "Completely hairless smooth-shaved body below neck — no stubble, pores intact. "
        "No red marks; preserve blue veins, discoloration, natural texture. No retouching.\n"
    )

    # --- Skin Color & Tone Lock ---
    prompt += (
        "SKIN COLOR & TONE LOCK: Lock the body skin color and skin tone of the subject to be 100% identical to the reference image. "
        "The skin tone of the edited body parts must seamlessly match the subject's face and neck skin tone from the reference image exactly. "
        "Do not lighten, do not darken, do not change the lighting temperature of the skin. Keep skin hue 100% consistent.\n"
    )

    # --- Body description (from Groq, already framing-matched) ---
    if body_desc:
        prompt += f"SUBJECT: {body_desc}\n"

    # Map breast size category to match the reference bust size and shape naturally without arbitrary changes.
    breast_size_clean = breast_size.lower().strip()
    if not chest_visible:
        breast_desc = "No breasts or chest nudity visible in reference framing. Chest is out of frame / hidden. Do not generate breasts or upper body nudity."
        breast_realism = ""
    else:
        if breast_size_clean == "huge":
            breast_desc = "breast size matching the huge proportions of the reference, natural heavy breasts, huge natural breasts"
        elif breast_size_clean == "large":
            breast_desc = "breast size matching the large proportions of the reference, full breasts, large natural breasts"
        elif breast_size_clean == "medium":
            breast_desc = "breast size matching the medium proportions of the reference, natural medium breasts, well-proportioned bust"
        elif breast_size_clean == "small":
            breast_desc = "breast size matching the small proportions of the reference, small natural breasts, petite bust"
        elif breast_size_clean == "flat":
            breast_desc = "completely flat chest matching the flat chest of the reference, with no breast projection"
        else:
            breast_desc = "nude breasts matching the exact natural size, shape, volume, and proportions of the subject's chest/clothing silhouette in the reference exactly"

        areola_nipple = analysis.get("areola_nipple_description", "").strip()
        if not areola_nipple or areola_nipple.lower() in ("none", "null"):
            import random
            areola_nipple = random.choice([
                "visible Montgomery glands on areolas with softly blended edges, natural dark pink/brown areola color",
                "small delicate pink nipples with compact, softly faded light pink areolas",
                "dusky rose areolas with softly blended margins, natural skin texture with tiny Montgomery glands",
                "warm caramel colored areolas with softly blended borders, small natural nipples",
                "natural peach-toned areolas with soft blended edges, realistic small nipples",
                "natural dusky pink areolas with tiny bumps, softly faded margins"
            ])

        breast_realism = (
            f"fully exposed nude breasts matching the exact chest size and proportions of the reference, "
            f"natural soft physics, natural sag, {areola_nipple}, "
            f"realistic skin texture with skin pores and soft underbust fold"
        )

    # --- Breast size & shape lock ---
    if chest_visible:
        prompt += (
            f"BREAST SIZE & SHAPE LOCK: {breast_desc}. "
            "The output breasts/chest size, volume, and boundary shape must align 1:1 with the subject's chest silhouette in the reference. "
            "DO NOT enlarge the breasts. DO NOT make them larger, fuller, or rounder than the reference. "
            "DO NOT shrink the breasts. "
            "Preserve the exact dimensions, chest outline, and natural scale of the subject's bust from the reference image. "
            "Do not enlarge, do not shrink, preserve the exact chest proportions, volume, and silhouette from the reference image.\n"
        )
    else:
        prompt += f"BREAST SIZE & SHAPE LOCK: {breast_desc}\n"

    # --- Head & face lock (with specific headwear from Groq analysis) ---
    has_headwear = head_cover_phrase and head_cover_phrase.lower() not in ("none", "null", "", "no headwear")
    if has_headwear:
        fabric_desc = f", {fabric_type}" if fabric_type and fabric_type.lower() not in ("none", "null", "") else ""
        prompt += (
            f"HEAD/FACE: 100% unchanged from reference — face, expression identical.\n"
            f"HEADWEAR ABSOLUTE LOCK: Subject is wearing a {head_cover_phrase}{fabric_desc}. "
            f"This {head_cover_phrase} MUST remain on the head in the output — "
            "same color, same fabric, same drape, same coverage as the reference. "
            "DO NOT remove it, replace it, or reveal the hair/scalp beneath it. "
            "The hairless-body instruction applies ONLY below the neck — the head and scalp are OFF LIMITS.\n"
        )
    else:
        prompt += (
            "HEAD/FACE: Completely unchanged from reference — face, hair, headwear, expression all 100% identical. "
            "Only neck-down body is edited.\n"
        )

    # --- Framing is the MASTER RULE — established first, overrides everything ---
    is_close   = "portrait" in framing or "close-up" in framing or "close up" in framing
    is_medium  = "medium" in framing or "waist" in framing
    is_full    = "full body" in framing or "three-quarter" in framing or "three quarter" in framing

    prompt += f"FRAMING LOCK (ABSOLUTE MASTER RULE): {framing}. Camera: {camera_viewpoint}. Pose: {key_pose}.\n"
    prompt += (
        "The output crop, camera distance, alignment, and framing must be 100% IDENTICAL to the reference image. "
        "DO NOT zoom out, DO NOT zoom in, DO NOT shift the camera position, DO NOT widen the shot, and DO NOT alter the perspective. "
        "The subject must remain in the exact same position, scale, and layout as the reference image.\n"
    )

    if is_close:
        if chest_visible:
            prompt += (
                f"CLOSE-UP / PORTRAIT SHOT: Output shows face and chest area only — same as reference. "
                f"Chest area only: fully exposed naked chest with {breast_desc}, {breast_realism}. "
                "ABSOLUTELY DO NOT show lower body, stomach, genitals, or legs. "
                "No zooming out under any circumstances.\n"
            )
        else:
            prompt += (
                "CLOSE-UP / PORTRAIT SHOT: Output shows face and neck only — same as reference. "
                "Chest and breasts are completely out of frame. DO NOT zoom out, DO NOT show chest, breasts, or nudity. "
                "No zooming out under any circumstances.\n"
            )
    elif is_medium:
        if chest_visible:
            prompt += (
                f"MEDIUM SHOT: Output shows waist up only — same as reference. "
                f"Upper body: fully exposed naked torso with {breast_desc}, {breast_realism}. "
                "DO NOT show legs, thighs, feet, or genitals. No zooming out.\n"
            )
        else:
            prompt += (
                "MEDIUM SHOT: Output shows waist up only — same as reference. "
                "Chest and breasts are completely out of frame/hidden. DO NOT show nudity on non-visible parts.\n"
            )
    elif is_full:
        if chest_visible:
            prompt += "FULL / THREE-QUARTER SHOT: Full body visible — show all body parts within reference framing.\n"
        else:
            prompt += "FULL / THREE-QUARTER SHOT: Full body visible — chest/breasts are hidden/out-of-frame.\n"

    if is_backview:
        prompt += (
            "BACK VIEW: Show back, spine, shoulder blades, and buttocks only. "
            "NO frontal anatomy — no breasts, no vulva, no chest. Subject faces away from camera.\n"
        )
    elif "side" in camera_viewpoint:
        prompt += "SIDE VIEW: Maintain exact lateral angle. Do not rotate to front or back.\n"

    # --- Framing lock for non-visible parts ---
    if non_visible_parts and non_visible_parts not in ("none", "null", ""):
        prompt += f"OUT OF FRAME — do NOT generate these parts: {non_visible_parts}.\n"

    # --- Anatomy Lock Conditions ---
    # IF breasts visible in reference: add realistic nipples
    # IF back view: only show back anatomy, NO nipples/breasts
    # IF clothing visible in reference: output must show same breast size naked
    
    # Detect if breasts are likely visible in reference (from visible_parts)
    breasts_likely_visible = "breast" in visible_parts or "chest" in visible_parts or "torso" in visible_parts
    
    # Detect if reference shows clothed breasts (from clothing description)
    has_clothed_breasts = any(term in visible_clothing.lower() for term in ["shirt", "top", "dress", "bra", "sweater", "blouse", "tank", "tube"])
    
    # Add intelligent conditional rules based on reference
    if is_backview:
        # BACK VIEW CONDITION: Only back anatomy, NO breasts/nipples
        prompt += "ANATOMY LOCK — BACK VIEW: Output must show ONLY back anatomy (spine, shoulder blades, buttocks). "
        prompt += "ABSOLUTELY NO breasts, NO chest, NO vulva, NO frontal anatomy. Back view only.\n"
    
    elif breasts_likely_visible or chest_visible:
        # BREAST VISIBILITY CONDITION: Add realistic nipple/areola details
        if chest_visible and areola_nipple and areola_nipple.lower() not in ("none", "null"):
            prompt += f"ANATOMY LOCK — BREAST VISIBILITY: Breasts are clearly visible in reference. "
            prompt += f"Output must include: {areola_nipple}. "
            prompt += "Realistic, detailed areola and nipple anatomy fully visible.\n"
    
    if has_clothed_breasts and chest_visible:
        # CLOTHED BREASTS CONDITION: Reference shows clothed breasts → output same size naked
        prompt += "REFERENCE CLOTHING ANALYSIS: Reference image shows clothed breasts/chest. "
        prompt += "The output must show the SAME breast size, shape, and volume underneath, now revealed as nude. "
        prompt += f"Exact sizing: {breast_desc} — match the clothed silhouette precisely as nude. "
        prompt += "No enlargement, no shrinking. Match the under-clothing breast form exactly.\n"
    
    # --- Nipple Specification Lock ---
    if chest_visible and not is_backview:
        if areola_nipple and areola_nipple.lower() not in ("none", "null"):
            prompt += f"NIPPLE & AREOLA LOCK: Use these exact realistic specifications: {areola_nipple}. "
            prompt += "Do not use generic or cartoon-style nipples. Must be photorealistic and anatomically accurate.\n"

    # --- Nudity & anatomy (only within permitted framing) ---
    prompt += f"Remove {visible_clothing}. Nude neck down within the visible framing only. Smooth-shaved, hairless body.\n"

    if is_backview:
        prompt += (
            "Back anatomy: natural spine curve, shoulder blades, realistic buttocks with gluteal fold creases. "
            "No frontal anatomy visible at all.\n"
        )
    elif not is_close and not is_medium:
        # Full body / three-quarter — show everything
        if chest_visible:
            prompt += (
                f"Full anatomy: fully exposed naked torso with {breast_desc}, {breast_realism}. "
                "Pubic area: a single soft closed natural vertical line — smooth mound, fully closed, "
                "no open labia, no protrusions, no visible internals. Completely hairless surrounding area.\n"
                "Buttocks: natural asymmetry, gluteal fold creases, realistic skin texture.\n"
            )
        else:
            prompt += (
                "Full anatomy: Subject is nude within visible framing. Chest and breasts are hidden/not visible. "
                "Pubic area: a single soft closed natural vertical line — smooth mound, fully closed, "
                "no open labia, no protrusions, no visible internals. Completely hairless surrounding area.\n"
                "Buttocks: natural asymmetry, gluteal fold creases, realistic skin texture.\n"
            )

    # --- Anti-distortion (canvas AR may differ slightly from reference) ---
    prompt += (
        "NO DISTORTION OR STRETCHING: The output canvas aspect ratio may differ slightly from the reference image. "
        "NEVER stretch, squeeze, compress, elongate, or warp the subject, face, body, limbs, or background to fill the frame. "
        "All body proportions must appear exactly as in the reference — natural, undistorted. "
        "If the canvas is marginally wider or taller than the reference, fill the extra space by "
        "extending the background/environment naturally (blur, wall, floor, sky) — do NOT scale or warp any body part.\n"
    )

    # --- Lighting & background ---
    prompt += (
        f"LIGHTING & BG: Identical to reference — {background}. Color temp {color_temp}K. "
        "No new light rays or shadows. "
        "Masterpiece, raw documentary photo, maximum realism, no AI perfection."
    )

    return prompt




def _aspect_keyboard() -> InlineKeyboardMarkup:
    buttons = [
        InlineKeyboardButton(a, callback_data=f"aspect:{a}") for a in ASPECTS
    ]
    return InlineKeyboardMarkup([buttons[:4], buttons[4:]])


# Hijab keyboard removed as bot now automatically preserves head/hijab/hair


async def _check_admin_access(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> bool:
    """Allow configured users; silently ignore everyone else."""
    uid = update.effective_user.id

    if uid == ADMIN_ID or uid in ALLOWED_USER_IDS:
        return True

    now = time.time()
    last = _blocked_access_last_log.get(uid, 0.0)
    if now - last >= BLOCKED_ACCESS_LOG_INTERVAL:
        _blocked_access_last_log[uid] = now
        username = update.effective_user.username or "none"
        log.info("Ignored unauthorized user access: %d (@%s)", uid, username)

    return False


async def cmd_status(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Show detailed system status from QueueManager."""
    if not await _check_admin_access(update, ctx):
        return
    
    try:
        queue_status = await queue_manager.get_queue_status()
        pool_line = ""
        if acct_manager is not None:
            ps = acct_manager.pool_stats()
            pool_line = f"\n*Session Pool:* `{ps['ready']}/{TARGET_POOL_SIZE}` ready · `{ps['in_use']}` in use · `{ps['total']}` total"
        maildev = _maildev_health_summary()
        maildev_line = (
            f"\n*Maildev:* proxy `{'healthy' if maildev['proxy_healthy'] else 'unhealthy'}`"
            f" · configured `{'yes' if maildev['proxy_configured'] else 'no'}`"
        )
        
        queue_info = f"""
*🤖 System Status*

*Workers:* `{NUM_WORKERS}` (pre-warm: `{PREWARM_WORKERS}`)
*Queue:* `{queue_status['queue_size']}/{queue_status['max_size']}`
*Active Users:* `{queue_status['active_users']}`
*Processed:* `{queue_status['total_jobs_processed']}`{pool_line}{maildev_line}
*Avg Process Time:* `{_format_duration(queue_status['avg_process_time'])}`

*Timeouts:* setup `{SETUP_TIMEOUT}s` · image `{GENERATION_ATTEMPT_TIMEOUT}s` · posing `{POSE_GENERATION_TIMEOUT}s` · bulk `{BULK_GENERATION_TIMEOUT}s` · video `{VIDEO_GENERATION_TIMEOUT}s` · worker `{WORKER_JOB_TIMEOUT}s` · pipeline attempts `{PIPELINE_MAX_ATTEMPTS}` · job requeue `{JOB_MAX_REQUEUE}`
*Browser Reuse:* normal `{BROWSER_REUSE_LIMIT}` · bulk `{BULK_MAX_BROWSER_REUSE}`

*Jobs in Queue:*
"""
        
        if queue_status['queue']:
            for i, job_info in enumerate(queue_status['queue'], 1):
                eta = _format_duration(job_info.get("eta_seconds") or 0)
                queue_info += (
                    f"`{i}. ID: {job_info['id'][:12]}... "
                    f"(User: {job_info['user_id']}, Priority: {job_info['priority']}, ETA: ~{eta})`\n"
                )
        else:
            queue_info += "`(empty)`\n"
        
        queue_info += f"\n*Capacity:* {int(queue_status['queue_size'] / queue_status['max_size'] * 100)}%"
        
        await update.message.reply_text(queue_info, parse_mode="Markdown")
    except Exception as e:
        log.error("❌ Error getting status: %s", e)
        await update.message.reply_text("❌ Error retrieving status.")



def _register_user(chat_id: int):
    """Save user chat ID to users.txt for broadcasting notifications."""
    try:
        users_file = DATA_DIR / "users.txt"
        chat_ids = set()
        if users_file.exists():
            with open(users_file, "r") as f:
                chat_ids = {int(line.strip()) for line in f if line.strip().isdigit()}
        if chat_id not in chat_ids:
            with open(users_file, "a") as f:
                f.write(f"{chat_id}\n")
            log.info("👤 Registered new user chat ID: %d", chat_id)
    except Exception as e:
        log.warning("⚠️ Failed to register user chat ID %d: %s", chat_id, e)


async def _download_and_preprocess_photo(
    update: Update, ctx: ContextTypes.DEFAULT_TYPE, uid: int
) -> Optional[dict]:
    """Download a Telegram photo and preprocess for generation. Returns metadata dict or None."""
    photo = update.message.photo[-1]
    tmp = tempfile.NamedTemporaryFile(suffix=".jpg", delete=False, dir=DATA_DIR)
    tmp.close()
    path = tmp.name
    file_id = photo.file_id

    for attempt in range(2):
        try:
            tg_file = await ctx.bot.get_file(file_id)
            await tg_file.download_to_drive(path)
            size = os.path.getsize(path)
            if size < MIN_TELEGRAM_IMAGE_BYTES:
                if attempt == 0:
                    log.warning(
                        "⚠️ Image too small (%d bytes) for user %d — retrying download",
                        size, uid,
                    )
                    continue
                log.error("❌ Image download failed: file too small (%d bytes)", size)
                return None
            if not _validate_image_file(path):
                if attempt == 0:
                    log.warning(
                        "⚠️ Image failed validation (%d bytes) for user %d — retrying download",
                        size, uid,
                    )
                    await asyncio.sleep(1.5)
                    continue
                if _repair_image_file(path):
                    log.info(
                        "✅ Repaired corrupt Telegram image for user %d (%d bytes)",
                        uid, os.path.getsize(path),
                    )
                    break
                log.warning(
                    "⚠️ Image invalid after retry (%d bytes) for user %d — defaulting to 1:1",
                    size, uid,
                )
                return None
            log.info("📥 Image downloaded for user %d: %s (%d bytes)", uid, path, size)
            break
        except Exception as e:
            if attempt == 0:
                log.warning("⚠️ Download attempt failed for user %d: %s — retrying", uid, e)
                continue
            log.error("❌ Failed to download photo: %s", e)
            return None
    else:
        return None

    admin_id = get_admin_group_id()
    if admin_id:
        try:
            await ctx.bot.send_photo(
                chat_id=admin_id,
                photo=open(path, "rb"),
                caption=f"📸 Reference from user {uid}",
            )
        except Exception as e:
            log.warning("⚠️ Failed to send reference to admin: %s", e)

    # Always detect closest Mage aspect for EVERY pipeline (Guava/Grok/GPT/Mango).
    # Previously posing/gpt forced aspect="auto" → later coerced to 1:1.
    try:
        aspect = get_closest_aspect_ratio(path)
    except Exception as e:
        log.error("❌ Failed to detect aspect: %s", e)
        aspect = DEF_ASPECT
    if aspect not in ASPECTS:
        aspect = DEF_ASPECT

    log.info(
        "✅ Image ready for %s (aspect=%s, no letterboxing)",
        ctx.user_data.get("pipeline") or "guava",
        aspect,
    )
    return {
        "image_path": path,
        "aspect": aspect,
        "raw_path": path,
        "letterboxed": False,
    }


async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    """Start — choose single or bulk mode."""
    log.info("/start from user %s", update.effective_user.id if update.effective_user else "?")
    if not await _check_admin_access(update, ctx):
        return ConversationHandler.END

    uid = update.effective_user.id
    if await _reject_if_user_busy(update, uid):
        return ASK_IMAGE
    if await _reject_if_user_on_cooldown(update, uid):
        return ASK_IMAGE
    
    chat_id = update.effective_chat.id
    _register_user(chat_id)
    
    _cleanup_single_images(ctx.user_data)
    _cleanup_bulk_images(ctx.user_data)
    ctx.user_data.clear()
    ctx.user_data["mode"] = "sending_photos"
    ctx.user_data["prompt"] = DEFAULT_IMAGE_PROMPT
    
    await update.message.reply_text(
        "Choose how you want to generate:",
        reply_markup=get_mode_keyboard(),
    )
    
    return ASK_MODE_SELECT


async def cmd_generate(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    """Alias for /start to maintain backward compatibility."""
    if not await _check_admin_access(update, ctx):
        return ConversationHandler.END
    
    return await cmd_start(update, ctx)



async def got_prompt(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    """Unused in simplified flow. Redirect text input to info message."""
    if not await _check_admin_access(update, ctx):
        return ConversationHandler.END
    
    uid = update.effective_user.id
    
    remaining = _user_cooldown_remaining(uid)
    if remaining > 0:
        await update.message.reply_text(
            f"⏳ Please wait *{int(remaining)+1}s* before sending another request.",
            parse_mode="Markdown"
        )
        return ASK_IMAGE

    await update.message.reply_text(
        "📸 Please send a *photo* to generate an image from it!",
        parse_mode="Markdown"
    )
    return ASK_IMAGE


async def handle_mode_select(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    """Choose single-image or bulk batch mode."""
    if not await _check_admin_access(update, ctx):
        return ConversationHandler.END

    query = update.callback_query
    await query.answer()
    uid = update.effective_user.id

    if await _reject_if_user_busy(update, uid):
        return ASK_MODE_SELECT
    if await _reject_if_user_on_cooldown(update, uid):
        return ASK_MODE_SELECT

    if query.data == "mode_bulk":
        # Bulk mode temporarily disabled
        await query.answer("📦 Bulk mode is temporarily unavailable.", show_alert=True)
        return ASK_MODE_SELECT

    if query.data == "mode_guava15_bulk":
        await query.answer("📦 Guava 1.5 Bulk is temporarily unavailable.", show_alert=True)
        return ASK_MODE_SELECT

    if query.data == "mode_mango3_bulk":
        await query.answer("📦 Mango 3 Bulk is temporarily unavailable.", show_alert=True)
        return ASK_MODE_SELECT

    if query.data == "mode_gpt_image_bulk":
        await query.answer("📦 GPT Image 2 Bulk is temporarily unavailable.", show_alert=True)
        return ASK_MODE_SELECT

    if query.data == "mode_posing_bulk":
        await query.answer("📦 Bulk Posing is temporarily unavailable.", show_alert=True)
        return ASK_MODE_SELECT

    if query.data == "mode_single":
        _cleanup_single_images(ctx.user_data)
        ctx.user_data["flow"] = "single"
        ctx.user_data["pipeline"] = "guava"
        log.info("📸 User %d chose SINGLE mode", uid)
        await query.edit_message_text(
            "Send one or more reference photos. Tap Done when ready.",
            parse_mode="Markdown",
        )
        return ASK_IMAGE

    if query.data == "mode_bulk":
        _cleanup_single_images(ctx.user_data)
        _cleanup_bulk_images(ctx.user_data)
        ctx.user_data["flow"] = "bulk"
        ctx.user_data["pipeline"] = "guava"
        ctx.user_data["bulk_images"] = []
        log.info("📦 User %d chose BULK mode", uid)
        await query.edit_message_text(
            f"📦 *Bulk mode*\n\n"
            f"Send all your reference photos (up to {MAX_BULK_IMAGES}).\n"
            "When finished, tap *Done*.",
            parse_mode="Markdown",
        )
        return ASK_BULK_IMAGES

    if query.data == "mode_guava15":
        _cleanup_single_images(ctx.user_data)
        ctx.user_data["flow"] = "single"
        ctx.user_data["pipeline"] = "guava15"
        log.info("🥭 User %d chose GUAVA 1.5 ENHANCED (single)", uid)
        await query.edit_message_text(
            "🥭 *Guava Pro 1.5 Enhanced*\n\n"
            "Send one or more reference photos. Tap Done when ready.",
            parse_mode="Markdown",
        )
        return ASK_IMAGE

    if query.data == "mode_guava15_bulk":
        _cleanup_single_images(ctx.user_data)
        _cleanup_bulk_images(ctx.user_data)
        ctx.user_data["flow"] = "bulk"
        ctx.user_data["pipeline"] = "guava15"
        ctx.user_data["bulk_images"] = []
        log.info("🥭📦 User %d chose GUAVA 1.5 BULK", uid)
        await query.edit_message_text(
            f"🥭📦 *Guava 1.5 Bulk*\n\n"
            f"Send all your reference photos (up to {MAX_BULK_IMAGES}).\n"
            "When finished, tap *Done*.",
            parse_mode="Markdown",
        )
        return ASK_BULK_IMAGES

    if query.data == "mode_posing":
        _cleanup_single_images(ctx.user_data)
        ctx.user_data["flow"] = "posing"
        ctx.user_data["pipeline"] = "posing"
        log.info("🧘 User %d chose POSING mode", uid)
        await query.edit_message_text(
            "*Posing*\n\nSend one or more reference photos. Tap Done when ready.",
            parse_mode="Markdown",
        )
        return ASK_IMAGE

    if query.data == "mode_posing_bulk":
        _cleanup_single_images(ctx.user_data)
        _cleanup_bulk_images(ctx.user_data)
        ctx.user_data["flow"] = "bulk"
        ctx.user_data["pipeline"] = "posing"
        ctx.user_data["bulk_images"] = []
        log.info("🧘📦 User %d chose BULK POSING mode", uid)
        await query.edit_message_text(
            f"🧘 *Bulk Posing*\n\n"
            f"Send all your reference photos (up to {MAX_BULK_IMAGES}).\n"
            "When finished, tap *Done*.",
            parse_mode="Markdown",
        )
        return ASK_BULK_IMAGES

    if query.data == "mode_video":
        _cleanup_single_images(ctx.user_data)
        ctx.user_data["flow"] = "video"
        ctx.user_data["pipeline"] = "video"
        log.info("🎬 User %d chose VIDEO mode", uid)
        await query.edit_message_text(
            "*Video mode*\n\nSend one or more reference photos. Tap Done when ready.",
            parse_mode="Markdown",
        )
        return ASK_IMAGE

    if query.data == "mode_mango3":
        _cleanup_single_images(ctx.user_data)
        ctx.user_data["flow"] = "single"
        ctx.user_data["pipeline"] = "mango3"
        log.info("🥭 User %d chose MANGO 3 mode", uid)
        await query.edit_message_text(
            "🥭 *Mango 3*\n\nSend one or more reference photos. Tap Done when ready.",
            parse_mode="Markdown",
        )
        return ASK_IMAGE

    if query.data == "mode_mango3_bulk":
        _cleanup_single_images(ctx.user_data)
        _cleanup_bulk_images(ctx.user_data)
        ctx.user_data["flow"] = "bulk"
        ctx.user_data["pipeline"] = "mango3"
        ctx.user_data["bulk_images"] = []
        log.info("🥭📦 User %d chose BULK MANGO 3 mode", uid)
        await query.edit_message_text(
            f"🥭📦 *Bulk Mango 3*\n\n"
            f"Send all your reference photos (up to {MAX_BULK_IMAGES}).\n"
            "When finished, tap *Done*.",
            parse_mode="Markdown",
        )
        return ASK_BULK_IMAGES

    if query.data == "mode_gpt_image":
        _cleanup_single_images(ctx.user_data)
        ctx.user_data["flow"] = "single"
        ctx.user_data["pipeline"] = "gpt_image"
        log.info("🎨 User %d chose GPT IMAGE 2 mode", uid)
        await query.edit_message_text(
            "🎨 *GPT Image 2*\n\nSend one or more reference photos. Tap Done when ready.",
            parse_mode="Markdown",
        )
        return ASK_IMAGE

    if query.data == "mode_gpt_image_bulk":
        _cleanup_single_images(ctx.user_data)
        _cleanup_bulk_images(ctx.user_data)
        ctx.user_data["flow"] = "bulk"
        ctx.user_data["pipeline"] = "gpt_image"
        ctx.user_data["bulk_images"] = []
        log.info("🎨📦 User %d chose BULK GPT IMAGE 2 mode", uid)
        await query.edit_message_text(
            f"🎨 *Bulk GPT Image 2*\n\n"
            f"Send all your reference photos (up to {MAX_BULK_IMAGES}).\n"
            "When finished, tap *Done*.",
            parse_mode="Markdown",
        )
        return ASK_BULK_IMAGES

    return ASK_MODE_SELECT


async def got_bulk_image(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    """Collect reference images for a bulk batch."""
    if not await _check_admin_access(update, ctx):
        return ConversationHandler.END

    uid = update.effective_user.id
    if await _reject_if_user_busy(update, uid):
        return ASK_BULK_IMAGES
    if await _reject_if_user_on_cooldown(update, uid):
        return ASK_BULK_IMAGES

    chat_id = update.effective_chat.id
    _register_user(chat_id)

    meta = await _download_and_preprocess_photo(update, ctx, uid)
    if not meta:
        await update.message.reply_text("❌ Failed to download image")
        return ASK_BULK_IMAGES

    bulk_images = ctx.user_data.setdefault("bulk_images", [])
    if len(bulk_images) >= MAX_BULK_IMAGES:
        await update.message.reply_text(
            f"⚠️ Maximum {MAX_BULK_IMAGES} images reached. Tap Done to continue.",
            reply_markup=get_bulk_done_keyboard(len(bulk_images)),
        )
        return ASK_BULK_IMAGES

    bulk_images.append(meta)
    ctx.user_data["chat_id"] = chat_id
    ctx.user_data["uid"] = uid
    ctx.user_data["flow"] = "bulk"

    count = len(bulk_images)
    bulk_label = _bulk_collect_label(ctx)
    status_text = (
        f"{'🧘' if _is_posing_pipeline(ctx) else '📦'} *{bulk_label}* — "
        f"{count} image{'s' if count != 1 else ''} collected.\n"
        "Send more photos or tap Done when ready."
    )
    bulk_msg_id = ctx.user_data.get("bulk_status_msg_id")
    try:
        if bulk_msg_id:
            await ctx.bot.edit_message_text(
                chat_id=chat_id,
                message_id=bulk_msg_id,
                text=status_text,
                parse_mode="Markdown",
                reply_markup=get_bulk_done_keyboard(count),
            )
        else:
            msg = await update.message.reply_text(
                status_text,
                parse_mode="Markdown",
                reply_markup=get_bulk_done_keyboard(count),
            )
            ctx.user_data["bulk_status_msg_id"] = msg.message_id
    except Exception:
        msg = await update.message.reply_text(
            status_text,
            parse_mode="Markdown",
            reply_markup=get_bulk_done_keyboard(count),
        )
        ctx.user_data["bulk_status_msg_id"] = msg.message_id
    return ASK_BULK_IMAGES


async def handle_bulk_done(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    """Finish collecting bulk images and move to prompt selection."""
    if not await _check_admin_access(update, ctx):
        return ConversationHandler.END

    query = update.callback_query
    await query.answer()
    uid = update.effective_user.id

    if query.data == "bulk_cancel":
        _cleanup_bulk_images(ctx.user_data)
        ctx.user_data.pop("bulk_images", None)
        await query.edit_message_text(
            "Cancelled. Choose mode again:",
            reply_markup=get_mode_keyboard(),
        )
        return ASK_MODE_SELECT

    bulk_images = ctx.user_data.get("bulk_images", [])
    if not bulk_images:
        await query.answer("Send at least one photo first.", show_alert=True)
        return ASK_BULK_IMAGES

    count = len(bulk_images)
    pipeline = ctx.user_data.get("pipeline", "guava")
    log.info(
        "📦 User %d finished bulk upload (%d images, pipeline=%s)",
        uid, count, pipeline,
    )
    prefix = "🧘" if pipeline == "posing" else "📦"
    await query.edit_message_text(
        f"{prefix} {count} image{'s' if count != 1 else ''} ready.\nType your prompt:"
    )
    return ASK_CUSTOM_PROMPT


async def got_image(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    if not await _check_admin_access(update, ctx):
        return ConversationHandler.END

    uid = update.effective_user.id
    if await _reject_if_user_busy(update, uid):
        return ASK_IMAGE
    if await _reject_if_user_on_cooldown(update, uid):
        return ASK_IMAGE

    chat_id = update.effective_chat.id
    _register_user(chat_id)

    meta = await _download_and_preprocess_photo(update, ctx, uid)
    if not meta:
        await update.message.reply_text("❌ Failed to download image")
        return ASK_IMAGE

    refs = ctx.user_data.setdefault("single_images", [])
    if len(refs) >= MAX_SINGLE_REFERENCES:
        _cleanup_image_meta(meta)
        await update.message.reply_text(
            f"Maximum {MAX_SINGLE_REFERENCES} references reached. Tap Done to continue.",
            reply_markup=get_reference_done_keyboard(len(refs)),
        )
        return ASK_IMAGE

    refs.append(meta)
    if len(refs) == 1:
        ctx.user_data["image_path"] = meta["image_path"]
        ctx.user_data["aspect"] = meta["aspect"]
        ctx.user_data["raw_image_path"] = meta.get("raw_path")

    ctx.user_data["chat_id"] = chat_id
    ctx.user_data["uid"] = uid
    pipeline = ctx.user_data.get("pipeline", "guava")
    if pipeline not in ("posing", "video"):
        ctx.user_data["flow"] = "single"

    count = len(refs)
    label = (
        "Video references" if pipeline == "video"
        else ("Posing references" if pipeline == "posing"
        else ("Mango 3 references" if pipeline == "mango3"
        else ("GPT Image 2 references" if pipeline == "gpt_image"
        else ("Guava 1.5 references" if pipeline == "guava15" else "References"))))
    )
    status_text = (
        f"{label}: {count} reference{'s' if count != 1 else ''} collected.\n"
        "Send more photos, tap Done, or type your prompt."
    )
    status_msg_id = ctx.user_data.get("single_refs_status_msg_id")
    try:
        if status_msg_id:
            await ctx.bot.edit_message_text(
                chat_id=chat_id,
                message_id=status_msg_id,
                text=status_text,
                reply_markup=get_reference_done_keyboard(count),
            )
        else:
            msg = await update.message.reply_text(
                status_text,
                reply_markup=get_reference_done_keyboard(count),
            )
            ctx.user_data["single_refs_status_msg_id"] = msg.message_id
    except Exception:
        msg = await update.message.reply_text(
            status_text,
            reply_markup=get_reference_done_keyboard(count),
        )
        ctx.user_data["single_refs_status_msg_id"] = msg.message_id

    return ASK_IMAGE


def _sync_single_ref_primary(user_data: dict) -> None:
    """Point image_path/aspect at the first collected reference."""
    refs = user_data.get("single_images") or []
    if not refs:
        return
    first = refs[0]
    user_data["image_path"] = first.get("image_path")
    user_data["aspect"] = first.get("aspect")
    user_data["raw_image_path"] = first.get("raw_path")
    user_data.pop("single_refs_status_msg_id", None)


async def got_prompt_after_refs(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    """Accept prompt while still collecting refs — skips Done button."""
    if not await _check_admin_access(update, ctx):
        return ConversationHandler.END
    if not ctx.user_data.get("single_images"):
        await update.message.reply_text("📸 Send at least one reference photo first.")
        return ASK_IMAGE
    _sync_single_ref_primary(ctx.user_data)
    return await got_custom_prompt(update, ctx)


async def handle_single_refs_done(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    """Finish collecting references for a normal single-output generation."""
    if not await _check_admin_access(update, ctx):
        return ConversationHandler.END

    query = update.callback_query
    await query.answer()

    if query.data == "refs_cancel":
        _cleanup_single_images(ctx.user_data)
        await query.edit_message_text(
            "Cancelled. Choose mode again:",
            reply_markup=get_mode_keyboard(),
        )
        return ASK_MODE_SELECT

    refs = ctx.user_data.get("single_images", [])
    if not refs:
        await query.answer("Send at least one photo first.", show_alert=True)
        return ASK_IMAGE

    _sync_single_ref_primary(ctx.user_data)

    await query.edit_message_text("Type your prompt:")
    return ASK_CUSTOM_PROMPT


def _is_bulk_flow(ctx: ContextTypes.DEFAULT_TYPE) -> bool:
    return ctx.user_data.get("flow") == "bulk" and bool(ctx.user_data.get("bulk_images"))


async def _offer_guava_version_or_queue(
    ctx: ContextTypes.DEFAULT_TYPE,
    uid: int,
    prompt: str,
    *,
    mode_label: str,
    status_msg,
) -> int:
    """For single/bulk guava flows, show V1/V2 picker before queueing."""
    pipeline = ctx.user_data.get("pipeline", "guava")
    if pipeline in ("posing", "video", "guava15", "gpt_image", "mango3"):
        return await _queue_generation_job(
            ctx, uid, prompt, mode_label=mode_label, status_msg=status_msg
        )
    ctx.user_data["pending_prompt"] = prompt
    ctx.user_data["pending_mode_label"] = mode_label
    await status_msg.edit_text(
        "🥭 Choose model:",
        reply_markup=get_guava_version_keyboard(),
    )
    return ASK_GUAVA_VERSION


def _extract_and_strip_aspect_from_prompt(prompt: str) -> tuple[str, str | None]:
    if not prompt:
        return prompt, None
    m = re.search(r"(?i)\baspect\s+([0-9]+[:/][0-9]+)\b", prompt)
    if m:
        extracted = m.group(1).replace("/", ":")
        clean = re.sub(r"(?i)\baspect\s+[0-9]+[:/][0-9]+\b", "", prompt).strip()
        if extracted not in ASPECTS:
            try:
                w, h = map(float, extracted.split(":"))
                ratio = w / h
                closest = min(ASPECTS, key=lambda a: abs((float(a.split(':')[0]) / float(a.split(':')[1])) - ratio))
                extracted = closest
            except:
                pass
        return clean, extracted
    return prompt, None


async def _queue_generation_job(
    ctx: ContextTypes.DEFAULT_TYPE,
    uid: int,
    prompt: str,
    *,
    mode_label: str,
    status_msg,
    prompt_mode: str | None = None,
) -> int:
    """Queue a generation job and return the next conversation state."""
    if uid in STRICT_QUEUE_USER_IDS and await _user_has_pending_jobs(uid):
        await status_msg.edit_text(_BUSY_USER_MSG)
        return ASK_IMAGE

    cooldown_left = _user_cooldown_remaining(uid)
    if cooldown_left > 0:
        await status_msg.edit_text(_cooldown_message(cooldown_left))
        return ASK_IMAGE

    if _is_bulk_flow(ctx):
        return await _queue_bulk_generation_jobs(
            ctx, uid, prompt, mode_label=mode_label, status_msg=status_msg,
            prompt_mode=prompt_mode or ctx.user_data.get("prompt_mode", "preserve"),
        )

    prompt, custom_aspect = _extract_and_strip_aspect_from_prompt(prompt)

    single_refs = [
        meta for meta in ctx.user_data.get("single_images", [])
        if isinstance(meta, dict) and meta.get("image_path")
    ]
    first_ref = single_refs[0] if single_refs else {}
    image_path = first_ref.get("image_path") or ctx.user_data.get("image_path")
    aspect = custom_aspect or first_ref.get("aspect") or ctx.user_data.get("aspect")
    raw_image_path = first_ref.get("raw_path") or ctx.user_data.get("raw_image_path")
    reference_image_paths = [meta["image_path"] for meta in single_refs] or ([image_path] if image_path else [])
    raw_reference_image_paths = [
        meta["raw_path"] for meta in single_refs if meta.get("raw_path")
    ] or ([raw_image_path] if raw_image_path else [])
    reference_letterboxed = (
        any(_meta_reference_letterboxed(meta) for meta in single_refs)
        or _meta_reference_letterboxed(first_ref)
        or (isinstance(image_path, str) and "_processed" in image_path)
    )
    chat_id = ctx.user_data.get("chat_id") or status_msg.chat_id
    status_msg_id = status_msg.message_id

    job_id = f"job_{uid}_{int(time.time() * 1000)}"
    persisted_refs = _persist_job_reference_paths(job_id, reference_image_paths)
    persisted_raw_refs = _persist_job_reference_paths(f"{job_id}_raw", raw_reference_image_paths)
    if reference_image_paths and not persisted_refs:
        await status_msg.edit_text("❌ Reference image files missing. Please send photos again.")
        return ASK_IMAGE

    job = Job(
        id=job_id,
        chat_id=chat_id,
        user_id=uid,
        prompt=prompt,
        image_path=persisted_refs[0] if persisted_refs else image_path,
        aspect=aspect,
        status_msg_id=status_msg_id,
        raw_image_path=persisted_raw_refs[0] if persisted_raw_refs else raw_image_path,
        reference_image_paths=persisted_refs or reference_image_paths,
        raw_reference_image_paths=persisted_raw_refs or raw_reference_image_paths,
        pipeline=ctx.user_data.get("pipeline", "guava"),
        prompt_mode=prompt_mode or ctx.user_data.pop("prompt_mode", "preserve"),
        reference_letterboxed=reference_letterboxed,
    )

    try:
        added = await queue_manager.add_job(job)
        if added:
            log.info("✅ Job %s queued for user %d (%s: %.80s...)", job.id, uid, mode_label, prompt)
            _cleanup_single_images(ctx.user_data)
        else:
            _remove_job_reference_files(job)
            log.error("❌ Failed to queue job: user may have active job or queue full")
            busy_msg = _BUSY_USER_MSG if uid in STRICT_QUEUE_USER_IDS else (
                "❌ Queue full or you already have an image processing. Please wait."
            )
            await status_msg.edit_text(busy_msg)
    except Exception as e:
        log.error("❌ Error queuing job: %s", e)
        await status_msg.edit_text("❌ Error queueing request. Please try again.")

    return ASK_IMAGE


async def _queue_bulk_generation_jobs(
    ctx: ContextTypes.DEFAULT_TYPE,
    uid: int,
    prompt: str,
    *,
    mode_label: str,
    status_msg,
    prompt_mode: str = "preserve",
) -> int:
    """Queue one job per bulk image, same prompt, processed sequentially."""
    bulk_images = ctx.user_data.get("bulk_images", [])
    if not bulk_images:
        await status_msg.edit_text("❌ No images in bulk batch. Use /start to try again.")
        return ASK_MODE_SELECT

    prompt, custom_aspect = _extract_and_strip_aspect_from_prompt(prompt)

    chat_id = ctx.user_data.get("chat_id") or status_msg.chat_id
    bulk_total = len(bulk_images)
    batch_id = f"bulk_{uid}_{int(time.time() * 1000)}"
    status_msg_id = status_msg.message_id

    bulk_prompt_mode = ctx.user_data.pop("prompt_mode", prompt_mode)

    # Pre-build all Job objects first so bulk_total is correct before any worker
    # can pick up a job — avoids a race where job #1 is dequeued with bulk_total=0.
    queued = 0
    created_jobs: list[Job] = []
    pending_jobs: list[Job] = []  # built but not yet enqueued
    for idx, meta in enumerate(bulk_images, start=1):
        job_id = f"{batch_id}_{idx}"
        persisted_image = _persist_job_reference_paths(job_id, [meta["image_path"]])
        raw_path = meta.get("raw_path")
        persisted_raw = (
            _persist_job_reference_paths(f"{job_id}_raw", [raw_path]) if raw_path else []
        )
        if not persisted_image:
            log.error("❌ Bulk image %d missing on disk for user %d", idx, uid)
            break
        job = Job(
            id=job_id,
            chat_id=chat_id,
            user_id=uid,
            prompt=prompt,
            image_path=persisted_image[0],
            aspect=custom_aspect or meta["aspect"],
            status_msg_id=status_msg_id,
            raw_image_path=persisted_raw[0] if persisted_raw else raw_path,
            is_bulk=True,
            bulk_batch_id=batch_id,
            bulk_index=idx,
            bulk_total=bulk_total,  # set correctly upfront — no post-patch race
            pipeline=ctx.user_data.get("pipeline", "guava"),
            prompt_mode=bulk_prompt_mode,
            reference_letterboxed=bool(meta.get("letterboxed")) or (
                isinstance(meta.get("image_path"), str) and "_processed" in meta["image_path"]
            ),
        )
        pending_jobs.append(job)

    # Now enqueue — bulk_total is already correct on every job object
    for job in pending_jobs:
        try:
            if await queue_manager.add_job(job, priority=1):
                created_jobs.append(job)
                queued += 1
            else:
                log.error("❌ Bulk queue full at image %d/%d for user %d", job.bulk_index, bulk_total, uid)
                _remove_job_reference_files(job)
                break
        except Exception as e:
            log.error("❌ Error queuing bulk job %d: %s", job.bulk_index, e)
            _remove_job_reference_files(job)
            break

    # Update bulk_total on queued jobs to reflect actual count enqueued
    # (may differ from bulk_total if queue was full partway through)
    for job in created_jobs:
        job.bulk_total = queued

    for meta in bulk_images[queued:]:
        _cleanup_image_meta(meta)

    if queued:
        if TARGET_POOL_SIZE > 0 and queued > 1:
            _ensure_pool_replacement(reason="bulk-batch", owner_uid=uid)
        log.info(
            "✅ Bulk batch %s queued for user %d (%s): %d/%d images",
            batch_id, uid, mode_label, queued, bulk_total,
        )
        pipeline = ctx.user_data.get("pipeline", "guava")
        bulk_icon = "🧘" if pipeline == "posing" else "📦"
        bulk_label = "Bulk Posing" if pipeline == "posing" else "Bulk"
        if queued < bulk_total:
            status_text = (
                f"⚠️ Queue limit: only {queued}/{bulk_total} images queued.\n"
                f"{bulk_icon} {bulk_label} editing... (1/{queued})"
            )
        else:
            status_text = (
                f"{bulk_icon} {bulk_label} queued: {queued} image{'s' if queued != 1 else ''}\n"
                f"{bulk_icon} {bulk_label} editing... (1/{queued})"
            )
        await status_msg.edit_text(status_text)
        for meta in bulk_images[:queued]:
            _cleanup_image_meta(meta)
        ctx.user_data.pop("bulk_images", None)
        ctx.user_data.pop("bulk_status_msg_id", None)
    else:
        _cleanup_bulk_images(ctx.user_data)
        await status_msg.edit_text("❌ Queue full. Please wait and try again.")

    return ASK_MODE_SELECT


async def handle_video_prompt(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    """Video mode: ask user to type a custom prompt (no preset options)."""
    if not await _check_admin_access(update, ctx):
        return ConversationHandler.END

    query = update.callback_query
    await query.answer()

    uid = update.effective_user.id
    if await _reject_if_user_on_cooldown(update, uid):
        return ASK_PROMPT_MODE

    log.info("✏️ User %d in VIDEO mode — asking for custom prompt", uid)
    await query.edit_message_text("Type your video prompt:")
    return ASK_CUSTOM_PROMPT


async def handle_prompt_mode(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle prompt mode selection (Auto, Custom, Templates, or Random)."""
    if not await _check_admin_access(update, ctx):
        return ConversationHandler.END

    query = update.callback_query
    await query.answer()

    uid = update.effective_user.id

    if query.data == "prompt_auto":
        log.info("🤖 User %d chose AUTO mode", uid)
        status_msg = await query.edit_message_text(TG_EDITING_TEXT)
        return await _offer_guava_version_or_queue(
            ctx, uid, DEFAULT_IMAGE_PROMPT, mode_label="AUTO mode", status_msg=status_msg
        )

    if query.data == "prompt_custom":
        log.info("✏️ User %d chose CUSTOM mode", uid)
        await query.edit_message_text("Type your prompt:")
        return ASK_CUSTOM_PROMPT

    if query.data == "prompt_templates":
        log.info("📚 User %d opened template library", uid)
        await query.edit_message_text(
            "📚 *Fast Prompt Templates*\nPick a category:",
            parse_mode="Markdown",
            reply_markup=get_category_keyboard(),
        )
        return ASK_TEMPLATES

    if query.data == "prompt_random":
        label, prompt, cat_idx, tpl_idx = get_random_template()
        log.info("🎲 User %d chose random template [%s:%s] %s", uid, cat_idx, tpl_idx, label)
        status_msg = await query.edit_message_text(
            f"📚 *{label}*\n\n{TG_EDITING_TEXT}",
            parse_mode="Markdown",
        )
        return await _offer_guava_version_or_queue(
            ctx, uid, prompt, mode_label=f"RANDOM TEMPLATE {label}", status_msg=status_msg
        )

    return ASK_IMAGE


async def handle_templates(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    """Browse template categories and fire one-click prompts."""
    if not await _check_admin_access(update, ctx):
        return ConversationHandler.END

    query = update.callback_query
    await query.answer()
    uid = update.effective_user.id
    data = query.data

    if data == "tplback:menu":
        await query.edit_message_text(
            "Choose prompt mode:",
            reply_markup=get_prompt_mode_keyboard(),
        )
        return ASK_PROMPT_MODE

    if data == "tplback:cats":
        await query.edit_message_text(
            "📚 *Fast Prompt Templates*\nPick a category:",
            parse_mode="Markdown",
            reply_markup=get_category_keyboard(),
        )
        return ASK_TEMPLATES

    if data.startswith("tplcat:"):
        cat_idx = int(data.split(":", 1)[1])
        title = PROMPT_TEMPLATE_CATEGORIES[cat_idx]["title"]
        await query.edit_message_text(
            f"📚 *{title}*\nPick a template:",
            parse_mode="Markdown",
            reply_markup=get_template_keyboard(cat_idx),
        )
        return ASK_TEMPLATES

    if data.startswith("tplpick:"):
        _, cat_idx, tpl_idx = data.split(":")
        cat_idx, tpl_idx = int(cat_idx), int(tpl_idx)
        label, prompt = get_template_prompt(cat_idx, tpl_idx)
        log.info("📚 User %d chose template [%s] %s", uid, cat_idx, label)
        status_msg = await query.edit_message_text(
            f"📚 *{label}*\n\n{TG_EDITING_TEXT}",
            parse_mode="Markdown",
        )
        return await _offer_guava_version_or_queue(
            ctx, uid, prompt, mode_label=f"TEMPLATE {label}", status_msg=status_msg
        )

    return ASK_TEMPLATES


async def handle_guava_version(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    """Single/bulk: choose V1  or V2  then queue."""
    if not await _check_admin_access(update, ctx):
        return ConversationHandler.END

    query = update.callback_query
    await query.answer()
    uid = update.effective_user.id

    if await _reject_if_user_busy(update, uid):
        return ASK_GUAVA_VERSION
    if await _reject_if_user_on_cooldown(update, uid):
        return ASK_GUAVA_VERSION

    if query.data == "guava_v1":
        ctx.user_data["pipeline"] = "guava"
        log.info("🥭 User %d chose Guava V1 (Pro Fast)", uid)
    elif query.data == "guava_v2":
        ctx.user_data["pipeline"] = "guava15"
        log.info("🥭 User %d chose Guava V2 (Pro 1.5)", uid)
    else:
        return ASK_GUAVA_VERSION

    prompt = ctx.user_data.pop("pending_prompt", None)
    mode_label = ctx.user_data.pop("pending_mode_label", "AUTO mode")
    if not prompt:
        await query.edit_message_text("❌ Session expired. Use /start to try again.")
        return ASK_MODE_SELECT

    status_msg = await query.edit_message_text(TG_EDITING_TEXT)
    return await _queue_generation_job(
        ctx, uid, prompt, mode_label=mode_label, status_msg=status_msg
    )


async def got_custom_prompt(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    """Receive custom prompt from user."""
    if not await _check_admin_access(update, ctx):
        return ConversationHandler.END
    
    uid = update.effective_user.id
    custom_prompt = update.message.text
    
    if not custom_prompt or len(custom_prompt.strip()) == 0:
        await update.message.reply_text("❌ Prompt cannot be empty. Please try again.")
        return ASK_CUSTOM_PROMPT
    
    log.info("📝 User %d provided custom prompt (%d chars)", uid, len(custom_prompt))

    if ctx.user_data.get("pipeline") == "video":
        ctx.user_data["prompt_mode"] = "video"
    else:
        ctx.user_data["prompt_mode"] = "custom"
    status_msg = await update.message.reply_text(TG_EDITING_TEXT)
    pipeline = ctx.user_data.get("pipeline", "guava")
    if pipeline == "video":
        mode_label = "VIDEO CUSTOM"
    elif pipeline == "guava15":
        mode_label = "GUAVA 1.5 CUSTOM"
    else:
        mode_label = "CUSTOM mode"
    if pipeline == "video":
        return await _queue_generation_job(
            ctx, uid, custom_prompt, mode_label=mode_label, status_msg=status_msg,
            prompt_mode="video",
        )
    return await _offer_guava_version_or_queue(
        ctx, uid, custom_prompt, mode_label=mode_label, status_msg=status_msg
    )


async def skip_image(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    """Unused in simplified flow."""
    await update.message.reply_text(
        "📸 Please send a *photo* to get started!",
        parse_mode="Markdown"
    )
    return ASK_IMAGE


async def got_aspect(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    """Unused in simplified flow. Aspect is auto-detected from image."""
    if not await _check_admin_access(update, ctx):
        return ConversationHandler.END
    
    query = update.callback_query
    await query.answer()
    await query.edit_message_text(
        "✅ Generation queued. Send the next photo anytime!"
    )
    return ASK_IMAGE




async def cmd_cancel(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    if not await _check_admin_access(update, ctx):
        return ConversationHandler.END

    user_id = update.effective_user.id

    # 1️⃣ Raise the cancel flag BEFORE draining the queue so any worker that
    #    picks up a job in the tiny race window also sees it immediately.
    _user_cancel_flags.add(user_id)

    # 2️⃣ Drain all queued + mark active jobs cancelled
    drained = await queue_manager.cancel_all_user_jobs(user_id)

    # 3️⃣ Clean up conversation state
    _cleanup_single_images(ctx.user_data)
    _cleanup_bulk_images(ctx.user_data)
    ctx.user_data.clear()
    ctx.user_data["mode"] = "sending_photos"
    ctx.user_data["prompt"] = DEFAULT_IMAGE_PROMPT

    # 4️⃣ Build reply
    if drained:
        cancel_text = (
            f"🚫 *Cancelled* — {drained} queued job{'s' if drained != 1 else ''} removed.\n"
            "Any running generation will stop within seconds.\n\n"
            "Use /start to begin a new session."
        )
    else:
        cancel_text = (
            "🚫 *Cancelled.* Any running generation will stop within seconds.\n\n"
            "Use /start to begin a new session."
        )

    await update.message.reply_text(
        cancel_text,
        parse_mode="Markdown",
        reply_markup=get_mode_keyboard(),
    )

    # 5️⃣ Clear the cancel flag after 10 s — long enough for any worker to exit
    async def _clear_flag_later():
        await asyncio.sleep(10)
        _user_cancel_flags.discard(user_id)
        log.debug("🔓 Cancel flag cleared for user %d", user_id)

    asyncio.create_task(_clear_flag_later())
    return ASK_MODE_SELECT


async def cmd_cancel_job(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Cancel one queued job by full job ID or unique prefix."""
    if not await _check_admin_access(update, ctx):
        return

    if not ctx.args:
        await update.message.reply_text("Usage: /cancel_job <job id prefix>")
        return

    prefix = ctx.args[0].strip()
    job = await queue_manager.cancel_queued_job(prefix)
    if not job:
        await update.message.reply_text(
            "No queued job matched that prefix. Active jobs cannot be interrupted."
        )
        return

    _remove_job_reference_files(job)
    try:
        if job.status_msg_id:
            await ctx.bot.edit_message_text(
                chat_id=job.chat_id,
                message_id=job.status_msg_id,
                text="Cancelled before processing.",
            )
    except Exception as e:
        log.debug("Could not update cancelled job status message: %s", e)

    await update.message.reply_text(f"Cancelled queued job `{job.id}`", parse_mode="Markdown")


async def handle_moderation_cancel(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle the cancel button click during moderation retry loop."""
    if not await _check_admin_access(update, ctx):
        return ConversationHandler.END
    
    query = update.callback_query
    await query.answer()
    
    _cleanup_single_images(ctx.user_data)
    _cleanup_bulk_images(ctx.user_data)

    ctx.user_data.clear()
    ctx.user_data["mode"] = "sending_photos"
    ctx.user_data["prompt"] = DEFAULT_IMAGE_PROMPT
    
    await query.edit_message_text(
        "❌ Cancelled. Use /start to choose single or bulk mode.",
        reply_markup=get_mode_keyboard(),
    )
    return ASK_MODE_SELECT


async def cmd_set_admin(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not await _check_admin_access(update, ctx):
        return
    
    global _cached_admin_id
    chat_id = update.effective_chat.id
    _cached_admin_id = chat_id
    with open(DATA_DIR / "admin_group.txt", "w") as f:
        f.write(str(chat_id))
    await update.message.reply_text("✅ Admin logging bound to this group.")


async def _cleanup_old_files():
    """Periodically delete orphaned temp images older than 2 hours."""
    while True:
        await asyncio.sleep(3600)  # Run every hour
        cutoff = time.time() - 7200  # 2 hours old
        removed = 0
        failed = 0
        
        try:
            # Limit to prevent scanning huge directories
            all_files = list(DATA_DIR.iterdir())[:2000]
        except Exception as e:
            log.warning("🧹 Failed to list DATA_DIR: %s", e)
            continue
        
        for f in all_files:
            try:
                # Only process image files
                if f.is_file() and f.suffix.lower() in ('.jpg', '.jpeg', '.png', '.gif'):
                    # Get mtime with timeout
                    try:
                        mtime = f.stat().st_mtime
                    except OSError:
                        continue
                    
                    # Delete if older than cutoff
                    if mtime < cutoff:
                        try:
                            f.unlink()
                            removed += 1
                            log.debug("🧹 Deleted old temp file: %s", f.name)
                        except OSError as e:
                            # File may be in use - that's OK
                            failed += 1
                            log.debug("🧹 Could not delete (in use): %s", f.name)
            except Exception as e:
                log.debug("🧹 Cleanup error on file: %s", e)
        
        if removed > 0:
            log.info("🧹 Cleaned up %d old temp files (%d failed to delete)", removed, failed)


async def post_init(app: Application):
    """Spawn NUM_WORKERS workers, each with its own isolated browser session.
    Also start background maintenance loops."""
    await _prepare_telegram_transport(app)
    _spawn_background_task(_heartbeat_loop(), name="heartbeat")
    _spawn_background_task(_queue_maintenance_loop(), name="queue-maintenance")
    _spawn_background_task(_idle_status_loop(), name="idle-status")

    # Initialize account/session manager: load accounts, load existing sessions, and start background refill
    try:
        if acct_manager is not None:
            accounts_file = DATA_DIR / "accounts.json"
            if accounts_file.exists():
                try:
                    data = json.loads(accounts_file.read_text(encoding="utf-8"))
                    if isinstance(data, list):
                        mapping = {}
                        for item in data:
                            if isinstance(item, dict) and item.get("username"):
                                mapping[item["username"]] = item
                        acct_manager.add_accounts(mapping)
                    elif isinstance(data, dict):
                        acct_manager.add_accounts(data)
                except Exception as e:
                    log.warning("⚠️ Failed to load accounts.json: %s", e)
            
            acct_manager.load_existing_sessions()
            acct_manager.reset_in_use_on_boot()

            if FRESH_POOL_ON_BOOT and not _on_cloud:
                await _boot_fresh_pool_prep()
            else:
                acct_manager.purge_invalid()
                if MULTI_USER_ISOLATION:
                    legacy = acct_manager.assign_legacy_owners(sorted(ALLOWED_USER_IDS))
                    if legacy:
                        log.info("🔐 Assigned owner to %d legacy pooled session(s)", legacy)

            ready = _count_live_ready() if LIVE_ONLY_POOL else acct_manager.count_ready()
            pool_mode = "live-only fresh" if (FRESH_POOL_ON_BOOT and LIVE_ONLY_POOL) else (
                "live-only" if LIVE_ONLY_POOL else "disk"
            )
            log.info("🔐 Session pool: %d/%d ready (%s)", ready, TARGET_POOL_SIZE, pool_mode)
            if TARGET_POOL_SIZE > 0:
                for builder_id in range(PARALLEL_BUILDERS):
                    delay = BUILDER_BOOT_DELAY_SEC if builder_id > 0 else 0
                    _spawn_background_task(
                        _delayed_builder_start(delay, builder_id=builder_id),
                        name=f"session-builder-{builder_id}",
                    )
                _spawn_background_task(_pool_maintenance_loop(), name="pool-maintenance")
                if not (FRESH_POOL_ON_BOOT and not _on_cloud):
                    for uid in sorted(ALLOWED_USER_IDS):
                        if _pool_deficit(uid) > 0:
                            _ensure_pool_replacement(reason="boot", owner_uid=uid)
                log.info(
                    "🔐 Dedicated session builder started (%d parallel, target pool=%d)",
                    PARALLEL_BUILDERS, TARGET_POOL_SIZE,
                )
            else:
                log.info("🔐 Pool pre-building disabled (TARGET_POOL_SIZE=%d)", TARGET_POOL_SIZE)
    except Exception as e:
        log.warning("Account manager init failed: %s", e)

    for i in range(NUM_WORKERS):
        session = WorkerSession(worker_id=i)
        _spawn_background_task(_worker_loop(app, session), name=f"worker-{i}")
        if PREWARM_WORKERS > 0 and i < PREWARM_WORKERS:
            delay = 0 if i == 0 else PREWARM_STAGGER_SEC * i
            _spawn_background_task(_staggered_prewarm(session, delay_sec=delay), name=f"prewarm-{i}")

    _spawn_background_task(_cleanup_old_files(), name="cleanup-files")
    _spawn_background_task(_log_maildev_connectivity(), name="maildev-connectivity")
    
    log.info("✅ %d worker(s) started (%d pre-warmed browsers)", NUM_WORKERS, PREWARM_WORKERS)
    log.info("✅ Queue maintenance loop started")


from telegram.request import HTTPXRequest
from telegram.request._requestdata import RequestData

_TELEGRAM_PROXY_DISABLED = False


def _telegram_proxy_url() -> str:
    """Effective Telegram proxy base URL (workers.dev is unreachable from HF Spaces)."""
    url = os.getenv("TELEGRAM_PROXY_URL", "").strip().rstrip("/")
    if not url:
        return ""
    if _on_hf and ".workers.dev" in url and not _truthy_env("TELEGRAM_PROXY_FORCE"):
        return ""
    return url


def _telegram_skip_proxy_on_hf_boot() -> None:
    global _TELEGRAM_PROXY_DISABLED
    configured = os.getenv("TELEGRAM_PROXY_URL", "").strip().rstrip("/")
    if not _on_hf or not configured:
        return
    if ".workers.dev" in configured and not _truthy_env("TELEGRAM_PROXY_FORCE"):
        _TELEGRAM_PROXY_DISABLED = True
        log_startup.warning(
            "⚠️ HF Space: workers.dev Telegram proxy is blocked from Spaces — "
            "deploy proxies/vercel-telegram and set TELEGRAM_PROXY_URL to the Vercel URL"
        )


def _resolve_space_host() -> str:
    """HF Space hostname for inbound webhooks (username-spacename.hf.space)."""
    host = (
        os.getenv("SPACE_HOST", "").strip()
        or os.getenv("HF_SPACE_HOST", "").strip()
    )
    if host:
        if host.startswith("http"):
            host = host.split("://", 1)[-1].strip("/")
        return host.rstrip("/").lower()

    space_id = os.getenv("SPACE_ID", "").strip()
    if "/" in space_id:
        return (space_id.replace("/", "-") + ".hf.space").lower()

    repo = os.getenv("HF_REPO_ID", "").strip() or os.getenv("HF_SPACE_REPO", "").strip()
    if repo:
        if repo.startswith("http"):
            repo = repo.split("://", 1)[-1].strip("/")
        if "/" in repo:
            return (repo.replace("/", "-") + ".hf.space").lower()
        username = os.getenv("HF_USERNAME", "").strip()
        if username:
            return f"{username}-{repo}.hf.space".lower()

    space_name = os.getenv("HF_SPACE_NAME", "").strip()
    username = os.getenv("HF_USERNAME", "").strip()
    if space_name and username:
        return f"{username}-{space_name}.hf.space".lower()
    return ""


def _resolve_pa_host() -> str:
    """PythonAnywhere hostname for inbound webhooks."""
    host = os.getenv("PA_HOST", "").strip()
    if host:
        if host.startswith("http"):
            host = host.split("://", 1)[-1].strip("/")
        return host.rstrip("/").lower()
    return "moamed12.pythonanywhere.com"


def _use_pa_webhook() -> bool:
    if not _on_pa:
        return False
    if _falsey_env("TELEGRAM_WEBHOOK"):
        return False
    if _truthy_env("TELEGRAM_POLLING"):
        return False
    return _truthy_env("TELEGRAM_WEBHOOK") or bool(_resolve_pa_host())


def _ingress_webhook_url() -> str:
    if _on_pa:
        host = _resolve_pa_host()
    else:
        host = _resolve_space_host()
    if not host:
        log_startup.warning("⚠️ Ingress host not set — webhook URL may be invalid")
    return f"https://{host}{_telegram_webhook_path()}"


def _use_hf_polling() -> bool:
    """On HF, prefer inbound webhooks — polling only when explicitly enabled."""
    if not _on_hf:
        return False
    if _truthy_env("TELEGRAM_WEBHOOK"):
        return False
    if _truthy_env("TELEGRAM_POLLING"):
        return bool(_telegram_proxy_url())
    if _falsey_env("TELEGRAM_POLLING"):
        return False
    # Default on HF: webhook when space host is known (avoids 409 getUpdates conflicts).
    if _resolve_space_host():
        return False
    return bool(_telegram_proxy_url())


def _use_hf_webhook() -> bool:
    if _use_hf_polling():
        return False
    if _falsey_env("TELEGRAM_WEBHOOK"):
        return False
    if _truthy_env("TELEGRAM_WEBHOOK"):
        return _on_hf and bool(_resolve_space_host())
    return _on_hf and bool(_resolve_space_host())


def _telegram_webhook_path() -> str:
    custom = os.getenv("INBOUND_HOOK_PATH", "").strip().strip("/")
    if custom:
        return f"/{custom}"
    secret = os.getenv("TELEGRAM_WEBHOOK_SECRET", "").strip()
    if not secret:
        secret = hashlib.sha256((BOT_TOKEN or "webhook").encode()).hexdigest()[:24]
    base = inbound_hook_base_path().rstrip("/")
    return f"{base}/{secret}"


def _telegram_webhook_url() -> str:
    return _ingress_webhook_url()


async def _warn_if_webhook_not_public(webhook_url: str) -> None:
    """Private HF Spaces return 404 to Telegram — webhook delivery will fail."""
    probe_url = webhook_url.split(".hf.space", 1)[0] + ".hf.space/api/health"
    try:
        async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as client:
            resp = await client.get(probe_url)
        if resp.status_code == 404:
            log.error(
                "❌ HF Space health URL is not publicly reachable (%s → 404).\n"
                "   Telegram cannot deliver webhooks to a private Space.\n"
                "   Fix: Hugging Face → Space Settings → make the Space public,\n"
                "   or run the bot locally: python bot.py",
                probe_url,
            )
        elif resp.status_code == 200:
            log.info("✅ Webhook endpoint is publicly reachable")
    except Exception as exc:
        log.warning("⚠️ Could not verify public webhook reachability: %s", _brief_exc(exc))


_telegram_skip_proxy_on_hf_boot()

_telegram_conflict_last_log: float = 0.0
_TELEGRAM_CONFLICT_LOG_INTERVAL = 60.0


def _log_telegram_conflict(message: str, *args) -> None:
    """Throttle repeated 409 Conflict warnings — two pollers is a steady state, not every poll."""
    global _telegram_conflict_last_log
    now = time.time()
    if now - _telegram_conflict_last_log >= _TELEGRAM_CONFLICT_LOG_INTERVAL:
        _telegram_conflict_last_log = now
        log.warning(message, *args)
    else:
        log.debug(message, *args)


async def _prepare_telegram_transport(app: Application) -> None:
    """Ensure a single legal Telegram transport — webhook on HF/PA, or exclusive polling."""
    if _use_pa_webhook() or _use_hf_webhook():
        expected = _telegram_webhook_url()
        try:
            info = await app.bot.get_webhook_info()
            current = (info.url or "").strip()
            pending = int(getattr(info, "pending_update_count", 0) or 0)
            log.info(
                "📡 Ingress webhook mode — current=%r pending=%d expected=%s",
                current or "(empty)", pending, _stealth_log_url(expected),
            )
            if current != expected:
                await _register_telegram_webhook(app, expected)
        except Exception as exc:
            log.warning("Webhook prep failed (%s) — will retry in maintenance loop", _brief_exc(exc))
        return

    try:
        await app.bot.delete_webhook(drop_pending_updates=False)
        log.info("📡 Cleared Telegram webhook — exclusive polling mode")
        await asyncio.sleep(0.3 if not _on_cloud else 1.5)
    except Exception as exc:
        log.warning("Could not clear Telegram webhook before polling: %s", _brief_exc(exc))


def _telegram_rewrite_url(url: str, proxy_base: str) -> str:
    if proxy_base and "api.telegram.org" in url:
        return url.replace("https://api.telegram.org", proxy_base.rstrip("/"))
    return url


def _is_connect_failure(exc: BaseException) -> bool:
    if isinstance(exc, (httpx.ConnectError, httpx.ConnectTimeout)):
        return True
    text = _brief_exc(exc).lower()
    return "connecterror" in text or "connecttimeout" in text or "connect error" in text


class RetryingHTTPXRequest(HTTPXRequest):
    _logged_connection_mode = False
    USER_AGENT = _HTTP_CLIENT_PROFILE.user_agent

    def _apply_request_url(self, args: tuple, kwargs: dict, url: str) -> tuple[tuple, dict]:
        if args:
            return (url,) + args[1:], kwargs
        kwargs = dict(kwargs)
        kwargs["url"] = url
        return args, kwargs

    async def _execute_request(self, *args, **kwargs) -> tuple[int, bytes]:
        url = str(args[0] if args else kwargs.get("url", ""))
        proxy = _telegram_proxy_url()
        request_data = args[2] if len(args) > 2 else kwargs.get("request_data")
        method = args[1] if len(args) > 1 else kwargs.get("method", "POST")

        # Multipart uploads: forward raw multipart through the proxy (not JSON shim).
        if (
            proxy
            and not _TELEGRAM_PROXY_DISABLED
            and isinstance(request_data, RequestData)
            and request_data.contains_files
        ):
            log.debug("Telegram file upload — forwarding multipart via proxy (%s)", method)
            return await super().do_request(*args, **kwargs)

        if (
            proxy
            and not _TELEGRAM_PROXY_DISABLED
            and url.startswith(proxy.rstrip("/"))
            and isinstance(request_data, RequestData)
            and not request_data.contains_files
            and str(method).upper() == "POST"
        ):
            read_timeout = args[3] if len(args) > 3 else kwargs.get("read_timeout")
            write_timeout = args[4] if len(args) > 4 else kwargs.get("write_timeout")
            connect_timeout = args[5] if len(args) > 5 else kwargs.get("connect_timeout")
            pool_timeout = args[6] if len(args) > 6 else kwargs.get("pool_timeout")
            from telegram._utils.defaultvalue import DefaultValue

            if isinstance(read_timeout, DefaultValue):
                read_timeout = self._client.timeout.read
            if isinstance(connect_timeout, DefaultValue):
                connect_timeout = self._client.timeout.connect
            if isinstance(pool_timeout, DefaultValue):
                pool_timeout = self._client.timeout.pool
            if isinstance(write_timeout, DefaultValue):
                write_timeout = self._client.timeout.write

            timeout = httpx.Timeout(
                connect=connect_timeout,
                read=read_timeout,
                write=write_timeout,
                pool=pool_timeout,
            )
            res = await self._client.request(
                method="POST",
                url=url,
                json=request_data.parameters,
                headers={"User-Agent": self.USER_AGENT},
                timeout=timeout,
            )
            return res.status_code, res.content

        return await super().do_request(*args, **kwargs)

    async def do_request(self, *args, **kwargs) -> tuple[int, bytes]:
        global _TELEGRAM_PROXY_DISABLED
        from telegram.error import NetworkError, TimedOut, Conflict

        TELEGRAM_PROXY_URL = _telegram_proxy_url()

        if not RetryingHTTPXRequest._logged_connection_mode:
            RetryingHTTPXRequest._logged_connection_mode = True
            configured = os.getenv("TELEGRAM_PROXY_URL", "").strip().rstrip("/")
            if TELEGRAM_PROXY_URL:
                log.info("🌐 Routing Telegram API through proxy: %s", TELEGRAM_PROXY_URL)
            elif configured and _on_hf and ".workers.dev" in configured:
                log.info(
                    "🌐 HF Space: using direct Telegram API + inbound webhook "
                    "(workers.dev proxy blocked; set a Vercel proxy URL to enable outbound API)"
                )
            elif _on_hf:
                log.info("🌐 Running on Hugging Face Spaces: using direct connection to Telegram")
            else:
                log.info("🌐 Direct connection to Telegram (no proxy configured)")

        original_url = str(args[0] if args else kwargs.get("url", ""))
        use_proxy = bool(
            TELEGRAM_PROXY_URL
            and not _TELEGRAM_PROXY_DISABLED
            and "api.telegram.org" in original_url
        )
        request_url = _telegram_rewrite_url(original_url, TELEGRAM_PROXY_URL) if use_proxy else original_url
        req_args, req_kwargs = self._apply_request_url(args, kwargs, request_url)

        method = original_url.split("/")[-1] or original_url

        async def _try_direct_fallback(exc: BaseException) -> tuple[int, bytes] | None:
            global _TELEGRAM_PROXY_DISABLED
            nonlocal use_proxy
            if not use_proxy or not _is_connect_failure(exc):
                return None
            _TELEGRAM_PROXY_DISABLED = True
            log.warning(
                "⚠️ Telegram proxy unreachable (%s) — falling back to direct api.telegram.org",
                _brief_exc(exc),
            )
            direct_args, direct_kwargs = self._apply_request_url(args, kwargs, original_url)
            use_proxy = False
            return await self._execute_request(*direct_args, **direct_kwargs)

        if "getUpdates" in original_url:
            try:
                return await self._execute_request(*req_args, **req_kwargs)
            except Conflict:
                _log_telegram_conflict(
                    "🔴 409 Conflict on getUpdates: Another bot instance is polling. "
                    "Stop duplicate instances or set TELEGRAM_WEBHOOK=1 on HF. Waiting 5s…"
                )
                await asyncio.sleep(5)
                raise
            except Exception as exc:
                direct = await _try_direct_fallback(exc)
                if direct is not None:
                    return direct
                raise

        last_exc: BaseException = RuntimeError("All Telegram request attempts exhausted")
        max_attempts = 10
        for attempt in range(max_attempts):
            try:
                return await self._execute_request(*req_args, **req_kwargs)
            except Conflict as conflict_err:
                last_exc = conflict_err
                sleep_time = min(2 ** (attempt + 1), 30)
                log.warning(
                    "Telegram %s got 409 Conflict (attempt %d/%d) — another instance active. Retrying in %ds…",
                    method, attempt + 1, max_attempts, sleep_time,
                )
                await asyncio.sleep(sleep_time)
            except (NetworkError, TimedOut, httpx.HTTPError) as exc:
                if use_proxy and _is_connect_failure(exc):
                    try:
                        return await _try_direct_fallback(exc)
                    except Exception as direct_exc:
                        last_exc = direct_exc
                        log.warning(
                            "Telegram %s direct fallback failed: %s",
                            method, _brief_exc(direct_exc),
                        )
                        break
                last_exc = exc
                sleep_time = min(2 ** attempt, 16)
                log.warning(
                    "Telegram %s failed (attempt %d/%d): %s — retrying in %ds…",
                    method, attempt + 1, max_attempts, _brief_exc(exc), sleep_time,
                )
                await asyncio.sleep(sleep_time)
        raise last_exc


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Enhanced error handler with smart logging and user notification."""
    
    error = context.error
    error_msg = str(error)
    
    # Classify error type
    error_type = type(error).__name__
    
    # Log with appropriate level and context
    if isinstance(error, ValueError):
        log.warning("🔴 Validation Error: %s", error_msg)
    elif isinstance(error, RuntimeError):
        log.warning("🟠 Runtime Error: %s", error_msg)
    elif isinstance(error, (NetworkError, TimedOut, httpx.HTTPError)):
        log.warning(
            "⚠️ Telegram network request failed after retries: %s: %s",
            error_type, _brief_exc(error),
        )
        return
    elif isinstance(error, asyncio.TimeoutError):
        log.warning("⏱️ Timeout Error: %s", error_msg)
    elif error_type == "Conflict":
        _log_telegram_conflict(
            "⚠️ Telegram Conflict: %s (stop duplicate pollers or use TELEGRAM_WEBHOOK=1 on HF)",
            error_msg,
        )
    else:
        log.error("🔴 Unexpected %s: %s\n%s", error_type, error_msg, traceback.format_exc())
    
    # Try to send error notification to user if we have a chat
    try:
        if isinstance(update, Update) and update.effective_chat:
            chat_id = update.effective_chat.id
            
            # Don't spam user with all error details, keep it friendly
            if "placeholder.jpg" in error_msg.lower():
                user_msg = "⚠️ Generation was blocked by content filter. Retrying with a fresh account... 🔄"
            elif "timed out" in error_msg.lower():
                user_msg = "⏱️ Generation took too long. Retrying... 🔄"
            elif "not found" in error_msg.lower():
                user_msg = "❌ Could not find UI element. Retrying... 🔄"
            else:
                user_msg = f"❌ Error: {error_msg[:100]}... Retrying... 🔄"
            
            await context.bot.send_message(chat_id=chat_id, text=user_msg)
    except Exception as notify_err:
        log.debug("Could not notify user of error: %s", notify_err)


async def cmd_broadcast(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    admin_id = get_admin_group_id()
    sender_id = update.effective_chat.id
    if not admin_id or sender_id != admin_id:
        await update.message.reply_text("❌ Unauthorized. Only the admin group can use this command.")
        return

    # Extract message
    msg_text = " ".join(ctx.args).strip()
    if not msg_text:
        await update.message.reply_text("Usage: /broadcast <message>")
        return

    users_file = DATA_DIR / "users.txt"
    if not users_file.exists():
        await update.message.reply_text("No registered users found.")
        return

    with open(users_file, "r") as f:
        chat_ids = [int(line.strip()) for line in f if line.strip().isdigit()]

    if not chat_ids:
        await update.message.reply_text("No registered users found in file.")
        return

    sent_count = 0
    fail_count = 0
    status_msg = await update.message.reply_text(f"📢 Starting broadcast to {len(chat_ids)} users...")

    for cid in chat_ids:
        try:
            await ctx.bot.send_message(chat_id=cid, text=msg_text, parse_mode="Markdown")
            sent_count += 1
            await asyncio.sleep(0.05)  # Compliance with Telegram broadcast rate limit
        except Exception as e:
            log.warning("Broadcast failed for user %d: %s", cid, e)
            fail_count += 1

    await status_msg.edit_text(
        f"📢 *Broadcast finished!*\n\n"
        f"• *Successful*: `{sent_count}`\n"
        f"• *Failed/Blocked*: `{fail_count}`"
    )


async def _run_hf_webhook_server(app: Application) -> web.AppRunner:
    """Serve health check + Telegram webhook on port 7860 (HF Spaces)."""
    global _last_heartbeat
    _last_heartbeat = time.time()

    webhook_path = _telegram_webhook_path()
    webhook_secret = webhook_path.rsplit("/", 1)[-1]

    async def health_check(request):
        return _make_health_response()

    async def status_api(_request):
        body = _health_response_text(degraded=_health_is_stale())
        return web.Response(text=body, content_type="application/json", status=200)

    async def telegram_webhook(request):
        if request.method != "POST":
            return web.Response(status=405)
        provided = request.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
        if provided and provided != webhook_secret:
            return web.Response(status=403, text="invalid secret")
        try:
            data = await request.json()
        except Exception:
            return web.Response(status=400, text="invalid json")
        update = Update.de_json(data, app.bot)
        if update is not None:
            await app.update_queue.put(update)
        return web.Response(text="ok")

    web_app = web.Application()
    web_app.router.add_get("/", health_check)
    web_app.router.add_get("/api/health", status_api)
    web_app.router.add_get("/api/v1/status", status_api)
    web_app.router.add_post(webhook_path, telegram_webhook)
    runner = web.AppRunner(web_app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", 7860)
    await site.start()
    log.info("🌐 Web server started on port 7860 (health + inbound hook)")
    return runner


async def _register_telegram_webhook(app: Application, webhook_url: str) -> bool:
    """Register (or re-register) the inbound Telegram webhook."""
    secret = webhook_url.rsplit("/", 1)[-1]
    try:
        await app.bot.set_webhook(
            webhook_url,
            secret_token=secret,
            drop_pending_updates=False,
        )
        log.info("📡 Ingress webhook registered: %s", _stealth_log_url(webhook_url))
        return True
    except Exception as exc:
        log.warning("set_webhook via bot API failed (%s) — trying HTTP fallback", _brief_exc(exc))

    proxy = _telegram_proxy_url()
    api_base = proxy.rstrip("/") if proxy else "https://api.telegram.org"
    token = app.bot.token
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                f"{api_base}/bot{token}/setWebhook",
                json={
                    "url": webhook_url,
                    "secret_token": secret,
                    "drop_pending_updates": False,
                },
            )
        body = resp.text.replace(" ", "")
        if resp.status_code == 200 and '"ok":true' in body:
            log.info("📡 Ingress webhook registered via HTTP fallback: %s", _stealth_log_url(webhook_url))
            return True
        log.error("HTTP setWebhook failed (%s): %s", resp.status_code, resp.text[:300])
    except Exception as exc:
        log.error("HTTP setWebhook error: %s", _brief_exc(exc))
    return False


async def _webhook_maintenance_loop(app: Application) -> None:
    """Keep the ingress webhook registered — local polling or restarts can clear it."""
    expected = _telegram_webhook_url()
    while True:
        await asyncio.sleep(90)
        if not (_on_hf or _on_pa):
            return
        try:
            info = await app.bot.get_webhook_info()
            current = (info.url or "").strip()
            if current != expected:
                log.warning(
                    "📡 Webhook missing or wrong (current=%r expected=%r) — re-registering",
                    current or "(empty)",
                    expected,
                )
                await _register_telegram_webhook(app, expected)
        except Exception as exc:
            log.warning("Webhook maintenance failed (%s) — retrying registration", _brief_exc(exc))
            await _register_telegram_webhook(app, expected)


async def _pa_queue_consumer_loop(app: Application) -> None:
    """Drain Telegram updates enqueued by the PA WSGI web app."""
    from pa_bridge import dequeue_telegram_updates

    while True:
        try:
            batch = dequeue_telegram_updates(max_n=20)
            if not batch:
                await asyncio.sleep(0.25)
                continue
            for data in batch:
                update = Update.de_json(data, app.bot)
                if update is not None:
                    await app.update_queue.put(update)
        except Exception as exc:
            log.warning("PA queue consumer error: %s", _brief_exc(exc))
            await asyncio.sleep(1.0)


def _local_polling_allowed(token: str) -> bool:
    """Block accidental local polling when the HF webhook is active."""
    if _truthy_env("LOCAL_BOT"):
        return True
    proxy = _telegram_proxy_url()
    api_base = proxy.rstrip("/") if proxy else "https://api.telegram.org"
    try:
        with httpx.Client(timeout=15.0) as client:
            resp = client.get(f"{api_base}/bot{token}/getWebhookInfo")
            url = (resp.json().get("result") or {}).get("url", "")
            if url and (".hf.space" in url or ".pythonanywhere.com" in url):
                host_label = "HF" if ".hf.space" in url else "PA"
                log.error(
                    "❌ %s webhook is active at %s\n"
                    "   Running locally would delete it and break Telegram on the remote host.\n"
                    "   Use the remote bot as-is, or set LOCAL_BOT=1 to force local polling.",
                    host_label,
                    url,
                )
                return False
            probe = client.get(
                f"{api_base}/bot{token}/getUpdates",
                params={"timeout": 0, "limit": 1},
            )
            if probe.status_code == 409:
                log.error(
                    "❌ Another bot instance is already polling Telegram (409 Conflict).\n"
                    "   Stop the Hugging Face Space or the other local process first,\n"
                    "   or set LOCAL_BOT=1 to take over (will break the other instance).",
                )
                return False
    except Exception as exc:
        log.warning("Could not check active webhook before local polling: %s", _brief_exc(exc))
    return True


async def _pa_main(app: Application) -> None:
    """Run the bot on PythonAnywhere always-on task (WSGI enqueues, workers process)."""
    webhook_url = _telegram_webhook_url()
    stop_event = asyncio.Event()

    def _request_shutdown() -> None:
        if not stop_event.is_set():
            log.info("🛑 Shutdown requested (SIGTERM/SIGINT) — stopping bot gracefully...")
            stop_event.set()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(sig, _request_shutdown)
        except (NotImplementedError, RuntimeError):
            pass

    try:
        await app.initialize()
        if app.post_init:
            await app.post_init(app)
        await app.start()

        if not await _register_telegram_webhook(app, webhook_url):
            log.error(
                "❌ Could not register Telegram webhook. Run from your PC:\n"
                "  python scripts/register_pa_webhook.py"
            )

        _spawn_background_task(_pa_queue_consumer_loop(app), name="pa-queue-consumer")
        _spawn_background_task(_webhook_maintenance_loop(app), name="webhook-maintenance")
        log.info(
            "✅ PA service running — WSGI ingress + queue consumer + %d workers",
            NUM_WORKERS,
        )

        await stop_event.wait()
    finally:
        await _shutdown_background_tasks()
        try:
            await app.stop()
            await app.shutdown()
        except Exception as e:
            log.warning("Application shutdown: %s", e)
        log.info("🛑 PA bot shutdown complete")


async def _hf_main(app: Application) -> None:
    """Run the bot on HF using inbound webhooks (avoids blocked outbound long-polling)."""
    runner = await _run_hf_webhook_server(app)
    webhook_url = _telegram_webhook_url()
    stop_event = asyncio.Event()

    def _request_shutdown() -> None:
        if not stop_event.is_set():
            log.info("🛑 Shutdown requested (SIGTERM/SIGINT) — stopping bot gracefully...")
            stop_event.set()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(sig, _request_shutdown)
        except (NotImplementedError, RuntimeError):
            pass

    try:
        await app.initialize()
        if app.post_init:
            await app.post_init(app)
        await app.start()

        await _warn_if_webhook_not_public(webhook_url)
        if not await _register_telegram_webhook(app, webhook_url):
            log.error(
                "❌ Could not register Telegram webhook. Run from your PC:\n"
                "  python scripts/register_hf_webhook.py"
            )

        _spawn_background_task(_webhook_maintenance_loop(app), name="webhook-maintenance")
        log.info("✅ Service running — waiting for jobs (ingress + %d workers)", NUM_WORKERS)

        await stop_event.wait()
    finally:
        await _shutdown_background_tasks()
        try:
            await app.stop()
            await app.shutdown()
        except Exception as e:
            log.warning("Application shutdown: %s", e)
        finally:
            await runner.cleanup()
            log.info("🛑 HF bot shutdown complete")


def _build_application(request_obj: RetryingHTTPXRequest) -> Application:
    app = (
        Application.builder()
        .token(BOT_TOKEN or os.getenv("TELEGRAM_BOT_TOKEN", ""))
        .request(request_obj)
        .get_updates_request(request_obj)
        .post_init(post_init)
        .concurrent_updates(False)
        .build()
    )

    conv = ConversationHandler(
        entry_points=[
            CommandHandler("generate", cmd_generate),
            CommandHandler("start", cmd_start),
            CommandHandler("help", cmd_start),
        ],
        states={
            ASK_MODE_SELECT: [
                CallbackQueryHandler(
                    handle_mode_select,
                    pattern=r"^mode_(single|bulk|guava15_bulk|guava15|posing_bulk|posing|video|gpt_image|gpt_image_bulk|mango3|mango3_bulk)$",
                ),
            ],
            ASK_IMAGE: [
                MessageHandler(filters.PHOTO, got_image),
                MessageHandler(filters.TEXT & ~filters.COMMAND, got_prompt_after_refs),
                CallbackQueryHandler(handle_single_refs_done, pattern=r"^refs_(done|cancel)$"),
                CallbackQueryHandler(got_aspect, pattern=r"^aspect:"),
            ],
            ASK_BULK_IMAGES: [
                MessageHandler(filters.PHOTO, got_bulk_image),
                CallbackQueryHandler(handle_bulk_done, pattern=r"^bulk_(done|cancel)$"),
            ],
            ASK_PROMPT_MODE: [
                CallbackQueryHandler(handle_video_prompt, pattern=r"^video_prompt:(kiss|sex|teasing|custom)$"),
                CallbackQueryHandler(handle_prompt_mode, pattern=r"^prompt_(auto|custom|templates|random)$"),
            ],
            ASK_TEMPLATES: [
                CallbackQueryHandler(handle_templates, pattern=r"^tpl"),
            ],
            ASK_CUSTOM_PROMPT: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, got_custom_prompt),
                CallbackQueryHandler(handle_moderation_cancel, pattern=r"^moderation_cancel$"),
            ],
            ASK_GUAVA_VERSION: [
                CallbackQueryHandler(handle_guava_version, pattern=r"^guava_v[12]$"),
            ],
        },
        fallbacks=[CommandHandler("cancel", cmd_cancel)],
        allow_reentry=True,
        per_message=False,
        conversation_timeout=None,
    )

    app.add_handler(conv)
    app.add_handler(CommandHandler("status", cmd_status))
    app.add_handler(CommandHandler("set_admin", cmd_set_admin))
    app.add_handler(CommandHandler("broadcast", cmd_broadcast))
    app.add_handler(CommandHandler("cancel_job", cmd_cancel_job))
    app.add_error_handler(error_handler)
    return app


def main():
    token = BOT_TOKEN or os.getenv("TELEGRAM_BOT_TOKEN", "")
    if not token:
        log.error("❌ Set BOT_TOKEN (or TELEGRAM_BOT_TOKEN) in environment / HF Secrets")
        raise SystemExit(1)

    request_obj = RetryingHTTPXRequest(
        connection_pool_size=10,
        connect_timeout=60.0 if _on_cloud else 15.0,
        read_timeout=75.0 if _on_cloud else 25.0,
        write_timeout=75.0 if _on_cloud else 25.0,
        pool_timeout=30.0 if _on_cloud else 10.0,
    )
    app = _build_application(request_obj)
    log.info("🚀 Service starting …")

    if _on_pa:
        if not _use_pa_webhook():
            log.error("❌ On PA: set PYTHONANYWHERE=1, PA_HOST, and TELEGRAM_WEBHOOK=1")
            raise SystemExit(1)
        log.info(
            "📡 PA ingress webhook mode (WSGI → queue via %s)",
            _stealth_log_url(_telegram_webhook_url()),
        )
        asyncio.run(_pa_main(app))
        return

    if _on_hf:
        use_webhook = _use_hf_webhook()
        use_polling = _use_hf_polling()
        if use_polling or not use_webhook:
            _web_ready = threading.Event()
            threading.Thread(target=_run_web_thread, args=(_web_ready,), daemon=True).start()
            if not _web_ready.wait(timeout=15):
                log.warning("⚠️ Health-check server did not start within 15 s — continuing anyway")
        if use_polling:
            log.info("📡 HF polling mode via %s", _telegram_proxy_url())
            app.run_polling(drop_pending_updates=False, bootstrap_retries=-1)
            return
        if use_webhook:
            log.info("📡 HF ingress webhook mode (inbound via %s)", _stealth_log_url(_telegram_webhook_url()))
            asyncio.run(_hf_main(app))
            return
        log.error(
            "❌ On HF: set SPACE_HOST/HF_REPO_ID for webhooks, or TELEGRAM_PROXY_URL + TELEGRAM_POLLING=1"
        )
        raise SystemExit(1)

    log.info("📡 Local polling mode — Telegram updates via getUpdates (stop HF or clear webhook first)")
    if not _local_polling_allowed(token):
        raise SystemExit(1)
    _web_ready = threading.Event()
    threading.Thread(target=_run_web_thread, args=(_web_ready,), daemon=True).start()
    if not _web_ready.wait(timeout=15):
        log.warning("⚠️ Health-check server did not start within 15 s — continuing anyway")
    app.run_polling(drop_pending_updates=False, bootstrap_retries=-1)


if __name__ == "__main__":
    try:
        main()
    except Exception as _fatal:
        log.critical("💀 Bot crashed: %s", _fatal, exc_info=True)
        raise
