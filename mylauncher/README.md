# mylauncher

A small launcher for macOS in the spirit of Raycast or Alfred, built **slowly, in Python, for learning**.
Press a hotkey (default **Command+Shift+D**), type, see suggestions, press Enter.

> Status: **step 3 of N**. Engine, command line, tkinter window, Command+D hotkey and start at login are built; see `docs/04-journal.md`.

## Layout

| Folder  | What lives there |
|---------|------------------|
| `conf/` | `myconfiguration.json`: **every** setting (hotkey, folders with apps, commands, search options) |
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
```

Window: `app/mylauncher-app --hotkey-test`, then `app/mylauncher-app --show`, then Command+D (needs the permissions in `docs/01-installation.md`).

Design rule: **readability and flexibility over speed**. Read `docs/03-implementation.md` to understand every file.
