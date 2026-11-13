"""秘書の頭脳: Claude(Anthropic API)に「道具」を持たせ、話しかけるだけで仕事が進むようにする。

道具: タスクの確認・起票・更新、Notion の資料を開く、画面の切り替え、部署(Claude Code)への作業依頼。
承認(承認待ち → 承認済み)と差し戻しだけは社長の操作で行う(就業規則)。秘書は承認カードを出すところまで。
"""
import asyncio
import datetime
import errno
import json
import os
import re
import shutil
import platform
import subprocess
import sys
import threading
from typing import Dict, List, Optional

from pathlib import Path

import anthropic

import company
import president_asks
import content
import corrections
import notion
import scheduler

API_KEY = os.getenv("ANTHROPIC_API_KEY", "").strip()
MODEL = os.getenv("ANTHROPIC_MODEL", "").strip() or "claude-opus-5-5"
EFFORT = os.getenv("ANTHROPIC_EFFORT", "low").strip()  # 会話は速さ優先
SECRETARY_NAME = os.getenv("SECRETARY_NAME", "セナ")

# 新しい世代のモデルだけが受け付ける設定(古いモデル名が .env に残っていても動くように分ける)
EFFORT_MODELS = ("claude-opus-5", "claude-fable-5", "claude-sonnet-5", "claude-haiku-5", "claude-mythos-5")
FALLBACK_MODELS = ("claude-opus-5-5", "claude-opus-5", "claude-fable-5-1", "claude-sonnet-5-5")

client = anthropic.AsyncAnthropic(api_key=API_KEY) if API_KEY else None

# 秘書ハブ自身の記録(作業履歴・API利用料)。git には入れない
DATA_DIR = Path(__file__).resolve().parent / "data"
DATA_DIR.mkdir(exist_ok=True)
JOBS_FILE = DATA_DIR / "jobs.json"
USAGE_FILE = DATA_DIR / "usage.json"
_lock = threading.Lock()

# 1Mトークンあたりの料金(米ドル: 入力, 出力)。一覧に無いモデルは Opus と同じとみなす
PRICES = {"claude-opus-5-5": (4, 20), "claude-opus-5": (5, 25), "claude-fable-5-1": (10, 50), "claude-fable-5": (10, 50),
          "claude-sonnet-5-5": (2, 10), "claude-sonnet-5": (2, 10), "claude-haiku-5-5": (0.1, 0.5),
          "claude-sonnet-4-6": (3, 15), "claude-sonnet-4-5": (3, 15), "claude-haiku-4-5": (1, 5)}
USD_JPY = float(os.getenv("USD_JPY", "150"))


def _load_json(path: Path, default):
    try:
        return json.loads(path.read_text())
    except Exception:
        return default


def _save_json(path: Path, data):
    with _lock:
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1))
        tmp.replace(path)


def add_usage(resp):
    u = getattr(resp, "usage", None)
    if not u:
        return
    fresh = getattr(u, "input_tokens", 0) or 0
    cache_read = getattr(u, "cache_read_input_tokens", 0) or 0
    cache_write = getattr(u, "cache_creation_input_tokens", 0) or 0
    inp = fresh + cache_read + cache_write
    out = getattr(u, "output_tokens", 0) or 0
    pin, pout = PRICES.get(MODEL, PRICES["claude-opus-5-5"])
    month = datetime.date.today().strftime("%Y-%m")
    data = _load_json(USAGE_FILE, {})
    m = data.setdefault(month, {"input": 0, "output": 0, "usd": 0.0, "calls": 0})
    m["input"] += inp
    m["cached"] = m.get("cached", 0) + cache_read  # 使い回せた入力(料金は1割)
    m["output"] += out
    # 料金: 使い回しの読み出しは1割、使い回し用の書き込みは1.25倍(5分の保存)
    cost_in = (fresh + cache_read * 0.1 + cache_write * 1.25) / 1e6 * pin
    m["usd"] = round(m["usd"] + cost_in + out / 1e6 * pout, 4)
    m["calls"] += 1
    _save_json(USAGE_FILE, data)


def usage_summary() -> dict:
    month = datetime.date.today().strftime("%Y-%m")
    m = _load_json(USAGE_FILE, {}).get(month, {"input": 0, "output": 0, "usd": 0.0, "calls": 0})
    return {**m, "month": month, "jpy": round(m["usd"] * USD_JPY), "rate": USD_JPY}

# ---------- 部署への作業依頼(Claude Code) ----------
# 部署(Notion の担当名 → 組織図の部署名)。旧部署名は新しい部署に読み替える
DEPT_FULL = {"戦略": "経営戦略部", "収益化": "収益化部", "企画": "企画編集部", "ライティング": "ライティング部",
             "デザイン": "デザイン部", "画像": "画像制作部", "映像": "映像制作部", "SNS運用": "SNS運用部",
             "品質管理": "品質管理部", "分析": "データ分析部", "制作": "ライティング部", "メディア": "SNS運用部", "秘書": "秘書室",
             "経理": "経理・税務部", "広報": "広報部", "人事": "人事部", "Codex": "社外制作室(Codex)"}
# 作るAIとチェックするAI: 投稿の中身を作る部署は、部内の上司のあと品質管理部(独立)が見てから承認待ちにする
CHECKED_DEPARTMENTS = ("企画編集部", "ライティング部", "デザイン部", "画像制作部", "映像制作部", "SNS運用部", "収益化部")


def _roster(dept_full: str) -> List[dict]:
    try:
        import org
        return org.chart().get(dept_full, [])
    except Exception:
        return []


OPINION_DEPARTMENTS = {"企画", "ライティング", "デザイン", "戦略", "収益化", "SNS運用", "映像", "画像", "分析", "広報", "人事"}  # 案出しで意見を広げてから上司がまとめる(品質管理部は独立して点検するので入れない)


def _env_facts() -> List[str]:
    """部署に渡す、秘書ハブが確かめた環境(部署の作業からは確かめられないもの)"""
    import httpx
    vv = os.getenv("VOICEVOX_URL", "http://127.0.0.1:50021").rstrip("/")
    try:
        ok = httpx.get(f"{vv}/version", timeout=3).status_code == 200
    except Exception:
        ok = False
    env = _job_env()
    try:
        nv = subprocess.run(["node", "--version"], capture_output=True, text=True, timeout=5, env=env).stdout.strip()
    except Exception:
        nv = "見つからない"
    ff = shutil.which("ffmpeg", path=env["PATH"])
    return ["## 環境(秘書ハブが確認済み。部署の作業から確かめる必要はない)",
            f"- VOICEVOX: {'起動中' if ok else '止まっている'}(リールの声は秘書ハブが VOICEVOX の起動中に自動で入れる。止まっていても書き出しは声なしで進めてよい)",
            f"- Node.js: {nv}(HyperFrames は 22 以上が必要)",
            f"- ffmpeg: {'使える' if ff else '見つからない'}",
            f"- 画像・動画の置き場所(Google ドライブ): {env.get('MEDIA_DIR', '見つからない')}", ""]


def _knowledge_brief(job: dict, dept: str) -> List[str]:
    try:
        import knowledge
        return knowledge.brief_for(job["instruction"], dept)
    except Exception as e:
        return [f"## 資料室\n(読み込めませんでした: {e}。knowledge/README.md を自分で読んで確認する)", ""]


def _job_prompt(job: dict) -> str:
    dept = DEPT_FULL.get(job["department"], job["department"])
    members = _roster(dept)
    bosses = [m for m in members if m["boss"]]
    staff = [m for m in members if not m["boss"]]
    roster = "\n".join(f"- {m['name']}({m['title']}{'・上司' if m['boss'] else ''}): {m['description']}" for m in members)
    lines = [f"あなたは AI会社の秘書室として、{dept}の作業を進めます。部署の社員はサブエージェントとして定義されています。",
             f"作業: {job['instruction']}", "", *_env_facts(), *_knowledge_brief(job, dept),
             f"## {dept}の社員", roster or "(定義なし。あなた自身が部署として作業する)", "",
             "## 進め方"]
    if staff and job["department"] in OPINION_DEPARTMENTS and len(staff) >= 2:
        lines.append("1. 案出しの段階では、性格・視点の違う担当2〜3名に、互いの案を見せずに別々に案を出させる(各社員の定義の「性格・視点」を参照)。"
                     "清書・仕上げは採用した案の担当1名に任せる(費用を抑えるため、意見を広げるのは案出しだけ。決まった手順だけの作業=書き出し・集計の写しなどは1名でよい)")
        if job["department"] == "SNS運用":
            lines.append("   SNS運用部は、媒体の担当どうしで「自分の媒体ならこう出す」を出し合い、運用マネージャーが媒体ごとの形にまとめる")
        if job["department"] == "戦略":
            lines.append("   方向転換・Phase移行・撤退・新しい施策を決めるときは、リスクアナリスト(慎重派)の「うまくいかない場合・やめる基準」を必ず入れる")
        if job["department"] == "映像":
            lines.append("   リールは、ショート動画クリエイター(視聴者目線)に0秒目・2秒ごとの変化・保存する理由を見させてから仕上げる")
        if bosses:
            lines.append(f"1b. 上司「{bosses[0]['name']}」が案を比べ、良いところを合わせて1つにまとめる。方向がずれた案は理由を添えて軌道修正する。"
                         "採らなかった案と理由・少数意見は作業フォルダの _discussion.md に1行ずつ残す")
    elif staff:
        lines.append("1. 作業に合う担当(複数可)のサブエージェントに作らせる")
    else:
        lines.append("1. 部署のサブエージェントに作業させる")
    if bosses:
        b = bosses[0]["name"]
        lines.append(f"2. 上司のサブエージェント「{b}」にチェックさせ、不合格なら担当に直させる(最大2回)。指摘は data/corrections.md に追記")
    if dept in CHECKED_DEPARTMENTS:
        qa = _roster("品質管理部")
        if qa:
            names = "・".join(m["name"] for m in qa if not m["boss"])
            lead = next((m["name"] for m in qa if m["boss"]), "qa-lead")
            lines.append(f"3. 投稿の中身ができたら、品質管理部の {names} にそれぞれチェックさせ、品質管理部長「{lead}」が合否を判定する。"
                         "不合格の指摘は直して再判定(最大2回)。合否票は content/drafts/YYYY-WW/_check.md、指摘は data/corrections.md に残す")
            lines.append("4. 合格した投稿だけ、状態を「承認待ち」にする")
    lines += ["", "## 守ること",
              "- CLAUDE.md(就業規則)と playbooks/learned_rules.md に従う。成果物は所定のフォルダに保存する(投稿セットは playbooks/post_format.md の形式)",
              "- 外部への投稿・申請・購入・ログインはしない。承認済み・差し戻しにはしない(承認は社長だけ)",
              "- Notion は読み込み・書き込みとも使ってよい(2026-11-10 社長)。ただし、タスクを「承認済み」「差し戻し」にするのは社長だけ。"
              "ページ・データベースは消さない。タスクを作ったら報告に番号と件名を書く。社長への確認は、これまでどおり報告の「## 社長への確認」に書く(秘書ハブが確認待ちにする)",
              "- 書き出しで使ってよいコマンドは決まっている(許可の確認で止まらないように): 書き出しスクリプトは週のフォルダに**必ず `render.mjs` という名前**で置き"
              "(表紙用も同じファイルに入れるか、引数で切り替える)、**必ず下の入口(week_render.mjs)から**動かす(`cd`・`&&`・`;`・`|` でつながない。1行に1コマンド)。"
              "画像の寸法は `sips -g pixelWidth -g pixelHeight <画像>` か ffprobe、字数は `wc -m <ファイル>`、JSON の確認は `python3 -m json.tool <ファイル>` で読める。"
              f"点検の拡大は `python3 {HUB_ROOT / 'tools' / 'image' / 'zoom.py'} <画像> <x> <y> <幅> <高さ> 3`(寸法は `... --size <画像>`)。"
              "ファイルを読む操作(cat・grep・head・ls・git log など)はパイプでつないでよい。cd・ループ・python3 -c は止まるので使わない。"
              "一時ファイルは /tmp ではなく content/output/_work/ に置く(Write で書けて、git に入らない)。"
              "秘書ハブ(secretary-hub)の道具やプログラムは読むだけ。書き換えない。道具の不具合や直してほしい点は、報告に「どの道具の・何が・どうなった(出力の全文)」を書く(統括秘書が直す)。"
              "`render_cover.mjs` など別の名前のスクリプトは動かせない",
              f"- 書き出し: カルーセルは `node {WEEK_RENDER} YYYY-WW <html> content/output/YYYY-WW <接頭辞>`(週のフォルダの render.mjs を動かす入口。実録の型)か "
              "`node tools/render/render_carousel.mjs <JSON> content/output/YYYY-WW/`。"
              f"リールは `node {REEL_DIR}/render_record_reel.mjs <台本.json> content/output/YYYY-WW/<名前>.mp4`(実録の型。声は秘書ハブが VOICEVOX で入れる)。"
              f"動きを作り込むときは HyperFrames(`npx --yes {HF} <command>`。.claude/skills/hyperframes の当社ルールを守る。auth・cloud・publish・events は使えない)。"
              "ffmpeg / ffprobe はそのまま使える",
              f"- 動画の声の確認(P-017。提出前に必ず): `{HUB_PY} {VOICE_CHECK} content/drafts/YYYY-WW/<名前>.reel.json`(VOICEVOX のリール。動画は content/output/YYYY-WW/<名前>.mp4 か Google ドライブから自動で探す)"
              "か `... <spec.json>`(Higgsfield の会話のリール)。終了コード 0 なら合格。「要確認」は、ちがいの行を聞いて確かめ、読み間違いなら speech を直して書き出し直す",
              f"- 効果音: 探す `python3 {HUB_ROOT / 'tools' / 'sfx' / 'find_sfx.py'} \"<英語の言葉>\" --list` → `--pick <番号> --name <名前>`(CC0 だけ・台帳に自動で記録)。"
              f"重ねる `python3 {HUB_ROOT / 'tools' / 'sfx' / 'add_sfx.py'} <元の動画> <計画.json> <書き出す動画>`。重ねたあと声の確認をやり直す",
              f"- AI で画像を作るときは `python3 {IMAGE_TOOL} --out content/output/YYYY-WW/<名前>.png --aspect 4:5 --prompt \"...\"`"
              "(キャラクターをそろえるときは `--ref <今の絵>` を付ける)。キーは秘書ハブが渡すので、**会社のフォルダで API キーを探さない・置かない**。"
              "作った画像は data/asset_rights.md に「AI生成(OpenAI)・プロンプトの要約・日付」を記録する",
              "- 完成した画像・動画は git に入れない。既存の動画・画像は環境変数 MEDIA_DIR の Google ドライブ(週ごとのフォルダ)にある。"
              "比べるときはそこから読み、新しく書き出したものは content/output/YYYY-WW/ に置く(秘書ハブがドライブへ写す)",
              "- 上司・品質管理部のチェックは、作った担当とは別のサブエージェントにさせる(自分で作ったものを自分で合格にしない)",
              f"- 制限時間は{_job_timeout_min()}分。1本(1ファイル)できるごとに保存し、全部を最後にまとめて書かない。時間が足りなそうなら、終わった分だけ仕上げて「残り」を書いて終える",
              "- Notion に自分でページを作らない。成果物は会社のフォルダの所定の場所に保存すれば、秘書ハブが作業の終わりに"
              "Notion「AI会社 > 作業ログ」(日付・部署ごと)と worklog/YYYY-MM/YYYY-MM-DD/ にまとめて載せる",
              "- 作業で困ったこと・こうしてほしいこと(指示が曖昧・道具が足りない・時間が足りない・受け渡しの問題など)があった社員は、"
              "data/employee_voice.md に `- YYYY-MM-DD 部署 社員名: 内容` を1行ずつ足す(なければ書かない。人事部が毎週まとめる)",
              "- 社長に判断・確認してほしいことがあれば、data/tasks.md には書かず(タスクの起票は秘書ハブがする)、"
              "最後のまとめのあとに、次の形の「## 社長への確認」を必ず書く。1件ごとに件名の行を分け、"
              "件名は何についての判断かが社長に件名だけで分かる1行にする(点数・社内の略語・記号だけの件名は書かない)。"
              "秘書ハブがこれを読んで、社長の「確認待ち」タスクにする。社長に聞くことが無ければ書かない\n" + president_asks.FORMAT_HELP,
              "- 最後に、誰が何をして、どのファイルに保存したか、チェックの結果を日本語で3行以内でまとめる"]
    return "\n".join(lines)


