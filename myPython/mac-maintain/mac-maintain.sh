#!/bin/bash
# =============================================================================
# mac-maintain.sh - one-command maintenance for a Mac (macOS, Homebrew, Python)
# =============================================================================
#
# What it does (each job is a "step"; run them all or pick some):
#
#   check      Memory, disk, load, battery, security settings, Time Machine age
#   timemachine  Start a Time Machine backup  (sudo tmutil startbackup --auto)
#   backup     rsync  /Volumes/MacDatosMaster  and  ~/macOS  ->  /Volumes/MacDatosSlave
#   trash      Empty the Trash (Finder)
#   downloads  Move OLD files from ~/Downloads to the Trash (never deletes directly)
#   cleanup    Browser CACHES (never cookies/passwords/history) + old user logs
#   brew       brew update, upgrade, fix missing dependencies, autoremove, cleanup
#   macos      List macOS and App Store updates (installs only if you ask)
#   pip        Update pip + requirements.txt of ~/macOS/myPython, tests, roll back on failure
#   git        git add -A, commit with the date, push ~/macOS (with a secrets scan)
#
# SAFE BY DEFAULT: without --run the script only SHOWS what it would do.
# With --run it asks before every destructive action (--yes = do not ask).
#
# Usage:
#   mac-maintain.sh                      # dry run of everything (changes nothing)
#   mac-maintain.sh --run                # really do it, asking before deleting
#   mac-maintain.sh --run --only brew,pip
#   mac-maintain.sh --run --skip backup,timemachine
#   mac-maintain.sh --help
#
# Written for bash 3.2 (the bash that ships with macOS) and plain BSD tools.
# Run it as YOUR user, never with sudo (it asks for sudo itself where needed).
# Full manual: MAINTENANCE.md
# =============================================================================

VERSION="1.0.0"

# Not using `set -e` on purpose: one failing step must not stop the others.
# Every step reports OK / SKIP / WARN / FAIL in the final summary.
set -u
set -o pipefail

# --------------------------------------------------------------------------- #
# Settings (override in ~/.config/mac-maintain/config or with environment)    #
# --------------------------------------------------------------------------- #

DOTFILES_DIR="${DOTFILES_DIR:-$HOME/macOS}"
PYTHON_DIR="${PYTHON_DIR:-$DOTFILES_DIR/myPython}"
VENV_DIR="${VENV_DIR:-$PYTHON_DIR/.venv}"

SRC_MASTER="${SRC_MASTER:-/Volumes/MacDatosMaster}"
DST_SLAVE="${DST_SLAVE:-/Volumes/MacDatosSlave}"
BACKUP_ROOT="${BACKUP_ROOT:-$DST_SLAVE/Backups}"
MIRROR_DELETE="${MIRROR_DELETE:-1}"        # 1 = files deleted on Master are moved to _deleted/ on Slave
KEEP_DELETED_DAYS="${KEEP_DELETED_DAYS:-60}"  # _deleted/ folders older than this are offered for removal

DOWNLOADS_DIR="${DOWNLOADS_DIR:-$HOME/Downloads}"
DOWNLOADS_DAYS="${DOWNLOADS_DAYS:-30}"             # untouched this long -> Trash
DOWNLOADS_INSTALLER_DAYS="${DOWNLOADS_INSTALLER_DAYS:-7}"  # .dmg .pkg .iso .mpkg

LOGS_DAYS="${LOGS_DAYS:-30}"               # ~/Library/Logs files older than this
BROWSERS="${BROWSERS:-chrome safari firefox brave edge}"
PIP_CACHE_PURGE="${PIP_CACHE_PURGE:-0}"

BREW_GREEDY="${BREW_GREEDY:-0}"            # 1 = also upgrade casks that update themselves
BREWFILE_UPDATE="${BREWFILE_UPDATE:-0}"    # 1 = rewrite $DOTFILES_DIR/Brewfile from what is installed
MAS_UPGRADE="${MAS_UPGRADE:-0}"            # 1 = also run `mas upgrade` (App Store apps)
MACOS_INSTALL="${MACOS_INSTALL:-0}"        # 1 = install macOS updates (asks; may restart)
MACOS_RESTART="${MACOS_RESTART:-0}"        # 1 = allow softwareupdate to restart

TM_BLOCK="${TM_BLOCK:-0}"                  # 1 = wait until Time Machine finishes
GIT_SCAN="${GIT_SCAN:-1}"                  # 0 = disable the secrets scan (not recommended)
GIT_MAX_FILE_MB="${GIT_MAX_FILE_MB:-50}"
MIN_FREE_PERCENT="${MIN_FREE_PERCENT:-15}"
SWAP_WARN_MB="${SWAP_WARN_MB:-4096}"
KEEP_LOGS="${KEEP_LOGS:-30}"

CONF="${MAC_MAINTAIN_CONF:-$HOME/.config/mac-maintain/config}"
# shellcheck disable=SC1090
[ -f "$CONF" ] && . "$CONF"

ALL_STEPS="check timemachine backup trash downloads cleanup brew macos pip git"

# Homebrew is not in PATH for launchd/cron jobs.
PATH="/opt/homebrew/bin:/opt/homebrew/sbin:/usr/local/bin:$PATH"
export PATH
export HOMEBREW_NO_ENV_HINTS=1

# --------------------------------------------------------------------------- #
# Command line                                                                #
# --------------------------------------------------------------------------- #

DRY_RUN=1
ASSUME_YES=0
ONLY=""
SKIP=""

usage() {
  cat <<EOF
mac-maintain.sh $VERSION - maintenance for your Mac

  --run, -r        really do it (default is a dry run that changes nothing)
  --dry-run, -n    show what would happen (default)
  --yes, -y        with --run: do not ask before destructive actions
  --only a,b,c     run only these steps
  --skip a,b       run everything except these steps
  --list-steps     print the step names, in order
  --macos-install  with --run: install macOS updates (asks first)
  --version, -V    print the version
  --help, -h       this text

Steps (in this order): $ALL_STEPS

Examples:
  mac-maintain.sh                              look, change nothing
  mac-maintain.sh --run --only check,brew      weekly quick one
  mac-maintain.sh --run --skip timemachine     everything but Time Machine
EOF
}

while [ $# -gt 0 ]; do
  case "$1" in
    --run|-r)        DRY_RUN=0 ;;
    --dry-run|-n)    DRY_RUN=1 ;;
    --yes|-y)        ASSUME_YES=1 ;;
    --only)          shift; ONLY="${1:-}" ;;
    --only=*)        ONLY="${1#--only=}" ;;
    --skip)          shift; SKIP="${1:-}" ;;
    --skip=*)        SKIP="${1#--skip=}" ;;
    --macos-install) MACOS_INSTALL=1 ;;
    --list-steps)    printf '%s\n' $ALL_STEPS; exit 0 ;;
    --version|-V)    echo "$VERSION"; exit 0 ;;
    --help|-h)       usage; exit 0 ;;
    *) echo "unknown option: $1 (try --help)" >&2; exit 2 ;;
  esac
  shift
done
ONLY=$(printf '%s' "$ONLY" | tr ',' ' ')
SKIP=$(printf '%s' "$SKIP" | tr ',' ' ')

for s in $ONLY $SKIP; do
  case " $ALL_STEPS " in *" $s "*) ;; *) echo "unknown step: $s (valid: $ALL_STEPS)" >&2; exit 2 ;; esac
done

want_step() {
  local s="$1" x
  if [ -n "$ONLY" ]; then
    case " $ONLY " in *" $s "*) ;; *) return 1 ;; esac
  fi
  for x in $SKIP; do [ "$x" = "$s" ] && return 1; done
  return 0
}

