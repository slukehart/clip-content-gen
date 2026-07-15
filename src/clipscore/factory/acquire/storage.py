"""Local-filesystem storage seam for acquired media (Pipeline B Stage B2).

Pure `pathlib` / `hashlib` / `glob` helpers — no network, no ORM imports.
Content-addressed layout: `<media_dir>/<source_type>/<sha256(source_ref)[:16]><ext>`.
"""
import hashlib
from pathlib import Path


def stem_key(source_type: str, source_ref: str) -> str:
    digest = hashlib.sha256(source_ref.encode("utf-8")).hexdigest()[:16]
    return f"{source_type}/{digest}"


def path_for(media_dir: str, stem: str, ext: str) -> str:
    return str(Path(media_dir) / f"{stem}{ext}")


def find_existing(media_dir: str, source_type: str, source_ref: str) -> str | None:
    stem = stem_key(source_type, source_ref)
    base = Path(media_dir)
    candidates = list(base.glob(f"{stem}.*"))
    extensionless = base / stem
    if extensionless.exists():
        candidates.append(extensionless)
    for candidate in candidates:
        if candidate.is_file() and candidate.stat().st_size > 0:
            return str(candidate)
    return None


def dir_usage_bytes(media_dir: str) -> int:
    base = Path(media_dir)
    if not base.exists():
        return 0
    return sum(f.stat().st_size for f in base.rglob("*") if f.is_file())


def ensure_parent(path: str) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
