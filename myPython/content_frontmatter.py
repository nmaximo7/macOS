"""
content_frontmatter.py - propose the Hugo front matter of a page (read-only, like check_latex).

    from content_frontmatter import check_hugo_frontmatter, page_frontmatter

    page_frontmatter(Path(page))        # -> the text between the two "---" lines (a str)
    check_hugo_frontmatter(Path(page))  # -> prints the front matter that suits the page

Nothing is ever written or created: check_hugo_frontmatter only PRINTS (with Rich) the
whole front matter it proposes, ready to copy and paste.
Values that are new or different from what the page has now are printed in RED;
values that are already right (or that are kept as they are) in the normal colour.

Who decides each field
----------------------
    keywords        Ollama (15-25 key phrases, comma separated, one line)
    language        always "en"
    title           Ollama
    author          always the AUTHOR value of .env (if AUTHOR is not set: the page's own is kept)
    date            always today, as "YYYY-MM-DD"
    categories      Ollama, preferring the categories your site already uses
    featured_image  kept if the page has one, otherwise FEATURED_IMAGE of .env (if not set: none is proposed)
    weight          kept if the page has one, otherwise DEFAULT_WEIGHT
    description     Ollama (1-2 sentences, 150-300 characters)
    firstarticle    (and any other field this script does not know) kept exactly as it is

To save time (local models are slow) ONE single question is sent to the model; it answers
with a small JSON object containing title, keywords, categories and description.
"""

from __future__ import annotations

import datetime
import json
import re
from collections import Counter
from functools import lru_cache
from pathlib import Path

from rich.console import Console
from rich.text import Text

from myconfig import get_settings  # AUTHOR and FEATURED_IMAGE come from .env
from myollama import (
    call_ollama,
)  # the project's helper to talk to Ollama (needs show=False support)

# --------------------------------------------------------------------------- #
# Settings (edit freely)                                                      #
# --------------------------------------------------------------------------- #

# The author and the default featured image are personal: they are read from .env
# (AUTHOR and FEATURED_IMAGE), see myconfig.py.
LANGUAGE = "en"  # always English
DEFAULT_WEIGHT = 100  # used only if the page has none
KEEP_EXISTING_DATE = False  # False = always today's date

MAX_KEYWORDS = 30  # hard limit after cleaning the model's answer
MAX_CATEGORIES = 4
MAX_ARTICLE_CHARS = 10_000  # how much of the article start is sent to the model
MAX_TAIL_CHARS = 2_000  # ... plus this much of its end
MAX_HEADINGS = 60  # headings listed for the model (they summarise the article well)
CATEGORY_SCAN_LIMIT = (
    5_000  # at most this many pages are scanned to learn your categories
)

NEW_STYLE = "bold red"  # new or changed values
KEY_STYLE = "bold"  # field names
TEXT_STYLE = ""  # unchanged values ("" = your terminal's normal colour)
DIM_STYLE = "dim"

console = Console(highlight=False)

# --------------------------------------------------------------------------- #
# 1. Reading the page and its current front matter                            #
# --------------------------------------------------------------------------- #


def _read(page) -> str:
    """Read a file as UTF-8 text with '\\n' line endings (also accepts a str path)."""
    with open(Path(page), "r", encoding="utf-8", newline="") as fh:
        return fh.read().replace("\r\n", "\n")


def _split_page(text: str):
    """Return (front_matter, body).

    front_matter is the text between the first two '---' lines (without them);
    it is '' when the page has no front matter.  body is everything after it.
    """
    lines = text.lstrip("﻿").split("\n")
    if not lines or lines[0].strip() != "---":
        return "", text  # no front matter at all
    for i in range(1, len(lines)):
        if lines[i].strip() in ("---", "..."):  # the closing line
            return "\n".join(lines[1:i]), "\n".join(lines[i + 1 :])
    return "", text  # opened but never closed: ignore it


