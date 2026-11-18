
import math
import time


def distance(a, b):
    return math.sqrt(
        (a.x - b.x) ** 2
        + (a.y - b.y) ** 2
        + (a.z - b.z) ** 2
    )


def angle(a, b, c):
    ab = (
        a.x - b.x,
        a.y - b.y,
        a.z - b.z
    )

    cb = (
        c.x - b.x,
        c.y - b.y,
        c.z - b.z
    )

    dot = sum(
        x * y for x, y in zip(ab, cb)
    )

    na = math.sqrt(
        sum(x * x for x in ab)
    )

    nc = math.sqrt(
        sum(x * x for x in cb)
    )

    if na * nc < 1e-8:
        return 0.0

    cosine = max(
        -1.0,
        min(1.0, dot / (na * nc))
    )

    return math.degrees(
        math.acos(cosine)
    )


def finger_extended(lm, mcp, pip, tip):
    return angle(
        lm[mcp], lm[pip], lm[tip]
    ) > 155


def finger_folded(lm, mcp, pip, tip):
    return angle(
        lm[mcp], lm[pip], lm[tip]
    ) < 125


def is_v_sign(lm):
    index_open = finger_extended(
        lm, 5, 6, 8
    )

    middle_open = finger_extended(
        lm, 9, 10, 12
    )

    ring_folded = finger_folded(
        lm, 13, 14, 16
    )

    pinky_folded = finger_folded(
        lm, 17, 18, 20
    )

    spread = angle(
        lm[8], lm[5], lm[12]
    ) > 15

    return (
        index_open
        and middle_open
        and ring_folded
        and pinky_folded
        and spread
    )


OK_OTHERS_MIN = 120  # OK 사인에서 중지·약지·새끼의 최소 관절 각도 (3D, 도)


def is_ok(lm, world=None):
    """엄지-검지 끝이 붙고 나머지 세 손가락이 펴진 자세.

    나머지 세 손가락 기준을 원본 '155도 초과(화면 좌표)'에서 '120도 이상(3D)'으로 낮췄다.
    2026-11-18 실측: OK 를 만든 구간 352프레임에서 세 손가락 중 가장 굽은 손가락의 3D 각도는
    중앙값 138도, 하위 10% 133도 (OK 자세에서는 중지가 자연스럽게 휜다).
    921프레임 중 155도를 넘은 건 4프레임뿐이라 OK 가 거의 인식되지 않았다.
    주먹은 같은 값이 96도 이하라 120도면 충분히 갈린다.
    """
    palm = max(
        distance(lm[0], lm[9]),
        1e-6
    )

    touching = (
        distance(lm[4], lm[8]) / palm
    ) < 0.35

    joints = lm if world is None else world
    others_open = all(
        angle(joints[a], joints[b], joints[c]) >= OK_OTHERS_MIN
        for a, b, c in ((9, 10, 12), (13, 14, 16), (17, 18, 20))
    )

    return touching and others_open


def is_fist(lm):
    return all([
        finger_folded(lm, 5, 6, 8),
        finger_folded(lm, 9, 10, 12),
        finger_folded(lm, 13, 14, 16),
        finger_folded(lm, 17, 18, 20)
    ])


def thumb_pose(lm, world=None, margin=0.02):
    """엄지만 편 자세. 엄지가 위(따봉)면 "UP", 아래면 "DOWN", 아니면 None.

    조건: 네 손가락은 접힘 + 엄지는 펴짐
          + 엄지 끝이 다른 손가락 전부보다 margin 이상 위(UP) 또는 아래(DOWN).

    lm    = 화면 좌표 랜드마크 (네 손가락 접힘, 위/아래 판단. 위로 갈수록 y 가 작다)
    world = 3D 랜드마크(미터 단위). 주면 엄지 각도는 이걸로 잰다.
    네 손가락 접힘은 화면 좌표가 더 잘 잡혔다 (2026-11-15 15:48 실측: 같은 프레임에서
    3D 쪽이 6~7% 더 놓침). 그래서 엄지 각도만 3D 를 쓴다.

    '엄지가 세로 방향' 조건은 뺐다 (2026-11-15 실측): 엄지를 아래로 내리면 손목이 덜 돌아가
    엄지가 비스듬해져서, 엄지 아래 프레임의 74% 가 그 조건 하나로 탈락했다.
    """
    joints = lm if world is None else world

    if not is_fist(lm):
        return None

    if angle(joints[2], joints[3], joints[4]) < 150:  # 엄지가 굽어 있음
        return None

    others = [lm[i].y for i in range(5, 21)]

    if min(others) - lm[4].y > margin:
        return "UP"

    if lm[4].y - max(others) > margin:
        return "DOWN"

    return None


