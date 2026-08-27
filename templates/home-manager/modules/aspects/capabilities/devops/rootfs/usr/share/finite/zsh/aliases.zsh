alias ls='eza --icons'
alias ll='eza -lh --icons --git'
alias la='eza -lah --icons --git'
alias tree='eza --tree --icons'
compdef eza=ls

alias cat='bat'
alias grep='rg --color=auto'
alias diff='diff --color=auto'
alias df='df -h'
alias -- -='cd -'

lf() {
  local tmp dir
  tmp="$(mktemp)"
  command lf -last-dir-path="${tmp}" "$@"
  if [[ -f "${tmp}" ]]; then
    dir="$(command cat "${tmp}")"
    rm -f "${tmp}"
    [[ -d "${dir}" && "${dir}" != "${PWD}" ]] && cd "${dir}"
  fi
}

alias vim='nvim'
alias glog='PAGER="less -F -X" git log'
alias gadog='PAGER="less -F -X" git log --all --decorate --oneline --graph'
alias dotfiles='git --git-dir=$HOME/.dotfiles --work-tree=$HOME'
alias stream='mpv av://v4l2:/dev/video4 --fullscreen --demuxer-lavf-o=input_format=mjpeg,framerate=30 --profile=low-latency --untimed'
