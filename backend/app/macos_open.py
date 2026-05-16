"""Host-native ``/usr/bin/open`` helpers.

macOS often hands files to Launch Services asynchronously. In those cases ``open`` can exit
non-zero with an empty stderr even though the document opened. We only treat subprocess output
as failure when it clearly indicates a missing path or TCC denial.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Sequence


def _merged_output(r: subprocess.CompletedProcess[str]) -> str:
    e = (r.stderr or "").strip()
    o = (r.stdout or "").strip()
    return (e + "\n" + o).strip().lower()


def _suggests_fatal_open_error(msg_lower: str) -> bool:
    if not msg_lower:
        return False
    fatal = (
        "no such file or directory",
        "does not exist",
        "can't open file",
        "cannot open file",
        "not permitted.",
        "operation not permitted",
        "permission denied",
        "no application knows how to open",
        "unable to open",
        "invalid argument",
        "can't find application",
        "unable to find application",
    )
    return any(x in msg_lower for x in fatal)


def open_argv(
    argv: Sequence[str],
    *,
    path_hint: Path | None = None,
    timeout: float = 32,
) -> tuple[bool, str]:
    """Run ``open`` (or any argv). If exit code is non-zero, apply LaunchServices leniency when
    ``path_hint`` exists and stderr does not show a clear hard failure.
    """
    try:
        r = subprocess.run(
            list(argv),
            capture_output=True,
            text=True,
            timeout=timeout,
            env=os.environ.copy(),
        )
    except (OSError, subprocess.TimeoutExpired) as e:
        return False, str(e)
    if r.returncode == 0:
        return True, ""
    merged = _merged_output(r)
    if path_hint is None:
        if _suggests_fatal_open_error(merged):
            return False, (merged or f"exit {r.returncode}")[:800]
        return True, ""
    try:
        exists = path_hint.exists()
    except OSError:
        exists = False
    if exists and not _suggests_fatal_open_error(merged):
        return True, ""
    tail = merged or f"exit {r.returncode}"
    return False, tail[:800]


def macos_open_path(path: Path, *, reveal_only: bool) -> tuple[bool, str]:
    """``open`` a file/dir, or ``open -R`` to reveal in Finder."""
    opener = "/usr/bin/open" if Path("/usr/bin/open").is_file() else "open"
    ps = str(path.resolve())
    last_err = ""
    if reveal_only:
        for args in ((opener, "-R", ps), (opener, "-g", "-R", ps)):
            ok, err = open_argv(args, path_hint=path)
            last_err = err
            if ok:
                return True, ""
        return False, last_err
    for args in ((opener, ps), (opener, "-g", ps)):
        ok, err = open_argv(args, path_hint=path)
        last_err = err
        if ok:
            return True, ""
    return False, last_err


def macos_open_application(app_name: str) -> tuple[bool, str]:
    """``open -a Name``."""
    opener = "/usr/bin/open" if Path("/usr/bin/open").is_file() else "open"
    ok, err = open_argv((opener, "-a", app_name), path_hint=None)
    if ok:
        return True, ""
    ok2, err2 = open_argv((opener, "-g", "-a", app_name), path_hint=None)
    if ok2:
        return True, ""
    return False, err or err2


def macos_open_app_with_path(app_name: str, path: Path) -> tuple[bool, str]:
    """``open -a App path`` (e.g. Cursor workspace)."""
    opener = "/usr/bin/open" if Path("/usr/bin/open").is_file() else "open"
    ps = str(path.resolve())
    for args in ((opener, "-a", app_name, ps), (opener, "-g", "-a", app_name, ps)):
        ok, err = open_argv(args, path_hint=path)
        if ok:
            return True, ""
    return False, err
