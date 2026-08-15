export VIRTUAL_ENV_DISABLE_PROMPT=1
FUNCNEST=100

if (( $+commands[starship] )); then
  eval "$(starship init zsh)"
fi