def page_frontmatter(page) -> str:
    """Return the front matter of `page`: the text between the two '---' lines.

    Returns '' when the page has no front matter.
    """
    return _split_page(_read(page))[0]


_KEY_RE = re.compile(
    r"^([A-Za-z_][A-Za-z0-9_-]*)\s*:(.*)$"
)  # a top-level "key: value" line


def _parse_blocks(front: str) -> dict:
    """Split front matter into {key: [its lines]}, keeping the original text.

    A block is the 'key: value' line plus the lines that belong to it (an indented
    continuation, or a list written as '- item' lines).  No YAML library is needed.
    """
    blocks, current = {}, None
    for line in front.split("\n"):
        m = _KEY_RE.match(line)
        if m:  # a new top-level key starts here
            current = m.group(1)
            blocks[current] = [line]
        elif current is not None:  # continuation of the previous key
            blocks[current].append(line)
    for key, lines in blocks.items():  # drop trailing blank lines of each block
        while len(lines) > 1 and not lines[-1].strip():
            lines.pop()
    return blocks


def _unquote(value: str) -> str:
    """'"abc"' -> 'abc'   (also single quotes)."""
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        value = value[1:-1]
    return value


def _block_value(lines: list):
    """The VALUE of a block, to compare it with the proposed one.

    A scalar becomes a normalised string; a list ('[a, b]' or '- a' lines) a tuple.
    """
    first = _KEY_RE.match(lines[0]).group(2).strip()
    if first.startswith("[") and first.endswith("]"):  # flow list: [a, b]
        return tuple(_unquote(p) for p in first[1:-1].split(",") if p.strip())
    if first:  # plain scalar
        return " ".join(_unquote(first).split())
    items = [
        _unquote(re.sub(r"^\s*-\s*", "", ln))
        for ln in lines[1:]
        if ln.lstrip().startswith("-")
    ]
    return tuple(items)  # block list


# --------------------------------------------------------------------------- #
# 2. What the model gets to see                                               #
# --------------------------------------------------------------------------- #


@lru_cache(maxsize=None)
def _site_categories(content_root: str) -> tuple:
    """Categories already used in the site, most frequent first (so the model reuses them).

    Looks at the front matter of the .md files below `content_root`.
    """
    counts = Counter()
    for n, md in enumerate(Path(content_root).rglob("*.md")):
        if n >= CATEGORY_SCAN_LIMIT:
            break
        try:
            with open(md, "r", encoding="utf-8", errors="ignore") as fh:
                head = fh.read(8000)  # the front matter is at the very top
        except OSError:
            continue
        block = _parse_blocks(_split_page(head.replace("\r\n", "\n"))[0]).get(
            "categories"
        )
        if block:
            value = _block_value(block)
            counts.update([value] if isinstance(value, str) else value)
    ranked = sorted(
        counts.items(), key=lambda kv: (-kv[1], kv[0])
    )  # most used first, ties alphabetical
    return tuple(name for name, _ in ranked[:40] if name)


def _known_categories(page) -> tuple:
    """Categories used elsewhere in the same Hugo site ('' if the page is not under .../content/)."""
    for parent in Path(page).resolve().parents:
        if parent.name == "content":
            return _site_categories(str(parent))
    return ()


def _article_digest(body: str, current_title: str, known_categories: tuple) -> str:
    """Build the text sent to the model: hints + headings + the start (and end) of the article."""
    headings = [
        m.group(1).strip() for m in re.finditer(r"^#{1,6}\s+(.+?)\s*#*\s*$", body, re.M)
    ]
    excerpt = body[:MAX_ARTICLE_CHARS]
    if len(body) > MAX_ARTICLE_CHARS + MAX_TAIL_CHARS:
        excerpt += "\n[...]\n" + body[-MAX_TAIL_CHARS:]
    elif len(body) > MAX_ARTICLE_CHARS:
        excerpt = body
    parts = []
    if current_title:
        parts.append(f"CURRENT TITLE (it may be generic or wrong): {current_title}")
    if known_categories:
        parts.append(
            "CATEGORIES ALREADY USED ON THE SITE: " + ", ".join(known_categories)
        )
    if headings:
        parts.append(
            "HEADINGS:\n" + "\n".join(f"- {h}" for h in headings[:MAX_HEADINGS])
        )
    parts.append("ARTICLE (Markdown):\n" + excerpt.strip())
    return "\n\n".join(parts)


