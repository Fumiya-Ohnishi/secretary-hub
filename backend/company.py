"""会社データ(タスク・収益・資料)の読み書き。

タスクの正は Notion(NOTION_TOKEN があるとき)。無いときは ai-company/data/tasks.md(控え)を使う。
収益は ai-company/data/revenue.csv。
"""
import csv
import json
import datetime
import os
import re
from pathlib import Path
from typing import Dict, List, Optional

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
def read_revenue_all() -> List[dict]:
    """revenue.csv の全部の行(古い順)"""
    rows = []
    if REVENUE_CSV.exists():
        with REVENUE_CSV.open() as f:
            for r in csv.DictReader(f):
                try:
                    src = r.get("source", "")
                    rows.append({"date": r.get("date", ""), "source": src, "source_ja": REVENUE_SOURCE_JA.get(src, src),
                                 "amount": int(float(r.get("amount", 0) or 0)), "memo": r.get("memo", "")})
                except ValueError:
                    pass
    return rows


def read_revenue() -> dict:
    rows = []
    if REVENUE_CSV.exists():
        with REVENUE_CSV.open() as f:
            for r in csv.DictReader(f):
                try:
                    src = r.get("source", "")
                    rows.append({"date": r.get("date", ""), "source": src, "source_ja": REVENUE_SOURCE_JA.get(src, src),
                                 "amount": int(float(r.get("amount", 0) or 0)), "memo": r.get("memo", "")})
                except ValueError:
                    pass
    today = datetime.date.today()
    month = today.strftime("%Y-%m")
    m_total = sum(r["amount"] for r in rows if r["date"].startswith(month))
    by_month: dict = {}
    by_all: dict = {}
    for r in rows:
        by_all[r["source"]] = by_all.get(r["source"], 0) + r["amount"]
        if r["date"].startswith(month):
            by_month[r["source"]] = by_month.get(r["source"], 0) + r["amount"]
    by_source = [{"source": k, "source_ja": REVENUE_SOURCE_JA.get(k, k), "month": by_month.get(k, 0), "all": v}
                 for k, v in sorted(by_all.items(), key=lambda kv: -kv[1])]
    return {"month": month, "month_total": m_total, "goal": GOAL, "by_source": by_source,
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


def _file_create(title: str, assignee: str, due: Optional[str], status: str = "未着手") -> dict:
    text = TASKS_MD.read_text() if TASKS_MD.exists() else "| ID | タスク | 担当 | 期限 | 状態 |\n|---|---|---|---|---|\n"
    nums = [int(n) for n in re.findall(r"T-(\d+)", text)]
    new_id = f"T-{(max(nums) + 1) if nums else 1:03d}"
    row = f"| {new_id} | {title} | {assignee} | {due or datetime.date.today().isoformat()} | {status if status in STATUSES else '未着手'} |"
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
                      note: str = "", link: str = "", status: str = "未着手") -> dict:
    assignee = assignee if assignee in ASSIGNEES else "秘書"
    if notion.configured():
        return await notion.create_task(title, assignee, due, note, link, status)
    full = title + (f"({note[:160]})" if note else "")
    return _file_create(full.replace("|", "/").replace("\n", " "), assignee, due, status)  # 表が崩れないように


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
    asking = [t for t in tasks if t["status"] == "確認待ち"]
    lines = [
        f"【会社データ(自動取得 今日は {datetime.date.today().isoformat()}({'月火水木金土日'[datetime.date.today().weekday()]}))】",
        f"- 今月の収益: {rev['month_total']:,}円(目標{GOAL:,}円・達成率 {rev['progress']}%)",
        f"- タスク({'Notion' if data['task_source'] == 'notion' else '控えファイル'}): "
        f"全{len(tasks)}件/未完了{len(open_t)}件/社長の確認待ち{len(asking)}件/承認待ち{len(approval)}件",
    ]
    gaps = followers_gaps()
    if gaps:
        lines.append("- フォロワー数が7日以上記録されていない媒体: " + "・".join(PLATFORM_JA[p] for p in gaps)
                     + "(推測で埋めない。社長に今の数を聞いて record_followers で記録する)")
    for t in open_t[:12]:
        lines.append(f"  - {t['id']} {t['title'][:60]}(担当:{t['assignee']}・状態:{t['status']}・期限:{t['due'] or '-'})")
    return "\n".join(lines)


