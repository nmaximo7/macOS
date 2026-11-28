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

GUIDED TOUR OF THIS FILE (for someone who is just starting to program) --------------------------
This is the biggest file (~1800 lines) so it is read in THREE parts. A "part" is marked by a banner
comment made of dashes; search for  "Step A", "Step B", "Step C".

  Step A  (top)     BUILD AND SEARCH. Turn the configuration into a list of `Item`s (build_items, build_*_items,
                    tool_items, news_items, emoji_items), understand what the user typed (normalize_query,
                    detect_mode) and rank the items for it (_search). This is the "brain" of the launcher.
  Step B  (middle)  ONE FUNCTION PER SUB-COMMAND: cmd_list, cmd_search, cmd_run, cmd_help, cmd_emoji, cmd_secret,
                    cmd_timer, cmd_news, cmd_daily_gospel*, cmd_doctor ... Each one receives the parsed command-line
                    arguments and the Config, does its job, prints, and RETURNS an exit code (an int).
  Step C  (bottom)  make_parser() describes the command line (argparse) and main() ties everything together.

THE LIFE OF ONE KEYSTROKE (what happens when you type  "yt lofi"  in the window):
  1. The window (app/mylauncher_app.py) starts the program:   ml search --json "yt lofi"
  2. main() reads the arguments -> finds the configuration (myconfig) -> calls cmd_search().
  3. cmd_search() calls _search(): normalize_query -> split_prefix -> the first word "yt" is a quicklink
     keyword -> ONE Item(kind="quicklink", action="open_url", target="https://youtube.com/results?...").
  4. cmd_search() prints the items as JSON; the window draws the rows.
  5. You press Enter: the window starts   ml run --id link:yt --json "yt lofi"   -> cmd_run() -> run_item()
     (myactions.py) -> open_url -> `open https://...`.
Each keystroke is a NEW short program run. That sounds slow but Python starts in ~50 ms, and it makes the
engine trivially testable: no window, no hidden state, just  arguments in -> text out.

THE INJECTION HABIT: look at the parameters of every cmd_* function: runner, spawn, sleep, opener, fetcher,
today, out, ask. They are the "outside world" (running programs, waiting, opening files, the network, the
clock, printing, asking the user). In real life main() passes the real ones; the tests pass fakes. That is why
865 tests can run in 5 seconds without ever opening an app, touching the network or waiting. `**_` at the end
of a signature means "accept and ignore any other keyword argument": every cmd_* can then be called the same way.
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import os
import re
import shutil
import subprocess
import sys
import shlex
import time
from pathlib import Path

from myactions import ACTIONS, RunOptions, ml_command, default_runner, default_spawn, run_item
from myapps import find_apps
from myconfig import Config, ConfigError, find_config_path, load_config
import myespanso
from myexpander import describe_groups, group_of, load_snippets, preview
from myedit import build_edit_items
from myexecute import build_execute_items, build_favorites_items
from mysecret import add_name, scrub_names, keychain_get, set_notes, build_secret_items, edit_item, file_problems, read_secrets, table as secret_table
from mynotify import resolve as resolve_notifier, send as send_notification
import myversion
import mytimer
import mynews
import myemoji
import myimage
import mygospel
import mypost
import myfacebook
import myprayer
import myassistant
import mybriefing
from myhelp import TOPICS, help_end, help_search
from myhistory import History
from mykill import running_apps
from myquicklinks import build_url
from mysearch import complete, rank, split_prefix
from mytypes import Item, Match

VERSION = myversion.VERSION

SCORE_MODE = 200  # a quicklink you have already started typing a query for beats everything else


# --------------------------------------------------------------------------- #
# Step A: build the list of everything the launcher can do                    #
# --------------------------------------------------------------------------- #


# An `Item` (mytypes.py) is ONE ROW of the launcher: an id, a title, a "kind" (app, command, prefix, snippet...),
# an "action" (the key of ACTIONS in myactions.py) and a "target" (what the action works on).
# Everything the launcher shows is an Item; everything it does is `run_item(item)`.
def build_items(config: Config) -> list:
    """The STATIC items (they do not depend on what you typed): commands, "prefix" hints, apps.

    kind="prefix" items are words that need more text after them ("yt", "kill"). Selecting one and
    pressing Enter (or Tab) writes the word and a space in the search box.
    """
    items = []
    # 1) the commands written in the JSON ("commands": [...]) become Items one to one
    for command in config.commands:
        items.append(
            Item(
                id=f"cmd:{command.id}",
                title=command.title,
                kind="command",
                action=command.action,
                keywords=command.keywords,
                confirm=command.confirm,
                icon=command.icon,
                subtitle=command.description,
            )
        )
    # 2) the "prefix" rows: words that need more text after them. They do nothing when run ("prefix_hint"
    #    only explains), but they appear in the list and Tab completes them. The words come from the
    #    configuration (config.kill_word ...), so renaming `kill` to `quit` in the JSON just works.
    items.append(
        Item(
            id=f"prefix:{config.kill_word}",
            title=f"Close an app ({config.kill_word} <name>)",
            kind="prefix",
            action="prefix_hint",
            keywords=(config.kill_word,),
            complete=f"{config.kill_word} ",
            subtitle="Quits the app; force quit if it does not answer",
            icon="💀",
        )
    )
    items.append(
        Item(
            id=f"prefix:{config.secret_word}",
            title=f"Show your secrets ({config.secret_word})",
            kind="prefix",
            action="prefix_hint",
            keywords=(config.secret_word, "api key", "token", "password"),
            complete=f"{config.secret_word} ",
            subtitle="Names and values; Enter copies one (secret google)",
            icon="🔑",
        )
    )
    items.append(
        Item(
            id=f"prefix:{config.secret_edit_word}",
            title=f"Edit the secret file ({config.secret_edit_word})",
            kind="prefix",
            action="prefix_hint",
            keywords=(config.secret_edit_word, "secret", "api key", "token"),
            complete=config.secret_edit_word,
            subtitle="Opens the file of secrets in your editor",
            icon="🔐",
        )
    )
    items.append(
        Item(
            id=f"prefix:{config.help_word}",
            title=f"Help about your Mac ({config.help_word} <topic>)",
            kind="prefix",
            action="prefix_hint",
            keywords=(config.help_word, "aliases", "functions", "aerospace", "shortcuts"),
            complete=f"{config.help_word} ",
            subtitle="Aliases, functions, AeroSpace keys, snippets, scripts...",
            icon="📚",
        )
    )
    items.append(
        Item(
            id=f"prefix:{config.edit_word}",
            title=f"Edit a file ({config.edit_word} <name>)",
            kind="prefix",
            action="prefix_hint",
            keywords=(config.edit_word,),
            complete=f"{config.edit_word} ",
            subtitle="Files of edit.json: your configuration, scripts, notes",
            icon="📝",
        )
    )
    items.append(
        Item(
            id=f"prefix:{config.execute_word}",
            title=f"Execute a command ({config.execute_word} <name>)",
            kind="prefix",
            action="prefix_hint",
            keywords=(config.execute_word,),
            complete=f"{config.execute_word} ",
            subtitle="Commands of execute.json: scripts, maintenance, briefing",
            icon="▶️",
        )
    )
    items.append(
        Item(
            id=f"prefix:{config.favorites_word}",
            title=f"Favorites ({config.favorites_word})",
            kind="prefix",
            action="prefix_hint",
            keywords=(config.favorites_word, "favorite", "favourites"),
            complete=f"{config.favorites_word} ",
            subtitle="Your short list (conf/favorites.json): shut down the three computers, content creation, the prayer posts",
            icon="⭐",
        )
    )
    # the fixed tool words, written as a table: (word, title, subtitle, icon). One loop builds six items.
    for word, title, subtitle, icon in (
        ("about", "About mylauncher (about)", "Version, Python, configuration, hotkey: what is running now", "ℹ️"),
        ("timer", "Timer (timer <time>)", "timer 90, timer 5m, timer 1h30m: notification and sound at the end", "⏱️"),
        ("explain", "Explain a concept (explain <topic>)", "Local model, beginner explanation; the prompt is in prompts.json", "🧠"),
        ("deep_study", "Deep study (deep_study <topic>)", "Intuition, analogies, examples, why it works", "🔬"),
        ("copy_image_topic", "Copy images about a topic (copy_image_topic <topic>)", "Pictures that fit the topic, from your images folder to the destination folder", "🗂️"),
        ("describe_image", "Describe an image (describe_image <file>)", "Detailed description of a picture; no file = the newest screenshot", "🖼️"),
    ):
        items.append(Item(id=f"prefix:{word}", title=title, kind="prefix", action="prefix_hint", keywords=(word, word.replace("_", " ")), complete=f"{word} ", subtitle=subtitle, icon=icon))
    items.append(
        Item(
            id=f"prefix:{config.run_word}",
            title=f"List all applications ({config.run_word})",
            kind="prefix",
            action="prefix_hint",
            keywords=(config.run_word,),
            complete=f"{config.run_word} ",
            subtitle="Every application of this Mac; keep typing to filter",
            icon="🚀",
        )
    )
    # 3) one prefix row per quicklink (conf/quicklinks.json): "yt", "g", "wiki" ...
    for link in config.quicklinks:
        items.append(
            Item(
                id=f"link:{link.keyword}",
                title=f"Search {link.title} ({link.keyword} <text>)",
                kind="prefix",
                action="prefix_hint",
                keywords=(link.keyword,),
                complete=f"{link.keyword} ",
                subtitle=link.url.split("?")[0],
                icon=link.icon,
            )
        )
    # 4) the applications: scan the folders for *.app (myapps.py). The last and the longest part of the list.
    for name, path in find_apps(config.app_folders, config.app_exclude):
        items.append(Item(id=f"app:{name}", title=f"Run {name}", kind="app", action="open_app", target=str(path), subtitle=str(path.parent)))
    return items


def build_snippet_items(config: Config) -> list:
    """One item per Espanso trigger (see myexpander.py). The trigger is the title (that is what you
    search), and the text goes in `subtitle` (shown, not searched) and `target` (what gets copied).

    Snippets come from the Espanso YAML files (myexpander.py). They are NOT part of build_items(): there can be
    hundreds, so they are added only when you type something (see the end of _search)."""
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


def build_group_items(config: Config, prefix: str = "") -> list:
    """One row per snippet GROUP (";p", ";e"...): what appears when you type just ";".

    Selecting one and pressing Enter/Tab writes the group in the search box, and then the snippets
    of that group are listed (";pclarify", ";pexplain"...).
    """
    if not config.expander_enabled:
        return []
    scan = load_snippets(config.expander_folder, config.expander_strip_cursor)
    groups = describe_groups(scan.snippets, config.expander_group_length, config.expander_groups)
    items = []
    for key in sorted(groups):
        if not key.startswith(prefix):
            continue
        name, icon, count = groups[key]
        items.append(
            Item(
                id=f"group:{key}",
                title=f"{key}  {name}".rstrip(),
                kind="prefix",
                action="prefix_hint",
                complete=key,
                subtitle=f"{count} snippet(s)",
                icon=icon or "✂️",
                badge="Group",
            )
        )
    return items


def snippet_problem(config: Config) -> Item | None:
    """A row that explains WHY the snippet list is empty (missing PyYAML, folder not found), or None."""
    scan = load_snippets(config.expander_folder, config.expander_strip_cursor)
    if scan.missing_yaml:
        title, hint = "Snippets are off: PyYAML is not installed", ".venv/bin/pip install pyyaml  then  mlauto restart"
    elif not scan.snippets:
        title = "No snippets found"
        hint = scan.problems[0] if scan.problems else f"no triggers in {config.expander_folder}"
    else:
        return None
    return Item(id="info:snippets", title=title, kind="prefix", action="prefix_hint", complete=";", subtitle=hint, icon="⚠️", badge="Fix")


# The "tool words": typing `timer 5m` or `explain entropy` shows ONE row that starts a tool.
# ("deep-study" with a dash is accepted too: detect_mode normalises both spellings.)
TOOL_WORDS = ("about", "timer", "explain", "deep_study", "deep-study", "describe_image", "describe-image", "copy_image_topic", "copy-image-topic", "news", "create_image")


_ml_command = ml_command


