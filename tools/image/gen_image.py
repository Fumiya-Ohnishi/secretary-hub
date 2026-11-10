#!/usr/bin/env python3
"""部署の作業から画像を作る道具(OpenAI の画像API)。2026-11-10 追加。

キーは秘書ハブの backend/.env の OPENAI_API_KEY(秘書ハブが部署の作業に環境変数で渡す)。
**会社のフォルダ(ai-company)にキーを置かない・探さない**。キーは画面にもファイルにも出さない。

使い方(会社のフォルダから):
  python3 <秘書ハブ>/tools/image/gen_image.py --out content/output/2026-47/sena_surprise.png \
      --aspect 4:5 --prompt "..." [--ref content/output/2026-47/sena_3d_base.png ...]
- --ref に今の3Dセナの画像を渡すと、その絵柄・顔に寄せて作る(キャラクターをそろえるとき)
- --aspect: 4:5(カルーセル 1080×1350)/ 9:16(リール・ストーリー 1080×1920)/ 1:1 / 16:9
- 出力は content/output/ の下だけ
"""
import argparse
import base64
import json
import mimetypes
import os
import shutil
import subprocess
import sys
import urllib.error
import urllib.request
import uuid
from pathlib import Path

API = "https://api.openai.com/v1"
MODEL = os.getenv("OPENAI_IMAGE_MODEL", "gpt-image-1").strip() or "gpt-image-1"
HUB = Path(__file__).resolve().parents[2]
SIZES = {"1:1": "1024x1024", "16:9": "1536x1024", "4:5": "1024x1536", "9:16": "1024x1536"}


def api_key() -> str:
    k = os.getenv("OPENAI_API_KEY", "").strip()
    env = HUB / "backend" / ".env"
    if not k and env.exists():
        for line in env.read_text(encoding="utf-8").splitlines():
            if line.strip().startswith("OPENAI_API_KEY="):
                k = line.split("=", 1)[1].strip().strip('"').strip("'")
    if not k:
        sys.exit("OPENAI_API_KEY が見つかりません。秘書ハブの backend/.env に OPENAI_API_KEY=... を書き、秘書ハブを起動し直してください"
                 "(会社のフォルダには置かない)")
    return k


class ApiError(Exception):
    def __init__(self, code: int, text: str):
        super().__init__(f"画像API {code}: {text[:300]}")
        self.code, self.text = code, text


def _post(url: str, body: bytes, ctype: str) -> dict:
    req = urllib.request.Request(url, data=body, method="POST",
                                 headers={"Authorization": f"Bearer {api_key()}", "Content-Type": ctype})
    try:
        with urllib.request.urlopen(req, timeout=300) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        raise ApiError(e.code, e.read().decode("utf-8", "replace"))


