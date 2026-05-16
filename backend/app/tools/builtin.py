from __future__ import annotations

import platform
import subprocess
from pathlib import Path
from typing import Annotated

from langchain_core.tools import tool

from app.config import settings
from app.macos_open import macos_open_application
from app.plugins.registry import load_plugin_tools
from app.memory.store import get_memory_store
from app.security.permissions import PolicyError, is_terminal_command_allowed, resolve_under_roots
from app.tools.file_search_tool import mac_finder_tools
from app.tools.filesystem_extra import find_and_open_file, open_path, search_files_by_keyword, show_in_finder
from app.tools.host_filesystem_ops import (
    copy_path,
    create_markdown_in_documents,
    move_path,
    open_latest_pdf,
    open_named_repo_in_cursor,
    open_workspace_in_cursor,
    rename_in_place,
)
from app.tools.user_folder_ops import create_folder_for_user
from app.voice.session_context import current_voice_session
from app.voice.tool_telemetry import record_tool_activity


@tool
def voice_set_listening(
    listen: Annotated[
        bool,
        "False stops the HUD microphone until the user taps Speak again. True keeps listening.",
    ],
) -> str:
    """Control browser listening. Use when the user says goodbye, mute, stop listening, or you dismiss them."""
    sess = current_voice_session.get()
    if sess is None:
        return "Acknowledged."
    sess.desired_mic_listening = listen
    return (
        "I'll stop listening until you need me again."
        if not listen
        else "Very good — I'm still listening when you're ready."
    )


@tool
def filesystem_overview() -> str:
    """Summarize allowed filesystem roots Jarvis may access and a shallow listing of each."""
    record_tool_activity("filesystem_overview", {})
    lines: list[str] = []
    if settings.full_filesystem_access:
        lines.append(
            "LOCAL FULL DISK — Jarvis may open, search, and read any path on this machine "
            "(except kernel pseudo-mounts like /dev and /proc). Spotlight covers most files; "
            "walk search uses home, external volumes, and common mount points."
        )
        preview_roots: list[tuple[str, Path]] = [("HOME", Path.home())]
        if platform.system() == "Darwin":
            preview_roots.append(("VOLUMES", Path("/Volumes")))
        elif platform.system() == "Linux":
            preview_roots.extend(
                ("MOUNT", p) for p in (Path("/mnt"), Path("/media")) if p.is_dir()
            )
    else:
        preview_roots = [(f"ROOT {root}", root) for root in settings.allowed_root_paths]

    for label, root in preview_roots:
        lines.append(f"{label} {root}")
        try:
            if not root.is_dir():
                lines.append("  (not a directory)")
                continue
            visible = [
                x
                for x in sorted(
                    root.iterdir(),
                    key=lambda a: (not a.is_dir(), a.name.lower()),
                )
                if not x.name.startswith(".")
            ]
            for x in visible[:30]:
                suffix = "/" if x.is_dir() else ""
                lines.append(f"  {x.name}{suffix}")
            if len(visible) > 30:
                lines.append(f"  … +{len(visible) - 30} more (use list_directory)")
        except OSError as e:
            lines.append(f"  (unreadable: {e})")
    if not settings.full_filesystem_access:
        lines.append(
            "Unrestricted local disk is the default on a bare Mac/Linux install when "
            "JARVIS_ALLOWED_ROOTS is unset. Set that variable to restrict Jarvis to specific folders."
        )
    return "\n".join(lines)


@tool
def list_directory(
    path: Annotated[str, "Folder under allowed roots; use . for your default root"],
    max_entries: Annotated[int, "Max names to return"] = 120,
) -> str:
    """List files and subfolders in one directory (under sandbox roots)."""
    record_tool_activity("list_directory", {"path": path, "max_entries": max_entries})
    try:
        p = resolve_under_roots(path)
    except PolicyError as e:
        return (
            f"Denied: {e}. Use filesystem_overview to see allowed roots, "
            "or extend JARVIS_ALLOWED_ROOTS."
        )
    if not p.is_dir():
        return f"Not a directory: {p}"
    max_entries = max(10, min(int(max_entries), 400))
    try:
        items = sorted(p.iterdir(), key=lambda x: (not x.is_dir(), x.name.lower()))
    except OSError as e:
        return f"List error: {e}"
    visible = [x for x in items if not x.name.startswith(".")]
    lines: list[str] = [f"{p} ({len(items)} entries):"]
    subset = visible[:max_entries]
    for x in subset:
        tag = "DIR " if x.is_dir() else "FILE"
        try:
            extra = f" ({x.stat().st_size} B)" if x.is_file() else ""
        except OSError:
            extra = ""
        lines.append(f"  {tag} {x.name}{extra}")
    if len(visible) > len(subset):
        lines.append(f"… +{len(visible) - len(subset)} more entries")
    return "\n".join(lines)


@tool
def find_files(
    pattern: Annotated[
        str,
        "Glob fragment only (no path slashes): *.py, report.pdf, *resume*, notes-*.md",
    ],
    root_path: Annotated[str, "Folder under allowed roots to search from, default ."] = ".",
    max_hits: Annotated[int, "Maximum files returned"] = 80,
) -> str:
    """Search files under an allowed directory by glob (recursive)."""
    record_tool_activity("find_files", {"pattern": pattern, "root_path": root_path})
    pat = pattern.strip()
    if not pat or any(c in pat for c in ("..",)):
        return "Invalid pattern."
    if "/" in pat or "\\" in pat:
        return "Use a single glob fragment (e.g. *.md), not a nested path."
    if "**" in pat:
        return "Use one * wildcard per segment (e.g. *resume*) — not **."
    try:
        base = resolve_under_roots(root_path)
    except PolicyError as e:
        return f"Denied: {e}"
    if not base.is_dir():
        return f"Search root is not a directory: {base}"
    max_hits = max(5, min(int(max_hits), 200))
    hits: list[str] = []
    try:
        for hit in sorted(base.rglob(pat)):
            if hit.is_file():
                hits.append(str(hit))
            if len(hits) >= max_hits:
                break
    except OSError as e:
        return f"Glob error: {e}"
    if not hits:
        return f"No files matching {pat!r} under {base} (limit {max_hits})."
    extra = "\n… (cap reached)" if len(hits) >= max_hits else ""
    return "\n".join(hits) + extra


