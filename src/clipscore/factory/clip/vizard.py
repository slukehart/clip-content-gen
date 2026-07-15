"""Real Vizard clipping-engine adapter (Pipeline B Stage B3).

Manual-acceptance-only: this module talks to the real Vizard REST API over
the network and is never imported or exercised by the CI test suite (see
`tests/test_clip_base.py`, which only touches `clip/base.py`). It is loaded
lazily by `build_engine()` when `settings.clip_engine != "fake"`.

Flow: submit the source video for clipping -> poll for completion (bounded
by `clip_poll_interval_s` / `clip_poll_timeout_s`) -> download each finished
clip file into `dest_dir` -> map Vizard's clip results to `ProducedClip`.

Operator run (Step 5, manual acceptance -- needs a real API key, never CI):

    CLIPSCORE_VIZARD_API_KEY=... CLIPSCORE_CLIP_ENGINE=vizard python3 -c "
    from clipscore.config import Settings
    from clipscore.factory.clip.base import ClipSpec
    from clipscore.factory.clip.vizard import VizardEngine
    engine = VizardEngine(Settings())
    clips = engine.produce(
        'https://example.com/source.mp4',
        [ClipSpec(platform_variant='tiktok', min_len_s=60, max_len_s=180)],
        dest_dir='./media/clips/manual-test',
    )
    print(clips)
    "
"""
import time

import httpx

from clipscore.config import Settings
from clipscore.factory.acquire import storage
from clipscore.factory.clip.base import BaseClipEngine, ClipSpec, ProducedClip

_API_BASE = "https://elb-api.vizard.ai/hvizard-server-front/open-api/v1"


class VizardEngine(BaseClipEngine):
    """Manual-acceptance-only. Never invoked in CI -- see module docstring."""

    name = "vizard"

    def __init__(self, settings: Settings):
        if not settings.vizard_api_key:
            raise RuntimeError(
                "VizardEngine requires settings.vizard_api_key (CLIPSCORE_VIZARD_API_KEY)"
            )
        self.settings = settings
        self._headers = {"VIZARDAI_API_KEY": settings.vizard_api_key}

    def produce(
        self, source_uri: str, specs: list[ClipSpec], *, dest_dir: str
    ) -> list[ProducedClip]:
        with httpx.Client(
            base_url=_API_BASE, headers=self._headers, timeout=self.settings.http_timeout_s
        ) as client:
            project_id = self._submit(client, source_uri, specs)
            clip_results = self._poll(client, project_id)
            return self._download(client, clip_results, specs, dest_dir=dest_dir)

    def _submit(self, client: httpx.Client, source_uri: str, specs: list[ClipSpec]) -> str:
        # One project per source video; Vizard clips the full source and
        # returns a set of candidate clips we filter/match to our specs.
        max_len = max((spec.max_len_s for spec in specs), default=180)
        resp = client.post(
            "/project/create",
            json={
                "videoUrl": source_uri,
                "lang": "en",
                "preferLength": [max_len],
            },
        )
        resp.raise_for_status()
        return resp.json()["projectId"]

    def _poll(self, client: httpx.Client, project_id: str) -> list[dict]:
        deadline = time.monotonic() + self.settings.clip_poll_timeout_s
        while True:
            resp = client.get(f"/project/query/{project_id}")
            resp.raise_for_status()
            data = resp.json()
            status = data.get("status")
            if status == "success" or status == 2:
                return data.get("clips", [])
            if status in ("failed", 1) or status == -1:
                raise RuntimeError(f"Vizard project {project_id} failed: {data}")
            if time.monotonic() >= deadline:
                raise TimeoutError(
                    f"Vizard project {project_id} did not complete within "
                    f"{self.settings.clip_poll_timeout_s}s"
                )
            time.sleep(self.settings.clip_poll_interval_s)

    def _download(
        self,
        client: httpx.Client,
        clip_results: list[dict],
        specs: list[ClipSpec],
        *,
        dest_dir: str,
    ) -> list[ProducedClip]:
        produced = []
        for i, spec in enumerate(specs):
            clip = clip_results[i] if i < len(clip_results) else {}
            video_url = clip.get("videoUrl")
            dest_path = f"{dest_dir}/{spec.platform_variant}.mp4"
            if video_url:
                storage.ensure_parent(dest_path)
                with client.stream("GET", video_url) as resp:
                    resp.raise_for_status()
                    with open(dest_path, "wb") as f:
                        for chunk in resp.iter_bytes():
                            f.write(chunk)
            produced.append(
                ProducedClip(
                    platform_variant=spec.platform_variant,
                    storage_uri=dest_path,
                    duration_s=clip.get("videoMsDuration", 0) // 1000 if clip.get("videoMsDuration") else None,
                    transcript=clip.get("transcript"),
                    engine="vizard",
                    engine_clip_id=str(clip.get("videoId")) if clip.get("videoId") else None,
                    cost_usd=self.settings.clip_est_cost_usd,
                )
            )
        return produced
