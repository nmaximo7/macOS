"""
content_expand.py - rewrite and expand ONE Hugo article with an AI model, ready to paste.

    from content_expand import expand_article
    result = expand_article("content/calculus/maxwellfaraday.md")
    print(result.text)          # the new article (Markdown, no front matter)
    print(result.saved_to)      # where a copy was written

    python3 content_expand.py content/calculus/maxwellfaraday.md
    python3 content_expand.py page.md --provider ollama
    python3 content_expand.py page.md --model some/model --copy

What it does, step by step
--------------------------
 1. Reads the page and DROPS the front matter: only the article body is sent.
 2. Sends the body to a model with the system prompt `expand_article` of mymessages.py
    ("provide a fully rewritten, highly expanded and polished version ... that I can copy
    and paste directly into my website ... no placeholders ... every step in full").
       provider "openrouter"  hosted model, through openrouter.py (API key in the Keychain)
       provider "ollama"      your local model (MYMODEL_QUERY), through myollama.py
    The default provider is EXPAND_PROVIDER of .env ("openrouter").
 3. CLEANS the answer: removes a <think> block, a wrapping ```markdown fence, a front
    matter block the model should not have written, and a chatty first line ("Here is...").
 4. CHECKS the result against the original (the "quality gate", see compare_texts):
       - placeholders such as "insert proof here", TODO, "...", "to be completed";
       - an answer SHORTER than the original (it was not expanded);
       - links, images and Hugo shortcodes that disappeared;
       - links or images that are NEW (models invent URLs: they must be checked);
       - math written as \\( \\) or \\[ \\] instead of $ $ and $$ $$.
 5. SAVES a copy (`<page>-expanded-<date>.md`) in EXPAND_OUTPUT_DIR (default ~/hugo-expanded),
    PRINTS the article so you can copy it from the terminal, and with copy=True / --copy
    puts it on the macOS clipboard (pbcopy).

What it NEVER does
------------------
It never writes inside your Hugo `content/` folder (Hugo would publish the file as a new
page: an output folder inside content/ is refused) and it never changes the page itself.
You paste the result yourself, after reading it.

PRIVACY: with the "openrouter" provider the article is sent to OpenRouter and to whichever
company runs the model; free models may keep prompts. That is fine for text you are about
to publish, not for private drafts: use --provider ollama for those.
"""

from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn, TimeElapsedColumn
from rich.text import Text

from content_urls import front_len, read_lines
from myconfig import DEFAULT_EXPAND_RETRIES, DEFAULT_EXPAND_RETRY_WAIT, EXPAND_PROVIDERS, get_settings

console = Console(highlight=False)

# --------------------------------------------------------------------------- #
# Constants                                                                   #
# --------------------------------------------------------------------------- #

PROMPT_NAME = "expand_article"  # the system prompt in mymessages.py
PROMPT_RESEARCH = "expand_article_research"  # same, for an article + web search results
MAX_RESEARCH_CHARS = 60_000  # hard cap; the real size is SEARX_CONTEXT_CHARS (default 30000)
MAX_BODY_CHARS = 100_000  # same limit as myollama.py / openrouter.py
MIN_BODY_CHARS = 20  # a body shorter than this is not an article
MIN_GROWTH = 1.15  # "expanded" means at least 15% more words than the original
DEFAULT_OUTPUT_DIR = Path.home() / "hugo-expanded"
OLLAMA_MAX_TOKENS = 20_000  # answer length allowed for the local model

NEW_STYLE = "bold green"
WARN_STYLE = "yellow"
DIM_STYLE = "dim"


class ExpandError(RuntimeError):
    """Anything that stops an expansion (empty page, no API key, network, bad folder...).

    The message is written for a human and never contains the API key.
    """


@dataclass
class Expansion:
    """Everything expand_article() learned, so callers can use it without parsing text."""

    text: str  # the cleaned article (Markdown, no front matter)
    provider: str  # "openrouter" or "ollama"
    model: str  # the model that answered
    words_before: int
    words_after: int
    seconds: float
    saved_to: "Path | None" = None
    copied: bool = False
    warnings: list = field(default_factory=list)  # things to review before pasting
    cautions: list = field(default_factory=list)  # worth a look, but not a problem (little growth...)
    attempts: int = 1  # how many times the model was asked (more than 1 after an empty answer)
    notes: list = field(default_factory=list)  # harmless facts ("removed a code fence")

    @property
    def serious(self) -> bool:
        """True when the quality gate found something you must read before pasting."""
        return bool(self.warnings)


