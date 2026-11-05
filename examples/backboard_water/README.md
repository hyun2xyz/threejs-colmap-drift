# 백보드 물 · PnP / OpenGL

작은 물방울이 유리면에 붙어 있다가 합쳐져 내려오는 실험입니다. 최신 클로즈업 작업에서 사용한 방울 운동과 GLSL을 이식했습니다. **실사 물의 최종 룩은 검수 중인 실험 버전**이며, 이 데모가 농구대 최종 납품 영상은 아닙니다.

원본 촬영이나 사용자 폴더 없이 실행할 수 있습니다. 데모의 배경·백보드·환경광은 코드로 생성합니다. 기존 Three.js 물체/무중력 물 데모와 독립적으로 실행됩니다. 이 예제의 물 픽셀은 Python + 네이티브 OpenGL 3.3으로 만들며, Three.js 렌더라고 표기하지 않습니다.

## 처음 실행

Python3.12, FFmpeg/ffprobe와 OpenGL3.3 이상을 준비하고 저장소 루트에서 실행합니다.

```sh
python -m venv .venv
# Windows PowerShell: .venv\Scripts\Activate.ps1
# macOS/Linux: source .venv/bin/activate
python -m pip install -r requirements.txt

# 짧은 실행 확인
python examples/backboard_water/run.py --demo --frames 12 --output local-runs/board-smoke

# 약8초:192frames /24000/1001fps
python examples/backboard_water/run.py --demo --output local-runs/board-8s
```

Linux의 화면 없는 환경에서는 지원되는 GPU/EGL 구성과 `--backend egl`이 필요할 수 있습니다. Windows/NVIDIA에서 검증했고 다른 운영체제의 GPU 경로는 미검증입니다. 렌더 폴더가 비어 있지 않으면 종료하므로 재실행할 때 새 `--output` 경로를 사용하세요.

출력:

- `Composite.mp4`: 물을 합친 영상.
- `Plate.mp4`: 동일 크기·시간축의 원본/데모 플레이트.
- `Alpha.mov`: ProRes4444 Straight 알파. AE에서 **Straight / Unmatted**로 해석해 `Plate.mp4` 위에 놓습니다.
- `tracks.json`, `camera.json`: 네 모서리 관측과 PnP 카메라. source0부터 시작합니다.
- `report.json`: 프레임 수·fps·전체 디코딩·피팅 잔차·방울 합류와 부피 프록시 수지.

## 내 촬영에 사용

촬영 영상은 CFR Rec.709, 정사각 픽셀이어야 합니다. 백보드나 유리판이 고정되어 있고 평면이라고 가정합니다. **먼저 각 프레임의 네 모서리를 실제 영상에서 추적**해 다음 JSON을 만드세요. 점 순서는 좌상·우상·우하·좌하입니다.

```json
{
  "width": 1920,
  "height": 1080,
  "fps": [24000, 1001],
  "focal_px": 1100,
  "board_aspect": 1.5025,
  "frames": [
    {"source_frame": 0, "corners": [[532,176],[1319,173],[1317,699],[533,696]]}
  ]
}
```

위 숫자는 형식 예시이며 자기 촬영에 그대로 쓰면 안 됩니다. `frames`에는 실제 모든 프레임의 관측이 필요합니다. `focal_px`는 해당 해상도에서의 렌즈 내부 파라미터, `board_aspect`는 판의 가로/세로 비율입니다. 렌즈 왜곡은 미리 보정하고, 보정된 영상의 내부 파라미터를 사용하세요. 이 스크립트는 왜곡·rolling shutter를 추정하지 않습니다.

```sh
python examples/backboard_water/run.py --plate inputs/my-shot.mp4 --tracks inputs/my-corners.json --hdri inputs/my-light.hdr --grid 2048 --output local-runs/my-board
```

앞을 가리는 물체가 있으면 `--holdouts inputs/mattes`를 추가합니다. `000.png`, `001.png`…의 원본 해상도 회색조 매트에서255는 물을 가리고0은 통과시킵니다. 크롭하려면 `--crop X Y WIDTH HEIGHT`, 확대하려면 같은 종횡비의 `--size WIDTH HEIGHT`를 사용하세요. 플레이트와 물이 동일하게 크롭되며 카메라 자체나 물체 크기를 프레임마다 고정하지 않습니다.

## PnP 원리와 한계

PnP(Perspective-n-Point)는 위치를 알고 있는3D점이 영상의2D관측에 겹치도록 회전·이동을 구합니다. 여기서는 가로1.8이라는 가정된 판의 모서리 네 개를 투영해서 실사 모서리에 맞춥니다. 카메라 초점거리·판 비율이 잘못되면 화면상 피팅이 작아도 실제 깊이·반사각은 틀릴 수 있습니다. [OpenCV 공식 설명](https://docs.opencv.org/4.12.0/d5/d1f/calib3d_solvePnP.html)

이 예제는 **이미 추적한 모서리로 카메라를 푸는 단계**입니다. 자동 모서리 추적이나 COLMAP SfM 재구성을 수행하지 않습니다. COLMAP 입력은 기존 [tracking 문서](../../tracking/README.md)를 보세요. `report.json`의 잔차는 같은 네 점에 대한 피팅 값으로, 독립 검증이나 실제 트래킹 합격을 의미하지 않습니다. 실제 납품 전에는 별도 점과 처음·중간·끝·최악 프레임의 미끄러짐을 확인해야 합니다.

물은 중력·표면 고착·저항·합류를 단순화한 방울 모델입니다. 완전한 Navier–Stokes 유체 해석이 아니고, 부피 수치는 반지름 세제곱의 프록시입니다. 굴절은 현재 플레이트를 이동 샘플링하는 근사이므로 알파를 다른 배경에 그대로 옮기면 맞지 않습니다. HDRI가 없으면 절차적 조명 프록시가 쓰입니다. 원본1080p를 크게 크롭해도 실제 촬영 디테일이 새로 생기지는 않습니다.

설계 참고: [Shadertoy 물방울 참고 작품](https://www.shadertoy.com/view/ldSBWW), [Water Droplets 논문/저자 자료](https://home.hiroshima-u.ac.jp/kin/publications/CA93/wdroplet.html). 포함한Python/GLSL은 이 파이프라인용으로 작성한 구현이며 링크된 작품의 소스나 촬영 미디어를 재배포하지 않습니다.
