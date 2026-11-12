"""LINE スタンプ・絵文字のセット(2026-11-12 社長: 週に1つずつ作って数を増やす)。

ai-company/content/stamps/{セットID}/_set.md に1セットの設計(front matter + 本文)を置き、
画像は content/output/stamps/{セットID}/ (Google ドライブ)に置く。
状態: 下書き → 承認待ち → 承認済み(社長)/差し戻し(社長) → 申請した(社長が LINE に申請)→ 販売中 / リジェクト(LINE の審査で落ちた)
社長だけが 承認済み・差し戻し にする(秘書ハブのボタン)。申請・販売開始は社長が LINE Creators Market で行う。
"""
import datetime
import re
from pathlib import Path
from typing import List, Optional

import company
import content

STATUSES = ["下書き", "承認待ち", "承認済み", "差し戻し", "申請した", "販売中", "リジェクト"]
KINDS = {"stamp": "スタンプ", "emoji": "絵文字"}
IMG_EXT = {".png", ".jpg", ".jpeg", ".webp"}
ID_RE = re.compile(r"^[0-9A-Za-z_-]{3,60}$")


def root() -> Path:
    return company.COMPANY_DIR / "content" / "stamps"


def _images(sid: str) -> List[dict]:
    rel_dir = f"content/output/stamps/{sid}"
    seen = {}
    for base in [content.media_dir() and (content.media_dir() / "stamps" / sid), company.COMPANY_DIR / rel_dir]:
        if base and base.exists():
            for p in sorted(base.iterdir()):
                if p.suffix.lower() in IMG_EXT and p.name not in seen:
                    seen[p.name] = {"path": f"{rel_dir}/{p.name}", "name": p.name}
    return [seen[k] for k in sorted(seen)]


def _iso_week(d: str) -> str:
    try:
        y, w, _ = datetime.date.fromisoformat(d[:10]).isocalendar()
        return f"{y}-{w:02d}"
    except Exception:
        return ""


def _set(path: Path) -> dict:
    meta, body = content.parse(path.read_text())
    sid = path.parent.name
    imgs = _images(sid)
    return {"id": sid, "path": str(path.relative_to(company.COMPANY_DIR)), "kind": meta.get("kind", "stamp"),
            "kind_ja": KINDS.get(meta.get("kind", "stamp"), meta.get("kind", "")), "title": meta.get("title", sid),
            "theme": meta.get("theme", ""), "count": meta.get("count", ""), "status": meta.get("status", "下書き"),
            "created": meta.get("created", ""), "submitted": meta.get("submitted", ""), "on_sale": meta.get("on_sale", ""),
            "sale_url": meta.get("sale_url", ""), "account": meta.get("account", "main"),
            "sections": content.sections(body), "images": imgs,
            "main_image": next((i for i in imgs if "main" in i["name"].lower()), imgs[0] if imgs else None)}


def list_sets() -> dict:
    d = root()
    sets = [_set(p) for p in sorted(d.glob("*/_set.md"), reverse=True)] if d.exists() else []
    week = _iso_week(datetime.date.today().isoformat())
    this_week = {k: sum(1 for s in sets if s["kind"] == k and _iso_week(s["created"]) == week) for k in KINDS}
    counts = {}
    for s in sets:
        counts[s["status"]] = counts.get(s["status"], 0) + 1
    rev = company.read_revenue_all()
    month = datetime.date.today().strftime("%Y-%m")
    rrows = [r for r in rev if r["source"] == "line_creators"]
    return {"sets": sets, "week": week, "this_week": this_week, "target": {"stamp": 1, "emoji": 1}, "counts": counts,
            "revenue": {"source": "line_creators", "source_ja": company.REVENUE_SOURCE_JA.get("line_creators"), "rows": rrows[::-1][:30],
                        "month_total": sum(r["amount"] for r in rrows if r["date"].startswith(month)),
                        "all_total": sum(r["amount"] for r in rrows)}}


ACTIONS = {  # 社長のボタン → (今の状態として許すもの, 次の状態)
    "approve": (("承認待ち",), "承認済み"),
    "reject": (("承認待ち", "承認済み"), "差し戻し"),
    "submitted": (("承認済み", "リジェクト"), "申請した"),
    "line_rejected": (("申請した",), "リジェクト"),
    "on_sale": (("申請した", "承認済み"), "販売中"),
}


def decide(sid: str, action: str, comment: str = "", url: str = "") -> dict:
    if not ID_RE.match(sid or ""):
        raise ValueError("セットIDが正しくありません")
    path = root() / sid / "_set.md"
    if not path.exists():
        raise KeyError(f"{sid} が見つかりません")
    if action not in ACTIONS:
        raise ValueError("操作は " + " / ".join(ACTIONS) + " のどれかです")
    allowed, nxt = ACTIONS[action]
    meta, body = content.parse(path.read_text())
    cur = meta.get("status", "下書き")
    if cur not in allowed:
        raise ValueError(f"今の状態({cur})からは「{nxt}」にできません")
    today = datetime.date.today().isoformat()
    meta["status"] = nxt
    if action == "submitted":
        meta["submitted"] = today
    if action == "on_sale":
        meta["on_sale"] = today
        if url:
            if not url.startswith("https://"):
                raise ValueError("販売ページの URL は https:// から入れてください")
            meta["sale_url"] = url.strip()
    if comment.strip():
        label = {"reject": "社長コメント(差し戻し)", "line_rejected": "LINE の審査の結果(リジェクトの理由)"}.get(action, "社長コメント")
        body = body.rstrip() + f"\n\n## {label} {today}\n{comment.strip()}\n"
    path.write_text(content.dump(meta, body))
    return _set(path)
