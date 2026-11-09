"""
myollama.py - talk to Ollama: one question to one model, or one question to many models.

SELF-CONTAINED (since v0.19): it needs only the Python standard library and, for the
prompt names, the data file mymessages.py that sits next to it (plain dictionaries, no
imports). It no longer imports util.py, myconfig.py, colorama, rich or the `ollama` package
(it speaks Ollama's HTTP API, POST /api/chat, directly), so you can drop myollama.py +
mymessages.py into any folder, call it from a Raycast script, or run it from the terminal.

Public functions
----------------
    call_ollama(content, prompt="query_expand", ...)   -> str          one model
    call_ollamas(content, prompt="query_expand", ...)  -> dict         every model of MODELS_NEWCONTENT
    available_prompts()                                -> dict         which prompt names exist
    list_models()                                      -> list         models installed in Ollama

Quick examples
--------------
    call_ollama("Raycast Launcher")                              # expand (the default prompt)
    call_ollama("Raycast Launcher", prompt="check_proof")        # proofread instead of expand
    call_ollamas("Raycast Launcher")                             # same question, all models

From the terminal (the text can also come from a pipe):

    python3 myollama.py "Raycast Launcher"
    python3 myollama.py --prompt check_proof --model qwen3:8b "teh quick brown fox"
    cat article.md | python3 myollama.py --prompt expand_article --raw > expanded.md
    python3 myollama.py --list-models
    python3 myollama.py --list-prompts

How the prompts work
--------------------
A "prompt" is the system message that tells the model WHAT to do with your text.
They live in mymessages.py as dictionaries, for example:

    query_expand = {"role": "system", "content": "You are an AI model that ... expands a given text."}
    check_proof  = {"role": "system", "content": "You are a meticulous academic proofreader ..."}

You select one just by its NAME (a string), or pass your own {"role", "content"} dictionary.
To create a new kind of query, add a dictionary to mymessages.py: no change is needed here.

Settings (environment variables, or lines in the `.env` file next to this module; a real
environment variable wins over `.env`). All optional:

    MYMODEL_QUERY       default model                                (qwen3:32b)
    MODELS_NEWCONTENT   models for call_ollamas, spaces or commas    (none)
    BASE_URL            address of the Ollama server                 (http://127.0.0.1:11434)
    OLLAMA_TIMEOUT      seconds to wait for an answer                (600)
    OLLAMA_NUM_CTX      context window in tokens, e.g. 32768         (Ollama's default)

Note: inside the toolkit myconfig.py loads the same .env file *over* the shell variables;
this module lets the shell win, which is what you want from a terminal or Raycast.
"""

from __future__ import annotations

import argparse
import itertools
import json
import os
import re
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

# --------------------------------------------------------------------------- #
# Constants                                                                   #
# --------------------------------------------------------------------------- #

DEFAULT_PROMPT = "query_expand"  # prompt used when you do not choose one
DEFAULT_MODEL = "qwen3:32b"
DEFAULT_HOST = "http://127.0.0.1:11434"
DEFAULT_TIMEOUT = 600.0  # seconds; big local models can be slow
MAX_CONTENT_CHARS = 100_000  # refuse absurdly long input (about 25k tokens)
ENV_FILE = Path(__file__).resolve().parent / ".env"

_GREEN, _RED, _GREY, _RESET = "\033[32m", "\033[31m", "\033[90m", "\033[0m"


# --------------------------------------------------------------------------- #
# 1. Settings (a tiny .env reader: no python-dotenv needed)                   #
# --------------------------------------------------------------------------- #


def _dotenv_values(path: Path = ENV_FILE) -> dict:
    """Read KEY=VALUE lines of a .env file: comments, `export`, quotes, trailing ` # comment`."""
    values = {}
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return values
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        if line.startswith("export "):
            line = line[7:].lstrip()
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip()
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key):
            continue
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        else:
            value = re.split(r"\s+#", value)[0].strip()
        values[key] = value
    return values


