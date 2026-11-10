"""
mysearch.py - decide which items match what the user typed, and in which order.

This file is pure thinking: it never touches the disk, the screen or the Mac. You give it a list
of Items and a text, it gives back the best Matches. That makes it easy to test and easy to
change; if you want the launcher to rank differently, this is the only file you edit.

The rules (each rule gives a score; the best rule that applies wins):

    100   the text is EXACTLY the title                  "shutdown"   ->  Shutdown
     80   the title STARTS with the text                 "shut"       ->  Shutdown
     60   a WORD of the title starts with the text       "obs"        ->  Run Obsidian
     40   the text appears INSIDE the title              "sidi"       ->  Run Obsidian
     20   the letters appear in ORDER (fuzzy)            "rsfr"       ->  Run Safari
      0   no match: the item is not shown

Before comparing, both sides are normalised: lower case, no accents, single spaces. That is what
gives us the "lowercase to make it easy" behaviour: typing "OBS", "Obs" or "obs" is the same.

Each item is tried with its title AND its keywords ("power off" finds Shutdown); the best score wins.
"""

from __future__ import annotations

import unicodedata

from mytypes import Item, Match

SCORE_EXACT = 100
SCORE_STARTS = 80
SCORE_WORD = 60
SCORE_INSIDE = 40
SCORE_FUZZY = 20


def normalize(text: str, ignore_accents: bool = True) -> str:
    """lower case, optionally without accents, with single spaces.   "  Café  OBS " -> "cafe obs"."""
    text = text.lower()
    if ignore_accents:
        # NFD splits "é" into "e" + an accent mark; then we drop the marks.
        decomposed = unicodedata.normalize("NFD", text)
        text = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    return " ".join(text.split())


def _is_subsequence(query: str, text: str) -> bool:
    """True if the letters of `query` appear in `text` in the same order (not necessarily together)."""
    remaining = iter(text)  # an iterator remembers where it is, so each letter is searched AFTER the previous one
    return all(letter in remaining for letter in query)


def score_text(query: str, text: str, fuzzy: bool = True) -> int:
    """Score of ONE normalised text against ONE normalised query (see the table above)."""
    if not query:
        return 1  # nothing typed: everything matches a little, so the whole list is shown
    if text == query:
        return SCORE_EXACT
    if text.startswith(query):
        return SCORE_STARTS
    if any(word.startswith(query) for word in text.split()):
        return SCORE_WORD
    if query in text:
        return SCORE_INSIDE
    if fuzzy and _is_subsequence(query, text.replace(" ", "")):
        return SCORE_FUZZY
    return 0


def rank(items, query: str, limit: int | None = None, ignore_accents: bool = True, fuzzy: bool = True) -> list:
    """The best matches for `query`, best first. Returns a list of Match."""
    wanted = normalize(query, ignore_accents)
    matches = []
    for item in items:
        texts = [item.title, *item.keywords]
        best = max(score_text(wanted, normalize(t, ignore_accents), fuzzy) for t in texts)
        if best > 0:
            matches.append(Match(item, best))
    # Sort: higher score first; on a tie, commands before apps; then alphabetical.
    matches.sort(key=lambda m: (-m.score, m.item.kind != "command", normalize(m.item.title, ignore_accents)))
    return matches if limit is None else matches[:limit]


def complete(query: str, matches, ignore_accents: bool = True) -> str:
    """The text the search box should show when the user presses Tab (autocomplete).

    It is the title of the best match, in lower case: "obs" -> "run obsidian".
    With no match, the text is left as it was.
    """
    if not matches:
        return query
    return normalize(matches[0].item.title, ignore_accents)
