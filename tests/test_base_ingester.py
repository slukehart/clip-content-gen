from clipscore.ingest.base import BaseIngester
from clipscore.ingest.dto import CampaignUpsert, SnapshotData


def test_fake_ingester_yields_upserts(fake_ingester):
    raws = fake_ingester.fetch()
    assert len(raws) == 2
    up = fake_ingester.normalize(raws[0])
    assert isinstance(up, CampaignUpsert)
    assert isinstance(up.snapshot, SnapshotData)
    assert up.source == "fake"


def test_baseingester_is_abstract():
    import pytest
    with pytest.raises(TypeError):
        BaseIngester()
