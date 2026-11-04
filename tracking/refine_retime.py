"""Fit native COLMAP/PnP poses to measured slow-motion frames and adjacent flow."""

import argparse
from collections import defaultdict
from fractions import Fraction
import json
from pathlib import Path

import numpy as np
from scipy.sparse import coo_matrix
from scipy.sparse.linalg import spsolve
from scipy.spatial.transform import Rotation, Slerp


def interpolate(native, times):
    indices = np.arange(len(native))
    poses = np.repeat(np.eye(4)[None], len(times), axis=0)
    poses[:, :3, :3] = Slerp(indices, Rotation.from_matrix(native[:, :3, :3]))(times).as_matrix()
    for axis in range(3):
        poses[:, axis, 3] = np.interp(times, indices, native[:, axis, 3])
    return poses


def projection(pose, xyz, k):
    pc = (xyz - pose[:3, 3]) @ pose[:3, :3]
    x, y, z = pc.T
    if np.any(z <= 0):
        raise ValueError("Landmark behind a camera; check the pose initialization")
    x, y = x/z, y/z
    zeros = np.zeros_like(z)
    j = np.stack([-x*y, 1+x*x, -y, 1/z, zeros, -x/z,
                  -1-y*y, x*y, x, zeros, 1/z, -y/z], axis=-1).reshape(-1, 2, 6)
    focal = np.array([k[0, 0], k[1, 1]])
    return np.column_stack([x, y])*focal + k[:2, 2], j*focal[None, :, None]


def fit(poses, frames, landmarks, steps, k):
    # Solve the sparse normal equations for one six-component twist per pose.
    def partition(rows):
        training = rows[rows[:, 1].astype(np.int64) % 5 != 0]
        return [training[training[:, 0] == frame] for frame in frames]

    landmarks, steps = partition(landmarks), partition(steps)
    poses = poses.copy()
    for _ in range(4):
        blocks = defaultdict(lambda: np.zeros((6, 6)))
        rhs = np.zeros((len(frames), 6))

        def accumulate(terms, err, weights):
            for i, ji in terms:
                rhs[i] -= np.einsum("nai,na,n->i", ji, err, weights)
                for j, jj in terms:
                    blocks[i, j] += np.einsum("nai,naj,n->ij", ji, jj, weights)

        for i, obs in enumerate(landmarks):
            if len(obs) < 6:
                raise ValueError(f"Too few landmarks at frame {frames[i]}")
            uv, jac = projection(poses[i], obs[:, 4:7], k)
            err = uv - obs[:, 2:4]
            weight = obs[:, 7] / np.sqrt(1 + np.sum(err**2, axis=1)/.4**2)
            accumulate([(i, jac)], err, weight)
            if i+1 < len(frames):
                step = steps[i]
                if len(step) < 6:
                    raise ValueError(f"Too few flow measurements at frame {frames[i]}")
                uv1, j1 = projection(poses[i], step[:, 8:11], k)
                uv2, j2 = projection(poses[i+1], step[:, 8:11], k)
                err = (uv2-uv1) - (step[:, 6:8]-step[:, 2:4])
                weight = 16 / np.sqrt(1 + np.sum(err**2, axis=1)/.12**2)
                accumulate([(i, -j1), (i+1, j2)], err, weight)

        rr, cc = np.mgrid[0:6, 0:6]
        rows = np.concatenate([(rr+6*i).ravel() for i, j in blocks])
        cols = np.concatenate([(cc+6*j).ravel() for i, j in blocks])
        vals = np.concatenate([v.ravel() for v in blocks.values()])
        shape = (6*len(frames),)*2
        h = coo_matrix((vals, (rows, cols)), shape=shape).tocsr()
        twists = spsolve(h, rhs.ravel()).reshape(-1, 6)
        if not np.isfinite(twists).all():
            raise ValueError("Singular fit; check landmark coverage and depth")
        for i, delta in enumerate(twists):
            inc = np.eye(4)
            inc[:3, :3] = Rotation.from_rotvec(delta[:3]).as_matrix()
            inc[:3, 3] = delta[3:]
            poses[i] = np.linalg.inv(inc @ np.linalg.inv(poses[i]))
    return poses


