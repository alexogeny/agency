#!/usr/bin/env bash

agency_configure_snapshots() (
  set -euo pipefail
  local target=${1:-/etc/snap-pac.ini} temporary
  temporary=$(mktemp)
  trap 'rm -f -- "$temporary"' EXIT
  python3 "$AGENCY_DIR/scripts/merge-snap-pac.py" \
    "$target" "$AGENCY_DIR/system/snap-pac.ini" > "$temporary"
  agency_install_policy "$temporary" "$target"
)

if [[ ${BASH_SOURCE[0]} == "$0" ]]; then
  set -euo pipefail
  AGENCY_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
  source "$AGENCY_DIR/scripts/lib.sh"
  source "$AGENCY_DIR/scripts/platform.sh"
  if [[ $(agency_detect_platform) == linux ]]; then
    agency_configure_snapshots
  else
    printf 'Package snapshot policy applies only to Arch/CachyOS Linux.\n'
  fi
fi
