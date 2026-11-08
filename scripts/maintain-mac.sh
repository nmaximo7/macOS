#!/bin/bash
# =============================================================================
# maintain-mac.sh - one-command maintenance for a Mac (macOS, Apple Silicon/Intel)
# =============================================================================
#
# WHAT IT DOES (in this order; every step can be skipped or run alone):
#
#   check      Read-only health report: memory, swap, disk, SMART, battery, security.
#   tm         Start a Time Machine backup (`sudo tmutil startbackup`) and wait for it.
#   backup     rsync  ~/macOS  and  /Volumes/MacDatosMaster  ->  /Volumes/DatosSlave
#              (changed/deleted files are kept in a dated history folder).
#   downloads  Move OLD files from ~/Downloads to a quarantine folder (not deleted yet);
#              delete quarantine batches that are older still.
#   trash      Empty the Trash (via Finder, so every volume's Trash is emptied).
#   junk       Clear BROWSER CACHES and old user logs, with strict safety rules.
#   brew       Update Homebrew, upgrade formulae and casks, repair missing dependencies.
#   pip        Upgrade the Python packages of ~/macOS/myPython SAFELY (pip-compile from
#              requirements.in, run the tests, roll back if they fail).
#   git        git add . / commit (date) / push of ~/macOS, after a secrets check.
#   updates    List macOS and App Store updates (installing macOS updates is opt-in).
#
# SAFE BY DEFAULT: without --run the script only PRINTS what it would do.
#
# USAGE
#   maintain-mac.sh                      # dry run of everything (changes nothing)
#   maintain-mac.sh --run                # do it for real (asks for confirmation)
#   maintain-mac.sh --run --yes          # ...without asking
#   maintain-mac.sh --run --only brew,pip
#   maintain-mac.sh --run --skip tm,backup
#   maintain-mac.sh --list               # list the steps
#   maintain-mac.sh --help
#
# SETTINGS: every variable below can be overridden in maintain-mac.conf, which lives
# NEXT TO THIS SCRIPT (~/macOS/scripts/maintain-mac.conf), or in the environment.
# Plain `NAME=value` lines; nothing needs editing here. Lookup order:
#   1. $MAINTAIN_MAC_CONF   2. <script folder>/maintain-mac.conf   3. ~/.config/maintain-mac.conf
#
# Needs only what macOS already has, plus (optional) Homebrew, git, and a Python
# virtualenv in ~/macOS/myPython/.venv. Compatible with the old bash 3.2 that
# macOS ships as /bin/bash.
# =============================================================================

# ----------------------------------------------------------------------------
# Always run under real bash. On macOS `sh script.sh` is bash in POSIX mode, which
# does not understand `< <(command)` ("syntax error near unexpected token `<'").
# Bash reads a script command by command, so this guard (placed BEFORE any such syntax)
# can re-start the script with bash in time. `sh`, `dash`, `zsh script.sh` all work.
# ----------------------------------------------------------------------------
if [ -z "${BASH_VERSION:-}" ] || set -o 2>/dev/null | grep -Eq 'posix[[:space:]]+on'; then
  exec /bin/bash "$0" "$@"
fi

set -o pipefail
set -u
umask 077

VERSION="1.1.0"
SCRIPT_NAME="maintain-mac"

