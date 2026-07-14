"""LLM-based extractor for Pipeline B clip-source targets.

MANUAL-ACCEPTANCE-ONLY: `RegexExtractor` (`clipscore.factory.extract`) is the
always-run deterministic floor; this adapter needs a real Anthropic API key,
network access, and incurs billing, so it is never invoked in CI -- see
`enrich.py`'s guard, which only constructs/calls this when a key is
configured, and always falls back to the regex floor on any failure.

`anthropic` is imported lazily, inside `extract()`, NOT at module top level --
same pattern as `bot/discord_bot.py`'s lazy `discord` import. This lets the
module (and anything that imports it) load fine in environments where the
`anthropic` package isn't installed.
"""
import structlog
from clipscore.factory.extract import BaseExtractor, ExtractedTargets, FIELDS

log = structlog.get_logger()

_TOOL_NAME = "record_extracted_targets"

_TOOL_SCHEMA = {
    "name": _TOOL_NAME,
    "description": (
        "Record the clip-source targets extracted from a campaign brief, "
        "tagging each field's source."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "content_bank_url": {"type": ["string", "null"]},
            "target_creator": {"type": "array", "items": {"type": "string"}},
            "target_platforms": {"type": "array", "items": {"type": "string"}},
            "clip_min_len_s": {"type": ["integer", "null"]},
            "clip_max_len_s": {"type": ["integer", "null"]},
            "caption_rules": {"type": ["string", "null"]},
            "banned_content": {"type": ["string", "null"]},
            "provenance": {
                "type": "object",
                "description": (
                    "One entry per field above; each value is exactly "
                    "'description', 'whop_page', or 'absent'."
                ),
                "properties": {f: {"type": "string", "enum": ["description", "whop_page", "absent"]}
                               for f in FIELDS},
            },
        },
        "required": ["provenance"],
    },
}

_SYSTEM_PROMPT = (
    "You extract clip-sourcing targets for a content-clipping campaign from two "
    "independent text sources supplied separately: a marketplace campaign "
    "DESCRIPTION and, if available, the raw text of the campaign's WHOP product "
    "page. Briefs may be written in any language -- handle multilingual text and "
    "do not assume English. For each of the 7 fields (content_bank_url, "
    "target_creator, target_platforms, clip_min_len_s, clip_max_len_s, "
    "caption_rules, banned_content), report the value AND tag which source it "
    "came from: 'description', 'whop_page', or 'absent' if neither source "
    "states it. Never guess or fabricate a value that is not explicitly present "
    "in one of the two sources; when unsure, mark the field absent."
)


class LLMExtractor(BaseExtractor):
    """Manual-acceptance-only adapter; requires `settings.llm_api_key`."""

    def __init__(self, settings=None):
        from clipscore.config import get_settings
        self._settings = settings or get_settings()

    def extract(self, description: str | None, page_text: str | None,
                base_platforms: list[str]) -> ExtractedTargets:
        import anthropic  # lazy: keeps this module importable with anthropic absent

        settings = self._settings
        if not settings.llm_api_key:
            raise RuntimeError("LLMExtractor.extract called with no llm_api_key configured")

        client = anthropic.Anthropic(api_key=settings.llm_api_key)
        user_content = (
            f"DESCRIPTION:\n{description or '(none)'}\n\n"
            f"WHOP_PAGE_TEXT:\n{page_text or '(none)'}\n\n"
            f"allowed_socials (fallback for target_platforms if silent): {base_platforms}"
        )
        resp = client.messages.create(
            model=settings.llm_model,
            max_tokens=1024,
            system=_SYSTEM_PROMPT,
            tools=[_TOOL_SCHEMA],
            tool_choice={"type": "tool", "name": _TOOL_NAME},
            messages=[{"role": "user", "content": user_content}],
        )
        tool_use = next((b for b in resp.content if getattr(b, "type", None) == "tool_use"), None)
        if tool_use is None:
            raise RuntimeError("LLM response had no tool_use block")

        data = tool_use.input
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
