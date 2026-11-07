"""
openrouter.py - ask a hosted model through OpenRouter (https://openrouter.ai).

The API key is NOT stored in this file, in .env or in your shell history: it lives in
the system keychain (macOS Keychain, Windows Credential Locker, Linux Secret Service),
reached through the `keyring` package.

One-time setup (the prompt hides what you type):

    python3 openrouter.py --set-key

Quick test:

    python3 openrouter.py                         # sends "Hello!" to openrouter/free
    python3 openrouter.py "Explain Stokes' theorem in two sentences"
    python3 openrouter.py "Hello!" --model openrouter/free --timeout 30

Remove the key again:

    python3 openrouter.py --delete-key

From Python:

    from openrouter import ask_openrouter, call_openrouter
    text, model_used = ask_openrouter("Hello!")                   # low level: you give the system text
    text, model_used = call_openrouter("Raycast Launcher")        # like myollama.call_ollama: a PROMPT NAME
    text, model_used = call_openrouter(article, prompt="expand_article")

call_openrouter() uses the same prompt names as myollama.py (they live in mymessages.py:
query_expand, check_proof, expand_article...) and the settings OPENROUTER_MODEL,
OPENROUTER_TIMEOUT and OPENROUTER_MAX_TOKENS of .env.

From the command line, the same prompts:

    python3 openrouter.py "Raycast Launcher" --system query_expand

Where the key is looked for, in this order:
    1. the keychain   (service "justtothepoint-toolkit", user "OPENROUTER_API_KEY")
    2. the environment variable OPENROUTER_API_KEY   (handy on a server or in CI)

macOS may ask you once to allow Python to use the Keychain: choose "Always Allow".
Importing this file does nothing: a request is made only when a function is called.
"""

from __future__ import annotations

import argparse
import getpass
import os
import re
import sys

import requests

# --------------------------------------------------------------------------- #
# Constants                                                                   #
# --------------------------------------------------------------------------- #

API_URL = "https://openrouter.ai/api/v1/chat/completions"
DEFAULT_MODEL = "openrouter/free"  # OpenRouter picks a free model for you
DEFAULT_TIMEOUT = 60.0  # seconds to wait for the answer
MAX_CONTENT_CHARS = 100_000  # refuse absurdly long input (same limit as myollama.py)

# Where the key is saved in the keychain
KEYRING_SERVICE = "justtothepoint-toolkit"
KEYRING_USER = "OPENROUTER_API_KEY"
ENV_VARIABLE = "OPENROUTER_API_KEY"


class OpenRouterError(RuntimeError):
    """Anything that goes wrong here (no key, network, HTTP error, odd answer).

    The message is written for a human and NEVER contains the API key.
    """


# --------------------------------------------------------------------------- #
# The API key                                                                 #
# --------------------------------------------------------------------------- #


def _keyring():
    """Import keyring lazily, so the rest of the project does not need it."""
    try:
        import keyring
    except ImportError:
        return None
    return keyring


def get_api_key() -> str:
    """Return the API key: from the keychain first, then from OPENROUTER_API_KEY.

    Raises OpenRouterError (with the exact commands to fix it) when there is none.
    """
    keyring = _keyring()
    keychain_problem = ""
    if keyring is None:
        keychain_problem = "the 'keyring' package is not installed (pip install keyring)"
    else:
        try:
            key = keyring.get_password(KEYRING_SERVICE, KEYRING_USER)
            if key and key.strip():
                return key.strip()
        except Exception as exc:  # no backend, keychain locked, access denied...
            keychain_problem = f"the keychain could not be read ({type(exc).__name__})"

    key = os.environ.get(ENV_VARIABLE, "").strip()
    if key:
        return key

    message = "No OpenRouter API key found. Save it once with:  python3 openrouter.py --set-key"
    if keychain_problem:
        message += f"\n(note: {keychain_problem})"
    raise OpenRouterError(message)


