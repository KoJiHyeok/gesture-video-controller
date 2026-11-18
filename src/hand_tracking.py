
import argparse
import time
from collections import deque  # FPS 이동평균용
from pathlib import Path

import cv2
import mediapipe as mp

from gesture_recognition import (
    GestureController,
    recognize_gesture,
    select_gesture,
    is_fist,
    is_true_fist,
    is_relaxed_open,
    thumb_pose,
    thumb_info
)
from fullscreen_tracking import FullscreenTracker
from window_pin import keep_on_top, pin_top_right
from clip_recorder import ClipRecorder  # 명령 직전 1.5초 손 좌표 저장 + F8 오작동 / F9 안 나옴 표시
from swing_tracking import SwingTracker, SeekGate, trace  # 가운데->좌/우 스윙 SEEK + 3초/주먹 규칙

# 볼륨 = 엄지 위(따봉) + 손 위로 이동 / 엄지 아래 + 손 아래로 이동. 끄려면 False.
ENABLE_VOLUME = True
DEBUG_FULLSCREEN = False  # 상태 전환을 터미널에 출력
SEEK_COMMANDS = ("SEEK_FORWARD", "SEEK_BACKWARD")
WINDOW_NAME = "Gesture Controller"
PREVIEW_WIDTH = 480      # 우측 상단 미리보기 창 폭(px). 영상 비율대로 높이를 맞춘다
TOPMOST_EVERY = 2.0      # 이 간격(초)마다 '항상 위'를 다시 건다
AUTO_OFF_SEC = 15.0      # 제어 ON 상태에서 이 시간(초) 동안 명령이 없으면 자동으로 OFF (생활 동작 오작동 방지)
FS_COMMAND_LOCK = 0.3  # 전체화면 명령 뒤 SEEK·볼륨·OK 를 막는 시간(초). 원본은 0.8


BASE_DIR = Path(__file__).resolve().parent.parent
MODEL_PATH = BASE_DIR / "models" / "hand_landmarker.task"

if not MODEL_PATH.is_file():
    raise FileNotFoundError(
        f"모델 파일이 없습니다: {MODEL_PATH}"
    )


BaseOptions = mp.tasks.BaseOptions
HandLandmarker = mp.tasks.vision.HandLandmarker
HandLandmarkerOptions = mp.tasks.vision.HandLandmarkerOptions
RunningMode = mp.tasks.vision.RunningMode


CONNECTIONS = [
    (0, 1), (1, 2), (2, 3), (3, 4),
    (0, 5), (5, 6), (6, 7), (7, 8),
    (5, 9), (9, 10), (10, 11), (11, 12),
    (9, 13), (13, 14), (14, 15), (15, 16),
    (13, 17), (17, 18), (18, 19), (19, 20),
    (0, 17)
]


def draw_landmarks(frame, landmarks):
    height, width = frame.shape[:2]
    points = []

    for lm in landmarks:
        x = int(lm.x * width)
        y = int(lm.y * height)
        points.append((x, y))

        cv2.circle(
            frame, (x, y), 4, (0, 0, 255), -1
        )

    for start, end in CONNECTIONS:
        cv2.line(
            frame,
            points[start],
            points[end],
            (0, 255, 0),
            2
        )


def get_handedness(result, index):
    if (
        index >= len(result.handedness)
        or not result.handedness[index]
    ):
        return "UNKNOWN"

    detected = result.handedness[index][0].category_name

    if detected == "Left":
        return "Right"

    if detected == "Right":
        return "Left"

    return "UNKNOWN"


def draw_text(frame, text, x, y, color=(255, 255, 255)):
    cv2.putText(
        frame,
        text,
        (x, y),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.6,
        color,
        2
    )


