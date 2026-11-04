"""Prepare native poses or retime measurements for refine_retime.py."""

import argparse
from functools import lru_cache
import json
from pathlib import Path
import re

import cv2
import numpy as np
import pycolmap


def frame_number(path):
    match = re.search(r"(\d+)$", Path(path).stem)
    if not match:
        raise ValueError("Frame filenames must end in digits")
    return int(match.group())


def flow(src, dst, uv, *, win, iterations, epsilon, tolerance, border):
    uv = np.ascontiguousarray(uv, np.float32).reshape(-1, 2)
    options = dict(winSize=(win, win), maxLevel=3, criteria=(3, iterations, epsilon))
    xy, ok, _ = cv2.calcOpticalFlowPyrLK(src, dst, uv, None, **options)
    back, valid, _ = cv2.calcOpticalFlowPyrLK(dst, src, xy, None, **options)
    keep = (ok.ravel()>0) & (valid.ravel()>0) & (np.linalg.norm(back-uv, axis=1)<tolerance)
    if border:
        h, w = dst.shape
        keep &= (xy[:, 0]>border) & (xy[:, 0]<w-border) & (xy[:, 1]>border) & (xy[:, 1]<h-border)
    return xy, keep


def dense_poses(keys, tracks, points, gray, k):
    poses = dict(keys)
    for left, right in zip(sorted(keys), sorted(keys)[1:]):
        for n in range(left+1, right):
            ends = []
            for key in (left, right):
                ids, uv = tracks[key]
                xy, keep = flow(gray(key), gray(n), uv, win=23, iterations=25,
                                epsilon=.01, tolerance=.6, border=0)
                ends.append(dict(zip(ids[keep], xy[keep])))
            a, b = ends
            ids = [i for i in a if i in b and i % 5 != 0 and np.linalg.norm(a[i]-b[i]) < 1.7]
            if len(ids) < 16:
                raise ValueError(f"Insufficient common landmark support at native frame {n}")
            xy = np.array([(a[i]*(right-n)+b[i]*(n-left))/(right-left) for i in ids], dtype=float)
            xyz = np.array([points[i] for i in ids])
            ok, rot, t, mask = cv2.solvePnPRansac(xyz, xy, k, None, iterationsCount=150,
                reprojectionError=1.8, confidence=.999, flags=cv2.SOLVEPNP_EPNP)
            if not ok or mask is None or len(mask) < 13:
                raise ValueError(f"PnP failed at native frame {n}")
            sel = mask.ravel()
            rot, t = cv2.solvePnPRefineLM(xyz[sel], xy[sel], k, None, rot, t)
            view = np.eye(4)
            view[:3, :3] = cv2.Rodrigues(rot)[0]
            view[:3, 3] = t.ravel()
            poses[n] = np.linalg.inv(view)
    return np.stack([poses[i] for i in range(max(poses)+1)])


