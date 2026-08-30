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

uv_tool_python=${AGENCY_UV_TOOL_PYTHON:-"$(command -v python3)"}
retained=()

while IFS='|' read -r command label package; do
  if $update || ! command -v "$command" >/dev/null 2>&1; then
    arguments=(tool install --python "$uv_tool_python")
    if $update; then
      arguments+=(--upgrade)
    fi
    uv "${arguments[@]}" "$package"
  else
    retained+=("$label")
  fi
done <<'EOF'
gantry|Gantry|git+https://github.com/alexogeny/gantry-cli.git
thoreau|Thoreau|git+https://github.com/alexogeny/thoreau.git
podman-compose|podman-compose|podman-compose
EOF

if (( ${#retained[@]} )); then
  printf '⚠ Already installed and left unchanged:\n'
  printf '  - %s\n' "${retained[@]}"
  printf 'If any version is older than upstream, run ./install.sh --update.\n'
fi
