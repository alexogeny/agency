#!/usr/bin/env bash

agency_configure_storage() {
  local tool="$AGENCY_DIR/Tools/agency-storage"
  local config="${XDG_CONFIG_HOME:-$HOME/.config}/agency/storage.json"

  if [[ ${1:-} == --dry-run ]]; then
    "$tool" setup --dry-run
  elif [[ -e $config || -L $config ]]; then
    "$tool" status
  elif [[ -t 0 && -t 1 ]]; then
    "$tool" setup --interactive
  else
    printf 'Storage setup skipped: run agency-storage setup --interactive to opt in.\n'
  fi
}

if [[ ${BASH_SOURCE[0]} == "$0" ]]; then
  set -euo pipefail
  AGENCY_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
  agency_configure_storage "$@"
fi