def image_models() -> list:
    """このキーで使える画像のモデル(新しい順。mini は後ろ)"""
    req = urllib.request.Request(f"{API}/models", headers={"Authorization": f"Bearer {api_key()}"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            ids = [m["id"] for m in json.loads(r.read()).get("data", [])]
    except Exception:
        return []
    imgs = [i for i in ids if i.startswith("gpt-image")]
    def key(i):
        nums = [-int(x) for x in __import__("re").findall(r"\d+", i)][:3]
        return ("mini" in i, nums + [0] * (3 - len(nums)), i)  # 新しい版が先(2 → 1.5 → 1)、mini は後ろ
    return sorted(imgs, key=key)


def _with_model(call):
    """指定のモデルが使えないときは、このキーで使える画像モデルに切り替えて1回やり直す"""
    try:
        return call(MODEL), MODEL
    except ApiError as e:
        low = e.text.lower()
        if "verif" in low:
            sys.exit("OpenAI の組織の確認(Verify Organization)が済んでいないため、画像のモデルが使えません。"
                     "社長が platform.openai.com の Settings → Organization → General で確認を済ませてください。" + f"\n({e})")
        if e.code not in (400, 403, 404) or "model" not in low:
            sys.exit(str(e))
        for m in image_models():
            if m == MODEL:
                continue
            try:
                print(f"モデル {MODEL} が使えないため {m} で作ります", file=sys.stderr)
                return call(m), m
            except ApiError as e2:
                last = e2
                continue
        sys.exit(f"{e}\nこのキーで使える画像のモデルが見つかりませんでした(使えるモデル: {', '.join(image_models()) or 'なし'})")


def generate(prompt: str, size: str):
    def call(model):
        d = _post(f"{API}/images/generations", json.dumps({"model": model, "prompt": prompt, "size": size, "n": 1}).encode(),
                  "application/json")
        return base64.b64decode(d["data"][0]["b64_json"])
    return _with_model(call)


def edit(prompt: str, size: str, refs: list):
    return _with_model(lambda model: _edit(model, prompt, size, refs))


def _edit(model: str, prompt: str, size: str, refs: list) -> bytes:
    """参考画像(今のキャラクター)に寄せて作る"""
    b = uuid.uuid4().hex
    parts = []
    for k, v in (("model", model), ("prompt", prompt), ("size", size), ("n", "1")):
        parts.append(f'--{b}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode())
    for p in refs:
        ct = mimetypes.guess_type(p.name)[0] or "image/png"
        parts.append(f'--{b}\r\nContent-Disposition: form-data; name="image[]"; filename="{p.name}"\r\nContent-Type: {ct}\r\n\r\n'.encode()
                     + p.read_bytes() + b"\r\n")
    parts.append(f"--{b}--\r\n".encode())
    d = _post(f"{API}/images/edits", b"".join(parts), f"multipart/form-data; boundary={b}")
    return base64.b64decode(d["data"][0]["b64_json"])


def main():
    ap = argparse.ArgumentParser(description="画像を1枚作る(OpenAI)")
    ap.add_argument("--prompt"); ap.add_argument("--prompt-file")
    ap.add_argument("--out", required=True); ap.add_argument("--aspect", default="4:5", choices=list(SIZES))
    ap.add_argument("--ref", action="append", default=[])
    a = ap.parse_args()
    prompt = Path(a.prompt_file).read_text(encoding="utf-8") if a.prompt_file else (a.prompt or "")
    if not prompt.strip():
        sys.exit("--prompt か --prompt-file を指定してください")
    out = Path(a.out)
    if out.is_absolute() or ".." in out.parts or out.parts[:2] != ("content", "output"):
        sys.exit("出力は会社のフォルダの content/output/ の下に、相対パスで指定してください")
    refs = [Path(r) for r in a.ref]
    for r in refs:
        if not r.exists():
            sys.exit(f"参考画像がありません: {r}")
    size = SIZES[a.aspect]
    raw, used = edit(prompt, size, refs) if refs else generate(prompt, size)
    out.parent.mkdir(parents=True, exist_ok=True)
    ff = os.getenv("FFMPEG") or shutil.which("ffmpeg", path=os.environ.get("PATH", "") + ":/opt/homebrew/bin:/usr/local/bin")
    if a.aspect in ("4:5", "9:16") and ff:  # 縦長に切り抜いて投稿の大きさにそろえる
        tmp = out.with_suffix(".src.png"); tmp.write_bytes(raw)
        vf = "crop=iw:iw*5/4,scale=1080:1350" if a.aspect == "4:5" else "crop=ih*9/16:ih,scale=1080:1920"
        subprocess.run([ff, "-y", "-loglevel", "error", "-i", str(tmp), "-vf", vf, str(out)], check=True)
        tmp.unlink(missing_ok=True)
    else:
        out.write_bytes(raw)
    print(f"作成: {out}({a.aspect}・{used}{'・参考画像 ' + str(len(refs)) + '枚' if refs else ''})。AIで作った画像として記録すること")


if __name__ == "__main__":
    main()
