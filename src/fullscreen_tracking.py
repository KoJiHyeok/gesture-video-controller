"""Two-hand fullscreen detection; update returns (command, motion_active).

로컬 수정 (2026-11-17, upstream 65562b4 기준):
  A. 방향 고정 — 벌리기 = FULLSCREEN_ON, 모으기 = FULLSCREEN_OFF.
     단 같은 명령은 연달아 내지 않는다: ON 상태에서 벌리기, OFF 상태에서 모으기는 무시
     (2026-11-17 사용자 지침: "ON 인데 또 ON 이 되면 안 된다").
     self.fullscreen 이 프로그램이 아는 현재 상태다. 실제 화면과 어긋나면
     (키보드로 바꿨거나 오인식) 반대 동작을 한 번 해야 맞춰진다.
  B. 손을 잠깐 놓쳐도 동작을 이어 본다.
     실측(11-17 20:13~20:21): 양손 추적이 끊긴 97번 중 79번이 화면 끝이 아니라
     움직이는 도중(모션 블러)이었고, 대부분 0.25초 안에 돌아왔다.
     - 한 손만 보이면 안 보이는 손은 마지막 위치에 둔 채 계속 계산한다.
     - 둘 다 안 보여도 missing_grace 동안은 기록을 지우지 않고, 손이 돌아오면
       끊기기 전 기록과 비교해 판정한다 (빠르게 벌려 화면 밖으로 나간 경우 포함).
"""

import time
from collections import deque


DUPLICATE_GAP = 0.06  # 두 손목이 이보다 가까우면 같은 손을 두 번 검출한 것으로 본다
OPEN_RATIO = 0.8      # 동작 구간에서 두 손이 다 편 손이었던 프레임 비율이 이 이상이어야 전체화면
BALANCE = 0.3         # 덜 움직인 손이 더 움직인 손의 이 비율 이상 움직여야 양손 동작


