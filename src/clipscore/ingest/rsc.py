"""Extract campaign objects from the /discover Next.js RSC payload.

The page emits many `self.__next_f.push([1,"<chunk>"])` calls whose JS string
chunks concatenate into one escaped blob. There is NO single named campaigns
array (the list is RSC-streamed), so we locate each campaign by its
`whopExperienceId`, brace-walk to the enclosing object, and dedup by `id`.
`$$` is the RSC escape for a literal `$` in money fields. Validated in the
Phase 0 spike (526 raw matches -> 502 distinct on live data)."""
import json
import re

_CHUNK = re.compile(r'self\.__next_f\.push\(\[1,\s*(".*?")\]\)', re.DOTALL)

def _decode_blob(html: str) -> str:
    chunks = _CHUNK.findall(html)
    if not chunks:
        return ""
    parts = []
    for c in chunks:
        try:
            parts.append(json.loads(c))   # unescape the JS string literal
        except json.JSONDecodeError:
            continue
    return "".join(parts).replace("$$", "$")

def _enclosing_object(s: str, idx: int) -> str | None:
    depth = 0
    start = None
    for i in range(idx, -1, -1):
        ch = s[i]
        if ch == "}":
            depth += 1
        elif ch == "{":
            if depth == 0:
                start = i
                break
            depth -= 1
    if start is None:
        return None
    depth = 0
    for j in range(start, len(s)):
        ch = s[j]
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return s[start:j + 1]
    return None

def parse_discover(html: str) -> list[dict]:
    blob = _decode_blob(html)
    if not blob:
        return []
    out: dict[str, dict] = {}
    for m in re.finditer("whopExperienceId", blob):
        obj = _enclosing_object(blob, m.start())
        if not obj:
            continue
        try:
            d = json.loads(obj)
        except json.JSONDecodeError:
            continue
        cid = d.get("id")
        if cid and cid not in out:
            out[cid] = d
    return list(out.values())
