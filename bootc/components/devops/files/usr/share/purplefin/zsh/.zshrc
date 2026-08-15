# Powerful but tastefully minimal Purplefin zsh configuration.
# Based on https://github.com/radleylewis/zsh (MIT).

HISTFILE="${XDG_STATE_HOME}/zsh/history"
HISTSIZE=100000
SAVEHIST=100000

setopt APPEND_HISTORY
setopt SHARE_HISTORY
setopt HIST_IGNORE_DUPS
setopt HIST_IGNORE_SPACE
setopt HIST_EXPIRE_DUPS_FIRST
setopt HIST_FIND_NO_DUPS
setopt AUTOCD
setopt NOBEEP
setopt NUMERIC_GLOB_SORT

if [[ -r "${HOME}/.config/lf/icons" ]]; then
  LF_ICONS="$(tr '\n' ':' < "${HOME}/.config/lf/icons")"
  export LF_ICONS
fi

if (( $+commands[zoxide] )); then
  eval "$(zoxide init zsh)"
fi

autoload -Uz compinit
compinit -d "${XDG_CACHE_HOME}/zsh/zcompdump"
zstyle ':completion:*' menu select
zstyle ':completion:*' matcher-list 'm:{a-z}={A-Za-z}'

# Load fzf's standard Ctrl-R/Ctrl-T bindings and completion where available.
for fzf_shell_dir in \
  "${HOMEBREW_PREFIX:-/home/linuxbrew/.linuxbrew}/opt/fzf/shell" \
  /opt/homebrew/opt/fzf/shell \
  /usr/local/opt/fzf/shell \
  /usr/share/fzf \
  /usr/share/doc/fzf/examples; do
  if [[ -r "${fzf_shell_dir}/key-bindings.zsh" ]]; then
    source "${fzf_shell_dir}/key-bindings.zsh"
    [[ -r "${fzf_shell_dir}/completion.zsh" ]] && source "${fzf_shell_dir}/completion.zsh"
    break
  fi
done
unset fzf_shell_dir

source "${ZDOTDIR}/fzf.zsh"
source "${ZDOTDIR}/aliases.zsh"
source "${ZDOTDIR}/bindings.zsh"
source "${ZDOTDIR}/plugins.zsh"
source "${ZDOTDIR}/prompt.zsh"

export NVM_DIR="${HOME}/.nvm"
[[ -s "${NVM_DIR}/nvm.sh" ]] && source "${NVM_DIR}/nvm.sh"
[[ -s "${NVM_DIR}/bash_completion" ]] && source "${NVM_DIR}/bash_completion"