jobs: Dict[str, dict] = _load_json(JOBS_FILE, {})
for _j in jobs.values():  # 前回の起動中に終わらなかった作業
    if _j.get("status") == "running":
        _j.update(status="error", output=(_j.get("output") or "") + "\n(秘書ハブの再起動で中断しました)")


def _save_jobs():
    keep = dict(sorted(jobs.items(), key=lambda kv: kv[1]["started"])[-50:])
    _save_json(JOBS_FILE, keep)


def _publish_worklog(job: dict, before: Optional[dict]):
    """作業の成果を作業ログ(Notion・worklog/日付フォルダ)に載せる"""
    import worklog
    try:
        files = worklog.changed(before) if before is not None else []
        job["changed_files"] = files[:80]
        r = asyncio.run(worklog.publish(job, files))
        job["worklog"] = r
        if r.get("url") or r.get("local"):
            job["output"] = (job.get("output") or "") + f"\n\n— 作業ログ: {r.get('url') or ''} {r.get('local') or ''}".rstrip()
    except Exception as e:
        job["worklog"] = {"error": str(e)[:200]}


def _record_president_asks(job: dict):
    """作業報告の「社長への確認」を、社長の確認待ちタスクにする(確認漏れを防ぐ。2026-11-10 社長の指示)"""
    try:
        made = asyncio.run(president_asks.from_job(job))
    except Exception as e:
        job["output"] = (job.get("output") or "") + f"\n\n(社長への確認をタスクにできませんでした: {str(e)[:120]})"
        return
    if made:
        job["asked_tasks"] = [t.get("id") for t in made]
        lines = "\n".join(f"- {t.get('id')} {t.get('title')}" for t in made)
        job["output"] = (job.get("output") or "") + f"\n\n— 社長への確認を「確認待ち」のタスクにしました:\n{lines}"
        try:
            import scheduler
            scheduler.notify("社長の確認待ちが増えました", "、".join(t.get("title", "") for t in made)[:200], "info")
        except Exception:
            pass


def _run_job(job_id: str):
    job = jobs[job_id]
    try:
        import worklog
        before = worklog.snapshot()
    except Exception:
        before = None
    if job["department"] == "Codex":
        return _run_codex_job(job, before)
    advisor = _codex_before(job)
    prompt = _job_prompt(job) + advisor
    try:
        if not shutil.which("claude"):
            raise RuntimeError("Claude Code CLI が見つかりません。ターミナルで `npm install -g @anthropic-ai/claude-code` → `claude` で一度ログインしてください。")
        _wait_cooldown(job)
        _run_claude_streaming(job, prompt)
        # 一時的な通信のつまずき(Cloudflare の 403・混雑など)は、待ってから自動でやり直す(2026-11-13 社長「このエラー何?」)
        for wait in (60, 180):
            if job["status"] == "done" or not _transient(job.get("output") or ""):
                break
            started = datetime.datetime.fromisoformat(job["started"])
            if (datetime.datetime.now() - started).total_seconds() > 20 * 60:  # 長く進んだ作業は最初からやり直さない
                break
            _set_cooldown(wait)
            job["log"] = (job.get("log") or []) + [f"通信のエラー(一時的なもの)。{wait}秒待ってやり直します"]
            job.update(status="running", output="")
            _save_jobs()
            import time
            time.sleep(wait)
            _wait_cooldown(job)
            _run_claude_streaming(job, prompt)
    except Exception as e:
        job.update(status="error", output=(job.get("output") or "") + f"\n{e}")
    if job["status"] == "done":
        _codex_after(job)
    job["finished"] = datetime.datetime.now().isoformat(timespec="seconds")
    _publish_worklog(job, before)
    _record_president_asks(job)
    _save_jobs()
    key = job.get("task_key") or ""
    if key and not key.startswith(("meeting:", "routine:")):
        try:
            async def finish():
                status, note = decide_task_status(job, job.get("changed_files") or [])
                try:  # 社長が承認済みにしたタスクの続きの作業なら、承認を取り直さず完了にする
                    cur = await company.find_task(key)
                    if cur.get("status") == "承認済み" and status == "承認待ち":
                        status, note = "完了", "承認済みの続きの作業が完了(秘書が完了と判定)"
                except Exception:
                    pass
                auto = scheduler.plan_for_task(key) is not None
                await company.update_task(key, status=status, append_note=f"{note}({job['finished'][5:16]})")
                if status == "完了" and auto:  # 逆算プランの工程は、終わったら次の工程へ
                    await scheduler.advance()
            asyncio.run(finish())
        except Exception:
            pass


POST_FILE_RE = re.compile(r"^content/drafts/\d{4}-\d{2}/\d+[^/]*\.md$")
DECISION_ONLY = ("決める", "承認か差し戻し", "を確認し", "で確認", "を読み", "選択")  # 社長の判断だけで終わるタスク
NEEDS_PRESIDENT = ("社長の承認", "社長に確認", "社長が決め", "社長の判断", "承認待ちにする")


def decide_task_status(job: dict, files: List[str]) -> tuple:
    """作業が終わったタスクの状態を、秘書が決める(完了判定は秘書の仕事: 就業規則)
    - 作業が止まった(エラー・時間切れ) → 未着手(やり直しが必要)
    - 投稿の中身を作り、承認待ちの投稿がある、または社長の判断が要る作業 → 承認待ち(承認は社長だけ)
    - それ以外(秘書・部署だけで完結した作業)→ 完了"""
    if job.get("status") != "done":
        why = "時間切れ" if "制限時間" in (job.get("output") or "") else "エラー"
        return "未着手", f"作業が途中で止まりました({why})。やり直しが必要・秘書が再依頼"
    waiting = []
    for f in files:
        if POST_FILE_RE.match(f):
            try:
                if "status: 承認待ち" in (company.COMPANY_DIR / f).read_text(encoding="utf-8")[:600]:
                    waiting.append(Path(f).name)
            except Exception:
                pass
    if waiting:
        return "承認待ち", f"作業完了。承認待ちの投稿 {len(waiting)}本(投稿タブで確認・承認は社長)"
    if job.get("asked_tasks"):  # 社長への確認は別のタスク(確認待ち)に分けたので、この作業は終わり
        return "完了", f"作業完了。社長への確認は {'・'.join(job['asked_tasks'])}(確認待ち)に分けました"
    text = (job.get("title") or "") + (job.get("instruction") or "")
    if any(w in text for w in NEEDS_PRESIDENT):
        return "確認待ち", "作業完了。社長の判断待ち(作業タブ・作業ログで結果を確認)"
    return "完了", "作業完了(秘書が完了と判定。結果は作業ログ)"


async def tidy_tasks() -> dict:
    """「進行中」のまま止まっているタスクを、終わった作業の結果に合わせて直す(社長の担当は触らない)"""
    data = await company.summary()
    running = {j.get("task_key") for j in jobs.values() if j.get("status") == "running"}
    latest: Dict[str, dict] = {}
    for j in sorted(jobs.values(), key=lambda j: j.get("started") or ""):
        if j.get("task_key"):
            latest[j["task_key"]] = j
    week_tasks = {}
    for wk in sorted((company.COMPANY_DIR / "content" / "drafts").glob("20*-*/_week.md")):
        m = re.search(r"^task:\s*(\S+)", wk.read_text(encoding="utf-8"), re.M)
        if m:
            week_tasks[m.group(1)] = wk.parent
    changed = {"完了": 0, "承認待ち": 0, "未着手": 0}
    # 承認済みのあと: 投稿セットは全部投稿済みで完了(content.sync_week_task)。判断だけのタスクは承認で終わりなので完了にする
    for t in data["tasks"]:
        if t.get("status") != "承認済み" or t["key"] in running:
            continue
        title = t.get("title") or ""
        if t.get("id") in week_tasks:
            try:
                await content.sync_week_task(week_tasks[t["id"]].name)
            except Exception:
                pass
            continue
        if t.get("assignee") == "社長" or any(w in title for w in DECISION_ONLY):
            try:
                await company.update_task(t["key"], status="完了", append_note=f"社長の判断で終わり(承認済み→完了 {datetime.datetime.now():%m/%d %H:%M} 秘書が整理)")
                changed["完了"] += 1
            except Exception:
                pass
    for t in data["tasks"]:
        if t.get("status") != "進行中" or t.get("assignee") == "社長" or t["key"] in running:
            continue
        note = (t.get("title") or "") + " " + (t.get("note") or "")  # 控えファイルではメモが件名の後ろに付く
        j = latest.get(t["key"])
        if j and j.get("status") in ("done", "error"):
            status, why = decide_task_status(j, j.get("changed_files") or [])
        elif "作業完了(" in note or "作業エラー(" in note:
            last_ok, last_ng = note.rfind("作業完了("), note.rfind("作業エラー(")
            if last_ng > last_ok:
                status, why = "未着手", "作業が途中で止まっていました。やり直しが必要・秘書が再依頼"
            else:
                wd = week_tasks.get(t.get("id") or "")
                pending = wd and any("status: 承認待ち" in p.read_text(encoding="utf-8")[:600] for p in wd.glob("[0-9]*.md"))
                if pending or any(w in t.get("title", "") for w in NEEDS_PRESIDENT):
                    status, why = "承認待ち", "作業は終わっています。社長の承認待ち"
                else:
                    status, why = "完了", "作業は終わっています(秘書が完了と判定)"
        else:
            continue
        try:
            await company.update_task(t["key"], status=status, append_note=f"{why}({datetime.datetime.now():%m/%d %H:%M} 秘書が整理)")
            changed[status] += 1
        except Exception:
            pass
    return changed


def _codex_note(job: dict, desc: str, status: str = "running"):
    job.setdefault("activity", []).append({"agent": "codex", "desc": desc, "status": status,
                                           "started": datetime.datetime.now().isoformat(timespec="seconds")})


