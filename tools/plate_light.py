"""Blend a tracked rectilinear Rec.709 plate frame into a measured latitude-longitude HDRI."""
import argparse
import json
from pathlib import Path
import subprocess

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("panorama", type=Path, help="Linear RGB Radiance .hdr, oriented to the scene")
    parser.add_argument("--frame", type=int, default=0, help="Local frame index shared by plate and camera")
    parser.add_argument("--output", type=Path, default=ROOT / "Lighting/Forest_FrameLight.hdr")
    args = parser.parse_args()
    if args.output.exists():
        parser.error("Output exists. Supply a new --output path.")
    shot = json.loads((ROOT / "Camera/Camera_Three.json").read_text(encoding="utf-8-sig"))
    if not 0 <= args.frame < len(shot["frames"]):
        parser.error("Frame outside camera range")
    pano = cv2.imread(str(args.panorama), cv2.IMREAD_UNCHANGED)
    if pano is None or pano.dtype != np.float32 or pano.ndim != 3 or pano.shape[2] != 3:
        parser.error("Expected a floating-point RGB panorama")
    if pano.shape[1] != pano.shape[0] * 2:
        parser.error("Expected a 2:1 equirectangular panorama")
    plate = ROOT / "Footage/Forest_08s.mov"
    vf = (f"select=eq(n\\,{args.frame}),scale=1920:1080,"
          "zscale=matrixin=709:primariesin=709:transferin=709:rangein=limited:"
          "matrix=gbr:primaries=709:transfer=linear:range=full:npl=100,format=gbrpf32le")
    raw = subprocess.check_output(["ffmpeg","-v","error","-i",str(plate),"-vf",vf,"-frames:v","1",
                                   "-f","rawvideo","-pix_fmt","gbrpf32le","-"])
    # FFmpeg emits planar G, B, R. OpenCV uses interleaved BGR.
    image = np.frombuffer(raw, dtype="<f4").reshape(3,1080,1920)[[1,0,2]].transpose(1,2,0)
    height, width = pano.shape[:2]
    y, x = np.mgrid[:height,:width]
    lon = ((x+.5)/width-.5)*2*np.pi
    lat = (.5-(y+.5)/height)*np.pi
    directions = np.stack((np.cos(lat)*np.cos(lon),np.sin(lat),np.cos(lat)*np.sin(lon)),axis=-1)
    camera = np.array(shot["frames"][args.frame]["matrixWorld"]).reshape(4,4).T
    rays = directions @ camera[:3,:3]
    z = -rays[:,:,2]
    x = (shot["cx"] + shot["fx"]*rays[:,:,0]/np.maximum(z,.0001))*1920/shot["width"]
    y = (shot["cy"] - shot["fy"]*rays[:,:,1]/np.maximum(z,.0001))*1080/shot["height"]
    sampled = cv2.remap(image,x.astype("f"),y.astype("f"),cv2.INTER_LINEAR,borderMode=cv2.BORDER_REPLICATE)
    blend = np.clip(np.minimum.reduce([x/120,(1919-x)/120,y/75,(1079-y)/75]),0,1)*(z>0)
    blend = blend*blend*(3-2*blend)
    interior = blend>.95
    if not np.any(interior):
        raise ValueError("No plate pixels covered the HDRI")
    gain = np.clip(np.median(pano[interior])/max(.001,np.median(sampled[interior])),.35,3)
    result = pano*(1-blend[:,:,None])+sampled*(gain*blend[:,:,None])
    args.output.parent.mkdir(exist_ok=True, parents=True)
    if not cv2.imwrite(str(args.output),result.astype("f")):
        raise OSError("HDRI write failed")
    print(f"Wrote {args.output} (plate exposure multiplier {gain:.3f})")


if __name__ == "__main__":
    main()
