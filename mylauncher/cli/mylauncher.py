#!/usr/bin/env python3
"""
mylauncher.py - the command line of mylauncher. THIS is the engine; the window (app/) will only be a
pretty skin that calls this program.

    python3 cli/mylauncher.py list                       every item the launcher knows
    python3 cli/mylauncher.py search obs                 suggestions for what you typed
    python3 cli/mylauncher.py complete obs               what Tab would write:  run obsidian
    python3 cli/mylauncher.py run obsidian               do the best match (like pressing Enter)
    python3 cli/mylauncher.py run --id cmd:shutdown      do one exact item
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
                   ->  myactions.py (do the thing)
    all of them share the data shapes of  mytypes.py

Exit codes:  0 = all good   1 = nothing found / action failed / cancelled   2 = bad usage or bad configuration
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys

from myactions import default_runner, run_item
from myapps import find_apps
from myconfig import Config, ConfigError, find_config_path, load_config
from mysearch import complete, rank
from mytypes import Item

VERSION = "0.1.0"


# --------------------------------------------------------------------------- #
# Step A: build the list of everything the launcher can do                    #
# --------------------------------------------------------------------------- #


def build_items(config: Config) -> list:
    """All the Items: first the commands from the configuration, then one "Run X" per installed app."""
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
    for name, path in find_apps(config.app_folders, config.app_exclude):
        items.append(Item(id=f"app:{name}", title=f"Run {name}", kind="app", action="open_app", target=str(path)))
    return items


def _search(config: Config, query: str, limit: int | None = None) -> list:
    """items -> ranked matches for `query`, using the search settings of the configuration."""
    return rank(
        build_items(config),
        query,
        limit=config.max_results if limit is None else limit,
        ignore_accents=config.ignore_accents,
        fuzzy=config.fuzzy,
    )


def _print_json(data) -> None:
    print(json.dumps(data, indent=2, ensure_ascii=False))


# --------------------------------------------------------------------------- #
# Step B: one function per sub-command                                        #
# --------------------------------------------------------------------------- #


def cmd_list(args, config: Config, **_) -> int:
    items = build_items(config)
    if args.json:
        _print_json([item.to_dict() for item in items])
        return 0
    width = max((len(i.id) for i in items), default=0)
    for item in items:
        print(f"{item.id:<{width}}  {item.title}")
    print(f"\n{len(items)} item(s)")
    return 0


def cmd_search(args, config: Config, **_) -> int:
    query = " ".join(args.query)
    matches = _search(config, query, args.limit)
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


def cmd_complete(args, config: Config, **_) -> int:
    query = " ".join(args.query)
    completion = complete(query, _search(config, query), config.ignore_accents)
    if args.json:
        _print_json({"query": query, "completion": completion})
    else:
        print(completion)
    return 0


def cmd_run(args, config: Config, runner=default_runner, ask=input, **_) -> int:
    items = build_items(config)

    # 1. Which item? An exact --id, or the best match for the words given (what Enter does).
    if args.id:
        item = next((i for i in items if i.id == args.id), None)
        if item is None:
            return _fail(args, f"no item with id {args.id!r} (see: list)")
    else:
        query = " ".join(args.query)
        if not query:
            return _fail(args, "say what to run, for example:  run obsidian   (or use --id)", code=2)
        matches = _search(config, query, limit=1)
        if not matches:
            return _fail(args, f"no match for {query!r}")
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
    result = run_item(item, runner=runner, dry_run=args.dry_run)
    if args.json:
        _print_json({"item": item.to_dict(), "result": result.to_dict()})
    else:
        print(f"{item.title}: {result.message}")
    return 0 if result.ok else 1


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
        results.append(("✔", f"hotkey: {'+'.join(config.hotkey_modifiers)}+{config.hotkey_key} (used by the window, from step 3)"))
        for folder in config.app_folders:
            results.append(("✔" if folder.is_dir() else "!", f"app folder {folder}" + ("" if folder.is_dir() else " does not exist")))
        apps = find_apps(config.app_folders, config.app_exclude)
        results.append(("✔" if apps else "!", f"{len(apps)} application(s) found"))
        results.append(("✔", f"{len(config.commands)} command(s): " + ", ".join(c.id for c in config.commands)))

    for program, why in (("open", "opens applications"), ("osascript", "shuts the Mac down")):
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
    p.set_defaults(func=cmd_run)

    sub.add_parser("config", parents=[common], help="where the settings are and what they say").set_defaults(func=cmd_config)
    sub.add_parser("doctor", parents=[common], help="check the installation").set_defaults(func=cmd_doctor)
    return parser


def main(argv=None, runner=default_runner, ask=input) -> int:
    """Entry point. `runner` and `ask` can be replaced in tests (so no real command runs, nobody is asked)."""
    args = make_parser().parse_args(argv)
    config, config_error = None, ""
    try:
        config = load_config(find_config_path(args.config))
    except ConfigError as exc:
        config_error = str(exc)
    if config is None and args.command != "doctor":  # doctor reports the problem itself
        return _fail(args, config_error, code=2)
    return args.func(args, config=config, config_error=config_error, runner=runner, ask=ask)


if __name__ == "__main__":
    sys.exit(main())
