#!/usr/bin/env bash
set -euo pipefail

update=false
case ${1:-} in
  --update) update=true ;;
  "") ;;
  *)
    printf 'Usage: %s [--update]\n' "${0##*/}" >&2
    exit 2
    ;;
esac
(( $# <= 1 )) || { printf 'Usage: %s [--update]\n' "${0##*/}" >&2; exit 2; }

as_root() {
  if sudo -n true 2>/dev/null; then
    sudo "$@"
  else
    printf 'The parent installer must establish sudo first.\n' >&2
    exit 1
  fi
}

packages=()
retained=()
while IFS='|' read -r package command label; do
  if $update || ! pacman -Q "$package" >/dev/null 2>&1 ||
    ! command -v "$command" >/dev/null 2>&1; then
    packages+=("$package")
  else
    retained+=("$label")
  fi
done <<'EOF'
1password|1password|1Password desktop
1password-cli|op|1Password CLI
EOF

if (( ${#packages[@]} )); then
  mkdir -p "$HOME/Scratch"
  build_root="$(mktemp -d -p "$HOME/Scratch" 1password-build.XXXXXX)"
  cleanup() {
    if [[ -d $build_root && $build_root == "$HOME/Scratch/"1password-build.* ]]; then
      rm -rf -- "$build_root"
    fi
  }
  trap cleanup EXIT

  curl -fsSL https://downloads.1password.com/linux/keys/1password.asc | gpg --import

  for package in "${packages[@]}"; do
    git clone --depth 1 "https://aur.archlinux.org/${package}.git" "$build_root/$package"
    (
      cd "$build_root/$package"
      makepkg --noconfirm
      mapfile -t built_packages < <(
        find "$PWD" -maxdepth 1 -type f -name '*.pkg.tar.zst' -print
      )
      as_root pacman -U --noconfirm "${built_packages[@]}"
    )
  done
fi

while IFS='|' read -r package command label; do
  if ! pacman -Q "$package" >/dev/null 2>&1; then
    printf '%s package is unavailable after installation.\n' "$label" >&2
    exit 1
  fi
  if ! command -v "$command" >/dev/null 2>&1; then
    printf '%s command is unavailable after installation.\n' "$label" >&2
    exit 1
  fi
done <<'EOF'
1password|1password|1Password desktop
1password-cli|op|1Password CLI
EOF

if (( ${#retained[@]} )); then
  printf '⚠ Already installed and left unchanged:\n'
  printf '  - %s\n' "${retained[@]}"
  printf 'If any version is older than upstream, run ./install.sh --update.\n'
fi
