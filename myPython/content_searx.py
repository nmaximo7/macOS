"""
content_searx.py - the "searx" step: search the web for the topic of ONE Hugo page.

    from content_searx import research_page
    research = research_page("content/calculus/maxwellfaraday.md")
    print(research.query)         # what was searched
    print(research.text)          # compact text for an AI prompt (titles, snippets, URLs)

    python3 content_searx.py content/calculus/maxwellfaraday.md
    python3 content_searx.py page.md --query "faraday law of induction explained" --limit 10

How it fits in the toolkit
--------------------------
content_creation.py runs this step just BEFORE the "expand" step. The results are shown to you
and handed to the AI rewrite as reference material (prompt `expand_article_research`): the model
can check facts, add current information and end with a "Further reading" list. Without this
step (or when it fails) the rewrite works exactly as before.

Deep research (default)
-----------------------
More information is better, so the step does not stop at ten links. For one page it
  1. builds several query variants (mysearx.build_queries: the title, "... tutorial",
     "... examples", the description's words, the title plus tags...) - SEARX_QUERIES, default 4;
  2. reads SEARX_PAGES result pages of each (default 2) and merges everything into ONE list,
     the links found by several queries first;
  3. downloads the text of the best SEARX_FETCH_PAGES pages (default 8; SEARX_FETCH=0 turns it off);
  4. hands up to SEARX_CONTEXT_CHARS characters (default 30000) of titles, snippets and page
     excerpts to the AI rewrite as reference material.
`deep=False` (CLI: --quick) does the old single search instead.

What is searched
----------------
The TITLE of the page (front matter `title:`). A title is the best single source of keywords
because you already wrote it to say what the page is about. Details (mysearx.build_query):
  * a very short title (under 3 words, e.g. "Fourier") is ambiguous, so up to two of the page's
    keywords/tags are added ("Fourier signal-processing");
  * no title: the first `# Heading` of the article, then the file name;
  * --query "..." (or the `search_query` option) overrides everything.
Only those short queries leave your Mac through your own SearXNG, which forwards them to the search
engines. The article itself is never sent to the search. Downloading the pages (step 3) is done
by your Mac directly, so those sites see your IP address; SEARX_FETCH=0 avoids it.

Docker is started for the search and stopped again right after it (SEARX_AUTOSTART /
SEARX_AUTOSTOP in .env, see mysearx.py); something that was already running is never stopped.

The module that talks to SearXNG is mysearx.py (standard library only, usable on its own).
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

from rich.console import Console
from rich.table import Table
from rich.text import Text

import mysearx
from content_urls import front_len, read_lines

console = Console(highlight=False)

# --------------------------------------------------------------------------- #
# 1. Reading what we need from the page                                       #
# --------------------------------------------------------------------------- #

_KEY = re.compile(r"^([A-Za-z_][A-Za-z0-9_-]*)\s*:(.*)$")


def _unquote(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        return value[1:-1]
    return re.split(r"\s+#", value)[0].strip()


def _front_values(front: list, key: str) -> list:
    """The values of `key` in front matter lines: 'k: a' / 'k: [a, b]' / 'k: a, b' / '- a' lines."""
    for index, line in enumerate(front):
        m = _KEY.match(line)
        if not m or m.group(1).lower() != key:
            continue
        first = m.group(2).strip()
        if first.startswith("[") and first.endswith("]"):
            return [_unquote(p) for p in first[1:-1].split(",") if p.strip()]
        if first and first not in ("|", ">", "|-", ">-"):
            value = _unquote(first)
            return [p.strip() for p in value.split(",")] if key in ("keywords", "tags") else [value]
        items = []
        for follow in front[index + 1 :]:
            if _KEY.match(follow):
                break
            stripped = follow.strip()
            if stripped.startswith("-"):
                items.append(_unquote(stripped[1:]))
        return [i for i in items if i]
    return []


def page_fields(page) -> tuple:
    """(title, tags, description) of a page, for building the query.

    title:       front matter `title`, else the first "# Heading" of the article, else the
                 file name (index.md -> its folder name).
    tags:        keywords, then tags, then categories (the most specific first).
    description: front matter `description` ("" if none).
    """
    page = Path(page)
    lines = read_lines(page)
    n = front_len(lines)
    front = lines[1 : n - 1] if n else []
    body = lines[n:]

    title = next(iter(_front_values(front, "title")), "")
    if not title:
        heading = next((re.match(r"^#{1,6}\s+(.+?)\s*#*\s*$", ln) for ln in body if ln.startswith("#")), None)
        title = heading.group(1) if heading else ""
    if not title:
        stem = page.stem
        title = page.resolve().parent.name if stem in ("index", "_index") else stem
        title = title.replace("-", " ").replace("_", " ")
    tags = _front_values(front, "keywords") + _front_values(front, "tags") + _front_values(front, "categories")
    description = next(iter(_front_values(front, "description")), "")
    return title, [t for t in tags if t], description


# --------------------------------------------------------------------------- #
# 2. The research                                                             #
# --------------------------------------------------------------------------- #


@dataclass
class Research:
    """What the step found: keep it, show it, or hand it to expand_article()."""

    query: str
    response: "mysearx.SearxResponse"
    text: str = ""  # mysearx.as_context(): what the AI model receives
    urls: tuple = ()  # every URL in `text`
    notes: list = field(default_factory=list)

    @property
    def count(self) -> int:
        return len(self.response.results)


def _print_results(research: Research) -> None:
    table = Table(show_header=True, header_style="bold", box=None, pad_edge=False, expand=True)
    table.add_column("#", justify="right", no_wrap=True)
    table.add_column("Result", ratio=3)
    table.add_column("Site", ratio=1, no_wrap=True, overflow="ellipsis")
    for number, r in enumerate(research.response.results, 1):
        cell = Text(r.title, style="bold")
        if r.snippet:
            cell.append("\n" + (r.snippet if len(r.snippet) <= 160 else r.snippet[:159] + "…"), style="dim")
        cell.append("\n" + r.url, style="blue")
        table.add_row(str(number), cell, r.domain)
    resp = research.response
    if len(resp.queries) > 1:
        console.print(Text(f"Web research: {len(resp.queries)} searches", style="bold"))
        for q in resp.queries:
            console.print(Text(f"  - {q}", style="dim"))
    else:
        console.print(Text(f"Web search: {research.query!r}", style="bold"))
    console.print(table)
    if resp.pages:
        size = sum(len(t) for t in resp.pages.values())
        console.print(Text(f"  {len(resp.pages)} page(s) downloaded, {size:,} characters of text", style="green"))
    for answer in research.response.answers:
        console.print(Text(f"  answer: {answer}", style="green"))
    if research.response.suggestions:
        console.print(Text("  related: " + "; ".join(research.response.suggestions), style="dim"))
    for note in research.notes:
        console.print(Text(f"  i {note}", style="dim"))


def research_page(
    page,
    query: "str | None" = None,
    limit: "int | None" = None,
    show: bool = True,
    autostart: "bool | None" = None,
    autostop: "bool | None" = None,
    deep: bool = True,
) -> Research:
    """Search the web for the topic of `page` and return a Research.

    query:     what to search; None = built from the page title (see the module docstring).
    limit:     results per search page; None = SEARX_RESULTS.
    show:      print the results table.
    autostart: start Docker/SearXNG when it is down; None = SEARX_AUTOSTART.
    autostop:  stop it afterwards when WE started it; None = SEARX_AUTOSTOP.
    deep:      True = several queries and pages, merged, plus the text of the best pages;
               False = one plain search.

    Raises mysearx.SearxError (it is not running, it refused, no query...) and ValueError.
    """
    page = Path(page)
    explicit = bool(query and query.strip())
    if explicit:
        queries = [query.strip()]
    else:
        title, tags, description = page_fields(page)
        cfg0 = mysearx.load_config()
        queries = mysearx.build_queries(title, tags, description, max_queries=cfg0.queries if deep else 1)
    if not queries:
        raise mysearx.SearxError(f"cannot build a search query for {page.name}: it has no title")

    cfg = mysearx.load_config()
    notes = []
    if not mysearx.is_up(cfg):
        console.print(Text("SearXNG is not running: starting Docker and SearXNG (the first time can take minutes)...", style="dim"))
    with mysearx.running(cfg, autostart=autostart, autostop=autostop) as started:
        def run_search():
            if deep:
                return mysearx.gather(
                    queries, limit=limit, config=cfg,
                    progress=lambda text: console.print(Text(f"  {text}", style="dim")),
                )
            return mysearx.search(queries[0], limit=limit, config=cfg)

        try:
            response = run_search()
        except mysearx.SearxNotRunning as exc:
            # It looked up but then stopped answering (hung Docker...). Restart everything once.
            enabled = cfg.autostart if autostart is None else autostart
            if not (enabled and cfg.restart_on_fail and cfg.is_local):
                raise
            console.print(Text(f"SearXNG stopped answering ({str(exc).splitlines()[0]}): restarting Docker no matter what...", style="yellow"))
            mysearx.reset(cfg)
            started = True
            notes.append("Docker was restarted because SearXNG did not answer")
            response = run_search()
        will_stop = (cfg.autostop if autostop is None else autostop) and (started or cfg.stop_always)
        if started:
            notes.append("SearXNG was started for this search" + (" and is stopped again now" if will_stop else ""))
        elif will_stop:
            notes.append("SearXNG was already running; it is stopped now (SEARX_AUTOSTOP=always)")
    for engine in response.unresponsive:
        notes.append(f"engine not responding: {engine}")
    for problem in response.errors[:6]:
        notes.append(problem)
    if len(response.errors) > 6:
        notes.append(f"... and {len(response.errors) - 6} more problems (the rest of the research is fine)")
    text = mysearx.as_context(response, cfg.context_chars if deep else 6000)
    research = Research(
        query=response.query if not deep else " | ".join(queries[:1]),
        response=response,
        text=text,
        urls=tuple(r.url for r in response.results),
        notes=notes,
    )
    if show:
        _print_results(research)
    return research


# --------------------------------------------------------------------------- #
# Command line                                                                #
# --------------------------------------------------------------------------- #


def cli(argv=None) -> int:
    """python3 content_searx.py PAGE.md [--query Q] [--limit N] [--keep]."""
    parser = argparse.ArgumentParser(
        prog="content_searx.py", description="Search the web (your own SearXNG) for the topic of one Hugo page."
    )
    parser.add_argument("page", help="the .md file (path, or relative to HUGO_ROOT/content)")
    parser.add_argument("--query", help="search for this instead of the page title")
    parser.add_argument("--limit", type=int, help="how many results (default SEARX_RESULTS)")
    parser.add_argument("--keep", action="store_true", help="do not stop SearXNG afterwards")
    parser.add_argument("--quick", action="store_true", help="one plain search (no query variants, no page downloads)")
    args = parser.parse_args(argv)

    from content_creation import find_page

    path, _tried = find_page(args.page)
    if path is None:
        print(f"page not found: {args.page}", file=sys.stderr)
        return 2
    try:
        research = research_page(path, query=args.query, limit=args.limit, autostop=False if args.keep else None, deep=not args.quick)
    except (mysearx.SearxError, ValueError) as exc:
        console.print(Text(f"error: {exc}", style="red"))
        return 1
    return 0 if research.count else 1


if __name__ == "__main__":
    sys.exit(cli())