@tool
def read_file(path: Annotated[str, "Path under allowed dirs; use only when user wants a file read"]) -> str:
    """Read UTF-8 text. Do not call for general chat — only when user asked for this file."""
    record_tool_activity("read_file", {"path": path})
    try:
        p = resolve_under_roots(path)
    except PolicyError as e:
        return (
            f"Denied: {e}. Ask the user for a path under their allowed folders, "
            "or they can set JARVIS_ALLOWED_ROOTS."
        )
    if not p.is_file():
        return f"Not a file: {p}"
    try:
        return p.read_text(encoding="utf-8", errors="replace")
    except OSError as e:
        return f"Read error: {e}"


@tool
def write_file(
    path: Annotated[str, "Target path"],
    content: Annotated[str, "Full file contents"],
) -> str:
    """Write or overwrite a UTF-8 file under allowed directories."""
    record_tool_activity("write_file", {"path": path})
    try:
        p = resolve_under_roots(path)
    except PolicyError as e:
        return f"Denied: {e}"
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
        return f"Wrote {len(content)} chars to {p}"
    except OSError as e:
        return f"Write error: {e}"


@tool
def run_terminal(
    command: Annotated[str, "Single-line shell command; must match allowlist prefixes"],
) -> str:
    """Run a sandboxed terminal command (prefix allowlist only)."""
    record_tool_activity("run_terminal", {"command": command})
    if not is_terminal_command_allowed(command):
        return (
            "Command not on allowlist. Ask the operator to extend "
            "JARVIS_TERMINAL_ALLOW_PREFIXES."
        )
    try:
        proc = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=120,
            cwd=str(settings.allowed_root_paths[0]),
        )
        out = (proc.stdout or "") + (proc.stderr or "")
        return out[:32000] or f"exit {proc.returncode}"
    except subprocess.TimeoutExpired:
        return "Command timed out after 120s."
    except OSError as e:
        return f"Execution error: {e}"


@tool
def open_application(name: Annotated[str, "Application name: cursor, terminal, finder"]) -> str:
    """Open a local GUI application (macOS-oriented; best-effort on Linux)."""
    key = name.strip().lower()
    system = platform.system()
    try:
        if system == "Darwin":
            mapping = {
                "cursor": "Cursor",
                "terminal": "Terminal",
                "finder": "Finder",
                "vscode": "Visual Studio Code",
            }
            app = mapping.get(key, name.strip())
            ok, err = macos_open_application(app)
            if ok:
                return f"Opened {app}"
            return f"Open failed: {err}"
        if system == "Linux":
            import subprocess

            subprocess.run(["xdg-open", name], check=False)
            return f"xdg-open {name}"
        return f"Unsupported desktop OS: {system}"
    except OSError as e:
        return f"Open failed: {e}"


@tool
def memory_save_fact(
    fact: Annotated[str, "Short fact or preference to remember long-term"],
) -> str:
    """Persist an atomic fact into local vector memory."""
    mid = get_memory_store().remember(
        fact,
        metadata={"source": "user", "kind": "fact"},
    )
    return f"remembered:{mid}"


@tool
def memory_search(
    query: Annotated[str, "What to recall from past context"],
) -> str:
    """Retrieve relevant past notes from vector memory."""
    hits = get_memory_store().recall(query)
    if not hits:
        return "No relevant memory."
    return "\n---\n".join(hits)


@tool
def fetch_url(url: Annotated[str, "https URL"]) -> str:
    """Fetch web page text (readability-lite: strip tags naively)."""
    import re

    import httpx

    try:
        r = httpx.get(url, timeout=30.0, follow_redirects=True)
        r.raise_for_status()
        text = re.sub(r"<[^>]+>", " ", r.text)
        text = re.sub(r"\s+", " ", text).strip()
        return text[:12000]
    except httpx.HTTPError as e:
        return f"HTTP error: {e}"


@tool
def email_list_unread_dummy() -> str:
    """Placeholder: wire to IMAP/Gmail API with app password when configured."""
    return (
        "Email integration not configured. Set IMAP or Gmail OAuth in backend "
        "and replace this tool with a real provider."
    )


@tool
def calendar_list_dummy() -> str:
    """Placeholder for CalDAV / Google Calendar."""
    return "Calendar integration stub — connect Apple Calendar or Google Calendar APIs."


def all_tools():
    core = [
        voice_set_listening,
        filesystem_overview,
        list_directory,
        find_files,
        search_files_by_keyword,
        find_and_open_file,
        read_file,
        write_file,
        run_terminal,
        open_application,
        open_path,
        show_in_finder,
        create_folder_for_user,
        move_path,
        copy_path,
        rename_in_place,
        open_latest_pdf,
        open_workspace_in_cursor,
        open_named_repo_in_cursor,
        create_markdown_in_documents,
        *mac_finder_tools,
        memory_save_fact,
        memory_search,
        fetch_url,
        email_list_unread_dummy,
        calendar_list_dummy,
    ]
    return [*core, *load_plugin_tools()]
