"""Notion との接続(公式 REST API)。

使うには backend/.env に NOTION_TOKEN(Notion の「インテグレーション」のシークレット)を入れ、
Notion で「AI会社」ページにそのインテグレーションを接続する(README の手順)。
未設定なら configured() が False になり、呼び出し側は data/tasks.md の控えに切り替える。
"""
import datetime
import os
import re
from typing import Dict, List, Optional

import httpx

API = "https://api.notion.com/v1"
VERSION = "2022-06-28"

STATUSES = ["未着手", "進行中", "承認待ち", "承認済み", "完了", "差し戻し"]
ASSIGNEES = ["秘書", "戦略", "企画", "制作", "メディア", "分析", "社長"]

# 既定は社長の Notion「AI会社」(2026-11-06 作成)。別の場所を使うときは .env で上書き
TASK_DB = os.getenv("NOTION_TASK_DB", "cd694a11babc42d7877eb741b262ec00").strip()
ROOT_PAGE = os.getenv("NOTION_ROOT_PAGE", "41087d4363058170a319e6e7da8faca4").strip()


def token() -> str:
    return os.getenv("NOTION_TOKEN", "").strip()


def configured() -> bool:
    return bool(token())


class NotionError(Exception):
    pass


async def _req(method: str, path: str, json: Optional[dict] = None, params: Optional[dict] = None) -> dict:
    headers = {"Authorization": f"Bearer {token()}", "Notion-Version": VERSION, "Content-Type": "application/json"}
    async with httpx.AsyncClient(timeout=20) as client:
        r = await client.request(method, f"{API}{path}", headers=headers, json=json, params=params)
    if r.status_code >= 400:
        try:
            msg = r.json().get("message", r.text)
        except Exception:
            msg = r.text
        if r.status_code == 401:
            msg = "NOTION_TOKEN が正しくありません"
        elif r.status_code == 404:
            msg = "ページが見つかりません(Notion で「AI会社」ページにインテグレーションを接続してください)"
        raise NotionError(f"Notion エラー({r.status_code}): {msg[:200]}")
    return r.json()


# ---------- 文字列の出し入れ ----------
def plain(rich: List[dict]) -> str:
    return "".join(t.get("plain_text", "") for t in rich or [])


def rich_segments(rich: List[dict]) -> List[dict]:
    """画面表示用に、太字・リンク等の情報を残した短い形にする"""
    out = []
    for t in rich or []:
        a = t.get("annotations", {})
        seg = {"t": t.get("plain_text", "")}
        if a.get("bold"):
            seg["b"] = 1
        if a.get("italic"):
            seg["i"] = 1
        if a.get("code"):
            seg["c"] = 1
        if a.get("strikethrough"):
            seg["s"] = 1
        href = t.get("href")
        if href:
            seg["href"] = href
        out.append(seg)
    return out


def _text(value: str) -> List[dict]:
    return [{"type": "text", "text": {"content": value[:1900]}}]


def page_id_from(value: str) -> Optional[str]:
    """URL や ID(ハイフン有無どちらでも)から 32桁のページIDを取り出す"""
    m = re.findall(r"[0-9a-f]{8}-?[0-9a-f]{4}-?[0-9a-f]{4}-?[0-9a-f]{4}-?[0-9a-f]{12}", (value or "").lower())
    return m[-1].replace("-", "") if m else None


def page_title(page: dict) -> str:
    for prop in page.get("properties", {}).values():
        if prop.get("type") == "title":
            return plain(prop.get("title", [])) or "(無題)"
    return "(無題)"