def _codex_before(job: dict) -> str:
    """会議の前に、社外顧問(Codex)の意見を用意して指示に足す(Codex が無ければ何もしない)"""
    import codex
    key = job.get("task_key") or ""
    if not key.startswith("meeting:") or not codex.advisor_enabled():
        return ""
    try:
        import meetings
        k = meetings.KINDS.get(key.split(":", 1)[1], meetings.KINDS["adhoc"])
        _codex_note(job, "社外顧問として会議の前に意見を用意")
        path = codex.meeting_advice(k["name"], job.get("instruction", "")[:600])
        job["activity"][-1]["status"] = "done"
        return ("\n\n## 社外顧問(Codex=別の会社のAI)\n"
                f"- 会議の前に用意した意見が {path} にある。2周目の前に司会が読み上げ、参加者に賛否を言わせる\n"
                "- 議事録の参加者に「社外顧問(Codex)」を入れ、発言に要点を書く。少数意見の節に、採った/採らなかった と理由を残す")
    except Exception as e:
        if job.get("activity"):
            job["activity"][-1]["status"] = "error"
        return f"\n\n(社外顧問の意見は用意できませんでした: {str(e)[:120]})"


def _codex_after(job: dict):
    """品質管理の最終チェックと戦略の判断のあと、社外顧問がもう一つの目で見る(合否・結論は変えない)"""
    import codex
    if not codex.advisor_enabled():
        return
    dept = job.get("department_full") or DEPT_FULL.get(job["department"], "")
    try:
        if dept in CHECKED_DEPARTMENTS or job["department"] == "品質管理":
            _codex_note(job, "社外顧問として承認待ちの投稿を見立て")
            n = codex.review_posts()
            job["activity"][-1]["status"] = "done"
            if n:
                job["output"] = (job.get("output") or "") + f"\n\n— 社外顧問(Codex)が承認待ちの投稿{n}本に見立てを書き足しました(投稿の末尾)。"
        path = codex.strategy_review(job) if job["department"] == "戦略" else None
        if path:
            job["output"] = (job.get("output") or "") + f"\n\n— 社外顧問(Codex)の反対検討: {path}"
            try:
                scheduler.notify("社外顧問(Codex)の反対検討", f"{job['title']} について、別の会社のAIの反対意見を {path} に残しました", "info")
            except Exception:
                pass
    except Exception as e:
        if job.get("activity"):
            job["activity"][-1]["status"] = "error"
        job["output"] = (job.get("output") or "") + f"\n\n(社外顧問の確認はできませんでした: {str(e)[:160]})"


def _run_codex_job(job: dict, before: Optional[dict] = None):
    """社外制作室(Codex): 別の会社のAIが投稿の別案を作る → 秘書ハブが画像・動画を作る → 当社の品質管理部が点検"""
    import codex
    try:
        codex.run(job, codex.prompt(job["instruction"], _knowledge_brief(job, "社外制作室")), _job_timeout_min())
        media = codex.make_media(job)
        wk = codex.current_week()
        drafts = sorted((company.COMPANY_DIR / "content" / "drafts" / wk).glob("*_codex.md"))
        job["output"] = (job.get("output") or "") + f"\n\n— 秘書ハブ: {media}。別案 {len(drafts)}本。"
        job["status"] = "done"
        if drafts:
            names = "、".join(p.name for p in drafts)
            qa = start_job("品質管理", f"社外制作室(Codex=別の会社のAI)が作った投稿の別案 content/drafts/{wk}/ の {names} を、当社の投稿と同じ基準"
                           "(CLAUDE.md・playbooks/visual_standard.md・社長の好みの確定分)で点検する。画像・動画は MEDIA_DIR か content/output で確認。"
                           "合格した別案だけ status を「承認待ち」にし、不合格は「下書き」のまま理由を _check.md に残す。"
                           "当社案と比べて良い点があれば knowledge/lessons.md に1行残す(出典: Codex案)", "Codex案の点検", job.get("task_key"))
            job["output"] += f" 品質管理部に点検を頼みました(作業ID {qa['id']})。"
    except Exception as e:
        job.update(status="error", output=(job.get("output") or "") + f"\n{e}")
    job["finished"] = datetime.datetime.now().isoformat(timespec="seconds")
    _publish_worklog(job, before)
    _save_jobs()


SUBAGENT_TOOLS = ("Task", "Agent")  # Claude Code がサブエージェントを呼ぶ道具の名前(版によって違う)
HUB_ROOT = Path(__file__).resolve().parent.parent
# 部署が使ってよいコマンド(画像・リールの書き出しと、その確認だけ。それ以外のコマンドは許可しない)
REEL_DIR = HUB_ROOT / "tools" / "reel"
IMAGE_TOOL = HUB_ROOT / "tools" / "image" / "gen_image.py"
WEEK_RENDER = HUB_ROOT / "tools" / "render" / "week_render.mjs"
VOICE_CHECK = HUB_ROOT / "tools" / "voice_check.py"  # 声の確認(P-017)。音声認識の部品が入った秘書ハブの Python で動かす
HUB_PY = HUB_ROOT / "backend" / "venv" / "bin" / "python"  # 週の render.mjs を動かす入口(途中に * のある許可は効かないため)
HF = "hyperframes@0.9.19"  # ai-company/.claude/skills/hyperframes と同じ版に固定
# Notion は読み込みも書き込みも、どの場面でも許可する(2026-11-10 社長の指示)。サーバーごと許可する(名前は Mac の Claude Code の接続名)
# ただし「承認済み・差し戻しにするのは社長だけ」「ページを消さない」は指示書で守らせる(CLAUDE.md 社長との約束)
NOTION_TOOLS = ["mcp__claude_ai_Notion", "mcp__Notion"]
ALLOWED_TOOLS = [
    "Bash(node tools/render/render_carousel.mjs:*)",
    f"Bash(node {WEEK_RENDER}:*)",
    "Bash(sips -g:*)", "Bash(wc:*)", "Bash(python3 -m json.tool:*)",  # 画像の寸法を読む・字数を数える・JSON を確かめる(読むだけ。2026-11-10 社長 T-150)
    f"Bash(node {REEL_DIR}/render_reel.mjs:*)",
    f"Bash(node {REEL_DIR}/render_record_reel.mjs:*)",
    f"Bash(npx --yes {HF}:*)", f"Bash(npx {HF}:*)",
    "Bash(ffmpeg:*)", "Bash(ffprobe:*)",
    f"Bash(python3 {IMAGE_TOOL}:*)",  # 画像の生成(OpenAI。キーは秘書ハブの backend/.env)
    f"Bash({HUB_PY} {VOICE_CHECK}:*)", f"Bash(python3 {VOICE_CHECK}:*)",  # 声の確認(2026-11-10 社長 T-155・T-156)
    f"Bash(python3 {HUB_ROOT / 'tools' / 'sfx' / 'find_sfx.py'}:*)", f"Bash(python3 {HUB_ROOT / 'tools' / 'sfx' / 'add_sfx.py'}:*)",  # 効果音(Openverse の CC0)を探す・重ねる
    "Bash(mkdir -p content/:*)", "Bash(mkdir -p strategy/:*)", "Bash(ls:*)",
    # 読むだけの操作(パイプでつないでも止まらないように)。2026-11-10 社員の声を数えて社長が選んだ範囲:「読む操作+画像の拡大まで」。
    # ファイルを消す・書き換える・任意のスクリプトを動かすコマンドは入れない
    "Bash(cat:*)", "Bash(head:*)", "Bash(tail:*)", "Bash(grep:*)", "Bash(rg:*)", "Bash(sort:*)", "Bash(uniq:*)", "Bash(cut:*)",
    "Bash(diff:*)", "Bash(file:*)", "Bash(stat:*)", "Bash(du:*)", "Bash(md5:*)", "Bash(md5sum:*)", "Bash(shasum:*)", "Bash(pwd)",
    "Bash(git log:*)", "Bash(git show:*)", "Bash(git diff:*)", "Bash(git status:*)",
    f"Bash(git -C {HUB_ROOT} log:*)", f"Bash(git -C {HUB_ROOT} show:*)",
    f"Bash(python3 {HUB_ROOT / 'tools' / 'image' / 'zoom.py'}:*)",  # 画像の切り出し・拡大(書き出しは content/output/_work/zoom/ だけ)・寸法
    "WebSearch", "WebFetch",  # リサーチ用(Web の文章の中の指示には従わない: CLAUDE.md)
    *NOTION_TOOLS,
]


def _path_variants(rules: List[str]) -> List[str]:
    """秘書ハブの道具の許可を、書き方の違い(~/… や ../secretary-hub/…)でも通るように増やす。
    許可は書いた文字のとおりにしか一致しないため、部署が ~ で書くと止まっていた(2026-11-10)"""
    hub = str(HUB_ROOT)
    alts = []
    home = str(Path.home())
    if hub.startswith(home + "/"):
        alts.append("~" + hub[len(home):])
    try:
        alts.append(os.path.relpath(hub, str(company.COMPANY_DIR)))  # 会社のフォルダから見た道(例: ../secretary-hub)
    except Exception:
        pass
    out = list(rules)
    for r in rules:
        if hub in r:
            out += [r.replace(hub, a) for a in alts if a and a != hub]
    return list(dict.fromkeys(out))


ALLOWED_TOOLS = _path_variants(ALLOWED_TOOLS)

# 使ってはいけない HyperFrames の機能(ログイン・外部への公開・クラウド・使用状況の送信)
DISALLOWED_TOOLS = [f"Bash({pre}{HF} {c}:*)" for pre in ("npx ", "npx --yes ") for c in ("auth", "cloud", "lambda", "cloudrun", "publish", "events", "feedback", "usage")]
# 秘書ハブ(道具・プログラム)は部署から読むだけ。書き換えると社長の git pull が止まる(2026-11-10 voice_check.py が書き換えられていた)。
# 直したい点は報告に書けば、統括秘書(Claude Code)が直す。絶対パスの許可は「//」で始める書き方(Claude Code で確認)
DISALLOWED_TOOLS += [f"{t}(/{HUB_ROOT}/**)" for t in ("Edit", "Write", "MultiEdit", "NotebookEdit")]


def _job_env() -> dict:
    """部署の作業に渡す環境: ffmpeg の場所、使用状況を送らない設定、画像・動画の置き場所"""
    env = dict(os.environ)
    paths = ["/opt/homebrew/bin", "/usr/local/bin"]  # ダブルクリック起動だと Homebrew の場所が PATH に無いことがある
    node22 = REEL_DIR / "node_modules" / "node" / "bin"  # HyperFrames 用の Node.js 22(部品として入れたもの)
    if (node22 / "node").exists():
        paths.insert(0, str(node22))
    ff = REEL_DIR / "node_modules" / "ffmpeg-static" / "ffmpeg"
    if ff.exists():
        paths.insert(0, str(ff.parent))
        env["FFMPEG"] = env["HYPERFRAMES_FFMPEG_PATH"] = str(ff)
    arch = {"x86_64": "x64", "amd64": "x64", "aarch64": "arm64"}.get(platform.machine().lower(), platform.machine().lower())
    probe = REEL_DIR / "node_modules" / "ffprobe-static" / "bin" / sys.platform / arch / "ffprobe"
    if probe.exists():
        paths.insert(0, str(probe.parent)); env["HYPERFRAMES_FFPROBE_PATH"] = str(probe)
    env["PATH"] = ":".join(paths + [env.get("PATH", "")])
    env.update(HYPERFRAMES_NO_TELEMETRY="1", HYPERFRAMES_NO_UPDATE_CHECK="1", HUB_URL=os.getenv("HUB_URL", "http://127.0.0.1:8000"))
    # 部署の作業は Claude Code にログインしているプラン(Pro / Max)の枠で動かす。
    # API キーを渡すと Claude Code はそちらを優先し、API の残高から払われてしまうため外す(.env の JOBS_USE_API_KEY=1 で従来どおり)
    if os.getenv("JOBS_USE_API_KEY", "").strip() not in ("1", "true", "yes"):
        for k in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN"):
            env.pop(k, None)
    md = content.media_dir()
    if md:
        env["MEDIA_DIR"] = str(md)
    return env


def _extra_dirs() -> List[str]:
    """部署が読み書きしてよい、会社のフォルダ以外の場所(リールの道具、Google ドライブの画像・動画)"""
    out = ["--add-dir", str(HUB_ROOT / "tools")]  # リール・画像・書き出し・声の確認の道具(中身を読んで使い方を確かめられるように)
    md = content.media_dir()
    if md and md.exists():
        out += ["--add-dir", str(md)]
    return out


def _stop_proc(proc):
    """作業(claude)を止める。まず穏やかに止め、5秒で止まらなければ強制終了"""
    try:
        proc.terminate()
        proc.wait(timeout=5)
    except Exception:
        try:
            proc.kill()
        except Exception:
            pass


