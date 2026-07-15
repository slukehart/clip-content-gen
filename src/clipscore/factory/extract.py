"""Deterministic (regex-only) extraction of Pipeline B clip-source targets from a
campaign's free-text `description` and, when available, the raw Whop page text.

Same discipline as `clipscore.ingest.extract`: no match => field stays absent,
never a guessed/fake value. The regex floor here only reliably catches
machine-parseable tokens (a Google-Drive/Docs/Dropbox URL, `@handle`s) and
defaults `target_platforms` from the campaign's already-ingested
`allowed_socials`. Everything else (length caps, caption rules, banned
content) is left `None`/`absent` for the LLM adapter (Task 3) to fill in.

Provenance values name the SOURCE the value came from, not the extraction
method: `description | whop_page | allowed_socials | absent`. Never `regex`.

PURE / deterministic module: no network calls, no LLM client import here.
"""
import hashlib
import json
import re
from typing import Protocol

from pydantic import BaseModel, Field

# Bump when the extraction logic/prompt changes in a way that should force every
# campaign to be re-extracted on its next poll. It is folded into the input hash
# (below), so a bump makes every stored hash stale at once.
EXTRACT_VERSION = 1


def compute_input_hash(requirements_raw: str | None) -> str:
    """Stable hash of the extraction *input*, stored on the campaign so
    `enrich_batch` can detect when a re-extraction is needed: the campaign's
    `requirements_raw` changed, or `EXTRACT_VERSION` was bumped after an
    extractor improvement. The Whop page text is intentionally NOT part of the
    input -- it is not stored and is fetched fresh each pass, so it could not be
    compared at staleness-check time anyway."""
    payload = f"{EXTRACT_VERSION}\n{requirements_raw or ''}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()

_BANK_URL = re.compile(
    r"https?://(?:www\.)?(?:drive\.google\.com|docs\.google\.com|dropbox\.com)/\S+",
    re.I,
)
_HANDLE = re.compile(r"(?<![A-Za-z0-9._])@[A-Za-z0-9_.]+")

_TRAILING_PUNCT = ".,;:)]}\"'"


def _strip_trailing_punct(s: str) -> str:
    return s.rstrip(_TRAILING_PUNCT)


class ExtractedTargets(BaseModel):
    content_bank_url: str | None = None
    target_creator: list[str] = Field(default_factory=list)
    target_platforms: list[str] = Field(default_factory=list)
    clip_min_len_s: int | None = None
    clip_max_len_s: int | None = None
    caption_rules: str | None = None
    banned_content: str | None = None
    provenance: dict[str, str] = Field(default_factory=dict)


FIELDS = (
    "content_bank_url",
    "target_creator",
    "target_platforms",
    "clip_min_len_s",
    "clip_max_len_s",
    "caption_rules",
    "banned_content",
)


class BaseExtractor(Protocol):
    def extract(
        self, description: str | None, page_text: str | None, base_platforms: list[str]
    ) -> ExtractedTargets: ...


def _find_bank_url(text: str) -> str | None:
    m = _BANK_URL.search(text)
    if not m:
        return None
    return _strip_trailing_punct(m.group(0))


def _find_handles(text: str) -> list[str]:
    handles = []
    for m in _HANDLE.finditer(text):
        h = _strip_trailing_punct(m.group(0))
        if h not in handles:
            handles.append(h)
    return handles


class RegexExtractor:
    """Deterministic floor: URL/handle patterns over description, falling back
    to page_text when description has no match. `target_platforms` is always
    defaulted from `base_platforms` (never read from text)."""

    def extract(
        self, description: str | None, page_text: str | None, base_platforms: list[str]
    ) -> ExtractedTargets:
        provenance: dict[str, str] = {}

        content_bank_url = None
        if description:
            content_bank_url = _find_bank_url(description)
            if content_bank_url is not None:
                provenance["content_bank_url"] = "description"
        if content_bank_url is None and page_text:
            content_bank_url = _find_bank_url(page_text)
            if content_bank_url is not None:
                provenance["content_bank_url"] = "whop_page"
        if content_bank_url is None:
            provenance["content_bank_url"] = "absent"

        target_creator: list[str] = []
        if description:
            target_creator = _find_handles(description)
            if target_creator:
                provenance["target_creator"] = "description"
        if not target_creator and page_text:
            target_creator = _find_handles(page_text)
            if target_creator:
                provenance["target_creator"] = "whop_page"
        if not target_creator:
            provenance["target_creator"] = "absent"

        target_platforms = list(base_platforms) if base_platforms else []
        provenance["target_platforms"] = "allowed_socials"

        provenance["clip_min_len_s"] = "absent"
        provenance["clip_max_len_s"] = "absent"
        provenance["caption_rules"] = "absent"
        provenance["banned_content"] = "absent"

        return ExtractedTargets(
            content_bank_url=content_bank_url,
            target_creator=target_creator,
            target_platforms=target_platforms,
            clip_min_len_s=None,
            clip_max_len_s=None,
            caption_rules=None,
            banned_content=None,
            provenance=provenance,
        )


def _is_present(value) -> bool:
    if value is None:
        return False
    if isinstance(value, list):
        return len(value) > 0
    if isinstance(value, str):
        return value != ""
    return True


def merge_extractions(
    regex: ExtractedTargets, llm: ExtractedTargets, base_platforms: list[str]
) -> ExtractedTargets:
    """Per field: a present LLM value wins over regex, else regex, else absent.
    Merged provenance carries the winning source's label. `target_platforms`
    falls back to `base_platforms` (`allowed_socials`) if neither source has it."""
    merged: dict = {}
    provenance: dict[str, str] = {}

    for field in FIELDS:
        llm_val = getattr(llm, field)
        regex_val = getattr(regex, field)

        if _is_present(llm_val):
            merged[field] = llm_val
            provenance[field] = llm.provenance.get(field, "whop_page")
        elif _is_present(regex_val):
            merged[field] = regex_val
            provenance[field] = regex.provenance.get(field, "description")
        elif field == "target_platforms" and base_platforms:
            merged[field] = list(base_platforms)
            provenance[field] = "allowed_socials"
        else:
            merged[field] = [] if field in ("target_creator", "target_platforms") else None
            provenance[field] = "absent"

    return ExtractedTargets(**merged, provenance=provenance)


def apply_to_campaign(campaign, extracted: ExtractedTargets) -> None:
    """Write the 7 extracted fields onto a Campaign ORM instance. Lists are
    serialized as JSON arrays (strings); `extract_provenance` is a JSON dict
    covering all 7 fields (missing entries default to 'absent')."""
    campaign.content_bank_url = extracted.content_bank_url
    campaign.target_creator = json.dumps(extracted.target_creator)
    campaign.target_platforms = json.dumps(extracted.target_platforms)
    campaign.clip_min_len_s = extracted.clip_min_len_s
    campaign.clip_max_len_s = extracted.clip_max_len_s
    campaign.caption_rules = extracted.caption_rules
    campaign.banned_content = extracted.banned_content

    provenance = {field: extracted.provenance.get(field, "absent") for field in FIELDS}
    campaign.extract_provenance = json.dumps(provenance)

    # Stamp the input hash alongside provenance so any successful pass (LLM or
    # regex-fallback) records what it extracted from. enrich_batch compares this
    # against a freshly computed hash to decide whether to re-extract.
    campaign.extract_input_hash = compute_input_hash(campaign.requirements_raw)
