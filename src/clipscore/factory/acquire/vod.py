"""VOD acquirer for creator-hosted platforms (`youtube`/`twitch`/`kick`).

Downloads go through `yt-dlp`, an OPTIONAL dependency that is NOT installed
by default and must not become a hard import-time requirement. `yt_dlp` is
therefore imported lazily, only inside `_ytdlp_download`'s body -- this
module must import cleanly with `yt-dlp` absent.

All tested logic goes through the `downloader` DI seam on `YtDlpAcquirer` so
CI never invokes real yt-dlp / network access; `_ytdlp_download` itself is
manual-acceptance-only.
"""
import re

from clipscore.factory.acquire.base import AcquisitionResult, BaseAcquirer

_UNAVAILABLE_RE = re.compile(r"private|removed|unavailable|geo", re.IGNORECASE)
_BLOCKED_RE = re.compile(r"rate.?limit|403|challenge", re.IGNORECASE)


class VodBlocked(Exception):
    """The source blocked or rate-limited the download attempt."""


class VodUnavailable(Exception):
    """The VOD is private, removed, geo-restricted, or otherwise unavailable."""


class YtDlpUnavailable(Exception):
    """`yt-dlp` is not installed."""


def _ytdlp_download(source_ref: str, dest_path_noext: str) -> dict:
    """Real yt-dlp download. Manual-acceptance-only; never hit in CI."""
    try:
        import yt_dlp
    except ImportError as exc:
        raise YtDlpUnavailable() from exc

    outtmpl = dest_path_noext + ".%(ext)s"
    try:
        with yt_dlp.YoutubeDL({"outtmpl": outtmpl}) as ydl:
            info = ydl.extract_info(source_ref, download=True)
            path = ydl.prepare_filename(info)
    except yt_dlp.utils.DownloadError as exc:
        message = str(exc)
        if _UNAVAILABLE_RE.search(message):
            raise VodUnavailable(message) from exc
        if _BLOCKED_RE.search(message):
            raise VodBlocked(message) from exc
        raise

    import os

    return {
        "path": path,
        "bytes": os.path.getsize(path) if os.path.exists(path) else None,
        "duration_s": info.get("duration"),
        "creator": info.get("uploader") or info.get("channel"),
    }


class YtDlpAcquirer(BaseAcquirer):
    """VOD acquirer for a single source_type (youtube/twitch/kick)."""

    requires_authorization = True

    def __init__(self, source_type: str, downloader=None):
        self.source_type = source_type
        self._downloader = downloader or _ytdlp_download

    def acquire(
        self,
        source_ref: str,
        dest_path: str,
        *,
        authorizing_campaign_id: str | None = None,
        client=None,
        ua: str = "clipscore",
        robots_cache: dict | None = None,
    ) -> AcquisitionResult:
        try:
            info = self._downloader(source_ref, dest_path)
        except VodBlocked:
            return AcquisitionResult(
                status="blocked",
                platform=self.source_type,
                source_url=source_ref,
            )
        except VodUnavailable:
            return AcquisitionResult(
                status="failed",
                error="vod_unavailable",
                platform=self.source_type,
                source_url=source_ref,
            )
        except YtDlpUnavailable:
            return AcquisitionResult(
                status="failed",
                error="yt_dlp_unavailable",
                platform=self.source_type,
                source_url=source_ref,
            )
        except Exception:
            return AcquisitionResult(
                status="failed",
                error="download_error",
                platform=self.source_type,
                source_url=source_ref,
            )

        return AcquisitionResult(
            status="acquired",
            storage_uri=info.get("path"),
            bytes=info.get("bytes"),
            duration_s=info.get("duration_s"),
            creator=info.get("creator"),
            platform=self.source_type,
            source_url=source_ref,
        )
