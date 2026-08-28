#!/usr/bin/env bash
set -euo pipefail

# Bun keeps these under ~/.bun, so installation needs no root access.
bun add --global @openai/codex @anthropic-ai/claude-code
bun add --global --ignore-scripts @earendil-works/pi-coding-agent
