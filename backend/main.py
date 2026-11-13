"""
AI秘書ハブ — 中継サーバー
- 顔(React の画面)と、頭脳(Anthropic API)・会社(Notion / ai-company リポジトリ / Claude Code)を繋ぐ
- 起動: python3 main.py  (http://localhost:8000)
"""
import os
import re
import shutil
import datetime
from pathlib import Path
from typing import List, Optional

# .env を最初に読む(以下のモジュールは読み込み時に設定を見る)
BASE = Path(__file__).resolve().parent
for line in (BASE / ".env").read_text().splitlines() if (BASE / ".env").exists() else []:
    if "=" in line and not line.strip().startswith("#"):
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip())

import httpx
import uvicorn
from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response
from pydantic import BaseModel

import asyncio
import html

import json
import subprocess
import sys

from fastapi.responses import StreamingResponse

import agent
import company
import accounts
import proposals
import reels
import content
import corrections
import notion
import org
import scheduler

COMPANY_DIR = company.COMPANY_DIR
SECRETARY_NAME = agent.SECRETARY_NAME
# 声: VOICEVOX(無料の読み上げソフト)が起動していればその声を使う。無ければブラウザの声
VOICEVOX_URL = os.getenv("VOICEVOX_URL", "http://127.0.0.1:50021").rstrip("/")
VOICEVOX_SPEAKER = os.getenv("VOICEVOX_SPEAKER", "冥鳴ひまり").strip()

app = FastAPI(title="AI-Secretary Hub")


@app.on_event("startup")
async def start_scheduler():
    asyncio.create_task(scheduler.loop())  # 決まった時間に動く係
    asyncio.create_task(media_loop())       # 完成した画像・動画を Google ドライブへ写す
    asyncio.create_task(reels_loop())       # 声なしのリールを声入りに書き出し直す
    asyncio.create_task(watch_loop())       # 参考アカウントの評価・確認の結果を台帳と Notion に反映
    asyncio.create_task(meeting_loop())     # 会議の議事録を Notion に載せ、やることを起票して通知
    asyncio.create_task(instagram_loop())   # Meta 公式の仕組みで、自社のフォロワー数(毎日)と参考アカウントの数字(毎週月曜)を取る
    asyncio.create_task(worklog_backfill())  # 作業ログが無い直近の作業を、作業ログに載せる(最初の1回)
    asyncio.create_task(task_tidy_loop())    # 「進行中」のまま止まったタスクを、作業の結果に合わせて直す(30分ごと)
    asyncio.create_task(git_sync_loop())     # 会社のフォルダを GitHub と自動でそろえる(10分ごと。作業中は待つ)


async def git_sync_loop():
    import gitsync
    await asyncio.sleep(30)
    last_ok = True
    while True:
        try:
            busy = any(j.get("status") == "running" for j in agent.jobs.values())
            if gitsync.enabled() and not busy:
                r = await asyncio.to_thread(gitsync.sync)
                if r.get("conflicts"):
                    scheduler.notify("会社のフォルダを自動保存しました", "GitHub 側と同じ所が変わっていたので、Mac 側を優先しました: "
                                     + "、".join(r["conflicts"][:5]), "info")
                if not r.get("ok") and last_ok:
                    scheduler.notify("会社のフォルダの自動保存が止まっています", r.get("detail", ""), "warn")
                last_ok = bool(r.get("ok"))
        except Exception as e:
            print("自動保存でエラー:", e)
        await asyncio.sleep(600)


async def task_tidy_loop():
    await asyncio.sleep(60)
    while True:
        try:
            r = await agent.tidy_tasks()
            n = sum(r.values())
            if n:
                parts = [f"{k}{v}件" for k, v in r.items() if v]
                scheduler.notify("タスクの状態を整えました", "進行中のまま止まっていたタスク: " + "・".join(parts), "info")
        except Exception as e:
            print("タスクの整理でエラー:", e)
        await asyncio.sleep(1800)


async def worklog_backfill():
    """この仕組みより前の作業(直近14日)も、作業ログ(Notion・worklog/日付フォルダ)に載せておく"""
    try:  # ついでに数字の表を整える(フォロワーの重複行をまとめる)
        r = company.normalize_followers()
        if r.get("removed"):
            print(f"followers.csv の重複 {r['removed']}行をまとめました")
    except Exception as e:
        print("followers.csv を整えられませんでした:", e)
    try:  # 2026-11-12: 手入力の数字の空欄は 0 にそろえる(本・別アカウント)
        for acct in company.account_ids():
            n = accounts.fill_zeros(acct)
            if n:
                print(f"数字の表の空欄 {n}か所を 0 にしました({acct})")
    except Exception as e:
        print("数字の表の空欄を 0 にできませんでした:", e)
    import worklog
    await asyncio.sleep(20)
    since = (datetime.datetime.now() - datetime.timedelta(days=14)).isoformat()
    for j in list(agent.jobs.values()):
        if j.get("status") == "running" or j.get("worklog") or (j.get("started") or "") < since:
            continue
        try:
            j["worklog"] = await worklog.publish(j, [])
        except Exception as e:
            j["worklog"] = {"error": str(e)[:200]}
    agent._save_jobs()


async def instagram_loop():
    import instagram_api
    last_day, last_week = "", ""
    while True:
        try:
            now = datetime.datetime.now()
            today = now.date().isoformat()
            if now.strftime("%H:%M") >= "08:00" and last_day != today:
                # 2026-11-12: つないだ全アカウント(本・別)の Instagram・Threads・YouTube のフォロワーと投稿ごとの数字を1日1回
                last_day = today
                import stats_sync
                r = await stats_sync.run()
                bad = [k for k, v in r.items() if v.get("connected") and not v.get("ok")]
                if bad:
                    print("数字の自動取得で失敗:", {k: r[k]["detail"] for k in bad})
            if instagram_api.configured() and now.strftime("%H:%M") >= "08:00":
                if now.weekday() == 0 and last_week != today:  # 月曜: 週次リサーチ(8:30)の前に参考アカウントの数字
                    last_week = today
                    r = await instagram_api.refresh_watched()
                    print("参考アカウント(Instagram)を更新:", r)
        except Exception as e:
            print("Instagram の数字の取得でエラー:", e)
        await asyncio.sleep(300)


