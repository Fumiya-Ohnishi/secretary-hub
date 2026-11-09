#!/usr/bin/env python3
"""Sora(OpenAI の動画生成)で、人物が動いてしゃべるリールを作る。

使い方(会社のフォルダ ai-company で):
    python3 ~/secretary-hub/tools/sora/make_reel.py content/drafts/2026-47/honne01/sora/spec.json
    --dry   : Sora に送る指示と、生成する秒数だけを表示する(お金はかからない)
    --join  : 生成済みの場面をつなぎ直すだけ(テロップを直したとき)

- OpenAI のキーは環境変数 OPENAI_API_KEY か、秘書ハブの backend/.env の OPENAI_API_KEY を使う(画面には出さない)
- 場面ごとに Sora で生成 → 出来た場面は保存して、2回目からは作り直さない(やり直したい場面は、その mp4 を消す)
- 最後に ffmpeg で、場面をつなぎ、テロップ・記録カード・まとめの画面を重ねる
- 必要なもの: Python 3(標準のまま)と ffmpeg(brew install ffmpeg)
"""
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

API = "https://api.openai.com/v1"
MODEL = os.getenv("OPENAI_VIDEO_MODEL", "sora-2")
HUB = Path(__file__).resolve().parents[2]


def api_key() -> str:
    k = os.getenv("OPENAI_API_KEY", "").strip()
    for env in (HUB / "backend" / ".env", HUB / ".env"):  # 秘書ハブの設定は backend/.env
        if k or not env.exists():
            continue
        for line in env.read_text(encoding="utf-8").splitlines():
            if line.strip().startswith("OPENAI_API_KEY="):
                k = line.split("=", 1)[1].strip().strip('"').strip("'")
    if not k:
        sys.exit(f"OPENAI_API_KEY が見つかりません({HUB / 'backend' / '.env'} に OPENAI_API_KEY=... の行を書いてください)")
    return k


def ffmpeg() -> str:
    f = shutil.which("ffmpeg", path=os.environ.get("PATH", "") + ":/opt/homebrew/bin:/usr/local/bin")
    if not f:
        sys.exit("ffmpeg がありません。ターミナルで brew install ffmpeg を実行してください")
    return f


def _req(method, url, key, data=None, headers=None, timeout=60):
    h = {"Authorization": f"Bearer {key}"}
    h.update(headers or {})
    r = urllib.request.Request(url, data=data, method=method, headers=h)
    try:
        with urllib.request.urlopen(r, timeout=timeout) as res:
            return res.status, res.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()
    except urllib.error.URLError as e:
        sys.exit(f"OpenAI につながりませんでした: {e.reason}\n"
                 "(CERTIFICATE_VERIFY_FAILED と出たら、Finder のアプリケーション > Python 3.x の「Install Certificates.command」を一度ダブルクリック)")


def _multipart(fields: dict, file_field=None, file_path=None):
    b = uuid.uuid4().hex
    out = bytearray()
    for k, v in fields.items():
        out += f"--{b}\r\nContent-Disposition: form-data; name=\"{k}\"\r\n\r\n{v}\r\n".encode()
    if file_path:
        mime = "image/png" if file_path.suffix == ".png" else "image/jpeg"
        out += (f"--{b}\r\nContent-Disposition: form-data; name=\"{file_field}\"; filename=\"{file_path.name}\"\r\n"
                f"Content-Type: {mime}\r\n\r\n").encode() + file_path.read_bytes() + b"\r\n"
    out += f"--{b}--\r\n".encode()
    return bytes(out), {"Content-Type": f"multipart/form-data; boundary={b}"}


def build_prompt(spec, clip) -> str:
    who = {s for s, _ in clip["dialogue"]} | {c for c in spec["characters"] if c.upper() in clip["prompt"]}
    lines = [spec["style"], ""] + [spec["characters"][c] for c in spec["characters"] if c in who] + ["", clip["prompt"], "", "Dialogue (spoken aloud in Japanese, in this order, nothing else is spoken):"]
    lines += [f'{s.upper()} says: 「{t}」' for s, t in clip["dialogue"]]
    return "\n".join(lines)


