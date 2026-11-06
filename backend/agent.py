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

from pathlib import Path

import anthropic

import company
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
    inp = (getattr(u, "input_tokens", 0) or 0) + (getattr(u, "cache_read_input_tokens", 0) or 0) \
        + (getattr(u, "cache_creation_input_tokens", 0) or 0)
    out = getattr(u, "output_tokens", 0) or 0
    pin, pout = PRICES.get(MODEL, PRICES["claude-opus-5-5"])
    month = datetime.date.today().strftime("%Y-%m")
    data = _load_json(USAGE_FILE, {})
    m = data.setdefault(month, {"input": 0, "output": 0, "usd": 0.0, "calls": 0})
    m["input"] += inp
    m["output"] += out
    m["usd"] = round(m["usd"] + inp / 1e6 * pin + out / 1e6 * pout, 4)
    m["calls"] += 1
    _save_json(USAGE_FILE, data)


def usage_summary() -> dict:
    month = datetime.date.today().strftime("%Y-%m")
    m = _load_json(USAGE_FILE, {}).get(month, {"input": 0, "output": 0, "usd": 0.0, "calls": 0})
    return {**m, "month": month, "jpy": round(m["usd"] * USD_JPY), "rate": USD_JPY}

# ---------- 部署への作業依頼(Claude Code) ----------
# 作るAIとチェックするAI: この部署の成果物は、別の部署(メディア部)が見直してから承認待ちに回す
CHECKED_DEPARTMENTS = ("企画", "制作")
CHECK_STEP = (
    "作業が終わったら、別のサブエージェント「media」(チェック役)に、成果物を就業規則・playbooks・learned_rules.md と照合させること"
    "(NG事項、PR表記、AI製の明示、文字数、出典、入れてはいけない情報の明示)。"
    "指摘はすべて直し、指摘内容は data/corrections.md の表に「| 日付 | 対象 | 指摘 | チェックAI |」の形で1行ずつ追記する。"
    "投稿セットの場合は確認結果を content/drafts/YYYY-WW/_check.md に残し、直し終えた投稿の状態を「承認待ち」にする。"
)

SUBAGENTS = {"戦略": "strategy", "企画": "planning", "制作": "production", "メディア": "media", "分析": "analysis"}
jobs: Dict[str, dict] = _load_json(JOBS_FILE, {})
for _j in jobs.values():  # 前回の起動中に終わらなかった作業
    if _j.get("status") == "running":
        _j.update(status="error", output=(_j.get("output") or "") + "\n(秘書ハブの再起動で中断しました)")


def _save_jobs():
    keep = dict(sorted(jobs.items(), key=lambda kv: kv[1]["started"])[-50:])
    _save_json(JOBS_FILE, keep)


def _run_job(job_id: str):
    job = jobs[job_id]
    agent_name = SUBAGENTS.get(job["department"], "")
    prompt = (
        (f"サブエージェント「{agent_name}」({job['department']}部、定義は .claude/agents/{agent_name}.md)に、次の作業をさせてください。\n"
         if agent_name else f"{job['department']}部として次の作業をしてください。\n")
        + f"作業: {job['instruction']}\n"
        "CLAUDE.md(就業規則)と playbooks/learned_rules.md(過去の失敗から学んだルール)に従い、成果物は所定のフォルダに保存すること。"
        "投稿セットは playbooks/post_format.md の形式。外部への投稿・申請はしない。承認済みにはしない(承認は社長だけ)。"
        + (CHECK_STEP if job["department"] in CHECKED_DEPARTMENTS else "")
        + "最後に、何をしてどのファイルに保存したかを日本語で3行以内でまとめること。"
    )
    try:
        if not shutil.which("claude"):
            raise RuntimeError("Claude Code CLI が見つかりません。ターミナルで `npm install -g @anthropic-ai/claude-code` → `claude` で一度ログインしてください。")
        proc = subprocess.run(["claude", "-p", prompt, "--permission-mode", "acceptEdits"],
                              cwd=str(company.COMPANY_DIR), capture_output=True, text=True,
                              encoding="utf-8", errors="replace", timeout=1800)
        out = (proc.stdout or "").strip() or (proc.stderr or "").strip()
        job.update(status="done" if proc.returncode == 0 else "error", output=out[-6000:])
    except Exception as e:
        job.update(status="error", output=str(e))
    job["finished"] = datetime.datetime.now().isoformat(timespec="seconds")
    _save_jobs()
    if job.get("task_key"):
        ok = job["status"] == "done"
        mark = "作業完了" if ok else "作業エラー"
        try:
            async def finish():
                auto = scheduler.plan_for_task(job["task_key"]) is not None
                # 逆算プランの工程は、終わったら完了にして次の工程へ(秘書の完了判定)
                await company.update_task(job["task_key"], status="完了" if (ok and auto) else None,
                                          append_note=f"{mark}({job['finished'][5:16]}・秘書ハブの作業タブに結果)")
                if ok and auto:
                    await scheduler.advance()
            asyncio.run(finish())
        except Exception:
            pass


