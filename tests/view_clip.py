"""clips/ 의 CSV 를 손 뼈대 애니메이션으로 다시 본다 (카메라 없이).

사용:
  python tests/view_clip.py clips/20261118_150000            # 폴더 안 전부
  python tests/view_clip.py clips/20261118_150000 --only MISFIRE
  python tests/view_clip.py clips/x/150102_123_SEEK_FORWARD.csv

키: SPACE 일시정지 · n 다음 클립 · p 이전 클립 · q/ESC 종료
화면 아래 글자 = 그 프레임의 판정 (손: 정적 제스처 / 엄지 / 주먹 / 편 손)
"""
import argparse
import csv
import sys
from pathlib import Path

import cv2

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
from clip_recorder import render  # noqa: E402

W, H = 640, 480


def load(path):
    frames = {}
    with open(path, encoding="utf-8") as f:
        for r in csv.DictReader(f):
            t = float(r["t"])
            fr = frames.setdefault(t, (t, r["enabled"] == "True", [], r["command"] or None))
            if r["hand"] == "NONE":
                continue
            pts = [(float(r[f"x{i}"]), float(r[f"y{i}"]), float(r[f"z{i}"])) for i in range(21)]
            fr[2].append({"name": r["hand"], "pts": pts, "static": r["static"], "thumb": r["thumb"],
                          "fist": r["fist"], "true_fist": r["true_fist"], "open": r["open"]})
    return [frames[t] for t in sorted(frames)]


def describe(hd):
    s = f"{hd['name'][0]}: {hd['static']}"
    if hd["thumb"]:
        s += f" thumb={hd['thumb']}"
    if hd["true_fist"] == "True":
        s += " FIST"
    elif hd["open"] == "True":
        s += " open"
    return s


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("paths", nargs="+")
    ap.add_argument("--only", help="파일 이름에 이 글자가 든 클립만 (예: MISFIRE, SEEK)")
    ap.add_argument("--fps", type=float, default=15, help="재생 속도 (실제는 약 30fps -> 기본 절반 속도)")
    args = ap.parse_args()

    files = []
    for p in map(Path, args.paths):
        files += sorted(p.glob("*.csv")) if p.is_dir() else [p]
    if args.only:
        files = [f for f in files if args.only in f.name]
    if not files:
        sys.exit("클립이 없습니다.")

    i, delay = 0, max(1, int(1000 / args.fps))
    while 0 <= i < len(files):
        frames = load(files[i])
        k, paused, step = 0, False, None
        while step is None:
            shown = frames[: k + 1]
            img = render(shown, (W, H), f"[{i + 1}/{len(files)}] {files[i].stem}")
            t = frames[k][0] if frames else 0
            lines = [f"t={t:+.2f}s"] + [describe(hd) for hd in (frames[k][2] if frames else [])]
            for j, s in enumerate(lines):
                cv2.putText(img, s, (W - 330, H - 12 - 22 * (len(lines) - 1 - j)),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.5, (200, 255, 200), 1, cv2.LINE_AA)
            cv2.imshow("clip", img)
            key = cv2.waitKey(0 if paused else delay) & 0xFF
            if key in (27, ord("q")):
                return
            if key == ord(" "):
                paused = not paused
            elif key == ord("n"):
                step = 1
            elif key == ord("p"):
                step = -1
            elif not paused:
                k += 1
                if k >= len(frames):  # 끝 -> 0.8초 멈췄다 반복
                    cv2.waitKey(800)
                    k = 0
        i = max(0, i + step)


if __name__ == "__main__":
    main()
