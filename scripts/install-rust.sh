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