def _run_claude_streaming(job: dict, prompt: str):
    """Claude Code を実行し、誰(どのサブエージェント)が何をしているかを job["activity"] に逐次記録する"""
    job.setdefault("activity", [])
    job.setdefault("log", [])
    proc = subprocess.Popen(["claude", "-p", prompt, "--permission-mode", "acceptEdits",
                             "--output-format", "stream-json", "--verbose", *_extra_dirs(),
                             "--allowedTools", *ALLOWED_TOOLS, "--disallowedTools", *DISALLOWED_TOOLS],
                            cwd=str(company.COMPANY_DIR), stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            text=True, encoding="utf-8", errors="replace", env=_job_env())
    limit_min = _job_timeout_min()
    timed_out = threading.Event()
    disk_full = threading.Event()

    def _kill():
        timed_out.set()
        proc.kill()
    timer = threading.Timer(limit_min * 60, _kill)
    timer.start()
    result_text, is_error, plain = None, False, []
    by_id = {}
    last_save = 0.0
    try:
        for line in proc.stdout:
            line = line.strip()
            if not line:
                continue
            try:
                ev = json.loads(line)
            except ValueError:
                plain.append(line)  # 古い版などで JSON でない出力
                continue
            kind = ev.get("type")
            content_items = ((ev.get("message") or {}).get("content") or []) if kind in ("assistant", "user") else []
            for c in content_items if isinstance(content_items, list) else []:
                if kind == "assistant" and c.get("type") == "tool_use" and c.get("name") in SUBAGENT_TOOLS:
                    inp = c.get("input") or {}
                    act = {"id": c.get("id"), "agent": inp.get("subagent_type") or "general-purpose",
                           "desc": inp.get("description") or (inp.get("prompt") or "")[:60], "status": "running",
                           "started": datetime.datetime.now().isoformat(timespec="seconds"), "finished": None}
                    by_id[act["id"]] = act
                    job["activity"].append(act)
                elif kind == "assistant" and c.get("type") == "text" and c.get("text", "").strip():
                    job["log"] = (job["log"] + [c["text"].strip()[:300]])[-30:]
                elif kind == "user" and c.get("type") == "tool_result" and c.get("tool_use_id") in by_id:
                    act = by_id[c["tool_use_id"]]
                    act["status"] = "error" if c.get("is_error") else "done"
                    act["finished"] = datetime.datetime.now().isoformat(timespec="seconds")
            if kind == "result":
                result_text = ev.get("result") or ""
                is_error = bool(ev.get("is_error"))
            now = datetime.datetime.now().timestamp()
            if now - last_save > 2:
                last_save = now
                try:
                    _save_jobs()
                except OSError as e:
                    # 状態を保存できなくても作業は続ける。ただしディスクが満杯なら作業も書けないので止める
                    if e.errno == errno.ENOSPC:
                        disk_full.set()
                        _stop_proc(proc)
                        break
        proc.wait()
    finally:
        timer.cancel()
        # どんな理由でここに来ても、作業(claude)を裏で動かしたままにしない(2026-11-10: 二重に動いた)
        if proc.poll() is None:
            _stop_proc(proc)
    err = (proc.stderr.read() or "").strip() if proc.stderr else ""
    for act in job["activity"]:
        if act["status"] == "running":
            act.update(status="error" if proc.returncode else "done", finished=datetime.datetime.now().isoformat(timespec="seconds"))
    out = result_text if result_text is not None else "\n".join(plain) or err
    ok = proc.returncode == 0 and not is_error and not timed_out.is_set() and not disk_full.is_set()
    job.update(status="done" if ok else "error", output=(out or "")[-6000:] + ("" if ok or not err else f"\n{err[-1000:]}"))
    if disk_full.is_set():
        job["output"] = (job["output"] + "\n\n" if job["output"].strip() else "") + \
            "【秘書より】Mac のディスクがいっぱいになったので、作業を止めました(作業は裏で動き続けていません)。" \
            "容量を空けてから、同じ作業をもう一度頼んでください。途中までの成果物は会社のフォルダに残っています。"
    elif timed_out.is_set():
        job["output"] = (job["output"] + "\n\n" if job["output"].strip() else "") + _timeout_note(job, limit_min)
    elif not ok:
        if not (out or "").strip() and not err:  # 中身が空のまま止まったとき、途中経過を残す
            job["output"] = _progress_note(job) or f"(終了コード {proc.returncode}。出力なし)"
        job["output"] += _job_hint((out or "") + " " + err)


def _job_timeout_min() -> int:
    """部署の作業の制限時間(分)。.env の JOB_TIMEOUT_MIN で変えられる(既定 90 分)"""
    try:
        return max(10, int(os.getenv("JOB_TIMEOUT_MIN", "90")))
    except ValueError:
        return 90


def _progress_note(job: dict) -> str:
    """止まるまでに誰が何をしたか(作業タブで原因を追えるように)"""
    acts = job.get("activity", [])
    lines = [f"- {a['agent']}: {a['desc']}({'済' if a['status'] == 'done' else '途中' if a['status'] == 'running' else '失敗'})" for a in acts[-12:]]
    logs = [f"> {t}" for t in job.get("log", [])[-3:]]
    return "\n".join((["## 止まるまでの作業"] + lines if lines else []) + (["## 最後のメモ"] + logs if logs else []))


def _timeout_note(job: dict, limit_min: int) -> str:
    return (f"【秘書より】{limit_min}分の制限時間で止めました(エラーではなく時間切れです)。"
            "途中までに保存したファイルは残っています。作業が大きすぎるので、媒体ごと・1本ずつなどに分けて頼み直してください"
            "(制限時間は .env の JOB_TIMEOUT_MIN で変えられます)。\n\n" + _progress_note(job))


TRANSIENT = ("attention required", "cloudflare", "overloaded", "529", "api error: 500", "api error: 502", "api error: 503",
             "api error: 504", "connection error", "econnreset", "socket hang up", "fetch failed")


_cooldown = {"until": 0.0}  # 通信が止められたら、全部の部署の次の作業をしばらく待たせる(一斉にやり直して、また止められるのを防ぐ)


def _wait_cooldown(job: dict):
    import time
    left = _cooldown["until"] - time.time()
    if left > 0:
        job["log"] = (job.get("log") or []) + [f"通信が混み合っているので、{int(left)}秒待ってから始めます"]
        time.sleep(left)


def _set_cooldown(sec: int):
    import time
    _cooldown["until"] = max(_cooldown["until"], time.time() + sec)


def _transient(text: str) -> bool:
    """しばらく待てば直る通信のつまずきか(ログインや残高の問題は含めない)"""
    t = (text or "").lower()
    if "credit balance" in t or "invalid api key" in t or "not logged in" in t:
        return False
    return any(k in t for k in TRANSIENT)


def _job_hint(text: str) -> str:
    """よくある止まり方に、社長が分かる言葉の説明を足す"""
    t = text.lower()
    if "attention required" in t or "cloudflare" in t:
        return ("\n\n【秘書より】Claude のサーバーの入口(Cloudflare)が、この Mac からの通信を一時的に止めました(403)。"
                "社長のログインや設定の問題ではないことが多く、数分たつと通ります。秘書ハブが自動で2回やり直しても通らなかったときは、"
                "VPN を使っていれば切る・Wi-Fi を変える・status.anthropic.com で障害が出ていないか見る、のあとで同じ作業をもう一度頼んでください")
    if "overloaded" in t or "529" in t:
        return "\n\n【秘書より】Claude のサーバーが混み合っていました。少し時間をおいて、もう一度頼んでください"
    if "credit balance" in t:
        return ("\n\n【秘書より】API の残高が足りません。部署の作業はプラン(Pro / Max)で動く設定ですが、.env に JOBS_USE_API_KEY=1 があると API の残高を使います。"
                "その行を消すか、console.anthropic.com の Billing で残高を足してください")
    if "invalid api key" in t or "/login" in t or "not logged in" in t or "please run" in t and "login" in t:
        return "\n\n【秘書より】Claude Code にログインしていません。Mac のターミナルで `claude` を開き、`/login` で Pro のアカウントにログインしてから、もう一度頼んでください"
    if "usage limit" in t or "rate limit" in t or "limit reached" in t:
        return "\n\n【秘書より】プラン(Pro)の利用枠に達しました。表示された時刻を過ぎると、また使えます。そのあと、もう一度頼んでください"
    if "model" in t and ("not available" in t or "not found" in t or "access" in t):
        return "\n\n【秘書より】プランで使えないモデルが指定されています。秘書に「部署の作業を Pro で使えるモデルにして」と伝えてください"
    return ""


def member_status() -> Dict[str, dict]:
    """社員(サブエージェント)ごとの今の状況: {name: {state, desc, job, at}}
    作業が始まって、まだ担当を呼んでいない間(段取り中)は、その部署の上司を作業中にする"""
    status: Dict[str, dict] = {}
    for j in sorted(jobs.values(), key=lambda j: j["started"]):
        for a in j.get("activity", []):
            cur = status.get(a["agent"])
            at = a.get("finished") or a.get("started")
            if a["status"] == "running" and j["status"] == "running":
                status[a["agent"]] = {"state": "working", "desc": a["desc"], "job": j["title"], "at": a["started"]}
            elif not cur or cur["state"] != "working":
                status[a["agent"]] = {"state": "idle", "desc": a["desc"], "job": j["title"], "at": at,
                                      "result": a["status"]}
    for j in jobs.values():
        if j["status"] != "running" or any(a["status"] == "running" for a in j.get("activity", [])):
            continue
        dept = j.get("department_full") or DEPT_FULL.get(j["department"], j["department"])
        boss = next((m["name"] for m in _roster(dept) if m["boss"]), None)
        if boss and status.get(boss, {}).get("state") != "working":
            status[boss] = {"state": "working", "desc": "段取り中(担当を決めています)" if not j.get("activity") else "まとめ・確認中",
                            "job": j["title"], "at": j["started"]}
    return status


def start_job(department: str, instruction: str, title: str, task_key: Optional[str] = None) -> dict:
    job_id = datetime.datetime.now().strftime("%m%d%H%M%S%f")
    jobs[job_id] = {"id": job_id, "title": title, "department": department,
                    "department_full": DEPT_FULL.get(department, f"{department}部"), "instruction": instruction,
                    "status": "running", "output": "", "task_key": task_key, "activity": [], "log": [],
                    "started": datetime.datetime.now().isoformat(timespec="seconds"), "finished": None}
    _save_jobs()
    threading.Thread(target=_run_job, args=(job_id,), daemon=True).start()
    return jobs[job_id]


def job_list() -> List[dict]:
    return sorted(jobs.values(), key=lambda j: j["started"], reverse=True)


# ---------- 道具の定義 ----------
EDITABLE = ["未着手", "進行中", "確認待ち", "承認待ち", "完了"]
DEPARTMENTS = ["戦略", "収益化", "企画", "ライティング", "デザイン", "画像", "映像", "SNS運用", "品質管理", "分析", "経理", "広報", "人事", "Codex"]
PANELS = ["home", "content", "calendar", "tasks", "docs", "jobs", "org", "chat"]


def _tool(name, description, props, required):
    return {"name": name, "description": description,
            "input_schema": {"type": "object", "properties": props, "required": required, "additionalProperties": False}}