class FullscreenTracker:
    def __init__(
        self, min_change=0.14, window=2.0, cooldown=1.2,
        min_hand_motion=0.025, missing_grace=0.5, confirm_frames=2,
        start_change=0.04, start_hand_motion=0.01, motion_timeout=0.35,
    ):
        if not (0 < start_change <= min_change and
                0 < start_hand_motion <= min_hand_motion):
            raise ValueError("Start thresholds must be positive and <= detection thresholds")
        if min(window, cooldown, missing_grace, motion_timeout) <= 0:
            raise ValueError("Time limits must be positive")
        if not isinstance(confirm_frames, int) or confirm_frames < 1:
            raise ValueError("confirm_frames must be a positive integer")
        self.min_change = min_change
        self.window = window
        self.cooldown = cooldown
        self.min_hand_motion = min_hand_motion
        self.missing_grace = missing_grace  # 원본 0.25 -> 0.5 (B)
        self.confirm_frames = confirm_frames
        self.start_change = start_change
        self.start_hand_motion = start_hand_motion
        self.motion_timeout = motion_timeout
        self.fullscreen = False  # 프로그램이 아는 현재 상태 (True 면 다음은 OFF 만 받는다)
        self.last_command_time = -float("inf")
        self.history = deque()
        self.last_seen_time = None   # 두 손이 마지막으로 다 보인 시각
        self.last_pair = None        # 그때(또는 한 손으로 갱신한) 두 손 x (x1 <= x2)
        self.confirm_count = 0
        self.state = "WAIT_HANDS"
        self.distance = 0.0
        self.delta = 0.0
        self.motion_active = False
        self._direction = 0
        self._last_progress_time = None
        self._peak_progress = 0.0

    def center(self, hand):
        """손 위치 = 손목(0번). 원본은 손바닥 중심(0,5,9,13,17 평균)이었다.

        SEEK 스윙은 손목을 고정하고 손을 좌우로 꺾는 동작이라 손바닥 중심은 크게 움직이지만
        손목은 거의 안 움직인다. 손목으로 재면 한 손 스윙이 '양손 거리 변화'로 잡히지 않는다
        (2026-11-18 사용자 보고: SEEK 중 전체화면 오작동).
        """
        return hand[0].x, hand[0].y

    def reset_motion(self):
        """Clear a gesture (history included)."""
        self.history.clear()
        self.confirm_count = 0
        self.delta = 0.0
        self.motion_active = False
        self._direction = 0
        self._last_progress_time = None
        self._peak_progress = 0.0
        self.state = "READY"

    def _forget_hands(self, state):
        self.reset_motion()
        self.last_seen_time = None
        self.last_pair = None
        self.distance = 0.0
        self.state = state

    def update(self, hands, enabled=True, opens=None):
        """hands = 이번 프레임에 검출된 손 랜드마크 목록 (0~2개, 순서 무관).
        opens = 같은 순서로 각 손이 편 손인지. 주면 손바닥을 편 동작만 전체화면으로 받는다."""
        now = time.monotonic()
        if not enabled:
            self._forget_hands("DISABLED")
            return None, False

        hands = list(hands)[:2]
        # 보이는 손이 전부 편 손인가 (주먹을 쥔 채 벌리고 모으는 것은 전체화면이 아니다)
        all_open = True if opens is None else all(list(opens)[:len(hands)])
        xs = sorted(self.center(h)[0] for h in hands)
        if len(xs) == 2 and xs[1] - xs[0] < DUPLICATE_GAP:
            # 같은 손을 두 번 검출한 것 (빠르게 움직일 때 생긴다, 11-18 실측 26프레임) -> 한 손
            xs = xs[:1]
        within_grace = (self.last_seen_time is not None and
                        now - self.last_seen_time <= self.missing_grace)

        if len(xs) == 2:
            if not within_grace and self.last_seen_time is not None:
                self.reset_motion()  # 오래 끊겼다 돌아옴 -> 새 동작
            x1, x2 = xs
            self.last_seen_time = now
            self.last_pair = (x1, x2)
        elif within_grace and len(xs) == 1:
            # 보이는 손은 가까운 쪽으로 갱신, 안 보이는 손은 마지막 위치 유지
            a, b = self.last_pair
            x = xs[0]
            x1, x2 = sorted((x, b) if abs(x - a) <= abs(x - b) else (a, x))
            self.last_pair = (x1, x2)
        elif within_grace:
            # 둘 다 안 보임: 기록은 지우지 않고 기다린다 (새 샘플도 넣지 않음)
            self.confirm_count = 0
            self.state = "HAND_MISSING"
            return None, self.motion_active
        else:
            self._forget_hands("WAIT_HANDS")
            return None, False

        self.distance = x2 - x1

        if now - self.last_command_time < self.cooldown:
            self.reset_motion()
            self.state = "COOLDOWN"
            return None, False

        sample = (now, x1, x2, self.distance, all_open)
        self.history.append(sample)
        while self.history and now - self.history[0][0] > self.window:
            self.history.popleft()
        if len(self.history) < 3:
            self.state = "READY"
            return None, False

        # 지금 상태에서 의미 있는 방향만 본다: ON 이면 모으기(OFF)만, OFF 면 벌리기(ON)만.
        # 같은 명령이 연달아 나가지 않게 하고, 의미 없는 방향의 동작은 스윙을 막지도 않는다.
        best = None
        for direction, pick in (((-1, max),) if self.fullscreen else ((1, min),)):
            start = pick(self.history, key=lambda p: p[3])
            progress = direction * (self.distance - start[3])
            if best is None or progress > best[2]:
                best = (direction, start, progress)
        direction, (start_time, start_x1, start_x2, start_distance, _), progress = best
        # 동작 구간(시작 샘플 이후)에서 편 손 프레임 비율. 정상 동작은 직전 0.8초 거의 100%,
        # 주먹으로 벌린 경우는 편 손 0~66% 였다 (11-18 실측).
        span = [p[4] for p in self.history if p[0] >= start_time]
        open_ratio = sum(span) / len(span)

        if self.motion_active and direction != self._direction:
            # 진행 중이던 방향이 뒤집힘 = 원위치하는 동작. 이전 동작은 버린다.
            self.reset_motion()
            self.history.append(sample)
            return None, False

        self.delta = self.distance - start_distance
        left_motion = -direction * (x1 - start_x1)
        right_motion = direction * (x2 - start_x2)
        # 매 프레임 '편 손'을 요구하면 빠르게 움직일 때 한두 프레임 블러로 끊겨서, 구간 비율만 본다.
        started = (now > start_time and open_ratio >= OPEN_RATIO
                   and progress >= self.start_change
                   and left_motion >= self.start_hand_motion
                   and right_motion >= self.start_hand_motion)
        # 양손 동작은 두 손이 비슷하게 움직인다. 한 손만 크게 움직이고 다른 손은 조금 흔들린 것은 거른다.
        balanced = min(left_motion, right_motion) >= BALANCE * max(left_motion, right_motion)
        detected = (started and balanced and progress >= self.min_change
                    and left_motion >= self.min_hand_motion
                    and right_motion >= self.min_hand_motion)

        if started:
            if not self.motion_active or progress > self._peak_progress + 0.002:
                self._last_progress_time = now
                self._peak_progress = progress
            self.motion_active = True
            self._direction = direction
        if self.motion_active and (
                not started or now - self._last_progress_time > self.motion_timeout):
            # Do not repeatedly reacquire a stalled gesture from an old extreme.
            self.reset_motion()
            self.history.append(sample)
            return None, False

        self.state = ("MOVING_OPEN" if direction > 0 else "MOVING_CLOSE") \
            if self.motion_active else "READY"
        self.confirm_count = self.confirm_count + 1 if detected else 0
        if self.confirm_count >= self.confirm_frames:
            command = "FULLSCREEN_ON" if direction > 0 else "FULLSCREEN_OFF"
            self.fullscreen = command == "FULLSCREEN_ON"
            self.last_command_time = now
            self.reset_motion()
            self.state = command
            return command, True
        return None, self.motion_active
