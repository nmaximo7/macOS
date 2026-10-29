"""
content_urls.py - the shared engine behind check_links() and check_images().

What lives here
---------------
    page_url(page)       "/Volumes/.../justtothepoint/content/calculus/lineintegralspace.md"
                         -> "http://192.168.1.46:1313/calculus/lineintegralspace/"
    scan_page(page)      finds every link and image of a page (with its line number)
    PageContext          knows where the page is served and resolves any link to a full URL
    Checker              asks the servers (many at once) and remembers the answers
    evaluate(...)        scan + resolve + ask + judge  ->  one verdict per link/image
    run_check(...)       evaluate + print the Rich report (what check_links/check_images call)

Settings come from .env through myconfig.py:
    HUGO_SERVER=192.168.1.46:1313                  where Hugo answers
    HUGO_ROOT=/Volumes/MacDatosMaster/justtothepoint   where the site lives on THIS computer
(the two folders are kept in sync with Syncthing, so a page edited here is served there).

Nothing is ever written or changed: this file only READS pages and ASKS servers.
Only the Python standard library is used for the network part; Rich draws the report.
"""

from __future__ import annotations

import html
import http.client
import os
import re
import socket
import ssl
import threading
import urllib.error
import urllib.request
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field, replace
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import quote, unquote, urldefrag, urljoin, urlsplit, urlunsplit

from rich.console import Console
from rich.progress import (
    BarColumn,
    MofNCompleteColumn,
    Progress,
    SpinnerColumn,
    TextColumn,
)
from rich.text import Text

from myconfig import get_settings

# ============================================================================ #
# Settings you may want to change                                              #
# ============================================================================ #

CONTENT_DIR = "content"  # folders of the Hugo site (inside HUGO_ROOT)
STATIC_DIR = "static"
ASSETS_DIR = "assets"
LOWERCASE_URLS = True  # Hugo lower-cases URLs by default (disablePathToLower = false)

TIMEOUT = 12.0  # seconds to wait for each server
MAX_WORKERS = 8  # how many addresses are checked at the same time
MAX_REDIRECTS = 8
MAX_BODY_BYTES = 3_000_000  # how much of a page is read to look for #anchors
LARGE_IMAGE_BYTES = 1_000_000  # check_images warns above this size

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36 content-checker"
)

# Front matter keys that hold an image (checked by check_images)
FRONTMATTER_IMAGE_KEYS = (
    "featured_image",
    "image",
    "thumbnail",
    "cover",
    "banner",
    "header_image",
)

# Colours of the report
OK_STYLE = "green"
WARN_STYLE = "yellow"
BAD_STYLE = "bold red"
DIM_STYLE = "dim"
LINENO_STYLE = "dim cyan"
THEME_STYLE = "dim magenta"  # the tag (nav, foot ...) shown instead of a line number for theme items

console = Console(highlight=False)

# ============================================================================ #
# 1. Settings + the page -> URL function                                       #
# ============================================================================ #


class HugoConfigError(RuntimeError):
    """HUGO_SERVER / HUGO_ROOT are missing in .env."""


def _hugo_settings():
    """Return (server, root) from .env, or raise a clear error saying what to add."""
    s = get_settings()
    if not s.hugo_server:
        raise HugoConfigError(
            "HUGO_SERVER is not set in .env (for example HUGO_SERVER=192.168.1.46:1313)"
        )
    if s.hugo_root is None:
        raise HugoConfigError(
            "HUGO_ROOT is not set in .env "
            "(for example HUGO_ROOT=/Volumes/MacDatosMaster/justtothepoint)"
        )
    return s.hugo_server, s.hugo_root


# ---- small text helpers for front matter ----------------------------------- #

_FM_KEY = re.compile(r"^([A-Za-z_][A-Za-z0-9_-]*)\s*:\s*(.*?)\s*$")


def read_lines(path: Path) -> list:
    """The lines of a file (UTF-8). Line N of this list is line N+1 in your editor."""
    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        return fh.read().replace("\r\n", "\n").replace("\r", "\n").split("\n")


def front_len(lines: list) -> int:
    """How many lines the front matter takes, '---' lines included (0 = no front matter)."""
    if lines and lines[0].lstrip("\ufeff").strip() == "---":
        for i in range(1, len(lines)):
            if lines[i].strip() in ("---", "..."):
                return i + 1
    return 0


def _unquote_value(value: str) -> str:
    """'"abc"' -> 'abc'   and   'abc  # comment' -> 'abc'."""
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        return value[1:-1]
    return re.split(r"\s+#", value)[0].strip()


def _fields_of(path: Path) -> dict:
    """Top-level 'key: value' pairs of a page's front matter ({} if unreadable)."""
    try:
        lines = read_lines(path)
    except OSError:
        return {}
    n = front_len(lines)
    out = {}
    for ln in lines[1 : n - 1] if n else []:
        m = _FM_KEY.match(ln)
        if m:
            out[m.group(1)] = _unquote_value(m.group(2))
    return out


# ---- URL text helpers ------------------------------------------------------ #

_PATH_SAFE = "/%:@!$&'()*+,;=-._~"


def _quote_path(path: str) -> str:
    """Percent-encode what must be encoded and keep what already is (%C3%B1 stays)."""
    return quote(path, safe=_PATH_SAFE)