@dataclass(frozen=True)
class OllamaConfig:
    """The settings of this module, read from the environment (see the module docstring)."""

    model: str = DEFAULT_MODEL
    models: tuple = ()  # MODELS_NEWCONTENT
    base_url: str = DEFAULT_HOST
    timeout: float = DEFAULT_TIMEOUT
    num_ctx: "int | None" = None


def _normalize_host(raw: str) -> str:
    raw = (raw or "").strip().strip("\"'").rstrip("/")
    if not raw:
        return DEFAULT_HOST
    return raw if "://" in raw else "http://" + raw


def load_config() -> OllamaConfig:
    """Build the configuration from the environment (and the .env next to this file)."""
    env = _dotenv_values()

    def get(name: str) -> str:
        value = os.environ.get(name, "").strip()
        return value or env.get(name, "").strip()

    def number(name: str, default, cast):
        raw = get(name)
        if not raw:
            return default
        try:
            return cast(raw)
        except ValueError:
            raise ValueError(f"{name} must be a number, got {raw!r}") from None

    return OllamaConfig(
        model=get("MYMODEL_QUERY") or DEFAULT_MODEL,
        models=tuple(p for p in get("MODELS_NEWCONTENT").replace(",", " ").split() if p),
        base_url=_normalize_host(get("BASE_URL")),
        timeout=number("OLLAMA_TIMEOUT", DEFAULT_TIMEOUT, float),
        num_ctx=number("OLLAMA_NUM_CTX", None, int),
    )


# --------------------------------------------------------------------------- #
# 2. Prompts: choose them by name                                             #
# --------------------------------------------------------------------------- #


def _messages():
    """Import mymessages.py (the prompt collection) with a clear error when it is missing."""
    here = str(Path(__file__).resolve().parent)
    if here not in sys.path:  # also works when started with `python -I` or from another folder
        sys.path.append(here)
    try:
        import mymessages
    except ImportError:
        raise ValueError(
            "mymessages.py (the file with the prompts) must sit next to myollama.py; "
            "or pass your own {'role': 'system', 'content': '...'} dictionary as the prompt"
        ) from None
    return mymessages


def available_prompts() -> dict:
    """Return {name: prompt_dict} for every valid prompt found in mymessages.py."""
    return _messages().available_prompts()


def resolve_prompt(prompt) -> dict:
    """Turn a prompt name (or a ready-made dictionary) into a valid prompt dictionary.

    Raises ValueError: unknown name, or a dictionary without 'role' and 'content'.
    """
    if isinstance(prompt, dict):  # a dictionary needs no mymessages.py at all
        if "role" not in prompt or "content" not in prompt:
            raise ValueError("a prompt dictionary must have 'role' and 'content' keys")
        return prompt
    return _messages().resolve_prompt(prompt)


# --------------------------------------------------------------------------- #
# 3. Small helpers                                                            #
# --------------------------------------------------------------------------- #


def _validate_call(content, model_name, temperature, max_tokens) -> None:
    """Stop early, with a clear message, if an argument makes no sense."""
    if not isinstance(content, str) or not content.strip():
        raise ValueError("content must be a non-empty string")
    if len(content) > MAX_CONTENT_CHARS:
        raise ValueError(f"content is too long ({len(content)} characters, maximum {MAX_CONTENT_CHARS})")
    if not model_name or not isinstance(model_name, str):
        raise ValueError("model_name must be a non-empty string")
    # Ollama accepts temperatures above 1 (up to about 2), so 0-2 is allowed.
    if not isinstance(temperature, (int, float)) or not 0 <= temperature <= 2:
        raise ValueError("temperature must be a number between 0 and 2")
    if not isinstance(max_tokens, int) or max_tokens <= 0:
        raise ValueError("max_tokens must be a positive integer")


def _strip_thinking(text: str) -> str:
    """Remove the <think>...</think> block that reasoning models (qwen3, deepseek-r1) add."""
    return re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()


