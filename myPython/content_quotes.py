"""
content_quotes.py - provide_quotes(Path(page)): propose 2-3 quotes for an article.

    from content_quotes import provide_quotes
    provide_quotes(Path("/Volumes/MacDatosMaster/justtothepoint/content/calculus/lineintegralspace.md"))

Like check_latex(), it is READ-ONLY: it never touches the page. It prints the quotes (Rich),
in the same format as your fortunes file, so you can copy the ones you like:

    1  [file:tech]   matches: vector, field
       The first principle is that you must not fool yourself -- and you are the easiest
       person to fool.
           -- Richard Feynman

and returns them as a list of Quote objects.

What it reads (.env, see .env.example)
--------------------------------------
    TOPIC           technology, maths, humor, ...  or "auto" (taken from the page categories)
    NUMBER_QUOTES   how many quotes to propose (default 3)
    FORTUNES_PATH   your fortunes file or folder (no default: needed for the "file" source)
    QUOTE_SOURCES   where to look, in order of preference (default: file fortune)

Where quotes come from (QUOTE_SOURCES)
--------------------------------------
    file       FORTUNES_PATH: a file or a folder of files in the fortunes format
               (text, "    -- Author", and a line with just "%" between quotes).
               In a folder, the file whose NAME matches the topic is used (tech, maths, humor...).
    fortune    the system `fortune` command (macOS: brew install fortune). Its data files are read
               directly (much faster than running the command once per quote); the command is the fallback.
    library    the Python package `quotes-library` (pip install quotes-library; needs Python 3.11+)
    zenquotes  free online API, https://zenquotes.io  (internet; asks to credit them -> a note is printed)
    dummyjson  free online API, https://dummyjson.com (internet)
  Online sources are OFF by default: nothing goes to the internet unless you ask for it.
  A source that is missing or fails only prints a yellow note; the others keep working.

How the quotes are chosen (the "improvements")
----------------------------------------------
  1. Only quotes WITH an author (an anonymous cookie is a joke, not a quote for an article).
  2. Not too long (<= 6 lines / 420 characters) and not repeated.
  3. On-topic first: file name or key words must match TOPIC.
  4. Then the ones that share words with THIS page (title, headings, keywords, categories, text).
  5. Never a quote that already appears somewhere in your site (HUGO_ROOT/content), the page included,
     so every article gets fresh quotes and running the function twice gives new ones.
  6. At most one quote per author, and a bit of randomness among equals.

Nothing is cached or written on disk.
"""

from __future__ import annotations

import json
import os
import random
import re
import shutil
import subprocess
import textwrap
import urllib.request
from dataclasses import dataclass, replace
from pathlib import Path

from rich.console import Console
from rich.text import Text

from content_urls import USER_AGENT, front_len, make_ssl_context, read_lines
from myconfig import get_settings

# --------------------------------------------------------------------------- #
# Constants you may want to tweak                                              #
# --------------------------------------------------------------------------- #

MAX_LINES = 6  # a longer quote is a paragraph, not a quote
MAX_CHARS = 420
MIN_CHARS = 25  # "Be yourself." is not worth a blockquote
HTTP_TIMEOUT = 8  # seconds, for the online sources
REQUIRE_AUTHOR = True  # False = also accept anonymous fortunes
SKIP_EXTENSIONS = {
    ".dat",
    ".u8",
    ".idx",
    ".md",
    ".py",
    ".sh",
    ".json",
    ".bak",
    ".orig",
    ".swp",
}

console = Console()


# --------------------------------------------------------------------------- #
# The data: one Quote                                                          #
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class Quote:
    text: str  # the quote, lines separated by "\n"
    author: str = ""  # "Richard Feynman" ("" = unknown)
    source: str = (
        ""  # where it came from: "file:tech", "fortune:computers", "zenquotes"...
    )
    on_topic: bool = True  # does it match TOPIC (by file name or key words)?
    hits: tuple = ()  # words it shares with the page (shown as "matches: ...")
    score: float = 0.0  # ranking value, bigger = better

    def as_fortune(self) -> str:
        """The quote in YOUR format: text, then '    -- Author' (no final '%')."""
        out = self.text
        if self.author:
            out += f"\n    -- {self.author}"
        return out


