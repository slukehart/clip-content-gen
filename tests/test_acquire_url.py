import httpx
from clipscore.factory.acquire.url import UrlAcquirer


def test_url_acquirer_downloads_and_requires_auth(tmp_path):
    def h(req):
        if req.url.path == "/robots.txt":
            return httpx.Response(200, text="User-agent: *\nAllow: /\n")
        return httpx.Response(200, content=b"m" * 20, headers={"content-type": "video/mp4"})
    a = UrlAcquirer()
    assert a.requires_authorization is True
    r = a.acquire("https://x.test/clip.mp4", str(tmp_path / "u" / "k"),
                  client=httpx.Client(transport=httpx.MockTransport(h)), ua="clipscore",
                  robots_cache={})
    assert r.status == "acquired" and r.platform == "url"
