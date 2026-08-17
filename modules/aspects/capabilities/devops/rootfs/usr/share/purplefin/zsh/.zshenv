# Purplefin zsh environment

: "${XDG_CONFIG_HOME:=${HOME}/.config}"
: "${XDG_CACHE_HOME:=${HOME}/.cache}"
: "${XDG_DATA_HOME:=${HOME}/.local/share}"
: "${XDG_STATE_HOME:=${HOME}/.local/state}"
export XDG_CONFIG_HOME XDG_CACHE_HOME XDG_DATA_HOME XDG_STATE_HOME

# This file also doubles as a user-local bootstrap on systems where the
# image-level /etc/zshenv change has not been deployed yet.
if [[ -z "${ZDOTDIR:-}" && -d "${XDG_CONFIG_HOME}/zsh" ]]; then
  export ZDOTDIR="${XDG_CONFIG_HOME}/zsh"
fi

export EDITOR="nvim"
export VISUAL="nvim"

if (( $+commands[bat] )); then
  export MANPAGER="bat -l man -p"
elif (( $+commands[batcat] )); then
  export MANPAGER="batcat -l man -p"
fi

if [[ -t 0 ]]; then
  export GPG_TTY="$(tty)"
fi

export STARSHIP_CONFIG="${ZDOTDIR:-${XDG_CONFIG_HOME}/zsh}/starship.toml"
export PATH="${HOME}/.local/bin:${PATH}"
