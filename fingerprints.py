"""Deploy-scoped browser + HTTP fingerprints — unique per Space, stable per worker."""

from __future__ import annotations

import hashlib
import json
import os
import random
from dataclasses import dataclass


def _deploy_seed() -> str:
    return (
        os.getenv("DEPLOY_INSTANCE_ID", "").strip()
        or os.getenv("PA_HOST", "").strip()
        or os.getenv("SPACE_ID", "").strip()
        or os.getenv("HF_SPACE", "").strip()
        or "local-dev"
    )


def _rng(tag: str, worker_id: int = 0) -> random.Random:
    raw = f"{_deploy_seed()}:{tag}:{worker_id}".encode()
    return random.Random(int(hashlib.sha256(raw).hexdigest()[:16], 16))


_CHROME_BUILDS = (
    ("124.0.0.0", "124"),
    ("125.0.0.0", "125"),
    ("126.0.0.0", "126"),
    ("127.0.0.0", "127"),
    ("128.0.0.0", "128"),
)
_PLATFORMS = (
    ("Win32", "Windows NT 10.0; Win64; x64"),
    ("Win32", "Windows NT 11.0; Win64; x64"),
    ("MacIntel", "Macintosh; Intel Mac OS X 10_15_7"),
    ("MacIntel", "Macintosh; Intel Mac OS X 14_5_0"),
)
_TIMEZONES = (
    "America/New_York",
    "America/Chicago",
    "America/Los_Angeles",
    "Europe/London",
    "Europe/Berlin",
)
_LOCALES = ("en-US", "en-GB", "en-CA")


@dataclass(frozen=True)
class BrowserFingerprint:
    user_agent: str
    viewport_width: int
    viewport_height: int
    platform: str
    platform_nav: str
    languages: tuple[str, ...]
    timezone_id: str
    locale: str
    hardware_concurrency: int
    device_memory: int
    chrome_full: str
    chrome_major: str


@dataclass(frozen=True)
class HttpClientProfile:
    user_agent: str
    accept_language: str


def get_worker_fingerprint(worker_id: int = 0) -> BrowserFingerprint:
    """Deterministic fingerprint per worker within this deploy instance."""
    rng = _rng("browser", worker_id)
    chrome_full, chrome_major = rng.choice(_CHROME_BUILDS)
    platform_nav, _ = rng.choice(_PLATFORMS)
    platform_js = platform_nav.split(";")[0].strip()
    if platform_js == "Macintosh":
        platform_js = "MacIntel"
    elif "Windows" in platform_nav:
        platform_js = "Win32"

    vw = rng.choice((1366, 1440, 1536, 1600, 1920))
    vh = rng.choice((768, 864, 900, 1024, 1080))
    if vw >= 1600:
        vh = max(vh, 900)

    locale = rng.choice(_LOCALES)
    lang_primary = locale
    lang_secondary = "en" if not locale.startswith("en") else "en-US"
    languages = (lang_primary, lang_secondary)

    ua = (
        f"Mozilla/5.0 ({platform_nav}) "
        f"AppleWebKit/537.36 (KHTML, like Gecko) "
        f"Chrome/{chrome_full} Safari/537.36"
    )

    return BrowserFingerprint(
        user_agent=ua,
        viewport_width=vw,
        viewport_height=vh,
        platform=platform_js,
        platform_nav=platform_nav,
        languages=languages,
        timezone_id=rng.choice(_TIMEZONES),
        locale=locale,
        hardware_concurrency=rng.choice((4, 6, 8, 12, 16)),
        device_memory=rng.choice((4, 8, 16)),
        chrome_full=chrome_full,
        chrome_major=chrome_major,
    )


def get_http_client_profile() -> HttpClientProfile:
    """Outbound HTTP client face (Telegram proxy, health probes, etc.)."""
    rng = _rng("http-client", 0)
    chrome_full, _ = rng.choice(_CHROME_BUILDS)
    platform_nav = rng.choice([p[1] for p in _PLATFORMS])
    locale = rng.choice(_LOCALES)
    ua = (
        f"Mozilla/5.0 ({platform_nav}) "
        f"AppleWebKit/537.36 (KHTML, like Gecko) "
        f"Chrome/{chrome_full} Safari/537.36"
    )
    return HttpClientProfile(
        user_agent=ua,
        accept_language=f"{locale},{locale.split('-')[0]};q=0.9",
    )