# --------------------------------------------------------------------------- #
# Topics: what "technology" or "maths" means                                   #
# --------------------------------------------------------------------------- #
# aliases:  other names the user may type in TOPIC
# files:    names of fortune files (system or yours) that belong to the topic
# words:    key words; a quote containing one of them counts as on-topic
# The file names are those of the standard fortune-mod package; a missing one is simply ignored.

TOPICS = {
    "technology": dict(
        aliases=(
            "tech",
            "computing",
            "computers",
            "computer",
            "programming",
            "coding",
            "software",
        ),
        files=(
            "computers",
            "tech",
            "technology",
            "perl",
            "linuxcookie",
            "debian",
            "programming",
        ),
        words=(
            "computer",
            "software",
            "program",
            "code",
            "bug",
            "hardware",
            "algorithm",
            "data",
            "network",
            "internet",
            "technology",
            "machine",
            "digital",
            "unix",
            "linux",
            "debug",
        ),
    ),
    "maths": dict(
        aliases=("math", "mathematics", "mathematical"),
        files=(
            "maths",
            "math",
            "mathematics",
            "goedel",
            "paradoxum",
            "science",
            "definitions",
        ),
        words=(
            "math",
            "number",
            "theorem",
            "proof",
            "prove",
            "equation",
            "geometry",
            "algebra",
            "calculus",
            "infinity",
            "infinite",
            "logic",
            "zero",
            "prime",
            "integral",
            "function",
            "triangle",
        ),
    ),
    "science": dict(
        aliases=("physics", "scientific"),
        files=("science", "physics", "goedel", "paradoxum"),
        words=(
            "science",
            "scientist",
            "physics",
            "experiment",
            "nature",
            "universe",
            "theory",
            "atom",
        ),
    ),
    "humor": dict(
        aliases=("humour", "funny", "jokes", "joke", "humorists"),
        files=("humor", "humour", "humorists", "funny", "jokes", "fortunes"),
        words=(
            "laugh",
            "joke",
            "funny",
            "humor",
            "humour",
            "absurd",
            "silly",
            "comedy",
        ),
    ),
    "wisdom": dict(
        aliases=("philosophy", "life", "inspiration", "motivation"),
        files=("wisdom", "tao", "platitudes", "literature", "philosophy"),
        words=(
            "wisdom",
            "wise",
            "truth",
            "mind",
            "life",
            "happiness",
            "courage",
            "learn",
        ),
    ),
    "education": dict(
        aliases=("learning", "teaching", "school"),
        files=("education", "learning"),
        words=(
            "learn",
            "teach",
            "student",
            "school",
            "education",
            "knowledge",
            "study",
            "ignorance",
        ),
    ),
}


@dataclass(frozen=True)
class Topic:
    """A resolved TOPIC. `name == ""` means "no topic": every quote is on-topic."""

    name: str = ""
    files: frozenset = frozenset()
    words: frozenset = frozenset()

    @property
    def active(self) -> bool:
        return bool(self.name)

    def matches_file(self, stem: str) -> bool:
        stem = stem.lower()
        return self.active and (
            stem in self.files or any(len(f) >= 4 and f in stem for f in self.files)
        )

    def matches_text(self, text: str) -> bool:
        low = text.lower()
        return self.active and any(w in low for w in self.words)


def resolve_topic(raw: str, page_text: str = "") -> Topic:
    """'Technology' / 'tech' / 'chess' / 'auto' -> Topic.

    A known name or alias gives its file names and key words. An unknown word ('chess') is
    still useful: it is looked for as a file name and as a key word. 'auto' picks the first known
    topic whose name or alias appears in the page's categories/keywords (the `page_text`).
    """
    raw = (raw or "").strip().lower()
    if raw in ("", "any", "all", "none"):
        return Topic()
    if raw == "auto":
        low = page_text.lower()
        for name, info in TOPICS.items():
            if any(
                re.search(rf"\b{re.escape(w)}", low) for w in (name, *info["aliases"])
            ):
                return resolve_topic(name)
        return Topic()
    for name, info in TOPICS.items():
        if raw == name or raw in info["aliases"]:
            return Topic(
                name, frozenset(info["files"]) | {name}, frozenset(info["words"])
            )
    return Topic(raw, frozenset({raw}), frozenset({raw}))


# --------------------------------------------------------------------------- #
# Reading the fortunes format                                                  #
# --------------------------------------------------------------------------- #

