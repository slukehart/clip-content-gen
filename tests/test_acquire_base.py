from clipscore.factory.acquire.base import AcquisitionResult, BaseAcquirer


def test_acquisition_result_defaults():
    r = AcquisitionResult(status="manual", source_url="https://drive.google.com/x")
    assert r.status == "manual"
    assert r.storage_uri is None and r.bytes is None and r.error is None


def test_base_acquirer_is_abstract():
    import pytest
    with pytest.raises(TypeError):
        BaseAcquirer()  # abstract acquire() cannot be instantiated