def retime_ledger(tracks, points, gray, clip, start, count, factor):
    options = dict(iterations=30, epsilon=.006, border=8)
    obs, step = [], []
    for j in range(start, start+count):
        patches = []
        for key in sorted(tracks, key=lambda i: abs(i-j/factor))[:4]:
            d = abs(key-j/factor)
            if d >= 8:
                continue
            ids, uv = tracks[key]
            xy, keep = flow(gray(key), clip[j], uv, win=21, tolerance=.6, **options)
            patches.append((ids[keep], xy[keep], np.full(keep.sum(), (1-d/8)**2)))
        if not patches:
            raise ValueError(f"No nearby registered frame at retimed frame {j}")
        ids, xy, weight = (np.concatenate(values) for values in zip(*patches))
        unique, idx = np.unique(ids, return_inverse=True)
        weight_sum = np.bincount(idx, weight)
        uv = np.stack([np.bincount(idx, weights=weight*col)/weight_sum for col in xy.T], axis=-1)
        spread = np.sqrt(np.bincount(idx, weights=weight*np.sum((xy-uv[idx])**2, axis=1))/weight_sum)
        keep = (weight_sum>.05) & (spread<.70)
        ids, uv, weight = unique[keep], uv[keep], np.minimum(weight_sum[keep], 1.)
        if len(ids) < 6:
            raise ValueError(f"Insufficient retime observations at frame {j}")
        xyz = np.array([points[i] for i in ids])
        obs.append(np.c_[np.full(len(ids), j), ids, uv, xyz, weight])
        before, a = flow(clip[j], clip[j-1], uv, win=17, tolerance=.35, **options)
        after, b = flow(clip[j], clip[j+1], uv, win=17, tolerance=.35, **options)
        keep = a & b
        step.append(np.c_[np.full(keep.sum(), j), ids[keep], uv[keep], before[keep], after[keep], xyz[keep]])
    return dict(obs=np.vstack(obs), step=np.vstack(step))


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("stage", choices=("native", "observations"))
    p.add_argument("model", type=Path, help="Single-camera pinhole COLMAP reconstruction")
    p.add_argument("frames", type=Path, help="Directory of all native-speed PNG frames, in numeric order")
    p.add_argument("output", type=Path, help="New NPZ file")
    p.add_argument("--key-map", type=Path, help="JSON array mapping model file sequence to zero-based native indices")
    p.add_argument("--exclude", type=float, nargs=4, metavar=("LEFT", "TOP", "RIGHT", "BOTTOM"),
                   help="Static rectangle to reject in registered observations, in COLMAP pixel coordinates")
    p.add_argument("--retime-gray", type=Path, help="Contiguous uint8 gray frames at solve resolution")
    p.add_argument("--start", type=int, help="First retimed frame to measure, including fit padding")
    p.add_argument("--count", type=int, help="Number of frames to measure, including fit padding")
    p.add_argument("--factor", type=int, default=4)
    args = p.parse_args()
    if args.output.exists():
        p.error("Output file already exists")
    cv2.setNumThreads(3)
    cv2.setRNGSeed(919)
    model = pycolmap.Reconstruction(args.model)
    if len(model.cameras) != 1:
        p.error("Expected one shared camera")
    camera = next(iter(model.cameras.values()))
    if camera.model_name not in ("SIMPLE_PINHOLE", "PINHOLE"):
        p.error("Use an undistorted pinhole model and matching plates")
    files = sorted(args.frames.glob("*.png"), key=frame_number)
    if not files:
        p.error("No native PNG frames found")
    file_indices = {frame_number(f): i for i, f in enumerate(files)}
    if len(file_indices) != len(files) or max(file_indices)-min(file_indices)+1 != len(files):
        p.error("Native PNG frame numbers must be contiguous and unique")

    @lru_cache(maxsize=20)
    def gray(i):
        image = cv2.imread(str(files[i]), cv2.IMREAD_GRAYSCALE)
        if image is None or image.shape != (camera.height, camera.width):
            raise ValueError(f"Native frame {i} could not be read at solve resolution")
        return image

    mapping = json.loads(args.key_map.read_text(encoding="utf-8")) if args.key_map else None
    if mapping is not None and (not isinstance(mapping, list) or
            any(type(i) is not int or i < 0 or i >= len(files) for i in mapping)):
        p.error("--key-map must contain valid zero-based native frame indices")
    points = {i: point.xyz for i, point in model.points3D.items()}
    keys, tracks = {}, {}
    for image in model.images.values():
        n = frame_number(image.name)
        if mapping is not None and not 1 <= n <= len(mapping):
            p.error("Registered model frame number outside key map")
        i = mapping[n-1] if mapping is not None else file_indices[n]
        if i in keys:
            p.error("Model maps multiple images to the same native frame")
        view = np.eye(4)
        view[:3] = image.cam_from_world().matrix()
        keys[i] = np.linalg.inv(view)
        ids, xy = [], []
        for point in image.points2D:
            if not point.has_point3D():
                continue
            x, y = point.xy
            if args.exclude:
                x0, y0, x1, y1 = args.exclude
                if x0 < x < x1 and y0 < y < y1:
                    continue
            ids.append(point.point3D_id)
            xy.append([x-.5, y-.5])
        if args.stage == "native":
            # The native PnP tracker uses one pixel per reconstructed landmark.
            observations = dict(zip(ids, xy))
            ids, xy = list(observations), list(observations.values())
        if len(ids) < 6:
            p.error(f"Too few static points on registered frame {i}")
        tracks[i] = np.array(ids, dtype=np.int64), np.array(xy, dtype=np.float32)
    k = camera.calibration_matrix()
    if args.stage == "native":
        if not keys or min(keys) != 0 or max(keys) != len(files)-1:
            p.error("Registered keys must span the first and last native frame")
        kcv = k.copy()
        kcv[:2, 2] -= .5
        data = dict(c2w=dense_poses(keys, tracks, points, gray, kcv), K=k)
    else:
        if None in (args.retime_gray, args.start, args.count) or args.factor < 1:
            p.error("observations needs --retime-gray, --start, --count and a positive --factor")
        frame_bytes = camera.width * camera.height
        length, remainder = divmod(args.retime_gray.stat().st_size, frame_bytes)
        if remainder or args.count < 1 or args.start < 1 or args.start+args.count >= length:
            p.error("Invalid gray frame packing or missing neighbor frames")
        clip = np.memmap(args.retime_gray, dtype="u1", mode="r", shape=(length, camera.height, camera.width))
        data = retime_ledger(tracks, points, gray, clip, args.start, args.count, args.factor)
    with args.output.open("xb") as output:
        np.savez_compressed(output, **data)
    print(f"Wrote {args.stage} data to {args.output}")


if __name__ == "__main__":
    main()
