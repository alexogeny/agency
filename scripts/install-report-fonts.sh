#!/usr/bin/env bash
set -euo pipefail

version=0.7.0
archive="cm-unicode-$version-ttf.tar.xz"
checksum=2609c14450f42d0bcd40203900afcb1d693521a9b24a18c65e14b6b0585ff150
mkdir -p "$HOME/Scratch"
scratch_dir=$(mktemp -d "$HOME/Scratch/report-fonts.XXXXXX")
trap 'rm -rf -- "$scratch_dir"' EXIT
url="https://downloads.sourceforge.net/project/cm-unicode/cm-unicode/$version/$archive"

curl --fail --location --silent --show-error "$url" --output "$scratch_dir/$archive"
if command -v shasum >/dev/null 2>&1; then
  printf '%s  %s\n' "$checksum" "$scratch_dir/$archive" | shasum -a 256 -c
else
  printf '%s  %s\n' "$checksum" "$scratch_dir/$archive" | sha256sum --check --status
fi
tar -xJf "$scratch_dir/$archive" -C "$scratch_dir"
source_dir="$scratch_dir/cm-unicode-$version"
font_dir="$HOME/.local/share/fonts/cm-unicode"
license_dir="$HOME/.local/share/licenses/cm-unicode"

mkdir -p "$font_dir" "$license_dir"
install -m644 "$source_dir/cmunrm.ttf" "$font_dir/cmunrm.ttf"
install -m644 "$source_dir/cmunbx.ttf" "$font_dir/cmunbx.ttf"
install -m644 "$source_dir/cmunti.ttf" "$font_dir/cmunti.ttf"
install -m644 "$source_dir/cmunbi.ttf" "$font_dir/cmunbi.ttf"
install -m644 "$source_dir/OFL.txt" "$license_dir/OFL.txt"
install -m644 "$source_dir/OFL-FAQ.txt" "$license_dir/OFL-FAQ.txt"
install -m644 "$source_dir/README" "$license_dir/README"
fc-cache -f "$font_dir"
