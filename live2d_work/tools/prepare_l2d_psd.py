"""Phase 1 の PSD を Live2D 用に仕上げる(Phase 2 の前処理)。

See-through は「今見えている絵」しか分けないため、リギングに足りない差分を描き足す:
1. 口の中レイヤー `mouth_inner` を口の下に追加(口パク用。Cubism で口レイヤーにクリッピングして使う)
2. 頬染めレイヤー `cheek` を顔の上に追加(上機嫌の表情用。Cubism で不透明度を 0→70% に動かす)

使い方:
  python live2d_work/tools/prepare_l2d_psd.py [入力PSD] [出力PSD]
既定: live2d_work/secretary_psd/secretary_bust.psd → live2d_work/secretary_psd/secretary_bust_l2d.psd
同じフォルダに確認用の l2d_check.png も出力する。

依存: psd-tools, numpy, pillow
"""
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter
from psd_tools import PSDImage

WORK = Path(__file__).resolve().parent.parent
DEFAULT_SRC = WORK / "secretary_psd" / "secretary_bust.psd"
ALPHA_ON = 16
SS = 4               # 図形を描くときの超解像倍率(縁を滑らかにする)


def load(path):
    psd = PSDImage.open(path)
    size = (psd.width, psd.height)
    layers = []
    for layer in psd.descendants():
        if layer.is_group():
            continue
        canvas = Image.new("RGBA", size)
        canvas.paste(layer.topil().convert("RGBA"), (layer.left, layer.top))
        layers.append([layer.name, np.asarray(canvas).copy()])
    return size, layers


def get(layers, name):
    return next(rgba for n, rgba in layers if n == name)


def centroid(rgba):
    ys, xs = np.nonzero(rgba[..., 3] > ALPHA_ON)
    return xs.mean(), ys.mean(), xs.min(), ys.min(), xs.max(), ys.max()


def shape_layer(size, draw_fn, blur=0):
    """SS 倍で描いて縮小し、縁を滑らかにした RGBA レイヤーを返す。"""
    W, H = size
    img = Image.new("RGBA", (W * SS, H * SS))
    draw_fn(ImageDraw.Draw(img), SS)
    img = img.resize(size, Image.LANCZOS)
    if blur:
        img = img.filter(ImageFilter.GaussianBlur(blur))
    return np.asarray(img).copy()


def mouth_inner(size, layers):
    """口を開けたときに見える口の中。口レイヤーの幅に合わせた楕円(上=暗い赤、下=舌)。"""
    cx, cy, x0, _, x1, _ = centroid(get(layers, "mouth"))
    w = (x1 - x0) * 0.85
    h = w * 0.55

    def draw(d, s):
        box = [(cx - w / 2) * s, (cy - h / 2) * s, (cx + w / 2) * s, (cy + h / 2) * s]
        d.ellipse(box, fill=(96, 32, 44, 255))
        tongue = [(cx - w * 0.3) * s, (cy + h * 0.05) * s, (cx + w * 0.3) * s, (cy + h * 0.6) * s]
        d.ellipse(tongue, fill=(196, 104, 112, 255))

    rgba = shape_layer(size, draw)
    # 舌が楕円の外にはみ出した分は消す
    outline = shape_layer(size, lambda d, s: d.ellipse(
        [(cx - w / 2) * s, (cy - h / 2) * s, (cx + w / 2) * s, (cy + h / 2) * s], fill=(0, 0, 0, 255)))
    rgba[..., 3] = np.minimum(rgba[..., 3], outline[..., 3])
    return rgba


def cheek(size, layers):
    """左右の目の下にぼかした薄いピンクの楕円。"""
    centers = []
    for side in ("r", "l"):
        cx, cy, *_ = centroid(get(layers, f"eyewhite-{side}"))
        centers.append((cx, cy + 50))

    def draw(d, s):
        for cx, cy in centers:
            d.ellipse([(cx - 30) * s, (cy - 13) * s, (cx + 30) * s, (cy + 13) * s], fill=(236, 140, 152, 150))

    return shape_layer(size, draw, blur=6)


def save(path, size, layers):
    psd = PSDImage.new(mode="RGBA", size=size, depth=8)
    for name, rgba in layers:  # 先に作ったものほど奥
        ys, xs = np.nonzero(rgba[..., 3])
        y0, y1, x0, x1 = ys.min(), ys.max() + 1, xs.min(), xs.max() + 1
        psd.create_pixel_layer(Image.fromarray(rgba[y0:y1, x0:x1]), name=name, top=int(y0), left=int(x0), opacity=255)
    psd.save(path)


def check_image(size, layers, out_png):
    """確認用: 追加前の顔 / 口の中・頬染めを表示した顔(閉じた口の線は隠す)。"""
    def comp(skip=()):
        bg = Image.new("RGBA", size, (200, 200, 210, 255))
        for name, rgba in layers:
            if name not in skip:
                bg.alpha_composite(Image.fromarray(rgba))
        return bg

    _, _, fx0, fy0, fx1, fy1 = centroid(get(layers, "face"))
    box = (int(fx0) - 40, int(fy0) + 120, int(fx1) + 40, int(fy1) + 20)
    views = [("original", comp(("mouth_inner", "cheek"))), ("mouth_inner + cheek", comp(("mouth",)))]
    w, h = box[2] - box[0], box[3] - box[1]
    sheet = Image.new("RGB", (len(views) * w, h + 30), "white")
    d = ImageDraw.Draw(sheet)
    for i, (label, img) in enumerate(views):
        sheet.paste(img.crop(box).convert("RGB"), (i * w, 30))
        d.text((i * w + 8, 6), label, fill="black")
    sheet.save(out_png)


def main():
    src = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_SRC
    dst = Path(sys.argv[2]) if len(sys.argv) > 2 else src.with_name(src.stem + "_l2d.psd")
    size, layers = load(src)
    names = [n for n, _ in layers]
    layers.insert(names.index("mouth"), ["mouth_inner", mouth_inner(size, layers)])
    names = [n for n, _ in layers]
    layers.insert(names.index("face") + 1, ["cheek", cheek(size, layers)])

    save(dst, size, layers)
    check_image(size, layers, dst.with_name("l2d_check.png"))
    print(f"{src.name} -> {dst.name}: mouth_inner・cheek を追加({len(layers)}レイヤー)")


if __name__ == "__main__":
    main()
