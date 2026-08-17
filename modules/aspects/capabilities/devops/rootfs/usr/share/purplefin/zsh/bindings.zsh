ZVM_INSERT_MODE_CURSOR=$ZVM_CURSOR_BEAM
ZVM_NORMAL_MODE_CURSOR=$ZVM_CURSOR_BLOCK
ZVM_VISUAL_MODE_CURSOR=$ZVM_CURSOR_BLOCK

ZVM_VI_HIGHLIGHT_BACKGROUND=none
ZVM_VI_HIGHLIGHT_FOREGROUND=none
ZVM_VI_HIGHLIGHT_EXTRASTYLE=none

# zsh-vi-mode resets bindings during initialization, so register them in its
# post-initialization hook.
zvm_after_init() {
  bindkey '^[[1;5C' forward-word
  bindkey '^[[1;5D' backward-word
  bindkey '^F' _fzf_file_no_hidden
  bindkey '^\' autosuggest-toggle
  bindkey '^[[A' history-substring-search-up
  bindkey '^[[B' history-substring-search-down
}