# The instructions for the model. (If you prefer, move this dictionary to mymessages.py
# as `frontmatter` and call the helper with prompt="frontmatter".)
FRONTMATTER_PROMPT = {
    "role": "system",
    "content": (
        "You are the SEO editor of a website of programming, mathematics and technology tutorials "
        "written in English. You receive an article in Markdown plus a few hints. "
        "Reply with ONE JSON object and nothing else: no code fences, no comments. "
        "It must have exactly these keys:\n"
        '  "title": a clear, specific and attractive title for the article, at most 80 characters, '
        "no trailing period, no quotation marks around it;\n"
        '  "keywords": an array of 15 to 25 strings with the most important keywords and key phrases '
        "of the article, most important first; lowercase (except established spellings such as macOS), "
        "no duplicates, no hashtags, no colons;\n"
        '  "categories": an array of 2 to 4 short lowercase strings (one or two words). '
        "Choose from the categories already used on the site whenever they fit; "
        "invent a new one only if none fits;\n"
        '  "description": a meta description of 150 to 300 characters (one or two sentences, plain text, '
        "no quotation marks, no line breaks) saying what the reader will learn or build."
    ),
}


# --------------------------------------------------------------------------- #
# 3. Asking the model, and turning its answer into clean values               #
# --------------------------------------------------------------------------- #


def _extract_json(answer: str) -> dict:
    """Pull the JSON object out of the model's answer (models sometimes add fences or chatter)."""
    answer = re.sub(r"```(?:json)?", "", answer)
    start, end = answer.find("{"), answer.rfind("}")
    if start == -1 or end <= start:
        raise ValueError("the model did not return a JSON object")
    data = json.loads(answer[start : end + 1])
    if not isinstance(data, dict):
        raise ValueError("the model's JSON is not an object")
    return data


def _ask_model(digest: str) -> dict:
    """Ask Ollama (silently) for title/keywords/categories/description; retry once if the JSON is bad."""
    request, last_error = digest, None
    for attempt in range(2):
        answer = call_ollama(
            content=request,
            prompt=FRONTMATTER_PROMPT,
            temperature=0.3
            if attempt == 0
            else 0.1,  # low: we want consistent, boring output
            max_tokens=2000,
            show=False,  # do NOT print/clear: we print the result ourselves
        )
        try:
            return _extract_json(answer)
        except ValueError as exc:  # includes json.JSONDecodeError
            last_error = exc
            request = (
                digest
                + "\n\nYour previous answer was not valid JSON. Return ONLY the JSON object."
            )
    raise RuntimeError(f"could not get valid JSON from the model ({last_error})")


def _clean_text(value) -> str:
    """One line, single spaces, without wrapping quotes/backticks/asterisks."""
    text = " ".join(str(value).split())
    return text.strip("\"'`*“”‘’ ").strip()


def _as_list(value) -> list:
    """Accept a JSON array or a comma/newline separated string."""
    if isinstance(value, str):
        value = re.split(r"[,\n]", value)
    if not isinstance(value, (list, tuple)):
        return []
    return [str(v) for v in value]


