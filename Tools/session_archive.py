import argparse
from collections import Counter
import datetime
import hashlib
import itertools
import json
import os
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))
from agency_streams import load_json_digest
import re
import stat


DATA_URI = re.compile(
    r"data:(?:image/[^;,\s\"'\\]+|audio/[^;,\s\"'\\]+|video/[^;,\s\"'\\]+|application/octet-stream)(?:;[^,\s\"'\\]*)?;base64,[A-Za-z0-9+/=_-]+",
    re.IGNORECASE,
)
RAW_IMAGE = re.compile(r"(?:iVBORw0KGgo|/9j/|UklGR|R0lGOD)[A-Za-z0-9+/=_-]{128,}")
IMAGE_OBJECT = re.compile(
    r'"(?:type|mimeType|mime_type|media_type)"\s*:\s*"(?:image|input_image|output_image|image/[^\"]+)"'
)


def marker(size, counts):
    counts["payloads"] += 1
    counts["characters"] += size
    return f"[embedded image/binary payload omitted: {size} characters]"


def clean(value, counts):
    if isinstance(value, dict):
        image = value.get("type") in {"image", "input_image", "output_image"} or any(
            isinstance(value.get(key), str) and value[key].startswith("image/")
            for key in ("mimeType", "mime_type", "media_type", "mime")
        )
        return {
            key: marker(len(item), counts)
            if image
            and key in {"data", "base64", "b64_json", "bytes"}
            and isinstance(item, str)
            and not item.startswith("[embedded image/binary payload omitted:")
            else clean(item, counts)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [clean(item, counts) for item in value]
    if not isinstance(value, str):
        return value
    result = DATA_URI.sub(lambda match: marker(len(match.group()), counts), value)
    result = RAW_IMAGE.sub(lambda match: marker(len(match.group()), counts), result)
    if result.lstrip().startswith(("{", "[")) and IMAGE_OBJECT.search(result):
        try:
            encoded = json.loads(result)
        except json.JSONDecodeError:
            return result
        nested_counts = Counter()
        encoded = clean(encoded, nested_counts)
        if nested_counts["payloads"]:
            counts.update(nested_counts)
            return json.dumps(encoded, ensure_ascii=False, separators=(",", ":"))
    return result


def identity(path):
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode):
        raise RuntimeError(f"Not a regular file: {path}")
    return {
        "bytes": info.st_size,
        "allocated_bytes": getattr(info, "st_blocks", 0) * 512,
        "mtime_ns": info.st_mtime_ns,
        "ctime_ns": info.st_ctime_ns,
        "device": info.st_dev,
        "inode": info.st_ino,
    }


def check_source(path, expected):
    actual = identity(path)
    for key in ("bytes", "mtime_ns", "ctime_ns", "device", "inode"):
        if actual[key] != expected[key]:
            raise RuntimeError(f"File changed ({key}): {path}")


def write_json(path, value):
    temporary = path.with_name(path.name + ".partial")
    with temporary.open("x", encoding="utf-8") as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    temporary.replace(path)


def text_content(content):
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n\n".join(filter(None, (text_content(part) for part in content)))
    if isinstance(content, dict):
        if isinstance(content.get("text"), str):
            return content["text"]
        if content.get("type") in {"input_image", "output_image", "image"}:
            return "[Embedded image omitted]"
        if "output" in content:
            return text_content(content["output"])
    return ""


def markdown_record(record):
    if record.get("type") != "response_item":
        return ""
    payload = record.get("payload", {})
    kind = payload.get("type")
    timestamp = record.get("timestamp", "")
    if kind in {"message", "agent_message"}:
        text = text_content(payload.get("content", []))
        speaker = payload.get("role") or payload.get("author") or "assistant"
        if not text:
            return ""
        return f"\n## {speaker.title()} · {timestamp}\n\n{text}\n"
    if kind in {"function_call", "custom_tool_call"}:
        label = "Tool call: " + payload.get("name", "unknown")
        text = payload.get("arguments", payload.get("input", ""))
    elif kind in {"function_call_output", "custom_tool_call_output"}:
        label = "Tool result"
        text = text_content(payload.get("output", ""))
    else:
        return ""
    if not isinstance(text, str):
        text = json.dumps(text, ensure_ascii=False)
    fence = "`" * max(
        3, max((len(run) + 1 for run in re.findall(r"`+", text)), default=3)
    )
    return f"\n## {label} · {timestamp}\n\n{fence}\n{text}\n{fence}\n"


