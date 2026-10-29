"""
content_render.py - check_render(Path(page)): is the FINAL page (what Hugo serves) really OK?

    from content_render import check_render
    check_render(Path("/Volumes/MacDatosMaster/justtothepoint/content/calculus/stoketheorem.md"))

check_links() and check_images() look at addresses. This one looks at the RESULT: the page as a
visitor's browser receives it, and (when Playwright is installed) as a real browser draws it.
It is read-only: nothing is written (except an optional screenshot you ask for).

The report is a checklist. A check without problems is one line; a check with problems is followed
by the problems, with the line of your Markdown when it can be found:

    /Volumes/.../calculus/stoketheorem.md
    served at http://192.168.1.46:1313/calculus/stoketheorem/
      ✓ the page loads (HTTP 200)
      ✓ math engine: KaTeX 0.16.47 (auto-render)
      ✓ scripts and stylesheets load (6)
      ✗ formulas reach the browser intact
            42  ✗ Markdown changed the formula: the source has '\\{' but the page has '{'  [\\{x\\}]
      ✗ formulas are typeset
            57  ✗ KaTeX cannot draw this formula: Undefined control sequence: \\dd  [\\dd x]
            63  ✗ left as raw text, not typeset  [$\\vec{F}=\\langle x,y\\rangle]
      ✓ formulas fit the window
      ✓ no errors in the browser console
      ✓ no leftovers in the text
      ! HTML structure
            -   ! <div> opened at HTML line 310 is never closed

What is checked
---------------
  the page loads       HTTP status of the page itself.
  math engine          KaTeX or MathJax (or formulas pre-rendered by Hugo) is really loaded; a page with
                       formulas and NO engine shows the raw $...$ to every visitor.
  scripts/stylesheets  every <script src> and stylesheet of the page answers (a 404 on katex.min.js or
                       katex.min.css is the classic reason for formulas that "do not work").
  formulas intact      The formulas in the HTML are compared with the ones in your Markdown. Differences are
                       what Markdown does to LaTeX behind your back: a_b ... c_d turned into italics, "\\\\"
                       reduced to "\\", "\\{" to "{", "\\," lost, the prime f' turned into a curly quote
                       (typographer). This works with the plain HTML, no browser needed.
  formulas typeset     (browser) formulas that KaTeX/MathJax could not draw (error nodes), formulas left as
                       raw text ($...$ visible), fewer formulas drawn than written in the Markdown, KaTeX
                       fonts that failed to load.
  formulas fit         (browser) a formula wider than the window: cut off or needing a horizontal scroll, on a
                       desktop window (1280 px, problem) and on a phone (390 px, warning); a page that scrolls
                       sideways on a phone.
  browser console      (browser) JavaScript errors, files that fail to load (images are left to check_images).
  leftovers            {{< shortcodes >}} shown as text, Hugo template errors (<no value>, ZgotmplZ, %!s(...)),
                       Markdown shown literally (![img](..), **bold**, "##Heading", a table drawn as "| a | b |").
  HTML structure       tags opened and never closed, repeated id= (breaks #anchors), no or several <h1>,
                       empty headings, empty links inside the article, empty <title>.

The "browser" checks need Playwright (once):   pip install playwright && playwright install chromium
Without it they are shown as skipped and everything else still runs.

check_render() returns the number of problems (the "!" warnings are not counted), or -1 when nothing could
be checked (server unreachable, HUGO_SERVER / HUGO_ROOT missing).

    check_render(page, show_ok=False)               only the checks with problems
    check_render(page, browser=False)               skip the browser even if Playwright is installed
    check_render(page, phone=False)                 do not repeat the "fit" check with a phone-sized window
    check_render(page, screenshot_dir="~/shots")    also save a full-page PNG of what the browser saw
"""

from __future__ import annotations

import bisect
import difflib
import html as htmllib
import re
import time
from dataclasses import dataclass, field
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urljoin, urlsplit

from rich.text import Text

from content_urls import (
    BAD_STYLE,
    DIM_STYLE,
    OK_STYLE,
    WARN_STYLE,
    Checker,
    HugoConfigError,
    PageContext,
    USER_AGENT,
    front_len,
    read_lines,
    console,
)

# --------------------------------------------------------------------------- #
# Settings you may want to change                                              #
# --------------------------------------------------------------------------- #

DESKTOP_WIDTH = 1280  # the two window sizes used by the "fit" check
PHONE_WIDTH = 390
BROWSER_TIMEOUT_MS = 30_000  # time allowed to open the page in the browser
MAX_PER_CHECK = 25  # never print more than this many rows for one check
PHONE_ROWS = 5  # phone problems listed one by one (the rest are only counted)
SNIPPET = 70  # characters of a formula shown in the report

# The checks, in the order they are printed: key -> title.
CHECKS = {
    "page": "the page loads",
    "engine": "math engine",
    "resources": "scripts and stylesheets load",
    "intact": "formulas reach the browser intact",
    "typeset": "formulas are typeset",
    "fit": "formulas fit the window",
    "console": "no errors in the browser console",
    "leftovers": "no leftovers in the text",
    "structure": "HTML structure",
}
BROWSER_CHECKS = ("typeset", "fit", "console")


@dataclass
class Finding:
    """One problem found by a check."""

    check: str  # a key of CHECKS
    level: str  # "bad" (counted) or "warn"
    message: str
    line: int = 0  # line of YOUR Markdown file (0 = unknown)
    snippet: str = ""  # the formula / text concerned
    count: int = (
        1  # how many problems this row stands for (a summary row stands for several)
    )
    detail: str = ""  # one more line of explanation, printed under the row


@dataclass
class Report:
    findings: list = field(default_factory=list)
    notes: dict = field(
        default_factory=dict
    )  # check key -> short detail shown after the title
    skipped: dict = field(default_factory=dict)  # check key -> why it was not run
    hints: dict = field(
        default_factory=dict
    )  # check key -> advice printed under its problems

    def add(self, check, level, message, line=0, snippet="", count=1, detail=""):
        finding = Finding(check, level, message, line, snippet, count, detail)
        if finding not in self.findings:
            self.findings.append(finding)


# --------------------------------------------------------------------------- #
# 1. Your Markdown: where are the formulas, and on which line is a given text? #
# --------------------------------------------------------------------------- #

_DISPLAY = re.compile(r"\$\$(.+?)\$\$", re.S)
_INLINE = re.compile(
    r"(?<![\\$])\$(?=[^\s$])((?:\\.|[^$\\]){1,400}?)(?<=[^\s\\])\$(?![\d$])", re.S
)
_PAREN = re.compile(r"\\\((.+?)\\\)", re.S)
_BRACKET = re.compile(r"\\\[(.+?)\\\]", re.S)


