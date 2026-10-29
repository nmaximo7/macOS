"""
mymessages.py - the system prompts ("what should the model do with my text?").

Each prompt is a dictionary {"role": ..., "content": ...}. myollama.py finds them by
themselves (available_prompts()), and you choose one just by its NAME:

    call_ollama(text)                            # "query_expand" (the default)
    call_ollama(text, prompt="check_proof")      # proofread instead of expand

To add a new kind of query, add another dictionary with "role" and "content" below:
no change is needed anywhere else. Keep only real SYSTEM prompts here: every public
dictionary with "role" and "content" is offered as a selectable prompt.
"""

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
