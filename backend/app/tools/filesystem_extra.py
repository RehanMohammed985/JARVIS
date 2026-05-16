from __future__ import annotations

import json
import os
import platform
import re
import subprocess
import time
from pathlib import Path
from typing import Annotated

from langchain_core.tools import tool

from app.config import settings
from app.macos_open import macos_open_path
from app.security.permissions import (
    PermissionError,
    is_path_under_allowed_roots,
    resolve_under_roots,
)
from app.voice.file_actions import (
    enqueue_local_file_action,
    should_delegate_file_actions_to_client,
)
from app.voice.session_context import current_voice_session
from app.voice.tool_telemetry import record_tool_activity

_KEYWORD_CACHE_TTL_SEC = 55.0
_KEYWORD_SEARCH_CACHE: dict[str, tuple[float, list[str]]] = {}

_SKIP_DIR_NAMES = frozenset({
    "node_modules",
    ".git",
    "__pycache__",
    ".next",
    "dist",
    "build",
    "venv",
    ".venv",
    "Pods",
    "Carthage",
    "DerivedData",
    ".gradle",
    "target",
    "site-packages",
    ".Trash",
})

_HOME_LIBRARY_PRUNE = frozenset({
    "Caches",
    "Logs",
    "Containers",
    "Metadata",
    "Application Support",
    "Developer",
    "Saved Application State",
})


def _env() -> dict[str, str]:
    return os.environ.copy()


def _posix_file_literal(p: Path) -> str:
    return json.dumps(str(p.resolve()), ensure_ascii=False)


def _macos_open_via_finder(p: Path) -> tuple[bool, str]:
    """Use Finder via AppleScript so the GUI session picks up the file reliably."""
    lit = _posix_file_literal(p)
    script = (
        'tell application "Finder"\n'
        f"    open POSIX file {lit}\n"
        "    activate\n"
        "end tell"
    )
    try:
        r = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True,
            text=True,
            timeout=24,
            env=_env(),
        )
    except (subprocess.TimeoutExpired, OSError) as e:
        return False, str(e)
    err = (r.stderr or r.stdout or "").strip()
    if r.returncode != 0:
        return False, err or f"exit {r.returncode}"
    return True, ""


def _macos_reveal_in_finder(p: Path) -> tuple[bool, str]:
    """Select item in Finder: ``open -R`` (lenient), then AppleScript reveal."""
    ok, err = macos_open_path(p, reveal_only=True)
    if ok:
        return True, ""
    errs: list[str] = [err] if err else []
    lit = _posix_file_literal(p)
    script = (
        'tell application "Finder"\n'
        "    activate\n"
        f"    reveal POSIX file {lit}\n"
        "end tell"
    )
    try:
        r = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True,
            text=True,
            timeout=24,
            env=_env(),
        )
    except (subprocess.TimeoutExpired, OSError) as e:
        return False, "; ".join(errs + [str(e)]) if errs else str(e)
    err = (r.stderr or r.stdout or "").strip()
    if r.returncode != 0:
        tail = err or f"exit {r.returncode}"
        return False, "; ".join(errs + [tail]) if errs else tail
    return True, ""


def _keyword_parts(keyword: str) -> list[str]:
    """Legacy helper; prefer parse_open_file_query for semantic tokenization."""
    from app.tools.file_query import parse_open_file_query

    q = parse_open_file_query(keyword)
    return list(q.tokens)


def _prune_dirnames(parent: Path, dirnames: list[str]) -> None:
    home_lib = Path.home() / "Library"
    keep: list[str] = []
    for d in dirnames:
        if d in _SKIP_DIR_NAMES:
            continue
        if parent == home_lib and d in _HOME_LIBRARY_PRUNE:
            continue
        keep.append(d)
    dirnames[:] = keep


