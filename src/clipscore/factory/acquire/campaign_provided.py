"""Acquirer for campaign-provided footage (the primary, authorized path).

Campaigns on the marketplace often hand out a share link (Drive/Dropbox) to
raw footage rather than a direct media URL. `_normalize_share_url` maps the
common share-link shapes to a direct-download URL; anything that resolves to
a folder listing or a doc (not a single file) is left to the operator --
never scraped/evaded.
"""
import re
from urllib.parse import parse_qs, urlparse

from clipscore.factory.acquire.base import AcquisitionResult, BaseAcquirer
from clipscore.factory.acquire.download import download_direct

_DRIVE_FILE_RE = re.compile(r"/file/d/([^/]+)")


def _normalize_share_url(source_ref: str) -> str | None:
    parsed = urlparse(source_ref)
    host = parsed.netloc.lower()

    if "drive.google.com" in host:
        match = _DRIVE_FILE_RE.search(parsed.path)
        if match:
            file_id = match.group(1)
            return f"https://drive.google.com/uc?export=download&id={file_id}"
        return None  # drive/folders, or an unrecognized Drive path shape

    if "docs.google.com" in host:
        return None

    if "dropbox.com" in host:
        query = parse_qs(parsed.query)
        query["dl"] = ["1"]
        new_query = "&".join(f"{k}={v[0]}" for k, v in query.items())
        return parsed._replace(query=new_query).geturl()

    # Plain media URL (or any other host we don't special-case) -- pass through.
    return source_ref


class CampaignProvidedAcquirer(BaseAcquirer):
    source_type = "campaign_provided"
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
        direct_url = _normalize_share_url(source_ref)
        if direct_url is None:
            return AcquisitionResult(
                status="manual",
                source_url=source_ref,
                error="folder_or_unsupported_share_link",
            )

        result = download_direct(
            direct_url, dest_path, client=client, ua=ua, robots_cache=robots_cache
        )
        result.platform = "campaign_provided"
        result.source_url = source_ref
        return result
