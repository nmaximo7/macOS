# --- Oh My Zsh ---------------------------------------------------------
export ZSH="$HOME/.oh-my-zsh"

# Starship draws the prompt, so Oh My Zsh must not set a theme
ZSH_THEME=""

plugins=(git)

source "$ZSH/oh-my-zsh.sh"

# --- Personal config ---------------------------------------------------
# Aliases (only load if the file exists)
[ -f "$HOME/.zsh_aliases" ] && source "$HOME/.zsh_aliases"

# Machine-specific or secret settings (NOT tracked by Git, see section 11)
[ -f "$HOME/.zshrc.local" ] && source "$HOME/.zshrc.local"

# Useful plugins
# brew install zsh-autosuggestions zsh-syntax-highlighting
source "$(brew --prefix)/share/zsh-autosuggestions/zsh-autosuggestions.zsh"
source "$(brew --prefix)/share/zsh-syntax-highlighting/zsh-syntax-highlighting.zsh"

# --- Starship prompt (keep this at the very bottom) --------------------
eval "$(starship init zsh)"
