from __future__ import annotations

import re

_STOP_TOKEN = "[[STOP_MIC]]"

_GOODBYE = re.compile(
    r"\b("
    r"goodbye|good\s+bye|bye-?bye|farewell|"
    r"see\s+you|talk\s+later|catch\s+you\s+later|have\s+to\s+go|"
    r"signing\s+off|until\s+next\s+time|bye"
    r")\b",
    re.IGNORECASE,
)

_MIC_DISMISS = re.compile(
    r"\b("
    r"stop\s+listening|stop\s+the\s+mic|mute(\s+the\s+mic)?|"
    r"quiet(\s+now)?|shut\s+up|"
    r"that'?s\s+all|that\s+is\s+all|dismissed|leave\s+me"
    r")\b",
    re.IGNORECASE,
)


def user_said_goodbye(text: str) -> bool:
    """Polite sign-off (should hear a farewell, not 'I will stop listening')."""
    return bool(_GOODBYE.search(text or ""))


def user_requested_mic_dismiss(text: str) -> bool:
    """Explicit 'stop the mic' without necessarily saying goodbye."""
    return bool(_MIC_DISMISS.search(text or ""))


def user_wants_session_end(text: str) -> bool:
    """Goodbye or explicit mic dismiss — pause listening after the reply."""
    return user_said_goodbye(text) or user_requested_mic_dismiss(text)


def strip_stop_mic_token(text: str) -> tuple[str, bool]:
    """Remove Jarvis stop-listen token from spoken/displayed text."""
    if not text or _STOP_TOKEN not in text:
        return text, False
    cleaned = text.replace(_STOP_TOKEN, "").strip()
    return cleaned, True