# A last line like "    -- Richard Feynman", "-- Mark Twain, Pudd'nhead Wilson" or "— Einstein".
_AUTHOR_LINE = re.compile(r"^\s*(?:--+|—|―|–)\s*(\S.*?)\s*$")
_SEPARATOR = re.compile(r"(?m)^%\s*$")  # a line with just "%"


def parse_fortunes(raw: str, source: str = "") -> list:
    """Split the content of a fortunes file into Quote objects.

        The first principle is that you must not fool yourself ...
            -- Richard Feynman
        %
        Next quote...

    The text keeps its original line breaks (poems and code stay readable).
    """
    quotes = []
    for block in _SEPARATOR.split(raw.replace("\r\n", "\n").replace("\r", "\n")):
        lines = [ln.rstrip() for ln in block.split("\n")]
        while lines and not lines[0].strip():
            lines.pop(0)
        while lines and not lines[-1].strip():
            lines.pop()
        if not lines:
            continue
        author = ""
        match = _AUTHOR_LINE.match(lines[-1]) if len(lines) > 1 else None
        if match:
            author = match.group(1)
            lines.pop()
            while lines and not lines[-1].strip():
                lines.pop()
        text = textwrap.dedent("\n".join(lines)).strip("\n")
        if text.strip():
            quotes.append(Quote(text=text, author=author, source=source))
    return quotes


def _read_fortune_file(path: Path):
    """The text of a fortunes file, or None when it is unreadable or binary (e.g. a .dat index)."""
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            raw = fh.read()
    except OSError:
        return None
    return None if "\0" in raw else raw


def _fortune_files(folder: Path) -> list:
    """The fortune data files of a folder (not recursive: the 'off/' folder of fortune is rot13-coded)."""
    try:
        entries = sorted(folder.iterdir())
    except OSError:
        return []
    return [
        p
        for p in entries
        if p.is_file()
        and not p.name.startswith(".")
        and p.suffix.lower() not in SKIP_EXTENSIONS
    ]


def _quotes_from_files(files: list, topic: Topic, label: str) -> list:
    """Read fortune files and mark which quotes are on-topic.

    If some FILE NAMES match the topic (tech.txt for 'technology'), only those are read and all
    their quotes are on-topic. Otherwise every file is read and each quote is on-topic only if
    it contains one of the topic's key words.
    """
    named = [f for f in files if topic.matches_file(f.stem)]
    chosen = named or files
    quotes = []
    for path in chosen:
        raw = _read_fortune_file(path)
        if raw is None:
            continue
        for quote in parse_fortunes(raw, f"{label}:{path.stem}"):
            on_topic = (
                (not topic.active) or bool(named) or topic.matches_text(quote.text)
            )
            quotes.append(replace(quote, on_topic=on_topic))
    return quotes


# --------------------------------------------------------------------------- #
# Sources. Each one:  (settings, topic, notes) -> list of Quote                #
# `notes` is a list the source appends (level, message) to; they are printed.  #
# --------------------------------------------------------------------------- #


def _source_file(cfg, topic, notes) -> list:
    """Your fortunes file or folder (FORTUNES_PATH)."""
    path = cfg.fortunes_path
    if path is None:
        notes.append(("warn", "file: FORTUNES_PATH is not set in .env"))
        return []
    if not path.exists():
        notes.append(("warn", f"file: {path} does not exist (FORTUNES_PATH in .env)"))
        return []
    files = [path] if path.is_file() else _fortune_files(path)
    quotes = _quotes_from_files(files, topic, "file")
    if not quotes:
        notes.append(("warn", f"file: no quotes found in {path}"))
    return quotes


def _find_fortune_command():
    """Path of the `fortune` program (also where Homebrew puts it, in case PATH is short)."""
    found = shutil.which("fortune")
    if found:
        return found
    for folder in ("/opt/homebrew/bin", "/usr/local/bin", "/usr/games", "/usr/bin"):
        candidate = os.path.join(folder, "fortune")
        if os.access(candidate, os.X_OK):
            return candidate
    return None


def _run(args: list, timeout: float = 10.0) -> str:
    """Run a command; stdout and stderr together ('fortune -f' prints its list on stderr)."""
    done = subprocess.run(
        args,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        universal_newlines=True,
        timeout=timeout,
    )
    return done.stdout


