from __future__ import annotations

import re
from collections.abc import Iterable
from enum import StrEnum


class CustomerResponseLanguageMode(StrEnum):
    ENGLISH = "english"
    HINDI = "hindi"
    HINGLISH = "hinglish"
    GUJARATI = "gujarati"
    GUJLISH = "gujlish"


_EXPLICIT_MODE_PATTERNS: tuple[tuple[CustomerResponseLanguageMode, re.Pattern[str]], ...] = (
    (
        CustomerResponseLanguageMode.HINGLISH,
        re.compile(r"\b(?:reply in|speak|bolo) hinglish\b|\bhinglish me\b"),
    ),
    (
        CustomerResponseLanguageMode.GUJLISH,
        re.compile(r"\b(?:reply in|speak|bolo) gujlish\b|\bgujlish ma\b"),
    ),
    (
        CustomerResponseLanguageMode.GUJARATI,
        re.compile(r"\b(?:reply in|speak|bolo) gujarati\b|\bgujarati ma\b"),
    ),
    (
        CustomerResponseLanguageMode.HINDI,
        re.compile(r"\b(?:reply in|speak|bolo) hindi\b|\bhindi me\b"),
    ),
    (CustomerResponseLanguageMode.ENGLISH, re.compile(r"\b(?:answer|reply|speak) in english\b")),
)

_GUJLISH_WORDS = frozenset(
    {"shu", "chhe", "chhiye", "joie", "mane", "tame", "kai", "ma", "nathi", "che"}
)
_HINGLISH_WORDS = frozenset(
    {
        "hai",
        "hain",
        "kya",
        "kaunsa",
        "chahiye",
        "mujhe",
        "hum",
        "hume",
        "dikhao",
        "batao",
        "nahi",
        "zyada",
        "thoda",
    }
)
_GUJLISH_PHRASES = ("kari do", "aapo", "apo")
_HINGLISH_PHRASES = ("kar do",)


def resolve_customer_response_mode(
    latest_message: str, *, prior_user_messages: Iterable[str] = ()
) -> CustomerResponseLanguageMode:
    explicit = _explicit_mode(latest_message)
    if explicit is not None:
        return explicit
    if _script_character_count(latest_message, "\u0a80", "\u0aff") >= 2:
        return CustomerResponseLanguageMode.GUJARATI
    if _script_character_count(latest_message, "\u0900", "\u097f") >= 2:
        return CustomerResponseLanguageMode.HINDI

    gujlish_score, hinglish_score = _latin_scores(latest_message)
    if gujlish_score >= 2 and gujlish_score > hinglish_score:
        return CustomerResponseLanguageMode.GUJLISH
    if hinglish_score >= 2 and hinglish_score > gujlish_score:
        return CustomerResponseLanguageMode.HINGLISH

    for message in reversed(tuple(prior_user_messages)):
        explicit = _explicit_mode(message)
        if explicit is not None:
            return explicit
    return CustomerResponseLanguageMode.ENGLISH


def response_mode_instruction(mode: CustomerResponseLanguageMode) -> str:
    instructions = {
        CustomerResponseLanguageMode.ENGLISH: "Respond in concise natural English.",
        CustomerResponseLanguageMode.HINDI: (
            "Respond in natural Hindi using Devanagari script. English restaurant terms may remain "
            "where natural."
        ),
        CustomerResponseLanguageMode.HINGLISH: (
            "Respond in natural Hinglish using Latin/Roman script. Do not default to full English. "
            "Use normal Hindi-English conversational wording written in Latin script; never use "
            "Devanagari."
        ),
        CustomerResponseLanguageMode.GUJARATI: (
            "Respond in natural Gujarati using Gujarati script. English restaurant/menu terms may "
            "remain where natural."
        ),
        CustomerResponseLanguageMode.GUJLISH: (
            "Respond in natural Gujlish using Latin/Roman script. Do not default to full English. "
            "Use Gujarati-English conversational wording in Latin script; never use "
            "Gujarati script."
        ),
    }
    return instructions[mode]


def _explicit_mode(message: str) -> CustomerResponseLanguageMode | None:
    normalized = " ".join(message.lower().split())
    for mode, pattern in _EXPLICIT_MODE_PATTERNS:
        if pattern.search(normalized):
            return mode
    return None


def _latin_scores(message: str) -> tuple[int, int]:
    normalized = " ".join(message.lower().split())
    words = set(re.findall(r"[a-z]+", normalized))
    gujlish_score = len(words & _GUJLISH_WORDS) + sum(
        phrase in normalized for phrase in _GUJLISH_PHRASES
    )
    hinglish_score = len(words & _HINGLISH_WORDS) + sum(
        phrase in normalized for phrase in _HINGLISH_PHRASES
    )
    return gujlish_score, hinglish_score


def _script_character_count(message: str, lower: str, upper: str) -> int:
    return sum(lower <= character <= upper for character in message)
