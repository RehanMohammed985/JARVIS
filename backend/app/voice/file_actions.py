from __future__ import annotations

import platform
from pathlib import Path

from app.config import settings
from app.voice.session_context import current_voice_session


def running_in_docker() -> bool:
    """True when the process is running inside a typical Linux container."""
    return Path("/.dockerenv").is_file()


def should_delegate_file_actions_to_client() -> bool:
    """When True, open/show-in-Finder runs on the user's Mac via the browser + local bridge.

    - client: always delegate (API never runs `open` / AppleScript).
    - server: never delegate (API runs macOS commands — works only on a bare-metal Mac API).
    - auto: delegate in Docker, on non-macOS hosts, or when JARVIS_FORCE_CLIENT_FILE_ACTIONS=1.
    """
    mode = settings.file_actions_mode
    if mode == "client":
        return True
    if mode == "server":
        return False
    if settings.force_client_file_actions:
        return True
    if running_in_docker():
        return True
    if platform.system() != "Darwin":
        return True
    return False


def enqueue_local_file_action(action: str, path: str) -> None:
    """Queue a file action for the HUD to run against the local desktop bridge."""
    sess = current_voice_session.get()
    if sess is None:
        return
    fn = getattr(sess, "enqueue_local_file_action", None)
    if callable(fn):
        fn(action, path)
