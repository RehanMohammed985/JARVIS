from __future__ import annotations

import re

# One-word open targets that must NOT trigger the filesystem agent (avoid noise / chit-chat).
_OPEN_TARGET_BLOCK = frozenset({
    "cursor",
    "terminal",
    "finder",
    "vscode",
    "visual",
    "studio",
    "settings",
    "preferences",
    "safari",
    "chrome",
    "mail",
    "messages",
    "music",
    "calculator",
    "the",
    "this",
    "that",
    "it",
    "them",
    "something",
    "anything",
    "a",
    "an",
    "to",
    "in",
    "on",
    "for",
    "now",
    "please",
    "pls",
    "me",
    "up",
    "here",
})

_FIND_VERB_BLOCK = frozenset({
    "me",
    "out",
    "a",
    "an",
    "the",
    "it",
    "something",
    "anything",
})


def _open_filename_intent(t: str) -> bool:
    """True for 'open resume', 'open my tax.pdf', etc. — must use tools, not chat-only."""
    m = re.search(
        r"\bopen\s+(?:my\s+|the\s+|a\s+|an\s+)?([A-Za-z0-9][^\s,.;!?]{1,})\b",
        t,
        re.IGNORECASE,
    )
    if not m:
        return False
    word = m.group(1).lower()
    if word in _OPEN_TARGET_BLOCK:
        return False
    if len(word) < 2:
        return False
    return True


def _find_keyword_intent(t: str) -> bool:
    m = re.search(
        r"\b(?:find|locate)\s+(?:my\s+|the\s+|a\s+|an\s+)?([A-Za-z0-9][^\s,.;!?]{1,})\b",
        t,
        re.IGNORECASE,
    )
    if not m:
        return False
    w = m.group(1).lower()
    if w in _FIND_VERB_BLOCK or len(w) < 2:
        return False
    return True


_TOOL_HINT = re.compile(
    "|".join(
        [
            r"https?://\S+",
            r"\b(?:read|open|show|display|cat|edit|write|save|create)\s+.{0,80}\b(?:file|path|document|folder|directory)\b",
            r"`[^`]+\.(?:py|ts|tsx|js|mjs|cjs|md|json|txt|yaml|yml|toml|rs|go|java|kt)\b`",
            r"/(?:users|home|tmp|var|etc|usr|opt)/[^,\s|>]+",
            r"[A-Za-z]:\\",
            r"\b(?:run|execute)\s+(?:a\s+)?(?:shell|command)\b",
            r"\bin\s+terminal\b",
            r"\bopen\s+(?:cursor|terminal|finder|vscode|visual studio)\b",
            r"\b(?:remember|recall|remind\s+me|what\s+did\s+i\s+(?:say|tell|save))\b",
            r"\b(?:fetch|scrape)\b.{0,30}\b(?:url|page|site|article)\b",
            r"\b(?:email|inbox|unread\s+mail|calendar|meeting|appointment)\b",
            r"\b(?:filesystem|sandbox)\s+overview\b",
            r"\b(?:what|where)\s+.{0,50}(?:files?|folders?|directories|on\s+my\s+(?:computer|mac|machine))\b",
            r"\b(?:list|ls|dir)\s+.{0,40}(?:folder|directory|contents)\b",
            r"\bfind\s+(?:files?|all\s+files)\b",
            r"\bsearch\s+(?:my\s+)?(?:computer|disk|drive|machine|laptop)\s+for\b",
            r"\b(?:is\s+there|do\s+i\s+have)\s+(?:a\s+)?",
            r"\b(?:look|search|locate)\s+(?:for\s+)?(?:a\s+)?(?:file|something)\b",
            r"\b(?:look|search|locate)\s+for\b",
            r"\bsearch\s+for\b",
            r"\bopen\s+[\"']",
            r"\bopen\s+/\S",
            r"\bopen\s+~/\S",
            r"\bopen\s+(?:my\s+|the\s+|this\s+|that\s+)?(?:file|document|pdf|folder)\b",
            r"\bopen\s+(?:number|#)?\s*\d+",
            r"\bopen\s+(?:the\s+)?pdf\b",
            r"\b(?:launch|show)\s+(?:something|anything|it|this|that)\b",
            r"\b(?:show|reveal)\s+(?:me\s+)?(?:in\s+)?(?:the\s+)?(?:file|folder|document)\b",
            r"\b(?:open|show|put)\b.{0,40}\b(?:in|with)\s+finder\b",
            r"\bfinder\b.{0,20}\b(?:open|show|reveal)\b",
            r"\bwhere\s+(?:is|are)\s+.{0,50}\bfile\b",
            r"\b(?:does|did)\s+.{0,60}\b(?:exist|exists)\b",
            r"\b(?:any|some)\s+.{0,50}\bfile\b",
            r"\bglob\s+",
        ]
    ),
    re.IGNORECASE,
)


def _create_folder_intent(t: str) -> bool:
    return bool(
        re.search(
            r"\b(?:create|make)\s+(?:a\s+|an\s+|the\s+)?(?:new\s+)?folder\b",
            t,
            re.IGNORECASE,
        )
    )


def _markdown_create_intent(t: str) -> bool:
    return bool(
        re.search(
            r"\b(?:create|make)\s+(?:a\s+|an\s+)?(?:new\s+)?(?:markdown|md)\s+file\b",
            t,
            re.IGNORECASE,
        )
    )


def _latest_pdf_intent(t: str) -> bool:
    return bool(
        re.search(
            r"\b(?:latest|most\s+recent|last)\s+pdf\b",
            t,
            re.IGNORECASE,
        )
    )


def _cursor_repo_intent(t: str) -> bool:
    return bool(
        re.search(
            r"\bopen\b.{0,120}\b(?:in|with)\s+cursor\b|\b(?:repo|project)\b.{0,40}\b cursor\b",
            t,
            re.IGNORECASE,
        )
    )


def _mutate_path_intent(t: str) -> bool:
    return bool(
        re.search(
            r"\b(?:move|copy|rename)\b.{0,80}\b(?:file|folder|directory)\b",
            t,
            re.IGNORECASE,
        )
    )


def should_use_tools(text: str) -> bool:
    """If False, use a fast chat-only model path (no ReAct / tool loop)."""
    t = (text or "").strip()
    if len(t) < 2:
        return False
    if _create_folder_intent(t):
        return True
    if _markdown_create_intent(t) or _latest_pdf_intent(t):
        return True
    if _cursor_repo_intent(t) or _mutate_path_intent(t):
        return True
    if _open_filename_intent(t) or _find_keyword_intent(t):
        return True
    return bool(_TOOL_HINT.search(t))