def draw_command_log(frame, command_log):
    """최근 인식 명령을 우측 하단에 스택으로 표시. 최신이 맨 아래, 밝게."""
    if not command_log:
        return

    height, width = frame.shape[:2]
    font = cv2.FONT_HERSHEY_SIMPLEX
    scale, thick, line_h, pad = 0.55, 1, 24, 8

    lines = [f"{t:.1f}s  {cmd}" for t, cmd in command_log]
    box_w = max(cv2.getTextSize(s, font, scale, thick)[0][0] for s in lines) + pad * 2
    box_h = line_h * len(lines) + pad
    x0, y0 = width - box_w - 10, height - box_h - 10

    # 반투명 검은 배경
    overlay = frame.copy()
    cv2.rectangle(overlay, (x0, y0), (width - 10, height - 10), (0, 0, 0), -1)
    cv2.addWeighted(overlay, 0.55, frame, 0.45, 0, frame)

    for i, s in enumerate(lines):
        newest = i == len(lines) - 1
        color = (0, 255, 255) if newest else (180, 180, 180)  # 최신 = 노랑, 이전 = 회색
        cv2.putText(frame, s, (x0 + pad, y0 + line_h * (i + 1)), font, scale, color,
                    thick + (1 if newest else 0))


def start_youtube():
    """유튜브 제어 스레드 시작. 명령이 오면 유튜브 창을 자동으로 앞으로 가져오고
    (창 활성화 -> 탭 전환 -> 영상 플레이어 포커스) 단축키를 보낸다. 실제 작업은 youtube_control 이 한다."""
    from youtube_control.common import Command
    from youtube_control.worker import ControlWorker

    worker = ControlWorker()
    worker.start()
    worker.ready.wait(timeout=10)

    commands = {
        "PLAY_PAUSE": Command.PLAY_PAUSE,
        "SEEK_FORWARD": Command.SEEK_FORWARD_10,
        "SEEK_BACKWARD": Command.SEEK_BACK_10,
        "VOLUME_UP": Command.VOLUME_UP,
        "VOLUME_DOWN": Command.VOLUME_DOWN,
        "FULLSCREEN_ON": Command.FULLSCREEN_ON,
        "FULLSCREEN_OFF": Command.FULLSCREEN_OFF,
    }
    return worker, commands


