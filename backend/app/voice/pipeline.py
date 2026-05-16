from __future__ import annotations

import asyncio
import base64
import queue
import re
from pathlib import Path
from typing import Any, Literal, cast

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage

from app.agent.direct_file_open import try_cached_finder_pick, try_direct_find_and_open
from app.agent.graph import run_voice_turn
from app.agent.mic_control import (
    strip_stop_mic_token,
    user_requested_mic_dismiss,
    user_said_goodbye,
)
from app.agent.quick_replies import try_quick_reply
from app.agent.tool_router import should_use_tools
from app.config import settings
from app.schemas import SessionState, WSServerMessage
from app.voice.session_context import current_voice_session
from app.voice.stt import get_stt
from app.voice.tool_telemetry import merge_tool_event_lists
from app.voice.tts import get_tts

OrbPhase = Literal["idle", "listening", "thinking", "speaking", "tool_running"]


def _summarize_tool_event(name: str, args: object) -> str:
    a = args if isinstance(args, dict) else {}
    if name == "search_files_by_keyword":
        return f'Search · “{a.get("keyword", "")}”'
    if name == "find_files":
        return f'Glob · {a.get("pattern", "")}'
    if name == "find_and_open_file":
        mode = "Finder" if a.get("show_in_finder") else "Open"
        frag = str(a.get("name_fragment", "") or "")
        return f"{mode} · search “{frag}”"
    if name == "open_path":
        reveal = a.get("reveal_in_finder")
        tag = "Finder" if reveal else "Open"
        return f"{tag} · {a.get('path', '')}"
    if name == "show_in_finder":
        return f'Finder · {a.get("path", "")}'
    if name == "list_directory":
        return f'List · {a.get("path", ".")}'
    if name == "read_file":
        return f'Read · {a.get("path", "")}'
    if name == "write_file":
        return f'Write · {a.get("path", "")}'
    if name == "filesystem_overview":
        return "Filesystem overview"
    if name == "run_terminal":
        cmd = str(a.get("command", "")).strip()
        tail = "…" if len(cmd) > 120 else ""
        return f"Shell · {cmd[:120]}{tail}"
    if name == "voice_set_listening":
        return "Mic · listening update"
    if name == "mac_finder_search":
        return f'Mac Finder search · “{a.get("keyword", "")}”'
    if name == "mac_finder_open_selection":
        sel = str(a.get("selection_text", "") or "")[:56]
        return f"Mac Finder open · {sel}{'…' if len(str(a.get('selection_text', ''))) > 56 else ''}"
    if name == "create_folder_for_user":
        return f'Create folder · “{a.get("folder_name", "")}” in {a.get("location", "")}'
    if name == "move_path":
        return f'Move · {a.get("source", "")} → {a.get("destination", "")}'
    if name == "copy_path":
        return f'Copy · {a.get("source", "")} → {a.get("destination", "")}'
    if name == "rename_in_place":
        return f'Rename · {a.get("path", "")} → {a.get("new_name", "")}'
    if name == "open_latest_pdf":
        return "Open · latest PDF"
    if name == "open_workspace_in_cursor":
        return f'Cursor · {a.get("path", "")}'
    if name == "open_named_repo_in_cursor":
        return f'Cursor · repo “{a.get("folder_name_fragment", "")}”'
    if name == "create_markdown_in_documents":
        return f'Markdown · Documents/{a.get("filename", "")}'
    return name.replace("_", " ") + (" · running" if not a else "")


def strip_wake(text: str, wake: str | None = None) -> str:
    wake_l = (wake or settings.wake_word).lower()
    w = re.escape(wake_l)
    stripped = re.sub(rf"(?i)\b{w}\b", "", text)
    return stripped.strip()


def detect_wake(text: str, wake: str | None = None) -> bool:
    w = (wake or settings.wake_word).lower()
    return bool(re.search(rf"\b{re.escape(w)}\b", text.lower()))