PALM_FACING_MAX = -0.005  # 손가락 끝 깊이 - 손가락 뿌리 깊이 (m). 이보다 작으면 손바닥이 카메라를 향한 주먹
#   11-18 14:03 실측: 손바닥 주먹 -13 ~ -38mm, 손등 주먹 +7 ~ +42mm -> 가운데보다 손바닥 쪽으로 5mm 여유


def palm_depth(world):
    """주먹에서 손가락 끝(8,12,16,20)이 손가락 뿌리(5,9,13,17)보다 카메라에 얼마나 가까운가 (3D, m).

    손바닥을 보이며 주먹을 쥐면 말린 손가락 끝이 손바닥 쪽(카메라 쪽)에 오므로 음수,
    손등을 보이며 쥐면 손가락 끝이 손등 뒤로 가서 양수가 된다. (MediaPipe world z 는 작을수록 가깝다)
    """
    tips = sum(world[i].z for i in (8, 12, 16, 20)) / 4
    mcps = sum(world[i].z for i in (5, 9, 13, 17)) / 4
    return tips - mcps


def palm_cross(lm):
    """화면 좌표에서 (손목->검지 뿌리) x (손목->새끼 뿌리) 의 z 성분. 손바닥/손등과 왼/오른손에 따라 부호가 갈린다.
    진단 기록용 (palm_depth 와 어느 쪽이 더 잘 가르는지 실측으로 고르기 위해)."""
    ax, ay = lm[5].x - lm[0].x, lm[5].y - lm[0].y
    bx, by = lm[17].x - lm[0].x, lm[17].y - lm[0].y
    return ax * by - ay * bx


def is_true_fist(lm, world, reach_max=1.3, poke_max=0.02):
    """엄지까지 접은 주먹 (SEEK 방향 전환용). 엄지를 세운 따봉/엄지 아래 자세와 구분한다.

    네 손가락 접힘 + 엄지 끝이 손바닥 가까이(reach) + 엄지 끝이 다른 손가락보다 위/아래로 튀어나오지 않음.
    2026-11-18 실측 (주먹 2881프레임 vs 엄지 자세 562프레임):
      엄지 돌출 거리 reach : 주먹 중앙값 0.91 (90% 가 1.2 이하) / 엄지 자세 5% 가 1.4 이상
      엄지 끝 튀어나옴     : 주먹 98% 가 0.02 미만      / 엄지 자세 5% 가 0.05 이상
    원본은 엄지 끝마디 각도 150도 미만을 요구했는데, 주먹이어도 엄지를 곧게 붙이면 160도가 넘어
    주먹 프레임의 약 30% 를 놓쳤다 (주먹 인식률 저하의 주원인). 그래서 각도 조건을 뺐다.
    """
    if not is_fist(lm):
        return False
    others = [lm[i].y for i in range(5, 21)]
    poke = max(min(others) - lm[4].y, lm[4].y - max(others))  # 엄지 끝이 위/아래로 튀어나온 정도
    # 2026-11-18 사용자 지침: 잠금 주먹은 손바닥이 보이게 쥔 주먹만 인정한다
    # (손등 쪽 주먹은 생활 동작에서 흔해 오작동 원인)
    return (thumb_reach(world) < reach_max and poke < poke_max
            and palm_depth(world) < PALM_FACING_MAX)


def thumb_reach(world):
    """엄지 끝이 손바닥 중심에서 얼마나 떨어졌나 (손바닥 폭 = 5~17 거리로 나눈 값).

    진짜 주먹(엄지 접음)은 0.8 안팎, 엄지를 편 자세는 1.2 이상 (2026-11-15 실측).
    """
    cx = sum(world[i].x for i in (0, 5, 9, 13, 17)) / 5
    cy = sum(world[i].y for i in (0, 5, 9, 13, 17)) / 5
    cz = sum(world[i].z for i in (0, 5, 9, 13, 17)) / 5
    tip = world[4]
    reach = math.sqrt((tip.x - cx) ** 2 + (tip.y - cy) ** 2 + (tip.z - cz) ** 2)
    return reach / max(distance(world[5], world[17]), 1e-6)


