"""Host macOS checks — TCC cannot be queried reliably from Python; we probe best-effort.

Run the Jarvis API **natively** on macOS (real Terminal / Cursor / Python), not inside Docker,
so ``Path.home()``, Finder, AppleScript, and ``open`` target your machine.
"""

from __future__ import annotations

import errno
import platform
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

from app.config import settings

# Shown in HUD and echoed in README — keep steps actionable.
MACOS_SETUP_SECTIONS: list[dict[str, Any]] = [
    {
        "id": "native_host",
        "title": "Run the backend on macOS (not Docker)",
        "steps": [
            "Start uvicorn from Terminal or from Cursor's integrated terminal using your host Python venv (see `backend/requirements.txt`).",
            "Do not run the FastAPI app inside a Linux container for normal use — `Path.home()` and Finder would target the container.",
            "Optional: `docker compose up -d ollama` for Ollama only; keep `OLLAMA_BASE_URL=http://127.0.0.1:11434` pointing at the host.",
            "Convenience script: `./scripts/run_backend_native_macos.sh` from the repo root.",
        ],
        "after_save": "Restart: stop uvicorn (Ctrl+C) and run your start command again.",
    },
    {
        "id": "full_disk",
        "title": "Full Disk Access",
        "steps": [
            "Open System Settings → Privacy & Security → Full Disk Access.",
            "Enable the app that launches the Python process: usually Terminal, iTerm, or Cursor (if you start uvicorn from the IDE terminal).",
            "If you launch python/uvicorn by absolute path, you may need to add that binary or the wrapping app — check the HUD Host Python path.",
            "Without FDA, Mail, Safari data, some iCloud paths, and other protected locations may fail with “Operation not permitted”.",
        ],
        "after_save": "Quit and relaunch Terminal or Cursor (full quit from Dock), then start uvicorn again.",
    },
    {
        "id": "files_and_folders",
        "title": "Files and Folders (Desktop, Documents, Downloads)",
        "steps": [
            "Open System Settings → Privacy & Security → Files and Folders.",
            "Allow your Terminal / Cursor / Python to access Desktop, Documents, Downloads as needed.",
        ],
        "after_save": "Relaunch Terminal/Cursor if macOS still blocks folder access.",
    },
    {
        "id": "automation_finder",
        "title": "Automation — control Finder",
        "steps": [
            "When macOS prompts, allow Terminal (or Cursor) to control Finder.",
            "Or: System Settings → Privacy & Security → Automation → expand your terminal app → enable Finder.",
        ],
        "after_save": "No full reboot required; retry after toggling. If stuck, relaunch Terminal.",
    },
    {
        "id": "accessibility",
        "title": "Accessibility (optional but recommended)",
        "steps": [
            "System Settings → Privacy & Security → Accessibility.",
            "Add Terminal, Cursor, or Python if AppleScript / automation prompts mention accessibility.",
        ],
        "after_save": "Toggle off/on and relaunch the app if behaviour is inconsistent.",
    },
    {
        "id": "microphone",
        "title": "Microphone",
        "steps": [
            "Browser HUD: When Chrome/Safari asks, allow the microphone for http://localhost:3000 (voice capture is in the browser).",
            "Native `./jarvis` listener: Allow Terminal (or the app running the script) under Privacy & Security → Microphone.",
        ],
        "after_save": "Reload the HUD page or restart the terminal listener after granting.",
    },
    {
        "id": "file_actions_mode",
        "title": "Native `open` vs browser bridge",
        "steps": [
            "On a bare Mac, defaults use native `open`. If you set `JARVIS_FILE_ACTIONS_MODE=client`, file opens go through `scripts/jarvis_file_bridge.py` — run it on the Mac or switch to `JARVIS_FILE_ACTIONS_MODE=server`.",
        ],
        "after_save": "Restart uvicorn after changing `.env`.",
    },
]


def _probe_finder_automation() -> tuple[bool, str]:
    try:
        r = subprocess.run(
            [
                "osascript",
                "-e",
                'tell application "Finder" to get version',
            ],
            capture_output=True,
            text=True,
            timeout=12,
        )
    except (OSError, subprocess.TimeoutExpired) as e:
        return False, str(e)
    if r.returncode == 0:
        return True, ""
    return False, (r.stderr or r.stdout or "").strip() or f"exit {r.returncode}"


def _probe_system_events_accessibility() -> tuple[bool, str]:
    """Best-effort: System Events queries often need Accessibility + Automation."""
    try:
        r = subprocess.run(
            [
                "osascript",
                "-e",
                'tell application "System Events" to count processes',
            ],
            capture_output=True,
            text=True,
            timeout=12,
        )
    except (OSError, subprocess.TimeoutExpired) as e:
        return False, str(e)
    if r.returncode == 0:
        return True, ""
    err = (r.stderr or r.stdout or "").strip()
    return False, err or f"exit {r.returncode}"


