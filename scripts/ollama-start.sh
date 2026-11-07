#!/usr/bin/env bash
# =============================================================================
# ollama-start.sh: get the Mac ready for local AI (Ollama + Continue)
#
#   1. Set the Ollama server options (launchctl setenv) and restart Ollama
#   2. Quit the memory-hungry apps: Zen, Obsidian, Passwords, Safari
#   3. Load the chat model (and the small autocomplete model) into memory
#   4. Check it runs 100% on the GPU and send a macOS notification
#
# Usage:   ollama-start.sh [--force] [--keep-apps]
#   --force       if an app refuses to quit within 15 s, kill it (unsaved work is lost!)
#   --keep-apps   skip step 2 (do not quit any app)
# Override the model for one run:   MODEL=qwen3.6:27b ollama-start.sh
# =============================================================================
set -euo pipefail

# ---------------------------------------------------------------------------
# CONFIG: the only part you normally edit
# ---------------------------------------------------------------------------
MODEL="${MODEL:-qwen3.8:27b}"                 # chat model. MUST match `model:` in ~/.continue/config.yaml
AUTOCOMPLETE_MODEL="qwen2.5-coder:1.5b"       # small model for tab autocomplete (~1 GB)
NUM_CTX="${NUM_CTX:-16384}"                   # context window. MUST match `contextLength:` in config.yaml
KEEP_ALIVE="30m"                              # unload an idle model after this long (frees ~18 GB)
APPS_TO_QUIT=("Zen" "Obsidian" "Passwords" "Safari")   # names as shown in /Applications
OLLAMA_HOST_URL="http://localhost:11434"
CONTINUE_CFG="$HOME/.continue/config.yaml"

# ---------------------------------------------------------------------------
# OPTIONS
# ---------------------------------------------------------------------------
FORCE=0
KEEP_APPS=0
for arg in "$@"; do
    case "$arg" in
        --force)      FORCE=1 ;;
        --keep-apps)  KEEP_APPS=1 ;;
        -h|--help)    sed -n '2,15p' "$0"; exit 0 ;;
        *)            echo "Unknown option: $arg (try --help)" >&2; exit 2 ;;
    esac
done

# ---------------------------------------------------------------------------
# HELPERS
# ---------------------------------------------------------------------------
log()  { printf '\033[1;34m==>\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33mwarning:\033[0m %s\n' "$*" >&2; }

# notify <title> <message>: macOS notification with a sound.
# The text is passed to AppleScript as arguments (not pasted into the code), so quotes in
# the message can't break it.
notify() {
    osascript \
        -e 'on run argv' \
        -e 'display notification (item 2 of argv) with title (item 1 of argv) sound name "Glass"' \
        -e 'end run' \
        -- "$1" "$2" >/dev/null 2>&1 || true
}

die() {
    printf '\033[1;31merror:\033[0m %s\n' "$*" >&2
    notify "Ollama: setup failed" "$*"
    exit 1
}

# is_running <App Name>: true if the app is running. Asking AppleScript "is running"
# never launches the app, unlike telling it to do something.
is_running() {
    [ "$(osascript -e "application \"$1\" is running" 2>/dev/null || echo false)" = "true" ]
}

# wait_until_closed <App Name> <seconds>
wait_until_closed() {
    local i
    for ((i = 0; i < $2; i++)); do
        is_running "$1" || return 0
        sleep 1
    done
    return 1
}

STILL_OPEN=()

# quit_app <App Name>: graceful quit (like Cmd+Q), then optionally a hard kill.
quit_app() {
    local app="$1"
    if ! is_running "$app"; then
        log "$app: not running"
        return 0
    fi
    log "$app: quitting"
    osascript -e "tell application \"$app\" to quit" >/dev/null 2>&1 || true
    if wait_until_closed "$app" 15; then
        log "$app: closed"
        return 0
    fi
    if [ "$FORCE" -eq 1 ]; then
        warn "$app did not quit, killing it (--force)"
        pkill -f "$app.app/Contents/MacOS" || true
        sleep 1
        is_running "$app" || return 0
    fi
    warn "$app is still open (an unsaved-changes dialog may be waiting). Close it yourself or use --force."
    STILL_OPEN+=("$app")
}

# ollama_gone: true when neither the menu-bar app (process "Ollama") nor the server
# (process "ollama serve") is running.
ollama_gone() {
    ! pgrep -x Ollama >/dev/null 2>&1 && ! pgrep -f "ollama serve" >/dev/null 2>&1
}

# stop_ollama: quit Ollama and its server, escalating until it is really gone.
# 1) polite AppleScript quit (can silently fail: a pending Automation permission, or a
#    menu-bar app that ignores the request), 2) SIGTERM, 3) SIGKILL.
# Ollama keeps nothing that needs saving, so stopping the process is safe.
stop_ollama() {
    ollama_gone && return 0
    osascript -e 'tell application "Ollama" to quit' >/dev/null 2>&1 || true
    local i
    for ((i = 0; i < 10; i++)); do ollama_gone && return 0; sleep 1; done
    warn "Ollama ignored the quit request, sending SIGTERM"
    pkill -x Ollama || true
    pkill -f "ollama serve" || true
    for ((i = 0; i < 10; i++)); do ollama_gone && return 0; sleep 1; done
    warn "Ollama still running, sending SIGKILL"
    pkill -9 -x Ollama || true
    pkill -9 -f "ollama serve" || true
    sleep 2
    ollama_gone
}

wait_for_server() {
    local i
    for ((i = 0; i < 60; i++)); do
        curl -fsS "$OLLAMA_HOST_URL/api/version" >/dev/null 2>&1 && return 0
        sleep 1
    done
    return 1
}

