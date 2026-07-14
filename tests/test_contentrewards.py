from pathlib import Path
import httpx, pytest
from clipscore.config import get_settings
from clipscore.ingest.contentrewards import ContentrewardsIngester
from clipscore.ingest.detect import SourceHalted

FIX = Path("tests/fixtures/contentrewards/discover_golden.html").read_text(encoding="utf-8")
ROBOTS_OK = "User-Agent: *\nAllow: /discover\nDisallow: /api/\n"

@pytest.fixture(autouse=True)
def _clear():
    get_settings.cache_clear(); yield; get_settings.cache_clear()

def _client(handler):
    return httpx.Client(transport=httpx.MockTransport(handler), base_url="https://contentrewards.com")

def test_fetch_parses_campaigns():
    def handler(req):
        if req.url.path == "/robots.txt":
            return httpx.Response(200, text=ROBOTS_OK)
        return httpx.Response(200, text=FIX)
    raws = ContentrewardsIngester(client=_client(handler)).fetch()
    assert len(raws) == 5

def test_fetch_403_raises_halt():
    def handler(req):
        if req.url.path == "/robots.txt":
            return httpx.Response(200, text=ROBOTS_OK)
        return httpx.Response(403, text="Forbidden")
    with pytest.raises(SourceHalted) as ei:
        ContentrewardsIngester(client=_client(handler)).fetch()
    assert ei.value.event_type == "blocked_403"

def test_robots_disallow_raises_halt():
    def handler(req):
        if req.url.path == "/robots.txt":
            return httpx.Response(200, text="User-Agent: *\nDisallow: /discover\n")
        return httpx.Response(200, text=FIX)
    with pytest.raises(SourceHalted) as ei:
        ContentrewardsIngester(client=_client(handler)).fetch()
    assert ei.value.event_type == "robots_disallow"

def test_normalize_maps_fields():
    ing = ContentrewardsIngester()
    raw = {"id": "abc", "whopExperienceId": "exp_1", "whopProductRoute": "slug",
           "title": "T", "brand": "B", "category": "Personal Brand",
           "campaignType": "clipping", "pricePerView": "$1.50",
           "totalBudget": "$250,000", "budgetSpent": "$50,000", "creators": 10,
           "socialPlatforms": ["tiktok", "instagram"], "isVerified": True,
           "status": "completed", "description": "Max $500 per video.",
           "stats": {"successRate": 26, "engagement": "50000.0", "viewCount": "51.4M"}}
    up = ing.normalize(raw)
    assert up.external_id == "abc" and up.whop_experience_id == "exp_1"
    assert up.niche == "personal brand"           # category, slugified
    assert up.campaign_type == "clipping"
    assert up.cpm_usd == 1.5 and up.budget_total_usd == 250000.0
    assert up.status == "ended"                    # completed -> ended
    assert up.cap_per_post_usd == 500.0 and up.cap_provenance == "observed"
    assert up.snapshot.budget_remaining_usd == 200000.0
    assert up.snapshot.total_views == 51_400_000
    assert up.snapshot.active_clippers == 10
    assert up.snapshot.success_rate == 26.0
    assert up.allowed_socials == ["tiktok", "instagram"]
