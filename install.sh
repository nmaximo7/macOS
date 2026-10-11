#!/usr/bin/env bash
set -euo pipefail

DOTFILES="$HOME/nixOS"
PACKAGES=(git zsh ghostty nvim)

# Homebrew
if ! command -v brew >/dev/null 2>&1; then
  echo "Homebrew is not installed. Install it from https://brew.sh and re-run." >&2
  exit 1
fi

# Tools and apps
brew bundle --file="$DOTFILES/Brewfile"

# Make sure ~/.config exists so Stow does not fold it into the repo
mkdir -p "$HOME/.config"

# Link every package (dry run first: abort on conflicts)
cd "$DOTFILES"
stow -nv "${PACKAGES[@]}"
stow -v  "${PACKAGES[@]}"

echo "Done. Open a new terminal session."