def _try_listdir(path: Path) -> tuple[bool, str | None]:
    if not path.exists():
        return True, None
    try:
        next(path.iterdir())
        return True, None
    except OSError as e:
        if e.errno in (errno.EPERM, errno.EACCES):
            return False, str(e)
        return True, None


def _probe_full_disk_library() -> str | None:
    home = Path.home()
    probes = [
        home / "Library/Mail",
        home / "Library/Messages",
        home / "Library/Safari",
    ]
    for p in probes:
        if not p.exists():
            continue
        ok, err = _try_listdir(p)
        if not ok:
            return f"Cannot read protected Library folder {p.name} ({err}). Full Disk Access is likely required for the host running Python."
    return None


def _compile_permission_checks() -> list[dict[str, Any]]:
    """Structured rows for HUD; status is derived from probes on Darwin."""
    checks: list[dict[str, Any]] = []
    home = Path.home()

    # Native vs docker
    if settings.running_in_docker:
        checks.append(
            {
                "id": "host_runtime",
                "label": "Host-native backend (not Docker)",
                "status": "error",
                "detail": "Process has /.dockerenv — use macOS Terminal + host Python, not the API container.",
            }
        )
    elif platform.system() != "Darwin":
        checks.append(
            {
                "id": "host_runtime",
                "label": "macOS host",
                "status": "info",
                "detail": "Not macOS; Finder/native open use fallbacks or bridge.",
            }
        )
    else:
        checks.append(
            {
                "id": "host_runtime",
                "label": "Host-native on macOS",
                "status": "ok",
                "detail": "API process is not running inside Docker.",
            }
        )

    if platform.system() != "Darwin" or settings.running_in_docker:
        checks.append(
            {
                "id": "guide",
                "label": "Manual setup",
                "status": "info",
                "detail": "Open the checklist below for Full Disk Access, Automation, and microphone steps.",
            }
        )
        return checks

    for folder_name, rel in (
        ("Desktop", home / "Desktop"),
        ("Documents", home / "Documents"),
        ("Downloads", home / "Downloads"),
    ):
        if not rel.exists():
            checks.append(
                {
                    "id": f"folder_{folder_name.lower()}",
                    "label": f"{folder_name} access",
                    "status": "info",
                    "detail": f"{folder_name} path not present — skipped.",
                }
            )
            continue
        ok, err = _try_listdir(rel)
        if ok:
            checks.append(
                {
                    "id": f"folder_{folder_name.lower()}",
                    "label": f"{folder_name} readable",
                    "status": "ok",
                    "detail": "Folder is readable by this process.",
                }
            )
        else:
            checks.append(
                {
                    "id": f"folder_{folder_name.lower()}",
                    "label": f"{folder_name} readable",
                    "status": "error",
                    "detail": f"Blocked: {err}. Enable Files and Folders or Full Disk Access for your Terminal/Cursor/Python host.",
                }
            )

    icloud = home / "Library/Mobile Documents/com~apple~CloudDocs"
    if icloud.is_dir():
        ok, err = _try_listdir(icloud)
        if ok:
            checks.append(
                {
                    "id": "icloud",
                    "label": "iCloud Drive (~/Library/Mobile Documents/…)",
                    "status": "ok",
                    "detail": "Readable.",
                }
            )
        else:
            checks.append(
                {
                    "id": "icloud",
                    "label": "iCloud Drive",
                    "status": "warn",
                    "detail": f"May be limited: {err}. Grant Full Disk Access or Files and Folders if tools must see iCloud files.",
                }
            )

    vol = Path("/Volumes")
    if vol.is_dir():
        try:
            list(vol.iterdir())
            checks.append(
                {
                    "id": "volumes",
                    "label": "External volumes (/Volumes)",
                    "status": "ok",
                    "detail": "Readable.",
                }
            )
        except OSError as e:
            checks.append(
                {
                    "id": "volumes",
                    "label": "External volumes",
                    "status": "warn",
                    "detail": f"Listing /Volumes failed: {e}. Full Disk Access may help for external drives.",
                }
            )

    lib_issue = _probe_full_disk_library()
    if lib_issue:
        checks.append(
            {
                "id": "full_disk_library",
                "label": "Protected Library (FDA probe)",
                "status": "warn",
                "detail": lib_issue,
            }
        )
    else:
        probes_exist = any(
            (home / p).exists()
            for p in (
                "Library/Mail",
                "Library/Messages",
                "Library/Safari",
            )
        )
        if probes_exist:
            checks.append(
                {
                    "id": "full_disk_library",
                    "label": "Protected Library (FDA probe)",
                    "status": "ok",
                    "detail": "Sample protected Library folders readable.",
                }
            )

    if shutil.which("osascript"):
        ok_f, err_f = _probe_finder_automation()
        checks.append(
            {
                "id": "finder_automation",
                "label": "Finder / Apple Events",
                "status": "ok" if ok_f else "error",
                "detail": "osascript can query Finder."
                if ok_f
                else f"Failed: {err_f[:280]}. Enable Automation for Finder (Terminal/Cursor).",
            }
        )
        ok_se, err_se = _probe_system_events_accessibility()
        if ok_se:
            checks.append(
                {
                    "id": "system_events",
                    "label": "System Events (Accessibility/Automation)",
                    "status": "ok",
                    "detail": "osascript can query System Events.",
                }
            )
        else:
            checks.append(
                {
                    "id": "system_events",
                    "label": "System Events (Accessibility/Automation)",
                    "status": "warn",
                    "detail": (
                        f"Limited: {(err_se or 'unknown')[:280]}. "
                        "If file tools still work, ignore. Otherwise enable Accessibility for Terminal/Cursor "
                        "and Automation for System Events if prompted."
                    ),
                }
            )
    else:
        checks.append(
            {
                "id": "osascript",
                "label": "osascript",
                "status": "error",
                "detail": "`/usr/bin/osascript` not found — install Xcode CLI tools / macOS developer extras.",
            }
        )

    open_bin = "/usr/bin/open" if Path("/usr/bin/open").is_file() else shutil.which("open")
    checks.append(
        {
            "id": "open_cli",
            "label": "open CLI",
            "status": "ok" if open_bin else "error",
            "detail": f"Using `{open_bin}`." if open_bin else "No `open` binary — cannot launch apps/files natively.",
        }
    )

    try:
        from app.voice.file_actions import should_delegate_file_actions_to_client

        if should_delegate_file_actions_to_client():
            checks.append(
                {
                    "id": "file_actions_mode",
                    "label": "Native file open (`open`)",
                    "status": "warn",
                    "detail": "Delegation/bridge mode: opens may route through the browser bridge. Set JARVIS_FILE_ACTIONS_MODE=server on bare macOS for direct open.",
                }
            )
        else:
            checks.append(
                {
                    "id": "file_actions_mode",
                    "label": "Native file open (`open`)",
                    "status": "ok",
                    "detail": "Server-side native `open` enabled for this host.",
                }
            )
    except Exception:
        pass

    checks.append(
        {
            "id": "microphone",
            "label": "Microphone",
            "status": "info",
            "detail": "Grant in the browser for the HUD (localhost). For `./jarvis`, grant Terminal under Privacy → Microphone.",
        }
    )

    return checks


