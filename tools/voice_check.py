#!/usr/bin/env python3
"""動画のセリフが「日本語として台本どおりに聞こえるか」を、提出前に機械で確かめる。

使い方(会社のフォルダ ai-company で):
    python3 ~/Documents/git/secretary-hub/tools/voice_check.py content/drafts/2026-47/honne01/sora/spec.json
    python3 ~/Documents/git/secretary-hub/tools/voice_check.py content/drafts/2026-47/04_ig_reel.reel.json [動画.mp4]

- *.reel.json(VOICEVOX の声で書き出したリール。2026-11-10 追加)は、動画1本を通しで書き起こし、各行の speech(無ければ text)をつないだ台本と比べる。
  動画は2つ目の引数か、content/output/YYYY-WW/<名前>.mp4(名前は .reel.json を除いたもの)、無ければ MEDIA_DIR(Google ドライブ)の同じ名前

- spec.json の場面ごとの動画(<完成品の名前>_sora/clip_<id>.mp4)を音声認識(Whisper)で書き起こし、
  台本のセリフと「読み(ひらがな)」で比べる。句読点・漢字/ひらがなの書き方の違いは無視する
- 読みが台本と食い違う場面があれば「要確認」として、どこが違うかを出す(例: たしかめますね → かしきめますね)
- 最後の0.25秒以上が無音か(セリフが切れていないか)も確かめる
- 全部合格なら終了コード 0、要確認があれば 1
- 必要なもの: pip install faster-whisper pykakasi(初回は音声認識のモデル(約1.5GB)を Hugging Face から取得する)と ffmpeg
"""
import difflib
import json
import re
import subprocess
import sys
from pathlib import Path

MODEL = "medium"  # 日本語の聞き取りに十分な大きさ(small では読み違いを見逃しやすい)
PASS_RATIO = 1.0  # 読みが1文字でも違えば要確認(「確かめますね」→「かしきめますね」は95%一致でも聞けば別の言葉)
TAIL_SEC = 0.25  # 最後にこれだけ無音がなければ「切れている」


def pcm(path: Path):
    import numpy as np
    raw = subprocess.run(["ffmpeg", "-loglevel", "error", "-i", str(path), "-ac", "1", "-ar", "16000", "-f", "s16le", "-"],
                         capture_output=True, check=True).stdout
    return np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768


# 音声認識が、無音や環境音のところに勝手に足しやすい言葉(実際には誰も言っていない)。書き起こしから外す
HALLUCINATIONS = ("ご視聴ありがとうございました", "ご覧いただきありがとうございます", "チャンネル登録よろしくお願いします",
                  "チャンネル登録お願いします", "最後までご視聴いただきありがとうございました")


def heard_text(segs) -> str:
    out = []
    for sg in segs:
        t = sg.text.strip()
        for h in HALLUCINATIONS:
            t = t.replace(h, "")
        out.append(t)
    return "".join(out)


COUNTERS = ["ひとつ", "ふたつ", "みっつ", "よっつ", "いつつ", "むっつ", "ななつ", "やっつ", "ここのつ"]
KANJI_NUM = "一二三四五六七八九"
WORDS = (("AI", "えーあい"), ("ＡＩ", "えーあい"), ("Claude", "くろーど"), ("ChatGPT", "ちゃっとじーぴーてぃー"))


def reading(text: str, kks) -> str:
    for w, r in WORDS:  # 英字の言葉は読みにそろえる(台本は「エーアイ」、聞き取りは「AI」のように分かれるため)
        text = text.replace(w, r)
    text = re.sub(r"[\s、。,.!?！？「」『』…・〜ー\-*()()]", "", text)
    for i, k in enumerate(COUNTERS):  # 1つ〜9つ・一つ〜九つ は「ひとつ」〜「ここのつ」
        text = text.replace(f"{i + 1}つ", k).replace(f"{KANJI_NUM[i]}つ", k)
    hira = "".join(x["hira"] for x in kks.convert(text))
    for d, k in zip("0123456789", ["ぜろ", "いち", "に", "さん", "よん", "ご", "ろく", "なな", "はち", "きゅう"]):
        hira = hira.replace(d, k)
    return hira


def tail_silent(path: Path, sec: float = TAIL_SEC) -> bool:
    out = subprocess.run(["ffmpeg", "-hide_banner", "-i", str(path), "-af", "silencedetect=noise=-35dB:d=0.2", "-f", "null", "-"],
                         capture_output=True, text=True).stderr
    dur = float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
                               capture_output=True, text=True).stdout.strip())
    starts = [float(x) for x in re.findall(r"silence_start: ([\d.]+)", out)]
    ends = [float(x) for x in re.findall(r"silence_end: ([\d.]+)", out)]
    return bool(starts) and (len(ends) < len(starts) or ends[-1] >= dur - 0.05) and starts[-1] <= dur - sec


