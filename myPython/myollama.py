"""
myollama.py - talk to Ollama: one question to one model, or one question to many models.

Public functions
----------------
    call_ollama(content, prompt="query_expand", ...)   -> str          one model
    call_ollamas(content, prompt="query_expand", ...)  -> dict         every model of MODELS_NEWCONTENT
    available_prompts()                                -> dict         which prompt names exist

Quick examples
--------------
    call_ollama("Raycast Launcher")                              # expand (the default prompt)
    call_ollama("Raycast Launcher", prompt="check_proof")        # proofread instead of expand
    call_ollamas("Raycast Launcher")                             # same question, all models

How the prompts work
--------------------
A "prompt" is the system message that tells the model WHAT to do with your text.
They live in mymessages.py as dictionaries, for example:

    query_expand = {"role": "system", "content": "You are an AI model that ... expands a given text."}
    check_proof  = {"role": "system", "content": "You are a meticulous academic proofreader ..."}

You select one just by its NAME (a string).  To create a new kind of query, add a new
dictionary like the ones above to mymessages.py: no change is needed in this file.

The settings (.env) and the Ollama client come from myconfig.py.
"""

from __future__ import annotations

import os
import re

import ollama  # only used here for its error classes
from colorama import Fore  # colour names understood by util.py
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn, TimeElapsedColumn

import mymessages  # your collection of system prompts
from myconfig import get_client, get_settings  # settings read once from .env
from util import display_alarm_color, display_text_color, text_horizontalRuler

# --------------------------------------------------------------------------- #
# Constants                                                                   #
# --------------------------------------------------------------------------- #

DEFAULT_PROMPT = "query_expand"  # prompt used when you do not choose one
MAX_CONTENT_CHARS = 100_000  # refuse absurdly long input (about 25k tokens)

# One Rich console shared by the whole module (spinner, clearing the screen).
console = Console()


# --------------------------------------------------------------------------- #
# 1. Prompts: choose them by name                                             #
# --------------------------------------------------------------------------- #


def available_prompts() -> dict:
    """Return {name: prompt_dict} for every valid prompt found in mymessages.py.

    A valid prompt is any public variable of mymessages.py that is a dictionary
    containing the keys 'role' and 'content'.
    """
    return {
        name: value
        for name, value in vars(mymessages).items()
        if not name.startswith("_")  # ignore private names
        and isinstance(value, dict)
        and "role" in value
        and "content" in value
    }


def resolve_prompt(prompt) -> dict:
    """Turn a prompt name (or a ready-made dictionary) into a valid prompt dictionary.

    Args:
        prompt: "query_expand" (a name from mymessages.py)  or
                {"role": "system", "content": "..."} (your own one-off prompt).
    Raises:
        ValueError: unknown name, or a dictionary without 'role' and 'content'.
    """
    # Case 1: the caller passed a dictionary directly -> just check its shape.
    if isinstance(prompt, dict):
        if "role" not in prompt or "content" not in prompt:
            raise ValueError("a prompt dictionary must have 'role' and 'content' keys")
        return prompt

    # Case 2: the caller passed a name -> look it up in mymessages.py.
    prompts = available_prompts()
    if isinstance(prompt, str) and prompt in prompts:
        return prompts[prompt]

    # Anything else: explain what the valid choices are (much friendlier than a KeyError).
    raise ValueError(
        f"unknown prompt {prompt!r}. Available prompts: {', '.join(sorted(prompts)) or '(none found)'}"
    )


# --------------------------------------------------------------------------- #
# 2. Small helpers                                                            #
# --------------------------------------------------------------------------- #


def _validate_call(content, model_name, temperature, max_tokens) -> None:
    """Stop early, with a clear message, if an argument makes no sense."""
    if not isinstance(content, str) or not content.strip():
        raise ValueError("content must be a non-empty string")
    if len(content) > MAX_CONTENT_CHARS:
        raise ValueError(
            f"content is too long ({len(content)} characters, maximum {MAX_CONTENT_CHARS})"
        )
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


def _clear_terminal() -> None:
    """Clear the screen, but only when we are really printing to a terminal.

    (If the output is redirected to a file or a pipe, clearing would write
    strange escape codes into it, so we skip it.)
    """
    if console.is_terminal:
        console.clear()