async def meeting_loop():
    import meetings
    while True:
        try:
            r = await meetings.sync()
            if r:
                print("議事録を反映しました:", r)
        except Exception as e:
            print("議事録の反映でエラー:", e)
        await asyncio.sleep(120)


@app.get("/api/meetings")
def meetings_list():
    import meetings
    running = [j for j in agent.job_list() if (j.get("task_key") or "").startswith("meeting:") and j["status"] == "running"]
    return {"minutes": meetings.list_minutes(), "running": [{"title": j["title"], "started": j["started"], "log": j.get("log", [])[-12:],
                                                              "activity": j.get("activity", [])[-20:]} for j in running]}


class MeetingIn(BaseModel):
    kind: str = "adhoc"
    topic: str = ""
    departments: Optional[List[str]] = None


@app.post("/api/meetings")
async def meetings_start(body: MeetingIn):
    actions: list = []
    msg = await agent.run_tool("hold_meeting", {"kind": body.kind, "topic": body.topic, "departments": body.departments}, actions)
    return {"message": msg, "job": next((a["job"] for a in actions if a["type"] == "job"), None)}


async def watch_loop():
    import watch
    while True:
        try:
            n = await watch.sync_updates()
            if n:
                print(f"参考アカウントを {n} 件反映しました")
        except Exception as e:
            print("参考アカウントの反映でエラー:", e)
        await asyncio.sleep(600)


async def reels_loop():
    await asyncio.sleep(60)  # 起動直後は画面の表示を優先
    while True:
        try:
            ok = False
            async with httpx.AsyncClient(timeout=3) as client:
                try:
                    ok = (await client.get(f"{VOICEVOX_URL}/version")).status_code == 200
                except Exception:
                    ok = False
            done = await asyncio.to_thread(reels.render_pending, f"http://127.0.0.1:{os.getenv('HUB_PORT', '8000')}", ok)
            if done:
                await asyncio.to_thread(content.sync_media)
                scheduler.notify("リールに声を入れました", "、".join(done) + " を声入りにしました(Google ドライブも更新済み)。", "info")
            elif reels.last_error:
                print("  ⚠ リールの声入れ:", reels.last_error)
        except Exception as e:
            print("  ⚠ リールの声入れに失敗:", e)
        await asyncio.sleep(900)


async def media_loop():
    while True:
        try:
            n = await asyncio.to_thread(content.sync_media)
            if n:
                print(f"  画像・動画 {n} 件を Google ドライブ({content.media_dir()})へ保存しました")
            gone = await asyncio.to_thread(content.prune_local_media)  # 写し終わった古いものを Mac から消す
            if gone:
                print(f"  ドライブに写し終わった古い画像・動画 {gone} 件を Mac から消しました(ドライブには残っています)")
        except Exception as e:
            print("  ⚠ Google ドライブへの保存に失敗:", e)
        await asyncio.sleep(600)


def err(e: Exception, code: int = 502):
    return JSONResponse({"error": str(e)}, status_code=code)


# ---------- 状態 ----------
_tools_cache = {"at": 0.0, "v": None}


def video_tools() -> dict:
    """動画の道具(ffmpeg・Node.js 22)がそろっているか。1分ごとに確かめ直す"""
    import time
    if _tools_cache["v"] and time.time() - _tools_cache["at"] < 60:
        return _tools_cache["v"]
    env = agent._job_env()
    ff = shutil.which("ffmpeg", path=env["PATH"])
    try:
        nv = subprocess.run(["node", "--version"], capture_output=True, text=True, timeout=5, env=env).stdout.strip()
    except Exception:
        nv = ""
    major = int(nv.lstrip("v").split(".")[0]) if nv[1:2].isdigit() else 0
    v = {"ffmpeg": ff or "", "node": nv, "node_ok": major >= 22, "ok": bool(ff) and major >= 22}
    _tools_cache.update(at=time.time(), v=v)
    return v


@app.get("/api/health")
def health():
    return {"ok": True, "secretary": SECRETARY_NAME, "company_dir": str(COMPANY_DIR),
            "company_found": COMPANY_DIR.exists(), "api_key_set": bool(agent.API_KEY), "model": agent.MODEL,
            "notion": notion.configured(), "claude_cli": bool(shutil.which("claude")),
            "agents": (COMPANY_DIR / ".claude" / "agents").exists(), "video_tools": video_tools()}


@app.get("/api/company/summary")
async def summary():
    data = await company.summary()
    data["jobs"] = agent.job_list()[:10]
    data["metrics"] = company.metrics()
    data["usage"] = agent.usage_summary()
    data["content_weeks"] = content.list_weeks()[:6]
    data["scheduler"] = scheduler.summary()
    data["rule_proposals"] = corrections.proposals()
    try:
        import knowledge
        data["pref_pending"] = knowledge.prefs()["pending"]
    except Exception:
        data["pref_pending"] = []
    return data


@app.get("/api/briefing")
async def briefing():
    """起動時の報告。APIキーが無いときは text なし(画面側で簡易の挨拶を出す)"""
    if not agent.API_KEY:
        return {"text": None}
    try:
        return await agent.briefing()
    except Exception as e:
        return {"text": None, "error": str(e)}


# ---------- タスク ----------
class TaskIn(BaseModel):
    title: str
    assignee: str = "秘書"
    due: Optional[str] = None
    note: str = ""


class TaskPatch(BaseModel):
    status: Optional[str] = None
    note: Optional[str] = None
    due: Optional[str] = None  # "YYYY-MM-DD"。"" で期限を消す


class Decision(BaseModel):
    decision: str  # approve / reject
    comment: str = ""


@app.post("/api/tasks")
async def create_task(t: TaskIn):
    try:
        return await company.create_task(t.title, t.assignee, t.due or None, t.note)
    except Exception as e:
        return err(e)


