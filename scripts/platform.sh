#!/usr/bin/env bash

agency_detect_platform() {
  case $(uname -s) in
    Darwin) printf 'macos\n' ;;
    Linux) printf 'linux\n' ;;
    *) printf 'Unsupported operating system: %s\n' "$(uname -s)" >&2; return 1 ;;
  esac
}

agency_find_brew() {
  if command -v brew >/dev/null 2>&1; then
    command -v brew
  elif [[ -x /opt/homebrew/bin/brew ]]; then
    printf '/opt/homebrew/bin/brew\n'
  elif [[ -x /usr/local/bin/brew ]]; then
    printf '/usr/local/bin/brew\n'
  else
    return 1
  fi
}

agency_bootstrap_homebrew() (
  set -euo pipefail
  revision=d797f6b3d244abc548808fd75b879ca6860c653f
  checksum=71d25d14c32edd7adeaf4413ba671b28474ea08e4f6662cb1a73e85ff0eba368
  scratch=$(mktemp -d "${TMPDIR:-/tmp}/agency-homebrew.XXXXXX") || exit 1
  trap 'rm -rf -- "$scratch"' EXIT
  installer="$scratch/install.sh"

  printf 'Installing Homebrew with its verified official installer. This may install Apple Command Line Tools and request sudo.\n'
  if ! curl --fail --location --silent --show-error --proto '=https' --proto-redir '=https' \
    "https://raw.githubusercontent.com/Homebrew/install/$revision/install.sh" --output "$installer"; then
    printf 'Could not download the Homebrew installer; setup stopped.\n' >&2
    exit 1
  fi
  if ! printf '%s  %s\n' "$checksum" "$installer" | shasum -a 256 --check --status; then
    printf 'Homebrew installer checksum verification failed; nothing was executed.\n' >&2
    exit 1
  fi
  if ! /bin/bash "$installer"; then
    printf 'Homebrew installation failed; resolve the installer error and rerun Agency.\n' >&2
    exit 1
  fi
)

agency_ensure_homebrew() {
  if AGENCY_BREW=$(agency_find_brew); then
    return
  fi
  agency_bootstrap_homebrew || return 1
  if ! AGENCY_BREW=$(agency_find_brew); then
    printf 'Homebrew installer finished, but Agency could not find brew in PATH, /opt/homebrew/bin, or /usr/local/bin.\n' >&2
    return 1
  fi
}
