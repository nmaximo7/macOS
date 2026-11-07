"""
content_creation.py - run every content check on ONE Hugo page and summarise the result.

Usage
-----
    python3 content_creation.py                          # the page you edited LAST (see below)
    python3 content_creation.py PAGE.md                  # all seven steps
    python3 content_creation.py content/calculus/page.md # relative to HUGO_ROOT is fine too
    python3 content_creation.py PAGE.md --only links images
    python3 content_creation.py PAGE.md --skip render quotes expand
    python3 content_creation.py PAGE.md --hide-ok         # print only the problems
    python3 content_creation.py PAGE.md --only expand --provider ollama --copy

WITHOUT A PAGE (since v0.18) the script looks through HUGO_ROOT/content for every Markdown
file (.md and .markdown), picks the one with the most recent modification time, tells you
which one it chose and how long ago it was saved, and runs everything on it. Hidden
folders/files and the section pages named _index.md are ignored (add --include-index to
include the latter). It needs HUGO_ROOT in .env.

PAGE can be a full path, a path relative to the current folder, or a path relative to
the Hugo site (HUGO_ROOT in .env), with or without the leading "content/":
    content/calculus/page.md      or      calculus/page.md

The steps, in this order (the names are the ones used by --only / --skip):

    frontmatter   proposed front matter (title, keywords, categories, description...)
    latex         lines that need LaTeX fixes
    links         do all the links work?                     (counts broken links)
    images        are all the images really visible?         (counts broken images)
    quotes        fresh, on-topic quotes to add to the page
    render        does the page Hugo serves render well?     (counts problems)
    expand        a fully rewritten, expanded version of the article, ready to paste
                  (content_expand.py: OpenRouter by default, or your local Ollama)

"expand" sends the article (without its front matter) to a model, saves the result in
EXPAND_OUTPUT_DIR (default ~/hugo-expanded, never inside content/) and prints it. It is the
only step that talks to a hosted service, so it can take a minute or two: leave it out with
--skip expand when you only want the checks.

Every check prints its own report. At the end a summary says what happened, and the
exit code tells scripts / git hooks whether something needs attention:

    0   nothing needs attention
    1   at least one check found problems, could not run, or crashed
    2   wrong usage (no page found, file not found, unknown check name)

"frontmatter", "latex" and "quotes" only make PROPOSALS to review by hand: they never
change the exit code (unless they crash). "expand" is a proposal too, except that it counts
as PROBLEMS when the rewrite has issues (placeholders, lost links, shorter than the
original...) and as "could not run" when there is no API key or no network.
One check crashing never stops the others.

From Python:

    from content_creation import main
    exit_code = main("/path/to/content/calculus/stoketheorem.md", only=["links"])
    exit_code = main()        # the most recently modified page
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from dataclasses import dataclass
from pathlib import Path

from rich.console import Console
from rich.text import Text

console = Console()

# Same names as myconfig.EXPAND_PROVIDERS. They are repeated here on purpose: importing
# myconfig needs the `ollama` and `dotenv` packages, and this script must start (and run
# the other checks) even when one of them is missing. A test keeps both lists equal.
EXPAND_PROVIDERS = ("openrouter", "ollama")

# --------------------------------------------------------------------------- #
# Results                                                                     #
# --------------------------------------------------------------------------- #

OK = "ok"  # the check ran and found nothing wrong
PROPOSAL = "proposal"  # the check printed suggestions for you to review
PROBLEMS = "problems"  # the check found something broken
UNCHECKED = "unchecked"  # the check could not run (server down, bad config...)
ERROR = "error"  # the check crashed with an exception

# Marker and colour used in the summary for each status
_LOOK = {
    OK: ("✓", "green"),
    PROPOSAL: ("•", "cyan"),
    PROBLEMS: ("✗", "red"),
    UNCHECKED: ("!", "yellow"),
    ERROR: ("✗", "red"),
}


@dataclass
class StepResult:
    """What happened in one check."""

    key: str  # "links", "images"...
    title: str  # human-readable name
    status: str  # one of OK, PROPOSAL, PROBLEMS, UNCHECKED, ERROR
    detail: str = ""

    @property
    def needs_attention(self) -> bool:
        """True when this check makes the whole run "not clean" (exit code 1)."""
        return self.status in (PROBLEMS, UNCHECKED, ERROR)


# --------------------------------------------------------------------------- #
# The steps. Each one imports its module only when it runs, so a missing      #
# package or a broken module affects that check alone, not the whole script.  #
# Every step returns (status, detail).                                        #
# --------------------------------------------------------------------------- #


def _counted(count: int, noun: str) -> tuple:
    """Turn the number returned by check_links / check_images / check_render into a status.

    count > 0  -> that many problems;  0 -> fine;  -1 -> the check could not run.
    """
    if count < 0:
        return UNCHECKED, "could not be checked (see the message above)"
    if count == 0:
        return OK, f"no {noun} problems"
    return PROBLEMS, f"{count} {noun} problem(s)"


def _step_frontmatter(page: Path, show_ok: bool) -> tuple:
    from content_frontmatter import check_hugo_frontmatter

    check_hugo_frontmatter(page)  # prints the proposed front matter
    return PROPOSAL, "proposal printed: values in red are new or changed"


def _step_latex(page: Path, show_ok: bool) -> tuple:
    from content_latex import check_latex

    check_latex(page)  # prints the lines that need a LaTeX fix
    return PROPOSAL, "lines to fix (if any) are printed above"


def _step_links(page: Path, show_ok: bool) -> tuple:
    from content_links import check_links

    return _counted(check_links(page, show_ok=show_ok), "link")


def _step_images(page: Path, show_ok: bool) -> tuple:
    from content_images import check_images

    return _counted(check_images(page, show_ok=show_ok), "image")


def _step_quotes(page: Path, show_ok: bool) -> tuple:
    from content_quotes import provide_quotes

    quotes = provide_quotes(page)  # prints the quotes and returns them
    return PROPOSAL, f"{len(quotes)} quote(s) proposed"


def _step_render(page: Path, show_ok: bool) -> tuple:
    from content_render import check_render

    return _counted(check_render(page, show_ok=show_ok), "render")


# Options of the "expand" step. main() fills them in from the command line; they live here
# because every step has the same two-argument signature (page, show_ok).
_EXPAND_DEFAULTS = {"provider": None, "model": None, "temperature": None, "copy": False, "save": True}
_expand_options = dict(_EXPAND_DEFAULTS)


def _step_expand(page: Path, show_ok: bool) -> tuple:
    from content_expand import ExpandError, expand_article

    try:
        result = expand_article(page, **_expand_options)
    except ExpandError as exc:
        console.print(Text(f"expansion failed: {exc}", style="red"))
        return UNCHECKED, str(exc).splitlines()[0]
    where = f", saved to {result.saved_to}" if result.saved_to else ""
    if result.serious:
        return PROBLEMS, f"{len(result.warnings)} issue(s) in the rewrite, read them before pasting{where}"
    return PROPOSAL, f"{result.words_before} -> {result.words_after} words{where}"


# (key, title, function) in the order they run
STEPS = [
    ("frontmatter", "Front matter", _step_frontmatter),
    ("latex", "LaTeX", _step_latex),
    ("links", "Links", _step_links),
    ("images", "Images", _step_images),
    ("quotes", "Quotes", _step_quotes),
    ("render", "Rendered page", _step_render),
    ("expand", "Expanded text", _step_expand),
]
STEP_KEYS = [key for key, _title, _func in STEPS]


# --------------------------------------------------------------------------- #
# Running and summarising                                                     #
# --------------------------------------------------------------------------- #


def run_checks(page, only=None, skip=None, show_ok: bool = True) -> list:
    """Run the selected checks on `page` and return a list of StepResult.

    page:    path of the .md file inside HUGO_ROOT/content (Path or str).
    only:    list of check names to run (None = all of them).
    skip:    list of check names to leave out.
    show_ok: False = the link / image / render reports show only the problems.

    A check that raises an exception is recorded as ERROR and the next one still runs.
    """
    page = Path(page).expanduser()
    wanted = [
        step
        for step in STEPS
        if (not only or step[0] in only) and not (skip and step[0] in skip)
    ]
    results = []
    for number, (key, title, func) in enumerate(wanted, 1):
        console.rule(f"{number}/{len(wanted)}  {title}")
        try:
            status, detail = func(page, show_ok)
        except Exception as exc:  # one failing check must not stop the others
            status, detail = ERROR, f"{type(exc).__name__}: {exc}"
            console.print(Text(f"{key} failed: {detail}", style="red"))
        results.append(StepResult(key, title, status, detail))
    return results


def print_summary(results: list) -> int:
    """Print one line per check and a final verdict. Returns the exit code (0 or 1)."""
    console.rule("Summary")
    for result in results:
        marker, colour = _LOOK[result.status]
        row = Text()
        row.append(f" {marker} ", style=colour)
        row.append(f"{result.title:<14}", style="bold")
        row.append(result.detail)
        console.print(row)

    attention = [r for r in results if r.needs_attention]
    proposals = [r for r in results if r.status == PROPOSAL]
    if attention:
        verdict = f"{len(attention)} of {len(results)} check(s) need attention: " + ", ".join(
            r.key for r in attention
        )
        console.print(Text(verdict, style="bold red"))
        return 1
    verdict = "All automatic checks passed!"
    if proposals:
        verdict += f" ({len(proposals)} proposal(s) to review by hand)"
    console.print(Text(verdict, style="bold green"))
    return 0


def find_page(raw) -> tuple:
    """Locate the Markdown page named by the user. Returns (path or None, places tried).

    Tries, in this order:
      1. the path as written (absolute, or relative to the current folder);
      2. HUGO_ROOT / path          e.g.  content/calculus/page.md
      3. HUGO_ROOT / content / path  e.g.  calculus/page.md
    HUGO_ROOT comes from .env (through myconfig); if it is not set, only (1) is tried.
    """
    given = Path(raw).expanduser()
    tried = [given]
    if given.is_file():
        return given.resolve(), tried
    if not given.is_absolute():
        try:
            from myconfig import get_settings

            root = get_settings().hugo_root
        except Exception:  # missing module or invalid .env: just skip this convenience
            root = None
        if root:
            for candidate in (root / given, root / "content" / given):
                tried.append(candidate)
                if candidate.is_file():
                    return candidate.resolve(), tried
    return None, tried


_MARKDOWN_SUFFIXES = (".md", ".markdown")


def find_latest_page(content_root, include_index: bool = False):
    """The most recently modified Markdown file under `content_root`: (path, mtime) or (None, 0).

    Ignored: hidden folders and files (.git, .DS_Store, ".#x.md"), editor leftovers ending in
    "~", and the section pages named _index.md (unless include_index). The newest
    modification time wins; if two files have exactly the same one, the path that sorts
    last wins, so the answer is always the same.
    """
    best, best_key = None, (-1, "")
    for folder, dirs, files in os.walk(content_root):
        dirs[:] = [d for d in dirs if not d.startswith(".")]  # do not enter .git etc.
        for name in files:
            if name.startswith(".") or name.endswith("~"):
                continue
            if not name.lower().endswith(_MARKDOWN_SUFFIXES):
                continue
            if name.lower() == "_index.md" and not include_index:
                continue
            path = Path(folder) / name
            try:
                mtime = path.stat().st_mtime_ns
            except OSError:  # vanished or unreadable while we looked
                continue
            key = (mtime, str(path))
            if key > best_key:
                best, best_key = path, key
    if best is None:
        return None, 0
    return best.resolve(), best_key[0] / 1e9


def _ago(seconds: float) -> str:
    """90 -> '1 minute ago';  7300 -> '2 hours ago'."""
    seconds = max(0, int(seconds))
    for unit, size in (("day", 86400), ("hour", 3600), ("minute", 60)):
        if seconds >= size:
            n = seconds // size
            return f"{n} {unit}{'s' if n != 1 else ''} ago"
    return "a few seconds ago"


def _choose_latest(include_index: bool):
    """Pick the page to work on when none was given. Returns the path, or None (and says why)."""
    try:
        from myconfig import get_settings

        root = get_settings().hugo_root
    except Exception as exc:  # invalid .env, missing module...
        console.print(Text(f"cannot read the settings: {exc}", style="red"))
        return None
    if not root:
        console.print(Text("no page given and HUGO_ROOT is not set in .env.", style="red"))
        console.print(Text("Give a page (python3 content_creation.py content/x/page.md) or set HUGO_ROOT.", style="dim"))
        return None
    content = Path(root).expanduser() / "content"
    if not content.is_dir():
        console.print(Text(f"no page given and {content} does not exist.", style="red"))
        return None
    path, mtime = find_latest_page(content, include_index=include_index)
    if path is None:
        console.print(Text(f"no Markdown page found in {content}", style="red"))
        return None
    when = time.strftime("%Y-%m-%d %H:%M", time.localtime(mtime))
    console.print(Text("No page given: using the most recently modified one", style="bold"))
    console.print(Text(f"  {path}", style="bold"))
    console.print(Text(f"  last saved {when} ({_ago(time.time() - mtime)})", style="dim"))
    return path


def main(
    page=None,
    only=None,
    skip=None,
    show_ok: bool = True,
    include_index: bool = False,
    expand_options=None,
) -> int:
    """Run the checks, print the summary and return the exit code (0, 1 or 2).

    page:           the page; None = the most recently modified Markdown file of the site.
    expand_options: dict for the "expand" step: provider, model, temperature, copy, save.
    """
    _expand_options.update(_EXPAND_DEFAULTS)  # every call starts from the defaults: no leftovers
    _expand_options.update(expand_options or {})
    if page is None:
        latest = _choose_latest(include_index)
        if latest is None:
            return 2
        page = latest
    path, tried = find_page(page)
    if path is None:
        console.print(Text(f"page not found: {page}", style="red"))
        console.print(Text("looked in:", style="dim"))
        for place in tried:
            console.print(Text(f"  {place}", style="dim"))
        if len(tried) == 1:
            console.print(
                Text(
                    "tip: set HUGO_ROOT in .env to use paths relative to your site.",
                    style="dim",
                )
            )
        return 2
    console.print(Text(str(path), style="bold"))
    return print_summary(run_checks(path, only=only, skip=skip, show_ok=show_ok))


def cli(argv=None) -> int:
    """Command-line entry point: parse the arguments and call main()."""
    parser = argparse.ArgumentParser(
        prog="content_creation.py",
        description="Run every content check (front matter, LaTeX, links, images, "
        "quotes, rendering) and an AI rewrite on one Hugo Markdown page. "
        "Without a page it uses the most recently modified one.",
    )
    parser.add_argument(
        "page",
        nargs="?",
        default=None,
        help="path of the .md file inside HUGO_ROOT/content (default: the most recently modified page)",
    )
    parser.add_argument(
        "--only",
        nargs="+",
        metavar="CHECK",
        choices=STEP_KEYS,
        help="run only these checks: " + " ".join(STEP_KEYS),
    )
    parser.add_argument(
        "--skip",
        nargs="+",
        metavar="CHECK",
        choices=STEP_KEYS,
        help="leave these checks out",
    )
    parser.add_argument(
        "--hide-ok",
        action="store_true",
        help="in the links / images / render reports, print only the problems",
    )
    parser.add_argument(
        "--include-index",
        action="store_true",
        help="when no page is given, also consider section pages named _index.md",
    )
    parser.add_argument(
        "--provider",
        choices=EXPAND_PROVIDERS,
        help="who rewrites the article: openrouter (hosted) or ollama (local); default EXPAND_PROVIDER",
    )
    parser.add_argument("--model", help="model for the rewrite (default OPENROUTER_MODEL / MYMODEL_QUERY)")
    parser.add_argument("--temperature", type=float, help="creativity of the rewrite, 0 ... 2")
    parser.add_argument("--copy", action="store_true", help="put the rewritten article on the clipboard")
    parser.add_argument(
        "--no-save", action="store_true", help="do not write the rewrite to EXPAND_OUTPUT_DIR"
    )
    args = parser.parse_args(argv)
    return main(
        args.page,
        only=args.only,
        skip=args.skip,
        show_ok=not args.hide_ok,
        include_index=args.include_index,
        expand_options={
            "provider": args.provider,
            "model": args.model,
            "temperature": args.temperature,
            "copy": args.copy,
            "save": not args.no_save,
        },
    )


if __name__ == "__main__":
    sys.exit(cli())