def _safe_url(url: str) -> str:
    """Make a URL that urllib accepts: encode non-ASCII path/query, IDNA host, drop #fragment."""
    parts = urlsplit(url)
    netloc = parts.netloc
    try:
        netloc.encode("ascii")
    except UnicodeEncodeError:
        host, sep, port = netloc.rpartition(":") if ":" in netloc else (netloc, "", "")
        try:
            netloc = (
                (host.encode("idna").decode("ascii") + sep + port)
                if sep
                else netloc.encode("idna").decode("ascii")
            )
        except UnicodeError:
            pass
    return urlunsplit(
        (
            parts.scheme,
            netloc,
            quote(parts.path, safe=_PATH_SAFE),
            quote(parts.query, safe=_PATH_SAFE + "?"),
            "",
        )
    )


def _urlize(segment: str) -> str:
    """One path segment the way Hugo writes it: lower case, spaces -> hyphens."""
    segment = segment.strip()
    if LOWERCASE_URLS:
        segment = segment.lower()
    return re.sub(r"\s+", "-", segment)


def _content_url_path(path: Path, root: Path) -> str:
    """URL path (always starting and ending with '/') of a file inside root/content.

        content/calculus/lineintegralspace.md  ->  /calculus/lineintegralspace/
        content/calculus/_index.md             ->  /calculus/
        content/posts/mybundle/index.md        ->  /posts/mybundle/
    A `url:` in the page's front matter wins; a `slug:` replaces the last segment.
    """
    content = root / CONTENT_DIR
    try:
        rel = path.relative_to(content)
    except ValueError:
        raise ValueError(
            f"{path} is not inside {content} (check HUGO_ROOT in .env)"
        ) from None
    fields = _fields_of(path)
    if fields.get("url"):
        url = fields["url"]
        return _quote_path(url if url.startswith("/") else "/" + url)
    parts = list(rel.with_suffix("").parts)
    if parts[-1] in ("_index", "index"):
        parts.pop()  # section index / page bundle
    elif fields.get("slug"):
        parts[-1] = fields["slug"]
    parts = [_urlize(p) for p in parts]
    return _quote_path("/" + "/".join(parts) + ("/" if parts else ""))


def page_url(page, include_scheme: bool = True) -> str:
    """The address where Hugo serves `page`.

        page_url("/Volumes/MacDatosMaster/justtothepoint/content/calculus/lineintegralspace.md")
        -> "http://192.168.1.46:1313/calculus/lineintegralspace/"
        page_url(..., include_scheme=False) -> "192.168.1.46:1313/calculus/lineintegralspace/"

    Raises HugoConfigError (HUGO_SERVER / HUGO_ROOT missing in .env) or ValueError
    (the page is not inside HUGO_ROOT/content).
    """
    url = PageContext(page).url
    return url if include_scheme else url.split("://", 1)[1]


# ============================================================================ #
# 2. Finding the links and images of a page                                    #
# ============================================================================ #


@dataclass(frozen=True)
class Ref:
    """One link or image found in a page."""

    line: int  # line number in the file (the same one your editor shows)
    kind: str  # "link" or "image"
    target: str  # exactly as written in the page
    label: str = ""  # link text, or the alt text of an image
    source: str = "markdown"  # markdown | html | shortcode | autolink | bare | definition | frontmatter | theme
    region: str = (
        ""  # only for source == "theme": head | nav | main | aside | foot | meta | page
    )


_FENCE = re.compile(r"^[ \t>]*(`{3,}|~{3,})")
_CODE_SPAN = re.compile(r"(`+)(?!`)(.+?)(?<!`)\1(?!`)")
_DEF = re.compile(r"^ {0,3}\[([^\]]+)\]:\s*(<[^>]*>|\S+)")
_HTML_A = re.compile(
    r"<a\b[^<>]*?\bhref\s*=\s*(?:\"([^\"]*)\"|'([^']*)'|([^\s>\"']+))[^<>]*>", re.I
)
_HTML_IMG = re.compile(r"<img\b[^<>]*>", re.I)
_ATTR = re.compile(
    r"""([A-Za-z_:][-A-Za-z0-9_:.]*)\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s"'>]+))"""
)
_FIGURE = re.compile(r"\{\{[<%]\s*figure\b(.*?)[>%]\}\}", re.I | re.S)
_REF_SC = re.compile(r"\{\{[<%]\s*(?:rel)?ref\s+(?:\"[^\"]+\"|'[^']+'|\S+?)\s*[>%]\}\}")
_AUTOLINK = re.compile(r"<((?:https?://|mailto:)[^>\s]+)>", re.I)
_BARE = re.compile(r"(?<![\w@])(https?://[^\s<>\"'`\]]+)")


def _blank(match) -> str:
    return " " * len(match.group(0))


def _mask_line(line: str, in_comment: bool):
    """Blank out <!-- comments --> and `code spans` (keeping every column in place)."""
    s, pos = line, 0
    if in_comment:
        end = s.find("-->")
        if end == -1:
            return " " * len(s), True
        s, pos = " " * (end + 3) + s[end + 3 :], end + 3
    while True:
        a = s.find("<!--", pos)
        if a == -1:
            break
        b = s.find("-->", a + 4)
        if b == -1:  # the comment goes on in the next lines
            return _CODE_SPAN.sub(_blank, s[:a]) + " " * (len(s) - a), True
        s, pos = s[:a] + " " * (b + 3 - a) + s[b + 3 :], b + 3
    return _CODE_SPAN.sub(_blank, s), False


def _attrs(tag: str) -> dict:
    """{'src': '...', 'alt': '...'} of an HTML tag or Hugo shortcode (names lower-cased)."""
    out = {}
    for m in _ATTR.finditer(tag):
        out[m.group(1).lower()] = next(g for g in m.groups()[1:] if g is not None)
    return out


