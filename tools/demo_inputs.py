"""Generate an eight-second virtual light room and matching equirectangular HDRI."""
from pathlib import Path
import json
import shutil
import subprocess
import tempfile

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
RATE = "24000/1001"


def coordinates(width, height):
    u, v = np.meshgrid((np.arange(width, dtype="f") + .5) / width,
                       (np.arange(height, dtype="f") + .5) / height)
    return u, v


def room(eye, rays):
    """Intersect rays with six faces of a simple, original tiled studio set."""
    low = np.array([-8, -2.4, -7], dtype="f")
    high = np.array([9, 5.8, 13], dtype="f")
    planes = np.where(rays > 0, high, low)
    distances = np.divide(planes - eye, rays, out=np.full_like(rays, np.inf),
                          where=np.abs(rays) > 1e-8)
    side = np.argmin(distances, axis=-1)
    hit = eye + rays * np.min(distances, axis=-1)[..., None]
    x, y, z = hit.transpose(2, 0, 1)
    u = np.where(side == 0, z, x)
    v = np.where(side == 1, z, y)
    floor = (side == 1) & (rays[..., 1] < 0)
    ceiling = (side == 1) & ~floor
    wall = side != 1
    color = np.empty_like(rays)
    color[:] = [.25, .34, .32]
    color[floor] = [.28, .22, .16]
    color[ceiling] = [.47, .43, .34]
    panel = (np.floor(u / 2) + np.floor(v / 1.25)) % 2
    color *= (.90 + .10 * panel[..., None])
    joint = (np.mod(u + .02, 2) < .034) | (np.mod(v + .02, 1.25) < .03)
    color[joint] *= .63
    windows = wall & (y > 1.1) & (y < 4.5) & (np.mod(u + 1, 3.7) < 2.05)
    color[windows] = [2.9, 3.55, 4.2]
    mullion = windows & ((np.mod(u + 1, 3.7) > .98) & (np.mod(u + 1, 3.7) < 1.04) | (np.abs(y - 2.78) < .037))
    color[mullion] = [.065, .085, .09]
    color[wall & (y > -.77) & (y < -.32)] = [.49, .125, .061]
    color[ceiling & (np.mod(x, 3.5) < .19)] = [4.6, 3.6, 2.45]
    return color


def encode_srgb(linear):
    # Match the display plate to the room while retaining highlight range in the HDRI.
    mapped = linear / (1 + linear)
    return np.uint8(255 * np.clip(1.055 * mapped ** (1 / 2.4) - .055, 0, 1) + .5)


def main():
    shot = json.loads((ROOT / "Camera/Camera_Three.json").read_text(encoding="utf-8-sig"))
    frames = shot["frames"]
    if len(frames) != 192 or shot["fps"] != [24000, 1001]:
        raise ValueError("The example requires 192 frames at 24000/1001 fps")
    plate = ROOT / "Footage/Forest_08s.mov"
    light = ROOT / "Lighting/Forest_FrameLight.hdr"
    if plate.exists() or light.exists():
        raise SystemExit("Input files already exist. Run this sample in a fresh checkout.")
    plate.parent.mkdir(exist_ok=True)
    light.parent.mkdir(exist_ok=True)
    width, height = 640, 360
    u, v = coordinates(width, height)
    local = np.stack(((u * shot["width"] - shot["cx"]) / shot["fx"],
                      (shot["cy"] - v * shot["height"]) / shot["fy"],
                      -np.ones_like(u)), axis=-1)
    with tempfile.TemporaryDirectory(dir=ROOT) as tmp:
        tmp = Path(tmp)
        lon, lat = coordinates(1024, 512)
        lon = (lon - .5) * 2 * np.pi
        lat = (.5 - lat) * np.pi
        rays = np.stack((np.cos(lat) * np.cos(lon), np.sin(lat), np.cos(lat) * np.sin(lon)), axis=-1)
        if not cv2.imwrite(str(tmp / "light.hdr"), room(np.zeros(3, dtype="f"), rays)[..., ::-1]):
            raise OSError("Could not write demo HDRI")
        args = ["ffmpeg", "-v", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{width}x{height}",
                "-framerate", RATE, "-i", "-", "-vf", "scale=1920:1080:flags=bicubic:out_color_matrix=bt709",
                "-an", "-c:v", "prores_ks", "-profile:v", "2", "-pix_fmt", "yuv422p10le", "-threads", "4",
                "-color_primaries", "bt709", "-color_trc", "bt709", "-colorspace", "bt709",
                "-video_track_timescale", "24000", str(tmp / "plate.mov")]
        with subprocess.Popen(args, stdin=subprocess.PIPE) as proc:
            for frame in frames:
                camera = np.asarray(frame["matrixWorld"], dtype="f").reshape(4,4).T
                rgb = room(camera[:3, 3], local @ camera[:3,:3].T)
                proc.stdin.write(encode_srgb(rgb).tobytes())
            proc.stdin.close()
            if proc.wait() != 0:
                raise RuntimeError("FFmpeg could not encode the demo plate")
        shutil.move(str(tmp / "light.hdr"), light)
        shutil.move(str(tmp / "plate.mov"), plate)
    print("Generated a synthetic 192-frame 1080p plate and a linear HDRI.")


if __name__ == "__main__":
    main()
