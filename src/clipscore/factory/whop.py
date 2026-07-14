"""Fetch a Whop product-page's raw text, for the LLM extractor (Task 3) to read.

Compliance: whop.com/robots.txt is `Allow: /` (only `/api/` and
`/discover/search/*` disallowed; confirmed compliant 2026-07-14) -- checked at
runtime on every call, same discipline as `clipscore.ingest.contentrewards`.
Honest UA, `classify_response()` before returning any text, and
drop-don't-evade on any block/challenge/non-200: never spoof headers, never
solve a CAPTCHA, never retry past a halt. This module only ever returns text
or `None` -- callers (see `factory.enrich`) treat `None` as "skip this
campaign's page-derived fields", never as an error to work around.
"""
import httpx
import structlog
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser
from clipscore.config import get_settings
from clipscore.ingest.detect import classify_response, SourceHalted

log = structlog.get_logger()


def _robots_allowed(client: httpx.Client, ua: str, url: str) -> bool:
    parsed = urlparse(url)
    robots_url = f"{parsed.scheme}://{parsed.netloc}/robots.txt"
    try:
        r = client.get(robots_url, headers={"User-Agent": ua})
    except httpx.HTTPError:
        return True  # fail open on the robots check itself; classify_response still guards the body
    rp = RobotFileParser()
    rp.parse(r.text.splitlines())
    return rp.can_fetch(ua, parsed.path or "/")


def fetch_page_text(url: str, client: httpx.Client | None = None) -> str | None:
    """GET a Whop product page and return its raw text.

    Returns `None` (logging the reason) on: robots.txt disallow, any
    non-`ok` `classify_response` verdict (403/429/captcha/challenge/login
    wall/empty parse), or a network error. Never evades a block -- no header
    spoofing, no CAPTCHA solving, no retry with different tactics.
    """
    settings = get_settings()
    ua = settings.user_agent
    own_client = client is None
    http = client or httpx.Client(timeout=settings.http_timeout_s, follow_redirects=True)
    try:
        try:
            if not _robots_allowed(http, ua, url):
                raise SourceHalted(url, "robots_disallow", None, "robots.txt disallows this path")
            resp = http.get(url, headers={"User-Agent": ua})
            event = classify_response(resp.status_code, resp.text)
            if event != "ok":
                raise SourceHalted(url, event, resp.status_code, f"classify_response={event}")
            return resp.text
        except SourceHalted as e:
            log.info("whop_fetch_halted", url=e.url, event_type=e.event_type,
                     http_status=e.http_status, detail=e.detail)
            return None
        except httpx.HTTPError as e:
            log.info("whop_fetch_halted", url=url, event_type="http_error", detail=str(e))
            return None
    finally:
        if own_client:
            http.close()
