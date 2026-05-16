"""Modular macOS Finder search + open flow with explicit directory permission (HUD progress).

Requires JARVIS_MAC_FINDER_PRESET=recommended and/or JARVIS_MAC_FINDER_ROOTS=...
See Settings mac_finder_* / README. Not enabled by default.
"""

from __future__ import annotations

import json
import os
import platform
import re
import subprocess
import time
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Annotated, Any, Callable

from langchain_core.tools import tool

from app.config import settings
from app.voice.file_actions import enqueue_local_file_action, should_delegate_file_actions_to_client
from app.voice.session_context import current_voice_session
from app.voice.tool_telemetry import record_tool_activity


@dataclass
class FileMatch:
    path: str
    name: str
    is_directory: bool
    file_type: str
    modified_iso: str

    def to_row(self, index: int) -> dict[str, Any]:
        return {
            "index": index,
            "name": self.name,
            "path": self.path,
            "file_type": self.file_type,
            "modified": self.modified_iso,
            "is_directory": self.is_directory,
        }


_SKIP_DIR_PARTS = frozenset({
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


_BLOCKED_ABS_PREFIXES = (
    "/System",
    "/usr/",
    "/bin/",
    "/sbin/",
    "/private/",
    "/Library",
    "/dev/",
    "/etc/",
    "/var/",
    "/Applications/",  # apps, not user documents
)


def mac_finder_module_configured() -> bool:
    """True when the user explicitly enabled preset or listed roots."""
    preset = (settings.mac_finder_preset or "").strip().lower()
    if preset in ("recommended", "1", "true", "yes", "on"):
        return True
    return bool((settings.mac_finder_roots or "").strip())


def _recommended_preset_dirs() -> list[Path]:
    home = Path.home()
    out: list[Path] = []
    for rel in ("Desktop", "Documents", "Downloads", "Projects", "Code"):
        p = home / rel
        if p.is_dir():
            out.append(p.resolve())
    cloud = home / "Library/CloudStorage"
    if cloud.is_dir():
        for p in sorted(cloud.glob("GoogleDrive*")):
            if p.is_dir():
                out.append(p.resolve())
        for p in sorted(cloud.glob("OneDrive*")):
            if p.is_dir():
                out.append(p.resolve())
    icloud = home / "Library/Mobile Documents/com~apple~CloudDocs"
    if icloud.is_dir():
        out.append(icloud.resolve())
    return out


def configured_search_directories() -> list[Path]:
    """Resolved allowed directories; empty if module off or invalid."""
    if not mac_finder_module_configured():
        return []
    roots: list[Path] = []
    raw = [p.strip() for p in (settings.mac_finder_roots or "").split(",") if p.strip()]
    for item in raw:
        try:
            roots.append(Path(item).expanduser().resolve())
        except OSError:
            continue
    preset = (settings.mac_finder_preset or "").strip().lower()
    if preset in ("recommended", "1", "true", "yes", "on"):
        seen_pre = {str(p) for p in roots}
        for p in _recommended_preset_dirs():
            k = str(p)
            if k not in seen_pre:
                seen_pre.add(k)
                roots.append(p)
    # dedupe preserve order
    seen: set[str] = set()
    out: list[Path] = []
    for r in roots:
        k = str(r)
        if k not in seen:
            seen.add(k)
            out.append(r)
    return [p for p in out if not _is_root_forbidden(p)]


def _is_root_forbidden(path: Path) -> bool:
    try:
        s = str(path.resolve())
    except OSError:
        return True
    home_s = str(Path.home().resolve())
    if s == home_s or s.startswith(home_s + "/"):
        return False
    if s.startswith("/Volumes/"):
        return False
    for bad in _BLOCKED_ABS_PREFIXES:
        if s == bad.rstrip("/") or s.startswith(bad):
            return True
    return False


def _mtime_iso(p: Path) -> str:
    try:
        ts = p.stat().st_mtime
        return datetime.fromtimestamp(ts).isoformat(timespec="seconds")
    except OSError:
        return ""


def _file_kind(p: Path) -> str:
    if p.is_dir():
        return "folder"
    suf = p.suffix.lower().lstrip(".")
    return suf or "file"


def _path_under_allowed_roots(candidate: Path, roots: list[Path]) -> bool:
    try:
        c = candidate.resolve()
    except OSError:
        return False
    for root in roots:
        try:
            c.relative_to(root.resolve())
            return True
        except ValueError:
            continue
    return False


def _emit_progress(payload: dict[str, Any]) -> None:
    sess = current_voice_session.get()
    if sess is None:
        return
    fn = getattr(sess, "enqueue_finder_event", None)
    if callable(fn):
        fn("finder_search_progress", payload)


def search_files(
    keyword: str,
    allowed_dirs: list[str | Path],
    *,
    max_results: int = 50,
    on_progress: Callable[[dict[str, Any]], None] | None = None,
) -> list[FileMatch]:
    """Search files and folders whose names contain ``keyword`` (case-insensitive)."""
    emit = on_progress or _emit_progress
    kw = (keyword or "").strip().lower()
    if len(kw) < 1:
        return []

    roots: list[Path] = []
    for d in allowed_dirs:
        try:
            roots.append(Path(d).expanduser().resolve())
        except OSError:
            continue

    roots = [r for r in roots if r.is_dir() and not _is_root_forbidden(r)]
    emit(
        {
            "message": f"Searching for files matching: {keyword}",
            "keyword": keyword,
            "phase": "start",
            "directories": [str(r) for r in roots],
            "match_count": 0,
        },
    )

    max_results = max(1, min(int(max_results), 200))
    hits: dict[str, FileMatch] = {}

    def consider_path(p: Path) -> None:
        if len(hits) >= max_results:
            return
        try:
            if not p.exists():
                return
            r = p.resolve()
        except OSError:
            return
        if kw not in r.name.lower():
            return
        if not r.is_file() and not r.is_dir():
            return
        if not _path_under_allowed_roots(r, roots):
            return
        key = str(r)
        if key in hits:
            return
        hits[key] = FileMatch(
            path=key,
            name=r.name,
            is_directory=r.is_dir(),
            file_type=_file_kind(r),
            modified_iso=_mtime_iso(r),
        )

    if platform.system() == "Darwin":
        parts = [p for p in re.split(r"\s+", kw) if p]
        if parts:
            glob_core = "*".join(parts)
            if "'" in glob_core:
                glob_core = glob_core.replace("'", "")
            query = f"kMDItemFSName == '*{glob_core}*'c"
            for root in roots:
                emit(
                    {
                        "message": f"Scanning: {root}",
                        "keyword": keyword,
                        "phase": "scanning",
                        "directory": str(root),
                        "match_count": len(hits),
                    },
                )
                last_emit = 0.0
                try:
                    proc = subprocess.run(
                        ["/usr/bin/mdfind", "-onlyin", str(root), query],
                        capture_output=True,
                        text=True,
                        timeout=22,
                        env=os.environ.copy(),
                    )
                except (subprocess.TimeoutExpired, OSError):
                    continue
                for line in proc.stdout.splitlines():
                    line = line.strip()
                    if not line:
                        continue
                    consider_path(Path(line))
                    now = time.monotonic()
                    if now - last_emit > 0.14 or len(hits) >= max_results:
                        last_emit = now
                        emit(
                            {
                                "message": f"Matches so far: {len(hits)}",
                                "keyword": keyword,
                                "phase": "scanning",
                                "directory": str(root),
                                "match_count": len(hits),
                            },
                        )
                    if len(hits) >= max_results:
                        break
                if len(hits) >= max_results:
                    break

    if len(hits) < max_results:
        scanned = 0
        scan_budget = 120_000
        for root in roots:
            emit(
                {
                    "message": f"Walking: {root}",
                    "keyword": keyword,
                    "phase": "walking",
                    "directory": str(root),
                    "match_count": len(hits),
                },
            )
            for dirpath, dirnames, filenames in os.walk(
                root,
                topdown=True,
                followlinks=False,
            ):
                dirnames[:] = [d for d in dirnames if d not in _SKIP_DIR_PARTS and not d.startswith(".")]
                parent = Path(dirpath)
                if kw in parent.name.lower() and parent.is_dir():
                    consider_path(parent)
                for fn in filenames:
                    scanned += 1
                    if scanned > scan_budget or len(hits) >= max_results:
                        break
                    if kw in fn.lower():
                        consider_path(parent / fn)
                if scanned > scan_budget or len(hits) >= max_results:
                    break
            emit(
                {
                    "message": f"Matches so far: {len(hits)}",
                    "keyword": keyword,
                    "phase": "walking",
                    "directory": str(root),
                    "match_count": len(hits),
                },
            )
            if len(hits) >= max_results:
                break

    ordered = sorted(
        hits.values(),
        key=lambda m: m.modified_iso or "",
        reverse=True,
    )
    emit(
        {
            "message": f"Done — {len(ordered)} matches",
            "keyword": keyword,
            "phase": "complete",
            "match_count": len(ordered),
            "total_matches": len(ordered),
        },
    )
    return ordered


def open_file(path: str, *, reveal_in_finder: bool = False) -> dict[str, Any]:
    """Open path with the default app, or reveal in Finder."""
    p = Path(path).expanduser()
    try:
        rp = p.resolve()
    except OSError as e:
        return {"ok": False, "path": path, "message": str(e)}
    if not rp.exists():
        return {"ok": False, "path": str(rp), "message": "Path does not exist."}

    if platform.system() != "Darwin":
        return {"ok": False, "path": str(rp), "message": "This tool targets macOS Finder / open."}

    if should_delegate_file_actions_to_client():
        action = "reveal" if reveal_in_finder else "open"
        enqueue_local_file_action(action, str(rp))
        return {
            "ok": True,
            "path": str(rp),
            "message": f"Delegated {action} to desktop",
            "delegated": True,
        }

    opener = "/usr/bin/open" if Path("/usr/bin/open").is_file() else "open"
    args = [opener, "-R", str(rp)] if reveal_in_finder else [opener, str(rp)]
    try:
        r = subprocess.run(args, capture_output=True, text=True, timeout=60)
    except OSError as e:
        return {"ok": False, "path": str(rp), "message": str(e)}
    if r.returncode != 0:
        err = (r.stderr or r.stdout or "").strip()
        return {"ok": False, "path": str(rp), "message": err or f"exit {r.returncode}"}
    return {"ok": True, "path": str(rp), "message": "Opened successfully"}


def resolve_user_selection(user_text: str, matches: list[FileMatch]) -> FileMatch | None:
    """Resolve phrases like 'open 2', 'the pdf', or a substring of the filename."""
    t = (user_text or "").strip()
    if not t or not matches:
        return None

    low = t.lower()
    m = re.search(r"\b(?:open|pick|select|use|number)\s*[#]?\s*(\d{1,3})\b", low)
    if m:
        idx = int(m.group(1))
        if 1 <= idx <= len(matches):
            return matches[idx - 1]
        return None

    if "pdf" in low:
        for fm in matches:
            if fm.name.lower().endswith(".pdf"):
                return fm
    if "folder" in low or "directory" in low:
        for fm in matches:
            if fm.is_directory:
                return fm

    # longest name match
    best: FileMatch | None = None
    best_len = 0
    for fm in matches:
        n = fm.name.lower()
        if n in low or n.replace(" ", "") in low.replace(" ", ""):
            if len(fm.name) > best_len:
                best_len = len(fm.name)
                best = fm
        frag = re.sub(r"[^\w]+", " ", low).strip()
        if frag and frag in n:
            if len(frag) > best_len:
                best_len = len(frag)
                best = fm

    if best:
        return best

    part = re.sub(r"^.*?\b(?:open|show|use)\s+", "", low, flags=re.IGNORECASE).strip()
    if part:
        for fm in matches:
            if part in fm.name.lower():
                return fm
    return None


def _set_match_cache(rows: list[dict[str, Any]]) -> None:
    sess = current_voice_session.get()
    if sess is None:
        return
    fn = getattr(sess, "set_finder_match_cache", None)
    if callable(fn):
        fn(rows)


def _emit_open_status(path: str, status: str, message: str) -> None:
    sess = current_voice_session.get()
    if sess is None:
        return
    fn = getattr(sess, "enqueue_finder_event", None)
    if callable(fn):
        fn(
            "finder_open_status",
            {"path": path, "status": status, "message": message},
        )


@tool
def mac_finder_search(
    keyword: Annotated[
        str,
        "Keyword appearing in file or folder names (e.g. resume from 'open resume').",
    ],
    max_results: Annotated[int, "Cap on matches (default 50)."] = 50,
) -> str:
    """Search configured Mac directories for files/folders matching a keyword. Shows HUD progress.
    After results, ask which to open if there are several; then call mac_finder_open_selection."""
    if platform.system() != "Darwin":
        return "Mac Finder search runs on macOS only."
    if not mac_finder_module_configured():
        return (
            "Mac Finder search is not enabled. Set JARVIS_MAC_FINDER_PRESET=recommended and/or "
            "JARVIS_MAC_FINDER_ROOTS to a comma-separated list of folders, then restart the API."
        )
    record_tool_activity("mac_finder_search", {"keyword": keyword, "max_results": max_results})
    dirs = configured_search_directories()
    if not dirs:
        return (
            "No valid Mac Finder search directories after filtering. Check JARVIS_MAC_FINDER_PRESET "
            "and JARVIS_MAC_FINDER_ROOTS."
        )

    matches = search_files(keyword, dirs, max_results=max_results)
    rows = [m.to_row(i + 1) for i, m in enumerate(matches)]
    _set_match_cache(rows)

    sess = current_voice_session.get()
    if sess is not None:
        fn = getattr(sess, "enqueue_finder_event", None)
        if callable(fn):
            fn("finder_match_list", {"keyword": keyword, "matches": rows})

    if not matches:
        return json.dumps(
            {
                "result": "none",
                "say": f"I couldn't find any files or folders with “{keyword}”.",
                "matches": [],
            },
            ensure_ascii=False,
        )

    if len(matches) == 1:
        m0 = matches[0]
        return json.dumps(
            {
                "result": "single",
                "say": f"I found one match: {m0.name}. Should I open it?",
                "matches": rows,
            },
            ensure_ascii=False,
        )

    return json.dumps(
        {
            "result": "multiple",
            "say": (
                f"I found {len(matches)} items with “{keyword}”. "
                "Which one should I open? Say the number or the file name."
            ),
            "matches": rows,
        },
        ensure_ascii=False,
    )


@tool
def mac_finder_open_selection(
    selection_text: Annotated[
        str,
        "User reply such as 'open number 2', 'the PDF', or the filename fragment.",
    ],
    reveal_in_finder: Annotated[
        bool,
        "True to select in Finder only; False to open with the default application.",
    ] = False,
) -> str:
    """Open one item from the last mac_finder_search results using the user's selection."""
    if platform.system() != "Darwin":
        return "Mac Finder open runs on macOS only."
    record_tool_activity(
        "mac_finder_open_selection",
        {"selection_text": selection_text, "reveal_in_finder": reveal_in_finder},
    )
    sess = current_voice_session.get()
    if sess is None:
        return "No active session."
    get_cache = getattr(sess, "get_finder_match_cache", None)
    if not callable(get_cache):
        return "Match cache unavailable."
    raw_rows: list[dict[str, Any]] = get_cache()
    if not raw_rows:
        return "No pending search results. Run mac_finder_search first."

    matches = [
        FileMatch(
            path=str(r.get("path", "")),
            name=str(r.get("name", "")),
            is_directory=bool(r.get("is_directory", False)),
            file_type=str(r.get("file_type", "")),
            modified_iso=str(r.get("modified", "")),
        )
        for r in raw_rows
        if r.get("path")
    ]
    if selection_text.strip().lower() in ("yes", "yeah", "ok", "please", "open it", "go ahead"):
        if len(matches) == 1:
            picked = matches[0]
        else:
            return "Say which item (number or name); there are several matches."
    else:
        picked = resolve_user_selection(selection_text, matches)
    if picked is None:
        return (
            "I could not match that to a result. Say a list number (e.g. open 2) or part of the name."
        )

    _emit_open_status(picked.path, "opening", f"Opening {picked.name}")
    result = open_file(picked.path, reveal_in_finder=reveal_in_finder)
    if result.get("ok"):
        _emit_open_status(picked.path, "success", result.get("message", "Opened successfully"))
        return json.dumps(
            {
                "ok": True,
                "path": result.get("path"),
                "message": result.get("message", "Opened"),
            },
            ensure_ascii=False,
        )
    _emit_open_status(picked.path, "error", str(result.get("message", "failed")))
    return json.dumps(
        {"ok": False, "path": result.get("path"), "message": result.get("message")},
        ensure_ascii=False,
    )


mac_finder_tools = [mac_finder_search, mac_finder_open_selection]
