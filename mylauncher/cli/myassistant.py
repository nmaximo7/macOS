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

KINDS = {  # launcher word -> prompt name in prompts.json
    "explain": "explain",
    "deep_study": "deep_study",
    "describe_image": "describe_image",
}
NEEDS_TOPIC = ("explain", "deep_study")
IMAGE_SUFFIXES = (".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp")


class AssistantError(Exception):
    """Something to tell the user in one line (no traceback)."""


def load_prompts(path) -> dict:
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
    return max(images, key=lambda p: p.stat().st_mtime, default=None)


def read_image(path) -> str:
    path = Path(str(path).strip().strip("'\"")).expanduser()
    if not path.is_file():
        raise AssistantError(f"no image at {path}")
    if path.suffix.lower() not in IMAGE_SUFFIXES:
        raise AssistantError(f"{path.name}: Ollama reads {', '.join(IMAGE_SUFFIXES)} (convert a HEIC with: sips -s format png file.heic --out file.png)")
    return base64.b64encode(path.read_bytes()).decode("ascii")


def payload(config, prompt: str, images=(), model: str = "") -> dict:
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
    """The whole job of `explain` / `deep_study` / `describe_image`. Returns an exit code."""
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


def cache_key(image: Path, model: str) -> str:
    stat = image.stat()
    return f"{image}|{stat.st_size}|{int(stat.st_mtime)}|{model}"


def quiet_generate(config, body, opener, spawn, sleep, err) -> str:
    return generate(config, body, io.StringIO(), opener, spawn, sleep).strip()


def parse_numbers(text: str, limit: int) -> list:
    """The numbers of a reply like "[2, 5, 7]" (or "2, 5 and 7"), only those that exist."""
    m = re.search(r"\[([\d,\s]*)\]", text)
    chosen = re.findall(r"\d+", m.group(1) if m else text)
    return sorted({int(n) for n in chosen if 1 <= int(n) <= limit})


def find_images(config, folder, topic: str, prompts_path=None, names_only=False, refresh=False, limit=0, opener=urllib.request.urlopen,
                spawn=None, sleep=time.sleep, err=None, chunk: int = 30) -> list:
    """The images of `folder` (recursively) that are about `topic`. Returns paths."""
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
