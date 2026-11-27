"""
myassistant.py - `explain`, `deep_study` and `describe_image`: ask a local model (Ollama) and read the answer as it is written.

How it works, in four small steps:
  1. The PROMPTS are in conf/prompts.json (not here): you improve them by editing that file, nothing else changes.
     A prompt may be one text or a list of lines (easier to read in the file). {topic} is replaced by what you typed.
  2. The model, the address of Ollama and the options are in the `ollama` section of conf/myconfiguration.json.
  3. We talk to Ollama's local HTTP interface (http://127.0.0.1:11434/api/generate) with the standard library
     only: no extra package, and the image goes as base64 inside the request (no trouble with spaces in paths).
  4. The answer is printed while it arrives. If Ollama is not running we start `ollama serve` and wait a little.

From the launcher, `explain photosynthesis` opens a terminal window that runs `ml explain photosynthesis`.

GUIDED TOUR (for someone who is just starting to program) ---------------------------------------------------------------
The file has three layers. Read them in this order:

  A. TALKING TO THE MODEL  (the foundation)
       load_prompts -> build_prompt     the TEXT we send (from conf/prompts.json)
       payload                           the JSON BODY of the request (model, prompt, images, options)
       stream                            POST it to Ollama and print the answer AS IT ARRIVES
       ensure_server / generate          if Ollama is not running: start it, wait, try once more
       ask                               the whole job of explain / deep_study / describe_image, returning an exit code
  B. FINDING PICTURES BY TOPIC  (find_images and its helpers: scan_images, words_of, match_names, cache, parse_numbers)
  C. COPYING WHAT WAS FOUND   (unique_target, copy_images)

WHAT IS AN "API REQUEST"? Ollama is a program that runs on your Mac and listens on a local address (127.0.0.1:11434; 127.0.0.1 always means "this
computer"). We send it a small JSON document with an HTTP POST (like a web form) and it answers with JSON. With "stream": true it does NOT wait to
finish: it sends many small JSON lines, one per few words ("chunks"), the last one with "done": true. `stream()` reads them one by one and prints each
immediately: that is why you see the answer being typed. One chunk looks like   {"response": " the", "done": false}.
We use only the standard library (urllib), so there is nothing to install. An IMAGE travels as base64: the bytes of the file turned into plain text
letters, so it fits inside JSON (and a path with spaces cannot cause trouble).
Try it (a real Mac with Ollama):   ml explain "entropy"        ml describe-image ~/Pictures/some.png
"""

from __future__ import annotations

import base64
import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

from mytypes import ConfigError

# A dict again used as a lookup table: the word you type -> the name of the prompt in prompts.json.
KINDS = {  # launcher word -> prompt name in prompts.json
    "explain": "explain",
    "deep_study": "deep_study",
    "describe_image": "describe_image",
}
NEEDS_TOPIC = ("explain", "deep_study")
IMAGE_SUFFIXES = (".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp")


class AssistantError(Exception):
    """Something to tell the user in one line (no traceback).

    Our own kind of error, like ConfigError (chapter 7). Everything that can go wrong in an EXPECTED way (Ollama not installed, model missing, no such image)
    raises this with a sentence; `ask()` catches it at the top and prints it. Unexpected bugs still show a traceback: that is deliberate, they should be seen.
    """


def load_prompts(path) -> dict:
    """Read conf/prompts.json -> {name: text}. A prompt may be a text or a LIST OF LINES (joined with newlines: easier to read in the file).

    Keys starting with "_" (like "_help") are notes for yourself and are skipped.
    """
    path = Path(path)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ConfigError(f"cannot read the prompts file {path}: {exc}") from None
    except json.JSONDecodeError as exc:
        raise ConfigError(f"{path} is not valid JSON (line {exc.lineno}, column {exc.colno}): {exc.msg}") from None
    if not isinstance(data, dict):
        raise ConfigError(f'{path} must be an object: {{"explain": "...", "deep_study": "...", "describe_image": "..."}}')
    prompts = {}
    for name, value in data.items():
        if name.startswith("_"):
            continue  # "_help": notes for yourself
        if isinstance(value, list) and all(isinstance(line, str) for line in value):
            value = "\n".join(value)
        if not isinstance(value, str) or not value.strip():
            raise ConfigError(f"{path}: {name!r} must be a text (or a list of lines)")
        prompts[name] = value.strip()
    return prompts


