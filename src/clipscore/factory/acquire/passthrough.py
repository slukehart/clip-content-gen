"""No-download acquirer for Vizard-fetchable public URLs (Pipeline B B4.5).

Vizard fetches the source itself by URL, so for a YouTube/Twitch/Drive-file/
direct-mp4 link there is nothing to download: we simply record the public URL
as a `SourceAsset` (`storage_uri=None`) and let the clip step hand that URL to
the engine. A URL Vizard can't fetch is surfaced as `manual` (operator handles
it) -- never scraped or evaded.
"""
from clipscore.factory.acquire.base import AcquisitionResult, BaseAcquirer
from clipscore.factory.clip.videotype import detect_video_type


class PassthroughAcquirer(BaseAcquirer):
    source_type = "passthrough"
    requires_authorization = False

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
        if detect_video_type(source_ref) is None:
            return AcquisitionResult(
                status="manual",
                source_url=source_ref,
                error="unsupported_passthrough_url",
            )
        return AcquisitionResult(
            status="acquired",
            storage_uri=None,
            source_url=source_ref,
            platform="passthrough",
        )