# --------------------------------------------------------------------------- #
# Safety checks before anything happens                                       #
# --------------------------------------------------------------------------- #

if [ "$(id -u)" = "0" ] && [ "${MAC_MAINTAIN_TESTING:-0}" != "1" ]; then
  echo "Do not run this script with sudo: it would use root's home folder." >&2
  echo "Run it as yourself; it asks for sudo only for the few commands that need it." >&2
  exit 2
fi
if [ "$(uname -s)" != "Darwin" ] && [ "${MAC_MAINTAIN_TESTING:-0}" != "1" ]; then
  echo "This script is for macOS (uname says $(uname -s))." >&2
  exit 2
fi

# --------------------------------------------------------------------------- #
# Output helpers, log file, lock                                              #
# --------------------------------------------------------------------------- #

if [ -t 1 ] && [ -z "${NO_COLOR:-}" ]; then
  C_BOLD=$(printf '\033[1m'); C_DIM=$(printf '\033[2m'); C_RED=$(printf '\033[31m')
  C_GRN=$(printf '\033[32m'); C_YEL=$(printf '\033[33m'); C_CYN=$(printf '\033[36m'); C_OFF=$(printf '\033[0m')
else
  C_BOLD=""; C_DIM=""; C_RED=""; C_GRN=""; C_YEL=""; C_CYN=""; C_OFF=""
fi
IS_TTY=0; [ -t 0 ] && [ -t 1 ] && IS_TTY=1

STAMP=$(date '+%Y-%m-%d_%H%M%S')
LOG_DIR="$HOME/Library/Logs/mac-maintain"
mkdir -p "$LOG_DIR" 2>/dev/null
LOG="$LOG_DIR/$STAMP.log"
# Everything printed is also written to the log (colour codes included: read it with `less -R`).
exec > >(tee -a "$LOG") 2>&1

TMP=$(mktemp -d "${TMPDIR:-/tmp}/mac-maintain.XXXXXX")
LOCKDIR="${TMPDIR:-/tmp}/mac-maintain.lock"
SUDO_PID=""
SUMMARY=""
START_EPOCH=$(date +%s)

cleanup_exit() {
  sleep 0.3   # let the log writer (tee) finish before the prompt comes back
  [ -n "$SUDO_PID" ] && kill "$SUDO_PID" 2>/dev/null
  rm -rf "$TMP"
  [ -d "$LOCKDIR" ] && [ "$(cat "$LOCKDIR/pid" 2>/dev/null)" = "$$" ] && rm -rf "$LOCKDIR"
}
trap cleanup_exit EXIT
trap 'echo; echo "Interrupted."; exit 130' INT TERM

if ! mkdir "$LOCKDIR" 2>/dev/null; then
  oldpid=$(cat "$LOCKDIR/pid" 2>/dev/null)
  if [ -n "$oldpid" ] && kill -0 "$oldpid" 2>/dev/null; then
    echo "Another mac-maintain.sh is already running (pid $oldpid)." >&2
    exit 2
  fi
  rm -rf "$LOCKDIR"; mkdir "$LOCKDIR" 2>/dev/null
fi
echo $$ > "$LOCKDIR/pid"

section() { printf '\n%s== %s ==%s\n' "$C_BOLD$C_CYN" "$1" "$C_OFF"; }
info()    { printf '  %s\n' "$*"; }
good()    { printf '  %s✔%s %s\n' "$C_GRN" "$C_OFF" "$*"; }
warn()    { printf '  %s!%s %s\n' "$C_YEL" "$C_OFF" "$*"; }
bad()     { printf '  %s✘%s %s\n' "$C_RED" "$C_OFF" "$*"; }
note()    { printf '  %s%s%s\n' "$C_DIM" "$*" "$C_OFF"; }

# Status of the step that is running: OK < SKIP < WARN < FAIL (the worst one wins).
CUR_STATUS="OK"; CUR_NOTE=""
rank() { case "$1" in OK) echo 0;; SKIP) echo 1;; WARN) echo 2;; FAIL) echo 3;; *) echo 0;; esac; }
rec() {
  [ "$(rank "$1")" -gt "$(rank "$CUR_STATUS")" ] && CUR_STATUS="$1"
  [ -n "${2:-}" ] && CUR_NOTE="${CUR_NOTE:+$CUR_NOTE; }$2"
  return 0
}

# Run a command that CHANGES something. In a dry run it only prints it.
run() {
  if [ "$DRY_RUN" = 1 ]; then
    printf '  %s[dry-run] would run:%s %s\n' "$C_DIM" "$C_OFF" "$*"
    return 0
  fi
  "$@"
}

# confirm "question": 0 = go ahead.
#   dry run  -> always 0 (nothing is changed anyway)
#   --yes    -> 0
#   terminal -> asks
#   no terminal and no --yes -> 1 (never delete unattended by accident)
confirm() {
  [ "$DRY_RUN" = 1 ] && return 0
  [ "$ASSUME_YES" = 1 ] && return 0
  if [ "$IS_TTY" != 1 ]; then
    warn "no terminal to ask: skipped (use --yes for unattended runs)"
    return 1
  fi
  local ans
  printf '  %s?%s %s [y/N] ' "$C_YEL" "$C_OFF" "$1"
  read -r ans </dev/tty
  case "$ans" in y|Y|yes|YES) return 0 ;; *) info "skipped."; return 1 ;; esac
}

dir_kb() { du -sk "$1" 2>/dev/null | awk '{print $1+0}'; }
human() {
  awk -v k="${1:-0}" 'BEGIN{ if (k>=1048576) printf "%.1f GB", k/1048576;
                              else if (k>=1024) printf "%.1f MB", k/1024; else printf "%d KB", k }'
}
have() { command -v "$1" >/dev/null 2>&1; }

DATA_VOL="/System/Volumes/Data"; [ -d "$DATA_VOL" ] || DATA_VOL="/"
free_kb() { df -k "$1" 2>/dev/null | awk 'NR==2 {print $4+0}'; }
FREE_BEFORE_KB=$(free_kb "$DATA_VOL")

# sudo once, kept alive while the script runs. Returns 0 if sudo is usable.
SUDO_STATE=""
ensure_sudo() {
  [ "$DRY_RUN" = 1 ] && return 0
  [ -n "$SUDO_STATE" ] && return "$SUDO_STATE"
  if sudo -n true 2>/dev/null; then
    SUDO_STATE=0
  elif [ "$IS_TTY" = 1 ]; then
    info "sudo password needed (asked once):"
    if sudo -v; then SUDO_STATE=0; else SUDO_STATE=1; fi
  else
    SUDO_STATE=1
  fi
  if [ "$SUDO_STATE" = 0 ]; then
    ( while kill -0 "$$" 2>/dev/null; do sudo -n true 2>/dev/null; sleep 50; done ) >/dev/null 2>&1 &
    SUDO_PID=$!
  fi
  return "$SUDO_STATE"
}

