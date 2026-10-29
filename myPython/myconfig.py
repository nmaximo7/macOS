"""
myconfig.py - ONE place that reads the .env file and builds the Ollama client.

Why this file exists
--------------------
Before, every module that needed the model names or the Ollama host had to repeat
the "find .env / load it / read the variables / create the client" code.
Now every module simply does:

    from myconfig import get_settings, get_client

    settings = get_settings()      # the configuration (read from .env)
    client   = get_client()        # the Ollama client, ready to use

How the "singleton" works
-------------------------
get_settings() and get_client() are decorated with functools.lru_cache.
That means: the FIRST call does the real work (reads .env, creates the client) and
every later call, from any module, returns the very same object.
Nothing is read at import time, so importing this file is free and cannot fail;
errors in .env show up only when the settings are first requested.

Variables understood in .env  (all optional - see .env.example)
---------------------------------------------------------------
    MYMODEL_QUERY       model used for summaries / queries           (qwen3:32b)
    MODELS_NEWCONTENT   models for content expansion, separated by
                        spaces or commas:  "qwen3:32b gemma3:27b"    (none)
    BASE_URL            address of the Ollama server                 (http://localhost:11434)
    OLLAMA_TIMEOUT      seconds to wait for an answer                (600)
    OLLAMA_NUM_CTX      context window in tokens, e.g. 32768         (Ollama's default)

    HUGO_SERVER         where your Hugo server answers, e.g.
                        192.168.1.46:1313  (with or without http://)  (none)
    HUGO_ROOT           folder of the Hugo site on THIS computer (the one
                        that contains content/ and static/), e.g.
                        /Volumes/MacDatosMaster/justtothepoint          (none)
                        Both are used by check_links() / check_images() to turn
                        a page file into the address where Hugo serves it.

    TOPIC               subject of the quotes added to articles: technology,
                        maths, humor, ... or "auto" (taken from the page
                        categories); empty = any subject                (none)
    NUMBER_QUOTES       how many quotes provide_quotes() proposes       (3)
    FORTUNES_PATH       a fortunes file, or a folder of them, in the usual
                        format (text, "    -- Author", "%" between quotes)
                                                                    (none: set it to use "file")
    QUOTE_SOURCES       where quotes come from, in order of preference,
                        separated by spaces or commas. Choose among:
                        file fortune library zenquotes dummyjson     (file fortune)

    RSS_FEED_URLS       news feeds shown by greetings.py, separated by
                        spaces (one or many URLs)                       (none)
    WEATHER_CITY        city for the weather line of greetings.py, e.g.
                        Malaga ("" = wttr.in guesses it from your IP)   (none)
    WEATHER_LANG        language of that weather line: en, es, fr...    (en)
    STOCK_TICKERS       tickers shown by greetings.py, separated by
                        spaces or commas                       (AAPL MSFT GOOGL ...)

    AUTHOR              value of "author:" proposed by check_hugo_frontmatter
                        ("" = leave each page's own author alone)       (none)
    FEATURED_IMAGE      value of "featured_image:" proposed when a page has
                        none, e.g. /code/images/default.jpg
                        ("" = do not propose one)                       (none)

Check your configuration at any time with:   python3 myconfig.py
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
import os

import ollama  # the official Ollama Python library
from dotenv import load_dotenv  # reads KEY=VALUE lines from a .env file

# --------------------------------------------------------------------------- #
# Constants                                                                   #
# --------------------------------------------------------------------------- #

# The .env file lives next to this file, no matter where the program is started from.
ENV_PATH = Path(__file__).resolve().parent / ".env"

# Values used when the variable is missing from .env
DEFAULT_MODEL = "qwen3:32b"
DEFAULT_HOST = "http://localhost:11434"
DEFAULT_TIMEOUT = 600.0  # seconds; big local models can be slow
DEFAULT_NUMBER_QUOTES = 3
DEFAULT_QUOTE_SOURCES = ("file", "fortune")  # online sources are opt-in
DEFAULT_WEATHER_LANG = "en"
DEFAULT_STOCK_TICKERS = (  # major US stocks; change them with STOCK_TICKERS in .env
    "AAPL", "MSFT", "GOOGL", "AMZN", "TSLA", "BRK-B", "NVDA", "META", "JPM", "V",
)


# --------------------------------------------------------------------------- #
# The configuration object                                                    #
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)  # frozen = read-only: nobody can change it by accident
class Settings:
    """All the project settings in one tidy, immutable object."""

    model_query: str  # model for summaries / queries
    models_newcontent: tuple  # models used to expand content (a tuple of names)
    base_url: str  # where the Ollama server listens
    timeout: float  # seconds to wait for Ollama before giving up
    num_ctx: "int | None"  # context window size, None = let Ollama decide
    # --- Hugo site (used by content_urls.py, content_links.py, content_images.py) ---
    hugo_server: str = ""  # "http://192.168.1.46:1313" (always with scheme, no final "/"); "" = not set
    hugo_root: "Path | None" = None  # local folder of the Hugo site; None = not set
    # --- Quotes (used by content_quotes.py) ---
    topic: str = ""  # "technology", "maths", "humor", "auto" ... ; "" = any
    number_quotes: int = DEFAULT_NUMBER_QUOTES
    fortunes_path: "Path | None" = None  # None = not set (the "file" quote source is skipped)
    quote_sources: tuple = DEFAULT_QUOTE_SOURCES
    # --- Daily dashboard (used by greetings.py) ---
    rss_feed_urls: tuple = ()  # feed URLs, () = not set
    weather_city: str = ""  # "Malaga"; "" = wttr.in guesses from your IP address
    weather_lang: str = DEFAULT_WEATHER_LANG  # "en", "es"...
    stock_tickers: tuple = DEFAULT_STOCK_TICKERS
    # --- Front matter (used by content_frontmatter.py) ---
    author: str = ""  # "" = do not propose an author, keep each page's own
    featured_image: str = ""  # "" = do not propose one


# --------------------------------------------------------------------------- #
# Small helper functions (each does one thing)                                #
# --------------------------------------------------------------------------- #


def _split_list(raw: str) -> tuple:
    """'a b,c' -> ('a', 'b', 'c').   Accepts spaces and/or commas as separators."""
    return tuple(part for part in raw.replace(",", " ").split() if part)


def _read_number(name: str, default, cast):
    """Read a numeric variable from the environment.

    Returns `default` when the variable is missing or empty, and raises a clear
    error (naming the variable) when the value is not a valid number.
    """
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        return cast(raw)
    except ValueError:
        raise ValueError(
            f"{name} in {ENV_PATH} must be a number, got {raw!r}"
        ) from None


def _normalize_server(raw: str) -> str:
    """'192.168.1.46:1313' -> 'http://192.168.1.46:1313'   ('' stays '').

    A scheme is added when missing and the final '/' is removed, so the rest of
    the project can always do  server + "/calculus/page/".
    """
    raw = raw.strip().strip("\"'").rstrip("/")
    if not raw:
        return ""
    return raw if "://" in raw else "http://" + raw


def _read_text(name: str) -> str:
    """Read a free-text variable ('' when missing); surrounding quotes and spaces are removed."""
    return os.environ.get(name, "").strip().strip("\"'").strip()


def _read_path(name: str):
    """Read a folder path from the environment ('~' is expanded); None when missing."""
    raw = os.environ.get(name, "").strip().strip("\"'")
    return Path(raw).expanduser() if raw else None


def load_settings() -> Settings:
    """Build a Settings object from the CURRENT environment variables.

    It does not touch the .env file itself (get_settings does that), which makes
    this function easy to test: set os.environ, call it, check the result.
    """
    return Settings(
        model_query=os.environ.get("MYMODEL_QUERY", "").strip() or DEFAULT_MODEL,
        models_newcontent=_split_list(os.environ.get("MODELS_NEWCONTENT", "")),
        base_url=os.environ.get("BASE_URL", "").strip() or DEFAULT_HOST,
        timeout=_read_number("OLLAMA_TIMEOUT", DEFAULT_TIMEOUT, float),
        num_ctx=_read_number("OLLAMA_NUM_CTX", None, int),
        hugo_server=_normalize_server(os.environ.get("HUGO_SERVER", "")),
        hugo_root=_read_path("HUGO_ROOT"),
        topic=os.environ.get("TOPIC", "").strip().strip("\"'").lower(),
        number_quotes=max(1, _read_number("NUMBER_QUOTES", DEFAULT_NUMBER_QUOTES, int)),
        fortunes_path=_read_path("FORTUNES_PATH"),
        quote_sources=_split_list(os.environ.get("QUOTE_SOURCES", "").lower())
        or DEFAULT_QUOTE_SOURCES,
        # Whitespace only (not commas): a URL may legitimately contain a comma.
        rss_feed_urls=tuple(os.environ.get("RSS_FEED_URLS", "").split()),
        weather_city=_read_text("WEATHER_CITY"),
        weather_lang=_read_text("WEATHER_LANG").lower() or DEFAULT_WEATHER_LANG,
        stock_tickers=tuple(
            t.upper() for t in _split_list(os.environ.get("STOCK_TICKERS", ""))
        )
        or DEFAULT_STOCK_TICKERS,
        author=_read_text("AUTHOR"),
        featured_image=_read_text("FEATURED_IMAGE"),
    )


# --------------------------------------------------------------------------- #
# The two "singletons" the rest of the project uses                           #
# --------------------------------------------------------------------------- #


@lru_cache(maxsize=None)
def get_settings() -> Settings:
    """Return the project settings (the .env file is read only the first time)."""
    # override=True: values in .env win over variables already set in the shell.
    load_dotenv(ENV_PATH, override=True)
    return load_settings()


@lru_cache(maxsize=None)
def get_client() -> "ollama.Client":
    """Return the shared Ollama client (created only the first time)."""
    settings = get_settings()
    return ollama.Client(host=settings.base_url, timeout=settings.timeout)


def reload_settings() -> Settings:
    """Forget the cached objects and read .env again.

    Useful after editing .env while a long-running program is alive, or in tests.
    """
    get_settings.cache_clear()
    get_client.cache_clear()
    return get_settings()


# --------------------------------------------------------------------------- #
# `python3 myconfig.py` prints what the project will use                      #
# --------------------------------------------------------------------------- #

if __name__ == "__main__":
    print(
        f".env file : {ENV_PATH}  ({'found' if ENV_PATH.exists() else 'NOT found - using defaults'})"
    )
    for field, value in vars(get_settings()).items():
        print(f"{field:18}: {value}")