def main():
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    from faster_whisper import WhisperModel
    import pykakasi
    kks = pykakasi.kakasi()
    spec_path = Path(sys.argv[1]).resolve()
    spec = json.loads(spec_path.read_text(encoding="utf-8"))
    if spec_path.name.endswith(".reel.json"):
        sys.exit(check_reel(spec_path, spec, sys.argv[2] if len(sys.argv) > 2 else "", kks, WhisperModel))
    out = Path(spec["out"]).resolve()
    clips = out.with_name(out.stem + "_sora")
    model = WhisperModel(MODEL, device="cpu", compute_type="int8")
    bad = 0
    for c in spec["clips"]:
        f = clips / f"clip_{c['id']}.mp4"
        script = "".join(t for _, t in c["dialogue"])
        segs, _ = model.transcribe(pcm(f), language="ja", beam_size=5)
        heard = heard_text(segs)
        a, b = reading(script, kks), reading(heard, kks)
        ratio = difflib.SequenceMatcher(None, a, b).ratio()
        cut = not tail_silent(f)
        ok = ratio >= PASS_RATIO and not cut
        bad += not ok
        print(f"場面{c['id'].upper()}: {'合格' if ok else '要確認'}(読みの一致 {ratio:.0%}{'・最後が切れている' if cut else ''})")
        print(f"  台本  : {script}")
        print(f"  聞こえた: {heard}")
        if ratio < 1:
            for op, i1, i2, j1, j2 in difflib.SequenceMatcher(None, a, b).get_opcodes():
                if op != "equal":
                    print(f"  ちがい: 「{a[i1:i2]}」→「{b[j1:j2]}」")
    print("音声チェック: " + ("全部合格" if not bad else f"{bad}場面が要確認(社長に出す前に直す)"))
    sys.exit(1 if bad else 0)


def _reel_video(spec_path: Path, given: str) -> Path:
    if given:
        return Path(given).resolve()
    name = spec_path.name[: -len(".reel.json")] + ".mp4"
    week = spec_path.parent.name
    cands = [Path("content/output") / week / name]
    import os
    if os.getenv("MEDIA_DIR"):
        md = Path(os.environ["MEDIA_DIR"])
        cands += [md / week / name, md / name]
    for c in cands:
        if c.exists():
            return c.resolve()
    sys.exit(f"動画が見つかりません: {' / '.join(str(c) for c in cands)}(2つ目の引数で動画のパスを渡せます)")


def check_reel(spec_path: Path, spec: dict, given: str, kks, WhisperModel) -> int:
    """VOICEVOX のリール(1本の動画)を通しで書き起こして、台本の読みと比べる"""
    video = _reel_video(spec_path, given)
    lines = [(l.get("speech") or l.get("text") or "") for l in spec.get("lines", [])]
    script = "".join(lines)
    if not script:
        print("セリフがありません(声の無いリール)。音声チェック: 対象なし")
        return 0
    model = WhisperModel(MODEL, device="cpu", compute_type="int8")
    segs, _ = model.transcribe(pcm(video), language="ja", beam_size=5)
    heard = heard_text(segs)
    a, b = reading(script, kks), reading(heard, kks)
    sm = difflib.SequenceMatcher(None, a, b)
    ratio = sm.ratio()
    cut = not tail_silent(video)
    ok = ratio >= PASS_RATIO and not cut
    print(f"{spec_path.name}({video.name}): {'合格' if ok else '要確認'}(読みの一致 {ratio:.1%}{'・最後が切れている' if cut else ''})")
    print(f"  聞こえた: {heard}")
    if ratio < 1:
        # どの行のどこが違うかを、台本の行ごとに示す
        bounds, pos = [], 0
        for i, l in enumerate(lines):
            r = reading(l, kks); bounds.append((pos, pos + len(r), i)); pos += len(r)
        for op, i1, i2, j1, j2 in sm.get_opcodes():
            if op == "equal":
                continue
            row = next((n for s0, e0, n in bounds if s0 <= i1 < e0 or (i1 == i2 and s0 <= i1 <= e0)), None)
            where = f"{row + 1}行目「{lines[row][:24]}」" if row is not None else "末尾"
            print(f"  ちがい({where}): 「{a[i1:i2]}」→「{b[j1:j2]}」")
    print("音声チェック: " + ("合格" if ok else "要確認(聞いて確かめ、読み間違いなら speech を直して書き出し直す)"))
    return 0 if ok else 1


if __name__ == "__main__":
    main()
