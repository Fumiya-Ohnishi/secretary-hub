"""作業のまとまり(やり取りの流れ)。2026-11-12 社長「部署からの報告→社長確認→差し戻し→部署からの報告と何度かやり取りしている際、
どこからの関連かがわかりにくい。作業ごとにファイル分けされて、そのファイル内にやり取りが溜まっていく感じにしたい」

1つの作業(元の作業名が同じもの。T-315 の工程のように「T-番号 …: 工程」の形なら T-番号ごと)を Notion の
「作業のまとまり」DB の1ページにし、次のことを起きた順に1行ずつ書き足す。
- 📝 部署の報告(作業ログへのリンク)
- ❓ 社長への確認(確認タスク)
- ✅ 承認 / ↩ 差し戻し(社長のコメント)
- ▶ 続きを部署に依頼
作業ログ・確認タスクとは、関連(リレーション)の「まとまり」でつながる。Notion が使えないときは何もしない(作業は止めない)。
"""
import asyncio
import datetime
import json
import os
import re
import threading
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import notion
import president_asks

THREAD_DB = os.getenv("NOTION_THREAD_DB", "7505dc7496794877a5f1342aae3d321c").strip()
CACHE = Path(__file__).resolve().parent / "data" / "threads.json"
DEPTS = {"経営戦略部", "収益化部", "企画編集部", "ライティング部", "デザイン部", "画像制作部", "映像制作部", "SNS運用部",
         "品質管理部", "データ分析部", "広報部", "人事部", "経理・税務部", "秘書室", "社外制作室(Codex)"}


def key_of(title: str) -> Tuple[str, str]:
    """作業の件名から (キー, まとまりの名前) を決める"""
    base = president_asks.base_title(title)
    m = re.match(r"^(T-\d+)\s+(.+?)[::]\s*\S", base)  # 「T-315 note別アカ 最初の週(…): 記事4本の品質チェック」= 工程
    if m:
        return m.group(1), f"{m.group(1)} {m.group(2)}"[:100]
    m = re.match(r"^(T-\d+)\b", base)
    if m:
        return m.group(1), base[:100]
    base = base or "(名前のない作業)"
    return base[:60], base[:100]


def _load() -> Dict[str, str]:
    try:
        return json.loads(CACHE.read_text())
    except Exception:
        return {}


def _save(d: Dict[str, str]) -> None:
    try:
        CACHE.parent.mkdir(parents=True, exist_ok=True)
        CACHE.write_text(json.dumps(d, ensure_ascii=False, indent=1))
    except Exception:
        pass


async def _find(key: str) -> Optional[dict]:
    data = await notion._req("POST", f"/databases/{THREAD_DB}/query",
                             json={"page_size": 1, "filter": {"property": "キー", "rich_text": {"equals": key}}})
    res = data.get("results") or []
    return res[0] if res else None


async def ensure(title: str, dept: str = "", day: Optional[str] = None) -> Optional[str]:
    """まとまりのページID(無ければ作る)"""
    if not notion.configured():
        return None
    key, name = key_of(title)
    if True:
        cache = _load()
        if key in cache:
            return cache[key]
        page = await _find(key)
        if page:
            pid = page["id"].replace("-", "")
        else:
            day = day or datetime.date.today().isoformat()
            props = {"まとまり": {"title": notion._text(name)}, "キー": {"rich_text": notion._text(key)},
                     "状態": {"select": {"name": "進行中"}}, "始めた日": {"date": {"start": day}},
                     "最後の動き": {"date": {"start": day}}, "やり取りの回数": {"number": 0}}
            if dept in DEPTS:
                props["部署"] = {"multi_select": [{"name": dept}]}
            page = await notion._req("POST", "/pages", json={
                "parent": {"database_id": THREAD_DB}, "icon": {"type": "emoji", "emoji": "🧵"}, "properties": props,
                "children": notion.markdown_to_blocks("> この作業についての、部署の報告・社長の確認・回答が、起きた順に下へ溜まっていきます。\n\n## やり取りの流れ")})
            pid = page["id"].replace("-", "")
        cache[key] = pid
        _save(cache)
        return pid


def _line(icon: str, text: str, link: str = "", link_text: str = "") -> dict:
    now = datetime.datetime.now().strftime("%m/%d %H:%M")
    rich = [{"type": "text", "text": {"content": f"{icon} {now}  "}, "annotations": {"bold": True}},
            {"type": "text", "text": {"content": text[:1800]}}]
    if link:
        rich.append({"type": "text", "text": {"content": f"  → {link_text or '開く'}", "link": {"url": link}}})
    return {"type": "bulleted_list_item", "bulleted_list_item": {"rich_text": rich}}


async def add(title: str, icon: str, text: str, *, dept: str = "", link: str = "", link_text: str = "",
              state: Optional[str] = None, relate_worklog: str = "", relate_task: str = "") -> Optional[str]:
    """まとまりに1行足し、状態・最後の動き・回数・部署を更新する。関連づけるページがあればつなぐ"""
    try:
        pid = await ensure(title, dept)
        if not pid:
            return None
        await notion.append_blocks(pid, [_line(icon, text, link, link_text)])
        page = await notion._req("GET", f"/pages/{pid}")
        pr = page.get("properties", {})
        props = {"最後の動き": {"date": {"start": datetime.date.today().isoformat()}},
                 "やり取りの回数": {"number": ((pr.get("やり取りの回数") or {}).get("number") or 0) + 1}}
        if state:
            props["状態"] = {"select": {"name": state}}
        depts = [o["name"] for o in (pr.get("部署") or {}).get("multi_select", [])]
        if dept in DEPTS and dept not in depts:
            props["部署"] = {"multi_select": [{"name": d} for d in depts + [dept]]}
        for name, other in (("作業ログ", relate_worklog), ("確認タスク", relate_task)):
            if other:
                cur = [r["id"] for r in (pr.get(name) or {}).get("relation", [])]
                if other.replace("-", "") not in [c.replace("-", "") for c in cur]:
                    props[name] = {"relation": [{"id": c} for c in cur] + [{"id": other}]}
        await notion._req("PATCH", f"/pages/{pid}", json={"properties": props})
        return pid
    except Exception:
        return None  # まとまりが書けなくても、作業は止めない


def add_in_background(*args, **kwargs) -> None:
    """同期の処理(社長の回答の受け取りなど)から呼ぶとき用"""
    threading.Thread(target=lambda: asyncio.run(add(*args, **kwargs)), daemon=True).start()
