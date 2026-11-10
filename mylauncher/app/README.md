# app/ - the window

Thin graphical layer (tkinter + pynput) on top of `cli/`. It holds no search or action logic:
for each keystroke it runs `cli/mylauncher.py search "<text>" --json`, and on Enter `run --id <id> --yes --json`.

    mylauncher-app             start (hidden); press the hotkey (Command+D by default)
    mylauncher-app --show      start and show the window
    mylauncher-app --hotkey-test   check the hotkey / permissions, no window

Installation (including the macOS permissions): `../docs/01-installation.md`. Internals: `../docs/03-implementation.md`.