# --------------------------------------------------------------------------- #
# 1. Reading the article                                                      #
# --------------------------------------------------------------------------- #


def article_body(page) -> str:
    """The Markdown of `page` WITHOUT its front matter (leading/trailing blank lines removed)."""
    lines = read_lines(Path(page))
    return "\n".join(lines[front_len(lines):]).strip()


def count_words(text: str) -> int:
    return len(re.findall(r"\w+", text))


# --------------------------------------------------------------------------- #
# 2. Cleaning the model's answer                                              #
# --------------------------------------------------------------------------- #

_THINK = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)
_CHATTY_FIRST_LINE = re.compile(
    r"^(here is|here's|here are|sure|certainly|of course|okay|ok,|below is|absolutely)\b.{0,160}$",
    re.IGNORECASE,
)


def _unwrap_fence(text: str):
    """If the WHOLE answer is inside one ``` fence, return the inside; else None.

    Only a fence opened with ```, ```markdown or ```md on the first line and closed on the
    last line counts, and only when the inside has an even number of ``` lines (so an
    article that really starts and ends with code blocks is never damaged).
    """
    lines = text.split("\n")
    if len(lines) < 3:
        return None
    if lines[0].strip().lower() not in ("```", "```markdown", "```md"):
        return None
    if lines[-1].strip() != "```":
        return None
    inner = lines[1:-1]
    fences = sum(1 for line in inner if line.lstrip().startswith("```"))
    if fences % 2:
        return None
    return "\n".join(inner).strip()


def clean_answer(answer: str):
    """Tidy the model's answer. Returns (text, notes), notes = what was removed.

    Removes, in this order: a <think> block, a fence around the whole answer, a front
    matter block, and a chatty first line followed by a blank line.
    """
    notes = []
    text = answer or ""
    if _THINK.search(text):
        text = _THINK.sub("", text)
        notes.append("removed a <think> block")
    text = text.strip()

    unwrapped = _unwrap_fence(text)
    if unwrapped is not None:
        text = unwrapped
        notes.append("removed a code fence around the whole answer")

    lines = text.split("\n")
    n = front_len(lines)
    if n:
        text = "\n".join(lines[n:]).strip()
        notes.append("removed a front matter block (your page keeps its own)")

    lines = text.split("\n")
    if (
        len(lines) > 2
        and not lines[1].strip()
        and _CHATTY_FIRST_LINE.match(lines[0].strip())
        and not lines[0].lstrip().startswith("#")
    ):
        text = "\n".join(lines[2:]).strip()
        notes.append(f"removed an introductory line: {lines[0].strip()[:60]!r}")
    return text, notes


# --------------------------------------------------------------------------- #
# 3. The quality gate: compare the answer with the original                   #
# --------------------------------------------------------------------------- #

_LINK_TARGET = re.compile(r"!?\[[^\]]*\]\(\s*<?([^)\s>]+)")
_BARE_URL = re.compile(r"https?://[^\s)>\]\"'<]+")
_SHORTCODE = re.compile(r"\{\{[<%].*?[>%]\}\}", re.DOTALL)
_HEADING = re.compile(r"^#{1,6}\s+(.+?)\s*#*\s*$", re.MULTILINE)
_BAD_MATH = re.compile(r"\\\(|\\\)|\\\[|\\\]")
_PLACEHOLDER = re.compile(
    r"(insert\b[^.\n]{0,40}\bhere|\bTODO\b|\bTBD\b|to be (?:completed|added|filled|written)|"
    r"\blorem ipsum\b|\[\s*(?:\.\.\.|…)\s*\]|\(\s*(?:\.\.\.|…)\s*\)|"
    r"(?:proof|derivation|details?|steps?|calculations?)\s+(?:omitted|left to the reader)|"
    r"^\s*(?:\.\.\.|…)\s*$)",
    re.IGNORECASE | re.MULTILINE,
)


