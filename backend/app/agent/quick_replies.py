from __future__ import annotations

import re
from datetime import datetime


def try_quick_reply(text: str) -> str | None:
    """Answer common voice prompts instantly without hitting the LLM."""
    t = (text or "").strip().lower()
    if len(t) < 3:
        return None

    now = datetime.now().astimezone()

    # Date / day
    if re.search(
        r"\b(what'?s?\s+)?(what\s+)?(day|date)\s+(is\s+it|are\s+we|today|now)\b",
        t,
    ):
        return (
            f"Today is {now.strftime('%A')}, {now.day} {now.strftime('%B %Y')}."
        )
    if re.search(r"\bwhat\s+day\s+is\s+today\b", t):
        return (
            f"Today is {now.strftime('%A')}, {now.day} {now.strftime('%B %Y')}."
        )
    if re.search(r"\bwhat'?s?\s+today'?s?\s+(day|date)\b", t):
        return (
            f"Today is {now.strftime('%A')}, {now.day} {now.strftime('%B %Y')}."
        )
    if re.search(r"\btoday'?s?\s+(day|date)\b", t):
        return (
            f"Today is {now.strftime('%A')}, {now.day} {now.strftime('%B %Y')}."
        )

    # Time
    if re.search(r"\bwhat\s+time\b", t) or re.search(
        r"\btime\s+(is\s+it|now)\b",
        t,
    ):
        h12 = now.hour % 12 or 12
        ampm = "a.m." if now.hour < 12 else "p.m."
        return f"The time is {h12}:{now.minute:02d} {ampm}."

    # Presence check (often after wake word is stripped)
    if re.search(
        r"\b("
        r"r\s*u\s+there|u\s+there|you\s+there|are\s+you\s+there|"
        r"anybody\s+home|still\s+with\s+me"
        r")\b",
        t,
    ):
        return "For you, sir, always."

    return None