def _mdfind_union_for_terms(
    terms: list[str],
    *,
    cap_per_term: int,
    total_cap: int,
) -> list[Path]:
    """Run Spotlight once per term (OR-style coverage) — avoids one glued literal like rehanmohammedresume."""
    if platform.system() != "Darwin" or not terms:
        return []
    roots = list(settings.filesystem_walk_roots)[:16]
    seen: set[str] = set()
    out: list[Path] = []
    for term in terms:
        t = term.strip().lower()
        if len(t) < 2:
            continue
        if any(c in t for c in ("'", "\\", "\n", "\0", '"')):
            continue
        glob_pat = f"*{t}*"
        query = f"kMDItemFSName == '{glob_pat}'c"
        term_hits = 0
        for root in roots:
            if term_hits >= cap_per_term or len(out) >= total_cap:
                break
            try:
                if not root.is_dir():
                    continue
                _ = str(root.resolve())
            except OSError:
                continue
            try:
                proc = subprocess.run(
                    ["/usr/bin/mdfind", "-onlyin", str(root), query],
                    capture_output=True,
                    text=True,
                    timeout=14,
                    env=_env(),
                )
            except (subprocess.TimeoutExpired, OSError):
                continue
            for line in proc.stdout.splitlines():
                if term_hits >= cap_per_term or len(out) >= total_cap:
                    break
                line = line.strip()
                if not line:
                    continue
                p = Path(line)
                try:
                    if not (p.is_file() or p.is_dir()):
                        continue
                    if not is_path_under_allowed_roots(p):
                        continue
                    key = str(p.resolve())
                except OSError:
                    continue
                if key in seen:
                    continue
                seen.add(key)
                out.append(Path(key))
                term_hits += 1
    return out


def _quick_name_gate(filename_lower: str, q) -> bool:
    from app.tools.file_query import OpenFileQuery, token_filename_match_score

    if not isinstance(q, OpenFileQuery):
        return False
    if q.is_resume_intent and re.search(r"resume|cv|curriculum|vitae", filename_lower):
        return True
    return token_filename_match_score(filename_lower, q) >= 52.0


def _walk_semantic_hits(
    q,
    max_hits: int,
    max_files_scanned: int,
    seen: set[str],
) -> list[str]:
    """Bounded directory walk: dirs + files whose names fuzz-match query tokens."""
    hits: list[str] = []
    scanned = 0

    for root in settings.filesystem_walk_roots:
        try:
            if not root.is_dir():
                continue
            base = root.resolve()
        except OSError:
            continue
        for dirpath, dirnames, filenames in os.walk(base, topdown=True, followlinks=False):
            _prune_dirnames(Path(dirpath), dirnames)
            try:
                dpath = Path(dirpath).resolve()
            except OSError:
                continue
            dkey = str(dpath)
            if (
                max_hits > 0
                and dkey not in seen
                and dpath.is_dir()
                and is_path_under_allowed_roots(dpath)
            ):
                dn = dpath.name.lower()
                if _quick_name_gate(dn, q):
                    seen.add(dkey)
                    hits.append(dkey)
                    if len(hits) >= max_hits:
                        return hits

            parent = Path(dirpath)
            for fn in filenames:
                scanned += 1
                if scanned > max_files_scanned:
                    return hits
                fl = fn.lower()
                if not _quick_name_gate(fl, q):
                    continue
                try:
                    full = (parent / fn).resolve()
                except OSError:
                    continue
                key = str(full)
                if key in seen or not is_path_under_allowed_roots(full):
                    continue
                if not full.is_file():
                    continue
                seen.add(key)
                hits.append(key)
                if len(hits) >= max_hits:
                    return hits
    return hits


def _walk_fuzzy_hits(
    q,
    max_hits: int,
    max_files_scanned: int,
    seen: set[str],
    *,
    min_score: float,
) -> list[str]:
    """Second-pass walk: RapidFuzz-style score on basenames; catches order/spacing variants."""
    from app.tools.file_query import OpenFileQuery, token_filename_match_score

    if not isinstance(q, OpenFileQuery):
        return []
    pool: list[tuple[float, str]] = []
    scanned = 0

    for root in settings.filesystem_walk_roots:
        try:
            if not root.is_dir():
                continue
            base = root.resolve()
        except OSError:
            continue
        for dirpath, dirnames, filenames in os.walk(base, topdown=True, followlinks=False):
            _prune_dirnames(Path(dirpath), dirnames)
            try:
                dpath = Path(dirpath).resolve()
            except OSError:
                continue
            if dpath.is_dir() and is_path_under_allowed_roots(dpath):
                dk = str(dpath)
                if dk not in seen:
                    ds = token_filename_match_score(dpath.name.lower(), q)
                    if ds >= min_score:
                        pool.append((ds, dk))
            parent = Path(dirpath)
            for fn in filenames:
                scanned += 1
                if scanned > max_files_scanned:
                    pool.sort(key=lambda x: x[0], reverse=True)
                    return _take_new_paths(pool, seen, max_hits)
                fl = fn.lower()
                sc = token_filename_match_score(fl, q)
                if sc < min_score:
                    continue
                try:
                    full = (parent / fn).resolve()
                except OSError:
                    continue
                key = str(full)
                if key in seen or not is_path_under_allowed_roots(full):
                    continue
                if not full.is_file():
                    continue
                pool.append((sc, key))

    pool.sort(key=lambda x: x[0], reverse=True)
    return _take_new_paths(pool, seen, max_hits)


