#!/usr/bin/env python3

import argparse
import json
import os
import tempfile
from pathlib import Path


def load_json(path, default=None):
    if not path.exists():
        return default
    with path.open() as source:
        return json.load(source)


def merged_config(target, fragment):
    result = load_json(target, {})
    additions = load_json(fragment)
    if not isinstance(result, dict) or not isinstance(additions, dict):
        raise ValueError("hook configuration must be a JSON object")
    fragment_hooks = additions.get("hooks")
    if not isinstance(fragment_hooks, dict):
        raise ValueError("hook fragment must contain a hooks object")
    target_hooks = result.setdefault("hooks", {})
    if not isinstance(target_hooks, dict):
        raise ValueError("target hooks value must be a JSON object")
    for event, groups in fragment_hooks.items():
        if not isinstance(groups, list):
            raise ValueError(f"hook event {event} must contain a JSON array")
        target_groups = target_hooks.setdefault(event, [])
        if not isinstance(target_groups, list):
            raise ValueError(f"target hook event {event} must contain a JSON array")
        managed_commands = {
            handler.get("command")
            for group in groups
            if isinstance(group, dict)
            for handler in group.get("hooks", [])
            if isinstance(handler, dict) and handler.get("command")
        }
        retained_groups = []
        for target_group in target_groups:
            if target_group in groups or not isinstance(target_group, dict):
                retained_groups.append(target_group)
                continue
            target_handlers = target_group.get("hooks")
            if not isinstance(target_handlers, list):
                retained_groups.append(target_group)
                continue
            retained_handlers = [
                handler
                for handler in target_handlers
                if not isinstance(handler, dict)
                or handler.get("command") not in managed_commands
            ]
            if retained_handlers:
                retained_group = dict(target_group)
                retained_group["hooks"] = retained_handlers
                retained_groups.append(retained_group)
        retained_groups.extend(group for group in groups if group not in retained_groups)
        target_hooks[event] = retained_groups
    return result


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    mode = path.stat().st_mode & 0o777 if path.exists() else 0o600
    with tempfile.NamedTemporaryFile(
        mode="w", dir=path.parent, prefix=f".{path.name}.", delete=False
    ) as destination:
        json.dump(value, destination, indent=2)
        destination.write("\n")
        temporary = Path(destination.name)
    os.chmod(temporary, mode)
    os.replace(temporary, path)


def main():
    parser = argparse.ArgumentParser(
        description="Merge additive lifecycle hooks into an agent JSON config."
    )
    parser.add_argument("--check", action="store_true")
    parser.add_argument("target", type=Path)
    parser.add_argument("fragment", type=Path)
    arguments = parser.parse_args()
    existing = load_json(arguments.target, {})
    merged = merged_config(arguments.target, arguments.fragment)
    if arguments.check:
        raise SystemExit(0 if merged != existing else 1)
    if merged != existing:
        write_json(arguments.target, merged)


if __name__ == "__main__":
    main()
