from __future__ import annotations

from pathlib import Path

from app.config import settings


class PermissionError(Exception):
    """Raised when a path or command is outside allowed policy."""


def _special_fs_blocked(path: Path) -> bool:
    """Block kernel/meta filesystems even in full-disk desktop mode."""
    try:
        prefix = str(path.resolve())
    except OSError:
        prefix = str(path)
    blocked = (
        "/dev/",
        "/proc/",
        "/sys/",
        "/net/",
        "/run/",
    )
    if prefix in ("/dev", "/proc", "/sys", "/net", "/run"):
        return True
    return any(prefix.startswith(b) for b in blocked)


def resolve_under_roots(path: str | Path) -> Path:
    """Resolve a user/model path to a real path that lies under at least one allowed root.

    Relative paths are tried against: cwd, then each configured root (so "README.md" can
    resolve to the repo or home instead of only uvicorn's cwd).
    """
    raw = Path(path).expanduser()
    candidates: list[Path] = []
    if raw.is_absolute():
        candidates.append(raw.resolve())
    else:
        candidates.append((Path.cwd() / raw).resolve())
        for root in settings.allowed_root_paths:
            candidates.append((root / raw).resolve())

    seen: set[str] = set()
    for cand in candidates:
        key = str(cand)
        if key in seen:
            continue
        seen.add(key)
        try:
            cand = cand.resolve()
        except OSError:
            continue
        if settings.full_filesystem_access:
            if _special_fs_blocked(cand):
                continue
            try:
                if str(cand).startswith("/"):
                    return cand
            except (OSError, ValueError):
                continue
        for root in settings.allowed_root_paths:
            try:
                cand.relative_to(root)
                return cand
            except ValueError:
                continue
    if settings.full_filesystem_access:
        raise PermissionError(
            f"{path} (outside accessible paths, blocked location, or path could not be resolved)"
        )
    roots_hint = ", ".join(str(r) for r in settings.allowed_root_paths)
    raise PermissionError(f"{path} (not under allowed roots: {roots_hint})")


def is_path_under_allowed_roots(path: str | Path) -> bool:
    """True if path resolves under policy (full local disk on bare desktop, else sandbox roots)."""
    try:
        resolved = Path(path).expanduser().resolve()
    except OSError:
        return False
    if settings.full_filesystem_access:
        try:
            s = str(resolved)
        except OSError:
            return False
        if not s.startswith("/"):
            return False
        return not _special_fs_blocked(resolved)
    for root in settings.allowed_root_paths:
        try:
            resolved.relative_to(root.resolve())
            return True
        except ValueError:
            continue
    return False


def is_terminal_command_allowed(command: str) -> bool:
    prefixes = [
        p.strip()
        for p in settings.terminal_allow_prefixes.split(",")
        if p.strip()
    ]
    if not prefixes:
        return False
    cmd = command.strip()
    return any(cmd.startswith(prefix) for prefix in prefixes)
