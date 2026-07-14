from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="CLIPSCORE_", env_file=".env", extra="ignore")

    db_url: str = "sqlite:///clipscore.db"
    poll_interval_minutes: int = 45
    unseen_polls_to_end: int = 3
    harvest_min_campaigns: int = 50
    default_p_approval: float = 0.7
    default_assumed_cap_usd: float = 500.0
    hours_per_clip: float = 0.75
    raw_retention_days: int = 14
    discord_token: str | None = None
    alert_percentile: float = 0.90
    min_niche_sample: int = 5
    discord_alert_channel_id: int | None = None
    summary_hour_et: int = 9
    enable_playwright: bool = False
    source_base_url: str = "https://contentrewards.com"
    discover_path: str = "/discover"
    # Campaign detail pages live on Whop, not under contentrewards.com/discover/<route>
    # (that path serves a soft-404). Links are built as {whop_base_url}/{whopProductRoute}.
    whop_base_url: str = "https://whop.com"
    user_agent: str = "clipscore/0.1 (+personal research; contact via repo)"
    http_timeout_s: int = 60
    llm_api_key: str | None = None
    llm_model: str = "claude-haiku-4-5"
    extract_from_whop_page: bool = True
    extract_enabled: bool = True
    # Modest pacing between real (non-injected-fetch) Whop page fetches within
    # a single enrich_batch sweep -- see plans/pipeline-b-stage-1-extraction.md
    # Global Constraints ("modest pacing"). Not applied when a fake `fetch` is
    # injected (tests stay fast).
    whop_fetch_pacing_s: float = 1.0


@lru_cache
def get_settings() -> Settings:
    return Settings()