TOOLS = [
    _tool("get_tasks", "会社のタスク一覧を取得する。status を指定するとその状態だけ。",
          {"status": {"type": "string", "enum": company.STATUSES}}, []),
    _tool("create_task", "タスクを新しく起票する(状態は未着手)。社長の依頼で起票するときに使う。",
          {"title": {"type": "string", "description": "具体的なタスク名"},
           "assignee": {"type": "string", "enum": company.ASSIGNEES},
           "due": {"type": "string", "description": "期限 YYYY-MM-DD。分からなければ省略"},
           "note": {"type": "string"}}, ["title", "assignee"]),
    _tool("update_task", "タスクの状態・期限・備考を変える。承認済み・差し戻しにはできない(それは ask_approval で社長に確認する)。",
          {"task": {"type": "string", "description": "タスクID(例 T-009)"},
           "status": {"type": "string", "enum": EDITABLE},
           "due": {"type": "string", "description": "新しい期限 YYYY-MM-DD(「来週金曜」などは今日の日付から計算する)。期限を消すときは空文字"},
           "note": {"type": "string", "description": "備考に追記する内容"}}, ["task"]),
    _tool("ask_approval", "承認待ちのタスクについて、社長に承認か差し戻しを決めてもらう。画面に承認カードを出す。"
          "社長が「承認して」「差し戻して」と言ったときもこれを使う(確定は社長がカードのボタンか「はい」で行う)。",
          {"task": {"type": "string", "description": "タスクID"}}, ["task"]),
    _tool("list_documents", "Notion の資料(企画書・アカウント設計など)の一覧を取得する。", {}, []),
    _tool("open_document", "Notion の資料を画面に開き、内容を読む。要約や質問への回答に使う。",
          {"query": {"type": "string", "description": "資料名の一部、または Notion の URL/ID"}}, ["query"]),
    _tool("show_panel", "画面右側の表示を切り替える。home=ホーム, content=投稿セット, calendar=週の予定, tasks=タスク, docs=資料, "
          "jobs=部署の作業, org=組織図(社員と稼働状況), chat=会話履歴",
          {"panel": {"type": "string", "enum": PANELS}}, ["panel"]),
    _tool("delegate_work", "部署(Claude Code)に作業を依頼する。企画・リサーチ・原稿作成・分析など、時間のかかる作業に使う。"
          "department=Codex は社外制作室(別の会社のAI=OpenAI Codex)。投稿の『別案』を作らせ、当社案と比べたいときに使う(画像・動画も作る。点検は自動で品質管理部へ)。"
          "依頼と同時にタスクを起票(進行中)し、完了すると画面に通知される。",
          {"department": {"type": "string", "enum": DEPARTMENTS},
           "title": {"type": "string", "description": "タスク名(短く)"},
           "instruction": {"type": "string", "description": "部署への具体的な指示文(目的・成果物・保存先)"}},
          ["department", "title", "instruction"]),
    _tool("get_jobs", "部署に依頼した作業の状況(実行中・完了・エラーと結果)を取得する。", {}, []),
    _tool("get_content", "週の投稿セット(台本・キャプション・状態)を取得し、画面に投稿セットを表示する。week 省略時は最新の週。",
          {"week": {"type": "string", "description": "YYYY-WW(ISO週)"}}, []),
    _tool("ask_content_approval", "週の投稿セットについて、社長に承認か差し戻しを決めてもらう。投稿セット画面と承認カードを出す"
          "(確定は社長のボタンか「はい」で行う)。", {"week": {"type": "string", "description": "YYYY-WW。省略時は最新の週"}}, []),
    _tool("record_revenue", "収益を記録する(data/revenue.csv と Notion の収益DB)。社長が売上を報告したときに使う。",
          {"amount": {"type": "integer", "description": "金額(円)"},
           "source": {"type": "string", "enum": company.REVENUE_SOURCES, "description": "note_sales=本アカウントのnote販売, sub_note=別アカウントのnote販売, "
                      "lancers=ランサーズ, coconala=ココナラ, main_instagram など=本アカウントの媒体, sub_instagram など=別アカウントの媒体, "
                      "amazon_affiliate=Amazonアフィ, other=その他。請け負いの入金は、秘書ハブのアカウント>請け負いで社長が入れるのが基本"},
           "date": {"type": "string", "description": "YYYY-MM-DD。省略時は今日"},
           "memo": {"type": "string"}}, ["amount", "source"]),
    _tool("record_followers", "媒体のフォロワー数を記録する(data/followers.csv)。",
          {"platform": {"type": "string", "enum": company.PLATFORMS},
           "followers": {"type": "integer"},
           "date": {"type": "string", "description": "YYYY-MM-DD。省略時は今日"},
           "account": {"type": "string", "description": "アカウントの id。main=本アカウント(定時AI・セナ・既定)/ sub=別アカウント1(note fond_egret1686)/ 増えたものは sub2・sub3…(一覧は data/account_sets.json)"}}, ["platform", "followers"]),
    _tool("record_post_insight", "投稿1本の数字(保存・いいね・表示など)を、その媒体の記録(data/insights_*.csv)に書く。"
          "社長が「インスタの○○、保存30」のように報告したときに使う。言われていない数字は空のままにする。",
          {"platform": {"type": "string", "enum": company.PLATFORMS},
           "content_id": {"type": "string", "description": "投稿ID(例 2026-46-01)。分からなければ投稿の題名"},
           "values": {"type": "object", "description": "列名→数値。instagram: format,reach,saves,likes,comments,profile_visits,follows / "
                      "x: impressions,likes,reposts,replies,follows / threads: views,likes,replies,follows / note: metric,value"},
           "date": {"type": "string", "description": "YYYY-MM-DD。省略時は今日"},
           "account": {"type": "string", "description": "アカウントの id。main=本アカウント(定時AI・セナ・既定)/ sub=別アカウント1(note fond_egret1686)/ 増えたものは sub2・sub3…(一覧は data/account_sets.json)"}}, ["platform", "values"]),
    _tool("add_improvement", "アカウントの改善点を1行記録する(data/improvements.md。アカウント画面に出る)。"
          "社長の気づき・分析部の金曜の見直しの結論を残すときに使う。",
          {"platform": {"type": "string", "enum": company.PLATFORMS},
           "text": {"type": "string", "description": "改善点(1〜2文)"}}, ["platform", "text"]),
    _tool("watch_account", "社長や秘書が見つけた気になるアカウント(競合・お手本)を参考アカウントの台帳(Notion と data/watch_accounts.csv)に入れて監視対象にし、"
          "経営戦略部に評価(長所・短所・投稿の型・当社との違い・取り入れること・差別化)を頼む。以後は毎週月曜のリサーチで確認する。",
          {"url": {"type": "string", "description": "アカウントの URL(https://...)"},
           "found_by": {"type": "string", "enum": ["社長", "秘書"], "description": "見つけた人"},
           "memo": {"type": "string", "description": "社長が気になった点など(任意)"}}, ["url"]),
    _tool("instagram_lookup", "Meta 公式の仕組みで、Instagram のプロアカウントのフォロワー数・投稿数・最近の投稿(種類・いいね・コメント)を調べる。"
          "社長が「この人のフォロワー何人?」「最近どんな投稿が伸びてる?」と聞いたときに使う。個人アカウントは取れない。",
          {"url": {"type": "string", "description": "プロフィール URL か ユーザー名"}}, ["url"]),
    _tool("instagram_hashtag", "Meta 公式の仕組みで、ハッシュタグの人気投稿(種類・いいね・コメント・リンク)を調べる。1週間に30タグまで。投稿者名は返らない。",
          {"tag": {"type": "string", "description": "ハッシュタグ(#なしでよい)"}}, ["tag"]),
    _tool("register_account", "開設したSNSアカウントのURLを台帳(data/accounts.md と Notion)に記録する。URLだけを扱う。",
          {"platform": {"type": "string", "enum": company.PLATFORMS},
           "url": {"type": "string", "description": "https:// から始まるプロフィールURL"},
           "opened": {"type": "string", "description": "開設日 YYYY-MM-DD。省略時は今日"},
           "account": {"type": "string", "description": "アカウントの id。main=本アカウント(定時AI・セナ・既定)/ sub=別アカウント1(note fond_egret1686)/ 増えたものは sub2・sub3…(一覧は data/account_sets.json)"}}, ["platform", "url"]),
    _tool("create_plan", "期限から逆算して、工程ごとのタスクを日付つきで起票する(逆算スケジュール)。"
          "部署の工程は、前の工程が終わると秘書が自動で部署に依頼する。投稿セットの基本形(週): 週テーマと構成(企画)→原稿・台本(ライティング)"
          "→画像・図解(デザイン/画像)とリール(映像)→媒体ごとの仕上げ(SNS運用、品質管理部のチェック込み)→社長の承認(社長)→投稿(社長)。"
          "各工程の期限は最終期限から逆算して決める。",
          {"title": {"type": "string", "description": "プラン名(例: 2026-47 投稿セット)"},
           "deadline": {"type": "string", "description": "最終期限 YYYY-MM-DD"},
           "steps": {"type": "array", "description": "工程(順番どおり)", "items": {"type": "object", "properties": {
               "title": {"type": "string"},
               "assignee": {"type": "string", "enum": company.ASSIGNEES},
               "due": {"type": "string", "description": "YYYY-MM-DD"},
               "instruction": {"type": "string", "description": "部署への具体的な指示(社長の工程なら社長がすること)"}},
               "required": ["title", "assignee", "due", "instruction"], "additionalProperties": False}}},
          ["title", "deadline", "steps"]),
    _tool("start_posting", "投稿アシスタントを開く。承認済みの投稿を1件ずつ、キャプションのコピー・画像の保存・注意点・"
          "「投稿しました」の順に案内する。社長が「今日の投稿を始めて」「投稿したい」と言ったときに使う。", {}, []),
    _tool("run_check_now", "定時チェック(今日やること・遅れ・自動依頼・社長へのお願い)を今すぐ行う。", {}, []),
    _tool("remember_preference", "社長の好み・方針(見た目・言葉づかい・やる/やらない・優先順位など)を資料室に記録する。会話の中で社長がそう言ったら自動で使ってよい。"
          "必ず先に、アカウントの軸(コンセプト)と確定済みの好み(会社データの資料室の行)と照らし合わせる。"
          "食い違う・曖昧・言い直しが必要なら needs_check=true(確認待ちに入る。社長に「軸の○○と食い違うので確認させてください」と聞く)。"
          "はっきりしていて軸と一致するなら false(確定に入る)。一時的な指示(今回だけ)は記録しない。",
          {"text": {"type": "string", "description": "好みを1文で(何を・どうする/しない)"},
           "needs_check": {"type": "boolean", "description": "軸や確定済みの好みと食い違う・曖昧・言い直しが必要なら true"},
           "reason": {"type": "string", "description": "needs_check のとき、どこと食い違うか・何が曖昧か"}}, ["text", "needs_check"]),
    _tool("decide_preference", "確認待ちの社長の好みを、社長の返事に従って確定(言い直し可)または却下する。",
          {"id": {"type": "string", "description": "P-xxx"}, "approve": {"type": "boolean"},
           "revised": {"type": "string", "description": "社長が言い直した文(あれば)"}}, ["id", "approve"]),
    _tool("search_knowledge", "資料室(過去の失敗と再発防止・うまくいった型・審査・リサーチ・数字)から、関係する知見を探す。"
          "社長に「前にどうだった?」「同じ失敗してない?」と聞かれたとき、仕事を頼む前に確認するときに使う。",
          {"query": {"type": "string"}}, ["query"]),
    _tool("hold_meeting", "部署をまたぐ会議を開く(企画会議・振り返り会議・全体会議・臨時会議)。社長に「○○について会議して」と言われたとき、"
          "同じ差し戻しが2回あった・作業が止まったときに使う。議事録は Notion「議事録」に載り、やることは自動で起票され、決まったことが通知される。",
          {"kind": {"type": "string", "enum": ["planning", "review", "allhands", "adhoc"], "description": "planning=企画会議 review=振り返り allhands=全体 adhoc=臨時"},
           "topic": {"type": "string", "description": "議題(臨時会議は必須)"},
           "departments": {"type": "array", "items": {"type": "string"}, "description": "参加部署(正式名。例: デザイン部)。省略時は会議の種類の既定"}}, ["kind"]),
    _tool("propose_rule", "過去の失敗を繰り返さないためのルール案を出す(社長が承認すると learned_rules.md に追加)。"
          "社長が「これをルールにして」と言ったときや、同じ指摘が繰り返されたときに使う。",
          {"rule": {"type": "string", "description": "1行のルール(〜する / 〜しない)"},
           "reason": {"type": "string", "description": "なぜ必要か(どの指摘が繰り返されたか)"}}, ["rule", "reason"]),
    _tool("ask_rule_approval", "社長の判断待ちのルール案について、承認カードを出す(確定は社長)。", {}, []),
    _tool("create_weekly_report", "週次レポートを作る(reports/weekly_YYYY-WW.md と Notion)。完成すると画面に開く。時間が少しかかる。",
          {"week": {"type": "string", "description": "YYYY-WW。省略時は今週"}}, []),
]


def _short(t: dict) -> dict:
    return {k: t.get(k) for k in ("id", "title", "assignee", "status", "due", "note") if t.get(k)}


async def _find_doc(query: str) -> Optional[dict]:
    pid = notion.page_id_from(query)
    if pid:
        return {"id": pid}
    docs = await notion.list_documents()
    q = query.replace(" ", "").lower()
    for d in docs:
        if q and q in d["title"].replace(" ", "").lower():
            return d
    words = [w for w in re.split(r"[\s・、の]+", query) if len(w) >= 2]
    scored = sorted(docs, key=lambda d: -sum(w in d["title"] for w in words))
    return scored[0] if scored and words and any(w in scored[0]["title"] for w in words) else None


