"""Acquirer for generic, operator-supplied media URLs.

Unlike `campaign_provided`, a bare URL was not vetted as part of an approved
campaign, so `requires_authorization` is True -- the orchestrator (later
task) must pair it with an `authorizing_campaign_id` before use.
"""
from clipscore.factory.acquire.base import AcquisitionResult, BaseAcquirer
from clipscore.factory.acquire.download import download_direct


class UrlAcquirer(BaseAcquirer):
    source_type = "url"
    requires_authorization = True

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
        result = download_direct(
            source_ref, dest_path, client=client, ua=ua, robots_cache=robots_cache
        )
        result.platform = "url"
        result.source_url = source_ref
        return result