# ----------------------------------------------------------------------------
# Settings (override in maintain-mac.conf next to this script, or in the environment)
# ----------------------------------------------------------------------------
# Folder of this script, following symlinks (stow may link it). No `readlink -f` on old macOS.
_src="$0"
while [ -L "$_src" ]; do
  _dir="$(cd "$(dirname "$_src")" && pwd)"
  _src="$(readlink "$_src")"
  case "$_src" in /*) ;; *) _src="$_dir/$_src" ;; esac
done
SCRIPT_DIR="$(cd "$(dirname "$_src")" && pwd)"
unset _src _dir

if [ -n "${MAINTAIN_MAC_CONF:-}" ]; then
  CONF_FILE="$MAINTAIN_MAC_CONF"
elif [ -f "$SCRIPT_DIR/maintain-mac.conf" ]; then
  CONF_FILE="$SCRIPT_DIR/maintain-mac.conf"
else
  CONF_FILE="$HOME/.config/maintain-mac.conf"
fi
# shellcheck disable=SC1090
[ -f "$CONF_FILE" ] && . "$CONF_FILE"

: "${DOTFILES:=$HOME/macOS}"                 # your stow/dotfiles git repository
: "${PY_DIR:=$DOTFILES/myPython}"            # the Python project inside it
: "${VOL_MASTER:=/Volumes/MacDatosMaster}"   # first external drive (source)
: "${VOL_SLAVE:=/Volumes/DatosSlave}"     # second external drive (backup target)
: "${DOWNLOADS:=$HOME/Downloads}"

: "${DOWNLOADS_DAYS:=30}"        # files untouched for this many days are quarantined
: "${QUARANTINE_DAYS:=30}"       # quarantine batches older than this are deleted
: "${LOG_DAYS:=30}"              # user logs in ~/Library/Logs older than this are deleted
: "${LOG_KEEP_DAYS:=90}"         # this script's own logs are kept this long
: "${QUIT_BROWSERS:=}"           # comma list of browsers to QUIT before clearing their cache, e.g. "Safari"
: "${CLEAN_XCODE:=0}"            # 1 = also clear Xcode DerivedData (regenerable)
: "${TRASH_ENABLED:=1}"

: "${TM_WAIT:=1}"                # 1 = wait for Time Machine to finish (tmutil --block)
: "${RSYNC_DELETE:=1}"           # 1 = mirror deletions (deleted files go to history)
: "${RSYNC_MAX_DELETE:=500}"     # abort a job that would delete more files than this ("unlimited" = no limit)
: "${HISTORY_DAYS:=60}"          # keep changed/deleted files in the history for N days
: "${RSYNC_EXTRA_EXCLUDES:=}"    # extra patterns, separated by spaces (no spaces inside)

: "${BREW_GREEDY:=0}"            # 1 = also upgrade casks that update themselves
: "${BREW_CLEANUP_DAYS:=30}"     # brew cleanup --prune=N

: "${PIP_UPGRADE:=1}"            # 0 = only check, never upgrade
: "${COMMIT_PREFIX:=maintain-mac:}"
: "${GIT_PULL:=1}"               # 1 = git pull --rebase --autostash before pushing
: "${MAX_FILE_MB:=50}"           # refuse to commit files bigger than this

: "${INSTALL_OS_UPDATES:=0}"     # 1 = run `sudo softwareupdate -i -a` (no restart)
: "${MAS_UPGRADE:=0}"            # 1 = run `mas upgrade` (App Store apps)

: "${DISK_WARN_PCT:=85}"         # warn when a disk is fuller than this
: "${MIN_FREE_GB:=20}"           # ...or has less free space than this
: "${MEM_FREE_WARN_PCT:=15}"     # warn when "memory free percentage" is below this

LOG_DIR="${LOG_DIR:-$HOME/Library/Logs/maintain-mac}"
MM_OS="${MM_OS:-$(uname -s)}"    # tests override this

# ----------------------------------------------------------------------------
# Globals
# ----------------------------------------------------------------------------
DRY_RUN=1
ASSUME_YES=0
NO_SUDO=0
ONLY=""
SKIP=""
LIST_ONLY=0
SHOW_HELP=0

STEP_IDS=(check tm backup downloads trash junk brew pip git updates)
STEP_FUNCS=(step_check step_tm step_backup step_downloads step_trash step_junk step_brew step_pip step_git step_updates)
STEP_TITLES=(
  "System health check"
  "Time Machine backup"
  "Backup to the second external drive"
  "Downloads cleanup (quarantine)"
  "Empty the Trash"
  "Browser caches and old logs"
  "Homebrew update and repair"
  "Python packages (myPython)"
  "Git: commit and push dotfiles"
  "macOS and App Store updates"
)

RESULT_IDS=(); RESULT_STATUS=(); RESULT_SECS=(); RESULT_NOTES=()
NOTE=""
NOTE_FILE=""
SUDO_OK=0
SUDO_KEEPALIVE_PID=""
CAFFEINATE_PID=""
LOCK_DIR=""
START_SECS=$SECONDS
START_FREE_KB=0
USE_COLOR=0
C_RESET=""; C_BOLD=""; C_DIM=""; C_RED=""; C_GREEN=""; C_YELLOW=""; C_BLUE=""

# ----------------------------------------------------------------------------
# Small helpers
# ----------------------------------------------------------------------------
init_colors() {
  if [ -t 1 ] && [ -z "${NO_COLOR:-}" ]; then
    USE_COLOR=1
    C_RESET=$'\033[0m'; C_BOLD=$'\033[1m'; C_DIM=$'\033[2m'
    C_RED=$'\033[31m'; C_GREEN=$'\033[32m'; C_YELLOW=$'\033[33m'; C_BLUE=$'\033[34m'
  fi
}

say()   { printf '%s\n' "$*"; }
info()  { printf '  %s\n' "$*"; }
good()  { printf '  %s✔%s %s\n' "$C_GREEN" "$C_RESET" "$*"; }
warn()  { printf '  %s!%s %s\n' "$C_YELLOW" "$C_RESET" "$*"; }
bad()   { printf '  %s✘%s %s\n' "$C_RED" "$C_RESET" "$*"; }
header() {
  printf '\n%s== [%s] %s ==%s\n' "$C_BOLD$C_BLUE" "$1" "$2" "$C_RESET"
}

have() { command -v "$1" >/dev/null 2>&1; }
is_mac() { [ "$MM_OS" = "Darwin" ]; }

# Run a command that CHANGES something. In dry-run mode it only prints it.
#   act "what it does" command arg...
act() {
  local desc="$1"; shift
  if [ "$DRY_RUN" = 1 ]; then
    printf '  %s[dry-run]%s would: %s\n' "$C_DIM" "$C_RESET" "$desc"
    return 0
  fi
  printf '  → %s\n' "$desc"
  "$@"
}

# Run a command with a time limit (macOS has no `timeout`). Uses timeout/gtimeout when present,
# else perl's alarm. Exit status 124 = timed out. Usage: with_timeout SECONDS command args...
with_timeout() {
  local secs="$1"; shift
  if have timeout;  then timeout "$secs" "$@"; return $?; fi
  if have gtimeout; then gtimeout "$secs" "$@"; return $?; fi
  if have perl; then
    perl -e '$s=shift; $p=fork(); if(!$p){exec @ARGV; exit 127} $SIG{ALRM}=sub{kill "TERM",$p; sleep 2; kill "KILL",$p; $t=1}; alarm $s; waitpid($p,0); exit 124 if $t; exit($? >> 8)' "$secs" "$@"
    return $?
  fi
  "$@"
}

human_kb() {   # 1536 -> "1.5 MB"
  awk -v k="${1:-0}" 'BEGIN {
    if (k >= 1048576) printf "%.1f GB", k/1048576;
    else if (k >= 1024) printf "%.1f MB", k/1024;
    else printf "%d KB", k }'
}

dir_kb() {     # size of a file or folder in KB (0 if unreadable)
  local out
  out=$(du -sk "$1" 2>/dev/null | awk '{print $1}')
  printf '%s' "${out:-0}"
}

free_kb() {    # free space of the volume that holds $1, in KB
  df -Pk "$1" 2>/dev/null | awk 'NR==2 {print $4}'
}

used_kb() {    # space USED on the volume that holds $1, in KB (instant, unlike `du` on a whole disk)
  df -Pk "$1" 2>/dev/null | awk 'NR==2 {print $3}'
}

fmt_secs() {
  local s="$1"
  if [ "$s" -ge 60 ]; then printf '%dm%02ds' $((s / 60)) $((s % 60)); else printf '%ds' "$s"; fi
}

is_mounted() {  # is $1 a real mounted volume (not just a leftover folder)?
  [ "${MM_ASSUME_MOUNTED:-0}" = 1 ] && [ -d "$1" ] && return 0
  [ -d "$1" ] || return 1
  mount | grep -F " on $1 (" >/dev/null 2>&1
}

dev_id() {      # device number of the filesystem that holds $1
  if is_mac; then stat -f '%d' "$1" 2>/dev/null; else stat -c '%d' "$1" 2>/dev/null; fi
}

selected() {    # is step $1 selected by --only / --skip ?
  local id="$1"
  if [ -n "$ONLY" ]; then
    case ",$ONLY," in *",$id,"*) : ;; *) return 1 ;; esac
  fi
  case ",$SKIP," in *",$id,"*) return 1 ;; esac
  return 0
}

app_running() { pgrep -x "$1" >/dev/null 2>&1; }

# ----------------------------------------------------------------------------
# Argument parsing
# ----------------------------------------------------------------------------
usage() {
  cat <<EOF
$SCRIPT_NAME $VERSION - maintenance for your Mac

Usage: $SCRIPT_NAME [options]

  (no options)     dry run of every step: prints what it WOULD do, changes nothing
  --run            do it for real (asks "Continue?" first)
  --yes, -y        do not ask for confirmation (needed when there is no terminal)
  --dry-run        explicit dry run (the default)
  --only a,b       run only these steps
  --skip a,b       run everything except these steps
  --no-sudo        never ask for the administrator password (skips tm / OS updates)
  --allow-big-delete  this run only: no limit on files the backup may delete on the backup drive
                   (use after rsync stopped with "more than 500 files would be deleted")
  --list           show the step names and exit
  --help, -h       this text
  --version        show the version

Steps: ${STEP_IDS[*]}
Config file (optional): $CONF_FILE
Logs: $LOG_DIR
EOF
}

list_steps() {
  local i=0
  while [ "$i" -lt "${#STEP_IDS[@]}" ]; do
    printf '  %-10s %s\n' "${STEP_IDS[$i]}" "${STEP_TITLES[$i]}"
    i=$((i + 1))
  done
}

valid_step() {
  local s
  for s in "${STEP_IDS[@]}"; do [ "$s" = "$1" ] && return 0; done
  return 1
}

validate_list() {   # validate_list "a,b,c" -> exit 2 on unknown name
  local item old_ifs="$IFS"
  IFS=','
  for item in $1; do
    IFS="$old_ifs"
    [ -z "$item" ] && continue
    if ! valid_step "$item"; then
      echo "unknown step: '$item' (valid: ${STEP_IDS[*]})" >&2
      exit 2
    fi
  done
  IFS="$old_ifs"
}

parse_args() {
  while [ $# -gt 0 ]; do
    case "$1" in
      --run)        DRY_RUN=0 ;;
      --dry-run)    DRY_RUN=1 ;;
      --yes|-y)     ASSUME_YES=1 ;;
      --no-sudo)    NO_SUDO=1 ;;
      --allow-big-delete) RSYNC_MAX_DELETE=unlimited ;;
      --only)       shift; [ $# -gt 0 ] || { echo "--only needs a list" >&2; exit 2; }; ONLY="$1" ;;
      --skip)       shift; [ $# -gt 0 ] || { echo "--skip needs a list" >&2; exit 2; }; SKIP="$1" ;;
      --only=*)     ONLY="${1#--only=}" ;;
      --skip=*)     SKIP="${1#--skip=}" ;;
      --list)       LIST_ONLY=1 ;;
      --help|-h)    SHOW_HELP=1 ;;
      --version)    echo "$SCRIPT_NAME $VERSION"; exit 0 ;;
      *)            echo "unknown option: $1 (try --help)" >&2; exit 2 ;;
    esac
    shift
  done
  validate_list "$ONLY"
  validate_list "$SKIP"
}

# ----------------------------------------------------------------------------
# Environment, lock, sudo
# ----------------------------------------------------------------------------
setup_path() {
  PATH="/opt/homebrew/bin:/opt/homebrew/sbin:/usr/local/bin:/usr/local/sbin:/usr/bin:/bin:/usr/sbin:/sbin:${PATH:-}"
  export PATH
}

acquire_lock() {
  LOCK_DIR="${TMPDIR:-/tmp}/maintain-mac.$(id -u).lock"
  if mkdir "$LOCK_DIR" 2>/dev/null; then
    echo "$$" > "$LOCK_DIR/pid"
    return 0
  fi
  local old
  old=$(cat "$LOCK_DIR/pid" 2>/dev/null || echo "")
  if [ -n "$old" ] && kill -0 "$old" 2>/dev/null; then
    return 1
  fi
  rm -rf "$LOCK_DIR"            # stale lock from a crashed run
  mkdir "$LOCK_DIR" 2>/dev/null && echo "$$" > "$LOCK_DIR/pid"
}

cleanup() {
  [ -n "$SUDO_KEEPALIVE_PID" ] && kill "$SUDO_KEEPALIVE_PID" 2>/dev/null
  [ -n "$CAFFEINATE_PID" ] && kill "$CAFFEINATE_PID" 2>/dev/null
  [ -n "$LOCK_DIR" ] && rm -rf "$LOCK_DIR"
  [ -n "$NOTE_FILE" ] && rm -f "$NOTE_FILE"
}

on_interrupt() {
  printf '\n%sInterrupted. Steps already finished stay finished.%s\n' "$C_YELLOW" "$C_RESET"
  exit 130
}

# Ask for the sudo password once and keep the ticket alive while we work.
ensure_sudo() {
  [ "$SUDO_OK" = 1 ] && return 0
  [ "$NO_SUDO" = 1 ] && return 1
  have sudo || return 1
  if sudo -n true 2>/dev/null; then
    SUDO_OK=1
  elif [ -r /dev/tty ] && [ "${MM_NO_TTY:-0}" != 1 ]; then
    info "Administrator password needed (for Time Machine / OS updates):"
    if sudo -v </dev/tty; then SUDO_OK=1; else return 1; fi
  else
    return 1
  fi
  # Output must go to /dev/null: a background job that keeps our stdout open would make `tee` wait for it.
  ( while true; do sudo -n true 2>/dev/null; sleep 50; kill -0 "$$" 2>/dev/null || exit 0; done ) >/dev/null 2>&1 &
  SUDO_KEEPALIVE_PID=$!
  return 0
}

# ----------------------------------------------------------------------------
# STEP: check - read-only system health
# ----------------------------------------------------------------------------
vm_field() {   # vm_field "Pages free" -> number of pages
  printf '%s\n' "$VM_TEXT" | awk -F: -v k="$1" '$1 == k { gsub(/[ .]/, "", $2); print $2 }'
}

check_memory() {
  local total_b page free spec inact wired comp avail_gb used_gb total_gb pct swap used_m rc=0
  total_b=$(sysctl -n hw.memsize 2>/dev/null || echo 0)
  VM_TEXT=$(vm_stat 2>/dev/null || true)
  page=$(printf '%s\n' "$VM_TEXT" | awk '/page size of/ { for (i = 1; i <= NF; i++) if ($i == "of") print $(i + 1) }')
  page=${page:-4096}
  free=$(vm_field "Pages free");               free=${free:-0}
  spec=$(vm_field "Pages speculative");        spec=${spec:-0}
  inact=$(vm_field "Pages inactive");          inact=${inact:-0}
  wired=$(vm_field "Pages wired down");        wired=${wired:-0}
  comp=$(vm_field "Pages occupied by compressor"); comp=${comp:-0}
  total_gb=$(awk -v b="$total_b" 'BEGIN { printf "%.1f", b / 1073741824 }')
  avail_gb=$(awk -v p="$page" -v a="$free" -v b="$inact" -v c="$spec" 'BEGIN { printf "%.1f", (a + b + c) * p / 1073741824 }')
  used_gb=$(awk -v t="$total_gb" -v a="$avail_gb" 'BEGIN { printf "%.1f", t - a }')
  info "Memory: ${total_gb} GB total, about ${avail_gb} GB available (free + inactive + speculative), ${used_gb} GB in use"
  info "        wired $(awk -v p="$page" -v w="$wired" 'BEGIN { printf "%.1f", w * p / 1073741824 }') GB, compressed $(awk -v p="$page" -v w="$comp" 'BEGIN { printf "%.1f", w * p / 1073741824 }') GB"
  pct=$(memory_pressure 2>/dev/null | awk -F': ' '/free percentage/ { gsub(/%/, "", $2); print $2 }')
  if [ -n "$pct" ]; then
    if [ "${pct%.*}" -lt "$MEM_FREE_WARN_PCT" ]; then
      warn "Memory pressure: only ${pct}% free (limit ${MEM_FREE_WARN_PCT}%). Close heavy apps."
      rc=3
    else
      good "Memory pressure OK (${pct}% free)"
    fi
  fi
  swap=$(sysctl -n vm.swapusage 2>/dev/null || true)
  if [ -n "$swap" ]; then
    info "Swap: $swap"
    used_m=$(printf '%s\n' "$swap" | awk '{ for (i = 1; i <= NF; i++) if ($i == "used") { v = $(i + 2); gsub(/M/, "", v); print int(v) } }')
    if [ -n "$used_m" ] && [ "$used_m" -ge 4096 ]; then
      warn "Swap in use is ${used_m} MB: the Mac is short of RAM."
      rc=3
    fi
  fi
  return $rc
}

check_disk_line() {   # check_disk_line "label" "/path"
  local label="$1" path="$2" total avail pct free_gb
  [ -e "$path" ] || return 0
  read -r total avail < <(df -Pk "$path" 2>/dev/null | awk 'NR==2 {print $2, $4}')
  [ -n "${total:-}" ] && [ "$total" -gt 0 ] || return 0
  pct=$(awk -v t="$total" -v a="$avail" 'BEGIN { printf "%d", (t - a) * 100 / t }')
  free_gb=$(awk -v a="$avail" 'BEGIN { printf "%.1f", a / 1048576 }')
  if [ "$pct" -ge "$DISK_WARN_PCT" ] || [ "${free_gb%.*}" -lt "$MIN_FREE_GB" ]; then
    warn "$label: ${pct}% used, ${free_gb} GB free (limits: ${DISK_WARN_PCT}% / ${MIN_FREE_GB} GB)"
    return 3
  fi
  good "$label: ${pct}% used, ${free_gb} GB free"
  return 0
}

check_disks() {
  local rc=0 data="/"
  [ -d /System/Volumes/Data ] && data="/System/Volumes/Data"
  check_disk_line "Internal disk" "$data" || rc=3
  if is_mounted "$VOL_MASTER"; then check_disk_line "$VOL_MASTER" "$VOL_MASTER" || rc=3
  else warn "$VOL_MASTER is not mounted"; rc=3; fi
  if is_mounted "$VOL_SLAVE"; then check_disk_line "$VOL_SLAVE" "$VOL_SLAVE" || rc=3
  else warn "$VOL_SLAVE is not mounted"; rc=3; fi
  info "(macOS may also count 'purgeable' space as used; Settings > General > Storage shows the real figure.)"
  return $rc
}

step_check() {
  local rc=0 smart batt
  if is_mac; then
    info "$(sw_vers -productName 2>/dev/null) $(sw_vers -productVersion 2>/dev/null) ($(sw_vers -buildVersion 2>/dev/null)), $(uname -m)"
  fi
  info "Uptime:$(uptime | sed 's/^.*up/ up/')"
  check_memory || rc=3
  check_disks  || rc=3
  if have diskutil; then
    smart=$(diskutil info / 2>/dev/null | awk -F: '/SMART Status/ { gsub(/^ +/, "", $2); print $2 }')
    [ -n "$smart" ] && { if [ "$smart" = "Verified" ] || [ "$smart" = "Not Supported" ]; then good "Disk SMART status: $smart"; else warn "Disk SMART status: $smart"; rc=3; fi; }
  fi
  if have pmset; then
    batt=$(pmset -g batt 2>/dev/null | tail -1)
    case "$batt" in *InternalBattery*) info "Battery: $batt" ;; esac
  fi
  if have system_profiler; then
    system_profiler SPPowerDataType 2>/dev/null | awk '/Cycle Count|Condition|Maximum Capacity/ { sub(/^ +/, ""); print "  Battery " $0 }'
  fi
  if have tmutil; then
    local last
    last=$(tmutil latestbackup 2>/dev/null | tail -1)
    info "Last Time Machine backup: ${last:-none found}"
  fi
  if have fdesetup; then info "FileVault: $(fdesetup status 2>/dev/null | head -1)"; fi
  if have csrutil;  then info "SIP: $(csrutil status 2>/dev/null | sed 's/System Integrity Protection status: //')"; fi
  if have spctl;    then info "Gatekeeper: $(spctl --status 2>/dev/null)"; fi
  if [ -x /usr/libexec/ApplicationFirewall/socketfilterfw ]; then
    info "Firewall: $(/usr/libexec/ApplicationFirewall/socketfilterfw --getglobalstate 2>/dev/null)"
  fi
  if have ps; then
    info "Top 5 processes by memory:"
    ps -Ao pid,pmem,comm -m 2>/dev/null | head -6 | sed 's/^/      /'
  fi
  return $rc
}

# ----------------------------------------------------------------------------
# STEP: tm - Time Machine
# ----------------------------------------------------------------------------
step_tm() {
  have tmutil || { NOTE="tmutil not found"; return 2; }
  local dest status args
  dest=$(tmutil destinationinfo 2>&1)
  case "$dest" in
    *"No destinations configured"*|"")
      NOTE="no Time Machine destination configured (System Settings > General > Time Machine)"
      warn "$NOTE"; return 3 ;;
  esac
  info "Destination: $(printf '%s\n' "$dest" | awk -F': *' '/^Name/ { print $2; exit }')"
  status=$(tmutil status 2>/dev/null)
  case "$status" in
    *"Running = 1"*) NOTE="a backup is already running"; good "$NOTE"; return 0 ;;
  esac
  if [ "$DRY_RUN" = 0 ] && ! ensure_sudo; then
    NOTE="no administrator rights (run it in a terminal, not from a scheduler)"
    warn "$NOTE"; return 2
  fi
  args="--auto"
  [ "$TM_WAIT" = 1 ] && args="--auto --block"
  # shellcheck disable=SC2086
  act "sudo tmutil startbackup $args" sudo tmutil startbackup $args || { bad "tmutil failed (does Terminal have Full Disk Access?)"; return 1; }
  return 0
}

# ----------------------------------------------------------------------------
# STEP: backup - rsync to the second external drive
# ----------------------------------------------------------------------------
pick_rsync() {
  if [ -x /opt/homebrew/bin/rsync ]; then RSYNC=/opt/homebrew/bin/rsync
  elif [ -x /usr/local/bin/rsync ]; then RSYNC=/usr/local/bin/rsync
  else RSYNC=$(command -v rsync || true); fi
}

# rsync_job "label" "source/" "destination/" "history-dir"
rsync_job() {
  local label="$1" src="$2" dst="$3" hist="$4" stamp out rc excl
  local args=(-a --partial --stats)
  stamp=$(date '+%Y-%m-%d_%H%M%S')
  # Files that macOS or the build tools regenerate; no need to back them up.
  # Time Machine data is NEVER copied: a Time Machine backup is made of hard links (every backup
  # "contains" every unchanged file, yet takes no extra space). rsync -a copies each hard link as
  # a full separate file, so 1 TB of Time Machine history becomes several TB on the backup drive
  # and the copy never finishes. Time Machine keeps its own history; it does not need rsync.
  for excl in .Spotlight-V100 .Trashes .fseventsd .TemporaryItems .DocumentRevisions-V100 \
              .PKInstallSandboxManager-SystemSoftware .DS_Store .venv __pycache__ .pytest_cache \
              '._*' Backups.backupdb '*.sparsebundle' '*.backupbundle' .MobileBackups 'com.apple.TimeMachine.*' \
              $RSYNC_EXTRA_EXCLUDES; do
    args+=("--exclude=$excl")
  done
  if [ "$RSYNC_DELETE" = 1 ]; then
    args+=(--delete)
    # RSYNC_MAX_DELETE=500 stops a job that would delete more than 500 files (a safety net against
    # an unmounted or emptied source). "unlimited" (or --allow-big-delete) removes the limit for
    # this run. NOTE: rsync's own --max-delete=0 means "delete nothing", so 0 is not "unlimited".
    case "$RSYNC_MAX_DELETE" in
      unlimited|"") ;;
      *[!0-9]*)     warn "RSYNC_MAX_DELETE must be a number or 'unlimited' (got '$RSYNC_MAX_DELETE'): using 500"
                    args+=(--max-delete=500) ;;
      *)            args+=(--max-delete="$RSYNC_MAX_DELETE") ;;
    esac
  fi
  args+=(--backup "--backup-dir=$hist/$stamp")
  [ "$DRY_RUN" = 1 ] && args+=(-n)
  info "$label:  $src  ->  $dst"
  mkdir -p "$dst" 2>/dev/null || [ "$DRY_RUN" = 1 ] || { bad "cannot create $dst"; return 1; }
  out=$(mktemp "${TMPDIR:-/tmp}/maintain-mac-rsync.XXXXXX")
  # While rsync runs, print a short "still working" line every HEARTBEAT_SECS seconds with how much
  # was written to the backup drive so far. (v1.0.1: this replaces a live progress line that used a
  # pipe through awk; it could leave rsync waiting on a Mac. Plain lines cannot.) The helper stops
  # by itself when this script ends, even after Ctrl-C.
  local hb="" start_used now_used
  if [ "$DRY_RUN" = 0 ] && [ "${HEARTBEAT_SECS:-60}" -gt 0 ] 2>/dev/null; then
    start_used=$(used_kb "$dst"); start_used=${start_used:-0}
    (
      parent=$$; began=$(date +%s)
      while kill -0 "$parent" 2>/dev/null; do
        waited=0   # sleep in 1-second slices so the helper notices at once when the script ends
        while [ "$waited" -lt "${HEARTBEAT_SECS:-60}" ]; do
          sleep 1; waited=$((waited + 1))
          kill -0 "$parent" 2>/dev/null || exit 0
        done
        now_used=$(used_kb "$dst"); now_used=${now_used:-0}
        grew=$(( now_used - start_used )); [ "$grew" -lt 0 ] && grew=0
        printf '      ... still copying %s: %s min, %s more used on the backup drive so far\n' \
          "$label" "$(( ($(date +%s) - began) / 60 ))" "$(human_kb "$grew")"
      done
    ) >&1 2>/dev/null &
    hb=$!
  fi
  "$RSYNC" "${args[@]}" "$src" "$dst" >"$out" 2>&1
  rc=$?
  if [ -n "$hb" ]; then kill "$hb" 2>/dev/null; wait "$hb" 2>/dev/null; fi
  grep -E 'Number of (regular )?files|Number of files transferred|Number of created|Number of deleted|Total transferred file size|Total file size' "$out" | sed 's/^/      /'
  case "$rc" in
    0)  good "$label done$([ "$DRY_RUN" = 1 ] && echo ' (simulation, nothing copied)')" ;;
    24) warn "$label: some files vanished while copying (normal for a live disk)"; rc=3 ;;
    25) bad "$label: STOPPED by the safety limit: more than $RSYNC_MAX_DELETE files on the backup drive would be deleted."
        info "      Why: files were removed from the source (a clean-up?), or the backup drive holds files the source no longer has."
        info "      1) Make sure the source is complete and mounted:  ls \"$src\" | head"
        info "      2) If the deletions are expected, run the backup once without the limit:"
        info "           bash $0 --run --only backup --allow-big-delete"
        info "         (deleted/replaced files are moved to $hist, not lost)"
        rc=1 ;;
    *)  bad "$label: rsync exit code $rc"; tail -5 "$out" | sed 's/^/      /'; rc=1 ;;
  esac
  rm -f "$out"
  # forget history older than HISTORY_DAYS
  if [ "$DRY_RUN" = 0 ] && [ -d "$hist" ]; then
    find "$hist" -mindepth 1 -maxdepth 1 -type d -mtime +"$HISTORY_DAYS" -exec rm -rf {} + 2>/dev/null
  fi
  return $rc
}

step_backup() {
  pick_rsync
  [ -n "${RSYNC:-}" ] || { NOTE="rsync not found"; return 2; }
  is_mounted "$VOL_SLAVE" || { NOTE="backup drive $VOL_SLAVE is not mounted"; warn "$NOTE"; return 2; }
  local rc=0 r slave_dev home_dev dev_id_m
  slave_dev=$(dev_id "$VOL_SLAVE"); home_dev=$(dev_id "$HOME")
  if [ -n "$slave_dev" ] && [ "$slave_dev" = "$home_dev" ]; then
    NOTE="$VOL_SLAVE is on the same disk as your home folder: refusing to 'back up' onto itself"
    bad "$NOTE"; return 1
  fi
  local avail_kb need_kb
  avail_kb=$(free_kb "$VOL_SLAVE")
  local rver
  rver=$("$RSYNC" --version 2>&1 | head -1)
  case "$rver" in
    *openrsync*)
      NOTE="macOS's built-in rsync is 'openrsync', which lacks options this script needs. Run: brew install rsync"
      bad "$NOTE"; return 1 ;;
  esac
  info "rsync: $RSYNC ($rver)"
  info "Free space on backup drive: $(human_kb "${avail_kb:-0}")"
  if [ -d "$DOTFILES" ]; then
    rsync_job "Dotfiles" "$DOTFILES/" "$VOL_SLAVE/macOS-dotfiles/" "$VOL_SLAVE/_history/macOS-dotfiles"
    r=$?; [ "$r" -gt "$rc" ] && rc=$r
  else
    warn "$DOTFILES not found: dotfiles not backed up"; rc=3
  fi
  if is_mounted "$VOL_MASTER"; then
    dev_id_m=$(dev_id "$VOL_MASTER")
    if [ -n "$dev_id_m" ] && [ "$dev_id_m" = "$slave_dev" ]; then
      bad "$VOL_MASTER and $VOL_SLAVE are the same volume"; return 1
    fi
    # Tell the user what is NOT copied, so a smaller backup is not a surprise.
    local skipped="" t
    for t in "$VOL_MASTER"/Backups.backupdb "$VOL_MASTER"/*.sparsebundle "$VOL_MASTER"/*.backupbundle "$VOL_MASTER"/.MobileBackups; do
      [ -e "$t" ] && skipped="$skipped $(basename "$t")"
    done
    if [ -n "$skipped" ]; then
      warn "Time Machine data on $VOL_MASTER is NOT copied:$skipped"
      info "  (Time Machine already keeps that history; copying it with rsync would multiply its size.)"
      info "  So \"Used on $VOL_MASTER\" below includes it, but the backup will be much smaller."
    fi
    need_kb=$(used_kb "$VOL_MASTER")
    info "Used on $VOL_MASTER: $(human_kb "${need_kb:-0}") (the first full copy can take hours; later runs only copy changes)"
    if [ "${need_kb:-0}" -gt "${avail_kb:-0}" ] 2>/dev/null; then
      warn "the backup drive may not have room for a full copy of $VOL_MASTER"
    fi
    rsync_job "MacDatosMaster" "$VOL_MASTER/" "$VOL_SLAVE/MacDatosMaster/" "$VOL_SLAVE/_history/MacDatosMaster"
    r=$?; [ "$r" -gt "$rc" ] && rc=$r
  else
    warn "$VOL_MASTER is not mounted: skipped"; rc=3
  fi
  [ "$rc" = 25 ] && rc=1
  return $rc
}

# ----------------------------------------------------------------------------
# STEP: downloads - two-stage cleanup, nothing is deleted on the first pass
# ----------------------------------------------------------------------------
newest_epoch() {   # newest of birth time, modification time and access time
  local b m a out
  if is_mac; then out=$(stat -f '%B %m %a' "$1" 2>/dev/null); else out=$(stat -c '%W %Y %X' "$1" 2>/dev/null); fi
  [ -n "$out" ] || { echo 0; return; }
  read -r b m a <<<"$out"
  awk -v b="${b:-0}" -v m="${m:-0}" -v a="${a:-0}" 'BEGIN { x = b; if (m > x) x = m; if (a > x) x = a; print x }'
}

step_downloads() {
  [ -d "$DOWNLOADS" ] || { NOTE="$DOWNLOADS does not exist"; return 2; }
  [ -n "$DOWNLOADS" ] && [ "$DOWNLOADS" != "/" ] && [ "$DOWNLOADS" != "$HOME" ] || { bad "unsafe DOWNLOADS=$DOWNLOADS"; return 1; }
  local q="$DOWNLOADS/.cleanup-quarantine" stamp cutoff now f name t total_kb=0 moved=0 kept=0 sz batch purged=0 rc=0
  stamp=$(date '+%Y-%m-%d_%H%M%S')
  now=$(date +%s)
  cutoff=$((now - DOWNLOADS_DAYS * 86400))

  # Stage 2: permanently remove quarantine batches that are old enough.
  if [ -d "$q" ]; then
    while IFS= read -r -d '' batch; do
      sz=$(dir_kb "$batch")
      info "Quarantine batch older than ${QUARANTINE_DAYS} days: $(basename "$batch") ($(human_kb "$sz"))"
      case "$batch" in
        "$q"/?*) act "delete $batch" rm -rf "$batch" || rc=3 ;;
        *) warn "refusing to delete $batch"; rc=3 ;;
      esac
      purged=$((purged + 1))
    done < <(find "$q" -mindepth 1 -maxdepth 1 -type d -mtime +"$QUARANTINE_DAYS" -print0 2>/dev/null)
  fi

  # Stage 1: move old, untouched top-level items to the quarantine.
  while IFS= read -r -d '' f; do
    name=$(basename "$f")
    case "$name" in
      .*|_*|*.download|*.crdownload|*.part|*.partial|*.opdownload) kept=$((kept + 1)); continue ;;
    esac
    t=$(newest_epoch "$f")
    if [ "$t" -gt "$cutoff" ]; then kept=$((kept + 1)); continue; fi
    if [ -d "$f" ] && [ -n "$(find "$f" -type f -mtime -"$DOWNLOADS_DAYS" 2>/dev/null | head -1)" ]; then
      kept=$((kept + 1)); continue     # a folder with recent files inside
    fi
    sz=$(dir_kb "$f")
    total_kb=$((total_kb + sz))
    moved=$((moved + 1))
    if [ "$moved" -le 40 ]; then info "old: $name ($(human_kb "$sz"))"; fi
    if [ "$DRY_RUN" = 0 ]; then
      mkdir -p "$q/$stamp" && mv -n "$f" "$q/$stamp/" || { warn "could not move $name"; rc=3; }
    fi
  done < <(find "$DOWNLOADS" -mindepth 1 -maxdepth 1 -print0 2>/dev/null)

  [ "$moved" -gt 40 ] && info "... and $((moved - 40)) more"
  NOTE="$moved moved to quarantine ($(human_kb "$total_kb")), $kept kept, $purged old batch(es) deleted"
  if [ "$DRY_RUN" = 1 ]; then
    good "would quarantine $moved item(s), $(human_kb "$total_kb"); $kept stay"
  else
    good "$NOTE"
    [ "$moved" -gt 0 ] && info "Recover with:  mv \"$q/$stamp/<name>\" \"$DOWNLOADS/\""
  fi
  return $rc
}

# ----------------------------------------------------------------------------
# STEP: trash
# ----------------------------------------------------------------------------
empty_trash_files() {   # fallback when Finder cannot be scripted
  [ -d "$HOME/.Trash" ] && [ ! -L "$HOME/.Trash" ] || return 0
  find "$HOME/.Trash" -mindepth 1 -maxdepth 1 -exec rm -rf {} + 2>/dev/null
}

empty_trash() {
  if is_mac && have osascript && osascript -e 'tell application "Finder" to empty trash' >/dev/null 2>&1; then
    return 0
  fi
  warn "Finder could not empty the Trash (Automation permission?); deleting ~/.Trash by hand"
  empty_trash_files
}

step_trash() {
  [ "$TRASH_ENABLED" = 1 ] || { NOTE="disabled (TRASH_ENABLED=0)"; return 2; }
  local kb
  kb=$(dir_kb "$HOME/.Trash")
  info "Trash holds about $(human_kb "$kb") (external drives have their own Trash, also emptied by Finder)"
  act "empty the Trash" empty_trash || return 1
  NOTE="about $(human_kb "$kb") in the user Trash"
  return 0
}

# ----------------------------------------------------------------------------
# STEP: junk - browser caches and old logs, with strict safety rules
# ----------------------------------------------------------------------------
# SAFETY RULES (all enforced in code):
#   1. Only these locations may ever be cleaned: folders under ~/Library/Caches,
#      ~/Library/Logs and (opt-in) Xcode DerivedData. Never /System, /Library,
#      Application Support, Preferences, Containers, Mail, Photos, Keychains.
#   2. Only CACHES of browsers: never cookies, history, bookmarks, passwords,
#      sessions, extensions or profiles (those are not in Caches).
#   3. A browser that is running is skipped.
#   4. Symlinks and paths containing ".." are refused; the Caches folder itself
#      is never emptied.
#   5. Logs are deleted only when older than LOG_DAYS days.
is_safe_junk_path() {
  local p="$1"
  [ -n "$HOME" ] && [ "$HOME" != "/" ] || return 1
  case "$p" in *..*) return 1 ;; esac
  [ -d "$p" ] && [ ! -L "$p" ] || return 1
  case "$p" in
    "$HOME/Library/Caches/"?*) return 0 ;;
    "$HOME/Library/Logs/"?*)   return 0 ;;
    "$HOME/Library/Developer/Xcode/DerivedData") [ "$CLEAN_XCODE" = 1 ] && return 0; return 1 ;;
  esac
  return 1
}

# QUIT_BROWSERS="Safari,Google Chrome": browsers this script may quit (politely, like Cmd+Q) so that
# their cache can be cleared. Off by default: quitting closes the windows (Safari and Chrome
# normally reopen them on the next launch).
browser_listed_for_quit() {
  local list
  list=",$(printf '%s' "$QUIT_BROWSERS" | sed 's/ *, */,/g'),"
  case "$list" in *",$1,"*) return 0 ;; *) return 1 ;; esac
}

