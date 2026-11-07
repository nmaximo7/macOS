#!/bin/bash
# =============================================================================
# searx.sh - install, update, start and STOP your own SearXNG (a private search engine)
# =============================================================================
#
# SearXNG asks Google, Bing, DuckDuckGo, Wikipedia... for you and returns the merged answer
# without trackers. Here it runs in Docker, reachable ONLY from this Mac:
#
#     http://127.0.0.1:8080
#
# USAGE
#   searx.sh install        brew-install Docker Desktop if missing, write the config, pull the image
#   searx.sh start          start Docker (if needed) and SearXNG, wait until it answers, self-test
#   searx.sh stop           stop SearXNG; quit Docker Desktop too, but ONLY if this script launched it
#   searx.sh stop --keep-docker     stop SearXNG, leave Docker Desktop running
#   searx.sh stop --quit-docker     stop SearXNG and always quit Docker Desktop (unless other
#                                   containers are running)
#   searx.sh restart        stop + start
#   searx.sh update         newest SearXNG image (and Docker Desktop with --docker), recreate
#   searx.sh status         is Docker up? is SearXNG up? does JSON search work?
#   searx.sh test           run one JSON search and show the first results
#   searx.sh logs           follow the container log (Ctrl-C to leave)
#   searx.sh paths          where everything lives
#   searx.sh help
#
# DIFFERENCES FROM THE SIMPLE SCRIPT YOU SKETCHED (and why)
#   * settings.yml enables the JSON format. SearXNG answers HTTP 403 to ?format=json unless
#     `search: formats: [html, json]` is set, so the plain compose file would fail.
#     The limiter (bot protection for public servers) is switched off: it also blocks scripts,
#     and this instance is private.
#   * The port is published as 127.0.0.1:8080, not 8080: without "127.0.0.1" every device on your
#     Wi-Fi could use your search engine.
#   * No `restart: unless-stopped`: you want it to cost nothing when you are not using it.
#   * Files live in ~/.local/share/searxng (not in whatever folder you ran the script from).
#     The config is only written when missing, so your own edits survive updates.
#   * `brew install --cask docker` only when Docker is not installed (brew update is slow).
#   * Waiting for Docker has a time limit (the first launch asks for your password/licence and
#     the simple loop would wait forever).
#   * stop: `docker compose down`, then quits Docker Desktop if (and only if) this script
#     started it and nothing else is running in it.
#
# SETTINGS: environment variables, or NAME="value" lines in searx.conf next to this script.
#   SEARX_PORT=8080            SEARX_HOME=~/.local/share/searxng
#   SEARX_IMAGE=searxng/searxng:latest      SEARX_MEMORY=1g      SEARX_CPUS=2
#   DOCKER_WAIT=240            seconds to wait for Docker to start
#   SEARX_WAIT=120             seconds to wait for SearXNG to answer
#
# Works with the bash 3.2 that macOS ships. Run it as `bash searx.sh ...` or `./searx.sh ...`
# =============================================================================

# `sh searx.sh` runs bash in POSIX mode on macOS: restart under real bash (see maintain-mac.sh).
if [ -z "${BASH_VERSION:-}" ] || set -o 2>/dev/null | grep -Eq 'posix[[:space:]]+on'; then
  exec /bin/bash "$0" "$@"
fi

set -u
set -o pipefail

# Docker Desktop puts its `docker` command in one of these (a script started from Raycast or
# launchd has a very short PATH and would not find it).
PATH="$PATH:/usr/local/bin:/opt/homebrew/bin:$HOME/.docker/bin:/Applications/Docker.app/Contents/Resources/bin"
export PATH