def _find_open(s: str, close: int):
    """Index of the '[' that matches the ']' at `close` (None if there is none)."""
    depth = 0
    for k in range(close - 1, -1, -1):
        if k and s[k - 1] == "\\":
            continue
        if s[k] == "]":
            depth += 1
        elif s[k] == "[":
            if depth == 0:
                return k
            depth -= 1
    return None


def _parse_dest(s: str, k: int):
    """Parse what follows '](' : destination, optional "title", closing ')'.

    Returns (destination, index after the ')') or None when it is not a real link.
    Handles <angle brackets>, balanced (parentheses) in URLs and {{< relref "x" >}}.
    """
    n = len(s)
    while k < n and s[k] in " \t":
        k += 1
    if k >= n:
        return None
    if s.startswith("{{", k):  # Hugo ref / relref shortcode
        m = _REF_SC.match(s, k)
        if not m:
            return None
        dest, k = m.group(0), m.end()
        frag = re.compile(r"#[^\s)]*").match(s, k)
        if frag:
            dest, k = dest + frag.group(0), frag.end()
    elif s[k] == "<":
        end = s.find(">", k)
        if end == -1:
            return None
        dest, k = s[k + 1 : end], end + 1
    else:
        start, depth = k, 0
        while k < n:
            c = s[k]
            if c == "\\" and k + 1 < n:
                k += 2
                continue
            if c in " \t":
                break
            if c == "(":
                depth += 1
            elif c == ")":
                if depth == 0:
                    break
                depth -= 1
            k += 1
        dest = s[start:k]
    while k < n and s[k] in " \t":
        k += 1
    if k < n and s[k] in "\"'(":  # optional title
        closer = ")" if s[k] == "(" else s[k]
        end = s.find(closer, k + 1)
        if end == -1:
            return None
        k = end + 1
        while k < n and s[k] in " \t":
            k += 1
    if k < n and s[k] == ")":
        return dest, k + 1
    return None


def _scan_line(s: str, n: int, refs: list) -> None:
    """Find the links/images of ONE (already masked) body line."""
    d = _DEF.match(s)
    if d and not d.group(1).startswith("^"):  # [label]: url   (not a footnote)
        refs.append(Ref(n, "link", d.group(2).strip("<>"), d.group(1), "definition"))
        return
    consumed = []  # (start, end) already explained

    def free(pos: int) -> bool:
        return not any(a <= pos < b for a, b in consumed)

    # --- [text](url)  and  ![alt](url)  (also  [![alt](img)](url)) ----------
    i = 0
    while True:
        j = s.find("](", i)
        if j == -1:
            break
        o = _find_open(s, j)
        parsed = _parse_dest(s, j + 2) if o is not None else None
        if parsed is None:
            i = j + 2
            continue
        dest, end = parsed
        is_img = o > 0 and s[o - 1] == "!"
        label = re.sub(r"!\[[^\]]*\]\([^)]*\)", "[image]", s[o + 1 : j]).strip()
        refs.append(Ref(n, "image" if is_img else "link", dest, label))
        consumed.append((o - 1 if is_img else o, end))
        i = end
    # --- <a href="..."> and <img src="..."> ----------------------------------
    for m in _HTML_A.finditer(s):
        if not free(m.start()):
            continue
        href = next(g for g in m.groups() if g is not None)
        close = s.find("</a>", m.end())
        label = (
            re.sub(r"<[^>]+>", "", s[m.end() : close]).strip() if close != -1 else ""
        )
        refs.append(Ref(n, "link", href, label, "html"))
        consumed.append((m.start(), close + 4 if close != -1 else m.end()))
    for m in _HTML_IMG.finditer(s):
        if not free(m.start()):
            continue
        a = _attrs(m.group(0))
        if a.get("src"):
            refs.append(Ref(n, "image", a["src"], a.get("alt", ""), "html"))
        consumed.append(m.span())
    # --- {{< figure src="..." link="..." >}} ----------------------------------
    for m in _FIGURE.finditer(s):
        if not free(m.start()):
            continue
        a = _attrs(m.group(1))
        if a.get("src"):
            refs.append(
                Ref(
                    n,
                    "image",
                    a["src"],
                    a.get("alt") or a.get("caption", ""),
                    "shortcode",
                )
            )
        if a.get("link"):
            refs.append(Ref(n, "link", a["link"], "figure link", "shortcode"))
        consumed.append(m.span())
    # --- <https://autolinks> ----------------------------------------------------
    for m in _AUTOLINK.finditer(s):
        if free(m.start()):
            refs.append(Ref(n, "link", m.group(1), "", "autolink"))
            consumed.append(m.span())
    # --- bare https://addresses in the text ---------------------------------------
    for m in _BARE.finditer(s):
        if not free(m.start()):
            continue
        url = m.group(1).rstrip(".,;:!?*_'\"")
        while url.endswith(")") and url.count(")") > url.count("("):
            url = url[:-1]
        refs.append(Ref(n, "link", url, "", "bare"))


