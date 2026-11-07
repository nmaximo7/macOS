#!/usr/bin/env bash
# =============================================================================
# ollama-stop.sh: give the memory back when you are done with local AI
#
#   1. Unload every model from memory (ollama stop <model>)
#   2. Quit the Ollama app (this also stops the server)
#   3. With --reopen: relaunch Zen, Obsidian and Safari
#   4. Send a notification
#
# Usage:   ollama-stop.sh [--reopen]
# =============================================================================
set -euo pipefail

APPS_TO_REOPEN=("Zen" "Obsidian" "Safari")

REOPEN=0
for arg in "$@"; do
    case "$arg" in
        --reopen)  REOPEN=1 ;;
        -h|--help) sed -n '2,12p' "$0"; exit 0 ;;
        *)         echo "Unknown option: $arg (try --help)" >&2; exit 2 ;;
    esac
done

log() { printf '\033[1;34m==>\033[0m %s\n' "$*"; }

notify() {
    osascript \
        -e 'on run argv' \
        -e 'display notification (item 2 of argv) with title (item 1 of argv) sound name "Glass"' \
        -e 'end run' \
        -- "$1" "$2" >/dev/null 2>&1 || true
}

is_running() {
    [ "$(osascript -e "application \"$1\" is running" 2>/dev/null || echo false)" = "true" ]
}

OLLAMA="$(command -v ollama || true)"
[ -n "$OLLAMA" ] || OLLAMA="/Applications/Ollama.app/Contents/Resources/ollama"

ollama_gone() {
    ! pgrep -x Ollama >/dev/null 2>&1 && ! pgrep -f "ollama serve" >/dev/null 2>&1
}

# 1. Unload models. `ollama ps` lists loaded models, the first column is the name.
if ! ollama_gone && [ -x "$OLLAMA" ]; then
    for model in $("$OLLAMA" ps 2>/dev/null | awk 'NR>1 {print $1}'); do
        log "Unloading $model"
        "$OLLAMA" stop "$model" || true
    done
fi

# 2. Quit Ollama: polite AppleScript quit first, then SIGTERM, then SIGKILL.
if ollama_gone; then
    log "Ollama was not running"
else
    log "Quitting Ollama"
    osascript -e 'tell application "Ollama" to quit' >/dev/null 2>&1 || true
    for ((i = 0; i < 10; i++)); do ollama_gone && break; sleep 1; done
    if ! ollama_gone; then
        log "Ollama ignored the quit request, stopping the process"
        pkill -x Ollama || true
        pkill -f "ollama serve" || true
        for ((i = 0; i < 10; i++)); do ollama_gone && break; sleep 1; done
    fi
    ollama_gone || pkill -9 -f "ollama serve" || true
fi

# 3. Optionally bring the apps back (open -a on a running app just focuses it).
if [ "$REOPEN" -eq 1 ]; then
    for app in "${APPS_TO_REOPEN[@]}"; do
        log "Opening $app"
        open -a "$app" || true
    done
fi

notify "Ollama: stopped" "Models unloaded and Ollama closed. Memory is free again."
log "Done"
