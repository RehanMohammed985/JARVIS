#!/usr/bin/env python3
"""Run the macOS file bridge, FastAPI backend, and Next.js HUD together (one command)."""

from __future__ import annotations

import os
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PROCS = []


def stop_all() -> None:
    for p in PROCS:
        if p.poll() is None:
            p.terminate()
    for p in PROCS:
        try:
            p.wait(timeout=8)
        except subprocess.TimeoutExpired:
            p.kill()


def main() -> None:
    def on_signal(_sig: int, _frame: object) -> None:
        stop_all()
        sys.exit(128)

    signal.signal(signal.SIGINT, on_signal)
    signal.signal(signal.SIGTERM, on_signal)

    env = os.environ.copy()

    if sys.platform == "darwin":
        PROCS.append(
            subprocess.Popen(
                [sys.executable, str(ROOT / "scripts" / "jarvis_file_bridge.py")],
                cwd=ROOT,
                env=env,
            ),
        )

    py = shutil.which("python3") or sys.executable
    PROCS.append(
        subprocess.Popen(
            [
                py,
                "-m",
                "uvicorn",
                "app.main:app",
                "--reload",
                "--host",
                "127.0.0.1",
                "--port",
                "8000",
            ],
            cwd=ROOT / "backend",
            env=env,
        ),
    )

    npm = shutil.which("npm")
    if npm:
        PROCS.append(
            subprocess.Popen(
                [npm, "run", "dev"],
                cwd=ROOT / "frontend",
                env=env,
            ),
        )
    else:
        print("npm not in PATH; start the HUD with: cd frontend && npm run dev", file=sys.stderr)

    try:
        while True:
            for p in PROCS:
                if p.poll() is not None:
                    stop_all()
                    sys.exit(p.returncode or 0)
            time.sleep(0.25)
    finally:
        stop_all()


if __name__ == "__main__":
    main()