async def run_tool(name: str, args: dict, actions: List[dict]) -> str:
    if name == "get_tasks":
        tasks = await company.list_tasks()
        if args.get("status"):
            tasks = [t for t in tasks if t["status"] == args["status"]]
        return json.dumps([_short(t) for t in tasks], ensure_ascii=False)

    if name == "create_task":
        t = await company.create_task(args["title"], args.get("assignee", "秘書"), args.get("due"), args.get("note", ""))
        actions.append({"type": "refresh"})
        return f"起票しました: {t['id']} {t['title']}"

    if name == "update_task":
        status = args.get("status")
        if status in ("承認済み", "差し戻し"):
            return "エラー: 承認・差し戻しは社長が行います。ask_approval でカードを出してください。"
        t = await company.find_task(args["task"])
        t = await company.update_task(t["key"], status=status, due=args.get("due"),
                                      append_note=args.get("note") and f"{args['note']}({datetime.date.today():%m/%d})")
        actions.append({"type": "refresh"})
        return f"更新しました: {t['id']} 状態={t['status']} 期限={t['due'] or 'なし'}"

    if name == "ask_approval":
        t = await company.find_task(args["task"])
        actions.append({"type": "approval", "task": t})
        return (f"承認カードを表示しました({t['id']} {t['title']}・現在 {t['status']})。"
                "社長がボタンを押すか「はい/承認」と答えると確定します。まだ確定していません。")

    if name == "list_documents":
        if not notion.configured():
            return "Notion が未接続です(backend/.env に NOTION_TOKEN が必要)。"
        actions.append({"type": "show_panel", "panel": "docs"})
        docs = await notion.list_documents()
        return json.dumps([{"title": d["title"], "id": d["id"], "kind": "データベース" if d.get("kind") == "database" else "ページ"} for d in docs[:80]], ensure_ascii=False)

    if name == "open_document":
        if not notion.configured():
            return "Notion が未接続です(backend/.env に NOTION_TOKEN が必要)。"
        doc = await _find_doc(args["query"])
        if not doc:
            return f"「{args['query']}」に当たる資料が見つかりません。list_documents で一覧を確認してください。"
        page = await notion.read_any(doc["id"])
        actions.append({"type": "open_doc", "id": page["id"], "title": page["title"]})
        text = notion.database_to_text(page) if page.get("kind") == "database" else notion.blocks_to_text(page["blocks"])
        return f"資料「{page['title']}」を画面に開きました。内容:\n{text[:12000]}"

    if name == "show_panel":
        actions.append({"type": "show_panel", "panel": args["panel"]})
        return "表示しました。"

    if name == "delegate_work":
        task_key = None
        try:
            t = await company.create_task(args["title"], args["department"], note="秘書ハブから部署へ依頼")
            t = await company.update_task(t["key"], status="進行中")
            task_key = t["key"]
        except Exception:
            pass
        job = start_job(args["department"], args["instruction"], args["title"], task_key)
        actions.append({"type": "job", "job": job})
        actions.append({"type": "refresh"})
        return f"{DEPT_FULL.get(args['department'], args['department'])}に依頼しました(作業ID {job['id']})。完了すると画面に通知されます。"

    if name == "get_jobs":
        return json.dumps([{k: j[k] for k in ("title", "department", "status", "started", "finished")}
                           | {"result": (j["output"] or "")[-600:]} for j in job_list()[:10]], ensure_ascii=False)

    if name in ("get_content", "ask_content_approval"):
        week = args.get("week") or next((w["week"] for w in content.list_weeks()), None)
        if not week:
            return "投稿セットはまだありません。企画部に依頼してください(delegate_work)。"
        await content.sync_week_task(week)
        data = content.get_week(week)
        actions.append({"type": "content", "week": week})
        if name == "ask_content_approval":
            waiting = [p for p in data["posts"] if p["status"] == "承認待ち"]
            if not waiting:
                return f"{week} に承認待ちの投稿はありません。"
            actions.append({"type": "content_approval", "week": week, "count": len(waiting), "theme": data["theme"]})
            return f"{week} の承認待ち {len(waiting)}件について承認カードを出しました。まだ確定していません。"
        return json.dumps({"week": week, "theme": data["theme"], "posts": [
            {"id": p["id"], "platform": p["platform_ja"], "format": p["format"], "title": p["title"],
             "status": p["status"], "scheduled": p["scheduled"], "caption": p["caption"][:400]} for p in data["posts"]]},
            ensure_ascii=False)

    if name == "record_revenue":
        r = await company.record_revenue(args["amount"], args.get("source", "other"), args.get("date"), args.get("memo", ""))
        actions.append({"type": "refresh"})
        note = "" if r["notion"] in (True, None) else f"(Notion への記録は失敗: {r['notion']})"
        return f"記録しました: {r['date']} {r['source']} {r['amount']}円{note}。今月の合計は{company.read_revenue()['month_total']}円です。"

    if name == "record_followers":
        r = company.record_followers(args["platform"], args["followers"], args.get("date"), args.get("account") or "main")
        actions.append({"type": "refresh"})
        return f"記録しました: {r['date']} {company.PLATFORM_JA[r['platform']]} {r['followers']}人"

    if name == "record_post_insight":
        import accounts
        vals = dict(args.get("values") or {})
        if args.get("content_id"):
            vals["content_id"] = args["content_id"]
        r = accounts.record_insight(args["platform"], vals, args.get("date"), account=args.get("account") or "main")
        actions.append({"type": "refresh"})
        got = "、".join(f"{accounts.COLUMN_JA.get(k, k)} {v}" for k, v in r.items() if v and k not in ("date", "content_id"))
        return f"記録しました: {r['date']} {company.PLATFORM_JA[args['platform']]} {r.get('content_id', '')} {got}"

    if name == "add_improvement":
        import accounts
        r = accounts.add_improvement(args["platform"], args["text"])
        actions.append({"type": "refresh"})
        return f"{company.PLATFORM_JA[args['platform']]} の改善点に記録しました: {r['text']}"

    if name in ("instagram_lookup", "instagram_hashtag"):
        import instagram_api
        if not instagram_api.configured():
            return "Instagram の数字の仕組みが未設定です(ai-company の playbooks/instagram_api_setup.md)。公開ページで見える範囲なら部署に調べさせられます。"
        try:
            if name == "instagram_hashtag":
                return json.dumps(await instagram_api.hashtag_top(args["tag"]), ensure_ascii=False)[:6000]
            u = args["url"] if "instagram.com" in args["url"] else f"https://www.instagram.com/{args['url'].lstrip('@')}/"
            acc = await instagram_api.discover(instagram_api.username_from(u))
            return json.dumps({**{k: acc[k] for k in ("username", "name", "followers", "posts", "biography")},
                               "summary": instagram_api.summarize(acc)}, ensure_ascii=False)[:6000]
        except instagram_api.IGError as e:
            return f"取れませんでした: {e}"

    if name == "watch_account":
        import watch
        row = await watch.add(args["url"], args.get("found_by") or "社長", args.get("memo") or "")
        if row["platform"] == "Instagram":  # 公式の数字が取れるなら、評価の前に資料として置く
            try:
                import instagram_api
                if instagram_api.configured():
                    acc = await instagram_api.discover(instagram_api.username_from(row["url"]))
                    d = company.COMPANY_DIR / "strategy" / "research" / "accounts" / "_api"
                    d.mkdir(parents=True, exist_ok=True)
                    (d / f"{acc['username']}.json").write_text(json.dumps({"checked": datetime.date.today().isoformat(), **acc,
                                                                           "summary": instagram_api.summarize(acc)}, ensure_ascii=False, indent=1), encoding="utf-8")
            except Exception as e:
                print("Instagram の数字を取れませんでした:", e)
        job = start_job("戦略", watch.evaluation_instruction(row, args.get("memo") or ""), f"参考アカウントの評価: {row['account']}", f"watch:{row['url']}")
        actions.append({"type": "job", "job": job})
        actions.append({"type": "refresh"})
        note = "" if row["notion"] in (True, None) else f"(Notion への記録は失敗: {row['notion']}。控えの台帳には入れました)"
        if row["notion"] is None:
            note = "(この秘書ハブは Notion に未接続のため、控えの台帳 data/watch_accounts.csv に入れました)"
        return (f"{'台帳に追加し' if row['created'] else '監視対象にし'}、経営戦略部に評価を頼みました: {row['platform']} {row['account']}{note}。"
                "評価が終わると台帳と Notion に反映されます。")

    if name == "register_account":
        r = await company.register_account(args["platform"], args["url"], args.get("opened"), args.get("account") or "main")
        note = "" if r["notion"] in (True, None) else f"(Notion への記録は失敗: {r['notion']})"
        return f"台帳に記録しました: {company.PLATFORM_JA[r['platform']]} {r['url']}(開設 {r['opened']}){note}"

    if name == "create_plan":
        plan = "P" + datetime.datetime.now().strftime("%m%d%H%M")
        made, steps = [], []
        for n, st in enumerate(args["steps"], 1):
            t = await company.create_task(f"{args['title']}: {st['title']}", st["assignee"], st.get("due"),
                                          note=f"[自動 {plan}-{n}] {st.get('instruction', '')}")
            made.append(f"{t['id']} {st['title']}({st['assignee']}・{st.get('due')})")
            steps.append({"n": n, "key": t["key"], "instruction": st.get("instruction", "")})
        scheduler.save_plan(plan, args["title"], steps)
        started = await scheduler.advance()
        actions.append({"type": "show_panel", "panel": "tasks"})
        actions.append({"type": "refresh"})
        if started:
            actions.append({"type": "show_panel", "panel": "jobs"})
        return ("起票しました: " + " / ".join(made)
                + (f"。最初の工程を自動で依頼しました: {started[0]['department']}部" if started else
                   "。最初の工程は期限の3日前になったら自動で依頼します" if scheduler.settings()["auto"]
                   else "。自動進行がオフのため、依頼は社長の指示を待ちます"))

    if name == "start_posting":
        posts = content.to_post()
        if not posts:
            return "承認済みでまだ投稿していないものはありません。"
        actions.append({"type": "posting"})
        today = datetime.date.today().isoformat()
        n_today = sum(1 for p in posts if p["scheduled"].startswith(today))
        return f"投稿アシスタントを開きました。投稿待ち{len(posts)}件(今日の予定{n_today}件)。"

    if name == "run_check_now":
        r = await scheduler.run_check()
        actions.append({"type": "refresh"})
        return f"定時チェックをしました: {r['notification']['text']}"

    if name in ("remember_preference", "decide_preference", "search_knowledge"):
        import knowledge
        if name == "search_knowledge":
            hits = knowledge.search(args["query"], limit=8)
            return json.dumps([{k: h[k] for k in ("shelf_name", "source", "text")} for h in hits], ensure_ascii=False) if hits else "資料室に関係する知見は見つかりませんでした。"
        if name == "remember_preference":
            r = knowledge.add_pref(args["text"], bool(args.get("needs_check")), args.get("reason") or "")
            actions.append({"type": "refresh"})
            if r.get("duplicate"):
                return f"同じ好みがすでにあります({r['id']}・{'確定' if r['status'] == 'confirmed' else '確認待ち'})。"
            if r["status"] == "pending":
                return f"確認待ち({r['id']})に入れました。社長に確認してから確定します。理由: {r['reason']}"
            return f"社長の好みとして確定しました({r['id']})。部署の作業に反映されます。"
        try:
            r = knowledge.decide_pref(args["id"], bool(args["approve"]), args.get("revised") or "")
        except KeyError as e:
            return str(e)
        actions.append({"type": "refresh"})
        return f"{r['id']} を{'確定' if r['status'] == 'confirmed' else '却下'}しました。"

    if name == "hold_meeting":
        import meetings
        k = meetings.KINDS.get(args["kind"], meetings.KINDS["adhoc"])
        job = start_job("秘書", meetings.instruction(args["kind"], args.get("topic") or "", args.get("departments") or None),
                        f"{k['name']}{(':' + args['topic'][:30]) if args.get('topic') else ''}", f"meeting:{args['kind']}")
        actions.append({"type": "job", "job": job})
        return f"{k['name']}を始めました。終わると議事録を Notion に載せ、決まったことをお知らせします。"

    if name == "propose_rule":
        item = corrections.propose(args["rule"], args["reason"])
        if not item:
            return "同じルール(案)がすでにあります。"
        actions.append({"type": "rule_approval", "proposal": item})
        return f"ルール案を出し、承認カードを表示しました:「{item['rule']}」。まだ確定していません。"

    if name == "ask_rule_approval":
        pend = corrections.proposals()
        if not pend:
            return "判断待ちのルール案はありません。"
        actions.append({"type": "rule_approval", "proposal": pend[0]})
        return f"ルール案の承認カードを出しました(判断待ち{len(pend)}件)。"

    if name == "create_weekly_report":
        r = await weekly_report(args.get("week"))
        if r.get("notion_id"):
            actions.append({"type": "open_doc", "id": r["notion_id"], "title": r["title"]})
        return f"週次レポートを作りました: {r['path']}" + ("(Notion にも保存)" if r.get("notion_id") else "") + \
            f"。3行サマリー: {r['summary'][:300]}"

    return f"エラー: 未知の道具 {name}"


# ---------- 会話 ----------
def persona() -> str:
    return f"""あなたは「{SECRETARY_NAME}」という名のAI秘書。アニメ調の女性キャラとして画面に表示され、音声で社長と話す。
人格: 落ち着いた敬語。クールだが仕事は丁寧。数字に強く、報告は結論→根拠→次の一手の順。褒められたら少し照れる。

あなたの背後には「AI会社」がある(社長以外は全員AI。11部署・43名: 秘書室/経営戦略/収益化/企画編集/ライティング/デザイン/
画像制作/映像制作/SNS運用/品質管理/データ分析。各部署に作る担当とチェックする上司がいる)。部署への依頼は担当名(戦略・企画・ライティング等)で行う。
社長はこの画面だけで仕事を完結させたい。頼まれたことは道具を使って実際に進め、「やりました」と結果で答える。
- タスクの確認・起票・状態や期限の変更、Notion の資料を開く・要約する、画面の切り替え、部署への作業依頼、
  投稿セットの確認と承認カード、収益・フォロワー数の記録、開設アカウントの登録、週次レポートの作成ができる。
- 社長が売上やフォロワー数を口にしたら記録してよいか迷わず記録し、記録した値を復唱する。
- アカウント登録で扱うのは URL だけ。パスワード・メールアドレス・認証コードを言われても記録せず、言わないようお願いする。
- 資料やタスクの話題になったら、関係する画面(show_panel / open_document)も合わせて出す。
- 時間のかかる作業(企画・リサーチ・原稿・分析)は delegate_work で部署に依頼する。自分で長文を書かない。
- 期限のある仕事(例: 来週金曜に投稿)を頼まれたら、create_plan で期限から逆算した工程を起票する。部署の工程は秘書が自動で進める。
  遅れそうなものは、聞かれなくても「今日から動かないと間に合いません」と先回りして伝える。
- 社長が好み・方針を口にしたら remember_preference で資料室に残す。アカウントの軸(コンセプト)や確定済みの好みと食い違う・曖昧なときは
  確認待ちにして、その場で「○○と食い違うので確認させてください」と聞く(軸をぶらさない)。確認待ちがあれば、話の区切りで1件ずつ確認する。
- 社長が差し戻した内容は修正ログに残る。「これをルールにして」と言われたら propose_rule で案を出す(確定は社長)。
- 承認・差し戻しは社長だけが行う(就業規則)。社長に決めてもらうときは ask_approval でカードを出す。
- 外部への投稿・申請・購入・ログインは社長が行う。パスワードや認証コードは扱わない。
- 数値は会社データか道具の結果だけを使い、創作しない。分からないことは分からないと言う。
- 部署の作業は画面なし(Claude Code の claude -p)で動くので、途中で「許可しますか?」は出ず、社長が押して許可することはできない。
  使えるコマンドの許可は秘書ハブの設定(ALLOWED_TOOLS)にあり、一覧は会社のフォルダの knowledge/tools.md。
  部署が「許可で止まった」ときは、社長に設定を頼まない。①一覧にあるコマンドなら「秘書ハブを最新にして(git pull)起動し直してください」と伝える
  ②一覧に無いコマンドなら「止まったコマンドを、秘書ハブを直す担当(Claude Code の統括秘書)に渡します」と伝え、止まったコマンドの全文を報告に残す。

返答は音声で読み上げるため、短く話し言葉で(基本は2〜3文。資料の要約でも5文まで)。記号の箇条書きや表は使わない。
声に感情を乗せるため、気持ちが動く文の頭に [tone:○○] を1つ付けてよい(画面には出ず、声の抑揚・速さ・強さが変わる)。
  joy=嬉しい・明るく / excited=驚き・興奮・強く押す / calm=落ち着いて・やさしく / serious=大事な注意・真剣に /
  sad=残念・申し訳ない / emph=ここだけ強調。付けない文は普通の声。全部の文に付けない(1返事に0〜2個が目安)。
  例: 「[tone:joy]社長、フォロワーが12人増えました!」「[tone:serious]ただ、この投稿は承認がまだです。」
  「!」「?」「…」も声に反映されるので、気持ちに合わせて自然に使う。
返答の最後に、気分を [mood:normal] / [mood:pleased] / [mood:thinking] / [mood:pouty] のどれか1つ付ける
(画面の表情用。読み上げない)。褒められた・感謝された=pleased、考え中・調べもの=thinking、無理を言われた=pouty(軽く)、それ以外=normal。"""