def tool_items(config: Config, word: str, rest: str) -> list:
    """The one row of a tool word typed with a space: timer, explain, deep_study, describe_image."""
    word = word.replace("-", "_")
    if word == "timer":
        seconds = mytimer.parse_duration(rest) if rest.strip() else None
        if not rest.strip():  # "timer " alone: the timers that are counting down (the window redraws them every second)
            now = time.time()
            rows = [Item(id=f"timer-run:{t['id']}", title=mytimer.clock(t["remaining"]), kind="timer_run", action="timer_cancel", target=t["id"],
                         subtitle=f"{mytimer.format_duration(t['seconds'])} timer, rings at {time.strftime('%H:%M:%S', time.localtime(t['end']))}  ·  Enter cancels it",
                         detail=str(t["end"]), complete="timer ", icon="⏱️", badge="Running") for t in mytimer.running(config.timer_folder, now)]
            hint = Item(id="info:timer", title="Timer: how long?" if not rows else "New timer: how long?", kind="prefix", action="prefix_hint", complete="timer ",
                        subtitle="type the time: 90, 90s, 5m, 1h30m, 1:30", icon="⏱️", badge="Timer")
            return [*rows, hint]
        if seconds is None:
            sub = "type the time: 90, 90s, 5m, 1h30m, 1:30" + (f"   ({rest!r} is not a time)" if rest.strip() else "")
            return [Item(id="info:timer", title="Timer: how long?", kind="prefix", action="prefix_hint", complete="timer ", subtitle=sub, icon="⏱️", badge="Timer")]
        ends = time.strftime("%H:%M:%S", time.localtime(time.time() + seconds))
        return [Item(id=f"timer:{seconds}", title=f"Timer: {mytimer.format_duration(seconds)}", kind="timer", action="timer", target=str(seconds),
                     complete=f"timer {rest.strip()}", subtitle=f"rings at {ends}: notification and sound", icon="⏱️", badge="Timer")]
    if word == "news":
        return news_items(config, rest)
    if word == "create_image":
        prompt, folder = myimage.split_folder(rest, config.create_image_folder)
        if not prompt.strip():
            return [Item(id="info:create_image", title="Create image: what should it show?", kind="prefix", action="prefix_hint", complete="create image ",
                         subtitle="create image a red fox in the snow [FOLDER]   (folder = last word starting with / or ~)", icon="🎨", badge="Image")]
        return [Item(id="ai:create_image", title=f"Create image: {prompt}", kind="ai", action="execute_terminal", target=_ml_command("create-image", "--", rest.strip()),
                     complete=f"create image {rest.strip()}", subtitle=f"{config.create_image_backend}: { {'mflux': Path(config.create_image_mflux_command).name, 'ollama': config.create_image_ollama_model}.get(config.create_image_backend, config.create_image_openrouter_model) }  →  {folder}",
                     icon="🎨", badge="Image")]
    if word == "copy_image_topic":
        parts = [p.strip() for p in rest.split("|")]
        usage = "copy_image_topic FOLDER | TOPIC | DESTINATION     (or just  copy_image_topic TOPIC  with the folders of the `images` section)"
        if len(parts) == 1 and parts[0] and config.images_folder and config.images_destination:
            folder, topic, dest = config.images_folder, parts[0], config.images_destination
        elif len(parts) == 3 and all(parts):
            folder, topic, dest = parts
        else:
            return [Item(id="info:copy_image_topic", title="Copy images about a topic: how?", kind="prefix", action="prefix_hint", complete="copy_image_topic ",
                         subtitle=usage, icon="🗂️", badge="Images")]
        return [Item(id="ai:copy_image_topic", title=f"Copy images about {topic!r}", kind="ai", action="execute_terminal",
                     target=_ml_command("copy-image-topic", "--", folder, topic, dest), complete=f"copy_image_topic {rest}".rstrip(),
                     subtitle=f"{folder}  →  {dest}", icon="🗂️", badge="Images")]
    kind = {"explain": "explain", "deep_study": "deep_study", "describe_image": "describe_image"}.get(word)
    if kind is None:
        return []
    icon = {"explain": "🧠", "deep_study": "🔬", "describe_image": "🖼️"}[kind]
    what = {"explain": "Explain", "deep_study": "Deep study", "describe_image": "Describe image"}[kind]
    if kind == "describe_image":
        image = rest.strip().strip("'\"")
        if not image:  # nothing typed: the newest screenshot
            found = myassistant.latest_image(Path(config.screenshot_dir).expanduser() if config.screenshot_dir != "auto" else Path("~/Desktop").expanduser())
            if found is None:
                return [Item(id="info:describe_image", title="Describe image: which file?", kind="prefix", action="prefix_hint", complete="describe_image ",
                             subtitle="type the path of a png/jpg (no path = the newest screenshot)", icon=icon, badge=what)]
            image = str(found)
            subtitle = f"the newest screenshot: {found.name}  ·  model {config.ollama_vision_model or config.ollama_model}"
        else:
            subtitle = f"{image}  ·  model {config.ollama_vision_model or config.ollama_model}"
        return [Item(id="ai:describe_image", title=f"Describe image: {Path(image).name}", kind="ai", action="execute_terminal",
                     target=_ml_command("describe-image", "--", image), complete=f"describe_image {rest}".rstrip(), subtitle=subtitle, icon=icon, badge=what)]
    if not rest.strip():
        return [Item(id=f"info:{kind}", title=f"{what}: which concept?", kind="prefix", action="prefix_hint", complete=f"{kind} ",
                     subtitle="type the concept: photosynthesis, quantum entanglement ...", icon=icon, badge=what)]
    return [Item(id=f"ai:{kind}", title=f"{what}: {rest.strip()}", kind="ai", action="execute_terminal", target=_ml_command(kind.replace("_", "-"), "--", rest.strip()),
                 complete=f"{kind} {rest.strip()}", subtitle=f"opens a terminal and asks {config.ollama_model} (prompt: prompts.json)", icon=icon, badge=what)]


# `normalize_query` exists because some commands have a SPACE or DASH in their name for humans
# ("create image", "secret-set") but one word inside the code ("create_image"). It rewrites the start of the
# text only, and keeps the SAME LENGTH, because the window colours the first N characters (detect_mode returns N).
# Regular expression crib:  ^ start, (\s*) leading spaces (kept as \1), [ -] a space or a dash, (?=\s|$) "followed
# by a space or the end" without consuming it, re.IGNORECASE ignores capitals.
def normalize_query(query: str) -> str:
    """'create image x' and 'create-image x' become 'create_image x' (same length, so the coloured prefix stays right)."""
    query = re.sub(r"^(\s*)create[ -]image(?=\s|$)", r"\1create_image", query, flags=re.IGNORECASE)
    query = re.sub(r"^(\s*)secret[ -]set(?=\s|$)", r"\1secret_set", query, flags=re.IGNORECASE)
    return re.sub(r"^(\s*)emoji[ -](add|remove)(?=\s|$)", lambda m: f"{m.group(1)}emoji_{m.group(2).lower()}", query, flags=re.IGNORECASE)  # same length: 'secret-set' = 'secret_set'


# From here: one function per "family" of rows (news, emoji). Same recipe every time:
#   read what is cached/stored -> build a list of Item(...) -> return it. They never act, they only describe.
def news_items(config: Config, rest: str) -> list:
    """`news`, `news games`, `news finance bitcoin`: a refresh row, then the cached headlines (never the network: it must answer at once)."""
    try:
        categories = mynews.load_feeds(config.news_feeds_file)
    except mynews.NewsError as error:
        return [Item(id="info:news", title="News: the feeds file has a problem", kind="prefix", action="prefix_hint", complete="news ", subtitle=str(error)[:140], icon="📰", badge="News")]
    category, words = mynews.split_query(categories, config.news_default if config.news_default in categories else sorted(categories)[0], rest)
    cache = mynews.read_cache(config.news_cache_folder, category)
    now = time.time()
    if cache:
        stamp = f"last fetched {mynews.age(float(cache.get('fetched_at', 0)), now)}"
        title = f"Refresh {category} news"
    else:
        stamp = "nothing fetched yet: Enter downloads the feeds (a few seconds)"
        title = f"Fetch the {category} news"
    rows = [Item(id=f"news-refresh:{category}", title=title, kind="news_refresh", action="news_refresh", target=category,
                 complete=f"news {category} {words}".rstrip(), subtitle=f"{stamp}  ·  {len(categories[category])} feeds", icon="🔄", badge="News")]
    entries = mynews.select(cache["entries"], words, config.news_days, now) if cache else []
    for e in entries[: config.max_browse_results]:
        if e["url"].startswith(("http://", "https://")):
            rows.append(Item(id=f"news:{e['url']}", title=e["title"], kind="news", action="open_url", target=e["url"], complete=f"news {category} {words}".rstrip(),
                             subtitle=f"{e['source']}  ·  {mynews.age(e['date'], now)}", detail=e["summary"], icon="📰", badge=category.title()))
    if cache and not entries:
        rows.append(Item(id="info:news-none", title="No headline matches", kind="prefix", action="prefix_hint", complete=f"news {category} ", subtitle=f"in {category} (last {config.news_days} days): {words!r}", icon="📰", badge="News"))
    if not words:  # the other categories, one row each
        for other in sorted(categories):
            if other != category:
                rows.append(Item(id=f"info:news-{other}", title=f"News: {other}", kind="prefix", action="prefix_hint", complete=f"news {other} ", subtitle=f"{len(categories[other])} feeds", icon="📰", badge="News"))
    return rows


def emoji_row(config: Config, entry, favorites: set, verb: str = "") -> Item:
    """One emoji as a row. verb "" = Enter copies it; "add" / "remove" = Enter changes your favorites."""
    star = "⭐ " if myemoji.bare(entry.char) in favorites else ""
    detail = f"{entry.label}" + (f"  ·  {entry.words}" if entry.words else "")
    if verb:
        return Item(id=f"emoji-{verb}:{entry.char}", title=f"{'Add' if verb == 'add' else 'Remove'} {entry.char}  {entry.name} {'to' if verb == 'add' else 'from'} my_favorites",
                    kind="emoji_fav", action="emoji_favorite", target=entry.char, subtitle=star + detail, icon=entry.char, badge="Favorites", complete=f"emoji-{verb} {entry.name}")
    return Item(id=f"emoji:{entry.char}", title=f"{entry.char}  {entry.name}", kind="emoji", action="copy_emoji", target=entry.char, subtitle=star + detail,
                icon=entry.char, badge="Emoji", complete=f"emoji {entry.name}")


def emoji_items(config: Config, mode: str, rest: str) -> list:
    """The rows of `emoji ...`, `emoji-add ...` and `emoji-remove ...`."""
    path = config.emoji_favorites_file
    favorites = {myemoji.bare(e.char) for e in myemoji.favorite_entries(path)}
    if not myemoji.load_all():
        return [Item(id="info:emoji", title="Emoji: the data file is missing", kind="prefix", action="prefix_hint", complete="emoji ", subtitle=f"expected {myemoji.DATA_FILE}", icon="😀", badge="Emoji")]
    if mode == "emoji_remove":
        entries = myemoji.favorite_entries(path)
        entries = myemoji.search(entries, rest) if rest.strip() else entries
        if not entries:
            return [Item(id="info:emoji", title="Remove from my_favorites: nothing matches", kind="prefix", action="prefix_hint", complete="emoji-remove ", subtitle="type part of a name, e.g. emoji-remove brain", icon="⭐", badge="Favorites")]
        return [emoji_row(config, e, favorites, "remove") for e in entries]
    if mode == "emoji_add":
        if not rest.strip():
            return [Item(id="info:emoji", title="Add to my_favorites: which emoji?", kind="prefix", action="prefix_hint", complete="emoji-add ",
                         subtitle="type the emoji itself (emoji-add 🧠) or part of its name (emoji-add brain)", icon="⭐", badge="Favorites")]
        found = myemoji.chars_in(rest) if not rest.isascii() else []
        entries = found or myemoji.search(myemoji.load_all(), rest)
        if not entries:
            return [Item(id="info:emoji", title=f"No emoji matches {rest!r}", kind="prefix", action="prefix_hint", complete="emoji-add ", subtitle="try another word", icon="⭐", badge="Favorites")]
        return [emoji_row(config, e, favorites, "add") for e in entries]
    category, entries = myemoji.select(path, rest)
    if not category and not rest.strip():  # `emoji` alone: the categories
        counts = myemoji.category_counts(path)
        return [Item(id=f"info:emoji-{key}", title=label, kind="prefix", action="prefix_hint", complete=f"emoji {key} ", icon=icon, badge="Category",
                     subtitle=f"{counts.get(key, 0)} emoji  ·  emoji {key}   (Enter opens it)") for key, (label, icon) in myemoji.CATEGORIES.items()]
    if not entries:
        hint = "no favorites yet: emoji-add brain" if category == myemoji.FAVORITES and not rest.split(maxsplit=1)[1:] else "nothing matches; try another word"
        return [Item(id="info:emoji", title="Emoji: nothing found", kind="prefix", action="prefix_hint", complete="emoji ", subtitle=hint, icon="😀", badge="Emoji")]
    return [emoji_row(config, e, favorites) for e in entries]


