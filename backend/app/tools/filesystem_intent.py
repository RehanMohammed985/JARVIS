"""Intent-aware routing for natural “open …” commands — folders, latest PDF, repos, resume-like files."""

from __future__ import annotations

import difflib
import re
import time
from pathlib import Path

from app.config import settings
from app.security.permissions import is_path_under_allowed_roots

# --- Normalization ---------------------------------------------------------------------------

_FOLDER_NOISE = re.compile(
    r"\b(?:folder|directory|dir|please|pls|now|my|the)\b",
    re.IGNORECASE,
)
_WS = re.compile(r"\s+")


def normalize_open_fragment(fragment: str) -> str:
    t = (fragment or "").strip()
    t = _FOLDER_NOISE.sub(" ", t)
    t = _WS.sub(" ", t).strip().lower().strip(".,!?:;")
    return t


# Canonical key -> resolved path (under home or standard macOS)
def well_known_folder_path(normalized: str) -> Path | None:
    home = Path.home()
    table: dict[str, Path] = {
        "desktop": home / "Desktop",
        "downloads": home / "Downloads",
        "documents": home / "Documents",
        "document": home / "Documents",
        "docs": home / "Documents",
        "pictures": home / "Pictures",
        "photos": home / "Pictures",
        "pics": home / "Pictures",
        "movies": home / "Movies",
        "music": home / "Music",
        "public": home / "Public",
        "home": home,
        "homedir": home,
        "user": home,
    }
    return table.get(normalized)


def latest_pdf_intent(normalized: str) -> bool:
    return bool(
        re.search(r"\b(latest|most recent|newest|last)\b", normalized)
        and re.search(r"\b(pdf|pdfs)\b", normalized)
    )


def resume_like_intent(normalized: str) -> bool:
    return bool(
        re.search(r"\b(resume|cv|curriculum|vitae|c\.?\s*v\.?)\b", normalized, re.IGNORECASE)
    )


def repo_intent(normalized: str) -> bool:
    return bool(re.search(r"\b(repo|repository|project)\b", normalized))


def _safe_mtime(p: Path) -> float:
    try:
        return p.stat().st_mtime
    except OSError:
        return 0.0


def _name_similarity(a: str, b: str) -> float:
    return difflib.SequenceMatcher(None, a.lower(), b.lower()).ratio()


def find_git_repo_fuzzy(fragment: str) -> Path | None:
    """Locate a git repo under common dev roots with fuzzy name match (typos like ‘campanion’)."""
    raw = normalize_open_fragment(fragment)
    raw = re.sub(r"\b(repo|repository|project)\b", "", raw).strip()
    if len(raw) < 2:
        return None
    candidates: list[Path] = []
    for rel in ("Projects", "Developer", "dev", "src", "workspace", "code"):
        candidates.append(Path.home() / rel)
    candidates.append(Path.home() / "Documents" / "GitHub")
    candidates.append(Path.home() / "Documents" / "projects")
    seen_dirs: set[str] = set()
    best: tuple[float, Path] | None = None
    for base in candidates:
        try:
            if not base.is_dir():
                continue
            for child in base.iterdir():
                if not child.is_dir():
                    continue
                try:
                    key = str(child.resolve())
                except OSError:
                    continue
                if key in seen_dirs:
                    continue
                if not (child / ".git").is_dir():
                    continue
                if not is_path_under_allowed_roots(child):
                    continue
                seen_dirs.add(key)
                name = child.name
                sim = _name_similarity(raw, name)
                # token overlap
                if raw in name.lower() or name.lower() in raw:
                    sim = max(sim, 0.92)
                if sim >= 0.55 and (best is None or sim > best[0]):
                    best = (sim, child)
        except OSError:
            continue
    return best[1] if best and best[0] >= 0.55 else None


def rank_paths_for_open(paths: list[str], *, fragment: str, prefer_resume: bool) -> list[str]:
    """Re-rank candidate paths using fuzzy phrase match and resume/location/recency hints."""
    from dataclasses import replace

    from app.tools.file_query import parse_open_file_query, rank_paths_by_query

    q = parse_open_file_query(fragment)
    if prefer_resume:
        q = replace(q, is_resume_intent=True)
    ranked = rank_paths_by_query(paths, q)
    return [s for _, s in ranked]
