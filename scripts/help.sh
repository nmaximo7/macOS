#!/usr/bin/env zsh
# =============================================================================
#  help.sh - Personal cheat sheet (memory aid)
#  Location : /Users/nmaximo7/macOS/scripts/help.sh   (alias: myhelp, defined in ~/.zsh_aliases)
#
#  Usage:
#     help.sh            interactive menu
#     help.sh 1..9       show one section directly
#     help.sh all        show everything
#     help.sh -s TEXT    search every section for TEXT (case-insensitive)
#     help.sh -h         usage
#
#  Sections:
#     1 Espanso     2 KeyClu     3 Spotlight   4 Raycast   5 AeroSpace
#     6 .zshrc      7 macOS/OpenClaw      8 Terminal    9 Finder/Screenshots
#     0 Tips on how to keep this file useful
#
#  Sections 1, 5 and 6 READ YOUR REAL CONFIG FILES, so they stay up to date
#  automatically. The other sections are static: edit them as you like.
# =============================================================================

# ---------- Always run under zsh (works even if launched with bash/sh) ------
if [ -z "$ZSH_VERSION" ]; then
  if command -v zsh >/dev/null 2>&1; then
    exec zsh "$0" "$@"
  else
    echo "help.sh needs zsh (it ships with macOS: /bin/zsh)." >&2
    exit 1
  fi
fi

# ---------- Settings you can change -----------------------------------------
ZSH_FILES=("$HOME/.zshrc" "$HOME/.zsh_aliases" "$HOME/.zsh_functions")
ESPANSO_MATCH_DIR="$HOME/Library/Application Support/espanso/match"
AEROSPACE_CONFIGS=("$HOME/.aerospace.toml" "$HOME/.config/aerospace/aerospace.toml")

# ---------- Colors ----------------------------------------------------------
if [[ -t 1 ]]; then
  B=$'\e[1m'; D=$'\e[2m'; R=$'\e[0m'
  C1=$'\e[1;36m'   # titles
  C2=$'\e[1;33m'   # keys
  C3=$'\e[0;32m'   # descriptions
  C4=$'\e[0;35m'   # sub-titles
else
  B=""; D=""; R=""; C1=""; C2=""; C3=""; C4=""
fi

# ---------- Helpers ---------------------------------------------------------
title() { printf "\n${C1}%s\n  %s\n%s${R}\n" "==============================================================" "$1" "=============================================================="; }
sub()   { printf "\n${C4}${B}-- %s --${R}\n" "$1"; }
row()   { printf "  ${C2}%-28s${R} ${C3}%s${R}\n" "$1" "$2"; }
note()  { printf "  ${D}%s${R}\n" "$1"; }