# ---------- 数字の記録(収益・フォロワー) ----------
FOLLOWERS_CSV = COMPANY_DIR / "data" / "followers.csv"
# ---------- アカウントの組(2026-11-12 社長: 別アカウントが増えても選べるように) ----------
# ai-company/data/account_sets.json に一覧と、媒体ごとの登録(URL)を持つ。本アカウント(main)の URL は前からの accounts.md
ACCOUNT_SETS_JSON = COMPANY_DIR / "data" / "account_sets.json"
DEFAULT_SETS = [
    {"id": "main", "label": "本アカウント", "note": "定時AI・秘書セナ", "urls": {}},
    {"id": "sub", "label": "別アカウント1", "note": "note の別アカウント(収益化用)", "urls": {}},
]


def account_sets() -> List[dict]:
    try:
        sets = json.loads(ACCOUNT_SETS_JSON.read_text())
        if not isinstance(sets, list) or not sets:
            raise ValueError
    except Exception:
        sets = [dict(x, urls=dict(x["urls"])) for x in DEFAULT_SETS]
    if not any(x.get("id") == "main" for x in sets):
        sets.insert(0, dict(DEFAULT_SETS[0]))
    for x in sets:
        x.setdefault("urls", {})
        x.setdefault("note", "")
    return sets


def _save_sets(sets: List[dict]):
    ACCOUNT_SETS_JSON.parent.mkdir(parents=True, exist_ok=True)
    ACCOUNT_SETS_JSON.write_text(json.dumps(sets, ensure_ascii=False, indent=1) + "\n")


def account_ids() -> List[str]:
    return [x["id"] for x in account_sets()]


def account_label(account: str) -> str:
    return next((x["label"] for x in account_sets() if x["id"] == account), account)


def check_account(account: str):
    if account not in account_ids():
        raise ValueError("アカウントは " + " / ".join(f"{x['id']}({x['label']})" for x in account_sets()) + " のどれかです")


def add_account_set(label: str, note: str = "") -> dict:
    """別アカウントを1つ足す(id は sub2, sub3… を自動で付ける)"""
    label = " ".join((label or "").split())
    if not label:
        raise ValueError("アカウントの名前を入れてください(例: 別アカウント2)")
    sets = account_sets()
    if any(x["label"] == label for x in sets):
        raise ValueError(f"「{label}」はもうあります")
    ids = {x["id"] for x in sets}
    n = 2
    while f"sub{n}" in ids:
        n += 1
    new = {"id": "sub" if "sub" not in ids else f"sub{n}", "label": label, "note": " ".join((note or "").split()), "urls": {}}
    sets.append(new)
    _save_sets(sets)
    return new


def account_data_dir(account: str = "main") -> Path:
    """アカウントごとの数字の置き場所。本アカウントは data/ のまま、別アカウントは data/{id}/(例 data/sub/)"""
    check_account(account)
    return COMPANY_DIR / "data" if account == "main" else COMPANY_DIR / "data" / account


def followers_csv(account: str = "main") -> Path:
    return account_data_dir(account) / "followers.csv"
ACCOUNTS_MD = COMPANY_DIR / "data" / "accounts.md"
PLATFORMS = ["instagram", "x", "threads", "note", "tiktok", "youtube"]
PLATFORM_JA = {"instagram": "Instagram", "x": "X", "threads": "Threads", "note": "note", "tiktok": "TikTok", "youtube": "YouTube"}
# 収益の出どころ(2026-11-12 社長: アカウントごと・請け負いごとに確定した金額を入れられるように)
# 本アカウント(main)・別アカウント(sub)の媒体は「main_instagram」「sub_note」の形。note の本アカウントは前からの note_sales のまま
_PJA_ALL = {"instagram": "Instagram", "x": "X", "threads": "Threads", "note": "note", "tiktok": "TikTok", "youtube": "YouTube"}
_FIXED_SOURCES = {"note_sales": "note販売(本アカウント)", "amazon_affiliate": "Amazonアフィ", "lancers": "ランサーズ", "coconala": "ココナラ",
                  "line_creators": "LINEスタンプ・絵文字"}


def revenue_sources() -> Dict[str, str]:
    """収益の出どころ {キー: 日本語}。アカウントが増えると自動で増える(キーは「アカウントid_媒体」。本アカウントの note だけ note_sales)"""
    out = dict(_FIXED_SOURCES)
    for x in account_sets():
        for p, pja in _PJA_ALL.items():
            if x["id"] == "main" and p == "note":
                continue
            out[f"{x['id']}_{p}"] = f"{pja}販売({x['label']})" if p == "note" else f"{pja}({x['label']})"
    out["other"] = "その他"
    return out