def _squash(tex: str) -> str:
    """A formula without any whitespace: the way two versions of it are compared."""
    return re.sub(r"\s+", "", tex)


def _alnum(text: str) -> str:
    """Only letters and digits, lower case: survives wrapping, markup and typographic changes."""
    return re.sub(r"[\W_]+", "", text.lower())


class SourceIndex:
    """Reads your .md file once: its formulas and a way to find the line of any text."""

    def __init__(self, page: Path):
        lines = read_lines(page)
        self.first = front_len(lines)  # lines taken by the front matter
        masked, in_fence = [], False
        for ln in lines[self.first :]:
            if ln.lstrip().startswith(
                ("```", "~~~")
            ):  # code is not math: hide it, keep line numbers
                in_fence = not in_fence
                masked.append(" " * len(ln))
            elif in_fence:
                masked.append(" " * len(ln))
            else:
                masked.append(
                    re.sub(r"`+[^`\n]*`+", lambda m: " " * len(m.group()), ln)
                )
        self.lines = masked
        self.starts, offset = [], 0  # offset where each body line starts in `body`
        for ln in masked:
            self.starts.append(offset)
            offset += len(ln) + 1
        body = "\n".join(masked)

        self.formulas = []  # [(line, tex)]
        work = body
        for rx in (_DISPLAY, _BRACKET, _PAREN, _INLINE):
            for m in rx.finditer(work):
                if re.search(
                    r"\n[ \t]*\n", m.group(1)
                ):  # a blank line ends a paragraph: not a formula
                    continue
                self.formulas.append((self._line_at(m.start()), m.group(1)))
            # blank out what was matched (line breaks kept) so the next pattern cannot pair its $ again
            work = rx.sub(lambda m: re.sub(r"[^\n]", " ", m.group()), work)
        self.formulas.sort()
        self.by_fp, self.tex_of = (
            {},
            {},
        )  # squashed formula -> first line / original text
        for line, tex in self.formulas:
            self.by_fp.setdefault(_squash(tex), line)
            self.tex_of.setdefault(_squash(tex), tex)

        # fingerprint of the whole body to look text up: letters/digits only + a map to the line
        self._fp, self._fp_lines = "", []
        for i, ln in enumerate(masked):
            piece = _alnum(ln)
            self._fp += piece
            self._fp_lines += [self.first + i + 1] * len(piece)

    def _line_at(self, offset: int) -> int:
        """Line number (as in your editor) of a character offset in the body."""
        return self.first + bisect.bisect_right(self.starts, offset)

    def find_line(self, text: str) -> int:
        """Line of your Markdown where `text` appears (0 = not found)."""
        key = _alnum(text)[:30]
        if len(key) < 6:
            return 0
        at = self._fp.find(key)
        return self._fp_lines[at] if at >= 0 else 0

    def find_tag(self, tag: str, closing: bool = False) -> int:
        """First line of your Markdown that contains <tag ...> (or </tag> when closing=True); 0 = none."""
        rx = re.compile(
            r"</%s\b" % re.escape(tag) if closing else r"<%s\b" % re.escape(tag), re.I
        )
        for i, ln in enumerate(self.lines):
            if rx.search(ln):
                return self.first + i + 1
        return 0

    def find_heading(self, text: str) -> int:
        """Line of the '# text' heading in your Markdown (falls back to a plain text search)."""
        want = _alnum(text)
        for i, ln in enumerate(self.lines):
            m = re.match(r"\s{0,3}#{1,6}\s+(.*?)\s*#*\s*$", ln)
            if m and want and _alnum(m.group(1)) == want:
                return self.first + i + 1
        return self.find_line(text)

    def closest(self, squashed: str, cutoff: float = 0.7):
        """(line, squashed formula) of the source formula most like `squashed`, or None."""
        near = difflib.get_close_matches(squashed, list(self.by_fp), n=1, cutoff=cutoff)
        return (self.by_fp[near[0]], near[0]) if near else None


# --------------------------------------------------------------------------- #
# 2. Reading the HTML the server sends                                         #
# --------------------------------------------------------------------------- #

VOID = frozenset(
    "area base br col embed hr img input link meta param source track wbr".split()
)
OPTIONAL_END = frozenset(
    "p li dt dd tr td th thead tbody tfoot option colgroup caption html head body".split()
)
NO_TEXT = frozenset(
    {
        "script",
        "style",
        "pre",
        "code",
        "textarea",
        "noscript",
        "svg",
        "template",
        "title",
    }
)
BLOCKS = frozenset(
    "p li td th div h1 h2 h3 h4 h5 h6 blockquote dd dt figcaption ul ol table tr section article main "
    "header footer aside nav".split()
)
MATH_CLASSES = frozenset(
    {
        "katex",
        "katex-display",
        "katex-error",
        "MathJax",
        "MathJax_Display",
        "MathJax_Preview",
        "mjx-container",
    }
)


