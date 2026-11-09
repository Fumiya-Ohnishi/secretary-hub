"""Notion との接続(公式 REST API)。

使うには backend/.env に NOTION_TOKEN(Notion の「インテグレーション」のシークレット)を入れ、
Notion で「AI会社」ページにそのインテグレーションを接続する(README の手順)。
未設定なら configured() が False になり、呼び出し側は data/tasks.md の控えに切り替える。
"""
import datetime
import asyncio
import os
import re
from typing import Dict, List, Optional

import httpx

API = "https://api.notion.com/v1"
VERSION = "2022-06-28"

STATUSES = ["未着手", "進行中", "承認待ち", "承認済み", "完了", "差し戻し"]
# 担当(Notion の「担当」)。組織設計案 v1 の10部署+秘書・社長。制作・メディアは旧部署名(過去のタスク用)
ASSIGNEES = ["秘書", "戦略", "収益化", "企画", "ライティング", "デザイン", "画像", "映像", "SNS運用", "品質管理", "分析",
             "社長", "制作", "メディア"]

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


def valid_date(value: str) -> str:
    """YYYY-MM-DD か確認して返す(空文字は「期限なし」)"""
    value = (value or "").strip()
    if value:
        datetime.date.fromisoformat(value)  # 形式が違えば ValueError
    return value


async def update_task(key: str, status: Optional[str] = None, note: Optional[str] = None,
                      append_note: Optional[str] = None, due: Optional[str] = None, link: Optional[str] = None) -> dict:
    """due: None=変更しない / "" =期限を消す / "YYYY-MM-DD"=その日に変える"""
    props: Dict[str, dict] = {}
    if link:
        props["資料"] = {"url": link}
    if due is not None:
        due = valid_date(due)
        props["期限"] = {"date": {"start": due} if due else None}
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
async def _search_all(kind: str, limit: int = 1000) -> List[dict]:
    out, cursor = [], None
    while len(out) < limit:
        body = {"filter": {"property": "object", "value": kind},
                "sort": {"direction": "descending", "timestamp": "last_edited_time"}, "page_size": 100}
        if cursor:
            body["start_cursor"] = cursor
        data = await _req("POST", "/search", json=body)
        out += data.get("results", [])
        if not data.get("has_more"):
            break
        cursor = data.get("next_cursor")
    return out


def _icon(p: dict) -> str:
    icon = p.get("icon") or {}
    return icon.get("emoji", "") if icon.get("type") == "emoji" else ""


async def list_documents() -> List[dict]:
    """インテグレーションが見られるページとデータベースの一覧(新しい順)。
    データベースの行(タスク・議事録など)は一覧に出さず、データベースを開くと表で見られる"""
    pages, dbs = await asyncio.gather(_search_all("page"), _search_all("database", 300))
    docs = []
    for d in dbs:
        if d.get("archived") or d.get("in_trash"):
            continue
        docs.append({"id": d["id"].replace("-", ""), "kind": "database", "title": plain(d.get("title", [])) or "(無題のデータベース)",
                     "icon": _icon(d) or "🗂", "edited": d.get("last_edited_time", ""), "url": d.get("url", ""), "is_root": False})
    for p in pages:
        if p.get("archived") or p.get("in_trash") or p.get("parent", {}).get("type") == "database_id":
            continue
        docs.append({
            "id": p["id"].replace("-", ""),
            "kind": "page",
            "title": page_title(p),
            "icon": _icon(p),
            "edited": p.get("last_edited_time", ""),
            "url": p.get("url", ""),
            "is_root": p["id"].replace("-", "") == ROOT_PAGE,
        })
    docs.sort(key=lambda d: d["edited"], reverse=True)
    return docs


