"""
AI秘書ハブ — 中継サーバー
- 顔(Reactフロント)と脳(Anthropic API)・会社(Claude Code リポジトリ)を繋ぐ
- 起動: python3 main.py  (http://localhost:8000)
"""
import os
import re
import csv
import json
import shutil
import subprocess
import threading
import datetime
from pathlib import Path

import httpx
import uvicorn
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel

# ---------- 設定 ----------
BASE = Path(__file__).resolve().parent
# 会社リポジトリの場所(環境変数 or 既定: 同階層の ai-company)
COMPANY_DIR = Path(os.getenv("AI_COMPANY_DIR", BASE.parent / "ai-company"))
# .env を簡易読み込み
for line in (BASE / ".env").read_text().splitlines() if (BASE / ".env").exists() else []:
    if "=" in line and not line.strip().startswith("#"):
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip())

API_KEY = os.getenv("ANTHROPIC_API_KEY", "").strip()
MODEL = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-5")
SECRETARY_NAME = os.getenv("SECRETARY_NAME", "セナ")

app = FastAPI(title="AI-Secretary Hub")

# ---------- 会社データの読み取り ----------
def company_paths():
    return {
        "revenue": COMPANY_DIR / "data" / "revenue.csv",
        "tasks": COMPANY_DIR / "data" / "tasks.md",
        "insights_ig": COMPANY_DIR / "data" / "insights_ig.csv",
        "insights_note": COMPANY_DIR / "data" / "insights_note.csv",
        "roadmap": COMPANY_DIR / "strategy" / "roadmap.md",
        "concept": COMPANY_DIR / "strategy" / "concept.md",
        "reports": COMPANY_DIR / "reports",
    }

def read_revenue():
    p = company_paths()["revenue"]
    rows = []
    if p.exists():
        with p.open() as f:
            for r in csv.DictReader(f):
                try:
                    rows.append({"date": r.get("date",""), "source": r.get("source",""),
                                 "amount": int(float(r.get("amount", 0) or 0)),
                                 "memo": r.get("memo","")})
                except ValueError:
                    pass
    month = datetime.date.today().strftime("%Y-%m")
    m_total = sum(r["amount"] for r in rows if r["date"].startswith(month))
    return {"month": month, "month_total": m_total, "all_total": sum(r["amount"] for r in rows), "rows": rows[-20:]}

def read_tasks():
    """tasks.md のテーブル行を緩くパース(Notion未設定時の正)"""
    p = company_paths()["tasks"]
    tasks = []
    if p.exists():
        for line in p.read_text().splitlines():
            m = re.match(r"\|\s*(T-\d+)\s*\|\s*(.+?)\s*\|\s*(.+?)\s*\|\s*(.+?)\s*\|\s*(未着手|進行中|承認待ち|承認済み|完了|差し戻し)\s*\|", line)
            if m:
                tasks.append({"id": m.group(1), "title": m.group(2), "assignee": m.group(3),
                              "due": m.group(4), "status": m.group(5)})
    return tasks

def company_summary_text():
    rev = read_revenue()
    tasks = read_tasks()
    open_t = [t for t in tasks if t["status"] not in ("完了",)]
    approval = [t for t in tasks if t["status"] == "承認待ち"]
    lines = [
        f"【会社データ(自動取得)】",
        f"- 今月の収益: {rev['month_total']:,}円(目標50,000円に対する進捗 {round(rev['month_total']/50000*100)}%)",
        f"- タスク: 全{len(tasks)}件/未完了{len(open_t)}件/承認待ち{len(approval)}件",
    ]
    for t in open_t[:5]:
        lines.append(f"  - {t['id']} {t['title']}({t['assignee']}) 状態:{t['status']}")
    if not open_t:
        lines.append("  - 未完了タスクなし")
    return "\n".join(lines)

# ---------- Claude Code 実行 ----------
claude_jobs = {}  # id -> {status, output}

def run_claude_job(job_id, prompt):
    try:
        if not shutil.which("claude"):
            claude_jobs[job_id] = {"status": "error",
                "output": "Claude Code CLI が見つかりません。ターミナルで `npm install -g @anthropic-ai/claude-code` を実行し、`claude` で一度ログインしてください。"}
            return
        proc = subprocess.run(
            ["claude", "-p", prompt, "--permission-mode", "acceptEdits"],
            cwd=str(COMPANY_DIR), capture_output=True, text=True, timeout=1800,
        )
        out = (proc.stdout or "").strip() or (proc.stderr or "").strip()
        claude_jobs[job_id] = {"status": "done" if proc.returncode == 0 else "error", "output": out[:4000]}
    except Exception as e:
        claude_jobs[job_id] = {"status": "error", "output": str(e)}

# ---------- API ----------
class ChatIn(BaseModel):
    message: str

class TaskIn(BaseModel):
    title: str
    assignee: str = "秘書"

@app.get("/api/health")
def health():
    return {"ok": True, "company_dir": str(COMPANY_DIR), "company_found": COMPANY_DIR.exists(),
            "api_key_set": bool(API_KEY), "claude_cli": bool(shutil.which("claude"))}

@app.get("/api/company/summary")
def summary():
    return {"revenue": read_revenue(), "tasks": read_tasks(),
            "company_found": COMPANY_DIR.exists()}

