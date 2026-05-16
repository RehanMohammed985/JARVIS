from __future__ import annotations

import json
import re
from typing import Any, Iterable

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_ollama import ChatOllama
from langgraph.prebuilt import create_react_agent

from app.agent.mic_control import strip_stop_mic_token
from app.agent.tool_router import should_use_tools
from app.config import settings
from app.memory.store import get_memory_store
from app.tools.builtin import all_tools
from app.voice.tool_telemetry import merge_tool_event_lists

SYSTEM_PROMPT = """You are Jarvis: a calm, precise British digital majordomo.
Rules:
- Listen to the user's actual request and answer it directly. One clear reply.
- NEVER invent, guess, or assume file names, paths, or that something opened unless a tool in THIS
  turn returned those exact facts. If no tool listed a path, say you did not find a match yet and
  offer to search again — do not name imaginary files.
- For greetings, small talk, explanations, or general questions: reply WITHOUT using tools.
- For "is there a … on my computer", "find resume", "does X exist", or any request to locate a file
  by name: you MUST call search_files_by_keyword (or find_files with a glob) in the same turn —
  do not claim you searched without calling the tool.
- When the user wants to open, show, or launch a file or folder by **name or fragment only**
  (e.g. "open resume", "open something on my desktop", no full path): call **find_and_open_file**
  with that name fragment first. If they gave a **full path**, use **open_path** (or **show_in_finder**).
  After search, you may call open_path with the absolute path from results. Do not say you opened
  without calling the appropriate tool.
- If they want the item **in Finder** (show/reveal/select/open in Finder, “pop it up in Finder”,
  “I want to see it in Finder”) on macOS: call **show_in_finder** with the full path — that selects
  the file in a Finder window. Use open_path with reveal_in_finder=true only if you prefer; show_in_finder
  is clearer for Finder-only requests. Use open_path with reveal_in_finder=false to open the file
  with its default application (e.g. double-click behaviour).
- Use **mac_finder_search** then **mac_finder_open_selection** when the user wants the guided
  Finder flow with HUD progress (enabled only if JARVIS_MAC_FINDER_PRESET / JARVIS_MAC_FINDER_ROOTS
  are set). On macOS with that enabled, for phrases like "open resume" use **mac_finder_search** with
  keyword "resume" instead of **find_and_open_file**.
- After **mac_finder_search**, speak the JSON `say` field; if `result` is `single`, confirm before
  calling **mac_finder_open_selection**; if `multiple`, wait for the user to pick a number or name.
- Use **create_folder_for_user** when the user asks to create/make a folder in Downloads, Desktop,
  etc. Pass the folder name and a plain-English location (e.g. "my downloads"). Do not invent paths.
- Use **create_markdown_in_documents** for “create a markdown file in Documents” / “new md in Documents”.
- Use **open_latest_pdf** for “open my latest PDF”, “most recent pdf”.
- Use **open_named_repo_in_cursor** when they name a repo or project to open in Cursor (e.g. “Campanion repo in Cursor”).
  If they give a full path, use **open_workspace_in_cursor** instead.
- Use **move_path**, **copy_path**, **rename_in_place** when they explicitly ask to move, copy, or rename
  a specific path (not vague chat).
- Use read_file / write_file ONLY when they want contents read or written to arbitrary paths.
- When JARVIS_ALLOWED_ROOTS is unset on a normal Mac or Linux **desktop** install (not Docker),
  tools can access the whole local disk; containers remain sandboxed until you set roots explicitly.
- When the API runs in Docker or off-host, `open` / Finder actions are delegated to your browser,
  which POSTs paths to `scripts/jarvis_file_bridge.py` on your Mac — `scripts/jarvis_dev.py` starts
  that bridge together with the API and HUD.
- Never say you lack permission, cannot read files, or "I'm afraid I can't" unless the user
  just asked you to read a specific path AND a tool returned Denied. For normal chat, never
  mention file permissions or access.
- If a tool returns "Denied" or "Not a file", do NOT repeat the same tool with the same path.
  Ask the user for the exact path or offer to help another way.
- Do NOT narrate reasoning, say "I made a mistake", or apologize for how you answer.
- If the user says goodbye or signs off: answer with a short courteous farewell (never say you
  "will stop listening"), then call voice_set_listening with listen=False once.
- If they only ask to mute or stop listening without a farewell: acknowledge briefly, then call
  voice_set_listening with listen=False once.
- Be brief; suitable for text-to-speech (short sentences)."""

CHAT_SYSTEM_PROMPT = """You are Jarvis: a calm, precise British assistant.
Reply in one or two short sentences meant to be spoken aloud.
Answer the question directly. Do not hedge with "I'm not sure what you're referring to"
unless the user truly gave no usable topic.
Never mention tools, files, permissions, or internal systems.
Never claim a file, document, or path exists on the user's computer — you cannot see their disk in this mode.
If they ask to find or open files, tell them briefly to use the voice command again starting with "open" plus the exact name (e.g. open budget) so the full assistant can search.
If the user says goodbye or signs off, respond with a warm farewell (e.g. "Goodbye, sir.")
then a final line containing only [[STOP_MIC]].
If they only ask to stop listening or mute without saying goodbye, acknowledge briefly, then [[STOP_MIC]]."""


