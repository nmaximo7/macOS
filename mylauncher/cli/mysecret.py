"""
mysecret.py - your secrets (API keys...) in one file OUTSIDE the repository, shown by the launcher.

The file is a plain list of NAME=value lines, the format of a .env file:

    # OpenRouter, for content_creation.py
    OPENROUTER_API_KEY=sk-or-v1-xxxxxxxxxxxxxxxx
    export OTHER_TOKEN="a value with spaces"

A `#` comment right above a line describes it. By default the file is  ~/.config/mylauncher/secrets.env
(`secret.file`); you can also point it at a .env you already have (the one of the Hugo toolkit, say).

    secret                the entries, values hidden (only the last characters show); Enter shows one in full,
                          Enter again copies it (and the clipboard is emptied again after `secret.clear_seconds`)
    secret all            the first row shows EVERYTHING of the file, values visible
    keep_secret           opens the file in your editor (creating it, with safe permissions, if it is missing)

A value can ALSO live in the macOS Keychain, like the key of openrouter.py (service "justtothepoint-toolkit",
account = the name). Write the name with an empty value or the word keychain:

    OPENROUTER_API_KEY=keychain

and the launcher reads it with the `security` program that comes with macOS. Save a value there with
`ml secret-set NAME` (the same entry as `python3 openrouter.py --set-key` for OPENROUTER_API_KEY).

Rules that keep it safe:
  * never put the file inside a git repository (`ml doctor` warns if it is);
  * its permissions must be 600 (only you can read it; `keep_secret` sets them);
  * the launcher never writes values to its logs or to the usage history.
"""

from __future__ import annotations

import os
import re
import stat
from dataclasses import dataclass
from pathlib import Path

from myhelp import comment_above
from myedit import tidy
from mytypes import Item

TEMPLATE = """# mylauncher secrets: one NAME=value per line (the format of a .env file).
# A comment right above a line describes it. Open this file with the command:  keep_secret
# This file must NEVER be in git, and only you may read it (permissions 600).
#
# A value can be written here, or kept in the macOS Keychain: write "keychain" instead of the value
# and save it with:  ml secret-set NAME
#
# OpenRouter, for content_creation.py (the same Keychain entry that openrouter.py --set-key uses)
OPENROUTER_API_KEY=keychain
"""
KEYCHAIN_WORDS = ("", "keychain")
NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_.-]*$")


@dataclass(frozen=True)
class Secret:
    name: str
    value: str
    comment: str = ""
    source: str = "file"  # "file" or "keychain"
    problem: str = ""  # why a Keychain value could not be read


def parse_value(text: str) -> str:
    text = text.strip()
    if len(text) >= 2 and text[0] == text[-1] and text[0] in "'\"":
        inner = text[1:-1]
        return inner.replace('\\"', '"') if text[0] == '"' else inner
    return re.split(r"\s+#", text, maxsplit=1)[0].strip()  # an unquoted value ends at " #comment"


def parse_secrets(text: str) -> list:
    lines = text.splitlines()
    found = []
    for index, line in enumerate(lines):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        stripped = stripped.removeprefix("export ").lstrip()
        name, sep, value = stripped.partition("=")
        name = name.strip()
        if not sep or not NAME.match(name):
            continue
        found.append(Secret(name, parse_value(value), comment_above(lines, index)))
    return found


def mask(value: str, reveal: int = 4) -> str:
    """"sk-or-v1-abcdef123456" -> "••••••••••3456". Short values show no character at all."""
    if not value:
        return "(empty)"
    dots = "•" * min(max(len(value) - reveal, 6), 12)
    if reveal > 0 and len(value) >= reveal * 4:
        return dots + value[-reveal:]
    return "•" * 8


def keychain_get(runner, service: str, account: str) -> tuple:
    """(value, problem) from the macOS Keychain, using `security find-generic-password` (nothing to install)."""
    command = ["security", "find-generic-password", "-s", service, "-a", account, "-w"]
    try:
        done = runner(command)
    except FileNotFoundError:
        return "", "the program 'security' was not found (is this a Mac?)"
    except Exception as exc:  # noqa: BLE001 - a timeout or anything odd: report it, do not crash the list
        return "", f"Keychain error ({type(exc).__name__})"
    if done.returncode == 0:
        value = (done.stdout or "").rstrip("\n")
        return (value, "") if value else ("", f"nothing stored yet: run  ml secret-set {account}")
    if done.returncode == 44:  # "The specified item could not be found in the keychain."
        return "", f"not in the Keychain yet: run  ml secret-set {account}"
    return "", f"the Keychain refused ({(done.stderr or '').strip().splitlines()[-1:] or done.returncode}); allow it with 'Always Allow'"


def read_secrets(path, runner=None, service: str = "") -> tuple:
    """([Secret], problem). problem is "" when the file was read (even if it holds nothing).

    With a `runner`, the entries whose value is empty or "keychain" are read from the Keychain."""
    try:
        found = parse_secrets(Path(path).expanduser().read_text(encoding="utf-8"))
    except FileNotFoundError:
        return [], "the secret file does not exist yet"
    except OSError as exc:
        return [], f"cannot read the secret file: {exc}"
    if runner is not None:
        filled = []
        for s in found:
            if s.value.lower() in KEYCHAIN_WORDS:
                value, problem = keychain_get(runner, service, s.name)
                s = Secret(s.name, value, s.comment, "keychain", problem)
            filled.append(s)
        found = filled
    return found, ""


