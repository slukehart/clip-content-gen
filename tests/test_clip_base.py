from types import SimpleNamespace

from clipscore.config import Settings
from clipscore.factory.clip.base import (
    ClipSpec, FakeClipEngine, build_engine, derive_specs,
)


def _campaign(**kw):
    base = dict(clip_min_len_s=None, clip_max_len_s=None,
                target_platforms='["tiktok"]')
    base.update(kw)
    return SimpleNamespace(**base)


def test_derive_specs_returns_single_window_from_campaign():
    spec = derive_specs(_campaign(clip_min_len_s=30, clip_max_len_s=90), Settings())
    assert isinstance(spec, ClipSpec)
    assert (spec.min_len_s, spec.max_len_s) == (30, 90)


def test_derive_specs_defaults_when_no_window():
    spec = derive_specs(_campaign(), Settings())
    assert (spec.min_len_s, spec.max_len_s) == (0, 0)


def test_clipspec_has_no_platform_variant():
    assert "platform_variant" not in ClipSpec.model_fields


def test_fake_engine_returns_multiple_platformless_clips():
    spec = ClipSpec(min_len_s=30, max_len_s=90)
    clips = FakeClipEngine().produce("https://youtu.be/abc", spec, dest_dir="/tmp/x")
    assert len(clips) == 3
    assert all(c.platform_variant is None for c in clips)
    assert all(c.engine == "fake" for c in clips)
    assert all(c.duration_s == 30 for c in clips)


def test_build_engine_selects_fake():
    assert build_engine(Settings(_env_file=None, clip_engine="fake")).name == "fake"
