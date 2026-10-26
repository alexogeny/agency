#!/usr/bin/env bash
set -euo pipefail

script_directory=${BASH_SOURCE[0]%/*}
[[ $script_directory != "${BASH_SOURCE[0]}" ]] || script_directory=.
source "$script_directory/lib.sh"
update=$(agency_install_update_mode "$@")

stable_is_default=false
while IFS= read -r toolchain; do
  if [[ $toolchain == stable-* && $toolchain == *default* ]]; then
    stable_is_default=true
    break
  fi
done < <(rustup toolchain list)

if ! $stable_is_default; then
  rustup default stable
elif $update; then
  rustup update stable
else
  printf '⚠ stable Rust is already installed and left unchanged.\n'
  printf 'If it is older than upstream, run ./install.sh --update.\n'
fi
