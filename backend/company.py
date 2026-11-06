"""会社データ(タスク・収益・資料)の読み書き。

タスクの正は Notion(NOTION_TOKEN があるとき)。無いときは ai-company/data/tasks.md(控え)を使う。
収益は ai-company/data/revenue.csv。
"""
import csv
import datetime
import os
import re
from pathlib import Path
from typing import List, Optional

import notion

BASE = Path(__file__).resolve().parent
COMPANY_DIR = Path(os.getenv("AI_COMPANY_DIR", "").strip() or BASE.parent.parent / "ai-company").expanduser()
TASKS_MD = COMPANY_DIR / "data" / "tasks.md"
REVENUE_CSV = COMPANY_DIR / "data" / "revenue.csv"
GOAL = 50000

STATUSES = notion.STATUSES
ASSIGNEES = notion.ASSIGNEES
ROW = re.compile(r"^\|\s*(T-\d+)\s*\|\s*(.+?)\s*\|\s*(.+?)\s*\|\s*(.+?)\s*\|\s*(" + "|".join(STATUSES) + r")\s*\|")


def task_source() -> str:
    return "notion" if notion.configured() else "file"


# ---------- 収益 ----------
def read_revenue() -> dict:
    rows = []
    if REVENUE_CSV.exists():
        with REVENUE_CSV.open() as f:
            for r in csv.DictReader(f):
                try:
                    rows.append({"date": r.get("date", ""), "source": r.get("source", ""),
                                 "amount": int(float(r.get("amount", 0) or 0)), "memo": r.get("memo", "")})
                except ValueError:
                    pass
    today = datetime.date.today()
    month = today.strftime("%Y-%m")
    m_total = sum(r["amount"] for r in rows if r["date"].startswith(month))
    return {"month": month, "month_total": m_total, "goal": GOAL,
            "progress": round(m_total / GOAL * 100), "all_total": sum(r["amount"] for r in rows),
            "today_total": sum(r["amount"] for r in rows if r["date"] == today.isoformat()),
            "rows": rows[-20:]}


# ---------- タスク(控えファイル) ----------
def _file_tasks() -> List[dict]:
    if not TASKS_MD.exists():
        return []
    out = []
    for line in TASKS_MD.read_text().splitlines():
        m = ROW.match(line)
        if m:
            out.append({"key": m.group(1), "id": m.group(1), "title": m.group(2), "assignee": m.group(3),
                        "due": m.group(4), "status": m.group(5), "note": "", "link": "", "url": "", "week": None})
    return out


def _file_update(key: str, status: Optional[str], append_note: Optional[str]) -> dict:
    lines = TASKS_MD.read_text().splitlines()
    for i, line in enumerate(lines):
        m = ROW.match(line)
        if m and m.group(1) == key:
            title = m.group(2) + (f"({append_note})" if append_note else "")
            lines[i] = f"| {key} | {title} | {m.group(3)} | {m.group(4)} | {status or m.group(5)} |"
            TASKS_MD.write_text("\n".join(lines) + "\n")
            return next(t for t in _file_tasks() if t["key"] == key)
    raise KeyError(key)


def _file_create(title: str, assignee: str, due: Optional[str]) -> dict:
    text = TASKS_MD.read_text() if TASKS_MD.exists() else "| ID | タスク | 担当 | 期限 | 状態 |\n|---|---|---|---|---|\n"
    nums = [int(n) for n in re.findall(r"T-(\d+)", text)]
    new_id = f"T-{(max(nums) + 1) if nums else 1:03d}"
    row = f"| {new_id} | {title} | {assignee} | {due or datetime.date.today().isoformat()} | 未着手 |"
    lines = text.splitlines()
    last = max((i for i, l in enumerate(lines) if ROW.match(l)), default=None)
    if last is None:
        lines.append(row)
    else:
        lines.insert(last + 1, row)
    TASKS_MD.write_text("\n".join(lines) + "\n")
    return next(t for t in _file_tasks() if t["id"] == new_id)


# ---------- タスク(共通の入口) ----------
async def list_tasks() -> List[dict]:
    if notion.configured():
        return await notion.list_tasks()
    return _file_tasks()


async def find_task(ref: str) -> dict:
    """「T-9」「T-009」「9」やページIDからタスクを探す"""
    ref = (ref or "").strip()
    tasks = await list_tasks()
    pid = notion.page_id_from(ref)
    num = re.search(r"\d+", ref) if not pid else None
    for t in tasks:
        if t["key"] == ref or (pid and t["key"] == pid):
            return t
        tm = re.search(r"\d+", t["id"] or "")
        if num and tm and int(tm.group()) == int(num.group()):
            return t
    raise KeyError(f"タスク {ref} が見つかりません")


async def update_task(key: str, status: Optional[str] = None, note: Optional[str] = None,
                      append_note: Optional[str] = None) -> dict:
    if status and status not in STATUSES:
        raise ValueError(f"ステータスは {' / '.join(STATUSES)} のどれかです")
    if notion.configured():
        return await notion.update_task(key, status=status, note=note, append_note=append_note)
    return _file_update(key, status, append_note or note)


async def create_task(title: str, assignee: str = "秘書", due: Optional[str] = None,
                      note: str = "", link: str = "") -> dict:
    assignee = assignee if assignee in ASSIGNEES else "秘書"
    if notion.configured():
        return await notion.create_task(title, assignee, due, note, link)
    return _file_create(title, assignee, due)


async def summary() -> dict:
    tasks, error = [], None
    try:
        tasks = await list_tasks()
    except Exception as e:  # Notion に繋がらないときは控えで続ける
        error = str(e)
        tasks = _file_tasks()
    return {"revenue": read_revenue(), "tasks": tasks, "task_source": task_source(), "task_error": error,
            "company_found": COMPANY_DIR.exists()}


def summary_text(data: dict) -> str:
    rev, tasks = data["revenue"], data["tasks"]
    open_t = [t for t in tasks if t["status"] != "完了"]
    approval = [t for t in tasks if t["status"] == "承認待ち"]
    lines = [
        f"【会社データ(自動取得 {datetime.date.today().isoformat()})】",
        f"- 今月の収益: {rev['month_total']:,}円(目標{GOAL:,}円・達成率 {rev['progress']}%)",
        f"- タスク({'Notion' if data['task_source'] == 'notion' else '控えファイル'}): "
        f"全{len(tasks)}件/未完了{len(open_t)}件/承認待ち{len(approval)}件",
    ]
    for t in open_t[:12]:
        lines.append(f"  - {t['id']} {t['title'][:60]}(担当:{t['assignee']}・状態:{t['status']}・期限:{t['due'] or '-'})")
    return "\n".join(lines)
