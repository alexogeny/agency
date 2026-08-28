#!/usr/bin/env bash

agency_as_root() {
  if (( EUID != 0 )); then
    sudo "$@"
  else
    "$@"
  fi
}

agency_ensure_backup_root() {
  if [[ -z ${AGENCY_BACKUP_ROOT:-} ]]; then
    AGENCY_BACKUP_ROOT="$HOME/.local/state/agency/backups/$(date -u +%Y%m%dT%H%M%SZ)-$$"
    export AGENCY_BACKUP_ROOT
  fi
}

agency_backup_path() {
  local target=$1
  agency_ensure_backup_root

  if [[ $target == "$HOME"/* ]]; then
    printf '%s/home/%s\n' "$AGENCY_BACKUP_ROOT" "${target#"$HOME"/}"
  else
    printf '%s/system/%s\n' "$AGENCY_BACKUP_ROOT" "${target#/}"
  fi
}

agency_backup_copy() {
  local target=$1

  if [[ ! -e $target || -L $target ]]; then
    return
  fi

  local backup
  agency_ensure_backup_root
  backup=$(agency_backup_path "$target")
  mkdir -p "$(dirname -- "$backup")"
  cp -a -- "$target" "$backup"
  printf 'Backed up %s to %s\n' "$target" "$backup"
}

agency_link() {
  local source=$1
  local target=$2

  if [[ ! -e $source && ! -L $source ]]; then
    printf 'Managed link source does not exist: %s\n' "$source" >&2
    return 1
  fi

  mkdir -p "$(dirname -- "$target")"
  if [[ -e $target && $source -ef $target ]]; then
    return
  fi

  if [[ -e $target && ! -L $target ]]; then
    local backup
    agency_ensure_backup_root
    backup=$(agency_backup_path "$target")
    mkdir -p "$(dirname -- "$backup")"
    mv -- "$target" "$backup"
    printf 'Backed up %s to %s\n' "$target" "$backup"
  fi

  ln -sfnT -- "$source" "$target"
}

agency_link_as_root() {
  local source=$1
  local target=$2

  if [[ ! -e $source && ! -L $source ]]; then
    printf 'Managed link source does not exist: %s\n' "$source" >&2
    return 1
  fi

  agency_as_root mkdir -p "$(dirname -- "$target")"
  if [[ -e $target && $source -ef $target ]]; then
    return
  fi

  if [[ -e $target && ! -L $target ]]; then
    local backup
    agency_ensure_backup_root
    backup=$(agency_backup_path "$target")
    agency_as_root mkdir -p "$(dirname -- "$backup")"
    agency_as_root mv -- "$target" "$backup"
    printf 'Backed up %s to %s\n' "$target" "$backup"
  fi

  agency_as_root ln -sfnT -- "$source" "$target"
}

agency_install_git_identity() {
  local identity_file=$1

  if [[ -e $identity_file || -L $identity_file ]]; then
    return
  fi

  local name email signing_key
  name=$(git config --global --includes --get user.name 2>/dev/null || true)
  email=$(git config --global --includes --get user.email 2>/dev/null || true)
  signing_key=$(git config --global --includes --get user.signingkey 2>/dev/null || true)

  mkdir -p "$(dirname -- "$identity_file")"
  install -m 600 /dev/null "$identity_file"

  if [[ -n $name || -n $email || -n $signing_key ]]; then
    [[ -z $name ]] || git config --file "$identity_file" user.name "$name"
    [[ -z $email ]] || git config --file "$identity_file" user.email "$email"
    [[ -z $signing_key ]] || git config --file "$identity_file" user.signingkey "$signing_key"
    printf 'Imported the existing Git identity into %s\n' "$identity_file"
    return
  fi

  printf '%s\n' \
    '# Machine-local Git identity. Copy values from the repository identity.example.' \
    >> "$identity_file"
  printf 'Edit %s with your Git author identity.\n' "$identity_file"
}

agency_preserve_git_config() {
  local local_config=$1
  shift

  if [[ -e $local_config || -L $local_config ]]; then
    return
  fi

  local source
  for source in "$@"; do
    [[ -f $source && ! -L $source ]] || continue
    mkdir -p "$(dirname -- "$local_config")"
    cp -a -- "$source" "$local_config"
    chmod 600 "$local_config"
    printf 'Preserved existing Git settings in %s\n' "$local_config"
    return
  done
}

agency_prepare_scratch() {
  local canonical="$HOME/Scratch"
  local legacy="$HOME/scratch"

  if [[ -d $legacy && ! -L $legacy && ! -e $canonical && ! -L $canonical ]]; then
    mv -- "$legacy" "$canonical"
    printf 'Migrated %s to %s\n' "$legacy" "$canonical"
  elif [[ -d $legacy && ! -L $legacy && -d $canonical && ! -L $canonical ]]; then
    local item name moved=0 conflicts=0
    while IFS= read -r -d '' item; do
      name=${item##*/}
      if [[ -e $canonical/$name || -L $canonical/$name ]]; then
        (( conflicts += 1 ))
        continue
      fi
      mv -- "$item" "$canonical/$name"
      (( moved += 1 ))
    done < <(find "$legacy" -mindepth 1 -maxdepth 1 -print0)
    if (( moved )); then
      printf 'Migrated %d non-conflicting entries from %s to %s\n' \
        "$moved" "$legacy" "$canonical"
    fi
    if (( conflicts )); then
      printf '%d conflicting entry or entries remain in %s for manual review.\n' \
        "$conflicts" "$legacy" >&2
    else
      rmdir -- "$legacy"
    fi
  elif [[ ( -e $legacy || -L $legacy ) && ( -e $canonical || -L $canonical ) ]]; then
    printf 'Cannot safely merge %s and %s because one is not a regular directory.\n' \
      "$legacy" "$canonical" >&2
  fi

  mkdir -p "$canonical"
}

agency_merge_agent_hooks() {
  local fragment=$1
  local target=$2
  local library_dir merger status
  library_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
  merger="$library_dir/merge-agent-hooks.py"

  if "$merger" --check "$target" "$fragment"; then
    agency_backup_copy "$target"
    "$merger" "$target" "$fragment"
    printf 'Added session context hook to %s\n' "$target"
    return
  else
    status=$?
  fi

  if (( status == 1 )); then
    return
  fi
  return "$status"
}
