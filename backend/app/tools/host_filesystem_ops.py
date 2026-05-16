"""Host-native move/copy/rename, latest-file open, and Cursor workspace open — under allowed-root policy."""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Annotated, Any

from langchain_core.tools import tool

from app.macos_open import macos_open_app_with_path
from app.security.permissions import PolicyError, is_path_under_allowed_roots, resolve_under_roots
from app.tools.filesystem_extra import _open_existing_allowed_path, keyword_search_paths
from app.voice.session_context import current_voice_session
from app.voice.tool_telemetry import record_tool_activity


def _emit(phase: str, message: str, **extra: Any) -> None:
    sess = current_voice_session.get()
    if sess is None:
        return
    fn = getattr(sess, "enqueue_finder_event", None)
    if callable(fn):
        fn("filesystem_activity", {"phase": phase, "message": message, **extra})


def _safe_stat_mtime(p: Path) -> float:
    try:
        return p.stat().st_mtime
    except OSError:
        return 0.0


def _launch_cursor_on_dir(p: Path) -> str:
    ok, err = macos_open_app_with_path("Cursor", p)
    if ok:
        return f"Opened in Cursor: {p}"
    return f"Could not launch Cursor: {err}"


@tool
def move_path(
    source: Annotated[str, "File or folder path under allowed roots"],
    destination: Annotated[str, "Target path (parent must exist unless moving a file into a new name)"],
) -> str:
    """Move a file or directory to a new location on disk."""
    record_tool_activity("move_path", {"source": source, "destination": destination})
    _emit("start", "Move: verifying paths…", source=source, dest=destination)
    try:
        src = resolve_under_roots(source)
        dst = resolve_under_roots(destination)
    except PolicyError as e:
        _emit("error", str(e))
        return f"Denied: {e}"
    if not src.exists():
        _emit("error", "Source missing")
        return f"Source does not exist: {src}"
    if dst.exists() and dst.is_dir() and src.is_dir():
        _emit("error", "Destination exists")
        return f"Refusing to overwrite existing directory: {dst}"
    try:
        _emit("mv", f"Moving to {dst.name}…", path=str(dst))
        shutil.move(str(src), str(dst))
    except OSError as e:
        _emit("error", str(e))
        return f"Move failed: {e}"
    _emit("done", f"Moved to {dst}", path=str(dst))
    return f"Moved to {dst}"


@tool
def copy_path(
    source: Annotated[str, "File or folder to copy"],
    destination: Annotated[str, "Destination file or folder path"],
) -> str:
    """Copy a file (or recursively copy a directory) under allowed roots."""
    record_tool_activity("copy_path", {"source": source, "destination": destination})
    _emit("start", "Copy: verifying paths…", source=source, dest=destination)
    try:
        src = resolve_under_roots(source)
        dst = resolve_under_roots(destination)
    except PolicyError as e:
        _emit("error", str(e))
        return f"Denied: {e}"
    if not src.exists():
        return f"Source does not exist: {src}"
    try:
        if src.is_dir():
            _emit("cp", f"Copying directory tree → {dst.name}…", path=str(dst))
            shutil.copytree(src, dst, dirs_exist_ok=True)
        else:
            _emit("cp", f"Copying file → {dst.name}…", path=str(dst))
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
    except OSError as e:
        _emit("error", str(e))
        return f"Copy failed: {e}"
    _emit("done", f"Copied to {dst}", path=str(dst))
    return f"Copied to {dst}"