def _scan_front(lines: list, fm_len: int, refs: list) -> None:
    """Images named in the front matter (featured_image: /code/images/x.jpg ...)."""
    in_images = False
    for idx in range(1, fm_len - 1):
        ln, number = lines[idx], idx + 1
        if in_images and re.match(r"^\s*-\s+\S", ln):
            refs.append(
                Ref(
                    number,
                    "image",
                    _unquote_value(re.sub(r"^\s*-\s+", "", ln)),
                    "images",
                    "frontmatter",
                )
            )
            continue
        in_images = False
        m = _FM_KEY.match(ln)
        if not m:
            continue
        key, value = m.group(1), _unquote_value(m.group(2))
        if key in FRONTMATTER_IMAGE_KEYS and value:
            refs.append(Ref(number, "image", value, key, "frontmatter"))
        elif key == "images":
            if value.startswith("["):  # images: [a.jpg, b.jpg]
                for item in value.strip("[]").split(","):
                    if item.strip():
                        refs.append(
                            Ref(
                                number,
                                "image",
                                _unquote_value(item),
                                "images",
                                "frontmatter",
                            )
                        )
            elif not value:
                in_images = True


def scan_page(page) -> list:
    """Every link and image of the page as a list of Ref, in page order.

    Skipped on purpose: fenced code blocks, `inline code` and <!-- comments -->.
    """
    lines = read_lines(Path(page))
    fm = front_len(lines)
    refs: list = []
    if fm:
        _scan_front(lines, fm, refs)
    fence, in_comment = None, False
    for idx in range(fm, len(lines)):
        line = lines[idx]
        m = _FENCE.match(line)
        if fence:
            if (
                m
                and m.group(1)[0] == fence[0]
                and len(m.group(1)) >= len(fence)
                and not line.lstrip(" \t>")[len(m.group(1)) :].strip()
            ):
                fence = None
            continue
        if m:
            fence = m.group(1)
            continue
        masked, in_comment = _mask_line(line, in_comment)
        _scan_line(masked, idx + 1, refs)
    refs.sort(key=lambda r: r.line)  # stable: keeps the order inside a line
    return refs


# ============================================================================ #
# 3. From "what the page says" to "an address we can ask"                      #
# ============================================================================ #


@dataclass(frozen=True)
class Target:
    status: str  # "fetch" = ask a server | "skip" = not checkable | "bad" = wrong as written
    url: str = ""  # absolute address, without #fragment (status == "fetch")
    fragment: str = ""  # the #anchor, decoded
    internal: bool = False  # served by YOUR Hugo server?
    note: str = ""  # why it is skipped / wrong


_SKIP_SCHEMES = {
    "mailto",
    "tel",
    "sms",
    "javascript",
    "data",
    "irc",
    "magnet",
    "skype",
    "geo",
    "whatsapp",
    "file",
    "ftp",
    "sftp",
    "ssh",
    "git",
}


def _locate(base: Path, rel: str):
    """Find `rel` under `base` comparing names EXACTLY (macOS ignores upper/lower case, Linux does not).

    Returns (path, exact) or None.  exact=False means "found, but with different capitals".
    """
    cur, exact = base, True
    for part in Path(rel).parts:
        try:
            names = os.listdir(cur)
        except OSError:
            return None
        if part in names:
            cur = cur / part
            continue
        similar = [x for x in names if x.lower() == part.lower()]
        if not similar:
            return None
        cur, exact = cur / similar[0], False
    return cur, exact


class PageContext:
    """Everything we need to know about ONE page: where it is served and how to read its links."""

    def __init__(self, page):
        self.server, root = _hugo_settings()
        self.root = root.resolve()
        self.path = Path(page).expanduser().resolve()
        self.netloc = urlsplit(self.server).netloc.lower()
        self.url = self.server + _content_url_path(self.path, self.root)

    def resolve(self, raw: str, root_relative: bool = False) -> Target:
        """Turn a link exactly as written in the page into a Target.

        root_relative: relative paths start at the site root (used for front matter
        images such as  featured_image: images/x.jpg).
        """
        target = html.unescape(raw.strip())
        target = re.sub(
            r"\\([!-/:-@\[-`{-~])", r"\1", target
        )  # markdown backslash escapes
        if not target:
            return Target("bad", note="empty target")
        if "{{" in target:
            return self._resolve_shortcode(target)
        if target.startswith("//"):  # //host/path
            target = urlsplit(self.server).scheme + ":" + target
        scheme = urlsplit(target).scheme.lower()
        if scheme == "data":
            return Target("skip", note="inline data: nothing to check")
        if scheme in _SKIP_SCHEMES:
            return Target("skip", note=f"{scheme}: links are not checked")
        if scheme in ("http", "https"):
            absolute = self._as_server(target)
        elif scheme:
            return Target("skip", note=f"{scheme}: not checked")
        else:
            absolute = urljoin(self.server + "/" if root_relative else self.url, target)
        absolute, fragment = urldefrag(absolute)
        absolute = _safe_url(absolute)
        return Target(
            "fetch",
            absolute,
            unquote(fragment),
            urlsplit(absolute).netloc.lower() == self.netloc,
        )

    def _as_server(self, absolute: str) -> str:
        """http://localhost:1313/x  ->  http://192.168.1.46:1313/x   (same port as HUGO_SERVER).

        `hugo server` writes its own links with localhost unless it was started with --baseURL.
        On THIS computer localhost is not your Hugo server, so such links are read as the server's.
        """
        parts, server = urlsplit(absolute), urlsplit(self.server)
        local = {"localhost", "127.0.0.1", "::1", "0.0.0.0"}
        try:
            same_port = server.port is not None and parts.port == server.port
        except ValueError:  # a nonsense port such as :abc
            return absolute
        if (
            same_port
            and (parts.hostname or "").lower() in local
            and (server.hostname or "").lower() not in local
        ):
            return urlunsplit(
                (server.scheme, server.netloc, parts.path, parts.query, parts.fragment)
            )
        return absolute

    def _resolve_shortcode(self, target: str) -> Target:
        """{{< ref "x.md" >}} / {{< relref "x.md#part" >}}  ->  the page's address (if the file exists)."""
        m = re.match(
            r"\{\{[<%]\s*(?:rel)?ref\s+(?:\"([^\"]+)\"|'([^']+)'|(\S+?))\s*[>%]\}\}(#.*)?$",
            target,
        )
        if not m:
            return Target("skip", note="Hugo shortcode: not checked")
        arg = next(g for g in m.groups()[:3] if g)
        arg, _, frag = arg.partition("#")
        frag = frag or (m.group(4) or "")[1:]
        base = (
            self.root / CONTENT_DIR / arg.lstrip("/")
            if arg.startswith("/")
            else self.path.parent / arg
        )
        base = Path(os.path.normpath(base))
        for cand in (
            base,
            base.with_name(base.name + ".md"),
            base / "index.md",
            base / "_index.md",
        ):
            if cand.is_file():
                return Target(
                    "fetch",
                    self.server + _content_url_path(cand.resolve(), self.root),
                    unquote(frag),
                    True,
                )
        return Target("bad", note=f"ref target not found in {CONTENT_DIR}/: {arg}")

    def local_matches(self, url: str) -> list:
        """Where a served file exists on THIS computer: [(folder, path, exact_case?)]."""
        rel = unquote(urlsplit(url).path).lstrip("/")
        found = []
        for folder in (STATIC_DIR, CONTENT_DIR, ASSETS_DIR):
            hit = _locate(self.root / folder, rel) if rel else None
            if hit:
                found.append((folder, hit[0], hit[1]))
        return found


