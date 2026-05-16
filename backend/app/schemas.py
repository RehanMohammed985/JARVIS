from typing import Any, Literal

from pydantic import BaseModel, Field


class WSClientMessage(BaseModel):
    type: Literal[
        "ping",
        "user_text",
        "ptt_start",
        "ptt_end",
        "audio_chunk",
        "config",
    ]
    payload: dict[str, Any] = Field(default_factory=dict)


class WSServerMessage(BaseModel):
    type: Literal[
        "pong",
        "session",
        "transcript",
        "assistant_delta",
        "assistant_final",
        "speech_audio",
        "state",
        "thinking_hint",
        "tool_event",
        "local_file_action",
        "finder_search_progress",
        "finder_match_list",
        "finder_open_status",
        "filesystem_activity",
        "jarvis_trace",
        "mic_control",
        "metrics",
        "error",
    ]
    payload: dict[str, Any] = Field(default_factory=dict)


class SessionState(BaseModel):
    """Orb / pipeline state for UI sync."""

    phase: Literal["idle", "listening", "thinking", "speaking", "tool_running"] = "idle"
    wake_mode: Literal["push_to_talk", "wake_word", "always_on"] = "push_to_talk"
    transcript_partial: str | None = None
    tool_name: str | None = None
