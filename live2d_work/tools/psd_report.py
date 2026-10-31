"""See-through が出力した PSD を自己検収し、レイヤー一覧画像と検収レポートを作る。

使い方:
  python live2d_work/tools/psd_report.py <PSD> [--ref 入力画像] [--out 出力フォルダ]

出力:
  <out>/layers_overview.png   レイヤー一覧(下→上の順、市松模様=透明)
  <out>/qa_report.md          品質チェックリスト(自動判定 + 社長の目視欄)

依存: psd-tools, numpy, pillow, scipy
"""
import argparse
import math
import re
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont
from psd_tools import PSDImage
from scipy import ndimage

# Live2D で独立していてほしいパーツ(キー: 表示名, 値: レイヤー名に含まれる語)
REQUIRED_PARTS = {
    "前髪": ("hairf", "front hair"),
    "後ろ髪": ("hairb", "back hair"),
    "顔(輪郭・肌)": ("face",),
    "眉": ("brow",),
    "白目": ("eyewhite", "eyebg"),
    "瞳": ("irid",),
    "まつ毛・上まぶた": ("lash",),
    "口": ("mouth",),
    "首": ("neck",),
    "胴体(服)": ("topwear",),
}
# 隠れていた部分の補完(インペイント)を確認するパーツ
INPAINT_TARGETS = {
    "顔(前髪の下の額)": ("face",),
    "首(襟・髪の下)": ("neck",),
    "後ろ髪(顔・体の裏)": ("hairb", "back hair"),
}
FRAGMENT_RATIO = 0.002   # レイヤー面積に対してこれ未満の孤立片を「欠け・ゴミ」とみなす
MAX_FRAGMENTS = 5
MIN_OCCLUDED_RATIO = 0.03  # 隠れ部分のうち、これ以上が描かれていれば補完ありとみなす
ALPHA_ON = 16


def find(layers, keys):
    return [l for l in layers if any(k in l["name"].lower() for k in keys)]


def load_layers(psd_path):
    psd = PSDImage.open(psd_path)
    W, H = psd.width, psd.height
    layers = []
    for layer in psd.descendants():  # 下(奥)→上(手前)の順
        if layer.is_group():
            continue
        img = layer.topil()
        if img is None:
            continue
        canvas = Image.new("RGBA", (W, H))
        canvas.paste(img.convert("RGBA"), (layer.left, layer.top))
        layers.append({"name": layer.name, "rgba": np.asarray(canvas), "visible": layer.is_visible()})
    return (W, H), layers


def composite(layers, size):
    out = Image.new("RGBA", size)
    for l in layers:
        if l["visible"]:
            out = Image.alpha_composite(out, Image.fromarray(l["rgba"]))
    return out


def fragment_count(alpha):
    mask = alpha > ALPHA_ON
    area = mask.sum()
    if area == 0:
        return 0, 0
    lab, n = ndimage.label(mask, structure=np.ones((3, 3)))
    sizes = ndimage.sum(mask, lab, range(1, n + 1))
    return int((sizes < area * FRAGMENT_RATIO).sum()), int(n)


def occluded_painted_ratio(layers, idx):
    """layers[idx] のうち、上のレイヤーに完全に隠れている領域の面積比。

    0 なら「見えている所しか描かれていない」=補完なし。
    """
    mask = layers[idx]["rgba"][..., 3] > ALPHA_ON
    if not mask.any():
        return 0.0
    above = np.zeros(mask.shape, dtype=np.float32)
    for l in layers[idx + 1:]:
        a = l["rgba"][..., 3].astype(np.float32) / 255
        above = above + a * (1 - above)
    return float((mask & (above > 0.95)).sum() / mask.sum())


def psnr(a, b, mask):
    d = (a.astype(np.float32) - b.astype(np.float32))[mask]
    mse = float((d ** 2).mean()) if d.size else 0.0
    return float("inf") if mse == 0 else 10 * math.log10(255 ** 2 / mse)