def prop_text(pr: dict) -> str:
    """データベースの1マスを文字にする"""
    t = pr.get("type")
    v = pr.get(t)
    if v is None:
        return ""
    if t in ("title", "rich_text"):
        return plain(v)
    if t in ("select", "status"):
        return v.get("name", "")
    if t == "multi_select":
        return "・".join(x.get("name", "") for x in v)
    if t == "date":
        return (v.get("start") or "")[:16].replace("T", " ") + (f"〜{v['end'][:10]}" if v.get("end") else "")
    if t == "checkbox":
        return "✓" if v else ""
    if t in ("number", "url", "email", "phone_number"):
        return str(v)
    if t in ("created_time", "last_edited_time"):
        return v[:10]
    if t == "people":
        return "・".join(x.get("name", "") for x in v)
    if t == "relation":
        return f"{len(v)}件" if v else ""
    if t == "formula":
        return str(v.get(v.get("type"), "") or "")
    if t == "rollup":
        return str(v.get("number", "") or "")
    if t == "unique_id":
        return f"{v.get('prefix') or ''}-{v.get('number')}" if v.get("prefix") else str(v.get("number", ""))
    return ""


ORDER = {"title": 0, "status": 1, "select": 2, "date": 3, "number": 4, "multi_select": 5, "checkbox": 6, "url": 7, "rich_text": 8}


async def read_database(db_id: str, limit: int = 300) -> dict:
    """データベースを表で見るための中身(列は大事なものから最大7つ)"""
    db = await _req("GET", f"/databases/{db_id}")
    props = [(name, p.get("type")) for name, p in db.get("properties", {}).items() if p.get("type") in ORDER]
    props.sort(key=lambda x: ORDER[x[1]])
    cols = [n for n, _ in props][:7]
    rows, cursor = [], None
    while len(rows) < limit:
        body = {"page_size": 100, "sorts": [{"timestamp": "last_edited_time", "direction": "descending"}]}
        if cursor:
            body["start_cursor"] = cursor
        data = await _req("POST", f"/databases/{db_id}/query", json=body)
        for r in data.get("results", []):
            pr = r.get("properties", {})
            rows.append({"id": r["id"].replace("-", ""), "icon": _icon(r), "url": r.get("url", ""),
                         "cells": [prop_text(pr.get(c, {})) for c in cols]})
        if not data.get("has_more"):
            break
        cursor = data.get("next_cursor")
    return {"id": db_id, "kind": "database", "title": plain(db.get("title", [])) or "(無題のデータベース)", "icon": _icon(db) or "🗂",
            "url": db.get("url", ""), "edited": db.get("last_edited_time", ""), "columns": cols, "rows": rows, "more": len(rows) >= limit}


MAX_BLOCKS = 1500
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
        node["text"] = [{"t": body.get("title", "") or "データベース"}]
        node["db_id"] = b["id"].replace("-", "")
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
        "kind": "page",
        "title": page_title(page),
        "icon": icon.get("emoji", "") if icon.get("type") == "emoji" else "",
        "url": page.get("url", ""),
        "edited": page.get("last_edited_time", ""),
        "blocks": blocks,
    }


async def read_any(doc_id: str) -> dict:
    """ページでもデータベースでも開く(どちらか分からない ID 用)"""
    try:
        return await read_page(doc_id)
    except NotionError as e:
        if "database" in str(e).lower():
            return await read_database(doc_id)
        raise


def database_to_text(db: dict) -> str:
    lines = [" | ".join(db["columns"])]
    lines += [" | ".join(r["cells"]) for r in db["rows"]]
    return "\n".join(lines)


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


# ---------- 収益・アカウント・レポート ----------
REVENUE_DB = os.getenv("NOTION_REVENUE_DB", "0ca816aeacb8476d9326f5623b3def3d").strip()
REVENUE_SOURCE_JA = {"note_sales": "note販売", "amazon_affiliate": "Amazonアフィ", "other": "その他"}


async def add_revenue(date: str, source: str, amount: int, memo: str) -> None:
    await _req("POST", "/pages", json={"parent": {"database_id": REVENUE_DB}, "properties": {
        "メモ": {"title": _text(memo or REVENUE_SOURCE_JA.get(source, source))},
        "ソース": {"select": {"name": REVENUE_SOURCE_JA.get(source, "その他")}},
        "金額": {"number": amount},
        "日付": {"date": {"start": date}},
    }})