class _Sources(dict):  # 前からの REVENUE_SOURCE_JA[...] の呼び方をそのまま使えるように(毎回読み直す)
    def get(self, k, d=None):
        return revenue_sources().get(k, d)

    def __getitem__(self, k):
        return revenue_sources()[k]

    def __contains__(self, k):
        return k in revenue_sources()


REVENUE_SOURCE_JA = _Sources()
REVENUE_SOURCES = list(revenue_sources())


def revenue_source(account: str, platform: str) -> str:
    """アカウントと媒体から、収益の出どころのキーを決める"""
    if account == "main" and platform == "note":
        return "note_sales"
    key = f"{account}_{platform}"
    return key if key in REVENUE_SOURCE_JA else "other"


def _append_csv(path: Path, header: List[str], row: List[str]):
    path.parent.mkdir(parents=True, exist_ok=True)
    new = not path.exists() or not path.read_text().strip()
    with path.open("a", newline="") as f:
        w = csv.writer(f)
        if new:
            w.writerow(header)
        w.writerow(row)


async def record_revenue(amount: int, source: str = "other", date: Optional[str] = None, memo: str = "") -> dict:
    if source not in revenue_sources():
        source = "other"
    date = notion.valid_date(date or "") or datetime.date.today().isoformat()
    amount = int(amount)
    _append_csv(REVENUE_CSV, ["date", "source", "amount", "memo"], [date, source, str(amount), memo])
    synced = None
    if notion.configured():
        try:
            await notion.add_revenue(date, source, amount, memo, REVENUE_SOURCE_JA.get(source))
            synced = True
        except Exception as e:
            synced = str(e)
    return {"date": date, "source": source, "amount": amount, "memo": memo, "notion": synced}


def _read_follower_rows(account: str = "main") -> List[dict]:
    rows = []
    path = followers_csv(account)
    if path.exists():
        with path.open() as f:
            for r in csv.DictReader(f):
                try:
                    rows.append({"date": notion.valid_date(r["date"]), "platform": r["platform"].strip().lower(),
                                 "followers": int(float(r["followers"]))})
                except Exception:
                    pass
    return rows


def normalize_followers(account: str = "main") -> dict:
    """followers.csv を整える: 同じ日・同じ媒体の行は最後の値だけ残し、日付→媒体の順に並べる。
    数字の無い媒体は埋めない(推測の数字を作らない。抜けは「未記録」として扱う)"""
    rows = _read_follower_rows(account)
    if not rows:
        return {"rows": 0, "removed": 0}
    latest = {}
    for r in rows:
        if r["platform"] in PLATFORMS and r["date"]:
            latest[(r["date"], r["platform"])] = r["followers"]
    order = {p: i for i, p in enumerate(PLATFORMS)}
    keys = sorted(latest, key=lambda k: (k[0], order[k[1]]))
    path = followers_csv(account)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["date", "platform", "followers"])
        for d, p in keys:
            w.writerow([d, p, latest[(d, p)]])
    return {"rows": len(keys), "removed": len(rows) - len(keys)}


def record_followers(platform: str, followers: int, date: Optional[str] = None, account: str = "main") -> dict:
    """同じ日・同じ媒体がすでにあれば上書きする(重複させない)"""
    if platform not in PLATFORMS:
        raise ValueError(f"媒体は {' / '.join(PLATFORMS)} のどれかです")
    date = notion.valid_date(date or "") or datetime.date.today().isoformat()
    path = followers_csv(account)
    path.parent.mkdir(parents=True, exist_ok=True)
    _append_csv(path, ["date", "platform", "followers"], [date, platform, str(int(followers))])
    normalize_followers(account)
    return {"date": date, "platform": platform, "followers": int(followers), "account": account}


def followers_gaps(days: int = 7) -> List[str]:
    """直近 days 日に記録の無い媒体(Instagram 以外は自動で取れないので、社長に聞く)"""
    since = (datetime.date.today() - datetime.timedelta(days=days)).isoformat()
    seen = {r["platform"] for r in _read_follower_rows() if r["date"] and r["date"] >= since}
    return [p for p in PLATFORMS if p not in seen]


def read_followers(account: str = "main") -> dict:
    """媒体ごとの推移 {platform: [{date, followers}]}(同じ日は最後の値)"""
    series: dict = {p: {} for p in PLATFORMS}
    path = followers_csv(account)
    if path.exists():
        with path.open() as f:
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