def _targets(text: str) -> set:
    """Every link/image destination and bare URL in `text` (trailing punctuation trimmed)."""
    found = set(_LINK_TARGET.findall(text)) | set(_BARE_URL.findall(text))
    return {t.rstrip(".,;:") for t in found}


def _placeholders(text: str) -> list:
    return [m.group(0).strip() for m in _PLACEHOLDER.finditer(text)]


def growth_caution(before: int, after: int) -> str:
    """"" when the rewrite grew enough; otherwise a short sentence (a CAUTION, not a problem)."""
    if before and before <= after < before * MIN_GROWTH:
        return (
            f"only {100 * (after - before) // before}% longer than the original ({before} -> {after} words); "
            "free models often do this: run it again or try another model if you want more"
        )
    return ""


def compare_texts(original: str, expanded: str, known_urls=()):
    """Check an expansion against the original. Returns (warnings, notes).

    warnings are things to read BEFORE pasting; notes are only information.
    known_urls: URLs that came from the web search (the "searx" step). A NEW link that is one of
    them is not "invented" (it was found by the search), so it is only mentioned in a note.
    """
    warnings, notes = [], []

    before, after = count_words(original), count_words(expanded)
    if not expanded.strip():
        return ["the answer is empty"], notes
    if after < before:
        warnings.append(f"the rewrite is SHORTER than the original ({after} vs {before} words): it was not expanded")
    # Little growth is NOT a warning here: free models often rewrite without adding much. It is
    # reported separately by growth_caution() as a caution (yellow, does not fail the run).

    old_placeholders = len(_placeholders(original))
    new_placeholders = _placeholders(expanded)
    if len(new_placeholders) > old_placeholders:
        sample = "; ".join(repr(p) for p in new_placeholders[:3])
        warnings.append(f"{len(new_placeholders)} placeholder(s) found, e.g. {sample}")

    old_targets, new_targets = _targets(original), _targets(expanded)
    missing = sorted(old_targets - new_targets)
    invented = sorted(new_targets - old_targets)
    if missing:
        warnings.append(
            f"{len(missing)} link/image(s) of the original are missing, e.g. {missing[0]}"
        )
    known = {u.rstrip(".,;:") for u in known_urls}
    searched = [u for u in invented if u in known]
    invented = [u for u in invented if u not in known]
    if searched:
        notes.append(f"{len(searched)} link(s) added from the web search (check them before publishing)")
    if invented:
        warnings.append(
            f"{len(invented)} NEW link/image(s) that are not in the original (models invent URLs), e.g. {invented[0]}"
        )

    old_codes = sorted(m.group(0) for m in _SHORTCODE.finditer(original))
    new_codes = sorted(m.group(0) for m in _SHORTCODE.finditer(expanded))
    lost = [c for c in old_codes if c not in new_codes]
    if lost:
        warnings.append(f"{len(lost)} Hugo shortcode(s) changed or missing, e.g. {lost[0][:60]}")

    if _BAD_MATH.search(expanded) and not _BAD_MATH.search(original):
        warnings.append(r"math written with \( \) or \[ \]: your site uses $...$ and $$...$$")

    old_heads = {h.strip().lower() for h in _HEADING.findall(original)}
    new_heads = {h.strip().lower() for h in _HEADING.findall(expanded)}
    renamed = sorted(old_heads - new_heads)
    if renamed:
        notes.append(f"{len(renamed)} original heading(s) not found verbatim (renamed?), e.g. {renamed[0]!r}")
    if after >= before:
        notes.append(f"{before} -> {after} words (x{after / max(before, 1):.1f})")
    return warnings, notes


# --------------------------------------------------------------------------- #
# 4. Asking the model                                                         #
# --------------------------------------------------------------------------- #


def _sleep(seconds: float) -> None:
    """time.sleep, in a function so the tests can replace it."""
    time.sleep(seconds)


