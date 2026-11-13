# mylauncher

A small launcher for macOS in the spirit of Raycast or Alfred, built **slowly, in Python, for learning**.
Press a hotkey (default **Command+D**), type, see suggestions, press Enter.

> Status: **step 6 of N**. Step 6: Raycast-like window, `run`/`;` lists, hotkey swallowed, searches in a new Zen tab. Engine, command line, tkinter window, Command+D hotkey, start at login, most-used-first, quicklinks, `kill`, the menu bar icon and Espanso snippets are built; see `docs/04-journal.md`.

## Layout

| Folder  | What lives there |
|---------|------------------|
| `conf/` | `myconfiguration.json`: the settings (hotkey, folders with apps, commands, search options, kill, usage, menu bar, Espanso folder) and `quicklinks.json`: your web searches |
| `cli/`  | The engine, as command-line scripts. Everything the launcher does can be done here |
| `app/`  | The tkinter window and the global hotkey. It only *calls* `cli/` |
| `docs/` | `01-installation.md`, `02-use.md`, `03-implementation.md`, `04-journal.md` |
| `tests/`| Automated tests (`python3 -m unittest discover -s tests`) |

## Try it in 30 seconds

```bash
cd ~/macOS/mylauncher
cli/ml doctor            # checks configuration, folders, tools
cli/ml search obs        # -> Run Obsidian
cli/ml run obs --dry-run # shows what it WOULD do, does nothing
cli/ml run obs           # opens Obsidian
cli/ml search yt lofi    # a quicklink: keyword, space, query
cli/ml run kill textedit --dry-run   # what closing TextEdit would do
```

Window: `app/mylauncher-app --hotkey-test`, then `app/mylauncher-app --show`, then Command+D (needs the permissions in `docs/01-installation.md`).

## If something breaks

**Restart the app (do this first):**

```bash
app/mylauncher-autostart restart
```

It runs `launchctl kickstart -k gui/501/com.mylauncher.app` (501 = your user id): macOS stops the launcher and starts it again. The rest of the toolbox:

| Problem | Command |
|---------|---------|
| Hotkey or window does not react | `app/mylauncher-autostart restart` |
| What is it doing? Is it running? | `app/mylauncher-autostart status` and `app/mylauncher-autostart logs` |
| After editing `conf/myconfiguration.json` or `quicklinks.json` | `app/mylauncher-autostart restart` |
| Something looks wrong with the installation | `cli/ml doctor` (✔ fine, ! look at it, ✘ broken) |
| Permissions (hotkey does nothing) | `app/mylauncher-app --hotkey-test`, then `--keys`; see `docs/01-installation.md`, section 4 |
| Stop starting at login | `app/mylauncher-autostart uninstall` |

**`Permission denied` when running a script** (it happens when files are copied and pasted: the "executable" flag is lost):

```bash
cd ~/macOS/mylauncher
chmod a+x cli/ml cli/mylauncher.py app/mylauncher-app app/mylauncher_app.py app/mylauncher-autostart app/myautostart.py
```

or run it through bash, which needs no flag: `bash app/mylauncher-autostart restart`. `cli/ml doctor` tells you which ones are missing the flag.
Git remembers the flag: after the `chmod`, `git add` and commit and it will stay.

Design rule: **readability and flexibility over speed**. Read `docs/03-implementation.md` to understand every file.
