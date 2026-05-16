from __future__ import annotations

import contextvars
from typing import Any

# Bound around VoiceSession.handle_user_text so tools can signal mic / UI.
current_voice_session: contextvars.ContextVar[Any | None] = contextvars.ContextVar(
    "current_voice_session",
    default=None,
)
