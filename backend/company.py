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


def _file_update(key: str, status: Optional[str], append_note: Optional[str], due: Optional[str] = None) -> dict:
    lines = TASKS_MD.read_text().splitlines()
    for i, line in enumerate(lines):
        m = ROW.match(line)
        if m and m.group(1) == key:
            title = m.group(2) + (f"({append_note})" if append_note else "")
            new_due = m.group(4) if due is None else (due or "-")
            lines[i] = f"| {key} | {title} | {m.group(3)} | {new_due} | {status or m.group(5)} |"
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
                      append_note: Optional[str] = None, due: Optional[str] = None, link: Optional[str] = None) -> dict:
    """due: None=変更しない / "" =期限を消す / "YYYY-MM-DD"=その日に変える。link=資料(Notion の作業ログなど)"""
    if status and status not in STATUSES:
        raise ValueError(f"ステータスは {' / '.join(STATUSES)} のどれかです")
    if due is not None:
        try:
            due = notion.valid_date(due)
        except ValueError:
            raise ValueError("期限は YYYY-MM-DD の形で指定してください")
    if notion.configured():
        return await notion.update_task(key, status=status, note=note, append_note=append_note, due=due, link=link)
    return _file_update(key, status, append_note or note, due)


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
        f"【会社データ(自動取得 今日は {datetime.date.today().isoformat()}({'月火水木金土日'[datetime.date.today().weekday()]}))】",
        f"- 今月の収益: {rev['month_total']:,}円(目標{GOAL:,}円・達成率 {rev['progress']}%)",
        f"- タスク({'Notion' if data['task_source'] == 'notion' else '控えファイル'}): "
        f"全{len(tasks)}件/未完了{len(open_t)}件/承認待ち{len(approval)}件",
    ]
    for t in open_t[:12]:
        lines.append(f"  - {t['id']} {t['title'][:60]}(担当:{t['assignee']}・状態:{t['status']}・期限:{t['due'] or '-'})")
    return "\n".join(lines)


# ---------- 数字の記録(収益・フォロワー) ----------
FOLLOWERS_CSV = COMPANY_DIR / "data" / "followers.csv"
ACCOUNTS_MD = COMPANY_DIR / "data" / "accounts.md"
PLATFORMS = ["instagram", "x", "threads", "note"]
PLATFORM_JA = {"instagram": "Instagram", "x": "X", "threads": "Threads", "note": "note"}
REVENUE_SOURCES = ["note_sales", "amazon_affiliate", "other"]


def _append_csv(path: Path, header: List[str], row: List[str]):
    path.parent.mkdir(parents=True, exist_ok=True)
    new = not path.exists() or not path.read_text().strip()
    with path.open("a", newline="") as f:
        w = csv.writer(f)
        if new:
            w.writerow(header)
        w.writerow(row)


async def record_revenue(amount: int, source: str = "other", date: Optional[str] = None, memo: str = "") -> dict:
    if source not in REVENUE_SOURCES:
        source = "other"
    date = notion.valid_date(date or "") or datetime.date.today().isoformat()
    amount = int(amount)
    _append_csv(REVENUE_CSV, ["date", "source", "amount", "memo"], [date, source, str(amount), memo])
    synced = None
    if notion.configured():
        try:
            await notion.add_revenue(date, source, amount, memo)
            synced = True
        except Exception as e:
            synced = str(e)
    return {"date": date, "source": source, "amount": amount, "memo": memo, "notion": synced}


def record_followers(platform: str, followers: int, date: Optional[str] = None) -> dict:
    if platform not in PLATFORMS:
        raise ValueError(f"媒体は {' / '.join(PLATFORMS)} のどれかです")
    date = notion.valid_date(date or "") or datetime.date.today().isoformat()
    _append_csv(FOLLOWERS_CSV, ["date", "platform", "followers"], [date, platform, str(int(followers))])
    return {"date": date, "platform": platform, "followers": int(followers)}


def read_followers() -> dict:
    """媒体ごとの推移 {platform: [{date, followers}]}(同じ日は最後の値)"""
    series: dict = {p: {} for p in PLATFORMS}
    if FOLLOWERS_CSV.exists():
        with FOLLOWERS_CSV.open() as f:
            for r in csv.DictReader(f):
                try:
                    series.setdefault(r["platform"], {})[r["date"]] = int(float(r["followers"]))
                except (KeyError, ValueError):
                    pass
    return {p: [{"date": d, "followers": v} for d, v in sorted(s.items())] for p, s in series.items() if s}


