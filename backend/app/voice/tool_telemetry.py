from __future__ import annotations

from typing import Any

from app.voice.session_context import current_voice_session


def record_tool_activity(name: str, args: object = None) -> None:
    """Called from tools while a voice session is handling a turn (ContextVar-bound)."""
    sess = current_voice_session.get()
    if sess is None:
        return
    fn = getattr(sess, "record_tool_activity", None)
    if callable(fn):
        fn(name, args)


def merge_tool_event_lists(*lists: list[list[dict[str, Any]]]) -> list[dict[str, Any]]:
    """Merge provider + execution telemetry; keep one row per tool name with richest args."""
    order: list[str] = []
    best: dict[str, dict[str, Any]] = {}
    for lst in lists:
        for ev in lst:
            name = str(ev.get("name") or "tool")
            raw = ev.get("args")
            args = dict(raw) if isinstance(raw, dict) else {}
            if name not in best:
                order.append(name)
                best[name] = {"name": name, "args": args}
                continue
            if len(args) > len(best[name]["args"]):
                best[name] = {"name": name, "args": args}
    return [best[k] for k in order if k in best]