@tool
def rename_in_place(
    path: Annotated[str, "File or folder to rename"],
    new_name: Annotated[str, "New name only (not a path), e.g. notes_backup.md"],
) -> str:
    """Rename a file or folder in the same directory."""
    record_tool_activity("rename_in_place", {"path": path, "new_name": new_name})
    _emit("start", "Rename: resolving…", path=path)
    try:
        src = resolve_under_roots(path)
    except PolicyError as e:
        _emit("error", str(e))
        return f"Denied: {e}"
    if not src.exists():
        return f"Path does not exist: {src}"
    name = new_name.strip().replace("\\", "").replace("/", "")
    if not name or name in (".", ".."):
        return "Invalid new name."
    dst = (src.parent / name).resolve()
    if not is_path_under_allowed_roots(dst):
        return "Denied: target path outside allowed policy."
    if dst.exists():
        return f"Target already exists: {dst}"
    try:
        _emit("rename", f"Renaming to “{name}”…", path=str(src))
        src.rename(dst)
    except OSError as e:
        _emit("error", str(e))
        return f"Rename failed: {e}"
    _emit("done", f"Renamed → {dst.name}", path=str(dst))
    return f"Renamed to {dst}"


def open_latest_pdf_impl(show_in_finder: bool = False) -> str:
    """Find the most recently modified PDF under Documents, Downloads, and Desktop, then open it."""
    _emit("scan", "Scanning Documents, Downloads, Desktop for PDFs (mtime)…")
    home = Path.home()
    roots = [home / "Documents", home / "Downloads", home / "Desktop"]
    candidates: list[Path] = []
    scanned = 0
    max_scan = 12_000
    for root in roots:
        if not root.is_dir():
            continue
        try:
            for p in root.rglob("*.pdf"):
                scanned += 1
                if scanned > max_scan:
                    break
                try:
                    rp = p.resolve()
                    if rp.is_file() and is_path_under_allowed_roots(rp):
                        candidates.append(rp)
                except OSError:
                    continue
            if scanned > max_scan:
                break
        except OSError:
            continue
    if not candidates:
        _emit("error", "No PDFs found in standard folders")
        return "No PDF files found under Documents, Downloads, or Desktop (or search cap reached)."
    candidates.sort(key=_safe_stat_mtime, reverse=True)
    best = candidates[0]
    _emit("open", f"Opening latest PDF: {best.name}", path=str(best))
    return _open_existing_allowed_path(best, reveal_in_finder=show_in_finder)


@tool
def open_latest_pdf(
    show_in_finder: Annotated[
        bool,
        "True to reveal in Finder; False to open with the default PDF viewer",
    ] = False,
) -> str:
    """Find the most recently modified PDF under Documents, Downloads, and Desktop, then open it."""
    record_tool_activity("open_latest_pdf", {"show_in_finder": show_in_finder})
    return open_latest_pdf_impl(show_in_finder)


@tool
def open_workspace_in_cursor(
    path: Annotated[
        str,
        "Folder path for the project/repo (e.g. ~/Projects/foo). Must be under allowed roots.",
    ],
) -> str:
    """Open a folder in the Cursor app (macOS `open -a Cursor`)."""
    record_tool_activity("open_workspace_in_cursor", {"path": path})
    _emit("start", "Opening folder in Cursor…", path=path)
    try:
        p = resolve_under_roots(path)
    except PolicyError as e:
        _emit("error", str(e))
        return f"Denied: {e}"
    if not p.exists():
        return f"Path does not exist: {p}"
    if not p.is_dir():
        return f"Not a directory (open the repo root folder): {p}"
    if not is_path_under_allowed_roots(p):
        return "Denied: path outside allowed roots."
    msg = _launch_cursor_on_dir(p)
    if msg.startswith("Opened"):
        _emit("done", f"Launched Cursor for {p.name}", path=str(p))
    else:
        _emit("error", msg)
    return msg


