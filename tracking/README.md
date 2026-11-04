# COLMAP 카메라를 Three.js로 내보내기

동봉한 [예제 카메라](../Camera/Camera_Three.json)는 Drift의 실제 192개 포즈다. 렌더만 재현할 때는 그 파일을 바로 쓴다. 아래 첫 번째 절차는 새 영상의 모든 프레임이 등록된 경우에, 두 번째 절차는 성긴 원속도 카메라와 실제 슬로모션 영상이 함께 있는 경우에 쓴다.

## 일반 영상

한 개의 고정 렌즈를 가정한다. 프레임마다 파일명 끝에 연속 번호를 붙인다. 아래는 이미 렌즈 왜곡을 보정한 단일 영상의 예다. 저장소 루트에서 `.scratch` 아래에 `frames`, `sparse`, `model-txt` 빈 디렉터리를 먼저 만든다. `plate.mov`는 직접 준비한다.

```sh
ffmpeg -i plate.mov -map 0:v:0 -fps_mode passthrough -start_number 0 .scratch/frames/frame_%06d.png
colmap feature_extractor --database_path .scratch/match.db --image_path .scratch/frames --ImageReader.single_camera 1 --ImageReader.camera_model PINHOLE
colmap sequential_matcher --database_path .scratch/match.db
colmap mapper --database_path .scratch/match.db --image_path .scratch/frames --output_path .scratch/sparse
colmap model_converter --input_path .scratch/sparse/0 --output_path .scratch/model-txt --output_type TXT
python tracking/export_colmap.py .scratch/model-txt .scratch/camera.json --fps 24000/1001
```

