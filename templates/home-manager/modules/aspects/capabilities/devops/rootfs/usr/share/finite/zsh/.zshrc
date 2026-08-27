# Powerful but tastefully minimal Finite zsh configuration.
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

source "${ZDOTDIR}/fzf.zsh"
source "${ZDOTDIR}/aliases.zsh"
source "${ZDOTDIR}/bindings.zsh"
source "${ZDOTDIR}/prompt.zsh"

export NVM_DIR="${HOME}/.nvm"
[[ -s "${NVM_DIR}/nvm.sh" ]] && source "${NVM_DIR}/nvm.sh"
[[ -s "${NVM_DIR}/bash_completion" ]] && source "${NVM_DIR}/bash_completion"