@app.patch("/api/tasks/{key}")
async def patch_task(key: str, body: TaskPatch):
    """社長が画面で状態を変える(社長の操作なので承認済みも可)"""
    try:
        note = body.note and f"{body.note}({datetime.date.today():%m/%d} 社長)"
        return await company.update_task(key, status=body.status, append_note=note, due=body.due)
    except ValueError as e:
        return err(e, 400)
    except Exception as e:
        return err(e)


@app.post("/api/tasks/{key}/decision")
async def decide(key: str, body: Decision):
    """承認カードのボタン(または社長の「はい」)から呼ばれる。承認・差し戻しの確定はここだけ"""
    today = f"{datetime.date.today():%m/%d}"
    try:
        try:  # 答える前の状態(確認待ちだったか)を見ておく
            before = await company.find_task(key)
        except Exception:
            before = {}
        if body.decision == "approve":
            note = f"{today} 社長が秘書ハブで承認" + (f":{body.comment}" if body.comment else "")
            t = await company.update_task(key, status="承認済み", append_note=note)
        elif body.decision == "reject":
            note = f"{today} 差し戻し:{body.comment or '(理由なし)'}"
            t = await company.update_task(key, status="差し戻し", append_note=note)
            asyncio.create_task(agent.on_correction(f"タスク {t['id']} {t['title'][:40]}", body.comment or "(理由なし)"))
        else:
            return err(ValueError("decision は approve か reject"), 400)
        # 確認タスクに答えたら、確認を出した部署に続きを頼む(2026-11-10)
        if before.get("status") == "確認待ち" or agent.ASK_TITLE.match(t.get("title") or ""):
            agent._resumed.add(t.get("key") or key)
            job = agent.resume_after_answer({**before, **t, "prev_status": before.get("status", "")}, body.decision, body.comment or "")
            if job:
                t = {**t, "resumed_job": job["id"]}
        return t
    except Exception as e:
        return err(e)


@app.post("/api/tasks/{key}/resume")
async def resume_task(key: str):
    """答え済みの確認タスクについて、確認を出した部署に続きを頼む(この仕組みより前に答えた分・頼み直したいとき)"""
    try:
        t = await company.find_task(key)
        if t.get("status") not in ("承認済み", "差し戻し"):
            return err(ValueError("答え済み(承認済み・差し戻し)の確認タスクだけです"), 400)
        last = [x.strip() for x in re.split(r"\s*/\s*", t.get("note") or "") if "社長" in x or "差し戻し" in x]
        job = agent.resume_after_answer({**t, "prev_status": "確認待ち"}, "approve" if t["status"] == "承認済み" else "reject", last[-1] if last else "")
        if not job:
            return err(ValueError("どの部署の確認か分かりませんでした(備考に「出どころ: ○○の作業」が無い)。部署の作業タブから頼んでください"), 400)
        agent._resumed.add(t["key"])
        return {"task": t["id"], "job": job["id"], "department": job["department_full"]}
    except Exception as e:
        return err(e)


# ---------- 資料(Notion) ----------
@app.get("/api/docs")
async def docs():
    if not notion.configured():
        return {"configured": False, "docs": []}
    try:
        return {"configured": True, "docs": await notion.list_documents()}
    except Exception as e:
        return err(e)


@app.get("/api/worklog")
async def worklog_list(days: int = 60):
    if not notion.configured():
        return {"configured": False, "rows": []}
    try:
        return {"configured": True, "rows": await notion.list_worklog(days)}
    except Exception as e:
        return {"configured": True, "rows": [], "error": str(e)[:200]}


@app.get("/api/docs/tree")
async def docs_tree():
    if not notion.configured():
        return {"configured": False, "tree": []}
    try:
        return {"configured": True, "tree": await notion.tree()}
    except Exception as e:
        return {"configured": True, "tree": [], "error": str(e)[:200]}


@app.get("/api/docs/db/{db_id}")
async def doc_db(db_id: str):
    try:
        return await notion.read_database(notion.page_id_from(db_id) or db_id)
    except Exception as e:
        return err(e)


@app.get("/api/docs/{page_id}")
async def doc(page_id: str):
    try:
        return await notion.read_any(notion.page_id_from(page_id) or page_id)
    except Exception as e:
        return err(e)


# ---------- 投稿セット ----------
class PostDecision(BaseModel):
    path: str
    decision: str  # approve / reject / posted / draft(下書きに戻す) / wait(承認待ちに戻す)
    comment: str = ""


@app.get("/api/content/weeks")
def content_weeks():
    return {"weeks": content.list_weeks(), "current": content.current_week()}


@app.get("/api/content/weeks/{week}")
def content_week(week: str):
    try:
        return content.get_week(week)
    except (KeyError, ValueError) as e:
        return err(e, 404)


@app.get("/api/content/file")
def content_file(path: str):
    try:
        return FileResponse(content.safe_path(path))
    except PermissionError as e:
        return err(e, 403)
    except FileNotFoundError as e:
        return err(e, 404)


@app.post("/api/content/decision")
async def content_decision(body: PostDecision):
    """社長が投稿を承認・差し戻し・投稿済みにする(ボタンか声の返事から)"""
    try:
        post = await content.decide(body.path, body.decision, body.comment)
        if body.decision == "reject":
            asyncio.create_task(agent.on_correction(f"投稿 {post['id']} {post['title'][:40]}", body.comment or "(理由なし)"))
        return post
    except (PermissionError, ValueError) as e:
        return err(e, 400)
    except Exception as e:
        return err(e)


class ScheduleIn(BaseModel):
    path: str
    date: str


@app.get("/api/content/to_post")
def content_to_post():
    return {"posts": content.to_post(), "today": datetime.date.today().isoformat()}


@app.get("/api/content/posts")
def content_all_posts():
    return {"posts": content.all_posts()}


@app.post("/api/content/schedule")
def content_schedule(body: ScheduleIn):
    try:
        return content.set_scheduled(body.path, body.date)
    except (PermissionError, ValueError) as e:
        return err(e, 400)


@app.post("/api/content/weeks/{week}/approve")
async def content_approve_week(week: str, account: Optional[str] = None):
    try:
        return await content.approve_week(week, account)
    except Exception as e:
        return err(e, 400)