# =============================================================================
# 1. ESPANSO
# =============================================================================
sec_espanso() {
  title "1. ESPANSO - text expander   (open search/help: Alt + Space)"
  sub "How it works"
  row "Alt + Space"        "Espanso search bar: type to find any snippet, Enter to insert it"
  row "type a trigger"     "Trigger gets replaced instantly (e.g. :date -> today's date)"
  row "Backspace (right after)" "Undo the expansion and get the raw trigger back"
  row "Esc (in search bar)" "Close the search bar"

  sub "Useful terminal commands"
  row "espanso status"       "Is the service running?"
  row "espanso restart"      "Restart after editing a config file"
  row "espanso edit"         "Open the default match file in your editor"
  row "espanso edit -c"      "Open the config file"
  row "espanso match list"   "List ALL triggers (same data as below)"
  row "espanso path"         "Show where config / match / packages live"
  row "espanso log"          "See the log when something misbehaves"
  row "espanso package list" "Installed packages"
  row "espanso package install NAME" "Install a package from the Hub"
  row "espanso service register" "Register the service so it starts at login"

  sub "YOUR triggers (read live from your match files)"
  if [[ -d "$ESPANSO_MATCH_DIR" ]]; then
    local f found=0
    while IFS= read -r f; do
      [[ -n "$f" ]] || continue
      found=1
      awk -v file="${f:t}" -v k="$C2" -v d="$C3" -v r="$R" -v dm="$D" '
        function flush() { if (trig != "") { printf "  %s%-28s%s %s%s%s  %s(%s)%s\n", k, trig, r, d, rep, r, dm, file, r }; trig=""; rep="" }
        /^[[:space:]]*-?[[:space:]]*trigger:/ { flush(); sub(/^[[:space:]]*-?[[:space:]]*trigger:[[:space:]]*/, ""); gsub(/^["'\'']|["'\'']$/, ""); trig=$0; next }
        /^[[:space:]]*-?[[:space:]]*triggers:/ { flush(); sub(/^[[:space:]]*-?[[:space:]]*triggers:[[:space:]]*/, ""); gsub(/[\[\]"'\'']/, ""); trig=$0; next }
        /^[[:space:]]*replace:/ { sub(/^[[:space:]]*replace:[[:space:]]*/, ""); gsub(/^["'\'']|["'\'']$/, ""); rep=$0; if (rep ~ /^[|>]/) rep="(multi-line text)"; next }
        /^[[:space:]]*(image_path|html|markdown|form|vars):/ { if (rep=="") rep="(special content)" }
        END { flush() }
      ' "$f"
    done < <(find "$ESPANSO_MATCH_DIR" -type f -name '*.yml' 2>/dev/null | sort)
    (( found )) || note "No .yml files found in $ESPANSO_MATCH_DIR"
  else
    note "Folder not found: $ESPANSO_MATCH_DIR (run: espanso path)"
  fi
}

# =============================================================================
# 2. KEYCLU
# =============================================================================
sec_keyclu() {
  title "2. KEYCLU - shortcut viewer   (press Cmd 3 times)"
  row "Cmd Cmd Cmd"          "Show the shortcuts of the app you are currently in"
  row "Release Cmd"          "Hide the panel"
  row "Esc"                  "Close the panel"
  note "KeyClu lists the menu-bar shortcuts of the frontmost app: great"
  note "when you forget how to do something in Safari, Finder, Mail, VS Code..."
  sub "Ideas"
  row "Custom shortcuts"     "KeyClu > Preferences > add your own list for apps that lack menus"
  row "Different trigger"    "Preferences lets you change the 3x Cmd gesture if it conflicts"
  row "Pin a cheat sheet"    "Add this very help.sh shortcuts as a custom list"
}

# =============================================================================
# 3. SPOTLIGHT
# =============================================================================
sec_spotlight() {
  title "3. SPOTLIGHT   (Cmd + Space)"
  sub "Launching"
  row "Cmd + Space"          "Open Spotlight"
  row "type app name"        "Launch an app (Safari, Notes, Terminal...)"
  row "Enter"                "Open the selected result"
  row "Cmd + Enter"          "Reveal the file in Finder"
  row "Tab / arrows"         "Move through result groups"

  sub "Quick jumps (macOS Tahoe and later)"
  row "Cmd + 1"              "Applications browser"
  row "Cmd + 2"              "Files"
  row "Cmd + 3"              "Actions (shortcuts, app actions)"
  row "Cmd + 4"              "Clipboard history"

  sub "Things you can just type"
  row "12*7+3"               "Calculator, answer shown immediately"
  row "20 usd in eur"        "Currency conversion"
  row "15 km in miles"       "Unit conversion"
  row "define serendipity"   "Dictionary definition"
  row "madrid time"          "Time in another city"
  row "kind:pdf invoice"     "Filter by kind (pdf, folder, image, app, mail...)"
  row "name:report"          "Search only file names"
  row "created:today"        "Files created today (also modified:yesterday)"
  row "System Settings, Bluetooth" "Jump straight to a settings pane"
  row "Activity Monitor"     "Handy when the Mac is slow"
  row "Dark Mode / Night Shift" "Toggle through Actions"
}

# =============================================================================
# 4. RAYCAST
# =============================================================================
sec_raycast() {
  title "4. RAYCAST   (Ctrl + Space)"
  sub "Core"
  row "Ctrl + Space"         "Open Raycast"
  row "Cmd + K"              "Action menu for the selected item (the secret weapon)"
  row "Cmd + ,"              "Raycast settings"
  row "Tab"                  "Switch to the argument field of a command"
  row "Esc"                  "Go back / close"

  sub "Main keywords to type"
  row "clipboard"            "Clipboard History"
  row "snippets"             "Search / create text snippets"
  row "emoji"                "Emoji & symbols picker"
  row "window / left half"   "Window management (Left Half, Maximize, Center...)"
  row "calc / 25*4"          "Calculator and unit/currency conversion"
  row "kill / quit"          "Force quit a process / Quit apps"
  row "color"                "Color picker"
  row "search files"         "File search"
  row "quicklinks"           "Open or create web shortcuts"
  row "notes / floating"     "Floating Notes"
  row "translate"            "Translator"
  row "ai / Tab"             "Raycast AI (if enabled)"
  row "confetti"             "Because you deserve it"
  row "store"                "Browse the extension Store"
  note "Tip: give your most-used commands an ALIAS in Raycast Settings > Extensions"
  note "(e.g. 'cb' for Clipboard History) and a global hotkey."
  sub "Window management hotkeys you may have set"
  note "Check: Raycast > Window Management > assign hotkeys (e.g. Ctrl+Opt+Arrows)."
}

# =============================================================================
# 5. AEROSPACE
# =============================================================================
sec_aerospace() {
  title "5. AEROSPACE - tiling window manager   (main key: Alt)"
  sub "Defaults (the stock config; yours may differ, see live list below)"
  row "Alt + H/J/K/L"        "Focus window left/down/up/right"
  row "Alt+Shift + H/J/K/L"  "Move window left/down/up/right"
  row "Alt + 1..9 / A..Z"    "Go to workspace"
  row "Alt+Shift + 1..9/A..Z" "Send window to workspace"
  row "Alt + Tab"            "Previous workspace (back-and-forth)"
  row "Alt+Shift + Tab"      "Move workspace to next monitor"
  row "Alt + /"              "Toggle layout tiles (horizontal/vertical)"
  row "Alt + ,"              "Toggle layout accordion"
  row "Alt+Shift + - / ="    "Resize window smaller / bigger"
  row "Alt+Shift + ;"        "Enter SERVICE mode"
  sub "Service mode (after Alt+Shift+;)"
  row "Esc"                  "Reload config and leave service mode"
  row "R"                    "Reset (flatten) the workspace tree"
  row "F"                    "Toggle floating / tiling for the window"
  row "Backspace"            "Close all windows but the current one"
  row "Alt+Shift + H/J/K/L"  "Join with neighbouring window"

  sub "Command line"
  row "aerospace reload-config"  "Apply config changes"
  row "aerospace list-windows --all" "See every window and its workspace"
  row "aerospace list-workspaces --all" "All workspaces"
  row "aerospace layout floating" "Float the focused window"
  row "aerospace enable toggle"  "Pause / resume AeroSpace"

  sub "YOUR bindings (read live from your aerospace.toml)"
  local cfg=""
  for f in "${AEROSPACE_CONFIGS[@]}"; do [[ -f "$f" ]] && { cfg="$f"; break; }; done
  if [[ -n "$cfg" ]]; then
    note "Source: $cfg"
    awk -v k="$C2" -v d="$C3" -v r="$R" -v m="$C4" '
      /^\[mode\.[^.]+\.binding\]/ { mode=$0; sub(/^\[mode\./,"",mode); sub(/\.binding\]/,"",mode); printf "  %s[mode: %s]%s\n", m, mode, r; inb=1; next }
      /^\[/ { inb=0 }
      inb && /^[[:space:]]*[A-Za-z0-9_-]+[[:space:]]*=/ {
        line=$0; sub(/^[[:space:]]+/,"",line)
        key=line; sub(/[[:space:]]*=.*/,"",key)
        cmd=line; sub(/^[^=]*=[[:space:]]*/,"",cmd)
        gsub(/#.*/,"",cmd)
        printf "  %s%-28s%s %s%s%s\n", k, key, r, d, cmd, r
      }
    ' "$cfg"
  else
    note "No aerospace.toml found in: ${AEROSPACE_CONFIGS[*]}"
  fi
}

# =============================================================================
# 6. .ZSHRC  (aliases + functions, read live)
# =============================================================================
sec_zsh() {
  title "6. .zshrc - aliases & functions (read live from your files)"
  note "Tip: put a comment line right ABOVE each alias/function and it will"
  note "show up here as its description:   # list files nicely"
  local f found=0
  for f in "${ZSH_FILES[@]}"; do
    [[ -f "$f" ]] || continue
    found=1
    sub "Aliases in ${f/#$HOME/~}"
    awk -v k="$C2" -v d="$C3" -v r="$R" -v dm="$D" '
      /^[[:space:]]*#/ { c=$0; sub(/^[[:space:]]*#+[[:space:]]*/,"",c); next }
      /^[[:space:]]*alias[[:space:]]/ {
        l=$0; sub(/^[[:space:]]*alias[[:space:]]+(-[a-z]+[[:space:]]+)?/,"",l)
        name=l; sub(/=.*/,"",name)
        val=l; sub(/^[^=]*=/,"",val); gsub(/^["'\'']|["'\'']$/,"",val)
        if (c != "") printf "  %s%-18s%s %s%s%s  %s# %s%s\n", k, name, r, d, val, r, dm, c, r
        else         printf "  %s%-18s%s %s%s%s\n", k, name, r, d, val, r
        c=""; next }
      { c="" }
    ' "$f"
    sub "Functions in ${f/#$HOME/~}"
    awk -v k="$C2" -v d="$C3" -v r="$R" '
      /^[[:space:]]*#/ { c=$0; sub(/^[[:space:]]*#+[[:space:]]*/,"",c); next }
      /^[[:space:]]*(function[[:space:]]+)?[A-Za-z_][A-Za-z0-9_.-]*[[:space:]]*(\(\))?[[:space:]]*\{/ {
        n=$0; sub(/^[[:space:]]*(function[[:space:]]+)?/,"",n); sub(/[[:space:]]*(\(\))?[[:space:]]*\{.*/,"",n)
        if (n ~ /^(if|for|while|case|until|select)$/) { c=""; next }
        if (c != "") printf "  %s%-18s%s %s%s%s\n", k, n "()", r, d, c, r
        else         printf "  %s%-18s%s\n", k, n "()", r
        c=""; next }
      { c="" }
    ' "$f"
    sub "Exports / PATH in ${f/#$HOME/~}"
    grep -E '^[[:space:]]*export[[:space:]]+(PATH|EDITOR|VISUAL|LANG|HISTSIZE)' "$f" 2>/dev/null | sed 's/^[[:space:]]*/  /'
  done
  (( found )) || note "No zsh files found in: ${ZSH_FILES[*]}"
  sub "Handy built-ins to remember"
  row "alias"                "List every alias currently loaded"
  row "functions | less"     "List every function currently loaded"
  row "type NAME"            "What is NAME? (alias, function, binary)"
  row "which NAME / where NAME" "Where does it live?"
  row "source ~/.zshrc"      "Reload your config after editing"
  row "history | grep TEXT"  "Find an old command"
}

# =============================================================================
# 7. macOS SYSTEM & OpenClaw SHORTCUTS
# =============================================================================
sec_macos() {
  title "7. macOS - system shortcuts"
  sub "Everyday"
  row "Cmd + Tab"            "Switch app (Cmd + backtick key switches windows of the same app)"
  row "Cmd + Q / W / M / H"  "Quit / close window / minimize / hide"
  row "Cmd + Opt + Esc"      "Force Quit dialog"
  row "Cmd + Ctrl + Q"       "Lock screen"
  row "Cmd + Ctrl + F"       "Full-screen toggle"
  row "Cmd + Shift + 5"      "Screenshot / screen recording toolbar"
  row "Ctrl + Cmd + Space"   "Emoji picker"
  row "Cmd + , "             "Preferences of the current app"
  row "Cmd + Z / Shift+Cmd+Z" "Undo / redo"
  row "Cmd + Shift + V"      "Paste and match style (in many apps)"
  sub "Text editing (works everywhere)"
  row "Opt + Left/Right"     "Jump word by word"
  row "Cmd + Left/Right"     "Start / end of line"
  row "Opt + Delete"         "Delete previous word"
  row "Cmd + Delete"         "Delete to start of line"
  row "Ctrl + A / E"         "Start / end of line (also in most text fields)"
  row "Ctrl + K"             "Delete to end of line"
  sub "Mission Control & spaces"
  row "Ctrl + Up"            "Mission Control"
  row "Ctrl + Left/Right"    "Switch desktop (macOS spaces)"
  row "F11 / Fn + F11"       "Show desktop"
  sub "System"
  row "Cmd + Opt + Power"    "Sleep"
  row "Ctrl + Cmd + Power"   "Force restart"
  row "Hold Opt on Wi-Fi/Sound icon" "Extra details / choose audio device"
  sub "OpenClaw"
  row "☀️ /daily-briefing"  "Daily briefings: Calendar, mail, weather, todo"
  row "⚙️ /gog" 	          "Gmail, Calendar, Drive via CLI"
  row "⚙️ /gog, e.g.," 	    "/gog gmail messages search -a nmaximo7@gmail.com 'in:inbox newer_than:7d'"
  row "🎙️ /local-audio"	   "Local audio transcription (Whisper CLI)"
  row "🎙️ /local-audio, e.g.,"	"/local-audio Transcribe the file at ~/Downloads/sample-speech.mp3"
  row "☔ /weather"          "Weather + forecasts"
  row "⚙️ /qmd"	            "Local file search"
  row "⚙️ /qmd, e.g.,"      "qmd search \"Todo\" -c macOS"
  row "/summarize-pro [text]"	"Summarize text/articles/docs"
  row "🌐 /local-search"	  "Local web search (DuckDuckGo/Bing/Google)"
  row "🌐 /local-search, e.g.,"	 "/local-search popular skills for OpenClaw"
  row "🙏 /daily-gospel"     "Daily Gospel"
  row "💸 /finance, e.g.,"  "Finance news, /finance compare AAPL,MSFT,GOOGL"
  row "Basic commands:"    "openclaw [setup | doctor | gateway restart | status]"
  row "/model openrouter/openrouter/free" "Switch model, then send your question"
  row "/model list"       "See available models"
  row "/site_health_check" "Check site health"
}

# =============================================================================
# 8. TERMINAL
# =============================================================================
sec_terminal() {
  title "8. TERMINAL - zsh survival kit"
  sub "Line editing"
  row "Ctrl + R"             "Search command history (type, then Ctrl+R again for older)"
  row "Ctrl + A / E"         "Start / end of line"
  row "Ctrl + W"             "Delete previous word"
  row "Ctrl + U"             "Delete whole line before cursor"
  row "Ctrl + L"             "Clear screen"
  row "Ctrl + C"             "Cancel the running command"
  row "Ctrl + D"             "Exit shell / end of input"
  row "Ctrl + Z, then fg"    "Suspend a command, then bring it back"
  row "Esc then ."           "Paste last argument of previous command"
  row "!!"                   "Repeat last command (sudo !! to rerun with sudo)"
  row "!\$"                   "Last argument of previous command"
  row "Tab Tab"              "Autocomplete / show options"
  sub "Navigation"
  row "cd -"                 "Go back to previous directory"
  row "cd ~ / cd .."         "Home / parent"
  row "pwd"                  "Where am I?"
  row "ls -lah"              "Long list with hidden files and human sizes"
  row "open ."               "Open current folder in Finder"
  row "open -a APP FILE"     "Open a file with a specific app"
  sub "Search & inspect"
  row "grep -rin TEXT ."     "Search text recursively, case-insensitive"
  row "find . -name '*.pdf'" "Find files by name"
  row "mdfind NAME"          "Spotlight search from the terminal"
  row "du -sh * | sort -h"   "Which folders are big?"
  row "df -h"                "Disk free"
  row "tail -f FILE"         "Follow a log live"
  row "less FILE (q to quit)" "Read a file page by page"
  sub "macOS-only gems"
  row "pbcopy / pbpaste"     "Clipboard from the terminal (cat file | pbcopy)"
  row "caffeinate -d"        "Keep the Mac awake while running"
  row "say 'hello'"          "Text to speech"
  row "defaults read DOMAIN" "Read app preferences"
  row "brew update && brew upgrade" "Update Homebrew and its packages"
  row "brew list / brew search X"   "What is installed / find a package"
  row "killall Finder"       "Restart Finder"
  row "networksetup -getairportnetwork en0" "Current Wi-Fi network"
  row "ipconfig getifaddr en0" "Your local IP address"
  row "curl ifconfig.me"     "Your public IP address"
  row "🛠️ maintain-mac.sh --run"   "Weekly maintenance (dry run without --run; --only brew,pip; --list)"
  row "searx.sh start|stop|status" "My private search engine (SearXNG in Docker)"
  row "ai-on / ai-off"       "Load / unload the local AI (Ollama + Continue)"
  row "content_creation"     "Check and improve the Hugo page edited last (--skip searx, --help)"
  row "greetings"            "Daily briefing (calendar, quote, weather, news, stocks)"
  sub "Git (the daily ones)"
  row "git status / git diff" "What changed?"
  row "git add -p"           "Stage changes chunk by chunk"
  row "git commit -m 'msg'"  "Commit"
  row "git log --oneline --graph -15" "Compact history"
  row "git switch -c NAME"   "New branch"
  row "git stash / stash pop" "Park changes / bring them back"
}

# =============================================================================
# 9. FINDER & SCREENSHOTS
# =============================================================================
sec_finder() {
  title "9. FINDER & SCREENSHOTS"
  sub "Finder"
  row "Space"                "Quick Look preview of the selected file"
  row "Cmd + Shift + G"      "Go to folder (type a path)"
  row "Cmd + Shift + ."      "Show / hide hidden files"
  row "Cmd + Shift + N"      "New folder"
  row "Cmd + Opt + C"        "Copy file path"
  row "Cmd + Opt + V"        "Move (instead of copy) pasted items"
  row "Cmd + Up"             "Parent folder"
  row "Cmd + Delete"         "Move to Trash"
  row "Cmd + Shift + Delete" "Empty Trash"
  row "Cmd + J"              "View options"
  row "Cmd + 1/2/3/4"        "Icon / list / column / gallery view"
  row "Cmd + Shift + A/U/D/H" "Applications / Utilities / Desktop / Home"
  row "Enter"                "Rename the selected file"
  sub "Screenshots"
  row "Cmd + Shift + 3"      "Whole screen"
  row "Cmd + Shift + 4"      "Selected area (Space = a window)"
  row "Cmd + Shift + 5"      "Toolbar: record screen, choose destination"
  row "+ Ctrl"               "Add Ctrl to any of the above to copy to clipboard"
}

# =============================================================================
# 0. TIPS
# =============================================================================
sec_tips() {
  title "0. KEEPING THIS HELP USEFUL"
  row "Alias"                "myhelp (defined in ~/.zsh_aliases) runs ~/macOS/scripts/help.sh"
  row "Quick search"         "myhelp -s clipboard    (finds every mention in every section)"
  row "Direct section"       "myhelp 5   -> AeroSpace,  myhelp 6 -> aliases"
  row "Comment your aliases" "A comment line above each alias/function becomes its description"
  row "Espanso trigger"      "Create :help that runs this script in a terminal"
  row "Raycast script"       "Put a script command in Raycast that opens Terminal with help.sh"
  row "Print it"             "myhelp all > ~/Desktop/cheatsheet.txt   (colors off when redirected)"
  row "Back it up"           "Keep ~/macOS in git or iCloud so you never lose it"
  note "Edit the static sections whenever you learn a new shortcut."
}

# =============================================================================
# Dispatcher
# =============================================================================
sections() {
  case "$1" in
    1) sec_espanso ;;  2) sec_keyclu ;;   3) sec_spotlight ;;
    4) sec_raycast ;;  5) sec_aerospace ;; 6) sec_zsh ;;
    7) sec_macos ;;    8) sec_terminal ;;  9) sec_finder ;;
    0) sec_tips ;;
    all) for n in 1 2 3 4 5 6 7 8 9 0; do sections $n; done ;;
    *) echo "Unknown section: $1" >&2; return 1 ;;
  esac
}

