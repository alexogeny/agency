#!/usr/bin/env bash

agency_plan_link() {
  local source=$1
  local target=$2
  local action

  if [[ -e $target && $source -ef $target ]]; then
    action="unchanged link"
  elif [[ -L $target ]]; then
    action="relink"
  elif [[ -e $target ]]; then
    action="backup + link"
  else
    action="create link"
  fi
  printf '  [%-16s] %s -> %s\n' "$action" "$target" "$source"
}

agency_plan_hook_merge() {
  local fragment=$1
  local target=$2
  local merger="$AGENCY_DIR/scripts/merge-agent-hooks.py"
  local status

  if "$merger" --check "$target" "$fragment"; then
    if [[ -e $target && ! -L $target ]]; then
      printf '  [%-16s] %s from %s (with source backup)\n' \
        "merge hooks" "$target" "$fragment"
    else
      printf '  [%-16s] %s from %s\n' "merge hooks" "$target" "$fragment"
    fi
    return
  else
    status=$?
  fi

  if (( status == 1 )); then
    printf '  [%-16s] %s\n' "hooks unchanged" "$target"
    return
  fi
  printf '  [%-16s] %s could not be inspected\n' "hook error" "$target" >&2
  return "$status"
}

agency_plan_scratch() {
  local canonical="$HOME/Scratch"
  local legacy="$HOME/scratch"

  if [[ -d $legacy && ! -L $legacy && ! -e $canonical && ! -L $canonical ]]; then
    printf '  [%-16s] %s -> %s\n' "rename directory" "$legacy" "$canonical"
  elif [[ -d $legacy && ! -L $legacy && -d $canonical && ! -L $canonical ]]; then
    local item name moves=0 conflicts=0
    while IFS= read -r -d '' item; do
      name=${item##*/}
      if [[ -e $canonical/$name || -L $canonical/$name ]]; then
        (( conflicts += 1 ))
      else
        (( moves += 1 ))
      fi
    done < <(find "$legacy" -mindepth 1 -maxdepth 1 -print0)
    printf '  [%-16s] %d non-conflicting entries %s -> %s\n' \
      "merge directory" "$moves" "$legacy" "$canonical"
    if (( conflicts )); then
      printf '  [%-16s] %d conflicting entries remain in %s\n' \
        "manual review" "$conflicts" "$legacy"
    fi
  elif [[ ( -e $legacy || -L $legacy ) && ( -e $canonical || -L $canonical ) ]]; then
    printf '  [%-16s] one path is not a regular directory; leave both untouched\n' \
      "scratch warning"
  elif [[ -e $canonical || -L $canonical ]]; then
    printf '  [%-16s] %s\n' "directory exists" "$canonical"
  else
    printf '  [%-16s] %s\n' "create directory" "$canonical"
  fi
}

agency_plan_git() {
  local identity="$HOME/.config/git/identity"
  local local_config="$HOME/.config/git/local"

  if [[ -e $identity || -L $identity ]]; then
    printf '  [%-16s] %s\n' "identity exists" "$identity"
  elif git config --global --includes --get-regexp '^user\.(name|email|signingkey)$' \
    >/dev/null 2>&1; then
    printf '  [%-16s] existing name/email/signing key -> %s\n' \
      "import identity" "$identity"
  else
    printf '  [%-16s] %s for manual identity values\n' "create identity" "$identity"
  fi

  if [[ -e $local_config || -L $local_config ]]; then
    printf '  [%-16s] %s\n' "local exists" "$local_config"
  elif [[ -f $HOME/.gitconfig && ! -L $HOME/.gitconfig ]] ||
    [[ -f $HOME/.config/git/config && ! -L $HOME/.config/git/config ]]; then
    printf '  [%-16s] existing non-identity Git settings -> %s\n' \
      "preserve config" "$local_config"
  else
    printf '  [%-16s] no regular global Git config to preserve\n' "no migration"
  fi

  agency_plan_link "$AGENCY_DIR/config/git/config" "$HOME/.gitconfig"
  agency_plan_link "$AGENCY_DIR/config/git/config" "$HOME/.config/git/config"
  agency_plan_link "$AGENCY_DIR/config/git/ignore" "$HOME/.config/git/ignore"
  agency_plan_link "$AGENCY_DIR/config/git/hooks" "$HOME/.config/git/hooks"
}

agency_plan_user_links() {
  local tool skill_dir skill_name
  local -a tools=(
    git-get
    long-processes
    sandbox
    agent-work
    comment-audit
    docs-exec
    document-inspect
    evidence-review
    instruction-bench
    perf-diagnose
    repo-map
    repository-setup
    report-build
    system-context
    sudo-gui
    web-research
  )

  for tool in "${tools[@]}"; do
    agency_plan_link "$AGENCY_DIR/Tools/$tool" "$HOME/.local/bin/$tool"
  done
  agency_plan_link "$AGENCY_DIR/Agents/AGENTS.md" "$HOME/.codex/AGENTS.md"
  agency_plan_link "$AGENCY_DIR/Agents/AGENTS.md" "$HOME/.claude/CLAUDE.md"
  agency_plan_link "$AGENCY_DIR/Agents/AGENTS.md" "$HOME/.pi/agent/AGENTS.md"
  agency_plan_link "$AGENCY_DIR/Agents/codex/coordinated-worker.toml" \
    "$HOME/.codex/agents/coordinated-worker.toml"
  agency_plan_link "$AGENCY_DIR/Agents/claude/coordinated-worker.md" \
    "$HOME/.claude/agents/coordinated-worker.md"

  for skill_dir in "$AGENCY_DIR"/Skills/*; do
    [[ -d $skill_dir ]] || continue
    skill_name=${skill_dir##*/}
    agency_plan_link "$skill_dir" "$HOME/.agents/skills/$skill_name"
    agency_plan_link "$skill_dir" "$HOME/.claude/skills/$skill_name"
    agency_plan_link "$skill_dir" "$HOME/.pi/agent/skills/$skill_name"
  done

  agency_plan_hook_merge "$AGENCY_DIR/config/codex/hooks.json" "$HOME/.codex/hooks.json"
  agency_plan_hook_merge "$AGENCY_DIR/config/claude/hooks.json" "$HOME/.claude/settings.json"
}

