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
# 規格(2026-11-12。第三者の解説で確かめた値。公式の制作ガイドラインで確かめ直す: ai-company/playbooks/line_stamps.md)
# スタンプは文字入りが前提・個数は 8/16/24/32/40 から選ぶ。絵文字は文字なしでよい
SPEC = {
    "stamp": {"counts": [8, 16, 24, 32, 40], "max": (370, 320), "exact": None, "main": (240, 240), "tab": (96, 74), "text": True},
    "emoji": {"counts": list(range(8, 41)), "max": None, "exact": (180, 180), "main": None, "tab": (96, 74), "text": False},
}
MAX_BYTES = 1024 * 1024


def _png_info(path: Path) -> Optional[dict]:
    """PNG の幅・高さ・透明の有無(ライブラリなしで頭だけ読む)"""
    try:
        b = path.read_bytes()
    except Exception:
        return None
    if b[:8] != b"\x89PNG\r\n\x1a\n":
        return {"png": False, "bytes": len(b)}
    w, h = int.from_bytes(b[16:20], "big"), int.from_bytes(b[20:24], "big")
    color = b[25]
    alpha = color in (4, 6) or b"tRNS" in b[:min(len(b), 4096)]
    return {"png": True, "w": w, "h": h, "alpha": alpha, "bytes": len(b)}


def _file(rel: str) -> Optional[Path]:
    try:
        return content.safe_path(rel)
    except Exception:
        return None


def check(kind: str, count: str, imgs: List[dict]) -> dict:
    """規格の点検(画面に ✓/✗ を出す)。main・tab の名前の画像はメイン画像・タブ画像として別に見る"""
    sp = SPEC.get(kind, SPEC["stamp"])
    problems = []
    try:
        n = int(count)
    except (TypeError, ValueError):
        n = 0
    if n not in sp["counts"]:
        problems.append(f"個数が規格外({count or '未設定'})。{KINDS.get(kind)}は " + ("8・16・24・32・40" if kind == "stamp" else "8〜40") + " から選ぶ")
    body = [i for i in imgs if not re.search(r"main|tab", i["name"], re.I)]
    if n and len(body) != n:
        problems.append(f"画像が {len(body)}枚(決めた個数は {n}個)")
    has_main = any(re.search(r"main", i["name"], re.I) for i in imgs)
    has_tab = any(re.search(r"tab", i["name"], re.I) for i in imgs)
    if sp["main"] and imgs and not has_main:
        problems.append("メイン画像(名前に main を入れる。240×240)が無い")
    if sp["tab"] and imgs and not has_tab:
        problems.append("タブ画像(名前に tab を入れる。96×74)が無い")
    for i in imgs:
        f = _file(i["path"])
        info = _png_info(f) if f else None
        i["check"] = ""
        if not info:
            continue
        bad = []
        if not info.get("png"):
            bad.append("PNG ではない")
        else:
            nm = i["name"].lower()
            if "main" in nm and sp["main"]:
                if (info["w"], info["h"]) != sp["main"]:
                    bad.append(f"{info['w']}×{info['h']}(メインは {sp['main'][0]}×{sp['main'][1]})")
            elif "tab" in nm and sp["tab"]:
                if (info["w"], info["h"]) != sp["tab"]:
                    bad.append(f"{info['w']}×{info['h']}(タブは {sp['tab'][0]}×{sp['tab'][1]})")
            elif sp["exact"] and (info["w"], info["h"]) != sp["exact"]:
                bad.append(f"{info['w']}×{info['h']}(絵文字は {sp['exact'][0]}×{sp['exact'][1]})")
            elif sp["max"] and (info["w"] > sp["max"][0] or info["h"] > sp["max"][1]):
                bad.append(f"{info['w']}×{info['h']}(最大 {sp['max'][0]}×{sp['max'][1]})")
            if not info["alpha"]:
                bad.append("背景が透明でない")
        if info["bytes"] > MAX_BYTES:
            bad.append(f"{info['bytes'] // 1024}KB(1MB まで)")
        i["check"] = "・".join(bad)
        if bad:
            problems.append(f"{i['name']}: " + "・".join(bad))
    return {"ok": not problems, "problems": problems, "needs_text": sp["text"], "counts": sp["counts"] if kind == "stamp" else [8, 40]}
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
    kind = meta.get("kind", "stamp")
    chk = check(kind, meta.get("count", ""), imgs)
    return {"id": sid, "check": chk, "path": str(path.relative_to(company.COMPANY_DIR)), "kind": meta.get("kind", "stamp"),
            "kind_ja": KINDS.get(meta.get("kind", "stamp"), meta.get("kind", "")), "title": meta.get("title", sid),
            "theme": meta.get("theme", ""), "count": meta.get("count", ""), "status": meta.get("status", "下書き"),
            "created": meta.get("created", ""), "submitted": meta.get("submitted", ""), "on_sale": meta.get("on_sale", ""),
            "sale_url": meta.get("sale_url", ""), "account": meta.get("account", "main"),
            "sections": content.sections(body), "images": imgs,
            "main_image": next((i for i in imgs if "main" in i["name"].lower()), imgs[0] if imgs else None)}


def list_sets(kind: Optional[str] = None) -> dict:
    d = root()
    all_sets = [_set(p) for p in sorted(d.glob("*/_set.md"), reverse=True)] if d.exists() else []
    sets = [x for x in all_sets if not kind or x["kind"] == kind]
    week = _iso_week(datetime.date.today().isoformat())
    this_week = {k: sum(1 for s in all_sets if s["kind"] == k and _iso_week(s["created"]) == week) for k in KINDS}
    counts = {}
    for s in sets:
        counts[s["status"]] = counts.get(s["status"], 0) + 1
    rev = company.read_revenue_all()
    month = datetime.date.today().strftime("%Y-%m")
    rrows = [r for r in rev if r["source"] == "line_creators"]
    return {"sets": sets, "kind": kind, "spec": {k: {"counts": v["counts"] if k == "stamp" else [8, 40], "text": v["text"]} for k, v in SPEC.items()},
            "week": week, "this_week": this_week, "target": {"stamp": 1, "emoji": 1}, "counts": counts,
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