# ---------- 数字・アカウント・レポート ----------
class RevenueIn(BaseModel):
    amount: int
    source: str = "other"
    date: Optional[str] = None
    memo: str = ""


class FollowersIn(BaseModel):
    platform: str
    followers: int
    date: Optional[str] = None
    account: str = "main"


class AccountIn(BaseModel):
    platform: str
    url: str
    opened: Optional[str] = None
    account: str = "main"


@app.post("/api/metrics/revenue")
async def add_revenue(body: RevenueIn):
    try:
        return await company.record_revenue(body.amount, body.source, body.date, body.memo)
    except ValueError as e:
        return err(e, 400)


class InsightIn(BaseModel):
    values: dict
    date: Optional[str] = None
    per_post: bool = False  # 投稿ごとの結果(note は記事ごとの表に入れる)
    account: str = "main"


class ImprovementIn(BaseModel):
    text: str
    account: str = "main"


class AccountSetIn(BaseModel):
    label: str
    note: str = ""


@app.post("/api/account_sets")
def add_account_set(body: AccountSetIn):
    """別アカウントを1つ足す(2026-11-12 社長: アカウントが増えても選べるように)"""
    try:
        return company.add_account_set(body.label, body.note)
    except ValueError as e:
        return err(e, 400)


@app.get("/api/accounts")
def get_accounts(account: str = "main"):
    try:
        return {"accounts": accounts.summary(account), "sets": accounts.account_sets()}
    except (ValueError, KeyError) as e:
        return err(e, 400)


@app.get("/api/accounts/{platform}")
def get_account(platform: str, account: str = "main"):
    try:
        return accounts.overview(platform, account)
    except ValueError as e:
        return err(e, 404)


@app.post("/api/accounts/{platform}/insights")
def add_insight(platform: str, body: InsightIn):
    try:
        return accounts.record_insight(platform, body.values, body.date, per_post=body.per_post, account=body.account)
    except ValueError as e:
        return err(e, 400)


@app.get("/api/accounts/{platform}/results")
def get_post_results(platform: str, id: str, account: str = "main"):
    try:
        return accounts.post_results(platform, id, account)
    except ValueError as e:
        return err(e, 400)


class CrosspostIn(BaseModel):
    path: str
    date: Optional[str] = None
    undo: bool = False  # 間違えて「投稿した」を押したのを取り消す


@app.post("/api/accounts/{platform}/crossposted")
def crossposted(platform: str, body: CrosspostIn):
    try:
        return accounts.mark_crossposted(platform, body.path, body.date, body.undo)
    except (ValueError, PermissionError) as e:
        return err(e, 400)


@app.post("/api/accounts/{platform}/improvements")
def add_improvement(platform: str, body: ImprovementIn):
    try:
        return accounts.add_improvement(platform, body.text, account=body.account)
    except ValueError as e:
        return err(e, 400)


@app.post("/api/metrics/followers")
def add_followers(body: FollowersIn):
    try:
        return company.record_followers(body.platform, body.followers, body.date, body.account)
    except ValueError as e:
        return err(e, 400)


@app.post("/api/accounts")
async def add_account(body: AccountIn):
    try:
        return await company.register_account(body.platform, body.url, body.opened, body.account)
    except ValueError as e:
        return err(e, 400)


# ---------- 請け負いの提案(ランサーズ・ココナラ。2026-11-12 社長) ----------
class ProposalIn(BaseModel):
    service: str
    title: str
    url: str = ""
    amount: str = ""
    memo: str = ""
    date: Optional[str] = None


class ProposalPatch(BaseModel):
    status: Optional[str] = None
    amount: Optional[str] = None
    memo: Optional[str] = None


class ProposalRevenueIn(BaseModel):
    amount: Optional[str] = None
    date: Optional[str] = None


@app.get("/api/proposals")
def get_proposals(service: Optional[str] = None):
    return proposals.listing(service)


@app.post("/api/proposals")
def add_proposal(body: ProposalIn):
    try:
        return proposals.add(body.service, body.title, body.url, body.amount, body.memo, body.date)
    except ValueError as e:
        return err(e, 400)


@app.patch("/api/proposals/{pid}")
def patch_proposal(pid: str, body: ProposalPatch):
    try:
        return proposals.update(pid, body.status, body.amount, body.memo)
    except (ValueError, KeyError) as e:
        return err(e, 400)


@app.post("/api/proposals/{pid}/revenue")
async def proposal_revenue(pid: str, body: ProposalRevenueIn):
    try:
        return await proposals.record_revenue(pid, body.amount, body.date)
    except (ValueError, KeyError) as e:
        return err(e, 400)


# ---------- LINE スタンプ・絵文字(2026-11-12 社長) ----------
class StampDecision(BaseModel):
    action: str
    comment: str = ""
    url: str = ""


@app.get("/api/stamps")
def stamps_list(kind: Optional[str] = None):
    import stamps
    return stamps.list_sets(kind if kind in ("stamp", "emoji") else None)


@app.post("/api/stamps/{sid}/decision")
async def stamps_decide(sid: str, body: StampDecision):
    """社長がスタンプのセットを承認・差し戻し・申請した・販売中にする(ボタンから)"""
    import stamps
    try:
        r = stamps.decide(sid, body.action, body.comment, body.url)
        if body.action in ("reject", "line_rejected"):
            asyncio.create_task(agent.on_correction(f"LINEスタンプ {sid} {r['title'][:40]}", body.comment or "(理由なし)"))
        return r
    except (ValueError, KeyError) as e:
        return err(e, 400)


# ---------- YouTube アナリティクス(最初に一度だけ Google で許可する。2026-11-12) ----------
@app.get("/api/youtube/oauth/start")
def yt_oauth_start(account: str = "main"):
    import youtube_analytics
    from fastapi.responses import RedirectResponse
    try:
        company.check_account(account)
        return RedirectResponse(youtube_analytics.auth_url(account))
    except Exception as e:
        return HTMLResponse(f"<meta charset='utf-8'><p>始められませんでした: {html.escape(str(e))}</p>", status_code=400)


