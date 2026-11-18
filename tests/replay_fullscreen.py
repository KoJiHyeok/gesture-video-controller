"""traces/*.csv 에 남은 손 좌표를 FullscreenTracker 에 다시 넣어 명령이 어떻게 나왔을지 재현한다.

카메라 없이 기준값·로직 수정의 효과를 비교하는 용도.
좌표: 기본(--point palm)은 손목 좌표 + 손 각도·크기로 손바닥 중심(0,5,9,13,17 평균)을 복원한다
      (중지 뿌리 9번 = 손목 + size*(sin a, -cos a), 중심 ~ 손목 + 0.75*(9 - 손목) 로 근사).
      --point wrist 면 손목 좌표를 그대로 쓴다.
      allow=False(제어 OFF / V·OK) 프레임은 enabled=False 로 넣는다.

사용:
  python tests/replay_fullscreen.py traces/swing_trace_*.csv
  python tests/replay_fullscreen.py --tracker 다른/fullscreen_tracking.py traces/x.csv   # 다른 버전과 비교
  python tests/replay_fullscreen.py -v traces/x.csv   # 명령 시각까지 출력
"""

import argparse
import csv
import math
import importlib.util
import inspect
import sys
import types
from collections import OrderedDict, Counter
from pathlib import Path

SRC = Path(__file__).resolve().parent.parent / "src" / "fullscreen_tracking.py"


def load_tracker(path):
    spec = importlib.util.spec_from_file_location(f"fs_{abs(hash(str(path)))}", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


PALM_RATIO = 0.75


def read_frames(path, point="palm"):
    frames = OrderedDict()
    with open(path, encoding="utf-8") as f:
        for row in csv.DictReader(f):
            t = float(row["t"])
            d = frames.setdefault(t, {"hands": {}, "allow": True, "open": {}})
            if row["event"] == "POSE":
                d["open"][row["hand"]] = row["result"].split(" ")[0].endswith("/open")
            if row["wrist_x"]:
                x, y = float(row["wrist_x"]), float(row["wrist_y"])
                if point == "palm" and row["angle"] and row["size"]:
                    a, size = math.radians(float(row["angle"])), float(row["size"])
                    x += PALM_RATIO * size * math.sin(a)
                    y -= PALM_RATIO * size * math.cos(a)
                d["hands"][row["hand"]] = (x, y)
            if row["allow"] == "False":
                d["allow"] = False
    return frames


def replay(mod, frames):
    clock = [0.0]
    mod.time = types.SimpleNamespace(monotonic=lambda: clock[0])
    tracker = mod.FullscreenTracker()
    params = inspect.signature(tracker.update).parameters
    new_api = "hands" in params
    has_opens = "opens" in params
    fake = lambda x, y: [types.SimpleNamespace(x=x, y=y)] * 21
    commands, states = [], Counter()
    for t, d in frames.items():
        clock[0] = t
        names = sorted(d["hands"], key=lambda h: d["hands"][h])
        hands = [fake(*d["hands"][h]) for h in names]
        if has_opens:
            cmd, _ = tracker.update(hands, enabled=d["allow"],
                                    opens=[d["open"].get(h, False) for h in names])
        elif new_api:
            cmd, _ = tracker.update(hands, enabled=d["allow"])
        else:
            pair = hands if len(hands) == 2 else (None, None)
            cmd, _ = tracker.update(pair[0], pair[1], enabled=d["allow"])
        states[tracker.state] += 1
        if cmd:
            commands.append((t, cmd))
    return commands, states


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("traces", nargs="+")
    ap.add_argument("--tracker", default=str(SRC))
    ap.add_argument("-v", action="store_true")
    ap.add_argument("--point", choices=("palm", "wrist"), default="palm")
    args = ap.parse_args()
    mod = load_tracker(args.tracker)
    for p in args.traces:
        frames = read_frames(p, args.point)
        cmds, states = replay(mod, frames)
        c = Counter(cmd for _, cmd in cmds)
        print(f"{Path(p).name}: ON {c['FULLSCREEN_ON']} / OFF {c['FULLSCREEN_OFF']}")
        if args.v:
            print("  ", " ".join(f"{t:.1f}{'+' if cmd.endswith('ON') else '-'}" for t, cmd in cmds))


if __name__ == "__main__":
    sys.exit(main())
