"""note のマガジン(棚)の管理(2026-11-16 社長「どの記事をどのマガジンに入れるか・入れないか・新しく作るかが分かった方が管理しやすい。溜まったらさらに分類もできる」)。

- 正の一覧: 会社のフォルダの data/magazines.json(id・アカウント・名前・作った日・バナー・分ける目安)
- 記事の側: note の投稿ファイルの front matter に `magazine: 名前, 名前`(入れないときは `magazine: なし`)
- ここでは、マガジンごとの記事の数(公開済み・これから)と、社長がすること(作る・分ける)を出す
"""
import datetime
import json
from typing import Dict, List

import company

NONE_WORDS = ("なし", "入れない", "-", "none")
PUBLIC = ("投稿済み",)
COMING = ("承認済み", "承認待ち", "投稿予定")
SPLIT_PAID = 4  # 有料記事がこの数そろったら、有料の棚を分ける(P-075)


def _path():
    return company.COMPANY_DIR / "data" / "magazines.json"


def registry() -> List[dict]:
    try:
        return json.loads(_path().read_text(encoding="utf-8"))
    except Exception:
        return []


def save(items: List[dict]):
    _path().write_text(json.dumps(items, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")


def names(value: str) -> List[str]:
    v = (value or "").strip()
    if not v or v.lower() in NONE_WORDS:
        return []
    return [x.strip() for x in v.replace("、", ",").split(",") if x.strip()]


def info_for(post_magazine: str, account: str) -> List[dict]:
    """投稿1本の「入れるマガジン」を、一覧と照らして返す(作ってあるか・一覧に無い新しい名前か)"""
    reg = {m["name"]: m for m in registry()}
    out = []
    for n in names(post_magazine):
        m = reg.get(n)
        out.append({"name": n, "known": bool(m), "created": bool(m and m.get("created")),
                    "id": m["id"] if m else "", "other_account": bool(m and m.get("account") != account)})
    return out


def overview(account: str = "") -> Dict:
    """マガジンごとの記事の数と、社長がすること。account を渡すとそのアカウントだけ"""
    import content
    posts = []
    for w in content.list_weeks():
        try:
            posts += [p for p in content.get_week(w["week"])["posts"] if p.get("platform") == "note"]
        except Exception:
            continue
    reg = [m for m in registry() if not account or m.get("account") == account]
    rows, todo = [], []
    for m in reg:
        mine = [p for p in posts if m["name"] in names(p.get("magazine", ""))]
        pub = [p for p in mine if p["status"] in PUBLIC]
        coming = [p for p in mine if p["status"] in COMING]
        paid = [p for p in mine if str(p.get("price") or "0").strip() not in ("", "0")]
        row = {**m, "public": len(pub), "coming": len(coming), "paid": len(paid),
               "posts": [{"id": p["id"], "title": p["title"], "status": p["status"], "week": p.get("week", ""), "file": p["file"]} for p in mine]}
        if not m.get("created") and (pub or coming):
            todo.append({"kind": "create", "magazine": m["name"], "text": f"「{m['name']}」を note で作って、記事を入れる(入れる記事 {len(pub) + len(coming)}本)"})
        if m.get("account") != "main" and len(paid) >= SPLIT_PAID and "有料" not in m["name"]:
            todo.append({"kind": "split", "magazine": m["name"], "text": f"「{m['name']}」の有料記事が{len(paid)}本そろった。有料の棚を分ける時期(P-075)"})
        rows.append(row)
    known = {m["name"] for m in registry()}
    loose = [p for p in posts if (not account or p.get("account") == account)
             and p["status"] in PUBLIC + COMING and not (p.get("magazine") or "").strip()]
    for p in loose:
        todo.append({"kind": "unset", "magazine": "", "text": f"{p['id']}「{p['title'][:30]}」の入れるマガジンが決まっていない"})
    unknown = sorted({n for p in posts for n in names(p.get("magazine", "")) if n not in known})
    for n in unknown:
        todo.append({"kind": "new", "magazine": n, "text": f"新しいマガジン「{n}」が投稿に書かれている(一覧に無い。作るなら名前・説明・バナーをそろえる)"})
    return {"magazines": rows, "todo": todo}


def mark_created(mag_id: str, created: bool = True) -> dict:
    items = registry()
    for m in items:
        if m["id"] == mag_id:
            m["created"] = datetime.date.today().isoformat() if created else ""
            save(items)
            return m
    raise KeyError("そのマガジンは一覧にありません")
