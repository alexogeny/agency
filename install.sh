#!/usr/bin/env bash
set -euo pipefail

AGENCY_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
source "$AGENCY_DIR/scripts/lib.sh"

usage() {
  cat <<'EOF'
Usage: ./install.sh [--dry-run] [--update]

  --dry-run  Inspect the resolved install plan without changing the system.
  --update   Update installed versioned tools managed outside pacman.
  --help     Show this help.

Without --update, existing stable Rust, yay, h2load, 1Password, Codex, Claude
Code, Pi, Gantry, Thoreau, and podman-compose are retained and reported instead.
EOF
}

dry_run=false
update=false
while (( $# )); do
  case $1 in
    --dry-run) dry_run=true ;;
    --update) update=true ;;
    --help|-h)
      usage
      exit
      ;;
    *)
      usage >&2
      exit 2
      ;;
  esac
  shift
done

if $dry_run; then
  source "$AGENCY_DIR/scripts/install-dry-run.sh"
  agency_print_install_plan "$update"
  exit
fi

update_arguments=()
if $update; then
  update_arguments+=(--update)
fi

sudo_keepalive_pid=""

cleanup() {
  if [[ -n "$sudo_keepalive_pid" ]]; then
    kill "$sudo_keepalive_pid" 2>/dev/null || true
  fi
}
trap cleanup EXIT

# Ask once, then refresh sudo's timestamp while the bootstrap is running.
if (( EUID != 0 )); then
  sudo -v
  while sleep 50; do
    sudo -n true || exit
  done &
  sudo_keepalive_pid=$!
fi

agency_prepare_scratch
mkdir -p \
  "$HOME/.codex/agents" \
  "$HOME/.claude/agents" \
  "$HOME/.pi/agent/extensions"
mkdir -p "$HOME/.local/bin"
agency_link "$AGENCY_DIR/Tools/agency-ui" "$HOME/.local/bin/agency-ui"
agency_link "$AGENCY_DIR/Tools/git-get" "$HOME/.local/bin/git-get"
agency_link "$AGENCY_DIR/Tools/long-processes" "$HOME/.local/bin/long-processes"
agency_link "$AGENCY_DIR/Tools/sandbox" "$HOME/.local/bin/sandbox"
agency_link "$AGENCY_DIR/Tools/agent-work" "$HOME/.local/bin/agent-work"
agency_link "$AGENCY_DIR/Tools/comment-audit" "$HOME/.local/bin/comment-audit"
agency_link "$AGENCY_DIR/Tools/docs-exec" "$HOME/.local/bin/docs-exec"
agency_link "$AGENCY_DIR/Tools/document-inspect" "$HOME/.local/bin/document-inspect"
agency_link "$AGENCY_DIR/Tools/evidence-review" "$HOME/.local/bin/evidence-review"
agency_link "$AGENCY_DIR/Tools/instruction-bench" "$HOME/.local/bin/instruction-bench"
agency_link "$AGENCY_DIR/Tools/resource-bench" "$HOME/.local/bin/resource-bench"
agency_link "$AGENCY_DIR/Tools/perf-diagnose" "$HOME/.local/bin/perf-diagnose"
agency_link "$AGENCY_DIR/Tools/repo-map" "$HOME/.local/bin/repo-map"
agency_link "$AGENCY_DIR/Tools/repository-setup" "$HOME/.local/bin/repository-setup"
agency_link "$AGENCY_DIR/Tools/report-build" "$HOME/.local/bin/report-build"
agency_link "$AGENCY_DIR/Tools/system-context" "$HOME/.local/bin/system-context"
agency_link "$AGENCY_DIR/Tools/sudo-gui" "$HOME/.local/bin/sudo-gui"
agency_link "$AGENCY_DIR/Tools/web-research" "$HOME/.local/bin/web-research"
agency_link "$AGENCY_DIR/Tools/web-research-mcp" "$HOME/.local/bin/web-research-mcp"
agency_link "$AGENCY_DIR/Agents/AGENTS.md" "$HOME/.codex/AGENTS.md"
agency_link "$AGENCY_DIR/Agents/AGENTS.md" "$HOME/.claude/CLAUDE.md"
agency_link "$AGENCY_DIR/Agents/AGENTS.md" "$HOME/.pi/agent/AGENTS.md"
agency_link "$AGENCY_DIR/Agents/pi/agency-web.ts" "$HOME/.pi/agent/extensions/agency-web.ts"
agency_link \
  "$AGENCY_DIR/Agents/codex/coordinated-worker.toml" \
  "$HOME/.codex/agents/coordinated-worker.toml"
