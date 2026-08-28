#!/usr/bin/env bash
set -euo pipefail

as_root() {
  if sudo -n true 2>/dev/null; then
    sudo "$@"
  else
    printf 'The parent installer must establish sudo first.\n' >&2
    exit 1
  fi
}

if command -v 1password >/dev/null && command -v op >/dev/null; then
  exit 0
fi

mkdir -p "$HOME/Scratch"
build_root="$(mktemp -d -p "$HOME/Scratch" 1password-build.XXXXXX)"
trap 'rm -rf -- "$build_root"' EXIT

curl -fsSL https://downloads.1password.com/linux/keys/1password.asc | gpg --import

for package in 1password 1password-cli; do
  if pacman -Q "$package" >/dev/null 2>&1; then
    continue
  fi
  git clone --depth 1 "https://aur.archlinux.org/${package}.git" "$build_root/$package"
  (
    cd "$build_root/$package"
    makepkg --needed --noconfirm
    mapfile -t built_packages < <(find "$PWD" -maxdepth 1 -type f -name '*.pkg.tar.zst' -print)
    as_root pacman -U --needed --noconfirm "${built_packages[@]}"
  )
done
