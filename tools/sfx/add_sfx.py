#!/usr/bin/env python3
"""動画に効果音を重ねる(声はそのまま、効果音は小さく)。2026-11-10 追加。

使い方(会社のフォルダ ai-company で):
  python3 <秘書ハブ>/tools/sfx/add_sfx.py <元の動画.mp4> <効果音の指定.json> <書き出す動画.mp4>
効果音の指定(JSON): [{"t": 0.4, "file": "content/assets/sfx/ping.mp3", "vol": 0.5, "note": "なぜここで鳴らすか"}, ...]
  または計画の形 {"sounds": {"ping": {"query": "notification", "title": "Notification Sound"}}, "cues": [{"t": 0.4, "sound": "ping", "vol": 0.3}]}
  (計画の形なら、まだ取り込んでいない音を Openverse から CC0 で自動で取り込む。find_sfx.py と同じ)
- t = 鳴らし始める秒、vol = 音量(1.0 = 元の大きさ。声の邪魔をしないよう 0.2〜0.6 が目安)
- 書き出したあと、声の確認(tools/voice_check.py)をもう一度回す(効果音でセリフが聞き取りにくくなっていないか)
"""
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path


def main():
    if len(sys.argv) != 4:
        sys.exit(__doc__)
    src, cue_file, out = Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3])
    plan = json.loads(cue_file.read_text(encoding="utf-8"))
    cues = plan
    if isinstance(plan, dict):
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        import find_sfx
        files = {}
        for name, sd in plan.get("sounds", {}).items():
            have = sorted(Path("content/assets/sfx").glob(f"{name}.*"))
            have = [h for h in have if h.suffix != ".json"]
            if not have:
                print(find_sfx.fetch(sd["query"], sd["title"], name, sd.get("max_sec", 4.0)))
                have = [h for h in sorted(Path("content/assets/sfx").glob(f"{name}.*")) if h.suffix != ".json"]
            files[name] = str(have[0])
        cues = [{**c, "file": c.get("file") or files[c["sound"]]} for c in plan.get("cues", [])]
    if not cues:
        sys.exit("効果音の指定が空です")
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    import ffbin
    ff = ffbin.ffmpeg()
    if not ff:
        sys.exit("ffmpeg がありません(秘書ハブを一度 run_mac.command で起動すると、リールの部品と一緒に入ります)")
    args = [ff, "-y", "-loglevel", "error", "-i", str(src)]
    parts, labels = [], ["[0:a]"]
    for i, c in enumerate(cues, 1):
        f = Path(c["file"])
        if not f.exists():
            sys.exit(f"効果音のファイルがありません: {f}")
        args += ["-i", str(f)]
        ms = int(float(c["t"]) * 1000)
        parts.append(f"[{i}:a]aresample=48000,volume={float(c.get('vol', 0.4))},adelay={ms}|{ms}[s{i}]")
        labels.append(f"[s{i}]")
    parts.append(f"{''.join(labels)}amix=inputs={len(labels)}:duration=first:normalize=0[a]")
    out.parent.mkdir(parents=True, exist_ok=True)
    args += ["-filter_complex", ";".join(parts), "-map", "0:v", "-map", "[a]", "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", str(out)]
    subprocess.run(args, check=True)
    print(f"書き出し: {out}(効果音 {len(cues)}個)。次に声の確認(voice_check.py)を回してください")


if __name__ == "__main__":
    main()
