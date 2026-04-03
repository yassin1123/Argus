import ipaddress
from urllib.parse import urlparse
from typing import Any

import httpx
from bs4 import BeautifulSoup


def validate_public_url(url: str) -> str:
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise ValueError("Only http and https URLs are allowed")
    host = parsed.hostname
    if not host:
        raise ValueError("Invalid URL")
    h = host.lower().rstrip(".")
    if h in ("localhost", "127.0.0.1", "0.0.0.0", "metadata.google.internal", "metadata", "[::1]"):
        raise ValueError("URL host is not allowed (SSRF protection)")
    if h.endswith(".local"):
        raise ValueError("URL host is not allowed (SSRF protection)")
    try:
        ip = ipaddress.ip_address(h.strip("[]"))
        if (
            ip.is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_multicast
            or ip.is_reserved
        ):
            raise ValueError("URL resolves to a blocked address")
    except ValueError as e:
        if "blocked address" in str(e):
            raise
    return url


async def parse_url(url: str) -> dict[str, Any]:
    validate_public_url(url)
    headers = {"User-Agent": "ArgusBot/1.0 (research tool)"}
    async with httpx.AsyncClient(timeout=15.0) as client:
        response = await client.get(url, headers=headers, follow_redirects=True)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser")
    for tag in soup(["script", "style", "nav", "footer", "header", "aside"]):
        tag.decompose()
    title = soup.title.string.strip() if soup.title and soup.title.string else url
    meta_desc = ""
    meta = soup.find("meta", attrs={"name": "description"})
    if meta:
        meta_desc = meta.get("content", "") or ""
    body = soup.find("body")
    content = body.get_text(separator="\n", strip=True) if body else ""
    return {
        "content": content,
        "title": title,
        "description": meta_desc,
        "url": url,
        "word_count": len(content.split()),
    }
