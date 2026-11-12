# app/ - the window and the menu bar icon

Thin graphical layer (tkinter + pynput + PyObjC) on top of `cli/`. It holds no search or action logic:
for each keystroke it runs `cli/mylauncher.py search "<text>" --json`, and on Enter `run --id <id> --text "<text>" --yes --json`.

    mylauncher-app                  start (hidden); press the hotkey (Command+D by default)
    mylauncher-app --show           start and show the window
    mylauncher-app --hotkey-test    check the hotkey / permissions, no window
    mylauncher-app --keys           print every key macOS lets us see (diagnostic)
    mylauncher-autostart install    start at login (see also: status, logs, restart, uninstall)

Files: `mylauncher_app.py` (entry point), `mywindow.py` (tkinter), `mystate.py` (selection logic),
`myengine.py` (calls cli/), `myhotkey.py` (hotkey + permission diagnostics), `mymenubar.py` (menu bar icon),
`myautostart.py` (launch agent).

Installation (Python 3.13, permissions): `../docs/01-installation.md`. Internals: `../docs/03-implementation.md`.