# Move paths to the Trash (recoverable): `trash` CLI > Finder > plain mv.
to_trash() {
  [ $# -eq 0 ] && return 0
  if have trash; then trash "$@"; return $?; fi
  if have osascript; then
    local f esc list=""
    for f in "$@"; do
      esc=${f//\\/\\\\}; esc=${esc//\"/\\\"}
      list="${list:+$list, }POSIX file \"$esc\""
    done
    osascript -e "tell application \"Finder\" to delete {$list}" >/dev/null && return 0
  fi
  local rc=0
  for f in "$@"; do
    mv -n "$f" "$HOME/.Trash/$(basename "$f").$(date +%H%M%S)" || rc=1
  done
  return $rc
}

# =========================================================================== #
# STEP: check                                                                 #
# =========================================================================== #

disk_line() { # disk_line path label
  local path="$1" label="$2" total avail pct
  [ -d "$path" ] || return 0
  set -- $(df -k "$path" 2>/dev/null | awk 'NR==2 {print $2+0, $4+0}')
  total="${1:-0}"; avail="${2:-0}"
  [ "$total" -gt 0 ] || return 0
  pct=$(( avail * 100 / total ))
  if [ "$pct" -lt "$MIN_FREE_PERCENT" ]; then
    warn "$label: only $pct% free ($(human "$avail") of $(human "$total"))"
    rec WARN "$label ${pct}% free"
  else
    good "$label: $pct% free ($(human "$avail") of $(human "$total"))"
  fi
}

vm_pages() { printf '%s\n' "$VM" | awk -F: -v k="$1" '$1==k {gsub(/[ .]/,"",$2); print $2+0}'; }

step_check() {
  if have sw_vers; then info "macOS $(sw_vers -productVersion) ($(uname -m))"; fi
  info "uptime: $(uptime | sed -E 's/^[^,]*up *//; s/, *[0-9]+ users?.*//')"
  info "load: $(uptime | sed -E 's/.*load averages?: *//') (cores: $(sysctl -n hw.ncpu 2>/dev/null || echo '?'))"

  echo; info "${C_BOLD}Disk${C_OFF}"
  disk_line "$DATA_VOL" "Macintosh HD (data)"
  disk_line "$SRC_MASTER" "$(basename "$SRC_MASTER")"
  disk_line "$DST_SLAVE" "$(basename "$DST_SLAVE")"

  echo; info "${C_BOLD}Memory${C_OFF}"
  local total page free inact spec purg avail pct swap
  total=$(sysctl -n hw.memsize 2>/dev/null || echo 0)
  VM=$(vm_stat 2>/dev/null)
  page=$(printf '%s\n' "$VM" | sed -n 's/.*page size of \([0-9]*\) bytes.*/\1/p')
  if [ "${total:-0}" -gt 0 ] && [ -n "$page" ]; then
    free=$(vm_pages "Pages free"); inact=$(vm_pages "Pages inactive")
    spec=$(vm_pages "Pages speculative"); purg=$(vm_pages "Pages purgeable")
    avail=$(( (free + inact + spec + purg) * page ))
    pct=$(( avail * 100 / total ))
    if [ "$pct" -lt 10 ]; then
      warn "memory: about $pct% available ($(human $((avail/1024))) of $(human $((total/1024))))"
      rec WARN "low memory ${pct}%"
    else
      good "memory: about $pct% available ($(human $((avail/1024))) of $(human $((total/1024))))"
    fi
  else
    note "(vm_stat / sysctl not available)"
  fi
  if have memory_pressure; then
    info "$(memory_pressure 2>/dev/null | sed -n 's/.*free percentage: *\(.*\)/system-wide memory free: \1/p')"
  fi
  swap=$(sysctl -n vm.swapusage 2>/dev/null)
  if [ -n "$swap" ]; then
    info "swap: $swap"
    local used_mb
    used_mb=$(printf '%s\n' "$swap" | awk '{for(i=1;i<=NF;i++) if($i=="used"){v=$(i+2); u=substr(v,length(v)); n=v+0; if(u=="G") n*=1024; print int(n)}}')
    if [ -n "$used_mb" ] && [ "$used_mb" -gt "$SWAP_WARN_MB" ]; then
      warn "swap in use is high (${used_mb} MB): restart apps or the Mac"
      rec WARN "high swap"
    fi
  fi
  info "top memory users:"
  ps -Ao pmem=,comm= 2>/dev/null | sort -rn | head -5 | awk '{p=$1; $1=""; sub(/^ /,""); n=split($0,a,"/"); printf "      %5s%%  %s\n", p, a[n]}'

  if have pmset && pmset -g batt 2>/dev/null | grep -q InternalBattery; then
    echo; info "${C_BOLD}Battery${C_OFF}"
    pmset -g batt | sed -n '2p' | sed 's/^ *//; s/^/  /'
  fi

  echo; info "${C_BOLD}Security${C_OFF}"
  have fdesetup && info "FileVault: $(fdesetup status 2>/dev/null | head -1)"
  have csrutil  && info "SIP: $(csrutil status 2>/dev/null | head -1 | sed 's/System Integrity Protection status: //')"
  have spctl    && info "Gatekeeper: $(spctl --status 2>/dev/null | head -1)"
  if [ -x /usr/libexec/ApplicationFirewall/socketfilterfw ]; then
    info "Firewall: $(/usr/libexec/ApplicationFirewall/socketfilterfw --getglobalstate 2>/dev/null | head -1)"
  fi

  echo; info "${C_BOLD}Time Machine${C_OFF}"
  if have tmutil; then
    local last
    last=$(tmutil latestbackup 2>/dev/null | tail -1)
    if [ -n "$last" ]; then
      info "latest backup: $(basename "$last")"
    else
      warn "no Time Machine backup found (or Terminal lacks Full Disk Access)"
      rec WARN "no Time Machine backup seen"
    fi
  else
    note "(tmutil not found)"
  fi

  echo; info "${C_BOLD}Drives${C_OFF}"
  for v in "$SRC_MASTER" "$DST_SLAVE"; do
    if mount | grep -qF " on $v "; then good "$v is mounted"; else warn "$v is NOT mounted"; rec WARN "$v not mounted"; fi
  done
}

# =========================================================================== #
# STEP: timemachine                                                           #
# =========================================================================== #

step_timemachine() {
  if ! have tmutil; then rec SKIP "tmutil not found"; warn "tmutil not found"; return; fi
  local dest status
  dest=$(tmutil destinationinfo 2>&1)
  if printf '%s\n' "$dest" | grep -qi "no destinations"; then
    warn "Time Machine has no destination configured (System Settings > General > Time Machine)"
    rec SKIP "no Time Machine destination"; return
  fi
  printf '%s\n' "$dest" | grep -E '^(Name|Kind|Mount Point)' | sed 's/^/    /'
  status=$(tmutil status 2>/dev/null)
  if printf '%s\n' "$status" | grep -q 'Running = 1'; then
    good "a backup is already running"; rec OK "already running"; return
  fi
  local args="--auto"; [ "$TM_BLOCK" = 1 ] && args="--auto --block"
  if ! ensure_sudo; then
    warn "sudo not available: Time Machine not started"; rec SKIP "no sudo"; return
  fi
  # shellcheck disable=SC2086
  if run sudo tmutil startbackup $args; then
    [ "$DRY_RUN" = 1 ] || good "backup requested (runs in the background unless TM_BLOCK=1)"
  else
    bad "tmutil startbackup failed"; rec FAIL "tmutil failed"
  fi
}

# =========================================================================== #
# STEP: backup (rsync)                                                        #
# =========================================================================== #

RSYNC=""; RSYNC_IS_3=0
pick_rsync() {
  local c v
  for c in /opt/homebrew/bin/rsync /usr/local/bin/rsync "$(command -v rsync 2>/dev/null)" /usr/bin/rsync; do
    [ -x "$c" ] || continue
    v=$("$c" --version 2>/dev/null | head -1)
    case "$v" in
      *openrsync*) [ -z "$RSYNC" ] && RSYNC="$c" ;;     # Apple's replacement: limited
      *"version 3."*|*"version 4."*) RSYNC="$c"; RSYNC_IS_3=1; return 0 ;;
      *) [ -z "$RSYNC" ] && RSYNC="$c" ;;
    esac
  done
  [ -n "$RSYNC" ]
}