# ============================================================================ #
# 4. Asking the servers                                                        #
# ============================================================================ #


@dataclass
class Probe:
    """What a server answered for one address."""

    url: str
    status: int = 0
    final_url: str = ""
    content_type: str = ""
    length: "int | None" = None  # size in bytes when the server says it
    head: bytes = b""  # first bytes of the file (mode "image")
    ids: "frozenset | None" = None  # the #anchors of the page (modes "body" and "page")
    html: str = ""  # the whole page (mode "page": what a visitor's browser receives)
    error: str = ""  # "" = we got an answer
    timeout: bool = False
    transient: bool = False  # worth one more try

    @property
    def ok(self) -> bool:
        return not self.error and 200 <= self.status < 300


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Never follow redirects automatically: we follow them ourselves to know the final address."""

    def redirect_request(self, *args, **kwargs):
        return None


class _IdCollector(HTMLParser):
    """Collects every id="..." (and <a name="...">) of an HTML page."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.ids: set = set()

    def handle_starttag(self, tag, attrs):
        for key, value in attrs:
            if value and (key == "id" or (key == "name" and tag == "a")):
                self.ids.add(value)


_REGION_TAGS = {
    "header": "head",
    "footer": "foot",
    "nav": "nav",
    "aside": "aside",
    "main": "main",
    "article": "main",
}


def _srcset(value: str) -> list:
    """'a.jpg 1x, b.jpg 2x' -> ['a.jpg', 'b.jpg']"""
    return [part.split()[0] for part in value.split(",") if part.strip()]


class _RenderedScanner(HTMLParser):
    """Finds the links and images of the HTML Hugo really serves (menu, header, footer included).

    items: [(kind, raw target, label, region)]   kind = "link" | "image"
    Links:  <a href>.   Images: <img src/srcset>, <source srcset>, <link rel="...icon">,
    <meta property="og:image">.  Region = the innermost header/nav/main/aside/footer around it
    ("meta" inside <head>, "page" when none).
    """

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.items: list = []
        self._stack: list = []
        self._in_head = False
        self._a = None  # [region, href, text pieces] while inside an <a>

    def _region(self) -> str:
        if self._in_head:
            return "meta"
        return _REGION_TAGS[self._stack[-1]] if self._stack else "page"

    def handle_starttag(self, tag, attrs):
        a = {k.lower(): (v or "") for k, v in attrs}
        if tag == "head":
            self._in_head = True
        elif tag in _REGION_TAGS:
            self._stack.append(tag)
        elif tag == "a" and a.get("href"):
            self._close_a()
            self._a = [self._region(), a["href"], []]
        elif tag == "img":
            alt = a.get("alt", "")
            for src in [a.get("src") or a.get("data-src")] + _srcset(
                a.get("srcset", "")
            ):
                if src:
                    self.items.append(("image", src, alt, self._region()))
            if self._a is not None:
                self._a[2].append(alt)  # an image-only link is named by its alt
        elif tag == "source":
            for src in _srcset(a.get("srcset", "")):
                self.items.append(("image", src, "", self._region()))
        elif tag == "link" and "icon" in a.get("rel", "").lower() and a.get("href"):
            self.items.append(("image", a["href"], "icon", "meta"))
        elif (
            tag == "meta"
            and a.get("content")
            and (
                a.get("property", "").lower() in ("og:image", "og:image:url")
                or a.get("name", "").lower() in ("twitter:image", "twitter:image:src")
            )
        ):
            self.items.append(
                ("image", a["content"], a.get("property") or a.get("name"), "meta")
            )

    def handle_endtag(self, tag):
        if tag == "head":
            self._in_head = False
        elif tag in _REGION_TAGS and tag in self._stack:
            while self._stack and self._stack.pop() != tag:
                pass
        elif tag == "a":
            self._close_a()

    def handle_data(self, data):
        if self._a is not None:
            self._a[2].append(data)

    def _close_a(self):
        if self._a is not None:
            region, href, parts = self._a
            self.items.append(("link", href, " ".join("".join(parts).split()), region))
            self._a = None

    def close(self):
        super().close()
        self._close_a()


