"""Low-level procfs readers; callers retain ownership and failure policies."""
import io
import os
import re


def read_process_file(path, *, limit=None, text=False):
    with open(path, 'r' if text else 'rb') as handle:
        value = handle.read() if limit is None else handle.read(limit + 1)
    if limit is not None and len(value) > limit:
        raise OSError('Process inspection size limit exceeded')
    return value


def read_link(path):
    return os.readlink(path)


def normalize_path(value, *, collapse_dots=False):
    value = value.removesuffix(' (deleted)')
    return os.path.normpath(value) if collapse_dots else value


def mapped_paths(content, *, decode_escapes=False):
    streamed = type(content) is bytes and len(content) > 65536 and b'\r' not in content
    lines = io.BytesIO(content) if streamed else content.splitlines()
    for line in lines:
        fields = line.split(None, 5)
        if len(fields) != 6:
            continue
        value = fields[5].removesuffix(b'\n') if streamed else fields[5]
        if decode_escapes:
            value = re.sub(rb'\\([0-7]{3})', lambda match: bytes([int(match[1], 8)]), value)
        yield os.fsdecode(value)