mounted() { mount | grep -qF " on $1 "; }

# rsync_one SRC DEST_DIR LABEL [extra excludes...]
rsync_one() {
  local src="$1" dest="$2" label="$3" rc ex
  shift 3
  if [ "$DRY_RUN" = 0 ]; then
    mkdir -p "$dest" 2>/dev/null || { bad "cannot create $dest"; rec FAIL "$label: cannot create $dest"; return; }
  fi
  local args=(-a)                       # Apple's openrsync: keep to the basics
  if [ "$RSYNC_IS_3" = 1 ]; then
    args=(-aHX --partial --human-readable --stats)
    [ "$IS_TTY" = 1 ] && args+=(--info=progress2)
  fi
  for ex in .Spotlight-V100 .fseventsd .Trashes .TemporaryItems .DocumentRevisions-V100 .PKInstallSandboxManager-SystemSoftware "$@"; do
    args+=(--exclude="$ex")
  done
  if [ "$MIRROR_DELETE" = 1 ] && [ "$RSYNC_IS_3" = 1 ]; then
    args+=(--delete --backup "--backup-dir=$BACKUP_ROOT/_deleted/$STAMP/$label")
  fi
  [ "$DRY_RUN" = 1 ] && args+=(-n)

  info "$label:  $src  ->  $dest"
  if [ "$DRY_RUN" = 1 ]; then
    "$RSYNC" "${args[@]}" "$src/" "$dest/" | grep -E 'Number of (regular )?files|Number of created|Number of deleted|Number of regular files transferred|Total transferred file size|Total file size' | sed 's/^/      /'
    rc=${PIPESTATUS[0]}
  else
    "$RSYNC" "${args[@]}" "$src/" "$dest/" | tail -n 18 | sed 's/^/      /'
    rc=${PIPESTATUS[0]}
  fi
  case "$rc" in
    0)     good "$label: done" ;;
    23|24) warn "$label: finished with some files skipped (rsync code $rc: unreadable or vanished files)"; rec WARN "$label rsync code $rc" ;;
    *)     bad "$label: rsync failed (code $rc)"; rec FAIL "$label rsync code $rc" ;;
  esac
}

step_backup() {
  pick_rsync || { bad "rsync not found"; rec FAIL "no rsync"; return; }
  info "rsync: $RSYNC ($("$RSYNC" --version 2>/dev/null | head -1))"
  if [ "$RSYNC_IS_3" != 1 ]; then
    warn "only Apple's limited rsync was found. Install the real one:  brew install rsync"
    warn "without it the copy is ADD-ONLY (nothing is deleted or versioned on the backup drive)"
    rec WARN "using openrsync (brew install rsync)"
  fi

  # --- the safety checks that matter -------------------------------------------------
  [ "$SRC_MASTER" != "$DST_SLAVE" ] || { bad "source and destination are the same path"; rec FAIL "same path"; return; }
  for v in "$SRC_MASTER" "$DST_SLAVE"; do
    if ! mounted "$v"; then
      warn "$v is not mounted: backup skipped (plug the drive in and unlock it)"
      rec SKIP "$v not mounted"; return
    fi
  done
  local dsrc ddst
  dsrc=$(stat -f %d "$SRC_MASTER" 2>/dev/null); ddst=$(stat -f %d "$DST_SLAVE" 2>/dev/null)
  if [ -n "$dsrc" ] && [ "$dsrc" = "$ddst" ]; then
    bad "$SRC_MASTER and $DST_SLAVE are on the same device: refusing to 'back up' onto itself"
    rec FAIL "same device"; return
  fi
  if [ -z "$(ls -A "$SRC_MASTER" 2>/dev/null | head -n 1)" ]; then
    bad "$SRC_MASTER looks EMPTY: refusing to mirror an empty source (it would wipe the backup)"
    rec FAIL "empty source"; return
  fi
  [ -w "$DST_SLAVE" ] || { bad "$DST_SLAVE is not writable (read-only drive?)"; rec FAIL "destination not writable"; return; }
  disk_line "$DST_SLAVE" "backup drive"

  if [ "$DRY_RUN" = 0 ]; then
    confirm "Copy $SRC_MASTER and $DOTFILES_DIR to $BACKUP_ROOT now?" || { rec SKIP "declined"; return; }
  fi

  rsync_one "$DOTFILES_DIR" "$BACKUP_ROOT/macOS-dotfiles" "macOS-dotfiles" .venv __pycache__ .pytest_cache
  rsync_one "$SRC_MASTER"   "$BACKUP_ROOT/MacDatosMaster" "MacDatosMaster"

  # old safety copies of deleted files
  if [ -d "$BACKUP_ROOT/_deleted" ]; then
    local old n
    old=$(find "$BACKUP_ROOT/_deleted" -mindepth 1 -maxdepth 1 -type d -mtime +"$KEEP_DELETED_DAYS" 2>/dev/null)
    n=$(printf '%s' "$old" | grep -c .)
    if [ "$n" -gt 0 ]; then
      info "$n old '_deleted' folder(s) (> $KEEP_DELETED_DAYS days) on the backup drive:"
      printf '%s\n' "$old" | sed 's/^/      /'
      if confirm "Remove them for good?"; then
        printf '%s\n' "$old" | while IFS= read -r d; do run rm -rf "$d"; done
      fi
    fi
  fi
}

# =========================================================================== #
# STEP: trash                                                                 #
# =========================================================================== #

step_trash() {
  local kb=""
  if [ -d "$HOME/.Trash" ] && ls "$HOME/.Trash" >/dev/null 2>&1; then
    kb=$(dir_kb "$HOME/.Trash")
    local n; n=$(find "$HOME/.Trash" -mindepth 1 -maxdepth 1 2>/dev/null | wc -l | tr -d ' ')
    if [ "$n" = 0 ]; then good "Trash is already empty"; return; fi
    info "Trash holds $n item(s), $(human "$kb")"
  else
    note "(cannot read ~/.Trash: give Terminal 'Full Disk Access' to see its size)"
  fi
  note "Tip: Finder > Settings > Advanced > 'Remove items from the Trash after 30 days' does this safely by itself."
  confirm "Empty the Trash? This cannot be undone." || { rec SKIP "declined"; return; }
  if have osascript; then
    if run osascript -e 'tell application "Finder" to empty the trash'; then
      [ "$DRY_RUN" = 1 ] || good "Trash emptied"
    else
      bad "Finder could not empty the Trash (allow Terminal to control Finder: System Settings > Privacy & Security > Automation)"
      rec FAIL "empty trash failed"
    fi
  else
    warn "osascript not found"; rec SKIP "no osascript"
  fi
}

# =========================================================================== #
# STEP: downloads                                                             #
# =========================================================================== #