def _take_new_paths(pool: list[tuple[float, str]], seen: set[str], max_hits: int) -> list[str]:
    out: list[str] = []
    for _s, key in pool:
        if key in seen:
            continue
        seen.add(key)
        out.append(key)
        if len(out) >= max_hits:
            break
    return out


def keyword_search_paths(keyword: str, max_hits: int = 50) -> list[str]:
    """Collect candidate file paths using parsed tokens + Spotlight union + semantic walk fallback."""
    from app.tools.file_query import parse_open_file_query

    q = parse_open_file_query(keyword)
    if not q.tokens and not q.is_resume_intent:
        return []

    max_hits = max(1, min(int(max_hits), 120))
    cache_key = f"{q.phrase}|{'|'.join(q.tokens)}|{max_hits}|{keyword.strip().lower()[:64]}"
    now = time.monotonic()
    cached = _KEYWORD_SEARCH_CACHE.get(cache_key)
    if cached and (now - cached[0]) < _KEYWORD_CACHE_TTL_SEC:
        return list(cached[1])

    collector_cap = min(140, max(max_hits * 4, 88))

    terms = list(q.mdfind_terms)
    if not terms and q.is_resume_intent:
        terms = ["resume", "cv", "vitae", "curriculum"]

    seen: set[str] = set()
    ordered: list[str] = []
    for p in _mdfind_union_for_terms(terms, cap_per_term=52, total_cap=collector_cap):
        try:
            k = str(p.resolve())
        except OSError:
            continue
        if k not in seen and (p.is_file() or p.is_dir()):
            seen.add(k)
            ordered.append(k)
    remain = collector_cap - len(ordered)
    if remain > 0:
        extra = _walk_semantic_hits(q, remain, 280_000, seen)
        ordered.extend(extra)
    remain2 = collector_cap - len(ordered)
    if remain2 > 0:
        fuzzy_extra = _walk_fuzzy_hits(
            q,
            min(56, remain2),
            380_000,
            seen,
            min_score=54.0 if q.tokens else 48.0,
        )
        ordered.extend(fuzzy_extra)

    result = ordered[: min(120, len(ordered))]
    _KEYWORD_SEARCH_CACHE[cache_key] = (now, list(result))
    if len(_KEYWORD_SEARCH_CACHE) > 96:
        stale = [k for k, (t, _) in _KEYWORD_SEARCH_CACHE.items() if now - t > _KEYWORD_CACHE_TTL_SEC]
        for k in stale[:48]:
            _KEYWORD_SEARCH_CACHE.pop(k, None)
    return result


def _open_existing_allowed_path(p: Path, *, reveal_in_finder: bool) -> str:
    """Open or reveal an existing path (must be under allowed roots)."""
    if not p.exists():
        return f"Path does not exist: {p}"
    try:
        rp = p.resolve()
        if not is_path_under_allowed_roots(rp):
            return f"Denied: not under allowed roots — {rp}"
    except OSError:
        return f"Denied: could not verify path — {p}"

    if should_delegate_file_actions_to_client():
        action = "reveal" if reveal_in_finder else "open"
        enqueue_local_file_action(action, str(p.resolve()))
        if reveal_in_finder:
            return f"Sent to your Mac to show in Finder: {p}"
        return f"Sent to your Mac to open: {p}"
    system = platform.system()
    try:
        if system == "Darwin":
            if reveal_in_finder:
                ok, err = _macos_reveal_in_finder(p)
                if ok:
                    return f"Shown in Finder: {p}"
                return (
                    f"Could not reveal in Finder ({err}). "
                    "Grant Automation for Terminal/Python in System Settings → Privacy & Security, "
                    "and ensure Full Disk Access if this path is outside sandboxed folders."
                )
            ok, err = macos_open_path(p, reveal_only=False)
            if ok:
                return f"Opened: {p}"
            ok2, err2 = _macos_open_via_finder(p)
            if ok2:
                return f"Opened: {p}"
            ok3, err3 = _macos_reveal_in_finder(p)
            if ok3:
                return f"Shown in Finder: {p}"
            return (
                f"Could not open this item ({err or 'unknown'}). "
                f"AppleScript fallback: {err2 or err3}. "
                "Check Full Disk Access and Automation (Finder) for the app running uvicorn, "
                "and confirm a GUI session is logged in."
            )
        if system == "Linux":
            r = subprocess.run(
                ["xdg-open", str(p)],
                capture_output=True,
                text=True,
                timeout=24,
                env=_env(),
            )
            if r.returncode != 0:
                return f"xdg-open failed: {(r.stderr or '').strip() or r.returncode}"
            return f"xdg-open: {p}"
        return f"Unsupported OS for open: {system}"
    except OSError as e:
        return f"Open failed: {e}"