def build_prompt(prompts: dict, kind: str, topic: str = "") -> str:
    if kind not in prompts:
        raise AssistantError(f"the prompts file has no {kind!r} entry")
    # A prompt is a TEMPLATE with a hole: "Explain {topic} to a beginner..." and .replace("{topic}", "entropy") fills the hole.
    prompt = prompts[kind]
    if kind in NEEDS_TOPIC:
        if "{topic}" not in prompt:
            raise AssistantError(f'the {kind!r} prompt must contain {{topic}} where the concept goes')
        prompt = prompt.replace("{topic}", topic.strip())
    return prompt


def latest_image(folder, suffixes=IMAGE_SUFFIXES):
    """The newest image of a folder (the screenshot you just took), or None."""
    try:
        images = [p for p in Path(folder).expanduser().iterdir() if p.suffix.lower() in suffixes and not p.name.startswith(".")]
    except OSError:
        return None
    # max(..., key=...) picks the item with the biggest key: here the most recent modification time. `default=None` avoids an error on an empty list.
    return max(images, key=lambda p: p.stat().st_mtime, default=None)


def read_image(path) -> str:
    path = Path(str(path).strip().strip("'\"")).expanduser()
    if not path.is_file():
        raise AssistantError(f"no image at {path}")
    if path.suffix.lower() not in IMAGE_SUFFIXES:
        raise AssistantError(f"{path.name}: Ollama reads {', '.join(IMAGE_SUFFIXES)} (convert a HEIC with: sips -s format png file.heic --out file.png)")
    return base64.b64encode(path.read_bytes()).decode("ascii")


def payload(config, prompt: str, images=(), model: str = "") -> dict:
    """The JSON body for /api/generate. Optional parts are added only when set, so we never send a field Ollama may not know.

    `think` switches the model's "reasoning" mode on/off (None = leave it to the model); `keep_alive` says how long Ollama keeps the model in memory.
    """
    data = {"model": model or config.ollama_model, "prompt": prompt, "stream": True}
    if config.ollama_think is not None:
        data["think"] = config.ollama_think
    if images:
        data["images"] = list(images)
    if config.ollama_keep_alive:
        data["keep_alive"] = config.ollama_keep_alive
    return data


def stream(config, body: dict, out, opener=urllib.request.urlopen) -> str:
    """POST the request and print the answer while it arrives. Returns the whole answer."""
    request = urllib.request.Request(
        config.ollama_host.rstrip("/") + "/api/generate", data=json.dumps(body).encode("utf-8"), headers={"Content-Type": "application/json"}
    )
    # `with ... as response` guarantees the connection is CLOSED when the block ends, even after an error. Iterating over `response` gives it line by line
    # (one JSON document per line), WHILE the model is still writing. `out.write(text); out.flush()` shows each piece at once (flush = "do not wait").
    answer = []
    try:
        with opener(request, timeout=config.ollama_timeout) as response:
            for raw in response:
                if not raw.strip():
                    continue
                chunk = json.loads(raw)
                if chunk.get("error"):
                    raise AssistantError(f"Ollama says: {chunk['error']}")
                text = chunk.get("response", "")
                if text:
                    answer.append(text)
                    out.write(text)
                    out.flush()
                if chunk.get("done"):
                    break
    except urllib.error.HTTPError as exc:
        detail = ""
        try:
            detail = json.loads(exc.read()).get("error", "")
        except (ValueError, OSError, AttributeError):
            pass
        if exc.code == 404:
            raise AssistantError(f"the model {body['model']!r} is not installed: run   ollama pull {body['model']}   ({detail})") from None
        raise AssistantError(f"Ollama answered {exc.code}: {detail}") from None
    return "".join(answer)


# is_down tells "Ollama is simply not running" (connection refused: start it) from every other network problem (report it). A URLError WRAPS the real
# reason in .reason, hence the first line.
def is_down(exc: BaseException) -> bool:
    reason = exc.reason if isinstance(exc, urllib.error.URLError) else exc
    return isinstance(reason, (ConnectionError, ConnectionRefusedError)) or isinstance(exc, ConnectionError)