# ----------------------------------------------------------------------------
# Settings
# ----------------------------------------------------------------------------
_src="$0"
while [ -L "$_src" ]; do
  _dir="$(cd "$(dirname "$_src")" && pwd)"
  _src="$(readlink "$_src")"
  case "$_src" in /*) ;; *) _src="$_dir/$_src" ;; esac
done
SCRIPT_DIR="$(cd "$(dirname "$_src")" && pwd)"
unset _src _dir

CONF_FILE="${SEARX_CONF:-$SCRIPT_DIR/searx.conf}"
# shellcheck disable=SC1090
[ -f "$CONF_FILE" ] && . "$CONF_FILE"

: "${SEARX_PORT:=8080}"
: "${SEARX_HOME:=$HOME/.local/share/searxng}"
: "${SEARX_IMAGE:=searxng/searxng:latest}"
: "${SEARX_MEMORY:=1g}"
: "${SEARX_CPUS:=2}"
: "${DOCKER_WAIT:=240}"
: "${SEARX_WAIT:=120}"
: "${SEARX_TEST_QUERY:=free software}"

CONTAINER="searxng"
COMPOSE_FILE="$SEARX_HOME/docker-compose.yml"
CONFIG_DIR="$SEARX_HOME/config"
SETTINGS_FILE="$CONFIG_DIR/settings.yml"
MARKER="$SEARX_HOME/.docker-started-by-searx.sh"   # exists = WE launched Docker Desktop
BASE="http://127.0.0.1:$SEARX_PORT"

# ----------------------------------------------------------------------------
# Output helpers
# ----------------------------------------------------------------------------
if [ -t 1 ] && [ -z "${NO_COLOR:-}" ]; then
  RED=$'\033[31m'; GREEN=$'\033[32m'; YELLOW=$'\033[33m'; DIM=$'\033[2m'; RESET=$'\033[0m'
else
  RED=""; GREEN=""; YELLOW=""; DIM=""; RESET=""
fi
info() { printf '%s\n' "$*"; }
good() { printf '%s✔ %s%s\n' "$GREEN" "$*" "$RESET"; }
warn() { printf '%s! %s%s\n' "$YELLOW" "$*" "$RESET" >&2; }
bad()  { printf '%s✗ %s%s\n' "$RED" "$*" "$RESET" >&2; }
die()  { bad "$*"; exit 1; }

have() { command -v "$1" >/dev/null 2>&1; }

# ----------------------------------------------------------------------------
# Docker helpers
# ----------------------------------------------------------------------------
docker_installed() { have docker || [ -d /Applications/Docker.app ]; }
docker_ready() { have docker && docker info >/dev/null 2>&1; }

# `docker compose` (plugin, what Docker Desktop ships) or the old `docker-compose`.
compose() {
  if docker compose version >/dev/null 2>&1; then
    docker compose -f "$COMPOSE_FILE" "$@"
  elif have docker-compose; then
    docker-compose -f "$COMPOSE_FILE" "$@"
  else
    die "neither 'docker compose' nor 'docker-compose' is available"
  fi
}

install_docker() {
  if docker_installed; then
    good "Docker is already installed"
    return 0
  fi
  have brew || die "Homebrew is not installed (https://brew.sh): install it, or install Docker Desktop by hand"
  info "Installing Docker Desktop with Homebrew (this asks for your password once)..."
  brew update && brew install --cask docker || die "brew could not install Docker Desktop"
  good "Docker Desktop installed"
}

# Start Docker Desktop (unless a Docker daemon already answers: Colima, OrbStack, Docker Desktop).
ensure_docker() {
  docker_installed || die "Docker is not installed. Run:  searx.sh install"
  if docker_ready; then
    return 0
  fi
  if [ -d /Applications/Docker.app ]; then
    info "Starting Docker Desktop (in the background)..."
    open -g -a Docker || die "could not open Docker Desktop"
    mkdir -p "$SEARX_HOME" && : > "$MARKER"   # remember: WE launched it, so WE may quit it
  else
    die "the Docker daemon is not running and Docker.app was not found: start your Docker runtime (colima start, OrbStack...)"
  fi
  info "Waiting for Docker to start (up to ${DOCKER_WAIT}s; the very first launch may ask you to accept the licence or type your password)..."
  local waited=0
  while ! docker info >/dev/null 2>&1; do
    sleep 2
    waited=$((waited + 2))
    if [ "$waited" -ge "$DOCKER_WAIT" ]; then
      die "Docker did not start within ${DOCKER_WAIT}s. Open Docker Desktop once by hand, accept its prompts, then run this again."
    fi
  done
  good "Docker is running"
}

# ----------------------------------------------------------------------------
# Configuration files (written only when missing)
# ----------------------------------------------------------------------------
write_compose() {
  mkdir -p "$SEARX_HOME" "$CONFIG_DIR"
  cat > "$COMPOSE_FILE" <<EOF
# Written by searx.sh. Safe to edit; delete it to have it rewritten.
services:
  searxng:
    image: $SEARX_IMAGE
    container_name: $CONTAINER
    ports:
      - "127.0.0.1:$SEARX_PORT:8080"   # only this Mac can connect
    volumes:
      - ./config:/etc/searxng
      - searxng-cache:/var/cache/searxng
    environment:
      - SEARXNG_BASE_URL=http://127.0.0.1:$SEARX_PORT/
      - BASE_URL=http://127.0.0.1:$SEARX_PORT/
    mem_limit: $SEARX_MEMORY
    cpus: $SEARX_CPUS
    restart: "no"   # no auto-restart: it should cost nothing when you are not using it
volumes:
  searxng-cache:
EOF
}

new_secret() {
  if have openssl; then openssl rand -hex 32
  else LC_ALL=C tr -dc 'a-f0-9' </dev/urandom | head -c 64; fi
}

write_settings() {
  mkdir -p "$CONFIG_DIR"
  cat > "$SETTINGS_FILE" <<EOF
# Written by searx.sh. Everything not listed here keeps SearXNG's defaults.
use_default_settings: true

general:
  instance_name: "my private search"

search:
  safe_search: 0
  formats:        # JSON must be listed, or  ?format=json  answers HTTP 403
    - html
    - json

server:
  secret_key: "$(new_secret)"
  limiter: false        # bot protection for PUBLIC servers; it would also block your scripts
  image_proxy: false
EOF
}

# JSON output is the one setting the Python code cannot work without: check it on every start.
settings_have_json() { [ -f "$SETTINGS_FILE" ] && grep -Eq '^[[:space:]]*-[[:space:]]*json[[:space:]]*$' "$SETTINGS_FILE"; }

ensure_config() {
  mkdir -p "$SEARX_HOME" "$CONFIG_DIR"
  [ -f "$COMPOSE_FILE" ] || { write_compose; info "wrote $COMPOSE_FILE"; }
  if [ ! -f "$SETTINGS_FILE" ]; then
    write_settings; info "wrote $SETTINGS_FILE"
  elif ! settings_have_json; then
    warn "$SETTINGS_FILE does not list the json format: searches from Python will get HTTP 403."
    warn "Add   - json   under   search: formats:   (or delete the file and run  searx.sh install)."
  fi
  # The container user must be able to read the config (a bind mount keeps your permissions).
  chmod 755 "$CONFIG_DIR" 2>/dev/null; chmod 644 "$SETTINGS_FILE" 2>/dev/null
  return 0
}

# ----------------------------------------------------------------------------
# Is SearXNG answering? Does JSON work?
# ----------------------------------------------------------------------------
searx_up() { curl -fsS -m 3 "$BASE/healthz" >/dev/null 2>&1 || curl -fsS -m 3 -o /dev/null "$BASE/" 2>/dev/null; }

wait_for_searx() {
  local waited=0
  info "Waiting for SearXNG to answer (up to ${SEARX_WAIT}s)..."
  while ! searx_up; do
    sleep 2
    waited=$((waited + 2))
    if [ "$waited" -ge "$SEARX_WAIT" ]; then
      bad "SearXNG did not answer within ${SEARX_WAIT}s. Look at:  searx.sh logs"
      return 1
    fi
  done
  good "SearXNG answers at $BASE"
}

# Returns 0 and prints a few results when JSON search works; explains the usual causes otherwise.
# (No Python here: on a fresh Mac `python3` can pop up an Xcode installer dialog.)
json_test() {
  local out code n
  out=$(mktemp "${TMPDIR:-/tmp}/searx-test.XXXXXX")
  code=$(curl -sS -m 40 -o "$out" -w '%{http_code}' -G "$BASE/search" \
         --data-urlencode "q=$SEARX_TEST_QUERY" --data-urlencode "format=json" 2>/dev/null) || code="000"
  case "$code" in
    200)
      if ! grep -q '"results"' "$out"; then
        rm -f "$out"; bad "the answer from $BASE was not SearXNG JSON"; return 1
      fi
      n=$(grep -o '"url": *"http' "$out" | wc -l | tr -d ' ')
      if [ "${n:-0}" -gt 0 ]; then
        good "JSON search works ($n result(s) for \"$SEARX_TEST_QUERY\")"
        grep -o '"title": *"[^"]*"' "$out" | head -3 | sed 's/^"title": *"/   - /; s/"$//'
      else
        warn "JSON works but there were no results (engines blocked or no internet?); try again in a minute"
      fi
      rm -f "$out"; return 0 ;;
    403) rm -f "$out"; bad "HTTP 403: the json format is not enabled in $SETTINGS_FILE (search: formats: - json), then: searx.sh restart"; return 1 ;;
    429) rm -f "$out"; bad "HTTP 429: the limiter is on. Set  server: limiter: false  in $SETTINGS_FILE, then: searx.sh restart"; return 1 ;;
    000) rm -f "$out"; bad "no answer from $BASE (is it running?  searx.sh status)"; return 1 ;;
    *)   rm -f "$out"; bad "unexpected HTTP $code from $BASE"; return 1 ;;
  esac
}

# ----------------------------------------------------------------------------
# Commands
# ----------------------------------------------------------------------------
cmd_install() {
  install_docker
  ensure_config
  ensure_docker
  info "Downloading the SearXNG image (once; a few hundred MB)..."
  compose pull || die "could not download $SEARX_IMAGE"
  good "Installed. Start it with:  searx.sh start"
}

# A container that was killed when Docker Desktop quit or crashed can be left half-removed; Docker
# then refuses to start it with "RWLayer of container ... is unexpectedly nil". Our container is
# disposable (config is a bind mount, the cache a named volume), so before starting we remove any
# leftover that is NOT running, and if starting still fails we retry once from a clean slate.
remove_stale_container() {
  docker ps -a --format '{{.Names}}' 2>/dev/null | grep -qx "$CONTAINER" || return 0
  docker ps --format '{{.Names}}' 2>/dev/null | grep -qx "$CONTAINER" && return 0   # running: leave it
  warn "removing a leftover '$CONTAINER' container from an earlier run"
  docker rm -f "$CONTAINER" >/dev/null 2>&1 && return 0
  compose down --remove-orphans >/dev/null 2>&1
  docker ps -a --format '{{.Names}}' 2>/dev/null | grep -qx "$CONTAINER" || return 0
  # Cannot remove it: move it out of the way so a new one can take the name.
  docker rename "$CONTAINER" "$CONTAINER-stale-$(date +%s)" >/dev/null 2>&1
  return 0
}

compose_up() {   # extra arguments (e.g. --force-recreate) go to `docker compose up -d`
  remove_stale_container
  compose up -d "$@" && return 0
  warn "docker compose up failed; cleaning up and retrying once..."
  docker rm -f "$CONTAINER" >/dev/null 2>&1
  compose down --remove-orphans >/dev/null 2>&1
  compose up -d "$@" && return 0
  bad "SearXNG could not be started."
  info "  If the message above mentions 'RWLayer ... unexpectedly nil', Docker's own storage has a damaged"
  info "  container record. In this order:"
  info "    1) Quit and reopen Docker Desktop, then:  searx.sh start"
  info "    2) docker rm -f $CONTAINER ; docker container prune -f ; searx.sh start"
  info "    3) Last resort (deletes ALL your Docker containers and images): Docker Desktop >"
  info "       Troubleshoot (bug icon) > Clean / Purge data, then:  searx.sh install"
  return 1
}

cmd_start() {
  have curl || die "curl is needed"
  ensure_config
  ensure_docker
  if searx_up; then
    good "SearXNG is already running at $BASE"
    return 0
  fi
  info "Starting SearXNG..."
  compose_up || exit 1
  wait_for_searx || exit 1
  json_test || exit 1
  info "${DIM}Stop it when you are done:  searx.sh stop${RESET}"
}

stop_container() {
  if docker_ready; then
    if [ -f "$COMPOSE_FILE" ]; then
      compose down >/dev/null 2>&1 && good "SearXNG stopped (container removed; image and config kept)" \
        || warn "docker compose down reported a problem"
    else
      docker rm -f "$CONTAINER" >/dev/null 2>&1 && good "SearXNG stopped"
    fi
  else
    info "Docker is not running: nothing to stop."
  fi
}

# Quit Docker Desktop? Never when something else runs in it; by default only when WE started it.
#   mode: auto = only if the marker says we launched it;  quit = always;  keep = never
maybe_quit_docker() {
  local mode="$1" others=""
  case "$mode" in
    keep) return 0 ;;
    auto) [ -f "$MARKER" ] || return 0 ;;
  esac
  docker_ready && others="$(docker ps -q 2>/dev/null)"
  if [ -n "$others" ]; then
    warn "other containers are still running: Docker Desktop stays open"
    return 0
  fi
  if pgrep -f "Docker.app/Contents" >/dev/null 2>&1; then
    info "Quitting Docker Desktop..."
    osascript -e 'quit app "Docker"' >/dev/null 2>&1 || warn "could not ask Docker Desktop to quit"
    local waited=0
    while docker info >/dev/null 2>&1 && [ "$waited" -lt 60 ]; do sleep 2; waited=$((waited + 2)); done
    good "Docker Desktop quit"
  fi
  rm -f "$MARKER"
}

cmd_stop() {
  local mode="auto"
  case "${1:-}" in
    --keep-docker) mode="keep" ;;
    --quit-docker) mode="quit" ;;
    "") ;;
    *) die "unknown option for stop: $1" ;;
  esac
  stop_container
  maybe_quit_docker "$mode"
}

cmd_update() {
  local with_docker=0
  [ "${1:-}" = "--docker" ] && with_docker=1
  have brew && { info "brew update..."; brew update >/dev/null 2>&1 || warn "brew update failed"; }
  if [ "$with_docker" = 1 ]; then
    have brew && brew upgrade --cask docker || warn "could not upgrade Docker Desktop"
  fi
  ensure_config
  ensure_docker
  info "Pulling the newest image..."
  compose pull || die "pull failed"
  compose_up --force-recreate || exit 1
  docker image prune -f >/dev/null 2>&1   # only dangling (unused) layers
  wait_for_searx || exit 1
  json_test || exit 1
  good "SearXNG updated and running"
}

cmd_status() {
  if docker_ready; then good "Docker is running"; else warn "Docker is not running"; fi
  if docker_ready && docker ps --format '{{.Names}}' 2>/dev/null | grep -qx "$CONTAINER"; then
    good "container '$CONTAINER' is up"
  else
    info "container '$CONTAINER' is not running"
  fi
  if searx_up; then good "SearXNG answers at $BASE"; json_test; else info "SearXNG does not answer at $BASE"; return 1; fi
}

cmd_test() { searx_up || die "SearXNG does not answer at $BASE (searx.sh start)"; json_test; }
cmd_logs() { docker_ready || die "Docker is not running"; compose logs -f --tail 100; }

cmd_paths() {
  info "home:      $SEARX_HOME"
  info "compose:   $COMPOSE_FILE"
  info "settings:  $SETTINGS_FILE"
  info "url:       $BASE"
  info "marker:    $MARKER $([ -f "$MARKER" ] && echo '(present: this script launched Docker Desktop)')"
  info "conf:      $CONF_FILE $([ -f "$CONF_FILE" ] || echo '(not present, defaults used)')"
}

usage() { awk 'NR > 1 && /^#/ { sub(/^# ?/, ""); print; next } NR > 1 { exit }' "$0"; }

case "${1:-help}" in
  install)        cmd_install ;;
  start)          cmd_start ;;
  stop)           shift; cmd_stop "${1:-}" ;;
  restart)        stop_container; cmd_start ;;
  update)         shift; cmd_update "${1:-}" ;;
  status)         cmd_status ;;
  test)           cmd_test ;;
  logs)           cmd_logs ;;
  paths)          cmd_paths ;;
  help|-h|--help) usage ;;
  *)              bad "unknown command: $1"; usage; exit 2 ;;
esac
