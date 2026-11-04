"""Render the moving-plate water pass with native OpenGL 3.3; no browser required."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import tempfile

import cv2
import moderngl as gl
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
WIDTH, HEIGHT = 1920, 1080
CROP_SIZE = 800
BUFFER_SIZE = 2 * CROP_SIZE
FRAME_COUNT = 192
FPS = "24000/1001"


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def camera_projection(shot):
    near, far = .02, 50
    w, h = shot["width"], shot["height"]
    return np.array([
        [2*shot["fx"]/w, 0, 1-2*shot["cx"]/w, 0],
        [0, 2*shot["fy"]/h, 2*shot["cy"]/h-1, 0],
        [0, 0, -(far+near)/(far-near), -2*far*near/(far-near)],
        [0, 0, -1, 0],
    ])


def rotation(angles):
    a, b, c = np.deg2rad(angles)
    ca, cb, cc = np.cos([a, b, c])
    sa, sb, sc = np.sin([a, b, c])
    return (np.array([[1,0,0], [0,ca,-sa], [0,sa,ca]])
            @ np.array([[cb,0,sb], [0,1,0], [-sb,0,cb]])
            @ np.array([[cc,-sc,0], [sc,cc,0], [0,0,1]]))


def draw_water(camera_frames, projection, track, frames, cache, output):
    ctx = gl.create_standalone_context(require=330)
    print("OpenGL", ctx.info["GL_VERSION"], ctx.info["GL_RENDERER"], flush=True)
    shaders = ROOT / "Water/shaders"
    vertex = (shaders / "surface.vert").read_text()
    back = ctx.program(vertex_shader=vertex, fragment_shader=(shaders / "exit.frag").read_text())
    front = ctx.program(vertex_shader=vertex, fragment_shader=(shaders / "water.frag").read_text())
    for i, name in enumerate(("positions", "normals", "plate", "hdr")):
        front[name] = i
    shape = (BUFFER_SIZE, BUFFER_SIZE)
    front["dim"] = tuple(map(float, shape))
    exit_buffers = [ctx.texture(shape, 4, dtype="f2") for _ in range(2)]
    for tex in exit_buffers:
        tex.repeat_x = tex.repeat_y = False
        tex.filter = (gl.NEAREST, gl.NEAREST)
    exit_fbo = ctx.framebuffer(exit_buffers, ctx.depth_renderbuffer(shape))
    beauty = ctx.framebuffer([ctx.texture(shape, 4)], ctx.depth_renderbuffer(shape))
    hdr = cv2.imread(str(ROOT / "Lighting/Forest_FrameLight.hdr"), cv2.IMREAD_UNCHANGED)
    if hdr is None:
        raise ValueError("Could not read Lighting/Forest_FrameLight.hdr")
    hdrtex = ctx.texture((hdr.shape[1], hdr.shape[0]), 3,
                         np.ascontiguousarray(hdr[::-1,:,::-1], dtype="f2").tobytes(), dtype="f2")
    hdrtex.repeat_y = False
    hdrtex.filter = (gl.LINEAR, gl.LINEAR)
    ctx.enable(gl.DEPTH_TEST | gl.CULL_FACE)
    for i in frames:
        camera = np.array(camera_frames[i]["matrixWorld"]).reshape(4,4).T
        vp = projection @ np.linalg.inv(camera)
        pos = np.array(track["pos"][i])
        clip = vp @ np.r_[pos, 1]
        xy = .5 + .5 * clip[:2] / clip[3]
        ox = int(np.clip(xy[0]*WIDTH-CROP_SIZE/2, 0, WIDTH-CROP_SIZE))
        oy = int(np.clip(xy[1]*HEIGHT-CROP_SIZE/2, 0, HEIGHT-CROP_SIZE))
        crop = np.eye(4)
        crop[0,0], crop[1,1] = WIDTH/CROP_SIZE, HEIGHT/CROP_SIZE
        crop[0,3], crop[1,3] = (WIDTH-2*ox-CROP_SIZE)/CROP_SIZE, (HEIGHT-2*oy-CROP_SIZE)/CROP_SIZE
        model = np.eye(4)
        model[:3,:3] = rotation(track["r"][i]) * track["scale"]
        model[:3,3] = pos
        buf = ctx.buffer((cache / "surface" / f"{i:03}.bin").read_bytes())
        for program in (back, front):
            for name, value in (("model", model), ("vp", vp), ("crop", crop)):
                program[name].write(np.ascontiguousarray(value.T, dtype="f4").tobytes())
        front["eye"] = tuple(camera[:3,3])
        plate = cv2.imread(str(cache / "frames" / f"f_{i:03}.jpg"))
        ptex = ctx.texture((WIDTH, HEIGHT), 3, np.ascontiguousarray(plate[::-1,:,::-1]).tobytes())
        ptex.filter = (gl.LINEAR, gl.LINEAR)
        ptex.repeat_x = ptex.repeat_y = False
        binding = [(buf, "3f 3f", "vertex", "normal")]
        va, vb = ctx.vertex_array(back, binding), ctx.vertex_array(front, binding)
        exit_fbo.use()
        exit_fbo.clear(0,0,0,0,depth=1)
        ctx.cull_face = "front"
        va.render()
        beauty.use()
        beauty.clear(0,0,0,0,depth=1)
        ctx.cull_face = "back"
        for unit, tex in enumerate([*exit_buffers, ptex, hdrtex]):
            tex.use(unit)
        vb.render()
        raw = np.frombuffer(beauty.read(components=4, alignment=1), np.uint8).reshape(*shape,4)[::-1]
        tile = cv2.resize(raw, (CROP_SIZE, CROP_SIZE), interpolation=cv2.INTER_AREA)
        alpha = tile[:,:,3:4].astype("f")
        rgb = np.clip(tile[:,:,:3].astype("f")*255/np.maximum(1,alpha), 0,255).astype("u1")
        frame = np.zeros((HEIGHT,WIDTH,4), np.uint8)
        region = frame[HEIGHT-oy-CROP_SIZE:HEIGHT-oy, ox:ox+CROP_SIZE]
        region[:,:,:3], region[:,:,3] = rgb[:,:,::-1], tile[:,:,3]
        if not cv2.imwrite(str(output / f"w_{i:03}.png"), frame, [cv2.IMWRITE_PNG_COMPRESSION, 2]):
            raise OSError(f"Could not write frame {i}")
        for resource in (va, vb, buf, ptex):
            resource.release()
    ctx.release()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("frames", nargs="*", type=int, help="Individual frames, 0 through 191")
    parser.add_argument("--encode", action="store_true", help="Render all frames and write Water/Water_Refraction.mov")
    args = parser.parse_args()
    if any(i < 0 or i >= FRAME_COUNT for i in args.frames) or (args.frames and args.encode):
        parser.error("Choose frames 0–191 or use --encode alone for the complete shot")
    plate = ROOT / "Footage/Forest_08s.mov"
    info = json.loads(subprocess.check_output(["ffprobe","-v","error","-select_streams","v:0",
                      "-show_streams","-of","json",str(plate)]))["streams"][0]
    if int(info["nb_frames"]) != FRAME_COUNT or info["avg_frame_rate"] != FPS:
        raise ValueError("Input plate must contain 192 frames at 24000/1001 fps")
    shot = read_json(ROOT / "Camera/Camera_Three.json")
    track = next(t for t in read_json(ROOT / "scene/layout.json")["tracks"] if t["kind"] == "Water")
    if len(shot["frames"]) != FRAME_COUNT or shot["fps"] != [24000, 1001]:
        raise ValueError("Expected a 192-frame camera at 24000/1001 fps")
    scratch = ROOT / "water-cache"
    scratch.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(dir=scratch) as tmp:
        cache = Path(tmp)
        output = (cache if args.encode else scratch) / "water"
        output.mkdir(exist_ok=True)
        (cache / "frames").mkdir()
        subprocess.run(["node",str(ROOT / "Source/water_surface.mjs"),str(cache / "surface")], check=True)
        subprocess.run(["ffmpeg","-v","error","-i",str(plate),"-vf",
                        "scale=1920:1080:in_color_matrix=bt709:out_range=full","-q:v","2","-start_number","0",
                        "-threads","4",str(cache/"frames/f_%03d.jpg")], check=True)
        draw_water(shot["frames"], camera_projection(shot), track, args.frames or range(FRAME_COUNT), cache, output)
        if args.encode:
            movie = cache / "water.mov"
            subprocess.run(["ffmpeg","-v","error","-framerate",FPS,"-start_number","0","-i",str(output/"w_%03d.png"),
                            "-frames:v","192","-vf","scale=out_color_matrix=bt709:out_range=tv",
                            "-c:v","prores_ks","-profile:v","4","-pix_fmt","yuva444p10le","-alpha_bits","16",
                            "-threads","6","-color_primaries","bt709","-colorspace","bt709","-color_trc","bt709",
                            "-video_track_timescale","24000",str(movie)], check=True)
            os.replace(movie, ROOT / "Water/Water_Refraction.mov")
            print("Wrote Water/Water_Refraction.mov (straight alpha).")
        else:
            print("Wrote PNG frames to", output)


if __name__ == "__main__":
    main()