step_downloads() {
  local dir="$DOWNLOADS_DIR" now f name ext days age_days b m newest total=0 n=0 list="" kb
  [ -d "$dir" ] || { warn "$dir does not exist"; rec SKIP "no Downloads folder"; return; }
  now=$(date +%s)
  info "Rule: top-level items untouched for > $DOWNLOADS_DAYS days ($DOWNLOADS_INSTALLER_DAYS for .dmg/.pkg/.iso)."
  info "Never touched: hidden files, unfinished downloads (.crdownload .download .part), a folder named _Keep,"
  info "and any folder that contains a file changed within the limit. Files go to the TRASH, not to oblivion."
  while IFS= read -r -d '' f; do
    name=$(basename "$f")
    case "$name" in
      _Keep|*.crdownload|*.download|*.part|*.partial|*.opdownload|*.aria2|*.tmp) continue ;;
    esac
    ext=$(printf '%s' "${name##*.}" | tr '[:upper:]' '[:lower:]')
    days="$DOWNLOADS_DAYS"
    case "$ext" in dmg|pkg|mpkg|iso) days="$DOWNLOADS_INSTALLER_DAYS" ;; esac
    set -- $(stat -f '%B %m' "$f" 2>/dev/null)
    b="${1:-0}"; m="${2:-0}"
    newest=$b; [ "$m" -gt "$newest" ] && newest=$m
    age_days=$(( (now - newest) / 86400 ))
    [ "$age_days" -ge "$days" ] || continue
    if [ -d "$f" ] && [ -n "$(find "$f" -type f -mtime -"$days" -print 2>/dev/null | head -n 1)" ]; then
      continue
    fi
    kb=$(dir_kb "$f")
    total=$(( total + kb )); n=$(( n + 1 ))
    list="${list}${f}"$'\n'
    printf '      %9s  %4sd  %s\n' "$(human "$kb")" "$age_days" "$name"
  done < <(find "$dir" -mindepth 1 -maxdepth 1 ! -name '.*' -print0 2>/dev/null)

  if [ "$n" = 0 ]; then good "nothing to clean in $dir"; return; fi
  info "$n item(s), $(human "$total") in total"
  confirm "Move these $n item(s) to the Trash? (recoverable until the Trash is emptied)" || { rec SKIP "declined"; return; }
  if [ "$DRY_RUN" = 1 ]; then
    info "[dry-run] would move $n item(s) to the Trash"
    return
  fi
  local rc=0
  # one call per 40 items keeps the AppleScript short
  printf '%s' "$list" | tr '\n' '\0' > "$TMP/dl.list"
  local batch=() cnt=0
  while IFS= read -r -d '' f; do
    batch+=("$f"); cnt=$((cnt+1))
    if [ "$cnt" -ge 40 ]; then to_trash "${batch[@]}" || rc=1; batch=(); cnt=0; fi
  done < "$TMP/dl.list"
  [ "$cnt" -gt 0 ] && { to_trash "${batch[@]}" || rc=1; }
  if [ "$rc" = 0 ]; then good "moved $n item(s) to the Trash ($(human "$total"))"; else warn "some items could not be moved"; rec WARN "downloads: some items not moved"; fi
}

# =========================================================================== #
# STEP: cleanup (browser caches + old logs)                                   #
# =========================================================================== #

browser_running() {
  case "$1" in
    chrome)  pgrep -x "Google Chrome" >/dev/null 2>&1 ;;
    safari)  pgrep -x "Safari" >/dev/null 2>&1 ;;
    firefox) pgrep -x "firefox" >/dev/null 2>&1 ;;
    brave)   pgrep -x "Brave Browser" >/dev/null 2>&1 ;;
    edge)    pgrep -x "Microsoft Edge" >/dev/null 2>&1 ;;
    *) return 1 ;;
  esac
}

# Print the cache folders (one per line) of a Chromium-family browser.
chromium_caches() { # vendor-dir-under-Application-Support  cache-dir-under-Library/Caches
  local app="$HOME/Library/Application Support/$1" c="$HOME/Library/Caches/$2" p sub
  [ -d "$c" ] && printf '%s\n' "$c"
  for p in "$app"/Default "$app"/Profile\ *; do
    [ -d "$p" ] || continue
    for sub in "Cache" "Code Cache" "GPUCache" "Service Worker/CacheStorage" "Service Worker/ScriptCache" "DawnCache"; do
      [ -d "$p/$sub" ] && printf '%s\n' "$p/$sub"
    done
  done
  for sub in GrShaderCache ShaderCache GraphiteDawnCache; do
    [ -d "$app/$sub" ] && printf '%s\n' "$app/$sub"
  done
  return 0
}

browser_cache_dirs() {
  local p
  case "$1" in
    chrome)  chromium_caches "Google/Chrome" "Google/Chrome" ;;
    brave)   chromium_caches "BraveSoftware/Brave-Browser" "BraveSoftware/Brave-Browser" ;;
    edge)    chromium_caches "Microsoft Edge" "Microsoft Edge" ;;
    safari)
      for p in "$HOME/Library/Caches/com.apple.Safari" "$HOME/Library/Containers/com.apple.Safari/Data/Library/Caches"; do
        [ -d "$p" ] && printf '%s\n' "$p"
      done ;;
    firefox)
      for p in "$HOME/Library/Caches/Firefox/Profiles/"*/cache2; do
        [ -d "$p" ] && printf '%s\n' "$p"
      done ;;
  esac
  return 0
}

step_cleanup() {
  info "${C_BOLD}Criteria that keep this safe${C_OFF}"
  note "  - Only CACHE folders the browser rebuilds by itself (pages, images, scripts, shaders)."
  note "  - NEVER cookies, logins, history, bookmarks, extensions, Local Storage, IndexedDB, sessions."
  note "  - A browser that is running is skipped (closing it first is the only safe way)."
  note "  - Logs: only files in ~/Library/Logs older than $LOGS_DAYS days. Not /var/log, not /Library, not 'Application Support'."
  note "  - Never touched: ~/Library/Caches as a whole, ~/.ollama (models), Hugo site folders, Mail, Messages, iCloud."
  echo

  local b dirs d kb total=0 list="" skipped=""
  for b in $BROWSERS; do
    if browser_running "$b"; then
      warn "$b is running: its cache is skipped"; skipped="$skipped $b"; continue
    fi
    dirs=$(browser_cache_dirs "$b")
    [ -n "$dirs" ] || continue
    while IFS= read -r d; do
      kb=$(dir_kb "$d")
      [ "$kb" -gt 0 ] || continue
      total=$(( total + kb ))
      list="${list}${d}"$'\n'
      printf '      %9s  [%s] %s\n' "$(human "$kb")" "$b" "${d#$HOME/}"
    done <<EOF
$dirs
EOF
  done
  [ -n "$skipped" ] && rec WARN "browsers running:$skipped"

  if [ -z "$list" ]; then
    good "no browser cache to clean"
  else
    info "browser caches: $(human "$total")"
    if confirm "Empty these browser caches?"; then
      local rc=0
      if [ "$DRY_RUN" = 1 ]; then
        info "[dry-run] would empty $(printf '%s' "$list" | grep -c .) cache folder(s)"
      else
        while IFS= read -r d; do
          [ -n "$d" ] || continue
          find "$d" -mindepth 1 -maxdepth 1 -exec rm -rf {} + 2>/dev/null || rc=1
        done <<EOF
$list
EOF
        if [ "$rc" = 0 ]; then good "browser caches emptied"; else
          warn "some caches could not be emptied (Safari needs Full Disk Access for Terminal)"; rec WARN "some caches not emptied"
        fi
      fi
    else rec SKIP "browser caches declined"; fi
  fi

  echo
  local logdir="$HOME/Library/Logs" nlogs lkb
  if [ -d "$logdir" ]; then
    nlogs=$(find "$logdir" -type f -mtime +"$LOGS_DAYS" ! -path "$LOG_DIR/*" 2>/dev/null | wc -l | tr -d ' ')
    if [ "$nlogs" -gt 0 ]; then
      lkb=$(find "$logdir" -type f -mtime +"$LOGS_DAYS" ! -path "$LOG_DIR/*" -exec du -sk {} + 2>/dev/null | awk '{s+=$1} END {print s+0}')
      info "$nlogs log file(s) older than $LOGS_DAYS days in ~/Library/Logs ($(human "$lkb"))"
      if confirm "Delete them?"; then
        if [ "$DRY_RUN" = 1 ]; then info "[dry-run] would delete $nlogs log file(s)"
        else find "$logdir" -type f -mtime +"$LOGS_DAYS" ! -path "$LOG_DIR/*" -delete 2>/dev/null; good "old logs deleted"; fi
      else rec SKIP "logs declined"; fi
    else good "no old logs"; fi
  fi

  # this script's own logs
  local oldlogs
  oldlogs=$(ls -1t "$LOG_DIR" 2>/dev/null | tail -n +$((KEEP_LOGS + 1)))
  if [ -n "$oldlogs" ] && [ "$DRY_RUN" = 0 ]; then
    printf '%s\n' "$oldlogs" | while IFS= read -r l; do rm -f "$LOG_DIR/$l"; done
  fi

  if [ "$PIP_CACHE_PURGE" = 1 ] && [ -x "$VENV_DIR/bin/python" ]; then
    run "$VENV_DIR/bin/python" -m pip cache purge
  fi
}

