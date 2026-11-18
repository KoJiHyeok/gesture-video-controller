"""명령이 나갈 때마다 '직전 1.5초 손 좌표'만 잘라 저장한다 (오작동 분석용).

저장 위치: clips/YYYYMMDD_HHMMSS(실행 시작)/
  HHMMSS_<명령>.csv   프레임별 21개 랜드마크 x,y,z + 그 프레임의 판정(정적 제스처·엄지·주먹·편 손)
  HHMMSS_<명령>.png   손 뼈대만 그린 그림 (오래된 프레임 = 어둡게, 마지막 = 밝게) + 손목 궤적

표시 키 (유튜브에 포커스가 있어도 동작하는 전역 키 — 미리보기 창을 클릭할 필요 없음):
  F8  = 방금 나간 명령은 오작동  -> 마지막 클립 파일 이름에 _MISFIRE 를 붙인다
  F9  = 제스처를 했는데 명령이 안 나옴 -> 직전 3초를 _MISSED 클립으로 저장한다
  (미리보기 창에 포커스가 있을 때는 x / m 키도 같은 동작)

다시 보기: python tests/view_clip.py clips/<폴더>   (뼈대 애니메이션 재생)
"""
import csv
import ctypes
import sys
import time
from collections import deque
from pathlib import Path

import cv2
import numpy as np

CLIP_ENABLED = True
CLIP_SEC = 1.5        # 명령 클립 길이 (명령 직전)
MISSED_SEC = 3.0      # '안 나옴' 클립 길이 — 동작 후 키를 누르기까지 반응 시간이 있어서 더 길게
MARK_WINDOW = 10.0    # F8 은 이 시간(초) 안에 나간 명령에만 붙는다
VK_MISFIRE, VK_MISSED = 0x77, 0x78  # F8, F9
KEY_MISFIRE, KEY_MISSED = ord("x"), ord("m")

CLIP_ROOT = Path(__file__).resolve().parent.parent / "clips"

CONNECTIONS = [
    (0, 1), (1, 2), (2, 3), (3, 4),
    (0, 5), (5, 6), (6, 7), (7, 8),
    (5, 9), (9, 10), (10, 11), (11, 12),
    (9, 13), (13, 14), (14, 15), (15, 16),
    (13, 17), (17, 18), (18, 19), (19, 20),
    (0, 17),
]
HAND_COLOR = {"Left": (255, 200, 0), "Right": (0, 160, 255)}  # BGR: 왼손 하늘색, 오른손 주황
FIELDS = ["t", "hand", "static", "thumb", "fist", "true_fist", "open", "enabled", "command"] + [
    f"{a}{i}" for i in range(21) for a in "xyz"
]


class _GlobalKeys:
    """GetAsyncKeyState 로 전역 키 눌림(올라갔다 내려간 순간)만 잡는다. Windows 외에서는 아무것도 안 함."""

    def __init__(self, vks):
        self.vks = vks
        self.down = {vk: False for vk in vks}
        self.u32 = None
        if sys.platform == "win32":
            # windll.user32 는 프로세스 공용 — 여기서 argtypes 를 건드리면 다른 모듈이 깨진다 (window_pin 참고)
            self.u32 = ctypes.WinDLL("user32")
            self.u32.GetAsyncKeyState.argtypes = [ctypes.c_int]
            self.u32.GetAsyncKeyState.restype = ctypes.c_short

    def pressed(self):
        if self.u32 is None:
            return []
        hit = []
        for vk in self.vks:
            now = bool(self.u32.GetAsyncKeyState(vk) & 0x8000)
            if now and not self.down[vk]:
                hit.append(vk)
            self.down[vk] = now
        return hit