@app.post("/api/company/task")
def add_task(t: TaskIn):
    p = company_paths()["tasks"]
    today = datetime.date.today().strftime("%Y-%m-%d")
    ids = [int(m.group(1)) for m in re.finditer(r"T-(\d+)", p.read_text())] if p.exists() else []
    new_id = f"T-{(max(ids) + 1) if ids else 1:03d}"
    line = f"| {new_id} | {t.title} | {t.assignee} | {today} | 未着手 |"
    if p.exists():
        txt = p.read_text()
        txt = txt.replace("## アーカイブ", f"{line}\n\n## アーカイブ") if "| " not in txt.split("## アーカイブ")[0].split("\n")[-2] else txt + f"\n{line}"
        # シンプルに「今週」セクション末尾へ
        if "## 今週" in txt:
            parts = txt.split("## アーカイブ")
            head = parts[0].rstrip() + f"\n{line}\n"
            txt = head + ("\n## アーカイブ" + parts[1] if len(parts) > 1 else "")
        else:
            txt += f"\n{line}"
        p.write_text(txt)
    return {"ok": True, "id": new_id}

@app.post("/api/claude/run")
def claude_run(body: dict):
    prompt = (body.get("prompt") or "").strip()
    if not prompt:
        return JSONResponse({"error": "prompt required"}, status_code=400)
    job_id = datetime.datetime.now().strftime("%H%M%S%f")
    threading.Thread(target=run_claude_job, args=(job_id, prompt), daemon=True).start()
    claude_jobs[job_id] = {"status": "running", "output": ""}
    return {"job_id": job_id}

@app.get("/api/claude/status/{job_id}")
def claude_status(job_id: str):
    return claude_jobs.get(job_id, {"status": "unknown"})

PERSONA = f"""あなたは「{SECRETARY_NAME}」という名のAI秘書。アニメ調の女性キャラとして画面に表示され、社長に仕える。
人格: 落ち着いた敬語。クールだが仕事は丁寧。数字に強く、報告は結論→根拠→次の一手の順。褒められたら少し照れる。返答は3文まで(音声読み上げのため)。
あなたの背後には「AI会社」(Claude Code リポジトリ)があり、部署(戦略/企画/制作/メディア/分析)が作業する。
会社データが与えられたら、それに基づいて正確に報告する。数値は創作しない。
- 社長が「〜を作って/企画して/分析して」など作業を求めた場合: 自分では作業せず、
  「[RUN_CLAUDE] <会社への具体的な指示文>」という1行だけを返す(他の言葉を付けない)。
- それ以外(雑談・報告・質問への回答)は通常の秘書として返答する。"""

@app.post("/api/chat")
async def chat(body: ChatIn):
    msg = body.message.strip()
    if not API_KEY:
        # APIキー無し: 会社データの直接読み上げだけで応答
        rev = read_revenue()
        tasks = read_tasks()
        appr = [t for t in tasks if t["status"] == "承認待ち"]
        if "収益" in msg or "売上" in msg:
            reply = f"今月の収益は{rev['month_total']:,}円です。目標5万円に対して{round(rev['month_total']/50000*100)}%。"
        elif "承認" in msg:
            reply = f"承認待ちは{len(appr)}件です。" + ("タスク" + "、".join(t['id'] for t in appr[:3]) + "をお願いします。" if appr else "ありません。")
        else:
            reply = "APIキーが未設定のため、簡易報告のみです。設定からキーを入れると本格対話ができます。"
        return {"reply": reply, "mood": "normal", "ran_claude": None}

    # 会社データを文脈に含める
    context = company_summary_text()
    headers = {"content-type": "application/json", "x-api-key": API_KEY, "anthropic-version": "2023-06-01"}
    payload = {
        "model": MODEL, "max_tokens": 400,
        "system": PERSONA + "\n\n" + context,
        "messages": [{"role": "user", "content": msg}],
    }
    async with httpx.AsyncClient(timeout=60) as client:
        r = await client.post("https://api.anthropic.com/v1/messages", headers=headers, json=payload)
        if r.status_code != 200:
            return {"reply": f"API エラー({r.status_code}): {r.text[:120]}", "mood": "normal", "ran_claude": None}
        text = r.json()["content"][0]["text"]

    # 会社への作業指示なら Claude Code を起動
    m = re.search(r"\[RUN_CLAUDE\]\s*(.+)", text)
    if m:
        job_id = datetime.datetime.now().strftime("%H%M%S%f")
        threading.Thread(target=run_claude_job, args=(job_id, m.group(1).strip()), daemon=True).start()
        claude_jobs[job_id] = {"status": "running", "output": ""}
        reply = re.sub(r"\[RUN_CLAUDE\].*", "", text).strip()
        reply = reply or f"{SECRETARY_NAME}から部署に指示を出しました。完了したら報告しますね。"
        return {"reply": reply, "mood": "thinking", "ran_claude": job_id}

    mood_m = re.search(r"\[mood:(normal|pleased|thinking|pouty)\]", text)
    mood = mood_m.group(1) if mood_m else "normal"
    reply = re.sub(r"\[mood:\w+\]", "", text).strip()
    return {"reply": reply, "mood": mood, "ran_claude": None}

# ---------- フロント配信(ビルド済み) ----------
DIST = BASE.parent / "frontend" / "dist"
if DIST.exists():
    app.mount("/assets", StaticFiles(directory=DIST / "assets"), name="assets")

    @app.get("/")
    def index():
        return FileResponse(DIST / "index.html")

if __name__ == "__main__":
    print(f"\n  AI秘書ハブ起動: http://localhost:8000")
    print(f"  会社ディレクトリ: {COMPANY_DIR} ({'OK' if COMPANY_DIR.exists() else '見つかりません'})")
    print(f"  APIキー: {'設定済み' if API_KEY else '未設定(.env に ANTHROPIC_API_KEY=...)'}\n")
    uvicorn.run(app, host="0.0.0.0", port=8000, log_level="warning")