# =========================================================================== #
# STEP: brew                                                                  #
# =========================================================================== #

step_brew() {
  have brew || { warn "Homebrew not found"; rec SKIP "no brew"; return; }
  info "$(brew --version | head -1)"

  info "${C_BOLD}Updating the package index${C_OFF}"
  if [ "$DRY_RUN" = 1 ]; then
    note "(dry run: skipping 'brew update'; showing what is outdated from the current index)"
  else
    brew update || { bad "brew update failed"; rec FAIL "brew update failed"; return; }
  fi

  local outdated greedy=""
  [ "$BREW_GREEDY" = 1 ] && greedy="--greedy"
  outdated=$(brew outdated $greedy 2>/dev/null)
  if [ -z "$outdated" ]; then
    good "everything is up to date"
  else
    info "outdated packages:"
    printf '%s\n' "$outdated" | sed 's/^/      /'
    if printf '%s\n' "$outdated" | grep -Eq '^python(@[0-9.]+)?( |$)'; then
      warn "Python is among them: your virtual environment (myPython/.venv) may need rebuilding afterwards."
      rec WARN "python upgrade: check .venv"
    fi
    if printf '%s\n' "$outdated" | grep -Eiq '^(docker|ollama|virtualbox|vmware)'; then
      note "heads-up: a package that runs services (ollama, docker...) is in the list; quit it first if it is busy."
    fi
    if confirm "Upgrade all of them?"; then
      # shellcheck disable=SC2086
      run brew upgrade $greedy || { bad "brew upgrade reported errors"; rec FAIL "brew upgrade errors"; }
    else rec SKIP "upgrade declined"; fi
  fi

  info "${C_BOLD}Broken dependencies${C_OFF}"
  local missing deps
  missing=$(brew missing 2>/dev/null)
  if [ -z "$missing" ]; then
    good "no missing dependencies"
  else
    warn "missing dependencies:"
    printf '%s\n' "$missing" | sed 's/^/      /'
    deps=$(printf '%s\n' "$missing" | sed 's/^[^:]*: *//' | tr ' ' '\n' | sort -u | grep .)
    if confirm "Install the missing dependencies?"; then
      # shellcheck disable=SC2086
      run brew install $deps || { rec FAIL "brew install of dependencies failed"; }
    fi
  fi

  info "${C_BOLD}Unneeded dependencies${C_OFF}"
  local auto
  auto=$(brew autoremove --dry-run 2>/dev/null | grep -v '^==>' | grep .)
  if [ -z "$auto" ]; then good "nothing to autoremove"; else
    printf '%s\n' "$auto" | sed 's/^/      /'
    confirm "Remove these packages nobody needs anymore?" && run brew autoremove
  fi

  info "${C_BOLD}Old downloads and versions${C_OFF}"
  run brew cleanup --prune=30

  info "${C_BOLD}Health check${C_OFF}"
  local doc
  doc=$(brew doctor 2>&1)
  if printf '%s\n' "$doc" | grep -q "ready to brew"; then good "brew doctor: ready to brew"; else
    warn "brew doctor has remarks (shown below; read them, they are usually harmless):"
    printf '%s\n' "$doc" | head -n 25 | sed 's/^/      /'
    rec WARN "brew doctor remarks"
  fi

  if [ -f "$DOTFILES_DIR/Brewfile" ]; then
    if brew bundle check --file="$DOTFILES_DIR/Brewfile" >/dev/null 2>&1; then
      good "everything in your Brewfile is installed"
    else
      warn "your Brewfile lists things that are not installed:"
      brew bundle check --verbose --file="$DOTFILES_DIR/Brewfile" 2>&1 | sed 's/^/      /' | head -n 15
      note "  install them with:  brew bundle --file=$DOTFILES_DIR/Brewfile"
      rec WARN "Brewfile not satisfied"
    fi
    local extra
    extra=$(brew bundle cleanup --file="$DOTFILES_DIR/Brewfile" 2>/dev/null | grep -v '^Run ' | grep -v '^Using' | grep .)
    [ -n "$extra" ] && note "installed but not in your Brewfile (info only): $(printf '%s' "$extra" | tr '\n' ' ' | cut -c1-200)"
    [ "$BREWFILE_UPDATE" = 1 ] && run brew bundle dump --force --file="$DOTFILES_DIR/Brewfile"
  fi
}

# =========================================================================== #
# STEP: macos (system + App Store updates)                                    #
# =========================================================================== #

step_macos() {
  if have softwareupdate; then
    info "${C_BOLD}macOS updates${C_OFF} (softwareupdate --list)"
    local out
    out=$(softwareupdate --list 2>&1)
    if printf '%s\n' "$out" | grep -Eq '^\*|Label:'; then
      printf '%s\n' "$out" | grep -v '^Software Update Tool' | grep . | sed 's/^/      /'
      warn "macOS updates are available"
      rec WARN "macOS updates available"
      if [ "$MACOS_INSTALL" = 1 ]; then
        local rflag=""; [ "$MACOS_RESTART" = 1 ] && rflag="--restart"
        if confirm "Install the recommended macOS updates now? (the Mac may need to restart)"; then
          if ensure_sudo; then
            # shellcheck disable=SC2086
            run sudo softwareupdate --install --recommended $rflag || rec FAIL "softwareupdate failed"
          else rec SKIP "no sudo for softwareupdate"; fi
        fi
      else
        note "  install later with:  mac-maintain.sh --run --only macos --macos-install"
        note "  or in System Settings > General > Software Update"
      fi
    else
      good "macOS is up to date"
    fi
    local auto
    auto=$(defaults read /Library/Preferences/com.apple.SoftwareUpdate AutomaticallyInstallMacOSUpdates 2>/dev/null)
    [ -n "$auto" ] && info "automatic macOS update installs: $([ "$auto" = 1 ] && echo ON || echo OFF)"
  else
    note "(softwareupdate not found)"
  fi

  if have mas; then
    info "${C_BOLD}App Store apps${C_OFF} (mas outdated)"
    local mo
    mo=$(mas outdated 2>&1)
    if [ -z "$mo" ]; then good "App Store apps are up to date"; else
      printf '%s\n' "$mo" | sed 's/^/      /'
      if [ "$MAS_UPGRADE" = 1 ]; then
        confirm "Upgrade these App Store apps?" && run mas upgrade
      else
        note "  upgrade with:  mas upgrade   (or set MAS_UPGRADE=1)"
        rec WARN "App Store updates available"
      fi
    fi
  else
    note "App Store apps: install 'mas' (brew install mas) to list/upgrade them from the terminal."
  fi
}

# =========================================================================== #
# STEP: pip                                                                   #
# =========================================================================== #