_LIST_LINE = re.compile(r"^\s*\d+(?:\.\d+)?%\s+(.+?)\s*$")


def _fortune_directory(listing: str):
    """From the output of `fortune -f`  ('100.00% /opt/.../share/games/fortunes' + indented
    '  12.5% computers' lines) get the folder holding the data files, or None."""
    for line in listing.splitlines():
        match = _LIST_LINE.match(line)
        if match and match.group(1).startswith("/"):
            return Path(match.group(1))
    return None


def _source_fortune(cfg, topic, notes) -> list:
    """The system `fortune` command and its database."""
    exe = _find_fortune_command()
    if not exe:
        notes.append(
            (
                "warn",
                "fortune: command not found (install it with: brew install fortune)",
            )
        )
        return []
    try:
        listing = _run([exe, "-f"])
    except (OSError, subprocess.SubprocessError) as exc:
        notes.append(("warn", f"fortune: could not run {exe} ({exc})"))
        return []
    folder = _fortune_directory(listing)
    if folder and folder.is_dir():
        quotes = _quotes_from_files(_fortune_files(folder), topic, "fortune")
        if quotes:
            return quotes
    # Fallback: ask the command itself, a handful of times (slower, fewer quotes).
    categories = sorted(
        f for f in topic.files if re.search(rf"\b{re.escape(f)}\b", listing)
    ) or [""]
    quotes = []
    for _ in range(12):
        for category in categories:
            try:
                out = _run(
                    [exe, "-n", str(MAX_CHARS), *([category] if category else [])],
                    timeout=5.0,
                )
            except (OSError, subprocess.SubprocessError):
                continue
            quotes += [
                replace(
                    q,
                    source=f"fortune:{category or 'all'}",
                    on_topic=bool(category) or topic.matches_text(q.text),
                )
                for q in parse_fortunes(out)
            ]
    if not quotes:
        notes.append(("warn", "fortune: the command gave no usable quotes"))
    return quotes


def _http_json(url: str):
    """GET a URL and decode the JSON (raises on any problem; callers catch it)."""
    request = urllib.request.Request(
        url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"}
    )
    https = urllib.request.HTTPSHandler(context=make_ssl_context())
    opener = urllib.request.build_opener(https)
    with opener.open(request, timeout=HTTP_TIMEOUT) as response:
        return json.loads(response.read().decode("utf-8", errors="replace"))


# The two online endpoints can be changed here (the tests point them to a fake server).
ZENQUOTES_URL = (
    "https://zenquotes.io/api/quotes"  # returns 50 random quotes: [{"q":..., "a":...}]
)
DUMMYJSON_URL = "https://dummyjson.com/quotes"  # {"quotes":[{"quote":..., "author":...}], "total": N}


def _online_quote(text, author, source, topic) -> Quote:
    return Quote(
        text=str(text).strip(),
        author=str(author).strip(),
        source=source,
        on_topic=(not topic.active) or topic.matches_text(str(text)),
    )


def _source_zenquotes(cfg, topic, notes) -> list:
    """ZenQuotes: 50 random quotes per request. They ask for attribution and ~5 requests / 30 s."""
    try:
        data = _http_json(ZENQUOTES_URL)
        quotes = [
            _online_quote(item["q"], item["a"], "zenquotes", topic)
            for item in data
            if isinstance(item, dict)
            and item.get("q")
            and item.get("a") != "zenquotes.io"
        ]  # "zenquotes.io" = their rate-limit message
    except Exception as exc:  # network, JSON, structure: all just a note
        notes.append(("warn", f"zenquotes: {type(exc).__name__}: {exc}"))
        return []
    if quotes:
        notes.append(
            (
                "info",
                "Quotes provided by ZenQuotes API (https://zenquotes.io), please credit them.",
            )
        )
    else:
        notes.append(
            (
                "warn",
                "zenquotes: no quotes (rate limit reached? try again in 30 seconds)",
            )
        )
    return quotes


