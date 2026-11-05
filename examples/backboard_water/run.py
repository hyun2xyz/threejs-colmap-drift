"""Portable tracked-plane water demo. No footage downloads or machine-local imports."""
from pathlib import Path
from fractions import Fraction
import argparse, hashlib, json, shutil, subprocess as sp
import cv2
import numpy as np
import moderngl
import simulation

HERE = Path(__file__).resolve().parent


def write_json(path, value):
    path.write_text(json.dumps(value, indent=2), encoding='utf-8')


def projected(points, pose, focal, width, height):
    q = (points - pose[:3, 3]) @ pose[:3, :3]
    return q[:, :2] / -q[:, 2:] * [focal, -focal] + [width / 2, height / 2]


def demo_inputs(count, width, height, focal, corners):
    """Procedural studio plate with a board. All pixels are generated locally."""
    rng = np.random.default_rng(405)
    yy, xx = np.indices((height, width))
    bg = np.stack(np.broadcast_arrays(150 + 35 * yy / height,
        161 + 30 * yy / height, 165 + 20 * yy / height), axis=-1).astype('uint8')
    bg[(xx // 110) % 5 == 0] = [110, 135, 149]
    bg[yy > height * .78] = [104, 106, 103]
    pane = np.full((512, 768, 3), [98, 124, 117], np.float32)
    pane += rng.normal(0, 2, pane.shape).astype('f')
    pane = np.uint8(pane.clip(0, 255))
    cv2.rectangle(pane, (8, 8), (759, 503), (225, 223, 209), 14)
    cv2.rectangle(pane, (296, 244), (472, 372), (223, 221, 211), 13)
    cv2.line(pane, (16, 140), (752, 140), (105, 78, 58), 14)
    for x in range(475, 745, 31):
        cv2.line(pane, (x, 18), (x + 3, 490), (87, 113, 106), 1)
    for i in range(count):
        pose = np.eye(4)
        pose[:3, 3] = [.035 * np.sin(i / 80), .025, 2.45 + i * .005]
        quad = projected(corners, pose, focal, width, height)
        warp = cv2.getPerspectiveTransform(np.float32([[0, 0], [767, 0], [767, 511], [0, 511]]), quad.astype('f'))
        image = bg.copy()
        board = cv2.warpPerspective(pane, warp, (width, height))
        mask = cv2.warpPerspective(np.full((512, 768), 255, np.uint8), warp, (width, height))
        image[mask > 0] = board[mask > 0]
        yield image, quad


class Encoder:
    def __init__(self, path, width, height, fps, alpha=False):
        self.path = path
        codec = (['-c:v', 'prores_ks', '-profile:v', '4', '-alpha_bits', '16', '-pix_fmt', 'yuva444p10le']
                 if alpha else ['-c:v', 'libx264', '-crf', '16', '-preset', 'fast', '-pix_fmt', 'yuv420p',
                 '-x264-params', 'colorprim=bt709:transfer=bt709:colormatrix=bt709:fullrange=off',
                 '-bsf:v', 'h264_metadata=colour_primaries=1:transfer_characteristics=1:matrix_coefficients=1:video_full_range_flag=0'])
        self.process = sp.Popen(['ffmpeg', '-v', 'error', '-n', '-f', 'rawvideo', '-pix_fmt',
            'rgba' if alpha else 'rgb24', '-s', f'{width}x{height}', '-framerate', str(fps), '-i', '-',
            '-an', '-vf', 'scale=in_range=pc:out_color_matrix=bt709:out_range=tv', '-filter_threads', '2',
            *codec, '-threads', '4', '-color_range', 'tv', '-colorspace', 'bt709',
            '-color_primaries', 'bt709', '-color_trc', 'bt709', '-movflags', '+faststart+write_colr',
            str(path)], stdin=sp.PIPE)

    def write(self, pixels):
        self.process.stdin.write(np.ascontiguousarray(pixels).tobytes())

    def finish(self):
        self.process.stdin.close()
        if self.process.wait() != 0:
            raise RuntimeError(f'FFmpeg failed: {self.path}')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--demo', action='store_true')
    mode.add_argument('--plate', type=Path, help='Own constant-frame-rate Rec.709 video')
    parser.add_argument('--tracks', type=Path, help='Required with --plate; see README schema')
    parser.add_argument('--hdri', type=Path, help='Linear .hdr environment, not sRGB JPEG')
    parser.add_argument('--holdouts', type=Path, help='Optional native-size grayscale000.png etc;255blockswater')
    parser.add_argument('--frames', type=int, help='First N source frames; demo default192')
    parser.add_argument('--fps', type=str, default='24000/1001', help='Demo frame rate only')
    parser.add_argument('--grid', type=int, default=768, help='Surface grid width; production used2048')
    parser.add_argument('--output', type=Path, default=Path('local-runs/backboard-demo'))
    parser.add_argument('--backend', help='ModernGL standalone backend, e.g. egl on headless Linux')
    parser.add_argument('--crop', type=int, nargs=4, metavar=('X', 'Y', 'WIDTH', 'HEIGHT'))
    parser.add_argument('--size', type=int, nargs=2, metavar=('WIDTH', 'HEIGHT'))
    args = parser.parse_args()
    if not shutil.which('ffmpeg') or not shutil.which('ffprobe'):
        parser.error('Install FFmpeg and put ffmpeg/ffprobe on PATH')
    if args.output.exists() and any(args.output.iterdir()):
        parser.error('Output must be a new or empty directory; previous renders are preserved')
    args.output.mkdir(parents=True, exist_ok=True)
    tracks = None
    if args.plate:
        if not args.tracks:
            parser.error('--plate requires --tracks with measured corner observations')
        tracks = json.loads(args.tracks.read_text(encoding='utf-8-sig'))
        width, height = tracks['width'], tracks['height']
        fps = Fraction(*tracks['fps'])
        focal = float(tracks['focal_px'])
        aspect = float(tracks['board_aspect'])
        count = min(args.frames or len(tracks['frames']), len(tracks['frames']))
        if [r['source_frame'] for r in tracks['frames'][:count]] != list(range(count)):
            parser.error('Tracks must cover contiguous source frames0..N-1')
        for row in tracks['frames'][:count]:
            if np.asarray(row['corners']).shape != (4, 2):
                parser.error('Each frame needs four TL,TR,BR,BL corners')
        probe = json.loads(sp.check_output(['ffprobe', '-v', 'error', '-select_streams', 'v:0',
            '-show_entries', 'stream=width,height,r_frame_rate,avg_frame_rate', '-of', 'json', str(args.plate)]))['streams'][0]
        if (probe['width'], probe['height']) != (width, height) or Fraction(probe['avg_frame_rate']) != fps:
            parser.error('Plate dimensions/frame rate must match tracks; no implicit retime')
    else:
        width, height, focal, aspect = 960, 540, 600., 1.5
        fps, count = Fraction(args.fps), args.frames or 192
    if count <= 0 or fps <= 0:
        parser.error('Positive frame count/fps required')
    crop = args.crop or [0, 0, width, height]
    x, y, cw, ch = crop
    ow, oh = args.size or [cw, ch]
    if min(x, y) < 0 or min(cw, ch, ow, oh) <= 0 or x + cw > width or y + ch > height or ow % 2 or oh % 2:
        parser.error('Crop must be inside plate and output dimensions must be positive even integers')
    if abs(ow / oh - cw / ch) > .002:
        parser.error('Output and crop aspect must match; do not stretch the camera image')
    corners = np.array([[-.9, .9/aspect, 0], [.9, .9/aspect, 0], [.9, -.9/aspect, 0], [-.9, -.9/aspect, 0]], float)
    K = np.array([[focal, 0, width/2], [0, focal, height/2], [0, 0, 1.]], float)
    simulation.configure(aspect, args.grid, float(fps))
    fluid = simulation.Runoff()
    for _ in range(480):
        fluid.tick()
    ctx = moderngl.create_standalone_context(require=330, **({'backend': args.backend} if args.backend else {}))
    vs = '#version 330\nvoid main(){vec2 p=vec2((gl_VertexID<<1)&2,gl_VertexID&2);gl_Position=vec4(p*2.-1.,0,1);}'
    program = ctx.program(vertex_shader=vs, fragment_shader=(HERE/'water.frag').read_text())
    vao = ctx.vertex_array(program, [])
    def texture(shape, n, dtype='f1'):
        t = ctx.texture(shape, n, dtype=dtype)
        t.filter = moderngl.LINEAR, moderngl.LINEAR
        t.repeat_x = t.repeat_y = False
        return t
    plate_tex = texture((width, height), 3)
    height_tex = texture((simulation.GRID, simulation.HEIGHT), 1, 'f4')
    hold_tex = texture((width, height), 1)
    if args.hdri:
        hdr = cv2.imread(str(args.hdri), cv2.IMREAD_UNCHANGED)
        if hdr is None or hdr.ndim != 3 or not np.issubdtype(hdr.dtype, np.floating):
            raise ValueError('HDRI must decode as a floating-point RGB environment')
        hdr = hdr[:, :, ::-1]
    else:
        u, v = np.meshgrid(np.linspace(0, 1, 512), np.linspace(0, 1, 256))
        daylight = .08 + .7 * np.maximum(np.cos(v*np.pi), 0)
        hdr = np.stack([daylight*.93, daylight, daylight*1.06], axis=-1).astype('f')
        hdr += (2*np.exp(-((u-.35)**2+(v-.22)**2)/.003))[:, :, None]
    env_tex = texture((hdr.shape[1], hdr.shape[0]), 3, 'f2')
    env_tex.repeat_x = True
    env_tex.write(np.ascontiguousarray(hdr, dtype='f2').tobytes())
    for unit, (name, tex) in enumerate(zip(['plate', 'depthMicrons', 'frontHoldout', 'environment'],
            [plate_tex, height_tex, hold_tex, env_tex])):
        program[name] = unit
        tex.use(unit)
    program['aspect'], program['focal'] = aspect, focal
    program['crop'], program['outputSize'] = crop, (ow, oh)
    fb = ctx.framebuffer([texture((ow, oh), 4) for _ in range(4)])
    fb.use()
    src_corners = np.float32([[0, 0], [simulation.GRID-1, 0], [simulation.GRID-1, simulation.HEIGHT-1], [0, simulation.HEIGHT-1]])
    dec = None
    if args.plate:
        dec = sp.Popen(['ffmpeg', '-v', 'error', '-i', str(args.plate), '-an', '-frames:v', str(count),
            '-vf', 'scale=in_color_matrix=bt709:out_range=pc', '-fps_mode', 'passthrough',
            '-pix_fmt', 'rgb24', '-f', 'rawvideo', '-'], stdout=sp.PIPE)
        def frames():
            for row in tracks['frames'][:count]:
                data = dec.stdout.read(width*height*3)
                if len(data) != width*height*3:
                    raise RuntimeError('Plate ends before tracked source frame')
                yield np.frombuffer(data, np.uint8).reshape(height, width, 3), np.array(row['corners'], float)
        source = frames()
    else:
        source = demo_inputs(count, width, height, focal, corners)
    writers = [Encoder(args.output/'Composite.mp4', ow, oh, fps),
        Encoder(args.output/'Plate.mp4', ow, oh, fps), Encoder(args.output/'Alpha.mov', ow, oh, fps, True)]
    poses, rows, errors = [], [], []
    try:
        for i, (rgb, quad) in enumerate(source):
            ok, rvec, tvec = cv2.solvePnP(corners, quad, K, None, flags=cv2.SOLVEPNP_ITERATIVE)
            if not ok:
                raise RuntimeError(f'PnP failed frame{i}')
            view = np.eye(4)
            view[:3, :3], view[:3, 3] = cv2.Rodrigues(rvec)[0], tvec[:, 0]
            pose = np.linalg.inv(view) @ np.diag([1., -1., -1., 1.])
            repro = cv2.projectPoints(corners, rvec, tvec, K, None)[0][:, 0]
            errors.extend(np.linalg.norm(repro-quad, axis=1).tolist())
            poses.append(pose.tolist())
            rows.append({'source_frame': i, 'corners': quad.tolist()})
            for _ in range(6):
                fluid.tick()
            field = fluid.surface().astype('f')*.001
            hold = np.zeros((height, width), np.uint8)
            if args.holdouts:
                hold = cv2.imread(str(args.holdouts/f'{i:03}.png'), 0)
                if hold is None or hold.shape != (height, width):
                    raise ValueError(f'Missing/native-size holdout at frame{i}')
            plate_tex.write(np.ascontiguousarray(rgb).tobytes())
            height_tex.write(field.tobytes())
            hold_tex.write(hold.tobytes())
            matrix = cv2.getPerspectiveTransform(src_corners, repro.astype('f'))
            program['screenToBoard'].write(np.ascontiguousarray(np.linalg.inv(matrix).T, 'f').tobytes())
            program['camera'].write(np.ascontiguousarray(pose.T, 'f').tobytes())
            vao.render(vertices=3)
            layer = np.frombuffer(fb.read(components=4, attachment=0, alignment=1), np.uint8).reshape(oh, ow, 4)[::-1].copy()
            bg = cv2.resize(rgb[y:y+ch, x:x+cw], (ow, oh), interpolation=cv2.INTER_LANCZOS4)
            aa = layer[:, :, 3].astype('f')/255
            pm = layer[:, :, :3]*aa[:, :, None]
            sigma = max(.25, .43*ow/cw)
            aa, pm = cv2.GaussianBlur(aa, (0, 0), sigma), cv2.GaussianBlur(pm, (0, 0), sigma)
            color = pm/np.maximum(aa[:, :, None], 1e-5)
            hold_crop = cv2.resize(hold[y:y+ch, x:x+cw], (ow, oh), interpolation=cv2.INTER_NEAREST)
            aa[hold_crop == 255] = 0
            layer = np.dstack([np.uint8(np.rint(color).clip(0, 255)), np.uint8(np.rint(aa*255))])
            a = layer[:, :, 3:4].astype('f')/255
            final = np.uint8(np.rint(bg*(1-a)+layer[:, :, :3]*a).clip(0, 255))
            for writer, data in zip(writers, [final, bg, layer]):
                writer.write(data)
            if i in {0, count//2, count-1}:
                cv2.imwrite(str(args.output/f'preview_{i:03}.png'), final[:, :, ::-1])
            if i % 24 == 0:
                print('rendered', i, '/', count, flush=True)
    finally:
        if dec:
            dec.stdout.close()
            if dec.wait() != 0:
                raise RuntimeError('Source decode failed')
        for writer in writers:
            writer.finish()
    tracks_out = {'width': width, 'height': height, 'fps': [fps.numerator, fps.denominator],
        'focal_px': focal, 'board_aspect': aspect, 'frames': rows}
    write_json(args.output/'tracks.json', tracks_out)
    write_json(args.output/'camera.json', {**{k:v for k,v in tracks_out.items() if k != 'frames'},
        'matrix_world': poses, 'convention': 'boardXY, Zforward; Blender camera looks-Z', 'assumed_board_width': 1.8})
    input_volume = fluid.added
    volume_error = abs(input_volume-fluid.runout-fluid.deposited-sum(d[2] for d in fluid.drops))/input_volume
    if volume_error > 1e-8:
        raise RuntimeError('Volume proxy accounting failed')
    videos = {}
    for writer in writers:
        sp.run(['ffmpeg', '-v', 'error', '-xerror', '-i', str(writer.path), '-f', 'null', '-'], check=True)
        probe = json.loads(sp.check_output(['ffprobe', '-v', 'error', '-count_frames', '-select_streams', 'v:0',
            '-show_entries', 'stream=width,height,r_frame_rate,nb_read_frames,pix_fmt,profile', '-of', 'json', str(writer.path)]))['streams'][0]
        if int(probe['nb_read_frames']) != count or Fraction(probe['r_frame_rate']) != fps:
            raise RuntimeError('Encoded frame clock mismatch')
        videos[writer.path.name] = probe
    write_json(args.output/'report.json', {'frames': count, 'fps': str(fps), 'videos': videos,
        'gpu': ctx.info['GL_RENDERER'], 'input': 'procedural demo' if args.demo else str(args.plate),
        'pnp_fit_p95_px': float(np.percentile(errors, 95)), 'pnp_fit_max_px': float(max(errors)),
        'fit_is_not_independent_tracking_validation': True, 'merged': fluid.merges, 'volume_proxy_relative_error': volume_error,
        'shader_sha256': hashlib.sha256((HERE/'water.frag').read_bytes()).hexdigest(),
        'limits': 'Experimental lookdev, not photorealistic approval. Reduced-order bead dynamics, not fullCFD. Assumed scale/lens. Screen-space refraction; supplied HDRI or procedural proxy. Straight alpha contains plate-specific refracted colors.'})
    print('Wrote', args.output.resolve())


if __name__ == '__main__':
    main()