def start_job(department: str, instruction: str, title: str, task_key: Optional[str] = None) -> dict:
    job_id = datetime.datetime.now().strftime("%m%d%H%M%S%f")
    jobs[job_id] = {"id": job_id, "title": title, "department": department, "instruction": instruction,
                    "status": "running", "output": "", "task_key": task_key,
                    "started": datetime.datetime.now().isoformat(timespec="seconds"), "finished": None}
    _save_jobs()
    threading.Thread(target=_run_job, args=(job_id,), daemon=True).start()
    return jobs[job_id]


def job_list() -> List[dict]:
    return sorted(jobs.values(), key=lambda j: j["started"], reverse=True)


# ---------- 道具の定義 ----------
EDITABLE = ["未着手", "進行中", "承認待ち", "完了"]
DEPARTMENTS = ["戦略", "企画", "制作", "メディア", "分析"]
PANELS = ["home", "content", "tasks", "docs", "jobs", "chat"]


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
    _tool("show_panel", "画面右側の表示を切り替える。home=ホーム, content=投稿セット, tasks=タスク, docs=資料, jobs=部署の作業, chat=会話履歴",
          {"panel": {"type": "string", "enum": PANELS}}, ["panel"]),
    _tool("delegate_work", "部署(Claude Code)に作業を依頼する。企画・リサーチ・原稿作成・分析など、時間のかかる作業に使う。"
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
           "source": {"type": "string", "enum": company.REVENUE_SOURCES, "description": "note_sales=note販売, amazon_affiliate=Amazonアフィ, other=その他"},
           "date": {"type": "string", "description": "YYYY-MM-DD。省略時は今日"},
           "memo": {"type": "string"}}, ["amount", "source"]),
    _tool("record_followers", "媒体のフォロワー数を記録する(data/followers.csv)。",
          {"platform": {"type": "string", "enum": company.PLATFORMS},
           "followers": {"type": "integer"},
           "date": {"type": "string", "description": "YYYY-MM-DD。省略時は今日"}}, ["platform", "followers"]),
    _tool("register_account", "開設したSNSアカウントのURLを台帳(data/accounts.md と Notion)に記録する。URLだけを扱う。",
          {"platform": {"type": "string", "enum": company.PLATFORMS},
           "url": {"type": "string", "description": "https:// から始まるプロフィールURL"},
           "opened": {"type": "string", "description": "開設日 YYYY-MM-DD。省略時は今日"}}, ["platform", "url"]),
    _tool("create_plan", "期限から逆算して、工程ごとのタスクを日付つきで起票する(逆算スケジュール)。"
          "部署の工程は、前の工程が終わると秘書が自動で部署に依頼する。投稿セットの基本形: 企画(企画部)→台本・原稿(制作部)"
          "→素材・仕上げ(制作部、メディア部のチェック込み)→社長の承認(社長)→投稿(社長)。各工程の期限は最終期限から逆算して決める。",
          {"title": {"type": "string", "description": "プラン名(例: 2026-47 投稿セット)"},
           "deadline": {"type": "string", "description": "最終期限 YYYY-MM-DD"},
           "steps": {"type": "array", "description": "工程(順番どおり)", "items": {"type": "object", "properties": {
               "title": {"type": "string"},
               "assignee": {"type": "string", "enum": company.ASSIGNEES},
               "due": {"type": "string", "description": "YYYY-MM-DD"},
               "instruction": {"type": "string", "description": "部署への具体的な指示(社長の工程なら社長がすること)"}},
               "required": ["title", "assignee", "due", "instruction"], "additionalProperties": False}}},
          ["title", "deadline", "steps"]),
    _tool("run_check_now", "定時チェック(今日やること・遅れ・自動依頼・社長へのお願い)を今すぐ行う。", {}, []),
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
        r = company.record_followers(args["platform"], args["followers"], args.get("date"))
        actions.append({"type": "refresh"})
        return f"記録しました: {r['date']} {company.PLATFORM_JA[r['platform']]} {r['followers']}人"

    if name == "register_account":
        r = await company.register_account(args["platform"], args["url"], args.get("opened"))
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

    if name == "run_check_now":
        r = await scheduler.run_check()
        actions.append({"type": "refresh"})
        return f"定時チェックをしました: {r['notification']['text']}"

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