# detect_mode is a long chain of `if word == ...: return (...)`. Order matters: the first match wins. It is
# deliberately NOT clever (no tables, no classes): you can follow it with your finger.
def detect_mode(config: Config, query: str) -> tuple:
    """(mode, n): what the launcher understood and how many characters at the start of the query
    make up the recognised command (the window paints them in colour).

    mode is one of: "normal", "run", "kill", "help", "edit", "execute", "favorites", "secret", "keep_secret", "quicklink", "snippets",
    "tool", "emoji", "emoji_add", "emoji_remove", "secret_set".

    Examples (default settings):
        detect_mode(cfg, "kill gh")     -> ("kill", 4)      the first 4 characters "kill" are painted orange
        detect_mode(cfg, "yt lofi")     -> ("quicklink", 2)
        detect_mode(cfg, ";pclar")      -> ("snippets", 6)  starts with a symbol: an Espanso trigger
        detect_mode(cfg, "safari")      -> ("normal", 0)    nothing special: search everything
    """
    query = normalize_query(query)
    text = query.lstrip()
    lead = len(query) - len(text)
    parts = split_prefix(query)
    word = parts[0] if parts else text.strip().lower()
    if word in TOOL_WORDS and parts:
        return "tool", lead + len(word)
    if word == config.run_word:
        return "run", lead + len(word)
    if word == config.kill_word:
        return "kill", lead + len(word)
    if word == config.help_word:
        return "help", lead + help_end(config, text)
    if word in ("emoji", "emoji_add", "emoji_remove"):
        return word, lead + len(word)
    if word == "secret_set":  # secret-set NAME VALUE: writes the Keychain
        return "secret_set", lead + len(word)
    if word == config.secret_word:
        return "secret", lead + len(word)
    if word == config.secret_edit_word:
        return "keep_secret", lead + len(word)
    if word == config.edit_word:
        return "edit", lead + len(word)
    if word == config.execute_word:
        return "execute", lead + len(word)
    if word == config.favorites_word:
        return "favorites", lead + len(word)
    if parts:
        for link in config.quicklinks:
            if word == link.keyword:
                return "quicklink", lead + len(word)
    if text and not text[0].isalnum() and not text[0].isspace() and config.expander_enabled:
        return "snippets", lead + len(text.split()[0])
    return "normal", 0


# `lambda item: ...` is a tiny anonymous function. Here it is the "extra points" rule handed to the ranker:
# every time you ran an item it earns `usage_boost_per_use` points, capped at `usage_max_boost` (the cap is
# below 20 so that a BETTER text match always beats a merely popular item).
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
    # How to read this long function: it is a list of special cases, tried from the most specific to the most
    # general, each one ending in `return`. The LAST lines are the normal case (rank everything).
    # `Match(item, score)` pairs an Item with how well it matched; a high fixed score (SCORE_MODE=200 or 100)
    # puts a special row above the normal results.
    limit = config.max_results if limit is None else limit
    options = dict(ignore_accents=config.ignore_accents, fuzzy=config.fuzzy, bonus=_bonus(config))
    query = normalize_query(query)
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
                    icon=link.icon,
                    subtitle=target if (target := build_url(link, rest)) else "",
                )
                return [Match(item, SCORE_MODE)]

    if parts and word == "about":
        return help_search(config, f"{config.help_word} about {rest}".rstrip(), runner, **options)
    if parts and word in TOOL_WORDS:
        return [Match(i, SCORE_MODE) for i in tool_items(config, word, rest)]
    if query.strip().lower() == "create_image":
        return [Match(i, SCORE_MODE) for i in tool_items(config, "create_image", "")]
    if query.strip().lower() == "news":
        return [Match(i, SCORE_MODE) for i in tool_items(config, "news", "")]
    if query.strip().lower() == "timer":  # alone: the timers that are counting down
        return [Match(i, SCORE_MODE) for i in tool_items(config, "timer", "")]

    mode, _ = detect_mode(config, query)

    if mode == "run":
        # every application (the rows are the normal "Run <name>" items) filtered by what follows
        apps = [i for i in build_items(config) if i.kind == "app"]
        return rank(apps, rest, config.max_browse_results, **options)

    if mode == "help":
        return help_search(config, query, runner, **options)

    if mode == "keep_secret":
        return [Match(edit_item(config), 100)]

    if mode in ("emoji", "emoji_add", "emoji_remove"):
        return [Match(i, 100) for i in emoji_items(config, mode, rest)[: config.max_browse_results]]

    if mode == "secret_set":  # secret-set google my password  ->  one row; Enter saves it in the Keychain
        name, _, value = rest.strip().partition(" ")
        value = value.strip()
        if not name or not value or not NAME_RE.match(name):
            hint = "type: secret-set NAME VALUE   (for example: secret-set google my password)" if not name else (f"{name!r} is not a good name (letters, digits, _ . -)" if not NAME_RE.match(name) else f"now type the value of {name}")
            return [Match(Item(id="info:secret-set", title="Save a secret in the Keychain", kind="prefix", action="prefix_hint", complete="secret-set ", subtitle=hint, icon="🔐", badge="Keychain"), 100)]
        item = Item(id="secret:*set*", title=f"Save {name} in the Keychain", kind="secret", action="secret_set", target=json.dumps({"name": name, "value": value}),
                    subtitle=f"{name} = {value}   (Enter saves it; the old value is replaced)", icon="🔐", badge="Keychain", complete=f"secret-set {name} ")
        return [Match(item, 100)]

    if mode == "secret":  # names and comments are searched, never the values
        items = build_secret_items(config, runner)
        if not rest.strip():
            return [Match(i, 100) for i in items[: config.max_browse_results]]
        found = rank([i for i in items if i.kind == "secret" or i.id.startswith("secret-problem:")], rest, config.max_browse_results, **{**options, "fuzzy": False})
        return found  # nothing found: an empty list (a value is never searched)

    if mode in ("edit", "execute", "favorites"):  # the lists of edit.json / execute.json / favorites.json, filtered by what follows the word
        items = {"edit": build_edit_items, "execute": build_execute_items, "favorites": build_favorites_items}[mode](config)
        if not rest.strip():  # nothing typed yet: the order of the file
            return [Match(i, 100) for i in items[: config.max_browse_results]]
        return rank(items, rest, config.max_browse_results, **{**options, "fuzzy": False})

    if mode == "snippets":
        typed = query.strip()
        problem = snippet_problem(config)
        if problem:
            return [Match(problem, 100)]
        if len(typed) < config.expander_group_length:
            groups = build_group_items(config, typed)
            return [Match(g, 100) for g in groups[: config.max_browse_results]]
        snippets = [i for i in build_snippet_items(config) if i.title.lower().startswith(typed.lower())]
        if not snippets:  # nothing starts like that: let the normal ranking look inside the texts too
            return rank(build_snippet_items(config), typed, config.max_browse_results, **options)
        return rank(snippets, typed, config.max_browse_results, **options)

    if query.strip().lower() == config.kill_word or (parts and word == config.kill_word):
        apps = running_apps(runner, config.kill_protected)
        # Rank on the bare names, then give each result its final title: otherwise the word "Kill"
        # in every title would match whatever you type after "kill".
        named = [Item(id=f"kill:{a.name}", title=a.name, kind="kill", action="kill_app", target=a.path, subtitle=a.path) for a in apps]
        matches = rank(named, rest, config.max_browse_results, **options)
        return [
            Match(
                dataclasses.replace(m.item, title=f"Kill {m.item.title}", complete=f"{config.kill_word} {m.item.title.lower()}"),
                m.score,
            )
            for m in matches
        ]

    # ---- the normal case: rank every command, hint and app against what was typed ----
    items = build_items(config)
    if query.strip():  # snippets can be many: they appear only when you type something
        items += build_snippet_items(config)
    matches = rank(items, query, limit, **options)
    # Two or more letters that start one of the command words ("exe", "ed", "sec") put that word first, so Tab completes it.
    typed = query.strip().lower()
    if len(typed) >= 2 and " " not in typed:
        words = [m for m in matches if m.item.kind == "prefix" and m.item.complete.strip().lower().startswith(typed)]
        words.sort(key=lambda m: len(m.item.complete))
        matches = words + [m for m in matches if m not in words]
    return matches


def _print_json(data) -> None:
    """The one way every command writes JSON: indented (readable), accents and emoji kept as they are (ensure_ascii=False)."""
    print(json.dumps(data, indent=2, ensure_ascii=False))


# --------------------------------------------------------------------------- #
# Step B: one function per sub-command                                        #
# --------------------------------------------------------------------------- #
#
# WHAT EVERY cmd_* LOOKS LIKE (learn this shape once, then all ~40 are easy):
#
#     def cmd_something(args, config, runner=default_runner, **_) -> int:
#         ...do the work with what is in `args` (the words typed after the sub-command) and `config`...
#         ...print the answer: human text, or JSON when args.json is True...
#         return 0            # 0 = success, 1 = "nothing found / failed", 2 = "you used it wrongly"
#
#   args    a Namespace made by argparse (Step C): args.query is a list of words, args.json a bool...
#   config  the checked, read-only Config (myconfig.py)
#   **_     "swallow" every other keyword: main() passes ALL the injected helpers to every command and each
#           command keeps only the ones it needs.
#   The int returned becomes the exit code of the whole program (`echo $?` in a terminal shows it),
#   which is how scripts and the window learn whether it worked.
#
# Reading order in this part: list, search, complete, run (the important one), help, emoji, secret, timer, AI tools,
# news, create-image, the daily-gospel family, then the maintenance commands (crash, report, history, doctor).


def cmd_list(args, config: Config, **_) -> int:
    """`ml list`: every static item (commands, hints, apps, snippets), one per line, or JSON with --json."""
    items = build_items(config) + build_snippet_items(config)
    if args.json:
        _print_json([item.to_dict() for item in items])
        return 0
    width = max((len(i.id) for i in items), default=0)  # the widest id, so the titles line up in a column
    for item in items:
        # f"{x:<10}" = "left-align x in a field 10 wide". Here the width is itself a variable: {item.id:<{width}}
        print(f"{item.id:<{width}}  {item.title}")
    print(f"\n{len(items)} item(s)")
    return 0


def cmd_search(args, config: Config, runner=default_runner, **_) -> int:
    """`ml search WORDS`: what the window calls on every keystroke.

    With --json it prints ONE object the window understands:
        {"query": "yt lofi", "completion": "yt lofi", "mode": "quicklink", "highlight": 2, "results": [ {item...}, ... ]}
    `completion` is what Tab would write, `mode`+`highlight` tell the window how many letters to paint orange.
    Exit code 1 means "no match" but the JSON is still printed (the window reads stdout whatever the code).
    """
    query = " ".join(args.query)  # argparse gave us a LIST of words; join them back into the text the user typed
    matches = _search(config, query, args.limit, runner)
    completion = complete(query, matches, config.ignore_accents)
    if args.json:
        mode, highlight = detect_mode(config, query)
        _print_json(
            {
                "query": query,
                "completion": completion,
                "mode": mode,
                "highlight": highlight,
                "results": [m.to_dict() for m in matches],
            }
        )
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
    """`ml complete obs` -> `run obsidian`: only the text Tab would write (see mysearch.complete)."""
    query = " ".join(args.query)
    completion = complete(query, _search(config, query, runner=runner), config.ignore_accents)
    if args.json:
        _print_json({"query": query, "completion": completion})
    else:
        print(completion)
    return 0


def cmd_run(args, config: Config, runner=default_runner, ask=input, sleep=time.sleep, spawn=default_spawn, **_) -> int:
    """`ml run WORDS` or `ml run --id ID --text WORDS`: do something. This is the Enter key.

    Four steps, numbered in the code:
      1. WHICH ITEM?   by exact id (the window sends the id of the highlighted row) or the best match of the words.
      2. CONFIRM?      items with confirm=True (restart, shutdown, publish...) ask "are you sure?" - except with
                       --yes, --dry-run, or --json (JSON mode never asks: the window asks and re-sends --yes).
      3. DO IT         build RunOptions from the Config, then run_item(...) from myactions.py.
      4. REMEMBER IT   count the use (so your favourites rise in the list) and print the result.
    Exit code: 0 done, 1 failed or cancelled, 2 bad usage.

    Why search again with --text when an id is given? Some items only exist for the text that created them
    ("Kill Safari" exists while Safari runs; "Search youtube for lofi" exists for the query "yt lofi"), so the
    id alone is not enough to rebuild them.
    """
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
        # Step 20.17 SAFETY: a list word alone ("favorites", "execute") shows a LIST in the window; as `ml run` it would run the FIRST entry of the list
        # (for favorites: the shutdown!). So we refuse and say how to choose.
        mode, _n = detect_mode(config, typed)
        if mode in ("favorites", "execute") and not typed.strip().split(maxsplit=1)[1:]:
            return _fail(args, f"say which one, for example:  run '{typed.strip()} <name>'   (the list: ml search -- {typed.strip()})", code=2)
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

    # 3. Do it. RunOptions (myactions.py) is a PACKAGE of settings for the actions; this copies, one by one,
    #    the settings that actions need from the Config. Long and boring on purpose: when you add an action
    #    that needs a setting, you add one line here (and one field in RunOptions).
    options = RunOptions(
        force=args.force,
        grace=config.kill_grace_seconds,
        auto_force=config.kill_auto_force,
        sleep=sleep,
        notify=config.expander_notify,
        copy_log=config.expander_copy_log,
        notify_method=config.notify_method,
        clear_seconds=config.secret_clear_seconds,
        secret_notify_value=config.secret_notify_value,
        secret_file=str(config.secret_file),
        emoji_favorites_file=str(config.emoji_favorites_file),
        secret_service=config.secret_service,
        timer_folder=config.timer_folder,
        timer_sound=config.timer_sound,
        timer_repeat=config.timer_repeat,
        timer_volume=config.timer_volume,
        timer_speak=config.timer_speak,
        timer_system_volume=config.timer_system_volume,
        weather_location=config.weather_location,
        weather_format=config.weather_format,
        weather_timeout=config.weather_timeout,
        news_feeds_file=str(config.news_feeds_file),
        gospel_folder=config.gospel_image_folder,
        gospel_image_count=config.gospel_image_count,
        news_cache_folder=config.news_cache_folder,
        news_timeout=config.news_timeout,
        aerospace=config.aerospace_enabled,
        aerospace_command=config.aerospace_command,
        aerospace_config=config.aerospace_config,
        aerospace_workspaces=config.aerospace_workspaces,
        power_force=config.power_force,
        power_grace=config.power_grace,
        power_protected=config.kill_protected,
        power_lock=config.power_lock,
        screenshot_dir=config.screenshot_dir,
        screenshot_clipboard=config.screenshot_clipboard,
        screenshot_delay=config.screenshot_delay,
        browser_command=config.browser_command,
        editor_command=config.edit_editor,
        shell=config.execute_shell,
        source_files=config.execute_source,
        terminal_command=config.execute_terminal_command,
        log_dir=config.execute_log_dir,
        execute_notify=config.execute_notify,
        spawn=spawn,
    )
    result = run_item(item, runner=runner, dry_run=args.dry_run, options=options)

    # 4. Remember it (for "most used first"), but only real, successful runs of real items. Secrets and emoji are
    #    not recorded: a usage file must never reveal which secret you copy.
    if result.ok and not args.dry_run and item.kind not in ("prefix", "help", "secret", "emoji", "emoji_fav"):
        History(config.usage_file, config.usage_enabled).record(item.id)

    if args.json:
        shown = item.to_dict()
        if item.kind == "secret":  # the value must not travel in the output (it would end up in logs and the window's memory)
            shown.update(target="(hidden)", detail="(hidden)", subtitle="(hidden)")
        _print_json({"item": shown, "result": result.to_dict()})
    else:
        print(f"{item.title}: {result.message}")
    return 0 if result.ok else 1