@app.get("/api/youtube/oauth/callback")
async def yt_oauth_callback(code: str = "", state: str = "", error: str = ""):
    import youtube_analytics
    if error:
        return HTMLResponse(f"<meta charset='utf-8'><p>許可されませんでした({html.escape(error)})。秘書ハブに戻ってやり直してください。</p>")
    try:
        r = await youtube_analytics.finish(code, state)
        return HTMLResponse("<meta charset='utf-8'><h2>YouTube アナリティクスをつなぎました</h2>"
                            f"<p>チャンネル: {html.escape(r.get('channel') or '(名前は取れませんでした)')}</p>"
                            "<p>このタブは閉じて、秘書ハブに戻ってください。毎朝 8:00 に自動で数字を取ります。</p>")
    except Exception as e:
        return HTMLResponse(f"<meta charset='utf-8'><p>つなげませんでした: {html.escape(str(e))}</p>", status_code=400)


@app.post("/api/stats/sync")
async def stats_sync_now(only: str = ""):
    """つないだアカウントの数字を今すぐ取る(アカウント画面の「今すぐ取る」ボタン)"""
    import stats_sync
    return await stats_sync.run(only)


@app.post("/api/reports/weekly")
async def make_report(week: Optional[str] = None):
    if not agent.API_KEY:
        return err(ValueError("週次レポートの作成には ANTHROPIC_API_KEY が必要です"), 400)
    try:
        return await agent.weekly_report(week)
    except Exception as e:
        return err(e)


# ---------- 定時チェック・お知らせ・修正ログ ----------
class SchedulerIn(BaseModel):
    auto: Optional[bool] = None
    times: Optional[List[str]] = None


class RuleDecision(BaseModel):
    approve: bool


@app.get("/api/scheduler")
def get_scheduler():
    return scheduler.summary()


@app.post("/api/scheduler")
def set_scheduler(body: SchedulerIn):
    try:
        scheduler.update_settings(body.auto, body.times)
        return scheduler.summary()
    except ValueError as e:
        return err(e, 400)


@app.post("/api/scheduler/run")
async def run_scheduler():
    return await scheduler.run_check()


@app.post("/api/news/flash")
def run_news_flash():
    """AIの新機能の速報チェックを今すぐ頼む(公式の更新情報を集めてから部署に渡す)"""
    try:
        return {"job": scheduler.run_routine_now("news_flash_am")}
    except ValueError as e:
        return err(e, 400)


# ---------- 参考動画の分析(2026-11-13 社長「コマ送りでは分かりにくい。音とテロップの使い方を確認してほしい」) ----------
@app.post("/api/video_refs")
async def upload_video_ref(request: Request, name: str = "", note: str = ""):
    """動画を本文そのままで受け取り(ヘッダー x-filename)、分けて材料を作り、映像制作部に分析を頼む"""
    import video_ref
    from urllib.parse import unquote
    filename = unquote(request.headers.get("x-filename", "video.mp4"))
    chunks = []
    async for c in request.stream():
        chunks.append(c)
    try:
        ref_id = await asyncio.to_thread(video_ref.save_upload, chunks, filename)
    except ValueError as e:
        return err(e, 400)
    return video_ref.start(ref_id, name.strip() or Path(filename).stem, note.strip())


@app.get("/api/video_refs")
def list_video_refs():
    import video_ref
    return {"items": video_ref.listing()}


@app.get("/api/notifications")
def get_notifications():
    return {"notifications": scheduler.notifications()}


@app.post("/api/notifications/read")
def read_notifications(body: dict):
    scheduler.mark_read(body.get("ids") or [])
    return {"ok": True}


@app.get("/api/rules")
def get_rules():
    return {"proposals": corrections.proposals(), "rules": corrections.rules(), "corrections": corrections.recent(20)}


@app.post("/api/rules/{pid}/decision")
def decide_rule(pid: str, body: RuleDecision):
    """ルール案の承認・却下(社長の操作だけ)"""
    try:
        return corrections.decide(pid, body.approve)
    except KeyError as e:
        return err(e, 404)


# ---------- 部署の作業(Claude Code) ----------
class JobIn(BaseModel):
    department: str
    title: str
    instruction: str


@app.get("/api/jobs")
def jobs():
    return {"jobs": agent.job_list(), "claude_cli": bool(shutil.which("claude"))}


@app.post("/api/jobs")
async def new_job(body: JobIn):
    actions: list = []
    await agent.run_tool("delegate_work", body.dict(), actions)
    return next((a["job"] for a in actions if a["type"] == "job"), {})


# ---------- 資料室 ----------
class PrefIn(BaseModel):
    text: str
    needs_check: bool = False
    reason: str = ""


class PrefDecision(BaseModel):
    approve: bool
    revised: str = ""


@app.get("/api/knowledge")
def knowledge_overview():
    import knowledge
    return knowledge.overview()


@app.get("/api/knowledge/search")
def knowledge_search(q: str = ""):
    import knowledge
    return {"hits": knowledge.search(q, limit=20)}


@app.post("/api/knowledge/prefs")
def knowledge_add_pref(body: PrefIn):
    import knowledge
    return knowledge.add_pref(body.text, body.needs_check, body.reason, "社長・画面")


@app.post("/api/knowledge/prefs/{pid}")
def knowledge_decide_pref(pid: str, body: PrefDecision):
    import knowledge
    try:
        return knowledge.decide_pref(pid, body.approve, body.revised)
    except KeyError as e:
        return JSONResponse({"error": str(e)}, status_code=404)


# ---------- 声(VOICEVOX) ----------
class TtsIn(BaseModel):
    text: str
    speaker: Optional[int] = None
    tone: Optional[str] = None


