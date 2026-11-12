"""請け負い仕事の提案の記録(ランサーズ・ココナラ。2026-11-12 社長の指示)。

ai-company/data/proposals.csv に1件1行で残す。社長が秘書ハブで入力する(当社はサービスにログインしない)。
状態: 提案した → やりとり中 → 採用 / 不採用 → 納品した → 入金済み
「入金済み」で金額が確定したら、収益(revenue.csv)にも入れる(ボタン1つ。二重に入れない)。
"""
import csv
import datetime
from typing import List, Optional

import company

PATH = company.COMPANY_DIR / "data" / "proposals.csv"
COLS = ["id", "date", "service", "title", "url", "amount", "status", "status_date", "memo", "revenue_date"]
SERVICES = {"lancers": "ランサーズ", "coconala": "ココナラ"}
STATUSES = ["提案した", "やりとり中", "採用", "不採用", "納品した", "入金済み"]
WON = ("採用", "納品した", "入金済み")


def _read() -> List[dict]:
    if not PATH.exists():
        return []
    with PATH.open(newline="") as f:
        return [{c: (r.get(c) or "").strip() for c in COLS} for r in csv.DictReader(f) if (r.get("id") or "").strip()]


def _write(rows: List[dict]):
    PATH.parent.mkdir(parents=True, exist_ok=True)
    with PATH.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=COLS)
        w.writeheader()
        for r in rows:
            w.writerow({c: r.get(c, "") for c in COLS})


def _amount(v) -> str:
    v = str(v or "").replace(",", "").replace("円", "").strip()
    if not v:
        return ""
    if not v.isdigit():
        raise ValueError("金額は数字で入れてください(円)")
    return v


def summary(rows: Optional[List[dict]] = None, service: Optional[str] = None) -> dict:
    rows = [r for r in (rows if rows is not None else _read()) if not service or r["service"] == service]
    n = len(rows)
    won = [r for r in rows if r["status"] in WON]
    lost = [r for r in rows if r["status"] == "不採用"]
    decided = len(won) + len(lost)
    month = datetime.date.today().strftime("%Y-%m")
    return {
        "proposals": n, "this_month": sum(1 for r in rows if r["date"].startswith(month)),
        "won": len(won), "lost": len(lost), "waiting": n - decided,
        "win_rate": round(len(won) / decided * 100) if decided else None,
        "paid_total": sum(int(r["amount"] or 0) for r in rows if r["status"] == "入金済み"),
        "expected_total": sum(int(r["amount"] or 0) for r in rows if r["status"] in ("採用", "納品した")),
    }


def listing(service: Optional[str] = None) -> dict:
    rows = _read()
    shown = [r for r in rows if not service or r["service"] == service][::-1]
    for r in shown:
        r["service_ja"] = SERVICES.get(r["service"], r["service"])
    return {"rows": shown, "summary": summary(rows, service), "services": [{"id": k, "label": v} for k, v in SERVICES.items()],
            "statuses": STATUSES}


def add(service: str, title: str, url: str = "", amount="", memo: str = "", date: Optional[str] = None) -> dict:
    if service not in SERVICES:
        raise ValueError("サービスは ランサーズ か ココナラ です")
    title = " ".join((title or "").split())
    if not title:
        raise ValueError("案件名を入れてください")
    url = (url or "").strip()
    if url and not url.startswith("https://"):
        raise ValueError("URL は https:// から入れてください")
    rows = _read()
    nid = max([int(r["id"][2:]) for r in rows if r["id"].startswith("P-") and r["id"][2:].isdigit()] + [0]) + 1
    date = date or datetime.date.today().isoformat()
    row = {"id": f"P-{nid:03d}", "date": date, "service": service, "title": title, "url": url, "amount": _amount(amount),
           "status": "提案した", "status_date": date, "memo": " ".join((memo or "").split()), "revenue_date": ""}
    rows.append(row)
    _write(rows)
    return row


def update(pid: str, status: Optional[str] = None, amount=None, memo: Optional[str] = None) -> dict:
    rows = _read()
    for r in rows:
        if r["id"] == pid:
            if status is not None:
                if status not in STATUSES:
                    raise ValueError("状態は " + " / ".join(STATUSES) + " のどれかです")
                if r["status"] != status:
                    r["status"], r["status_date"] = status, datetime.date.today().isoformat()
            if amount is not None:
                r["amount"] = _amount(amount)
            if memo is not None:
                r["memo"] = " ".join(memo.split())
            _write(rows)
            return r
    raise KeyError(f"{pid} が見つかりません")


async def record_revenue(pid: str, amount=None, date: Optional[str] = None) -> dict:
    """入金済みの提案の金額を、収益(revenue.csv)に入れる。同じ提案は1回だけ"""
    rows = _read()
    r = next((x for x in rows if x["id"] == pid), None)
    if not r:
        raise KeyError(f"{pid} が見つかりません")
    if r["revenue_date"]:
        raise ValueError(f"{pid} はもう収益に入れてあります({r['revenue_date']})")
    if amount is not None and str(amount).strip():
        r["amount"] = _amount(amount)
    if not r["amount"]:
        raise ValueError("確定した金額を入れてください")
    if r["status"] != "入金済み":
        r["status"], r["status_date"] = "入金済み", datetime.date.today().isoformat()
    res = await company.record_revenue(int(r["amount"]), r["service"], date, f"{pid} {r['title'][:40]}")
    r["revenue_date"] = res["date"]
    _write(rows)
    return {"proposal": r, "revenue": res}
