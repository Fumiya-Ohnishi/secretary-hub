"""See-through 入力画像の前処理。

元イラストは「バストアップ + 全身」の2体が並んだキャラシートのため、
そのままでは See-through が2体を1人として分解してしまう。
Live2D に使う左のバストアップだけを切り出し、長辺1280pxに拡大して保存する。

使い方:
  python live2d_work/tools/prepare_input.py [元画像] [出力PNG]
既定: ../ai-company/brand/secretary_design.png → live2d_work/input/secretary_bust.png
"""
import sys
from pathlib import Path

from PIL import Image

HERE = Path(__file__).resolve().parent
WORK = HERE.parent
DEFAULT_SRC = WORK.parent.parent / "ai-company" / "brand" / "secretary_design.png"
FALLBACK_SRC = WORK.parent / "frontend" / "public" / "faces" / "normal.jpg"
DEFAULT_DST = WORK / "input" / "secretary_bust.png"

# バストアップ領域(元画像の幅に対する比率)。右の全身図の髪にかからない位置で切る
BUST_RIGHT_RATIO = 588 / 880
TARGET_LONG_SIDE = 1280


def main():
    src = Path(sys.argv[1]) if len(sys.argv) > 1 else (DEFAULT_SRC if DEFAULT_SRC.exists() else FALLBACK_SRC)
    dst = Path(sys.argv[2]) if len(sys.argv) > 2 else DEFAULT_DST
    img = Image.open(src).convert("RGB")
    w, h = img.size
    bust = img.crop((0, 0, round(w * BUST_RIGHT_RATIO), h))
    scale = TARGET_LONG_SIDE / max(bust.size)
    bust = bust.resize((round(bust.width * scale), round(bust.height * scale)), Image.LANCZOS)
    dst.parent.mkdir(parents=True, exist_ok=True)
    bust.save(dst)
    print(f"{src} -> {dst} {bust.size}")


if __name__ == "__main__":
    main()