step_pip() {
  local py="$VENV_DIR/bin/python"
  [ -d "$PYTHON_DIR" ] || { warn "$PYTHON_DIR not found"; rec SKIP "no myPython"; return; }
  if [ ! -x "$py" ]; then
    warn "no virtual environment at $VENV_DIR: skipped (this script never touches the system Python)"
    note "  create it:  cd $PYTHON_DIR && python3 -m venv .venv && .venv/bin/python -m pip install -r requirements.txt"
    rec SKIP "no .venv"; return
  fi
  if ! "$py" -c 'import sys' >/dev/null 2>&1; then
    bad "the virtual environment is broken (its Python was probably upgraded by Homebrew)"
    note "  rebuild:  cd $PYTHON_DIR && rm -rf .venv && python3 -m venv .venv && .venv/bin/python -m pip install -r requirements.txt"
    rec FAIL "broken .venv"; return
  fi
  info "$("$py" --version) in $VENV_DIR"
  [ -f "$PYTHON_DIR/requirements.txt" ] || { warn "no requirements.txt"; rec SKIP "no requirements.txt"; return; }

  info "${C_BOLD}Outdated packages${C_OFF} (read-only)"
  ( cd "$PYTHON_DIR" && "$py" -m pip list --outdated --format=columns 2>/dev/null | sed 's/^/      /' )

  if [ ! -f "$PYTHON_DIR/requirements.in" ]; then
    warn "no requirements.in: cannot rebuild requirements.txt safely, only reporting"
    note "  (requirements.in = the packages you import; requirements.txt = the pinned result)"
    rec WARN "no requirements.in"; return
  fi

  if [ "$DRY_RUN" = 1 ]; then
    info "[dry-run] would: upgrade pip, install pip-tools if missing, run"
    note "      pip-compile --upgrade requirements.in -o requirements.txt"
    note "      pip install -r requirements.txt ; pip check ; pytest"
    note "      and restore the old requirements.txt + packages if anything fails."
    return
  fi
  confirm "Upgrade pip and every package (with tests and automatic rollback)?" || { rec SKIP "declined"; return; }

  cp -p "$PYTHON_DIR/requirements.txt" "$TMP/requirements.txt.bak"
  ( cd "$PYTHON_DIR" && "$py" -m pip freeze > "$TMP/freeze.bak" 2>/dev/null )

  rollback() {
    warn "rolling back to the previous requirements.txt"
    cp -p "$TMP/requirements.txt.bak" "$PYTHON_DIR/requirements.txt"
    ( cd "$PYTHON_DIR" && "$py" -m pip install --quiet -r requirements.txt ) && info "previous versions restored" || bad "rollback install failed: run pip install -r requirements.txt yourself"
  }

  "$py" -m pip install --quiet --upgrade pip || { bad "could not upgrade pip"; rec FAIL "pip upgrade failed"; return; }
  if ! "$py" -m pip show pip-tools >/dev/null 2>&1; then
    info "installing pip-tools in the virtual environment (it compiles requirements.in)"
    "$py" -m pip install --quiet pip-tools || { bad "could not install pip-tools"; rec FAIL "pip-tools"; return; }
  fi

  if ! ( cd "$PYTHON_DIR" && "$py" -m piptools compile --upgrade --quiet --output-file=requirements.txt requirements.in ); then
    bad "pip-compile failed (a package conflict?): requirements.txt left as it was"
    cp -p "$TMP/requirements.txt.bak" "$PYTHON_DIR/requirements.txt"
    rec FAIL "pip-compile failed"; return
  fi
  if ! ( cd "$PYTHON_DIR" && "$py" -m pip install --quiet -r requirements.txt ); then
    bad "installing the new versions failed"; rollback; rec FAIL "install failed, rolled back"; return
  fi
  if ! ( cd "$PYTHON_DIR" && "$py" -m pip check ); then
    bad "pip check found incompatible packages"; rollback; rec FAIL "pip check failed, rolled back"; return
  fi

  if [ -d "$PYTHON_DIR/tests" ]; then
    if ! "$py" -m pytest --version >/dev/null 2>&1; then "$py" -m pip install --quiet pytest; fi
    info "running the tests with the new versions..."
    if ( cd "$PYTHON_DIR" && "$py" -m pytest -q 2>&1 | tail -n 5 | sed 's/^/      /'; exit "${PIPESTATUS[0]}" ); then
      good "tests pass with the new versions"
    else
      bad "tests FAILED with the new versions"; rollback; rec FAIL "tests failed, rolled back"; return
    fi
  else
    warn "no tests/ folder: the update was not verified"; rec WARN "no tests"
  fi

  local changes
  changes=$(diff "$TMP/requirements.txt.bak" "$PYTHON_DIR/requirements.txt" | grep -E '^[<>] [A-Za-z0-9_.-]+==' | sed 's/^< /      - /; s/^> /      + /')
  if [ -n "$changes" ]; then info "pinned versions that changed:"; printf '%s\n' "$changes"; good "requirements.txt updated"
  else good "requirements.txt already current"; fi
}

# =========================================================================== #
# STEP: git                                                                   #
# =========================================================================== #

G() { git -C "$DOTFILES_DIR" "$@"; }

# Looks at what is staged (in the index named by GIT_INDEX_FILE if set).
# Prints WHICH file and WHAT KIND of secret, never the secret itself. Returns 1 if suspicious.
scan_staged() {
  local found=0 files f hit size
  files=$(G diff --cached --name-only --diff-filter=ACMR)
  while IFS= read -r f; do
    [ -n "$f" ] || continue
    case "$f" in
      *.env.example|*.env.sample|*.env.template) ;;
      .env|*/.env|.env.*|*/.env.*)  warn "staged file looks like an .env: $f"; found=1 ;;
    esac
    case "$(basename "$f")" in
      id_rsa|id_ed25519|id_ecdsa|id_dsa|*.pem|*.p12|*.pfx|*.key|*.keychain|*.keychain-db|.netrc|.git-credentials|.npmrc|credentials.json|secrets.json|secrets.yml|secrets.yaml)
        warn "staged file looks like a key or credential: $f"; found=1 ;;
    esac
    size=$(G cat-file -s ":$f" 2>/dev/null || echo 0)
    if [ "${size:-0}" -gt $(( GIT_MAX_FILE_MB * 1048576 )) ]; then
      warn "staged file is larger than ${GIT_MAX_FILE_MB} MB (GitHub refuses > 100 MB): $f"; found=1
    fi
  done <<EOF
$files
EOF
  # content of ADDED lines only
  G diff --cached -U0 --no-color --diff-filter=ACMR > "$TMP/staged.diff" 2>/dev/null
  local label pattern
  while IFS='|' read -r label pattern; do
    [ -n "$label" ] || continue
    hit=$(grep -E '^\+' "$TMP/staged.diff" | grep -v '^+++' | grep -Ec -e "$pattern")
    if [ "${hit:-0}" -gt 0 ]; then
      warn "staged changes contain $label ($hit line(s)); the value is not shown here"
      found=1
    fi
  done <<'EOF'
