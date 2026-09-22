#!/usr/bin/env bash
set -euo pipefail

AGENCY_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
source "$AGENCY_DIR/scripts/lib.sh"
if [[ ${AGENCY_PLATFORM:-} == macos || $(uname -s) == Darwin ]]; then
  profile_root="$HOME/Library/Application Support/Firefox"
  firefox_binary="/Applications/Firefox.app/Contents/MacOS/firefox"
else
  profile_root="$HOME/.mozilla/firefox"
  firefox_binary=firefox
fi
profiles_ini="$profile_root/profiles.ini"

if [[ ! -f "$profiles_ini" ]]; then
  mkdir -p "$profile_root"
  "$firefox_binary" -CreateProfile "default-release $profile_root/default-release"
fi

while IFS= read -r profile; do
  mkdir -p "$profile"
  agency_link "$AGENCY_DIR/firefox/user.js" "$profile/user.js"
done < <(
  awk -F= -v base="$profile_root" '
    { sub(/\r$/, "") }
    /^IsRelative=/{ relative=$2 }
    /^Path=/{ print (relative == 1 ? base "/" : "") $2 }
  ' "$profiles_ini"
)