# 声の感情: 速さ・高さ・抑揚・音量(VOICEVOX の audio_query の値)
TONES = {
    "": dict(speedScale=1.1, pitchScale=0.0, intonationScale=1.15, volumeScale=1.0),
    "joy": dict(speedScale=1.13, pitchScale=0.035, intonationScale=1.4, volumeScale=1.06),
    "excited": dict(speedScale=1.18, pitchScale=0.06, intonationScale=1.55, volumeScale=1.15),
    "calm": dict(speedScale=1.0, pitchScale=-0.01, intonationScale=0.95, volumeScale=0.92),
    "serious": dict(speedScale=1.03, pitchScale=-0.03, intonationScale=0.85, volumeScale=1.02),
    "sad": dict(speedScale=0.93, pitchScale=-0.04, intonationScale=0.8, volumeScale=0.85),
    "emph": dict(speedScale=1.05, pitchScale=0.02, intonationScale=1.45, volumeScale=1.2),
    "soft": dict(speedScale=1.0, pitchScale=-0.015, intonationScale=1.0, volumeScale=0.9),
}


def apply_tone(query: dict, tone: str, text: str) -> dict:
    query.update(TONES.get(tone or "", TONES[""]))
    t = text.strip()
    # 問いかけは語尾を上げる
    if t.endswith(("?", "？")) and query.get("accent_phrases"):
        moras = query["accent_phrases"][-1].get("moras") or []
        for k, m in enumerate(moras[-2:]):
            if m.get("pitch", 0) > 0:
                m["pitch"] += 0.18 * (k + 1)
    # 「…」は余韻を長めに
    if t.endswith(("…", "...")):
        query["postPhonemeLength"] = 0.45
    return query

async def voicevox_speakers():
    """VOICEVOX の声の一覧 [{id, name}]。起動していなければ []"""
    try:
        async with httpx.AsyncClient(timeout=3) as client:
            r = await client.get(f"{VOICEVOX_URL}/speakers")
            r.raise_for_status()
    except Exception:
        return []
    return [{"id": st["id"], "name": f"{sp['name']}({st['name']})"}
            for sp in r.json() for st in sp.get("styles", [])]

def default_speaker(speakers):
    """VOICEVOX_SPEAKER(名前の一部 or 数字のID)に合う声。ノーマルを優先"""
    if VOICEVOX_SPEAKER.isdigit():
        return int(VOICEVOX_SPEAKER)
    hits = [s for s in speakers if VOICEVOX_SPEAKER and VOICEVOX_SPEAKER in s["name"]]
    best = next((s for s in hits if "ノーマル" in s["name"]), hits[0] if hits else None)
    return (best or speakers[0])["id"] if speakers else None

@app.get("/api/tts/speakers")
async def tts_speakers():
    speakers = await voicevox_speakers()
    return {"available": bool(speakers), "speakers": speakers, "default": default_speaker(speakers)}

@app.post("/api/tts")
async def tts(body: TtsIn):
    text = body.text.strip()[:500]
    if not text:
        return JSONResponse({"error": "text required"}, status_code=400)
    speaker = body.speaker if body.speaker is not None else default_speaker(await voicevox_speakers())
    if speaker is None:
        return JSONResponse({"error": "VOICEVOX が起動していません"}, status_code=503)
    try:
        async with httpx.AsyncClient(timeout=60) as client:
            q = await client.post(f"{VOICEVOX_URL}/audio_query", params={"text": text, "speaker": speaker})
            q.raise_for_status()
            query = apply_tone(q.json(), (body.tone or "").strip(), text)
            wav = await client.post(f"{VOICEVOX_URL}/synthesis", params={"speaker": speaker}, json=query)
            wav.raise_for_status()
    except Exception as e:
        return JSONResponse({"error": f"VOICEVOX で音声を作れませんでした: {e}"}, status_code=502)
    return Response(content=wav.content, media_type="audio/wav")


# ---------- 組織図・検索・診断 ----------
@app.get("/api/org")
def get_org():
    running = {j.get("department_full") or agent.DEPT_FULL.get(j["department"], j["department"])
               for j in agent.job_list() if j["status"] == "running"}
    return {"departments": org.chart(), "running_departments": sorted(running), "jobs": agent.job_list()[:30],
            "members": agent.member_status()}


@app.get("/api/search")
async def search(q: str):
    q = q.strip().lower()
    if not q:
        return {"results": []}
    hits = []
    try:
        for t in await company.list_tasks():
            if q in (t["title"] + " " + (t.get("note") or "") + " " + t["id"]).lower():
                hits.append({"kind": "task", "title": f"{t['id']} {t['title']}", "sub": f"{t['status']}・{t['assignee']}", "key": t["key"],
                             "status": t["status"]})
    except Exception:
        pass
    for p in content.all_posts():
        if q in (p["title"] + " " + p["caption"] + " " + p["id"]).lower():
            hits.append({"kind": "post", "title": p["title"], "sub": f"{p['week']}・{p['platform_ja']}・{p['status']}", "week": p["week"]})
    if notion.configured():
        try:
            for d in await notion.list_documents():
                if q in d["title"].lower():
                    hits.append({"kind": "doc", "title": d["title"], "sub": "Notion のデータベース" if d.get("kind") == "database" else "Notion の資料", "id": d["id"]})
        except Exception:
            pass
    for j in agent.job_list():
        if q in (j["title"] + " " + j["instruction"]).lower():
            hits.append({"kind": "job", "title": f"{j['department']}部:{j['title']}", "sub": j["status"]})
    return {"results": hits[:40]}


