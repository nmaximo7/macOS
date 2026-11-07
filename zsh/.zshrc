export PATH="/Users/nmaximo7/.openclaw/bin:$PATH"
# =============================================================================
# ~/.zshrc  (stow package: zsh/.zshrc)   macOS, Apple Silicon, Ghostty, Starship
#
# ORDER MATTERS in this file. Each section depends on the previous ones:
#   1. PATH + Homebrew          everything below needs `brew` and your tools on PATH
#   2. Environment variables    editor, language, pager
#   3. Oh My Zsh                framework: plugins, git aliases, completion system
#   4. Shell behaviour          history, options, completion look, key bindings
#   5. Tools                    fzf (Ctrl-R / Ctrl-T / Alt-C) and zoxide (smart cd)
#   6. Your files               aliases, functions, machine-specific overrides
#   7. Prompt                   Starship
#   8. Plugins that wrap keys   autosuggestions, then syntax highlighting LAST
#
# Handy:  reload = exec zsh   |   zshbench = how long startup takes
#         zshprof = which line is slow   |   ezsh = edit this file
# =============================================================================

# Profiling switch: `ZPROF=1 zsh -i -c exit` prints a table of where startup time goes.
[[ -n $ZPROF ]] && zmodload zsh/zprof

# Directory with your dotfiles repo. Aliases and functions refer to it.
export DOTFILES="$HOME/macOS"


# =============================================================================
# 1. PATH + HOMEBREW
# =============================================================================
# `typeset -U` keeps PATH free of duplicates, so re-sourcing this file never grows it.
typeset -U path PATH

# Apple Silicon installs Homebrew in /opt/homebrew (Intel: /usr/local). `brew shellenv`
# sets PATH, MANPATH, FPATH (so Homebrew completions work) and HOMEBREW_PREFIX.
# Normally ~/.zprofile does this already, so this only runs if it did not.
if [[ -z $HOMEBREW_PREFIX ]]; then
    for _brew in /opt/homebrew/bin/brew /usr/local/bin/brew; do
        if [[ -x $_brew ]]; then eval "$($_brew shellenv)"; break; fi
    done
    unset _brew
fi

# Your own scripts first. This is a good place to put aliases and functions.
path=("$HOME/bin" "$HOME/.local/bin" $path)


# =============================================================================
# 2. ENVIRONMENT VARIABLES
# =============================================================================
export LANG="en_US.UTF-8"     # English messages + UTF-8 everywhere
export CLICOLOR=1             # colour for the BSD `ls` that ships with macOS

# EDITOR/VISUAL: used by git commit, crontab -e, fc, sudoedit...
# Homebrew puts nvim in /opt/homebrew/bin, never /usr/bin, so a hardcoded path breaks.
# $+commands[nvim] is a zsh test that evaluates to 1
# if nvim is known as an available command, and 0 otherwise.
if (( $+commands[nvim] )); then export EDITOR=nvim; else export EDITOR=vim; fi
export VISUAL="$EDITOR"

# GPG (GNU Privacy Guard: signs commits and encrypts files, it is NOT a password
# manager). It needs to know your terminal to ask for the key passphrase.
export GPG_TTY=$(tty 2>/dev/null)

# Coloured man pages through bat (needs: brew install bat). `col -bx` strips the
# backspace-based bold/underline that man emits, bat re-colours the text.
if (( $+commands[bat] )); then
    export MANPAGER="sh -c 'col -bx | bat -l man -p'"
fi

# Homebrew: no telemetry, no "hints" after every command.
export HOMEBREW_NO_ANALYTICS=1
export HOMEBREW_NO_ENV_HINTS=1

# fzf: use `fd` (fast, respects .gitignore) when installed, with Catppuccin Mocha colours.
if (( $+commands[fd] )); then
    export FZF_DEFAULT_COMMAND='fd --type f --hidden --follow --exclude .git'
    export FZF_CTRL_T_COMMAND="$FZF_DEFAULT_COMMAND"
fi
export FZF_DEFAULT_OPTS="--height=40% --layout=reverse --border \
--color=bg+:#313244,spinner:#f5e0dc,hl:#f38ba8,fg:#cdd6f4,header:#f38ba8 \
--color=info:#cba6f7,pointer:#f5e0dc,marker:#b4befe,fg+:#cdd6f4,prompt:#cba6f7,hl+:#f38ba8"


# =============================================================================
# 3. OH MY ZSH
# =============================================================================
export ZSH="$HOME/.oh-my-zsh"
export ZSH_CUSTOM="$ZSH/custom"

ZSH_THEME=""                              # Starship draws the prompt, OMZ must not.
zstyle ':omz:update' mode reminder        # remind about updates, never update silently
zstyle ':omz:update' frequency 14         # ...at most every 14 days
DISABLE_AUTO_TITLE="true"                 # Ghostty sets the tab title (shell-integration "title")

# Plugins, only those you really use (each one costs startup time):
#   git        ~200 aliases: gst (status), gsb (status -sb), gco, gcb, gp, gl (pull), glog...
#   brew       brew aliases and completions (bubo = update+outdated, bubc = upgrade+cleanup)
#   macos      ofd (open Finder here), cdf (cd to Finder folder), pfd, quick-look (ql)...
#   python/pip py, mkv/vrun (create/activate a venv), pip aliases
#   sudo       press ESC twice to put `sudo` in front of the current (or last) command
#   extract    `extract file.zip|tar.gz|7z|...` and the alias `x`: one command for every archive
#   web-search `google foo`, `ddg foo`, `github foo` opens the browser
plugins=(git brew macos python pip sudo extract web-search)

# OMZ also runs compinit (the completion system) here, so do NOT call compinit again.
[[ -r $ZSH/oh-my-zsh.sh ]] && source "$ZSH/oh-my-zsh.sh"


