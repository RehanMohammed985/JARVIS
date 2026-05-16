"""Tokenize natural-language file-open queries and rank paths with fuzzy matching."""

from __future__ import annotations

import difflib
import re
import time
from dataclasses import dataclass, field
from pathlib import Path

from app.tools.filesystem_intent import resume_like_intent

try:
    from rapidfuzz import fuzz as _rfuzz
except ImportError:  # pragma: no cover
    _rfuzz = None

_FILLER = frozenset(
    {
        "open",
        "show",
        "reveal",
        "launch",
        "launching",
        "find",
        "search",
        "the",
        "a",
        "an",
        "my",
        "me",
        "i",
        "im",
        "ive",
        "please",
        "pls",
        "can",
        "you",
        "could",
        "would",
        "file",
        "files",
        "document",
        "documents",
        "docs",
        "folder",
        "directory",
        "called",
        "named",
        "name",
        "is",
        "to",
        "in",
        "for",
        "with",
        "about",
        "this",
        "that",
        "it",
        "something",
        "somebody",
        "up",
        "out",
        "here",
        "there",
        "want",
        "need",
        "get",
        "give",
        "gimme",
        "let",
        "letme",
        "lets",
        "and",
        "or",
        "of",
        "on",
        "at",
        "by",
        "look",
        "looking",
    }
)

_WS = re.compile(r"\s+")


def _fuzz_wratio(a: str, b: str) -> float:
    if _rfuzz is not None:
        return float(_rfuzz.WRatio(a, b))
    return difflib.SequenceMatcher(None, a, b).ratio() * 100.0


def _fuzz_token_set(a: str, b: str) -> float:
    if _rfuzz is not None:
        return float(_rfuzz.token_set_ratio(a, b))
    return difflib.SequenceMatcher(None, a, b).ratio() * 100.0


def _fuzz_partial(a: str, b: str) -> float:
    if _rfuzz is not None:
        return float(_rfuzz.partial_ratio(a, b))
    # coarse fallback: substring
    if a in b or b in a:
        return 85.0
    return difflib.SequenceMatcher(None, a, b).ratio() * 100.0


def _split_raw_tokens(s: str) -> list[str]:
    s2 = re.sub(r"[^\w\s\-_.]", " ", s, flags=re.UNICODE)
    parts = re.split(r"\s+", s2.strip())
    return [p.strip("._-") for p in parts if p.strip("._-")]


def _decompose_glued(t: str) -> list[str]:
    """Split glued names like rehanmohammedresume or foo_bar_resume."""
    low = t.lower()
    m = re.search(r"(.+?)(resume|curriculumvitae|curriculum|vitae|cv)$", low)
    if m:
        head, tail = m.group(1).strip("_- \t"), m.group(2).lower()
        head = head.strip("_- ")
        th = tail
        if th == "curriculumvitae":
            tail_tokens = ["curriculum", "vitae", "cv", "resume"]
        elif th == "curriculum":
            tail_tokens = ["curriculum", "cv", "resume"]
        elif th == "vitae":
            tail_tokens = ["vitae", "cv", "curriculum", "resume"]
        elif th == "cv":
            tail_tokens = ["cv", "resume"]
        else:
            tail_tokens = ["resume", "cv"]
        out: list[str] = []
        if head and len(head) > 1:
            if "_" in head or "-" in head:
                for piece in re.split(r"[_\-]+", head):
                    pl = piece.lower().strip()
                    if len(pl) >= 2:
                        out.append(pl)
            else:
                out.append(head.lower())
        out.extend(tail_tokens)
        return out
    if "_" in low or "-" in low:
        return [p for p in re.split(r"[_\-]+", low) if len(p) >= 2]
    return [low] if len(low) >= 2 else []


@dataclass
class OpenFileQuery:
    """Structured search query from a user phrase or single fragment."""

    raw: str
    tokens: list[str] = field(default_factory=list)
    """Normalized significant tokens (lowercase, no fillers)."""

    phrase: str = ""
    """Space-joined tokens for fuzzy comparison."""

    is_resume_intent: bool = False
    mdfind_terms: list[str] = field(default_factory=list)
    """Terms to query Spotlight with (OR union); avoids one glued literal."""


def parse_open_file_query(raw: str) -> OpenFileQuery:
    base = (raw or "").strip()
    if not base:
        return OpenFileQuery(raw=raw)

    low_space = _WS.sub(" ", base).strip()
    tokens: list[str] = []
    for piece in _split_raw_tokens(low_space):
        pl = piece.lower()
        if pl in _FILLER or len(pl) < 2:
            continue
        expanded = _decompose_glued(pl)
        if not expanded and len(pl) >= 2:
            expanded = [pl.lower()]
        tokens.extend(expanded)

    seen: set[str] = set()
    uniq: list[str] = []
    for t in tokens:
        tl = t.lower()
        if tl in seen or tl in _FILLER or len(tl) < 2:
            continue
        seen.add(tl)
        uniq.append(tl)

    is_resume = resume_like_intent(" ".join(uniq)) or resume_like_intent(low_space.lower())

    if is_resume:
        for x in ("resume", "cv", "curriculum", "vitae"):
            if x not in seen:
                uniq.append(x)
                seen.add(x)

    phrase = " ".join(uniq)

    mdfind_terms: list[str] = []
    for t in uniq:
        if len(t) >= 3:
            mdfind_terms.append(t)
        elif t == "cv" and is_resume:
            mdfind_terms.append(t)

    # unique preserve order
    md_seen: set[str] = set()
    md_final: list[str] = []
    for t in mdfind_terms:
        if t not in md_seen:
            md_seen.add(t)
            md_final.append(t)

    return OpenFileQuery(
        raw=raw,
        tokens=uniq,
        phrase=phrase or low_space.lower(),
        is_resume_intent=is_resume,
        mdfind_terms=md_final,
    )


