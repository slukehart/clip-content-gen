from dataclasses import dataclass

RawCampaign = dict


@dataclass
class SnapshotData:
    budget_total_usd: float | None = None
    budget_spent_usd: float | None = None
    budget_remaining_usd: float | None = None
    active_clippers: int | None = None
    total_views: int | None = None
    success_rate: float | None = None
    engagement: float | None = None


@dataclass
class CampaignUpsert:
    source: str
    external_id: str
    snapshot: SnapshotData
    title: str | None = None
    campaign_type: str | None = None
    niche: str | None = None
    cpm_usd: float | None = None
    platform_fee_pct: float | None = None
    cap_per_post_usd: float | None = None
    cap_provenance: str = "absent"
    min_payout_threshold_usd: float | None = None
    min_views_threshold: int | None = None
    budget_total_usd: float | None = None
    allowed_socials: list | None = None
    requirements_raw: str | None = None
    status: str = "active"
    is_verified: bool | None = None
    whop_experience_id: str | None = None
    whop_product_route: str | None = None
    url: str | None = None
    brand: str | None = None
