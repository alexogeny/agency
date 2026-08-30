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

temporary_directories=()
cleanup() {
  local directory
  for directory in "${temporary_directories[@]}"; do
    if [[ -d $directory &&
      ( $directory == "$HOME/Scratch/"yay.* ||
        $directory == "$HOME/Scratch/"nghttp2.* ) ]]; then
      rm -rf -- "$directory"
    fi
  done
}
trap cleanup EXIT

retained=()

if ! command -v yay >/dev/null 2>&1; then
  mkdir -p "$HOME/Scratch"
  yay_build_dir="$(mktemp -d -p "$HOME/Scratch" yay.XXXXXX)"
  temporary_directories+=("$yay_build_dir")

  git clone --depth 1 https://aur.archlinux.org/yay.git "$yay_build_dir"
  review_recipe "$yay_build_dir/PKGBUILD"
  (
    cd "$yay_build_dir"
    makepkg -si --needed --noconfirm
  )
elif $update; then
  yay -S --needed --noconfirm yay
else
  retained+=(yay)
fi

verify_command yay

if command -v h2load >/dev/null 2>&1 && ! $update; then
  verify_command h2load
  retained+=(h2load)
  printf '⚠ Already installed and left unchanged:\n'
  printf '  - %s\n' "${retained[@]}"
  printf 'If any version is older than upstream, run ./install.sh --update.\n'
  exit 0
fi

if $update; then
  mkdir -p "$HOME/Scratch"
  nghttp2_build_dir="$(mktemp -d -p "$HOME/Scratch" nghttp2.XXXXXX)"
  temporary_directories+=("$nghttp2_build_dir")
  nghttp2_dir="$nghttp2_build_dir/source"
  git clone --depth 1 https://aur.archlinux.org/nghttp2.git "$nghttp2_dir"
else
  nghttp2_dir="${XDG_CACHE_HOME:-$HOME/.cache}/yay/nghttp2"
fi
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