# 「AI会社」ページの下のフォルダ(2026-11-09 整理)。キー → (名前, 既定のID)
FOLDERS = {
    "strategy": ("戦略・企画書", os.getenv("NOTION_FOLDER_STRATEGY", "41387d43630581d1a8f1c072b4a4c347")),
    "guide": ("手順・ガイド", os.getenv("NOTION_FOLDER_GUIDE", "41387d43630581a380afc1cae8395056")),
    "report": ("レポート", os.getenv("NOTION_FOLDER_REPORT", "41387d436305811e8fdcdd0a3d902b3b")),
    "data": ("データ・台帳", os.getenv("NOTION_FOLDER_DATA", "41387d43630581a48153d28e037ac4e4")),
}
WORKLOG_DB = os.getenv("NOTION_WORKLOG_DB", "8a1584c0189d4671a45585ac82c8ba59").strip()
_folder_cache: Dict[str, str] = {}


async def folder(key: str) -> str:
    """フォルダのページID(見つからなければ「AI会社」の下に作る)"""
    if key in _folder_cache:
        return _folder_cache[key]
    name, default = FOLDERS[key]
    pid = None
    try:
        await _req("GET", f"/pages/{default}")
        pid = default
    except Exception:
        pid = await find_child_page(name)
        if not pid:
            pid = (await create_page(name, [], "📁"))["id"]
    _folder_cache[key] = pid
    return pid


async def find_child_page(title: str, parent: Optional[str] = None) -> Optional[str]:
    cursor = None
    while True:
        params = {"page_size": 100}
        if cursor:
            params["start_cursor"] = cursor
        data = await _req("GET", f"/blocks/{parent or ROOT_PAGE}/children", params=params)
        for b in data.get("results", []):
            if b.get("type") == "child_page" and b["child_page"].get("title") == title:
                return b["id"].replace("-", "")
        if not data.get("has_more"):
            return None
        cursor = data.get("next_cursor")


async def create_page(title: str, blocks: List[dict], icon: str = "📄", parent: Optional[str] = None) -> dict:
    """「AI会社」ページ(か parent)の下にページを作る(ブロックは100個ずつ追加)"""
    page = await _req("POST", "/pages", json={
        "parent": {"page_id": parent or ROOT_PAGE}, "icon": {"type": "emoji", "emoji": icon},
        "properties": {"title": {"title": _text(title)}}, "children": blocks[:100]})
    pid = page["id"].replace("-", "")
    for i in range(100, len(blocks), 100):
        await append_blocks(pid, blocks[i:i + 100])
    return {"id": pid, "url": page.get("url", ""), "title": title}


async def append_blocks(page_id: str, blocks: List[dict]) -> None:
    await _req("PATCH", f"/blocks/{page_id}/children", json={"children": blocks})


async def archive_page(page_id: str) -> None:
    await _req("PATCH", f"/pages/{page_id}", json={"archived": True})


def _rt_md(text: str) -> List[dict]:
    """**太字** と `コード` だけを Notion の文字装飾にする"""
    out = []
    for part in re.split(r"(\*\*[^*]+\*\*|`[^`]+`)", text):
        if not part:
            continue
        ann = {}
        if part.startswith("**") and part.endswith("**"):
            part, ann = part[2:-2], {"bold": True}
        elif part.startswith("`") and part.endswith("`"):
            part, ann = part[1:-1], {"code": True}
        item = {"type": "text", "text": {"content": part[:1900]}}
        if ann:
            item["annotations"] = ann
        out.append(item)
    return out


def markdown_to_blocks(md: str) -> List[dict]:
    """週次レポートなどの簡単なマークダウンを Notion のブロックに変換する"""
    blocks: List[dict] = []
    lines = md.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i].rstrip()
        if line.startswith("|"):
            rows = []
            while i < len(lines) and lines[i].strip().startswith("|"):
                cells = [c.strip() for c in lines[i].strip().strip("|").split("|")]
                if not all(re.fullmatch(r":?-{2,}:?", c) for c in cells if c):
                    rows.append(cells)
                i += 1
            width = max(len(r) for r in rows) if rows else 0
            if rows:
                blocks.append({"type": "table", "table": {"table_width": width, "has_column_header": True, "children": [
                    {"type": "table_row", "table_row": {"cells": [_rt_md(c) for c in r + [""] * (width - len(r))]}}
                    for r in rows]}})
            continue
        m = re.match(r"^(#{1,3})\s+(.*)", line)
        if m:
            t = f"heading_{len(m.group(1))}"
            blocks.append({"type": t, t: {"rich_text": _rt_md(m.group(2))}})
        elif re.match(r"^\s*[-*]\s+", line):
            blocks.append({"type": "bulleted_list_item", "bulleted_list_item": {"rich_text": _rt_md(re.sub(r"^\s*[-*]\s+", "", line))}})
        elif re.match(r"^\s*\d+\.\s+", line):
            blocks.append({"type": "numbered_list_item", "numbered_list_item": {"rich_text": _rt_md(re.sub(r"^\s*\d+\.\s+", "", line))}})
        elif line.startswith(">"):
            blocks.append({"type": "quote", "quote": {"rich_text": _rt_md(line.lstrip("> "))}})
        elif line.strip() == "---":
            blocks.append({"type": "divider", "divider": {}})
        elif line.strip():
            blocks.append({"type": "paragraph", "paragraph": {"rich_text": _rt_md(line)}})
        i += 1
    return blocks


