from clipscore.factory.clip.base import ClipSpec, ProducedClip, FakeClipEngine, derive_specs, build_engine
from clipscore.db.models import Campaign
from clipscore.config import Settings


def test_derive_specs_maps_platforms_and_uses_campaign_lengths():
    c = Campaign(source="cr", external_id="x", status="active",
                 target_platforms='["tiktok", "instagram"]', clip_min_len_s=20, clip_max_len_s=45)
    specs = derive_specs(c, Settings(_env_file=None))
    variants = {s.platform_variant for s in specs}
    assert variants == {"tiktok", "reels"}
    assert all(s.min_len_s == 20 and s.max_len_s == 45 for s in specs)


def test_derive_specs_defaults_all_variants_with_fallback_lengths_when_silent():
    c = Campaign(source="cr", external_id="y", status="active", target_platforms=None,
                 clip_min_len_s=None, clip_max_len_s=None)
    specs = {s.platform_variant: s for s in derive_specs(c, Settings(_env_file=None))}
    assert set(specs) == {"tiktok", "reels", "shorts"}
    assert (specs["tiktok"].min_len_s, specs["tiktok"].max_len_s) == (60, 180)
    assert (specs["shorts"].min_len_s, specs["shorts"].max_len_s) == (15, 60)


def test_fake_engine_produces_one_clip_per_spec():
    specs = [ClipSpec(platform_variant="tiktok", min_len_s=60, max_len_s=180),
             ClipSpec(platform_variant="reels", min_len_s=15, max_len_s=90)]
    clips = FakeClipEngine().produce("s3://src.mp4", specs, dest_dir="/m/clips/abc")
    assert [c.platform_variant for c in clips] == ["tiktok", "reels"]
    assert all(c.engine == "fake" and c.cost_usd == 0.0 for c in clips)
    assert clips[0].storage_uri == "/m/clips/abc/tiktok.mp4"


def test_build_engine_selects_fake():
    assert build_engine(Settings(_env_file=None, clip_engine="fake")).name == "fake"
