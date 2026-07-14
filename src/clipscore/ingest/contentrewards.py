"""Ingester for contentrewards.com/discover (== Whop Content Rewards).

Compliance: robots.txt allows /discover, disallows /api/ (checked at runtime,
every poll). Single plain GET of the already-served public page; no Playwright,
no /api/ probing. Any challenge/block => SourceHalted (drop-don't-evade).
Initial recon 2026-07-13: robots allows /discover; site ToS has no anti-scraping
clause. See docs/spikes/2026-07-13-phase-0-stable-key-spike.md for payload shape."""
import httpx
from urllib.robotparser import RobotFileParser
from clipscore.config import get_settings
from clipscore.ingest.base import BaseIngester
from clipscore.ingest.dto import CampaignUpsert, SnapshotData
from clipscore.ingest.rsc import parse_discover
from clipscore.ingest.detect import classify_response, SourceHalted
from clipscore.ingest.extract import extract_requirements
from clipscore.ingest import coerce

_TERMINAL = {"completed": "ended", "ended": "ended", "paused": "paused", "active": "active"}

class ContentrewardsIngester(BaseIngester):
    source_name = "contentrewards"

    def __init__(self, client: httpx.Client | None = None, etag: str | None = None):
        s = get_settings()
        self._base = s.source_base_url
        self._path = s.discover_path
        self._whop = s.whop_base_url
        self._ua = s.user_agent
        self._timeout = s.http_timeout_s
        self._client = client
        self._etag = etag

    def _http(self) -> httpx.Client:
        return self._client or httpx.Client(base_url=self._base, timeout=self._timeout,
                                            headers={"User-Agent": self._ua}, follow_redirects=True)

    def _discover_url(self) -> str:
        return f"{self._base}{self._path}"

    def _check_robots(self, client: httpx.Client) -> None:
        try:
            r = client.get("/robots.txt")
        except httpx.HTTPError:
            return  # robots unreachable: fail open on the check, response classifier still guards
        rp = RobotFileParser()
        rp.parse(r.text.splitlines())
        if not rp.can_fetch(self._ua, self._path):
            raise SourceHalted(self._discover_url(), "robots_disallow", None,
                               f"robots.txt disallows {self._path}")

    def fetch(self) -> list[dict]:
        client = self._http()
        try:
            self._check_robots(client)
            headers = {"If-None-Match": self._etag} if self._etag else {}
            resp = client.get(self._path, headers=headers)
            if resp.status_code == 304:
                return []  # unchanged since last poll; caller keeps prior state
            body = resp.text
            event = classify_response(resp.status_code, body)
            if event != "ok":
                raise SourceHalted(self._discover_url(), event, resp.status_code,
                                   f"classify_response={event}")
            self._etag = resp.headers.get("ETag") or self._etag
            return parse_discover(body)
        finally:
            if self._client is None:
                client.close()

    def normalize(self, raw: dict) -> CampaignUpsert:
        stats = raw.get("stats") or {}
        req = extract_requirements(raw.get("description"))
        total = coerce.money_to_float(raw.get("totalBudget"))
        spent = coerce.money_to_float(raw.get("budgetSpent"))
        remaining = (total - spent) if (total is not None and spent is not None) else None
        category = raw.get("category")
        niche = category.strip().lower() if isinstance(category, str) and category.strip() else None
        route = raw.get("whopProductRoute")
        url = f"{self._whop}/{route}" if route else self._discover_url()
        return CampaignUpsert(
            source=self.source_name,
            external_id=raw["id"],
            whop_experience_id=raw.get("whopExperienceId"),
            whop_product_route=route,
            url=url,
            brand=raw.get("brand"),
            title=raw.get("title"),
            niche=niche,
            campaign_type=raw.get("campaignType"),
            cpm_usd=coerce.money_to_float(raw.get("pricePerView")),
            platform_fee_pct=None,  # source default applied at scoring from platform_trust
            cap_per_post_usd=req["cap_per_post_usd"],
            cap_provenance=req["cap_provenance"],
            min_payout_threshold_usd=req["min_payout_threshold_usd"],
            min_views_threshold=req["min_views_threshold"],
            budget_total_usd=total,
            allowed_socials=raw.get("socialPlatforms"),
            requirements_raw=raw.get("description"),
            status=_TERMINAL.get(raw.get("status"), "active"),
            is_verified=raw.get("isVerified"),
            snapshot=SnapshotData(
                budget_total_usd=total,
                budget_spent_usd=spent,
                budget_remaining_usd=remaining,
                active_clippers=coerce.to_int(raw.get("creators")),
                total_views=coerce.views_to_int(stats.get("viewCount")),
                success_rate=coerce.to_float(stats.get("successRate")),
                engagement=coerce.to_float(stats.get("engagement")),
            ),
        )
