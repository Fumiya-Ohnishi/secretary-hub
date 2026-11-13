"""参考動画の分析(2026-11-13 社長「リールをコマ送りにせず見て参考にしたい。音の使い方・テロップの使い方を確認してほしい」)。

Claude は動画を音つきでそのまま見られないので、秘書ハブ(社長の Mac)が動画を次の形に分けてから映像制作部に渡す。
1. カット: 場面が切り替わる秒(ffmpeg の場面検出)
2. 音: 0.25秒ごとの音量の推移・無音の区間(ffmpeg で音を数に直して測る)
3. 言葉: 話している言葉を秒つきで文字に起こす(OpenAI の文字起こし。.env の OPENAI_API_KEY があるとき)
4. 画面: 最初の3秒は 0.25秒ごと、そのあとはカットの直後と 1.5秒ごとの静止画(テロップの出方を追う)
→ 映像制作部が、秒ごとの表(画面・テロップ・音)と「当社に取り入れる点」を analysis.md に書く。

他人の動画は分析のためだけに使う(転載しない)。元の動画は秘書ハブの中(backend/data/video_refs/。git に入らない)、
静止画は会社のフォルダの frames/(.gitignore で git に入れない)に置く。
"""
import array
import datetime
import json
import math
import os
import re
import shutil
import subprocess
import threading
from pathlib import Path
from typing import Dict, List, Optional

import company

DATA = Path(__file__).resolve().parent / "data" / "video_refs"
OUT_REL = Path("strategy") / "research" / "video_refs"
MAX_BYTES = 600 * 1024 * 1024
STEP = 0.25  # 音量を測る間隔(秒)
_state: Dict[str, dict] = {}


def _bin(name: str) -> str:
    try:
        import agent
        path = agent._job_env()["PATH"]
    except Exception:
        path = os.environ.get("PATH", "")
    found = shutil.which(name, path=path)
    if not found:
        raise RuntimeError(f"{name} が見つかりません(ターミナルで brew install ffmpeg)")
    return found


def _run(args: List[str], timeout: int = 300) -> subprocess.CompletedProcess:
    return subprocess.run(args, capture_output=True, text=True, timeout=timeout)


def slug(name: str) -> str:
    s = re.sub(r"[\\/:*?\"<>|\s]+", "_", (name or "").strip())[:40].strip("_")
    return s or "video"


# ---------- 測る ----------
def probe(path: Path) -> dict:
    r = _run([_bin("ffprobe"), "-v", "error", "-show_entries", "format=duration:stream=codec_type,width,height,r_frame_rate",
              "-of", "json", str(path)], 60)
    info = json.loads(r.stdout or "{}")
    v = next((s for s in info.get("streams", []) if s.get("codec_type") == "video"), {})
    has_audio = any(s.get("codec_type") == "audio" for s in info.get("streams", []))
    return {"duration": float((info.get("format") or {}).get("duration") or 0), "width": v.get("width"), "height": v.get("height"),
            "has_audio": has_audio}


def cuts(path: Path, threshold: float = 0.3) -> List[float]:
    r = _run([_bin("ffmpeg"), "-hide_banner", "-i", str(path), "-vf", f"select='gt(scene,{threshold})',showinfo", "-an", "-f", "null", "-"], 600)
    times = [float(m) for m in re.findall(r"pts_time:([0-9.]+)", r.stderr)]
    out = []
    for t in times:
        if not out or t - out[-1] > 0.2:
            out.append(round(t, 2))
    return out