def _theme_targets(ctx, page_html: str, kinds, known_targets: list) -> list:
    """The links/images that are in the served HTML but NOT written in the Markdown.

    These come from the theme (menu, header logo, footer, icons...). Returns [(Ref, Target)].
    Left out: things already listed from the Markdown, mailto:/javascript: links, links that stay in
    the same page (table of contents, heading anchors), and repeated ones (shown once with "xN").
    """
    known = {
        (r.kind, t.url.rstrip("/"), t.fragment)
        for r, t in known_targets
        if t.status == "fetch"
    }
    scanner = _RenderedScanner()
    scanner.feed(page_html)
    scanner.close()
    page_key = ctx.url.rstrip("/")
    seen: dict = {}
    for kind, raw, label, region in scanner.items:
        if kind not in kinds:
            continue
        target = ctx.resolve(raw)
        if target.status != "fetch":
            continue
        key = (kind, target.url.rstrip("/"), target.fragment)
        if key in known or (target.fragment and target.url.rstrip("/") == page_key):
            continue
        if key in seen:
            seen[key][0] += 1
        else:
            seen[key] = [1, Ref(0, kind, raw, label, "theme", region), target]
    out = []
    for count, ref, target in seen.values():
        if count > 1:
            ref = replace(ref, label=f"{ref.label} ×{count}".strip())
        out.append((ref, target))
    return out


def make_ssl_context():
    """HTTPS context; uses the `certifi` certificates when installed (fixes macOS python.org builds)."""
    try:
        import certifi

        return ssl.create_default_context(cafile=certifi.where())
    except Exception:
        return ssl.create_default_context()


def _decode(data: bytes, content_type: str) -> str:
    """Bytes -> text using the charset the server announced (UTF-8 when missing or unknown)."""
    charset = re.search(r"charset=([\w-]+)", content_type)
    try:
        return data.decode(charset.group(1) if charset else "utf-8", "replace")
    except LookupError:
        return data.decode("utf-8", "replace")


def _length(headers, status: int):
    """Size of the file: from Content-Range (partial answers) or Content-Length."""
    cr = headers.get("Content-Range")
    if cr and "/" in cr:
        total = cr.rsplit("/", 1)[1].strip()
        return int(total) if total.isdigit() else None
    if status == 206:
        return None
    cl = (headers.get("Content-Length") or "").strip()
    return int(cl) if cl.isdigit() else None


