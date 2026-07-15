import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool
from clipscore.db.base import Base
from clipscore.db import models  # noqa: F401  — register ORM tables on Base.metadata


@pytest.fixture
def session():
    # StaticPool + check_same_thread=False: FastAPI's TestClient dispatches
    # requests via anyio on a separate thread, so a plain in-memory sqlite
    # engine (SingletonThreadPool) would hand that thread a *different*,
    # empty :memory: connection. Sharing one static connection across
    # threads lets web-route tests reuse this fixture's session unchanged.
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    with Session(engine) as s:
        yield s


import pytest
from clipscore.ingest.base import BaseIngester
from clipscore.ingest.dto import CampaignUpsert, SnapshotData


class FakeIngester(BaseIngester):
    source_name = "fake"

    def __init__(self, raws=None):
        self._raws = raws if raws is not None else [
            {"external_id": "a", "cpm": 1.5, "budget": 1000, "spent": 100, "clippers": 10, "views": 50000},
            {"external_id": "b", "cpm": 2.0, "budget": 500, "spent": 400, "clippers": 40, "views": 90000},
        ]

    def fetch(self):
        return list(self._raws)

    def normalize(self, raw):
        return CampaignUpsert(
            source="fake",
            external_id=raw["external_id"],
            title=f"camp {raw['external_id']}",
            niche="gaming",
            cpm_usd=raw["cpm"],
            platform_fee_pct=0.1,
            budget_total_usd=raw["budget"],
            allowed_socials=["tiktok"],
            status="active",
            snapshot=SnapshotData(
                budget_total_usd=raw["budget"],
                budget_spent_usd=raw["spent"],
                budget_remaining_usd=raw["budget"] - raw["spent"],
                active_clippers=raw["clippers"],
                total_views=raw["views"],
            ),
        )


@pytest.fixture
def fake_ingester():
    return FakeIngester()