def align_drift(native, poses, focal):
    # Shot-specific placement, expressed in the original sparse reconstruction.
    ref = native[170]
    depth = 5.5
    origin = ref[:3, 3] + ref[:3, :3] @ np.array([.48, -.077, 1.]) * depth
    toward = ref[:3, 3] - origin
    toward /= np.linalg.norm(toward)
    right = np.cross(-ref[:3, 1], toward)
    right /= np.linalg.norm(right)
    up = np.cross(toward, right)
    basis = np.column_stack([right, up, toward]) @ Rotation.from_euler("x", 12, degrees=True).as_matrix()
    unit = depth*.28*3840/focal/1.8528
    poses[:, :3, :3] = basis.T @ poses[:, :3, :3]
    poses[:, :3, 3] = (poses[:, :3, 3] - origin) @ basis/unit


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("native", type=Path, help="NPZ with native c2w and COLMAP K")
    p.add_argument("observations", type=Path, help="NPZ with obs and step (see README)")
    p.add_argument("output", type=Path)
    p.add_argument("--start", type=int, required=True, help="First retimed frame to deliver, zero-based")
    p.add_argument("--count", type=int, required=True)
    p.add_argument("--pad", type=int, default=8, help="Additional fitted frames on each side")
    p.add_argument("--factor", type=int, default=4, help="Retimed frame intervals per native interval")
    p.add_argument("--fps", type=Fraction, default=Fraction(24000, 1001))
    p.add_argument("--size", type=int, nargs=2, required=True, metavar=("WIDTH", "HEIGHT"),
                   help="Measurement image dimensions before output scaling")
    p.add_argument("--scale", type=int, default=1, help="Isotropic resolution multiplier in output")
    p.add_argument("--drift-layout", action="store_true", help="Use only with the original Drift sparse world")
    args = p.parse_args()
    if min(args.count, args.factor, args.fps, args.scale, *args.size) <= 0 or min(args.pad, args.start) < 0:
        p.error("Invalid timing, dimensions or scale")
    with np.load(args.native) as inputs:
        native, k = inputs["c2w"], inputs["K"].copy()
    begin = args.start - args.pad
    end = args.start + args.count + args.pad
    if begin < 0 or end-1 > (len(native)-1)*args.factor:
        p.error("Padded solve range outside native coverage; reduce --pad")
    if args.output.exists():
        p.error("Output file already exists")
    frames = np.arange(begin, end)
    poses = interpolate(native, frames/args.factor)
    kcv = k.copy()
    kcv[:2, 2] -= .5  # COLMAP pixel corners -> OpenCV centers.
    with np.load(args.observations) as measurements:
        poses = fit(poses, frames, measurements["obs"], measurements["step"], kcv)
    poses = poses[args.pad:args.pad+args.count].copy()
    if args.drift_layout:
        if len(native) <= 170 or list(args.size) != [960, 540] or args.scale != 4:
            p.error("Drift layout requires original 960x540 native cameras and --scale 4")
        align_drift(native, poses, args.scale*k[0, 0])
    poses[:, :3, 1:3] *= -1  # Optical camera -> Three.js local axes.
    rows = [dict(frame=i, sourceFrame=args.start+i, status="retime_image_and_flow_fit",
                 matrixWorld=np.round(pose.T.ravel(), 10).tolist()) for i, pose in enumerate(poses)]
    w, h = args.size
    s = args.scale
    result = dict(width=w*s, height=h*s, fps=[args.fps.numerator, args.fps.denominator],
                  fx=k[0, 0]*s, fy=k[1, 1]*s, cx=k[0, 2]*s, cy=k[1, 2]*s,
                  count=len(rows), sourceStartFrame=args.start, sourceEndFrameInclusive=args.start+len(rows)-1,
                  world="Drift object-centered" if args.drift_layout else "Original COLMAP world",
                  model="PINHOLE", distortion="pinhole", frames=rows)
    payload = json.dumps(result, separators=(",", ":"), allow_nan=False)
    with args.output.open("x", encoding="utf-8") as f:
        f.write(payload + "\n")
    print(f"Wrote {len(rows)} refined poses")


if __name__ == "__main__":
    main()