# quit_browser NAME PROCESS: osascript quit, then wait up to 15 s.
quit_browser() {
  local name="$1" proc="$2" i=0
  act "quit $name (osascript)" osascript -e "quit app \"$name\"" || return 1
  [ "$DRY_RUN" = 1 ] && return 0
  while [ "$i" -lt 15 ]; do
    app_running "$proc" || return 0
    sleep 1; i=$((i + 1))
  done
  return 1
}

clear_dir_contents() {
  find "$1" -mindepth 1 -maxdepth 1 -exec rm -rf {} + 2>/dev/null
}

step_junk() {
  local rc=0 total=0 i=0 name proc path before after freed
  local names=("Safari" "Google Chrome" "Firefox" "Brave" "Microsoft Edge" "Arc" "Vivaldi" "Opera")
  local procs=("Safari" "Google Chrome" "firefox" "Brave Browser" "Microsoft Edge" "Arc" "Vivaldi" "Opera")
  local paths=(
    "$HOME/Library/Caches/com.apple.Safari"
    "$HOME/Library/Caches/Google/Chrome"
    "$HOME/Library/Caches/Firefox/Profiles"
    "$HOME/Library/Caches/BraveSoftware/Brave-Browser"
    "$HOME/Library/Caches/Microsoft Edge"
    "$HOME/Library/Caches/company.thebrowser.Browser"
    "$HOME/Library/Caches/Vivaldi"
    "$HOME/Library/Caches/com.operasoftware.Opera"
  )
  while [ "$i" -lt "${#names[@]}" ]; do
    name="${names[$i]}"; proc="${procs[$i]}"; path="${paths[$i]}"; i=$((i + 1))
    [ -d "$path" ] || continue
    if app_running "$proc"; then
      if browser_listed_for_quit "$name"; then
        quit_browser "$name" "$proc" || { warn "$name did not quit (a dialog may be waiting): cache skipped"; rc=3; continue; }
      else
        warn "$name is running: cache skipped (quit it, or set QUIT_BROWSERS=\"$name\" in maintain-mac.conf to let this script do it)"; rc=3; continue
      fi
    fi
    if ! is_safe_junk_path "$path"; then warn "refused unsafe path: $path"; rc=3; continue; fi
    before=$(dir_kb "$path")
    if act "clear $name cache ($(human_kb "$before"))" clear_dir_contents "$path"; then
      after=$(dir_kb "$path")
      [ "$DRY_RUN" = 1 ] && after=0
      freed=$((before - after)); [ "$freed" -lt 0 ] && freed=0
      total=$((total + freed))
    else
      warn "could not clear all of $name's cache (Terminal needs Full Disk Access for Safari)"; rc=3
    fi
  done

  # Old user logs (not system logs, not this script's own logs).
  local logroot="$HOME/Library/Logs" nlogs lkb
  if [ -d "$logroot" ] && [ ! -L "$logroot" ]; then
    nlogs=$(find "$logroot" -type f -mtime +"$LOG_DAYS" ! -path "$LOG_DIR/*" 2>/dev/null | wc -l | tr -d ' ')
    lkb=$(find "$logroot" -type f -mtime +"$LOG_DAYS" ! -path "$LOG_DIR/*" -exec du -k {} + 2>/dev/null | awk '{s += $1} END {print s + 0}')
    if [ "${nlogs:-0}" -gt 0 ]; then
      act "delete $nlogs log file(s) older than $LOG_DAYS days in ~/Library/Logs ($(human_kb "$lkb"))" \
        find "$logroot" -type f -mtime +"$LOG_DAYS" ! -path "$LOG_DIR/*" -delete
      total=$((total + lkb))
    else
      info "No user logs older than $LOG_DAYS days"
    fi
  fi
  # This script's own logs.
  if [ -d "$LOG_DIR" ] && [ "$DRY_RUN" = 0 ]; then
    find "$LOG_DIR" -type f -name '*.log' -mtime +"$LOG_KEEP_DAYS" -delete 2>/dev/null
  fi

  if [ "$CLEAN_XCODE" = 1 ] && [ -d "$HOME/Library/Developer/Xcode/DerivedData" ]; then
    if app_running "Xcode"; then warn "Xcode is running: DerivedData skipped"; rc=3
    elif is_safe_junk_path "$HOME/Library/Developer/Xcode/DerivedData"; then
      before=$(dir_kb "$HOME/Library/Developer/Xcode/DerivedData")
      act "clear Xcode DerivedData ($(human_kb "$before"))" clear_dir_contents "$HOME/Library/Developer/Xcode/DerivedData"
      total=$((total + before))
    fi
  fi
  NOTE="about $(human_kb "$total") $([ "$DRY_RUN" = 1 ] && echo 'could be freed' || echo 'freed')"
  good "$NOTE"
  return $rc
}

