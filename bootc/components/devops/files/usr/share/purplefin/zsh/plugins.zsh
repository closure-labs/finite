# Plugins are installed and updated by Homebrew through Purplefin's Brewfile.
brew_prefix="${HOMEBREW_PREFIX:-/home/linuxbrew/.linuxbrew}"

_purplefin_source_plugin() {
  if [[ -r "$1" ]]; then
    source "$1"
  else
    print -u2 "Purplefin zsh plugin is not installed: $1"
  fi
}

_purplefin_source_plugin "${brew_prefix}/share/zsh-autosuggestions/zsh-autosuggestions.zsh"
_purplefin_source_plugin "${brew_prefix}/share/zsh-history-substring-search/zsh-history-substring-search.zsh"
_purplefin_source_plugin "${brew_prefix}/opt/zsh-vi-mode/share/zsh-vi-mode/zsh-vi-mode.plugin.zsh"
# Syntax highlighting must be sourced after other plugins.
_purplefin_source_plugin "${brew_prefix}/opt/zsh-fast-syntax-highlighting/share/zsh-fast-syntax-highlighting/fast-syntax-highlighting.plugin.zsh"

unset brew_prefix
unfunction _purplefin_source_plugin