def set_api_key(key: str | None = None) -> None:
    """Save the API key in the keychain. Without `key`, ask for it (input is hidden)."""
    keyring = _keyring()
    if keyring is None:
        raise OpenRouterError("The 'keyring' package is not installed: pip install keyring")
    if key is None:
        key = getpass.getpass("Paste your OpenRouter API key (hidden): ")
    key = key.strip()
    if not key:
        raise OpenRouterError("Nothing was entered: the keychain was not changed.")
    try:
        keyring.set_password(KEYRING_SERVICE, KEYRING_USER, key)
    except Exception as exc:
        raise OpenRouterError(
            f"Could not save the key in the keychain ({type(exc).__name__}: {exc})"
        ) from None


def delete_api_key() -> bool:
    """Remove the key from the keychain. Returns False when there was none."""
    keyring = _keyring()
    if keyring is None:
        raise OpenRouterError("The 'keyring' package is not installed: pip install keyring")
    try:
        keyring.delete_password(KEYRING_SERVICE, KEYRING_USER)
    except keyring.errors.PasswordDeleteError:
        return False
    except Exception as exc:
        raise OpenRouterError(
            f"Could not delete the key ({type(exc).__name__}: {exc})"
        ) from None
    return True


# --------------------------------------------------------------------------- #
# Asking a model                                                              #
# --------------------------------------------------------------------------- #


def _error_text(response) -> str:
    """Best short explanation of a failed HTTP response (never includes the key)."""
    try:
        detail = response.json().get("error", {})
        message = detail.get("message") if isinstance(detail, dict) else str(detail)
    except (ValueError, AttributeError):
        message = ""
    text = f"OpenRouter answered HTTP {response.status_code}"
    if message:
        text += f": {message}"
    if response.status_code in (401, 403):
        text += "\n(is the API key valid? replace it with:  python3 openrouter.py --set-key)"
    elif response.status_code == 402:
        text += "\n(the account has no credits for this model; try --model openrouter/free)"
    elif response.status_code == 429:
        text += "\n(rate limit: wait a little and try again)"
    return text


def ask_openrouter(
    prompt: str,
    model: str = DEFAULT_MODEL,
    timeout: float = DEFAULT_TIMEOUT,
    system: str | None = None,
    temperature: float | None = None,
    max_tokens: int | None = None,
) -> tuple:
    """Send `prompt` to OpenRouter. Returns (answer text, name of the model that answered).

    prompt:      what you want to ask.
    model:       OpenRouter model id; "openrouter/free" lets OpenRouter pick a free one.
    timeout:     seconds to wait before giving up.
    system:      optional system message (instructions for the model).
    temperature: 0 (precise) ... 2 (creative); None = the model's default.
    max_tokens:  cap on the length of the answer; None = the model's default.

    Raises OpenRouterError for every expected problem.
    """
    if not prompt or not prompt.strip():
        raise OpenRouterError("The prompt is empty.")

    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})

    body = {"model": model, "messages": messages}
    if temperature is not None:
        body["temperature"] = temperature
    if max_tokens is not None:
        body["max_tokens"] = max_tokens

    try:
        response = requests.post(
            API_URL,
            headers={
                "Authorization": f"Bearer {get_api_key()}",
                "Content-Type": "application/json",
            },
            json=body,
            timeout=timeout,
        )
    except requests.Timeout:
        raise OpenRouterError(f"OpenRouter did not answer within {timeout:g} seconds.") from None
    except requests.ConnectionError:
        raise OpenRouterError("Could not reach openrouter.ai (is the internet working?).") from None
    except requests.RequestException as exc:
        raise OpenRouterError(f"Request failed: {type(exc).__name__}") from None

    if not response.ok:
        raise OpenRouterError(_error_text(response))

    try:
        data = response.json()
        return data["choices"][0]["message"]["content"], data.get("model", model)
    except (ValueError, KeyError, IndexError, TypeError):
        raise OpenRouterError(
            "OpenRouter sent an answer in an unexpected format:\n" + response.text[:300]
        ) from None


# --------------------------------------------------------------------------- #
# The same idea as myollama.call_ollama: choose WHAT to do by prompt name     #
# --------------------------------------------------------------------------- #


def _strip_thinking(text: str) -> str:
    """Remove the <think>...</think> block that some reasoning models add."""
    return re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()


