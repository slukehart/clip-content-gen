"""Clip-engine abstraction for Pipeline B Stage B3.

`derive_specs` maps a campaign's accepted platforms + length constraints
into the `ClipSpec`s an engine must produce. `BaseClipEngine` is the ABC any
concrete clipping engine implements; `FakeClipEngine` is a no-I/O stand-in
used by tests and any CI-safe code path. `build_engine` selects the
configured engine at runtime (real Vizard adapter is manual-acceptance-only
-- see `clip/vizard.py`).
"""
import json
from abc import ABC, abstractmethod

from pydantic import BaseModel

from clipscore.config import Settings

_PLATFORM_VARIANT_MAP = {"tiktok": "tiktok", "instagram": "reels", "youtube": "shorts"}

# Fallback (min_len_s, max_len_s) per variant when the campaign doesn't specify.
_FALLBACK_LENGTHS = {
    "tiktok": (60, 180),
    "reels": (15, 90),
    "shorts": (15, 60),
}


class ClipSpec(BaseModel):
    platform_variant: str  # "tiktok" | "reels" | "shorts"
    min_len_s: int
    max_len_s: int


class ProducedClip(BaseModel):
    platform_variant: str
    storage_uri: str
    duration_s: int | None = None
    transcript: str | None = None
    engine: str
    engine_clip_id: str | None = None
    cost_usd: float | None = None


class BaseClipEngine(ABC):
    name: str = ""

    @abstractmethod
    def produce(
        self, source_uri: str, specs: list[ClipSpec], *, dest_dir: str
    ) -> list[ProducedClip]:
        ...


def _target_platforms(raw) -> list[str]:
    """`Campaign.target_platforms` is a JSON-array string (may be None) --
    parse it defensively like `factory/enrich._platforms`."""
    if isinstance(raw, list):
        return raw
    if isinstance(raw, str):
        try:
            val = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            return []
        return val if isinstance(val, list) else []
    return []


def derive_specs(campaign, settings: Settings) -> list[ClipSpec]:
    platforms = _target_platforms(getattr(campaign, "target_platforms", None))
    if platforms:
        wanted = {
            _PLATFORM_VARIANT_MAP[p] for p in platforms if p in _PLATFORM_VARIANT_MAP
        }
    else:
        wanted = set(_PLATFORM_VARIANT_MAP.values())
    # Iterate the map's insertion order (not the set) so the returned list has
    # a stable, deterministic order across runs/processes.
    variants = [v for v in _PLATFORM_VARIANT_MAP.values() if v in wanted]

    campaign_min = getattr(campaign, "clip_min_len_s", None)
    campaign_max = getattr(campaign, "clip_max_len_s", None)

    specs = []
    for variant in variants:
        if campaign_min is not None and campaign_max is not None:
            min_len_s, max_len_s = campaign_min, campaign_max
        else:
            min_len_s, max_len_s = _FALLBACK_LENGTHS[variant]
        specs.append(
            ClipSpec(platform_variant=variant, min_len_s=min_len_s, max_len_s=max_len_s)
        )
    return specs


class FakeClipEngine(BaseClipEngine):
    name = "fake"

    def produce(
        self, source_uri: str, specs: list[ClipSpec], *, dest_dir: str
    ) -> list[ProducedClip]:
        return [
            ProducedClip(
                platform_variant=spec.platform_variant,
                storage_uri=f"{dest_dir}/{spec.platform_variant}.mp4",
                duration_s=spec.min_len_s,
                transcript="fake transcript",
                engine="fake",
                engine_clip_id=f"fake-{i}",
                cost_usd=0.0,
            )
            for i, spec in enumerate(specs)
        ]


def build_engine(settings: Settings) -> BaseClipEngine:
    if settings.clip_engine == "fake":
        return FakeClipEngine()
    from clipscore.factory.clip.vizard import VizardEngine

    return VizardEngine(settings)