def thumb_info(lm, world=None):
    """진단용 한 줄.

    f   = 네 손가락 굽힘 각도 (world 가 있으면 3D 기준)
    th  = 엄지 끝마디 각도(2-3-4), mcp = 엄지 뿌리 각도(1-2-3)
    up/dn = 엄지 끝이 다른 손가락보다 얼마나 위/아래 (화면 좌표)
    reach = 엄지 돌출 거리 / 손바닥 폭
    img = 화면 좌표로 쟀다면 나왔을 판정 (3D 와 비교용)
    """
    j = lm if world is None else world
    f = [angle(j[a], j[b], j[c]) for a, b, c in ((5, 6, 8), (9, 10, 12), (13, 14, 16), (17, 18, 20))]
    others = [lm[i].y for i in range(5, 21)]
    img = "fist" if is_fist(lm) else "open" if is_relaxed_open(lm) else "-"
    return (
        "f=" + "|".join(f"{v:.0f}" for v in f)
        + f" th={angle(j[2], j[3], j[4]):.0f} mcp={angle(j[1], j[2], j[3]):.0f}"
        + f" up={min(others) - lm[4].y:+.3f} dn={lm[4].y - max(others):+.3f}"
        + (f" reach={thumb_reach(world):.2f} pd={palm_depth(world) * 1000:+.0f}mm" if world is not None else "")
        + f" cr={palm_cross(lm):+.4f}"
        + f" img={img}"
    )


def is_relaxed_open(lm):
    fingers = [
        (5, 6, 8),
        (9, 10, 12),
        (13, 14, 16),
        (17, 18, 20)
    ]

    open_count = sum(
        angle(lm[a], lm[b], lm[c]) >= 135
        for a, b, c in fingers
    )

    return open_count >= 3


def recognize_gesture(lm, handedness=None, world=None):
    if is_v_sign(lm):
        return "V_SIGN"

    if is_ok(lm, world):
        return "PLAY_PAUSE"

    return "UNKNOWN"


PRIORITY = {
    "V_SIGN": 1,
    "PLAY_PAUSE": 2,
    "SEEK_FORWARD": 3,
    "SEEK_BACKWARD": 3,
    "VOLUME_UP": 3,
    "VOLUME_DOWN": 3
}


def select_gesture(candidates):
    valid = [
        gesture
        for gesture in candidates
        if gesture in PRIORITY
    ]

    if not valid:
        return "UNKNOWN"

    best_priority = min(
        PRIORITY[g] for g in valid
    )

    selected = {
        g for g in valid
        if PRIORITY[g] == best_priority
    }

    if len(selected) != 1:
        return "UNKNOWN"

    return selected.pop()


class GestureController:
    def __init__(
        self,
        hold_time=1.0,
        cooldown=0.8,
        stable_time=0.15
    ):
        self.hold_time = hold_time
        self.cooldown = cooldown
        self.stable_time = stable_time

        self.enabled = False

        self.current_gesture = "UNKNOWN"
        self.gesture_start = time.monotonic()

        self.v_latched = False
        self.command_latched = False
        self.last_command_time = -float("inf")

    def reset_tracking(self):
        self.current_gesture = "UNKNOWN"
        self.gesture_start = time.monotonic()

        self.v_latched = False
        self.command_latched = False

    def update(self, gesture):
        now = time.monotonic()

        if gesture != self.current_gesture:
            self.current_gesture = gesture
            self.gesture_start = now
            self.command_latched = False

            if gesture != "V_SIGN":
                self.v_latched = False

        elapsed = now - self.gesture_start

        if gesture == "V_SIGN":
            if (
                elapsed >= self.hold_time
                and not self.v_latched
            ):
                self.enabled = not self.enabled
                self.v_latched = True
                self.last_command_time = now

                if self.enabled:
                    return "CONTROL_ON"

                return "CONTROL_OFF"

            return None

        if not self.enabled:
            return None

        if gesture == "UNKNOWN":
            return None

        if self.command_latched:
            return None

        motion_commands = (
            "SEEK_FORWARD",
            "SEEK_BACKWARD",
            "VOLUME_UP",
            "VOLUME_DOWN"
        )

        is_motion = gesture in motion_commands

        # 이동 명령은 한 프레임만 감지되어도 처리
        if (
            not is_motion
            and elapsed < self.stable_time
        ):
            return None

        if (
            now - self.last_command_time
            < self.cooldown
        ):
            return None

        self.command_latched = True
        self.last_command_time = now

        return gesture
