"""LLM-based extractor for Pipeline B clip-source targets.

MANUAL-ACCEPTANCE-ONLY: `RegexExtractor` (`clipscore.factory.extract`) is the
always-run deterministic floor; this adapter needs a real LLM API key, network
access, and incurs billing, so it is never invoked in CI -- see `enrich.py`'s
guard, which only constructs/calls this when a key is configured, and always
falls back to the regex floor on any failure.

Uses `clipscore.factory.llm.LLMClient` -- a provider-agnostic OpenAI-compatible
`/chat/completions` client (Stage B3) -- instead of a vendor SDK, so extraction
can target OpenRouter/Kimi/DeepSeek/local by config alone.
"""
import structlog
from clipscore.factory.extract import BaseExtractor, ExtractedTargets, FIELDS
from clipscore.factory.llm import LLMClient

log = structlog.get_logger()

_SYSTEM_PROMPT = (
    "You extract clip-sourcing targets for a content-clipping campaign from two "
    "independent text sources supplied separately: a marketplace campaign "
    "DESCRIPTION and, if available, the raw text of the campaign's WHOP product "
    "page. Briefs may be written in any language -- handle multilingual text and "
    "do not assume English. Reply with a single JSON object with exactly these "
    "keys: content_bank_url, target_creator, target_platforms, clip_min_len_s, "
    "clip_max_len_s, caption_rules, banned_content, and provenance. `provenance` "
    "is an object with one entry per field above; each value is exactly "
    "'description', 'whop_page', or 'absent'. Never guess or fabricate a value "
    "that is not explicitly present in one of the two sources; when unsure, mark "
    "the field absent."
)


class LLMExtractor(BaseExtractor):
    """Manual-acceptance-only adapter; requires `settings.llm_api_key`."""

    def __init__(self, settings=None, client=None):
        from clipscore.config import get_settings
        self._settings = settings or get_settings()
        self._client = client

    def extract(self, description: str | None, page_text: str | None,
                base_platforms: list[str]) -> ExtractedTargets:
        settings = self._settings
        if not settings.llm_api_key:
            raise RuntimeError("LLMExtractor.extract called with no llm_api_key configured")

        client = self._client or LLMClient(
            settings.llm_base_url, settings.llm_model, settings.llm_api_key,
            settings.http_timeout_s,
        )
        user_content = (
            f"DESCRIPTION:\n{description or '(none)'}\n\n"
            f"WHOP_PAGE_TEXT:\n{page_text or '(none)'}\n\n"
            f"allowed_socials (fallback for target_platforms if silent): {base_platforms}"
        )
        data = client.chat_json(_SYSTEM_PROMPT, user_content)

        raw_provenance = data.get("provenance") or {}
        provenance = {f: raw_provenance.get(f, "absent") for f in FIELDS}
        return ExtractedTargets(
            content_bank_url=data.get("content_bank_url"),
            target_creator=data.get("target_creator") or [],
            target_platforms=data.get("target_platforms") or [],
            clip_min_len_s=data.get("clip_min_len_s"),
            clip_max_len_s=data.get("clip_max_len_s"),
            caption_rules=data.get("caption_rules"),
            banned_content=data.get("banned_content"),
            provenance=provenance,
        )