@tool
def create_markdown_in_documents(
    filename: Annotated[str, 'File name only, e.g. "notes.md" — not a full path'],
    content: Annotated[str, "Markdown body"] = "",
) -> str:
    """Create a .md file in the user Documents folder (real macOS ~/Documents)."""
    record_tool_activity(
        "create_markdown_in_documents",
        {"filename": filename, "chars": len(content or "")},
    )
    home = Path.home().resolve()
    docs = (home / "Documents").resolve()
    _emit("start", "Creating markdown in Documents…", path=str(docs))
    name = (filename or "").strip().replace("\\", "").replace("/", "")
    if not name:
        name = "untitled.md"
    elif not name.lower().endswith(".md"):
        name = f"{name}.md"
    target = (docs / name).resolve()
    try:
        target.relative_to(home)
    except ValueError:
        msg = "Refusing to write outside home."
        _emit("error", msg)
        return msg
    if not is_path_under_allowed_roots(target):
        _emit("error", "Policy denied path")
        return "Denied: path outside allowed policy."
    try:
        docs.mkdir(parents=True, exist_ok=True)
        _emit("write", f"Writing {target.name}", path=str(target))
        target.write_text(content or "", encoding="utf-8")
    except OSError as e:
        _emit("error", str(e))
        return f"Write failed: {e}"
    _emit("done", "Markdown file ready", path=str(target))
    body = f"Created {target}"
    tail = _open_existing_allowed_path(target, reveal_in_finder=False)
    return f"{body}. {tail}"


def _collect_repo_candidates(frag: str, home: Path) -> list[Path]:
    hits: list[Path] = []
    seen: set[str] = set()
    subroots = [
        home,
        home / "Projects",
        home / "Code",
        home / "Developer",
        home / "Dev",
        home / "src",
        home / "Sites",
        home / "Workspace",
        home / "work",
        home / "Documents",
        home / "Desktop",
    ]
    for base in subroots:
        if not base.is_dir():
            continue
        try:
            for child in base.iterdir():
                if not child.is_dir() or child.name.startswith("."):
                    continue
                if frag in child.name.lower():
                    try:
                        r = child.resolve()
                    except OSError:
                        continue
                    k = str(r)
                    if k not in seen and is_path_under_allowed_roots(r):
                        seen.add(k)
                        hits.append(r)
                if base == home and len(hits) < 40:
                    try:
                        for sub in child.iterdir():
                            if not sub.is_dir() or sub.name.startswith("."):
                                continue
                            if frag in sub.name.lower():
                                try:
                                    r2 = sub.resolve()
                                except OSError:
                                    continue
                                k2 = str(r2)
                                if k2 not in seen and is_path_under_allowed_roots(r2):
                                    seen.add(k2)
                                    hits.append(r2)
                    except OSError:
                        pass
        except OSError:
            continue
    return hits


@tool
def open_named_repo_in_cursor(
    folder_name_fragment: Annotated[
        str,
        'Fragment of the repo folder name, e.g. "Campanion", "jarvis" — searches under home',
    ],
) -> str:
    """Find a project folder under your home whose name matches the fragment, then open it in Cursor."""
    record_tool_activity("open_named_repo_in_cursor", {"folder_name_fragment": folder_name_fragment})
    frag = (folder_name_fragment or "").strip().lower()
    if len(frag) < 2:
        return "Provide a clearer folder or repo name fragment."
    home = Path.home().resolve()
    _emit("scan", f"Searching for folder matching “{folder_name_fragment}”…")
    hits = _collect_repo_candidates(frag, home)
    if len(hits) < 3:
        for s in keyword_search_paths(folder_name_fragment, max_hits=40):
            pth = Path(s)
            try:
                cand = pth if pth.is_dir() else pth.parent
                if cand.is_dir() and frag in cand.name.lower():
                    k = str(cand.resolve())
                    if k not in {str(h) for h in hits} and is_path_under_allowed_roots(cand):
                        hits.append(cand.resolve())
            except OSError:
                continue
    if not hits:
        _emit("error", "No matching project folder")
        return (
            f"No folder under home matched {folder_name_fragment!r}. "
            "Try the full path with open_workspace_in_cursor."
        )
    hits.sort(key=_safe_stat_mtime, reverse=True)
    pick = hits[0]
    _emit("open", f"Opening in Cursor: {pick.name}", path=str(pick))
    msg = _launch_cursor_on_dir(pick)
    if msg.startswith("Opened"):
        _emit("done", msg, path=str(pick))
    else:
        _emit("error", msg)
    return msg
