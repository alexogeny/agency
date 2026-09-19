#!/usr/bin/env bash
set -euo pipefail

for registration in agency-web agency-decide; do
  case "$registration" in
    agency-web) server="$HOME/.local/bin/web-research-mcp" ;;
    agency-decide) server="$HOME/.local/bin/agency-decide-mcp" ;;
  esac

  if command -v codex >/dev/null 2>&1; then
    if codex mcp get "$registration" >/dev/null 2>&1; then
      printf 'Keeping existing %s MCP registration for Codex.\n' "$registration"
    else
      codex mcp add "$registration" -- "$server"
    fi
  fi

  if command -v claude >/dev/null 2>&1; then
    if claude mcp get "$registration" >/dev/null 2>&1; then
      printf 'Keeping existing %s MCP registration for Claude Code.\n' "$registration"
    else
      claude mcp add --scope user "$registration" -- "$server"
    fi
  fi
done
