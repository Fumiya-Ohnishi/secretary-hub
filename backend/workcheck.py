"""部署の作業の「完了条件」「引き継ぎメモ」「始める前の点検」(2026-11-23 社長が A・B・C)

Anthropic の記事(Building effective agents / Effective harnesses for long-running agents)と、当社で実際に起きた事から:
- A 完了条件: タスクごとに、成果物の完了条件を JSON の一覧にしておく(data/acceptance/<ref>.json)。
  部署は各項目の passes(合格/未合格)と evidence(確かめた方法・数字)だけを書き換える。項目の削除・書き換えは禁止
  (足すのはよい)。作業のあと秘書ハブが確かめ、未合格・書き換えがあれば完了・承認待ちにしない
  (例: 2026-11-15 T-419 で BGM・効果音の入っていない版が承認まで通った)
- B 引き継ぎメモ: 部署は作業の区切りごとに data/handoff/<ref>.md へ「済んだこと・残り・次にやること」を書く。
  やり直しのときは、秘書ハブがそのメモを渡し、最初からではなく続きからやらせる(時間切れで最初からやり直していた)
- C 始める前の点検: 作業に要る道具(ffmpeg・ffprobe・node)が無ければ作業を始めず、社長に1日1回だけ知らせる
  (2026-11-23 Mac に ffmpeg が無く、動画のまとめで止まった)
"""
import datetime
import json
import re
import shutil
from pathlib import Path
from typing import Dict, List, Optional

import company

HUB_DATA = Path(__file__).resolve().parent / "data"
SNAP_DIR = HUB_DATA / "acceptance_snap"       # 作ったときの完了条件の写し(書き換えを見つけるため。git に入らない)
NOTIFIED = HUB_DATA / "preflight_notified.json"

VIDEO_WORDS = ("リール", "動画", "reel", "TikTok", "YouTube", "ショート", "mp4")
CAROUSEL_WORDS = ("カルーセル", "フィード", "carousel", "画像", "表紙", "バナー", "サムネ", "見出し画像")
NOTE_WORDS = ("note", "記事")
POST_WORDS = ("投稿", "承認待ち", "post", "Threads", "X の", "キャプション")


def acc_dir() -> Path:
    return company.COMPANY_DIR / "data" / "acceptance"


def hand_dir() -> Path:
    return company.COMPANY_DIR / "data" / "handoff"


def ref_of(job: dict) -> Optional[str]:
    """タスクごとのファイル名。会議・定例・参考アカウントなどタスクでない作業には作らない"""
    key = job.get("task_key") or ""
    if not key or key.startswith(("meeting:", "routine:", "watch:")):
        return None
    return re.sub(r"[^0-9A-Za-z_-]", "_", key)[:48]


def _has(text: str, words) -> bool:
    return any(w.lower() in text.lower() for w in words)


def _item(i: str, cat: str, desc: str, steps: List[str]) -> dict:
    return {"id": i, "category": cat, "description": desc, "steps": steps, "passes": False, "evidence": ""}


def default_criteria(job: dict) -> List[dict]:
    """作業の内容から、当社の決まり(playbooks)に沿った完了条件を作る"""
    text = f"{job.get('title', '')} {job.get('instruction', '')}"
    items = [_item("saved", "共通", "成果物を所定のフォルダに保存した(evidence に保存した場所を書く)",
                   ["保存したファイルの場所を確かめる"])]
    post = _has(text, POST_WORDS + VIDEO_WORDS + CAROUSEL_WORDS + NOTE_WORDS)
    if post:
        items.append(_item("format", "共通", "投稿ファイルが playbooks/post_format.md の形(front matter・status・account など)になっている",
                           ["投稿ファイルを開いて front matter を確かめる"]))
        items.append(_item("ai_label", "共通", "AI で作ったことを隠していない(画像・動画の隅に「AI製」、キャプションにも AI の行)",
                           ["書き出した画像・動画の隅を拡大して見る", "キャプションの AI の行を確かめる"]))
    if _has(text, VIDEO_WORDS):
        items += [
            _item("video_size", "動画", "縦 1080×1920 で書き出した", ["ffprobe で幅と高さを測る"]),
            _item("voice_ok", "動画", "声の確認(voice_check)が合格した(P-017)", ["voice_check を動かし、終了コード 0 を確かめる"]),
            _item("audio_in", "動画", "BGM・効果音が書き出した最後のファイルに入っている(reel_format §6 の数字を audio_check.md に残した)",
                  ["md5 で _base と完成が違うことを確かめる", "volumedetect で BGM のすき間と効果音の所を測る"]),
            _item("credits", "動画", "声と BGM のクレジット(「VOICEVOX:名前」「音楽：曲名 / 作者（OpenTracks）」)を画面かキャプションに入れた",
                  ["キャプションと画面の文字を確かめる", "BGM はファイルのタグの曲名と一致する(next_bgm.mjs)"]),
        ]
    if _has(text, CAROUSEL_WORDS):
        items.append(_item("image_size", "画像", "画像の寸法が決まりどおり(カルーセルは 1080×1350・10枚以内など)",
                           ["sips か ffprobe で寸法を測る"]))
    if _has(text, NOTE_WORDS):
        items += [
            _item("magazine", "note", "投稿ファイルに magazine:(入れるマガジン。入れないときは「なし」)を書いた", ["front matter を確かめる"]),
            _item("images", "note", "見出し画像と本文の画像がそろい、原稿の【画像】の印と番号が合っている(表は画像にした P-073)",
                  ["【画像】の印の数と画像のファイルを数える"]),
        ]
    if post:
        items.append(_item("qa", "共通", "品質管理部の合格(_check.md に合否票)を受けた", ["_check.md の該当の投稿の行を確かめる"]))
    return items


