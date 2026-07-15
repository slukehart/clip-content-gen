import httpx
from clipscore.factory.acquire import download


def _client(handler):
    return httpx.Client(transport=httpx.MockTransport(handler))


def _robots_ok(req):
    if req.url.path == "/robots.txt":
        return httpx.Response(200, text="User-agent: *\nAllow: /\n")
    return None


def test_direct_media_is_downloaded(tmp_path):
    def h(req):
        return _robots_ok(req) or httpx.Response(200, content=b"VIDEO" * 100,
                                                 headers={"content-type": "video/mp4"})
    dest = str(tmp_path / "cp" / "abc")
    r = download.download_direct("https://x.test/v.mp4", dest, client=_client(h),
                                 ua="clipscore", robots_cache={})
    assert r.status == "acquired"
    assert r.storage_uri.endswith(".mp4") and r.bytes == 500


def test_403_is_blocked_not_saved(tmp_path):
    def h(req):
        return _robots_ok(req) or httpx.Response(403, text="nope")
    r = download.download_direct("https://x.test/v.mp4", str(tmp_path / "a"),
                                 client=_client(h), ua="clipscore", robots_cache={})
    assert r.status == "blocked" and r.storage_uri is None


def test_html_folder_page_is_manual(tmp_path):
    def h(req):
        return _robots_ok(req) or httpx.Response(200, text="<html>a drive folder</html>",
                                                 headers={"content-type": "text/html"})
    r = download.download_direct("https://drive.google.com/drive/folders/X", str(tmp_path / "a"),
                                 client=_client(h), ua="clipscore", robots_cache={})
    assert r.status == "manual" and r.error == "not_direct_media"


def test_html_captcha_is_blocked(tmp_path):
    def h(req):
        return _robots_ok(req) or httpx.Response(200, text="<html>please solve this recaptcha</html>",
                                                 headers={"content-type": "text/html"})
    r = download.download_direct("https://x.test/v", str(tmp_path / "a"),
                                 client=_client(h), ua="clipscore", robots_cache={})
    assert r.status == "blocked"


def test_robots_disallow_is_manual(tmp_path):
    def h(req):
        if req.url.path == "/robots.txt":
            return httpx.Response(200, text="User-agent: *\nDisallow: /\n")
        raise AssertionError("must not GET the file when robots disallows")
    r = download.download_direct("https://x.test/v.mp4", str(tmp_path / "a"),
                                 client=_client(h), ua="clipscore", robots_cache={})
    assert r.status == "manual" and r.error == "robots_disallow"