FPS는 실제 편집 타임라인 값으로 바꾼다. VFR 소스는 타임스탬프에 맞춰 고정 프레임률 작업본을 먼저 만든다. 재구성이 여러 모델로 나뉘면 필요한 프레임을 담은 모델을 선택한다. 왜곡이 있는 렌즈는 알맞은 모델로 먼저 풀고, COLMAP의 `image_undistorter`가 출력한 핀홀 모델과 보정 영상을 한 쌍으로 쓴다. [COLMAP 명령줄 가이드](https://colmap.github.io/cli.html)

변환기 자체는 Python 표준 라이브러리만 사용한다. `PINHOLE`과 `SIMPLE_PINHOLE`을 지원하며 한 구간에서 한 카메라 ID를 사용한다. 프레임 누락·중복은 오류로 보고한다. `--first 10 --last 49`는 파일 번호 10–49를 로컬 프레임 0–39로 내보낸다. 원본 파일 이름은 JSON에 기록하지 않는다.

### 행렬과 좌표

- `frame`은 로컬 0부터 시작한다. 일반 변환기의 `sourceFrame`은 파일명 끝의 번호다. 동봉한 예제에서는 0부터 센 슬로모션 타임라인의 192–383에 해당한다. 한 프레임의 길이는 `fps[1] / fps[0]`초다.
- `matrixWorld`는 카메라 로컬에서 월드로 가는 4×4 행렬을 열 우선으로 나열한 값이다. COLMAP의 world-to-camera 포즈를 뒤집고 카메라 로컬의 Y, Z축을 반전했다. Three.js의 카메라 전방은 −Z, 위쪽은 +Y다. [COLMAP 파일 형식](https://colmap.github.io/format.html)
- 일반 변환 결과의 월드 원점·위쪽·길이 단위는 재구성에서 정해진다. 장면의 지면과 오브젝트를 새 샷에 배치하거나, 카메라 중심과 장면 기하에 동일한 유사변환을 적용한다. 예제 카메라에는 이미 Drift 오브젝트 기준 좌표계가 적용됐다.
- `fx, fy, cx, cy`는 JSON의 `width, height` 기준 픽셀 값이다. 화면의 좌상단이 원점이다. 아래 코드는 부모가 없는 Three.js `PerspectiveCamera`와 전체 프레임을 표시하는 뷰포트를 사용한다.

```js
const { width: w, height: h, fx, fy, cx, cy } = shot;
const n = camera.near, f = camera.far;
camera.projectionMatrix.makePerspective(-cx*n/fx, (w-cx)*n/fx, cy*n/fy, -(h-cy)*n/fy, n, f);
camera.projectionMatrixInverse.copy(camera.projectionMatrix).invert();
camera.matrixAutoUpdate = false;
camera.matrix.fromArray(shot.frames[frame].matrixWorld);
camera.updateMatrixWorld(true);
```

## 실제 리타임 영상에 맞춘 보정

Drift에서는 원속도 238프레임 중 61프레임에 COLMAP 포즈가 있었다. `measure.py native`가 양쪽 키프레임의 같은 3D점을 Lucas–Kanade로 추적하고, 두 추적이 동의하는 관측으로 남은 177포즈를 RANSAC PnP와 LM으로 계산했다. 4배 슬로모션 타임라인의 초기 회전은 SLERP, 위치는 선형 보간했다.

`measure.py observations`는 슬로모션 영상 **각 프레임의 실제 픽셀**에서 고정 3D점 위치와 다음 프레임까지의 2D 이동을 측정한다. `refine_retime.py`가 두 잔차를 함께 최소화한다. 네 번의 반복에서 인접한 포즈를 함께 풀며, ID를 5로 나눈 나머지가 0인 점은 피팅에서 제외한다. 아래 숫자는 이 예제 샷에 사용한 설정이다.

### 입력 준비

1. `.scratch/native/`에 원속도 PNG 전부를 숫자 순서로 둔다. 원속도 영상, 리타임 영상, 등록 모델에서 렌즈 보정·프레이밍·픽셀 크기가 일치해야 한다. 예제의 측정 해상도는 960×540이었다.
2. `.scratch/key-model/`에 해당 프레임들의 단안 COLMAP 희소 재구성을 둔다. 시작과 끝 원속도 프레임은 등록돼 있어야 한다. 모델 파일 번호가 원속도 파일 번호와 같으면 다음 명령의 `--key-map`을 생략한다. 등록 대상을 따로 1부터 다시 번호 매겼다면 JSON 배열로 매핑한다. 예를 들어 `[0,4,8]`은 모델 파일 1, 2, 3이 원속도 프레임 0, 4, 8을 가리킨다는 뜻이다.
3. 실제 고정 속도 슬로모션 작업본의 영상 스트림을 8비트 그레이 프레임으로 디코딩한다. 원속도 프레임 0과 슬로모션 프레임 0이 같은 순간이어야 한다. 리타임 계수는 원속도 프레임 사이에 들어가는 시간 간격 수다.

```sh
ffmpeg -i retime.mov -map 0:v:0 -vf scale=960:540 -pix_fmt gray -fps_mode passthrough -f rawvideo .scratch/retime.gray
```

### 보정 실행

독립 가상환경에 예제 리플레이에 사용한 버전을 설치한다. 아래 명령은 Python 3.12에서 검증했다. `--exclude`는 움직이는 피사체가 차지하는 사각형의 좌·상·우·하 좌표다. 다른 영상에서는 해당 영역을 다시 측정하거나 옵션을 생략한다.

```sh
python -m pip install numpy==1.26.4 scipy==1.14.1 opencv-python==4.10.0.84 pycolmap==4.2.0
python tracking/measure.py native .scratch/key-model .scratch/native .scratch/native.npz --key-map .scratch/keymap.json --exclude 235 175 550 540
python tracking/measure.py observations .scratch/key-model .scratch/native .scratch/observations.npz --key-map .scratch/keymap.json --exclude 235 140 630 540 --retime-gray .scratch/retime.gray --factor 4 --start 184 --count 208
python tracking/refine_retime.py .scratch/native.npz .scratch/observations.npz .scratch/refined.json --start 192 --count 192 --pad 8 --factor 4 --size 960 540 --scale 4 --fps 24000/1001 --drift-layout
```

마지막 명령은 양쪽 8프레임까지 보정에 사용한 뒤 중앙 192프레임을 3840×2160 투영값으로 내보낸다. `--drift-layout`는 **당시 희소 재구성 좌표계에서만** 유효하다. 새 영상이나 새로 푼 모델에서는 이 옵션을 빼고 자기 장면을 정렬한다. `--size`는 측정 이미지의 실제 크기이고, `--scale`은 잘라내기 없는 균일 확대 배수다. 모든 출력 경로는 새 파일이어야 한다.

### 검산

공개 코드를 원래 샷의 비공개 입력으로 실행해 원속도 238포즈, 보정 구간의 고정점 관측 55,070건과 프레임 이동 관측 55,037건을 기존 계산과 대조했다. 최종 192행렬은 소수점 10자리 내보내기 정밀도에서 동봉 파일과 일치했다. 일반 변환기는 61개 등록 카메라에서 38,906개 점의 투영을 pycolmap과 비교해 최대 차이 2.4×10⁻¹²픽셀을 확인했다.

원래 샷의 독립 근거리 검수에서는 절대 위치와 프레임 간 떨림이 다르게 나타났다. 10.010–12.012초 구간의 지면·나무 트랙 36개, 관측 709건에서 프레임 이동 벡터 오차의 95백분위가 8.72 → 2.39픽셀, 화면 위치 오차가 40.48 → 18.83픽셀로 줄었다. 960×540에서 측정해 4K로 환산한 값이다. 새 샷은 그 샷에 배치할 물체와 비슷한 깊이의 정적 특징점으로 별도 검수한다.
