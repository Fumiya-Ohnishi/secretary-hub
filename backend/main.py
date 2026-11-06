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
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse, Response
from pydantic import BaseModel

import asyncio

import agent
import company
import content
import corrections
import notion
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


def err(e: Exception, code: int = 502):
    return JSONResponse({"error": str(e)}, status_code=code)


# ---------- 状態 ----------
@app.get("/api/health")
def health():
    return {"ok": True, "secretary": SECRETARY_NAME, "company_dir": str(COMPANY_DIR),
            "company_found": COMPANY_DIR.exists(), "api_key_set": bool(agent.API_KEY), "model": agent.MODEL,
            "notion": notion.configured(), "claude_cli": bool(shutil.which("claude")),
            "agents": (COMPANY_DIR / ".claude" / "agents").exists()}


@app.get("/api/company/summary")
async def summary():
    data = await company.summary()
    data["jobs"] = agent.job_list()[:10]
    data["metrics"] = company.metrics()
    data["usage"] = agent.usage_summary()
    data["content_weeks"] = content.list_weeks()[:6]
    data["scheduler"] = scheduler.summary()
    data["rule_proposals"] = corrections.proposals()
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
        if body.decision == "approve":
            note = f"{today} 社長が秘書ハブで承認" + (f":{body.comment}" if body.comment else "")
            return await company.update_task(key, status="承認済み", append_note=note)
        if body.decision == "reject":
            note = f"{today} 差し戻し:{body.comment or '(理由なし)'}"
            t = await company.update_task(key, status="差し戻し", append_note=note)
            asyncio.create_task(agent.on_correction(f"タスク {t['id']} {t['title'][:40]}", body.comment or "(理由なし)"))
            return t
        return err(ValueError("decision は approve か reject"), 400)
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


@app.get("/api/docs/{page_id}")
async def doc(page_id: str):
    try:
        return await notion.read_page(notion.page_id_from(page_id) or page_id)
    except Exception as e:
        return err(e)


# ---------- 投稿セット ----------
class PostDecision(BaseModel):
    path: str
    decision: str  # approve / reject / posted
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


@app.post("/api/content/weeks/{week}/approve")
async def content_approve_week(week: str):
    try:
        return await content.approve_week(week)
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


class AccountIn(BaseModel):
    platform: str
    url: str
    opened: Optional[str] = None


@app.post("/api/metrics/revenue")
async def add_revenue(body: RevenueIn):
    try:
        return await company.record_revenue(body.amount, body.source, body.date, body.memo)
    except ValueError as e:
        return err(e, 400)


@app.post("/api/metrics/followers")
def add_followers(body: FollowersIn):
    try:
        return company.record_followers(body.platform, body.followers, body.date)
    except ValueError as e:
        return err(e, 400)


@app.post("/api/accounts")
async def add_account(body: AccountIn):
    try:
        return await company.register_account(body.platform, body.url, body.opened)
    except ValueError as e:
        return err(e, 400)


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


# ---------- 声(VOICEVOX) ----------
class TtsIn(BaseModel):
    text: str
    speaker: Optional[int] = None

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
            query = q.json()
            query["speedScale"] = 1.1
            wav = await client.post(f"{VOICEVOX_URL}/synthesis", params={"speaker": speaker}, json=query)
            wav.raise_for_status()
    except Exception as e:
        return JSONResponse({"error": f"VOICEVOX で音声を作れませんでした: {e}"}, status_code=502)
    return Response(content=wav.content, media_type="audio/wav")


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
    appr = [t for t in tasks if t["status"] == "承認待ち"]
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
