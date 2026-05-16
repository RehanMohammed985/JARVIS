"""Create folders (and optional files) under the user home using plain-English locations — no hardcoded /Users/… paths."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Annotated, Any

from langchain_core.tools import tool

from app.security.permissions import is_path_under_allowed_roots
from app.voice.file_actions import enqueue_local_file_action
from app.voice.session_context import current_voice_session
from app.voice.tool_telemetry import record_tool_activity


def _emit_activity(phase: str, message: str, **extra: Any) -> None:
    sess = current_voice_session.get()
    if sess is None:
        return
    fn = getattr(sess, "enqueue_finder_event", None)
    if callable(fn):
        payload = {"phase": phase, "message": message, **extra}
        fn("filesystem_activity", payload)


def resolve_user_location_to_path(location_description: str) -> Path:
    """Map phrases like "my downloads", "desktop" to ``Path.home()`` / standard folder."""
    home = Path.home().resolve()
    s = (location_description or "").strip().lower()
    s = re.sub(r"[`'\"]+", " ", s)
    s = re.sub(r"[^\w\s]", " ", s)
    s = re.sub(r"\b(on|in|at|to|from|for|the|a|an|my|me)\b", " ", s)
    s = re.sub(r"\b(folder|directory|named|called|call|name)\b", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    # typo hints
    blob = s.replace(" ", "")
    if "donwlaod" in blob or "downlaod" in blob or "download" in s:
        return home / "Downloads"
    if "desktop" in s:
        return home / "Desktop"
    if "document" in s:
        return home / "Documents"
    if "picture" in s or "photo" in s:
        return home / "Pictures"
    if "movie" in s:
        return home / "Movies"
    if re.search(r"\bmusic\b", s):
        return home / "Music"
    if "public" in s:
        return home / "Public"
    if not s or s in ("home", "user", "house", "~"):
        return home
    # single token e.g. "downloads"
    first = s.split()[0] if s else ""
    token_map = {
        "downloads": home / "Downloads",
        "download": home / "Downloads",
        "desktop": home / "Desktop",
        "documents": home / "Documents",
        "pictures": home / "Pictures",
        "movies": home / "Movies",
        "music": home / "Music",
        "public": home / "Public",
    }
    if first in token_map:
        return token_map[first]
    raise ValueError(
        f"Could not resolve location {location_description!r}. "
        "Say e.g. Downloads, Desktop, Documents, or Home."
    )


def safe_folder_segment(name: str) -> str:
    n = (name or "").strip()
    n = n.replace("\\", "-").replace("/", "-")
    n = re.sub(r"^\.+", "", n)
    if not n or n in (".", ".."):
        raise ValueError("Folder name is empty or invalid.")
    if ".." in n or "/" in n or "\\" in n:
        raise ValueError("Folder name must be a single name, not a path.")
    return n


@tool
def create_folder_for_user(
    folder_name: Annotated[str, 'Only the folder name, e.g. "resume" or "Tax 2024" — not a full path'],
    location: Annotated[
        str,
        'Where to create it in plain English, e.g. "my downloads", "desktop", "documents"',
    ],
    reveal_in_finder: Annotated[
        bool,
        "If true (default), show the new folder in Finder after creating.",
    ] = True,
) -> str:
    """Create a folder under the user’s home (Downloads, Desktop, etc.) from plain English. Sends live HUD activity."""
    record_tool_activity(
        "create_folder_for_user",
        {"folder_name": folder_name, "location": location, "reveal_in_finder": reveal_in_finder},
    )
    _emit_activity(
        "start",
        f"Creating folder “{folder_name.strip()}” — resolving location…",
        folder_name=folder_name.strip(),
        location_hint=location.strip(),
    )
    try:
        base = resolve_user_location_to_path(location)
    except ValueError as e:
        _emit_activity("error", str(e))
        return str(e)

    _emit_activity("resolved", f"Parent: {base}", path=str(base))

    try:
        seg = safe_folder_segment(folder_name)
    except ValueError as e:
        _emit_activity("error", str(e))
        return str(e)

    target = (base / seg).resolve()
    _emit_activity("mkdir", f"Writing {target.name} under {base.name}", path=str(target))

    try:
        home = Path.home().resolve()
        target.relative_to(home)
    except ValueError:
        msg = "Refusing to create outside your home folder."
        _emit_activity("error", msg)
        return msg

    if not is_path_under_allowed_roots(target):
        msg = "Denied: path is outside allowed policy (check JARVIS_ALLOWED_ROOTS or run on desktop with defaults)."
        _emit_activity("error", msg)
        return msg

    existed = target.exists() and target.is_dir()
    try:
        target.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        _emit_activity("error", str(e))
        return f"Could not create folder: {e}"

    status = "Folder already existed." if existed else "Folder created."
    _emit_activity("done", f"{status} {target}", path=str(target), created=not existed)

    if reveal_in_finder:
        enqueue_local_file_action("reveal", str(target))
        _emit_activity("finder", "Showing in Finder…", path=str(target))

    return f"{status} Path: {target}"
