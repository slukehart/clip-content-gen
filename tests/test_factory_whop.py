import httpx
from clipscore.factory.whop import fetch_page_text

_PAGE = "<html>" + "self.__next_f.push(['x','product data here'])" + " " * 1200 + "</html>"


def _transport(product_status=200, product_body=_PAGE, robots_body="User-agent: *\nAllow: /\n"):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/robots.txt":
            return httpx.Response(200, text=robots_body)
        return httpx.Response(product_status, text=product_body)
    return httpx.MockTransport(handler)


def test_fetch_returns_text_for_allowed_product_page():
    client = httpx.Client(transport=_transport())
    text = fetch_page_text("https://whop.com/some-product", client=client)
    assert text is not None
    assert "product data here" in text


def test_fetch_returns_none_on_403_block():
    client = httpx.Client(transport=_transport(product_status=403, product_body="blocked"))
    text = fetch_page_text("https://whop.com/some-product", client=client)
    assert text is None


def test_fetch_returns_none_on_challenge_body():
    client = httpx.Client(transport=_transport(product_status=200, product_body="Attention Required! cf-chl-something"))
    text = fetch_page_text("https://whop.com/some-product", client=client)
    assert text is None


def test_fetch_returns_none_when_robots_disallows():
    client = httpx.Client(transport=_transport(robots_body="User-agent: *\nDisallow: /\n"))
    text = fetch_page_text("https://whop.com/some-product", client=client)
    assert text is None
