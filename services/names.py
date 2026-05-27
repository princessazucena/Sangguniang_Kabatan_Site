"""
Name-formatting helpers shared by signup, login, and admin views.

Display rule: every word in a person's name starts with an uppercase
letter, the rest are lowercase, regardless of how the user typed it.
We keep things simple — Title Case applied to each whitespace-separated
token, with a few special cases:

* Hyphenated parts are title-cased on each side of the hyphen
  ("anne-marie" -> "Anne-Marie").
* Apostrophe particles keep the lowercase letter after the apostrophe
  in normal English ("o'connor" -> "O'Connor").
* Roman-numeral suffixes are upper-cased ("ii", "iii", "iv").
* "ng" / "nang" stays lowercase when it appears between names so things
  like "Sangguniang Kabataan ng Bukal" still read naturally; we do NOT
  touch person names with these particles since first/middle/last rarely
  contain them — but if they do (e.g. de la cruz), each word is just
  capitalized.
"""
from __future__ import annotations

import re

_ROMAN_NUMERALS = {"i", "ii", "iii", "iv", "v", "vi", "vii", "viii", "ix", "x"}


def _cap_token(token: str) -> str:
    if not token:
        return token
    # Hyphenated parts: capitalize each side of the hyphen.
    if "-" in token:
        return "-".join(_cap_token(p) for p in token.split("-"))
    lower = token.lower()
    # Suffix style numerals (II, III, IV, ...)
    if lower in _ROMAN_NUMERALS:
        return lower.upper()
    # "Jr." / "Sr." style suffixes — strip trailing dot, capitalize, restore.
    if lower.endswith(".") and lower[:-1] in {"jr", "sr"}:
        return lower[:-1].capitalize() + "."
    if lower in {"jr", "sr"}:
        return lower.capitalize()
    # "O'Connor", "D'Cruz" etc.
    if "'" in lower:
        return "'".join(p.capitalize() for p in lower.split("'"))
    return lower.capitalize()


def title_name(value: str | None) -> str:
    """
    Return a person-name styled with Title Case: each whitespace-separated
    word starts uppercase, every other character lowercase. Hyphens and
    apostrophes get the same treatment per part.

    Whitespace is normalized to single spaces and trimmed.
    """
    if not value:
        return ""
    cleaned = re.sub(r"\s+", " ", value).strip()
    if not cleaned:
        return ""
    return " ".join(_cap_token(t) for t in cleaned.split(" "))


def build_full_name(first: str, middle: str, last: str, suffix: str) -> str:
    """Assemble a full name from its parts, each title-cased."""
    parts = [
        title_name(first),
        title_name(middle),
        title_name(last),
    ]
    parts = [p for p in parts if p]
    name = " ".join(parts)
    sfx = title_name(suffix)
    if sfx:
        name = f"{name} {sfx}"
    return name