def add_name(path, name: str, comment: str = "") -> bool:
    """Make sure `NAME=keychain` is in the file (so `secret` lists it). True when a line was added."""
    path = Path(path).expanduser()
    ensure_file(path)
    if any(s.name == name for s in parse_secrets(path.read_text(encoding="utf-8"))):
        return False
    with open(path, "a", encoding="utf-8") as handle:
        handle.write(("\n# " + comment if comment else "") + f"\n{name}=keychain\n")
    return True


def file_problems(path) -> list:
    """What is unsafe about the file: loose permissions, or inside a git repository."""
    path = Path(path).expanduser()
    problems = []
    try:
        mode = stat.S_IMODE(path.stat().st_mode)
        if mode & 0o077:
            problems.append(f"readable by other users (permissions {mode:o}): chmod 600 {path}")
    except OSError:
        return problems
    for parent in path.resolve().parents:
        if (parent / ".git").exists():
            problems.append(f"inside the git repository {parent}: make sure the file is ignored, or move it out")
            break
    return problems


def ensure_file(path) -> tuple:
    """Create the file (and its folder) with safe permissions when missing; fix loose permissions.
    Returns (path, what_was_done) where what_was_done is "" if nothing needed doing."""
    path = Path(path).expanduser()
    done = []
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)  # created 600 from the first byte
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(TEMPLATE)
        done.append("created")
    elif stat.S_IMODE(path.stat().st_mode) & 0o077:
        os.chmod(path, 0o600)
        done.append("permissions set to 600")
    return path, ", ".join(done)


def table(secrets: list) -> str:
    """Everything, unmasked, aligned: what the "all" row shows."""
    if not secrets:
        return "(nothing in the file yet)"
    width = max(len(s.name) for s in secrets)
    blocks = []
    for s in secrets:
        head = f"# {s.comment.splitlines()[0]}\n" if s.comment else ""
        blocks.append(f"{head}{s.name:<{width}} = " + (f"({s.problem})" if s.problem else s.value))
    return "\n\n".join(blocks)


def build_secret_items(config, runner=None) -> list:
    secrets, problem = read_secrets(config.secret_file, runner, config.secret_service)
    path = tidy(Path(config.secret_file).expanduser())
    hint = f"type {config.secret_edit_word} to create and edit {path}"
    if not secrets:
        return [Item(id="info:secret", title="No secrets yet" if not problem or "exist" in problem else "Cannot read the secrets",
                     kind="prefix", action="prefix_hint", complete=config.secret_edit_word, subtitle=problem + ": " + hint if problem else hint,
                     icon="⚠️", badge="Fix")]
    items = []
    for warning in file_problems(config.secret_file):
        items.append(Item(id="info:secret-perm", title="The secret file is not safe", kind="prefix", action="prefix_hint",
                          complete=config.secret_edit_word, subtitle=warning, icon="⚠️", badge="Fix"))
    items.append(Item(id="secret:*all*", title="all", kind="secret", action="copy_secret", target=table(secrets),
                      subtitle=f"every value of {path}, visible (Enter)", detail=f"{path}\n\n{table(secrets)}", icon="🔓", badge="Show all",
                      complete=f"{config.secret_word} all"))
    for s in secrets:
        if s.problem:  # a Keychain value that could not be read: a hint row, nothing to copy
            items.append(Item(id=f"secret-problem:{s.name}", title=s.name, kind="prefix", action="prefix_hint", complete=f"{config.secret_word} {s.name}",
                              subtitle=f"🔒 Keychain: {s.problem}", keywords=(s.comment,) if s.comment else (), icon="⚠️", badge="Keychain"))
            continue
        subtitle = ("🔒 " if s.source == "keychain" else "") + mask(s.value, config.secret_reveal) + (f"   # {s.comment.splitlines()[0]}" if s.comment else "")
        where = "\n(stored in the macOS Keychain)" if s.source == "keychain" else ""
        detail = f"{s.name}\n" + (f"# {s.comment}\n" if s.comment else "") + f"\n{s.value}\n{where}".rstrip()
        items.append(Item(id=f"secret:{s.name}", title=s.name, kind="secret", action="copy_secret", target=s.value, subtitle=subtitle,
                          detail=detail, keywords=(s.comment,) if s.comment else (), icon="🔑", badge="Secret",
                          complete=f"{config.secret_word} {s.name}"))
    return items


def edit_item(config) -> Item:
    path = tidy(Path(config.secret_file).expanduser())
    return Item(id="cmd:keep_secret", title=config.secret_edit_word, kind="command", action="edit_secret", target=str(Path(config.secret_file).expanduser()),
                keywords=("secret", "api key", "edit"), subtitle=f"Edit {path} (created with safe permissions if missing)", icon="🔐",
                complete=config.secret_edit_word)