def _wait_before_retry(seconds: float, attempt: int, attempts: int, reason: str) -> None:
    """Wait with a visible countdown (so a 5-minute pause does not look like a freeze)."""
    first = reason.strip().splitlines()[0][:110] if reason.strip() else "no answer"
    console.print(Text(f"  ! {first}", style=WARN_STYLE))
    console.print(
        Text(
            f"  Waiting {seconds / 60:.0f} min before attempt {attempt + 1} of {attempts} "
            "(free models are often busy; Ctrl-C to stop).",
            style=WARN_STYLE,
        )
    )
    remaining = int(seconds)
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        TimeElapsedColumn(),
        transient=True,
        console=console,
    ) as progress:
        task = progress.add_task("", total=None)
        while remaining > 0:
            progress.update(task, description=f"next attempt in {remaining // 60}:{remaining % 60:02d}")
            step = min(5, remaining)
            _sleep(step)
            remaining -= step


def _ask_openrouter(body: str, model, temperature, prompt: str = PROMPT_NAME):
    """Ask OpenRouter; when it gives NO answer (empty, busy, timeout, 429, 5xx) wait and ask again.

    EXPAND_RETRIES extra attempts (default 2), EXPAND_RETRY_WAIT seconds apart (default 300 = 5
    minutes). A wrong key, no credits or a bad request are not retried: they would fail again.
    Returns (text, model used, attempts made).
    """
    from openrouter import OpenRouterError, call_openrouter

    settings = get_settings()
    shown = model or settings.openrouter_model
    attempts = 1 + max(0, getattr(settings, "expand_retries", DEFAULT_EXPAND_RETRIES))
    wait = getattr(settings, "expand_retry_wait", DEFAULT_EXPAND_RETRY_WAIT)
    last_reason = ""
    for attempt in range(1, attempts + 1):
        if attempt > 1:
            _wait_before_retry(wait, attempt - 1, attempts, last_reason)
        try:
            with Progress(
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}"),
                TimeElapsedColumn(),
                transient=True,
                console=console,
            ) as progress:
                label = f"Asking OpenRouter ({shown})..." if attempt == 1 else f"Asking OpenRouter ({shown}), attempt {attempt}/{attempts}..."
                progress.add_task(label, total=None)
                text, used = call_openrouter(body, prompt=prompt, model=model, temperature=temperature)
        except OpenRouterError as exc:
            if getattr(exc, "retryable", False) and attempt < attempts:
                last_reason = str(exc)
                continue
            message = str(exc)
            if attempt > 1:
                message += f"\n(asked {attempt} times; gave up)"
            raise ExpandError(message) from None
        except ValueError as exc:
            raise ExpandError(str(exc)) from None
        if text and text.strip():
            return text, used, attempt
        last_reason = "the model returned an empty answer"
        if attempt == attempts:
            raise ExpandError(f"the model returned an empty answer {attempts} times; try again later or choose another model")
    raise ExpandError("no answer from OpenRouter")  # unreachable; keeps the function total


def _ask_ollama(body: str, model, temperature, prompt: str = PROMPT_NAME):
    from myollama import call_ollama

    settings = get_settings()
    used = model or settings.model_query
    try:
        text = call_ollama(
            body,
            prompt=prompt,
            model_name=used,
            temperature=0.7 if temperature is None else temperature,
            max_tokens=OLLAMA_MAX_TOKENS,
            show=False,
        )
    except (RuntimeError, ValueError) as exc:
        raise ExpandError(str(exc)) from None
    return text, used, 1


# --------------------------------------------------------------------------- #
# 5. Saving, copying, showing                                                 #
# --------------------------------------------------------------------------- #


def output_dir() -> Path:
    """Folder where expanded articles are saved (EXPAND_OUTPUT_DIR, else ~/hugo-expanded).

    Raises ExpandError if it is inside the Hugo content folder: Hugo would publish it.
    """
    settings = get_settings()
    folder = (settings.expand_output_dir or DEFAULT_OUTPUT_DIR).expanduser().resolve()
    if settings.hugo_root:
        content = (settings.hugo_root / "content").expanduser().resolve()
        if folder == content or content in folder.parents:
            raise ExpandError(
                f"EXPAND_OUTPUT_DIR ({folder}) is inside your Hugo content folder: "
                "Hugo would publish the file as a page. Choose another folder in .env."
            )
    return folder


