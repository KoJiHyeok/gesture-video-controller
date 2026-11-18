"""traces/*.csv 를 SwingTracker 에 다시 넣어 SEEK 가 어떻게 나왔을지 재현한다.

trace 의 손목 좌표 + 손 각도·크기로 랜드마크 0(손목)·9(중지 뿌리)를 복원하고,
POSE 줄의 엄지 자세 / 주먹 / 편 손 판정을 그대로 넣는다.
한계: SeekGate(반대 방향 3초 잠금)는 넣지 않는다. 원본 결과와 정확히 같지는 않고,
      같은 입력으로 '수정 전 vs 수정 후'를 비교하는 용도다.

사용:
  python tests/replay_swing.py traces/x.csv                       # 현재 src
  python tests/replay_swing.py --src 다른/src traces/x.csv         # 다른 버전
"""

import argparse
import csv
import importlib
import math
import sys
import types
from collections import Counter, OrderedDict
from pathlib import Path

SRC = Path(__file__).resolve().parent.parent / "src"


def load(src):
    sys.path.insert(0, str(src))
    for m in ("swing_tracking", "motion_tracking"):
        sys.modules.pop(m, None)
    mod = importlib.import_module("swing_tracking")
    sys.path.pop(0)
    mod.trace = lambda *a, **k: None
    return mod


def read(path):
    """t -> {hand: {...}} 프레임별 입력."""
    frames = OrderedDict()
    with open(path, encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if row["hand"] not in ("Left", "Right"):
                continue
            d = frames.setdefault(float(row["t"]), {}).setdefault(row["hand"], {})
            ev = row["event"]
            if ev == "POSE":
                head = row["result"].split(" ")[0]          # 예: "UP/fist", "None/open"
                thumb, _, shape = head.partition("/")
                d["thumb"] = None if thumb == "None" else thumb
                d["fist"] = shape == "fist"
                d["open"] = shape == "open"
                d["allow"] = row["allow"] == "True"
            elif ev == "SWING" and row["angle"]:
                a, size = math.radians(float(row["angle"])), float(row["size"])
                wx, wy = float(row["wrist_x"]), float(row["wrist_y"])
                d["lm"] = (wx, wy, wx + size * math.sin(a), wy - size * math.cos(a))
                d["actual"] = row["result"]
            elif ev == "SKIP":
                d["allow"] = False
    return frames


def replay(mod, frames):
    clock = [0.0]
    fake_time = types.SimpleNamespace(monotonic=lambda: clock[0])
    mod.time = fake_time
    sys.modules["motion_tracking"].time = fake_time
    trackers = {h: mod.SwingTracker(name=h, cooldown=0.3, vertical_threshold=0.15) for h in ("Left", "Right")}
    out = []
    for t, hands in frames.items():
        clock[0] = t
        for h, tr in trackers.items():
            d = hands.get(h)
            if not d or "allow" not in d:
                tr.mark_missing()
                continue
            lm = None
            if "lm" in d:
                wx, wy, bx, by = d["lm"]
                p0 = types.SimpleNamespace(x=wx, y=wy, z=0.0)
                p9 = types.SimpleNamespace(x=bx, y=by, z=0.0)
                lm = [p0] + [p9] * 20
            elif d.get("allow"):
                # 엄지 자세·주먹 프레임은 SWING 줄이 없다 -> 손목만으로 채운다
                continue
            res = tr.update(lm, allow_motion=d.get("allow", False), blocked=[],
                            thumb=d.get("thumb"), fist=d.get("fist", False),
                            open_hand=d.get("open", False))
            if res:
                out.append((t, h, res))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("traces", nargs="+")
    ap.add_argument("--src", default=str(SRC))
    ap.add_argument("-v", action="store_true")
    args = ap.parse_args()
    mod = load(args.src)
    for p in args.traces:
        out = replay(mod, read(p))
        c = Counter(r for _, _, r in out)
        print(f"{Path(p).name}: " + ", ".join(f"{k} {v}" for k, v in sorted(c.items())))
        if args.v:
            print("  ", " ".join(f"{t:.1f}{r[0]}{r.split('_')[-1][0]}" for t, _, r in out))


if __name__ == "__main__":
    sys.exit(main())