# `ml help` shows the same rows as typing `help` in the window. The rows are built in myhelp.py from your aliases,
# functions, AeroSpace config, skills and scripts; this function only prints them.
def cmd_help(args, config: Config, runner=default_runner, **_) -> int:
    """ml help [topic] [words...]: the same lists the launcher shows after typing `help`."""
    words = list(args.query)
    query = " ".join([config.help_word] + words)
    options = dict(ignore_accents=config.ignore_accents, fuzzy=config.fuzzy)
    matches = help_search(config, query, runner, refresh=args.refresh, **options)
    if args.json:
        _print_json([m.item.to_dict() for m in matches])
        return 0
    if not matches:
        print("nothing matches. Topics: " + ", ".join(TOPICS))
        return 1
    width = min(max(len(m.item.title) for m in matches), 40)
    for m in matches:
        sub = " ".join(m.item.subtitle.split())
        print(f"{m.item.title:<{width}}  {sub[:100]}{'…' if len(sub) > 100 else ''}")
    if len(matches) == 1 and matches[0].item.kind == "help":  # exactly one row: show everything about it
        print("\n" + matches[0].item.detail)
    return 0


# A secret's NAME must look like a shell variable: a letter or _, then letters, digits, _ . -  (GOOGLE_API_KEY, my-token).
# That keeps it safe inside a file line (NAME=value) and a Keychain account name.
NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_.-]*$")


def read_with_stars(prompt: str) -> str:
    """Read one line from the terminal showing * for every character typed (Backspace works). Falls back to input().

    A terminal normally waits for Enter and echoes what you type ("cooked mode"). `termios`/`tty.setcbreak` switch it
    to "cbreak": we get each key at once and decide ourselves what to show. The `finally:` ALWAYS puts the terminal
    back as it was, even if you press Ctrl-C, otherwise your shell would stay broken (no echo).
    """
    try:
        import termios
        import tty
        fd = sys.stdin.fileno()
        old = termios.tcgetattr(fd)
    except Exception:  # noqa: BLE001 - not a terminal (a pipe, Windows...): plain input
        return input(prompt)
    chars: list = []
    sys.stdout.write(prompt)
    sys.stdout.flush()
    try:
        tty.setcbreak(fd)
        while True:
            ch = sys.stdin.read(1)
            if ch in ("\n", "\r", ""):
                break
            if ch == "\x03":
                raise KeyboardInterrupt
            if ch in ("\x7f", "\b"):
                if chars:
                    chars.pop()
                    sys.stdout.write("\b \b")
            else:
                chars.append(ch)
                sys.stdout.write("*")
            sys.stdout.flush()
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old)
        sys.stdout.write("\n")
    return "".join(chars)


# The three emoji commands follow the same flow: find entries (myemoji) -> choose one (by emoji, exact name, or a
# number from a short list) -> change/copy -> print one line per emoji. `ask` is injected so tests can "type" the number.
def cmd_emoji(args, config: Config, runner=default_runner, **_) -> int:
    """ml emoji [CATEGORY] [WORDS]: the same lists as the launcher word `emoji`. --copy puts the first one in the clipboard."""
    text = " ".join(args.query).strip()
    category, entries = myemoji.select(config.emoji_favorites_file, text)
    if not category and not text:
        counts = myemoji.category_counts(config.emoji_favorites_file)
        for key, (label, icon) in myemoji.CATEGORIES.items():
            print(f"{icon}  {key:<12} {label:<20} {counts.get(key, 0):>4} emoji")
        print("\nExamples:  ml emoji smileys   ·   ml emoji brain   ·   ml emoji my_favorites   ·   ml emoji smileys happy   ·   ml emoji-add 🧠")
        return 0
    if not entries:
        print("nothing found" + ("; add favorites with:  ml emoji-add brain" if category == myemoji.FAVORITES else ""), file=sys.stderr)
        return 1
    shown = entries if args.limit == 0 else entries[: args.limit]
    if args.json:
        _print_json([{"emoji": e.char, "name": e.name, "category": e.category, "words": e.words} for e in shown])
    else:
        for e in shown:
            print(f"{e.char}  {e.name}   [{e.label}]")
        if len(shown) < len(entries):
            print(f"... {len(entries) - len(shown)} more (add words to narrow it, or --limit 0 for all)")
    if args.copy:
        done = runner(["pbcopy"], shown[0].char)
        print(f"{shown[0].char} copied to the clipboard" if done.returncode == 0 else "could not copy (pbcopy failed)", file=sys.stderr)
        return 0 if done.returncode == 0 else 1
    return 0


def _pick_emoji(entries, words: str, ask, verb: str):
    """One entry from a list: the only one, an exact name, or the one you choose by number (None = cancelled)."""
    if len(entries) == 1:
        return entries[0]
    exact = [e for e in entries if e.name == words.lower().strip()]
    if len(exact) == 1:
        return exact[0]
    for number, e in enumerate(entries[:20], 1):
        print(f"{number:>2}  {e.char}  {e.name}   [{e.label}]")
    if len(entries) > 20:
        print(f"    ... {len(entries) - 20} more: use more words")
    try:
        answer = ask(f"Which one to {verb}? number (Enter = cancel): ").strip()
    except (EOFError, KeyboardInterrupt):
        answer = ""
    if answer.isdigit() and 1 <= int(answer) <= min(len(entries), 20):
        return entries[int(answer) - 1]
    print("cancelled", file=sys.stderr)
    return None


def cmd_emoji_add(args, config: Config, ask=input, **_) -> int:
    """ml emoji-add 🧠   |   ml emoji-add brain: put an emoji in my_favorites (by the emoji itself, or by words, then a number if several)."""
    words = " ".join(args.query).strip()
    if not words:
        print("error: which emoji?  ml emoji-add 🧠   or   ml emoji-add brain", file=sys.stderr)
        return 2
    chosen = myemoji.chars_in(words) if not words.isascii() else []
    if not chosen:
        found = myemoji.search(myemoji.load_all(), words)
        if not found:
            print(f"error: no emoji matches {words!r}", file=sys.stderr)
            return 1
        pick = _pick_emoji(found, words, ask, "add")
        if pick is None:
            return 1
        chosen = [pick]
    for entry in chosen:
        added = myemoji.add_favorite(config.emoji_favorites_file, entry.char)
        print(f"{entry.char}  {entry.name}: " + ("added to my_favorites" if added else "was already in my_favorites"))
    return 0


def cmd_emoji_remove(args, config: Config, ask=input, **_) -> int:
    """ml emoji-remove brain: take an emoji out of my_favorites."""
    words = " ".join(args.query).strip()
    favorites = myemoji.favorite_entries(config.emoji_favorites_file)
    chosen = myemoji.chars_in(words) if words and not words.isascii() else []
    if not chosen:
        found = myemoji.search(favorites, words) if words else favorites
        if not found:
            print(f"error: nothing in my_favorites matches {words!r}", file=sys.stderr)
            return 1
        pick = _pick_emoji(found, words, ask, "remove")
        if pick is None:
            return 1
        chosen = [pick]
    for entry in chosen:
        removed = myemoji.remove_favorite(config.emoji_favorites_file, entry.char)
        print(f"{entry.char}  {entry.name}: " + ("removed from my_favorites" if removed else "was not in my_favorites"))
    return 0


# SECRETS in one paragraph: the VALUES live only in the macOS Keychain. secrets.env lists the NAMES (and notes) so you
# can see and edit them. `ml secret NAME` prints exactly the value and nothing else, so  $(ml secret google)  works in
# a shell. Nothing here logs or echoes a value except the commands whose job is to print it. See docs/secrets.md.
def cmd_secret(args, config: Config, runner=default_runner, **_) -> int:
    """ml secret [NAME]: print the value of NAME as it is (nothing else, so  $(ml secret google)  works); without NAME, every pair.

    Values come from the macOS Keychain. Changes typed in the secrets file (keep_secret) are moved into the Keychain first."""
    secrets, problem = read_secrets(config.secret_file, runner, config.secret_service)
    name = (args.name or "").strip()
    if not name:
        if not secrets:
            print(f"no secrets yet ({problem or 'the file is empty'}). Add one:  ml secret-set NAME VALUE", file=sys.stderr)
            return 1
        print(secret_table(secrets))
        return 0
    wanted = [s for s in secrets if s.name == name] or [s for s in secrets if s.name.lower() == name.lower()]
    if wanted:
        if wanted[0].problem:
            print(f"error: {name}: {wanted[0].problem}", file=sys.stderr)
            return 1
        print(wanted[0].value)
        return 0
    value, why = keychain_get(runner, config.secret_service, name)  # not in the file, but maybe in the Keychain
    if value:
        print(value)
        return 0
    print(f"error: no secret called {name!r}. Names: {', '.join(s.name for s in secrets) or '(none)'}. Add it:  ml secret-set {name} VALUE", file=sys.stderr)
    return 1


def cmd_secret_set(args, config: Config, ask=input, **_) -> int:
    """ml secret-set NAME [VALUE] [--notes TEXT]: save a value in the macOS Keychain and list the name.

    Without VALUE it is asked for, shown as `secret.input_echo` says: hidden, asterisks or visible.
    """
    name = args.name.strip()
    if not NAME_RE.match(name):
        print(f"error: {name!r} is not a good name (letters, digits, _ . -)", file=sys.stderr)
        return 2
    value = " ".join(args.value) if args.value else None
    mode = config.secret_input_echo
    if value is None and mode != "hidden":
        try:
            value = (read_with_stars if mode == "asterisks" else ask)(f"Value for {name}: ")
        except (EOFError, KeyboardInterrupt):
            print("\ncancelled", file=sys.stderr)
            return 1
        if not value:
            print("error: an empty value was not saved", file=sys.stderr)
            return 1
    # `security` is the macOS Keychain program: -U update if it exists, -s service (a folder-like label), -a account
    # (= the secret's name), -w the password. With -w LAST and no value, `security` asks for it itself and hides it.
    command = ["security", "add-generic-password", "-U", "-s", config.secret_service, "-a", name, "-w"]  # -w last: it asks, hidden
    if value is None:
        print(f"Saving {name} in the Keychain (service {config.secret_service}). Type or paste the value when asked (it is hidden).")
    else:
        command.append(value)
    try:
        code = subprocess.run(command, check=False).returncode
    except FileNotFoundError:
        print("error: the program 'security' was not found (is this a Mac?)", file=sys.stderr)
        return 1
    if code != 0:
        print(f"error: the Keychain did not save it (exit code {code})", file=sys.stderr)
        return 1
    added = add_name(config.secret_file, name)
    scrub_names(config.secret_file, [name])  # an old plain value on that line must not overwrite the new Keychain value later
    if args.notes is not None:
        set_notes(config.secret_file, name, args.notes.replace("\\n", "\n"))
    print("Saved." + (f" Added {name}= to {config.secret_file}." if added else "") + (" private_notes saved." if args.notes else ""))
    return 0


def cmd_secret_notes(args, config: Config, **_) -> int:
    """ml secret-notes NAME [TEXT]: the private_notes of an entry. Without TEXT, read lines from the terminal until Ctrl-D (empty = remove)."""
    name = args.name.strip()
    if not NAME_RE.match(name):
        print(f"error: {name!r} is not a good name (letters, digits, _ . -)", file=sys.stderr)
        return 2
    if args.text is not None:
        notes = args.text.replace("\\n", "\n")
    else:
        if sys.stdin.isatty():
            print(f"private_notes of {name}: type as many lines as you want, finish with Ctrl-D on an empty line (nothing = remove the notes).")
        notes = sys.stdin.read()
    add_name(config.secret_file, name)
    set_notes(config.secret_file, name, notes)
    print(f"private_notes of {name}: " + ("saved" if notes.strip() else "removed"))
    return 0