# ----------------------------------------------------------------------------
# STEP: brew
# ----------------------------------------------------------------------------
step_brew() {
  have brew || { NOTE="Homebrew not installed"; return 2; }
  local rc=0 missing deps doctor n rc_doc
  export HOMEBREW_NO_ENV_HINTS=1 HOMEBREW_NO_ANALYTICS=1

  act "brew update" brew update || { bad "brew update failed (network?)"; return 1; }
  [ "$DRY_RUN" = 0 ] && export HOMEBREW_NO_AUTO_UPDATE=1

  info "Outdated formulae:"; brew outdated --formula --quiet 2>/dev/null | sed 's/^/      /'
  local greedy=""; [ "$BREW_GREEDY" = 1 ] && greedy="--greedy"
  info "Outdated casks:";   brew outdated --cask $greedy --quiet 2>/dev/null | sed 's/^/      /'

  act "brew upgrade (formulae)" brew upgrade --formula || { warn "some formulae failed to upgrade"; rc=3; }
  # shellcheck disable=SC2086
  act "brew upgrade --cask $greedy" brew upgrade --cask $greedy || { warn "some casks failed to upgrade"; rc=3; }
  act "brew autoremove (unused dependencies)" brew autoremove || rc=3
  act "brew cleanup --prune=$BREW_CLEANUP_DAYS" brew cleanup --prune="$BREW_CLEANUP_DAYS" || rc=3

  # Repair: install any dependency that is missing.
  missing=$(brew missing 2>/dev/null)
  if [ -n "$missing" ]; then
    warn "Formulae with missing dependencies:"; printf '%s\n' "$missing" | sed 's/^/      /'
    deps=$(printf '%s\n' "$missing" | awk -F: '{ n = split($2, a, " "); for (i = 1; i <= n; i++) print a[i] }' | sort -u | tr '\n' ' ')
    # shellcheck disable=SC2086
    act "brew install $deps" brew install $deps || { bad "could not repair: $deps"; rc=1; }
  else
    good "No missing dependencies"
  fi

  info "brew doctor (up to ${BREW_DOCTOR_TIMEOUT:-120}s) ..."
  doctor=$(with_timeout "${BREW_DOCTOR_TIMEOUT:-120}" brew doctor 2>&1 </dev/null)
  rc_doc=$?
  if [ "$rc_doc" = 124 ]; then
    warn "brew doctor took longer than ${BREW_DOCTOR_TIMEOUT:-120}s: skipped (run it by hand: brew doctor)"
    [ "$rc" = 0 ] && rc=3
  elif [ "$rc_doc" -eq 0 ]; then
    good "brew doctor: Your system is ready to brew"
  else
    n=$(printf '%s\n' "$doctor" | grep -c '^Warning:')
    warn "brew doctor reports $n warning(s); first lines:"
    printf '%s\n' "$doctor" | head -12 | sed 's/^/      /'
    [ "$rc" = 0 ] && rc=3
  fi

  # Informational: what is installed but not in your Brewfile (nothing is removed).
  if [ -f "$DOTFILES/Brewfile" ]; then
    local extra
    info "Comparing installed packages with the Brewfile (up to 120s) ..."
    extra=$(with_timeout 120 brew bundle cleanup --file="$DOTFILES/Brewfile" 2>/dev/null </dev/null | grep -v '^Run `brew bundle cleanup' | head -15)
    if [ -n "$extra" ]; then
      info "Installed but NOT listed in $DOTFILES/Brewfile (nothing is removed; add them or ignore):"
      printf '%s\n' "$extra" | sed 's/^/      /'
    fi
  fi
  return $rc
}