def _ask_model(model_name, messages, temperature, max_tokens) -> str:
    """Send the chat to Ollama and return the answer text.

    Every failure is turned into a RuntimeError with a message that says what to do.
    """
    settings = get_settings()

    # Generation options. num_predict = maximum number of tokens in the answer.
    options = {"temperature": temperature, "num_predict": max_tokens}
    # A bigger context window avoids Ollama silently cutting long input.
    if settings.num_ctx:
        options["num_ctx"] = settings.num_ctx

    try:
        response = get_client().chat(
            model=model_name, messages=messages, options=options
        )
        return response.message.content or ""
    except ollama.ResponseError as exc:
        # The server answered with an error; 404 means the model is not installed.
        hint = (
            f" -> try:  ollama pull {model_name}"
            if getattr(exc, "status_code", None) == 404
            else ""
        )
        raise RuntimeError(f"Ollama rejected the request: {exc}{hint}") from exc
    except ConnectionError as exc:
        raise RuntimeError(
            f"Cannot reach Ollama at {settings.base_url}. Is it running? (try:  ollama serve)"
        ) from exc
    except Exception as exc:  # anything unexpected
        raise RuntimeError(f"Ollama chat failed: {exc}") from exc


# --------------------------------------------------------------------------- #
# 3. Call one model                                                           #
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
        model_name:     which model to use; None = MYMODEL_QUERY from .env.
        role:           role of the `content` message (normally "user").
        temperature:    creativity, 0 (precise) ... 2 (very creative). Default 0.7.
        max_tokens:     maximum length of the answer, in tokens.
        clear_screen:   clear the terminal just before printing the answer.
        strip_thinking: remove the <think>...</think> block of reasoning models.
        show:           print the answer. Use show=False when another module only
                        wants the returned text (the spinner is still displayed,
                        but nothing is cleared or printed afterwards).
        system_prompt:  OLD name of `prompt`, kept so existing calls keep working.

    Returns:
        The model's answer as a string.

    Raises:
        ValueError:   an argument is invalid or the prompt name is unknown.
        RuntimeError: Ollama could not be reached or returned an error.
    """
    # --- Step 1: decide the model and the prompt, and validate everything ------
    model_name = model_name or get_settings().model_query
    _validate_call(content, model_name, temperature, max_tokens)
    # The old keyword `system_prompt=` still works and wins over `prompt=`.
    system_message = resolve_prompt(
        system_prompt if system_prompt is not None else prompt
    )

    # --- Step 2: the conversation we send: [instructions, your text] ----------
    messages = [system_message, {"role": role, "content": content}]

    # --- Step 3: ask the model, showing a spinner with the elapsed time --------
    # The spinner is transient: it disappears by itself when the block ends.
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        TimeElapsedColumn(),
        transient=True,
        console=console,
    ) as progress:
        progress.add_task(
            f"Calling Ollama {model_name}...", total=None
        )  # total=None: endless spinner
        answer = _ask_model(model_name, messages, temperature, max_tokens)

    # --- Step 4: tidy the answer, clean the terminal, print it ----------------
    if strip_thinking:
        answer = _strip_thinking(answer)
    if show:  # silent callers (show=False) skip all printing
        if clear_screen:
            _clear_terminal()
        text_horizontalRuler(f"Response from model {model_name}")
        display_text_color(answer, Fore.GREEN)
    return answer


# --------------------------------------------------------------------------- #
# 4. Call every model of MODELS_NEWCONTENT                                    #
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


def call_ollamas(content: str, prompt="query_expand", models=None) -> dict:
    """Send the same content to several models, one after the other.

    Args:
        content: the text to work on.
        prompt:  prompt name from mymessages.py (default "query_expand").
        models:  list of model names; None = MODELS_NEWCONTENT from .env.

    Returns:
        {model_name: answer} for the models that worked (empty dict if none did).
        A model that fails is reported in red and skipped; the others still run.
    """
    models = (
        list(models) if models is not None else list(get_settings().models_newcontent)
    )

    # Check the input once, before spending time on the first model.
    problem = _problem_with_input(content, models)
    if problem:
        display_alarm_color(problem, Fore.RED)
        return {}

    display_text_color(f"Models for content expansion: {', '.join(models)}", Fore.LIGHTBLACK_EX)

    answers = {}
    for index, model in enumerate(models):
        try:
            answers[model] = call_ollama(
                content=content,
                prompt=prompt,
                model_name=model,
                temperature=0.7,
                max_tokens=20000,
                # Clear the screen only before the FIRST answer; clearing before
                # every model would erase the previous model's answer.
                clear_screen=(index == 0),
            )
        except (RuntimeError, ValueError) as exc:
            display_alarm_color(
                f"{model}: {exc}", Fore.RED
            )  # report it and go on with the next model
    return answers


# --------------------------------------------------------------------------- #
# Run this file directly for a quick test:  python3 myollama.py               #
# --------------------------------------------------------------------------- #

if __name__ == "__main__":
    call_ollamas("Raycast Launcher")
