"""Estimate shared 2D stabilization for the assembled 192-frame 1080p shot."""

import argparse
import json
from pathlib import Path

import cv2
import numpy as np


ROOT = Path(__file__).resolve().parents[1]
COUNT = 192
CENTER = np.array([480., 270.])


def gray(frame):
    small = cv2.resize(frame, (960, 540), interpolation=cv2.INTER_AREA)
    return cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)


def estimate_step(previous, current, mask, frame):
    points = cv2.goodFeaturesToTrack(previous, 750, .011, 13, mask=mask)
    error = f"Insufficient stable background tracks at frame {frame}"
    if points is None or len(points) < 12:
        raise ValueError(error)
    options = dict(winSize=(21, 21), maxLevel=3)
    moved, ok, _ = cv2.calcOpticalFlowPyrLK(previous, current, points, None, **options)
    back, ok_back, _ = cv2.calcOpticalFlowPyrLK(current, previous, moved, None, **options)
    good = ok.ravel().astype(bool) & ok_back.ravel().astype(bool)
    good &= np.linalg.norm((back - points)[:, 0], axis=1) < .50
    if good.sum() < 12:
        raise ValueError(error)
    src, dst = points[good, 0] - CENTER, moved[good, 0] - CENTER
    affine, inliers = cv2.estimateAffinePartial2D(src, dst, method=cv2.RANSAC,
                                                  ransacReprojThreshold=1.25,
                                                  maxIters=3000, refineIters=15)
    if affine is None or inliers is None or inliers.sum() < 12:
        raise ValueError(error)
    theta = np.arctan2(affine[1, 0], affine[0, 0])
    c, s = np.cos(theta), np.sin(theta)
    rotation = np.array([[c, -s], [s, c]])
    step = np.eye(3)
    step[:2, :2] = rotation
    step[:2, 2] = 2 * np.median((dst - src @ rotation.T)[inliers.ravel() > 0], axis=0)
    return step, int(inliers.sum())


def measure(plate, exclude_subject):
    capture = cv2.VideoCapture(str(plate))
    try:
        ok, image = capture.read()
        if not ok or image.shape[:2] != (1080, 1920):
            raise ValueError(f"Expected a decodable 1920x1080 plate: {plate}")
        if abs(capture.get(cv2.CAP_PROP_FPS) - 24000 / 1001) > .001:
            raise ValueError("Expected plate clock 24000/1001 fps")
        previous = gray(image)
        mask = np.full(previous.shape, 255, np.uint8)
        if exclude_subject:
            mask[167:535, 345:562] = 0
        transforms, counts = [np.eye(3)], []
        for frame in range(1, COUNT):
            ok, image = capture.read()
            if not ok:
                raise ValueError(f"Missing plate frame {frame}")
            current = gray(image)
            step, inliers = estimate_step(previous, current, mask, frame)
            transforms.append(step @ transforms[-1])
            counts.append(inliers)
            previous = current
        if capture.grab():
            raise ValueError("Expected a trimmed plate of exactly 192 frames")
    finally:
        capture.release()
    return np.asarray(transforms), min(counts)


def smooth(transforms):
    angle = np.unwrap(np.arctan2(transforms[:, 1, 0], transforms[:, 0, 0]))
    path = np.column_stack([transforms[:, :2, 2], angle])
    radius = 13
    offsets = np.arange(-radius, radius + 1)
    # Extend the ends at their local velocity to avoid easing the pan to a stop.
    before = path[0] + offsets[:radius, None] * np.median(np.diff(path[:6], axis=0), axis=0)
    after = path[-1] + offsets[radius + 1:, None] * np.median(np.diff(path[-6:], axis=0), axis=0)
    extended = np.vstack([before, path, after])
    weights = np.exp(-.5 * (offsets / 4.2) ** 2)
    weights /= weights.sum()
    corners = np.array([[-960, -540], [960, -540], [960, 540], [-960, 540]])
    rows, crop = [], 1.
    for i, original in enumerate(transforms):
        tx, ty, theta = weights @ extended[i:i + len(weights)]
        c, s = np.cos(theta), np.sin(theta)
        target = np.array([[c, -s, tx], [s, c, ty], [0, 0, 1]])
        change = target @ np.linalg.inv(original)
        pixels = (corners - change[:2, 2]) @ change[:2, :2]
        crop = max(crop, np.abs(pixels / [960, 540]).max())
        rows.append(dict(x=change[0, 2], y=change[1, 2],
                         deg=np.rad2deg(np.arctan2(change[1, 0], change[0, 0]))))
    return dict(rows=rows, crop=crop + .008)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plate", type=Path, default=ROOT / "Footage/Forest_08s.mov")
    parser.add_argument("--out", type=Path, default=ROOT / "scene/stabilize.json")
    parser.add_argument("--exclude-original-subject", action="store_true",
                        help="Mask the original shot's center/lower foreground during background tracking")
    args = parser.parse_args()
    cv2.setNumThreads(4)
    transforms, minimum = measure(args.plate, args.exclude_original_subject)
    result = smooth(transforms)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, separators=(",", ":"), allow_nan=False) + "\n", encoding="utf-8")
    print(f"Stabilized {len(result['rows'])} frames; min inliers {minimum}; scale {result['crop']:.6f}")
