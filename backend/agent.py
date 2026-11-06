"""秘書の頭脳: Claude(Anthropic API)に「道具」を持たせ、話しかけるだけで仕事が進むようにする。

道具: タスクの確認・起票・更新、Notion の資料を開く、画面の切り替え、部署(Claude Code)への作業依頼。
承認(承認待ち → 承認済み)と差し戻しだけは社長の操作で行う(就業規則)。秘書は承認カードを出すところまで。
"""
import asyncio
import datetime
import json
import os
import re
import shutil
import subprocess
import threading
from typing import Dict, List, Optional

import anthropic

import company
import notion

API_KEY = os.getenv("ANTHROPIC_API_KEY", "").strip()
MODEL = os.getenv("ANTHROPIC_MODEL", "").strip() or "claude-opus-5-5"
EFFORT = os.getenv("ANTHROPIC_EFFORT", "low").strip()  # 会話は速さ優先
SECRETARY_NAME = os.getenv("SECRETARY_NAME", "セナ")

# 新しい世代のモデルだけが受け付ける設定(古いモデル名が .env に残っていても動くように分ける)
EFFORT_MODELS = ("claude-opus-5", "claude-fable-5", "claude-sonnet-5", "claude-haiku-5", "claude-mythos-5")
FALLBACK_MODELS = ("claude-opus-5-5", "claude-opus-5", "claude-fable-5-1", "claude-sonnet-5-5")

client = anthropic.AsyncAnthropic(api_key=API_KEY) if API_KEY else None

# ---------- 部署への作業依頼(Claude Code) ----------
jobs: Dict[str, dict] = {}


def _run_job(job_id: str):
    job = jobs[job_id]
    prompt = (
        f"{job['department']}部として次の作業をしてください: {job['instruction']}\n"
        "CLAUDE.md(就業規則)に従い、成果物は所定のフォルダに保存すること。"
        "外部への投稿・申請はしない。最後に、何をしてどのファイルに保存したかを日本語で3行以内でまとめること。"
    )
    try:
        if not shutil.which("claude"):
            raise RuntimeError("Claude Code CLI が見つかりません。ターミナルで `npm install -g @anthropic-ai/claude-code` → `claude` で一度ログインしてください。")
        proc = subprocess.run(["claude", "-p", prompt, "--permission-mode", "acceptEdits"],
                              cwd=str(company.COMPANY_DIR), capture_output=True, text=True, timeout=1800)
        out = (proc.stdout or "").strip() or (proc.stderr or "").strip()
        job.update(status="done" if proc.returncode == 0 else "error", output=out[-6000:])
    except Exception as e:
        job.update(status="error", output=str(e))
    job["finished"] = datetime.datetime.now().isoformat(timespec="seconds")
    if job.get("task_key"):
        mark = "作業完了" if job["status"] == "done" else "作業エラー"
        try:
            asyncio.run(company.update_task(job["task_key"],
                                            append_note=f"{mark}({job['finished'][5:16]}・秘書ハブの作業タブに結果)"))
        except Exception:
            pass


def start_job(department: str, instruction: str, title: str, task_key: Optional[str] = None) -> dict:
    job_id = datetime.datetime.now().strftime("%m%d%H%M%S%f")
    jobs[job_id] = {"id": job_id, "title": title, "department": department, "instruction": instruction,
                    "status": "running", "output": "", "task_key": task_key,
                    "started": datetime.datetime.now().isoformat(timespec="seconds"), "finished": None}
    threading.Thread(target=_run_job, args=(job_id,), daemon=True).start()
    return jobs[job_id]


def job_list() -> List[dict]:
    return sorted(jobs.values(), key=lambda j: j["started"], reverse=True)


# ---------- 道具の定義 ----------
EDITABLE = ["未着手", "進行中", "承認待ち", "完了"]
DEPARTMENTS = ["戦略", "企画", "制作", "メディア", "分析"]
PANELS = ["home", "tasks", "docs", "jobs", "chat"]


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
    _tool("show_panel", "画面右側の表示を切り替える。home=ホーム, tasks=タスク, docs=資料, jobs=部署の作業, chat=会話履歴",
          {"panel": {"type": "string", "enum": PANELS}}, ["panel"]),
    _tool("delegate_work", "部署(Claude Code)に作業を依頼する。企画・リサーチ・原稿作成・分析など、時間のかかる作業に使う。"
          "依頼と同時にタスクを起票(進行中)し、完了すると画面に通知される。",
          {"department": {"type": "string", "enum": DEPARTMENTS},
           "title": {"type": "string", "description": "タスク名(短く)"},
           "instruction": {"type": "string", "description": "部署への具体的な指示文(目的・成果物・保存先)"}},
          ["department", "title", "instruction"]),
    _tool("get_jobs", "部署に依頼した作業の状況(実行中・完了・エラーと結果)を取得する。", {}, []),
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
        return json.dumps([{"title": d["title"], "id": d["id"]} for d in docs[:40]], ensure_ascii=False)

    if name == "open_document":
        if not notion.configured():
            return "Notion が未接続です(backend/.env に NOTION_TOKEN が必要)。"
        doc = await _find_doc(args["query"])
        if not doc:
            return f"「{args['query']}」に当たる資料が見つかりません。list_documents で一覧を確認してください。"
        page = await notion.read_page(doc["id"])
        actions.append({"type": "open_doc", "id": page["id"], "title": page["title"]})
        text = notion.blocks_to_text(page["blocks"])
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
        return f"{args['department']}部に依頼しました(作業ID {job['id']})。完了すると画面に通知されます。"

    if name == "get_jobs":
        return json.dumps([{k: j[k] for k in ("title", "department", "status", "started", "finished")}
                           | {"result": (j["output"] or "")[-600:]} for j in job_list()[:10]], ensure_ascii=False)

    return f"エラー: 未知の道具 {name}"


