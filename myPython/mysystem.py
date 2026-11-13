#!/usr/bin/env python3
"""mac-setup-master diagnostic helpers.

READ-ONLY. Never writes to disk, never executes the user's shell config,
never runs shortcuts. Safe to import from the Claude code interpreter.

Requires Python 3.11+ (stdlib ``tomllib``) and PyYAML.

CLI:
    python scripts/mysystem.py [info|aerospace|espanso|skills|help|zsh|all]
                               [--json] [--help]

Import:
    from mysystem import (
        get_sys_info, parse_aerospace, parse_espanso, parse_skills,
        parse_help_sections, get_zsh_aliases, get_zsh_functions,
    )
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

try:
    import tomllib  # type: ignore[import-not-found]
except ModuleNotFoundError:  # pragma: no cover
    sys.exit("mysystem.py requires Python 3.11+ (stdlib tomllib). Run `python3 -V`.")

import yaml  # PyYAML


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def _safe_version(cmd: str) -> str:
    """Return --version output, or 'not installed' if the binary is missing."""
    if shutil.which(cmd.split()[0]) is None:
        return "not installed"
    try:
        out = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=5, check=False).stdout.strip()
    except subprocess.TimeoutExpired:
        return "timed out"
    return out or "unknown"


def _emit(payload: Any, as_json: bool, pretty: bool = True) -> None:
    if as_json:
        print(json.dumps(payload, indent=2, ensure_ascii=False))
    elif pretty:
        # Human-readable handled by callers; this is just a fallback.
        print(payload)


# --------------------------------------------------------------------------- #
# System info
# --------------------------------------------------------------------------- #
def get_sys_info(as_json: bool = False) -> dict[str, str]:
    """Return read-only system metrics. Also prints unless as_json."""
    try:
        ram_bytes = int(subprocess.getoutput("sysctl -n hw.memsize"))
        ram = f"{ram_bytes / (1024**3):.2f} GB"
    except ValueError:
        ram = "unknown"

    info: dict[str, str] = {
        "OS_Version": _safe_version("sw_vers -productVersion"),
        "Architecture": _safe_version("uname -m"),
        "RAM": ram,
        "Disk_Free": f"{shutil.disk_usage('/').free / (1024**3):.2f} GB",
        "Zsh_Version": _safe_version("zsh --version"),
        "AeroSpace": _safe_version("aerospace --version"),
    }

    if as_json:
        return info
    for key, value in info.items():
        print(f"{key}: {value}")
    return info


# --------------------------------------------------------------------------- #
# AeroSpace
# --------------------------------------------------------------------------- #
def parse_aerospace(as_json: bool = False) -> dict[str, dict[str, str]]:
    """Parse ~/.config/aerospace/aerospace.toml -> {mode: {key: action}}."""
    path = Path("~/.config/aerospace/aerospace.toml").expanduser()
    if not path.exists():
        msg = f"AeroSpace config not found at {path}"
        print(msg, file=sys.stderr)
        return {}

    try:
        with path.open("rb") as fh:
            config = tomllib.load(fh)
    except tomllib.TOMLDecodeError as exc:
        print(f"Invalid TOML in {path}: {exc}", file=sys.stderr)
        return {}

    bindings: dict[str, dict[str, str]] = {}
    for mode, body in config.get("mode", {}).items():
        bindings[mode] = dict(body.get("binding", {}))

    if as_json:
        return bindings

    print("--- AeroSpace Keybindings ---")
    for mode, keys in bindings.items():
        print(f"\nMode: [{mode}]")
        for key, action in keys.items():
            print(f"  {key.ljust(18)} -> {action}")
    if not bindings:
        print("(no bindings found)")
    return bindings


# --------------------------------------------------------------------------- #
# Espanso
# --------------------------------------------------------------------------- #
def parse_espanso(as_json: bool = False) -> list[dict[str, str]]:
    """Parse $ESPANSO_MATCH_DIR (default Espanso match dir) for triggers."""
    match_dir = Path(
        os.environ.get(
            "ESPANSO_MATCH_DIR",
            os.path.expanduser("~/Library/Application Support/espanso/match"),
        )
    ).expanduser()

    if not match_dir.exists():
        print(f"Espanso match directory not found: {match_dir}", file=sys.stderr)
        return []

    results: list[dict[str, str]] = []
    for path in sorted(match_dir.rglob("*")):
        if path.suffix.lower() not in {".yml", ".yaml"}:
            continue
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        except (OSError, yaml.YAMLError) as exc:
            print(f"Could not read {path}: {exc}", file=sys.stderr)
            continue

        for match in data.get("matches", []):
            if not isinstance(match, dict):
                continue
            triggers = match.get("triggers", match.get("trigger", []))
            if isinstance(triggers, str):
                triggers = [triggers]

            replacement = match.get("replace")
            if replacement is None:
                kind = (
                    "form"
                    if "form" in match
                    else "vars"
                    if "vars" in match
                    else "image"
                    if "image_path" in match
                    else "dynamic"
                )
                replacement = f"<{kind} match>"

            for trigger in triggers:
                results.append(
                    {
                        "file": path.name,
                        "trigger": str(trigger),
                        "replacement": str(replacement),
                    }
                )

    if as_json:
        return results
    for row in results:
        print(f"{row['file']}: {row['trigger']!r} -> {row['replacement']!r}")
    return results


# --------------------------------------------------------------------------- #
# OpenClaw skills
# --------------------------------------------------------------------------- #
_FRONTMATTER_RE = re.compile(r"\A---\s*\n(.*?)\n---(?:\s|\Z)", re.S)


def search_skills(
    query: str | None = None,
    root: str = "~/macOS/claude/skills",
) -> list[dict[str, str]]:
    """Return OpenClaw skills whose name/description match *query* (case-insensitive)."""
    root_path = Path(root).expanduser()
    if not root_path.exists():
        print(f"Skills root not found: {root_path}", file=sys.stderr)
        return []

    q = query.casefold() if query else None
    results: list[dict[str, str]] = []

    for skill_file in root_path.rglob("SKILL.md"):
        text = skill_file.read_text(encoding="utf-8")
        match = _FRONTMATTER_RE.match(text)
        if not match:
            continue
        try:
            meta = yaml.safe_load(match.group(1)) or {}
        except yaml.YAMLError:
            continue

        name = meta.get("name", skill_file.parent.name)
        description = (meta.get("description") or "").strip()
        if q and q not in name.casefold() and q not in description.casefold():
            continue

        results.append(
            {
                "name": name,
                "description": description,
                "path": str(skill_file.parent),
            }
        )
    return results


def parse_skills(as_json: bool = False) -> list[dict[str, str]]:
    skills = search_skills()
    if as_json:
        return skills
    if not skills:
        print("(no skills found under ~/macOS/claude/skills)")
        return skills
    for skill in skills:
        print(f"{skill['name']}: {skill['description']}\n  {skill['path']}")
    return skills


# --------------------------------------------------------------------------- #
# help.sh sections (Spotlight / Raycast / Keyboard)
# --------------------------------------------------------------------------- #
_HELP_SECTION_RE = re.compile(
    r"^sec_(?P<name>spotlight|raycast|keyboard)\s*\(\)\s*\{(?P<body>.*?)^\}",
    re.S | re.M,
)


def parse_help_sections(as_json: bool = False) -> dict[str, str]:
    """Extract sec_spotlight / sec_raycast / sec_keyboard bodies from help.sh."""
    path = Path("~/macOS/scripts/help.sh").expanduser()
    if not path.exists():
        print(f"help.sh not found at {path}", file=sys.stderr)
        return {}

    text = path.read_text(encoding="utf-8")
    sections = {m.group("name"): m.group("body").strip() for m in _HELP_SECTION_RE.finditer(text)}

    if as_json:
        return sections
    for name, body in sections.items():
        print(f"\n=== sec_{name} ===\n{body}")
    return sections


# --------------------------------------------------------------------------- #
# Zsh helpers
# --------------------------------------------------------------------------- #
def get_zsh_aliases(as_json: bool = False) -> dict[str, str]:
    """Dump active aliases via an interactive, non-login shell."""
    out = subprocess.run(["zsh", "-ic", "alias"], capture_output=True, text=True, check=False).stdout
    aliases: dict[str, str] = {}
    for line in out.splitlines():
        # Format: name='value'  or  name=value
        match = re.match(r"^(\S+)=(?:'([^']*)'|\"([^\"]*)\"|(.*))$", line.strip())
        if not match:
            continue
        name = match.group(1)
        value = next(g for g in match.groups()[1:] if g is not None)
        aliases[name] = value
    if as_json:
        return aliases
    for name, value in aliases.items():
        print(f"{name}={value}")
    return aliases


def get_zsh_functions(as_json: bool = False) -> list[str]:
    """List public (non-underscore) function names from ~/.zsh_functions."""
    out = subprocess.run(
        ["zsh", "-f", "-c", "source ~/.zsh_functions; print -l ${(k)functions:#_*}"],
        capture_output=True,
        text=True,
        check=False,
    ).stdout
    names = sorted({line.strip() for line in out.splitlines() if line.strip()})
    if as_json:
        return names
    for name in names:
        print(name)
    return names


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
_COMMANDS = {
    "info": get_sys_info,
    "aerospace": parse_aerospace,
    "espanso": parse_espanso,
    "skills": parse_skills,
    "help": parse_help_sections,
    "zsh": lambda as_json=False: {
        "aliases": get_zsh_aliases(as_json=True) if as_json else None,
        "functions": get_zsh_functions(as_json=True) if as_json else None,
    },
    "all": None,  # special-cased
}


def _run_all(as_json: bool) -> None:
    if as_json:
        print(
            json.dumps(
                {
                    "info": get_sys_info(as_json=True),
                    "aerospace": parse_aerospace(as_json=True),
                    "espanso": parse_espanso(as_json=True),
                    "skills": parse_skills(as_json=True),
                    "help_sections": parse_help_sections(as_json=True),
                    "zsh_aliases": get_zsh_aliases(as_json=True),
                    "zsh_functions": get_zsh_functions(as_json=True),
                },
                indent=2,
                ensure_ascii=False,
            )
        )
        return
    get_sys_info()
    parse_aerospace()
    parse_espanso()
    parse_skills()
    parse_help_sections()
    print("\n--- Zsh aliases ---")
    get_zsh_aliases()
    print("\n--- Zsh functions ---")
    get_zsh_functions()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="mysystem.py",
        description="Read-only diagnostics for the mac-setup-master skill.",
    )
    parser.add_argument(
        "command",
        nargs="?",
        default="all",
        choices=sorted(_COMMANDS),
        help="section to run (default: all)",
    )
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    args = parser.parse_args(argv)

    if args.command == "all":
        _run_all(args.json)
        return 0

    fn = _COMMANDS[args.command]
    if args.command == "zsh":
        if args.json:
            print(
                json.dumps(
                    {
                        "aliases": get_zsh_aliases(as_json=True),
                        "functions": get_zsh_functions(as_json=True),
                    },
                    indent=2,
                    ensure_ascii=False,
                )
            )
        else:
            print("--- Zsh aliases ---")
            get_zsh_aliases()
            print("\n--- Zsh functions ---")
            get_zsh_functions()
        return 0
    fn(as_json=args.json)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