あなたの背後には「AI会社」がある(社長以外は全員AI。部署: 戦略/企画/制作/メディア/分析)。
社長はこの画面だけで仕事を完結させたい。頼まれたことは道具を使って実際に進め、「やりました」と結果で答える。
- タスクの確認・起票・状態や期限の変更、Notion の資料を開く・要約する、画面の切り替え、部署への作業依頼、
  投稿セットの確認と承認カード、収益・フォロワー数の記録、開設アカウントの登録、週次レポートの作成ができる。
- 社長が売上やフォロワー数を口にしたら記録してよいか迷わず記録し、記録した値を復唱する。
- アカウント登録で扱うのは URL だけ。パスワード・メールアドレス・認証コードを言われても記録せず、言わないようお願いする。
- 資料やタスクの話題になったら、関係する画面(show_panel / open_document)も合わせて出す。
- 時間のかかる作業(企画・リサーチ・原稿・分析)は delegate_work で部署に依頼する。自分で長文を書かない。
- 期限のある仕事(例: 来週金曜に投稿)を頼まれたら、create_plan で期限から逆算した工程を起票する。部署の工程は秘書が自動で進める。
  遅れそうなものは、聞かれなくても「今日から動かないと間に合いません」と先回りして伝える。
- 社長が差し戻した内容は修正ログに残る。「これをルールにして」と言われたら propose_rule で案を出す(確定は社長)。
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


def context_text(data: dict) -> str:
    return "\n".join([
        company.summary_text(data), content.summary_text(), company.metrics_text(), company.accounts_text(),
        corrections.summary_text(),
        f"- 定時チェック: {'オン' if scheduler.settings()['auto'] else 'オフ'}({'・'.join(scheduler.settings()['times'])})",
        f"- Notion: {'接続済み' if notion.configured() else '未接続(タスクは控えファイルで管理)'}",
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
_briefing_cache: dict = {}


async def briefing() -> dict:
    """秘書ハブを開いたときの報告(3行+本日のおすすめ)。同じ内容なら1時間は使い回す"""
    data = await company.summary()
    ctx = context_text(data)
    key = (datetime.date.today().isoformat(), hash(ctx))
    hit = _briefing_cache.get(key)
    if hit and (datetime.datetime.now() - hit["at"]).seconds < 3600:
        return hit["result"]
    text = await _one_shot(
        persona(),
        f"{ctx}\n\n社長が秘書ハブを開きました。起動時の報告をしてください。"
        "挨拶を1文、続けて①収益 ②タスクと承認待ち ③投稿・アカウントの状況を1文ずつ、最後に「本日のおすすめ」を1つ。"
        "合計5文以内の話し言葉で。道具は使えません。", 1500)
    body, mood = split_mood(text)
    result = {"text": body, "mood": mood}
    _briefing_cache.clear()
    _briefing_cache[key] = {"at": datetime.datetime.now(), "result": result}
    return result


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
            old = await notion.find_child_page(result["title"])
            if old:
                await notion.archive_page(old)
            page = await notion.create_page(result["title"], notion.markdown_to_blocks(md), "📊")
            result["notion_id"] = page["id"]
        except Exception as e:
            result["notion_error"] = str(e)
    return result


def split_mood(text: str):
    m = re.search(r"\[mood:\s*(normal|pleased|thinking|pouty)\s*\]", text)
    return re.sub(r"\[mood:[^\]]*\]", "", text).strip(), (m.group(1) if m else "normal")


async def chat(message: str, history: List[dict]) -> dict:
    actions: List[dict] = []
    data = await company.summary()
    system = persona() + "\n\n" + context_text(data)
    messages = _messages(history, message)
    reply = ""
    try:
        for _ in range(8):
            resp = await client.messages.create(model=MODEL, max_tokens=16000, system=system, tools=TOOLS,
                                                 messages=messages, **_request_options())
            add_usage(resp)
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