@app.get("/api/diagnostics")
async def diagnostics():
    """接続の診断。各項目に ok と、ダメなときの直し方を返す"""
    checks = []

    def add(key, label, ok, detail, fix=""):
        checks.append({"key": key, "label": label, "ok": ok, "detail": detail, "fix": "" if ok else fix})

    add("company", "会社リポジトリ(ai-company)", COMPANY_DIR.exists(), str(COMPANY_DIR),
        "secretary-hub と同じ階層に ai-company を置くか、backend/.env の AI_COMPANY_DIR にフルパスを書く")
    if agent.API_KEY:
        try:
            async with httpx.AsyncClient(timeout=10) as c:
                r = await c.get("https://api.anthropic.com/v1/models", headers={"x-api-key": agent.API_KEY, "anthropic-version": "2023-06-01"})
            add("api", "頭脳(Claude API)", r.status_code == 200, f"モデル {agent.MODEL}" if r.status_code == 200 else f"エラー {r.status_code}",
                "backend/.env の ANTHROPIC_API_KEY を確認(console.anthropic.com で発行)" if r.status_code in (401, 403) else "少し待って再確認")
        except Exception as e:
            add("api", "頭脳(Claude API)", False, f"接続できません: {str(e)[:80]}", "インターネット接続を確認")
    else:
        add("api", "頭脳(Claude API)", False, "APIキーが未設定(簡易モード)", "backend/.env に ANTHROPIC_API_KEY=... を書いて再起動")
    if notion.configured():
        try:
            await notion._req("GET", "/users/me")
            await notion._req("POST", f"/databases/{notion.TASK_DB}/query", json={"page_size": 1})
            add("notion", "Notion", True, "タスクDBに接続できています")
        except Exception as e:
            add("notion", "Notion", False, str(e)[:120], "「AI会社」ページの「•••」→「接続」に「秘書ハブ」を追加。NOTION_TOKEN も確認")
    else:
        add("notion", "Notion", False, "NOTION_TOKEN が未設定(タスクは控えファイルで管理中)", "README「Notion をつなぐ」の手順")
    speakers = await voicevox_speakers()
    add("voicevox", "声(VOICEVOX)", bool(speakers), f"{len(speakers)}種類の声" if speakers else "起動していません",
        "VOICEVOX アプリを起動する(起動後20秒で自動で切り替わります)")
    cli = shutil.which("claude")
    version = ""
    if cli:
        try:
            version = subprocess.run([cli, "--version"], capture_output=True, text=True, timeout=15).stdout.strip()
        except Exception:
            pass
    add("claude", "部署(Claude Code)", bool(cli), version or ("見つかりました" if cli else "claude コマンドがありません"),
        "ターミナルで npm install -g @anthropic-ai/claude-code → claude で一度ログイン")
    agents_dir = COMPANY_DIR / ".claude" / "agents"
    n = len(list(agents_dir.glob("*.md"))) if agents_dir.exists() else 0
    import codex
    cs = codex.status()
    add("codex", "社外制作室(Codex)", cs["cli"] or not cs["media_api"], ("Codex CLI あり" + ("・画像/動画API あり" if cs["media_api"] else "・画像/動画は OPENAI_API_KEY が未設定")) if cs["cli"] else "codex コマンドがありません(使わないなら問題なし)",
        "ターミナルで npm install -g @openai/codex → codex login(ChatGPT のアカウント)。画像・動画は backend/.env に OPENAI_API_KEY=...")
    add("agents", "部署の人材定義", n > 0, f"{n}名", "ai-company で git pull(.claude/agents/ が必要)")
    _tools_cache["v"] = None
    vt = video_tools()
    add("ffmpeg", "動画の道具: ffmpeg(動画の書き出し)", bool(vt["ffmpeg"]), vt["ffmpeg"] or "見つかりません",
        "秘書ハブを起動し直すと自動で入ります(tools/reel の部品)。入らないときはターミナルで `brew install ffmpeg`")
    add("node", "動画の道具: Node.js 22 以上(HyperFrames)", vt["node_ok"], vt["node"] or "見つかりません",
        "ターミナルで `brew install node@22` → `brew link --overwrite --force node@22`(または https://nodejs.org から 22 LTS を入れる)")
    import gitsync
    gs = gitsync.state
    add("gitsync", "会社のフォルダの自動保存(GitHub)", gs["ok"] is not False,
        ("10分ごとに自動で保存・取り込み" if gitsync.enabled() else "止めています(AUTO_GIT_SYNC=0)")
        + (f" ・ 前回 {gs['last'][5:16].replace('T', ' ')}: {gs['detail']}" if gs.get("last") else ""),
        "GitHub にログインできているか確認(ターミナルで ai-company フォルダの git push が通るか)")
    waiting_reels = reels.pending()
    scene_wait = f" ・ 場面のファイル待ち {len(reels.waiting_scene)}本({'、'.join(reels.waiting_scene[:3])})" if reels.waiting_scene else ""
    add("reels", "リールの声入れ", not waiting_reels and not reels.last_error,
        ("すべて声入り" if not waiting_reels else f"声入り待ち {len(waiting_reels)}本" + (f"(止まっている理由: {reels.last_error})" if reels.last_error else "")) + scene_wait,
        "VOICEVOX を起動しておくと、15分以内に自動で声入りになります(Node.js と Google Chrome が必要)")
    md = content.media_dir()
    add("media", "Google ドライブ(画像・動画の置き場所)", bool(md and md.parent.exists()), str(md) if md else "見つかりません",
        "Mac に Google ドライブのアプリを入れてログイン(または .env の MEDIA_DIR で場所を指定)")
    core = BASE.parent / "frontend" / "public" / "live2d" / "core" / "live2dcubismcore.js"
    import instagram_api
    if instagram_api.configured():
        try:
            m = await instagram_api.me()
            add("instagram_api", "Instagram の数字(Meta 公式)", True, f"@{m.get('username')}・フォロワー {m.get('followers_count')}・トークン {instagram_api.token_status()}")
        except Exception as e:
            add("instagram_api", "Instagram の数字(Meta 公式)", False, str(e)[:120], "ai-company の playbooks/account_connect.md")
    else:
        add("instagram_api", "Instagram の数字(Meta 公式)", False, "未設定(参考アカウントの数字は公開ページで見える範囲だけ)",
            "ai-company の playbooks/account_connect.md の手順で .env に IG_ACCESS_TOKEN を入れる")
    try:  # 2026-11-12: アカウントごとの自動取得の状態(Instagram・Threads・YouTube)
        import stats_sync
        st = stats_sync._state()
        for acct in company.account_ids():
            aj = company.account_label(acct)
            for pf, pj in (("instagram", "Instagram"), ("threads", "Threads"), ("youtube", "YouTube")):
                if acct != "main" and pf not in company.registered_platforms(acct):
                    continue  # 別アカウントで登録の無い媒体は出さない(利用なし)
                v = st.get(f"{acct}:{pf}") or {}
                conn = stats_sync.configured(pf, acct)
                add(f"auto_{acct}_{pf}", f"数字の自動取得 {aj} {pj}", bool(conn and v.get("ok")),
                    (v.get("detail") or ("つないであります(次の 8:00 に取ります)" if conn else "未接続")) + (f"(前回 {v['at'][5:16].replace('T', ' ')})" if v.get("at") else ""),
                    "ai-company の playbooks/account_connect.md(アカウント連携マニュアル)")
        import youtube_analytics
        for acct in company.account_ids():
            if acct != "main" and "youtube" not in company.registered_platforms(acct):
                continue
            ya = youtube_analytics.status(acct)
            add(f"yta_{acct}", f"YouTube アナリティクス {company.account_label(acct)}(総再生時間・視聴を継続)", ya["connected"] and not ya["error"],
                (ya["error"] or (f"つないであります(許可 {ya['since']}・{ya['channel']})" if ya["connected"] else ("未接続(「Google で許可する」を押す)" if ya["client"] else "未設定"))),
                "ai-company の playbooks/account_connect.md の「YouTube アナリティクス」")
    except Exception as e:
        print("自動取得の診断でエラー:", e)
    add("live2d", "Live2D(Cubism Core)", core.exists(), "配置済み" if core.exists() else "未配置(静止画で表示中)",
        "README「Live2D の秘書」の手順で live2dcubismcore.js を置く")
    s = scheduler.summary()
    add("scheduler", "定時チェック", s["auto"], f"{'・'.join(s['times'])}(次 {s['next']})" if s["auto"] else "オフ",
        "⚙ 声・設定 で「定時チェック」をオン")
    return {"checks": checks, "python": sys.version.split()[0]}


