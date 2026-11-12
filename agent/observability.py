from __future__ import annotations

import re
import uuid

_PII = re.compile(
    r"(?i)\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b|"
    r"(?<!\w)(?:\+?\d[\d\s().-]{7,}\d)(?!\w)|"
    r"\b(?:\d[ -]*?){13,19}\b"
)


def new_trace_id() -> str:
    return str(uuid.uuid4())


def mask_pii(text: str) -> str:
    if not isinstance(text, str):
        raise TypeError("text must be a string")
    return _PII.sub("[REDACTED]", text)