def main():
    parser = argparse.ArgumentParser(description="손 제스처 유튜브 제어")
    parser.add_argument("--test", action="store_true", help="유튜브를 건드리지 않고 인식만 한다")
    args = parser.parse_args()

    worker, youtube_commands = (None, {}) if args.test else start_youtube()
    print("[테스트] 유튜브에 키를 보내지 않습니다." if args.test
          else "[실제 제어] 명령마다 유튜브 창을 자동으로 앞으로 가져와 키를 보냅니다.", flush=True)

    options = HandLandmarkerOptions(
        base_options=BaseOptions(
            model_asset_path=str(MODEL_PATH)
        ),
        running_mode=RunningMode.VIDEO,
        num_hands=2
    )

    controller = GestureController()
    fullscreen_tracker = FullscreenTracker()
    last_fs_state = None

    trackers = {
        name: SwingTracker(
            name=name,
            cooldown=0.3,  # 원본 1.5초. 다시 가운데로 와야 준비되므로 짧게. 반대 방향은 SeekGate 가 3초 막음
            vertical_threshold=0.15 if ENABLE_VOLUME else float("inf")
        )
        for name in ("Left", "Right")
    }
    gate = SeekGate()  # 반대 방향 3초 / 주먹으로 전환 (두 손 공통)
    recorder = ClipRecorder()
    print("[clip] 명령마다 직전 1.5초를 clips/ 에 저장. F8 = 방금 명령 오작동, F9 = 했는데 안 나옴", flush=True)

    cap = cv2.VideoCapture(0)
    # 크기를 바꿀 수 있는 창으로 만들어 작게 띄운다 (화면에 그리는 글자도 같이 축소된다)
    cv2.namedWindow(WINDOW_NAME, cv2.WINDOW_NORMAL)
    pinned = False
    last_topmost = 0.0
    last_activity = time.monotonic()  # 마지막 명령(주먹 전환 포함) 시각 — 자동 OFF 기준

    if not cap.isOpened():
        raise RuntimeError("웹캠을 열 수 없습니다.")

    start_time = time.monotonic()
    last_timestamp = -1
    last_command = "NONE"
    loop_times = deque(maxlen=30)  # 최근 30프레임 루프 시작 시각 (FPS 이동평균)
    detect_ms = 0.0  # 직전 손 검출 소요 시간(ms)
    command_log = deque(maxlen=5)  # 최근 인식 명령 5개 (우측 하단 로그 스택)

    try:
        with HandLandmarker.create_from_options(options) as detector:
            while True:
                loop_times.append(time.perf_counter())  # 루프 1회 시작 시각 기록
                ret, frame = cap.read()

                if not ret:
                    print("프레임을 읽을 수 없습니다.")
                    break

                frame = cv2.flip(frame, 1)

                rgb = cv2.cvtColor(
                    frame,
                    cv2.COLOR_BGR2RGB
                )

                mp_image = mp.Image(
                    image_format=mp.ImageFormat.SRGB,
                    data=rgb
                )

                timestamp_ms = int(
                    (time.monotonic() - start_time) * 1000
                )
                timestamp_ms = max(
                    timestamp_ms,
                    last_timestamp + 1
                )
                last_timestamp = timestamp_ms

                t_detect = time.perf_counter()  # 검출 시작
                result = detector.detect_for_video(
                    mp_image,
                    timestamp_ms
                )
                detect_ms = (time.perf_counter() - t_detect) * 1000  # 검출 소요 ms

                hand_data = []
                seen_hands = set()

                if result.hand_landmarks:
                    for i, hand in enumerate(result.hand_landmarks):
                        draw_landmarks(frame, hand)

                        name = get_handedness(result, i)
                        # 3D 랜드마크는 엄지 각도·돌출 거리와 OK 사인의 손가락 각도에 쓴다.
                        # 네 손가락 접힘/편 손은 화면 좌표가 더 잘 잡혀서 그대로 둔다.
                        world = result.hand_world_landmarks[i]
                        static = recognize_gesture(hand, name, world)

                        hand_data.append({
                            "name": name,
                            "landmarks": hand,
                            "static": static,
                            "thumb": thumb_pose(hand, world),  # "UP"/"DOWN"/None
                            "fist": is_fist(hand),             # 네 손가락 접힘 (따봉도 포함)
                            "true_fist": is_true_fist(hand, world),  # 엄지까지 접은 주먹
                            "open": is_relaxed_open(hand),     # 편 손
                            "info": thumb_info(hand, world)    # 진단 기록용
                        })

                        if name in trackers:
                            seen_hands.add(name)

                static_gestures = [
                    item["static"] for item in hand_data
                ]

                high_priority_active = any(
                    gesture in ("V_SIGN", "PLAY_PAUSE")
                    for gesture in static_gestures
                )

                # V/OK는 기존 우선순위를 유지한다. 손은 트래커 안에서 화면 x좌표로
                # 정렬하므로 handedness 라벨이 흔들려도 전체화면 추적은 유지된다.
                # 한 손만 보이는 프레임도 넘긴다 (놓친 손은 트래커가 마지막 위치로 이어 본다).
                fullscreen_command, fullscreen_active = fullscreen_tracker.update(
                    [item["landmarks"] for item in hand_data],
                    opens=[item["open"] for item in hand_data],
                    enabled=controller.enabled and not high_priority_active
                )
                if fullscreen_active:
                    # 누락된 손의 스윙 기록도 지워 복귀 시 이전 동작이 발화하지 않게 한다.
                    for tracker in trackers.values():
                        tracker.reset()
                if DEBUG_FULLSCREEN and fullscreen_tracker.state != last_fs_state:
                    print(
                        f"[FS] {fullscreen_tracker.state} "
                        f"distance={fullscreen_tracker.distance:.3f} "
                        f"delta={fullscreen_tracker.delta:+.3f} "
                        f"active={fullscreen_active}"
                    )
                    last_fs_state = fullscreen_tracker.state

                candidates = list(static_gestures)
                motion_sources = {}

                # 주먹을 0.25초 쥐면: 방금 방향을 3초 막고 반대 방향을 푼다
                # 방향 전환은 엄지까지 접은 진짜 주먹만 인정한다 (따봉/엄지 아래는 제외)
                fist_visible = any(item["true_fist"] for item in hand_data)
                fist_switched = False
                if gate.update_fist(
                    fist_visible,
                    allowed=controller.enabled
                    and not high_priority_active and not fullscreen_active
                ):
                    print(f"FIST: now only {gate.last_seek}")
                    trace("gate", "FIST", "", "", "", "", "", "", "", "", "", gate.last_seek)
                    command_log.append(
                        (time.monotonic() - start_time, f"FIST > {gate.last_seek[5:]} only")
                    )
                    last_activity = time.monotonic()
                    fist_switched = True

                for item in hand_data:
                    name = item["name"]

                    if name not in trackers:
                        continue

                    tracker = trackers[name]

                    allow_motion = (
                        controller.enabled
                        and not high_priority_active
                        and not fullscreen_active
                    )

                    # 손 모양에 관계없이 이동 방향만 검사
                    motion = tracker.update(
                        item["landmarks"],
                        allow_motion=allow_motion,
                        # 잠긴 방향은 판정기에서 아예 인식하지 않는다
                        blocked=[c for c in SEEK_COMMANDS if not gate.allows(c)],
                        thumb=item["thumb"] if ENABLE_VOLUME else None,
                        fist=item["fist"],
                        open_hand=item["open"],
                        info=item["info"]
                    )

                    if motion is not None:
                        candidates.append(motion)
                        motion_sources.setdefault(
                            motion, []
                        ).append(name)

                    height, width = frame.shape[:2]
                    wrist = item["landmarks"][0]

                    x = int(wrist.x * width)
                    y = int(wrist.y * height) + 25

                    x = max(0, min(x, width - 230))
                    y = max(25, min(y, height - 10))

                    label = (
                        motion
                        if motion is not None
                        else item["static"]
                    )

                    draw_text(
                        frame,
                        f"{name}: {label}",
                        x, y,
                        (255, 255, 0)
                    )

                    if tracker.debug:  # 스윙 각도 변화 / 손목 이동 (값 조정용)
                        draw_text(frame, tracker.debug, x, min(y + 25, height - 10), (0, 200, 255))

                for name, tracker in trackers.items():
                    if name not in seen_hands:
                        tracker.mark_missing()

                selected = select_gesture(candidates)

                if not hand_data:
                    controller.reset_tracking()
                    command = None
                else:
                    command = controller.update(selected)

                # Fullscreen 명령은 원본 select_gesture의 PRIORITY에 없으므로
                # 직접 전달한다. 이 프레임의 일반 이동 후보는 위에서 차단된다.
                if fullscreen_command is not None:
                    command = fullscreen_command
                    selected = fullscreen_command
                    # 전체화면 뒤에는 다른 명령을 FS_COMMAND_LOCK 초만 막는다 (공통 쿨다운 0.8초 대신).
                    # 실측(11-17): 양손 동작이 볼륨으로 잡힌 오인식은 전부 0.03초 안이었다.
                    controller.last_command_time = (
                        time.monotonic() - (controller.cooldown - FS_COMMAND_LOCK)
                    )

                recorder.push(hand_data, controller.enabled, frame.shape, command)
                if fist_switched:
                    recorder.on_command("FIST")
                if command is not None:
                    recorder.on_command(command)

                if command is not None:
                    last_command = command
                    last_activity = time.monotonic()
                    print(f"Command: {command}")
                    if worker is not None and command in youtube_commands:
                        worker.submit(youtube_commands[command])
                    command_log.append(  # (시작 후 경과 초, 명령) 기록
                        (time.monotonic() - start_time, command)
                    )

                    if command in ("CONTROL_ON", "CONTROL_OFF"):
                        fullscreen_tracker.reset_motion()
                        fullscreen_tracker.last_seen_time = None
                        for tracker in trackers.values():
                            tracker.reset()

                    elif command in motion_sources:
                        for name in motion_sources[command]:
                            trackers[name].lock()

                    if command in SEEK_COMMANDS:
                        gate.on_seek(command)  # 반대 방향 3초 막기 시작

                # 자동 OFF: 영상을 보는 동안 생활 동작(손 흔들기·손짓)이 SEEK 로 잡히는 것을 막는다.
                # 다시 쓰려면 V 사인 1초.
                idle = time.monotonic() - last_activity
                if controller.enabled and idle > AUTO_OFF_SEC:
                    controller.enabled = False
                    controller.reset_tracking()
                    fullscreen_tracker.reset_motion()
                    fullscreen_tracker.last_seen_time = None
                    for tracker in trackers.values():
                        tracker.reset()
                    last_command = "CONTROL_OFF (auto)"
                    print(f"Command: CONTROL_OFF (자동, {AUTO_OFF_SEC:.0f}초 동안 명령 없음)")
                    command_log.append((time.monotonic() - start_time, "AUTO OFF"))

                status = "ON" if controller.enabled else "OFF"

                status_color = (
                    (0, 255, 0)
                    if controller.enabled
                    else (0, 0, 255)
                )

                draw_text(
                    frame,
                    f"Control: {status}"
                    + (f" (off in {max(0.0, AUTO_OFF_SEC - idle):.0f}s)" if controller.enabled else ""),
                    15, 35,
                    status_color
                )

                draw_text(
                    frame,
                    f"Hands detected: {len(hand_data)}",
                    15, 70,
                    (255, 255, 0)
                )

                draw_text(
                    frame,
                    f"Selected: {selected}",
                    15, 105,
                    (255, 255, 0)
                )

                draw_text(
                    frame,
                    f"Last Command: {last_command}",
                    15, 140,
                    (255, 0, 255)
                )

                draw_text(
                    frame,
                    f"Left: {trackers['Left'].state}",
                    15, 175
                )

                draw_text(
                    frame,
                    f"Right: {trackers['Right'].state}",
                    15, 205
                )

                draw_text(frame, f"FS State: {fullscreen_tracker.state}", 15, 235)
                draw_text(frame, f"FS Distance: {fullscreen_tracker.distance:.3f}", 15, 265)
                draw_text(frame, f"FS Delta: {fullscreen_tracker.delta:+.3f}", 15, 295)
                draw_text(frame, f"FS Active: {fullscreen_active}", 15, 325)

                draw_text(
                    frame,
                    "ESC: EXIT   F8: misfire   F9: missed",
                    15,
                    frame.shape[0] - 20
                )

                # FPS = 최근 30프레임 루프 간격 평균 (오른쪽 위 표시)
                if len(loop_times) >= 2:
                    fps = (len(loop_times) - 1) / (loop_times[-1] - loop_times[0])
                else:
                    fps = 0.0
                fw = frame.shape[1]  # 오른쪽 정렬용 프레임 너비
                draw_text(frame, f"FPS: {fps:.1f}", fw - 170, 35, (0, 255, 255))  # FPS 표시
                draw_text(frame, f"Detect: {detect_ms:.0f} ms", fw - 170, 70, (0, 255, 255))  # 검출 시간 표시

                # SEEK 가능 여부 (막혀 있으면 남은 초)
                for i, cmd in enumerate(SEEK_COMMANDS):
                    left = gate.remaining(cmd)
                    draw_text(
                        frame,
                        f"{cmd[5:]}: " + ("OK" if left == 0 else f"blocked {left:.1f}s"),
                        fw - 250, 105 + 30 * i,
                        (0, 255, 0) if left == 0 else (0, 0, 255)
                    )

                draw_command_log(frame, command_log)  # 우측 하단 명령 로그 (최신이 맨 아래)

                cv2.imshow(WINDOW_NAME, frame)

                # 첫 프레임에서 크기·위치를 잡고, 이후에는 주기적으로 '항상 위'만 다시 건다.
                # 포커스는 건드리지 않으므로 유튜브가 키 입력을 계속 받는다.
                if not pinned:
                    fh, fw = frame.shape[:2]
                    cv2.resizeWindow(WINDOW_NAME, PREVIEW_WIDTH, int(fh * PREVIEW_WIDTH / fw))
                    cv2.waitKey(1)
                    pinned = pin_top_right(WINDOW_NAME)
                    last_topmost = time.monotonic()
                elif time.monotonic() - last_topmost > TOPMOST_EVERY:
                    keep_on_top(WINDOW_NAME)
                    last_topmost = time.monotonic()

                key = cv2.waitKey(1) & 0xFF
                if key == 27:
                    break
                mark = recorder.poll_keys(key)
                if mark:
                    command_log.append((time.monotonic() - start_time, mark))

    finally:
        cap.release()
        cv2.destroyAllWindows()


if __name__ == "__main__":
    main()

