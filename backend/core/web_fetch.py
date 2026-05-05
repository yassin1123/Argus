"""Fetch and extract readable text from web pages (deep research). Policy via env."""

import os
import time
from urllib.parse import urlparse

import httpx
from bs4 import BeautifulSoup

DEFAULT_MAX_BYTES = int(os.getenv("WEB_FETCH_MAX_BYTES", "800000"))
DEFAULT_TIMEOUT = float(os.getenv("WEB_FETCH_TIMEOUT_SEC", "18"))
_FAILURE_STREAK = 0
_CIRCUIT_OPEN_UNTIL = 0.0
_FAILURE_THRESHOLD = int(os.getenv("WEB_FETCH_CIRCUIT_FAILURES", "5"))
_CIRCUIT_SEC = float(os.getenv("WEB_FETCH_CIRCUIT_SECONDS", "60"))


def _parse_domain_list(raw: str) -> list[str]:
    return [x.strip().lower() for x in raw.split(",") if x.strip()]


def _host_ok(host: str) -> tuple[bool, str]:
    host = host.lower().strip(".")
    allowed_raw = os.getenv("WEB_FETCH_ALLOWED_DOMAINS", "") or os.getenv("ARGUS_WEB_DOMAIN_ALLOWLIST", "")
    allowed = _parse_domain_list(allowed_raw)
    if allowed:
        if not any(host == d or host.endswith(f".{d}") for d in allowed):
            return False, f"host not in allowlist: {host}"
    blocked_raw = os.getenv("WEB_FETCH_BLOCKED_DOMAINS", "") or os.getenv("ARGUS_WEB_DOMAIN_DENYLIST", "")
    blocked = _parse_domain_list(blocked_raw)
    for b in blocked:
        if host == b or host.endswith(f".{b}"):
            return False, f"host blocked: {host}"
    return True, ""


def html_to_text(html: str, max_chars: int = 12000) -> str:
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "noscript", "template"]):
        tag.decompose()
    text = soup.get_text(separator="\n", strip=True)
    lines = [ln for ln in (x.strip() for x in text.splitlines()) if ln]
    out = "\n".join(lines)
    return out[:max_chars]


def _record_failure() -> None:
    global _FAILURE_STREAK, _CIRCUIT_OPEN_UNTIL
    _FAILURE_STREAK += 1
    if _FAILURE_STREAK >= _FAILURE_THRESHOLD:
        _CIRCUIT_OPEN_UNTIL = time.monotonic() + _CIRCUIT_SEC
        _FAILURE_STREAK = 0


def _record_success() -> None:
    global _FAILURE_STREAK
    _FAILURE_STREAK = 0


async def fetch_page_text(url: str, *, max_bytes: int | None = None) -> tuple[str | None, str | None]:
    """
    Returns (extracted_text, error_message).
    error_message set on policy violation or fetch/parse failure.
    """
    global _CIRCUIT_OPEN_UNTIL
    if time.monotonic() < _CIRCUIT_OPEN_UNTIL:
        return None, "fetch temporarily degraded — circuit open; retry shortly"

    max_b = max_bytes if max_bytes is not None else DEFAULT_MAX_BYTES
    try:
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https"):
            return None, "unsupported URL scheme"
        host = parsed.hostname or ""
        ok, reason = _host_ok(host)
        if not ok:
            return None, reason
    except Exception as e:
        return None, str(e)

    try:
        async with httpx.AsyncClient(
            timeout=DEFAULT_TIMEOUT,
            follow_redirects=True,
            headers={"User-Agent": "ArgusResearchBot/1.0 (+https://example.invalid)"},
        ) as client:
            r = await client.get(url)
            r.raise_for_status()
            body = r.content[:max_b]
            ctype = (r.headers.get("content-type") or "").lower()
            if "html" not in ctype and not url.lower().endswith(".html"):
                # still try parse as html; many servers omit charset
                pass
            text = html_to_text(body.decode("utf-8", errors="replace"))
            if len(text.strip()) < 80:
                return None, "extracted text too short"
            _record_success()
            return text, None
    except Exception as e:
        _record_failure()
        return None, str(e)[:500]
