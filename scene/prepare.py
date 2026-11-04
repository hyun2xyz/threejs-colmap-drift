"""Rebuild the world-space prop motion and native AE camera from the same Three.js poses."""

import argparse
import json
from pathlib import Path

import numpy as np


ROOT = Path(__file__).resolve().parents[1]
WIDTH, HEIGHT = 1920, 1080
FPS = (24000, 1001)
COUNT, REFERENCE = 192, 96
# name, model, reference screen x/y, depth, uniform scale, phase, initial Euler, deg/s
PLACEMENTS = [
    ("01 Close flask", "Flask", .264, .530, 3.65, .98, 0, [-8, 36, -13], [11, 34, 17]),
    ("02 Porcelain in orbit", "Cup", .795, .390, 4.55, 1.18, 1.7, [14, -31, 18], [-11, -24, 12]),
    ("03 Distant flask", "Flask", .680, .275, 7.80, .70, 3.1, [12, 32, 41], [14, -21, -13]),
    ("04 Distant cup", "Cup", .305, .265, 8.70, .87, 4.5, [10, 10, -25], [-12, 22, 11]),
    ("05 Low drifting cup", "Cup", .300, .790, 5.75, .83, 2.6, [20, -20, 15], [10, -19, 10]),
    ("06 Far right flask", "Flask", .920, .710, 9.20, .53, .7, [-10, 29, -34], [-8, 17, -9]),
    ("07 Water", "Water", .695, .625, 4.50, 1.76, 3.3, [0, 0, 0], [7, 14, 7]),
]


def load_camera(path):
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    width, height = data["width"], data["height"]
    if tuple(data["fps"]) != FPS or len(data["frames"]) != COUNT:
        raise ValueError("Expected 192 frames at 24000/1001 fps")
    if width <= 0 or height <= 0 or width * HEIGHT != height * WIDTH:
        raise ValueError("Expected a 16:9 camera with square pixels")
    fx, fy = data["fx"], data["fy"]
    if not (np.isfinite(fx) and fx > 0 and np.isclose(fx, fy) and
            np.isclose(data["cx"], width / 2) and np.isclose(data["cy"], height / 2)):
        raise ValueError("Expected a centered principal point and matching pixel focal lengths")
    frames = data["frames"]
    if any(f.get("frame", i) != i for i, f in enumerate(frames)):
        raise ValueError("Camera frame indices must be contiguous and zero based")
    # Matrix4.toArray/fromArray stores the translation at indices 12, 13, 14.
    mats = np.asarray([f["matrixWorld"] for f in frames], dtype=float).reshape(COUNT, 4, 4).transpose(0, 2, 1)
    basis = mats[:, :3, :3]
    if not (np.isfinite(mats).all() and np.allclose(mats[:, 3], [0, 0, 0, 1]) and
            np.allclose(basis.transpose(0, 2, 1) @ basis, np.eye(3), atol=1e-5) and
            np.allclose(np.linalg.det(basis), 1, atol=1e-5)):
        raise ValueError("Camera matrices must be finite, right-handed rigid transforms")
    return mats, fx * WIDTH / width


def make_layout(mats, focal):
    ref = mats[REFERENCE]
    axis, eye = ref[:3, :3], ref[:3, 3]
    t = np.arange(COUNT) * FPS[1] / FPS[0]
    tracks = []
    for name, kind, x, y, depth, scale, phase, initial, speed in PLACEMENTS:
        ray = [(x - .5) * WIDTH * depth / focal, (.5 - y) * HEIGHT * depth / focal, -depth]
        anchor = eye + axis @ ray
        motion = np.column_stack([.22 * np.sin(.56 * t + phase),
                                  .15 * np.sin(.73 * t + phase * .8),
                                  .20 * np.cos(.52 * t + phase)])
        motion *= .6 if kind == "Water" else 1
        world = anchor + (motion - motion[REFERENCE]) @ axis.T
        angles = initial + np.outer(t - 4, speed) + np.column_stack([
            7 * np.sin(.6 * t + phase), 8 * np.cos(.44 * t + phase), 9 * np.sin(.7 * t + phase)])
        tracks.append(dict(name=name, kind=kind, scale=scale, pos=world.round(7).tolist(),
                           r=angles.round(5).tolist()))
    return dict(f=focal, tracks=tracks)


def make_ae_camera(mats, focal):
    flip = np.array([1., -1., -1.])
    center = np.array([WIDTH / 2, HEIGHT / 2, 0])
    pos, poi, roll, probes = [], [], [], []
    sample = np.array([.82, -.36, -3.])
    for mat in mats:
        rot, eye = mat[:3, :3], mat[:3, 3]
        p = center + 1000 * flip * eye
        fw, down = -flip * rot[:, 2], -flip * rot[:, 1]
        right = np.cross([0., 1., 0.], fw)
        if np.linalg.norm(right) < 1e-7:
            raise ValueError("Vertical AE two-node camera encountered; choose another camera convention")
        unrolled_down = np.cross(fw, right / np.linalg.norm(right))
        roll.append(np.arctan2(fw @ np.cross(unrolled_down, down), unrolled_down @ down))
        pos.append(p.tolist())
        poi.append((p + 1000 * fw).tolist())
        probes.append((center + 1000 * flip * (eye + rot @ sample)).tolist())
    # Native AE toComp samples this off-axis world point, also exercising zoom and roll.
    check_uv = [center[0] - focal * sample[0] / sample[2], center[1] + focal * sample[1] / sample[2]]
    return dict(width=WIDTH, height=HEIGHT, fps=FPS, count=COUNT, zoom=focal,
                position=pos, poi=poi, roll=np.rad2deg(np.unwrap(roll)).tolist(),
                probe=probes, expected=check_uv)


def write_json(path, data):
    path.write_text(json.dumps(data, separators=(",", ":"), allow_nan=False) + "\n", encoding="utf-8")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--camera", type=Path, default=ROOT / "Camera/Camera_Three.json")
    parser.add_argument("--out-dir", type=Path, default=ROOT / "scene")
    args = parser.parse_args()
    matrices, zoom = load_camera(args.camera)
    layout = make_layout(matrices, zoom)
    ae_camera = make_ae_camera(matrices, zoom)
    args.out_dir.mkdir(parents=True, exist_ok=True)
    write_json(args.out_dir / "layout.json", layout)
    write_json(args.out_dir / "camera_ae.json", ae_camera)
    print(f"Prepared {COUNT} camera keys and {len(layout['tracks'])} tracks; AE zoom {zoom:.3f} px")
