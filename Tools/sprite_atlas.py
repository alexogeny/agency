import argparse
import hashlib
import heapq
import json
from pathlib import Path
import re

MAX_PIXELS = 16_777_216


def components(alpha, width, height, threshold):
    if (
        width < 1
        or height < 1
        or width * height != len(alpha)
        or width * height > MAX_PIXELS
    ):
        raise ValueError(
            "Alpha dimensions must match and contain at most 16777216 pixels"
        )
    if not 0 <= threshold <= 255:
        raise ValueError("Alpha threshold must be between 0 and 255")
    mask = bytearray(value > threshold for value in alpha)
    parts = []
    for index in range(width * height):
        if not mask[index]:
            continue
        mask[index] = 0
        pending, pixels = [index], []
        x1, y1, x2, y2 = width, height, 0, 0
        while pending:
            pixel = pending.pop()
            pixels.append(pixel)
            x, y = pixel % width, pixel // width
            x1, y1, x2, y2 = min(x1, x), min(y1, y), max(x2, x + 1), max(y2, y + 1)
            for ny in range(max(0, y - 1), min(height, y + 2)):
                for nx in range(max(0, x - 1), min(width, x + 2)):
                    neighbor = ny * width + nx
                    if mask[neighbor]:
                        mask[neighbor] = 0
                        pending.append(neighbor)
        parts.append({"bbox": [x1, y1, x2, y2], "area": len(pixels), "pixels": pixels})
    return parts


def arrange(parts, count, columns, satellite_distance):
    if count < 1 or not 1 <= columns <= count or count > 4096 or satellite_distance < 0:
        raise ValueError(
            "Require 1–4096 names, 1–count columns, and a nonnegative satellite distance"
        )
    ranked = sorted(
        parts, key=lambda part: (-part["area"], part["bbox"][1], part["bbox"][0])
    )
    if len(ranked) < count:
        raise ValueError(f"Found {len(ranked)} components for {count} names")
    main = sorted(
        ranked[:count],
        key=lambda part: (part["bbox"][1] + part["bbox"][3], part["bbox"][0]),
    )
    ordered = []
    for start in range(0, count, columns):
        ordered.extend(
            sorted(
                main[start : start + columns],
                key=lambda part: part["bbox"][0] + part["bbox"][2],
            )
        )
    result = [
        {**part, "bbox": list(part["bbox"]), "pixels": list(part["pixels"])}
        for part in ordered
    ]
    def bounds(indices):
        boxes = [ordered[index]['bbox'] for index in indices]
        return [min(box[0] for box in boxes), min(box[1] for box in boxes),
                max(box[2] for box in boxes), max(box[3] for box in boxes)]

    def tree(indices):
        box = bounds(indices)
        if len(indices) == 1:
            return box, indices[0], None, None
        axis = 0 if box[2] - box[0] >= box[3] - box[1] else 1
        indices.sort(key=lambda index: ordered[index]['bbox'][axis] + ordered[index]['bbox'][axis + 2])
        middle = len(indices) // 2
        return box, None, tree(indices[:middle]), tree(indices[middle:])

    spatial = tree(list(range(count))) if satellite_distance else None
    for fragment in ranked[count:]:
        if satellite_distance == 0:
            continue
        cx = (fragment["bbox"][0] + fragment["bbox"][2]) / 2
        cy = (fragment["bbox"][1] + fragment["bbox"][3]) / 2

        def distance(part):
            x1, y1, x2, y2 = part["bbox"]
            return max(x1 - cx, 0, cx - x2) ** 2 + max(y1 - cy, 0, cy - y2) ** 2

        def lower_bound(box):
            x1, y1, x2, y2 = box
            return max(x1 - cx, 0, cx - x2) ** 2 + max(y1 - cy, 0, cy - y2) ** 2

        nearest, best = None, satellite_distance ** 2
        queue = [(lower_bound(spatial[0]), 0, spatial)]
        serial = 0
        while queue:
            bound, _, node = heapq.heappop(queue)
            if bound > best:
                break
            if node[1] is not None:
                index = node[1]
                value = distance(ordered[index])
                if value <= best and (value < best or nearest is None or index < nearest):
                    nearest, best = index, value
            else:
                for child in node[2:]:
                    value = lower_bound(child[0])
                    if value <= best:
                        serial += 1
                        heapq.heappush(queue, (value, serial, child))
        if nearest is not None:
            target = result[nearest]
            target["pixels"].extend(fragment["pixels"])
            a, b = target["bbox"], fragment["bbox"]
            target["bbox"] = [
                min(a[0], b[0]),
                min(a[1], b[1]),
                max(a[2], b[2]),
                max(a[3], b[3]),
            ]
            target["area"] += fragment["area"]
    for part in result:
        part["pixels"].sort()
    return result