def export_one(source, output, markdown, expected):
    check_source(source, expected)
    output.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    markdown.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary = output.with_name(output.name + ".partial")
    markdown_temporary = markdown.with_name(markdown.name + ".partial")
    source_hash, backup_hash, markdown_hash = (
        hashlib.sha256(),
        hashlib.sha256(),
        hashlib.sha256(),
    )
    counts = Counter()
    records = 0
    workspace = ""
    with (
        source.open("rb") as original,
        temporary.open("xb") as backup,
        markdown_temporary.open("xb") as readable,
    ):
        heading = (
            f"# Session transcript\n\nSource: `{source.name}`\n\n"
            "Embedded images and binary media are omitted. This file contains conversation messages and tool activity. "
            "The accompanying JSONL preserves the complete record sequence, including context checkpoints and internal events.\n"
        ).encode()
        readable.write(heading)
        markdown_hash.update(heading)
        for line in original:
            source_hash.update(line)
            record = json.loads(line)
            if not isinstance(record, dict):
                raise ValueError("Each session record must be a JSON object")
            record = clean(record, counts)
            encoded = (
                json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n"
            ).encode()
            backup.write(encoded)
            backup_hash.update(encoded)
            rendered = markdown_record(record).encode()
            readable.write(rendered)
            markdown_hash.update(rendered)
            if record.get("type") == "session_meta":
                workspace = record.get("payload", {}).get("cwd", "")
            records += 1
        for handle in (backup, readable):
            handle.flush()
            os.fsync(handle.fileno())
    check_source(source, expected)
    if not records:
        raise RuntimeError(f"Empty source: {source}")
    temporary.replace(output)
    markdown_temporary.replace(markdown)
    return {
        "records": records,
        "source_sha256": source_hash.hexdigest(),
        "backup_sha256": backup_hash.hexdigest(),
        "markdown_sha256": markdown_hash.hexdigest(),
        "omitted_payloads": counts["payloads"],
        "omitted_characters": counts["characters"],
        "backup_bytes": output.stat().st_size,
        "markdown_bytes": markdown.stat().st_size,
        "workspace": workspace,
    }


def verify_one(source, output, markdown, expected, report):
    check_source(source, expected)
    source_hash, backup_hash = hashlib.sha256(), hashlib.sha256()
    records = 0
    with source.open("rb") as original, output.open("rb") as backup:
        for line, saved in itertools.zip_longest(original, backup):
            if line is None or saved is None:
                raise RuntimeError(f"Record count mismatch: {output}")
            source_hash.update(line)
            backup_hash.update(saved)
            expected_record = clean(json.loads(line), Counter())
            actual_record = json.loads(saved)
            if actual_record != expected_record:
                raise RuntimeError(
                    f"Transcript content mismatch at record {records + 1}: {output}"
                )
            residual = Counter()
            clean(actual_record, residual)
            if residual["payloads"]:
                raise RuntimeError(f"Embedded media remains: {output}")
            records += 1
    if records != report["records"] or not records:
        raise RuntimeError(f"Invalid record count: {output}")
    if (
        source_hash.hexdigest() != report["source_sha256"]
        or backup_hash.hexdigest() != report["backup_sha256"]
    ):
        raise RuntimeError(f"Checksum mismatch: {output}")
    markdown_hash = hashlib.sha256()
    with markdown.open("rb") as readable:
        for block in iter(lambda: readable.read(1024 * 1024), b""):
            markdown_hash.update(block)
    if markdown_hash.hexdigest() != report["markdown_sha256"]:
        raise RuntimeError(f"Markdown checksum mismatch: {markdown}")
    check_source(source, expected)
    return {
        "backup_identity": identity(output),
        "markdown_identity": identity(markdown),
    }


def safe_path(root, relative):
    relative = Path(relative)
    if relative.is_absolute() or ".." in relative.parts or relative.suffix != ".jsonl":
        raise ValueError("Unsafe session path")
    path = root
    for part in relative.parts:
        path = path / part
        if path.is_symlink():
            raise ValueError("Session paths must not contain symlinks")
    return path


def walk_error(error):
    raise error


