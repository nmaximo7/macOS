"""
mymessages.py - the system prompts ("what should the model do with my text?").

Each prompt is a dictionary {"role": ..., "content": ...}. myollama.py finds them by
themselves (available_prompts()), and you choose one just by its NAME:

    call_ollama(text)                            # "query_expand" (the default)
    call_ollama(text, prompt="check_proof")      # proofread instead of expand

To add a new kind of query, add another dictionary with "role" and "content" below:
no change is needed anywhere else. Keep only real SYSTEM prompts here: every public
dictionary with "role" and "content" is offered as a selectable prompt.

Since v0.18 the lookup itself (available_prompts / resolve_prompt) lives at the bottom of
THIS file, so that every provider shares it: myollama.py (local Ollama) and
openrouter.py (hosted models). Both accept the same prompt names.

Prompts at a glance
-------------------
    query_expand    the original, general "clarify and expand this text" (default of call_ollama)
    check_proof     proofread and report problems, without rewriting
    expand_article  a complete, copy-and-paste-ready rewrite of a Hugo article (content_expand.py)
"""

import sys

# Ollama query for expanding content (the default prompt of myollama.py)
query_expand = {
    "role": "system",
    "content": (
        "You are an AI model that clarifies, proofreads, explains, and expands a given text.\n"
        "The expanded text should be more detailed, comprehensive, easy-to-read with many examples and clear headings.\n"
    ),
}

# Ollama query for proofreading content
check_proof = {
    "role": "system",
    "content": (
        "You are a meticulous academic proofreader and text validator.\n"
        "Analyze ONLY the substantive content below, ignoring all front matter headers.\n"
        "Proofread, validate, fix spelling and grammar, punctuation, and flag ambiguous phrasing.\n"
        "Provide a detailed report of any issues, including the location.\n"
    ),
}

# Rewrites a whole article for the website (used by content_expand.expand_article).
# The rules are numbered because models follow numbered rules more reliably, and each one
# prevents a problem seen in practice: placeholders, invented links, wrong math
# delimiters, a chatty preamble that would have to be deleted by hand before pasting.
expand_article = {
    "role": "system",
    "content": (
        "You are an expert technical writer and teacher. You receive the body of a Markdown "
        "article for a Hugo website (its front matter has already been removed).\n"
        "Provide a fully rewritten, highly expanded, and polished version of the article that "
        "I can copy and paste directly into my website.\n"
        "\n"
        "Rules:\n"
        "1. Do not use placeholders (like \"insert proof here\", \"...\", \"TODO\" or "
        "\"to be completed\"). Write out every single step, proof, derivation and example "
        "completely.\n"
        "2. Keep the topic, the structure, the headings and the voice of the author. Add detail, "
        "intuition, fully worked examples and clear sub-headings where they help. Fix spelling "
        "and grammar. Write in English.\n"
        "3. Never drop information that is in the original.\n"
        "4. Output Markdown only. Keep every existing link, image, Hugo shortcode "
        "({{< ... >}}), code block and HTML tag exactly as written. Do not invent URLs, "
        "images, references or quotations.\n"
        "5. Mathematics: use $...$ for inline formulas and $$...$$ for display formulas. Never "
        "use \\( \\) or \\[ \\].\n"
        "6. Do not write front matter (no --- block), no preamble such as \"Here is the "
        "article\", no closing remarks, and do not wrap the answer in a code fence. The first "
        "character of your answer is the first character of the article.\n"
    ),
}


# --------------------------------------------------------------------------- #
# Finding a prompt by name (shared by myollama.py and openrouter.py)           #
# --------------------------------------------------------------------------- #


def available_prompts() -> dict:
    """Return {name: prompt_dict} for every valid prompt defined in this file.

    A valid prompt is any public variable of this module that is a dictionary
    containing the keys 'role' and 'content'.
    """
    return {
        name: value
        for name, value in vars(sys.modules[__name__]).items()
        if not name.startswith("_")  # ignore private names
        and isinstance(value, dict)
        and "role" in value
        and "content" in value
    }


def resolve_prompt(prompt) -> dict:
    """Turn a prompt name (or a ready-made dictionary) into a valid prompt dictionary.

    Args:
        prompt: "query_expand" (a name from this file)  or
                {"role": "system", "content": "..."} (your own one-off prompt).
    Raises:
        ValueError: unknown name, or a dictionary without 'role' and 'content'.
    """
    # Case 1: the caller passed a dictionary directly -> just check its shape.
    if isinstance(prompt, dict):
        if "role" not in prompt or "content" not in prompt:
            raise ValueError("a prompt dictionary must have 'role' and 'content' keys")
        return prompt

    # Case 2: the caller passed a name -> look it up.
    prompts = available_prompts()
    if isinstance(prompt, str) and prompt in prompts:
        return prompts[prompt]

    # Anything else: explain what the valid choices are (much friendlier than a KeyError).
    raise ValueError(
        f"unknown prompt {prompt!r}. Available prompts: {', '.join(sorted(prompts)) or '(none found)'}"
    )
