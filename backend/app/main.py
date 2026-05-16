from __future__ import annotations

import asyncio
import base64
import json
import logging
import platform
import queue
import sys
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.macos_integration import probe_macos_environment
from app.schemas import WSClientMessage, WSServerMessage
from app.voice.pipeline import VoiceSession

log = logging.getLogger(__name__)

WORK_ROOT = Path("./data/sessions")


@asynccontextmanager
async def lifespan(app: FastAPI):
    if settings.running_in_docker:
        log.warning(
            "Jarvis API is running inside Docker: filesystem and Finder tools operate on the "
            "container environment, not your Mac desktop. For real macOS Finder, Spotlight, "
            "AppleScript, and `open`, run uvicorn natively on macOS (see README and "
            "scripts/run_backend_native_macos.sh)."
        )
    elif platform.system() != "Darwin":
        log.info(
            "Non-macOS host: Finder- and AppleScript-specific behaviour uses fallbacks or "
            "client delegation where configured."
        )
    else:
        log.info("Jarvis host Python: %s", sys.executable)
        snap = probe_macos_environment()
        if snap.get("permissions_complete"):
            log.info("macOS permission probe: no blocking errors reported.")
        else:
            for row in snap.get("permission_checks") or []:
                label = row.get("label")
                detail = row.get("detail")
                if row.get("status") == "error":
                    log.warning("macOS permission — %s: %s", label, detail)
                elif row.get("status") == "warn":
                    log.info("macOS permission (review) — %s: %s", label, detail)
        if snap.get("warnings"):
            log.info("See HUD macOS panel or GET /health/macos for full checklist.")
    yield


app = FastAPI(title=settings.app_name, lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

SESSIONS: dict[str, VoiceSession] = {}


@app.get("/health")
def health() -> dict:
    on_macos_host = platform.system() == "Darwin" and not settings.running_in_docker
    return {
        "status": "ok",
        "ollama_base": settings.ollama_base_url,
        "model": settings.ollama_model,
        "runtime": {
            "platform": platform.system(),
            "in_docker": settings.running_in_docker,
            "filesystem_tools_expect_host_macos": on_macos_host,
            "note": (
                "Finder / native open / Spotlight require the API on macOS outside Docker; "
                "see README if filesystem tools mis-target the wrong machine."
                if not on_macos_host
                else "Backend on macOS host — file tools use this Mac."
            ),
        },
    }


@app.get("/health/macos")
def health_macos() -> dict:
    """Best-effort macOS host / TCC hints for the HUD."""
    return probe_macos_environment()


async def _handle_turn_with_live_stream(
    ws: WebSocket,
    sess: VoiceSession,
    text: str,
    *,
    require_wake: bool,
) -> None:
    """Run sync turn on a worker thread while draining live HUD events to the socket."""
    q: queue.SimpleQueue = queue.SimpleQueue()
    sess.set_realtime_sink(q)
    loop = asyncio.get_running_loop()
    fut = loop.run_in_executor(
        None,
        lambda: sess.handle_user_text_sync(text, require_wake=require_wake),
    )
    msgs: list[WSServerMessage] = []
    try:
        while True:
            while True:
                try:
                    await ws.send_json(q.get_nowait())
                except queue.Empty:
                    break
            if fut.done():
                while True:
                    try:
                        await ws.send_json(q.get_nowait())
                    except queue.Empty:
                        break
                msgs = await fut
                break
            await asyncio.sleep(0.002)
    finally:
        sess.set_realtime_sink(None)
    for m in msgs:
        await ws.send_json(m.model_dump(mode="json"))


@app.websocket("/ws/session")
async def ws_session(ws: WebSocket) -> None:
    await ws.accept()
    sid = str(uuid.uuid4())
    sess = VoiceSession(sid, WORK_ROOT / sid)
    SESSIONS[sid] = sess
    await ws.send_json(
        WSServerMessage(
            type="session",
            payload={"session_id": sid, "macos": probe_macos_environment()},
        ).model_dump(mode="json"),
    )
    wake_mode = "always_on"

    async def send_all(msgs: list[WSServerMessage]) -> None:
        for m in msgs:
            await ws.send_json(m.model_dump())

    try:
        while True:
            try:
                raw = await ws.receive_json()
            except json.JSONDecodeError as e:
                await ws.send_json(
                    WSServerMessage(
                        type="error",
                        payload={"detail": f"Invalid JSON: {e}"},
                    ).model_dump(),
                )
                continue
            try:
                msg = WSClientMessage.model_validate(raw)
            except Exception as e:
                await ws.send_json(
                    WSServerMessage(
                        type="error",
                        payload={"detail": f"Bad message: {e}"},
                    ).model_dump(),
                )
                continue

            if msg.type == "ping":
                await ws.send_json(WSServerMessage(type="pong", payload={}).model_dump())
            elif msg.type == "config":
                wake_mode = str(msg.payload.get("wake_mode", wake_mode))
                await ws.send_json(
                    WSServerMessage(
                        type="session",
                        payload={
                            "session_id": sid,
                            "wake_mode": wake_mode,
                            "macos": probe_macos_environment(),
                        },
                    ).model_dump(mode="json"),
                )
            elif msg.type == "user_text":
                text = str(msg.payload.get("text", ""))
                req_wake = wake_mode == "wake_word"
                try:
                    await _handle_turn_with_live_stream(
                        ws, sess, text, require_wake=req_wake
                    )
                except Exception as e:
                    log.exception("handle_user_text failed")
                    await ws.send_json(
                        WSServerMessage(
                            type="error",
                            payload={"detail": str(e)},
                        ).model_dump(mode="json"),
                    )
            elif msg.type == "audio_chunk":
                b64 = str(msg.payload.get("base64", ""))
                sr = int(msg.payload.get("sample_rate", 16000))
                pcm = base64.b64decode(b64)
                pre, text = await sess.transcribe_pcm(pcm, sr)
                await send_all(pre)
                if not text.strip():
                    continue
                req_wake = wake_mode == "wake_word"
                try:
                    await _handle_turn_with_live_stream(
                        ws, sess, text, require_wake=req_wake
                    )
                except Exception as e:
                    log.exception("handle_user_audio turn failed")
                    await ws.send_json(
                        WSServerMessage(
                            type="error",
                            payload={"detail": str(e)},
                        ).model_dump(mode="json"),
                    )
            elif msg.type == "ptt_start":
                await ws.send_json(
                    WSServerMessage(type="state", payload={"phase": "listening"}).model_dump(),
                )
            elif msg.type == "ptt_end":
                await ws.send_json(
                    WSServerMessage(type="state", payload={"phase": "idle"}).model_dump(),
                )
            else:
                await ws.send_json(
                    WSServerMessage(
                        type="error",
                        payload={"detail": f"Unsupported message type: {msg.type}"},
                    ).model_dump(),
                )
    except WebSocketDisconnect:
        SESSIONS.pop(sid, None)
