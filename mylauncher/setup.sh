#!/usr/bin/env bash
# setup.sh - ONE command that builds everything from zero. Run it again whenever something is wrong:
#
#     bash ~/macOS/mylauncher/setup.sh
#
# It: finds Python 3.13 -> deletes and recreates .venv -> installs the libraries -> makes the scripts
# executable -> (re)installs the start-at-login agent -> shows the ONE path macOS needs in Privacy settings
# -> runs the checks. Nothing in it is clever: read it top to bottom, each step prints what it does.

set -u
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$here" || exit 1

step() { printf '\n\033[1m== %s\033[0m\n' "$*"; }
stop() { printf '\n\033[31mSTOP: %s\033[0m\n' "$*" >&2; exit 1; }

step "1/6  Python 3.13 with tkinter"
py=""
for candidate in /opt/homebrew/bin/python3.13 /usr/local/bin/python3.13 "$(command -v python3.13 2>/dev/null)"; do
  if [ -n "$candidate" ] && [ -x "$candidate" ]; then py="$candidate"; break; fi
done
[ -n "$py" ] || stop "python3.13 not found. Install it:  brew install python@3.13 python-tk@3.13   then run setup.sh again"
"$py" -c "import tkinter" 2>/dev/null || stop "$py has no tkinter. Install it:  brew install python-tk@3.13   then run setup.sh again"
echo "using $py ($("$py" --version))"

step "2/6  Stop the running launcher (if any)"
if [ -x .venv/bin/python ]; then
  .venv/bin/python app/myautostart.py uninstall >/dev/null 2>&1 || true
fi
pkill -f "mylauncher_app.py" 2>/dev/null || true
echo "done"

step "3/6  Fresh virtual environment (.venv) and libraries"
rm -rf .venv
"$py" -m venv .venv || stop "could not create .venv"
.venv/bin/pip install --quiet --upgrade pip
.venv/bin/pip install --quiet -r app/requirements.txt || stop "pip install failed (is the internet working?)"
.venv/bin/python -c "import pynput, yaml, AppKit; print('pynput, PyYAML and PyObjC import fine')" || stop "a library does not import"

step "4/6  Make the scripts executable"
chmod a+x setup.sh cli/ml cli/mylauncher.py app/mylauncher-app app/mylauncher_app.py app/mylauncher-autostart app/myautostart.py
echo "done"

step "5/6  Start at login (and start now)"
bash app/mylauncher-autostart install

step "6/6  The ONE thing macOS must allow"
real="$(.venv/bin/python -c 'import os, sys; print(os.path.realpath(sys.executable))')"
printf '%s' "$real" | pbcopy 2>/dev/null
cat <<EOF

Add THIS program (its path is already in your clipboard) to BOTH lists in
System Settings > Privacy & Security:   Accessibility   and   Input Monitoring
(press +, then Cmd+Shift+G, paste the path, Open, switch it on):

    $real

I open the two panes for you now. After adding it, run:   bash app/mylauncher-autostart restart
(If Homebrew upgrades Python later, the path changes: run setup.sh again and add the new one.)
EOF
open "x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility" 2>/dev/null || true
sleep 1
open "x-apple.systempreferences:com.apple.preference.security?Privacy_ListenEvent" 2>/dev/null || true

step "Check"
.venv/bin/python cli/mylauncher.py doctor | head -40