def _source_dummyjson(cfg, topic, notes) -> list:
    """DummyJSON: ~1400 quotes; we ask for a random page of 50."""
    try:
        first = _http_json(f"{DUMMYJSON_URL}?limit=1")
        total = int(first.get("total", 0))
        skip = random.randint(0, max(0, total - 50)) if total else 0
        data = _http_json(f"{DUMMYJSON_URL}?limit=50&skip={skip}")
        return [
            _online_quote(item["quote"], item["author"], "dummyjson", topic)
            for item in data["quotes"]
            if item.get("quote") and item.get("author")
        ]
    except Exception as exc:
        notes.append(("warn", f"dummyjson: {type(exc).__name__}: {exc}"))
        return []


def _coerce(item, source: str, topic: Topic):
    """Turn whatever a library returns (dict or 'text - author') into a Quote, or None."""
    if isinstance(item, dict):
        text = item.get("quote") or item.get("text") or item.get("q") or ""
        author = item.get("author") or item.get("a") or ""
    elif isinstance(item, str) and " - " in item:
        text, author = item.rsplit(" - ", 1)
    else:
        return None
    return _online_quote(text, author, source, topic) if str(text).strip() else None


def _source_library(cfg, topic, notes) -> list:
    """The `quotes-library` Python package (offline database, ~500k quotes, 100+ categories).

    Documented API (PyPI page): get_quotes(category=None, author=None, count=None, random=False),
    get_categories(); every answer is a dict {"data": ..., "status_code": ..., "status_text": ...}.
    The module name and the shape of each item are not documented, so several are tried.
    """
    module = None
    for name in ("quotes_library", "quotes"):
        try:
            module = __import__(name)
            if hasattr(module, "get_quotes"):
                break
            module = None
        except ImportError:
            continue
    if module is None:
        notes.append(
            (
                "warn",
                "library: quotes-library is not installed (pip install quotes-library; Python 3.11+)",
            )
        )
        return []
    try:
        wanted = {topic.name, *topic.files} if topic.active else set()
        category = None
        if wanted and hasattr(module, "get_categories"):
            answer = module.get_categories()
            names = answer.get("data", []) if isinstance(answer, dict) else answer
            names = [
                n if isinstance(n, str) else (n.get("name") or n.get("category") or "")
                for n in names
            ]
            category = next((n for n in names if n.lower() in wanted), None)
        answer = module.get_quotes(category=category, count=60, random=True)
        items = answer.get("data", []) if isinstance(answer, dict) else answer
        if isinstance(items, dict):
            items = [items]
        quotes = [
            q
            for q in (_coerce(i, f"library:{category or 'any'}", topic) for i in items)
            if q
        ]
        if category:
            quotes = [replace(q, on_topic=True) for q in quotes]
        return quotes
    except Exception as exc:
        notes.append(("warn", f"library: {type(exc).__name__}: {exc}"))
        return []


SOURCES = {
    "file": _source_file,
    "fortune": _source_fortune,
    "library": _source_library,
    "zenquotes": _source_zenquotes,
    "dummyjson": _source_dummyjson,
}


# --------------------------------------------------------------------------- #
# Reading the page: which words describe it?                                   #
# --------------------------------------------------------------------------- #

_STOPWORDS = frozenset(
    """
about above after again against being below between both could does doing down during each from further
have having here itself just more most other over same should some such than that their them then there these
they this those through under until very were what when where which while will with would your yours into
also only once been because before cannot like make many much must never often often shall since still
""".split()
)
_NOISY_FRONT_MATTER = frozenset(
    {
        "date",
        "weight",
        "featured_image",
        "author",
        "language",
        "url",
        "slug",
        "draft",
        "firstarticle",
        "layout",
        "type",
        "image",
        "lastmod",
    }
)
_WORD = re.compile(r"[^\W\d_]{4,}", re.UNICODE)


def _stem(word: str) -> str:
    """A crude stem so 'integrals' matches 'integral' and 'proving' matches 'prove'."""
    word = word.lower()
    for suffix in ("ing", "ed", "es", "s"):
        if len(word) > len(suffix) + 3 and word.endswith(suffix):
            return word[: -len(suffix)]
    return word


def _words(text: str) -> list:
    return [w for w in (_stem(m) for m in _WORD.findall(text)) if w not in _STOPWORDS]