_THINK_TAG = re.compile(r"<think>[\s\S]*?</think>", re.IGNORECASE)
_REASONING_TAG = re.compile(r"<reasoning>[\s\S]*?</reasoning>", re.IGNORECASE)
_MEM_HINT = re.compile(
    r"\b(remember|recall|last\s+time|you\s+said|preference|saved|earlier|before)\b",
    re.IGNORECASE,
)


def _should_skip_memory(user_text: str) -> bool:
    t = (user_text or "").strip()
    if len(t) >= 48:
        return False
    return not bool(_MEM_HINT.search(t))


def sanitize_model_reply(text: str) -> str:
    """Strip chain-of-thought some reasoning models emit (DeepSeek-R1, etc.)."""
    if not text:
        return ""
    t = text
    if "</think>" in t:
        t = t.split("</think>")[-1].strip()
    t = _THINK_TAG.sub("", t)
    t = _REASONING_TAG.sub("", t)
    t = re.sub(r"<think>[\s\S]*", "", t, flags=re.IGNORECASE)
    meta_starts = (
        "i made a mistake",
        "let me try again",
        "let me rethink",
        "actually, i need to",
        "hmm,",
        "i'm not sure what you're referring to",
        "i am not sure what you're referring to",
        "i'm not sure what you mean",
    )
    lines_out: list[str] = []
    for line in t.split("\n"):
        low = line.lower().strip()
        if any(low.startswith(p) for p in meta_starts):
            continue
        if low.startswith("wait,") and len(low) < 40:
            continue
        if low:
            lines_out.append(line)
    t = "\n".join(lines_out).strip()
    if not t:
        paras = [p.strip() for p in text.split("\n\n") if p.strip()]
        if paras:
            t = paras[-1]
        else:
            t = text.strip()
    # Same-line meta junk (reasoning models)
    segs = re.split(r"(?<=[.!?])\s+", t)
    bad = ("i made a mistake", "let me try again", "let me rethink", "need to provide a direct")
    segs_kept = [
        s
        for s in segs
        if s.strip() and not any(b in s.lower() for b in bad)
    ]
    if segs_kept:
        t = " ".join(segs_kept).strip()
    t = re.sub(r"[\t ]+", " ", t)
    t = re.sub(r"\n{3,}", "\n\n", t).strip()
    return t


def _ai_message_text(m: AIMessage) -> str:
    raw = m.content
    if isinstance(raw, str):
        return raw.strip()
    if isinstance(raw, list):
        chunks: list[str] = []
        for part in raw:
            if isinstance(part, str):
                chunks.append(part)
            elif isinstance(part, dict):
                t = part.get("text")
                if isinstance(t, str):
                    chunks.append(t)
        return "".join(chunks).strip()
    return str(raw).strip()


def _final_assistant_text(final_messages: list[BaseMessage]) -> str:
    """Prefer the last plain-voice AI reply (skip tool-planning messages)."""
    for m in reversed(final_messages):
        if not isinstance(m, AIMessage):
            continue
        tool_calls = getattr(m, "tool_calls", None) or []
        if tool_calls:
            continue
        t = sanitize_model_reply(_ai_message_text(m))
        if t:
            return t
    for m in reversed(final_messages):
        if isinstance(m, AIMessage):
            t = sanitize_model_reply(_ai_message_text(m))
            if t:
                return t
    return ""


def _coerce_tool_args(raw: object) -> dict[str, Any]:
    if isinstance(raw, dict):
        return dict(raw)
    return {}


def _parse_one_tool_call(tc: object) -> dict[str, Any] | None:
    if isinstance(tc, dict):
        fn = tc.get("function")
        if isinstance(fn, dict) and (fn.get("name") or tc.get("name")):
            name = str(fn.get("name") or tc.get("name") or "tool")
            args_raw = fn.get("arguments")
            if args_raw is None:
                args_raw = tc.get("args")
            if isinstance(args_raw, str):
                try:
                    args = json.loads(args_raw) if args_raw.strip() else {}
                except json.JSONDecodeError:
                    args = {}
            else:
                args = _coerce_tool_args(args_raw)
            return {"name": name, "args": args}
        if tc.get("name"):
            return {"name": str(tc["name"]), "args": _coerce_tool_args(tc.get("args"))}
    name = getattr(tc, "name", None)
    if name:
        return {"name": str(name), "args": _coerce_tool_args(getattr(tc, "args", None))}
    return None