def _permissions_complete(checks: list[dict[str, Any]]) -> bool:
    for c in checks:
        if c.get("status") == "error":
            return False
    return True


def probe_macos_environment() -> dict[str, Any]:
    """Runtime probe + static checklist for HUD and /health/macos."""
    checks = _compile_permission_checks()
    warnings: list[str] = []
    for c in checks:
        if c.get("status") == "error":
            warnings.append(f"{c.get('label')}: {c.get('detail')}")
        elif c.get("status") == "warn":
            warnings.append(f"{c.get('label')}: {c.get('detail')}")

    out: dict[str, Any] = {
        "platform": platform.system(),
        "in_docker": settings.running_in_docker,
        "native_macos_backend": platform.system() == "Darwin" and not settings.running_in_docker,
        "home": str(Path.home().resolve()) if platform.system() == "Darwin" else None,
        "host_python_executable": sys.executable,
        "file_actions_native": True,
        "permission_checks": checks,
        "permissions_complete": _permissions_complete(checks),
        "warnings": warnings,
        "setup_sections": MACOS_SETUP_SECTIONS,
        "setup": [
            s["title"] + ": see checklist in HUD (expand ‘Full macOS setup guide’)."
            for s in MACOS_SETUP_SECTIONS
        ],
        "relaunch_hint": "After changing Full Disk Access or Accessibility, fully quit Terminal/Cursor (Cmd+Q) and start uvicorn again.",
        "permissions": {},
    }

    if platform.system() != "Darwin":
        out["setup"] = ["See README for non-macOS limitations."]
        return out
    if settings.running_in_docker:
        out["file_actions_native"] = False
        return out

    try:
        from app.voice.file_actions import should_delegate_file_actions_to_client

        out["file_actions_native"] = not should_delegate_file_actions_to_client()
    except Exception:
        pass

    for c in checks:
        cid = str(c.get("id", ""))
        if cid:
            st = c.get("status")
            out["permissions"][cid] = {
                "status": st,
                "ok": st == "ok",
                "detail": c.get("detail"),
            }

    return out
