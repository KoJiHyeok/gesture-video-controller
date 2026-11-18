# Gesture Video Controller

웹캠으로 손동작을 인식해 유튜브 영상을 제어하는 컴퓨터비전 팀 프로젝트입니다. Python, OpenCV, MediaPipe Hand Landmarker로 양손의 랜드마크를 검출하고, 손 모양과 움직임을 명령으로 바꿔 유튜브 창에 단축키를 보냅니다.

> 원본: [junseop02/gesture_video_controller](https://github.com/junseop02/gesture_video_controller) (commit `65562b4`).
> 이 저장소는 원본에 유튜브 자동 제어, 전체화면 제스처 보정, **오작동 기록 도구**를 더한 버전입니다.

## 설치

Windows와 Python 3.12에서 개발했습니다. 웹캠이 필요하고, 손 랜드마크 모델(`models/hand_landmarker.task`)은 저장소에 들어 있습니다.

아래 명령은 모두 **이 저장소를 받은 폴더 안에서** 실행합니다. 폴더 위치는 사람마다 달라도 상관없습니다.

**PowerShell**

```powershell
git clone https://github.com/KoJiHyeok/gesture-video-controller.git
cd gesture-video-controller
py -3.12 -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

**Git Bash**

```bash
git clone https://github.com/KoJiHyeok/gesture-video-controller.git
cd gesture-video-controller
py -3.12 -m venv .venv
source .venv/Scripts/activate
python -m pip install -r requirements.txt
```

> 가상환경을 켜지 않고 `python`을 실행하면 `No module named 'cv2'` 오류가 납니다.
> 가상환경을 켜기 싫다면 `python` 대신 `.venv\Scripts\python.exe`(Git Bash에서는 `.venv/Scripts/python.exe`)로 실행하세요.

## 실행

```bash
python src/hand_tracking.py          # 실제 제어: 명령마다 유튜브 창을 앞으로 가져와 키를 보냄
python src/hand_tracking.py --test   # 테스트: 유튜브는 건드리지 않고 인식만
```

- 웹캠 미리보기 창은 화면 오른쪽 위에 작게, 항상 위로 뜹니다. 키보드 포커스는 유튜브에 그대로 남습니다.
- 종료는 미리보기 창을 한 번 클릭한 뒤 **Esc**.
- 카메라만 확인하려면 `python tests/camera_test.py`.

## 제스처

실행 직후에는 제어가 꺼져 있습니다. V 사인을 1초 유지해 `CONTROL_ON`을 확인한 뒤 사용하세요. 15초 동안 명령이 없으면 자동으로 꺼집니다.

| 손동작 | 인식 결과 | 유튜브 동작 |
|---|---|---|
| V 사인을 1초 유지 | `CONTROL_ON` / `CONTROL_OFF` | 제스처 제어 켜기·끄기 |
| OK 사인 | `PLAY_PAUSE` | 재생·일시정지 |
| 편 손을 세운 뒤 오른쪽으로 빠르게 젖히기 | `SEEK_FORWARD` | 10초 앞으로 |
| 편 손을 세운 뒤 왼쪽으로 빠르게 젖히기 | `SEEK_BACKWARD` | 10초 뒤로 |
| 엄지를 위로 편 자세를 0.3초 유지한 뒤 손을 위로 | `VOLUME_UP` | 볼륨 증가 |
| 엄지를 아래로 편 자세를 0.3초 유지한 뒤 손을 아래로 | `VOLUME_DOWN` | 볼륨 감소 |
| 편 양손을 가운데에서 양옆으로 벌리기 | `FULLSCREEN_ON` | 전체화면 |
| 편 양손을 양옆에서 가운데로 모으기 | `FULLSCREEN_OFF` | 전체화면 해제 |
| 탐색 명령 후 엄지까지 접은 주먹을 0.25초 유지 | `FIST` | 반대 탐색 방향 허용 |

탐색 명령이 나가면 손을 되돌리는 동작이 반대 명령으로 잡히지 않도록 반대 방향을 3초 동안 잠급니다. 천천히 기울이는 동작은 탐색으로 치지 않습니다.

## 오작동 기록

명령이 나갈 때마다 **직전 1.5초 동안의 손 좌표**를 자동으로 저장합니다. 오작동이 나면 키 하나로 표시해 두고, 나중에 손 뼈대 애니메이션으로 다시 볼 수 있습니다. 따로 켤 옵션은 없고 항상 동작합니다.

### 키로 표시하기

전역 키라서 유튜브 창이 선택된 상태에서도 바로 눌립니다.

| 키 | 미리보기 창에서 | 뜻 | 결과 |
|---|---|---|---|
| **F8** | `x` | 방금 나간 명령이 오작동 | 마지막 클립 이름 뒤에 `_MISFIRE`가 붙음 (명령 후 10초 안에) |
| **F9** | `m` | 제스처를 했는데 명령이 안 나옴 | 직전 3초를 `_MISSED` 클립으로 저장 |

누르면 미리보기 창 오른쪽 아래 로그에 표시가 뜹니다. 노트북에서 F8/F9가 밝기·볼륨으로 잡히면 **Fn**과 같이 누르세요.

### 저장 위치

저장소 폴더 안 `clips/`에, 프로그램을 켤 때마다 켠 시각 이름으로 폴더가 생깁니다.

```
clips/
└─ 20261118_150000/                    ← 켠 시각 (YYYYMMDD_HHMMSS)
   ├─ 150102_412_CONTROL_ON.csv
   ├─ 150105_088_SEEK_FORWARD_MISFIRE.csv   ← F8 로 표시한 것
   ├─ 150105_088_SEEK_FORWARD_MISFIRE.png
   ├─ 150110_731_FIST.csv
   └─ 150118_204_MISSED.csv                 ← F9
```

| 파일 | 내용 |
|---|---|
| `.csv` | 프레임마다 21개 관절의 x, y, z와 그 프레임의 판정(정적 제스처, 엄지 위/아래, 주먹, 편 손, 제어 ON 여부). `t`는 명령 순간이 0, 그 전은 음수 |
| `.png` | 손 뼈대만 그린 그림. 오래된 프레임은 어둡게, 마지막은 밝게, 흰 선은 손목 궤적. 왼손 하늘색, 오른손 주황 |

`clips/`와 `traces/`는 `.gitignore`에 들어 있어 커밋되지 않습니다. 공유할 클립은 따로 골라 보내세요.

### 다시 보기

`<폴더>` 자리에는 `clips/` 안에 생긴 폴더 이름을 넣습니다. 이름 순서가 시간 순서라 마지막이 최신입니다.

```bash
ls clips                                                  # 어떤 폴더가 있는지
python tests/view_clip.py clips/<폴더>                     # 그 실행의 클립 전부
python tests/view_clip.py clips/<폴더> --only MISFIRE      # 오작동 표시한 것만
python tests/view_clip.py clips/* --only MISFIRE           # 모든 실행에서 오작동만
```

| 키 | 동작 |
|---|---|
| SPACE | 일시정지 / 재생 |
| n / p | 다음 / 이전 클립 |
| q / Esc | 종료 |

화면 오른쪽 아래에 그 순간의 시간과 손별 판정이 나옵니다. 기본은 실제의 약 절반 속도이고, `--fps 30`을 붙이면 실제 속도입니다.

### 쓰는 요령

1. 영상을 평소처럼 보다가 오작동이 날 때마다 **F8**만 누릅니다. 그 자리에서 원인을 따질 필요는 없습니다.
2. 클립이 몇 개 모이면 `--only MISFIRE`로 한꺼번에 보면서 원인별로 묶습니다 (예: 손 내리기, 머리 긁기, 천천히 기울이기).
3. 테스트로 켠 기록은 그 폴더째 지워서 실생활 기록과 섞이지 않게 합니다.

설정은 `src/clip_recorder.py` 위쪽에서 바꿉니다: 키(`VK_MISFIRE`, `VK_MISSED`), 클립 길이(`CLIP_SEC`), 기록 끄기(`CLIP_ENABLED = False`).

## 진단 도구

| 명령 | 용도 |
|---|---|
| `python tests/replay_swing.py traces/<파일>.csv` | 저장된 trace를 스윙 판정기에 다시 넣어 SEEK가 어떻게 나왔을지 재현 |
| `python tests/replay_fullscreen.py traces/<파일>.csv` | 같은 방식으로 전체화면 판정 재현 |

실행할 때마다 프레임별 진단 CSV가 `traces/`에 쌓입니다. 기준값을 바꾼 뒤 같은 trace로 수정 전후를 비교할 때 씁니다.

## 주요 파일

| 경로 | 역할 |
|---|---|
| `src/hand_tracking.py` | 웹캠 입력, 양손 검출, 제스처 처리, 화면 표시 |
| `src/gesture_recognition.py` | V·OK·주먹·엄지 자세 판정과 명령 처리 |
| `src/swing_tracking.py` | 좌우 스윙, 반대 방향 잠금, 엄지 자세 기반 볼륨 판정 |
| `src/fullscreen_tracking.py` | 양손 벌리기/모으기 전체화면 판정 |
| `src/clip_recorder.py` | 오작동 기록 (명령 직전 1.5초 저장, F8/F9 표시) |
| `src/youtube_control/` | 유튜브 창 찾기·포커스·단축키 전송 (Windows UI Automation) |
| `src/window_pin.py` | 미리보기 창 오른쪽 위 고정, 항상 위 |
| `tests/view_clip.py` | 오작동 클립 재생 |
