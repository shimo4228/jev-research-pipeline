"""What counts as a searchable query string.

Used on both sides of the model boundary: Qwen's output is validated with it (a
violation is retried and metered) and every adapter checks it again before sending.
qwen3.8-flash's NativeOutput intermittently leaks chat-template tokens
("<|start|>assistant: …", ",", "]") and arXiv answered 406 to `search_query=all:,`
(second live run, 2026-09-23), so the guard is deterministic and lives in code.
"""

import re
from typing import Final

MIN_QUERY_CHARS: Final = 3
_EDGE_PUNCTUATION: Final = " \t\n\r,.;:!?\"'`|[](){}<>*/\\-_=+~^#@$%&"
_WORD_RE: Final = re.compile(r"[0-9A-Za-z\u3041-\u309f\u30a0-\u30ff\u4e00-\u9fff]")


def clean_query(text: str) -> str | None:
    """The query with whitespace collapsed and edge punctuation stripped, or None when it
    is too short, carries a template token, or has no alphanumeric / CJK character."""
    if "<|" in text:  # a chat-template token anywhere means the string is contaminated
        return None
    stripped = " ".join(text.split()).strip(_EDGE_PUNCTUATION)
    if len(stripped) < MIN_QUERY_CHARS or not _WORD_RE.search(stripped):
        return None
    return stripped
