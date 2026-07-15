import pytest
from clipscore.factory.acquire.vod import (
    YtDlpAcquirer, VodBlocked, VodUnavailable, YtDlpUnavailable,
)

def test_import_does_not_require_ytdlp():
    import importlib
    importlib.import_module("clipscore.factory.acquire.vod")  # must not raise with yt-dlp absent

def test_success_maps_to_acquired():
    def fake(ref, dest): return {"path": dest + ".mp4", "bytes": 1234, "duration_s": 90, "creator": "diego"}
    a = YtDlpAcquirer("youtube", downloader=fake)
    r = a.acquire("https://youtube.com/watch?v=x", "/m/youtube/abc", authorizing_campaign_id="c1")
    assert r.status == "acquired" and r.platform == "youtube"
    assert r.storage_uri == "/m/youtube/abc.mp4" and r.duration_s == 90 and r.creator == "diego"
    assert a.requires_authorization is True

def test_blocked_maps_to_blocked():
    def fake(ref, dest): raise VodBlocked("429")
    r = YtDlpAcquirer("twitch", downloader=fake).acquire("u", "/m/twitch/abc")
    assert r.status == "blocked" and r.storage_uri is None

def test_unavailable_maps_to_failed():
    def fake(ref, dest): raise VodUnavailable("private video")
    r = YtDlpAcquirer("kick", downloader=fake).acquire("u", "/m/kick/abc")
    assert r.status == "failed" and r.error == "vod_unavailable"

def test_missing_ytdlp_maps_to_failed_unavailable():
    def fake(ref, dest): raise YtDlpUnavailable()
    r = YtDlpAcquirer("youtube", downloader=fake).acquire("u", "/m/youtube/abc")
    assert r.status == "failed" and r.error == "yt_dlp_unavailable"
