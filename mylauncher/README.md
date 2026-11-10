# mylauncher

A small launcher for macOS in the spirit of Raycast or Alfred, built **slowly, in Python, for learning**.
Press a hotkey (default **Command+Shift+D**), type, see suggestions, press Enter.

> Status: **step 1 of N**. The engine and its command line work and are tested.
> The window (GUI) and the global hotkey come in step 2: see `docs/04-journal.md`.

## Layout

| Folder  | What lives there |
|---------|------------------|
| `conf/` | `myconfiguration.json`: **every** setting (hotkey, folders with apps, commands, search options) |
| `cli/`  | The engine, as command-line scripts. Everything the launcher does can be done here |
| `app/`  | The graphical window. It will only *call* `cli/`. Empty for now |
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

Design rule: **readability and flexibility over speed**. Read `docs/03-implementation.md` to understand every file.
