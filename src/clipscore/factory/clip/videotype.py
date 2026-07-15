"""URL -> Vizard `videoType` mapping (Pipeline B Stage B4.5).

Single source of truth for "which sources can Vizard fetch by URL, and as
what type". Used by BOTH `jobs/clipfactory.create_clip_job` (to route a
Vizard-fetchable URL to the no-download `passthrough` acquirer) and
`factory/clip/vizard.py` (to send the right `videoType`). Keeping one copy
prevents the mapping drift that broke the original adapter.

Vizard is URL-only. Types (probed 2026-07-15, see the `vizard-api-contract`
memory): 1=direct file (needs `ext`), 2=YouTube, 3=Google Drive *file*,
4=Vimeo, 9=Twitch. A URL we can't classify -> None (caller falls back to a
download path or surfaces it for manual handling).
"""
import re
from urllib.parse import urlparse

_DRIVE_FILE_RE = re.compile(r"/file/d/[^/]+")
_DIRECT_EXTS = ("mp4", "mov", "avi", "3gp")


def detect_video_type(url: str) -> tuple[int, str | None] | None:
    if not isinstance(url, str) or not url.strip():
        return None
    parsed = urlparse(url.strip())
    host = parsed.netloc.lower()
    path = parsed.path

    if "youtube.com" in host or "youtu.be" in host:
        return (2, None)
    if "drive.google.com" in host:
        return (3, None) if _DRIVE_FILE_RE.search(path) else None
    if "docs.google.com" in host:
        return None
    if "vimeo.com" in host:
        return (4, None)
    if "twitch.tv" in host:
        return (9, None)
    if "." in path:
        ext = path.rsplit(".", 1)[-1].lower()
        if ext in _DIRECT_EXTS:
            return (1, ext)
    return None