# ----------------------------------------------------------------------------
# STEP: pip - safe upgrade of the project packages
# ----------------------------------------------------------------------------
# Why not `pip freeze > requirements.txt` or "upgrade everything"?
#   * freeze mixes direct and transitive packages, drops your comments and
#     includes tools such as pytest;
#   * upgrading everything can break the project silently;
#   * Homebrew's Python refuses global installs (PEP 668).
# So: re-resolve requirements.in with pip-compile, install into the project's
# venv, run the tests, and roll back requirements.txt if anything fails.
step_pip() {
  [ -d "$PY_DIR" ] || { NOTE="$PY_DIR not found"; return 2; }
  [ -f "$PY_DIR/requirements.in" ] || { NOTE="no requirements.in in $PY_DIR (see the guide)"; warn "$NOTE"; return 2; }
  local vpy="$PY_DIR/.venv/bin/python" rc=0 bak
  cd "$PY_DIR" || return 1

  if ! "$vpy" -c 'import sys' >/dev/null 2>&1; then
    warn "The virtualenv in $PY_DIR/.venv is missing or broken (Homebrew Python upgrades do that)."
    have python3 || { bad "python3 not found"; return 1; }
    act "create a fresh virtualenv with $(python3 --version 2>&1)" python3 -m venv --clear "$PY_DIR/.venv" || return 1
    if [ "$DRY_RUN" = 1 ]; then NOTE="virtualenv would be recreated"; return 3; fi
    act "install the current requirements" "$vpy" -m pip install -q -r requirements.txt pytest || return 1
  fi

  if [ "$PIP_UPGRADE" != 1 ]; then
    info "PIP_UPGRADE=0: only checking"
    "$vpy" -m pip list --outdated 2>/dev/null | sed 's/^/      /'
    return 0
  fi

  act "upgrade pip and pip-tools" "$vpy" -m pip install -q --upgrade pip pip-tools || { bad "cannot upgrade pip/pip-tools"; return 1; }

  if [ "$DRY_RUN" = 1 ]; then
    info "Currently outdated in the venv:"; "$vpy" -m pip list --outdated 2>/dev/null | sed 's/^/      /'
    act "pip-compile --upgrade requirements.in -> requirements.txt, install, run pytest, roll back on failure" true
    return 0
  fi

  bak=$(mktemp "${TMPDIR:-/tmp}/requirements.bak.XXXXXX")
  cp requirements.txt "$bak" 2>/dev/null || : > "$bak"

  info "Resolving the newest compatible versions from requirements.in ..."
  if ! "$vpy" -m piptools compile --upgrade --quiet --strip-extras --output-file requirements.txt requirements.in; then
    bad "pip-compile failed; requirements.txt restored"
    cp "$bak" requirements.txt; rm -f "$bak"; return 1
  fi

  info "Version changes:"
  diff <(grep -E '^[A-Za-z0-9_.-]+==' "$bak" | sort) <(grep -E '^[A-Za-z0-9_.-]+==' requirements.txt | sort) \
    | grep -E '^[<>]' | sed 's/^< /      - /; s/^> /      + /'

  if ! "$vpy" -m pip install -q -r requirements.txt pytest; then
    bad "install failed; rolling back"
    cp "$bak" requirements.txt
    "$vpy" -m pip install -q -r requirements.txt pytest
    rm -f "$bak"; NOTE="rolled back: install failed"; return 1
  fi

  info "Running the tests with the new versions (up to ${PYTEST_TIMEOUT:-900}s) ..."
  if with_timeout "${PYTEST_TIMEOUT:-900}" "$vpy" -m pytest -q -x </dev/null; then
    good "Tests pass: requirements.txt updated"
  else
    bad "TESTS FAILED with the new versions: rolling back requirements.txt and the environment"
    cp "$bak" requirements.txt
    "$vpy" -m pip install -q -r requirements.txt pytest
    rm -f "$bak"; NOTE="rolled back: tests failed with new versions"; return 1
  fi
  rm -f "$bak"

  if "$vpy" -m pip check >/dev/null 2>&1; then good "pip check: no broken requirements"
  else warn "pip check reports conflicts:"; "$vpy" -m pip check | sed 's/^/      /'; rc=3; fi
  "$vpy" -m pip cache purge >/dev/null 2>&1 && info "pip download cache purged"
  return $rc
}