def loudness(path: Path) -> List[float]:
    """STEP 秒ごとの音量(dBFS。無音に近いほど小さい)"""
    rate = 8000
    p = subprocess.run([_bin("ffmpeg"), "-hide_banner", "-loglevel", "error", "-i", str(path), "-vn", "-ac", "1", "-ar", str(rate),
                        "-f", "s16le", "-"], capture_output=True, timeout=600)
    samples = array.array("h")
    samples.frombytes(p.stdout[: len(p.stdout) // 2 * 2])
    n = int(rate * STEP)
    out = []
    for i in range(0, len(samples), n):
        chunk = samples[i:i + n]
        if not chunk:
            break
        rms = math.sqrt(sum(x * x for x in chunk) / len(chunk))
        out.append(round(20 * math.log10(rms / 32768), 1) if rms > 0 else -90.0)
    return out


def transcribe(path: Path, work: Path) -> Optional[List[dict]]:
    """話している言葉を秒つきで(OpenAI の文字起こし)。キーが無ければ None"""
    key = os.getenv("OPENAI_API_KEY", "").strip()
    if not key:
        return None
    audio = work / "audio.mp3"
    _run([_bin("ffmpeg"), "-hide_banner", "-loglevel", "error", "-y", "-i", str(path), "-vn", "-ac", "1", "-ar", "16000", "-b:a", "48k", str(audio)], 300)
    if not audio.exists() or audio.stat().st_size < 1000:
        return []
    import httpx
    with audio.open("rb") as f:
        r = httpx.post("https://api.openai.com/v1/audio/transcriptions", headers={"Authorization": f"Bearer {key}"},
                       data={"model": "whisper-1", "response_format": "verbose_json", "language": "ja"},
                       files={"file": ("audio.mp3", f, "audio/mpeg")}, timeout=300)
    r.raise_for_status()
    return [{"start": round(s["start"], 2), "end": round(s["end"], 2), "text": s["text"].strip()} for s in r.json().get("segments", [])]


def frame_times(duration: float, cut_list: List[float]) -> List[float]:
    ts = [round(i * STEP, 2) for i in range(int(min(3.0, duration) / STEP) + 1)]
    ts += [round(c + 0.15, 2) for c in cut_list]
    t = 4.5
    while t < duration:
        ts.append(round(t, 2))
        t += 1.5
    out = []
    for t in sorted(set(x for x in ts if x < duration - 0.05)):
        if not out or t - out[-1] >= 0.2:
            out.append(t)
    return out[:60]


def grab_frames(path: Path, times: List[float], dest: Path) -> List[str]:
    dest.mkdir(parents=True, exist_ok=True)
    names = []
    for t in times:
        name = f"{t:06.2f}s.jpg"
        _run([_bin("ffmpeg"), "-hide_banner", "-loglevel", "error", "-y", "-ss", f"{t}", "-i", str(path), "-frames:v", "1",
              "-vf", "scale=540:-2", "-q:v", "4", str(dest / name)], 60)
        if (dest / name).exists():
            names.append(name)
    return names


# ---------- まとめる ----------
def _bar(db: float) -> str:
    level = max(0, min(10, int((db + 60) / 6)))  # -60dB 以下=0、0dB=10
    return "█" * level + "·" * (10 - level)


def timeline_md(name: str, note: str, info: dict, cut_list: List[float], loud: List[float], words: Optional[List[dict]],
                frames: List[str]) -> str:
    lines = [f"# 参考動画の分析材料: {name}", "",
             f"- 秘書ハブが {datetime.datetime.now():%Y-%m-%d %H:%M} に作成。長さ {info['duration']:.1f}秒・{info.get('width')}×{info.get('height')}・音 {'あり' if info['has_audio'] else 'なし'}",
             f"- 社長のメモ: {note or '(なし)'}",
             "- 他人の動画は分析のためだけに使う。文章・画像・音は当社の投稿に使わない(型だけ学ぶ)", "",
             "## カット(場面が切り替わった秒)", ", ".join(f"{c:.2f}" for c in cut_list) or "(検出なし=1カット、または動きの少ない動画)", "",
             "## 言葉(秒つきの文字起こし)"]
    if words is None:
        lines.append("(OpenAI のキーが無いため未作成。画面の静止画と音量から判断する)")
    elif not words:
        lines.append("(話し声は見つからなかった。BGM・効果音だけの可能性)")
    else:
        lines += [f"- {w['start']:.2f}〜{w['end']:.2f}秒: {w['text']}" for w in words]
    lines += ["", f"## 音量の推移({STEP}秒ごと。█が多いほど大きい。-60dB以下はほぼ無音)", "```"]
    for i, db in enumerate(loud):
        t = i * STEP
        mark = " ← カット" if any(abs(t - c) < STEP / 2 + 0.01 for c in cut_list) else ""
        lines.append(f"{t:6.2f}s {_bar(db)} {db:6.1f}dB{mark}")
    lines += ["```", "", "## 画面の静止画(frames/。ファイル名=秒)", "最初の3秒は0.25秒ごと、そのあとはカットの直後と1.5秒ごと。",
              ", ".join(frames)]
    return "\n".join(lines) + "\n"


INSTRUCTION = """参考動画の分析をする(2026-11-13 社長「コマ送りでは分かりにくい、音の使い方とテロップの使い方を確認してほしい」)。
材料: {folder}/timeline.md(カット・秒つきの言葉・0.25秒ごとの音量)と {folder}/frames/ の静止画(ファイル名=秒)。全部の静止画を順に見る。
映像ディレクターが中心に、動画編集者・音声担当・ショート動画クリエイターの目でも見て、{folder}/analysis.md に次を書く:
1. 秒ごとの表: 秒 | 画面(何が映っているか) | テロップ(文言・位置・大きさ・色・出方/消え方) | 音(声・BGM・効果音・無音。音量の山と合わせて) | 狙い(推測は推測と書く)
2. 最初の3秒: 何で止めているか(画・文字・音のどれが先か、何秒で何が起きるか)
3. 音の使い方: BGM の入りと抜け、声と BGM の大きさの差、効果音が鳴る位置とテロップ・カットとの合わせ方、無音の使い方
4. テロップの使い方: 1枚あたりの文字数と表示秒数、出る速さ、強調の仕方、位置(Instagram の端で切れない範囲か)
5. 当社のリールに取り入れる点3つ(playbooks/reel_format.md のどこを直すか)と、取り入れない点1つ
音は音量の数字と文字起こしから判断し、分からないこと(曲名・効果音の種類など)は「推測」と書く。
他人の動画は型だけ学び、文章・画像・音を当社の投稿に使わない。最後に、学んだことを knowledge/external_insights.md に出典つき(社長が送った参考動画・日付)で1〜3行足す。"""


def _work(ref_id: str) -> Path:
    return DATA / ref_id


def save_upload(chunks, filename: str) -> str:
    ref_id = datetime.datetime.now().strftime("%Y%m%d%H%M%S")
    work = _work(ref_id)
    work.mkdir(parents=True, exist_ok=True)
    ext = (Path(filename or "").suffix.lower() or ".mp4")[:6]
    dest = work / f"source{ext}"
    size = 0
    with dest.open("wb") as f:
        for c in chunks:
            size += len(c)
            if size > MAX_BYTES:
                f.close()
                shutil.rmtree(work, ignore_errors=True)
                raise ValueError("動画が大きすぎます(600MBまで)")
            f.write(c)
    if size == 0:
        shutil.rmtree(work, ignore_errors=True)
        raise ValueError("動画が空でした")
    return ref_id


def analyze(ref_id: str, name: str, note: str = "", start_job: bool = True) -> dict:
    """分けて材料を作り、映像制作部に分析を頼む(時間がかかるので別スレッドから呼ぶ)"""
    work = _work(ref_id)
    src = next(work.glob("source.*"))
    st = _state.setdefault(ref_id, {"id": ref_id, "name": name, "status": "分析の材料を作成中", "error": "", "folder": "", "job": ""})
    try:
        info = probe(src)
        if info["duration"] <= 0:
            raise ValueError("動画の長さが読めませんでした")
        cut_list = cuts(src)
        loud = loudness(src) if info["has_audio"] else []
        try:
            words = transcribe(src, work) if info["has_audio"] else []
        except Exception as e:
            words, st["error"] = None, f"文字起こしはできませんでした: {str(e)[:120]}"
        folder = OUT_REL / f"{datetime.date.today():%Y-%m-%d}_{slug(name)}_{ref_id[-6:]}"
        base = company.COMPANY_DIR / folder
        frames = grab_frames(src, frame_times(info["duration"], cut_list), base / "frames")
        base.mkdir(parents=True, exist_ok=True)
        (base / "timeline.md").write_text(timeline_md(name, note, info, cut_list, loud, words, frames), encoding="utf-8")
        st.update(folder=str(folder), status="映像制作部が分析中" if start_job else "材料ができました")
        if start_job:
            import agent
            job = agent.start_job("映像", INSTRUCTION.format(folder=folder), f"参考動画の分析: {name}")
            st["job"] = job["id"]
    except Exception as e:
        st.update(status="失敗", error=str(e)[:300])
    return st


def start(ref_id: str, name: str, note: str) -> dict:
    _state[ref_id] = {"id": ref_id, "name": name, "status": "分析の材料を作成中", "error": "", "folder": "", "job": ""}
    threading.Thread(target=analyze, args=(ref_id, name, note), daemon=True).start()
    return _state[ref_id]


def listing() -> List[dict]:
    """これまでの分析(新しい順)。analysis.md ができていれば中身の頭も"""
    try:
        import agent
        jobs = {j["id"]: j for j in agent.job_list()}
    except Exception:
        jobs = {}
    root = company.COMPANY_DIR / OUT_REL
    done = {}
    for d in sorted(root.glob("*/"), reverse=True)[:30] if root.exists() else []:
        a = d / "analysis.md"
        done[str(d.relative_to(company.COMPANY_DIR))] = a.read_text(encoding="utf-8")[:1500] if a.exists() else None
    running = []
    for s in sorted(_state.values(), key=lambda x: x["id"], reverse=True):
        if s["folder"] and done.get(s["folder"]):
            continue
        j = jobs.get(s.get("job") or "")
        if j and j["status"] != "running" and s["status"] == "映像制作部が分析中":
            s["status"] = "分析が止まりました(部署の作業タブで確認してください)"
        running.append({"running": True, **s})
    shown = {s["folder"] for s in running}
    return running + [{"folder": f, "name": Path(f).name, "done": bool(t), "summary": t or ""}
                      for f, t in done.items() if f not in shown]
