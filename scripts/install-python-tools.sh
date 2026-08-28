#!/usr/bin/env bash
set -euo pipefail

uv_tool_python=${AGENCY_UV_TOOL_PYTHON:-"$(command -v python3)"}

# Keep uv from implicitly preferring an installed free-threaded interpreter.
# Some compiled tool dependencies publish wheels for cp314 but not cp314t.
uv tool install --python "$uv_tool_python" --upgrade \
  git+https://github.com/alexogeny/gantry-cli.git
uv tool install --python "$uv_tool_python" --upgrade \
  git+https://github.com/alexogeny/thoreau.git
uv tool install --python "$uv_tool_python" --upgrade podman-compose