def account_row_name(platform: str, account: str = "main") -> str:
    """data/accounts.md の表の1列目。別アカウントは「note(別アカウント1)」の形"""
    return PLATFORM_JA[platform] if account == "main" else f"{PLATFORM_JA[platform]}({account_label(account)})"


def is_account_row(cell: str, platform: str, account: str = "main") -> bool:
    name = PLATFORM_JA[platform]
    if account == "main":
        return cell == name
    return cell == account_row_name(platform, account) or (account == "sub" and cell.startswith(name + "(別アカウント"))


def account_url(platform: str, account: str = "main") -> str:
    """その媒体の登録(URL)。別アカウントは account_sets.json、無ければ accounts.md の行"""
    if account != "main":
        for x in account_sets():
            if x["id"] == account:
                u = (x.get("urls") or {}).get(platform) or {}
                if u.get("url"):
                    return u["url"]
    if ACCOUNTS_MD.exists():
        for line in ACCOUNTS_MD.read_text().splitlines():
            cells = [c.strip() for c in line.strip().strip("|").split("|")]
            if line.startswith("|") and len(cells) > 1 and is_account_row(cells[0], platform, account) and cells[1].startswith("http"):
                return cells[1]
    return ""


def registered_platforms(account: str = "main") -> List[str]:
    return [p for p in PLATFORMS if account_url(p, account)]


async def register_account(platform: str, url: str, opened: Optional[str] = None, account: str = "main") -> dict:
    """data/accounts.md の表に URL と開設日を書き、Notion の「アカウント台帳」ページにも記録する"""
    if platform not in PLATFORMS:
        raise ValueError(f"媒体は {' / '.join(PLATFORMS)} のどれかです")
    url = url.strip()
    if not re.match(r"^https://", url) or not any(h in url.split("/")[2] for h in ACCOUNT_HOSTS[platform]):
        raise ValueError(f"{PLATFORM_JA[platform]} の URL(https://{ACCOUNT_HOSTS[platform][0]}/...)を指定してください")
    opened = notion.valid_date(opened or "") or datetime.date.today().isoformat()
    check_account(account)
    newly = not account_url(platform, account)
    if account != "main":
        sets = account_sets()
        for x in sets:
            if x["id"] == account:
                x.setdefault("urls", {})[platform] = {"url": url, "opened": opened}
        _save_sets(sets)
    name = account_row_name(platform, account)
    if ACCOUNTS_MD.exists():
        lines = ACCOUNTS_MD.read_text().splitlines()
        last_row = None
        for i, line in enumerate(lines):
            cells = [c.strip() for c in line.strip().strip("|").split("|")]
            if line.startswith("|"):
                last_row = i
            if line.startswith("|") and cells and is_account_row(cells[0], platform, account):
                cells[1], cells[2] = url, opened
                lines[i] = "| " + " | ".join(cells) + " |"
                break
        else:
            if last_row is not None:  # 表に無い(別アカウントの SNS など)→ 表の最後に足す
                lines.insert(last_row + 1, f"| {name} | {url} | {opened} | — | y/n |")
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
    if newly:  # 2026-11-12 社長: 登録された次の会議から、その媒体の投稿を作る → 目安箱に議題として入れる
        try:
            sug = COMPANY_DIR / "meetings" / "_suggestions.md"
            if sug.exists():
                sug.write_text(sug.read_text().rstrip("\n") + f"\n- {opened} 秘書室(社長が登録): **{account_label(account)}の{PLATFORM_JA[platform]}を登録しました**({url})。"
                               f"次の企画会議で、この媒体の運用の型・本数・最初の投稿を決める(投稿ファイルに account: {account})\n")
        except Exception as e:
            print("目安箱に書けませんでした:", e)
    return {"platform": platform, "url": url, "opened": opened, "account": account, "notion": synced, "new": newly}


def accounts_text() -> str:
    """秘書・部署が読む、アカウントごとの登録済みの媒体(登録の無い媒体の投稿は作らない。2026-11-12 社長)"""
    lines = []
    for x in account_sets():
        reg = [f"{PLATFORM_JA[p]} {account_url(p, x['id'])}" for p in registered_platforms(x["id"])]
        lines.append(f"  - {x['label']}(account: {x['id']}): " + ("、".join(reg) if reg else "登録なし"))
    return "- アカウントと登録済みの媒体(登録の無い媒体は「利用なし」=投稿を作らない):\n" + "\n".join(lines)