def extract_tool_plan_events(messages: list[BaseMessage]) -> list[dict[str, Any]]:
    """Collect tool calls the model requested (several provider payload shapes)."""
    events: list[dict[str, Any]] = []
    for m in messages:
        if not isinstance(m, AIMessage):
            continue
        tcalls: list = list(getattr(m, "tool_calls", None) or [])
        if not tcalls:
            addkw = getattr(m, "additional_kwargs", None) or {}
            raw = addkw.get("tool_calls")
            if isinstance(raw, list):
                tcalls = list(raw)
        for tc in tcalls:
            parsed = _parse_one_tool_call(tc)
            if parsed:
                events.append(parsed)
    return events


def extract_tool_execution_events(messages: list[BaseMessage]) -> list[dict[str, Any]]:
    """One row per ToolMessage (tool actually ran)."""
    out: list[dict[str, Any]] = []
    for m in messages:
        if isinstance(m, ToolMessage):
            nm = getattr(m, "name", None) or "tool"
            out.append({"name": str(nm), "args": {}})
    return out


def _build_model() -> ChatOllama:
    return ChatOllama(
        base_url=settings.ollama_base_url,
        model=settings.ollama_model,
        temperature=0.07,
        timeout=90.0,
        num_ctx=4096,
        num_predict=1536,
    )


def _build_chat_model() -> ChatOllama:
    return ChatOllama(
        base_url=settings.ollama_base_url,
        model=settings.ollama_model,
        temperature=0.12,
        timeout=45.0,
        num_ctx=3072,
        num_predict=220,
    )


def build_graph():
    return create_react_agent(
        _build_model(),
        all_tools(),
        prompt=SYSTEM_PROMPT,
    )


_graph = None


def get_graph():
    global _graph
    if _graph is None:
        _graph = build_graph()
    return _graph


def _augment_messages(user_text: str, history: Iterable[BaseMessage]) -> list[BaseMessage]:
    memory_hits: list[str] = []
    if not _should_skip_memory(user_text) and not should_use_tools(user_text):
        try:
            memory_hits = get_memory_store().recall(user_text, k=3)
        except Exception:
            memory_hits = []
    msgs: list[BaseMessage] = list(history)
    if memory_hits:
        recalled = "\n".join(f"• {m}" for m in memory_hits)
        msgs.append(
            SystemMessage(
                content=(
                    "Long-term memory snippets (reference only; not something the user "
                    f"just said):\n{recalled}"
                ),
            ),
        )
    msgs.append(HumanMessage(content=user_text))
    return msgs


def run_agent_turn(
    user_text: str,
    history: list[BaseMessage],
) -> tuple[str, list[BaseMessage], list[dict[str, Any]]]:
    graph = get_graph()
    messages = _augment_messages(user_text, history)
    out = graph.invoke({"messages": messages}, {"recursion_limit": 18})
    final_messages: list[BaseMessage] = list(out.get("messages", []))
    assistant_text = _final_assistant_text(final_messages)
    plan = merge_tool_event_lists(
        extract_tool_execution_events(final_messages),
        extract_tool_plan_events(final_messages),
    )
    return assistant_text, final_messages, plan


def _strip_history_for_chat(history: list[BaseMessage]) -> list[BaseMessage]:
    """Drop tool traces for the lightweight chat path."""
    return [m for m in history if isinstance(m, (HumanMessage, AIMessage))][-24:]


def run_chat_turn(
    user_text: str,
    history: list[BaseMessage],
) -> tuple[str, list[BaseMessage], bool, list[dict[str, Any]]]:
    """Single LLM call, no tools — fast for voice. Third value: request to stop mic."""
    model = _build_chat_model()
    h = _strip_history_for_chat(history)
    msgs: list[BaseMessage] = [SystemMessage(content=CHAT_SYSTEM_PROMPT)]
    msgs.extend(h)
    memory_hits: list[str] = []
    if not _should_skip_memory(user_text):
        try:
            memory_hits = get_memory_store().recall(user_text, k=3)
        except Exception:
            pass
    if memory_hits:
        recalled = "\n".join(f"• {m}" for m in memory_hits)
        msgs.append(
            SystemMessage(
                content="Long-term memory (reference only):\n" + recalled,
            ),
        )
    msgs.append(HumanMessage(content=user_text))
    ai = model.invoke(msgs)
    raw = _ai_message_text(ai)
    cleaned, mic_stop = strip_stop_mic_token(raw)
    assistant_text = sanitize_model_reply(cleaned)
    new_history = (
        history
        + [
            HumanMessage(content=user_text),
            AIMessage(content=assistant_text),
        ]
    )[-48:]
    return assistant_text, new_history, mic_stop, []


def run_voice_turn(
    user_text: str,
    history: list[BaseMessage],
) -> tuple[str, list[BaseMessage], bool, list[dict[str, Any]]]:
    """Chat-only or full ReAct when tools look necessary (quick replies handled in the pipeline)."""
    if should_use_tools(user_text):
        full, hist, plan = run_agent_turn(user_text, history)
        full, stop = strip_stop_mic_token(full)
        return full, hist, stop, plan
    return run_chat_turn(user_text, history)
