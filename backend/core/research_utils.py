"""URL normalization, dedupe keys, and light recency heuristics for web research."""

import os
import re
from typing import Any
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

_TRACKING_PARAMS = frozenset(
    "utm_source utm_medium utm_campaign utm_term utm_content gclid fbclid mc_eid".split()
)


def normalize_url(url: str) -> str:
    """Stable key for deduplication (scheme/host/path, strip common tracking query params)."""
    try:
        p = urlparse((url or "").strip())
        if not p.scheme or not p.netloc:
            return (url or "").strip().lower()
        q = parse_qs(p.query, keep_blank_values=False)
        filtered = [(k, v[0]) for k, v in q.items() if k.lower() not in _TRACKING_PARAMS and v]
        filtered.sort()
        new_query = urlencode(filtered) if filtered else ""
        path = p.path or "/"
        if path != "/" and path.endswith("/"):
            path = path.rstrip("/")
        return urlunparse((p.scheme.lower(), p.netloc.lower(), path, "", new_query, ""))
    except Exception:
        return (url or "").strip().lower()


def recency_boost(result: dict[str, Any]) -> float:
    """
    0..1 boost from SerpAPI-style result (date string if present) and snippet year mentions.
    """
    score = 0.35
    date_s = str(result.get("date") or result.get("article_date") or "").strip()
    if date_s:
        score = 0.75
    else:
        snippet = str(result.get("snippet") or "")
        if re.search(r"\b20(2[4-9]|3\d)\b", snippet):
            score = 0.55
    pos = float(result.get("position") or 10)
    score += max(0.0, (11 - min(pos, 10)) * 0.02)
    return min(1.0, score)


def merge_source_score(base: float, result: dict[str, Any]) -> float:
    return min(1.0, float(base) * 0.6 + recency_boost(result) * 0.4)


def parse_preferred_domains() -> list[str]:
    raw = os.getenv("ARGUS_RESEARCH_PREFERRED_DOMAINS", "")
    return [x.strip().lower() for x in raw.split(",") if x.strip()]


def preferred_domain_boost(host: str, preferred: list[str] | None = None) -> float:
    """Additive score bump when host matches preferred list (e.g. sec.gov, reuters.com)."""
    if not host:
        return 0.0
    prefs = preferred if preferred is not None else parse_preferred_domains()
    if not prefs:
        return 0.0
    h = host.lower().strip(".")
    for p in prefs:
        if not p:
            continue
        if h == p or h.endswith(f".{p}"):
            return min(0.35, 0.12 + 0.03 * len(p) / 20)
    return 0.0


def research_v2_enabled() -> bool:
    return os.getenv("ARGUS_RESEARCH_V2", "").lower() in ("1", "true", "yes")