class VoiceSession:
    def __init__(self, session_id: str, workdir: Path) -> None:
        self.session_id = session_id
        self.workdir = workdir
        self.workdir.mkdir(parents=True, exist_ok=True)
        self.state = SessionState()
        self.history: list[BaseMessage] = []
        self.desired_mic_listening: bool = True
        self.tool_activity: list[dict[str, Any]] = []
        self.pending_local_file_actions: list[dict[str, str]] = []
        self.pending_finder_events: list[dict[str, Any]] = []
        self.finder_match_cache: list[dict[str, Any]] = []
        self._realtime_out: queue.SimpleQueue | None = None

    def set_realtime_sink(self, sink: queue.SimpleQueue | None) -> None:
        self._realtime_out = sink

    def _streaming(self) -> bool:
        return self._realtime_out is not None

    def emit_live(self, typ: str, payload: dict[str, Any]) -> None:
        qobj = self._realtime_out
        if qobj is None:
            return
        try:
            qobj.put_nowait(
                cast(
                    Any,
                    WSServerMessage(type=typ, payload=payload).model_dump(mode="json"),
                ),
            )
        except Exception:
            return

    def record_tool_activity(self, name: str, args: object = None) -> None:
        payload: dict[str, Any] = args if isinstance(args, dict) else {}
        self.tool_activity.append({"name": name, "args": dict(payload)})
        if self._streaming():
            nm = name
            args_d = dict(payload)
            self.emit_live(
                "tool_event",
                {
                    "name": nm,
                    "args": args_d,
                    "summary": _summarize_tool_event(nm, args_d),
                },
            )
            self.emit_live(
                "jarvis_trace",
                {
                    "stage": "tool",
                    "name": nm,
                    "summary": _summarize_tool_event(nm, args_d),
                },
            )

    def enqueue_local_file_action(self, action: str, path: str) -> None:
        if self._streaming():
            self.emit_live("local_file_action", {"action": action, "path": path})
            return
        self.pending_local_file_actions.append({"action": action, "path": path})

    def enqueue_finder_event(self, ws_type: str, payload: dict[str, Any]) -> None:
        pay = dict(payload)
        if self._streaming():
            self.emit_live(ws_type, pay)
            return
        self.pending_finder_events.append({"ws_type": ws_type, "payload": pay})

    def set_finder_match_cache(self, rows: list[dict[str, Any]]) -> None:
        self.finder_match_cache = [dict(r) for r in rows]

    def get_finder_match_cache(self) -> list[dict[str, Any]]:
        return [dict(r) for r in self.finder_match_cache]

    def set_phase(self, phase: OrbPhase) -> WSServerMessage:
        self.state.phase = phase
        return WSServerMessage(type="state", payload={"phase": phase})

    def _append_state(self, out: list[WSServerMessage], phase: OrbPhase) -> None:
        self.state.phase = phase
        if self._streaming():
            self.emit_live("state", {"phase": phase})
        else:
            out.append(WSServerMessage(type="state", payload={"phase": phase}))

    def _append_hint(self, out: list[WSServerMessage], text: str) -> None:
        if self._streaming():
            self.emit_live("thinking_hint", {"text": text})
        else:
            out.append(
                WSServerMessage(
                    type="thinking_hint",
                    payload={"text": text},
                ),
            )

    async def transcribe_pcm(self, pcm: bytes, sample_rate: int) -> tuple[list[WSServerMessage], str]:
        out: list[WSServerMessage] = []
        self.state.phase = "listening"
        out.append(WSServerMessage(type="state", payload={"phase": "listening"}))
        try:
            text = get_stt().transcribe_pcm16_mono(pcm, sample_rate)
        except Exception as e:
            out.append(WSServerMessage(type="error", payload={"detail": f"stt:{e}"}))
            self.state.phase = "idle"
            out.append(WSServerMessage(type="state", payload={"phase": "idle"}))
            return out, ""
        out.append(
            WSServerMessage(
                type="transcript",
                payload={"text": text, "final": True},
            ),
        )
        if not text.strip():
            self.state.phase = "idle"
            out.append(WSServerMessage(type="state", payload={"phase": "idle"}))
        return out, text

    def handle_user_text_sync(
        self,
        text: str,
        prefix_out: list[WSServerMessage] | None = None,
        *,
        require_wake: bool = False,
    ) -> list[WSServerMessage]:
        """Synchronous turn handler. When ``set_realtime_sink`` is active, filesystem/tool HUD feeds stream immediately."""
        out = list(prefix_out or [])
        stripped = (text or "").strip()
        if not stripped:
            out.append(
                WSServerMessage(
                    type="error",
                    payload={"detail": "Empty message — use Speak or keyboard fallback."},
                ),
            )
            self._append_state(out, "idle")
            return out

        if require_wake and not detect_wake(stripped):
            out.append(
                WSServerMessage(
                    type="error",
                    payload={
                        "detail": (
                            f'Wake word mode is on: start with "{settings.wake_word}" '
                            "(e.g. \"jarvis what time is it\") or switch input mode to "
                            '"Always on (text)" / "Push to talk".'
                        ),
                    },
                ),
            )
            self._append_state(out, "idle")
            return out

        user_text = strip_wake(stripped) if require_wake else stripped
        if not user_text.strip():
            user_text = stripped

        self._append_state(out, "thinking")
        if self._streaming():
            self.emit_live(
                "jarvis_trace",
                {"stage": "turn", "summary": "Reasoning and tools…"},
            )
        tok = current_voice_session.set(self)
        try:
            self.desired_mic_listening = True
            stop_mic = False
            tool_events: list[dict[str, Any]] = []
            self.tool_activity.clear()
            self.pending_local_file_actions.clear()
            self.pending_finder_events.clear()

            qr = try_quick_reply(user_text)
            if qr:
                full = qr
                self.history = (
                    self.history
                    + [
                        HumanMessage(content=user_text),
                        AIMessage(content=full),
                    ]
                )[-48:]
            elif user_said_goodbye(user_text):
                full = "Goodbye, sir. Until next time."
                self.history = (
                    self.history
                    + [
                        HumanMessage(content=user_text),
                        AIMessage(content=full),
                    ]
                )[-48:]
                stop_mic = True
            elif user_requested_mic_dismiss(user_text):
                full = "Very good — I'll stand by until you call for me."
                self.history = (
                    self.history
                    + [
                        HumanMessage(content=user_text),
                        AIMessage(content=full),
                    ]
                )[-48:]
                stop_mic = True
            elif (pick := try_cached_finder_pick(user_text)) is not None:
                full = pick
                self.history = (
                    self.history
                    + [
                        HumanMessage(content=user_text),
                        AIMessage(content=full),
                    ]
                )[-48:]
                tool_events = merge_tool_event_lists([], self.tool_activity)
            elif (direct := try_direct_find_and_open(user_text)) is not None:
                self._append_hint(
                    out,
                    "Scanning your computer for that file — watch System activity.",
                )
                full = direct
                self.history = (
                    self.history
                    + [
                        HumanMessage(content=user_text),
                        AIMessage(content=full),
                    ]
                )[-48:]
                tool_events = merge_tool_event_lists([], self.tool_activity)
            else:
                if should_use_tools(user_text):
                    self._append_hint(
                        out,
                        "Searching and using your files — follow steps in System activity.",
                    )
                plan_out: list[dict[str, Any]]
                full, self.history, stop_from_turn, plan_out = run_voice_turn(
                    user_text,
                    self.history,
                )
                self.history = self.history[-48:]
                full, token_stop = strip_stop_mic_token(full)
                stop_mic = (
                    stop_from_turn or token_stop or not self.desired_mic_listening
                )
                tool_events = merge_tool_event_lists(plan_out, self.tool_activity)

            if not self._streaming():
                for fe in self.pending_finder_events:
                    wt = str(fe.get("ws_type") or "")
                    if wt:
                        out.append(
                            WSServerMessage(
                                type=wt,  # type: ignore[arg-type]
                                payload=dict(fe.get("payload") or {}),
                            ),
                        )
                self.pending_finder_events.clear()

                for ev in tool_events:
                    nm = str(ev.get("name") or "tool")
                    args = ev.get("args") or {}
                    out.append(
                        WSServerMessage(
                            type="tool_event",
                            payload={
                                "name": nm,
                                "args": args,
                                "summary": _summarize_tool_event(nm, args),
                            },
                        ),
                    )

                for act in self.pending_local_file_actions:
                    out.append(
                        WSServerMessage(type="local_file_action", payload=dict(act)),
                    )
                self.pending_local_file_actions.clear()
            else:
                self.pending_finder_events.clear()
                self.pending_local_file_actions.clear()

            if not full.strip():
                out.append(
                    WSServerMessage(
                        type="error",
                        payload={
                            "detail": (
                                "The model returned an empty reply. Check that Ollama is "
                                f'running and `{settings.ollama_model}` is installed '
                                "(run `ollama pull ...`)."
                            ),
                        },
                    ),
                )
                self._append_state(out, "idle")
                return out

            use_client_tts = settings.voice_client_tts
            af_payload = {"text": full, "browser_tts": use_client_tts}
            if self._streaming():
                self.emit_live("assistant_final", af_payload)
            else:
                out.append(
                    WSServerMessage(
                        type="assistant_final",
                        payload=af_payload,
                    ),
                )
            if stop_mic:
                mc_payload = {"listen": False}
                if self._streaming():
                    self.emit_live("mic_control", mc_payload)
                else:
                    out.append(
                        WSServerMessage(
                            type="mic_control",
                            payload=mc_payload,
                        ),
                    )
        except Exception as e:
            out.append(
                WSServerMessage(
                    type="error",
                    payload={"detail": f"Agent error: {e}"},
                ),
            )
            self._append_state(out, "idle")
            return out
        finally:
            current_voice_session.reset(tok)

        self._append_state(out, "speaking")
        if not settings.voice_client_tts:
            wav_path = self.workdir / f"reply-{self.session_id}.wav"
            repo_root = Path(__file__).resolve().parents[3]
            ref = repo_root / "assets" / "jarvis_reference.wav"
            try:
                final_wav = get_tts().synth(
                    full,
                    wav_path,
                    reference_wav=ref if ref.is_file() else None,
                )
                data = final_wav.read_bytes() if final_wav.is_file() else b""
                if data:
                    sa_payload = {
                        "format": "wav",
                        "base64": base64.b64encode(data).decode("ascii"),
                    }
                    if self._streaming():
                        self.emit_live("speech_audio", sa_payload)
                    else:
                        out.append(
                            WSServerMessage(
                                type="speech_audio",
                                payload=sa_payload,
                            ),
                        )
            except Exception as e:
                err = WSServerMessage(type="error", payload={"detail": f"tts:{e}"})
                if self._streaming():
                    self.emit_live("error", dict(err.payload))
                else:
                    out.append(err)

        self._append_state(out, "idle")
        if self._streaming():
            self.emit_live(
                "jarvis_trace",
                {"stage": "done", "summary": "Turn complete"},
            )
        return out

    async def handle_user_text(
        self,
        text: str,
        prefix_out: list[WSServerMessage] | None = None,
        *,
        require_wake: bool = False,
    ) -> list[WSServerMessage]:
        """Non-streaming path: runs the sync handler on a thread so the event loop stays responsive."""
        return await asyncio.to_thread(
            self.handle_user_text_sync,
            text,
            prefix_out,
            require_wake=require_wake,
        )