def page_profile(page: Path):
    """Read a page and return (weights, front_matter_text).

    weights: {stem: weight}; title/keywords/categories words count 3, headings 2, body text 1.
    front_matter_text: the useful front matter, used to guess TOPIC=auto.
    """
    lines = read_lines(page)
    n = front_len(lines)
    weights: dict = {}

    def add(text: str, weight: int):
        for w in _words(text):
            weights[w] = max(weights.get(w, 0), weight)

    front, key = [], ""
    for ln in lines[1 : n - 1] if n else []:
        m = re.match(r"^([A-Za-z_][\w-]*)\s*:(.*)$", ln)
        if m:
            key = m.group(1).lower()
        if key not in _NOISY_FRONT_MATTER:
            front.append(m.group(2) if m else ln)
    front_text = " ".join(front)
    add(front_text, 3)
    in_fence = False
    body_chars = 0
    for ln in lines[n:]:
        if ln.lstrip().startswith(("```", "~~~")):
            in_fence = not in_fence
            continue
        if in_fence or not ln.strip():
            continue
        if ln.startswith("#"):
            add(ln.lstrip("# "), 2)
        elif body_chars < 6000:  # the beginning of the article is enough
            add(re.sub(r"[`$*_\[\]()<>{}\\|]", " ", ln), 1)
            body_chars += len(ln)
    return weights, front_text


# --------------------------------------------------------------------------- #
# "Have I already used it?"                                                    #
# --------------------------------------------------------------------------- #


def _fingerprint(text: str) -> str:
    """Letters and digits only, lower case: survives re-wrapping, quotes, markdown marks."""
    return re.sub(r"[\W_]+", "", text.lower())


def _site_text(root) -> str:
    """All the .md files of HUGO_ROOT/content as one fingerprint string ('' if unavailable)."""
    if not root:
        return ""
    content = Path(root) / "content"
    parts = []
    if content.is_dir():
        for path in content.rglob("*.md"):
            try:
                with open(path, "r", encoding="utf-8", errors="replace") as fh:
                    parts.append(_fingerprint(fh.read()))
            except OSError:
                continue
    return "\0".join(parts)


def _already_used(quote: Quote, site: str) -> bool:
    key = _fingerprint(quote.text)[:60]  # the beginning is enough and survives edits
    return len(key) >= 20 and key in site


# --------------------------------------------------------------------------- #
# Choosing                                                                     #
# --------------------------------------------------------------------------- #


def acceptable(quote: Quote) -> bool:
    """Is it a good length and (by default) does it have an author?"""
    text = quote.text.strip()
    if REQUIRE_AUTHOR and not quote.author:
        return False
    if (
        len(text) < MIN_CHARS
        or len(text) > MAX_CHARS
        or text.count("\n") + 1 > MAX_LINES
    ):
        return False
    return not any(tag in text.lower() for tag in ("<html", "http://", "https://"))


def rank(quotes: list, weights: dict, rng) -> list:
    """Score every quote and return them best first.

    score = 10 if on-topic  +  (page words it shares, weighted, max 6)  +  a little randomness
    The topic dominates; the page words decide among on-topic quotes; the randomness decides among equals.
    """
    ranked = []
    for quote in quotes:
        shown = {}  # stem -> the word as written in the quote
        for word in _WORD.findall(quote.text + " " + quote.author):
            stem = _stem(word)
            if stem in weights and stem not in _STOPWORDS:
                shown.setdefault(stem, word.lower())
        relevance = min(6.0, sum(weights[s] for s in shown) / 2)
        score = (10.0 if quote.on_topic else 0.0) + relevance + rng.random() * 0.9
        ranked.append(
            replace(quote, hits=tuple(sorted(shown.values()))[:5], score=score)
        )
    return sorted(ranked, key=lambda q: -q.score)


def choose(ranked: list, count: int, site: str = "") -> list:
    """The best `count` quotes: not used before, no repeated text, one per author when possible."""
    picked, seen_text, seen_author = [], set(), set()
    for strict in (True, False):  # 2nd round relaxes "one per author"
        for quote in ranked:
            if len(picked) >= count:
                return picked
            key = _fingerprint(quote.text)
            if key in seen_text or _already_used(quote, site):
                continue
            author = quote.author.lower()
            if strict and author and author in seen_author:
                continue
            picked.append(quote)
            seen_text.add(key)
            seen_author.add(author)
    return picked


# --------------------------------------------------------------------------- #
# The function you call                                                        #
# --------------------------------------------------------------------------- #


