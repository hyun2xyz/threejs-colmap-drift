"""Export a contiguous, fixed-intrinsics COLMAP text reconstruction to Three.js."""

import argparse
from fractions import Fraction
import json
import math
from pathlib import Path
import re


def matrix_world(pose):
    # COLMAP uses a Hamilton quaternion for world -> optical camera.
    w, x, y, z, tx, ty, tz = pose
    norm = math.hypot(w, x, y, z)
    if norm == 0 or not all(map(math.isfinite, pose)):
        raise ValueError("Invalid camera pose")
    w, x, y, z = (v / norm for v in (w, x, y, z))
    rows = [
        [1 - 2 * (y*y + z*z), 2 * (x*y - w*z), 2 * (x*z + w*y)],
        [2 * (x*y + w*z), 1 - 2 * (x*x + z*z), 2 * (y*z - w*x)],
        [2 * (x*z - w*y), 2 * (y*z + w*x), 1 - 2 * (x*x + y*y)],
    ]
    # Columns of R.T are rows of R. Three camera local Y and Z are reversed.
    center = [-sum(row[i] * t for row, t in zip(rows, (tx, ty, tz))) for i in range(3)]
    return [*rows[0], 0, *[-v for v in rows[1]], 0, *[-v for v in rows[2]], 0, *center, 1]


def read_images(path):
    poses = {}
    with path.open(encoding="utf-8") as lines:
        for line in lines:
            if not line.strip() or line.lstrip().startswith("#"):
                continue
            fields = line.strip().split(maxsplit=9)
            if len(fields) != 10:
                raise ValueError("Malformed image header in images.txt")
            # The observation line may be empty. Always consume exactly one.
            if next(lines, None) is None:
                raise ValueError("Missing observation line in images.txt")
            match = re.search(r"(\d+)$", Path(fields[-1]).stem)
            if not match:
                raise ValueError("Use image filenames ending in a frame number")
            number = int(match.group())
            if number in poses:
                raise ValueError(f"Duplicate filename frame number {number}")
            poses[number] = (int(fields[8]), matrix_world(list(map(float, fields[1:8]))))
    if not poses:
        raise ValueError("No registered frames")
    return poses


def read_intrinsics(path, camera_id):
    with path.open(encoding="utf-8") as lines:
        for line in lines:
            fields = line.split()
            if not fields or fields[0].startswith("#") or int(fields[0]) != camera_id:
                continue
            model = fields[1]
            width, height = map(int, fields[2:4])
            params = list(map(float, fields[4:]))
            if model == "SIMPLE_PINHOLE":
                fx, cx, cy = params
                fy = fx
            elif model == "PINHOLE":
                fx, fy, cx, cy = params
            else:
                raise ValueError(f"{model} has distortion. Export the model and plate from image_undistorter.")
            if min(width, height, fx, fy) <= 0 or not all(map(math.isfinite, params)):
                raise ValueError("Invalid camera intrinsics")
            return dict(model=model, width=width, height=height, fx=fx, fy=fy, cx=cx, cy=cy)
    raise ValueError(f"Missing camera ID {camera_id}")


def export(model, fps, first=None, last=None):
    if fps <= 0:
        raise ValueError("FPS must be positive")
    poses = read_images(model / "images.txt")
    first = min(poses) if first is None else first
    last = max(poses) if last is None else last
    if first > last:
        raise ValueError("Frame range is empty")
    frames = []
    camera_id = None
    for number in range(first, last + 1):
        if number not in poses:
            raise ValueError(f"Missing registered frame {number}. Solve the gap or select a contiguous range.")
        current_id, matrix = poses[number]
        if camera_id is not None and current_id != camera_id:
            raise ValueError("Selected frames must share one calibrated camera")
        camera_id = current_id
        frames.append(dict(frame=len(frames), sourceFrame=number, status="COLMAP", matrixWorld=matrix))
    return dict(**read_intrinsics(model / "cameras.txt", camera_id),
                fps=[fps.numerator, fps.denominator], count=len(frames), sourceStartFrame=first,
                sourceEndFrameInclusive=last, distortion="pinhole", frames=frames,
                world="Original COLMAP world, arbitrary origin, up and scale. Three.js camera looks down -Z. Column-major matrixWorld.")


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("model", type=Path, help="Folder containing cameras.txt and images.txt")
    p.add_argument("output", type=Path, help="New JSON file; parent directory must exist")
    p.add_argument("--fps", type=Fraction, required=True, help="Plate frame rate, e.g. 24000/1001")
    p.add_argument("--first", type=int, help="First filename frame number (inclusive)")
    p.add_argument("--last", type=int, help="Last filename frame number (inclusive)")
    args = p.parse_args()
    try:
        result = export(args.model, args.fps, args.first, args.last)
        payload = json.dumps(result, separators=(",", ":"), allow_nan=False) + "\n"
        with args.output.open("x", encoding="utf-8") as f:
            f.write(payload)
    except (OSError, ValueError) as exc:
        p.exit(1, f"Export failed: {exc}\n")
    print(f"Wrote {result['count']} poses to {args.output}")


if __name__ == "__main__":
    main()