def _emit_finder_match_choices(label: str, paths: list[Path]) -> None:
    """Populate HUD picker + session cache for mac_finder_open_selection / open number N."""
    from datetime import datetime, timezone

    rows: list[dict] = []
    for i, p in enumerate(paths, start=1):
        try:
            st = p.stat()
            mod = datetime.fromtimestamp(st.st_mtime, tz=timezone.utc).strftime(
                "%Y-%m-%dT%H:%M:%SZ"
            )
        except OSError:
            mod = ""
        rows.append(
            {
                "index": i,
                "name": p.name,
                "path": str(p.resolve()),
                "file_type": p.suffix.lower() or "file",
                "modified": mod,
                "is_directory": p.is_dir(),
            }
        )
    sess = current_voice_session.get()
    if sess is None:
        return
    fn = getattr(sess, "set_finder_match_cache", None)
    if callable(fn):
        fn(rows)
    enq = getattr(sess, "enqueue_finder_event", None)
    if callable(enq):
        enq("finder_match_list", {"keyword": label, "matches": rows})


def execute_find_and_open(name_fragment: str, show_in_finder: bool = False) -> str:
    """Search allowed locations by filename fragment, then open the best match (no LLM)."""
    record_tool_activity(
        "find_and_open_file",
        {"name_fragment": name_fragment, "show_in_finder": show_in_finder},
    )
    from dataclasses import replace

    from app.tools.file_query import parse_open_file_query, rank_paths_by_query
    from app.tools.filesystem_intent import (
        find_git_repo_fuzzy,
        latest_pdf_intent,
        normalize_open_fragment,
        repo_intent,
        resume_like_intent,
        well_known_folder_path,
    )
    from app.tools.host_filesystem_ops import open_latest_pdf_impl

    frag = (name_fragment or "").strip()
    low = normalize_open_fragment(frag)

    if latest_pdf_intent(low):
        record_tool_activity("open_latest_pdf", {"show_in_finder": show_in_finder})
        return open_latest_pdf_impl(show_in_finder)

    folder = well_known_folder_path(low)
    if folder is None:
        folder = well_known_folder_path(low.replace(" ", ""))
    if folder is not None:
        try:
            if folder.is_dir():
                body = _open_existing_allowed_path(folder, reveal_in_finder=show_in_finder)
                if not body.startswith("Denied") and "does not exist" not in body:
                    return f"Opened {folder.name}. {body}"
        except OSError:
            pass

    if repo_intent(low):
        repo = find_git_repo_fuzzy(frag)
        if repo is not None:
            body = _open_existing_allowed_path(repo, reveal_in_finder=show_in_finder)
            if not body.startswith("Denied") and "does not exist" not in body:
                return f"Opened project “{repo.name}”. {body}"

    q = parse_open_file_query(frag)
    if resume_like_intent(low):
        q = replace(q, is_resume_intent=True)

    paths = keyword_search_paths(name_fragment, max_hits=100)
    if not paths and q.is_resume_intent:
        paths = keyword_search_paths("resume cv", max_hits=100)

    ranked = rank_paths_by_query(paths, q)

    if not ranked:
        seen2: set[str] = set()
        rescue = _walk_fuzzy_hits(
            q,
            24,
            520_000,
            seen2,
            min_score=42.0,
        )
        ranked = rank_paths_by_query(rescue, q)

    if not ranked:
        if settings.full_filesystem_access:
            hint = "Those paths may be outside allowed roots or not indexed yet—try Desktop/Documents or adjust JARVIS_ALLOWED_ROOTS."
        else:
            hint = "Expand JARVIS_ALLOWED_ROOTS or run the desktop file bridge if the API is remote."
        return (
            f"No close matches for “{name_fragment}” under allowed locations. {hint} "
            "You can try a shorter keyword (e.g. resume, invoice)."
        )

    show = [Path(p) for _, p in ranked[:12]]
    _emit_finder_match_choices(name_fragment, show)

    if len(ranked) == 1:
        return (
            f"Found one match for “{name_fragment}”: {show[0].name}. "
            "Say **open number 1** or tap the HUD to open it."
        )

    best = show[0].name
    return (
        f"Found **{len(ranked)}** matches for “{name_fragment}” (best guess: **{best}**). "
        "Pick a **number** in the HUD or say **open number …**."
    )


