"""Classify an HTTP response for challenges/blocks BEFORE parsing.
Enforces drop-don't-evade: the ingester raises SourceHalted on any non-`ok`."""
import re

class SourceHalted(Exception):
    def __init__(self, url: str, event_type: str, http_status: int | None, detail: str):
        super().__init__(f"{event_type} at {url}: {detail}")
        self.url = url
        self.event_type = event_type
        self.http_status = http_status
        self.detail = detail

_CAPTCHA = re.compile(r"recaptcha|hcaptcha|captcha", re.I)
_CF = re.compile(r"cf-chl|cloudflare|attention required|__cf_bm", re.I)
_DATADOME = re.compile(r"datadome|perimeterx|px-captcha", re.I)
_LOGIN = re.compile(r"/login|please (log|sign) in|authentication required", re.I)
_PAYLOAD = "self.__next_f.push"
_MIN_BODY = 1000  # a real /discover page is ~8MB; anything tiny is a failed fetch

def classify_response(status_code: int, body: str) -> str:
    if status_code == 403:
        return "blocked_403"
    if status_code == 429:
        return "rate_limited_429"
    body = body or ""
    if _CAPTCHA.search(body):
        return "captcha"
    if _CF.search(body) or _DATADOME.search(body):
        return "cf_challenge"
    if _LOGIN.search(body) and _PAYLOAD not in body:
        return "login_wall"
    if status_code >= 500 or status_code >= 400:
        return "error"
    if _PAYLOAD not in body or len(body) < _MIN_BODY:
        return "empty_parse"
    return "ok"