def _slug(page: Path) -> str:
    """'calculus/maxwellfaraday.md' -> 'maxwellfaraday';  '.../topic/index.md' -> 'topic'."""
    stem = page.stem
    if stem in ("index", "_index"):
        stem = page.resolve().parent.name or stem
    return re.sub(r"[^A-Za-z0-9._-]+", "-", stem).strip("-") or "article"


def save_expansion(text: str, page) -> Path:
    """Write the article to the output folder and return the new file's path."""
    folder = output_dir()
    folder.mkdir(parents=True, exist_ok=True)
    name = f"{_slug(Path(page))}-expanded-{datetime.now():%Y%m%d-%H%M%S}.md"
    path = folder / name
    path.write_text(text.rstrip("\n") + "\n", encoding="utf-8", newline="\n")
    return path


def copy_to_clipboard(text: str) -> bool:
    """Put `text` on the macOS clipboard (pbcopy). False if that is not possible here."""
    if not shutil.which("pbcopy"):
        return False
    try:
        subprocess.run(["pbcopy"], input=text.encode("utf-8"), check=True, timeout=15)
    except (subprocess.SubprocessError, OSError):
        return False
    return True


def _report(result: Expansion, page: Path, show_text: bool) -> None:
    """Print the article (raw, so you can copy it) and then the report."""
    if show_text:
        console.rule("Expanded article (copy from here, or use the saved file)")
        # markup=False + soft_wrap=True: print the Markdown exactly, never re-wrapped or re-styled.
        console.print(result.text, markup=False, soft_wrap=True)
        console.rule()
    head = Text()
    head.append(f"{page.name}: ", style="bold")
    head.append(f"{result.words_before} -> {result.words_after} words, ")
    head.append(f"{result.provider} / {result.model}, {result.seconds:.0f}s", style=DIM_STYLE)
    console.print(head)
    if result.saved_to:
        console.print(Text(f"  saved: {result.saved_to}", style=NEW_STYLE))
    if result.copied:
        console.print(Text("  copied to the clipboard", style=NEW_STYLE))
    for note in result.notes:
        console.print(Text(f"  i {note}", style=DIM_STYLE))
    for caution in result.cautions:
        console.print(Text(f"  ! {caution}", style=WARN_STYLE))
    for warning in result.warnings:
        console.print(Text(f"  ! {warning}", style=WARN_STYLE))
    if result.warnings:
        console.print(
            Text("  Read the warnings above BEFORE pasting this into your site.", style=WARN_STYLE)
        )


# --------------------------------------------------------------------------- #
# 6. The public function                                                      #
# --------------------------------------------------------------------------- #