@tool
def search_files_by_keyword(
    keyword: Annotated[
        str,
        "Fragment of filename e.g. resume — matches MyResume.pdf, resume_final.docx (case-insensitive).",
    ],
    max_hits: Annotated[int, "Max file paths to return"] = 50,
) -> str:
    """Search for files whose names contain the keyword (and all words if you pass a phrase). Uses Spotlight on macOS plus a bounded directory walk under allowed roots."""
    record_tool_activity("search_files_by_keyword", {"keyword": keyword, "max_hits": max_hits})
    from app.tools.file_query import parse_open_file_query, rank_paths_by_query

    q = parse_open_file_query(keyword)
    if not q.tokens and not q.is_resume_intent:
        return "Provide a clearer search term (e.g. resume, invoice march)."

    max_hits = max(5, min(int(max_hits), 80))
    ordered = keyword_search_paths(keyword, max_hits=max_hits)

    if not ordered:
        if settings.full_filesystem_access:
            tail = "If this surprises you, check Spotlight indexing or try another keyword."
        else:
            tail = "Set JARVIS_ALLOWED_ROOTS in backend/.env to add disks or folders."
        return f"No files close to {keyword!r} on this machine. {tail}"

    ranked = rank_paths_by_query(ordered, q)
    out_paths = [p for _, p in ranked[:max_hits]] if ranked else ordered[:max_hits]

    tail = f"\n… (showing up to {max_hits}, fuzzy-ranked)" if len(out_paths) >= max_hits else ""
    return "\n".join(out_paths) + tail


@tool
def open_path(
    path: Annotated[str, "Path to a file or folder under allowed roots"],
    reveal_in_finder: Annotated[
        bool,
        "true: select in Finder; false: open with default application (still uses Finder on macOS if CLI open fails)",
    ] = False,
) -> str:
    """Open a file with its default application, open a folder in Finder, or reveal in Finder."""
    record_tool_activity(
        "open_path",
        {"path": path, "reveal_in_finder": reveal_in_finder},
    )
    try:
        p = resolve_under_roots(path)
    except PermissionError as e:
        return f"Denied: {e}"
    if not p.exists():
        return f"Path does not exist: {p}"
    return _open_existing_allowed_path(p, reveal_in_finder=reveal_in_finder)


@tool
def show_in_finder(
    path: Annotated[str, "Full path to a file or folder under allowed roots"],
) -> str:
    """macOS: switch to Finder and select this item in a window. Does not open the file in Preview/Word etc.

    Call this when the user asks to open/show/reveal the file in Finder, see it in Finder,
    or pop it up in Finder — not when they want the document opened in its default app."""
    record_tool_activity("show_in_finder", {"path": path})
    try:
        p = resolve_under_roots(path)
    except PermissionError as e:
        return f"Denied: {e}"
    if not p.exists():
        return f"Path does not exist: {p}"
    return _open_existing_allowed_path(p, reveal_in_finder=True)


@tool
def find_and_open_file(
    name_fragment: Annotated[
        str,
        "Keywords from the user (e.g. resume, rehan invoice). Not a full path. Results appear in the HUD; user picks a number.",
    ],
    show_in_finder: Annotated[
        bool,
        "True to reveal in Finder; False to open with the default application",
    ] = False,
) -> str:
    """Broad fuzzy search under allowed roots; lists matches in the HUD — user chooses which to open."""
    return execute_find_and_open(name_fragment, show_in_finder=show_in_finder)
