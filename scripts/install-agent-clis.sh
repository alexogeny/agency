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

standard_packages=()
pi_packages=()
retained=()

while IFS='|' read -r command label package group; do
  if $update || ! command -v "$command" >/dev/null 2>&1; then
    if [[ $group == standard ]]; then
      standard_packages+=("$package")
    else
      pi_packages+=("$package")
    fi
  else
    retained+=("$label")
  fi
done <<'EOF'
codex|Codex|@openai/codex|standard
claude|Claude Code|@anthropic-ai/claude-code|standard
pi|Pi|@earendil-works/pi-coding-agent|pi
EOF

if (( ${#standard_packages[@]} )); then
  bun add --global "${standard_packages[@]}"
fi
if (( ${#pi_packages[@]} )); then
  bun add --global --ignore-scripts "${pi_packages[@]}"
fi

if (( ${#retained[@]} )); then
  printf '⚠ Already installed and left unchanged:\n'
  printf '  - %s\n' "${retained[@]}"
  printf 'If any version is older than upstream, run ./install.sh --update.\n'
fi