def revenue_daily() -> List[dict]:
    """今月の日別収益と累計"""
    rev = read_revenue()
    month = rev["month"]
    by_day: dict = {}
    if REVENUE_CSV.exists():
        with REVENUE_CSV.open() as f:
            for r in csv.DictReader(f):
                if r.get("date", "").startswith(month):
                    try:
                        by_day[r["date"]] = by_day.get(r["date"], 0) + int(float(r.get("amount") or 0))
                    except ValueError:
                        pass
    total, out = 0, []
    for d in sorted(by_day):
        total += by_day[d]
        out.append({"date": d, "amount": by_day[d], "cumulative": total})
    return out


def metrics() -> dict:
    return {"followers": read_followers(), "revenue_daily": revenue_daily()}


def metrics_text() -> str:
    f = read_followers()
    if not f:
        return "- フォロワー: 記録なし"
    return "- フォロワー(最新): " + "、".join(
        f"{PLATFORM_JA[p]} {s[-1]['followers']}人({s[-1]['date']})" for p, s in f.items() if p in PLATFORM_JA)


# ---------- アカウント台帳 ----------
ACCOUNT_HOSTS = {"instagram": ("instagram.com",), "x": ("x.com", "twitter.com"),
                 "threads": ("threads.net", "threads.com"), "note": ("note.com",)}


async def register_account(platform: str, url: str, opened: Optional[str] = None) -> dict:
    """data/accounts.md の表に URL と開設日を書き、Notion の「アカウント台帳」ページにも記録する"""
    if platform not in PLATFORMS:
        raise ValueError(f"媒体は {' / '.join(PLATFORMS)} のどれかです")
    url = url.strip()
    if not re.match(r"^https://", url) or not any(h in url.split("/")[2] for h in ACCOUNT_HOSTS[platform]):
        raise ValueError(f"{PLATFORM_JA[platform]} の URL(https://{ACCOUNT_HOSTS[platform][0]}/...)を指定してください")
    opened = notion.valid_date(opened or "") or datetime.date.today().isoformat()
    name = PLATFORM_JA[platform]
    if ACCOUNTS_MD.exists():
        lines = ACCOUNTS_MD.read_text().splitlines()
        for i, line in enumerate(lines):
            cells = [c.strip() for c in line.strip().strip("|").split("|")]
            if line.startswith("|") and cells and cells[0] == name:
                cells[1], cells[2] = url, opened
                lines[i] = "| " + " | ".join(cells) + " |"
                break
        ACCOUNTS_MD.write_text("\n".join(lines) + "\n")
    synced = None
    if notion.configured():
        try:
            data_folder = await notion.folder("data")
            pid = await notion.find_child_page("アカウント台帳", data_folder) or await notion.find_child_page("アカウント台帳")
            item = [{"type": "bulleted_list_item", "bulleted_list_item": {"rich_text": [
                {"type": "text", "text": {"content": f"{name}: "}},
                {"type": "text", "text": {"content": url, "link": {"url": url}}},
                {"type": "text", "text": {"content": f"(開設 {opened})"}}]}}]
            if pid:
                await notion.append_blocks(pid, item)
            else:
                await notion.create_page("アカウント台帳", [{"type": "callout", "callout": {"rich_text": [{"type": "text", "text": {
                    "content": "開設したアカウントの URL。パスワード・認証情報は書かない"}}], "icon": {"type": "emoji", "emoji": "🔒"}}}] + item, "🪪", data_folder)
            synced = True
        except Exception as e:
            synced = str(e)
    return {"platform": platform, "url": url, "opened": opened, "notion": synced}


def accounts_text() -> str:
    if not ACCOUNTS_MD.exists():
        return ""
    got = []
    for line in ACCOUNTS_MD.read_text().splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if line.startswith("|") and len(cells) > 2 and cells[1].startswith("http"):
            got.append(f"{cells[0]} {cells[1]}")
    return "- 開設済みアカウント: " + ("、".join(got) if got else "まだなし")
