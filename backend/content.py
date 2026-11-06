"""週の投稿セット(ai-company/content/drafts/YYYY-WW/)の読み書き。形式は ai-company/playbooks/post_format.md。

承認済み・差し戻し・投稿済みは、社長の操作(秘書ハブのボタンか声の返事)からだけ書き込む。
"""
import datetime
import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import company

POST_STATUSES = ["下書き", "承認待ち", "承認済み", "差し戻し", "投稿済み"]
PLATFORM_JA = {"instagram": "Instagram", "x": "X", "threads": "Threads", "note": "note"}
WEEK_RE = re.compile(r"^\d{4}-\d{2}$")


def drafts_dir() -> Path:
    return company.COMPANY_DIR / "content" / "drafts"


def current_week(offset_weeks: int = 0) -> str:
    y, w, _ = (datetime.date.today() + datetime.timedelta(weeks=offset_weeks)).isocalendar()
    return f"{y}-{w:02d}"


# ---------- front matter(--- で囲んだ key: value)----------
def parse(text: str) -> Tuple[Dict[str, str], str]:
    meta: Dict[str, str] = {}
    body = text
    if text.startswith("---"):
        end = text.find("\n---", 3)
        if end != -1:
            for line in text[3:end].strip().splitlines():
                if ":" in line:
                    k, v = line.split(":", 1)
                    meta[k.strip()] = v.strip()
            body = text[end + 4:].lstrip("\n")
    return meta, body


def dump(meta: Dict[str, str], body: str) -> str:
    head = "\n".join(f"{k}: {v}" for k, v in meta.items())
    return f"---\n{head}\n---\n{body.rstrip()}\n"


def sections(body: str) -> List[dict]:
    """「## 見出し」ごとに分ける"""
    out, cur = [], None
    for line in body.splitlines():
        m = re.match(r"^##\s+(.+)", line)
        if m:
            cur = {"title": m.group(1).strip(), "text": ""}
            out.append(cur)
        elif cur is not None:
            cur["text"] += line + "\n"
        elif line.strip():
            cur = {"title": "", "text": line + "\n"}
            out.append(cur)
    for s in out:
        s["text"] = s["text"].strip()
    return out


# ---------- 読み取り ----------
def _post(path: Path) -> dict:
    meta, body = parse(path.read_text())
    secs = sections(body)
    assets = [a.strip() for a in meta.get("assets", "").split(",") if a.strip()]
    return {
        "path": str(path.relative_to(company.COMPANY_DIR)),
        "file": path.name,
        "id": meta.get("id", path.stem),
        "platform": meta.get("platform", ""),
        "platform_ja": PLATFORM_JA.get(meta.get("platform", ""), meta.get("platform", "")),
        "format": meta.get("format", ""),
        "title": meta.get("title", path.stem),
        "scheduled": meta.get("scheduled", ""),
        "status": meta.get("status", "下書き"),
        "posted": meta.get("posted", ""),
        "pr": meta.get("pr", "false").lower() == "true",
        "assets": assets,
        "sections": secs,
        "caption": next((s["text"] for s in secs if "キャプション" in s["title"]), ""),
    }


def list_weeks() -> List[dict]:
    d = drafts_dir()
    if not d.exists():
        return []
    weeks = []
    for wd in sorted((p for p in d.iterdir() if p.is_dir() and WEEK_RE.match(p.name)), reverse=True):
        posts = [_post(p) for p in sorted(wd.glob("[0-9]*.md"))]
        meta, _ = parse((wd / "_week.md").read_text()) if (wd / "_week.md").exists() else ({}, "")
        counts: Dict[str, int] = {}
        for p in posts:
            counts[p["status"]] = counts.get(p["status"], 0) + 1
        weeks.append({"week": wd.name, "theme": meta.get("theme", ""), "task": meta.get("task", ""),
                      "count": len(posts), "counts": counts})
    return weeks


