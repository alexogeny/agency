#!/usr/bin/env bash
set -euo pipefail
script_directory=${BASH_SOURCE[0]%/*}
[[ $script_directory != "${BASH_SOURCE[0]}" ]] || script_directory=.
source "$script_directory/lib.sh"

onepassword_revision=e323d0d1f8dea6b75bb651ce14acc73904cd0326
onepassword_cli_revision=b0d208821677a5dbb883a8b92f06a5c92b9e861a
update=$(agency_install_update_mode "$@")

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
    if [[ $package == 1password ]]; then
      revision=$onepassword_revision
    else
      revision=$onepassword_cli_revision
    fi
    clone_pinned_recipe "$package" "$revision" "$build_root/$package"
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
  printf 'To upgrade, update the reviewed AUR revisions and run ./install.sh --update.\n'
fi
