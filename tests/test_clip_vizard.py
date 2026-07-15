import json

import httpx

from clipscore.config import Settings
from clipscore.factory.clip.base import ClipSpec
from clipscore.factory.clip.vizard import VizardEngine


def _engine(handler, tmp_dir, **over):
    settings = Settings(_env_file=None, vizard_api_key="k", clip_poll_interval_s=0.0,
                        vizard_usd_per_credit=0.10, **over)
    eng = VizardEngine(settings)
    eng._transport = httpx.MockTransport(handler)   # test seam (see Step 3)
    return eng


def test_produce_submits_videotype_polls_and_downloads(tmp_path):
    calls = {"create": 0, "query": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/project/create"):
            calls["create"] += 1
            body = json.loads(request.content)
            assert body["videoType"] == 2            # YouTube
            assert body["videoUrl"] == "https://youtu.be/abc"
            assert body["preferLength"] == [0]
            return httpx.Response(200, json={"code": 2000, "projectId": 42})
        if "/project/query/" in request.url.path:
            calls["query"] += 1
            if calls["query"] == 1:
                return httpx.Response(200, json={"code": 1000})   # processing
            return httpx.Response(200, json={
                "code": 2000, "creditsUsed": 14,
                "videos": [
                    {"videoUrl": "https://cdn/v0.mp4", "videoMsDuration": 32000,
                     "transcript": "t0", "videoId": "v0", "viralScore": "9"},
                    {"videoUrl": "https://cdn/v1.mp4", "videoMsDuration": 41000,
                     "transcript": "t1", "videoId": "v1", "viralScore": "7"},
                ],
            })
        # clip download
        return httpx.Response(200, content=b"FAKEMP4")

    eng = _engine(handler, tmp_path)
    clips = eng.produce("https://youtu.be/abc", ClipSpec(min_len_s=0, max_len_s=0),
                        dest_dir=str(tmp_path))
    assert calls["create"] == 1 and calls["query"] == 2
    assert len(clips) == 2
    assert clips[0].engine == "vizard" and clips[0].platform_variant is None
    assert clips[0].duration_s == 32 and clips[0].engine_clip_id == "v0"
    # 14 credits * $0.10 / 2 clips = $0.70 each
    assert round(clips[0].cost_usd, 2) == 0.70
    assert (tmp_path / "clip-0.mp4").read_bytes() == b"FAKEMP4"


def test_produce_raises_on_unsupported_source(tmp_path):
    def handler(request):  # should never be called
        raise AssertionError("no HTTP call expected")
    eng = _engine(handler, tmp_path)
    try:
        eng.produce("https://example.com/page.html", ClipSpec(min_len_s=0, max_len_s=0),
                    dest_dir=str(tmp_path))
        assert False, "expected RuntimeError"
    except RuntimeError:
        pass


def test_produce_raises_on_error_code(tmp_path):
    def handler(request):
        if request.url.path.endswith("/project/create"):
            return httpx.Response(200, json={"code": 2000, "projectId": 1})
        return httpx.Response(200, json={"code": 4000, "errMsg": "bad source"})
    eng = _engine(handler, tmp_path)
    try:
        eng.produce("https://youtu.be/abc", ClipSpec(min_len_s=0, max_len_s=0),
                    dest_dir=str(tmp_path))
        assert False, "expected RuntimeError"
    except RuntimeError:
        pass