def generate(spec, clip, base: Path, dest: Path, key: str):
    prompt = build_prompt(spec, clip)
    fields = {"model": MODEL, "prompt": prompt, "seconds": str(clip["seconds"]), "size": spec.get("size", "720x1280")}
    ref = base / clip["ref"] if clip.get("ref") else None
    data, h = _multipart(fields, "input_reference", ref) if ref else _multipart(fields)
    st, body = _req("POST", f"{API}/videos", key, data, h)
    if st >= 400 and ref:  # 参考画像が通らないとき(人物の画像は断られることがある)は、文章だけで作り直す
        print(f"  参考画像つきは受け付けられませんでした({st}: {body[:160].decode(errors='ignore')})→ 文章だけで作ります")
        data, h = _multipart(fields)
        st, body = _req("POST", f"{API}/videos", key, data, h)
    if st >= 400:
        sys.exit(f"Sora に断られました({st}): {body[:300].decode(errors='ignore')}")
    vid = json.loads(body)["id"]
    for _ in range(150):  # 最長25分
        time.sleep(10)
        st, body = _req("GET", f"{API}/videos/{vid}", key)
        s = json.loads(body) if st < 400 else {}
        if s.get("status") == "completed":
            break
        if s.get("status") in ("failed", "cancelled"):
            sys.exit(f"場面 {clip['id']} の生成に失敗: {json.dumps(s.get('error') or s, ensure_ascii=False)[:300]}")
        print(f"  場面 {clip['id']}: 生成中 {s.get('progress', '?')}%", flush=True)
    else:
        sys.exit(f"場面 {clip['id']} が25分で終わりませんでした")
    st, body = _req("GET", f"{API}/videos/{vid}/content", key, timeout=300)
    if st >= 400:
        sys.exit(f"場面 {clip['id']} の受け取りに失敗({st})")
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(body)
    print(f"  場面 {clip['id']}: できました → {dest}")


def has_audio(ff, path) -> bool:
    r = subprocess.run([ff, "-hide_banner", "-i", str(path)], capture_output=True, text=True)
    return "Audio:" in r.stderr


def join(spec, base: Path, clips_dir: Path, out: Path):
    ff = ffmpeg()
    W, H = spec.get("size", "720x1280").split("x")
    norm = []
    for c in spec["clips"]:
        src, dst = clips_dir / f"clip_{c['id']}.mp4", clips_dir / f"n_{c['id']}.mp4"
        a = [] if has_audio(ff, src) else ["-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo"]
        subprocess.run([ff, "-y", "-loglevel", "error", "-i", str(src), *a, "-t", str(c["seconds"]),
                        "-vf", f"scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},fps=30,setsar=1",
                        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-ar", "48000", "-ac", "2", "-shortest", str(dst)], check=True)
        norm.append(dst)
    if spec.get("endcard"):
        img, secs = spec["endcard"]
        dst = clips_dir / "n_end.mp4"
        subprocess.run([ff, "-y", "-loglevel", "error", "-loop", "1", "-i", str(base / img), "-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo",
                        "-t", str(secs), "-vf", f"scale={W}:{H},fps=30,setsar=1,fade=in:0:12", "-c:v", "libx264", "-pix_fmt", "yuv420p",
                        "-c:a", "aac", "-ar", "48000", "-ac", "2", str(dst)], check=True)
        norm.append(dst)
    inputs, fc = [], ""
    for i, p in enumerate(norm):
        inputs += ["-i", str(p)]
        fc += f"[{i}:v][{i}:a]"
    fc += f"concat=n={len(norm)}:v=1:a=1[v0][a]"
    layers = [(s, e, img) for s, e, img in spec.get("overlays", [])] + [(s, e, img) for s, e, img in spec.get("captions", [])]
    for j, (s, e, img) in enumerate(layers):
        inputs += ["-i", str(base / img)]
        fc += f";[v{j}][{len(norm) + j}:v]overlay=0:0:enable='between(t,{s},{e})'[v{j + 1}]"
    out.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run([ff, "-y", "-loglevel", "error", *inputs, "-filter_complex", fc, "-map", f"[v{len(layers)}]", "-map", "[a]",
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "20", "-c:a", "aac", "-movflags", "+faststart", str(out)], check=True)
    print(f"完成: {out}")


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if not args:
        sys.exit(__doc__)
    spec_path = Path(args[0]).resolve()
    spec = json.loads(spec_path.read_text(encoding="utf-8"))
    base = spec_path.parent
    out = Path(spec["out"]).resolve()
    clips_dir = out.with_name(out.stem + "_sora")
    total = sum(c["seconds"] for c in spec["clips"])
    if "--dry" in sys.argv:
        for c in spec["clips"]:
            print(f"--- 場面 {c['id']}({c['seconds']}秒・参考画像 {c.get('ref') or 'なし'})\n{build_prompt(spec, c)}\n")
        print(f"Sora で生成する合計: {total}秒(モデル {MODEL})")
        return
    if "--join" not in sys.argv:
        key = api_key()
        todo = [c for c in spec["clips"] if not (clips_dir / f"clip_{c['id']}.mp4").exists()]
        print(f"Sora で {len(todo)}場面を作ります(合計 {sum(c['seconds'] for c in todo)}秒・モデル {MODEL})")
        for c in todo:
            generate(spec, c, base, clips_dir / f"clip_{c['id']}.mp4", key)
    join(spec, base, clips_dir, out)


if __name__ == "__main__":
    main()
