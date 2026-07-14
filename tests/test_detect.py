import pytest
from clipscore.ingest.detect import classify_response, SourceHalted

VALID = '<script>self.__next_f.push([1,"x"])</script>' + "x" * 5000

@pytest.mark.parametrize("status,body,expected", [
    (200, VALID, "ok"),
    (403, "Forbidden", "blocked_403"),
    (429, "Too Many Requests", "rate_limited_429"),
    (503, "<div>cf-chl-bypass</div>Cloudflare", "cf_challenge"),
    (200, "please complete the reCAPTCHA to continue", "captcha"),
    (200, "<html>Attention Required! Cloudflare</html>", "cf_challenge"),
    (200, "redirecting to /login for authentication", "login_wall"),
    (200, "<html><body>tiny</body></html>", "empty_parse"),
    (500, "Internal Server Error", "error"),
])
def test_classify(status, body, expected):
    assert classify_response(status, body) == expected

def test_sourcehalted_carries_fields():
    e = SourceHalted(url="https://x/discover", event_type="blocked_403",
                     http_status=403, detail="Forbidden")
    assert e.event_type == "blocked_403" and e.http_status == 403
