"""Logo asset cache for deck exports — W11/D4.

Fetches a firm's logo once, caches it to disk for 24h, resizes to
max width 300px so embedding doesn't blow the PPTX file size, and
falls back gracefully when the URL is unreachable.

Public surface:
  - :func:`fetch_and_cache_logo(firm_id, logo_url)` → ``bytes | None``
  - :data:`LOGO_CACHE_DIR` — module-level Path the cache lives at
    (overridable via ``ARGUS_LOGO_CACHE_DIR`` env var so tests can
    target ``tmp_path``).

Hard-rule compliance:
  - Network failure / bad URL → returns ``None`` (exporter falls back
    to firm-name text). Never raises out of the public API.
  - Cache lookup is the fast path; only one HTTP round-trip per firm
    per 24h window.
  - Re-sizing preserves aspect ratio (non-square logos stay
    non-square — spec hard rule).
"""

from __future__ import annotations

import base64
import logging
import os
import re
import time
from io import BytesIO
from pathlib import Path
from typing import Any
from uuid import UUID

logger = logging.getLogger(__name__)

# Default cache root. Lives outside the repo so it survives container
# restarts but is wiped by /tmp cleanup. Tests override via env var.
LOGO_CACHE_DIR = Path(
    os.environ.get("ARGUS_LOGO_CACHE_DIR")
    or (Path(os.environ.get("TEMP") or "/tmp") / "argus_logos")
)

_TTL_SECONDS = 24 * 60 * 60  # 24h per spec
_MAX_WIDTH_PX = 300           # per spec
_FETCH_TIMEOUT_S = 5.0


def _cache_path(firm_id: Any) -> Path:
    return LOGO_CACHE_DIR / f"{firm_id}.png"


def _cache_fresh(path: Path) -> bool:
    if not path.exists():
        return False
    try:
        mtime = path.stat().st_mtime
    except OSError:
        return False
    return (time.time() - mtime) < _TTL_SECONDS


def _resize_png(raw: bytes) -> bytes | None:
    """Resize to max width ``_MAX_WIDTH_PX`` preserving aspect ratio.
    Returns PNG bytes; returns ``None`` if Pillow can't decode the
    input (so the caller falls back to text)."""
    try:
        from PIL import Image
    except ImportError:
        logger.warning("Pillow not installed — skipping resize")
        return raw
    try:
        img = Image.open(BytesIO(raw))
        img.load()
    except Exception as e:  # noqa: BLE001
        logger.warning("logo image decode failed: %s", e)
        return None
    # Normalise to RGBA so PNG export always works regardless of mode.
    if img.mode not in ("RGBA", "RGB"):
        img = img.convert("RGBA")
    if img.width > _MAX_WIDTH_PX:
        ratio = _MAX_WIDTH_PX / img.width
        new_size = (_MAX_WIDTH_PX, max(1, int(img.height * ratio)))
        img = img.resize(new_size)
    buf = BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _decode_data_uri(uri: str) -> bytes | None:
    """``data:image/png;base64,XYZ...`` → bytes. Returns None on
    malformed input."""
    m = re.match(r"^data:[^;,]+(;base64)?,(.+)$", uri, re.S)
    if not m:
        return None
    is_base64 = bool(m.group(1))
    payload = m.group(2)
    try:
        if is_base64:
            return base64.b64decode(payload)
        return payload.encode("utf-8")
    except Exception:
        return None


async def _fetch_url(url: str) -> bytes | None:
    """HTTPS fetch via httpx. Never raises — returns None on any
    transport-level failure so callers can fall back cleanly."""
    try:
        import httpx
    except ImportError:
        logger.warning("httpx not installed — logo URL fetch disabled")
        return None
    try:
        async with httpx.AsyncClient(timeout=_FETCH_TIMEOUT_S, follow_redirects=True) as client:
            resp = await client.get(url)
            if resp.status_code != 200:
                logger.info("logo fetch %s returned status %s", url, resp.status_code)
                return None
            return resp.content
    except Exception as e:  # noqa: BLE001
        logger.info("logo fetch %s failed: %s", url, e)
        return None


def _read_local_path(p: str) -> bytes | None:
    try:
        return Path(p).read_bytes()
    except Exception:
        return None


async def fetch_and_cache_logo(firm_id: UUID | str, logo_url: str) -> bytes | None:
    """Return resized PNG bytes for the firm's logo, or ``None`` if
    the URL is empty / unreachable / undecodable.

    Resolves three kinds of input:
      - ``https://...``      — HTTP fetch via httpx
      - ``data:image/...``   — base64 / urlencoded inline data
      - ``/local/path.png``  — file read (useful for firm-uploaded logos)

    Cache: writes the resized bytes to
    ``<LOGO_CACHE_DIR>/<firm_id>.png`` with a 24h TTL. Stale or
    missing cache entries trigger a fresh fetch.
    """
    if not logo_url or not isinstance(logo_url, str):
        return None

    cache_path = _cache_path(firm_id)
    if _cache_fresh(cache_path):
        try:
            return cache_path.read_bytes()
        except OSError:
            pass  # fall through to refetch

    # Branch on URL scheme.
    raw: bytes | None
    if logo_url.startswith("data:"):
        raw = _decode_data_uri(logo_url)
    elif logo_url.startswith(("http://", "https://")):
        raw = await _fetch_url(logo_url)
    else:
        raw = _read_local_path(logo_url)

    if raw is None:
        return None

    resized = _resize_png(raw)
    if resized is None:
        return None

    try:
        LOGO_CACHE_DIR.mkdir(parents=True, exist_ok=True)
        cache_path.write_bytes(resized)
    except OSError as e:
        logger.info("logo cache write failed (%s) — returning bytes anyway", e)

    return resized


def clear_cache_for(firm_id: UUID | str) -> None:
    """Invalidate one firm's cache entry. Used by tests + the future
    branding-update admin endpoint."""
    try:
        _cache_path(firm_id).unlink(missing_ok=True)
    except Exception:
        pass


__all__ = [
    "LOGO_CACHE_DIR",
    "clear_cache_for",
    "fetch_and_cache_logo",
]
