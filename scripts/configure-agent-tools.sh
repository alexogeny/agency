#!/usr/bin/env bash
set -euo pipefail

server="$HOME/.local/bin/web-research-mcp"

if command -v codex >/dev/null 2>&1; then
  if codex mcp get agency-web >/dev/null 2>&1; then
    printf 'Keeping existing agency-web MCP registration for Codex.\n'
  else
    codex mcp add agency-web -- "$server"
  fi
fi

if command -v claude >/dev/null 2>&1; then
  if claude mcp get agency-web >/dev/null 2>&1; then
    printf 'Keeping existing agency-web MCP registration for Claude Code.\n'
  else
    claude mcp add --scope user agency-web -- "$server"
  fi
fi
