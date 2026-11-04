# Scene and stabilization

From the repository root, prepare the camera and placement data before rendering water. Run stabilization once the matching demo or replacement plate is available.

```sh
python scene/prepare.py
python scene/stabilize.py
```

The shot is 192 frames at 24000/1001 fps, or 8.008 s. `prepare.py` reads all camera-to-world matrices from `Camera/Camera_Three.json`. The inputs must use Three.js column-major order, a centered pinhole projection, square pixels and a 16:9 aspect ratio. The world is right-handed, Y-up, and camera forward is local −Z.

- Edit `PLACEMENTS` to change the six GLB instances and one water volume. Each anchor is set at frame 96 by normalized screen position and camera-space depth. The animated path then moves in 3D world units. In `layout.json`, each track has its model `kind`, scalar `scale`, world positions `pos` and Euler degrees `r` for all 192 frames. The water renderer selects the `Water` track.
- `camera_ae.json` contains positions, points of interest, roll angles, zoom and projection probes for the 1080p comp. A Three.js point `(x,y,z)` becomes `(960 + 1000x, 540 − 1000y, −1000z)` in AE. Poses and GLBs use the same conversion. The builder samples a projected off-axis point in AE on every frame and compares the result to the Three.js pinhole projection.
- `stabilize.json` contains centered 1080p pixel translations, rotations in degrees and a shared scale. Optical flow, forward/backward rejection and RANSAC estimate the background motion. Gaussian smoothing sets the target path. Only the final comp applies this transform. For the original shot's central moving subject, pass `--exclude-original-subject`.

These JSON files can be regenerated after changing camera, placement or plate. Both scripts also accept explicit paths. See `--help`.