# ---------- 作業ログ(社員の作業の成果。1作業=1ページ) ----------
async def add_worklog(title: str, day: str, dept: str, kind: str, status: str, files: List[str],
                      task: str, job_id: str, blocks: List[dict]) -> dict:
    props = {"作業": {"title": _text(title[:200])}, "日付": {"date": {"start": day}},
             "種類": {"select": {"name": kind}}, "状態": {"select": {"name": status}},
             "ファイル": {"rich_text": _text(", ".join(files)[:1900])}, "タスク": {"rich_text": _text(task[:200])},
             "作業ID": {"rich_text": _text(job_id)}}
    if dept:
        props["部署"] = {"select": {"name": dept}}
    page = await _req("POST", "/pages", json={"parent": {"database_id": WORKLOG_DB}, "icon": {"type": "emoji", "emoji": "🗂"},
                                              "properties": props, "children": blocks[:100]})
    pid = page["id"].replace("-", "")
    for i in range(100, len(blocks), 100):
        await append_blocks(pid, blocks[i:i + 100])
    return {"id": pid, "url": page.get("url", "")}


async def list_worklog(days: int = 60, limit: int = 300) -> List[dict]:
    since = (datetime.date.today() - datetime.timedelta(days=days)).isoformat()
    rows, cursor = [], None
    while len(rows) < limit:
        body = {"page_size": 100, "filter": {"property": "日付", "date": {"on_or_after": since}},
                "sorts": [{"property": "日付", "direction": "descending"}, {"timestamp": "created_time", "direction": "descending"}]}
        if cursor:
            body["start_cursor"] = cursor
        data = await _req("POST", f"/databases/{WORKLOG_DB}/query", json=body)
        for r in data.get("results", []):
            pr = r.get("properties", {})
            rows.append({"id": r["id"].replace("-", ""), "title": prop_text(pr.get("作業", {})) or "(無題)",
                         "date": prop_text(pr.get("日付", {}))[:10], "time": (r.get("created_time") or "")[11:16],
                         "dept": prop_text(pr.get("部署", {})), "kind": prop_text(pr.get("種類", {})),
                         "status": prop_text(pr.get("状態", {})), "url": r.get("url", "")})
        if not data.get("has_more"):
            break
        cursor = data.get("next_cursor")
    return rows


async def tree() -> List[dict]:
    """「AI会社」ページの中身をフォルダの形で(子ページ・データベース。フォルダは1段下まで)"""
    async def kids(pid: str, depth: int) -> List[dict]:
        out, cursor = [], None
        while True:
            params = {"page_size": 100}
            if cursor:
                params["start_cursor"] = cursor
            data = await _req("GET", f"/blocks/{pid}/children", params=params)
            for b in data.get("results", []):
                t = b.get("type")
                if t not in ("child_page", "child_database"):
                    continue
                item = {"id": b["id"].replace("-", ""), "title": b[t].get("title") or "(無題)",
                        "kind": "database" if t == "child_database" else "page"}
                if t == "child_page" and depth < 1 and b.get("has_children"):
                    item["children"] = await kids(item["id"], depth + 1)
                out.append(item)
            if not data.get("has_more"):
                break
            cursor = data.get("next_cursor")
        return out
    return await kids(ROOT_PAGE, 0)
