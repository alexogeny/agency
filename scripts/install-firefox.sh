#!/usr/bin/env bash
set -euo pipefail

AGENCY_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
source "$AGENCY_DIR/scripts/lib.sh"
profiles_ini="$HOME/.mozilla/firefox/profiles.ini"

if [[ ! -f "$profiles_ini" ]]; then
  mkdir -p "$HOME/.mozilla/firefox"
  firefox -CreateProfile "default-release $HOME/.mozilla/firefox/default-release"
fi

while IFS= read -r profile; do
  mkdir -p "$profile"
  agency_link "$AGENCY_DIR/firefox/user.js" "$profile/user.js"
done < <(
  awk -F= -v base="$HOME/.mozilla/firefox" '
    /^IsRelative=/{ relative=$2 }
    /^Path=/{ print (relative == 1 ? base "/" : "") $2 }
  ' "$profiles_ini"
)
