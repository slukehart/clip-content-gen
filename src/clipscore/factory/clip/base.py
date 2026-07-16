"""Clip-engine abstraction for Pipeline B Stage B3 / B4.5.

`derive_specs` maps a campaign's clip-length preference into a single
`ClipSpec` (a length window). Vizard (and any engine) picks its own clips
and count from the source video -- there is no per-platform variant
request anymore; Vizard returns format-identical vertical clips regardless
of destination platform. `BaseClipEngine` is the ABC any concrete clipping
engine implements; `FakeClipEngine` is a no-I/O stand-in used by tests and
any CI-safe code path. `build_engine` selects the configured engine at
runtime (real Vizard adapter is manual-acceptance-only -- see
`clip/vizard.py`).
"""
from abc import ABC, abstractmethod

from pydantic import BaseModel

from clipscore.config import Settings


class ClipSpec(BaseModel):
    min_len_s: int
    max_len_s: int


class ProducedClip(BaseModel):
    platform_variant: str | None = None
    storage_uri: str
    duration_s: int | None = None
    transcript: str | None = None
    engine: str
    engine_clip_id: str | None = None
    cost_usd: float | None = None
    credits_used: int | None = None  # project-level creditsUsed (same on every clip of one run)


class BaseClipEngine(ABC):
    name: str = ""

    @abstractmethod
    def produce(
        self, source_uri: str, spec: ClipSpec, *, dest_dir: str
    ) -> list[ProducedClip]:
        ...


def derive_specs(campaign, settings: Settings) -> ClipSpec:
    """The clip-length preference for this campaign as a single window.
    Vizard picks the clips and their count; the window is advisory (used for
    `preferLength` and as a matching hint). Both bounds present -> use them;
    otherwise (0, 0) = 'no preference'."""
    lo = getattr(campaign, "clip_min_len_s", None)
    hi = getattr(campaign, "clip_max_len_s", None)
    if lo is not None and hi is not None:
        return ClipSpec(min_len_s=lo, max_len_s=hi)
    return ClipSpec(min_len_s=0, max_len_s=0)


class FakeClipEngine(BaseClipEngine):
    name = "fake"

    def produce(self, source_uri: str, spec: ClipSpec, *, dest_dir: str) -> list[ProducedClip]:
        return [
            ProducedClip(
                platform_variant=None,
                storage_uri=f"{dest_dir}/clip-{i}.mp4",
                duration_s=spec.min_len_s,
                transcript="fake transcript",
                engine="fake",
                engine_clip_id=f"fake-{i}",
                cost_usd=0.0,
                credits_used=0,
            )
            for i in range(3)
        ]


def build_engine(settings: Settings) -> BaseClipEngine:
    if settings.clip_engine == "fake":
        return FakeClipEngine()
    from clipscore.factory.clip.vizard import VizardEngine

    return VizardEngine(settings)
