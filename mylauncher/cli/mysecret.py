"""
mysecret.py - your secrets (passwords, API keys...): every NAME + VALUE pair lives in the macOS Keychain.

THE RULE (since Step 19.2): the Keychain is the ONLY place that stores values.
  service = secret.keychain_service ("justtothepoint-toolkit"), account = the name (google, facebook, OPENROUTER_API_KEY...).
The text file  ~/.config/mylauncher/secrets.env  (`secret.file`) is only a convenient VIEW with your names, comments and private_notes.

Three things you can do (the launcher word, and the same in the terminal):

  A. SHOW a secret                      secret google                 ml secret google
     The value is shown AS IS (no hiding: it is your own computer). One Enter copies it (the clipboard is emptied again after
     `secret.clear_seconds`). `secret` alone lists every name with its value.  `ml secret` alone prints every pair.
  B. SET a secret                       secret-set google my password   ml secret-set google "my password"
     Writes the Keychain (a new value replaces the old one) and adds the name to the file. In the terminal, without the value you are asked for it.
  C. EDIT the file                      keep_secret   (launcher only)
     Opens the file in your editor showing every pair as  google=password_of_google  (the values are read from the Keychain just before).
     Change a value, add a line  newname=value,  save. The NEXT time any secret is read (secret, ml secret, keep_secret...) the changed values are
     moved into the Keychain and erased from the file (it shows  google=  again). So the passwords sit in the file only while you are editing.
     Everything else in the file (comments, the  NAME.private_notes=\"\"\" ... \"\"\"  blocks) is never touched.

The file looks like a .env file:

    # Google account
    google=password_of_google
    facebook=
    NAME.private_notes=\"\"\"
    any number of lines
    \"\"\"

A line with an empty value (or the old word `keychain`) means: "the value is in the Keychain". A line with a real value is a pending change.
If the Keychain cannot be written (this is not a Mac, or it refused) the value STAYS in the file and is shown from there: nothing is lost.
Removing a line from the file only hides the name from the list; the Keychain item stays (delete it with
`security delete-generic-password -s justtothepoint-toolkit -a NAME`).

Rules that keep it safe:
  * never put the file inside a git repository (`ml doctor` warns if it is);
  * its permissions must be 600 (only you can read it; `keep_secret` sets them);
  * the launcher never writes values to its logs or to the usage history.

GUIDED TOUR (for someone who is just starting to program) -----------------------------------------------------------------
Security code is the kind where you want to READ every line, so here is a map. The file has six parts, top to bottom:

  1. The Secret shape and the FILE FORMAT  Secret, parse_value, split_notes, parse_secrets, parse_all
        text of the file  ->  a list of Secret(name, value, comment, source, problem, notes)
  2. The Keychain doors                    keychain_get, keychain_set   (the ONLY two functions that talk to `security`)
  3. Writing the file back                 format_value, rewrite_values, _write_keeping_mode
  4. The synchronisation                   sync_file, scrub_names, read_secrets   (file <-> Keychain)
  5. Safety checks                         add_name, file_problems, ensure_file
  6. What the launcher shows               mask, table, vault_text, build_secret_items, edit_item, set_notes

THE KEY IDEA - two places, one source of truth:
      Keychain (encrypted by macOS)  = the ONLY place a value lives for good
      secrets.env (a text file)      = a VIEW: names, comments, notes, and the values only while YOU are editing

  You type in the editor:   google=newpassword      (a "pending change")
  Next time anything reads secrets, sync_file runs:
        - IMPORT: google has a real value -> keychain_set("google", "newpassword") -> the file line becomes  google=
        - (if the Keychain refuses: the value STAYS in the file; nothing is ever lost silently)
  Before the editor opens (keep_secret): EXPORT = fill each empty line from the Keychain so you can see/change it.

WHY THE FILE IS SO CAREFUL WITH TEXT: it is a file YOU also edit by hand, with comments and multi-line notes. So the program
may change ONLY the value after `=` of one line, and must leave every other byte alone (rewrite_values; the notes are "protected spans").
Where something could go wrong the code returns a problem sentence instead of crashing (a list of secrets must always display).
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

TEMPLATE = """# mylauncher secrets: one  name=value  per line. Open this file with the launcher word:  keep_secret
# The values live in the macOS Keychain; this file only shows them while you edit it. After you save it, the next time a
# secret is read the changed values go into the Keychain and disappear from here (the line becomes  name=).
# A comment right above a line describes it. This file must NEVER be in git, and only you may read it (permissions 600).
#
# OpenRouter, for content_creation.py (the same Keychain entry that openrouter.py --set-key uses)
OPENROUTER_API_KEY=
"""
KEYCHAIN_WORDS = ("", "keychain")
NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_.-]*$")


# One secret as the launcher sees it. `source` says where the value came from ("file" = typed in the file, "keychain" = read from
# the Keychain); `problem` is a sentence when a Keychain value could not be read (the list then shows a hint row instead of a value).
@dataclass(frozen=True)
class Secret:
    name: str
    value: str
    comment: str = ""
    source: str = "file"  # "file" or "keychain"
    problem: str = ""  # why a Keychain value could not be read
    notes: str = ""  # private_notes: any number of lines


def parse_value(text: str) -> str:
    """The value written after `=`:   abc   "a b"   'x'   abc  # comment   ->   abc | a b | x | abc.

    Quotes are removed (inside double quotes \\" means a quote), and an UNQUOTED value ends where " #" starts (a comment).
    `re.split(r"\\s+#", text, maxsplit=1)[0]` = cut at the first "spaces then #" and keep what is before it.
    """
    text = text.strip()
    if len(text) >= 2 and text[0] == text[-1] and text[0] in "'\"":
        inner = text[1:-1]
        return inner.replace('\\"', '"') if text[0] == '"' else inner
    return re.split(r"\s+#", text, maxsplit=1)[0].strip()  # an unquoted value ends at " #comment"


# Two ways to write private notes (many lines of text kept with a secret):
#   NAME.private_notes="""      <- a BLOCK: starts here, ends at the next triple quote (re.S: . matches newlines; re.M: ^ and $ per line)
#   line 1
#   line 2
#   """
#   NAME.private_notes=one line\nsecond line     <- a ONE-LINE form where \n means a new line
# Both are regular expressions; group(1) is the NAME and group(2) the text.
NOTES_BLOCK = re.compile(r'^([A-Za-z_][A-Za-z0-9_.-]*)\.private_notes[ \t]*=[ \t]*"""[ \t]*\n(.*?)\n?"""[ \t]*$', re.M | re.S)
NOTES_LINE = re.compile(r'^([A-Za-z_][A-Za-z0-9_.-]*)\.private_notes[ \t]*=(.*)$', re.M)


# `re.sub(pattern, function, text)` calls `function(match)` for every match and puts what it returns in place of the match.
# Here the function REMEMBERS the notes in a dict and returns "" (so the notes vanish from the text that is parsed next).
# A function defined inside another function (a "closure") can write to the outer `notes` dict: that is the trick.
def split_notes(text: str) -> tuple:
    """(text without the notes, {NAME: notes}). Notes are  NAME.private_notes=\"\"\"  lines...  \"\"\"  (or one line with \\n)."""
    notes = {}

    def block(m):
        notes[m.group(1)] = m.group(2)
        return ""

    text = NOTES_BLOCK.sub(block, text)

    def line(m):
        notes[m.group(1)] = parse_value(m.group(2)).replace("\\n", "\n")
        return ""

    return NOTES_LINE.sub(line, text), notes


def parse_secrets(text: str) -> list:
    text, notes = split_notes(text)
    found = parse_all(text)
    return [Secret(s.name, s.value, s.comment, s.source, s.problem, notes.get(s.name, "")) for s in found]


def parse_all(text: str) -> list:
    """Every `name=value` line (comments and blank lines skipped, `export NAME=...` accepted) -> [Secret].

    `stripped.partition("=")` cuts at the FIRST "=" only (a value may contain "=": base64 keys do). A line whose name does not
    match NAME is ignored, not an error: the file may contain anything you like.
    """
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


# mask() is kept for the places where a value should not be fully visible: it shows dots and only the last 4 characters,
# and only when the value is long enough (>= 16) that 4 characters reveal little. A short value shows no character at all.
def mask(value: str, reveal: int = 4) -> str:
    """"sk-or-v1-abcdef123456" -> "••••••••••3456". Short values show no character at all."""
    if not value:
        return "(empty)"
    dots = "•" * min(max(len(value) - reveal, 6), 12)
    if reveal > 0 and len(value) >= reveal * 4:
        return dots + value[-reveal:]
    return "•" * 8


# ---- the two doors to the Keychain ---------------------------------------------------------------------------------
# `security` is a program that ships with macOS. We call it through the INJECTED runner, so tests use FakeKeychain and no real
# Keychain is touched. Both functions return (result, problem) pairs instead of raising: the caller always gets an answer.
# Exit code 44 is `security`'s "item not found": a normal case (you have not stored it yet), explained with the command to fix it.
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


def keychain_set(runner, service: str, account: str, value: str) -> tuple:
    """(ok, problem): save `value` in the Keychain (`-U` = update it if it already exists)."""
    command = ["security", "add-generic-password", "-U", "-s", service, "-a", account, "-w", value]
    try:
        done = runner(command)
    except FileNotFoundError:
        return False, "the program 'security' was not found (is this a Mac?)"
    except Exception as exc:  # noqa: BLE001
        return False, f"Keychain error ({type(exc).__name__})"
    if done.returncode != 0:
        return False, f"the Keychain did not save it (exit code {done.returncode})"
    return True, ""


# format_value is the INVERSE of parse_value: choose how to write a value in the file so that parse_value reads back exactly the same
# text. A value with spaces at the ends, a leading quote or " #" is wrapped in double quotes. A value with a line break cannot be
# written on one line, so it returns None and the caller leaves the line empty (the value stays safe in the Keychain).
# Always ask: "if I write this and read it back, do I get the same thing?" - the "round trip" test.
def format_value(value: str):
    """How a value is written in the file so that parse_value reads it back; None if it cannot be (a value with a line break)."""
    if "\n" in value or "\r" in value:
        return None
    if value != value.strip() or value[:1] in "'\"" or " #" in value or "\t#" in value:
        return '"' + value.replace('"', '\\"') + '"'
    return value


def _protected_spans(text: str) -> list:
    """Where the private_notes live (offsets): lines inside are never edited, even if they look like name=value."""
    return [m.span() for m in NOTES_BLOCK.finditer(text)] + [m.span() for m in NOTES_LINE.finditer(text)]


# rewrite_values: the surgeon. For every line `name=...` whose name is in `mapping`, replace ONLY the value. Everything else
# (comments, blank lines, the notes blocks, the `export ` prefix, the line ending \n or \r\n) is copied unchanged.
# `splitlines(keepends=True)` keeps each line's ending so nothing shifts; `offset` tracks where each line starts so we can tell
# whether it is inside a protected span (a notes block). If the new value equals the old one the line is not even touched.
def rewrite_values(text: str, mapping: dict) -> str:
    """Return `text` with the value of every NAME in `mapping` replaced (comments, notes, other lines stay exactly as they are)."""
    spans = _protected_spans(text)
    out, offset = [], 0
    for line in text.splitlines(keepends=True):
        here, offset = offset, offset + len(line)
        if any(a <= here < b for a, b in spans):
            out.append(line)
            continue
        body = line.rstrip("\r\n")
        ending = line[len(body):]
        stripped = body.strip()
        if stripped and not stripped.startswith("#"):
            prefix = "export " if stripped.startswith("export ") else ""
            name, sep, _value = stripped.removeprefix("export ").lstrip().partition("=")
            name = name.strip()
            if sep and NAME.match(name) and name in mapping:
                if parse_value(_value) == parse_value(mapping[name]):  # nothing to change: the line stays exactly as you wrote it
                    out.append(line)
                else:
                    out.append(f"{prefix}{name}={mapping[name]}{ending}")
                continue
        out.append(line)
    return "".join(out)


# The file is created with permissions 0o600 (octal: owner may read+write, nobody else) FROM THE FIRST BYTE: `os.open(..., 0o600)`
# sets them at creation, whereas writing first and chmod-ing after would leave a moment when others could read it.
# Then the usual atomic swap with os.replace. (0o600 in binary groups: owner 6=rw-, group 0=---, others 0=---.)
def _write_keeping_mode(path: Path, text: str) -> None:
    tmp = path.with_name(path.name + ".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        handle.write(text)
    os.replace(tmp, path)


def sync_file(path, runner, service: str, export: bool = False) -> list:
    """Keep file and Keychain in step. Returns a list of what happened (for messages and tests).

    1. IMPORT: every entry with a real value (not empty, not "keychain") is a change you typed: it goes to the Keychain
       (unless it is already the same) and the file line becomes `name=`. If the Keychain refuses, the value stays in the file.
    2. EXPORT (only when `export` is true, i.e. just before keep_secret opens the editor): every empty entry is filled with its value
       from the Keychain, so you see `google=password_of_google`.
    """
    path = Path(path).expanduser()
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return []
    happened, mapping = [], {}
    found = parse_secrets(text)
    for s in found:
        if s.value and s.value.lower() not in KEYCHAIN_WORDS:
            current, _problem = keychain_get(runner, service, s.name)
            if current == s.value:
                mapping[s.name] = ""
                happened.append(f"{s.name}: already in the Keychain")
                continue
            ok, problem = keychain_set(runner, service, s.name, s.value)
            if ok:
                mapping[s.name] = ""
                happened.append(f"{s.name}: saved in the Keychain")
            else:
                happened.append(f"{s.name}: NOT saved ({problem}); the value stays in the file")
    if export:
        filled = {}
        for s in found:
            if s.name in mapping:  # just imported: it is still in the Keychain now, show it again
                value = s.value
            elif not s.value or s.value.lower() in KEYCHAIN_WORDS:
                value, _problem = keychain_get(runner, service, s.name)
            else:  # could not be saved: the value is still in the file
                continue
            written = format_value(value) if value else None
            if written is not None:
                filled[s.name] = written
        text = rewrite_values(text, {**{n: "" for n in mapping}, **filled})  # ONE pass: imported names are shown again with their value
        if filled:
            happened.append(f"{len(filled)} value(s) shown in the file for editing")
    elif mapping:
        text = rewrite_values(text, {n: "" for n in mapping})
    if mapping or export:
        _write_keeping_mode(path, text)
    return happened


def scrub_names(path, names) -> None:
    """Make the lines of `names` empty (after a `secret-set`, an old plain value in the file must not overwrite the new Keychain value)."""
    path = Path(path).expanduser()
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return
    new = rewrite_values(text, {n: "" for n in names})
    if new != text:
        _write_keeping_mode(path, new)


def read_secrets(path, runner=None, service: str = "") -> tuple:
    """([Secret], problem). problem is "" when the file was read (even if it holds nothing).

    With a `runner`, pending changes in the file are first moved into the Keychain (sync_file), then the entries whose
    value is empty or "keychain" are read from the Keychain."""
    if runner is not None:
        try:
            sync_file(path, runner, service)
        except OSError:
            pass  # a file we cannot rewrite: still show what is in it
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
                s = Secret(s.name, value, s.comment, "keychain", problem, s.notes)
            filled.append(s)
        found = filled
    return found, ""


def add_name(path, name: str, comment: str = "") -> bool:
    """Make sure a line `NAME=` is in the file (so `secret` lists it). True when a line was added."""
    path = Path(path).expanduser()
    ensure_file(path)
    if any(s.name == name for s in parse_secrets(path.read_text(encoding="utf-8"))):
        return False
    with open(path, "a", encoding="utf-8") as handle:
        handle.write(("\n# " + comment if comment else "") + f"\n{name}=\n")
    return True


# `mode & 0o077` keeps only the group and others bits: if ANY is set, other users can read the file -> a problem.
# Then we walk up the parent folders looking for a `.git` folder: a secrets file inside a git project may be committed by accident.
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


def indent_notes(notes: str) -> str:
    return "\n".join("    │ " + line for line in notes.splitlines())


def vault_text(secrets: list) -> str:
    """The private_vault: every entry that has private_notes, with its notes."""
    blocks = [f"{s.name}\n{indent_notes(s.notes)}" for s in secrets if s.notes]
    return "\n\n".join(blocks) if blocks else "(no private_notes yet: add them with  ml secret-notes NAME,  or edit the file with keep_secret)"


def table(secrets: list) -> str:
    """Everything, unmasked, aligned: what the "all" row shows."""
    if not secrets:
        return "(nothing in the file yet)"
    width = max(len(s.name) for s in secrets)
    blocks = []
    for s in secrets:
        head = f"# {s.comment.splitlines()[0]}\n" if s.comment else ""
        notes = ("\n" + indent_notes(s.notes)) if s.notes else ""
        blocks.append(f"{head}{s.name:<{width}} = " + (f"({s.problem})" if s.problem else s.value) + notes)
    return "\n\n".join(blocks)


# build_secret_items turns the Secrets into the ROWS of the window. Order: (1) problem rows (file missing / unsafe), (2) "all",
# (3) "private_vault", (4) one row per secret. A secret's action is `copy_secret` (myactions.py): copy, then empty the clipboard
# later ONLY if it still holds the secret. The subtitle uses small emoji as a legend: 🔒 value comes from the Keychain, 📝 has notes.
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
    items.append(Item(id="secret:*vault*", title="private_vault", kind="secret", action="copy_secret", target=vault_text(secrets),
                      subtitle=f"the private_notes of {sum(1 for s in secrets if s.notes)} entries (Enter)", detail=vault_text(secrets), icon="🗄️",
                      badge="Vault", complete=f"{config.secret_word} private_vault"))
    for s in secrets:
        if s.problem:  # a Keychain value that could not be read: a hint row, nothing to copy
            items.append(Item(id=f"secret-problem:{s.name}", title=s.name, kind="prefix", action="prefix_hint", complete=f"{config.secret_word} {s.name}",
                              subtitle=f"🔒 Keychain: {s.problem}", keywords=(s.comment,) if s.comment else (), icon="⚠️", badge="Keychain"))
            continue
        subtitle = ("📝 " if s.notes else "") + ("🔒 " if s.source == "keychain" else "") + (s.value or "(empty)") + (f"   # {s.comment.splitlines()[0]}" if s.comment else "")
        where = "\n(stored in the macOS Keychain)" if s.source == "keychain" else ""
        detail = f"{s.name}\n" + (f"# {s.comment}\n" if s.comment else "") + f"\n{s.value}\n{where}" + (f"\n\nprivate_notes:\n{s.notes}" if s.notes else "")
        detail = detail.rstrip()
        items.append(Item(id=f"secret:{s.name}", title=s.name, kind="secret", action="copy_secret", target=s.value, subtitle=subtitle,
                          detail=detail, keywords=(s.comment,) if s.comment else (), icon="🔑", badge="Secret",
                          complete=f"{config.secret_word} {s.name}"))
    return items


def edit_item(config) -> Item:
    path = tidy(Path(config.secret_file).expanduser())
    return Item(id="cmd:keep_secret", title=config.secret_edit_word, kind="command", action="edit_secret", target=str(Path(config.secret_file).expanduser()),
                keywords=("secret", "api key", "edit"), subtitle=f"Edit {path} (created with safe permissions if missing)", icon="🔐",
                complete=config.secret_edit_word)


def set_notes(path, name: str, notes: str) -> None:
    """Write (or replace) the private_notes block of NAME in the file; empty notes remove it."""
    path, _ = ensure_file(path)
    # Remove any existing notes of NAME (block form first, then one-line form), then append the new block. re.escape(name)
    # makes sure a dot or dash in a name is taken literally. The `chr(10)` is a newline character (used inside an f-string,
    # where a backslash is not allowed in older Python versions).
    text, _old = path.read_text(encoding="utf-8"), None
    text = re.sub(r'^' + re.escape(name) + r'\.private_notes[ \t]*=[ \t]*"""[ \t]*\n.*?\n?"""[ \t]*\n?', "", text, flags=re.M | re.S)
    text = re.sub(r'^' + re.escape(name) + r'\.private_notes[ \t]*=.*\n?', "", text, flags=re.M)
    if notes.strip():
        text = text.rstrip("\n") + f'\n{name}.private_notes="""\n{notes.strip(chr(10))}\n"""\n'
    path.write_text(text, encoding="utf-8")