def get_week(week: str) -> dict:
    if not WEEK_RE.match(week):
        raise ValueError("週は YYYY-WW の形で指定してください")
    wd = drafts_dir() / week
    if not wd.exists():
        raise KeyError(f"{week} の投稿セットはまだありません")
    meta, body = parse((wd / "_week.md").read_text()) if (wd / "_week.md").exists() else ({}, "")
    return {"week": week, "theme": meta.get("theme", ""), "task": meta.get("task", ""), "summary": body.strip(),
            "posts": [_post(p) for p in sorted(wd.glob("[0-9]*.md"))]}


def safe_path(rel: str) -> Path:
    """content/ の下のファイルだけを許可する(../ などで外に出さない)"""
    root = (company.COMPANY_DIR / "content").resolve()
    p = (company.COMPANY_DIR / rel).resolve()
    if root != p and root not in p.parents:
        raise PermissionError("content/ の外のファイルは開けません")
    if not p.is_file():
        raise FileNotFoundError(rel)
    return p


# ---------- 社長の判断の書き込み ----------
def _set_status(rel: str, status: str, comment: str = "") -> dict:
    path = safe_path(rel)
    if path.suffix != ".md" or not WEEK_RE.match(path.parent.name):
        raise PermissionError("投稿ファイルではありません")
    meta, body = parse(path.read_text())
    meta["status"] = status
    today = datetime.date.today().isoformat()
    if status == "投稿済み":
        meta["posted"] = today
    if status == "差し戻し":
        body = body.rstrip() + f"\n\n## 社長コメント\n- {today}: {comment or '(理由なし)'}\n"
    path.write_text(dump(meta, body))
    return _post(path)


async def decide(rel: str, decision: str, comment: str = "") -> dict:
    status = {"approve": "承認済み", "reject": "差し戻し", "posted": "投稿済み"}.get(decision)
    if not status:
        raise ValueError("decision は approve / reject / posted")
    post = _set_status(rel, status, comment)
    await sync_week_task(Path(rel).parent.name, comment if decision == "reject" else "")
    return post


async def approve_week(week: str) -> dict:
    data = get_week(week)
    n = 0
    for p in data["posts"]:
        if p["status"] == "承認待ち":
            _set_status(p["path"], "承認済み")
            n += 1
    await sync_week_task(week)
    return {"approved": n, **get_week(week)}


async def sync_week_task(week: str, reject_comment: str = ""):
    """週のタスク(_week.md の task:)を投稿の状態に合わせる。全部承認→承認済み、差し戻しあり→差し戻し"""
    try:
        data = get_week(week)
        if not data["task"]:
            return
        task = await company.find_task(data["task"])
        statuses = [p["status"] for p in data["posts"]]
        today = f"{datetime.date.today():%m/%d}"
        if reject_comment:
            await company.update_task(task["key"], status="差し戻し", append_note=f"{today} 投稿の差し戻し:{reject_comment}")
        elif statuses and all(s in ("承認済み", "投稿済み") for s in statuses) and task["status"] != "承認済み":
            await company.update_task(task["key"], status="承認済み", append_note=f"{today} 社長が秘書ハブで投稿セットを承認")
        elif "承認待ち" in statuses and task["status"] in ("未着手", "進行中", "差し戻し"):
            await company.update_task(task["key"], status="承認待ち", append_note=f"{today} 投稿セットが承認待ちになりました")
    except Exception:
        pass


def summary_text() -> str:
    weeks = list_weeks()[:3]
    if not weeks:
        return "- 投稿セット: まだありません(content/drafts/YYYY-WW/)"
    lines = ["- 投稿セット:"]
    for w in weeks:
        c = "・".join(f"{k}{v}" for k, v in w["counts"].items()) or "0件"
        lines.append(f"  - {w['week']} テーマ「{w['theme'] or '未定'}」: {c}")
    return "\n".join(lines)
