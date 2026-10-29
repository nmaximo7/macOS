"""
content_creation.py - run every content check on ONE Hugo page and summarise the result.

Usage
-----
    python3 content_creation.py PAGE.md                  # all six checks
    python3 content_creation.py content/calculus/page.md # relative to HUGO_ROOT is fine too
    python3 content_creation.py PAGE.md --only links images
    python3 content_creation.py PAGE.md --skip render quotes
    python3 content_creation.py PAGE.md --hide-ok         # print only the problems

PAGE can be a full path, a path relative to the current folder, or a path relative to
the Hugo site (HUGO_ROOT in .env), with or without the leading "content/":
    content/calculus/page.md      or      calculus/page.md

The checks, in this order (the names are the ones used by --only / --skip):

    frontmatter   proposed front matter (title, keywords, categories, description...)
    latex         lines that need LaTeX fixes
    links         do all the links work?                     (counts broken links)
    images        are all the images really visible?         (counts broken images)
    quotes        fresh, on-topic quotes to add to the page
    render        does the page Hugo serves render well?     (counts problems)

Every check prints its own report. At the end a summary says what happened, and the
exit code tells scripts / git hooks whether something needs attention:

    0   nothing needs attention
    1   at least one check found problems, could not run, or crashed
    2   wrong usage (no page, file not found, unknown check name)

"frontmatter", "latex" and "quotes" only make PROPOSALS to review by hand: they never
change the exit code (unless they crash). One check crashing never stops the others.

From Python:

    from content_creation import main
    exit_code = main("/path/to/content/calculus/stoketheorem.md", only=["links"])
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path

from rich.console import Console
from rich.text import Text

console = Console()

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


# (key, title, function) in the order they run
STEPS = [
    ("frontmatter", "Front matter", _step_frontmatter),
    ("latex", "LaTeX", _step_latex),
    ("links", "Links", _step_links),
    ("images", "Images", _step_images),
    ("quotes", "Quotes", _step_quotes),
    ("render", "Rendered page", _step_render),
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


def main(page, only=None, skip=None, show_ok: bool = True) -> int:
    """Run the checks, print the summary and return the exit code (0, 1 or 2)."""
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
        "quotes, rendering) on one Hugo Markdown page.",
    )
    parser.add_argument("page", help="path of the .md file inside HUGO_ROOT/content")
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
    args = parser.parse_args(argv)
    return main(args.page, only=args.only, skip=args.skip, show_ok=not args.hide_ok)


if __name__ == "__main__":
    sys.exit(cli())