def ensure_server(config, spawn, sleep, opener=urllib.request.urlopen, out=None) -> None:
    """Ollama is not answering: start `ollama serve` in the background and wait up to ~20 seconds."""
    out = out or sys.stdout
    if not config.ollama_autostart:
        raise AssistantError(f"Ollama is not running at {config.ollama_host}: start the Ollama app, or run  ollama serve")
    print(f"Ollama is not running: starting {config.ollama_command} serve ...", file=out, flush=True)
    try:
        spawn([config.ollama_command, "serve"], Path(config.execute_log_dir) / "ollama-serve.log")
    except OSError as exc:
        raise AssistantError(f"could not start {config.ollama_command!r} ({exc}): install it with  brew install ollama") from None
    # A polling loop: ask "are you up?" once per second, at most 20 times. `for _ in range(20)` = repeat 20 times, ignoring the counter (the name _ means
    # "I do not use this"). /api/tags is a cheap question every Ollama answers. `sleep` is injected, so the tests do not really wait 20 seconds.
    for _ in range(20):
        sleep(1)
        try:
            with opener(config.ollama_host.rstrip("/") + "/api/tags", timeout=2):
                return
        except (urllib.error.URLError, OSError):
            continue
    raise AssistantError(f"Ollama did not start in 20 seconds (log: {Path(config.execute_log_dir) / 'ollama-serve.log'})")


def generate(config, body: dict, out, opener=urllib.request.urlopen, spawn=None, sleep=time.sleep) -> str:
    """stream(), and if Ollama is not running: start it and try once more."""
    try:
        return stream(config, body, out, opener)
    except (urllib.error.URLError, ConnectionError) as exc:
        if not is_down(exc):
            raise AssistantError(f"cannot talk to Ollama at {config.ollama_host}: {exc}") from None
        ensure_server(config, spawn, sleep, opener, out)
        return stream(config, body, out, opener)