def expand_article(
    page,
    provider: str | None = None,
    model: str | None = None,
    temperature: float | None = None,
    save: bool = True,
    copy: bool = False,
    show: bool = True,
    research: str = "",
    research_urls=(),
) -> Expansion:
    """Rewrite and expand the article of `page`; return an Expansion.

    page:        the Markdown file (its front matter is ignored, never sent, never changed).
    provider:    "openrouter" or "ollama"; None = EXPAND_PROVIDER of .env.
    model:       model name; None = OPENROUTER_MODEL (openrouter) or MYMODEL_QUERY (ollama).
    temperature: 0..2; None = the provider's default (0.7).
    save:        write a copy in EXPAND_OUTPUT_DIR (never inside content/).
    copy:        put the article on the macOS clipboard.
    show:        print the article and the report.
    research:    optional web search results (text from mysearx.as_context). When given, the
                 model gets them next to the article and uses the prompt
                 `expand_article_research`; they are cut to MAX_RESEARCH_CHARS.
    research_urls: the URLs inside `research`; links to them are not reported as invented.

    Raises ExpandError for every expected problem (empty page, no API key, network...).
    """
    page = Path(page).expanduser()
    try:
        body = article_body(page)
    except OSError as exc:
        raise ExpandError(f"cannot read {page}: {exc}") from None
    if len(body) < MIN_BODY_CHARS:
        raise ExpandError(f"{page.name} has no article to expand (only {len(body)} characters after the front matter)")
    if len(body) > MAX_BODY_CHARS:
        raise ExpandError(
            f"{page.name} is too long to send in one piece ({len(body)} characters, maximum {MAX_BODY_CHARS}). "
            "Split the article or expand one section at a time."
        )

    provider = (provider or get_settings().expand_provider).lower()
    if provider not in EXPAND_PROVIDERS:
        raise ExpandError(f"unknown provider {provider!r} (choose: {', '.join(EXPAND_PROVIDERS)})")
    folder = output_dir() if save else None  # fail BEFORE spending time on the model

    research = (research or "").strip()[:MAX_RESEARCH_CHARS]
    if research:
        message = f"<article>\n{body}\n</article>\n\n<web_research>\n{research}\n</web_research>"
        prompt = PROMPT_RESEARCH
    else:
        message, prompt = body, PROMPT_NAME

    started = time.monotonic()
    ask = _ask_openrouter if provider == "openrouter" else _ask_ollama
    answer, used, attempts = ask(message, model, temperature, prompt=prompt)
    seconds = time.monotonic() - started

    text, notes = clean_answer(answer)
    if research:
        # A model may echo the tags of our input format; they must never reach the website.
        stripped = re.sub(r"</?(?:article|web_research)>\s*", "", text).strip()
        if stripped != text:
            text = stripped
            notes.append("removed <article>/<web_research> tags the model echoed")
    warnings, more_notes = compare_texts(body, text, known_urls=research_urls if research else ())
    cautions = [c for c in (growth_caution(count_words(body), count_words(text)),) if c]
    if attempts > 1:
        more_notes.append(f"the model answered on attempt {attempts}")
    if research:
        more_notes.insert(0, "the rewrite used web search results")
    result = Expansion(
        text=text,
        provider=provider,
        model=used,
        words_before=count_words(body),
        words_after=count_words(text),
        seconds=seconds,
        warnings=warnings,
        cautions=cautions,
        attempts=attempts,
        notes=notes + more_notes,
    )
    if not text.strip():
        raise ExpandError("the model returned an empty answer; try again or choose another model")
    if folder is not None:
        try:
            result.saved_to = save_expansion(text, page)
        except OSError as exc:
            result.warnings.append(f"could not save the file: {exc}")
    if copy:
        result.copied = copy_to_clipboard(text)
        if not result.copied:
            result.notes.append("the clipboard (pbcopy) is not available here")
    if show:
        _report(result, page, show_text=True)
    return result


# --------------------------------------------------------------------------- #
# Command line                                                                #
# --------------------------------------------------------------------------- #


def cli(argv=None) -> int:
    """python3 content_expand.py PAGE.md [--provider P] [--model M] [--copy] [--no-save]."""
    parser = argparse.ArgumentParser(
        prog="content_expand.py",
        description="Rewrite and expand one Hugo article with an AI model, ready to paste.",
    )
    parser.add_argument("page", help="the .md file (path, or relative to HUGO_ROOT/content)")
    parser.add_argument("--provider", choices=EXPAND_PROVIDERS, help="default: EXPAND_PROVIDER of .env")
    parser.add_argument("--model", help="model name (default: OPENROUTER_MODEL / MYMODEL_QUERY)")
    parser.add_argument("--temperature", type=float, help="0 (precise) ... 2 (creative)")
    parser.add_argument("--copy", action="store_true", help="also put the article on the clipboard")
    parser.add_argument("--no-save", action="store_true", help="do not write a copy to EXPAND_OUTPUT_DIR")
    args = parser.parse_args(argv)

    from content_creation import find_page  # same page lookup as content_creation.py

    path, tried = find_page(args.page)
    if path is None:
        print(f"page not found: {args.page}", file=sys.stderr)
        return 2
    try:
        result = expand_article(
            path,
            provider=args.provider,
            model=args.model,
            temperature=args.temperature,
            save=not args.no_save,
            copy=args.copy,
        )
    except ExpandError as exc:
        console.print(Text(f"error: {exc}", style="red"))
        return 1
    return 1 if result.serious else 0


if __name__ == "__main__":
    sys.exit(cli())
