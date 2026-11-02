import collections
from decimal import Decimal
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import stat
import argparse
import tarfile
import tempfile


def walk_error(error):
    raise error


def inventory(root):
    root = Path(root)
    if root.is_symlink() or not root.is_dir():
        raise ValueError("Source must be a real directory")
    result = {}
    paths = [root]
    for directory, dirs, files in os.walk(root, followlinks=False, onerror=walk_error):
        paths.extend(Path(directory) / name for name in dirs + files)
    for path in paths:
        info = path.lstat()
        kind = (
            "file"
            if stat.S_ISREG(info.st_mode)
            else "directory"
            if stat.S_ISDIR(info.st_mode)
            else "symlink"
            if stat.S_ISLNK(info.st_mode)
            else "special"
        )
        key = str(PurePosixPath(root.name) / path.relative_to(root).as_posix())
        result[key] = dict(
            kind=kind,
            mode=stat.S_IMODE(info.st_mode),
            size=info.st_size,
            mtime_ns=info.st_mtime_ns,
            ctime_ns=info.st_ctime_ns,
            uid=info.st_uid,
            gid=info.st_gid,
            inode=info.st_ino,
            device=info.st_dev,
            nlink=info.st_nlink,
        )
        if kind == "symlink":
            result[key]["target"] = os.readlink(path)
    return result


def digest_stream(stream):
    return hashlib.file_digest(stream, "sha256").hexdigest()


def digest_source(path, expected):
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(descriptor, "rb") as stream:
        info = os.fstat(stream.fileno())
        if (
            info.st_ino,
            info.st_dev,
            info.st_size,
            info.st_mtime_ns,
            info.st_ctime_ns,
        ) != (
            expected["inode"],
            expected["device"],
            expected["size"],
            expected["mtime_ns"],
            expected["ctime_ns"],
        ):
            raise RuntimeError(f"Source changed while hashing: {path}")
        digest = digest_stream(stream)
        after = os.fstat(stream.fileno())
        if (after.st_size, after.st_mtime_ns, after.st_ctime_ns) != (
            info.st_size,
            info.st_mtime_ns,
            info.st_ctime_ns,
        ):
            raise RuntimeError(f"Source changed while hashing: {path}")
        return digest


def validate_archive(archive, root, expected, manifest):
    root = Path(root)
    seen = set()
    hashes = {}
    source_hashes = {}
    errors = collections.Counter()
    examples = []
    counts = collections.Counter()
    total_bytes = 0

    def fail(category, path):
        errors[category] += 1
        if sum(errors.values()) >= 32:
            raise ValueError(json.dumps({"failures": dict(errors), "examples": examples}))
        if len(examples) < 20:
            examples.append({"kind": category, "path": path})

    for member in archive:
        name = member.name.rstrip("/")
        parts = PurePosixPath(name)
        if parts.is_absolute() or ".." in parts.parts or parts.as_posix() != name:
            fail("unsafe path", name)
            continue
        if name in seen:
            fail("duplicate path", name)
        seen.add(name)
        entry = expected.get(name)
        if entry is None:
            fail("unexpected path", name)
            continue
        kind = (
            "file"
            if member.isfile() or member.islnk()
            else "directory"
            if member.isdir()
            else "symlink"
            if member.issym()
            else "special"
        )
        if kind != entry["kind"]:
            fail("entry type", name)
            continue
        mtime_ns = int(
            Decimal(member.pax_headers.get("mtime", str(member.mtime))) * 10**9
        )
        if (member.mode, member.uid, member.gid, mtime_ns) != (
            entry["mode"],
            entry["uid"],
            entry["gid"],
            entry["mtime_ns"],
        ):
            fail("metadata", name)
        record = dict(path=name, kind=kind)
        if kind == "file":
            counts["regular_files"] += 1
            total_bytes += entry["size"]
            source_path = root.parent / name
            if not member.islnk() and member.size != entry['size']:
                fail('file size', name)
                raise ValueError(json.dumps({'failures': dict(errors), 'examples': examples}))
            identity = tuple(entry[key] for key in ('device', 'inode', 'size', 'mtime_ns', 'ctime_ns'))
            if identity in source_hashes:
                descriptor = os.open(source_path, os.O_RDONLY | os.O_NOFOLLOW)
                try:
                    current = os.fstat(descriptor)
                    actual = (current.st_dev, current.st_ino, current.st_size, current.st_mtime_ns, current.st_ctime_ns)
                    if actual != identity:
                        raise RuntimeError(f'Source changed while hashing: {source_path}')
                finally:
                    os.close(descriptor)
                source_hash = source_hashes[identity]
            else:
                source_hash = digest_source(source_path, entry)
                source_hashes[identity] = source_hash
            if member.islnk():
                archive_hash = hashes.get(member.linkname)
                target = expected.get(member.linkname, {})
                if (target.get("inode"), target.get("device")) != (
                    entry["inode"],
                    entry["device"],
                ):
                    fail("hardlink relationship", name)
            else:
                if member.size != entry["size"]:
                    fail("file size", name)
                with archive.extractfile(member) as stream:
                    archive_hash = digest_stream(stream)
            if archive_hash != source_hash:
                fail("file content SHA-256", name)
            hashes[name] = archive_hash
            record.update(
                size=entry["size"],
                archive_sha256=archive_hash,
                source_sha256=source_hash,
            )
        elif kind == "symlink":
            counts["symlinks"] += 1
            record["target"] = member.linkname
            if member.linkname != entry["target"]:
                fail("symlink target", name)
        elif kind == "directory":
            counts["directories"] += 1
        else:
            fail("unsupported special entry", name)
        manifest.write(json.dumps(record, sort_keys=True) + "\n")
    missing = expected.keys() - seen
    for name in sorted(missing):
        fail("missing path", name)
    if errors:
        raise ValueError(json.dumps({"failures": dict(errors), "examples": examples}))
    return dict(
        counts,
        archive_entries=len(seen),
        source_entries=len(expected),
        logical_file_bytes=total_bytes,
        missing_paths=0,
        unexpected_paths=0,
        duplicate_paths=0,
        content_mismatches=0,
        metadata_mismatches=0,
    )


def verify(source, archive_path, manifest=None):
    source, archive_path = Path(source), Path(archive_path)
    if source.is_symlink() or not source.is_dir():
        raise ValueError("Source must be a real directory")
    if archive_path.resolve().is_relative_to(source.resolve()):
        raise ValueError("Archive must be outside the source directory")
    if manifest is not None and Path(manifest).resolve().is_relative_to(
        source.resolve()
    ):
        raise ValueError("Manifest must be outside the source directory")
    expected = inventory(source)
    with tempfile.TemporaryFile(mode="w+", encoding="utf-8") as records:
        with tarfile.open(archive_path, mode="r|*") as archive:
            result = validate_archive(archive, source, expected, records)
        if inventory(source) != expected:
            raise RuntimeError("Source changed during verification")
        if manifest is not None:
            records.seek(0)
            with Path(manifest).open("x", encoding="utf-8") as output:
                for line in records:
                    output.write(line)
    return result


def main():
    os.umask(0o077)
    parser = argparse.ArgumentParser(
        description="Verify a tar archive against a source directory without extraction."
    )
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument(
        "--manifest",
        type=Path,
        help="Write a new JSONL file after successful verification",
    )
    args = parser.parse_args()
    try:
        result = verify(args.source, args.archive, args.manifest)
    except (OSError, ValueError, RuntimeError, tarfile.TarError) as error:
        parser.exit(1, f"{error}\n")
    print(json.dumps(result))


if __name__ == "__main__":
    main()
