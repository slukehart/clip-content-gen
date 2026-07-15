"""Shared direct-download HTTP path for Pipeline B's acquisition layer.

Drop-don't-evade: robots.txt is checked before every GET, and
`classify_response` (HTML-page-specific) is used to distinguish a genuine
bot-challenge (captcha / cf_challenge) from an ordinary non-media HTML page
(folder listing, login wall) on any `text/html` response. No header
spoofing, no CAPTCHA solving, no retries past a halt -- callers surface a
"manual" or "blocked" status and stop.
"""
from pathlib import PurePosixPath
from urllib.parse import urlparse

import httpx

from clipscore.factory.acquire import storage
from clipscore.factory.acquire.base import AcquisitionResult
from clipscore.factory.whop import _robots_allowed
from clipscore.ingest.detect import classify_response

_MEDIA_EXTENSIONS = {
    "video/mp4": ".mp4",
    "video/quicktime": ".mov",
    "video/webm": ".webm",
    "audio/mpeg": ".mp3",
}


def _ext_for(url: str, content_type: str) -> str:
    content_type = (content_type or "").split(";")[0].strip().lower()
    if content_type in _MEDIA_EXTENSIONS:
        return _MEDIA_EXTENSIONS[content_type]
    url_suffix = PurePosixPath(urlparse(url).path).suffix
    if content_type == "application/octet-stream":
        return url_suffix or ".mp4"
    return url_suffix or ".bin"


def download_direct(
    url: str,
    dest_path_noext: str,
    *,
    client: httpx.Client,
    ua: str,
    robots_cache: dict | None = None,
) -> AcquisitionResult:
    if not _robots_allowed(client, ua, url, robots_cache):
        return AcquisitionResult(status="manual", source_url=url, error="robots_disallow")

    with client.stream("GET", url, headers={"User-Agent": ua}) as resp:
        status_code = resp.status_code
        content_type = resp.headers.get("content-type", "")

        if status_code == 403:
            return AcquisitionResult(status="blocked", source_url=url, error="blocked_403")
        if status_code == 429:
            return AcquisitionResult(status="blocked", source_url=url, error="rate_limited_429")
        if status_code >= 400:
            return AcquisitionResult(status="failed", source_url=url, error=f"http_{status_code}")

        if content_type.split(";")[0].strip().lower() == "text/html":
            resp.read()
            body = resp.text
            event = classify_response(status_code, body)
            if event in ("captcha", "cf_challenge"):
                return AcquisitionResult(status="blocked", source_url=url, error=event)
            return AcquisitionResult(status="manual", source_url=url, error="not_direct_media")

        ext = _ext_for(url, content_type)
        dest_path = dest_path_noext + ext
        storage.ensure_parent(dest_path)
        total_bytes = 0
        with open(dest_path, "wb") as f:
            for chunk in resp.iter_bytes():
                f.write(chunk)
                total_bytes += len(chunk)

        return AcquisitionResult(
            status="acquired",
            storage_uri=dest_path,
            bytes=total_bytes,
            source_url=url,
        )