class ClipRecorder:
    def __init__(self):
        self.enabled = CLIP_ENABLED
        self.buf = deque()          # (t, enabled, [hand dict...], command)
        self.size = None            # (w, h) — 그림 비율용
        self.dir = None             # 첫 저장 때 만든다 (켜기만 하고 명령 없으면 폴더도 없음)
        self.last_clip = None       # (t, csv_path, png_path) — F8 대상
        self.keys = _GlobalKeys([VK_MISFIRE, VK_MISSED])

    # ---- 매 프레임 ----
    def push(self, hand_data, enabled, frame_shape, command=None):
        if not self.enabled:
            return
        t = time.monotonic()
        self.size = (frame_shape[1], frame_shape[0])
        hands = [{
            "name": h["name"],
            "static": h["static"],
            "thumb": h["thumb"] or "",
            "fist": h["fist"],
            "true_fist": h["true_fist"],
            "open": h["open"],
            "pts": [(lm.x, lm.y, lm.z) for lm in h["landmarks"]],
        } for h in hand_data]
        self.buf.append((t, enabled, hands, command))
        while self.buf and t - self.buf[0][0] > MISSED_SEC + 0.2:
            self.buf.popleft()

    def poll_keys(self, window_key):
        """전역 F8/F9 + 미리보기 창 x/m. 화면 로그에 띄울 문자열(없으면 None)을 돌려준다."""
        if not self.enabled:
            return None
        hits = self.keys.pressed()
        if VK_MISFIRE in hits or window_key == KEY_MISFIRE:
            return self.mark_misfire()
        if VK_MISSED in hits or window_key == KEY_MISSED:
            return self.save("MISSED", MISSED_SEC)
        return None

    # ---- 저장 ----
    def on_command(self, command):
        """명령이 나간 프레임에서 호출 (push 뒤에)."""
        if not self.enabled:
            return None
        return self.save(command, CLIP_SEC)

    def save(self, label, seconds):
        if not self.buf:
            return None
        t_end = self.buf[-1][0]
        frames = [f for f in self.buf if t_end - f[0] <= seconds]
        if self.dir is None:
            self.dir = CLIP_ROOT / time.strftime("%Y%m%d_%H%M%S")
            self.dir.mkdir(parents=True, exist_ok=True)
        stem = time.strftime("%H%M%S") + f"_{int((t_end % 1) * 1000):03d}_{label}"
        csv_path = self.dir / f"{stem}.csv"
        png_path = self.dir / f"{stem}.png"
        with open(csv_path, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(FIELDS)
            for t, en, hands, cmd in frames:
                rel = f"{t - t_end:.3f}"
                if not hands:
                    w.writerow([rel, "NONE", "", "", "", "", "", en, cmd or ""] + [""] * 63)
                for h in hands:
                    coords = [f"{v:.4f}" for p in h["pts"] for v in p]
                    w.writerow([rel, h["name"], h["static"], h["thumb"], h["fist"], h["true_fist"],
                                h["open"], en, cmd or ""] + coords)
        cv2.imwrite(str(png_path), render(frames, self.size, f"{label}  ({seconds:.1f}s)"))
        if label != "MISSED":
            self.last_clip = (t_end, csv_path, png_path)
        print(f"[clip] {csv_path.name}")
        return f"clip {label}"

    def mark_misfire(self):
        if self.last_clip is None or time.monotonic() - self.last_clip[0] > MARK_WINDOW:
            print(f"[clip] F8: 최근 {MARK_WINDOW:.0f}초 안에 나간 명령이 없어 표시하지 않음")
            return "F8: no recent command"
        _, csv_path, png_path = self.last_clip
        new = []
        for p in (csv_path, png_path):
            q = p.with_name(p.stem + "_MISFIRE" + p.suffix)
            p.rename(q)
            new.append(q)
        self.last_clip = None  # 같은 클립에 두 번 붙지 않게
        print(f"[clip] 오작동 표시: {new[0].name}")
        return "MARKED MISFIRE"


def render(frames, size, title, scale=1.0):
    """손 뼈대만 그린 그림. 시간이 지날수록 밝게, 손목은 궤적 선으로."""
    w, h = size or (640, 480)
    w, h = int(w * scale), int(h * scale)
    img = np.zeros((h, w, 3), np.uint8)
    n = len(frames)
    trails = {}
    for k, (t, en, hands, cmd) in enumerate(frames):
        a = 0.15 + 0.85 * (k + 1) / max(n, 1)  # 오래된 프레임 0.15 -> 마지막 1.0
        last = k == n - 1
        for hd in hands:
            base = HAND_COLOR.get(hd["name"], (200, 200, 200))
            color = tuple(int(c * a) for c in base)
            pts = [(int(x * w), int(y * h)) for x, y, _ in hd["pts"]]
            for s, e in CONNECTIONS:
                cv2.line(img, pts[s], pts[e], color, 2 if last else 1, cv2.LINE_AA)
            if last:
                for p in pts:
                    cv2.circle(img, p, 3, (255, 255, 255), -1, cv2.LINE_AA)
            trails.setdefault(hd["name"], []).append(pts[0])
    for name, tr in trails.items():
        if len(tr) > 1:
            cv2.polylines(img, [np.array(tr, np.int32)], False, (255, 255, 255), 1, cv2.LINE_AA)
    cv2.putText(img, title, (10, 28), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)
    cv2.putText(img, "Left", (10, h - 36), cv2.FONT_HERSHEY_SIMPLEX, 0.55, HAND_COLOR["Left"], 2)
    cv2.putText(img, "Right", (10, h - 12), cv2.FONT_HERSHEY_SIMPLEX, 0.55, HAND_COLOR["Right"], 2)
    return img
