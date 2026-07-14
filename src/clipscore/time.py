from datetime import datetime, timezone

def utcnow_iso() -> str:
    """Current UTC time as ISO-8601 with trailing Z, second precision."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