class Checker:
    """Asks servers for addresses, several at a time, and remembers every answer.

    Modes:  "head"  -> is it there?   (HEAD, falling back to GET when the server dislikes HEAD)
            "body"  -> also read the page, to know its #anchors
            "page"  -> read the page and keep its HTML (to find the links/images the theme adds)
            "image" -> read the first bytes of the file and its size
    """

    def __init__(self, server_netloc: str, timeout=None, workers: int = MAX_WORKERS):
        self.netloc = server_netloc.lower()
        self.timeout = TIMEOUT if timeout is None else timeout
        self.workers = workers
        https = urllib.request.HTTPSHandler(context=make_ssl_context())
        # Your own Hugo server is on the local network: never go through a proxy to reach it.
        self._internal = urllib.request.build_opener(
            urllib.request.ProxyHandler({}), _NoRedirect(), https
        )
        self._external = urllib.request.build_opener(_NoRedirect(), https)
        self._cache: dict = {}
        self._lock = threading.Lock()

    # -- public ---------------------------------------------------------------
    def probe(self, url: str, mode: str = "head") -> Probe:
        key = (url, mode)
        with self._lock:
            hit = self._cache.get(key)
        if hit is not None:
            return hit
        try:
            result = self._probe(url, mode)
        except Exception as exc:  # never let one address kill the report
            result = Probe(url, error=f"unexpected error: {exc}")
        with self._lock:
            self._cache[key] = result
        return result

    def run(self, jobs, on_done=None) -> dict:
        """jobs: [(url, mode)] -> {(url, mode): Probe}, asking up to `workers` servers at once."""
        results = {}
        with ThreadPoolExecutor(max_workers=self.workers) as pool:
            futures = {
                pool.submit(self.probe, url, mode): (url, mode) for url, mode in jobs
            }
            for fut in as_completed(futures):
                results[futures[fut]] = fut.result()
                if on_done:
                    on_done()
        return results

    # -- internals ------------------------------------------------------------
    def _probe(self, url: str, mode: str) -> Probe:
        internal = urlsplit(url).netloc.lower() == self.netloc
        opener = self._internal if internal else self._external
        result = Probe(url, error="not asked")
        for _attempt in range(2):  # one retry for timeouts/resets
            result = self._attempt(opener, url, mode)
            if not (result.error and result.transient):
                break
        return result

    def _attempt(self, opener, url: str, mode: str) -> Probe:
        methods = ["GET"] if mode in ("body", "image", "page") else ["HEAD", "GET"]
        result = Probe(url)
        for method in methods:
            result = self._request(opener, url, method, mode)
            if result.error or result.status < 400 or method == "GET":
                return result
        return result

    def _request(self, opener, url: str, method: str, mode: str) -> Probe:
        headers = {"User-Agent": USER_AGENT, "Accept": "*/*", "Accept-Language": "en"}
        if mode == "image":
            headers["Range"] = "bytes=0-511"  # only the first bytes are needed
        probe = Probe(url, final_url=url)
        current, resp = url, None
        try:
            for _hop in range(MAX_REDIRECTS + 1):
                req = urllib.request.Request(current, method=method, headers=headers)
                try:
                    resp = opener.open(req, timeout=self.timeout)
                except urllib.error.HTTPError as exc:  # 3xx/4xx/5xx also carry headers
                    resp = exc
                status = getattr(resp, "status", None) or getattr(resp, "code", 0)
                if status in (301, 302, 303, 307, 308) and resp.headers.get("Location"):
                    current = _safe_url(urljoin(current, resp.headers["Location"]))
                    resp.close()
                    resp = None
                    continue
                break
            else:
                probe.error = "too many redirects (redirect loop?)"
                return probe
            probe.status, probe.final_url = status, current
            raw_type = resp.headers.get("Content-Type", "")
            probe.content_type = raw_type.split(";")[0].strip().lower()
            probe.length = _length(resp.headers, status)
            if method == "GET" and 200 <= status < 300:
                if mode == "image":
                    probe.head = resp.read(512)
                elif mode in ("body", "page") and probe.content_type in (
                    "text/html",
                    "application/xhtml+xml",
                ):
                    text = _decode(resp.read(MAX_BODY_BYTES), raw_type)
                    collector = _IdCollector()
                    collector.feed(text)
                    probe.ids = frozenset(collector.ids)
                    if mode == "page":
                        probe.html = text
            return probe
        except (socket.timeout, TimeoutError):
            probe.error, probe.timeout, probe.transient = (
                f"timeout after {self.timeout:g}s",
                True,
                True,
            )
        except urllib.error.URLError as exc:
            self._describe(probe, exc.reason)
        except (
            ssl.SSLError,
            ConnectionError,
            http.client.HTTPException,
            OSError,
            ValueError,
        ) as exc:
            self._describe(probe, exc)
        finally:
            if resp is not None:
                try:
                    resp.close()
                except Exception:
                    pass
        return probe

    @staticmethod
    def _describe(probe: Probe, reason) -> None:
        """Put a human sentence about a network failure into probe.error."""
        if isinstance(reason, (socket.timeout, TimeoutError)):
            probe.error, probe.timeout, probe.transient = "timeout", True, True
        elif isinstance(reason, ssl.SSLCertVerificationError):
            probe.error = (
                f"SSL certificate problem ({getattr(reason, 'verify_message', reason)})"
            )
        elif isinstance(reason, ssl.SSLError):
            probe.error = f"SSL error ({reason})"
        elif isinstance(reason, socket.gaierror):
            probe.error = "unknown host (DNS)"
        elif isinstance(reason, ConnectionRefusedError):
            probe.error = "connection refused (nothing listens there)"
        elif isinstance(reason, ConnectionResetError):
            probe.error, probe.transient = "connection reset by the server", True
        else:
            probe.error = str(reason) or reason.__class__.__name__


# ============================================================================ #
# 5. Verdicts, evaluation and the report                                       #
# ============================================================================ #


@dataclass(frozen=True)
class Verdict:
    level: str  # "ok" | "warn" (cannot tell) | "bad" (broken) | "skip" (not checked)
    code: str  # "200", "404", "ERR", "-"
    note: str = ""  # explanation (coloured by level)
    extra: str = ""  # additional yellow remark (e.g. "no alt text")


# External sites often refuse automatic requests: they are "cannot tell", not "broken".
UNSURE_STATUS = {401, 403, 429, 451, 503, 999}


def reason(status: int) -> str:
    """'HTTP 404 Not Found'"""
    return f"HTTP {status} {http.client.responses.get(status, '')}".strip()


def moved_note(probe: Probe) -> str:
    """'-> https://final/address' when the server redirected us somewhere else."""
    a = probe.url.rstrip("/")
    b = probe.final_url.rstrip("/")
    return f"→ {probe.final_url}" if probe.final_url and a != b else ""


@dataclass
class Evaluation:
    page: Path
    ctx: "PageContext | None" = None
    fatal: str = ""  # why nothing could be checked
    warning: str = ""
    rows: list = field(default_factory=list)  # [(Ref, Verdict)] in page order


