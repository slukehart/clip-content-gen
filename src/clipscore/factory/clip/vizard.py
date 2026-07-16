"""Real Vizard clipping-engine adapter (Pipeline B Stage B4.5).

Rewritten against the real, probed Vizard REST contract (2026-07-15, see the
`vizard-api-contract` memory) -- the previous version never sent the
required `videoType`, polled the wrong status codes, and read `clips`
instead of the real `videos` field. Wire handling (submit/poll/download) is
now CI-tested against `httpx.MockTransport` in `tests/test_clip_vizard.py`
-- no real network touches CI. Only a run with a real `CLIPSCORE_VIZARD_API_KEY`
against the live API is manual-acceptance-only.

Flow: classify the source URL via `detect_video_type` (single source of
truth, shared with clip-job routing) -> submit for clipping -> poll for
completion (bounded by `clip_poll_interval_s` / `clip_poll_timeout_s`) ->
download each finished clip file into `dest_dir` -> map Vizard's `videos`
results to `ProducedClip`, splitting the project's `creditsUsed` evenly
across the returned clips.

Operator run (manual acceptance -- needs a real API key, never CI):

    CLIPSCORE_VIZARD_API_KEY=... CLIPSCORE_CLIP_ENGINE=vizard python3 -c "
    from clipscore.config import Settings
    from clipscore.factory.clip.base import ClipSpec
    from clipscore.factory.clip.vizard import VizardEngine
    engine = VizardEngine(Settings())
    clips = engine.produce(
        'https://youtu.be/XXXXXXXXXXX',
        ClipSpec(min_len_s=0, max_len_s=0),
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
from clipscore.factory.clip.videotype import detect_video_type

_API_BASE = "https://elb-api.vizard.ai/hvizard-server-front/open-api/v1"


class VizardEngine(BaseClipEngine):
    """Real Vizard adapter. Wire handling is CI-tested via `httpx.MockTransport`
    (see `tests/test_clip_vizard.py`); only the real-key/real-network run is
    manual-acceptance-only."""

    name = "vizard"

    def __init__(self, settings: Settings):
        if not settings.vizard_api_key:
            raise RuntimeError(
                "VizardEngine requires settings.vizard_api_key (CLIPSCORE_VIZARD_API_KEY)"
            )
        self.settings = settings
        self._headers = {"VIZARDAI_API_KEY": settings.vizard_api_key,
                         "Content-Type": "application/json"}
        self._transport = None  # tests inject an httpx.MockTransport here

    def _client(self) -> httpx.Client:
        return httpx.Client(base_url=_API_BASE, headers=self._headers,
                            timeout=self.settings.http_timeout_s,
                            transport=self._transport)

    def _download_client(self) -> httpx.Client:
        """A client for streaming clip files from the CDN. Shares the same
        transport (so tests' `httpx.MockTransport` still intercepts it) but
        carries none of the Vizard API-key headers -- those must never be
        sent to the clip CDN host."""
        return httpx.Client(timeout=self.settings.http_timeout_s,
                            transport=self._transport)

    def produce(self, source_uri: str, spec: ClipSpec, *, dest_dir: str) -> list[ProducedClip]:
        detected = detect_video_type(source_uri)
        if detected is None:
            raise RuntimeError(f"Vizard cannot fetch source by URL: {source_uri!r}")
        video_type, ext = detected
        with self._client() as client:
            project_id = self._submit(client, source_uri, video_type, ext, spec)
            videos, credits_used = self._poll(client, project_id)
            return self._download(client, videos, credits_used, dest_dir=dest_dir)

    def _submit(self, client, source_uri, video_type, ext, spec):
        s = self.settings
        payload = {"videoUrl": source_uri, "videoType": video_type,
                   "lang": "en", "preferLength": [0],
                   "ratioOfClip": s.vizard_ratio_of_clip,
                   "subtitleSwitch": int(s.vizard_subtitle),
                   "highlightSwitch": int(s.vizard_highlight),
                   "headlineSwitch": int(s.vizard_headline),
                   "emojiSwitch": int(s.vizard_emoji),
                   "autoBrollSwitch": int(s.vizard_broll),
                   "removeSilenceSwitch": int(s.vizard_remove_silence)}
        if video_type == 1:
            payload["ext"] = ext or "mp4"
        if spec.keyword:
            payload["keyword"] = spec.keyword
        resp = client.post("/project/create", json=payload)
        resp.raise_for_status()
        data = resp.json()
        if data.get("code") != 2000 or "projectId" not in data:
            raise RuntimeError(f"Vizard create rejected: {data}")
        return data["projectId"]

    def _poll(self, client, project_id):
        deadline = time.monotonic() + self.settings.clip_poll_timeout_s
        while True:
            resp = client.get(f"/project/query/{project_id}")
            resp.raise_for_status()
            data = resp.json()
            code = data.get("code")
            if code == 2000:
                return data.get("videos", []), data.get("creditsUsed", 0)
            if code != 1000:
                raise RuntimeError(f"Vizard project {project_id} failed: {data}")
            if time.monotonic() >= deadline:
                raise TimeoutError(
                    f"Vizard project {project_id} did not complete within "
                    f"{self.settings.clip_poll_timeout_s}s"
                )
            time.sleep(self.settings.clip_poll_interval_s)

    def _download(self, client, videos, credits_used, *, dest_dir):
        n = len(videos)
        per_clip_cost = (
            credits_used * self.settings.vizard_usd_per_credit / n if n else 0.0
        )
        produced = []
        with self._download_client() as dl_client:
            for i, clip in enumerate(videos):
                video_url = clip.get("videoUrl")
                dest_path = f"{dest_dir}/clip-{i}.mp4"
                if video_url:
                    storage.ensure_parent(dest_path)
                    with dl_client.stream("GET", video_url) as resp:
                        resp.raise_for_status()
                        with open(dest_path, "wb") as f:
                            for chunk in resp.iter_bytes():
                                f.write(chunk)
                ms = clip.get("videoMsDuration")
                produced.append(ProducedClip(
                    platform_variant=None,
                    storage_uri=dest_path,
                    duration_s=ms // 1000 if ms else None,
                    transcript=clip.get("transcript"),
                    engine="vizard",
                    engine_clip_id=str(clip.get("videoId")) if clip.get("videoId") else None,
                    cost_usd=per_clip_cost,
                    credits_used=credits_used,
                ))
        return produced