free_memory() {
    # "System-wide memory free percentage: 62%"  ->  62%
    memory_pressure 2>/dev/null | awk '/free percentage/ {print $5}' || true
}

# ---------------------------------------------------------------------------
# PRE-FLIGHT CHECKS (fail early, before closing anything)
# ---------------------------------------------------------------------------
OLLAMA="$(command -v ollama || true)"
[ -n "$OLLAMA" ] || OLLAMA="/Applications/Ollama.app/Contents/Resources/ollama"
[ -x "$OLLAMA" ] || die "ollama CLI not found. Install it: brew install --cask ollama-app"

# ---------------------------------------------------------------------------
# STEP 1: server options + restart
# ---------------------------------------------------------------------------
# A menu-bar app does not read ~/.zshrc, so options are given to it through launchd.
# They only affect programs started AFTERWARDS, which is why Ollama is restarted below.
# launchd forgets them at reboot, which is why this script exists.
log "Step 1/4: Ollama server options"
launchctl setenv OLLAMA_FLASH_ATTENTION 1       # memory-efficient attention (needed for the next option)
launchctl setenv OLLAMA_KV_CACHE_TYPE q8_0      # context cache in 8-bit: about half the memory
launchctl setenv OLLAMA_KEEP_ALIVE "$KEEP_ALIVE"

if ! ollama_gone; then
    log "Restarting Ollama so it picks up the options"
    stop_ollama || die "Could not stop Ollama. Check: pgrep -lf -i ollama"
fi
open -a Ollama
wait_for_server || die "Ollama server did not start. Open the Ollama app once and re-run."
log "Ollama server is up"

# Make sure the models are on disk BEFORE closing your apps (pulling ~18 GB takes minutes).
have_model() { "$OLLAMA" list | awk 'NR>1 {print $1}' | grep -qx "$1"; }
have_model "$MODEL"              || die "Model $MODEL is not downloaded. Run: ollama pull $MODEL"
have_model "$AUTOCOMPLETE_MODEL" || die "Model $AUTOCOMPLETE_MODEL is not downloaded. Run: ollama pull $AUTOCOMPLETE_MODEL"

# Continue must ask for the SAME model and context size, otherwise Ollama loads a second
# copy (18 GB more) or reloads the model every time you switch between chat and this script.
if [ -f "$CONTINUE_CFG" ]; then
    grep -q "model: $MODEL" "$CONTINUE_CFG" \
        || warn "$CONTINUE_CFG does not use 'model: $MODEL': Continue would load a different model."
    grep -q "contextLength: $NUM_CTX" "$CONTINUE_CFG" \
        || warn "$CONTINUE_CFG does not use 'contextLength: $NUM_CTX': Ollama would reload the model."
else
    warn "$CONTINUE_CFG not found (Continue not configured yet?)"
fi

# ---------------------------------------------------------------------------
# STEP 2: free memory by quitting apps
# ---------------------------------------------------------------------------
if [ "$KEEP_APPS" -eq 1 ]; then
    log "Step 2/4: skipped (--keep-apps)"
else
    log "Step 2/4: quitting apps (free memory before: $(free_memory))"
    for app in "${APPS_TO_QUIT[@]}"; do
        quit_app "$app"
    done
    log "Free memory after: $(free_memory)"
fi

# ---------------------------------------------------------------------------
# STEP 3: load the models into memory
# ---------------------------------------------------------------------------
# A /api/generate request with an EMPTY prompt loads the model and returns immediately,
# without generating text. keep_alive keeps it loaded. num_ctx fixes the context size.
log "Step 3/4: loading $MODEL (context $NUM_CTX), this can take a minute"
curl -fsS --max-time 600 "$OLLAMA_HOST_URL/api/generate" \
    -d "{\"model\":\"$MODEL\",\"prompt\":\"\",\"keep_alive\":\"$KEEP_ALIVE\",\"options\":{\"num_ctx\":$NUM_CTX}}" \
    >/dev/null || die "Could not load $MODEL. Check: ollama ps, and the Ollama menu-bar app."

log "Loading $AUTOCOMPLETE_MODEL (tab autocomplete)"
curl -fsS --max-time 120 "$OLLAMA_HOST_URL/api/generate" \
    -d "{\"model\":\"$AUTOCOMPLETE_MODEL\",\"prompt\":\"\",\"keep_alive\":\"$KEEP_ALIVE\"}" \
    >/dev/null || warn "Could not preload $AUTOCOMPLETE_MODEL (autocomplete will load on first use)"

# ---------------------------------------------------------------------------
# STEP 4: verify and notify
# ---------------------------------------------------------------------------
log "Step 4/4: verifying"
"$OLLAMA" ps

# PROCESSOR must say "100% GPU". A CPU/GPU split means the model does not fully fit and will be slow.
STATUS="ready"
DETAIL="$MODEL loaded, 100% GPU, context $NUM_CTX. Free memory: $(free_memory)."
if ! "$OLLAMA" ps | grep "$MODEL" | grep -q "100% GPU"; then
    STATUS="ready, but slow"
    DETAIL="$MODEL is partly on the CPU. Lower NUM_CTX (and contextLength in Continue) or quit more apps."
    warn "$DETAIL"
fi
if [ "${#STILL_OPEN[@]}" -gt 0 ]; then
    DETAIL="$DETAIL Still open: ${STILL_OPEN[*]}."
fi

log "$DETAIL"
notify "Ollama: $STATUS" "$DETAIL"
