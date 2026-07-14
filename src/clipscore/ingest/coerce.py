"""Pure coercion for contentrewards' display-formatted values.
Money arrives as strings like "$250,000"; view counts as "51.4M"/"226.2K"."""
import re

_SUFFIX = {"K": 1_000, "M": 1_000_000, "B": 1_000_000_000}

def money_to_float(s):
    if s is None:
        return None
    cleaned = str(s).replace("$", "").replace(",", "").strip()
    if not cleaned:
        return None
    try:
        return float(cleaned)
    except ValueError:
        return None

def views_to_int(s):
    if s is None:
        return None
    t = str(s).replace(",", "").strip()
    if not t:
        return None
    m = re.fullmatch(r"(\d+(?:\.\d+)?)([KMB])?", t)
    if not m:
        return None
    num = float(m.group(1))
    if m.group(2):
        num *= _SUFFIX[m.group(2)]
    return int(round(num))

def to_int(v):
    if v is None:
        return None
    try:
        return int(v)
    except (ValueError, TypeError):
        return None

def to_float(v):
    if v is None:
        return None
    try:
        return float(v)
    except (ValueError, TypeError):
        return None