agency_link \
  "$AGENCY_DIR/Agents/claude/coordinated-worker.md" \
  "$HOME/.claude/agents/coordinated-worker.md"
agency_merge_agent_hooks "$AGENCY_DIR/config/codex/hooks.json" "$HOME/.codex/hooks.json"
agency_merge_agent_hooks "$AGENCY_DIR/config/claude/hooks.json" "$HOME/.claude/settings.json"

mkdir -p "$HOME/.agents/skills" "$HOME/.claude/skills" "$HOME/.pi/agent/skills"
for skill_dir in "$AGENCY_DIR"/Skills/*; do
  [[ -d "$skill_dir" ]] || continue
  skill_name=${skill_dir##*/}
  agency_link "$skill_dir" "$HOME/.agents/skills/$skill_name"
  agency_link "$skill_dir" "$HOME/.claude/skills/$skill_name"
  agency_link "$skill_dir" "$HOME/.pi/agent/skills/$skill_name"
done

mapfile -t packages < <(sed -E '/^[[:space:]]*(#|$)/d' "$AGENCY_DIR/packages.txt")

# Podman is the one container stack. Remove only explicit competing frontends;
# shared runtimes such as containerd are left alone in case another package uses them.
mapfile -t competing_container_packages < <(
  pacman -Qq docker docker-compose nerdctl 2>/dev/null || true
)
if (( ${#competing_container_packages[@]} )); then
  agency_as_root pacman -Rns --noconfirm "${competing_container_packages[@]}"
fi

agency_as_root pacman -Syu --needed --noconfirm "${packages[@]}"
"$AGENCY_DIR/scripts/install-yay-h2load.sh" "${update_arguments[@]}"
"$AGENCY_DIR/scripts/install-report-fonts.sh"

mkdir -p "$HOME/.config/git"
agency_install_git_identity "$HOME/.config/git/identity"
agency_preserve_git_config \
  "$HOME/.config/git/local" \
  "$HOME/.gitconfig" \
  "$HOME/.config/git/config"
agency_link "$AGENCY_DIR/config/git/config" "$HOME/.gitconfig"
agency_link "$AGENCY_DIR/config/git/config" "$HOME/.config/git/config"
agency_link "$AGENCY_DIR/config/git/ignore" "$HOME/.config/git/ignore"
agency_link "$AGENCY_DIR/config/git/hooks" "$HOME/.config/git/hooks"

"$AGENCY_DIR/scripts/install-rust.sh" "${update_arguments[@]}"
"$AGENCY_DIR/scripts/install-agent-clis.sh" "${update_arguments[@]}"
"$AGENCY_DIR/scripts/configure-agent-tools.sh"
"$AGENCY_DIR/scripts/install-python-tools.sh" "${update_arguments[@]}"

mkdir -p "$HOME/.config/containers"
agency_link "$AGENCY_DIR/config/containers/containers.conf" \
  "$HOME/.config/containers/containers.conf"

agency_as_root install -Dm644 "$AGENCY_DIR/firefox/policies.json" /usr/lib/firefox/distribution/policies.json
"$AGENCY_DIR/scripts/install-firefox.sh"

agency_as_root install -Dm644 "$AGENCY_DIR/system/resolved-cloudflare-family.conf" \
  /etc/systemd/resolved.conf.d/60-cloudflare-family.conf
agency_as_root install -Dm644 "$AGENCY_DIR/system/networkmanager-resolved.conf" \
  /etc/NetworkManager/conf.d/60-systemd-resolved.conf
agency_link_as_root /run/systemd/resolve/stub-resolv.conf /etc/resolv.conf
agency_as_root systemctl enable --now systemd-resolved.service NetworkManager.service
agency_as_root systemctl reload-or-restart systemd-resolved.service
agency_as_root systemctl reload NetworkManager.service

mkdir -p "$HOME/.config/fish"
agency_link "$AGENCY_DIR/config/fish/config.fish" "$HOME/.config/fish/config.fish"
agency_link "$AGENCY_DIR/config/starship.toml" "$HOME/.config/starship.toml"
"$AGENCY_DIR/scripts/configure-power.sh"

agency_as_root install -Dm644 "$AGENCY_DIR/system/scx_loader.toml" /etc/scx_loader.toml
agency_as_root systemctl enable --now scx_loader.service
agency_as_root systemctl restart scx_loader.service
agency_as_root systemctl enable --now fstrim.timer

"$AGENCY_DIR/scripts/install-1password.sh" "${update_arguments[@]}"

printf '\n\033[1;35m✨ Workstation bootstrap complete. Restart Firefox to apply policy.\033[0m\n'
