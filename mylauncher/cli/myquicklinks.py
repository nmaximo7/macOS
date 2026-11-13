"""
myquicklinks.py - web searches you can start from the launcher: conf/quicklinks.json.

The file is a list; each entry has two required fields and one optional:

    [
      {"keyword": "yt",     "url": "https://www.youtube.com/results?search_query={query}"},
      {"keyword": "jttp",   "url": "https://justtothepoint.com/search/?query="},
      {"keyword": "google", "url": "https://www.google.com/search?q={query}", "title": "Google"}
    ]

  keyword  what you type first. It cannot contain spaces.
  url      the page to open. If it contains {query}, your text goes there; if not, your text is put at
           the END of the url (that is what you want for "...search/?query=").
           The text is URL-encoded for you: "lo fi" becomes "lo+fi".
  title    optional name shown in the list; by default the site name (youtube.com).
  icon     optional emoji shown at the start of the row; default 🔎.

How you use it:   yt   (then Space or Tab)   lofi beats   (then Enter)
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote_plus, urlsplit

from mytypes import ConfigError

PLACEHOLDER = "{query}"


@dataclass(frozen=True)
class Quicklink:
    keyword: str
    url: str
    title: str
    icon: str = ""


def site_name(url: str) -> str:
    """https://www.youtube.com/results... -> youtube.com"""
    return (urlsplit(url).hostname or url).removeprefix("www.")


def build_url(link: Quicklink, query: str) -> str:
    """Put the (encoded) query in the url: at {query}, or at the end when there is no {query}."""
    encoded = quote_plus(query.strip())
    if PLACEHOLDER in link.url:
        return link.url.replace(PLACEHOLDER, encoded)
    return link.url + encoded


def parse_quicklinks(data, where: str = "quicklinks.json", reserved=()) -> tuple:
    """Check the content read from the JSON file. `reserved` = words that cannot be keywords (like "kill")."""
    if not isinstance(data, list):
        raise ConfigError(f"{where} must be a list [ {{...}}, {{...}} ]")
    links, seen = [], set()
    for number, entry in enumerate(data):
        here = f"{where}[{number}]"
        if not isinstance(entry, dict):
            raise ConfigError(f"{here} must be an object with a keyword and a url")
        keyword = entry.get("keyword")
        if not isinstance(keyword, str) or not keyword.strip() or len(keyword.split()) != 1:
            raise ConfigError(f'{here}.keyword must be ONE word, for example "yt"')
        keyword = keyword.lower()
        if keyword in seen:
            raise ConfigError(f'{here}.keyword "{keyword}" is used twice')
        if keyword in reserved:
            raise ConfigError(f'{here}.keyword "{keyword}" is reserved for a built-in command')
        seen.add(keyword)
        url = entry.get("url")
        if not isinstance(url, str) or not url.startswith(("http://", "https://")):
            raise ConfigError(f"{here}.url must be text starting with http:// or https://")
        title = entry.get("title", "")
        if not isinstance(title, str):
            raise ConfigError(f"{here}.title must be text")
        icon = entry.get("icon", "")
        if not isinstance(icon, str):
            raise ConfigError(f"{here}.icon must be text (one emoji)")
        links.append(Quicklink(keyword, url, title.strip() or site_name(url), icon.strip()))
    return tuple(links)


def load_quicklinks(path, reserved=()) -> tuple:
    """Read conf/quicklinks.json. A missing file means "no quicklinks" (it is optional)."""
    path = Path(path)
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return ()
    except OSError as exc:
        raise ConfigError(f"cannot read {path}: {exc}") from None
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ConfigError(f"{path} is not valid JSON (line {exc.lineno}, column {exc.colno}): {exc.msg}") from None
    return parse_quicklinks(data, path.name, reserved)
