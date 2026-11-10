#!/usr/bin/env python3
"""画像の一部を切り出して拡大する(点検の「3倍拡大」用)。2026-11-10 追加(社員の声: sips・python・/tmp が許可で止まる)。

使い方(会社のフォルダから):
  python3 <秘書ハブ>/tools/image/zoom.py <画像> <x> <y> <幅> <高さ> [倍率=3]
  python3 <秘書ハブ>/tools/image/zoom.py --size <画像> [<画像> ...]   # 寸法を読むだけ
- 書き出し先は content/output/_work/zoom/<元の名前>_x_y_<倍率>x.png に固定(元の画像は変えない。git に入らない・部署が Read で開ける)
"""
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import ffbin  # noqa: E402


def size(p: str) -> str:
    return subprocess.run([ffbin.ffprobe() or "ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height",
                           "-of", "csv=p=0:s=x", p], capture_output=True, text=True).stdout.strip()


def main():
    a = sys.argv[1:]
    if not a:
        sys.exit(__doc__)
    if a[0] == "--size":
        for p in a[1:]:
            print(f"{p}: {size(p)}")
        return
    if len(a) < 5:
        sys.exit(__doc__)
    src, x, y, w, h = a[0], int(a[1]), int(a[2]), int(a[3]), int(a[4])
    k = float(a[5]) if len(a) > 5 else 3.0
    out = Path("content/output/_work/zoom") / f"{Path(src).stem}_{x}_{y}_{k:g}x.png"
    out.parent.mkdir(parents=True, exist_ok=True)
    vf = f"crop={w}:{h}:{x}:{y},scale=iw*{k}:ih*{k}:flags=neighbor"
    subprocess.run([ffbin.ffmpeg() or "ffmpeg", "-y", "-loglevel", "error", "-i", src, "-vf", vf, str(out)], check=True)
    print(f"拡大: {out}({w}×{h} を {k:g} 倍)")


if __name__ == "__main__":
    main()
