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
    clip_retention_days: int = 14  # age sweep for produced clip files (clips-only; passthrough keeps no source)
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
    llm_base_url: str = "https://openrouter.ai/api/v1"
    llm_model: str = "moonshotai/kimi-k2"
    extract_from_whop_page: bool = True
    extract_enabled: bool = True
    # Modest pacing between real (non-injected-fetch) Whop page fetches within
    # a single enrich_batch sweep -- see plans/pipeline-b-stage-1-extraction.md
    # Global Constraints ("modest pacing"). Not applied when a fake `fetch` is
    # injected (tests stay fast).
    whop_fetch_pacing_s: float = 1.0
    media_dir: str = "media/"
    max_media_gb: float = 50.0
    vizard_api_key: str | None = None
    clip_engine: str = "vizard"
    clip_poll_interval_s: float = 10.0
    clip_poll_timeout_s: float = 1800.0
    clip_est_cost_usd: float = 0.0
    vizard_usd_per_credit: float = 0.0
    monthly_cap_credits: int = 0  # 0 = uncapped; else block paid jobs projected over this in the ET month
    vizard_ratio_of_clip: int = 1   # 1=9:16, 2=1:1, 3=4:5, 4=16:9
    vizard_subtitle: bool = True
    vizard_highlight: bool = True
    vizard_headline: bool = True
    vizard_emoji: bool = True
    vizard_broll: bool = True
    vizard_remove_silence: bool = True


@lru_cache
def get_settings() -> Settings:
    return Settings()