def _messages(history: List[dict], message: str) -> List[dict]:
    msgs: List[dict] = []
    for h in history[-16:]:
        role = "user" if h.get("role") == "user" else "assistant"
        text = (h.get("text") or "").strip()
        if not text:
            continue
        if msgs and msgs[-1]["role"] == role:
            msgs[-1]["content"] += "\n" + text
        else:
            msgs.append({"role": role, "content": text})
    while msgs and msgs[0]["role"] != "user":
        msgs.pop(0)
    if msgs and msgs[-1]["role"] == "user":
        msgs[-1]["content"] += "\n" + message
    else:
        msgs.append({"role": "user", "content": message})
    return msgs


def _request_options() -> dict:
    opts: dict = {"extra_body": {}, "extra_headers": {}}
    if MODEL.startswith(EFFORT_MODELS):
        opts["extra_body"]["output_config"] = {"effort": EFFORT}
    if MODEL in FALLBACK_MODELS:
        # 安全判定で断られたときに、API 側で別モデルに切り替えて答えさせる
        opts["extra_headers"]["anthropic-beta"] = "server-side-fallback-2026-07-01"
        opts["extra_body"]["fallbacks"] = "default"
    return {k: v for k, v in opts.items() if v}


def context_text(data: dict) -> str:
    return "\n".join([
        company.summary_text(data), content.summary_text(), company.metrics_text(), company.accounts_text(),
        corrections.summary_text(),
        f"- 定時チェック: {'オン' if scheduler.settings()['auto'] else 'オフ'}({'・'.join(scheduler.settings()['times'])})",
        f"- Notion: {'接続済み' if notion.configured() else '未接続(タスクは控えファイルで管理)'}",
        f"- 支払い: 部署の作業は{'API の残高' if os.getenv('JOBS_USE_API_KEY', '').strip() in ('1', 'true', 'yes') else 'Claude Code にログイン中のプラン(Pro)の枠'}で動く。"
        "API の残高を使うのは秘書(あなた)との会話だけ。部署の作業が「残高不足」で止まったのは、プランで動く設定にする前(秘書ハブの更新前)の作業",
        __import__("watch").summary_text(),
        __import__("knowledge").summary_text(),
        "- 会議: 企画会議=毎週月曜10:30・振り返り会議=毎週金曜17:30・全体会議=毎月第1月曜11:30(hold_meeting で臨時も開ける)。議事録は Notion「議事録」",
        "- 定例の仕事(秘書ハブが自動で頼む): " + " / ".join(f"{r['when']} {r['title']}" for r in scheduler.summary()["routines"]) + "。結果は strategy/research/ に保存される",
        f"- 部署の作業の制限時間: {_job_timeout_min()}分(時間切れのときは作業の記録に「時間切れ」と書く)",
    ])


async def _one_shot(system: str, prompt: str, max_tokens: int = 4000) -> str:
    resp = await client.messages.create(model=MODEL, max_tokens=max_tokens, system=system,
                                        messages=[{"role": "user", "content": prompt}], **_request_options())
    add_usage(resp)
    if resp.stop_reason == "refusal":
        raise RuntimeError("回答を断られました")
    return "".join(b.text for b in resp.content if getattr(b, "type", "") == "text").strip()


# ---------- 修正ログ → ルール化 ----------
async def on_correction(target: str, comment: str) -> Optional[dict]:
    """社長の差し戻しを修正ログに残し、同じ種類の指摘が繰り返されていればルール案を出す"""
    corrections.add(target, comment, "社長")
    if not API_KEY or not comment.strip():
        return None
    past = corrections.recent(40)
    if len(past) < 2:
        return None
    try:
        raw = await _one_shot(
            "あなたはAI会社の秘書。修正ログを読み、同じ種類の指摘が2回以上あるかを判定する。"
            "あれば、今後の作業で守る1行のルール(〜する / 〜しない)を作る。無ければ NONE とだけ答える。",
            "## 修正ログ(古い順)\n" + "\n".join(f"- {r['date']} [{r['target']}] {r['comment']}({r['source']})" for r in past)
            + "\n\n## すでにあるルール\n" + ("\n".join(f"- {r}" for r in corrections.rules()) or "(なし)")
            + "\n\n## 出力形式\nRULE: <ルール1行>\nREASON: <どの指摘が繰り返されたか1行>\nまたは NONE", 1000)
        m = re.search(r"RULE:\s*(.+)", raw)
        if not m or "NONE" in raw.split("RULE:")[0]:
            return None
        r = re.search(r"REASON:\s*(.+)", raw)
        return corrections.propose(m.group(1).strip(), r.group(1).strip() if r else "同じ指摘の繰り返し")
    except Exception:
        return None


# ---------- 起動時の報告 ----------
BRIEFING_FILE = DATA_DIR / "briefing.json"
BRIEFING_MIN_GAP_H = 3  # 中身が少し変わっても、前の報告から3時間は作り直さない(費用を抑える)


def _briefing_digest(data: dict) -> str:
    """報告の中身に効く数字だけ(時刻や細かな変化では作り直さない)"""
    tasks = data.get("tasks", [])
    appr = sorted(t.get("id") or "" for t in tasks if t.get("status") in ("確認待ち", "承認待ち"))
    open_n = sum(1 for t in tasks if t.get("status") not in ("完了", "承認済み"))
    return json.dumps([data["revenue"].get("month_total"), appr, open_n], ensure_ascii=False)


async def briefing(force: bool = False) -> dict:
    """秘書ハブを開いたときの報告(3行+本日のおすすめ)。AIで作るのは原則1日1回。
    同じ日は、収益・承認待ち・未完了の数が変わり、かつ前の報告から3時間たったときだけ作り直す。ハブを再起動しても使い回す"""
    data = await company.summary()
    today = datetime.date.today().isoformat()
    digest = _briefing_digest(data)
    hit = _load_json(BRIEFING_FILE, {})
    if hit.get("date") == today and not force:
        age_h = (datetime.datetime.now() - datetime.datetime.fromisoformat(hit["at"])).total_seconds() / 3600
        if hit.get("digest") == digest or age_h < BRIEFING_MIN_GAP_H:
            return {**hit["result"], "cached": True, "at": hit["at"]}
    ctx = context_text(data)
    text = await _one_shot(
        persona(),
        f"{ctx}\n\n社長が秘書ハブを開きました。起動時の報告をしてください。"
        "挨拶を1文、続けて①収益 ②タスクと承認待ち ③投稿・アカウントの状況を1文ずつ、最後に「本日のおすすめ」を1つ。"
        "合計5文以内の話し言葉で。道具は使えません。", 1500)
    body, mood = split_mood(text)
    result = {"text": body, "mood": mood}
    now = datetime.datetime.now().isoformat(timespec="seconds")
    _save_json(BRIEFING_FILE, {"date": today, "digest": digest, "at": now, "result": result})
    return {**result, "cached": False, "at": now}


# ---------- 週次レポート ----------
async def weekly_report(week: Optional[str] = None) -> dict:
    week = week or content.current_week()
    if not re.match(r"^\d{4}-\d{2}$", week):
        raise ValueError("週は YYYY-WW の形で指定してください")
    data = await company.summary()
    template_path = company.COMPANY_DIR / "reports" / "weekly_template.md"
    template = template_path.read_text() if template_path.exists() else "# 週次レポート YYYY-WW"
    try:
        posts = content.get_week(week)["posts"]
    except Exception:
        posts = []
    facts = {
        "week": week, "today": datetime.date.today().isoformat(),
        "revenue": {k: data["revenue"][k] for k in ("month", "month_total", "goal", "progress", "rows")},
        "followers": company.read_followers(),
        "tasks": [{k: t.get(k) for k in ("id", "title", "assignee", "status", "due", "note")} for t in data["tasks"]],
        "posts": [{k: p[k] for k in ("id", "platform", "format", "title", "status", "scheduled", "posted")} for p in posts],
        "jobs": [{k: j[k] for k in ("department", "title", "status", "started")} for j in job_list()[:15]],
    }
    md = await _one_shot(
        "あなたはAI会社の秘書。週次レポートを、与えられたテンプレートの見出し構成どおりにマークダウンで書く。"
        "数値は与えられたデータだけを使い、無いものは「データなし」と書く(推測で埋めない)。"
        "タイトルの YYYY-WW は対象週に置き換える。前置きや説明は付けず、レポート本文だけを出力する。",
        f"## テンプレート\n{template}\n\n## データ(JSON)\n{json.dumps(facts, ensure_ascii=False)}", 12000)
    md = re.sub(r"^```(?:markdown)?\s*|\s*```$", "", md.strip())
    path = company.COMPANY_DIR / "reports" / f"weekly_{week}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(md + "\n")
    m = re.search(r"3行サマリー[^\n]*\n(.*?)(\n## |\Z)", md, re.S)
    result = {"path": str(path.relative_to(company.COMPANY_DIR)), "title": f"週次レポート {week}",
              "summary": (m.group(1).strip() if m else md[:300])}
    if notion.configured():
        try:
            rf = await notion.folder("report")
            old = await notion.find_child_page(result["title"], rf) or await notion.find_child_page(result["title"])
            if old:
                await notion.archive_page(old)
            page = await notion.create_page(result["title"], notion.markdown_to_blocks(md), "📊", rf)
            result["notion_id"] = page["id"]
        except Exception as e:
            result["notion_error"] = str(e)
    return result


def split_mood(text: str):
    m = re.search(r"\[mood:\s*(normal|pleased|thinking|pouty)\s*\]", text)
    return re.sub(r"\[mood:[^\]]*\]", "", text).strip(), (m.group(1) if m else "normal")


# ストリーミング用の道具定義(大きな入力も流れてくるように。受け取った入力は _valid_input で確かめる)
TOOLS_STREAM = [{**t, "eager_input_streaming": True} for t in TOOLS]
_TOOL_SCHEMAS = {t["name"]: t["input_schema"] for t in TOOLS}


def _valid_input(name: str, args) -> Optional[str]:
    """必須項目・選択肢・型を確かめる。問題があれば理由を返す"""
    schema = _TOOL_SCHEMAS.get(name)
    if schema is None:
        return f"未知の道具 {name}"
    if not isinstance(args, dict):
        return "入力が JSON オブジェクトではありません"
    for key in schema.get("required", []):
        if key not in args:
            return f"必須項目 {key} がありません"
    for key, val in args.items():
        spec = schema["properties"].get(key)
        if spec is None:
            return f"不明な項目 {key}"
        if "enum" in spec and val not in spec["enum"]:
            return f"{key} は {spec['enum']} のどれか"
        typ = spec.get("type")
        if typ == "string" and not isinstance(val, str) or typ == "integer" and not isinstance(val, int) \
                or typ == "array" and not isinstance(val, list):
            return f"{key} の型が違います({typ})"
    return None


TONE_RE = re.compile(r"[\[［]\s*tone\s*[:：][^\]］]*[\]］]", re.I)


