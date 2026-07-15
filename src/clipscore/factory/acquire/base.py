"""Base types for Pipeline B's acquisition layer (Stage B2).

`AcquisitionResult` is the uniform return type every acquirer produces,
regardless of source (campaign-provided link, YouTube/TikTok/IG VOD, manual
capture). `BaseAcquirer` is the ABC that concrete acquirers (downloaders,
VOD acquirers, orchestrator glue — later tasks) implement.

No network, no ORM imports here — pure interface definitions.
"""
from abc import ABC, abstractmethod

from pydantic import BaseModel


class AcquisitionResult(BaseModel):
    status: str  # "acquired" | "blocked" | "manual" | "failed"
    storage_uri: str | None = None
    bytes: int | None = None
    duration_s: int | None = None
    creator: str | None = None
    platform: str | None = None
    source_url: str | None = None
    error: str | None = None


class BaseAcquirer(ABC):
    source_type: str = ""
    requires_authorization: bool = False

    @abstractmethod
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
        ...