# ---------- タスク ----------
def _task_from_page(p: dict) -> dict:
    pr = p.get("properties", {})

    def sel(name):
        v = (pr.get(name) or {}).get("select")
        return v["name"] if v else ""

    due = ((pr.get("期限") or {}).get("date") or {}) or {}
    return {
        "key": p["id"].replace("-", ""),
        "id": plain((pr.get("ID") or {}).get("rich_text", [])),
        "title": plain((pr.get("タスク名") or {}).get("title", [])),
        "assignee": sel("担当"),
        "status": sel("ステータス"),
        "due": due.get("start") or "",
        "week": (pr.get("週") or {}).get("number"),
        "note": plain((pr.get("備考") or {}).get("rich_text", [])),
        "link": (pr.get("資料") or {}).get("url") or "",
        "url": p.get("url", ""),
        "edited": p.get("last_edited_time", ""),
    }


async def list_tasks() -> List[dict]:
    tasks, cursor = [], None
    while True:
        body = {"page_size": 100}
        if cursor:
            body["start_cursor"] = cursor
        data = await _req("POST", f"/databases/{TASK_DB}/query", json=body)
        tasks += [_task_from_page(p) for p in data.get("results", []) if not p.get("archived")]
        if not data.get("has_more"):
            break
        cursor = data.get("next_cursor")

    def order(t):
        m = re.search(r"\d+", t["id"] or "")
        return int(m.group()) if m else 9999

    return sorted(tasks, key=order)


async def update_task(key: str, status: Optional[str] = None, note: Optional[str] = None,
                      append_note: Optional[str] = None) -> dict:
    props: Dict[str, dict] = {}
    if status:
        if status not in STATUSES:
            raise NotionError(f"ステータスは {' / '.join(STATUSES)} のどれかです")
        props["ステータス"] = {"select": {"name": status}}
    if append_note:
        page = await _req("GET", f"/pages/{key}")
        old = plain(page["properties"].get("備考", {}).get("rich_text", []))
        note = f"{old} / {append_note}" if old else append_note
    if note is not None:
        props["備考"] = {"rich_text": _text(note)}
    page = await _req("PATCH", f"/pages/{key}", json={"properties": props})
    return _task_from_page(page)


async def create_task(title: str, assignee: str = "秘書", due: Optional[str] = None,
                      note: str = "", link: str = "") -> dict:
    existing = await list_tasks()
    nums = [int(m.group()) for t in existing for m in [re.search(r"\d+", t["id"] or "")] if m]
    new_id = f"T-{(max(nums) + 1) if nums else 1:03d}"
    props = {
        "タスク名": {"title": _text(title)},
        "ID": {"rich_text": _text(new_id)},
        "担当": {"select": {"name": assignee if assignee in ASSIGNEES else "秘書"}},
        "ステータス": {"select": {"name": "未着手"}},
        "週": {"number": datetime.date.today().isocalendar()[1]},
    }
    if due:
        props["期限"] = {"date": {"start": due}}
    if note:
        props["備考"] = {"rich_text": _text(note)}
    if link:
        props["資料"] = {"url": link}
    page = await _req("POST", "/pages", json={"parent": {"database_id": TASK_DB}, "properties": props})
    return _task_from_page(page)


# ---------- 資料(ページ) ----------
async def list_documents() -> List[dict]:
    """インテグレーションが見られるページの一覧(タスク等のデータベースの行は除く)。新しい順"""
    data = await _req("POST", "/search", json={
        "filter": {"property": "object", "value": "page"},
        "sort": {"direction": "descending", "timestamp": "last_edited_time"},
        "page_size": 100,
    })
    docs = []
    for p in data.get("results", []):
        if p.get("archived") or p.get("parent", {}).get("type") == "database_id":
            continue
        icon = p.get("icon") or {}
        docs.append({
            "id": p["id"].replace("-", ""),
            "title": page_title(p),
            "icon": icon.get("emoji", "") if icon.get("type") == "emoji" else "",
            "edited": p.get("last_edited_time", ""),
            "url": p.get("url", ""),
            "is_root": p["id"].replace("-", "") == ROOT_PAGE,
        })
    return docs