def evaluate(
    page, *, kinds, probe_mode, judge, checker=None, include_theme=True
) -> Evaluation:
    """Scan the page, ask the servers and judge every link/image.

    kinds:         which refs to look at: ("link",) or ("image",)
    probe_mode:    function (ref, target) -> "head" | "body" | "image"
    judge:         function (ref, target, probe, ctx) -> Verdict
    include_theme: also check what the theme adds (menu, header logo, footer...): the page is
                   read as the server renders it and everything not written in the Markdown is added
    """
    ev = Evaluation(Path(page))
    try:
        ev.ctx = ctx = PageContext(ev.page)
        refs = [r for r in scan_page(ev.page) if r.kind in kinds]
    except (HugoConfigError, ValueError) as exc:
        ev.fatal = str(exc)
        return ev
    except OSError as exc:
        ev.fatal = f"cannot read the page: {exc}"
        return ev
    if not refs and not include_theme:
        return ev

    checker = checker or Checker(ctx.netloc)
    home = checker.probe(ctx.url, "page" if include_theme else "head")
    if home.error:
        ev.fatal = (
            f"the Hugo server {ctx.server} does not answer ({home.error}). "
            "Is it running and reachable from this computer? (hugo server --bind 0.0.0.0)"
        )
        return ev
    if home.status == 404:
        ev.warning = (
            f"the server answers 404 for this page itself ({ctx.url}): is it a draft or dated "
            "in the future, not synced yet, or has Hugo not rebuilt?"
        )

    targets = [
        (r, ctx.resolve(r.target, root_relative=(r.source == "frontmatter")))
        for r in refs
    ]
    if include_theme and home.ok:
        if home.html:
            targets += _theme_targets(ctx, home.html, kinds, targets)
        else:
            ev.warning = (
                (ev.warning + " ") if ev.warning else ""
            ) + "the served page is not HTML: menu/header/footer were not checked."
    if not targets:
        return ev
    jobs = sorted(
        {(t.url, probe_mode(r, t)) for r, t in targets if t.status == "fetch"}
    )
    results: dict = {}
    if jobs:
        with Progress(
            SpinnerColumn(),
            TextColumn(f"Checking {len(jobs)} address(es)..."),
            BarColumn(),
            MofNCompleteColumn(),
            transient=True,
            console=console,
        ) as progress:
            task = progress.add_task("", total=len(jobs))
            results = checker.run(jobs, lambda: progress.advance(task))
    for ref, target in targets:
        if target.status == "skip":
            verdict = Verdict("skip", "-", target.note)
        elif target.status == "bad":
            verdict = Verdict("bad", "ERR", target.note)
        else:
            verdict = judge(
                ref, target, results[(target.url, probe_mode(ref, target))], ctx
            )
        ev.rows.append((ref, verdict))
    return ev


_MARK = {
    "ok": ("✓", OK_STYLE),
    "warn": ("!", WARN_STYLE),
    "bad": ("✗", BAD_STYLE),
    "skip": ("–", DIM_STYLE),
}
_NOTE_STYLE = {"ok": DIM_STYLE, "warn": WARN_STYLE, "bad": BAD_STYLE, "skip": DIM_STYLE}


def _render_row(ref: Ref, verdict: Verdict) -> Text:
    mark, style = _MARK[verdict.level]
    row = Text()
    if ref.line:
        row.append(f"{ref.line:>5}  ", style=LINENO_STYLE)
    else:  # from the theme: show where it sits instead of a line
        row.append(f"{ref.region:>5}  ", style=THEME_STYLE)
    row.append(f"{mark} {verdict.code:<4} ", style=style)
    row.append(ref.target or "(empty)")
    if ref.label:
        label = ref.label if len(ref.label) <= 40 else ref.label[:39] + "…"
        row.append(f"  [{label}]", style=DIM_STYLE)
    if verdict.note:
        row.append(f"  {verdict.note}", style=_NOTE_STYLE[verdict.level])
    if verdict.extra:
        row.append(f"  {verdict.extra}", style=WARN_STYLE)
    return row


def print_evaluation(ev: Evaluation, noun: str, show_ok: bool = True) -> int:
    """Print the report. Returns the number of broken items, or -1 when nothing could be checked."""
    console.print(Text(str(ev.page), style="bold"))
    if ev.fatal:
        console.print(Text(ev.fatal, style=BAD_STYLE))
        return -1
    console.print(Text(f"served at {ev.ctx.url}", style=DIM_STYLE))
    if ev.warning:
        console.print(Text(ev.warning, style=WARN_STYLE))
    if not ev.rows:
        console.print(Text(f"no {noun}s found in this page", style=DIM_STYLE))
        return 0
    counts = Counter(v.level for _, v in ev.rows)
    separator_shown = False
    for ref, verdict in ev.rows:
        if verdict.level == "ok" and not show_ok:
            continue
        if not ref.line and not separator_shown:
            console.print(
                Text(
                    "      ── from the theme (menu, header, footer, icons), not written in the Markdown ──",
                    style=THEME_STYLE,
                )
            )
            separator_shown = True
        console.print(_render_row(ref, verdict), soft_wrap=True)
    parts = [f"{counts['ok']} ok"]
    if counts["bad"]:
        parts.append(f"{counts['bad']} broken")
    if counts["warn"]:
        parts.append(f"{counts['warn']} cannot be verified (!)")
    if counts["skip"]:
        parts.append(f"{counts['skip']} skipped")
    theme = sum(1 for ref, _ in ev.rows if not ref.line)
    text = (
        f"{len(ev.rows)} {noun}(s): "
        + ", ".join(parts)
        + (f"  ({theme} from the theme)" if theme else "")
    )
    summary = Text(text, style=BAD_STYLE if counts["bad"] else OK_STYLE)
    console.print(summary)
    return counts["bad"]


def run_check(
    page,
    *,
    noun,
    kinds,
    probe_mode,
    judge,
    show_ok: bool = True,
    include_theme: bool = True,
) -> int:
    """evaluate() + print_evaluation(): what check_links() and check_images() call."""
    ev = evaluate(
        page,
        kinds=kinds,
        probe_mode=probe_mode,
        judge=judge,
        include_theme=include_theme,
    )
    return print_evaluation(ev, noun, show_ok)


# --------------------------------------------------------------------------- #
# Old private names, kept so that scripts written before v0.14 still import   #
# them. The project itself uses read_lines / front_len / make_ssl_context.     #
# --------------------------------------------------------------------------- #
_read_lines = read_lines
_front_len = front_len
_make_ssl_context = make_ssl_context