# ---------- 会話 ----------
class ChatIn(BaseModel):
    message: str
    history: List[dict] = []


# 褒め言葉(APIキー無しの簡易モードで表情を変えるため)
PRAISE_WORDS = ("ありがとう", "ありがと", "助かる", "助かった", "えらい", "偉い", "さすが", "すごい", "すばらしい",
                "素晴らしい", "かわいい", "可愛い", "いいね", "よくやった", "天才", "最高")


async def simple_reply(msg: str) -> dict:
    """APIキーが無いときの簡易応答(決まった言葉にだけ反応)"""
    data = await company.summary()
    rev, tasks = data["revenue"], data["tasks"]
    appr = [t for t in tasks if t["status"] in ("確認待ち", "承認待ち")]
    open_t = [t for t in tasks if t["status"] != "完了"]
    if "収益" in msg or "売上" in msg:
        return {"reply": f"今月の収益は{rev['month_total']:,}円です。目標5万円に対して{rev['progress']}%です。",
                "mood": "normal", "actions": [{"type": "show_panel", "panel": "home"}]}
    if "承認" in msg:
        acts = [{"type": "approval", "task": appr[0]}] if appr else [{"type": "show_panel", "panel": "tasks"}]
        return {"reply": f"承認待ちは{len(appr)}件です。" + (f"{appr[0]['id']}を表示します。" if appr else ""),
                "mood": "normal", "actions": acts}
    if "タスク" in msg:
        return {"reply": f"未完了のタスクは{len(open_t)}件です。タスク画面を開きます。", "mood": "normal",
                "actions": [{"type": "show_panel", "panel": "tasks"}]}
    if "投稿" in msg:
        return {"reply": "投稿セットを開きます。", "mood": "normal", "actions": [{"type": "show_panel", "panel": "content"}]}
    if "資料" in msg or "企画書" in msg or "ノーション" in msg or "Notion" in msg:
        return {"reply": "資料の一覧を開きます。", "mood": "normal", "actions": [{"type": "show_panel", "panel": "docs"}]}
    if any(w in msg for w in PRAISE_WORDS):
        return {"reply": "……ありがとうございます。そう言っていただけると、少し嬉しいです。", "mood": "pleased", "actions": []}
    return {"reply": "APIキーが未設定のため、収益・タスク・承認・資料の確認だけできます。キーを入れると何でも頼めます。",
            "mood": "normal", "actions": []}


@app.post("/api/chat")
async def chat(body: ChatIn):
    msg = body.message.strip()
    if not msg:
        return JSONResponse({"error": "message required"}, status_code=400)
    if not agent.API_KEY:
        return await simple_reply(msg)
    return await agent.chat(msg, body.history)


@app.post("/api/chat/stream")
async def chat_stream(body: ChatIn):
    """返事を1行ずつ(NDJSON)で返す。画面は届いた文から順に読み上げる"""
    msg = body.message.strip()

    async def gen():
        if not msg:
            yield json.dumps({"t": "done", "reply": "", "mood": "normal", "actions": []}, ensure_ascii=False) + "\n"
            return
        if not agent.API_KEY:
            r = await simple_reply(msg)
            yield json.dumps({"t": "text", "v": r["reply"]}, ensure_ascii=False) + "\n"
            yield json.dumps({"t": "done", **r}, ensure_ascii=False) + "\n"
            return
        async for ev in agent.chat_stream(msg, body.history):
            yield json.dumps(ev, ensure_ascii=False) + "\n"

    return StreamingResponse(gen(), media_type="application/x-ndjson")


# ---------- フロント配信(ビルド済み) ----------
DIST = BASE.parent / "frontend" / "dist"
if DIST.exists():
    # dist 全体を配信する(assets だけでなく faces/・live2d/ も)。API は上で先に登録済みなので優先される
    app.mount("/", StaticFiles(directory=DIST, html=True), name="frontend")

if __name__ == "__main__":
    print(f"\n  AI秘書ハブ起動: http://localhost:8000")
    print(f"  会社ディレクトリ: {COMPANY_DIR} ({'OK' if COMPANY_DIR.exists() else '見つかりません'})")
    print(f"  APIキー: {'設定済み(' + agent.MODEL + ')' if agent.API_KEY else '未設定(.env に ANTHROPIC_API_KEY=...)'}")
    print(f"  Notion: {'接続設定あり' if notion.configured() else '未設定(.env に NOTION_TOKEN=... ・タスクは控えファイルで管理)'}\n")
    uvicorn.run(app, host=os.getenv("HUB_HOST", "127.0.0.1"), port=8000, log_level="warning")
