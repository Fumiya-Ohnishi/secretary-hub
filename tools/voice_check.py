#!/usr/bin/env python3
"""動画のセリフが「日本語として台本どおりに聞こえるか」を、提出前に機械で確かめる。

使い方(会社のフォルダ ai-company で):
    python3 ~/Documents/git/secretary-hub/tools/voice_check.py content/drafts/2026-47/honne01/sora/spec.json

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


def reading(text: str, kks) -> str:
    text = re.sub(r"[\s、。,.!?！？「」『』…・〜ー\-]", "", text)
    for d, k in (("1つ", "ひとつ"), ("2つ", "ふたつ"), ("3つ", "みっつ"), ("一つ", "ひとつ"), ("二つ", "ふたつ"), ("三つ", "みっつ")):
        text = text.replace(d, k)
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
    out = Path(spec["out"]).resolve()
    clips = out.with_name(out.stem + "_sora")
    model = WhisperModel(MODEL, device="cpu", compute_type="int8")
    bad = 0
    for c in spec["clips"]:
        f = clips / f"clip_{c['id']}.mp4"
        script = "".join(t for _, t in c["dialogue"])
        segs, _ = model.transcribe(pcm(f), language="ja", beam_size=5)
        heard = "".join(s.text for s in segs)
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


if __name__ == "__main__":
    main()