class PageScan(HTMLParser):
    """One pass over the page's HTML collecting everything the static checks need."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.stack = []  # open elements: [tag, line, hides_text]
        self.scripts, self.styles = [], []
        self.inline_scripts = []
        self.classes = set()
        self.ids = []
        self.headings = []  # (level, text, line)
        self.title = None
        self.texts = []  # (text, html line, first text of its block?)
        self.issues = []  # ("unclosed"/"stray", tag, html line)
        self.empty_links = []  # (href, html line)
        self._script_buf = None
        self._heading = None
        self._anchors = []  # open <a> inside <main>/<article>
        self._new_block = True

    # -- helpers
    def _hidden(self) -> bool:
        return any(e[2] for e in self.stack)

    def _in_article(self) -> bool:
        return any(e[0] in ("main", "article") for e in self.stack)

    # -- parser callbacks
    def handle_starttag(self, tag, attrs):
        a = {k: (v or "") for k, v in attrs}
        line = self.getpos()[0]
        classes = set(a.get("class", "").split())
        self.classes |= classes
        if a.get("id"):
            self.ids.append(a["id"])
        if tag == "script":
            if a.get("src"):
                self.scripts.append(a["src"])
            else:
                self._script_buf = []
        elif (
            tag == "link" and "stylesheet" in a.get("rel", "").lower() and a.get("href")
        ):
            self.styles.append(a["href"])
        elif tag == "title":
            self.title = ""
        elif tag in ("h1", "h2", "h3", "h4", "h5", "h6"):
            self._heading = [int(tag[1]), [], line]
        elif tag == "a" and self._in_article():
            self._anchors.append(
                {
                    "href": a.get("href", ""),
                    "text": [],
                    "media": bool(a.get("aria-label") or a.get("title")),
                }
            )
        elif tag in ("img", "svg") and self._anchors:
            self._anchors[-1]["media"] = True
        if tag in BLOCKS:
            self._new_block = True
        if tag in VOID:
            return
        hides = tag in NO_TEXT or bool(classes & MATH_CLASSES) or tag.startswith("mjx-")
        self.stack.append([tag, line, hides])

    def handle_endtag(self, tag):
        if tag in VOID:
            return
        line = self.getpos()[0]
        if tag == "script" and self._script_buf is not None:
            self.inline_scripts.append("".join(self._script_buf))
            self._script_buf = None
        elif tag in ("h1", "h2", "h3", "h4", "h5", "h6") and self._heading:
            level, parts, hline = self._heading
            self.headings.append((level, "".join(parts).strip(), hline))
            self._heading = None
        elif tag == "a" and self._anchors:
            anchor = self._anchors.pop()
            if (
                not "".join(anchor["text"]).strip()
                and not anchor["media"]
                and anchor["href"] not in ("", "#")
            ):
                self.empty_links.append((anchor["href"], line))
        if tag in BLOCKS:
            self._new_block = True
        index = max((i for i, e in enumerate(self.stack) if e[0] == tag), default=-1)
        if index < 0:
            self.issues.append(("stray", tag, line))
            return
        for e in reversed(
            self.stack[index + 1 :]
        ):  # elements left open inside this one
            if e[0] not in OPTIONAL_END:
                self.issues.append(("unclosed", e[0], e[1]))
        del self.stack[index:]

    def handle_data(self, data):
        if self._script_buf is not None:
            self._script_buf.append(data)
            return
        if self.title is not None and self.stack and self.stack[-1][0] == "title":
            self.title += data
        if self._heading is not None:
            self._heading[1].append(data)
        for anchor in self._anchors:
            anchor["text"].append(data)
        if self._hidden() or not data.strip():
            return
        self.texts.append((data, self.getpos()[0], self._new_block))
        self._new_block = False

    def finish(self):
        """Call after feed(): elements still open at the end of the file."""
        for tag, line, _ in self.stack:
            if tag not in OPTIONAL_END:
                self.issues.append(("unclosed", tag, line))


def math_spans(page_html: str) -> list:
    """The formulas still written with delimiters in the HTML: [(inner html, inner text)].

    (Formulas already drawn by Hugo or by a script have no delimiters left and are not listed.)
    """
    cleaned = re.sub(r"<!--.*?-->", "", page_html, flags=re.S)
    cleaned = re.sub(
        r"<(script|style|pre|code|textarea|svg)\b.*?</\1\s*>",
        "",
        cleaned,
        flags=re.S | re.I,
    )
    spans = []
    for rx in (_DISPLAY, _BRACKET, _PAREN, _INLINE):
        for m in rx.finditer(cleaned):
            inner = m.group(1)
            if re.search(r"\n[ \t]*\n", inner):
                continue
            spans.append((inner, htmllib.unescape(re.sub(r"<[^>]+>", "", inner))))
        cleaned = rx.sub(lambda m: " " * len(m.group()), cleaned)
    return spans


# --------------------------------------------------------------------------- #
# 3. The checks that need only the HTML                                        #
# --------------------------------------------------------------------------- #


def _short(text: str, n: int = SNIPPET) -> str:
    text = re.sub(r"\s+", " ", text).strip()
    return text if len(text) <= n else text[: n - 1] + "…"


def _version(urls: list, patterns: tuple) -> str:
    for url in urls:
        for pat in patterns:
            m = re.search(pat, url, re.I)
            if m:
                return m.group(1)
    return ""


def detect_engine(scan: PageScan) -> dict:
    """Which math engine does the page use? {"name": "KaTeX"/"MathJax"/"pre-rendered"/"none", ...}"""
    code = (
        " ".join(scan.scripts) + " " + " ".join(scan.inline_scripts)
    ).lower()  # scripts only, not stylesheets
    classes = " ".join(scan.classes).lower()
    urls = scan.scripts + scan.styles
    info = {
        "katex": "katex" in code,
        "mathjax": "mathjax" in code,
        "auto": "auto-render" in code or "rendermathinelement" in code,
        "prerendered": "katex" in scan.classes or "katex-html" in scan.classes,
        "katex_css": any("katex" in u.lower() for u in scan.styles),
    }
    if info["mathjax"] and not info["katex"]:
        info["name"], info["version"] = (
            "MathJax",
            _version(urls, (r"mathjax@?/?(\d[\d.]*)", r"mathjax/(\d[\d.]*)")),
        )
    elif info["katex"]:
        info["name"], info["version"] = (
            "KaTeX",
            _version(
                urls, (r"katex@(\d[\d.]*)", r"/katex/(\d[\d.]*)/", r"KaTeX/(\d[\d.]*)")
            ),
        )
    elif info["prerendered"] or "mjx-container" in classes:
        info["name"], info["version"] = "pre-rendered", ""
    else:
        info["name"], info["version"] = "none", ""
    return info


def check_engine(rep: Report, scan: PageScan, src: SourceIndex, engine: dict):
    name = engine["name"]
    detail = {
        "none": "none loaded",
        "pre-rendered": "formulas pre-rendered by the server (KaTeX)",
    }.get(name)
    if detail is None:
        detail = f"{name}{' ' + engine['version'] if engine['version'] else ''}"
        if name == "KaTeX":
            detail += (
                " (auto-render)" if engine["auto"] else " (no auto-render script seen)"
            )
    rep.notes["engine"] = detail
    if name == "none" and src.formulas:
        rep.add(
            "engine",
            "bad",
            f"your Markdown has {len(src.formulas)} formula(s) but the page loads no KaTeX or MathJax: "
            "visitors will see the raw $...$",
            src.formulas[0][0],
            _short(src.formulas[0][1]),
        )
    if (
        name == "KaTeX"
        and not engine["auto"]
        and not engine["prerendered"]
        and src.formulas
    ):
        rep.add(
            "engine",
            "warn",
            "KaTeX is loaded but no auto-render script / renderMathInElement call was found: "
            "formulas written as $...$ are only drawn if something renders them",
        )
    if (
        (name in ("KaTeX", "pre-rendered"))
        and engine["prerendered"]
        and not engine["katex_css"]
    ):
        rep.add(
            "engine",
            "bad",
            "the page contains KaTeX formulas but no KaTeX stylesheet (katex.min.css): they will look broken",
        )


def check_resources(rep: Report, ctx: PageContext, scan: PageScan, checker: Checker):
    """Every script and stylesheet of the page must answer."""
    urls = []
    for raw in scan.scripts + scan.styles:
        if raw.startswith(("data:", "about:", "javascript:")):
            continue
        full = urljoin(ctx.url, raw)
        if full not in urls:
            urls.append(full)
    sheets = [
        u.split("?")[0].rstrip("/").split("/")[-1]
        for u in urls
        if u in [urljoin(ctx.url, x) for x in scan.styles]
    ]
    rep.notes["resources"] = (
        (
            f"({len(urls)}; stylesheets: {', '.join(sheets)})"
            if sheets
            else f"({len(urls)})"
        )
        if urls
        else ""
    )
    results = checker.run([(u, "head") for u in urls])
    for url in urls:
        probe = results[(url, "head")]
        math = bool(re.search(r"katex|mathjax", url, re.I))
        why = " - formulas cannot be drawn without it" if math else ""
        internal = urlsplit(url).netloc.lower() == ctx.netloc
        if probe.error:
            # an unreachable third-party file (tracker, font...) is a warning; your own files and the math libraries are problems
            level = "bad" if (internal or math) else "warn"
            rep.add("resources", level, f"{probe.error}: {_short(url, 90)}{why}")
        elif probe.status >= 400:
            rep.add("resources", "bad", f"HTTP {probe.status}: {_short(url, 90)}{why}")


# What Markdown does to LaTeX, in words.
_TAG_HINTS = {
    "em": "an underscore or asterisk pair became italics (<em>): in Markdown write \\_ or use passthrough",
    "i": "an underscore pair became italics: write \\_ or use passthrough",
    "strong": "asterisks became bold (<strong>): write \\* or use passthrough",
    "b": "asterisks became bold: write \\* or use passthrough",
    "br": "a line break (<br>) was inserted inside the formula: do not end a line with \\\\ or two spaces in it",
    "a": "part of the formula became a link",
    "del": "~~ became a strike-through",
}


def _explain_difference(source: str, page: str) -> str:
    """Say what changed between the formula in the Markdown and the one in the page."""
    sm = difflib.SequenceMatcher(None, source, page, autojunk=False)
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal":
            continue
        a, b = source[max(0, i1 - 2) : i2 + 2], page[max(0, j1 - 2) : j2 + 2]
        lost, got = source[i1:i2], page[j1:j2]
        what = f'the Markdown has "{a}" but the page has "{b}"'

        if any(ch in got for ch in "’‘“”–—…"):
            return (
                what
                + ": Hugo's typographer changed quotes/dashes (set markup.goldmark.extensions.typographer to false, or use passthrough)"
            )
        if "\\" in lost:
            return (
                what
                + ": Markdown ate a backslash (\\\\ \\{ \\, \\; \\|): enable markup.goldmark.extensions.passthrough or double it"
            )
        return what
    return "the formula differs"


_BLOCK_TAG = re.compile(
    r"</?(?:p|div|li|ul|ol|h[1-6]|table|thead|tbody|tr|td|th|blockquote|pre|section|article|"
    r"header|footer|nav|aside|figure|hr)\b",
    re.I,
)


def check_formulas_intact(
    rep: Report, page_html: str, src: SourceIndex, spans=None
) -> int:
    """Compare every formula of the HTML with those of the Markdown. Returns how many were compared.

    spans: [(inner html, inner text)]; default: the formulas still written with delimiters in the HTML.
    """
    spans = math_spans(page_html) if spans is None else spans
    for inner, text in spans:
        # Two unrelated $ signs (prices...) can enclose ordinary text, even whole paragraphs: that is not a formula.
        if len(inner) > 800 or _BLOCK_TAG.search(inner):
            continue
        squashed = _squash(text)
        tags = {t.lower() for t in re.findall(r"<([a-zA-Z][a-zA-Z0-9]*)\b", inner)}
        tags -= {"span"}
        if tags:
            near = src.closest(
                squashed
            )  # only a span that resembles a formula of YOUR file counts
            if not near:
                continue
            line = near[0]
            hint = next(
                (
                    _TAG_HINTS[t]
                    for t in ("em", "i", "strong", "b", "br", "a", "del")
                    if t in tags
                ),
                "HTML tags appear inside the formula (" + ", ".join(sorted(tags)) + ")",
            )
            shown = src.tex_of.get(near[1], text) if near else text
            rep.add(
                "intact",
                "bad",
                "Markdown changed the formula: " + hint,
                line,
                _short(shown),
            )
            continue
        if not squashed or squashed in src.by_fp:
            continue
        near = src.closest(squashed)
        if near:
            rep.add(
                "intact",
                "bad",
                "Markdown changed the formula: "
                + _explain_difference(near[1], squashed),
                near[0],
                _short(src.tex_of.get(near[1], near[1])),
            )
        elif (
            src.formulas
        ):  # a formula of the page that is not in the file (theme, shortcode...)
            continue
    return len(spans)


_LEFTOVERS = (
    ("bad", r"\{\{[<%]", "a Hugo shortcode was not processed and is shown as text"),
    (
        "bad",
        r"<no value>|ZgotmplZ|%!\w\(|error calling |can't evaluate field",
        "Hugo template error visible in the page",
    ),
    (
        "bad",
        r"!\[[^\]]*\]\([^)\s]+[^)]*\)",
        "an image written in Markdown was not converted",
    ),
    (
        "bad",
        r"\|\s*:?-{3,}:?\s*\|",
        "a Markdown table was not recognised (a blank line before the table is required)",
    ),
    (
        "warn",
        r"(?<![\w\[!])\[[^\]\n]+\]\((?:https?://|/|#)[^)\s]*\)",
        "a Markdown link was not converted",
    ),
    ("warn", r"(?<!\w)\*\*[^\s*][^*\n]*\*\*", "**bold** was not converted"),
    ("warn", r"<!--", "an HTML comment is visible"),
)


def check_leftovers(rep: Report, scan: PageScan, src: SourceIndex):
    """Things that should have been turned into HTML but are visible as text."""
    for text, _line, first in scan.texts:
        for level, pattern, message in _LEFTOVERS:
            m = re.search(pattern, text)
            if m:
                found = text[max(0, m.start() - 10) : m.end() + 25]
                rep.add(
                    "leftovers",
                    level,
                    message,
                    src.find_line(text.strip()[:60]),
                    _short(found),
                )
        if first and re.match(r"\s*#{1,6}[^\s#]", text):
            rep.add(
                "leftovers",
                "warn",
                "a heading was not recognised (a space is required after the #)",
                src.find_line(text.strip()[:60]),
                _short(text),
            )


def check_structure(rep: Report, scan: PageScan, src: SourceIndex):
    for kind, tag, line in scan.issues[:8]:
        if kind == "unclosed":
            rep.add(
                "structure",
                "warn",
                f"<{tag}> opened at HTML line {line} is never closed",
                src.find_tag(tag),
            )
        else:
            rep.add(
                "structure",
                "warn",
                f"</{tag}> at HTML line {line} closes nothing",
                src.find_tag(tag, closing=True),
            )
    for ident in sorted({i for i in scan.ids if scan.ids.count(i) > 1}):
        rep.add(
            "structure",
            "warn",
            f"id={ident!r} is used more than once: #anchors and the table of contents will jump to the first",
        )
    h1 = [h for h in scan.headings if h[0] == 1]
    if len(h1) != 1:
        message = (
            "the page has no <h1>"
            if not h1
            else f"the page has {len(h1)} <h1> headings"
        )
        lines = [n for n in (src.find_heading(h[1]) for h in h1) if n]
        if lines:
            message += (
                " (your Markdown has # headings at lines "
                + ", ".join(str(n) for n in lines[:8])
                + (" ..." if len(lines) > 8 else "")
                + ")"
            )
        rep.add("structure", "warn", message)
    for level, text, line in scan.headings:
        if not text:
            rep.add("structure", "warn", f"empty <h{level}> at HTML line {line}")
    for href, line in scan.empty_links[:5]:
        rep.add(
            "structure",
            "warn",
            f"link without text inside the article (HTML line {line}): {_short(href, 60)}",
        )
    if scan.title is not None and not scan.title.strip():
        rep.add("structure", "warn", "the <title> is empty")
    elif scan.title is None:
        rep.add("structure", "warn", "the page has no <title>")


# --------------------------------------------------------------------------- #
# 4. The browser pass (optional)                                               #
# --------------------------------------------------------------------------- #

# JavaScript run INSIDE the page after the math engine has finished. It only reads the page.
COLLECT_JS = r"""
async () => {
  try { await document.fonts.ready; } catch (e) {}
  const skip = 'script,style,textarea,pre,code,noscript,svg,option,.katex,.katex-display,mjx-container,.MathJax,.MathJax_Display,.MathJax_Preview';
  const out = {katex: (window.katex && window.katex.version) || '',
               mathjax: (window.MathJax && (window.MathJax.version || (window.MathJax.startup ? '3' : '2'))) || '',
               rendered: 0, errors: [], raw: [], tex: [], fontErrors: [], hasKatexFont: false};
  const tex = (el) => { const a = el.querySelector('annotation[encoding="application/x-tex"]');
                        return a ? a.textContent : (el.getAttribute('data-latex') || ''); };
  out.rendered = document.querySelectorAll('.katex').length + document.querySelectorAll('mjx-container').length +
                 document.querySelectorAll('span.MathJax').length;
  document.querySelectorAll('.katex-error').forEach(e => out.errors.push({tex: e.textContent, message: e.getAttribute('title') || 'KaTeX error'}));
  // KaTeX draws an unknown command in the error colour (#cc0000) INSIDE the formula instead of making an error node.
  document.querySelectorAll('.katex').forEach(k => {
    if (k.closest('.katex-error')) return;
    const names = [...new Set([...k.querySelectorAll('mstyle[mathcolor="#cc0000"]')].map(m => m.textContent.trim()).filter(Boolean))];
    if (names.length) out.errors.push({tex: tex(k), unknown: names.join(' ')});
  });
  document.querySelectorAll('mjx-merror,[data-mjx-error],.MathJax_Error').forEach(e =>
    out.errors.push({tex: (e.closest('mjx-container') && e.closest('mjx-container').getAttribute('data-latex')) || '',
                     message: e.getAttribute('data-mjx-error') || e.textContent || 'MathJax error'}));
  document.querySelectorAll('.katex').forEach(e => { if (!e.closest('.katex-error')) { const t = tex(e); if (t) out.tex.push(t); } });
  const rx = /\$\$[\s\S]+?\$\$|\$(?=[^\s$])[^$\n]+?(?<=\S)\$(?!\d)|\\\([\s\S]+?\\\)|\\\[[\s\S]+?\\\]|\\begin\{[a-zA-Z*]+\}/g;
  const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
  while (walker.nextNode()) {
    const node = walker.currentNode;
    if (!node.parentElement || node.parentElement.closest(skip)) continue;
    const found = node.nodeValue.match(rx);
    if (found) found.forEach(f => { if (/\\[a-zA-Z]|[\^_{]/.test(f)) out.raw.push(f.slice(0, 160)); });
  }
  for (const f of document.fonts) { if (/katex|mathjax/i.test(f.family)) { out.hasKatexFont = true; if (f.status === 'error') out.fontErrors.push(f.family); } }
  return out;
}
"""

OVERFLOW_JS = r"""
() => {
  const vw = document.documentElement.clientWidth;
  const tex = (el) => { const a = el.querySelector('annotation[encoding="application/x-tex"]');
                        return a ? a.textContent : (el.textContent || '').trim(); };
  const out = {viewport: vw, pageWidth: document.documentElement.scrollWidth, items: []};
  const flagged = new Set();
  const describe = (e) => e.tagName.toLowerCase() + (e.id ? '#' + e.id : '') +
                          (e.classList.length ? '.' + [...e.classList].slice(0, 2).join('.') : '');
  // The OUTERMOST ancestor wider than the window is the one that lets the page grow.
  const culprit = (el) => {
    let found = null;
    for (let n = el.parentElement; n && n !== document.documentElement && n !== document.body; n = n.parentElement) {
      const right = n.getBoundingClientRect().right;
      if (right > vw + 1) found = {el: describe(n), right: Math.round(right),
                                   parent: n.parentElement ? getComputedStyle(n.parentElement).display : ''};
    }
    return found;
  };
  // Which of the page's stylesheets sets `prop` for this element (the last matching rule wins, as an approximation).
  const ruleFor = (el, prop) => {
    let hit = '';
    const walk = (rules, sheet) => {
      for (const rule of rules) {
        if (rule.type === 1) { try { if (rule.style.getPropertyValue(prop) && el.matches(rule.selectorText))
            hit = (sheet.href ? sheet.href.split('/').pop().split('?')[0] : 'inline <style>') + ': ' + rule.selectorText; } catch (e) {} }
        else if (rule.type === 4 && window.matchMedia(rule.media.mediaText).matches) walk(rule.cssRules, sheet);
      }
    };
    for (const sheet of document.styleSheets) { try { walk(sheet.cssRules, sheet); } catch (e) {} }   // cross-origin sheets are unreadable
    return hit;
  };
  const wrapper = 'mjx-container[display="true"], .katex-display';
  const consider = (el) => {
    const outer = el.parentElement && el.parentElement.closest(wrapper);
    if (outer && flagged.has(outer)) return;                      // already reported through its display wrapper
    const r = el.getBoundingClientRect();
    if (r.width === 0 && r.height === 0) return;
    const ox = getComputedStyle(el).overflowX;
    const scrolls = ['auto', 'scroll', 'hidden', 'clip'].includes(ox);
    const reach = r.left + Math.max(r.width, scrolls ? 0 : el.scrollWidth);   // where its content really ends
    let how = '', kind = '';
    if (reach > vw + 1 || r.left < -1) { how = 'sticks out of the window'; kind = 'out'; }
    else if (scrolls && el.scrollWidth - el.clientWidth > Math.max(6, el.clientWidth * 0.03)) {   // ignore the 1-2 px overhang of subscripts
      if (ox === 'hidden' || ox === 'clip') { how = 'is cut off'; kind = 'cut'; }
      else { how = 'needs a horizontal scroll'; kind = 'scroll'; }
    }
    if (how) { flagged.add(el); out.items.push({how: how, kind: kind, tex: tex(el), reach: Math.round(reach),
                                                width: Math.round(Math.max(r.width, el.scrollWidth)),
                                                culprit: kind === 'out' ? culprit(el) : null,
                                                box: kind === 'out' ? {el: describe(el), display: getComputedStyle(el).display, overflowX: ox,
                                                                       maxWidth: getComputedStyle(el).maxWidth, rule: ruleFor(el, 'overflow-x')} : null}); }
  };
  document.querySelectorAll(wrapper).forEach(consider);
  document.querySelectorAll('.katex, mjx-container').forEach(consider);
  return out;
}
"""


@dataclass
class BrowserResult:
    engine: str = ""
    rendered: int = 0
    errors: list = field(default_factory=list)
    raw: list = field(default_factory=list)
    tex: list = field(default_factory=list)
    font_errors: list = field(default_factory=list)
    has_math_font: bool = False
    desktop: dict = field(default_factory=dict)
    phone: dict = field(default_factory=dict)
    console_errors: list = field(default_factory=list)
    failed_requests: list = field(default_factory=list)
    screenshot: str = ""


def run_browser(url: str, screenshot_dir=None, phone: bool = True) -> BrowserResult:
    """Open the page in headless Chromium, wait for the math engine, collect facts.

    Raises ImportError (Playwright not installed) or RuntimeError (Chromium cannot start).
    """
    from playwright.sync_api import Error as PlaywrightError  # may raise ImportError
    from playwright.sync_api import sync_playwright

    result = BrowserResult()
    with sync_playwright() as pw:
        try:
            browser = pw.chromium.launch(headless=True)
        except PlaywrightError as exc:
            raise RuntimeError(
                "Chromium is not installed for Playwright: run  playwright install chromium"
                f"  ({str(exc).splitlines()[0][:100]})"
            ) from None
        try:
            context = browser.new_context(
                viewport={"width": DESKTOP_WIDTH, "height": 900}, user_agent=USER_AGENT
            )
            page = context.new_page()
            page.on(
                "console",
                lambda m: (
                    result.console_errors.append(m.text)
                    if m.type == "error"
                    and not m.text.startswith("Failed to load resource")
                    else None
                ),
            )
            page.on("pageerror", lambda e: result.console_errors.append(str(e)))
            failed = {}  # url -> "HTTP 404" / reason (one entry per url)
            page.on(
                "requestfailed",
                lambda r: (
                    failed.setdefault(r.url, str(r.failure))
                    if r.resource_type != "image"
                    else None
                ),
            )
            page.on(
                "response",
                lambda r: (
                    failed.__setitem__(r.url, f"HTTP {r.status}")
                    if r.status >= 400
                    and r.request.resource_type not in ("image", "document")
                    else None
                ),
            )
            page.goto(url, wait_until="load", timeout=BROWSER_TIMEOUT_MS)
            try:
                page.wait_for_load_state("networkidle", timeout=8000)
            except PlaywrightError:
                pass  # a page that never goes idle is still analysable
            try:  # MathJax 3 tells when it has finished
                page.evaluate(
                    "() => (window.MathJax && MathJax.startup && MathJax.startup.promise) ? MathJax.startup.promise.then(() => true) : true"
                )
            except PlaywrightError:
                pass
            page.wait_for_timeout(500)
            data = page.evaluate(COLLECT_JS)
            result.engine = " ".join(
                x
                for x in (
                    ("KaTeX " + data["katex"]) if data["katex"] else "",
                    ("MathJax " + data["mathjax"]) if data["mathjax"] else "",
                )
                if x
            )
            result.rendered, result.errors, result.raw = (
                data["rendered"],
                data["errors"],
                data["raw"],
            )
            result.tex, result.font_errors, result.has_math_font = (
                data["tex"],
                data["fontErrors"],
                data["hasKatexFont"],
            )
            result.desktop = page.evaluate(OVERFLOW_JS)
            if screenshot_dir:
                folder = Path(screenshot_dir).expanduser()
                folder.mkdir(parents=True, exist_ok=True)
                target = folder / (
                    re.sub(r"[^\w.-]+", "_", urlsplit(url).path.strip("/")) or "index"
                )
                shot = str(target) + "-render.png"
                page.screenshot(path=shot, full_page=True)
                result.screenshot = shot
            if phone:
                page.set_viewport_size({"width": PHONE_WIDTH, "height": 800})
                page.wait_for_timeout(300)
                result.phone = page.evaluate(OVERFLOW_JS)
            result.failed_requests = [f"{url} ({why})" for url, why in failed.items()]
        finally:
            browser.close()
    return result


def check_browser_results(
    rep: Report,
    res: BrowserResult,
    src: SourceIndex,
    engine: dict,
    static_compared: int,
    netloc: str = "",
):
    """Turn what the browser saw into findings."""
    phone_checked = bool(res.phone)
    for item in res.errors:
        tex = item.get("tex", "")
        if item.get("unknown"):
            message = f"the formula uses a command or symbol the engine does not know: {item['unknown']}"
        else:
            message = (
                "the engine cannot draw this formula: "
                + re.sub(r"\s+", " ", item.get("message", "")).strip()
            )
        rep.add(
            "typeset",
            "bad",
            message,
            src.by_fp.get(_squash(tex)) or src.find_line(tex),
            _short(tex),
        )
    mathjax = "MathJax" in res.engine
    for raw in res.raw:
        hint = ""
        if mathjax and raw.startswith("$") and not raw.startswith("$$"):
            hint = " (MathJax reads only \\(...\\) unless inlineMath: [['$','$']] is configured)"
        rep.add(
            "typeset",
            "bad",
            "formula left as raw text, not typeset" + hint,
            src.find_line(raw.strip("$\\()[] ")),
            _short(raw),
        )
    if res.rendered < len(src.formulas) and not res.raw and not res.errors:
        rep.add(
            "typeset",
            "warn",
            f"your Markdown has {len(src.formulas)} formulas but the browser drew {res.rendered}",
        )
    for family in sorted(set(res.font_errors)):
        rep.add(
            "typeset",
            "bad",
            f"the math font {family!r} could not be loaded: formulas will look wrong",
        )
    if (
        res.rendered
        and engine["name"] != "none"
        and "KaTeX" in res.engine
        and not res.has_math_font
    ):
        rep.add(
            "typeset",
            "bad",
            "KaTeX formulas were drawn but the KaTeX fonts are not declared: katex.min.css is missing or not applied",
        )
    if not (res.rendered or res.raw or res.errors):
        rep.notes["typeset"] = "(no formulas on the page)"
    else:
        rep.notes["typeset"] = (
            f"({res.rendered} drawn, {len(res.errors)} with errors, {len(res.raw)} left raw)"
        )
    # the formulas as the browser parsed them: same comparison as the HTML one, if the HTML had none
    if static_compared == 0 and res.tex:
        check_formulas_intact(rep, "", src, spans=[(t, t) for t in res.tex])
        rep.notes["intact"] = f"({len(res.tex)} compared, read from the drawn formulas)"
    # fit
    sticks_out = sticks_css = inline_trap = False
    for label, level, data in (
        ("desktop", "bad", res.desktop),
        ("phone", "warn", res.phone),
    ):
        items = data.get("items", [])
        scroll = [
            i for i in items if i.get("kind") == "scroll"
        ]  # acceptable: the formula scrolls inside its own box
        others = [i for i in items if i.get("kind") != "scroll"]
        by_line = lambda i: src.by_fp.get(_squash(i.get("tex", "")), 0)
        dropped, hidden_scroll = [], 0
        if (
            label == "phone" and len(others) > PHONE_ROWS
        ):  # one cause, many rows: show the widest, count the rest
            widest = sorted(others, key=lambda i: -i["width"])
            dropped, others = (
                widest[PHONE_ROWS:],
                sorted(widest[:PHONE_ROWS], key=by_line),
            )
        hidden = len(dropped)
        if len(scroll) > PHONE_ROWS:
            widest = sorted(scroll, key=lambda i: -i["width"])
            hidden_scroll, scroll = (
                len(scroll) - PHONE_ROWS,
                sorted(widest[:PHONE_ROWS], key=by_line),
            )
        items = others + scroll
        for item in items[:MAX_PER_CHECK]:
            tex = item.get("tex", "")
            kind = item.get("kind", "out")
            # a formula that scrolls inside its own box is acceptable (warning); one that widens the page or is cut off is not
            lvl = "warn" if kind == "scroll" else level
            detail = (
                f"{item['width']} px wide, its right edge at {item['reach']} px"
                if kind == "out"
                else f"{item['width']} px wide"
            )
            why, culprit, box = [], item.get("culprit"), item.get("box")
            if box and label == "desktop":  # the facts about the formula's own box
                source = (
                    f"overflow-x set by {box['rule']}"
                    if box.get("rule")
                    else "no stylesheet sets overflow-x for it"
                )
                why.append(
                    f"the formula's box is <{box['el']}>: display:{box['display']}, overflow-x:{box['overflowX']}, "
                    f"max-width:{box['maxWidth']} ({source})"
                )
                css_applies = box["overflowX"] in ("auto", "scroll")
                if box["display"] == "inline" and (
                    css_applies or box["maxWidth"] != "none"
                ):
                    # the classic trap: max-width and overflow do nothing on an inline box (KaTeX's .katex is inline)
                    why.append(
                        "an inline box ignores max-width and overflow-x, so those rules do nothing here: "
                        "add  display: inline-block;  to the same CSS rule"
                    )
                    inline_trap = True
                sticks_css = sticks_css or not css_applies
            if culprit and label == "desktop":  # name the box that lets the page grow
                text = f"the container that is too wide is <{culprit['el']}> (right edge at {culprit['right']} px)"
                if any(k in culprit.get("parent", "") for k in ("flex", "grid")):
                    text += (
                        f"; its parent is display:{culprit['parent']} and such an item cannot shrink below its "
                        "content: give it min-width: 0"
                    )
                why.append(text)
            why = "\n".join(why)
            rep.add(
                "fit",
                lvl,
                f"on {label} ({data['viewport']} px) a formula {item['how']} ({detail})",
                src.by_fp.get(_squash(tex)) or src.find_line(tex),
                _short(tex),
                detail=why,
            )
            sticks_out = sticks_out or kind == "out"
        if hidden:
            rep.add(
                "fit",
                "warn",
                f"on {label} {hidden} more formulas also do not fit (only the {PHONE_ROWS} widest are listed)",
                count=hidden,
            )
            sticks_out = sticks_out or any(i.get("kind") == "out" for i in dropped)
        if hidden_scroll:
            rep.add(
                "fit",
                "warn",
                f"on {label} {hidden_scroll} more formulas need a horizontal scroll (only the {PHONE_ROWS} widest are listed)",
                count=hidden_scroll,
            )
        if data and data.get("pageWidth", 0) > data.get("viewport", 0) + 1:
            rep.add(
                "fit",
                level,
                f"on {label} the page scrolls sideways: it is {data['pageWidth']} px wide in a {data['viewport']} px window",
            )
            sticks_out = True
    if sticks_out:
        if inline_trap:
            rep.hints["fit"] = (
                "your CSS gives the formulas overflow-x:auto but they are display:inline, where it has no effect: "
                "p .katex, li .katex { display: inline-block; max-width: 100%; overflow-x: auto; overflow-y: hidden; }"
            )
        elif sticks_css or not res.desktop.get("items"):
            rep.hints["fit"] = (
                "a wide formula cannot wrap, so it widens the whole page. In your CSS, "
                ".katex-display { overflow-x: auto; overflow-y: hidden; max-width: 100%; } "
                "lets each one scroll by itself; or split the formula into several lines."
            )
        else:
            rep.hints["fit"] = (
                "the formulas already have overflow-x:auto, so a parent is what is too wide "
                "(see the container lines); check that the stylesheet with those rules is the one the page loads."
            )
    rep.notes["fit"] = f"(desktop {DESKTOP_WIDTH} px" + (
        f", phone {PHONE_WIDTH} px)" if phone_checked else ")"
    )
    # console
    for text in dict.fromkeys(res.console_errors):
        if (
            "livereload" in text.lower()
        ):  # `hugo server` injects it; its WebSocket may fail harmlessly
            continue
        rep.add("console", "bad", "JavaScript error: " + _short(text, 160))
    already = " ".join(
        f.message for f in rep.findings if f.check == "resources"
    )  # said by the resources check
    for text in dict.fromkeys(res.failed_requests):
        url = text.split(" (")[0]
        if url in already or "livereload" in url.lower():
            continue
        mine = (not netloc) or urlsplit(
            url
        ).netloc.lower() == netloc  # a failing third-party file is only a warning
        rep.add(
            "console",
            "bad" if mine else "warn",
            "file not loaded: " + _short(text, 160),
        )


# --------------------------------------------------------------------------- #
# 5. Printing                                                                  #
# --------------------------------------------------------------------------- #


def _row(f: Finding) -> Text:
    row = Text("      ")
    row.append(f"{f.line:>5}  " if f.line else "    -  ", style=DIM_STYLE)
    row.append(
        "✗ " if f.level == "bad" else "! ",
        style=BAD_STYLE if f.level == "bad" else WARN_STYLE,
    )
    row.append(f.message, style="red" if f.level == "bad" else WARN_STYLE)
    if f.snippet:
        row.append("  [" + f.snippet + "]", style="cyan")
    return row


def print_report(page: Path, url: str, rep: Report, show_ok: bool = True) -> int:
    """Print the checklist; returns the number of problems ("bad" findings)."""
    console.print(Text(str(page), style="bold"))
    console.print(Text(f"served at {url}", style=DIM_STYLE))
    bad = 0
    for key, title in CHECKS.items():
        found = [f for f in rep.findings if f.check == key]
        problems = [f for f in found if f.level == "bad"]
        bad += sum(f.count for f in problems)
        note = rep.notes.get(key, "")
        if key in rep.skipped and not found:
            if show_ok:
                console.print(
                    Text(
                        f"  – {title}  (skipped: {rep.skipped[key]})", style=DIM_STYLE
                    ),
                    soft_wrap=True,
                )
            continue
        if not found:
            if show_ok:
                line = Text("  ✓ ", style=OK_STYLE)
                line.append(title + (f"  {note}" if note else ""))
                console.print(line, soft_wrap=True)
            continue
        head = Text(
            "  ✗ " if problems else "  ! ", style=BAD_STYLE if problems else WARN_STYLE
        )
        head.append(title + (f"  {note}" if note else ""), style="bold")
        console.print(head, soft_wrap=True)
        for f in found[:MAX_PER_CHECK]:
            console.print(_row(f), soft_wrap=True)
            for extra in f.detail.split("\n") if f.detail else ():
                console.print(
                    Text("                " + extra, style=DIM_STYLE), soft_wrap=True
                )
        if len(found) > MAX_PER_CHECK:
            console.print(
                Text(
                    f"        ... and {len(found) - MAX_PER_CHECK} more",
                    style=DIM_STYLE,
                )
            )
        if key in rep.hints:
            console.print(
                Text("      hint: " + rep.hints[key], style=DIM_STYLE), soft_wrap=True
            )
    warns = sum(f.count for f in rep.findings if f.level == "warn")
    summary = Text(
        f"{bad} problem(s), {warns} warning(s)"
        if (bad or warns)
        else "the page renders without problems",
        style=BAD_STYLE if bad else (WARN_STYLE if warns else OK_STYLE),
    )
    console.print(summary)
    return bad


# --------------------------------------------------------------------------- #
# 6. The function you call                                                     #
# --------------------------------------------------------------------------- #


def check_render(
    page, show_ok: bool = True, browser="auto", screenshot_dir=None, phone: bool = True
) -> int:
    """Check that the page Hugo serves renders well. Returns the number of problems (-1 = could not check).

    page:           path of the .md file inside HUGO_ROOT/content (Path or str).
    show_ok:        False = print only the checks with problems.
    browser:        "auto" = use a real browser when Playwright is installed; True = same, but say so
                    loudly when it cannot be used; False = HTML checks only.
    screenshot_dir: folder where a full-page PNG of what the browser saw is saved (None = no screenshot).
    phone:          False = do not repeat the "formulas fit" check with a phone-sized window.
    """
    page = Path(page)
    try:
        ctx = PageContext(page)
        src = SourceIndex(page)
    except (HugoConfigError, ValueError) as exc:
        console.print(Text(str(page), style="bold"))
        console.print(Text(str(exc), style=BAD_STYLE))
        return -1
    except OSError as exc:
        console.print(Text(f"cannot read the page: {exc}", style=BAD_STYLE))
        return -1

    rep = Report()
    checker = Checker(ctx.netloc)
    started = time.time()
    probe = checker.probe(ctx.url, "page")
    if probe.error:
        console.print(Text(str(page), style="bold"))
        console.print(
            Text(
                f"the Hugo server {ctx.server} does not answer ({probe.error}). "
                "Is it running and reachable from this computer? (hugo server --bind 0.0.0.0)",
                style=BAD_STYLE,
            )
        )
        return -1
    if not probe.ok:
        rep.add(
            "page",
            "bad",
            f"the server answers HTTP {probe.status} for the page itself"
            + (
                " (is it a draft, dated in the future, not synced yet, or has Hugo not rebuilt?)"
                if probe.status == 404
                else ""
            ),
        )
        rep.skipped.update({k: "the page does not load" for k in CHECKS if k != "page"})
        return print_report(page, ctx.url, rep, show_ok)
    rep.notes["page"] = f"(HTTP {probe.status}, {time.time() - started:.1f} s)"

    scan = PageScan()
    scan.feed(probe.html)
    scan.close()
    scan.finish()

    engine = detect_engine(scan)
    check_engine(rep, scan, src, engine)
    check_resources(rep, ctx, scan, checker)
    compared = check_formulas_intact(rep, probe.html, src)
    rep.notes["intact"] = (
        f"({compared} compared with your Markdown)" if compared else ""
    )
    check_leftovers(rep, scan, src)
    check_structure(rep, scan, src)

    if browser is False:
        reason = "browser=False"
    else:
        reason = ""
        try:
            result = run_browser(ctx.url, screenshot_dir, phone)
            check_browser_results(rep, result, src, engine, compared, ctx.netloc)
            if result.screenshot:
                console.print(Text(f"screenshot: {result.screenshot}", style=DIM_STYLE))
        except ImportError:
            reason = "Playwright is not installed: pip install playwright && playwright install chromium"
        except RuntimeError as exc:
            reason = str(exc)
        except Exception as exc:  # a browser problem must never hide the rest
            reason = f"the browser failed ({type(exc).__name__}: {str(exc).splitlines()[0][:120]})"
    if reason:
        rep.skipped.update({k: reason for k in BROWSER_CHECKS})
        if browser is True:
            console.print(Text("browser checks not run: " + reason, style=WARN_STYLE))
    return print_report(page, ctx.url, rep, show_ok)


if __name__ == "__main__":
    import sys

    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if len(args) != 1:
        sys.exit("usage: python3 content_render.py page.md [--no-browser]")
    check_render(args[0], browser=("--no-browser" not in sys.argv))