# =============================================================================
# 4. SHELL BEHAVIOUR (after OMZ so these settings win)
# =============================================================================

# ---- History ----------------------------------------------------------------
HISTFILE="$HOME/.zsh_history"
HISTSIZE=120000      # kept in memory. Keep it larger than SAVEHIST so duplicates can be
SAVEHIST=100000      # expired first (HIST_EXPIRE_DUPS_FIRST) before real history is lost.
setopt EXTENDED_HISTORY          # save a timestamp and duration with every command
setopt SHARE_HISTORY             # all open tabs share one history. This ALSO appends
                                 # immediately, so INC_APPEND_HISTORY is not needed (the zsh
                                 # manual says to turn it off when SHARE_HISTORY is on)
setopt HIST_IGNORE_DUPS          # skip a command identical to the previous one
setopt HIST_EXPIRE_DUPS_FIRST    # when full, drop duplicates before unique entries
setopt HIST_FIND_NO_DUPS         # Ctrl-R / search do not show the same command twice
setopt HIST_IGNORE_SPACE         # a command starting with a space is not saved (for secrets)
setopt HIST_REDUCE_BLANKS        # trim superfluous blanks
setopt HIST_VERIFY               # `!!` and `!$` are shown first, you press Enter to run them

# Never save these: trivial commands, and lines that contain secrets.
HISTORY_IGNORE="(ls|ll|la|cd|pwd|exit|clear|history|reload|*TOKEN=*|*PASSWORD=*|*SECRET=*|*API_KEY=*)"

# ---- Options -----------------------------------------------------------------
setopt AUTO_CD               # typing a folder name cd's into it
setopt AUTO_PUSHD            # every cd is pushed on a stack: `dirs -v`, then `cd -2`
setopt PUSHD_IGNORE_DUPS
setopt PUSHD_SILENT
setopt INTERACTIVE_COMMENTS  # allow `# comments` when typing commands
setopt COMPLETE_IN_WORD      # complete in the middle of a word
setopt NO_BEEP

# ---- Completion look ---------------------------------------------------------
zstyle ':completion:*' matcher-list 'm:{a-zA-Z}={A-Za-z}'    # case-insensitive: `cd doc<Tab>` finds Documents
zstyle ':completion:*' menu select                           # arrow-key menu for completions
zstyle ':completion:*:descriptions' format '%F{8}── %d ──%f'  # dim group headings

# ---- Key bindings ------------------------------------------------------------
# Up/Down search the history for commands that START WITH what you already typed.
zmodload zsh/terminfo
autoload -Uz up-line-or-beginning-search down-line-or-beginning-search
zle -N up-line-or-beginning-search
zle -N down-line-or-beginning-search
[[ -n ${terminfo[kcuu1]} ]] && bindkey "${terminfo[kcuu1]}" up-line-or-beginning-search
[[ -n ${terminfo[kcud1]} ]] && bindkey "${terminfo[kcud1]}" down-line-or-beginning-search
# Option+Left/Right jump by word: works because Ghostty has `macos-option-as-alt = true`.


# =============================================================================
# 5. TOOLS
# =============================================================================
# fzf: Ctrl-R fuzzy history, Ctrl-T pick a file, Alt-C jump to a folder.
# (`fzf --zsh` needs fzf >= 0.48; Alt-C needs macos-option-as-alt in Ghostty.)
(( $+commands[fzf] )) && source <(fzf --zsh)

# zoxide: `z foo` jumps to the folder you use most that matches "foo"; `zi` picks interactively.
(( $+commands[zoxide] )) && eval "$(zoxide init zsh)"


# =============================================================================
# 6. YOUR FILES
# =============================================================================
[[ -f ~/.zsh_aliases   ]] && source ~/.zsh_aliases     # aliases (override OMZ ones)
[[ -f ~/.zsh_functions ]] && source ~/.zsh_functions   # functions
[[ -f ~/.zshrc.local   ]] && source ~/.zshrc.local     # this Mac only / secrets, NOT in git


# =============================================================================
# 7. PROMPT: Starship (config lives in ~/.config/starship.toml)
# =============================================================================
(( $+commands[starship] )) && eval "$(starship init zsh)"


# =============================================================================
# 8. PLUGINS THAT WRAP KEY WIDGETS (must be last)
# =============================================================================
# Install once:  brew install zsh-autosuggestions zsh-syntax-highlighting
# ${HOMEBREW_PREFIX} is already known, no slow `brew --prefix` call (~50 ms each).

# autosuggestions: grey ghost text from history, then from completion.
ZSH_AUTOSUGGEST_STRATEGY=(history completion)
ZSH_AUTOSUGGEST_HIGHLIGHT_STYLE='fg=8'          # dim grey
ZSH_AUTOSUGGEST_BUFFER_MAX_SIZE=40              # skip suggestions for very long lines (faster)
if [[ -r $HOMEBREW_PREFIX/share/zsh-autosuggestions/zsh-autosuggestions.zsh ]]; then
    source "$HOMEBREW_PREFIX/share/zsh-autosuggestions/zsh-autosuggestions.zsh"
    bindkey '^ ' autosuggest-accept             # Ctrl+Space accepts (Right arrow works too)
fi

# syntax highlighting (red = unknown command, green = valid). Its README says it must be
# sourced AFTER every other plugin and widget, so it goes at the very end.
if [[ -r $HOMEBREW_PREFIX/share/zsh-syntax-highlighting/zsh-syntax-highlighting.zsh ]]; then
    source "$HOMEBREW_PREFIX/share/zsh-syntax-highlighting/zsh-syntax-highlighting.zsh"
fi

[[ -n $ZPROF ]] && zprof