def validate_names(names):
    if not names or len({name.casefold() for name in names}) != len(names):
        raise ValueError("Names must be nonempty and unique ignoring case")
    for name in names:
        if not re.fullmatch(
            r"[A-Za-z0-9][A-Za-z0-9_-]{0,127}", name
        ) or name.casefold() in {"manifest", "contact"}:
            raise ValueError(f"Unsafe or reserved sprite name: {name!r}")


def extract(
    source, destination, names, columns, threshold=16, satellite_distance=0, padding=6
):
    from PIL import Image

    validate_names(names)
    if padding < 0 or padding > 1024:
        raise ValueError("Padding must be between 0 and 1024")
    source, destination = Path(source), Path(destination)
    if destination.exists() or destination.is_symlink():
        raise FileExistsError(destination)
    with source.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
        stream.seek(0)
        with Image.open(stream) as original:
            if original.width * original.height > MAX_PIXELS:
                raise ValueError("Image exceeds 16777216 pixels")
            image = original.convert("RGBA")
    width, height = image.size
    parts = components(image.getchannel("A").tobytes(), width, height, threshold)
    ordered = arrange(parts, len(names), columns, satellite_distance)
    output_pixels = sum((part['bbox'][2] - part['bbox'][0] + 2 * padding)
                        * (part['bbox'][3] - part['bbox'][1] + 2 * padding) for part in ordered)
    if output_pixels > MAX_PIXELS:
        raise ValueError('Aggregate sprite output exceeds 16777216 pixel budget')
    destination.mkdir()
    entries = []
    src = image.load()
    for name, part in zip(names, ordered, strict=True):
        x1, y1, x2, y2 = part["bbox"]
        crop = Image.new("RGBA", (x2 - x1 + 2 * padding, y2 - y1 + 2 * padding))
        dst = crop.load()
        for pixel in part["pixels"]:
            x, y = pixel % width, pixel // width
            dst[x - x1 + padding, y - y1 + padding] = src[x, y]
        filename = name + ".png"
        crop.save(destination / filename)
        entries.append(
            {
                "id": name,
                "file": filename,
                "source_bbox": part["bbox"],
                "output_size": list(crop.size),
                "assigned_pixels": part["area"],
            }
        )
    manifest = {
        "source": source.name,
        "source_sha256": digest,
        "source_size": [width, height],
        "alpha_threshold": threshold,
        "columns": columns,
        "padding": padding,
        "satellite_distance": satellite_distance,
        "component_count": len(parts),
        "unassigned_pixels": sum(part["area"] for part in parts)
        - sum(part["area"] for part in ordered),
        "crops": entries,
    }
    (destination / "manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
    )
    return manifest


def main():
    parser = argparse.ArgumentParser(
        description="Extract connected sprites from an alpha atlas."
    )
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument(
        "--destination", type=Path, required=True, help="New output directory"
    )
    parser.add_argument(
        "--names", type=Path, required=True, help="JSON array of names in row order"
    )
    parser.add_argument("--columns", type=int, required=True)
    parser.add_argument("--alpha-threshold", type=int, default=16)
    parser.add_argument(
        "--satellite-distance",
        type=float,
        default=0,
        help="Maximum distance for attaching smaller fragments; 0 leaves them unassigned",
    )
    parser.add_argument("--padding", type=int, default=6)
    args = parser.parse_args()
    try:
        names = json.loads(args.names.read_text())
        if not isinstance(names, list) or not all(
            isinstance(name, str) for name in names
        ):
            raise ValueError("Names must be a JSON array of strings")
        manifest = extract(
            args.source,
            args.destination,
            names,
            args.columns,
            args.alpha_threshold,
            args.satellite_distance,
            args.padding,
        )
    except ImportError:
        parser.exit(
            1, "Pillow is required. Run: uv run --with Pillow Tools/sprite-atlas ...\n"
        )
    except (OSError, ValueError) as error:
        parser.exit(1, f"{error}\n")
    print(
        json.dumps(
            {
                "sprites": len(manifest["crops"]),
                "unassigned_pixels": manifest["unassigned_pixels"],
            }
        )
    )


if __name__ == "__main__":
    main()