def build_stealth_init_script(fp: BrowserFingerprint) -> str:
    langs_json = json.dumps(list(fp.languages))
    return f"""
Object.defineProperty(navigator, 'webdriver', {{ get: () => undefined }});
window.chrome = window.chrome || {{ runtime: {{}} }};
Object.defineProperty(navigator, 'languages', {{ get: () => {langs_json} }});
Object.defineProperty(navigator, 'language', {{ get: () => {json.dumps(fp.languages[0])} }});
Object.defineProperty(navigator, 'plugins', {{ get: () => [1, 2, 3, 4, 5] }});
Object.defineProperty(navigator, 'platform', {{ get: () => {json.dumps(fp.platform)} }});
Object.defineProperty(navigator, 'hardwareConcurrency', {{ get: () => {fp.hardware_concurrency} }});
Object.defineProperty(navigator, 'deviceMemory', {{ get: () => {fp.device_memory} }});
Object.defineProperty(navigator, 'maxTouchPoints', {{ get: () => 0 }});
try {{
    Object.defineProperty(navigator, 'userAgent', {{ get: () => {json.dumps(fp.user_agent)} }});
}} catch (e) {{}}
"""


def maildev_http_headers(fp: BrowserFingerprint | None = None) -> dict[str, str]:
    profile = fp or get_worker_fingerprint(-1)
    lang = profile.languages[0]
    return {
        "User-Agent": profile.user_agent,
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": f"{lang},{profile.languages[1] if len(profile.languages) > 1 else lang};q=0.9",
        "Referer": "https://maildev.dev/",
        "Origin": "https://maildev.dev",
        "Cache-Control": "no-cache",
        "Pragma": "no-cache",
    }


def public_health_payload(*, pool_ready: int = 0, pool_target: int = 0) -> str:
    """External health face — no messenger or pool hints in the body."""
    stealth = os.getenv("STEALTH_PUBLIC_FACE", "1" if os.getenv("SPACE_ID") or os.getenv("HF_SPACE") else "0")
    if stealth.lower() not in ("1", "true", "yes", "on"):
        pool_bit = f" pool={pool_ready}/{pool_target}" if pool_target else ""
        return f"OK{pool_bit}"
    seed = _deploy_seed()
    version = f"2.{int(hashlib.sha256(seed.encode()).hexdigest()[:4], 16) % 900 + 100}.0"
    service = os.getenv("PUBLIC_SERVICE_NAME", "nvd-sync")
    theme = os.getenv("STEALTH_THEME", "").strip().lower()
    if theme == "collage" or _is_collage_service(service):
        checks = {"renderer": "ok", "assets": "ok", "export": "ok"}
    else:
        checks = {"database": "ok", "index": "ok", "ingress": "ok"}
    return json.dumps(
        {
            "service": service,
            "status": "operational",
            "version": version,
            "checks": checks,
        }
    )


_STEALTH_SERVICE_NAMES = (
    "nvd-sync",
    "cve-index",
    "vuln-feed",
    "advisory-cache",
    "security-mirror",
    "threat-index",
)
_COLLAGE_SERVICE_NAMES = (
    "mosaic-compose",
    "collage-engine",
    "layer-stack",
    "pixel-mosaic",
    "canvas-merge",
    "tile-layout",
)
_STEALTH_HOOK_BASES = (
    "api/v1/ingest",
    "api/v2/events",
    "internal/sync",
    "hooks/push",
    "svc/relay",
    "events/receive",
)
_COLLAGE_HOOK_BASES = (
    "api/v1/canvases",
    "api/v2/layers",
    "api/v1/mosaics",
    "svc/compose",
    "hooks/export",
    "api/v1/tiles",
)


def _is_collage_service(name: str) -> bool:
    n = (name or "").lower()
    return any(
        k in n
        for k in ("mosaic", "collage", "layer", "canvas", "pixel", "tile")
    )


def generate_stealth_service_name() -> str:
    """Random benign public service name per deploy."""
    return random.SystemRandom().choice(_STEALTH_SERVICE_NAMES)


def generate_collage_stealth_service_name() -> str:
    """Collage-themed public service name for creative-tool Space branding."""
    return random.SystemRandom().choice(_COLLAGE_SERVICE_NAMES)


def generate_stealth_hook_base() -> str:
    """Random inbound path prefix — avoids repeating the same URL shape."""
    return random.SystemRandom().choice(_STEALTH_HOOK_BASES)


def generate_collage_hook_base() -> str:
    """Collage-themed inbound path prefix."""
    return random.SystemRandom().choice(_COLLAGE_HOOK_BASES)


def generate_inbound_hook_suffix(length: int = 24) -> str:
    """Random path suffix for inbound webhook (no product names in URL)."""
    rng = random.SystemRandom()
    alphabet = "abcdefghijklmnopqrstuvwxyz0123456789"
    return "".join(rng.choice(alphabet) for _ in range(length))


def inbound_hook_base_path() -> str:
    """Generic inbound path prefix — override via INBOUND_HOOK_PATH."""
    custom = os.getenv("INBOUND_HOOK_PATH", "").strip().strip("/")
    if custom:
        return f"/{custom}"
    return "/api/v1/ingest"