def provide_quotes(page, count=None, topic=None, sources=None, rng=None) -> list:
    """Print `count` quotes suited to `page` and return them (a list of Quote). Writes nothing.

    page:    path of the .md file (Path or str).
    count:   how many (default NUMBER_QUOTES in .env).
    topic:   overrides TOPIC in .env ("technology", "maths", "humor", "auto", "" = any).
    sources: overrides QUOTE_SOURCES, e.g. ("file",) or ("file", "zenquotes").
    rng:     a random.Random, only for tests (to get repeatable results).
    """
    cfg = get_settings()
    page = Path(page)
    rng = rng or random.Random()
    count = count or cfg.number_quotes
    sources = tuple(sources) if sources is not None else cfg.quote_sources
    try:
        weights, front_text = page_profile(page)
    except OSError as exc:
        console.print(Text(f"cannot read {page}: {exc}", style="red"))
        return []
    topic_obj = resolve_topic(cfg.topic if topic is None else topic, front_text)

    # 1. Collect candidates from every source, remembering what went wrong with each.
    notes, candidates, used = [], [], []
    for name in sources:
        func = SOURCES.get(name)
        if func is None:
            notes.append(
                (
                    "warn",
                    f"unknown source {name!r} in QUOTE_SOURCES (valid: {', '.join(SOURCES)})",
                )
            )
            continue
        found = [q for q in func(cfg, topic_obj, notes) if acceptable(q)]
        if found:
            used.append(f"{name} ({len(found)})")
        candidates += found

    # 2. Rank and choose.
    chosen = choose(rank(candidates, weights, rng), count, _site_text(cfg.hugo_root))

    # 3. Print.
    header = Text()
    header.append(f"{len(chosen)} quote(s) for {page.name}", style="bold")
    header.append(f"   topic: {topic_obj.name or 'any'}", style="dim")
    header.append(f"   from: {', '.join(used) or 'nothing'}", style="dim")
    console.print(header)
    for level, message in notes:
        console.print(
            Text(
                f"  {'!' if level == 'warn' else 'i'} {message}",
                style="yellow" if level == "warn" else "dim",
            )
        )
    if topic_obj.active and chosen and not all(q.on_topic for q in chosen):
        console.print(
            Text(
                f"  ! fewer than {count} quotes match the topic {topic_obj.name!r}; the rest are general",
                style="yellow",
            )
        )
    if not chosen:
        console.print(Text("  no quotes to propose (see the notes above)", style="red"))
        return []
    for number, quote in enumerate(chosen, 1):
        tag = Text(f"\n{number:>3}  ", style="bold")
        tag.append(f"[{quote.source}]", style="cyan")
        if quote.hits:
            tag.append("  matches: " + ", ".join(quote.hits), style="dim")
        console.print(tag)
        console.print(Text(textwrap.indent(quote.text, "     "), style="italic"))
        if quote.author:
            console.print(Text(f"         -- {quote.author}", style="bold green"))
    return chosen


def daily_quote(sources=None, rng=None):
    """Pick ONE random quote for the daily dashboard (no page needed). Returns a Quote or None.

    Uses the same sources as provide_quotes (QUOTE_SOURCES), any topic, and the same
    length/author filter, but it does not avoid quotes already used in the site and it
    prints nothing: the caller decides how to show it. Use pick_daily_quote() to also
    get the notes explaining why a source failed.
    """
    quote, _ = pick_daily_quote(sources, rng)
    return quote


def pick_daily_quote(sources=None, rng=None):
    """Like daily_quote, but returns (Quote or None, notes) so callers can explain a failure."""
    cfg = get_settings()
    rng = rng or random.Random()
    sources = tuple(sources) if sources is not None else cfg.quote_sources
    notes, candidates = [], []
    for name in sources:
        func = SOURCES.get(name)
        if func is None:
            notes.append(("warn", f"unknown source {name!r} in QUOTE_SOURCES (valid: {', '.join(SOURCES)})"))
            continue
        try:
            candidates += [q for q in func(cfg, Topic(), notes) if acceptable(q)]
        except Exception as exc:  # a broken source must never break the dashboard
            notes.append(("warn", f"source {name!r} failed ({type(exc).__name__})"))
    return (rng.choice(candidates) if candidates else None), notes


if __name__ == "__main__":
    import sys

    if len(sys.argv) != 2:
        sys.exit("usage: python3 content_quotes.py page.md")
    provide_quotes(sys.argv[1])