a private key block|-----BEGIN [A-Z ]*PRIVATE KEY-----
an AWS access key|AKIA[0-9A-Z]{16}
a GitHub token|(ghp_|gho_|ghu_|ghs_|ghr_)[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{30,}
an OpenRouter or Anthropic or OpenAI key|(sk-or-v1-|sk-ant-|sk-proj-)[A-Za-z0-9_-]{20,}
a Slack token|xox[baprs]-[A-Za-z0-9-]{10,}
a TOR control password|TOR_CONTROL_PASS[[:space:]]*=[[:space:]]*[^[:space:]#]+
a hard-coded secret assignment|(password|passwd|secret|api_?key|access_?token)[[:space:]]*[=:][[:space:]]*['"][A-Za-z0-9/+_=.-]{16,}['"]
EOF
  return $found
}

step_git() {
  have git || { bad "git not found"; rec FAIL "no git"; return; }
  if [ ! -d "$DOTFILES_DIR" ] || ! G rev-parse --is-inside-work-tree >/dev/null 2>&1; then
    warn "$DOTFILES_DIR is not a git repository"; rec SKIP "not a repo"; return
  fi
  local branch remote_ok behind ahead
  branch=$(G rev-parse --abbrev-ref HEAD 2>/dev/null)
  info "repository: $DOTFILES_DIR   branch: $branch   remote: $(G remote get-url origin 2>/dev/null | sed -E 's#(https://)[^@/]+@#\1#')"

  if [ -n "$(G ls-files | grep -E '(^|/)\.DS_Store$' | head -n 1)" ]; then
    warn ".DS_Store files are tracked by git (macOS junk). Fix once:"
    note "      echo '.DS_Store' >> $DOTFILES_DIR/.gitignore && git -C $DOTFILES_DIR rm -r --cached --ignore-unmatch '*.DS_Store'"
    rec WARN ".DS_Store tracked"
  fi

  local status
  status=$(G status --porcelain 2>/dev/null)
  if [ -z "$status" ]; then
    good "working tree clean: nothing to commit"
  else
    info "changes to commit:"
    printf '%s\n' "$status" | head -n 40 | sed 's/^/      /'
    [ "$(printf '%s\n' "$status" | wc -l)" -gt 40 ] && note "      ... and more"

    # Scan what WOULD be committed. In a dry run use a throw-away copy of the index.
    if [ "$GIT_SCAN" = 1 ]; then
      local scan_rc
      if [ "$DRY_RUN" = 1 ]; then
        cp "$(G rev-parse --absolute-git-dir)/index" "$TMP/index.copy" 2>/dev/null
        GIT_INDEX_FILE="$TMP/index.copy" G add -A >/dev/null 2>&1
        GIT_INDEX_FILE="$TMP/index.copy" scan_staged; scan_rc=$?
      else
        G add -A
        scan_staged; scan_rc=$?
      fi
      if [ "$scan_rc" != 0 ]; then
        bad "possible secrets or oversized files in the changes: NOT committing"
        [ "$DRY_RUN" = 0 ] && G reset -q
        note "  review with git status / git diff; remove the file or add it to .gitignore."
        note "  If it is a false alarm run once with GIT_SCAN=0."
        rec FAIL "secrets scan blocked the commit"; return
      fi
      good "secrets scan: nothing suspicious in the staged changes"
    elif [ "$DRY_RUN" = 0 ]; then
      G add -A
    fi

    local msg; msg=$(date '+%Y-%m-%d %H:%M:%S')
    if [ "$DRY_RUN" = 1 ]; then
      info "[dry-run] would run: git add -A && git commit -m \"$msg\""
    else
      if G commit -q -m "$msg"; then good "committed: $msg ($(G rev-parse --short HEAD))"
      else bad "git commit failed"; rec FAIL "commit failed"; return; fi
    fi
  fi

  # --- push -----------------------------------------------------------------------
  if ! G remote get-url origin >/dev/null 2>&1; then
    warn "no remote 'origin': nothing to push"; rec WARN "no remote"; return
  fi
  [ "$IS_TTY" = 1 ] || export GIT_SSH_COMMAND="${GIT_SSH_COMMAND:-ssh -o BatchMode=yes -o ConnectTimeout=15}"
  export GIT_TERMINAL_PROMPT=0
  if ! G fetch -q origin 2>/dev/null; then
    warn "cannot reach the remote (offline, or the SSH key is locked): not pushing"
    rec WARN "remote unreachable"; return
  fi
  behind=0; ahead=0
  if G rev-parse --abbrev-ref '@{u}' >/dev/null 2>&1; then
    behind=$(G rev-list --count 'HEAD..@{u}' 2>/dev/null || echo 0)
    ahead=$(G rev-list --count '@{u}..HEAD' 2>/dev/null || echo 0)
  fi
  if [ "$DRY_RUN" = 1 ]; then
    info "[dry-run] the remote has $behind newer commit(s); you have $ahead unpushed commit(s) (plus today's, if any)."
    info "[dry-run] would run: git pull --rebase (only if behind), then git push"
    return
  fi
  if [ "$behind" -gt 0 ]; then
    info "the remote has $behind newer commit(s): git pull --rebase"
    if ! G pull --rebase --autostash -q; then
      G rebase --abort 2>/dev/null
      bad "pull --rebase failed (conflict?): aborted, nothing pushed. Resolve it by hand in $DOTFILES_DIR"
      rec FAIL "pull --rebase conflict"; return
    fi
  fi
  if G rev-parse --abbrev-ref '@{u}' >/dev/null 2>&1; then
    if [ "$(G rev-list --count '@{u}..HEAD')" = 0 ]; then good "already pushed: nothing to send"; return; fi
    G push -q && good "pushed to origin/$branch" || { bad "git push failed"; rec FAIL "push failed"; }
  else
    G push -q -u origin HEAD && good "pushed (new upstream origin/$branch)" || { bad "git push failed"; rec FAIL "push failed"; }
  fi
}

# =========================================================================== #
# Main                                                                        #
# =========================================================================== #

printf '%smac-maintain %s%s   %s   mode: %s%s%s\n' "$C_BOLD" "$VERSION" "$C_OFF" "$(date '+%A %d %B %Y, %H:%M')" \
  "$C_BOLD" "$([ "$DRY_RUN" = 1 ] && echo 'DRY RUN (nothing is changed; use --run)' || echo 'RUN')" "$C_OFF"
info "log: $LOG"

for s in $ALL_STEPS; do
  if want_step "$s"; then
    section "$s"
    CUR_STATUS="OK"; CUR_NOTE=""
    "step_$s"
    SUMMARY="${SUMMARY}${s}|${CUR_STATUS}|${CUR_NOTE}"$'\n'
  else
    SUMMARY="${SUMMARY}${s}|--|not selected"$'\n'
  fi
done

# --------------------------------------------------------------------------- #
# Summary                                                                     #
# --------------------------------------------------------------------------- #

section "summary"
EXIT=0
printf '%s' "$SUMMARY" | while IFS='|' read -r s st nt; do
  [ -n "$s" ] || continue
  case "$st" in
    OK)   c="$C_GRN" ;; WARN) c="$C_YEL" ;; FAIL) c="$C_RED" ;; *) c="$C_DIM" ;;
  esac
  printf '  %-12s %s%-5s%s %s\n' "$s" "$c" "$st" "$C_OFF" "$nt"
done
case "$SUMMARY" in *'|FAIL|'*) EXIT=1 ;; esac

FREE_AFTER_KB=$(free_kb "$DATA_VOL")
if [ "$DRY_RUN" = 0 ]; then
  DELTA=$(( FREE_AFTER_KB - FREE_BEFORE_KB ))
  if [ "$DELTA" -ge 0 ]; then info "disk space freed on the Mac: $(human "$DELTA") (now $(human "$FREE_AFTER_KB") free)"
  else info "free space changed by -$(human $(( -DELTA ))) (now $(human "$FREE_AFTER_KB") free)"; fi
else
  info "dry run: nothing was changed. Run again with --run to apply."
fi
info "took $(( $(date +%s) - START_EPOCH )) s   log: $LOG"
exit $EXIT