def summarize_crash(text: str, limit: int = 25) -> str:
    """A macOS crash report (.ips = two JSON documents, or an old .crash text) -> the few lines that matter.

    Used by `ml crash`. A crash report is thousands of lines; we keep: which app, which macOS, the exception, and
    the first `limit` frames (function calls) of the thread that crashed. The `try/except` is a safety net: if the
    file is not in the expected shape we print its first 60 lines instead of failing - a diagnostic tool must not
    crash while diagnosing a crash.
    """
    try:
        head, _, body = text.partition("\n")
        data = json.loads(body)
        exc, term = data.get("exception", {}), data.get("termination", {})
        lines = [f"app: {data.get('procName', '?')}  macOS: {data.get('osVersion', {}).get('train', '?')}",
                 f"exception: {exc.get('type', '?')} {exc.get('signal', '')} {exc.get('subtype', '')}".rstrip(),
                 f"termination: {term.get('indicator', term.get('reason', ''))}"]
        if data.get("asi"):
            lines.append(f"asi: {json.dumps(data['asi'])[:300]}")
        threads = data.get("threads", [])
        crashed = next((t for t in threads if t.get("triggered")), threads[data.get("faultingThread", 0)] if threads else {})
        images = data.get("usedImages", [])
        lines.append(f"crashed thread: {crashed.get('name') or crashed.get('queue') or crashed.get('id', '?')}")
        for frame in crashed.get("frames", [])[:limit]:
            image = images[frame["imageIndex"]].get("name", "?") if "imageIndex" in frame and frame["imageIndex"] < len(images) else "?"
            lines.append(f"  {image:<28} {frame.get('symbol', '?')}")
        return "\n".join(lines)
    except (ValueError, KeyError, TypeError, IndexError):
        return "\n".join(text.splitlines()[:60])


def cmd_about(args, config: Config, runner=default_runner, **_) -> int:
    """ml about: which mylauncher is this (version, files, Python, configuration, hotkey...)."""
    from myhelp import load_rows  # imported HERE, not at the top: only this command needs it (keeps start-up fast)

    rows, _problem = load_rows(config, "about", runner)
    if args.json:
        _print_json([{"name": r.title, "value": r.subtitle} for r in rows[1:]])
    else:
        print(f"mylauncher {myversion.one_line()}\n\n{rows[0].detail}")
    return 0


def cmd_timer(args, config: Config, runner=default_runner, spawn=default_spawn, **_) -> int:
    """ml timer 90 | 5m | 1h30m | 1:30: start a timer; a notification and a sound when it ends.

    Three sub-forms: `timer list`, `timer cancel [ID|all]`, and `timer <time>`. The time is parsed by
    mytimer.parse_duration (returns seconds, or None if it is not a time: exit code 2 = "you used it wrongly").
    Starting reuses the `timer` ACTION of myactions.py, exactly as the window would: one implementation, two doors.
    """
    text = " ".join(args.time)
    if text.strip().lower() in ("list", "ls"):
        found = mytimer.running(config.timer_folder, time.time())
        for t in found:
            print(f"{mytimer.clock(t['remaining'])}  {mytimer.format_duration(t['seconds'])} timer, rings at {time.strftime('%H:%M:%S', time.localtime(t['end']))}  (id {t['id']})")
        print(f"{len(found)} timer(s) running" if found else "no timer is running", file=sys.stderr)
        return 0
    if text.strip().lower().startswith("cancel"):
        wanted = text.split(None, 1)[1].strip() if " " in text.strip() else ""
        found = mytimer.running(config.timer_folder, time.time())
        chosen = [t for t in found if wanted in ("", "all", t["id"])]
        for t in chosen:
            mytimer.cancel(config.timer_folder, t["id"])
        print(f"{len(chosen)} timer(s) cancelled")
        return 0
    seconds = mytimer.parse_duration(text)
    if seconds is None:
        print(f"error: {text!r} is not a time. Try: 90, 90s, 5m, 1h30m, 1:30 (at most 24 h)", file=sys.stderr)
        return 2
    item = Item(id=f"timer:{seconds}", title="Timer", kind="timer", action="timer", target=str(seconds))
    options = RunOptions(notify_method=config.notify_method, timer_folder=config.timer_folder, timer_sound=config.timer_sound, timer_repeat=config.timer_repeat, timer_volume=config.timer_volume, timer_speak=config.timer_speak,
                         timer_system_volume=config.timer_system_volume, shell=config.execute_shell,
                         log_dir=config.execute_log_dir, spawn=spawn)
    result = ACTIONS["timer"](item, runner, args.dry_run, options)
    print(result.message)
    return 0 if result.ok else 1


# The AI commands (explain, deep-study, describe-image, find-image, copy-image-topic, daily-briefing) are THIN: they
# collect arguments and call myassistant.py / mybriefing.py, which talk to the local Ollama model. `opener` is the
# function that makes an HTTP request (real: urllib's urlopen; tests: a fake that returns a canned answer).
def _cmd_ai(kind: str, text: str, config: Config, spawn, sleep, opener, refresh: bool = False, **_) -> int:
    return myassistant.ask(config, kind, text, opener=opener or myassistant.urllib.request.urlopen, spawn=spawn, sleep=sleep, refresh=refresh)


def cmd_explain(args, config: Config, spawn=default_spawn, sleep=time.sleep, opener=None, **_) -> int:
    """ml explain TOPIC: a beginner explanation from the local model (prompt: conf/prompts.json)."""
    return _cmd_ai("explain", " ".join(args.topic), config, spawn, sleep, opener)


def cmd_deep_study(args, config: Config, spawn=default_spawn, sleep=time.sleep, opener=None, **_) -> int:
    """ml deep-study TOPIC: intuition, analogies, examples, why it works."""
    return _cmd_ai("deep_study", " ".join(args.topic), config, spawn, sleep, opener)


def cmd_describe_image(args, config: Config, spawn=default_spawn, sleep=time.sleep, opener=None, **_) -> int:
    """ml describe-image [FILE]: describe a picture in detail (no FILE: the newest screenshot)."""
    path = " ".join(args.file)
    if not path.strip():
        folder = Path("~/Desktop").expanduser() if config.screenshot_dir == "auto" else Path(config.screenshot_dir).expanduser()
        found = myassistant.latest_image(folder)
        if found is None:
            print(f"error: no image given and none found in {folder}", file=sys.stderr)
            return 1
        path = str(found)
    return _cmd_ai("describe_image", path, config, spawn, sleep, opener, refresh=args.refresh)