def path_location_bonus(p: Path) -> float:
    try:
        parts = [x.lower() for x in p.resolve().parts]
    except OSError:
        return 0.0
    joined = "/".join(parts)
    b = 0.0
    if "desktop" in parts:
        b += 10.0
    if "documents" in parts:
        b += 10.0
    if "downloads" in parts:
        b += 6.0
    if "projects" in parts or "github" in joined or "/dev/" in joined or "developer" in parts:
        b += 5.0
    if "mobile documents" in joined or "iclouddrive" in joined or "icloud" in joined:
        b += 8.0
    return b


def path_recency_bonus(p: Path) -> float:
    try:
        mt = p.stat().st_mtime
        age_days = max(0.0, (time.time() - mt) / 86400.0)
        return max(0.0, 18.0 - min(18.0, age_days / 21.0 * 18.0))
    except OSError:
        return 0.0


def resume_extension_bonus(p: Path) -> float:
    e = p.suffix.lower()
    if e == ".pdf":
        return 16.0
    if e in (".doc", ".docx"):
        return 14.0
    if e in (".rtf", ".txt", ".pages"):
        return 6.0
    return 0.0


def token_filename_match_score(filename_lower: str, q: OpenFileQuery) -> float:
    """Fuzzy + substring score for a file or folder basename."""
    compact = re.sub(r"[_\-\s]+", "", filename_lower)
    best = 0.0
    for t in q.tokens:
        if len(t) < 2:
            continue
        if t == "cv" or len(t) >= 3:
            best = max(best, _fuzz_partial(t, filename_lower))
            if len(t) >= 3 and t in filename_lower:
                best = max(best, 92.0)
            if len(t) >= 4 and t in compact:
                best = max(best, 90.0)
            if t == "cv" and t in compact:
                best = max(best, 88.0)
    glue_phrase = re.sub(r"[_\-\s]+", "", q.phrase.lower())
    if glue_phrase and compact:
        best = max(
            best,
            _fuzz_partial(glue_phrase, compact),
            _fuzz_token_set(q.phrase.lower(), filename_lower),
        )
    return best


def fuzzy_score_item(p: Path, q: OpenFileQuery) -> float:
    """Score a file or directory path against the query (case/spacing insensitive)."""
    try:
        if p.is_symlink():
            return -1.0
        if not (p.is_file() or p.is_dir()):
            return -1.0
    except OSError:
        return -1.0

    if p.is_dir():
        stem_norm = p.name.lower().replace("_", " ").replace("-", " ")
    else:
        stem_norm = p.stem.lower().replace("_", " ").replace("-", " ")

    name_full = p.name.lower()
    phrase = q.phrase.lower().strip()
    glue_name = re.sub(r"[_\-\s]+", "", name_full)
    glue_phrase = re.sub(r"[_\-\s]+", "", phrase)

    base = max(
        token_filename_match_score(name_full, q),
        _fuzz_wratio(phrase, stem_norm),
        _fuzz_token_set(phrase, stem_norm),
        _fuzz_wratio(glue_phrase, glue_name) if glue_phrase else 0.0,
    )

    bonus = path_location_bonus(p) + path_recency_bonus(p)
    if q.is_resume_intent and p.is_file():
        bonus += resume_extension_bonus(p)

    return base + bonus * 0.35


def fuzzy_score_path(p: Path, q: OpenFileQuery) -> float:
    """Scores files only (legacy helpers)."""
    try:
        if not p.is_file():
            return -1.0
    except OSError:
        return -1.0
    return fuzzy_score_item(p, q)


def rank_paths_by_query(paths: list[str], q: OpenFileQuery) -> list[tuple[float, str]]:
    scored: list[tuple[float, str]] = []
    for s in paths:
        try:
            score = fuzzy_score_item(Path(s), q)
        except OSError:
            continue
        if score >= 0:
            scored.append((score, str(Path(s).resolve())))
    scored.sort(key=lambda x: x[0], reverse=True)
    return scored


def should_auto_open(top: float, second: float, *, candidate_count: int) -> bool:
    """Open immediately when a single reasonable match or a clear winner among several."""
    if candidate_count <= 1:
        return top >= 68.0
    if second < 0.5:
        return top >= 72.0
    return top >= 88.0 and (top - second) >= 11.0


def is_ambiguous(top: float, second: float) -> bool:
    if second < 0.5:
        return False
    return (top - second) < 10.0 and top < 93.0
