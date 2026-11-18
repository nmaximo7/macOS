"""
mytimer.py - `timer 90`, `timer 5m`, `timer 1h30m`, `timer 1:30`: a notification and a sound when the time is up.

The timer is a small shell script started in the background (its own session, so it goes on if the launcher
restarts). It does NOT use one long `sleep`: it looks at the clock every second, so if the Mac sleeps in
the middle, the timer rings as soon as it wakes up instead of late by the whole sleep.
"""

from __future__ import annotations

import re
import shlex

from mynotify import script_line

MAX_SECONDS = 24 * 3600
UNITS = {"h": 3600, "m": 60, "s": 1, "": 1}
WORDS = (("seconds", "s"), ("second", "s"), ("secs", "s"), ("sec", "s"), ("minutes", "m"), ("minute", "m"), ("mins", "m"), ("min", "m"),
         ("hours", "h"), ("hour", "h"), ("hrs", "h"), ("hr", "h"))
PART = re.compile(r"(\d+(?:\.\d+)?)\s*([hms]?)")


def parse_duration(text: str):
    """"90" "90s" "5m" "1h30m" "1.5m" "1:30" (minutes:seconds) "1:02:03" -> seconds (int), or None if it makes no sense."""
    text = text.strip().lower()
    if not text:
        return None
    if ":" in text:
        pieces = text.split(":")
        if len(pieces) not in (2, 3) or not all(p.isdigit() for p in pieces):
            return None
        numbers = [int(p) for p in pieces]
        seconds = numbers[0] * 60 + numbers[1] if len(numbers) == 2 else numbers[0] * 3600 + numbers[1] * 60 + numbers[2]
    else:
        for word, letter in WORDS:
            text = text.replace(word, letter)
        text = text.replace(",", ".")
        parts, position = [], 0
        while position < len(text):
            m = PART.match(text, position)
            if not m:
                return None
            parts.append(m)
            position = m.end()
            while position < len(text) and text[position] == " ":
                position += 1
        if not parts or (len(parts) > 1 and any(m.group(2) == "" for m in parts)):
            return None
        seconds = round(sum(float(m.group(1)) * UNITS[m.group(2)] for m in parts))
    return seconds if 1 <= seconds <= MAX_SECONDS else None


def format_duration(seconds: int) -> str:
    hours, rest = divmod(seconds, 3600)
    minutes, secs = divmod(rest, 60)
    return " ".join(f"{n}{u}" for n, u in ((hours, "h"), (minutes, "m"), (secs, "s")) if n) or "0s"


def timer_script(seconds: int, notify_method: str, sound: str, repeat: int, label: str = "") -> str:
    """The shell script: wait (by the clock), notify, ring."""
    shown = format_duration(seconds) + (f" ({label})" if label else "")
    ring = ["i=0", f"while [ $i -lt {int(repeat)} ]; do", f"  /usr/bin/afplay {shlex.quote(sound)} 2>/dev/null || printf '\\a'", "  i=$((i+1))", "done"] if repeat > 0 else []
    return "\n".join(
        [
            f"end=$(( $(date +%s) + {int(seconds)} ))",
            'while [ "$(date +%s)" -lt "$end" ]; do sleep 1; done',
            f'msg="Time is up: {shown}"'.replace("`", "").replace("$(", "").replace('\\', ""),
            script_line(notify_method, "Timer"),
            *ring,
        ]
    )
