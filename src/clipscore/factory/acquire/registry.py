"""`source_type -> acquirer` registry for Pipeline B's acquisition layer.

`build_registry` wires up the acquirers from Tasks 1-3 into a single dict;
`select_acquirer` is a thin lookup the orchestrator uses so an unknown
`source_type` maps to `None` rather than a `KeyError`.
"""
from clipscore.factory.acquire.base import BaseAcquirer
from clipscore.factory.acquire.campaign_provided import CampaignProvidedAcquirer
from clipscore.factory.acquire.url import UrlAcquirer
from clipscore.factory.acquire.vod import YtDlpAcquirer


def build_registry(*, ytdlp_downloader=None) -> dict[str, BaseAcquirer]:
    return {
        "campaign_provided": CampaignProvidedAcquirer(),
        "url": UrlAcquirer(),
        "youtube": YtDlpAcquirer("youtube", ytdlp_downloader),
        "twitch": YtDlpAcquirer("twitch", ytdlp_downloader),
        "kick": YtDlpAcquirer("kick", ytdlp_downloader),
    }


def select_acquirer(source_type: str, registry: dict) -> BaseAcquirer | None:
    return registry.get(source_type)