def ask(config, kind: str, text: str, prompts_path=None, out=None, opener=urllib.request.urlopen, spawn=None, sleep=time.sleep, refresh: bool = False) -> int:
    """The whole job of `explain` / `deep_study` / `describe_image`. Returns an exit code.

    Flow: load the prompts -> (for an image: read it, and look in the picture folder's README: if this picture was already described by the same model and has
    not changed, print THAT and stop: the model takes minutes) -> build the body -> stream the answer -> (for an image: save the description in the README).
    The two `except` at the end turn expected problems into one line on stderr and exit code 1.
    """
    out = out or sys.stdout
    try:
        prompts = load_prompts(prompts_path or config.ollama_prompts)
        images, model = (), ""
        if kind == "describe_image":
            images, model = (read_image(text),), config.ollama_vision_model
            prompt = build_prompt(prompts, kind)
            file = Path(text.strip().strip("'\"")).expanduser().absolute()
            shown = file.name
            updated, readme_model, entries = (None, "", {}) if refresh else myreadme.read(file.parent, config.ollama_readme)
            if readme_model == (config.ollama_vision_model or config.ollama_model) and myreadme.is_fresh(file, file.name, updated, entries):
                print(f"🖼️ {shown}   (from {config.ollama_readme} of its folder, written {time.strftime(myreadme.STAMP, time.localtime(updated))}; --refresh asks the model again)\n\n{entries[file.name]}", file=out, flush=True)
                return 0
        else:
            if not text.strip():
                raise AssistantError("say what to explain, for example:  ml explain 'quantum entanglement'")
            prompt, shown = build_prompt(prompts, kind, text), text.strip()
        body = payload(config, prompt, images, model)
        print(f"🧠 {kind}: {shown}   (model {body['model']})\n", file=out, flush=True)
        started = time.time()
        answer = generate(config, body, out, opener, spawn, sleep)
        print(f"\n\n— {time.time() - started:.0f} s", file=out, flush=True)
        if kind == "describe_image" and answer and answer.strip():  # remember it in the README of the picture's folder
            _updated, _m, entries = myreadme.read(file.parent, config.ollama_readme)
            entries[file.name] = myreadme.one_line(answer)
            kept = {k: v for k, v in entries.items() if (file.parent / k).exists()}
            path = myreadme.write(file.parent, config.ollama_readme, kept, config.ollama_vision_model or config.ollama_model, time.time())
            print(f"(saved in {path})", file=out, flush=True)
        return 0
    except (AssistantError, ConfigError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except TimeoutError:
        print(f"error: Ollama did not answer in {config.ollama_timeout} s (ollama.timeout_seconds)", file=sys.stderr)
        return 1


# ---------------------------------------------------------------------------------------------------------------
# find_image: which pictures of a folder are about a topic?
#   1. every picture gets a short description by the vision model, ONCE (kept in a cache file: the second search
#      over the same folder is quick, and a different topic does not need to look at the pictures again);
#   2. the model reads the numbered descriptions (with the file names) and says which ones fit the topic.
# ---------------------------------------------------------------------------------------------------------------

# (These imports sit here, next to the code that uses them, because part B was added later. Python allows imports anywhere; the usual style is the top of the file.)
import contextlib
import io
import myreadme
import os
import re


def scan_images(folder) -> list:
    """Every image below `folder` (hidden folders and files skipped), sorted."""
    root = Path(folder).expanduser()
    if not root.is_dir():
        raise AssistantError(f"{root} is not a folder")
    found = []
    for here, dirs, files in os.walk(root):
        dirs[:] = sorted(d for d in dirs if not d.startswith("."))
        found += [Path(here) / f for f in sorted(files) if not f.startswith(".") and f.lower().endswith(IMAGE_SUFFIXES)]
    return found


# words_of splits names into words, so "jesusChrist_01.jpg" can be found by "jesus christ". Two regular-expression steps:
#   re.sub(r"([a-z])([A-Z])", r"\1 \2", text)   put a space between a lowercase letter and a capital: "jesusChrist" -> "jesus Christ"
#   re.split(r"[^A-Za-z0-9]+", ...)               cut at every run of characters that are NOT letters or digits (underscores, dots, dashes...)
# The \1 and \2 in the replacement mean "group 1" and "group 2" of the match (the two letters, kept).
def words_of(text: str) -> list:
    """"jesusChrist_01.jpg" -> ["jesus", "christ", "01", "jpg"]: for the quick match on names."""
    spaced = re.sub(r"([a-z])([A-Z])", r"\1 \2", text)
    return [w for w in re.split(r"[^A-Za-z0-9]+", spaced.lower()) if w]


def match_names(root, images: list, topic: str) -> list:
    """No model: the images whose path (folders included) contains every word of the topic."""
    wanted = [w for w in words_of(topic) if len(w) > 1] or words_of(topic)
    result = []
    for image in images:
        haystack = " ".join(words_of(str(image.relative_to(root)))) if image.is_relative_to(root) else " ".join(words_of(str(image)))
        if all(w in haystack for w in wanted):
            result.append(image)
    return result


def load_cache(path) -> dict:
    try:
        data = json.loads(Path(path).expanduser().read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def save_cache(path, cache: dict) -> None:
    path = Path(path).expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(".tmp")
    temp.write_text(json.dumps(cache, ensure_ascii=False, indent=0), encoding="utf-8")
    temp.replace(path)  # never a half-written cache, even if you press Ctrl-C


# The key of a cache entry contains the path, the SIZE, the modification TIME and the MODEL: if you edit the picture or switch model, the key changes and the old
# description is simply never found again. A cache that invalidates itself needs no "delete the cache" button.
def cache_key(image: Path, model: str) -> str:
    stat = image.stat()
    return f"{image}|{stat.st_size}|{int(stat.st_mtime)}|{model}"


def quiet_generate(config, body, opener, spawn, sleep, err) -> str:
    return generate(config, body, io.StringIO(), opener, spawn, sleep).strip()


def parse_numbers(text: str, limit: int) -> list:
    """The numbers of a reply like "[2, 5, 7]" (or "2, 5 and 7"), only those that exist.

    Models do not always answer in exactly the format you asked, so we are tolerant: look for [..] first, else any digits in the reply; keep only numbers
    from 1 to `limit` (a model may invent "42"); a set removes duplicates and sorted() orders them. Rule: NEVER trust what a model returns - validate it.
    """
    m = re.search(r"\[([\d,\s]*)\]", text)
    chosen = re.findall(r"\d+", m.group(1) if m else text)
    return sorted({int(n) for n in chosen if 1 <= int(n) <= limit})


def find_images(config, folder, topic: str, prompts_path=None, names_only=False, refresh=False, limit=0, opener=urllib.request.urlopen,
                spawn=None, sleep=time.sleep, err=None, chunk: int = 30) -> list:
    """The images of `folder` (recursively) that are about `topic`. Returns paths.

    Three phases (follow the comments in the code):
      1. LIST the pictures; with names_only=True stop here and match on file names (no model, instant).
      2. DESCRIBE the ones not yet described (the slow part; each description is saved in the folder's README, a checkpoint every 5 pictures and on Ctrl-C).
         `except BaseException: save(False); raise` saves what was learned and then re-raises the SAME error: cleanup without hiding the problem.
      3. ASK the model which numbered descriptions fit the topic, `chunk` (30) at a time, because a very long list would not fit the model's memory.
    """
    err = err or sys.stderr
    if not topic.strip():
        raise AssistantError("say the topic, for example:  ml find-image ~/Pictures religious")
    root = Path(folder).expanduser().absolute()
    images = scan_images(root)
    if not images:
        return []
    if names_only:
        return match_names(root, images, topic)
    prompts = load_prompts(prompts_path or config.ollama_prompts)
    for needed in ("caption_image", "find_image"):
        if needed not in prompts:
            raise AssistantError(f"the prompts file has no {needed!r} entry (see conf/prompts.json of this version)")
    model = config.ollama_vision_model or config.ollama_model
    readme = config.ollama_readme
    updated, readme_model, entries = (None, "", {}) if refresh else myreadme.read(root, readme)
    if readme_model and readme_model != model:  # another model wrote them: look again
        updated, entries = None, {}
    names = {i: str(i.relative_to(root)) for i in images}
    todo = [i for i in images if not myreadme.is_fresh(i, names[i], updated, entries)]
    if limit:
        todo = todo[:limit]
    complete = not limit
    print(f"{len(images)} image(s) in {root}: {len(images) - len([i for i in images if not myreadme.is_fresh(i, names[i], updated, entries)])} already in {readme}, {len(todo)} to look at (model {model})", file=err, flush=True)

    def save(finished: bool) -> None:
        # the date moves on only after a COMPLETE run: an interrupted run must not hide a picture that changed
        stamp = time.time() if (finished or updated is None) else updated
        myreadme.write(root, readme, {names[i]: entries[names[i]] for i in images if names[i] in entries}, model, stamp)

    try:
        for number, image in enumerate(todo, 1):
            print(f"  [{number}/{len(todo)}] {names[image]}", file=err, flush=True)
            try:
                body = payload(config, prompts["caption_image"], (read_image(image),), config.ollama_vision_model)
                entries[names[image]] = myreadme.one_line(quiet_generate(config, body, opener, spawn, sleep, err))
            except AssistantError as exc:
                if "no image" in str(exc) or "Ollama reads" in str(exc):
                    print(f"    skipped: {exc}", file=err, flush=True)
                    continue
                raise
            if number % 5 == 0:
                save(False)
        save(complete)
    except BaseException:
        save(False)  # Ctrl-C or an error: what was learned is kept
        raise
    known = [(i, entries[names[i]]) for i in images if names[i] in entries]
    chosen = []
    for start in range(0, len(known), chunk):
        part = known[start : start + chunk]
        listing = "\n".join(f"{n}. {i.relative_to(root)} :: {' '.join(c.split())[:600]}" for n, (i, c) in enumerate(part, 1))
        prompt = prompts["find_image"].replace("{topic}", topic.strip()).replace("{list}", listing)
        reply = quiet_generate(config, payload(config, prompt), opener, spawn, sleep, err)
        chosen += [part[n - 1][0] for n in parse_numbers(reply, len(part))]
    return chosen


# unique_target: never overwrite. If a file with that name exists: byte-identical (filecmp.cmp with shallow=False compares the CONTENT) -> "same", do nothing;
# a different file -> try name_2.ext, name_3.ext... until a free name. A `while` loop with a counter.
def unique_target(dest: Path, name: str, source: Path):
    """(path, status): the same file already there -> "same"; another file with that name -> name_2.ext; else the name."""
    import filecmp

    target = dest / name
    counter = 2
    while target.exists():
        if filecmp.cmp(source, target, shallow=False):
            return target, "same"
        target = dest / f"{Path(name).stem}_{counter}{Path(name).suffix}"
        counter += 1
    return target, "copied"


def copy_images(config, folder, topic: str, destination, dry_run=False, **find_kwargs) -> list:
    """find_images(), then copy what was found into `destination`. Returns [(source, target, "copied"|"same"|"would")]."""
    import shutil

    found = find_images(config, folder, topic, **find_kwargs)
    dest = Path(destination).expanduser().absolute()
    if found and dest.exists() and not dest.is_dir():
        raise AssistantError(f"{dest} exists and is not a folder")
    result = []
    taken = set()
    for source in found:
        target, status = unique_target(dest, source.name, source) if dest.is_dir() else (dest / source.name, "copied")
        while target in taken:  # two pictures of different folders with the same name, not yet written (dry run)
            target = target.with_name(f"{target.stem}_x{target.suffix}")
        taken.add(target)
        if status == "copied" and dry_run:
            status = "would"
        elif status == "copied":
            dest.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
        result.append((source, target, status))
    return result
