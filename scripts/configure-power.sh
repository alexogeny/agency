#!/usr/bin/env bash
set -euo pipefail

AGENCY_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)

mkdir -p "$HOME/.config"
ln -sfn "$AGENCY_DIR/config/kde/powerdevilrc" "$HOME/.config/powerdevilrc"

# PowerDevil reloads the linked policy immediately when a Plasma session exists.
systemctl --user try-restart plasma-powerdevil.service 2>/dev/null || true

is_laptop=false
case "$(cat /sys/class/dmi/id/chassis_type 2>/dev/null || true)" in
  8|9|10|11|12|14|30|31|32) is_laptop=true ;;
esac

for supply in /sys/class/power_supply/*; do
  [[ -e "$supply/type" ]] || continue
  if [[ $(<"$supply/type") == Battery ]]; then
    is_laptop=true
    break
  fi
done

if [[ $is_laptop == false ]] && command -v kscreen-doctor >/dev/null; then
  mapfile -t displays < <(
    kscreen-doctor --json 2>/dev/null |
      jq -r '.outputs[] | select(.connected and .enabled) | .name'
  )

  if (( ${#displays[@]} )); then
    brightness_settings=()
    for display in "${displays[@]}"; do
      brightness_settings+=("output.$display.brightness.100")
    done
    kscreen-doctor "${brightness_settings[@]}"
    printf '🎀 Set %d desktop display(s) to full brightness.\n' "${#displays[@]}"
  fi
else
  printf '🎀 Laptop/mobile hardware detected; preserving display brightness.\n'
fi