def call_openrouter(
    content: str,
    prompt="query_expand",
    model: str | None = None,
    timeout: float | None = None,
    temperature: float | None = 0.7,
    max_tokens: int | None = None,
    show: bool = False,
    strip_thinking: bool = True,
) -> tuple:
    """Send `content` to OpenRouter with a named system prompt. Returns (answer, model used).

    content:        the text you want the model to work on (e.g. an article).
    prompt:         WHAT to do with it: a name from mymessages.py ("query_expand",
                    "check_proof", "expand_article"...) or your own
                    {"role": "system", "content": "..."} dictionary.
    model:          None = OPENROUTER_MODEL of .env ("openrouter/free" if not set).
    timeout:        None = OPENROUTER_TIMEOUT of .env (300 seconds if not set).
    temperature:    0 ... 2, default 0.7 (the same as call_ollama).
    max_tokens:     None = OPENROUTER_MAX_TOKENS of .env, or the model's own default.
    show:           print the answer (False: only return it).
    strip_thinking: remove a <think>...</think> block.

    Raises ValueError for a bad argument or an unknown prompt name, and OpenRouterError
    for everything that goes wrong with the request (no key, network, HTTP error...).
    """
    # Imported here so that `python3 openrouter.py "Hello!"` keeps working with only
    # `requests` and `keyring` installed.
    import mymessages
    from myconfig import get_settings

    if not isinstance(content, str) or not content.strip():
        raise ValueError("content must be a non-empty string")
    if len(content) > MAX_CONTENT_CHARS:
        raise ValueError(
            f"content is too long ({len(content)} characters, maximum {MAX_CONTENT_CHARS})"
        )
    if temperature is not None and not 0 <= temperature <= 2:
        raise ValueError("temperature must be a number between 0 and 2")

    settings = get_settings()
    system_message = mymessages.resolve_prompt(prompt)
    text, model_used = ask_openrouter(
        content,
        model=model or settings.openrouter_model,
        timeout=timeout or settings.openrouter_timeout,
        system=system_message["content"],
        temperature=temperature,
        max_tokens=max_tokens or settings.openrouter_max_tokens,
    )
    if strip_thinking:
        text = _strip_thinking(text)
    if show:
        print(f"--- Response from model {model_used} ---")
        print(text)
    return text, model_used


# --------------------------------------------------------------------------- #
# Command line                                                                #
# --------------------------------------------------------------------------- #


def cli(argv=None) -> int:
    """Command-line entry point. Returns 0 on success, 1 on any OpenRouterError."""
    parser = argparse.ArgumentParser(
        prog="openrouter.py", description="Ask a model through OpenRouter."
    )
    parser.add_argument("prompt", nargs="?", default="Hello!", help='default: "Hello!"')
    parser.add_argument("--model", default=DEFAULT_MODEL, help=f"default: {DEFAULT_MODEL}")
    parser.add_argument(
        "--timeout", type=float, default=DEFAULT_TIMEOUT, help="seconds (default: 60)"
    )
    parser.add_argument(
        "--system",
        metavar="NAME",
        help="use a system prompt of mymessages.py, e.g. query_expand, check_proof, expand_article",
    )
    parser.add_argument(
        "--set-key", action="store_true", help="save your API key in the keychain and exit"
    )
    parser.add_argument(
        "--delete-key", action="store_true", help="remove your API key from the keychain and exit"
    )
    args = parser.parse_args(argv)

    try:
        if args.set_key:
            set_api_key()
            print("Saved to the keychain.")
        elif args.delete_key:
            print("Removed from the keychain." if delete_api_key() else "No key was saved.")
        elif args.system:
            text, model_used = call_openrouter(
                args.prompt, prompt=args.system, model=args.model, timeout=args.timeout
            )
            print(text)
            print("Model used:", model_used)
        else:
            text, model_used = ask_openrouter(args.prompt, args.model, args.timeout)
            print(text)  # answer from the selected model
            print("Model used:", model_used)  # which model OpenRouter chose
    except (OpenRouterError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(cli())