def export_directory(source, destination, before=None):
    source, destination = Path(source), Path(destination)
    if source.is_symlink() or not source.is_dir():
        raise ValueError("Source must be a real directory")
    source = source.resolve()
    if destination.resolve().is_relative_to(source):
        raise ValueError("Destination must be outside the source directory")
    if destination.exists() or destination.is_symlink():
        raise FileExistsError(destination)
    selected = []
    for directory, dirs, files in os.walk(source, onerror=walk_error):
        dirs[:] = sorted(d for d in dirs if not (Path(directory) / d).is_symlink())
        for name in sorted(files):
            if not name.endswith(".jsonl"):
                continue
            path = safe_path(source, (Path(directory) / name).relative_to(source))
            entry = identity(path)
            if before is None or entry["mtime_ns"] / 1e9 < before:
                selected.append(
                    {"relative_path": str(path.relative_to(source)), **entry}
                )
    if not selected:
        raise ValueError("No sessions match the selection")
    destination.mkdir(mode=0o700)
    reports = []
    for entry in selected:
        relative = Path(entry["relative_path"])
        report = export_one(
            source / relative,
            destination / "jsonl" / relative,
            destination / "markdown" / relative.with_suffix(".md"),
            entry,
        )
        reports.append({**entry, **report})
    manifest = {
        "version": 1,
        "source": str(source),
        "before_timestamp": before,
        "files": reports,
    }
    write_json(destination / "backup_manifest.json", manifest)
    (destination / "README.md").write_text(
        "# Session archive\n\n"
        "`jsonl/` retains record order, text, and metadata with recognized embedded media replaced by omission markers. "
        "`markdown/` contains readable messages and tool activity. "
        "`backup_manifest.json` records source identities, checksums, and omission counts.\n\n"
        "Images are omitted. This archive does not guarantee session resumability.\n",
        encoding="utf-8",
    )
    return {
        "files": len(reports),
        "records": sum(row["records"] for row in reports),
        "omitted_characters": sum(row["omitted_characters"] for row in reports),
    }


def verify_directory(source, destination):
    source, destination = Path(source), Path(destination)
    if source.is_symlink() or destination.is_symlink():
        raise ValueError("Source and destination must be real directories")
    manifest_path = destination / "backup_manifest.json"
    if manifest_path.is_symlink():
        raise ValueError("Manifest must not be a symlink")
    manifest, manifest_digest = load_json_digest(manifest_path, fields={'version', 'source', 'files'})
    if manifest.get("version") != 1 or Path(manifest["source"]) != source.resolve():
        raise ValueError("Manifest source or version differs")
    entries = manifest["files"]
    if not entries or len({entry["relative_path"] for entry in entries}) != len(
        entries
    ):
        raise ValueError("Empty or duplicate manifest entries")
    for entry in entries:
        relative = entry["relative_path"]
        original = safe_path(source, relative)
        backup = safe_path(destination / "jsonl", relative)
        readable = backup.relative_to(destination / "jsonl").with_suffix(".md")
        markdown = destination / "markdown" / readable
        for path in [
            destination / "jsonl",
            destination / "markdown",
            *markdown.parents,
        ]:
            if path.is_relative_to(destination) and path.is_symlink():
                raise ValueError("Archive paths must not contain symlinks")
        if markdown.is_symlink():
            raise ValueError("Markdown must not be a symlink")
        verify_one(original, backup, markdown, entry, entry)
    result = {
        "files": len(entries),
        "records": sum(row["records"] for row in entries),
        "complete": True,
    }
    result["manifest_sha256"] = manifest_digest
    result["verified_at"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
    return result


def main():
    os.umask(0o077)
    parser = argparse.ArgumentParser(
        description="Export and verify image-free session archives."
    )
    parser.add_argument("stage", choices=["export", "verify"])
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--destination", required=True, type=Path)
    parser.add_argument(
        "--before", help="Exclusive modification-time cutoff, ISO 8601 with a timezone"
    )
    args = parser.parse_args()
    before = None
    if args.before:
        stamp = datetime.datetime.fromisoformat(args.before)
        if stamp.tzinfo is None:
            parser.error("--before requires a timezone")
        if args.stage != "export":
            parser.error("--before applies to export only")
        before = stamp.timestamp()
    try:
        result = (
            export_directory(args.source, args.destination, before)
            if args.stage == "export"
            else verify_directory(args.source, args.destination)
        )
    except (OSError, ValueError, RuntimeError) as error:
        parser.exit(1, f"{error}\n")
    print(json.dumps(result))


if __name__ == "__main__":
    main()