def checker(size, s=16):
    w, h = size
    yy, xx = np.mgrid[0:h, 0:w]
    c = (((xx // s) + (yy // s)) % 2 * 40 + 200).astype(np.uint8)
    return Image.fromarray(np.stack([c, c, c, np.full_like(c, 255)], -1))


def font(size):
    try:
        return ImageFont.load_default(size=size)
    except TypeError:  # Pillow < 10.1
        return ImageFont.load_default()


def fit_to_canvas(ref, size):
    """元画像をキャンバスに合わせる。See-through は縦長画像を左右に余白を足して正方形にするため、
    引き伸ばさず縦横比を保って中央に置く。"""
    W, H = size
    ref = ref.convert("RGB")
    scale = min(W / ref.width, H / ref.height)
    ref = ref.resize((round(ref.width * scale), round(ref.height * scale)), Image.LANCZOS)
    canvas = Image.new("RGB", size, "white")
    canvas.paste(ref, ((W - ref.width) // 2, (H - ref.height) // 2))
    return canvas


def overview(layers, comp, ref, size, out_png, thumb=220):
    W, H = size
    tw, th = thumb, round(thumb * H / W)
    tiles = []
    for i, l in enumerate(layers):
        tile = checker((W, H))
        tile.alpha_composite(Image.fromarray(l["rgba"]))
        tiles.append((f"{i:02d} {l['name']}", tile))
    full = checker((W, H))
    full.alpha_composite(comp)
    tiles.append(("== composite", full))
    if ref is not None:
        tiles.append(("== input", fit_to_canvas(ref, (W, H)).convert("RGBA")))
    cols = 6
    rows = math.ceil(len(tiles) / cols)
    pad, label_h = 8, 22
    sheet = Image.new("RGB", (cols * (tw + pad) + pad, rows * (th + label_h + pad) + pad), "white")
    draw = ImageDraw.Draw(sheet)
    f = font(15)
    for i, (name, t) in enumerate(tiles):
        x = pad + (i % cols) * (tw + pad)
        y = pad + (i // cols) * (th + label_h + pad)
        sheet.paste(t.resize((tw, th), Image.LANCZOS).convert("RGB"), (x, y + label_h))
        draw.text((x, y + 2), name, fill="black", font=f)
    sheet.save(out_png)


def head_check(layers, size, out_png):
    """顔まわりを拡大し「全体 / 前髪なし / 目なし / 顔だけ」を並べた目視確認用の画像。"""
    W, H = size
    face = find(layers, ("face",))
    if not face:
        return
    ys, xs = np.nonzero(face[0]["rgba"][..., 3] > ALPHA_ON)
    box = (max(0, xs.min() - 120), max(0, ys.min() - 120), min(W, xs.max() + 120), min(H, ys.max() + 80))

    def comp_without(keys=None, only=None):
        bg = Image.new("RGBA", (W, H), (200, 200, 210, 255))
        for l in layers:
            name = l["name"].lower()
            if only is not None and name not in only:
                continue
            if keys and any(k in name for k in keys):
                continue
            bg.alpha_composite(Image.fromarray(l["rgba"]))
        return bg.crop(box).convert("RGB")

    views = [("all", comp_without()),
             ("no front hair", comp_without(("hairf", "front hair"))),
             ("no eyes", comp_without(("eyewhite", "irid", "lash"))),
             ("face only", comp_without(only=[l["name"].lower() for l in face]))]
    w, h = box[2] - box[0], box[3] - box[1]
    sheet = Image.new("RGB", (len(views) * w, h + 30), "white")
    draw = ImageDraw.Draw(sheet)
    for i, (name, img) in enumerate(views):
        sheet.paste(img, (i * w, 30))
        draw.text((i * w + 8, 6), name, fill="black", font=font(20))
    sheet.save(out_png)


def mark(ok):
    return "✅" if ok else "⚠️"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("psd")
    ap.add_argument("--ref", help="See-through に入れた元画像(再構成一致度の確認用)")
    ap.add_argument("--out", help="出力フォルダ(既定: PSDと同じ場所)")
    args = ap.parse_args()

    psd_path = Path(args.psd)
    out = Path(args.out) if args.out else psd_path.parent
    out.mkdir(parents=True, exist_ok=True)
    size, layers = load_layers(psd_path)
    comp = composite(layers, size)
    ref = Image.open(args.ref) if args.ref else None
    overview(layers, comp, ref, size, out / "layers_overview.png")
    head_check(layers, size, out / "head_check.png")

    lines = [f"# PSD 検収レポート: `{psd_path.name}`", "",
             f"- キャンバス: {size[0]}×{size[1]} px / レイヤー数: {len(layers)}",
             "- レイヤー一覧画像: `layers_overview.png`(番号が小さいほど奥)",
             "- 顔まわりの目視確認画像: `head_check.png`(全体 / 前髪なし / 目なし / 顔だけ)", ""]

    # 1. 縁の欠け
    lines += ["## 1. 各パーツの縁に欠けがない", "",
              "| # | レイヤー | 面積(px) | 孤立片 | 判定 |", "|---|---|---|---|---|"]
    edge_ok = True
    for i, l in enumerate(layers):
        frag, _ = fragment_count(l["rgba"][..., 3])
        area = int((l["rgba"][..., 3] > ALPHA_ON).sum())
        ok = area > 0 and frag <= MAX_FRAGMENTS
        edge_ok &= ok
        lines.append(f"| {i:02d} | {l['name']} | {area:,} | {frag} | {mark(ok)} |")
    lines += ["", "孤立片 = レイヤー面積の0.2%未満の切れ端。多いと縁が欠けている/他パーツの破片が混入している可能性。", ""]

    # 2. インペイント
    lines += ["## 2. 遮蔽部分がインペイントで補完されている", "",
              "| 対象 | レイヤー | 隠れた部分まで描かれている割合 | 判定 |", "|---|---|---|---|"]
    inpaint_ok = True
    for label, keys in INPAINT_TARGETS.items():
        hits = find(layers, keys)
        if not hits:
            inpaint_ok = False
            lines.append(f"| {label} | (なし) | - | ⚠️ |")
            continue
        for l in hits:
            r = occluded_painted_ratio(layers, layers.index(l))
            ok = r >= MIN_OCCLUDED_RATIO
            inpaint_ok &= ok
            lines.append(f"| {label} | {l['name']} | {r:.1%} | {mark(ok)} |")
    lines += ["", "0%に近い = 見えている所しか無い(前髪を揺らすと穴が開く)。", ""]

    # 3. 目・口の独立
    lines += ["## 3. 目・口などのパーツが独立している", "", "| パーツ | 該当レイヤー | 判定 |", "|---|---|---|"]
    parts_ok = True
    for label, keys in REQUIRED_PARTS.items():
        hits = find(layers, keys)
        parts_ok &= bool(hits)
        lines.append(f"| {label} | {', '.join(l['name'] for l in hits) or '(なし)'} | {mark(bool(hits))} |")
    # See-through は --tblr_split 時に "eyewhite-l" / "eyewhite-r" のように左右を分ける
    lr = any(re.search(r"(eye|irides|eyelash)\S*-[lr]$|^eye[lr]$", l["name"].lower()) for l in layers)
    lines += ["", f"- 左右の目が別レイヤー(片目ウインク用): {mark(lr)}", ""]

    # 4. 再構成
    if ref is not None:
        r = np.asarray(fit_to_canvas(ref, size))
        c = np.asarray(comp)
        m = c[..., 3] > 200
        p = psnr(c[..., :3], r, m)
        lines += ["## 4. 全レイヤー合成 ≒ 元画像", "", f"- PSNR(キャラ領域): {p:.1f} dB {mark(p >= 25)}(25dB以上なら見た目はほぼ同一)", ""]

    lines += ["## まとめ(自動判定)", "",
              f"- [{'x' if edge_ok else ' '}] 各パーツの縁に欠けがない",
              f"- [{'x' if inpaint_ok else ' '}] 遮蔽されていた部分(襟の下の首、前髪の下の額)がインペイントで補完されている",
              f"- [{'x' if parts_ok else ' '}] 目・口のパーツが独立している(差し替え可能)", "",
              "## 社長の目視確認(Phase 1 承認)", "",
              "PSD を開き(Photoshop / CLIP STUDIO / 無料なら Photopea)、各レイヤーの目アイコンを切り替えて確認:", "",
              "- [ ] 前髪を非表示にしても、額が自然に描かれている",
              "- [ ] 目のレイヤーを消すと、まぶたの下が肌色で埋まっている",
              "- [ ] 口・目・眉がそれぞれ単独で動かせそうに分かれている",
              "- [ ] 全体を表示すると元のイラストと同じに見える", "",
              "OKなら秘書に「PSD OK」と伝えてください(=Phase 1 承認)。"]
    (out / "qa_report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"wrote {out / 'layers_overview.png'}, {out / 'head_check.png'} and {out / 'qa_report.md'}")


if __name__ == "__main__":
    main()
