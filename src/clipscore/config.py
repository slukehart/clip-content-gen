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
    discord_token: str | None = None
    enable_playwright: bool = False


@lru_cache
def get_settings() -> Settings:
    return Settings()
