#!/usr/bin/env bash
set -euo pipefail

AGENCY_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
source "$AGENCY_DIR/scripts/lib.sh"

detect_laptop() {
  local sysfs_root=${AGENCY_SYSFS_ROOT:-/sys}
  local chassis_type
  chassis_type=$(cat "$sysfs_root/class/dmi/id/chassis_type" 2>/dev/null || true)

  case "$chassis_type" in
    8|9|10|11|12|14|30|31|32) return 0 ;;
  esac

  local supply
  for supply in "$sysfs_root"/class/power_supply/*; do
    [[ -e $supply/type ]] || continue
    if [[ $(<"$supply/type") == Battery ]] &&
      [[ ! -e $supply/present || $(<"$supply/present") != 0 ]] &&
      [[ ! -e $supply/scope || $(<"$supply/scope") != Device ]]; then
      return 0
    fi
  done

  return 1
}

set_desktop_brightness() {
  command -v kscreen-doctor >/dev/null || return

  local -a displays brightness_settings
  mapfile -t displays < <(
    kscreen-doctor --json 2>/dev/null |
      jq -r '.outputs[] | select(.connected and .enabled) | .name'
  )

  (( ${#displays[@]} )) || return
  brightness_settings=()
  local display
  for display in "${displays[@]}"; do
    brightness_settings+=("output.$display.brightness.100")
  done
  kscreen-doctor "${brightness_settings[@]}"
  printf '🎀 Set %d desktop display(s) to full brightness.\n' "${#displays[@]}"
}

configure_power() {
  local hardware profile
  local -a sleep_targets=(
    sleep.target
    suspend.target
    hibernate.target
    hybrid-sleep.target
  )

  if detect_laptop; then
    hardware=laptop
    profile="$AGENCY_DIR/config/kde/powerdevil-laptoprc"
  else
    hardware=desktop
    profile="$AGENCY_DIR/config/kde/powerdevil-desktoprc"
  fi

  agency_link "$profile" "$HOME/.config/powerdevilrc"

  if [[ $hardware == laptop ]]; then
    agency_as_root systemctl unmask "${sleep_targets[@]}"
    printf '🎀 Laptop/mobile hardware detected; enabling portable power policy.\n'
  else
    agency_as_root systemctl mask "${sleep_targets[@]}"
    set_desktop_brightness
  fi

  systemctl --user try-restart plasma-powerdevil.service 2>/dev/null || true
}

if [[ ${BASH_SOURCE[0]} == "$0" ]]; then
  configure_power
fi
