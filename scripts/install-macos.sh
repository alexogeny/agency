#!/usr/bin/env bash

agency_install_macos_packages() {
  local update=$1 package
  local -a missing=() installed=()
  while IFS= read -r package; do
    [[ -n $package && $package != \#* ]] || continue
    if brew list --formula "${package##*/}" >/dev/null 2>&1; then
      installed+=("$package")
    else
      missing+=("$package")
    fi
  done < "$AGENCY_DIR/packages-macos.txt"
  if [[ -n ${missing[*]:-} ]]; then
    brew install --formula "${missing[@]}"
  fi
  if $update && [[ -n ${installed[*]:-} ]]; then
    brew upgrade --formula "${installed[@]}"
  fi
  local rustup_prefix
  rustup_prefix=$(brew --prefix rustup) || return
  export PATH="$rustup_prefix/bin:$PATH"

  local name app
  while IFS='|' read -r name app; do
    if brew list --cask "$name" >/dev/null 2>&1; then
      if $update; then
        brew upgrade --cask "$name"
      else
        printf 'Keeping installed %s; use --update to upgrade.\n' "$name"
      fi
    elif [[ -n $app && -d /Applications/$app ]]; then
      printf 'Keeping existing /Applications/%s; update this app through its own updater.\n' "$app"
    elif [[ $name == 1password-cli ]] && command -v op >/dev/null 2>&1; then
      printf 'Keeping existing 1Password CLI; update it through its original installer.\n'
    else
      brew install --cask "$name"
    fi
  done <<'CASKS'
firefox|Firefox.app
1password|1Password.app
1password-cli|
font-fantasque-sans-mono-nerd-font|
CASKS
}

agency_install_macos_sandbox_runtime() {
  local update=$1
  if $update || ! command -v srt >/dev/null 2>&1; then
    bun add --global --ignore-scripts @anthropic-ai/sandbox-runtime@0.0.77
  else
    printf 'Keeping installed Sandbox Runtime; use --update to install the reviewed pin.\n'
  fi
}

agency_configure_macos_terminal() {
  local fish="${brew_prefix:?Homebrew prefix must be set}/bin/fish" current_shell
  if [[ ! -x $fish ]]; then
    printf 'Fish is missing at %s; Terminal settings were not changed.\n' "$fish" >&2
    return 1
  fi
  current_shell=$(defaults read com.apple.Terminal Shell 2>/dev/null || true)
  if [[ $current_shell != "$fish" ]]; then
    agency_backup_copy "$HOME/Library/Preferences/com.apple.Terminal.plist"
    defaults write com.apple.Terminal Shell -string "$fish"
  fi
  printf 'Terminal opens Fish (%s). Open a new window; restart Terminal if it retains the previous shell.\n' "$fish"
}

agency_configure_macos() {
  local firefox_app=/Applications/Firefox.app
  local distribution="$firefox_app/Contents/Resources/distribution"
  agency_link "$AGENCY_DIR/scripts/firefox-macos.sh" "$HOME/.local/bin/firefox"
  agency_install_policy "$AGENCY_DIR/firefox/policies.json" "$distribution/policies.json"

  mkdir -p "$HOME/.config/agency"
  local environment="$HOME/.config/agency/env.sh"
  agency_backup_copy "$environment"
  {
    printf 'export PATH="%s/bin:%s/sbin:%s/bin:$HOME/.local/bin:$HOME/.cargo/bin:$HOME/.bun/bin:$PATH"\n' \
      "$brew_prefix" "$brew_prefix" "$(brew --prefix rustup)"
  } > "$environment"
  local profile="$HOME/.zprofile"
  local source_line='[ ! -f "$HOME/.config/agency/env.sh" ] || . "$HOME/.config/agency/env.sh"'
  if ! grep -Fqx "$source_line" "$profile" 2>/dev/null; then
    agency_backup_copy "$profile"
    printf '\n%s\n' "$source_line" >> "$profile"
  fi
  agency_configure_macos_terminal
  printf '\nmacOS setup uses a Podman Linux VM. When needed, run: podman machine init && podman machine start\n'
  printf 'Native sandbox uses macOS Seatbelt through Sandbox Runtime. Linux perf/procfs diagnostics, KDE, system DNS, scheduler, and trim settings are unavailable.\n'
}

agency_print_macos_plan() {
  local update=${1:-false} package detected_brew developer_tools
  printf '\033[1;35mAGENCY INSTALL — DRY RUN (macOS)\033[0m\n'
  printf 'Checkout: %s\nNo sudo prompt will be shown and no commands below will be executed.\n\n' "$AGENCY_DIR"
  if detected_brew=$(agency_find_brew); then
    printf 'Homebrew found: %s (retain existing installation).\n' "$detected_brew"
  else
    printf 'Homebrew missing: install verified official installer (search PATH, /opt/homebrew/bin, /usr/local/bin).\n'
  fi
  if [[ $(uname -s) == Darwin ]]; then
    if developer_tools=$(xcode-select -p 2>/dev/null); then
      printf 'Apple developer tools selected: %s\n' "$developer_tools"
    else
      printf 'Apple Command Line Tools missing: the Homebrew installer will request installation.\n'
    fi
  fi
  printf 'Download the pinned official installer over HTTPS, verify SHA-256, then run it with native sudo/confirmation prompts.\n'
  printf 'The Homebrew installer installs missing Apple Command Line Tools; follow its prompts if macOS needs an interactive installation.\n'
  printf 'The current official installer supports new Apple Silicon installations; existing Intel Homebrew is retained.\n'
  printf 'Use Homebrew Bash for installation; the preview also supports macOS Bash 3.2.\n\n'
  agency_plan_scratch
  agency_plan_user_links
  printf '\nHomebrew formulae (install missing'
  if $update; then printf ', upgrade installed'; else printf ', retain installed'; fi
  printf '):\n'
  while IFS= read -r package; do
    [[ -n $package && $package != \#* ]] || continue
    printf '  %s\n' "$package"
  done < "$AGENCY_DIR/packages-macos.txt"
  printf 'Homebrew casks: Firefox, 1Password desktop, 1Password CLI, Fantasque Sans Mono Nerd Font (preserve externally installed apps).\n'
  printf 'Shared runtimes: stable Rust, Codex/Claude Code/Pi through Bun, Gantry/Thoreau/podman-compose through uv.\n'
  printf 'Native sandbox: Anthropic Sandbox Runtime 0.0.77 through Bun and built-in macOS Seatbelt (sandbox-exec).\n'
  if $update; then
    printf 'Update stable Rust and reinstall repository-pinned user tools.\n'
  else
    printf 'Retain installed user tools; use --update to reinstall reviewed pins.\n'
  fi
  printf 'Install verified Computer Modern Unicode report fonts.\n'
  agency_plan_git
  agency_plan_link "$AGENCY_DIR/config/fish/config.fish" "$HOME/.config/fish/config.fish"
  agency_plan_link "$AGENCY_DIR/config/starship.toml" "$HOME/.config/starship.toml"
  agency_plan_link "$AGENCY_DIR/scripts/firefox-macos.sh" "$HOME/.local/bin/firefox"
  printf 'Configure Firefox policy in /Applications/Firefox.app/Contents/Resources/distribution/policies.json.\n'
  printf 'Link user.js in ~/Library/Application Support/Firefox profiles; install 1Password Firefox extension through policy.\n'
  printf 'Back up changed shell files; add Homebrew and user-tool paths to ~/.zprofile.\n'
  printf 'Back up Terminal preferences and set Terminal to open Homebrew Fish; retain the account login shell.\n'
  printf 'Podman VM remains opt-in: podman machine init && podman machine start.\n'
  printf 'Linux-only tools and tuning are skipped: Bubblewrap, perf/procfs diagnostics, AUR, KDE, systemd DNS, scheduler, power and trim.\n'
  printf '\nNo changes were made. Run ./install.sh'
  if [[ $(agency_detect_platform) != macos ]]; then printf ' --platform macos'; fi
  if $update; then printf ' --update'; fi
  printf ' to apply this plan on a Mac.\n'
}
