"""
mytimer.py - `timer 90`, `timer 5m`, `timer 1h30m`, `timer 1:30`: a notification and a sound when the time is up.

The timer is a small shell script started in the background (its own session, so it goes on if the launcher
restarts). It does NOT use one long `sleep`: it looks at the clock every second, so if the Mac sleeps in
the middle, the timer rings as soon as it wakes up instead of late by the whole sleep.

GUIDED TOUR (four layers):
  1. PARSING  parse_duration(): text -> seconds, or None. "90", "5m", "1h30m", "1.5m", "1:30", "1:02:03", "two words" all handled.
     Two formats: with a colon (minutes:seconds or h:m:s, only digits) or with units. For the units form we first REPLACE words with letters
     (WORDS: "minutes" -> "m"; longer words first, so "minutes" is replaced before "min"), then read pieces with the regular expression
        PART = (\\d+(?:\\.\\d+)?)\\s*([hms]?)      a number, optional decimals, optional spaces, then an optional unit letter
     in a loop: `PART.match(text, position)` matches AT a position, `m.end()` says where it stopped, then we skip spaces. A leftover that
     does not match means "not a duration" (None). The rule `len(parts) > 1 and any unit is missing` rejects "1h 30" (ambiguous).
     `divmod(a, b)` gives (a // b, a % b) at once: divmod(5400, 3600) = (1, 1800).
  2. DISPLAY  format_duration (5400 -> "1h 30m"), clock (90 -> "00:01:30"; the +0.999 makes 0.2 s left still show 00:00:01).
  3. STATE    one small JSON file per running timer in a folder: start_file, running, cancel. The window and the menu bar read the folder every
     second; the timer's own SCRIPT checks that its file still exists - deleting the file IS the cancel button ("a file as a message").
     `running()` also cleans up dead timers (an end time more than 2 minutes in the past: a reboot killed the script).
     cancel() uses `Path(timer_id).name`, which strips any folder part: "../../x" cannot escape the timers folder.
  4. THE SCRIPT  timer_script(): lines of shell. `end=$(( $(date +%s) + N ))` then `while [ now -lt end ]; do sleep 1; done` - it asks the CLOCK every
     second, so a sleeping Mac rings on waking. Then notify (script_line), ring (afplay in a loop; `|| printf '\\a'` falls back to the terminal bell),
     `say` a sentence, and optionally raise and restore the system volume. Everything quoted with shlex.quote.
Try it:  python3 -c "import sys; sys.path.insert(0,'cli'); import mytimer as t; print(t.parse_duration('1h30m'), t.parse_duration('1:30'), t.clock(90))"
         ->  5400 90 00:01:30
"""

from __future__ import annotations

import json
import re
import shlex
from pathlib import Path

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


def clock(seconds: float) -> str:
    """90 -> "00:01:30" (what the window shows while counting down)."""
    seconds = max(0, int(seconds + 0.999))  # 0.2 s left still shows 00:00:01
    return f"{seconds // 3600:02d}:{seconds % 3600 // 60:02d}:{seconds % 60:02d}"


# ---- the running timers: one small JSON file each, in a folder (the window and the menu bar read it every second) ----


def start_file(folder, seconds: int, now: float, label: str = "") -> Path:
    folder = Path(folder).expanduser()
    folder.mkdir(parents=True, exist_ok=True)
    end = int(now) + int(seconds)
    path = folder / f"{end}-{int(seconds)}-{int(now * 1000) % 100000}.json"
    path.write_text(json.dumps({"end": end, "seconds": int(seconds), "label": label}), encoding="utf-8")
    return path


def running(folder, now: float) -> list:
    """The timers that are counting: [{"id", "end", "seconds", "label", "remaining"}], soonest first. Dead ones are cleaned up."""
    folder = Path(folder).expanduser()
    found = []
    try:
        files = sorted(folder.glob("*.json"))
    except OSError:
        return []
    for path in files:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            end = int(data["end"])
        except (OSError, ValueError, KeyError, TypeError):
            path.unlink(missing_ok=True)
            continue
        if end < now - 120:  # its script is gone (a reboot, a kill): forget it
            path.unlink(missing_ok=True)
            continue
        found.append({"id": path.stem, "end": end, "seconds": int(data.get("seconds", 0)), "label": data.get("label", ""), "remaining": end - now})
    return sorted(found, key=lambda t: t["end"])


def cancel(folder, timer_id: str) -> bool:
    path = Path(folder).expanduser() / f"{Path(timer_id).name}.json"  # .name: no way out of the folder
    existed = path.exists()
    path.unlink(missing_ok=True)
    return existed


def timer_script(seconds: int, notify_method: str, sound: str, repeat: int, label: str = "", state_file: str = "", volume: float = 3.0, speak: str = "", system_volume: int = 0) -> str:
    """The shell script: wait (by the clock; stop quietly if the state file is gone = cancelled), notify, ring.

    volume: afplay's own gain (1 = as recorded, 3 = three times louder). speak: a sentence for `say` (empty = silent).
    system_volume: 0 = do not touch the Mac's volume; 1-100 = set it for the ring and put it back afterwards (also un-mutes).
    """
    shown = format_duration(seconds) + (f" ({label})" if label else "")
    quoted = shlex.quote(state_file) if state_file else ""
    guard = f' [ -f {quoted} ] || exit 0;' if state_file else ""
    loud = []
    if system_volume > 0:
        loud = ["old=$(/usr/bin/osascript -e 'output volume of (get volume settings)' 2>/dev/null)",
                f"/usr/bin/osascript -e 'set volume output volume {int(system_volume)}' -e 'set volume without output muted' 2>/dev/null"]
    ring = []
    if repeat > 0:
        ring = ["i=0", f"while [ $i -lt {int(repeat)} ]; do", f"  /usr/bin/afplay -v {float(volume):g} {shlex.quote(sound)} 2>/dev/null || printf '\\a'", "  i=$((i+1))", "done"]
    if speak.strip():
        ring.append(f"/usr/bin/say {shlex.quote(speak.strip())} 2>/dev/null")
    restore = ['[ -n "$old" ] && /usr/bin/osascript -e "set volume output volume $old" 2>/dev/null'] if system_volume > 0 else []
    return "\n".join(
        [
            f"end=$(( $(date +%s) + {int(seconds)} ))",
            f'while [ "$(date +%s)" -lt "$end" ]; do{guard} sleep 1; done',
            *([f"[ -f {quoted} ] || exit 0", f"rm -f {quoted}"] if state_file else []),
            f'msg="Time is up: {shown}"'.replace("`", "").replace("$(", "").replace("\\", ""),
            *loud,
            script_line(notify_method, "Timer"),
            *ring,
            *restore,
        ]
    )