# ----------------------------------------------------------------------------
# STEP: git
# ----------------------------------------------------------------------------
SECRET_NAME_RE='(^|/)\.env(\.[A-Za-z0-9_-]+)?$|(^|/)id_(rsa|dsa|ecdsa|ed25519)$|\.(pem|key|p12|pfx|kdbx|keychain-db|keystore|jks)$|(^|/)\.netrc$|(^|/)\.npmrc$|(^|/)\.pypirc$|(^|/)credentials(\.json)?$'
SECRET_OK_RE='\.(example|sample|template|dist)$'
SECRET_CONTENT_RE='-----BEGIN [A-Z ]*PRIVATE KEY-----|AKIA[0-9A-Z]{16}|gh[pousr]_[A-Za-z0-9]{36,}|xox[baprs]-[A-Za-z0-9-]{10,}|sk-[A-Za-z0-9_-]{32,}|AIza[0-9A-Za-z_-]{35}'

# Read file names on stdin, print the ones that look like secrets.
flag_secret_names() {
  grep -E "$SECRET_NAME_RE" | grep -Ev "$SECRET_OK_RE"
}

step_git() {
  have git || { NOTE="git not installed"; return 2; }
  [ -d "$DOTFILES" ] || { NOTE="$DOTFILES not found"; return 2; }
  cd "$DOTFILES" || return 1
  git rev-parse --is-inside-work-tree >/dev/null 2>&1 || { NOTE="$DOTFILES is not a git repository"; return 2; }
  local branch gitdir rc=0 flagged bigs f msg ahead
  branch=$(git symbolic-ref --short -q HEAD) || { NOTE="detached HEAD: nothing pushed"; warn "$NOTE"; return 3; }
  gitdir=$(git rev-parse --git-dir)
  if [ -d "$gitdir/rebase-merge" ] || [ -d "$gitdir/rebase-apply" ] || [ -f "$gitdir/MERGE_HEAD" ]; then
    bad "A merge or rebase is in progress in $DOTFILES. Finish it by hand first."; return 1
  fi
  export GIT_TERMINAL_PROMPT=0
  export GIT_SSH_COMMAND="${GIT_SSH_COMMAND:-ssh -o BatchMode=yes -o ConnectTimeout=15}"

  info "Branch: $branch   Remote: $(git remote get-url origin 2>/dev/null || echo none)"

  if [ "$DRY_RUN" = 1 ]; then
    info "Pending changes:"; git status --short | head -25 | sed 's/^/      /'
    flagged=$(git status --porcelain | sed 's/^...//' | flag_secret_names)
    if [ -n "$flagged" ]; then warn "These files look like secrets and would BLOCK the commit:"; printf '%s\n' "$flagged" | sed 's/^/      /'; return 3; fi
    act "git add . ; git commit -m \"$COMMIT_PREFIX <date>\" ; git push" true
    return 0
  fi

  if [ "$GIT_PULL" = 1 ] && git rev-parse --abbrev-ref '@{u}' >/dev/null 2>&1; then
    info "git pull --rebase --autostash"
    if ! git pull --rebase --autostash --quiet; then
      bad "git pull failed (conflict or network). Nothing was committed or pushed. Resolve it by hand in $DOTFILES."
      return 1
    fi
  fi

  # A folder that has its own .git (a clone inside the dotfiles repo) cannot be added: git says
  # "does not have a commit checked out". Skip those folders and say so; to track one on purpose,
  # make it a submodule, or add it to .gitignore to silence this message.
  local nested=() d
  while IFS= read -r d; do
    d=${d#./}; d=${d%/.git}
    [ -n "$d" ] && ! git check-ignore -q "$d" 2>/dev/null && ! git ls-files --error-unmatch "$d" >/dev/null 2>&1 && nested+=(":(exclude)$d")
  done < <(find . -mindepth 2 -maxdepth 4 -name .git \( -type d -o -type f \) -not -path './.git/*' 2>/dev/null)
  if [ "${#nested[@]}" -gt 0 ]; then
    warn "Skipping folders that are separate git repositories (not added):"
    for d in "${nested[@]}"; do printf '      %s\n' "${d#:(exclude)}"; done
    warn "Add them to .gitignore to stop this warning, or make them submodules."
    [ "$rc" = 0 ] && rc=3
  fi
  git add -- . ${nested[@]+"${nested[@]}"} || { bad "git add failed"; return 1; }

  # Safety net 1: file names that look like secrets.
  flagged=$(git diff --cached --name-only --diff-filter=ACMR | flag_secret_names)
  # Safety net 2: secret-looking text inside the staged changes (names only are printed).
  flagged="$flagged$(git diff --cached --name-only --diff-filter=ACMR -G"$SECRET_CONTENT_RE" 2>/dev/null)"
  # Safety net 3: very large files.
  bigs=""
  while IFS= read -r f; do
    [ -f "$f" ] || continue
    if [ "$(wc -c < "$f" | tr -d ' ')" -gt $((MAX_FILE_MB * 1048576)) ]; then bigs="$bigs$f"$'\n'; fi
  done < <(git diff --cached --name-only --diff-filter=ACMR)

  if [ -n "$flagged" ] || [ -n "$bigs" ]; then
    git reset -q
    bad "COMMIT BLOCKED. Nothing was committed (changes were un-staged, files untouched)."
    [ -n "$flagged" ] && { info "Look like secrets:"; printf '%s\n' "$flagged" | sort -u | sed '/^$/d; s/^/      /'; }
    [ -n "$bigs" ] && { info "Larger than ${MAX_FILE_MB} MB:"; printf '%s' "$bigs" | sed 's/^/      /'; }
    info "Add them to .gitignore (or remove them), then run again."
    NOTE="blocked by the secrets/size check"
    return 1
  fi

  if git diff --cached --quiet; then
    info "Nothing new to commit."
  else
    msg="$COMMIT_PREFIX $(date '+%Y-%m-%d %H:%M')"
    git diff --cached --stat | tail -8 | sed 's/^/      /'
    git commit -q -m "$msg" && good "Committed: $msg" || { bad "git commit failed"; return 1; }
  fi

  if git rev-parse --abbrev-ref '@{u}' >/dev/null 2>&1; then
    ahead=$(git rev-list --count '@{u}..HEAD' 2>/dev/null || echo 0)
    if [ "${ahead:-0}" -gt 0 ]; then
      git push --quiet && good "Pushed $ahead commit(s)" || { bad "git push failed (SSH agent/keychain? network?)"; return 1; }
    else
      info "Already up to date with the remote."
    fi
  else
    git push --quiet -u origin "$branch" && good "Pushed and set upstream" || { bad "git push failed"; rc=1; }
  fi
  return $rc
}

# ----------------------------------------------------------------------------
# STEP: updates - macOS / App Store (the terminal version of Software Update)
# ----------------------------------------------------------------------------
step_updates() {
  local rc=0 out key
  if have softwareupdate; then
    info "Asking Apple for updates (can take up to a minute) ..."
    out=$(softwareupdate --list 2>&1)
    if printf '%s\n' "$out" | grep -qi 'No new software available'; then
      good "macOS: no updates available"
    else
      warn "macOS updates available:"
      printf '%s\n' "$out" | grep -E '^\s*(\*|Label:|Title:)' | sed 's/^/      /'
      NOTE="macOS updates are available"
      rc=3
      if [ "$INSTALL_OS_UPDATES" = 1 ]; then
        if [ "$DRY_RUN" = 0 ] && ! ensure_sudo; then bad "no administrator rights"; return 1; fi
        act "sudo softwareupdate --install --all (no automatic restart)" sudo softwareupdate --install --all || rc=1
      else
        info "Not installed automatically (INSTALL_OS_UPDATES=0). Install with: System Settings > General > Software Update,"
        info "or:  sudo softwareupdate --install --all --restart"
      fi
    fi
    for key in AutomaticCheckEnabled AutomaticDownload AutomaticallyInstallMacOSUpdates CriticalUpdateInstall ConfigDataInstall; do
      info "Setting $key = $(defaults read /Library/Preferences/com.apple.SoftwareUpdate "$key" 2>/dev/null || echo 'not set')"
    done
  else
    info "softwareupdate not found (not macOS?)"
  fi
  if have mas; then
    info "App Store apps with updates:"
    mas outdated 2>&1 | sed 's/^/      /'
    [ "$MAS_UPGRADE" = 1 ] && act "mas upgrade" mas upgrade
  else
    info "Tip: 'brew install mas' lets this script list and upgrade App Store apps."
  fi
  return $rc
}

# ----------------------------------------------------------------------------
# Runner and summary
# ----------------------------------------------------------------------------
status_name() {
  case "$1" in 0) echo "OK" ;; 2) echo "SKIPPED" ;; 3) echo "WARNINGS" ;; *) echo "FAILED" ;; esac
}

