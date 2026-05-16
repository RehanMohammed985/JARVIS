#!/usr/bin/env python3
"""
Voice-first entrypoint: listen for the wake phrase, ensure backend + HUD are up,
then open the browser (with optional ?vq=… so the first spoken command runs automatically).

Requires: backend venv with faster-whisper + sounddevice (see backend/requirements.txt).
macOS: microphone permission for the terminal / Python binary.
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Sequence
from urllib.parse import quote

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[1]
BACKEND_DIR = REPO_ROOT / "backend"
FRONTEND_DIR = REPO_ROOT / "frontend"
VENV_PY = BACKEND_DIR / ".venv" / "bin" / "python"


def port_open(port: int, host: str = "127.0.0.1") -> bool:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.settimeout(0.35)
        return s.connect_ex((host, port)) == 0
    finally:
        s.close()


def http_ok(url: str, timeout: float = 2.0) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            return 200 <= r.status < 300
    except (urllib.error.URLError, TimeoutError, OSError):
        return False


def wait_url(url: str, timeout: float = 90.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if http_ok(url):
            return True
        time.sleep(0.45)
    return False


def strip_wake(text: str, wake: str) -> str:
    return re.sub(rf"\b{re.escape(wake)}\b", "", text, flags=re.I).strip()


def detect_wake(text: str, wake: str) -> bool:
    return bool(re.search(rf"\b{re.escape(wake)}\b", text.lower()))


def open_hud(base: str, query: str | None) -> None:
    if query:
        url = f"{base.rstrip('/')}/?vq={quote(query, safe='')}"
    else:
        url = f"{base.rstrip('/')}/"
    system = sys.platform
    if system == "darwin":
        subprocess.run(["open", url], check=False)
    elif system == "win32":
        subprocess.run(["cmd", "/c", "start", "", url], check=False)
    else:
        subprocess.run(["xdg-open", url], check=False)
    print(f"Opened HUD: {url}", flush=True)


def spawn_backend(host: str, port: int) -> subprocess.Popen[bytes]:
    if not VENV_PY.is_file():
        print("Missing backend/.venv — run: cd backend && python3 -m venv .venv && pip install -r requirements.txt", flush=True)
        sys.exit(1)
    cmd: Sequence[str] = (
        str(VENV_PY),
        "-m",
        "uvicorn",
        "app.main:app",
        "--host",
        host,
        "--port",
        str(port),
    )
    return subprocess.Popen(
        cmd,
        cwd=str(BACKEND_DIR),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )


def spawn_frontend(dev: bool, port: int) -> subprocess.Popen[bytes]:
    env = os.environ.copy()
    env["PORT"] = str(port)
    env["CHOKIDAR_USEPOLLING"] = "true"
    env["WATCHPACK_POLLING"] = "true"
    if dev:
        cmd = ["npm", "run", "dev", "--", "-p", str(port)]
    else:
        if not (FRONTEND_DIR / ".next").is_dir():
            print("Building Next.js (first run may take a minute)…", flush=True)
            subprocess.run(["npm", "run", "build"], cwd=str(FRONTEND_DIR), check=True)
        cmd = ["npm", "run", "start", "--", "-p", str(port)]
    return subprocess.Popen(
        cmd,
        cwd=str(FRONTEND_DIR),
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )


def ensure_stack(
    *,
    api_host: str,
    api_port: int,
    ui_port: int,
    frontend_dev: bool,
) -> tuple[str, str]:
    api = f"http://{api_host}:{api_port}"
    ui = f"http://127.0.0.1:{ui_port}"

    if not port_open(api_port, api_host):
        print("Starting backend…", flush=True)
        spawn_backend(api_host, api_port)
    if not wait_url(f"{api}/health"):
        print("Backend did not become ready — check Ollama and backend logs.", flush=True)
        sys.exit(1)

    if not port_open(ui_port):
        if shutil.which("npm") is None:
            print("npm not found; install Node.js to run the HUD.", flush=True)
            sys.exit(1)
        mode = "dev" if frontend_dev else "production"
        print(f"Starting frontend ({mode})…", flush=True)
        spawn_frontend(frontend_dev, ui_port)
    if not wait_url(ui):
        print("Frontend did not become ready — try: cd frontend && npm install", flush=True)
        sys.exit(1)

    return api, ui


def record_utterance(
    *,
    samplerate: int,
    rms_thresh: float,
    max_seconds: float,
) -> np.ndarray:
    import sounddevice as sd

    block = int(0.1 * samplerate)
    silent_chunks = 0
    speech_chunks = 0
    active = False
    buf: list[np.ndarray] = []
    max_blocks = int(max_seconds / 0.1) + 2

    while True:
        block_audio = sd.rec(
            block,
            samplerate=samplerate,
            channels=1,
            dtype="float32",
            blocking=True,
        ).reshape(-1)
        rms = float(np.sqrt(np.mean(np.square(block_audio))))
        if not active:
            if rms > rms_thresh:
                speech_chunks += 1
                if speech_chunks >= 2:
                    active = True
                    buf = [block_audio]
                    silent_chunks = 0
            else:
                speech_chunks = 0
        else:
            buf.append(block_audio)
            if rms < rms_thresh * 0.75:
                silent_chunks += 1
                if silent_chunks >= 7:
                    break
            else:
                silent_chunks = 0
            if len(buf) >= max_blocks:
                break

    if not buf:
        return np.array([], dtype=np.float32)
    return np.concatenate(buf, axis=0)


def transcribe_audio(
    model: object,
    audio: np.ndarray,
) -> str:
    if audio.size == 0:
        return ""
    segments, _ = model.transcribe(
        audio.astype(np.float32),
        language="en",
        vad_filter=True,
    )
    parts = [s.text.strip() for s in segments]
    return " ".join(parts).strip()


def main() -> None:
    ap = argparse.ArgumentParser(description="Jarvis voice launcher")
    ap.add_argument("--wake", default="jarvis", help="Wake word / phrase")
    ap.add_argument("--api-host", default="127.0.0.1")
    ap.add_argument("--api-port", type=int, default=8000)
    ap.add_argument("--ui-port", type=int, default=3000)
    ap.add_argument(
        "--frontend-prod",
        action="store_true",
        help="Use next start (after build) instead of dev server — fewer file watchers",
    )
    ap.add_argument("--whisper-model", default="tiny", help="faster-whisper size for wake loop")
    ap.add_argument("--rms", type=float, default=0.014, help="Voice activity RMS threshold")
    ap.add_argument("--max-utterance-sec", type=float, default=7.0)
    ap.add_argument(
        "--skip-servers",
        action="store_true",
        help="Do not spawn backend/frontend (assume already running)",
    )
    ap.add_argument(
        "--open-only",
        action="store_true",
        help="Open the HUD once then exit (no microphone loop)",
    )
    args = ap.parse_args()

    ui_base = f"http://127.0.0.1:{args.ui_port}"
    if args.open_only:
        if not args.skip_servers:
            ensure_stack(
                api_host=args.api_host,
                api_port=args.api_port,
                ui_port=args.ui_port,
                frontend_dev=not args.frontend_prod,
            )
        open_hud(ui_base, None)
        return

    if not args.skip_servers:
        ensure_stack(
            api_host=args.api_host,
            api_port=args.api_port,
            ui_port=args.ui_port,
            frontend_dev=not args.frontend_prod,
        )

    print(
        f"Listening for “{args.wake}”… (speak in the same sentence to send a command, e.g. "
        f'"{args.wake} what time is it")',
        flush=True,
    )

    from faster_whisper import WhisperModel

    model = WhisperModel(args.whisper_model, device="auto")

    while True:
        try:
            audio = record_utterance(
                samplerate=16000,
                rms_thresh=args.rms,
                max_seconds=args.max_utterance_sec,
            )
            text = transcribe_audio(model, audio)
            if not text:
                continue
            print(f"Heard: {text!r}", flush=True)
            if not detect_wake(text, args.wake):
                continue
            follow = strip_wake(text, args.wake) or None
            open_hud(ui_base, follow)
        except KeyboardInterrupt:
            print("\nStopped.", flush=True)
            break


if __name__ == "__main__":
    main()