def _use_color(stream) -> bool:
    return stream.isatty() and not os.environ.get("NO_COLOR")


class _Spinner:
    """`with _Spinner("Calling Ollama..."):` shows a spinner + elapsed time on stderr.

    Only on a real terminal; in a pipe, a file or Raycast it prints nothing at all.
    """

    def __init__(self, label: str):
        self.label = label
        self.enabled = sys.stderr.isatty()
        self._stop = threading.Event()
        self._thread = None

    def _spin(self):
        started = time.monotonic()
        for frame in itertools.cycle("⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"):
            if self._stop.wait(0.1):
                break
            elapsed = int(time.monotonic() - started)
            sys.stderr.write(f"\r{frame} {self.label} {elapsed // 60}:{elapsed % 60:02d}")
            sys.stderr.flush()

    def __enter__(self):
        if self.enabled:
            self._thread = threading.Thread(target=self._spin, daemon=True)
            self._thread.start()
        return self

    def __exit__(self, *exc):
        if self._thread:
            self._stop.set()
            self._thread.join()
            sys.stderr.write("\r" + " " * (len(self.label) + 14) + "\r")
            sys.stderr.flush()
        return False


def _error_text(exc: HTTPError) -> str:
    """The `error` text of an Ollama error answer ({"error": "model 'x' not found"})."""
    try:
        data = json.loads(exc.read().decode("utf-8", errors="replace"))
        return str(data.get("error") or "") if isinstance(data, dict) else ""
    except (ValueError, OSError):
        return ""


