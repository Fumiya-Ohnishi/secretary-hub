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

sys.path.insert(0, str(Path(__file__).resolve().parent))
import ffbin  # noqa: E402  ffmpeg / ffprobe の場所(秘書ハブの部品も探す)

FF, FP = ffbin.ffmpeg() or "ffmpeg", ffbin.ffprobe() or "ffprobe"

MODEL = "medium"  # 日本語の聞き取りに十分な大きさ(small では読み違いを見逃しやすい)
PASS_RATIO = 1.0  # 読みが1文字でも違えば要確認(「確かめますね」→「かしきめますね」は95%一致でも聞けば別の言葉)
TAIL_SEC = 0.25  # 最後にこれだけ無音がなければ「切れている」


def pcm(path: Path):
    import numpy as np
    raw = subprocess.run([FF, "-loglevel", "error", "-i", str(path), "-ac", "1", "-ar", "16000", "-f", "s16le", "-"],
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
LETTERS = {"A": "えー", "B": "びー", "C": "しー", "D": "でぃー"}  # 1文字の A・B(「AかBか」)。英単語の中の字は変えない(2026-11-10 部署の直しを取り込み)


def reading(text: str, kks) -> str:
    for w, r in WORDS:  # 英字の言葉は読みにそろえる(台本は「エーアイ」、聞き取りは「AI」のように分かれるため)
        text = text.replace(w, r)
    text = re.sub(r"(?<![A-Za-z])([A-D])(?![A-Za-z])", lambda m: LETTERS[m.group(1)], text)
    # 数字の書き方(21:00/21時・3.6・10件)と「この後/消した後」(のち と読まれる)をそろえる(2026-11-10 部署の直しを取り込み)
    text = re.sub(r"(この|その|あの|た|の)後", r"\1あと", norm_num(text))
    text = re.sub(r"[\s、。,.!?！？「」『』…・〜ー\-*()()]", "", text)
    for i, k in enumerate(COUNTERS):  # 1つ〜9つ・一つ〜九つ は「ひとつ」〜「ここのつ」
        text = text.replace(f"{i + 1}つ", k).replace(f"{KANJI_NUM[i]}つ", k)
    hira = "".join(x["hira"] for x in kks.convert(text))
    for d, k in zip("0123456789", ["ぜろ", "いち", "に", "さん", "よん", "ご", "ろく", "なな", "はち", "きゅう"]):
        hira = hira.replace(d, k)
    return hira


def tail_silent(path: Path, sec: float = TAIL_SEC) -> bool:
    out = subprocess.run([FF, "-hide_banner", "-i", str(path), "-af", "silencedetect=noise=-35dB:d=0.2", "-f", "null", "-"],
                         capture_output=True, text=True).stderr
    # 動画全体ではなく「音声の長さ」で見る(音声が映像より少し短いだけで「切れている」と出ていた。2026-11-10 社員の声)
    ad = subprocess.run([FP, "-v", "error", "-select_streams", "a:0", "-show_entries", "stream=duration", "-of", "csv=p=0", str(path)],
                        capture_output=True, text=True).stdout.strip()
    dur = float(ad) if ad and ad != "N/A" else float(subprocess.run(
        [FP, "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)], capture_output=True, text=True).stdout.strip())
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
        ratio = difflib.SequenceMatcher(None, a, b, autojunk=False).ratio()
        cut = not tail_silent(f)
        ok = ratio >= PASS_RATIO and not cut
        bad += not ok
        print(f"場面{c['id'].upper()}: {'合格' if ok else '要確認'}(読みの一致 {ratio:.0%}{'・最後が切れている' if cut else ''})")
        print(f"  台本  : {script}")
        print(f"  聞こえた: {heard}")
        if ratio < 1:
            for op, i1, i2, j1, j2 in difflib.SequenceMatcher(None, a, b, autojunk=False).get_opcodes():
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
    sm = difflib.SequenceMatcher(None, a, b, autojunk=False)
    ratio = sm.ratio()
    cut = not tail_silent(video)
    # 行ごとに判定する(2026-11-10 部署の直しを取り込み)。行の聞こえた部分が、speech の読みか text(画面の字)の読みの
    # どちらかと完全に一致すれば、その行は合格。一致の基準(1文字も違わない)は変えない
    texts = [(l.get("text") or l.get("speech") or "") for l in spec.get("lines", [])]
    rows, pos = [], 0
    for l in lines:
        r = reading(l, kks); rows.append((pos, pos + len(r))); pos += len(r)
    ops = sm.get_opcodes()

    def to_b(p: int) -> int:  # 台本の読みの位置 → 聞こえた読みの位置
        for op, i1, i2, j1, j2 in ops:
            if i1 <= p < i2 or (p == i2 == len(a)):
                return j1 + (p - i1 if op == "equal" else round((p - i1) * (j2 - j1) / max(1, i2 - i1)))
        return len(b)

    bad_rows = []
    for i, (s0, e0) in enumerate(rows):
        hb = b[to_b(s0):to_b(e0) if e0 < len(a) else len(b)]
        cands = {reading(lines[i], kks), reading(texts[i], kks)}
        if phon(hb) in {phon(c) for c in cands}:
            continue
        best = max(cands, key=lambda c: difflib.SequenceMatcher(None, c, hb, autojunk=False).ratio())
        bad_rows.append((i, best, hb))
    ok = not bad_rows and not cut
    print(f"{spec_path.name}({video.name}): {'合格' if ok else '要確認'}(全体の読みの一致 {ratio:.1%}・"
          f"行ごと {len(rows) - len(bad_rows)}/{len(rows)} 行一致{'・最後が切れている' if cut else ''})")
    print(f"  聞こえた: {heard}")
    for i, best, hb in bad_rows:
        print(f"  ちがい({i + 1}行目「{texts[i][:30]}」):")
        for op, i1, i2, j1, j2 in difflib.SequenceMatcher(None, best, hb, autojunk=False).get_opcodes():
            if op != "equal":
                print(f"      「{best[i1:i2]}」→「{hb[j1:j2]}」(台本の読み …{best[max(0, i1 - 6):i2 + 6]}… / 聞こえた …{hb[max(0, j1 - 6):j2 + 6]}…)")
    print("音声チェック: " + ("合格" if ok else "要確認(聞いて確かめ、読み間違いなら speech を直して書き出し直す)"))
    return 0 if ok else 1


O_ROW, E_ROW = set("おこごそぞとどのほぼぽもよろょ"), set("えけげせぜてでねへべぺめれ")


def phon(s: str) -> str:
    """同じ音に聞こえる長音の書き方をそろえる(とおり/とうり・せんせい/せんせえ)。比べるときだけ使う"""
    out = []
    for ch in s:
        if out and ch == "う" and out[-1] in O_ROW:
            ch = "お"
        elif out and ch == "い" and out[-1] in E_ROW:
            ch = "え"
        out.append(ch)
    return "".join(out)


KNUM = "〇一二三四五六七八九"


def _kanji_int(n: int) -> str:
    if n == 0:
        return "〇"
    out = ""
    for unit, ch in ((1000, "千"), (100, "百"), (10, "十")):
        q, n = divmod(n, unit)
        if q:
            out += ("" if q == 1 else KNUM[q]) + ch
    return out + (KNUM[n] if n else "")


def norm_num(text: str) -> str:
    """数字の書き方をそろえる(21:00→二十一時・3.6→三点六・10件→十件)。読みに直す前に使う"""
    text = re.sub(r"(\d+):00", r"\1時", text)
    text = re.sub(r"(\d+)\.(\d+)", lambda m: _kanji_int(int(m.group(1))) + "点" + "".join(KNUM[int(d)] for d in m.group(2)), text)
    return re.sub(r"\d{1,4}", lambda m: _kanji_int(int(m.group(0))), text)


if __name__ == "__main__":
    main()
