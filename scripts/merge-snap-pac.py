#!/usr/bin/env python3
import configparser
from pathlib import Path
import re
import sys


def merge_policy(current: str, policy: str) -> str:
    managed = configparser.ConfigParser(interpolation=None)
    managed.read_string(policy)
    enabled = managed.getboolean("root", "snapshot")
    existing = configparser.ConfigParser(interpolation=None)
    existing.read_string(current)
    setting = f"snapshot = {enabled}\n"
    headers = list(re.finditer(r"(?m)^[ \t]*\[([^]\r\n]+)\][^\r\n]*(?:\n|$)", current))
    for index, header in enumerate(headers):
        if header[1] != "root":
            continue
        end = headers[index + 1].start() if index + 1 < len(headers) else len(current)
        body = current[header.end():end]
        option = re.search(r"(?im)^[ \t]*snapshot[ \t]*[:=][^\r\n]*(?:\n|$)", body)
        if option:
            if existing.getboolean("root", "snapshot") == enabled:
                return current
            body = body[:option.start()] + setting + body[option.end():]
        else:
            body = body + ("\n" if body and not body.endswith("\n") else "") + setting
        prefix = current[:header.end()]
        return prefix + ("\n" if not prefix.endswith("\n") else "") + body + current[end:]
    return current + ("\n" if current and not current.endswith("\n") else "") + "[root]\n" + setting


def main() -> int:
    if len(sys.argv) != 3:
        print("Usage: merge-snap-pac.py CURRENT_CONFIG MANAGED_POLICY", file=sys.stderr)
        return 2
    target, policy = map(Path, sys.argv[1:])
    try:
        current = target.read_text() if target.exists() else ""
        merged = merge_policy(current, policy.read_text())
    except (OSError, ValueError, configparser.Error) as error:
        print(f"Cannot configure package snapshots: {error}", file=sys.stderr)
        return 1
    sys.stdout.write(merged)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
