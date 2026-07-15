from clipscore.factory.acquire.passthrough import PassthroughAcquirer
from clipscore.factory.acquire.registry import build_registry, select_acquirer


def test_supported_url_acquires_without_download():
    acq = PassthroughAcquirer()
    res = acq.acquire("https://www.youtube.com/watch?v=abc", "/tmp/should-not-be-used.mp4")
    assert res.status == "acquired"
    assert res.storage_uri is None
    assert res.source_url == "https://www.youtube.com/watch?v=abc"
    assert res.platform == "passthrough"


def test_unsupported_url_is_manual():
    acq = PassthroughAcquirer()
    res = acq.acquire("https://example.com/page.html", "/tmp/x")
    assert res.status == "manual"
    assert res.error == "unsupported_passthrough_url"
    assert res.source_url == "https://example.com/page.html"


def test_no_authorization_required():
    assert PassthroughAcquirer().requires_authorization is False


def test_registered_in_registry():
    reg = build_registry()
    acq = select_acquirer("passthrough", reg)
    assert isinstance(acq, PassthroughAcquirer)
