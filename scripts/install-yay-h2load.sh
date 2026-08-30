#!/usr/bin/env bash
set -euo pipefail

if (( EUID == 0 )); then
  printf 'Build yay and nghttp2 as a normal user, not root.\n' >&2
  exit 1
fi

review_recipe() {
  local recipe=$1
  if [[ -t 0 && -t 1 ]]; then
    "${PAGER:-less}" "$recipe"
  else
    sed -n '1,260p' "$recipe"
  fi
}

verify_command() {
  local name=$1
  if ! command -v "$name" >/dev/null 2>&1; then
    printf 'Installation completed without providing %s.\n' "$name" >&2
    exit 1
  fi
  "$name" --version
}

if ! command -v yay >/dev/null 2>&1; then
  mkdir -p "$HOME/Scratch"
  yay_build_dir="$(mktemp -d -p "$HOME/Scratch" yay.XXXXXX)"
  cleanup() {
    if [[ -n ${yay_build_dir:-} && -d $yay_build_dir &&
      $yay_build_dir == "$HOME/Scratch/"yay.* ]]; then
      rm -rf -- "$yay_build_dir"
    fi
  }
  trap cleanup EXIT

  git clone --depth 1 https://aur.archlinux.org/yay.git "$yay_build_dir"
  review_recipe "$yay_build_dir/PKGBUILD"
  (
    cd "$yay_build_dir"
    makepkg -si --needed --noconfirm
  )
fi

verify_command yay

if command -v h2load >/dev/null 2>&1; then
  verify_command h2load
  exit 0
fi

nghttp2_dir="${XDG_CACHE_HOME:-$HOME/.cache}/yay/nghttp2"
if [[ ! -e $nghttp2_dir ]]; then
  mkdir -p "$(dirname -- "$nghttp2_dir")"
  git clone --depth 1 https://aur.archlinux.org/nghttp2.git "$nghttp2_dir"
fi
if [[ ! -f $nghttp2_dir/PKGBUILD ]]; then
  printf 'nghttp2 PKGBUILD is unavailable in %s.\n' "$nghttp2_dir" >&2
  exit 1
fi

if grep -Fq "'zlib>=1.2.3'" "$nghttp2_dir/PKGBUILD"; then
  sed -i "s/'zlib>=1.2.3'/'zlib'/" "$nghttp2_dir/PKGBUILD"
elif ! grep -Fq "'zlib'" "$nghttp2_dir/PKGBUILD"; then
  printf 'nghttp2 no longer declares the expected zlib dependency; review %s.\n' \
    "$nghttp2_dir/PKGBUILD" >&2
  exit 1
fi

git -C "$nghttp2_dir" diff -- PKGBUILD
(
  cd "$nghttp2_dir"
  makepkg -si --needed --noconfirm
)
verify_command h2load