def _clean_keywords(value) -> str:
    """-> 'a, b, c'   lowercase (macOS-style spellings kept), unique, no ':' or '#', limited."""
    seen, out = set(), []
    for raw in _as_list(value):
        kw = re.sub(r"[:#\"]", "", _clean_text(raw)).lstrip("-?!&*|>%@[]{}, ").strip()
        if not kw:
            continue
        if not re.match(
            r"^[a-z]+[A-Z]", kw
        ):  # keep 'macOS', 'iPhone'; lowercase the rest
            kw = kw.lower()
        if kw.lower() not in seen:
            seen.add(kw.lower())
            out.append(kw)
    if not out:
        raise ValueError("no keywords")
    return ", ".join(out[:MAX_KEYWORDS])


def _clean_categories(value, known: tuple) -> list:
    """Lowercase, unique, spelled like the site already spells them, at most MAX_CATEGORIES."""
    canonical = {k.lower(): k for k in known}
    seen, out = set(), []
    for raw in _as_list(value):
        cat = _clean_text(raw).lower()
        cat = canonical.get(cat, cat)
        if cat and cat not in seen:
            seen.add(cat)
            out.append(cat)
    if not out:
        raise ValueError("no categories")
    return out[:MAX_CATEGORIES]


def _clean_title(value) -> str:
    title = _clean_text(value).rstrip(".")
    if not title:
        raise ValueError("empty title")
    return title


def _clean_description(value) -> str:
    text = _clean_text(value)
    if not text:
        raise ValueError("empty description")
    if len(text) > 320:  # cut at the last sentence/word that fits
        cut = text[:320]
        text = (
            cut[: cut.rfind(". ") + 1]
            if cut.rfind(". ") > 150
            else cut[: cut.rfind(" ")].rstrip(",;:") + "."
        )
    return text


# --------------------------------------------------------------------------- #
# 4. Writing YAML                                                             #
# --------------------------------------------------------------------------- #

_PLAIN_BAD_START = set("-?:,[]{}#&*!|>'\"%@`")
_YAML_WORDS = {"yes", "no", "true", "false", "null", "on", "off", "~"}


def _quote(text: str) -> str:
    """Always "double quoted" (escapes backslashes and quotes)."""
    return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _scalar(text: str) -> str:
    """Plain YAML text when that is safe, "quoted" when it is not."""
    text = " ".join(text.split())
    unsafe = (
        not text
        or text[0] in _PLAIN_BAD_START
        or text.endswith(":")
        or ": " in text
        or " #" in text
        or text.lower() in _YAML_WORDS
        or re.fullmatch(r"[-+]?[\d.]+", text)
    )
    return _quote(text) if unsafe else text


# --------------------------------------------------------------------------- #
# 5. Building the proposed front matter                                       #
# --------------------------------------------------------------------------- #


def _comparable(value):
    """Normalise a value so '"x"' and 'x', or 'a, b' and ['a', 'b'], compare as equal."""
    if isinstance(value, str):
        value = [p for p in re.split(r",", value)] if "," in value else [value]
    return tuple(" ".join(str(v).split()).lower() for v in value if str(v).strip())