# ---------- 会話 ----------
def persona() -> str:
    return f"""あなたは「{SECRETARY_NAME}」という名のAI秘書。アニメ調の女性キャラとして画面に表示され、音声で社長と話す。
人格: 落ち着いた敬語。クールだが仕事は丁寧。数字に強く、報告は結論→根拠→次の一手の順。褒められたら少し照れる。

あなたの背後には「AI会社」がある(社長以外は全員AI。部署: 戦略/企画/制作/メディア/分析)。
社長はこの画面だけで仕事を完結させたい。頼まれたことは道具を使って実際に進め、「やりました」と結果で答える。
- タスクの確認・起票・状態変更、Notion の資料を開く・要約する、画面の切り替え、部署への作業依頼ができる。
- 資料やタスクの話題になったら、関係する画面(show_panel / open_document)も合わせて出す。
- 時間のかかる作業(企画・リサーチ・原稿・分析)は delegate_work で部署に依頼する。自分で長文を書かない。
- 承認・差し戻しは社長だけが行う(就業規則)。社長に決めてもらうときは ask_approval でカードを出す。
- 外部への投稿・申請・購入・ログインは社長が行う。パスワードや認証コードは扱わない。
- 数値は会社データか道具の結果だけを使い、創作しない。分からないことは分からないと言う。

返答は音声で読み上げるため、短く話し言葉で(基本は2〜3文。資料の要約でも5文まで)。記号の箇条書きや表は使わない。
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


def split_mood(text: str):
    m = re.search(r"\[mood:\s*(normal|pleased|thinking|pouty)\s*\]", text)
    return re.sub(r"\[mood:[^\]]*\]", "", text).strip(), (m.group(1) if m else "normal")


async def chat(message: str, history: List[dict]) -> dict:
    actions: List[dict] = []
    data = await company.summary()
    system = persona() + "\n\n" + company.summary_text(data) + \
        f"\n- Notion: {'接続済み' if notion.configured() else '未接続(タスクは控えファイルで管理)'}"
    messages = _messages(history, message)
    reply = ""
    try:
        for _ in range(8):
            resp = await client.messages.create(model=MODEL, max_tokens=16000, system=system, tools=TOOLS,
                                                 messages=messages, **_request_options())
            if resp.stop_reason == "refusal":
                reply = "申し訳ありません、その件はお答えできません。[mood:normal]"
                break
            uses = [b for b in resp.content if getattr(b, "type", "") == "tool_use"]
            texts = [b.text for b in resp.content if getattr(b, "type", "") == "text"]
            if resp.stop_reason == "pause_turn":
                messages.append({"role": "assistant", "content": resp.content})
                continue
            if not uses:
                reply = "".join(texts)
                break
            messages.append({"role": "assistant", "content": resp.content})
            results = []
            for u in uses:
                try:
                    out = await run_tool(u.name, dict(u.input or {}), actions)
                    results.append({"type": "tool_result", "tool_use_id": u.id, "content": out})
                except Exception as e:
                    results.append({"type": "tool_result", "tool_use_id": u.id, "content": f"エラー: {e}", "is_error": True})
            messages.append({"role": "user", "content": results})
        else:
            reply = "作業が長くなったため、いったんここまでにします。[mood:thinking]"
    except anthropic.AuthenticationError:
        reply = "APIキーが正しくないようです。backend/.env の ANTHROPIC_API_KEY を確認してください。"
    except anthropic.NotFoundError:
        reply = f"モデル {MODEL} が使えません。backend/.env の ANTHROPIC_MODEL を確認してください。"
    except anthropic.RateLimitError:
        reply = "API の利用上限に達しました。少し待ってからもう一度お願いします。"
    except anthropic.APIStatusError as e:
        reply = f"API エラー({e.status_code})です。少し待ってからもう一度お願いします。"
    except anthropic.APIConnectionError:
        reply = "API に接続できません。インターネット接続を確認してください。"
    text, mood = split_mood(reply)
    if any(a["type"] == "job" for a in actions) and mood == "normal":
        mood = "thinking"
    return {"reply": text or "承知しました。", "mood": mood, "actions": actions}
