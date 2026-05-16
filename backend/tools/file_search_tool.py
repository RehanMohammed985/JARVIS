"""Shim re-export: implementation lives in ``app.tools.file_search_tool`` (package layout)."""

from app.tools.file_search_tool import (
    FileMatch,
    mac_finder_module_configured,
    mac_finder_open_selection,
    mac_finder_search,
    mac_finder_tools,
    open_file,
    resolve_user_selection,
    search_files,
)

__all__ = [
    "FileMatch",
    "mac_finder_module_configured",
    "mac_finder_open_selection",
    "mac_finder_search",
    "mac_finder_tools",
    "open_file",
    "resolve_user_selection",
    "search_files",
]