def _build_blocks(existing: dict, ai: dict, known_categories: tuple) -> list:
    """Return [(key, [lines], changed?)] in the order they will be printed."""
    today = datetime.date.today().isoformat()
    cfg = get_settings()
    author = cfg.author  # "" = not configured: the page's own author is left alone
    keywords = _clean_keywords(ai.get("keywords"))
    categories = _clean_categories(ai.get("categories"), known_categories)
    title = _clean_title(ai.get("title"))
    description = _clean_description(ai.get("description"))

    # (key, proposed lines, proposed value used to decide "is it different from today's page?")
    wanted = [
        ("keywords", [f"keywords: {_scalar(keywords)}"], keywords),
        ("language", [f"language: {LANGUAGE}"], LANGUAGE),
        ("title", [f"title: {_quote(title)}"], title),
        ("author", [f"author: {_scalar(author)}"], author),
        ("date", [f"date: {_quote(today)}"], today),
        (
            "categories",
            ["categories:"] + [f"- {_quote(c)}" for c in categories],
            tuple(categories),
        ),
        ("description", [f"description: {_scalar(description)}"], description),
    ]

    blocks = []
    for key, lines, value in wanted:
        if key == "author" and not author:
            if key in existing:  # AUTHOR not set in .env: keep the page's own, where it is
                blocks.append((key, existing[key], False))
            continue
        if key == "date" and KEEP_EXISTING_DATE and "date" in existing:
            blocks.append((key, existing[key], False))  # leave the page's date alone
            continue
        old = _block_value(existing[key]) if key in existing else None
        changed = old is None or _comparable(old) != _comparable(value)
        blocks.append((key, lines, changed))

    # featured_image and weight: keep the page's own, otherwise the defaults.
    # They are placed after categories and before description, as in your example.
    extras_mid = []
    for key, default in (
        (
            "featured_image",
            f"featured_image: {cfg.featured_image}" if cfg.featured_image else None,
        ),
        ("weight", f"weight: {DEFAULT_WEIGHT}"),
    ):
        if key in existing:
            extras_mid.append((key, existing[key], False))  # kept exactly as it is
        elif default:
            extras_mid.append((key, [default], True))  # missing: proposed default
        # else: no default configured (FEATURED_IMAGE not set): propose nothing
    order = [b[0] for b in blocks]
    insert_at = order.index("description")
    blocks[insert_at:insert_at] = extras_mid

    # Everything else the page already had (firstarticle, draft, series ...) is kept verbatim, at the end.
    known = {b[0] for b in blocks}
    for key, lines in existing.items():
        if key not in known:
            blocks.append((key, lines, False))
    return blocks


# --------------------------------------------------------------------------- #
# 6. Printing                                                                 #
# --------------------------------------------------------------------------- #


def _print_block(lines: list, changed: bool) -> None:
    """Print one field: the key in bold, the value red when it is new or different."""
    style = NEW_STYLE if changed else TEXT_STYLE
    for i, line in enumerate(lines):
        row = Text()
        m = _KEY_RE.match(line) if i == 0 else None
        if m:  # "key: value"  -> bold key + coloured value
            row.append(m.group(1) + ":", style=KEY_STYLE)
            row.append(m.group(2), style=style)
        else:  # list items and continuation lines
            row.append(line, style=style)
        console.print(row, soft_wrap=True)


def check_hugo_frontmatter(page) -> None:
    """Print the front matter that suits `page` (nothing is written anywhere).

    page: path of the .md file (Path or str).
    New or different values are printed in red; unchanged or kept values in the normal colour.
    """
    path = Path(page)
    text = _read(path)
    front, body = _split_page(text)
    existing = _parse_blocks(front)

    console.print(Text(str(path), style="bold"))
    if not body.strip():
        console.print(Text("This page has no content to analyse.", style=NEW_STYLE))
        return
    if not front:
        console.print(
            Text(
                "(the page has no front matter yet: this is a new proposal)",
                style=DIM_STYLE,
            )
        )

    # Ask the model once (a spinner is shown by call_ollama while we wait).
    known = _known_categories(path)
    current_title = _block_value(existing["title"]) if "title" in existing else ""
    digest = _article_digest(
        body, current_title if isinstance(current_title, str) else "", known
    )
    try:
        blocks = _build_blocks(existing, _ask_model(digest), known)
    except (RuntimeError, ValueError) as exc:
        console.print(Text(f"Could not build the front matter: {exc}", style=NEW_STYLE))
        return

    console.print(Text("---", style=DIM_STYLE))
    for _key, lines, changed in blocks:
        _print_block(lines, changed)
    console.print(Text("---", style=DIM_STYLE))
    console.print(
        Text(
            "red = new or different from the page now; normal colour = unchanged / kept as it is",
            style=DIM_STYLE,
        )
    )


if __name__ == "__main__":
    import sys

    if len(sys.argv) != 2:
        sys.exit("usage: python3 content_frontmatter.py page.md")
    check_hugo_frontmatter(Path(sys.argv[1]))
