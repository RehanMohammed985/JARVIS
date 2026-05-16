"""Plugin registry for third-party tools (email, calendar, browser drivers).

Implement discover_tools() in a module and list it in PLUGIN_MODULES.
"""

from __future__ import annotations

from typing import Callable

PLUGIN_MODULES: list[str] = [
    # "app.plugins.examples",
]

ToolFactory = Callable[[], list]


def load_plugin_tools() -> list:
    """Import plugins lazily to avoid hard deps in core installs."""
    discovered: list = []
    for mod in PLUGIN_MODULES:
        try:
            imported = __import__(mod, fromlist=["discover_tools"])
            fn = getattr(imported, "discover_tools", None)
            if callable(fn):
                discovered.extend(fn())
        except Exception:
            continue
    return discovered
