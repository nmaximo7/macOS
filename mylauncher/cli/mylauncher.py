#!/usr/bin/env python3
"""
mylauncher.py - the command line of mylauncher. THIS is the engine; the window (app/) will only be a
pretty skin that calls this program.

    python3 cli/mylauncher.py list                       every item the launcher knows
    python3 cli/mylauncher.py search obs                 suggestions for what you typed
    python3 cli/mylauncher.py complete obs               what Tab would write:  run obsidian
    python3 cli/mylauncher.py run obsidian               do the best match (like pressing Enter)
    python3 cli/mylauncher.py run --id cmd:shutdown      do one exact item
    python3 cli/mylauncher.py search yt lofi             a quicklink: keyword, space, query
    python3 cli/mylauncher.py run kill ghostty           close an app (--force if it will not quit)
    python3 cli/mylauncher.py history                    what you use most (--clear forgets it)
    python3 cli/mylauncher.py config                     where the settings are, and what they say
    python3 cli/mylauncher.py doctor                     check that everything is in place

Useful options (they go after the sub-command):
    --json         write the answer as JSON (this is how the window will talk to us)
    --config FILE  use another configuration file
    --dry-run      (run) show what would happen, do nothing
    --yes          (run) do not ask "are you sure?"

How the pieces fit (one arrow = "uses"):

    mylauncher.py  ->  myconfig.py  (read the settings)
                   ->  myapps.py    (find the apps)
                   ->  mysearch.py  (rank the matches)
                   ->  myactions.py (do the thing)   ->  mykill.py (which apps are running)
                   ->  myquicklinks.py (web searches)    myhistory.py (most used first)
    all of them share the data shapes of  mytypes.py

Exit codes:  0 = all good   1 = nothing found / action failed / cancelled   2 = bad usage or bad configuration
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import os
import shutil
import sys
import time
from pathlib import Path

from myactions import RunOptions, default_runner, run_item
from myapps import find_apps
from myconfig import Config, ConfigError, find_config_path, load_config
from myexpander import load_snippets, preview
from myhistory import History
from mykill import running_apps
from myquicklinks import build_url
from mysearch import complete, rank, split_prefix
from mytypes import Item, Match

VERSION = "0.5.0"

SCORE_MODE = 200  # a quicklink you have already started typing a query for beats everything else


# --------------------------------------------------------------------------- #
# Step A: build the list of everything the launcher can do                    #
# --------------------------------------------------------------------------- #


def build_items(config: Config) -> list:
    """The STATIC items (they do not depend on what you typed): commands, "prefix" hints, apps.

    kind="prefix" items are words that need more text after them ("yt", "kill"). Selecting one and
    pressing Enter (or Tab) writes the word and a space in the search box.
    """
    items = []
    for command in config.commands:
        items.append(
            Item(
                id=f"cmd:{command.id}",
                title=command.title,
                kind="command",
                action=command.action,
                keywords=command.keywords,
                confirm=command.confirm,
            )
        )
    items.append(
        Item(
            id=f"prefix:{config.kill_word}",
            title=f"Close an app ({config.kill_word} <name>)",
            kind="prefix",
            action="prefix_hint",
            keywords=(config.kill_word,),
            complete=f"{config.kill_word} ",
        )
    )
    for link in config.quicklinks:
        items.append(
            Item(
                id=f"link:{link.keyword}",
                title=f"Search {link.title} ({link.keyword} <text>)",
                kind="prefix",
                action="prefix_hint",
                keywords=(link.keyword,),
                complete=f"{link.keyword} ",
            )
        )
    for name, path in find_apps(config.app_folders, config.app_exclude):
        items.append(Item(id=f"app:{name}", title=f"Run {name}", kind="app", action="open_app", target=str(path)))
    return items


def build_snippet_items(config: Config) -> list:
    """One item per Espanso trigger (see myexpander.py). The trigger is the title (that is what you
    search), and the text goes in `subtitle` (shown, not searched) and `target` (what gets copied)."""
    if not config.expander_enabled:
        return []
    scan = load_snippets(config.expander_folder, config.expander_strip_cursor)
    return [
        Item(
            id=f"snip:{snippet.trigger}",
            title=snippet.trigger,
            kind="snippet",
            action="copy_snippet",
            target=snippet.text,
            keywords=(snippet.label,) if snippet.label else (),
            complete=snippet.trigger,
            subtitle=preview(snippet.text),
        )
        for snippet in scan.snippets
    ]


def _bonus(config: Config):
    """Item -> extra points for the items you use most (see myhistory.py). None when history is off."""
    if not config.usage_enabled:
        return None
    counts = History(config.usage_file, True).counts()
    return lambda item: min(counts.get(item.id, 0) * config.usage_boost_per_use, config.usage_max_boost)


def _search(config: Config, query: str, limit: int | None = None, runner=default_runner) -> list:
    """items -> ranked matches for `query`.

    Three situations, decided by the FIRST word you typed:
      * "yt lofi"   the first word is a quicklink keyword and there is a space: ONE result, the web search.
      * "kill gh"   the first word is the kill word: the RUNNING apps, filtered by what follows.
      * anything else: the normal search over commands, hints and apps.
    """
    limit = config.max_results if limit is None else limit
    options = dict(ignore_accents=config.ignore_accents, fuzzy=config.fuzzy, bonus=_bonus(config))
    parts = split_prefix(query)
    word, rest = parts if parts else ("", "")

    if parts:
        for link in config.quicklinks:
            if word == link.keyword:
                title = f"Search {link.title} for {rest}" if rest else f"Search {link.title}: type what to look for"
                item = Item(
                    id=f"link:{link.keyword}",
                    title=title,
                    kind="quicklink",
                    action="open_url",
                    target=build_url(link, rest),
                    complete=f"{link.keyword} {rest}" if rest else f"{link.keyword} ",
                )
                return [Match(item, SCORE_MODE)]

    if query.strip().lower() == config.kill_word or (parts and word == config.kill_word):
        apps = running_apps(runner, config.kill_protected)
        # Rank on the bare names, then give each result its final title: otherwise the word "Kill"
        # in every title would match whatever you type after "kill".
        named = [Item(id=f"kill:{a.name}", title=a.name, kind="kill", action="kill_app", target=a.path) for a in apps]
        matches = rank(named, rest, limit, **options)
        return [
            Match(
                dataclasses.replace(m.item, title=f"Kill {m.item.title}", complete=f"{config.kill_word} {m.item.title.lower()}"),
                m.score,
            )
            for m in matches
        ]

    items = build_items(config)
    if query.strip():  # snippets can be many: they appear only when you type something
        items += build_snippet_items(config)
    return rank(items, query, limit, **options)


def _print_json(data) -> None:
    print(json.dumps(data, indent=2, ensure_ascii=False))


# --------------------------------------------------------------------------- #
# Step B: one function per sub-command                                        #
# --------------------------------------------------------------------------- #


def cmd_list(args, config: Config, **_) -> int:
    items = build_items(config) + build_snippet_items(config)
    if args.json:
        _print_json([item.to_dict() for item in items])
        return 0
    width = max((len(i.id) for i in items), default=0)
    for item in items:
        print(f"{item.id:<{width}}  {item.title}")
    print(f"\n{len(items)} item(s)")
    return 0


def cmd_search(args, config: Config, runner=default_runner, **_) -> int:
    query = " ".join(args.query)
    matches = _search(config, query, args.limit, runner)
    completion = complete(query, matches, config.ignore_accents)
    if args.json:
        _print_json({"query": query, "completion": completion, "results": [m.to_dict() for m in matches]})
        return 0 if matches else 1
    if not matches:
        print(f"no match for {query!r}")
        return 1
    width = max(len(m.item.title) for m in matches)
    for number, match in enumerate(matches, start=1):
        print(f"{number:>2}. {match.item.title:<{width}}  {match.item.kind:<8} score {match.score}")
    print(f"\ncompletion: {completion}")
    return 0


def cmd_complete(args, config: Config, runner=default_runner, **_) -> int:
    query = " ".join(args.query)
    completion = complete(query, _search(config, query, runner=runner), config.ignore_accents)
    if args.json:
        _print_json({"query": query, "completion": completion})
    else:
        print(completion)
    return 0


def cmd_run(args, config: Config, runner=default_runner, ask=input, sleep=time.sleep, **_) -> int:
    typed = args.text if args.text is not None else " ".join(args.query)

    # 1. Which item? An exact --id, or the best match for the words given (what Enter does).
    if args.id:
        # Dynamic items (a quicklink with its query, a running app to kill) only exist for the text
        # that produced them, so we search with --text first, then fall back to the static items.
        candidates = [m.item for m in _search(config, typed, limit=1000, runner=runner)] + build_items(config) + build_snippet_items(config)
        item = next((i for i in candidates if i.id == args.id), None)
        if item is None:
            return _fail(args, f"no item with id {args.id!r} (see: list)")
    else:
        if not typed.strip():
            return _fail(args, "say what to run, for example:  run obsidian   (or use --id)", code=2)
        matches = _search(config, typed, limit=1, runner=runner)
        if not matches:
            return _fail(args, f"no match for {typed!r}")
        item = matches[0].item

    # 2. Dangerous things ask first (unless --yes, or it is only a dry run).
    if item.confirm and not args.yes and not args.dry_run:
        if args.json:  # JSON mode must not print questions: the caller (the window) asks and passes --yes
            return _fail(args, f"'{item.title}' needs confirmation: run again with --yes")
        try:
            answer = ask(f"{item.title}: are you sure? [y/N] ")
        except EOFError:  # nobody is there to answer (for example a script): treat as "no"
            answer = ""
        if answer.strip().lower() not in ("y", "yes"):
            print("cancelled")
            return 1

    # 3. Do it.
    options = RunOptions(
        force=args.force,
        grace=config.kill_grace_seconds,
        auto_force=config.kill_auto_force,
        sleep=sleep,
        notify=config.expander_notify,
    )
    result = run_item(item, runner=runner, dry_run=args.dry_run, options=options)

    # 4. Remember it (for "most used first"), but only real, successful runs of real items.
    if result.ok and not args.dry_run and item.kind != "prefix":
        History(config.usage_file, config.usage_enabled).record(item.id)

    if args.json:
        _print_json({"item": item.to_dict(), "result": result.to_dict()})
    else:
        print(f"{item.title}: {result.message}")
    return 0 if result.ok else 1


def cmd_history(args, config: Config, **_) -> int:
    history = History(config.usage_file, True)
    if args.clear:
        history.clear()
        print(f"forgotten: {config.usage_file}")
        return 0
    titles = {i.id: i.title for i in build_items(config)}
    rows = history.top(args.limit)
    if args.json:
        _print_json([{"id": i, "count": n, "title": titles.get(i, i)} for i, n in rows])
        return 0
    if not config.usage_enabled:
        print("history is switched off (usage.enabled in the configuration)")
    if not rows:
        print(f"nothing yet ({config.usage_file})")
        return 0
    for item_id, count in rows:
        print(f"{count:>5}  {titles.get(item_id, item_id)}")
    return 0


def _fail(args, message: str, code: int = 1) -> int:
    """Report an error in the format the caller asked for, and return the exit code."""
    if args.json:
        _print_json({"error": message})
    else:
        print(f"error: {message}", file=sys.stderr)
    return code


def cmd_config(args, config: Config, **_) -> int:
    text = config.path.read_text(encoding="utf-8")
    if args.json:
        _print_json({"path": str(config.path), "config": json.loads(text)})
    else:
        print(f"# {config.path}")
        print(text.rstrip())
    return 0


def cmd_doctor(args, config: Config | None = None, config_error: str = "", **_) -> int:
    """Check the installation. ✔ = fine, ! = worth a look, ✘ = broken."""
    results = []  # (symbol, text)

    ok = sys.version_info >= (3, 11)
    results.append(("✔" if ok else "✘", f"Python {sys.version.split()[0]} (3.11 or newer needed)"))

    if config is None:
        results.append(("✘", config_error or "configuration could not be read"))
    else:
        results.append(("✔", f"configuration: {config.path}"))
        results.append(("✔", f"hotkey: {'+'.join(config.hotkey_modifiers)}+{config.hotkey_key} (used by the window in app/)"))
        for folder in config.app_folders:
            results.append(("✔" if folder.is_dir() else "!", f"app folder {folder}" + ("" if folder.is_dir() else " does not exist")))
        apps = find_apps(config.app_folders, config.app_exclude)
        results.append(("✔" if apps else "!", f"{len(apps)} application(s) found"))
        results.append(("✔", f"{len(config.commands)} command(s): " + ", ".join(c.id for c in config.commands)))
        exists = config.quicklinks_path.is_file()
        results.append(
            ("✔" if exists else "!", f"quicklinks: {len(config.quicklinks)} in {config.quicklinks_path}" + ("" if exists else " (file not found: no quicklinks)"))
        )
        if config.usage_enabled:
            counts = History(config.usage_file, True).counts()
            results.append(("✔", f"usage history on: {len(counts)} item(s) remembered in {config.usage_file}"))
        else:
            results.append(("✔", "usage history is switched off"))
        if config.expander_enabled:
            scan = load_snippets(config.expander_folder, config.expander_strip_cursor)
            if scan.missing_yaml:
                results.append(("!", "snippets: PyYAML is not installed (.venv/bin/pip install pyyaml), so Espanso snippets are off"))
            elif not config.expander_folder.is_dir():
                results.append(("!", f"snippets: folder {config.expander_folder} does not exist"))
            else:
                extra = []
                if scan.skipped:
                    extra.append(f"{scan.skipped} entr{'y' if scan.skipped == 1 else 'ies'} skipped (variables, forms or regex: need Espanso itself)")
                if scan.duplicates:
                    extra.append(f"{scan.duplicates} duplicate trigger(s) ignored")
                results.append(("✔", f"snippets: {len(scan.snippets)} trigger(s) from {scan.files} file(s) in {config.expander_folder}" + "".join(f"; {e}" for e in extra)))
                for problem in scan.problems:
                    results.append(("!", f"snippets: {problem}"))
        else:
            results.append(("✔", "snippets: not configured (set expander.folder to your Espanso folder)"))
        policy = "force quit automatically" if config.kill_auto_force else "asks before force quit"
        results.append(("✔", f"kill: '{config.kill_word} <name>' waits {config.kill_grace_seconds} s, then {policy}"))

    root = Path(__file__).resolve().parent.parent
    for relative in ("cli/ml", "app/mylauncher-app", "app/mylauncher-autostart"):
        script = root / relative
        if script.exists() and not os.access(script, os.X_OK):
            results.append(("!", f"{relative} is not executable (no problem with `bash {relative}`); to fix: chmod a+x {relative}"))
    for program, why in (("open", "opens applications and web pages"), ("osascript", "shuts the Mac down, asks apps to quit"), ("ps", "lists running apps (kill)")):
        found = shutil.which(program)
        results.append(("✔" if found else "!", f"'{program}' {why}: " + (found or "not found (normal if this is not a Mac)")))

    if args.json:
        _print_json([{"status": s, "text": t} for s, t in results])
    else:
        for symbol, text in results:
            print(f" {symbol} {text}")
    return 1 if any(s == "✘" for s, _ in results) else 0


# --------------------------------------------------------------------------- #
# Step C: read the command line and call the right function                   #
# --------------------------------------------------------------------------- #


def make_parser() -> argparse.ArgumentParser:
    # Options shared by every sub-command live in a "parent" parser, so we write them once.
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--config", metavar="FILE", help="configuration file (default: conf/myconfiguration.json)")
    common.add_argument("--json", action="store_true", help="write the answer as JSON")

    parser = argparse.ArgumentParser(prog="mylauncher", description="A small, readable launcher (command line engine).")
    parser.add_argument("--version", action="version", version=f"mylauncher {VERSION}")
    sub = parser.add_subparsers(dest="command", required=True, metavar="COMMAND")

    sub.add_parser("list", parents=[common], help="every item the launcher knows").set_defaults(func=cmd_list)

    p = sub.add_parser("search", parents=[common], help="suggestions for what you typed")
    p.add_argument("query", nargs="*", help="what you typed (nothing = everything)")
    p.add_argument("--limit", type=int, help="how many (default: search.max_results)")
    p.set_defaults(func=cmd_search)

    p = sub.add_parser("complete", parents=[common], help="the text Tab would write")
    p.add_argument("query", nargs="*")
    p.set_defaults(func=cmd_complete)

    p = sub.add_parser("run", parents=[common], help="do the best match, or one exact --id")
    p.add_argument("query", nargs="*", help="words to search; the best match is run")
    p.add_argument("--id", help="run exactly this item, e.g. app:Obsidian or cmd:shutdown")
    p.add_argument("--dry-run", action="store_true", help="show what would happen, do nothing")
    p.add_argument("--yes", action="store_true", help="do not ask for confirmation")
    p.add_argument("--text", help="what was typed in the search box (needed with --id for quicklinks and kill)")
    p.add_argument("--force", action="store_true", help="(kill) force quit now, without asking the app to quit")
    p.set_defaults(func=cmd_run)

    p = sub.add_parser("history", parents=[common], help="what you use most")
    p.add_argument("--clear", action="store_true", help="forget everything")
    p.add_argument("--limit", type=int, default=20)
    p.set_defaults(func=cmd_history)

    sub.add_parser("config", parents=[common], help="where the settings are and what they say").set_defaults(func=cmd_config)
    sub.add_parser("doctor", parents=[common], help="check the installation").set_defaults(func=cmd_doctor)
    return parser


def main(argv=None, runner=default_runner, ask=input, sleep=time.sleep) -> int:
    """Entry point. `runner`, `ask` and `sleep` can be replaced in tests (no real command, nobody asked, no waiting)."""
    args = make_parser().parse_args(argv)
    config, config_error = None, ""
    try:
        config = load_config(find_config_path(args.config))
    except ConfigError as exc:
        config_error = str(exc)
    if config is None and args.command != "doctor":  # doctor reports the problem itself
        return _fail(args, config_error, code=2)
    return args.func(args, config=config, config_error=config_error, runner=runner, ask=ask, sleep=sleep)


if __name__ == "__main__":
    sys.exit(main())