show() {
  if [[ -t 1 && -z "$HELP_NOPAGER" ]] && command -v less >/dev/null; then
    sections "$1" | less -R -F -X
  else
    sections "$1"
  fi
}

search() {
  local term="$1"
  [[ -z "$term" ]] && { echo "Usage: $0 -s TEXT"; return 1; }
  sections all | sed $'s/\e\\[[0-9;]*m//g' | grep -i --color=always "$term"
}

usage() {
  cat <<EOF
Usage: ${0:t} [section | all | -s TEXT | -h]
  1 Espanso      2 KeyClu        3 Spotlight    4 Raycast     5 AeroSpace
  6 .zshrc       7 macOS         8 Terminal     9 Finder      0 Tips
  all            everything       -s TEXT        search
EOF
}

menu() {
  while true; do
    printf "\n${C1}${B}  HELP - what do you want to remember?${R}\n\n"
    printf "   ${C2}1${R} Espanso (Alt+Space)      ${C2}6${R} .zshrc aliases & functions\n"
    printf "   ${C2}2${R} KeyClu (Cmd x3)          ${C2}7${R} macOS shortcuts & OpenClaw\n"
    printf "   ${C2}3${R} Spotlight (Cmd+Space)    ${C2}8${R} Terminal survival kit\n"
    printf "   ${C2}4${R} Raycast (Ctrl+Space)     ${C2}9${R} Finder & screenshots\n"
    printf "   ${C2}5${R} AeroSpace (Alt)          ${C2}0${R} Tips\n\n"
    printf "   ${C2}a${R} all    ${C2}s${R} search    ${C2}q${R} quit\n\n"
    printf "  > "
    read -k1 choice; echo
    case "$choice" in
      [0-9]) show "$choice" ;;
      a|A)   show all ;;
      s|S)   printf "  search for: "; read term; search "$term" | less -R ;;
      q|Q|$'\e'|"") return 0 ;;
      *)     echo "  ?" ;;
    esac
  done
}

case "$1" in
  "")        menu ;;
  -h|--help) usage ;;
  -s)        shift; search "$*" ;;
  *)         show "$1" ;;
esac
