from __future__ import annotations

import json
import re

_DIRECT_OPEN_BLOCK = re.compile(
    r"^(?:cursor|terminal|finder|vscode|visual\s+studio|settings|preferences|safari|chrome)\b",
    re.IGNORECASE,
)


def try_cached_finder_pick(user_text: str) -> str | None:
    """If HUD/list left matches in session cache, handle 'open number 2' without LLM."""
    t = (user_text or "").strip()
    if len(t) > 120:
        return None
    looks_pick = bool(
        re.search(
            r"\b(?:number|open\s+number|open\s+#|#\s*|pick\s+(?:number\s*)?)(\d+)\b",
            t,
            re.I,
        )
        or re.match(r"^\s*(\d+)\s*$", t)
        or re.search(r"\bopen\s+(\d+)\s*[.!?…]?\s*$", t, re.I)
    )
    if not looks_pick:
        return None

    from app.voice.session_context import current_voice_session

    sess = current_voice_session.get()
    if sess is None:
        return None
    get_cache = getattr(sess, "get_finder_match_cache", None)
    if not callable(get_cache) or not get_cache():
        return None

    from app.tools.file_search_tool import mac_finder_open_selection

    raw = mac_finder_open_selection.invoke(
        {"selection_text": user_text, "reveal_in_finder": False},
    )
    if isinstance(raw, str) and raw.startswith("{"):
        try:
            d = json.loads(raw)
            if d.get("ok"):
                return str(
                    d.get("message")
                    or f'Opened {d.get("path", "").split("/")[-1] or "file"}.',
                )
            return str(d.get("message") or raw)
        except Exception:
            return raw
    return str(raw)


def try_direct_find_and_open(user_text: str) -> str | None:
    """Broad token find/search/open without waiting for the LLM (HUD always lists results)."""
    t = (user_text or "").strip()
    if len(t) > 220:
        return None

    m = re.search(r"\b(?:open|launch)\s+(?:up\s+)?(.+)$", t, re.IGNORECASE | re.DOTALL)
    if not m:
        m = re.search(r"\b(?:find|search)\s+(?:for\s+)?(.+)$", t, re.IGNORECASE | re.DOTALL)
    if not m:
        m = re.search(r"\blook\s+for\s+(.+)$", t, re.IGNORECASE | re.DOTALL)
    if not m:
        return None

    frag = m.group(1).strip().rstrip(".!?… ")
    frag = re.sub(r"\b(?:for me|please|pls|now)\s*$", "", frag, flags=re.IGNORECASE).strip()
    frag = re.sub(r"\s+in\s+finder\s*$", "", frag, flags=re.IGNORECASE).strip()
    frag = re.sub(r"^(?:my|the|a|an|this|that)\s+", "", frag, flags=re.IGNORECASE).strip()
    frag = re.sub(r"^(?:file|files|document|documents|folder)\s+", "", frag, flags=re.IGNORECASE).strip()

    if len(frag) < 2 or len(frag) > 120:
        return None
    if re.match(r"^\d+$", frag.strip()):
        return None
    if re.match(r"^(?:it|this|that|them|something|anything)\s*$", frag, re.IGNORECASE):
        return None
    if _DIRECT_OPEN_BLOCK.match(frag):
        return None

    if re.search(r"\bopen\s+(?:number|#)\s*\d+", t, re.I):
        return None
    if re.match(r"^\s*\d+\s*$", t):
        return None

    in_finder = bool(re.search(r"\bin\s+finder\b", t, re.IGNORECASE))

    from app.tools.filesystem_extra import execute_find_and_open

    return execute_find_and_open(frag, show_in_finder=in_finder)
