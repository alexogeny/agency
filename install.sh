#!/usr/bin/env bash
set -euo pipefail

AGENCY_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"

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

as_root() {
  if (( EUID != 0 )); then
    sudo "$@"
  else
    "$@"
  fi
}

mkdir -p \
  "$HOME/Scratch" \
  "$HOME/.codex/agents" \
  "$HOME/.claude/agents" \
  "$HOME/.pi/agent"
mkdir -p "$HOME/.local/bin"
ln -sfn "$AGENCY_DIR/Tools/git-get" "$HOME/.local/bin/git-get"
ln -sfn "$AGENCY_DIR/Tools/long-processes" "$HOME/.local/bin/long-processes"
ln -sfn "$AGENCY_DIR/Tools/sandbox" "$HOME/.local/bin/sandbox"
ln -sfn "$AGENCY_DIR/Tools/agent-work" "$HOME/.local/bin/agent-work"
ln -sfn "$AGENCY_DIR/Tools/instruction-bench" "$HOME/.local/bin/instruction-bench"
ln -sfn "$AGENCY_DIR/Tools/repo-map" "$HOME/.local/bin/repo-map"
ln -sfn "$AGENCY_DIR/Tools/report-build" "$HOME/.local/bin/report-build"
ln -sfn "$AGENCY_DIR/Tools/web-research" "$HOME/.local/bin/web-research"
ln -sfn "$AGENCY_DIR/Agents/AGENTS.md" "$HOME/.codex/AGENTS.md"
ln -sfn "$AGENCY_DIR/Agents/AGENTS.md" "$HOME/.claude/CLAUDE.md"
ln -sfn "$AGENCY_DIR/Agents/AGENTS.md" "$HOME/.pi/agent/AGENTS.md"
ln -sfn \
  "$AGENCY_DIR/Agents/codex/coordinated-worker.toml" \
  "$HOME/.codex/agents/coordinated-worker.toml"
ln -sfn \
  "$AGENCY_DIR/Agents/claude/coordinated-worker.md" \
  "$HOME/.claude/agents/coordinated-worker.md"

mkdir -p "$HOME/.agents/skills" "$HOME/.claude/skills" "$HOME/.pi/agent/skills"
for skill_dir in "$AGENCY_DIR"/Skills/*; do
  [[ -d "$skill_dir" ]] || continue
  skill_name=${skill_dir##*/}
  ln -sfnT "$skill_dir" "$HOME/.agents/skills/$skill_name"
  ln -sfnT "$skill_dir" "$HOME/.claude/skills/$skill_name"
  ln -sfnT "$skill_dir" "$HOME/.pi/agent/skills/$skill_name"
done

mapfile -t packages < <(sed -E '/^[[:space:]]*(#|$)/d' "$AGENCY_DIR/packages.txt")

# Podman is the one container stack. Remove only explicit competing frontends;
# shared runtimes such as containerd are left alone in case another package uses them.
mapfile -t competing_container_packages < <(
  pacman -Qq docker docker-compose nerdctl 2>/dev/null || true
)
if (( ${#competing_container_packages[@]} )); then
  as_root pacman -Rns --noconfirm "${competing_container_packages[@]}"
fi

as_root pacman -Syu --needed --noconfirm "${packages[@]}"
"$AGENCY_DIR/scripts/install-report-fonts.sh"

mkdir -p "$HOME/.config/git"
ln -sfn "$AGENCY_DIR/config/git/config" "$HOME/.config/git/config"
ln -sfn "$AGENCY_DIR/config/git/ignore" "$HOME/.config/git/ignore"
ln -sfn "$AGENCY_DIR/config/git/hooks" "$HOME/.config/git/hooks"
if [[ ! -e "$HOME/.config/git/identity" ]]; then
  printf '%s\n' \
    '# Machine-local Git identity. Copy values from:' \
    "# $AGENCY_DIR/config/git/identity.example" \
    > "$HOME/.config/git/identity"
  printf 'Edit %s with your Git author identity.\n' "$HOME/.config/git/identity"
fi

rustup default stable
"$AGENCY_DIR/scripts/install-agent-clis.sh"
"$AGENCY_DIR/scripts/install-python-tools.sh"
uv tool install --upgrade podman-compose

mkdir -p "$HOME/.config/containers"
ln -sfn "$AGENCY_DIR/config/containers/containers.conf" \
  "$HOME/.config/containers/containers.conf"

as_root install -Dm644 "$AGENCY_DIR/firefox/policies.json" /usr/lib/firefox/distribution/policies.json
"$AGENCY_DIR/scripts/install-firefox.sh"

as_root install -Dm644 "$AGENCY_DIR/system/resolved-cloudflare-family.conf" \
  /etc/systemd/resolved.conf.d/60-cloudflare-family.conf
as_root install -Dm644 "$AGENCY_DIR/system/networkmanager-resolved.conf" \
  /etc/NetworkManager/conf.d/60-systemd-resolved.conf
as_root ln -sfn /run/systemd/resolve/stub-resolv.conf /etc/resolv.conf
as_root systemctl enable --now systemd-resolved.service NetworkManager.service
as_root systemctl reload-or-restart systemd-resolved.service
as_root systemctl reload NetworkManager.service

mkdir -p "$HOME/.config/fish"
ln -sfn "$AGENCY_DIR/config/fish/config.fish" "$HOME/.config/fish/config.fish"
ln -sfn "$AGENCY_DIR/config/starship.toml" "$HOME/.config/starship.toml"
"$AGENCY_DIR/scripts/configure-power.sh"

as_root install -Dm644 "$AGENCY_DIR/system/scx_loader.toml" /etc/scx_loader.toml
as_root systemctl enable --now scx_loader.service
as_root systemctl restart scx_loader.service
as_root systemctl enable --now fstrim.timer
as_root systemctl mask sleep.target suspend.target hibernate.target hybrid-sleep.target

"$AGENCY_DIR/scripts/install-1password.sh"

printf '\n\033[1;35m✨ Workstation bootstrap complete. Restart Firefox to apply policy.\033[0m\n'
