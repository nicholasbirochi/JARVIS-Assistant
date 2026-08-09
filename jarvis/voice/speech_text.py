"""Turns a reply's display text into what should actually be spoken --
used only for the text handed to the TTS engines (say/XTTS), never for
what's shown in the visualizer transcript or printed anywhere. The two
are deliberately different: the transcript should show "IA" as written,
but say/XTTS need "I.A." (dots force letter-by-letter pronunciation) or
they'll try to pronounce it as a word.

The system prompt already tells the model not to use markdown, but LLMs
don't always comply -- when it slips through, a literal "**IA**" read
aloud comes out as "asterisco asterisco I A asterisco asterisco" instead
of just being spoken plainly. Stripped here as a safety net, not because
markdown is expected to be the normal case.
"""

from __future__ import annotations

import re

# Order matters: bold before italic (so **x** doesn't leave stray single
# asterisks behind for the italic pattern to mishandle), links before bare
# brackets, code spans before general symbol cleanup.
_BOLD = re.compile(r"\*\*(.+?)\*\*|__(.+?)__")
_ITALIC = re.compile(r"\*(.+?)\*|_(.+?)_")
_INLINE_CODE = re.compile(r"`([^`]+)`")
_LINK = re.compile(r"\[([^\]]+)\]\([^)]+\)")
_HEADER = re.compile(r"^\s{0,3}#{1,6}\s+", re.MULTILINE)
_BULLET = re.compile(r"^\s*[-*+]\s+", re.MULTILINE)

# Acronyms: 2+ consecutive uppercase Latin letters as their own word (word
# boundaries keep this from matching inside normal capitalized words).
# Deliberately Latin-only (no \w, which would also match accented
# uppercase letters like "É" mid-word in ways that don't read as acronyms).
_ACRONYM = re.compile(r"\b[A-Z]{2,}\b")


_REPEATED_PERIODS = re.compile(r"\.{2,}")


def _spell_out(match: re.Match) -> str:
    return ".".join(match.group(0)) + "."


def strip_markdown(text: str) -> str:
    """Removes common markdown syntax, keeping the visible text -- "**IA**"
    becomes "IA", "[Gupy](https://...)" becomes "Gupy", etc. Not a full
    markdown parser (no tables, nested structures) -- this only needs to
    handle what a short spoken reply could plausibly contain."""
    text = _LINK.sub(r"\1", text)
    text = _INLINE_CODE.sub(r"\1", text)
    text = _BOLD.sub(lambda m: m.group(1) or m.group(2), text)
    text = _ITALIC.sub(lambda m: m.group(1) or m.group(2), text)
    text = _HEADER.sub("", text)
    text = _BULLET.sub("", text)
    return text


def spell_out_acronyms(text: str) -> str:
    """"IA" -> "I.A.", "LLM" -> "L.L.M." -- so say/XTTS pronounce each
    letter instead of trying to read the acronym as a word. Collapses the
    occasional "I.A.." double period that comes from an acronym landing
    right before the sentence's own final stop -- harmless for TTS either
    way, but a single period is cleaner."""
    text = _ACRONYM.sub(_spell_out, text)
    return _REPEATED_PERIODS.sub(".", text)


def prepare_for_speech(text: str) -> str:
    """The full pipeline tts.speak() runs before handing text to an
    engine. Markdown is stripped before acronyms are spelled out, since a
    bare acronym could otherwise be wrapped in now-irrelevant markdown
    syntax (e.g. "**IA**")."""
    text = strip_markdown(text)
    text = spell_out_acronyms(text)
    return text