run_steps() {
  local i=0 id func title t0 rc name
  while [ "$i" -lt "${#STEP_IDS[@]}" ]; do
    id="${STEP_IDS[$i]}"; func="${STEP_FUNCS[$i]}"; title="${STEP_TITLES[$i]}"; i=$((i + 1))
    selected "$id" || continue
    header "$id" "$title"
    NOTE=""
    t0=$SECONDS
    # Each step runs in a subshell: a crash or a `cd` cannot leak out. Its NOTE comes back through a file.
    ( cd "$HOME" && "$func"; r=$?; printf '%s' "$NOTE" > "$NOTE_FILE"; exit $r ); rc=$?
    [ "$rc" -gt 3 ] && rc=1
    RESULT_IDS+=("$id"); RESULT_STATUS+=("$rc"); RESULT_SECS+=($((SECONDS - t0)))
    RESULT_NOTES+=("$(cat "$NOTE_FILE" 2>/dev/null)")
  done
}

print_summary() {
  local i=0 fails=0 warns=0 st name colour
  printf '\n%s================= SUMMARY =================%s\n' "$C_BOLD" "$C_RESET"
  while [ "$i" -lt "${#RESULT_IDS[@]}" ]; do
    st="${RESULT_STATUS[$i]}"; name=$(status_name "$st")
    case "$st" in 0) colour="$C_GREEN" ;; 2) colour="$C_DIM" ;; 3) colour="$C_YELLOW"; warns=$((warns + 1)) ;; *) colour="$C_RED"; fails=$((fails + 1)) ;; esac
    printf '  %-10s %s%-9s%s %6s  %s\n' "${RESULT_IDS[$i]}" "$colour" "$name" "$C_RESET" "$(fmt_secs "${RESULT_SECS[$i]}")" "${RESULT_NOTES[$i]}"
    i=$((i + 1))
  done
  local now_free
  now_free=$(free_kb "$HOME")
  if [ -n "${now_free:-}" ] && [ "${START_FREE_KB:-0}" -gt 0 ]; then
    local delta=$((now_free - START_FREE_KB))
    if [ "$delta" -ge 0 ]; then printf '  Free space on the internal disk: %s (%s more than before)\n' "$(human_kb "$now_free")" "$(human_kb "$delta")"
    else printf '  Free space on the internal disk: %s (%s less than before)\n' "$(human_kb "$now_free")" "$(human_kb $((-delta)))"; fi
  fi
  printf '  Total time: %s    Failed: %d    With warnings: %d\n' "$(fmt_secs $((SECONDS - START_SECS)))" "$fails" "$warns"
  [ "$DRY_RUN" = 1 ] && printf '  %sDRY RUN: nothing was changed. Run again with --run to apply.%s\n' "$C_YELLOW" "$C_RESET"
  printf '  Log: %s\n' "$LOG"
  SUMMARY_FAILS=$fails
  SUMMARY_WARNS=$warns
}

