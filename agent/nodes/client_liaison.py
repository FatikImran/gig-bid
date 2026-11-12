from __future__ import annotations

import re
from typing import Literal

Intent = Literal[
    "question",
    "negotiation",
    "interview_request",
    "scam_signal",
    "prompt_injection",
    "other",
]


def classify_message(message: str) -> Intent:
    if not isinstance(message, str) or not message.strip():
        raise ValueError("Client message must be non-empty text")
    if re.search(
        r"\b(ignore|disregard|forget)\b.{0,50}\b(previous|prior|system)\b.{0,30}\b(instructions?|prompt)\b|"
        r"\b(reveal|print|show)\b.{0,30}\b(system prompt|hidden instructions?)\b",
        message,
        re.IGNORECASE,
    ):
        return "prompt_injection"
    if re.search(r"\b(telegram|whatsapp|crypto|gift card|pay a fee)\b", message, re.IGNORECASE):
        return "scam_signal"
    if re.search(r"\b(interview|available|calendar|schedule|meet)\b", message, re.IGNORECASE):
        return "interview_request"
    if re.search(
        r"\b(rate|budget|price|discount|negotiate)\b|"
        r"(?:US\$|\$)\s*\d|\b\d[\d,]*(?:\.\d+)?\s*(?:USD|dollars?|/\s*(?:hr|h)|per\s+hour|hourly)\b",
        message,
        re.IGNORECASE,
    ):
        return "negotiation"
    if "?" in message:
        return "question"
    return "other"


def draft_reply(message: str) -> dict[str, str]:
    intent = classify_message(message)
    if intent in {"scam_signal", "prompt_injection"}:
        return {"intent": intent, "draft": "", "status": "blocked"}
    if intent == "interview_request":
        response = "Thanks for reaching out. I can discuss the project; please share a few suitable times here."
    elif intent == "negotiation":
        response = "Thanks for sharing the budget. I can review the scope and confirm a suitable fixed price."
    elif intent == "question":
        response = "Thanks for the question. I will review the project details and respond with a specific answer."
    else:
        response = "Thanks for the update. I will review it and get back to you shortly."
    return {"intent": intent, "draft": response, "status": "pending_review"}