def cmd_find_image(args, config: Config, spawn=default_spawn, sleep=time.sleep, opener=None, **_) -> int:
    """ml find-image FOLDER TOPIC: the images below FOLDER that are about TOPIC, one path per line."""
    topic = " ".join(args.topic)
    try:
        found = myassistant.find_images(config, args.folder, topic, names_only=args.names_only, refresh=args.refresh, limit=args.limit,
                                        opener=opener or myassistant.urllib.request.urlopen, spawn=spawn, sleep=sleep)
    except (myassistant.AssistantError, ConfigError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    if args.json:
        _print_json([str(p) for p in found])
    else:
        for path in found:
            print(path)
        print(f"{len(found)} image(s) about {topic!r}", file=sys.stderr)
    return 0 if found else 1


def cmd_copy_image_topic(args, config: Config, spawn=default_spawn, sleep=time.sleep, opener=None, **_) -> int:
    """ml copy-image-topic FOLDER TOPIC DESTINATION: copy the images about TOPIC (see find-image) into DESTINATION."""
    topic = " ".join(args.topic)
    try:
        done = myassistant.copy_images(config, args.folder, topic, args.destination, names_only=args.names_only, refresh=args.refresh, limit=args.limit,
                                       dry_run=args.dry_run, opener=opener or myassistant.urllib.request.urlopen, spawn=spawn, sleep=sleep)
    except (myassistant.AssistantError, ConfigError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    if args.json:
        _print_json([{"from": str(s), "to": str(d), "status": st} for s, d, st in done])
    else:
        for source, target, status in done:
            print(f"{status:<8} {source}  ->  {target}")
        copied = sum(1 for *_x, st in done if st == "copied")
        print(f"{len(done)} image(s) about {topic!r}: {copied} copied" + (" (dry run: nothing was copied)" if args.dry_run else ""), file=sys.stderr)
    return 0 if done else 1


def cmd_daily_briefing(args, config: Config, runner=default_runner, spawn=default_spawn, sleep=time.sleep, opener=None, **_) -> int:
    """ml daily-briefing: calendar + inbox + to-do (gog and qmd), written as a briefing by the local model."""
    return mybriefing.run(config, runner, raw=args.raw, save=args.save, opener=opener or myassistant.urllib.request.urlopen, spawn=spawn, sleep=sleep)


def cmd_news(args, config: Config, fetcher=None, **_) -> int:
    """ml news [CATEGORY] [words]: the newest headlines of your feeds (conf/feeds.json), cached for news.cache_minutes.

    Flow: load the feeds file -> split the typed words into (category, search words) -> get() from the cache or the
    network -> filter by words and days -> print. A feed that does not answer is REPORTED but does not stop the others
    (`got["failed"]`). `fetcher` is injected so tests never touch the network.
    """
    try:
        categories = mynews.load_feeds(config.news_feeds_file)
        default = config.news_default if config.news_default in categories else sorted(categories)[0]
        category, words = mynews.split_query(categories, default, " ".join(args.words))
        if args.list:
            for name in sorted(categories):
                print(f"{name}: {len(categories[name])} feeds")
            return 0
        got = mynews.get(categories, category, config.news_cache_folder, config.news_cache_minutes, config.news_timeout, force=args.refresh, fetcher=fetcher or mynews.default_fetcher)
    except mynews.NewsError as error:
        print(f"ml news: {error}", file=sys.stderr)
        return 1
    days = args.days or config.news_days
    chosen = mynews.select(got["entries"], words, days)
    if args.limit:
        chosen = chosen[: args.limit]
    if got["failed"]:
        print(f"({len(got['failed'])} feed(s) did not answer: {', '.join(mynews.source_name(u) for u in got['failed'])})", file=sys.stderr)
    if args.json:
        print(json.dumps({"category": category, "fetched_at": got["fetched_at"], "total_entries": len(chosen), "entries": chosen}, ensure_ascii=False, indent=2))
        return 0 if chosen else 1
    if not chosen:
        print(f"No headline in {category!r} for the last {days} days" + (f" with {words!r}" if words else "") + ". Try --refresh or --days 30.", file=sys.stderr)
        return 1
    now = time.time()
    for e in chosen:
        print(f"{mynews.age(e['date'], now):>11}  {e['title']}\n{'':>13}{e['source']}  {e['url']}")
        if args.summary and e["summary"]:
            print(f"{'':>13}{e['summary']}")
    return 0


def cmd_create_image(args, config: Config, runner=default_runner, opener=None, **_) -> int:
    """ml create-image PROMPT [FOLDER]: a picture from a prompt (mflux, Ollama or OpenRouter), saved in FOLDER."""
    # Normally `runner` CAPTURES a program's output. For a slow image model we want the progress bar to appear in the
    # terminal, so in real life we swap in a runner that does not capture (except for the small `security`/`open` helpers).
    # A function defined INSIDE another function (a "closure") is fine in Python; `_real=default_runner` freezes the
    # real runner as a default argument so the inner function can still reach it.
    if runner is default_runner:  # in a terminal: let the model's progress bar show (the output is not captured)
        def runner(command, input_text=None, _real=default_runner):
            if command and command[0] in ("security", "open"):
                return _real(command, input_text)
            return subprocess.run(command, check=False)
    text = " ".join(args.words)
    if args.folder:
        text = f"{text} {args.folder}"
    try:
        paths, prompt, backend = myimage.generate(config, text, runner, opener or myimage.urllib.request.urlopen, backend=args.backend or "", model=args.model or "")
    except myimage.ImageError as error:
        print(f"ml create-image: {error}", file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps({"prompt": prompt, "backend": backend, "files": [str(p) for p in paths]}, ensure_ascii=False, indent=2))
    else:
        for path in paths:
            print(path)
    if config.create_image_open_after and not args.no_open and not args.json:
        try:
            runner(["open", str(paths[0])])
        except FileNotFoundError:
            pass
    return 0


# `_live_runner` is the same idea as in cmd_create_image, shared by the daily-gospel commands (they also run slow image models).
def _live_runner(runner):
    """In a terminal let the image model's progress show; small helper programs keep their captured output."""
    if runner is not default_runner:
        return runner
    real = default_runner

    # macOS prints "can't turn off malloc stack logging" from every Python child when this variable is set in the environment: do not pass it on
    clean_env = {k: v for k, v in os.environ.items() if not k.startswith("MallocStackLogging")}

    def live(command, input_text=None):
        return real(command, input_text) if command and command[0] in ("security", "open", "sips") else subprocess.run(command, check=False, env=clean_env)
    return live


# ---------------------------------------------------------------------------------------------------------------
# THE DAILY GOSPEL FAMILY - one pipeline, four commands, each one able to make the previous steps if they are missing:
#
#   ml daily-gospel-image     the Gospel -> theme + image prompt (Ollama) -> pictures
#   ml daily-gospel           the guided prayer (Ollama) + pictures, saved as DATE-gospel.json/.md/.html   (needs the above)
#   ml daily-gospel-post      a Hugo post DATE.md + pictures uploaded to the server (ssh/scp)               (needs daily-gospel)
#   ml daily-gospel-facebook  the Facebook text in the clipboard, the browser pastes it; YOU press Post     (needs daily-gospel)
#
# The "state of the day" is a small JSON file (myprayer.load_day / save_day). Every command first asks it "is the
# prayer done? are the pictures done?" and only does what is missing: that is why running a command twice is safe
# (idempotent) and why an interrupted run loses nothing. See docs/prayer.md, post.md, facebook.md.
# `today=` is injectable (tests pass a fixed date); `out=` is where progress messages go (stderr, so stdout stays clean for JSON).
# ---------------------------------------------------------------------------------------------------------------
def cmd_daily_gospel(args, config: Config, runner=default_runner, spawn=default_spawn, sleep=time.sleep, opener=None, fetcher=None, today=None, **_) -> int:
    """ml daily-gospel: EVERYTHING for today's Gospel, once a day.

    The guided prayer (date + saint, opening prayer, reading, reflection, Lord's Prayer, closing prayer) and the pictures, saved in
    gospel.image_folder as  DATE-gospel-prayer.md  (the result),  DATE-gospel.json  (all the data)  and  DATE-gospel-prayer.html  (the page
    that the launcher opens). If they are already there for today nothing is made again (--refresh makes them again); if only the pictures
    are missing, only they are made. The files are written after the prayer and again after the pictures: an interrupted run keeps the prayer.
    --plain: only the feed's reading (no model, no files). --no-images: no pictures. --json: print the JSON. --open: open the page.
    """
    # getattr(args, "x", default): "args.x if it exists, else default". Used because other commands build a partial
    # Namespace and call this function directly (see cmd_daily_gospel_post), without every option present.
    fetcher = fetcher or getattr(args, "fetcher", None) or mygospel.fetch
    if args.plain:
        try:
            gospel = mygospel.get_gospel(config, fetcher)
        except mygospel.GospelError as error:
            print(f"error: {error}", file=sys.stderr)
            return 1
        print(json.dumps(gospel, ensure_ascii=False, indent=2)) if args.json else mygospel.show(gospel)
        return 0
    from datetime import date as _date
    today = today or _date.today()
    day = today.strftime("%Y-%m-%d")
    folder = Path(getattr(args, "folder", "") or config.gospel_image_folder).expanduser()
    count = getattr(args, "count", 0) or config.gospel_image_count
    want_images = not getattr(args, "no_images", False)
    # --- 1. what already exists for today? (skipped entirely with --refresh) ---
    data = None if getattr(args, "refresh", False) else myprayer.load_day(folder, day)
    guided = dict(data) if data and myprayer.prayer_done(data) else None
    files = myprayer.day_files(folder, day)

    if guided is not None and (not want_images or myprayer.images_done(guided, folder, count)):  # nothing to do
        if args.json:
            print(json.dumps(guided, ensure_ascii=False, indent=2))
        else:
            if not files["html"].exists():
                files["html"].write_text(myprayer.render_html(guided, guided.get("title", "Daily Gospel")), encoding="utf-8")
            print(files["md"].read_text(encoding="utf-8") if files["md"].exists() else myprayer.render(guided))
            print(f"(already made today: {files['md']}   -  `ml daily-gospel --refresh` makes it again)", file=sys.stderr)
        if getattr(args, "open", False):
            myprayer.open_page(files["html"], config.browser_command, runner)
        return 0

    # --- 2. the prayer: fetch the reading, then ask the local model to compose the guided prayer ---
    try:
        if guided is None:
            gospel = mygospel.get_gospel(config, fetcher)
            print("🙏 preparing the prayer with the local model ...", file=sys.stderr, flush=True)
            guided = myprayer.compose(config, gospel, opener or myassistant.urllib.request.urlopen, spawn, sleep)
            guided["date_line"] = myprayer.date_line(today, myprayer.liturgical_name(today))
            guided["sources"] = [list(s) for s in (config.gospel_sources or myprayer.DEFAULT_SOURCES)]
            guided["images"], guided["theme"], guided["image_prompt"] = [], "", ""
        else:
            print("(the prayer of today is already made; only the pictures are missing)", file=sys.stderr, flush=True)
            for old in guided.get("images") or []:  # an interrupted run: start the pictures again, no _2 copies
                Path(old).unlink(missing_ok=True)
            guided["images"] = []
    except (mygospel.GospelError, myassistant.AssistantError, ConfigError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    if getattr(args, "refresh", False) and data:
        for old in data.get("images") or []:
            Path(old).unlink(missing_ok=True)
    # --- 3. save the prayer BEFORE making the pictures: pictures take minutes and may fail; the prayer must survive ---
    if not args.json:
        print(myprayer.render(guided))
    myprayer.save_day(folder, day, guided)
    print(f"(saved in {folder}: {files['md'].name}, {files['json'].name}, {files['html'].name})", file=sys.stderr, flush=True)
    # --- 4. the pictures (a failure here is reported but exit code 1 keeps the saved prayer) ---
    status = 0
    if want_images:
        try:
            prompt, paths, theme = mygospel.make_images(config, guided, _live_runner(runner), opener=opener or myassistant.urllib.request.urlopen, spawn=spawn, sleep=sleep,
                                                        count=count, folder=str(folder), backend=getattr(args, "backend", "") or "", note=False)
            guided["images"], guided["theme"], guided["image_prompt"] = paths, theme, prompt
            myprayer.save_day(folder, day, guided)
            if not args.json:
                for path in paths:
                    print(path)
        except (mygospel.GospelError, myimage.ImageError, myassistant.AssistantError, ConfigError) as error:
            print(f"error (the prayer is saved, the pictures are not): {error}", file=sys.stderr)
            status = 1
    if args.json:
        print(json.dumps({**guided, "images": [str(i) for i in guided["images"]]}, ensure_ascii=False, indent=2))
    if (getattr(args, "open", False) or (status == 0 and not getattr(args, "no_open", False) and config.create_image_open_after)):
        myprayer.open_page(files["html"], config.browser_command, runner)  # the finished page, in your browser
    return status


def cmd_daily_gospel_post(args, config: Config, runner=default_runner, spawn=default_spawn, sleep=time.sleep, opener=None, fetcher=None, today=None, out=None, **_) -> int:
    """ml daily-gospel-post: today's prayer as a Hugo post on your website.

    1. today's prayer and pictures (made first if they are not there), 2. title + description by Ollama (kept in the day's .json),
    3. DATE.md (for example 2026-11-24.md) with the Hugo front matter and the pictures at /prayer/images/, 4. pictures to the server, then the post.
    --dry-run: write the post locally and only PRINT the ssh/scp commands.  --no-upload: only write the post.  --draft: draft: true.
    --new-title: ask the model for another title/description.
    """
    from dataclasses import replace
    from datetime import date as _date
    out = out or sys.stderr
    today = today or _date.today()
    day = today.strftime("%Y-%m-%d")
    folder = Path(config.gospel_image_folder).expanduser()
    # `replace(config, post_draft=True)` = a COPY of the frozen Config with one field changed, for this run only.
    if getattr(args, "draft", False):
        config = replace(config, post_draft=True)
    data = myprayer.load_day(folder, day)
    # Step 1 of the post: make sure the prayer and the pictures exist. If not, call cmd_daily_gospel ourselves with a
    # hand-made Namespace (the object argparse would have built) - one command re-using another, no code copied.
    if not (myprayer.prayer_done(data) and myprayer.images_done(data, folder, config.gospel_image_count)):
        print("today's prayer or pictures are not complete: making them first (ml daily-gospel) ...", file=out, flush=True)
        inner = argparse.Namespace(json=False, plain=False, no_images=False, refresh=False, open=False, no_open=True, count=0, folder="", backend="", fetcher=getattr(args, "fetcher", None))
        status = cmd_daily_gospel(inner, config, runner=runner, spawn=spawn, sleep=sleep, opener=opener, fetcher=fetcher, today=today)
        data = myprayer.load_day(folder, day)
        if status != 0 or not (myprayer.prayer_done(data) and myprayer.images_done(data, folder, config.gospel_image_count)):
            print("error: the prayer or the pictures could not be completed, so nothing is posted.", file=sys.stderr)
            return 1
    data["sources"] = [list(s) for s in (config.gospel_sources or myprayer.DEFAULT_SOURCES)]  # today's list of links, also for a prayer made yesterday
    # Step 2: the title and description come from the model ONCE and are kept in the day's .json (a second run reuses them).
    if not data.get("post") or getattr(args, "new_title", False):
        print("asking the local model for a title and a description ...", file=out, flush=True)
        data["post"] = mypost.make_meta(config, data, opener or myassistant.urllib.request.urlopen, spawn, sleep)
        myprayer.save_day(folder, day, data)  # kept: the second run today does not ask again
    meta = data["post"]
    for note in meta.get("notes", []):
        print(f"({note})", file=out, flush=True)
    post = folder / f"{day}.md"  # the Hugo content file: 2026-11-24.md
    post.write_text(mypost.build_post(config, data, meta, today), encoding="utf-8")
    print(f"post written: {post}\n  title: {meta['title']}\n  description: {meta['description']}", file=out, flush=True)
    images = [Path(i) for i in data["images"]]
    if getattr(args, "no_upload", False):
        print("(--no-upload: nothing was sent to the server)", file=out, flush=True)
        return 0
    # Step 3: upload. plan_upload builds the list of ssh/scp commands (pure data), upload() runs them. With --dry-run
    # the plan is only PRINTED - the safest way to see what will be sent before sending it.
    plan = mypost.plan_upload(config, images, post)
    dry = getattr(args, "dry_run", False)
    live = _live_runner(runner) if not dry else runner
    try:
        mypost.upload(plan, live, out, dry_run=dry)
    except mypost.PostError as error:
        print(f"error: {error}\nThe post is saved in {post}; run the same command again when the server is reachable.", file=sys.stderr)
        return 1
    if dry:
        print("(--dry-run: nothing was sent)", file=out, flush=True)
    else:
        print(f"✔ on {config.post_remote_host}:\n  - {config.post_remote_images_dir}  ({', '.join(i.name for i in images)})\n  - {config.post_remote_post_dir}{post.name}", file=out, flush=True)
    return 0


def cmd_daily_gospel_facebook(args, config: Config, runner=default_runner, spawn=default_spawn, sleep=time.sleep, opener=None, fetcher=None, today=None, out=None, ask=input, sync_playwright=None, **_) -> int:
    """ml daily-gospel-facebook: today's prayer into a Facebook post. The text goes to the clipboard; the browser pastes it and attaches the
    pictures; YOU press Post. --copy-only: only the clipboard. --dry-run: no browser. --cdp: connect to a Chrome you started on port 9222."""
    from dataclasses import replace
    from datetime import date as _date
    out = out or sys.stderr
    today = today or _date.today()
    day = today.strftime("%Y-%m-%d")
    folder = Path(config.gospel_image_folder).expanduser()
    if getattr(args, "cdp", False):
        config = replace(config, facebook_mode="cdp")
    data = myprayer.load_day(folder, day)
    if not (myprayer.prayer_done(data) and myprayer.images_done(data, folder, config.gospel_image_count)):
        print("today's prayer or pictures are not complete: making them first (ml daily-gospel) ...", file=out, flush=True)
        inner = argparse.Namespace(json=False, plain=False, no_images=False, refresh=False, open=False, no_open=True, count=0, folder="", backend="", fetcher=getattr(args, "fetcher", None))
        status = cmd_daily_gospel(inner, config, runner=runner, spawn=spawn, sleep=sleep, opener=opener, fetcher=fetcher, today=today)
        data = myprayer.load_day(folder, day)
        if status != 0 or not (myprayer.prayer_done(data) and myprayer.images_done(data, folder, config.gospel_image_count)):
            print("error: the prayer or the pictures could not be completed, so nothing is posted.", file=sys.stderr)
            return 1
    data["sources"] = [list(s) for s in (config.gospel_sources or myprayer.DEFAULT_SOURCES)]  # today's list of links, also for a prayer made yesterday
    # The Facebook text is saved next to the prayer (so you can read or paste it by hand), then myfacebook.run does the
    # browser part. It NEVER clicks "Post": that stays your decision (see docs/facebook.md).
    (folder / f"{day}-facebook.txt").write_text(myfacebook.facebook_text(data), encoding="utf-8")
    try:
        return myfacebook.run(config, data, [Path(i) for i in data["images"]], runner, ask=ask, out=out, sync_playwright=sync_playwright,
                              dry_run=getattr(args, "dry_run", False), copy_only=getattr(args, "copy_only", False))
    except myfacebook.FacebookError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1


def cmd_daily_gospel_image(args, config: Config, runner=default_runner, spawn=default_spawn, sleep=time.sleep, opener=None, fetcher=None, gospel=None, **_) -> int:
    """ml daily-gospel-image: the Gospel -> a theme name and an image prompt written by Ollama -> pictures named after the theme."""
    runner = _live_runner(runner)
    try:
        gospel = gospel or mygospel.get_gospel(config, fetcher or mygospel.fetch)
        prompt, paths, theme = mygospel.make_images(config, gospel, runner, opener=opener or myassistant.urllib.request.urlopen, spawn=spawn, sleep=sleep,
                                                    count=getattr(args, "count", 0), folder=getattr(args, "folder", ""), prompt_only=getattr(args, "prompt_only", False),
                                                    backend=getattr(args, "backend", "") or "")
    except (mygospel.GospelError, myimage.ImageError, myassistant.AssistantError, ConfigError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    if args.json and not getattr(args, "images", False):
        print(json.dumps({"title": gospel["title"], "theme": theme, "prompt": prompt, "files": [str(p) for p in paths]}, ensure_ascii=False, indent=2))
    else:
        for path in paths:
            print(path)
        if paths and not getattr(args, "prompt_only", False) and not getattr(args, "no_open", False) and config.create_image_open_after:
            try:
                runner(["open", str(paths[0].parent)])
            except FileNotFoundError:
                pass
    return 0


# ---- maintenance commands: crash, notify-test, report, history, config, doctor ----------------------------------
def cmd_crash(args, config: Config, **_) -> int:
    """ml crash: the newest "Python quit unexpectedly" report of macOS, summarised, plus the end of the app log."""
    folder = Path("~/Library/Logs/DiagnosticReports").expanduser()
    reports = sorted([*folder.glob("Python*.ips"), *folder.glob("Python*.crash"), *folder.glob("python*.ips")], key=lambda p: p.stat().st_mtime, reverse=True)
    if not reports:
        print(f"No Python crash report in {folder}. (Open Console.app > Crash Reports to look for it yourself.)")
    else:
        newest = reports[0]
        print(f"{newest}\n")
        print(summarize_crash(newest.read_text(encoding="utf-8", errors="replace")))
        print(f"\n({len(reports)} report(s) in total; paste the text above in the chat)")
    log = config.autostart_log_dir / "mylauncher.log"
    if log.exists():
        tail = log.read_text(encoding="utf-8", errors="replace").splitlines()[-15:]
        print(f"\n--- end of {log} ---\n" + "\n".join(tail))
    return 0


def cmd_espanso_config(args, config: Config, **_) -> int:
    """ml espanso-config [--install]: keep Espanso from expanding triggers typed INTO the launcher window.

    Espanso (a text expander) watches the keyboard everywhere. If you type `;pclarify` in the launcher's search box,
    Espanso would expand it IN the box instead of letting the launcher list it. The file this command prints/installs
    tells Espanso to ignore the launcher window (matched by its title, `window.title`). See myespanso.py.
    """
    text = myespanso.config_text(config.window_title)
    if args.install:
        ok, message = myespanso.install(config.expander_folder, config.window_title)
        print(message, file=sys.stdout if ok else sys.stderr)
        return 0 if ok else 1
    folder = myespanso.config_dir(config.expander_folder)
    print(f"Put this in {(folder / myespanso.FILE_NAME) if folder else '<espanso folder>/config/' + myespanso.FILE_NAME}\n(or let me do it: ml espanso-config --install)\n")
    print(text)
    return 0


def cmd_notify_test(args, config: Config, runner=default_runner, **_) -> int:
    """Send a test notification and explain what to check when it does not appear.

    A good habit for anything that "silently does nothing": give the user a command that PROVES it works and
    explains the usual causes of failure (here macOS settings the program cannot read for itself).
    """
    name, path = resolve_notifier(config.notify_method)
    print(f"method: {config.notify_method}  ->  using {name}" + (f" ({path})" if path else ""))
    ok, detail = send_notification(runner, config.notify_method, "mylauncher", "Test", "If you can read this, notifications work.")
    print(f"{'sent' if ok else 'FAILED'}: {detail}")
    if name == "osascript":
        print("\nosascript says 'ok' even when macOS hides the notification. If you see nothing:")
        print("  1. brew install terminal-notifier   (then run this again: it is used automatically, and the")
        print("     first time macOS adds 'terminal-notifier' to System Settings > Notifications: allow it)")
        print("  2. check Focus / Do Not Disturb is off (menu bar, Control Centre)")
        print("  3. System Settings > Notifications > Script Editor: Allow, style Banners or Alerts")
    elif name == "terminal-notifier":
        print("\nIf you see nothing: System Settings > Notifications > terminal-notifier: Allow, and Focus off.")
    print("\nThe launcher window also shows its own message after an action (notifications.toast).")
    return 0 if ok else 1


def cmd_report(args, config: Config | None = None, config_error: str = "", runner=default_runner, **_) -> int:
    """Everything worth pasting into a bug report, in one go (nothing secret: no file contents but the logs).

    It runs `cmd_doctor` but CAPTURES its output: `contextlib.redirect_stdout(buffer)` temporarily points `print` at an
    in-memory text buffer (io.StringIO), so we can re-print it under our own heading. A nested function (`section`)
    keeps the headings uniform. Note it takes `config=None` plus `config_error`: it must work even when the
    configuration is BROKEN (that is exactly when you need a report).
    """
    import contextlib
    import io
    import platform
    from importlib import metadata

    def section(title):
        print(f"\n== {title} ==")

    print(f"mylauncher {VERSION} report, {time.strftime('%Y-%m-%d %H:%M:%S')}")
    section("python")
    print(f"version    {sys.version.split()[0]}\nexecutable {sys.executable}\nreal file  {os.path.realpath(sys.executable)}  <- the one Accessibility / Input Monitoring need")
    print(f"platform   {platform.platform()}")
    section("packages (of the python above)")
    for package in ("pynput", "pyobjc-framework-Cocoa", "pyobjc-framework-Quartz", "PyYAML"):
        try:
            print(f"{package:<26}{metadata.version(package)}")
        except metadata.PackageNotFoundError:
            print(f"{package:<26}NOT INSTALLED")
    section("doctor")
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        cmd_doctor(args, config=config, config_error=config_error)
    print(buffer.getvalue().rstrip())
    if config is None:
        return 1
    section(f"launch agent {config.autostart_label}")
    try:
        done = runner(["launchctl", "print", f"gui/{os.getuid()}/{config.autostart_label}"])
        text = (done.stdout or done.stderr or "").strip()
        keep = [ln for ln in text.splitlines() if any(k in ln for k in ("state", "pid", "last exit", "program", "path ="))]
        print("\n".join(keep[:12]) or text[:600] or "(no answer: not installed?  run: mlauto install)")
    except FileNotFoundError:
        print("launchctl not found (is this a Mac?)")
    section(f"logs in {config.autostart_log_dir}")
    logs = sorted(Path(config.autostart_log_dir).glob("*")) if Path(config.autostart_log_dir).is_dir() else []
    if not logs:
        print("(no log files yet)")
    for log in logs:
        print(f"--- {log.name} (last 25 lines)")
        try:
            print("\n".join(log.read_text(encoding="utf-8", errors="replace").splitlines()[-25:]))
        except OSError as exc:
            print(f"cannot read: {exc}")
    return 0


def cmd_history(args, config: Config, **_) -> int:
    """`ml history [--limit N] [--clear] [--json]`: the items you use most (what makes them rise in the list), see myhistory.py."""
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
    """`ml config`: print the settings file in use (which one is decided by find_config_path) - or as JSON with its path."""
    text = config.path.read_text(encoding="utf-8")
    if args.json:
        _print_json({"path": str(config.path), "config": json.loads(text)})
    else:
        print(f"# {config.path}")
        print(text.rstrip())
    return 0


def cmd_doctor(args, config: Config | None = None, config_error: str = "", **_) -> int:
    """Check the installation. ✔ = fine, ! = worth a look, ✘ = broken.

    The pattern: build a list of (symbol, sentence) pairs, one per check, then print them all at the end. Each check is
    an `if`: "is this folder there? is that program installed?". A check never raises; it records a "!" and goes on, so one
    problem does not hide the next. This is the first command to run when "something does not work".
    """
    results = []  # (symbol, text)

    ok = sys.version_info >= (3, 11)
    results.append(("✔" if ok else "✘", f"Python {sys.version.split()[0]} (3.11 or newer needed), running {sys.executable}"))

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
        if config.aerospace_enabled:
            import myaerospace
            program = myaerospace.find_command(config.aerospace_command)
            rules, problem = myaerospace.read_rules(config.aerospace_config)
            results.append(("✔" if program else "!", f"aerospace: {program or config.aerospace_command + ' not found (aerospace.enabled is true, but the program is not here)'}"))
            results.append(("!" if problem else "✔", f"aerospace workspaces: {len(rules)} rule(s) with move-node-to-workspace in {config.aerospace_config}, {len(config.aerospace_workspaces)} of your own" + (f" ({problem})" if problem else "")))
        else:
            results.append(("✔", "aerospace: off (aerospace.enabled is false): apps open without switching workspace"))
        exists = config.quicklinks_path.is_file()
        results.append(
            ("✔" if exists else "!", f"quicklinks: {len(config.quicklinks)} in {config.quicklinks_path}" + ("" if exists else " (file not found: no quicklinks)"))
        )
        for label, path_, entries in (("edit", config.edit_path, config.edit_entries), ("execute", config.execute_path, config.execute_entries),
                                      ("favorites", config.favorites_path, config.favorites_entries)):
            there = path_.is_file()
            results.append(("✔" if there else "!", f"{label}: {len(entries)} entr{'y' if len(entries) == 1 else 'ies'} in {path_}" + ("" if there else " (file not found)")))
        editor = config.edit_editor
        if editor[0] == "open" and len(editor) > 2 and editor[1] == "-a":
            known = any((Path(root) / f"{editor[2]}.app").exists() for root in ("/Applications", "/System/Applications", str(Path.home() / "Applications")))
            results.append(("✔" if known else "!", f"editor: {editor[2]}" + ("" if known else " (application not found in /Applications; edit.editor)")))
        else:
            found = shutil.which(editor[0])
            results.append(("✔" if found else "!", f"editor: {editor[0]}" + (f" ({found})" if found else " (program not found; edit.editor)")))
        missing = [i.title for i in build_edit_items(config) if i.badge == "Missing"]
        if missing:
            results.append(("!", f"edit: {len(missing)} file(s) do not exist: " + ", ".join(missing[:5]) + (" ..." if len(missing) > 5 else "")))
        secrets, problem = read_secrets(config.secret_file)
        if problem:
            results.append(("!", f"secret: {problem} ({config.secret_file}); type {config.secret_edit_word} to create it"))
        else:
            results.append(("✔", f"secret: {len(secrets)} entr{'y' if len(secrets) == 1 else 'ies'} in {config.secret_file}"))
        for warning in file_problems(config.secret_file):
            results.append(("!", f"secret file is {warning}"))
        method, found = resolve_notifier(config.notify_method)
        extra = "" if method != "osascript" else " (unreliable on recent macOS: brew install terminal-notifier, then ml notify-test)"
        results.append(("✔" if method != "osascript" else "!", f"notifications: {method}{extra}"))
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
                ok, message = myespanso.status(config.expander_folder, config.window_title)
                results.append(("✔" if ok else "!", message))
                for note in scan.skipped_notes[:10]:
                    results.append(("!", f"snippet skipped: {note}"))
                if len(scan.skipped_notes) > 10:
                    results.append(("!", f"... and {len(scan.skipped_notes) - 10} more skipped snippets"))
        else:
            results.append(("✔", "snippets: not configured (set expander.folder to your Espanso folder)"))
        policy = "force quit automatically" if config.kill_auto_force else "asks before force quit"
        results.append(("✔", f"kill: '{config.kill_word} <name>' waits {config.kill_grace_seconds} s, then {policy}"))

    # ---- checks that do not need the configuration: the scripts and the macOS programs we call ----
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
    """Describe the whole command line: every sub-command, its words and its options. Nothing runs here.

    `argparse` (standard library) is a small language for this. The vocabulary, in the order you meet it:
      add_parser("name", help=...)    declare a sub-command:   ml name ...
      add_argument("query", nargs="*")  a POSITIONAL word list ("*" = zero or more, "+" = one or more, "?" = optional)
      add_argument("--json", action="store_true")   an OPTION that is a switch: absent = False, present = True
      add_argument("--limit", type=int)             an option with a VALUE, converted to an int
      choices=[...]                  only these values are accepted (others give a clear error and exit code 2)
      aliases=["daily_gospel"]       a second name for the same sub-command (underscores for typing speed)
      help=argparse.SUPPRESS         accepted but hidden from --help (old options kept so old habits still work)
      set_defaults(func=cmd_x)       "when this sub-command is chosen, args.func is cmd_x"  <- the link to Step B
    `parse_args(argv)` then returns a Namespace: args.command, args.query, args.json, args.func ...
    The `help=` texts you write here are what `ml COMMAND --help` prints, so they are real documentation.

    HOW TO ADD A SUB-COMMAND: (1) write cmd_x in Step B, (2) declare it here with set_defaults(func=cmd_x),
    (3) document it in docs/use_cli.md and add an EXAMPLE in mycatalog.py (a test checks both), (4) add a test.
    """
    # Options shared by every sub-command live in a "parent" parser, so we write them once.
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--config", metavar="FILE", help="configuration file (default: conf/myconfiguration.json)")
    common.add_argument("--json", action="store_true", help="write the answer as JSON")

    parser = argparse.ArgumentParser(prog="mylauncher", description="A small, readable launcher (command line engine).")
    parser.add_argument("--version", action="version", version=f"mylauncher {myversion.one_line()}")
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
    emoji_p = sub.add_parser("emoji", parents=[common], help="find an emoji by category or name (my_favorites, smileys, people, ...)")
    emoji_p.add_argument("query", nargs="*", help="a category and/or words: smileys happy | brain | my_favorites")
    emoji_p.add_argument("--copy", action="store_true", help="copy the first emoji of the list to the clipboard")
    emoji_p.add_argument("--limit", type=int, default=50, help="how many to show (0 = all)")
    emoji_p.set_defaults(func=cmd_emoji)
    emoji_add = sub.add_parser("emoji-add", parents=[common], help="add an emoji to my_favorites (the emoji itself or words)")
    emoji_add.add_argument("query", nargs="*", help="🧠  or  brain")
    emoji_add.set_defaults(func=cmd_emoji_add)
    emoji_rm = sub.add_parser("emoji-remove", parents=[common], help="remove an emoji from my_favorites")
    emoji_rm.add_argument("query", nargs="*", help="🧠  or  brain")
    emoji_rm.set_defaults(func=cmd_emoji_remove)
    secret_get = sub.add_parser("secret", parents=[common], help="print a secret (its value, as it is) from the Keychain")
    secret_get.add_argument("name", nargs="?", default=None, help="e.g. google; without it, every name = value")
    secret_get.set_defaults(func=cmd_secret)
    secret_set = sub.add_parser("secret-set", parents=[common], help="save a secret in the macOS Keychain and list it in the secret file")
    secret_set.add_argument("name", help="e.g. google")
    secret_set.add_argument("value", nargs="*", default=None, help="the value (optional, may be several words: without it you are asked; with it, it stays in your shell history)")
    secret_set.add_argument("--notes", default=None, help="private_notes for the entry (\\n = new line)")
    secret_set.set_defaults(func=cmd_secret_set)
    about = sub.add_parser("about", parents=[common], help="which mylauncher is this: version, files, Python, settings")
    about.set_defaults(func=cmd_about)
    timer_p = sub.add_parser("timer", parents=[common], help="a timer: notification and sound at the end (90, 5m, 1h30m, 1:30)")
    timer_p.add_argument("time", nargs="+", help="90, 5m, 1h30m, 1:30   |   list   |   cancel [all|ID]")
    timer_p.add_argument("--dry-run", action="store_true", help="show what would happen")
    timer_p.set_defaults(func=cmd_timer)
    for name, function, text in (("explain", cmd_explain, "explain a concept to a beginner (local model)"), ("deep-study", cmd_deep_study, "deep, intuitive understanding of a concept")):
        ai = sub.add_parser(name, parents=[common], help=text)
        ai.add_argument("topic", nargs="+", help="the concept, for example: quantum entanglement")
        ai.set_defaults(func=function)
    describe = sub.add_parser("describe-image", parents=[common], help="describe an image in detail (no file: the newest screenshot)")
    describe.add_argument("file", nargs="*", help="a png/jpg file")
    describe.add_argument("--refresh", action="store_true", help="ask the model again even if the README of the folder already has a description")
    describe.set_defaults(func=cmd_describe_image)
    find = sub.add_parser("find-image", aliases=["find_image"], parents=[common], help="the images below a folder that are about a topic")
    find.add_argument("folder", help="the folder to search (recursively)")
    find.add_argument("topic", nargs="+", help="for example: religious")
    find.add_argument("--names-only", action="store_true", help="no model: only match the words of the topic against the file and folder names")
    find.add_argument("--refresh", action="store_true", help="forget what the model saw before and look at every picture again")
    find.add_argument("--limit", type=int, default=0, metavar="N", help="look at no more than N new pictures in this run (the next run continues)")
    find.set_defaults(func=cmd_find_image)
    copy_topic = sub.add_parser("copy-image-topic", aliases=["copy_image_topic"], parents=[common], help="copy the images about a topic (see find-image) to a folder")
    copy_topic.add_argument("folder", help="the folder to search (recursively)")
    copy_topic.add_argument("topic", nargs="+", help="for example: religious")
    copy_topic.add_argument("destination", help="where to copy the pictures (created if needed)")
    copy_topic.add_argument("--names-only", action="store_true", help="no model: match only the file and folder names")
    copy_topic.add_argument("--refresh", action="store_true", help="look at every picture again")
    copy_topic.add_argument("--limit", type=int, default=0, metavar="N", help="look at no more than N new pictures in this run")
    copy_topic.add_argument("--dry-run", action="store_true", help="say what would be copied, copy nothing")
    copy_topic.set_defaults(func=cmd_copy_image_topic)
    briefing_p = sub.add_parser("daily-briefing", aliases=["daily_briefing", "briefing"], parents=[common], help="your day from gog (calendar, mail) and qmd (to-do), written by the local model")
    briefing_p.add_argument("--raw", action="store_true", help="no model: print what gog and qmd answered")
    briefing_p.add_argument("--save", action="store_true", help="also save the briefing as DATE-briefing.md (in briefing.save_folder, or here)")
    briefing_p.set_defaults(func=cmd_daily_briefing)
    news_p = sub.add_parser("news", parents=[common], help="the newest headlines of your RSS feeds (conf/feeds.json)")
    news_p.add_argument("words", nargs="*", help="a category (news, games, finance, ...) and/or words that must appear in the headline")
    news_p.add_argument("--refresh", action="store_true", help="fetch the feeds now, whatever the cache says")
    news_p.add_argument("--limit", type=int, default=20, metavar="N", help="at most N headlines (default 20; 0 = all)")
    news_p.add_argument("--days", type=int, default=0, metavar="N", help="only the last N days (default: news.days)")
    news_p.add_argument("--summary", action="store_true", help="also print each summary")
    news_p.add_argument("--list", action="store_true", help="list the categories")
    news_p.set_defaults(func=cmd_news)
    image_p = sub.add_parser("create-image", aliases=["create_image"], parents=[common], help="make a picture from a prompt (Ollama image model or OpenRouter)")
    image_p.add_argument("words", nargs="+", help="the prompt; a last word starting with / or ~ is the folder")
    image_p.add_argument("--folder", default="", help="where to save it (default: create_image.folder)")
    image_p.add_argument("--backend", choices=["mflux", "ollama", "openrouter"], default="", help="override create_image.backend")
    image_p.add_argument("--model", default="", help="override the model of the backend")
    image_p.add_argument("--no-open", action="store_true", help="do not open the picture afterwards")
    image_p.set_defaults(func=cmd_create_image)
    gospel_p = sub.add_parser("daily-gospel", aliases=["daily_gospel"], parents=[common], help="today's Gospel reading (Evangelizo feed): title, date, reading, link")
    gospel_p.add_argument("--plain", action="store_true", help="only the reading of the feed (no model, no prayers)")
    gospel_p.add_argument("--no-images", action="store_true", help="the prayer only (no pictures, which take minutes each)")
    gospel_p.add_argument("--save", action="store_true", help=argparse.SUPPRESS)  # old option: saving is now always done
    gospel_p.add_argument("--images", action="store_true", help=argparse.SUPPRESS)  # old option: pictures are now the default
    gospel_p.add_argument("--count", type=int, default=0, metavar="N", help="how many pictures (default: gospel.image_count)")
    gospel_p.add_argument("--folder", default="", help="where to save the files and pictures (default: gospel.image_folder)")
    gospel_p.add_argument("--backend", choices=["mflux", "ollama", "openrouter"], default="", help="override create_image.backend")
    gospel_p.add_argument("--refresh", action="store_true", help="make today's prayer and pictures again even if the files already exist")
    gospel_p.add_argument("--open", action="store_true", help="open the page (DATE-gospel-prayer.html) in the browser")
    gospel_p.add_argument("--no-open", action="store_true", help="do not open the page when it is finished")
    gospel_p.set_defaults(func=cmd_daily_gospel)
    gpost_p = sub.add_parser("daily-gospel-post", aliases=["daily_gospel_post"], parents=[common], help="today's prayer as a Hugo post: pictures and post copied to your server (ssh/scp)")
    gpost_p.add_argument("--dry-run", action="store_true", help="write the post locally and only PRINT the ssh/scp commands")
    gpost_p.add_argument("--no-upload", action="store_true", help="only write DATE.md (the Hugo post); send nothing")
    gpost_p.add_argument("--draft", action="store_true", help="front matter draft: true (the site does not show it yet)")
    gpost_p.add_argument("--new-title", action="store_true", help="ask the model for another title and description")
    gpost_p.set_defaults(func=cmd_daily_gospel_post)
    gfb_p = sub.add_parser("daily-gospel-facebook", aliases=["daily_gospel_facebook"], parents=[common], help="today's prayer as a Facebook post: clipboard + browser (Playwright); you press Post")
    gfb_p.add_argument("--copy-only", action="store_true", help="only put the text in the clipboard (no browser)")
    gfb_p.add_argument("--dry-run", action="store_true", help="like --copy-only: put the text in the clipboard and print what would happen, open no browser")
    gfb_p.add_argument("--cdp", action="store_true", help="connect to a Chrome that you started with --remote-debugging-port=9222")
    gfb_p.set_defaults(func=cmd_daily_gospel_facebook)
    gimage_p = sub.add_parser("daily-gospel-image", aliases=["daily_gospel_image"], parents=[common], help="an image prompt from today's Gospel (Ollama), then pictures of it (create image)")
    gimage_p.add_argument("--count", type=int, default=0, metavar="N", help="how many pictures (default: gospel.image_count)")
    gimage_p.add_argument("--folder", default="", help="where to save them (default: gospel.image_folder)")
    gimage_p.add_argument("--backend", choices=["mflux", "ollama", "openrouter"], default="", help="override create_image.backend")
    gimage_p.add_argument("--prompt-only", action="store_true", help="only write the prompt (no pictures)")
    gimage_p.add_argument("--no-open", action="store_true", help="do not open the folder afterwards")
    gimage_p.set_defaults(func=cmd_daily_gospel_image)
    crash = sub.add_parser("crash", parents=[common], help="summarise the newest \"Python quit unexpectedly\" report")
    crash.set_defaults(func=cmd_crash)
    secret_notes = sub.add_parser("secret-notes", parents=[common], help="write the private_notes (many lines) of a secret")
    secret_notes.add_argument("name")
    secret_notes.add_argument("text", nargs="?", default=None, help="the notes (\\n = new line); without it, lines are read until Ctrl-D")
    secret_notes.set_defaults(func=cmd_secret_notes)
    espanso = sub.add_parser("espanso-config", parents=[common], help="keep Espanso from expanding triggers typed into the launcher")
    espanso.add_argument("--install", action="store_true", help="write the file into Espanso's config folder")
    espanso.set_defaults(func=cmd_espanso_config)
    sub.add_parser("notify-test", parents=[common], help="send a test notification and explain what to check").set_defaults(func=cmd_notify_test)
    p = sub.add_parser("help", parents=[common], help="aliases, functions, AeroSpace keys, snippets, scripts...")
    p.add_argument("query", nargs="*", help="a topic (aliases, functions, aerospace, espanso, skills, keys, scripts, system, launcher) and words to filter")
    p.add_argument("--refresh", action="store_true", help="ignore the remembered answer of slow topics (aliases, system)")
    p.set_defaults(func=cmd_help)

    sub.add_parser("report", parents=[common], help="everything to paste in a problem report").set_defaults(func=cmd_report)
    sub.add_parser("doctor", parents=[common], help="check the installation").set_defaults(func=cmd_doctor)
    return parser


def main(argv=None, runner=default_runner, ask=input, sleep=time.sleep, spawn=default_spawn, opener=None) -> int:
    """Entry point. `runner`, `ask` and `sleep` can be replaced in tests (no real command, nobody asked, no waiting).

    The whole program in six lines of logic:
      1. parse the command line                    -> args (and args.func = the cmd_* to call)
      2. find and load the configuration           -> config, or a ConfigError turned into text
      3. if the config is broken: say so and exit 2 - EXCEPT for `doctor` and `report`, whose job is to diagnose it
      4. call args.func(args, config=..., runner=..., ...) and return its exit code
    `main()` RETURNS the code instead of exiting, so tests can call it and check the number; only the last two
    lines of the file call sys.exit(main()).
    """
    args = make_parser().parse_args(argv)
    config, config_error = None, ""
    try:
        config = load_config(find_config_path(args.config))
    except ConfigError as exc:
        config_error = str(exc)
    if config is None and args.command not in ("doctor", "report"):  # doctor and report report the problem itself
        return _fail(args, config_error, code=2)
    return args.func(args, config=config, config_error=config_error, runner=runner, ask=ask, sleep=sleep, spawn=spawn, opener=opener)


# `__name__ == "__main__"` is True only when this file is RUN (python3 mylauncher.py ...), not when another file
# imports it (import mylauncher). So tests can import everything here without starting the program.
if __name__ == "__main__":
    sys.exit(main())