def _post(path: str, payload: dict, cfg: OllamaConfig, model_name: str = ""):
    """POST JSON to Ollama and return the decoded answer. Every failure becomes a RuntimeError."""
    request = Request(
        cfg.base_url + path,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urlopen(request, timeout=cfg.timeout) as reply:
            return json.loads(reply.read().decode("utf-8", errors="replace"))
    except HTTPError as exc:
        detail = _error_text(exc)
        hint = f" -> try:  ollama pull {model_name}" if exc.code == 404 and model_name else ""
        raise RuntimeError(f"Ollama rejected the request (HTTP {exc.code}): {detail or exc.reason}{hint}") from None
    except URLError as exc:
        if isinstance(exc.reason, TimeoutError) or "timed out" in str(exc.reason):
            raise RuntimeError(f"Ollama did not answer within {cfg.timeout:.0f}s (OLLAMA_TIMEOUT)") from None
        raise RuntimeError(f"Cannot reach Ollama at {cfg.base_url}. Is it running? (try:  ollama serve)") from None
    except TimeoutError:
        raise RuntimeError(f"Ollama did not answer within {cfg.timeout:.0f}s (OLLAMA_TIMEOUT)") from None
    except ValueError:
        raise RuntimeError(f"{cfg.base_url} did not answer with JSON: is BASE_URL really Ollama?") from None
    except OSError as exc:
        raise RuntimeError(f"Ollama request failed: {exc}") from None


def _ask_model(model_name, messages, temperature, max_tokens, cfg: "OllamaConfig | None" = None) -> str:
    """Send the chat to Ollama and return the answer text (RuntimeError says what to do)."""
    cfg = cfg or load_config()
    # num_predict = maximum number of tokens in the answer; a bigger context window
    # (num_ctx) stops Ollama silently cutting long input.
    options = {"temperature": temperature, "num_predict": max_tokens}
    if cfg.num_ctx:
        options["num_ctx"] = cfg.num_ctx
    data = _post(
        "/api/chat",
        {"model": model_name, "messages": messages, "stream": False, "options": options},
        cfg,
        model_name,
    )
    if not isinstance(data, dict):
        raise RuntimeError("unexpected answer from Ollama")
    if data.get("error"):
        raise RuntimeError(f"Ollama: {data['error']}")
    message = data.get("message")
    text = (message.get("content") if isinstance(message, dict) else "") or ""
    if data.get("done_reason") == "length":
        print(
            f"note: {model_name} stopped at max_tokens={max_tokens}: the answer is probably cut short",
            file=sys.stderr,
        )
    return text


def list_models(config: "OllamaConfig | None" = None) -> list:
    """Names of the models installed in Ollama (like `ollama list`). RuntimeError if unreachable."""
    cfg = config or load_config()
    request = Request(cfg.base_url + "/api/tags", method="GET")
    try:
        with urlopen(request, timeout=min(cfg.timeout, 15)) as reply:
            data = json.loads(reply.read().decode("utf-8", errors="replace"))
    except (URLError, OSError, ValueError):
        raise RuntimeError(f"Cannot reach Ollama at {cfg.base_url}. Is it running? (try:  ollama serve)") from None
    models = data.get("models", []) if isinstance(data, dict) else []
    return sorted(str(m.get("name")) for m in models if isinstance(m, dict) and m.get("name"))


def _ruler(text: str, stream, color: bool) -> None:
    line = f"──── {text} ────"
    stream.write((f"{_GREEN}{line}{_RESET}" if color else line) + "\n")


# --------------------------------------------------------------------------- #
# 4. Call one model                                                           #
# --------------------------------------------------------------------------- #


def call_ollama(
    content: str,
    prompt="query_expand",
    model_name: str | None = None,
    role: str = "user",
    temperature: float = 0.7,
    max_tokens: int = 10000,
    clear_screen: bool = True,
    strip_thinking: bool = True,
    show: bool = True,
    *,
    system_prompt=None,
) -> str:
    """Send `content` to one Ollama model, show the answer, and return it.

    Args:
        content:        the text you want the model to work on.
        prompt:         WHAT to do with it. A name from mymessages.py such as
                        "query_expand" or "check_proof" (see available_prompts()),
                        or your own {"role": ..., "content": ...} dictionary.
        model_name:     which model to use; None = MYMODEL_QUERY.
        role:           role of the `content` message (normally "user").
        temperature:    creativity, 0 (precise) ... 2 (very creative). Default 0.7.
        max_tokens:     maximum length of the answer, in tokens.
        clear_screen:   clear the terminal just before printing the answer (terminal only).
        strip_thinking: remove the <think>...</think> block of reasoning models.
        show:           print the answer. Use show=False when another module only wants the
                        returned text.
        system_prompt:  OLD name of `prompt`, kept so existing calls keep working.

    Returns:
        The model's answer as a string.

    Raises:
        ValueError:   an argument is invalid or the prompt name is unknown.
        RuntimeError: Ollama could not be reached or returned an error.
    """
    cfg = load_config()
    model_name = model_name or cfg.model
    _validate_call(content, model_name, temperature, max_tokens)
    # The old keyword `system_prompt=` still works and wins over `prompt=`.
    system_message = resolve_prompt(system_prompt if system_prompt is not None else prompt)
    messages = [system_message, {"role": role, "content": content}]

    with _Spinner(f"Calling Ollama {model_name}..."):
        answer = _ask_model(model_name, messages, temperature, max_tokens, cfg)

    if strip_thinking:
        answer = _strip_thinking(answer)
    if show:
        color = _use_color(sys.stdout)
        if clear_screen and sys.stdout.isatty():
            sys.stdout.write("\033[2J\033[H")
        _ruler(f"Response from model {model_name}", sys.stdout, color)
        sys.stdout.write((f"{_GREEN}{answer}{_RESET}" if color else answer) + "\n")
        sys.stdout.flush()
    return answer


# --------------------------------------------------------------------------- #
# 5. Call every model of MODELS_NEWCONTENT                                    #
# --------------------------------------------------------------------------- #


def _problem_with_input(content, models) -> str | None:
    """Return a message describing what is wrong with the input, or None if it is fine."""
    if not content or not isinstance(content, str):
        return "No content provided for expansion (it must be a non-empty string)."
    if len(content) > MAX_CONTENT_CHARS:
        return "Content is too long for expansion. Please provide shorter content."
    if not models:
        return 'No models provided: set MODELS_NEWCONTENT in .env (e.g. MODELS_NEWCONTENT="qwen3:32b gemma3:27b").'
    return None


def _alarm(text: str) -> None:
    color = _use_color(sys.stdout)
    print(f"{_RED}⚠️ {text}{_RESET}" if color else f"⚠️ {text}")


def call_ollamas(content: str, prompt="query_expand", models=None) -> dict:
    """Send the same content to several models, one after the other.

    models: list of model names; None = MODELS_NEWCONTENT.
    Returns {model_name: answer} for the models that worked (empty dict if none did).
    A model that fails is reported in red and skipped; the others still run.
    """
    models = list(models) if models is not None else list(load_config().models)
    problem = _problem_with_input(content, models)
    if problem:
        _alarm(problem)
        return {}

    note = f"Models for content expansion: {', '.join(models)}"
    print(f"{_GREY}{note}{_RESET}" if _use_color(sys.stdout) else note)

    answers = {}
    for index, model in enumerate(models):
        try:
            answers[model] = call_ollama(
                content=content,
                prompt=prompt,
                model_name=model,
                temperature=0.7,
                max_tokens=20000,
                # Clear the screen only before the FIRST answer; clearing before every
                # model would erase the previous model's answer.
                clear_screen=(index == 0),
            )
        except (RuntimeError, ValueError) as exc:
            _alarm(f"{model}: {exc}")  # report it and go on with the next model
    return answers


# --------------------------------------------------------------------------- #
# Command line (terminal, pipes, Raycast)                                      #
# --------------------------------------------------------------------------- #


def cli(argv=None) -> int:
    """python3 myollama.py [TEXT...] [--prompt NAME] [--model M] [--raw] [--all] ..."""
    parser = argparse.ArgumentParser(
        prog="myollama.py",
        description="Send a text to a local Ollama model with one of the prompts of mymessages.py.",
    )
    parser.add_argument("text", nargs="*", help="the text (omit it to read standard input)")
    parser.add_argument("--prompt", default=DEFAULT_PROMPT, help=f"prompt name (default {DEFAULT_PROMPT})")
    parser.add_argument("--model", help="model name (default MYMODEL_QUERY)")
    parser.add_argument("--temperature", type=float, default=0.7, help="0 (precise) ... 2 (creative)")
    parser.add_argument("--max-tokens", type=int, default=10000, help="maximum answer length in tokens")
    parser.add_argument("--keep-thinking", action="store_true", help="keep the <think> block of reasoning models")
    parser.add_argument("--raw", action="store_true", help="print ONLY the answer (no ruler, no colour, no clearing)")
    parser.add_argument("--all", action="store_true", help="ask every model of MODELS_NEWCONTENT")
    parser.add_argument("--list-models", action="store_true", help="list the installed models and exit")
    parser.add_argument("--list-prompts", action="store_true", help="list the prompt names and exit")
    args = parser.parse_args(argv)

    try:
        if args.list_models:
            print("\n".join(list_models()))
            return 0
        if args.list_prompts:
            for name, value in sorted(available_prompts().items()):
                first = value["content"].strip().splitlines()[0] if value["content"].strip() else ""
                print(f"{name:16} {first[:80]}")
            return 0

        text = " ".join(args.text).strip() if args.text else ("" if sys.stdin.isatty() else sys.stdin.read().strip())
        if not text:
            parser.print_usage(sys.stderr)
            print("error: give the text as arguments or on standard input", file=sys.stderr)
            return 2
        if args.all:
            return 0 if call_ollamas(text, prompt=args.prompt) else 1
        answer = call_ollama(
            text,
            prompt=args.prompt,
            model_name=args.model,
            temperature=args.temperature,
            max_tokens=args.max_tokens,
            strip_thinking=not args.keep_thinking,
            show=not args.raw,
        )
        if args.raw:
            sys.stdout.write(answer + "\n")
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except RuntimeError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(cli())