def prepare(job: dict) -> str:
    """作業を始める前: 完了条件の一覧と引き継ぎメモを用意し、部署への指示文に足す文を返す"""
    ref = ref_of(job)
    if not ref:
        return ""
    ap = acc_dir() / f"{ref}.json"
    hp = hand_dir() / f"{ref}.md"
    rel_a = ap.relative_to(company.COMPANY_DIR)
    rel_h = hp.relative_to(company.COMPANY_DIR)
    try:
        if not ap.exists():
            ap.parent.mkdir(parents=True, exist_ok=True)
            data = {"task_key": job.get("task_key"), "title": job.get("title", ""),
                    "created": datetime.datetime.now().isoformat(timespec="seconds"),
                    "rule": "部署は passes と evidence だけを書き換える。項目の削除・説明の書き換えは禁止(足すのはよい)",
                    "items": default_criteria(job)}
            ap.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
        SNAP_DIR.mkdir(parents=True, exist_ok=True)
        snap = SNAP_DIR / f"{ref}.json"
        if not snap.exists():
            snap.write_text(ap.read_text(encoding="utf-8"), encoding="utf-8")
    except Exception as e:
        return f"\n## 完了条件\n(用意できませんでした: {e})\n"
    memo = ""
    if hp.exists():
        memo = hp.read_text(encoding="utf-8")[-3000:]
    lines = ["", "## 完了条件(必ず守る。2026-11-23 社長)",
             f"- このタスクの完了条件は `{rel_a}`(JSON)。作業の最初に読み、作る物の目標にする",
             "- 各項目は、自分で確かめてから passes を true にし、evidence に確かめた方法と数字(例: ffprobe 1080x1920、audio_check.md の -48dB)を書く。"
             "確かめていない項目を true にしない。作った担当とは別の社員に確かめさせる",
             "- 項目の削除・説明(description・steps)の書き換えは禁止。足りない条件に気づいたら、新しい id で項目を足すのはよい",
             "- 秘書ハブは作業のあとこの一覧を確かめ、未合格の項目や書き換えがあれば、完了・承認待ちにしない(続きをもう一度頼む)",
             "", "## 引き継ぎメモ(必ず書く)",
             f"- 作業の区切りごと(1本できるごと・時間切れになりそうなとき・終わるとき)に `{rel_h}` を上書きする。"
             "中身は「## 済んだこと」「## 残り」「## 次にやること」「## 注意(前の作業で分かった落とし穴)」の4つ。短く具体的に(ファイルの場所を書く)"]
    if memo:
        lines += ["- **前の作業の引き継ぎメモがある。最初からやり直さず、メモの「次にやること」から続ける**。前の成果物が壊れていたら、新しいことを始める前に直す",
                  "", "### 前の作業の引き継ぎメモ(そのまま)", memo.strip()]
    return "\n".join(lines) + "\n"


def verify(job: dict) -> Optional[dict]:
    """作業のあと: 完了条件を確かめる。{"total","passed","failing":[説明],"tampered":[説明]}。一覧が無ければ None"""
    ref = ref_of(job)
    if not ref:
        return None
    ap = acc_dir() / f"{ref}.json"
    if not ap.exists():
        return None
    try:
        cur = json.loads(ap.read_text(encoding="utf-8"))
    except Exception as e:
        return {"total": 0, "passed": 0, "failing": [], "tampered": [f"完了条件のファイルが読めません({e})"]}
    items = cur.get("items") or []
    by_id = {i.get("id"): i for i in items}
    tampered = []
    snap = SNAP_DIR / f"{ref}.json"
    if snap.exists():
        try:
            orig = json.loads(snap.read_text(encoding="utf-8")).get("items") or []
            for o in orig:
                c = by_id.get(o.get("id"))
                if not c:
                    tampered.append(f"{o.get('id')}(項目が消された)")
                elif c.get("description") != o.get("description") or c.get("steps") != o.get("steps"):
                    tampered.append(f"{o.get('id')}(説明が書き換えられた)")
        except Exception:
            pass
    failing = [f"{i.get('id')}: {str(i.get('description', ''))[:40]}" for i in items if i.get("passes") is not True]
    return {"total": len(items), "passed": len(items) - len(failing), "failing": failing, "tampered": tampered}


def preflight(job: dict, env: Dict[str, str]) -> List[str]:
    """始める前の点検: この作業に要る道具が無ければ、その名前を返す"""
    text = f"{job.get('title', '')} {job.get('instruction', '')}"
    need = []
    if _has(text, VIDEO_WORDS):
        need += ["ffmpeg", "ffprobe", "node"]
    elif _has(text, CAROUSEL_WORDS):
        need += ["node"]
    path = env.get("PATH", "")
    return [t for t in need if not shutil.which(t, path=path)]


def notify_once(missing: List[str]) -> bool:
    """足りない道具を社長に知らせる(同じ道具は1日1回まで)。社長の手が要るので知らせる対象(P-065)"""
    today = datetime.date.today().isoformat()
    try:
        state = json.loads(NOTIFIED.read_text())
    except Exception:
        state = {}
    new = [m for m in missing if state.get(m) != today]
    if not new:
        return False
    for m in new:
        state[m] = today
    NOTIFIED.parent.mkdir(parents=True, exist_ok=True)
    NOTIFIED.write_text(json.dumps(state))
    try:
        import scheduler
        scheduler.notify("部署の作業を始められません",
                         f"Mac に {'・'.join(new)} が見つからないため、動画・画像の作業を止めています。秘書に「{new[0]} を入れたい」と伝えてください。", "error")
    except Exception:
        pass
    return True