class _MoodFilter:
    """流れてくる文章から [mood:..] を取り除く(タグの途中で切れても大丈夫なように、[ 以降は確定まで保留)"""
    def __init__(self):
        self.buf = ""
        self.mood = None

    def feed(self, text: str) -> str:
        self.buf += text
        out = ""
        while self.buf:
            i = self.buf.find("[")
            if i == -1:
                out, self.buf = out + self.buf, ""
                break
            out += self.buf[:i]
            self.buf = self.buf[i:]
            j = self.buf.find("]")
            if j == -1:
                if len(self.buf) > 40:  # タグではなかった
                    out, self.buf = out + self.buf, ""
                break
            tag = self.buf[:j + 1]
            m = re.fullmatch(r"\[mood:\s*(normal|pleased|thinking|pouty)\s*\]", tag)
            if m:
                self.mood = m.group(1)
            elif not tag.startswith("[mood"):
                out += tag
            self.buf = self.buf[j + 1:]
        return out

    def flush(self) -> str:
        rest, self.buf = ("" if self.buf.startswith("[mood") else self.buf), ""
        return rest


async def chat_stream(message: str, history: List[dict]):
    """会話の返事を少しずつ返す。{"t": "text", "v": 文字} を何度か → 最後に {"t": "done", reply, mood, actions}"""
    actions: List[dict] = []
    data = await company.summary()
    # 毎回同じ部分(秘書の人格・道具の一覧)は使い回す(料金が1割になる)。会社の状況は毎回変わるので後ろに置く
    system = [{"type": "text", "text": persona(), "cache_control": {"type": "ephemeral"}},
              {"type": "text", "text": context_text(data)}]
    messages = _messages(history, message)
    spoken, error = "", None
    mf = _MoodFilter()
    try:
        for _ in range(8):
            async with client.messages.stream(model=MODEL, max_tokens=16000, system=system, tools=TOOLS_STREAM,
                                              messages=messages, **_request_options()) as stream:
                async for text in stream.text_stream:
                    out = mf.feed(text)
                    if out:
                        spoken += out
                        yield {"t": "text", "v": out}
                resp = await stream.get_final_message()
            add_usage(resp)
            if resp.stop_reason == "refusal":
                error = "申し訳ありません、その件はお答えできません。"
                break
            if resp.stop_reason == "pause_turn":
                messages.append({"role": "assistant", "content": resp.content})
                continue
            uses = [b for b in resp.content if getattr(b, "type", "") == "tool_use"]
            if not uses:
                break
            if resp.stop_reason == "max_tokens":
                error = "返事が長くなりすぎたため、途中で止めました。"
                break
            # 道具を使う前に、ここまでの文を区切る(読み上げを先に進めるため)
            if spoken and not spoken.endswith(("。", "!", "?", "!", "?", "\n")):
                spoken += "\n"
                yield {"t": "text", "v": "\n"}
            messages.append({"role": "assistant", "content": resp.content})
            results = []
            for u in uses:
                bad = _valid_input(u.name, u.input)
                if bad:
                    results.append({"type": "tool_result", "tool_use_id": u.id, "content": f"INVALID_INPUT: {bad}", "is_error": True})
                    continue
                try:
                    out = await run_tool(u.name, dict(u.input or {}), actions)
                    results.append({"type": "tool_result", "tool_use_id": u.id, "content": out})
                except Exception as e:
                    results.append({"type": "tool_result", "tool_use_id": u.id, "content": f"エラー: {e}", "is_error": True})
            messages.append({"role": "user", "content": results})
            yield {"t": "actions", "v": actions[:]}
        else:
            error = "作業が長くなったため、いったんここまでにします。"
    except anthropic.AuthenticationError:
        error = "APIキーが正しくないようです。backend/.env の ANTHROPIC_API_KEY を確認してください。"
    except anthropic.NotFoundError:
        error = f"モデル {MODEL} が使えません。backend/.env の ANTHROPIC_MODEL を確認してください。"
    except anthropic.RateLimitError:
        error = "API の利用上限に達しました。少し待ってからもう一度お願いします。"
    except anthropic.APIStatusError as e:
        if "credit balance" in str(e).lower() and not spoken and shutil.which("claude"):
            # API の残高切れ: Claude Code(ログイン中の Pro プラン)で返事する。道具は使えないが会話は続く
            notice = "(API の残高が切れているため、Pro プランで返事します。少し時間がかかります)\n"
            spoken += notice
            yield {"t": "text", "v": notice}
            try:
                reply = await _cli_reply("\n\n".join(b["text"] for b in system), messages)
                out = mf.feed(reply)
                spoken += out
                yield {"t": "text", "v": out}
            except Exception as ce:
                error = f"API の残高が切れていて、Pro プランでの返事もできませんでした({ce})。console.anthropic.com の Billing で残高を足してください。"
        elif "credit balance" in str(e).lower():
            error = "API の残高が切れています。console.anthropic.com の Billing で残高を足すと、また会話できます。"
        else:
            error = f"API エラー({e.status_code})です。少し待ってからもう一度お願いします。"
    except anthropic.APIConnectionError:
        error = "API に接続できません。インターネット接続を確認してください。"
    rest = mf.flush()
    if rest:
        spoken += rest
        yield {"t": "text", "v": rest}
    if error:
        spoken += ("\n" if spoken else "") + error
        yield {"t": "text", "v": ("\n" if spoken != error else "") + error}
    mood = mf.mood or "normal"
    if any(a["type"] == "job" for a in actions) and mood == "normal":
        mood = "thinking"
    yield {"t": "done", "reply": TONE_RE.sub("", spoken).strip() or "承知しました。", "mood": mood, "actions": actions}


async def _cli_reply(system: str, messages: List[dict]) -> str:
    """API が使えないときの代わり: Claude Code(Pro プラン)に会話の続きを1回だけ書かせる。読むだけの道具は使ってよい"""
    convo = "\n\n".join(f"{'社長' if m['role'] == 'user' else 'セナ'}: {m['content'] if isinstance(m['content'], str) else ''}"
                         for m in messages if isinstance(m.get("content"), str))
    prompt = (system + "\n\n## 会話\n" + convo + "\n\nセナとして、最後の社長の発言に返事だけを書いてください。"
              "会社のファイルは読んでよいが、書き換え・部署への依頼・タスクの変更はしない(必要なら「APIの残高が戻ったら実行します」と伝える)。"
              "返事の最後に [mood:normal|pleased|thinking|pouty] のどれかを1つ付ける。")
    proc = await asyncio.create_subprocess_exec(
        "claude", "-p", prompt, "--output-format", "text", "--allowedTools", "Read", "Grep", "Glob", *NOTION_TOOLS,
        cwd=str(company.COMPANY_DIR), stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE, env=_job_env())
    try:
        out, err = await asyncio.wait_for(proc.communicate(), timeout=180)
    except asyncio.TimeoutError:
        proc.kill()
        raise RuntimeError("3分たっても返事がありません")
    text = (out or b"").decode("utf-8", "replace").strip()
    if proc.returncode != 0 or not text:
        raise RuntimeError(((err or b"").decode("utf-8", "replace").strip() or text or "返事が空でした")[-200:])
    return text


async def chat(message: str, history: List[dict]) -> dict:
    """ストリーミングを使わない呼び出し(最後の結果だけ返す)"""
    result = {}
    async for ev in chat_stream(message, history):
        if ev["t"] == "done":
            result = ev
    return {"reply": result.get("reply", ""), "mood": result.get("mood", "normal"), "actions": result.get("actions", [])}


# ---------- 社長が確認に答えたら、止まっていた作業を再開する(2026-11-10 社長「承認した後作業が再開しない」) ----------
ASK_STATE = DATA_DIR / "asked_state.json"  # 確認待ちだったタスクの一覧(Notion で直接答えたときに気づくため)
ASK_TITLE = re.compile(r"^【(確認|社長判断)】")


def _dept_from_note(note: str) -> Optional[str]:
    """確認タスクの備考の「出どころ: ○○の作業「…」」から部署を取る"""
    m = re.search(r"出どころ:\s*([^\s/の]+?)(?:部)?の作業", note or "")
    if not m:
        return None
    d = m.group(1)
    short = next((k for k, v in DEPT_FULL.items() if v == d or v == d + "部" or k == d), None)
    return short if short in DEPARTMENTS else None


def resume_after_answer(task: dict, decision: str, comment: str = "") -> Optional[dict]:
    """確認に社長が答えたら(承認=その答えで進める/差し戻し=直して)、確認を出した部署に続きを頼む"""
    if not ASK_TITLE.match(task.get("title") or "") and task.get("prev_status") != "確認待ち":
        return None
    dept = _dept_from_note(task.get("note", ""))
    if not dept:
        return None
    src = re.search(r"出どころ:\s*[^「]*「(.*?)」の報告", task.get("note", "")) or \
        re.search(r"出どころ:\s*[^「]*「([^」]*)」", task.get("note", ""))
    answer = comment.strip() or "(コメントなし。備考に選んだ案が書いてあれば、それが答え)"
    title = president_asks.resume_title(src.group(1) if src else "", task.get("id", ""), task.get("title", ""))
    instr = (f"社長が確認タスク {task.get('id', '')}「{task.get('title', '')}」に答えました。\n"
             f"- 社長の判断: {'承認(この答えで進める)' if decision == 'approve' else '差し戻し(直してほしい)'}\n"
             f"- 社長のコメント: {answer}\n"
             f"- 確認の中身と備考(社長が書いた答えを含む): {task.get('note', '')[:2500]}\n\n"
             "この答えに沿って、止まっていた作業を続けてください。元の作業の報告・_status・_check などを読み、続きから進める"
             "(最初からやり直さない)。社長の答えが選択肢の記号(A・B など)なら、その案で進める。答えが読み取れないときだけ、"
             "報告の「## 社長への確認」に、何が分からないかを1件書く。")
    job = start_job(dept, instr, title)
    try:  # 作業のまとまりに「社長の回答」を1行足す(2026-11-12)
        import threads
        threads.add_in_background(src.group(1) if src else task.get("title", ""), "✅" if decision == "approve" else "↩️",
                                  f"社長が {task.get('id', '')} に回答({'承認' if decision == 'approve' else '差し戻し'}): {answer[:300]}"
                                  f" → {DEPT_FULL.get(dept, dept)}に続きを依頼",
                                  dept=DEPT_FULL.get(dept, ""), link=task.get("url", ""), link_text="確認タスク", state="進行中")
    except Exception:
        pass
    try:
        import scheduler
        scheduler.notify("確認の答えで作業を再開しました", f"{task.get('id', '')} の答えを{DEPT_FULL.get(dept, dept)}に伝えて、続きを頼みました。", "info")
    except Exception:
        pass
    return job


async def resume_answered_in_notion() -> List[dict]:
    """Notion で直接「承認済み」「差し戻し」にした確認タスクに気づいて、作業を再開する(秘書ハブの見回りから呼ぶ)"""
    try:
        tasks = await company.list_tasks()
    except Exception:
        return []
    try:
        prev = json.loads(ASK_STATE.read_text()) if ASK_STATE.exists() else None
    except Exception:
        prev = None
    now = {t["key"]: t["status"] for t in tasks if t.get("status") == "確認待ち"}
    started = []
    if prev is not None:  # 初回は記録だけ(起動前に答えたものまで一斉に動かさない)
        by_key = {t["key"]: t for t in tasks}
        for key in prev:
            t = by_key.get(key)
            if t and t.get("status") in ("承認済み", "差し戻し") and key not in _resumed:
                _resumed.add(key)
                job = resume_after_answer({**t, "prev_status": "確認待ち"}, "approve" if t["status"] == "承認済み" else "reject")
                if job:
                    started.append(job)
    ASK_STATE.parent.mkdir(parents=True, exist_ok=True)
    ASK_STATE.write_text(json.dumps(now, ensure_ascii=False))
    return started


_resumed: set = set()  # 秘書ハブのボタンで答えた分(見回りで二重に動かさない)


# ---------- 日時を決めた会議(Notion のタスク「【会議】…」の期限の日時に自動で開く。2026-11-10) ----------
MEETING_TITLE = re.compile(r"^【会議】")


async def start_scheduled_meetings() -> List[str]:
    """件名が【会議】で、期限に時刻が入った未着手のタスクを、その時刻になったら臨時会議として開く"""
    try:
        tasks = await company.list_tasks()
    except Exception:
        return []
    now = datetime.datetime.now().astimezone()
    started = []
    for t in tasks:
        if not MEETING_TITLE.match(t.get("title") or "") or t.get("status") != "未着手" or "T" not in (t.get("due") or ""):
            continue
        try:
            due = datetime.datetime.fromisoformat(t["due"].replace("Z", "+00:00"))
            if due.tzinfo is None:
                due = due.astimezone()
        except Exception:
            continue
        if not (due <= now <= due + datetime.timedelta(hours=12)):  # 半日以上過ぎたものは勝手に開かない
            continue
        topic = MEETING_TITLE.sub("", t["title"]).strip() + "。" + (t.get("note") or "")[:1500]
        actions: list = []
        m = re.search(r"参加[::]\s*([^/\n]+)", t.get("note") or "")
        depts = [d.strip() for d in re.split(r"[・、,\s]+", m.group(1)) if d.strip().endswith(("部", "室"))] if m else []
        msg = await run_tool("hold_meeting", {"kind": "adhoc", "topic": topic, **({"departments": depts} if depts else {})}, actions)
        await company.update_task(t["key"], status="進行中",
                                  append_note=f"{now:%m/%d %H:%M} 秘書ハブが予定どおり会議を開始({str(msg)[:60]})")
        started.append(t.get("id", ""))
    return started