# ----------------------------------------------------------------------------
# "What to do next": for every step that ended with warnings or a failure, print the
# commands that usually fix it. Kept in one place so it is easy to extend.
# ----------------------------------------------------------------------------
hints_for() {   # $1 = step id
  case "$1" in
    check) cat <<'H'
  - Low memory: quit heavy apps. Local AI:  ai-off      SearXNG/Docker:  bash ~/macOS/scripts/searx.sh stop --quit-docker
  - Disk almost full: du -h -d 1 ~ | sort -hr | head   (alias du1)      Then empty the Trash and run: maintain-mac.sh --run --only downloads,junk
  - A drive is missing: ls /Volumes      diskutil list      (replug it, then run again)
H
    ;;
    tm) cat <<'H'
  - Is a destination set?   tmutil destinationinfo
  - Last backups:           tmutil listbackups | tail -3
  - Drive mounted?          ls /Volumes      (MacDatosMaster must be there)
  - Settings > General > Time Machine shows the error, if any. Start by hand: sudo tmutil startbackup --auto
H
    ;;
    backup) cat <<'H'
  - "STOPPED by the safety limit": check the source, then once:  bash ~/macOS/scripts/maintain-mac.sh --run --only backup --allow-big-delete
  - Drive not answering (ls or du hangs): unplug it, other port/cable (no hub), then  diskutil verifyVolume /Volumes/DatosSlave
  - File system of the backup drive (APFS or Mac OS Extended is best):  diskutil info /Volumes/DatosSlave | grep -E "File System|Type"
  - Start the backup drive clean (history and copies):  rm -rf /Volumes/DatosSlave/_history
  - Not enough space: see how much each folder uses:   du -sh /Volumes/DatosSlave/*
H
    ;;
    trash) cat <<'H'
  - Let your terminal control Finder: System Settings > Privacy & Security > Automation > Ghostty (or Terminal) > Finder.
  - Or empty it by hand:  rm -rf ~/.Trash/*
H
    ;;
    junk) cat <<'H'
  - A browser was running: quit it, or let the script do it: in maintain-mac.conf set  QUIT_BROWSERS="Safari"   (comma list)
  - "Full Disk Access": System Settings > Privacy & Security > Full Disk Access > add Ghostty (or Terminal), then restart it.
H
    ;;
    brew) cat <<'H'
  - Read the warnings:               brew doctor
  - "formulae are deprecated":       brew uses --installed NAME     (who needs it), then  brew uninstall NAME  or find the replacement
  - An upgrade failed:               brew upgrade --verbose     then   brew update-reset
  - Missing dependencies:            brew missing      then   brew install NAME
  - Installed but not in Brewfile:   brewdump   (alias: saves everything into ~/macOS/Brewfile)
  - Network trouble (update failed): try again later, or  brew update --force
H
    ;;
    pip) cat <<'H'
  - Tests failed with the new versions (nothing was changed, it rolled back):
        cd ~/macOS/myPython && source .venv/bin/activate && python -m pytest -x
    If a test is out of date, copy the current tests/ from the newest toolkit zip; if a package broke it, pin it in requirements.in (e.g. pandas<3.1).
  - Broken virtualenv:  cd ~/macOS/myPython && rm -rf .venv && python3 -m venv .venv && .venv/bin/pip install -r requirements.txt pytest
  - Conflicts:  .venv/bin/pip check
H
    ;;
    git) cat <<'H'
  - See the state:        cd ~/macOS && git status
  - Pull conflict:        git status   (fix the files marked "both modified"), then  git rebase --continue    or give up:  git rebase --abort
  - Secrets blocked:      git rm --cached FILE ; echo FILE >> .gitignore    (never commit .env or keys)
  - Folder with its own .git ("does not have a commit checked out"): add it to .gitignore, or make it a submodule
  - Push rejected:        git pull --rebase && git push
  - Cannot log in:        ssh -T git@github.com     (SSH key)   or   gh auth status
H
    ;;
    updates) cat <<'H'
  - macOS updates:   System Settings > General > Software Update       or      sudo softwareupdate --install --all --restart
  - Only Xcode tools (no restart):   softwareupdate --list    then   sudo softwareupdate --install "<label shown above>"
  - App Store apps:  open the App Store > Updates       or      brew install mas ; mas outdated ; mas upgrade
  - Let the script do it next time: in maintain-mac.conf set INSTALL_OS_UPDATES=1 and MAS_UPGRADE=1
H
    ;;
  esac
}

print_hints() {
  local i=0 st shown=0
  while [ "$i" -lt "${#RESULT_IDS[@]}" ]; do
    st="${RESULT_STATUS[$i]}"
    if [ "$st" = 1 ] || [ "$st" = 3 ] || [ "$st" -gt 3 ] 2>/dev/null; then
      if [ "$shown" = 0 ]; then printf '\n%s============= WHAT TO DO NEXT =============%s\n' "$C_BOLD" "$C_RESET"; shown=1; fi
      printf '%s[%s]%s %s\n' "$C_BOLD" "${RESULT_IDS[$i]}" "$C_RESET" "$(status_name "$st")"
      hints_for "${RESULT_IDS[$i]}"
    fi
    i=$((i + 1))
  done
  [ "$shown" = 1 ] && printf '  (details of each message are in the log: %s)\n' "$LOG"
  return 0
}

notify() {
  [ "$DRY_RUN" = 0 ] && is_mac && have osascript || return 0
  osascript -e "display notification \"$1\" with title \"maintain-mac\"" >/dev/null 2>&1 || true
}

confirm_plan() {
  local i=0
  say "Plan (this will CHANGE things):"
  while [ "$i" -lt "${#STEP_IDS[@]}" ]; do
    selected "${STEP_IDS[$i]}" && printf '   - %-10s %s\n' "${STEP_IDS[$i]}" "${STEP_TITLES[$i]}"
    i=$((i + 1))
  done
  [ "$ASSUME_YES" = 1 ] && return 0
  if [ ! -r /dev/tty ] || [ "${MM_NO_TTY:-0}" = 1 ]; then
    echo "No terminal to ask on: add --yes to confirm." >&2; return 1
  fi
  printf 'Continue? [y/N] ' > /dev/tty
  local ans; read -r ans < /dev/tty
  case "$ans" in y|Y|yes|YES) return 0 ;; *) echo "Cancelled."; return 1 ;; esac
}

main() {
  setup_path
  NOTE_FILE=$(mktemp "${TMPDIR:-/tmp}/maintain-mac-note.XXXXXX")
  trap cleanup EXIT
  trap on_interrupt INT TERM

  say "$SCRIPT_NAME $VERSION  -  $(date '+%A %d %B %Y, %H:%M')"
  if [ "$DRY_RUN" = 1 ]; then say "${C_YELLOW}DRY RUN: only showing what would happen.${C_RESET}"; fi

  if ! is_mac; then
    echo "This script is for macOS (found: $MM_OS)." >&2; exit 2
  fi
  if [ "$(id -u)" -eq 0 ] && [ "${MAINTAIN_MAC_ALLOW_ROOT:-0}" != 1 ]; then   # the override exists for the test-suite only
    echo "Do not run this with sudo: it asks for the password itself when needed." >&2; exit 2
  fi
  if ! acquire_lock; then
    echo "Another maintain-mac run is in progress (lock: $LOCK_DIR)." >&2; exit 2
  fi

  if [ "$DRY_RUN" = 0 ]; then
    confirm_plan || exit 1
    if have caffeinate; then caffeinate -dimsu -w $$ >/dev/null 2>&1 & CAFFEINATE_PID=$!; fi   # keep the Mac awake
    if selected tm || selected updates; then ensure_sudo || warn "No administrator rights: steps that need them will be skipped."; fi
  fi

  START_FREE_KB=$(free_kb "$HOME"); START_FREE_KB=${START_FREE_KB:-0}
  run_steps
  print_summary
  print_hints
  notify "Finished: ${SUMMARY_FAILS} failed, ${SUMMARY_WARNS} with warnings"
  [ "$SUMMARY_FAILS" -gt 0 ] && exit 1
  exit 0
}

# ----------------------------------------------------------------------------
# Entry point
# ----------------------------------------------------------------------------
if [ "${MAINTAIN_MAC_SOURCE_ONLY:-0}" = 1 ]; then
  return 0 2>/dev/null || exit 0      # lets the tests load the functions without running
fi

parse_args "$@"
init_colors
[ "$SHOW_HELP" = 1 ] && { usage; exit 0; }
[ "$LIST_ONLY" = 1 ] && { list_steps; exit 0; }

mkdir -p "$LOG_DIR" 2>/dev/null || LOG_DIR="${TMPDIR:-/tmp}"
LOG="$LOG_DIR/$(date '+%Y-%m-%d_%H%M%S')$([ "$DRY_RUN" = 1 ] && echo '-dryrun').log"
: > "$LOG" 2>/dev/null || LOG=/dev/null

main 2>&1 | tee -a "$LOG"
exit "${PIPESTATUS[0]}"
