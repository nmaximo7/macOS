"""
mysearx.py - search the web through YOUR OWN SearXNG, from Python, the terminal or Raycast.

SELF-CONTAINED: this file needs nothing but the Python standard library (3.9+). It does not
import any other file of the toolkit, so you can copy this single file anywhere (a Raycast
script folder, another project) and it works. The Docker side (install, start, stop) is the
companion shell script `searx.sh`; this module calls it when you ask it to.

What is SearXNG?
----------------
A "metasearch engine" you run yourself: you ask it one question and it asks Google, Bing,
DuckDuckGo, Wikipedia... for you, merges the answers and returns them WITHOUT trackers.
It runs in Docker on http://127.0.0.1:8080 (only this Mac can reach it).

Quick tour
----------
    from mysearx import search, build_query

    answer = search("faraday law of induction")           # needs SearXNG running
    for r in answer.results:
        print(r.title, r.url, r.snippet)

    # Start Docker + SearXNG only for the time you need it, stop it afterwards:
    from mysearx import running
    with running():                                       # starts it if it is not running
        answer = search("rust ownership", limit=5)
    # ... and here it is stopped again (only if THIS block started it)

    python3 mysearx.py "rust ownership" --limit 5          # from the terminal
    python3 mysearx.py "rust ownership" --json             # machine-readable (Raycast...)
    python3 mysearx.py --status | --start | --stop         # manage the container

Public API
----------
    search(query, ...)        -> SearxResponse   one HTTP request; raises SearxError
    gather(queries, ...)      -> SearxResponse   MANY searches (query variants x pages), merged,
                                                 plus the text of the best pages (deep research)
    build_queries(title, ...) -> list            several query variants from one page title
    build_query(title, tags)  -> str             a good search query from a page title
    is_up()                   -> bool            does SearXNG answer?
    start() / stop()                             run `searx.sh start|stop`
    ensure_running()          -> bool            start if needed; True if WE started it
    running()                                    context manager: start, yield, stop
    as_context(response)      -> str             compact text for an AI prompt
    format_results(response)  -> str             human-readable list

Settings (environment variables, or lines in the `.env` file next to this module; a real
environment variable wins over `.env`). All optional:

    SEARX_URL            where SearXNG listens                       http://127.0.0.1:8080
    SEARX_TIMEOUT        seconds to wait for one search              30
    SEARX_RESULTS        how many results to keep                    8
    SEARX_LANGUAGE       "en", "es", "all"...  ("" = SearXNG's own default)
    SEARX_CATEGORIES     general, it, science, news ... comma list   general
    SEARX_ENGINES        restrict to engines: "wikipedia,duckduckgo" (empty = all enabled)
    SEARX_TIME_RANGE     day, week, month, year  ("" = any time)
    SEARX_EXCLUDE        domains to drop from the results (your own site!), comma list
    SEARX_QUERIES        deep research: how many query variants to search       4   (1-8)
    SEARX_PAGES          deep research: result pages per query                  2   (1-5)
    SEARX_FETCH          1 = also DOWNLOAD the best pages and keep their text   1
    SEARX_FETCH_PAGES    how many pages to download                             8   (0-30)
    SEARX_FETCH_CHARS    text kept from each downloaded page                    4000
    SEARX_CONTEXT_CHARS  size of the research text handed to the AI model       30000
    SEARX_DELAY          seconds between two searches (engines block fast ones) 1.0
    SEARX_AUTOSTART      1 = start Docker/SearXNG when it is not running     1
    SEARX_AUTOSTOP       1 = stop it afterwards, only when WE started it     1
                         always = stop it afterwards EVERY time, even if it was already
                         running (start it by hand with searx.sh when you want it kept)
                         0 = never stop it
    SEARX_RESTART        1 = when SearXNG will not start (or stops answering), force-quit and
                         relaunch Docker Desktop NO MATTER WHAT it is doing, then try again    1
    SEARX_QUIT_DOCKER    1 = also quit Docker Desktop, only when WE launched it   1
                         always = quit Docker Desktop every time (it still stays open
                         when other containers are running in it); 0 = never quit it
    SEARX_SCRIPT         path of searx.sh (default: ../scripts/searx.sh next to this
                         folder, then ~/macOS/scripts/searx.sh, then next to this file)

Privacy: the SEARCH QUERIES leave your Mac through SearXNG, which forwards them to the search
engines without your IP address or cookies. With SEARX_FETCH=1 (the default of deep research)
this module also DOWNLOADS the best result pages directly from your Mac, so those sites see
your IP address like any visit from a browser. Set SEARX_FETCH=0 to avoid that: you then get
titles, snippets and URLs only. Private addresses (localhost, 192.168.x.x...) are never fetched.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import contextlib
import html
import ipaddress
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import time
from dataclasses import dataclass, field
from html.parser import HTMLParser
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse
from urllib.request import Request, urlopen

# --------------------------------------------------------------------------- #
# Constants                                                                   #
# --------------------------------------------------------------------------- #

DEFAULT_URL = "http://127.0.0.1:8080"
DEFAULT_TIMEOUT = 30.0
DEFAULT_LIMIT = 8
MAX_LIMIT = 50
MAX_QUERY_CHARS = 400  # search engines ignore the rest anyway
MAX_SNIPPET_CHARS = 500
MAX_RESPONSE_BYTES = 5_000_000  # never read more than this from the server
TIME_RANGES = ("", "day", "week", "month", "year")
USER_AGENT = "mysearx/1.0 (+local SearXNG client)"
ENV_FILE = Path(__file__).resolve().parent / ".env"

DEFAULT_QUERIES, MAX_QUERIES = 4, 8  # deep research: query variants
DEFAULT_PAGES, MAX_PAGES = 2, 5  # deep research: result pages per query
DEFAULT_FETCH_PAGES, MAX_FETCH_PAGES = 8, 30  # pages downloaded for their text
DEFAULT_FETCH_CHARS = 4_000  # text kept per downloaded page
DEFAULT_CONTEXT_CHARS = 30_000  # research text for the AI model
DEFAULT_DELAY = 1.0  # seconds between searches
FETCH_TIMEOUT = 15.0
MAX_PAGE_BYTES = 1_500_000  # never read more than this from one web page
FETCH_WORKERS = 4
BROWSER_UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15"
QUERY_SUFFIXES = ("tutorial", "examples", "explained", "guide", "how it works", "documentation", "best practices")

START_TIMEOUT = 420  # first start downloads the image and may boot Docker: be patient
STOP_TIMEOUT = 120
RESET_TIMEOUT = START_TIMEOUT + 180  # force-quit Docker, launch it again, start SearXNG


class SearxError(RuntimeError):
    """Any expected problem. The message says what to do next."""


class SearxNotRunning(SearxError):
    """SearXNG does not answer (container stopped, Docker not running, wrong URL)."""


# --------------------------------------------------------------------------- #
# 1. Settings                                                                 #
# --------------------------------------------------------------------------- #


def _dotenv_values(path: Path = ENV_FILE) -> dict:
    """Read KEY=VALUE lines of a .env file (a tiny parser: no python-dotenv needed).

    Understands comments, blank lines, `export KEY=...`, "double" and 'single' quotes and
    a trailing ` # comment` on unquoted values. Anything else is ignored.
    """
    values = {}
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return values
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        if line.startswith("export "):
            line = line[7:].lstrip()
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip()
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key):
            continue
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        else:
            value = re.split(r"\s+#", value)[0].strip()
        values[key] = value
    return values


def _get(name: str, default: str = "", dotenv: "dict | None" = None) -> str:
    """Environment variable first, then the .env file, then `default`."""
    if name in os.environ and os.environ[name].strip():
        return os.environ[name].strip()
    return (dotenv if dotenv is not None else _dotenv_values()).get(name, "").strip() or default


def _truthy(raw: str, default: bool) -> bool:
    raw = raw.strip().lower()
    if not raw:
        return default
    return raw in ("1", "true", "yes", "on", "y")


def _mode(raw: str, default: bool) -> tuple:
    """(enabled, always) for a setting that accepts 1/0/yes/no/... or the word `always`."""
    if raw.strip().lower() == "always":
        return True, True
    return _truthy(raw, default), False


def _number(name: str, raw: str, default, cast):
    if not raw:
        return default
    try:
        return cast(raw)
    except ValueError:
        raise SearxError(f"{name} must be a number, got {raw!r}") from None


def normalize_url(raw: str) -> str:
    """'127.0.0.1:8080/' -> 'http://127.0.0.1:8080'  (scheme added, final '/' removed)."""
    raw = (raw or "").strip().strip("\"'").rstrip("/")
    if not raw:
        return DEFAULT_URL
    if "://" not in raw:
        raw = "http://" + raw
    parsed = urlparse(raw)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise SearxError(f"SEARX_URL must be an http(s) address, got {raw!r}")
    return raw


def _csv(raw: str) -> tuple:
    return tuple(p.strip() for p in raw.replace(" ", ",").split(",") if p.strip())


@dataclass(frozen=True)
class SearxConfig:
    """Every setting in one read-only object (see the module docstring)."""

    url: str = DEFAULT_URL
    timeout: float = DEFAULT_TIMEOUT
    limit: int = DEFAULT_LIMIT
    language: str = ""
    categories: str = "general"
    engines: str = ""
    time_range: str = ""
    exclude: tuple = ()
    autostart: bool = True
    autostop: bool = True
    stop_always: bool = False  # SEARX_AUTOSTOP=always: stop it even when it was already running
    quit_docker: bool = True
    quit_docker_always: bool = False  # SEARX_QUIT_DOCKER=always: quit Docker Desktop every time
    restart_on_fail: bool = True  # SEARX_RESTART: when SearXNG will not start, force-restart Docker
    script: "Path | None" = None
    queries: int = DEFAULT_QUERIES  # deep research: query variants
    pages: int = DEFAULT_PAGES  # deep research: result pages per query
    fetch: bool = True  # download the best pages and keep their text
    fetch_pages: int = DEFAULT_FETCH_PAGES
    fetch_chars: int = DEFAULT_FETCH_CHARS
    context_chars: int = DEFAULT_CONTEXT_CHARS
    delay: float = DEFAULT_DELAY

    @property
    def port(self) -> int:
        """Port of `url` (80/443 when not written)."""
        parsed = urlparse(self.url)
        return parsed.port or (443 if parsed.scheme == "https" else 80)

    @property
    def is_local(self) -> bool:
        """True when SearXNG is on THIS Mac (only then can we start/stop it)."""
        return (urlparse(self.url).hostname or "") in ("127.0.0.1", "localhost", "::1")


def load_config() -> SearxConfig:
    """Build the configuration from the environment (and the .env next to this file)."""
    env = _dotenv_values()

    def get(name, default=""):
        return _get(name, default, env)

    time_range = get("SEARX_TIME_RANGE").lower()
    if time_range not in TIME_RANGES:
        raise SearxError(f"SEARX_TIME_RANGE must be one of day, week, month, year; got {time_range!r}")
    limit = _number("SEARX_RESULTS", get("SEARX_RESULTS"), DEFAULT_LIMIT, int)
    if not 1 <= limit <= MAX_LIMIT:
        raise SearxError(f"SEARX_RESULTS must be between 1 and {MAX_LIMIT}, got {limit}")
    script = get("SEARX_SCRIPT")
    autostop, stop_always = _mode(get("SEARX_AUTOSTOP"), True)
    quit_docker, quit_docker_always = _mode(get("SEARX_QUIT_DOCKER"), True)
    def bounded(name, default, low, high):
        value = _number(name, get(name), default, int)
        if not low <= value <= high:
            raise SearxError(f"{name} must be between {low} and {high}, got {value}")
        return value

    delay = _number("SEARX_DELAY", get("SEARX_DELAY"), DEFAULT_DELAY, float)
    if delay < 0:
        raise SearxError(f"SEARX_DELAY cannot be negative, got {delay}")
    return SearxConfig(
        queries=bounded("SEARX_QUERIES", DEFAULT_QUERIES, 1, MAX_QUERIES),
        pages=bounded("SEARX_PAGES", DEFAULT_PAGES, 1, MAX_PAGES),
        fetch=_truthy(get("SEARX_FETCH"), True),
        fetch_pages=bounded("SEARX_FETCH_PAGES", DEFAULT_FETCH_PAGES, 0, MAX_FETCH_PAGES),
        fetch_chars=bounded("SEARX_FETCH_CHARS", DEFAULT_FETCH_CHARS, 500, 20_000),
        context_chars=bounded("SEARX_CONTEXT_CHARS", DEFAULT_CONTEXT_CHARS, 2_000, 200_000),
        delay=delay,
        url=normalize_url(get("SEARX_URL")),
        timeout=_number("SEARX_TIMEOUT", get("SEARX_TIMEOUT"), DEFAULT_TIMEOUT, float),
        limit=limit,
        language=get("SEARX_LANGUAGE"),
        categories=get("SEARX_CATEGORIES", "general"),
        engines=get("SEARX_ENGINES"),
        time_range=time_range,
        exclude=tuple(d.lower().lstrip(".") for d in _csv(get("SEARX_EXCLUDE"))),
        autostart=_truthy(get("SEARX_AUTOSTART"), True),
        autostop=autostop,
        stop_always=stop_always,
        quit_docker=quit_docker,
        quit_docker_always=quit_docker_always,
        restart_on_fail=_truthy(get("SEARX_RESTART"), True),
        script=Path(script).expanduser() if script else None,
    )


# --------------------------------------------------------------------------- #
# 2. Building a good query                                                    #
# --------------------------------------------------------------------------- #

_MARKUP = re.compile(r"[`*_#>\[\]{}|\\]")


def build_query(title: str, tags=(), description: str = "", max_words: int = 12) -> str:
    """Turn a page's title (and, if needed, tags) into search keywords.

    The title is the best single source of keywords: you already chose it to say what the
    page is about. Rules:
      * Markdown/HTML symbols are removed and spaces collapsed.
      * A SHORT title (fewer than 3 words, e.g. "Fourier") is ambiguous, so up to two tags
        are appended ("Fourier signal-processing").
      * No title at all: the first words of the description are used.
      * At most `max_words` words, at most MAX_QUERY_CHARS characters.
    """

    def clean(text: str) -> str:
        text = html.unescape(re.sub(r"<[^>]+>", " ", str(text or "")))
        return " ".join(_MARKUP.sub(" ", text).split())

    words = clean(title).split()
    if not words:
        words = clean(description).split()[:8]
    elif len(words) < 3:
        lowered = {w.lower() for w in words}
        extra = 0
        for tag in tags or ():
            tag = clean(tag)
            if tag and tag.lower() not in lowered and extra < 2:
                words.append(tag)
                lowered.add(tag.lower())
                extra += 1
    query = " ".join(words[:max_words])
    return query[:MAX_QUERY_CHARS].strip()


# --------------------------------------------------------------------------- #
# 3. The search                                                               #
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class SearxResult:
    """One search hit."""

    title: str
    url: str
    snippet: str = ""
    engine: str = ""  # the engine that found it first ("duckduckgo"...)
    published: str = ""  # publication date when the engine gives one

    @property
    def domain(self) -> str:
        return (urlparse(self.url).hostname or "").removeprefix("www.")


@dataclass
class SearxResponse:
    """What search() returns."""

    query: str
    results: list = field(default_factory=list)
    suggestions: list = field(default_factory=list)  # "did you mean" queries
    answers: list = field(default_factory=list)  # direct answers (calculator, definitions...)
    unresponsive: list = field(default_factory=list)  # ["google: timeout", ...]
    seconds: float = 0.0
    total_found: int = 0  # hits before dropping duplicates / excluded domains / the limit
    queries: list = field(default_factory=list)  # every query that was searched (gather())
    pages: dict = field(default_factory=dict)  # url -> text of the downloaded page (gather())
    errors: list = field(default_factory=list)  # searches or downloads that failed, as text
    searches: int = 0  # how many requests were made to SearXNG (gather())


def _clean_text(value, limit: int = MAX_SNIPPET_CHARS) -> str:
    """Plain one-line text: tags removed, entities decoded, spaces collapsed, cut to `limit`."""
    text = html.unescape(re.sub(r"<[^>]+>", " ", str(value or "")))
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def _dedupe_key(url: str) -> str:
    """Two URLs that differ only by tracking noise get the same key."""
    p = urlparse(url)
    query = sorted(
        (k, v) for k, v in parse_qsl(p.query) if not k.lower().startswith(("utm_", "fbclid", "gclid"))
    )
    return urlunparse(("", p.netloc.lower().removeprefix("www."), p.path.rstrip("/"), "", urlencode(query), ""))


def _excluded(url: str, exclude: tuple) -> bool:
    host = (urlparse(url).hostname or "").lower()
    return any(host == d or host.endswith("." + d) for d in exclude)


def parse_results(data, limit: int, exclude: tuple = ()):
    """Turn SearXNG's JSON into (list of SearxResult, total hits seen).

    Keeps only http(s) links (a result could be javascript: or file:), drops entries
    without title or URL, duplicates, and the excluded domains, then cuts at `limit`.
    """
    raw = data.get("results") if isinstance(data, dict) else None
    if not isinstance(raw, list):
        return [], 0
    seen, out = set(), []
    for item in raw:
        if not isinstance(item, dict):
            continue
        url = str(item.get("url") or "").strip()
        title = _clean_text(item.get("title"), 200)
        if not title or urlparse(url).scheme not in ("http", "https") or not urlparse(url).netloc:
            continue
        if _excluded(url, exclude):
            continue
        key = _dedupe_key(url)
        if key in seen:
            continue
        seen.add(key)
        out.append(
            SearxResult(
                title=title,
                url=url,
                snippet=_clean_text(item.get("content")),
                engine=str(item.get("engine") or ""),
                published=str(item.get("publishedDate") or "")[:10],
            )
        )
    return out[:limit], len(raw)


def _hint_for_status(status: int, url: str) -> str:
    if status == 403:
        return (
            f"SearXNG at {url} refused the request (HTTP 403). Almost always this means the JSON "
            "output is switched off: settings.yml needs  search: formats: [html, json]. "
            "`searx.sh install` writes a settings.yml that has it."
        )
    if status == 429:
        return (
            f"SearXNG at {url} answered 'too many requests' (HTTP 429): its rate limiter is on. "
            "For your own local instance set  server: limiter: false  (searx.sh does)."
        )
    return f"SearXNG at {url} answered HTTP {status}."


def search(
    query: str,
    *,
    limit: "int | None" = None,
    language: "str | None" = None,
    categories: "str | None" = None,
    engines: "str | None" = None,
    time_range: "str | None" = None,
    exclude: "tuple | None" = None,
    pageno: int = 1,
    config: "SearxConfig | None" = None,
) -> SearxResponse:
    """Ask SearXNG and return the cleaned results. Any argument left out comes from the settings.

    Raises ValueError for a bad argument, SearxNotRunning when nothing answers, and SearxError
    for every other problem (refused, rate-limited, not JSON, timeout...).
    """
    if not isinstance(query, str) or not query.strip():
        raise ValueError("query must be a non-empty string")
    cfg = config or load_config()
    limit = cfg.limit if limit is None else limit
    if not isinstance(limit, int) or not 1 <= limit <= MAX_LIMIT:
        raise ValueError(f"limit must be an integer between 1 and {MAX_LIMIT}")
    time_range = cfg.time_range if time_range is None else time_range
    if time_range not in TIME_RANGES:
        raise ValueError("time_range must be '', day, week, month or year")
    exclude = cfg.exclude if exclude is None else tuple(d.lower() for d in exclude)

    if not isinstance(pageno, int) or not 1 <= pageno <= 20:
        raise ValueError("pageno must be an integer between 1 and 20")
    params = {"q": query.strip()[:MAX_QUERY_CHARS], "format": "json"}
    if pageno > 1:
        params["pageno"] = str(pageno)
    for name, value in (
        ("language", cfg.language if language is None else language),
        ("categories", cfg.categories if categories is None else categories),
        ("engines", cfg.engines if engines is None else engines),
        ("time_range", time_range),
    ):
        if value:
            params[name] = value
    request = Request(
        f"{cfg.url}/search?{urlencode(params)}",
        headers={"Accept": "application/json", "User-Agent": USER_AGENT},
    )

    started = time.monotonic()
    try:
        with urlopen(request, timeout=cfg.timeout) as reply:
            raw = reply.read(MAX_RESPONSE_BYTES + 1)
    except HTTPError as exc:
        raise SearxError(_hint_for_status(exc.code, cfg.url)) from None
    except URLError as exc:
        reason = exc.reason
        if isinstance(reason, TimeoutError) or "timed out" in str(reason):
            raise SearxError(f"SearXNG at {cfg.url} did not answer within {cfg.timeout:.0f}s") from None
        raise SearxNotRunning(
            f"nothing answers at {cfg.url} ({reason}). Start it with:  searx.sh start"
            "  (or python3 mysearx.py --start)"
        ) from None
    except (TimeoutError, OSError) as exc:
        raise SearxError(f"SearXNG at {cfg.url}: {exc}") from None

    if len(raw) > MAX_RESPONSE_BYTES:
        raise SearxError("SearXNG answered with more data than expected; refusing to read it")
    try:
        data = json.loads(raw.decode("utf-8", errors="replace"))
    except ValueError:
        raise SearxError(
            f"{cfg.url} did not answer with JSON. Is SEARX_URL really your SearXNG, "
            "and is the json format enabled in its settings.yml?"
        ) from None
    if not isinstance(data, dict):
        raise SearxError(f"unexpected answer from {cfg.url}")

    results, total = parse_results(data, limit, exclude)
    return SearxResponse(
        query=params["q"],
        results=results,
        suggestions=[
            _clean_text(s, 120)
            for s in (data.get("suggestions") if isinstance(data.get("suggestions"), list) else [])
            if isinstance(s, str)
        ][:5],
        answers=[
            text
            for text in (
                _clean_text(a if isinstance(a, str) else a.get("answer", "") if isinstance(a, dict) else "", 300)
                for a in (data.get("answers") if isinstance(data.get("answers"), list) else [])
            )
            if text
        ][:3],
        unresponsive=[
            ": ".join(str(x) for x in pair)
            for pair in (data.get("unresponsive_engines") if isinstance(data.get("unresponsive_engines"), list) else [])
            if isinstance(pair, (list, tuple))
        ],
        seconds=time.monotonic() - started,
        total_found=total,
    )


# --------------------------------------------------------------------------- #
# 3b. Deep research: many queries, many pages, merged, plus the text of the pages #
# --------------------------------------------------------------------------- #


def build_queries(title: str, tags=(), description: str = "", max_queries: int = DEFAULT_QUERIES, max_words: int = 12) -> list:
    """Several different searches about the same page, best first (no duplicates).

    One query finds one slice of the web; variants find the others. In this order:
    the plain title query, "... tutorial", the description's own words, "... examples",
    the title with the page's tags, then "... explained", "... guide" and so on.
    Returns [] when there is nothing to search for.
    """
    base = build_query(title, tags, description, max_words)
    if not base:
        return []
    words = base.split()
    lowered = {w.lower() for w in words}

    def with_suffix(suffix: str) -> str:
        extra = suffix.split()
        if extra[0].lower() in lowered:
            return ""
        return " ".join(words[: max(1, max_words - len(extra))] + extra)

    candidates = [base, with_suffix(QUERY_SUFFIXES[0])]
    if description.strip():
        candidates.append(build_query("", (), description, max_words=10))
    candidates.append(with_suffix(QUERY_SUFFIXES[1]))
    clean_tags = [" ".join(_MARKUP.sub(" ", str(t)).split()) for t in (tags or ())]
    clean_tags = [t for t in clean_tags if t and t.lower() not in lowered][:2]
    if clean_tags:
        candidates.append(" ".join(words[:5] + clean_tags)[:MAX_QUERY_CHARS])
    candidates.extend(with_suffix(sfx) for sfx in QUERY_SUFFIXES[2:])
    out, seen = [], set()
    for query in candidates:
        query = query.strip()
        if query and query.lower() not in seen:
            seen.add(query.lower())
            out.append(query)
    return out[: max(1, max_queries)]


def _sleep(seconds: float) -> None:
    """time.sleep in a function of its own so tests can replace it."""
    if seconds > 0:
        time.sleep(seconds)


class _TextExtractor(HTMLParser):
    """The readable text of a web page: headings, paragraphs, list items, code. No menus or scripts."""

    SKIP = {"script", "style", "noscript", "svg", "nav", "header", "footer", "aside", "form", "iframe",
            "template", "button", "select", "head"}
    BLOCK = {"p", "div", "li", "h1", "h2", "h3", "h4", "h5", "h6", "pre", "tr", "td", "th", "blockquote",
             "br", "section", "article", "dd", "dt", "table", "ul", "ol", "main"}
    HEADING = {"h1", "h2", "h3", "h4"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts: list = []
        self._skip = 0
        self._heading = False

    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP:
            self._skip += 1
        elif tag in self.BLOCK:
            self.parts.append("\n")
            if tag in self.HEADING:
                self._heading = True
                self.parts.append("## ")

    def handle_endtag(self, tag):
        if tag in self.SKIP and self._skip:
            self._skip -= 1
        elif tag in self.BLOCK:
            self._heading = False
            self.parts.append("\n")

    def handle_data(self, data):
        if not self._skip:
            self.parts.append(data)

    def text(self) -> str:
        lines, seen = [], set()
        for raw in "".join(self.parts).split("\n"):
            line = " ".join(raw.split())
            if not line:
                continue
            if not line.startswith("## ") and len(line) < 40:  # menu items, buttons, dates...
                continue
            if line in seen:
                continue
            seen.add(line)
            lines.append(line)
        return "\n".join(lines)


def _public_host(host: str) -> bool:
    """True when every address of `host` is a public internet address (never localhost, a LAN
    device, a link-local or a private range): downloading from this Mac must not reach them."""
    if not host:
        return False
    try:
        infos = socket.getaddrinfo(host, None)
    except OSError:
        return False
    addresses = {info[4][0].split("%")[0] for info in infos}
    try:
        return bool(addresses) and all(ipaddress.ip_address(a).is_global for a in addresses)
    except ValueError:
        return False


def _cut_lines(text: str, limit: int) -> str:
    """Cut at a line boundary (a line itself is cut only when it is the first one)."""
    if len(text) <= limit:
        return text
    cut = text[:limit]
    newline = cut.rfind("\n")
    return (cut[:newline] if newline > limit // 3 else cut).rstrip()


def fetch_page_text(url: str, max_chars: int = DEFAULT_FETCH_CHARS, timeout: float = FETCH_TIMEOUT) -> str:
    """Download ONE web page and return its readable text (at most `max_chars`).

    Safety: only http(s); never a private/local address (checked again after redirects); at most
    MAX_PAGE_BYTES are read; only text/html pages. Raises SearxError with a short reason.
    """
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise SearxError("not an http(s) link")
    if not _public_host(parsed.hostname):
        raise SearxError("not a public address")
    request = Request(url, headers={"User-Agent": BROWSER_UA, "Accept": "text/html,application/xhtml+xml,text/plain;q=0.8"})
    try:
        with urlopen(request, timeout=timeout) as reply:
            final = urlparse(reply.geturl())
            if final.hostname != parsed.hostname and not _public_host(final.hostname or ""):
                raise SearxError("redirected to a non-public address")
            kind = reply.headers.get_content_type()
            if kind not in ("text/html", "application/xhtml+xml", "text/plain"):
                raise SearxError(f"not a web page ({kind})")
            raw = reply.read(MAX_PAGE_BYTES)
            charset = reply.headers.get_content_charset() or "utf-8"
    except HTTPError as exc:
        raise SearxError(f"HTTP {exc.code}") from None
    except URLError as exc:
        raise SearxError(str(exc.reason)[:80]) from None
    except (TimeoutError, OSError, ValueError) as exc:
        raise SearxError(f"{type(exc).__name__}: {exc}"[:80]) from None
    try:
        page = raw.decode(charset, errors="replace")
    except LookupError:
        page = raw.decode("utf-8", errors="replace")
    if kind == "text/plain":
        text = "\n".join(" ".join(line.split()) for line in page.splitlines() if line.strip())
    else:
        extractor = _TextExtractor()
        try:
            extractor.feed(page)
            extractor.close()
        except Exception:  # broken HTML must never stop the research  # noqa: BLE001
            pass
        text = extractor.text()
    if len(text) < 200:
        raise SearxError("no readable text")
    return _cut_lines(text, max_chars)


def gather(
    queries,
    *,
    limit: "int | None" = None,
    pages: "int | None" = None,
    fetch: "bool | None" = None,
    fetch_pages: "int | None" = None,
    language: "str | None" = None,
    categories: "str | None" = None,
    engines: "str | None" = None,
    time_range: "str | None" = None,
    config: "SearxConfig | None" = None,
    progress=None,
) -> SearxResponse:
    """Deep research: search EVERY query (and `pages` result pages of each), merge the answers into
    one ranked list, and download the text of the best pages.

    queries:     a string or a list of strings (see build_queries()).
    limit:       results kept per search page; None = SEARX_RESULTS.
    pages:       result pages per query; None = SEARX_PAGES.
    fetch:       download the best pages' text; None = SEARX_FETCH.
    fetch_pages: how many pages to download; None = SEARX_FETCH_PAGES.
    progress:    optional function(text) called with a short message at every step.

    Ranking: a link found by several queries (and high in each) comes first (reciprocal rank
    fusion). One failing search does not stop the others; SearxNotRunning (nothing answers)
    does. Raises SearxError only when no search worked at all.
    """
    cfg = config or load_config()
    if isinstance(queries, str):
        queries = [queries]
    wanted, seen = [], set()
    for q in queries or ():
        q = (q or "").strip()
        if q and q.lower() not in seen:
            seen.add(q.lower())
            wanted.append(q)
    wanted = wanted[:MAX_QUERIES]
    if not wanted:
        raise ValueError("queries must contain at least one non-empty query")
    pages = cfg.pages if pages is None else pages
    if not isinstance(pages, int) or not 1 <= pages <= MAX_PAGES:
        raise ValueError(f"pages must be an integer between 1 and {MAX_PAGES}")
    per_page = cfg.limit if limit is None else limit
    say = progress or (lambda text: None)

    started = time.monotonic()
    merged: dict = {}  # dedupe key -> [SearxResult, score]
    answers, suggestions, unresponsive, errors, searched = [], [], [], [], []
    total = requests_made = successes = 0
    last_error = None
    for qi, query in enumerate(wanted):
        position = 0
        for page_number in range(1, pages + 1):
            if requests_made:
                _sleep(cfg.delay)
            requests_made += 1
            say(f"searching ({qi + 1}/{len(wanted)}, page {page_number}): {query}")
            try:
                response = search(
                    query, limit=per_page, language=language, categories=categories, engines=engines,
                    time_range=time_range, pageno=page_number, config=cfg,
                )
            except SearxNotRunning:
                raise
            except SearxError as exc:
                last_error = exc
                errors.append(f"search {query!r} page {page_number}: {str(exc).splitlines()[0]}")
                break  # the next page of a failing query would fail too
            successes += 1
            if query not in searched:
                searched.append(query)
            total += response.total_found
            for note in response.unresponsive:
                if note not in unresponsive:
                    unresponsive.append(note)
            for text in response.answers:
                if text not in answers:
                    answers.append(text)
            for text in response.suggestions:
                if text not in suggestions:
                    suggestions.append(text)
            if not response.results:
                break  # no more pages for this query
            for result in response.results:
                key = _dedupe_key(result.url)
                gain = 1.0 / (10 + position)
                position += 1
                if key in merged:
                    merged[key][1] += gain
                else:
                    merged[key] = [result, gain]
    if not successes:
        raise last_error or SearxError("no search could be made")

    ranked = [item[0] for item in sorted(merged.values(), key=lambda item: -item[1])]
    texts: dict = {}
    wanted_fetch = cfg.fetch if fetch is None else fetch
    count = cfg.fetch_pages if fetch_pages is None else fetch_pages
    if wanted_fetch and count > 0 and ranked:
        targets = [r for r in ranked if not urlparse(r.url).path.lower().endswith((".pdf", ".zip", ".mp4", ".png", ".jpg", ".gif"))][:count]
        say(f"downloading the text of {len(targets)} page(s)")

        def one(result):
            try:
                return result.url, fetch_page_text(result.url, cfg.fetch_chars), ""
            except SearxError as exc:
                return result.url, "", str(exc)

        with concurrent.futures.ThreadPoolExecutor(max_workers=FETCH_WORKERS) as pool:
            for url, text, reason in pool.map(one, targets):
                if text:
                    texts[url] = text
                else:
                    host = (urlparse(url).hostname or url).removeprefix("www.")
                    errors.append(f"download {host}: {reason}")
    return SearxResponse(
        query=" | ".join(searched or wanted),
        results=ranked,
        suggestions=suggestions[:10],
        answers=answers[:5],
        unresponsive=unresponsive,
        seconds=time.monotonic() - started,
        total_found=total,
        queries=searched,
        pages=texts,
        errors=errors,
        searches=requests_made,
    )


# --------------------------------------------------------------------------- #
# 4. Presenting the results                                                   #
# --------------------------------------------------------------------------- #


def format_results(response: SearxResponse, markdown: bool = False) -> str:
    """The results as text for a person (plain, or a Markdown list with [title](url))."""
    if not response.results:
        return f"No results for {response.query!r}."
    lines = []
    for number, r in enumerate(response.results, 1):
        if markdown:
            lines.append(f"{number}. [{r.title}]({r.url})" + (f" - {r.snippet}" if r.snippet else ""))
        else:
            lines.append(f"{number}. {r.title}\n   {r.url}" + (f"\n   {r.snippet}" if r.snippet else ""))
    return "\n".join(lines)


def as_context(response: SearxResponse, max_chars: int = 6000) -> str:
    """A text block for an AI prompt.

    Without downloaded pages: numbered title, domain, date, snippet and URL, cut at `max_chars` on a
    whole-result boundary. With pages (deep research, `response.pages`): the same list takes at
    most 40% of `max_chars`, followed by "PAGE EXCERPTS": the readable text of the best pages,
    as many as fit. Returns '' when there are no results.
    """
    has_pages = bool(response.pages)
    list_budget = int(max_chars * 0.4) if has_pages else max_chars
    blocks = []
    for number, r in enumerate(response.results, 1):
        head = f"[{number}] {r.title} ({r.domain}{', ' + r.published if r.published else ''})"
        block = head + (f"\n    {r.snippet}" if r.snippet else "") + f"\n    {r.url}"
        if sum(len(b) + 1 for b in blocks) + len(block) > list_budget:
            break
        blocks.append(block)
    text = "\n".join(blocks)
    if not has_pages or not text:
        return text
    parts = [text, "", "PAGE EXCERPTS (text of the pages above; [n] is the number of the result):"]
    used = len(text) + sum(len(p) + 1 for p in parts[1:])
    for number, r in enumerate(response.results, 1):
        body = response.pages.get(r.url)
        if not body:
            continue
        head = f"--- [{number}] {r.title} ({r.domain}) ---"
        room = max_chars - used - len(head) - 2
        if room < 400:  # not worth a stub
            break
        excerpt = _cut_lines(body, room)
        parts.extend([head, excerpt])
        used += len(head) + len(excerpt) + 2
    return "\n".join(parts)


# --------------------------------------------------------------------------- #
# 5. Is it running? Start it, stop it                                         #
# --------------------------------------------------------------------------- #


def is_up(config: "SearxConfig | None" = None, timeout: float = 3.0) -> bool:
    """True when SearXNG answers on its health URL (or its home page)."""
    cfg = config or load_config()
    for path in ("/healthz", "/"):
        try:
            with urlopen(Request(cfg.url + path, headers={"User-Agent": USER_AGENT}), timeout=timeout) as reply:
                if 200 <= reply.status < 300:
                    return True
        except (OSError, ValueError):
            continue
    return False


def find_script(config: "SearxConfig | None" = None) -> "Path | None":
    """Locate searx.sh: SEARX_SCRIPT, ../scripts/searx.sh, ~/macOS/scripts/searx.sh, next to this file."""
    cfg = config or load_config()
    here = Path(__file__).resolve().parent
    candidates = [cfg.script] if cfg.script else []
    candidates += [here.parent / "scripts" / "searx.sh", Path.home() / "macOS" / "scripts" / "searx.sh", here / "searx.sh"]
    for candidate in candidates:
        if candidate and candidate.is_file():
            return candidate
    return None


def _run_script(args: list, config: SearxConfig, timeout: float) -> str:
    """Run `bash searx.sh ARGS` and return its output; SearxError when it fails."""
    script = find_script(config)
    if script is None:
        raise SearxError(
            "searx.sh not found. Put it in ~/macOS/scripts/ or set SEARX_SCRIPT to its path."
        )
    if not shutil.which("bash"):
        raise SearxError("bash not found")
    env = dict(os.environ, SEARX_PORT=str(config.port))
    try:
        done = subprocess.run(
            ["bash", str(script), *args],
            capture_output=True,
            text=True,
            timeout=timeout,
            env=env,
            stdin=subprocess.DEVNULL,
        )
    except subprocess.TimeoutExpired:
        raise SearxError(f"searx.sh {' '.join(args)} did not finish within {timeout:.0f}s") from None
    except OSError as exc:
        raise SearxError(f"cannot run {script}: {exc}") from None
    output = (done.stdout or "") + (done.stderr or "")
    if done.returncode != 0:
        tail = "\n".join(output.strip().splitlines()[-8:])
        raise SearxError(f"searx.sh {' '.join(args)} failed (exit {done.returncode}):\n{tail}")
    return output


def start(config: "SearxConfig | None" = None) -> bool:
    """Start Docker (if needed) and SearXNG. True when WE started it, False if it already ran.

    Only works for a local SearXNG. Raises SearxError when it cannot be started.
    """
    cfg = config or load_config()
    if is_up(cfg):
        return False
    if not cfg.is_local:
        raise SearxNotRunning(f"{cfg.url} is not on this Mac and does not answer: cannot start it from here")
    problem = None
    try:
        _run_script(["start"], cfg, START_TIMEOUT)
        if not is_up(cfg, timeout=5):
            problem = SearxError("searx.sh start finished but SearXNG still does not answer; run:  searx.sh logs")
    except SearxError as exc:
        problem = exc
    if problem is not None:
        if not cfg.restart_on_fail:
            raise problem
        # Personal computer: nothing else needs Docker, so do not be gentle (SEARX_RESTART=0 turns this off).
        first = str(problem).strip().splitlines()[0] if str(problem).strip() else "no answer"
        print(f"SearXNG did not start ({first}). Restarting Docker no matter what...", file=sys.stderr)
        reset(cfg)
    return True


def reset(config: "SearxConfig | None" = None) -> None:
    """Restart EVERYTHING, no matter what: stop the container, force-quit Docker Desktop (even if it
    hangs or is busy with something else), launch it again and start SearXNG. Raises SearxError
    when SearXNG still does not answer afterwards. Only for a SearXNG on this Mac."""
    cfg = config or load_config()
    if not cfg.is_local:
        raise SearxNotRunning(f"{cfg.url} is not on this Mac and does not answer: cannot restart it from here")
    _run_script(["reset"], cfg, RESET_TIMEOUT)
    if not is_up(cfg, timeout=5):
        raise SearxError("SearXNG still does not answer after restarting Docker; run:  searx.sh logs")


def stop(config: "SearxConfig | None" = None, quit_docker: "bool | None" = None) -> None:
    """Stop the SearXNG container, and quit Docker Desktop according to SEARX_QUIT_DOCKER
    (1 = only if searx.sh launched it, always = every time, 0 = never)."""
    cfg = config or load_config()
    quit_it = cfg.quit_docker if quit_docker is None else quit_docker
    if not quit_it:
        flag = ["--keep-docker"]  # never quit Docker Desktop
    elif cfg.quit_docker_always:
        flag = ["--quit-docker"]  # quit it every time (not when other containers run)
    else:
        flag = []  # quit it only if searx.sh launched it
    _run_script(["stop", *flag], cfg, STOP_TIMEOUT)


def ensure_running(config: "SearxConfig | None" = None, autostart: "bool | None" = None) -> bool:
    """Make sure SearXNG answers. Returns True when this call had to start it.

    Raises SearxNotRunning when it is down and starting is disabled (SEARX_AUTOSTART=0).
    """
    cfg = config or load_config()
    if cfg.autostart if autostart is None else autostart:
        return start(cfg)  # start() itself checks first and returns False when it already answers
    if is_up(cfg):
        return False
    raise SearxNotRunning(f"SearXNG is not running at {cfg.url} and SEARX_AUTOSTART is off. Run:  searx.sh start")


@contextlib.contextmanager
def running(config: "SearxConfig | None" = None, autostart: "bool | None" = None, autostop: "bool | None" = None):
    """`with running(): ...` - SearXNG is up inside the block and, if the block had to
    start it, it is stopped again afterwards (even when the block raises or you press
    Ctrl-C). Something that was already running is left alone, UNLESS you chose
    SEARX_AUTOSTOP=always (then it is stopped every time, to free your Mac's resources).
    `autostop=False` (the --keep options) overrides everything and never stops it.

    Yields True when this block started it.
    """
    cfg = config or load_config()
    started = ensure_running(cfg, autostart)
    try:
        yield started
    finally:
        enabled = cfg.autostop if autostop is None else autostop
        if enabled and (started or cfg.stop_always):
            try:
                stop(cfg)
            except SearxError as exc:  # never hide the real error of the block
                print(f"warning: could not stop SearXNG: {exc}", file=sys.stderr)


def status(config: "SearxConfig | None" = None) -> str:
    """One line for a human: is it answering, and where."""
    cfg = config or load_config()
    return f"SearXNG at {cfg.url}: " + ("UP" if is_up(cfg) else "not answering")


# --------------------------------------------------------------------------- #
# Command line                                                                #
# --------------------------------------------------------------------------- #


def cli(argv=None) -> int:
    """python3 mysearx.py QUERY [--limit N] [--json|--markdown] [--start|--stop|--status|--keep]."""
    parser = argparse.ArgumentParser(
        prog="mysearx.py",
        description="Search the web through your own SearXNG (the Docker container managed by searx.sh).",
    )
    parser.add_argument("query", nargs="*", help="what to search for")
    parser.add_argument("--limit", type=int, help=f"results to show (1-{MAX_LIMIT}; SEARX_RESULTS)")
    parser.add_argument("--language", help="en, es, all ... (SEARX_LANGUAGE)")
    parser.add_argument("--categories", help="general, it, science, news ... (SEARX_CATEGORIES)")
    parser.add_argument("--engines", help="comma list, e.g. wikipedia,duckduckgo (SEARX_ENGINES)")
    parser.add_argument("--time-range", choices=[t for t in TIME_RANGES if t], help="day, week, month or year")
    out = parser.add_mutually_exclusive_group()
    out.add_argument("--json", action="store_true", help="print JSON (for scripts, Raycast...)")
    out.add_argument("--markdown", action="store_true", help="print a Markdown list")
    parser.add_argument("--status", action="store_true", help="say whether SearXNG answers, and exit")
    parser.add_argument("--start", action="store_true", help="start Docker and SearXNG, and exit")
    parser.add_argument("--stop", action="store_true", help="stop SearXNG (and Docker if we launched it), and exit")
    parser.add_argument(
        "--keep", action="store_true", help="with a query: do not stop SearXNG afterwards even if we started it"
    )
    args = parser.parse_args(argv)

    try:
        cfg = load_config()
        if args.status:
            print(status(cfg))
            return 0 if is_up(cfg) else 1
        if args.start:
            print("started" if start(cfg) else "already running")
            return 0
        if args.stop:
            stop(cfg)
            print("stopped")
            return 0
        query = " ".join(args.query).strip()
        if not query:
            parser.print_usage(sys.stderr)
            print("error: give a search query (or --status / --start / --stop)", file=sys.stderr)
            return 2
        with running(cfg, autostop=False if args.keep else None):
            response = search(
                query,
                limit=args.limit,
                language=args.language,
                categories=args.categories,
                engines=args.engines,
                time_range=args.time_range,
                config=cfg,
            )
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except SearxError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    if args.json:
        print(
            json.dumps(
                {
                    "query": response.query,
                    "seconds": round(response.seconds, 2),
                    "results": [vars(r) for r in response.results],
                    "suggestions": response.suggestions,
                    "answers": response.answers,
                    "unresponsive_engines": response.unresponsive,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
    else:
        print(format_results(response, markdown=args.markdown))
        for note in response.unresponsive:
            print(f"(engine not responding: {note})", file=sys.stderr)
    return 0 if response.results else 1


if __name__ == "__main__":
    sys.exit(cli())