MAX_BLOCKS = 500
CHILD_TYPES = {"bulleted_list_item", "numbered_list_item", "to_do", "toggle", "callout", "quote",
               "table", "column_list", "column", "synced_block", "paragraph"}


async def _children(block_id: str, depth: int, counter: List[int]) -> List[dict]:
    out, cursor = [], None
    while counter[0] < MAX_BLOCKS:
        params = {"page_size": 100}
        if cursor:
            params["start_cursor"] = cursor
        data = await _req("GET", f"/blocks/{block_id}/children", params=params)
        for b in data.get("results", []):
            counter[0] += 1
            out.append(await _block(b, depth, counter))
        if not data.get("has_more"):
            break
        cursor = data.get("next_cursor")
    return out


async def _block(b: dict, depth: int, counter: List[int]) -> dict:
    t = b.get("type")
    body = b.get(t, {}) or {}
    node = {"type": t}
    if "rich_text" in body:
        node["text"] = rich_segments(body["rich_text"])
    if t == "to_do":
        node["checked"] = body.get("checked", False)
    if t == "callout":
        icon = body.get("icon") or {}
        node["icon"] = icon.get("emoji", "💡") if icon.get("type") == "emoji" else "💡"
    if t == "code":
        node["language"] = body.get("language", "")
    if t == "child_page":
        node["text"] = [{"t": body.get("title", "")}]
        node["page_id"] = b["id"].replace("-", "")
    if t == "child_database":
        node["text"] = [{"t": body.get("title", "")}]
    if t == "table_row":
        node["cells"] = [rich_segments(c) for c in body.get("cells", [])]
    if t == "table":
        node["header"] = body.get("has_column_header", False)
    if t in ("bookmark", "embed", "link_preview"):
        node["url"] = body.get("url", "")
    if t in ("image", "file", "pdf", "video"):
        src = body.get(body.get("type", ""), {}) or {}
        node["url"] = src.get("url", "")
        node["text"] = rich_segments(body.get("caption", []))
    if b.get("has_children") and depth < 4 and (t in CHILD_TYPES or t == "table_row"):
        node["children"] = await _children(b["id"], depth + 1, counter)
    return node


async def read_page(page_id: str) -> dict:
    page = await _req("GET", f"/pages/{page_id}")
    blocks = await _children(page_id, 0, [0])
    icon = page.get("icon") or {}
    return {
        "id": page_id,
        "title": page_title(page),
        "icon": icon.get("emoji", "") if icon.get("type") == "emoji" else "",
        "url": page.get("url", ""),
        "edited": page.get("last_edited_time", ""),
        "blocks": blocks,
    }


def blocks_to_text(blocks: List[dict], indent: int = 0) -> str:
    """秘書(AI)に読ませるための、簡易マークダウン"""
    lines = []
    pad = "  " * indent
    numbered = 0
    for b in blocks:
        t = b["type"]
        text = "".join(s["t"] for s in b.get("text", []))
        numbered = numbered + 1 if t == "numbered_list_item" else 0
        if t.startswith("heading_"):
            lines.append(f"{'#' * int(t[-1])} {text}")
        elif t == "bulleted_list_item":
            lines.append(f"{pad}- {text}")
        elif t == "numbered_list_item":
            lines.append(f"{pad}{numbered}. {text}")
        elif t == "to_do":
            lines.append(f"{pad}- [{'x' if b.get('checked') else ' '}] {text}")
        elif t == "table_row":
            lines.append(pad + "| " + " | ".join("".join(s["t"] for s in c) for c in b.get("cells", [])) + " |")
        elif t == "divider":
            lines.append("---")
        elif t == "child_page":
            lines.append(f"{pad}[子ページ] {text}")
        elif text:
            lines.append(f"{pad}{text}")
        if b.get("children"):
            lines.append(blocks_to_text(b["children"], indent + (0 if t in ("table", "column_list", "column") else 1)))
    return "\n".join(l for l in lines if l is not None)