agency_plan_power() {
  source "$AGENCY_DIR/scripts/configure-power.sh"
  local profile
  if detect_laptop; then
    profile="$AGENCY_DIR/config/kde/powerdevil-laptoprc"
    agency_plan_link "$profile" "$HOME/.config/powerdevilrc"
    printf '  [%-16s] unmask sleep, suspend, hibernate, and hybrid-sleep\n' \
      "laptop policy"
  else
    profile="$AGENCY_DIR/config/kde/powerdevil-desktoprc"
    agency_plan_link "$profile" "$HOME/.config/powerdevilrc"
    printf '  [%-16s] mask system sleep targets; set connected displays to 100%%\n' \
      "desktop policy"
  fi
  printf '  [%-16s] plasma-powerdevil.service\n' "restart user"
}

agency_print_install_plan() {
  local update=${1:-false}
  local -a packages competing
  mapfile -t packages < <(sed -E '/^[[:space:]]*(#|$)/d' "$AGENCY_DIR/packages.txt")
  mapfile -t competing < <(pacman -Qq docker docker-compose nerdctl 2>/dev/null || true)

  printf '\033[1;35mAGENCY INSTALL — DRY RUN\033[0m\n'
  printf 'Checkout: %s\n' "$AGENCY_DIR"
  printf 'No sudo prompt will be shown and no commands below will be executed.\n\n'

  printf '\033[1mDirectories and managed agent files\033[0m\n'
  agency_plan_scratch
  agency_plan_user_links

  printf '\n\033[1mPackages and developer runtimes\033[0m\n'
  if (( ${#competing[@]} )); then
    printf '  [%-16s] pacman -Rns --noconfirm %s\n' \
      "remove frontend" "${competing[*]}"
  else
    printf '  [%-16s] Docker, Docker Compose, and nerdctl are not installed\n' \
      "nothing to remove"
  fi
  printf '  [%-16s] pacman -Syu --needed --noconfirm %s\n' \
    "install/update" "${packages[*]}"
  printf '  [%-16s] verified Computer Modern Unicode fonts\n' "install fonts"
  if $update; then
    printf '  [%-16s] yay and patched nghttp2/h2load AUR builds\n' "update AUR tools"
    printf '  [%-16s] 1Password desktop AUR build\n' "update AUR tool"
    printf '  [%-16s] 1Password CLI AUR build\n' "update AUR tool"
    printf '  [%-16s] stable Rust toolchain\n' "update toolchain"
    printf '  [%-16s] Codex, Claude Code, and Pi through Bun\n' \
      "update installed CLIs"
    printf '  [%-16s] Gantry, Thoreau, and podman-compose through uv\n' \
      "update installed CLIs"
  else
    printf '  [%-16s] yay and patched nghttp2/h2load; retain installed versions\n' \
      "install missing"
    printf '  [%-16s] 1Password desktop; retain installed version\n' \
      "install missing"
    printf '  [%-16s] 1Password CLI; retain installed version\n' \
      "install missing"
    printf '  [%-16s] stable Rust; retain the installed default\n' "install missing"
    printf '  [%-16s] Codex, Claude Code, and Pi; retain installed versions\n' \
      "install missing"
    printf '  [%-16s] Gantry, Thoreau, and podman-compose; retain installed versions\n' \
      "install missing"
    printf '  [%-16s] pass --update to check retained tools for newer versions\n' \
      "update warning"
  fi

  printf '\n\033[1mGit configuration\033[0m\n'
  agency_plan_git

  printf '\n\033[1mApplications and system configuration\033[0m\n'
  agency_plan_link "$AGENCY_DIR/config/containers/containers.conf" \
    "$HOME/.config/containers/containers.conf"
  printf '  [%-16s] Firefox enterprise policy and per-profile user.js\n' "configure"
  printf '  [%-16s] 1Password Firefox extension through managed policy\n' \
    "auto-install"
  printf '  [%-16s] /usr/lib/firefox/distribution/policies.json\n' "install root"
  printf '  [%-16s] /etc/systemd/resolved.conf.d/60-cloudflare-family.conf\n' \
    "install root"
  printf '  [%-16s] /etc/NetworkManager/conf.d/60-systemd-resolved.conf\n' \
    "install root"
  agency_plan_link /run/systemd/resolve/stub-resolv.conf /etc/resolv.conf
  printf '  [%-16s] systemd-resolved and NetworkManager\n' "enable/reload"
  agency_plan_link "$AGENCY_DIR/config/fish/config.fish" "$HOME/.config/fish/config.fish"
  agency_plan_link "$AGENCY_DIR/config/starship.toml" "$HOME/.config/starship.toml"
  agency_plan_power
  printf '  [%-16s] /etc/scx_loader.toml; enable/restart scx_loader.service\n' \
    "configure root"
  printf '  [%-16s] fstrim.timer\n' "enable"

  if $update; then
    printf '\n\033[1;35mNo changes were made.\033[0m Run ./install.sh --update to apply this plan.\n'
  else
    printf '\n\033[1;35mNo changes were made.\033[0m Run ./install.sh to apply this plan.\n'
  fi
}
