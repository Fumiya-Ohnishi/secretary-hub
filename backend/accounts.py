"""アカウントごとの管理(Instagram / X / Threads / note / TikTok / YouTube)。

1つの媒体について、プロフィールURL・フォロワー数の推移・投稿ごとの数字・改善点・運用ルールをまとめて返す。
- URL: ai-company/data/accounts.md
- フォロワー: ai-company/data/followers.csv
- 投稿ごとの数字: ai-company/data/insights_{ig,x,threads,note,tiktok,youtube}.csv(列は data/README.md)
- 改善点: ai-company/data/improvements.md(媒体ごとの見出しの下に箇条書き)+ 修正ログのうちその媒体の行
- ルール: ai-company/playbooks/{instagram,x,threads,note,tiktok,youtube}.md
"""
import csv
import datetime
import re
from pathlib import Path
from typing import Dict, List, Optional

import company

PLATFORMS = company.PLATFORMS
PLATFORM_JA = company.PLATFORM_JA
# アカウントの組は company.account_sets()(ai-company/data/account_sets.json)。どのアカウントも6媒体を並べ、
# URL が登録されていない媒体は「利用なし」(投稿を作らない。2026-11-12 社長)


INSIGHTS = {  # ファイル名と列(date の次から)。data/README.md と同じ
    "instagram": ("insights_ig.csv", ["content_id", "format", "reach", "saves", "likes", "comments", "profile_visits", "follows"]),
    "x": ("insights_x.csv", ["content_id", "impressions", "likes", "reposts", "replies", "follows"]),
    "threads": ("insights_threads.csv", ["content_id", "views", "likes", "replies", "follows"]),
    "note": ("insights_note.csv", ["metric", "value"]),
    # 2026-11-12 社長: TikTok・YouTube の画面で分かる「見られ方」も記録する(3秒の離脱の対策 P-032 に使う)
    "tiktok": ("insights_tiktok.csv", ["content_id", "views", "likes", "comments", "shares", "saves", "follows",
                                       "watch_time_sec", "avg_watch_sec", "full_watch_rate"]),
    "youtube": ("insights_youtube.csv", ["content_id", "views", "likes", "comments", "follows",
                                         "watch_hours", "stayed_rate"]),
}
COLUMN_JA = {"content_id": "投稿ID", "format": "形式", "reach": "リーチ", "saves": "保存", "likes": "いいね", "comments": "コメント",
             "profile_visits": "プロフィール訪問", "follows": "フォロー増", "impressions": "表示", "reposts": "リポスト",
             "replies": "返信", "views": "再生", "shares": "シェア", "metric": "項目", "value": "値",
             "watch_time_sec": "総再生時間(秒)", "avg_watch_sec": "平均視聴時間(秒)", "full_watch_rate": "フル視聴率(%)",
             "watch_hours": "総再生時間(時間)", "stayed_rate": "視聴を継続(%)"}
# 修正ログの「対象」から媒体を見分ける言葉
KEYWORDS = {"instagram": ("Instagram", "インスタ", "リール", "カルーセル"), "x": ("X ", "X(", "Xの", "ツイート", "スレッド"),
            "threads": ("Threads",), "note": ("note",),
            "tiktok": ("TikTok", "ティックトック"), "youtube": ("YouTube", "ショート", "Shorts")}


def _data(name: str, account: str = "main") -> Path:
    return company.account_data_dir(account) / name


def _check(platform: str, account: str = "main"):
    company.check_account(account)
    if platform not in PLATFORMS:
        raise ValueError(f"媒体は {' / '.join(PLATFORMS)} のどれかです")


def profile_url(platform: str, account: str = "main") -> str:
    return company.account_url(platform, account)


def read_insights(platform: str, limit: int = 30, account: str = "main") -> List[dict]:
    name, _ = INSIGHTS[platform]
    path = _data(name, account)
    if not path.exists():
        return []
    with path.open(newline="") as f:
        rows = [r for r in csv.DictReader(f) if any((v or "").strip() for v in r.values())]
    return rows[-limit:][::-1]


# 投稿ごとの結果(2026-11-10 社長: 投稿のところで結果を報告できるように)。note は媒体全体の数字(metric,value)と分けて、記事ごとの表を使う
POST_INSIGHTS = {**INSIGHTS, "note": ("insights_note_posts.csv", ["content_id", "views", "likes", "comments", "follows"])}
LABEL_BY_PLATFORM = {"threads": {"views": "閲覧"}, "x": {"impressions": "表示"}, "note": {"views": "ビュー", "likes": "スキ"},
                     "youtube": {"likes": "高評価", "follows": "登録者の増加"}, "instagram": {"follows": "フォロー増"}}


TEXT_COLS = ("content_id", "format", "metric")  # 数字ではない列(空でも 0 にしない)


def fill_zeros(account: str = "main") -> int:
    """手入力の数字の表(insights_*.csv・insights_note_posts.csv)の空欄を 0 にする(2026-11-12 社長)。
    自動で取った数字(auto_*.csv)の空欄は「公式に取れない」の意味なので触らない"""
    files = {n: c for n, c in INSIGHTS.values()}
    files.update({n: c for n, c in POST_INSIGHTS.values()})
    changed = 0
    for name in sorted(files):
        path = _data(name, account)
        if not path.exists():
            continue
        with path.open(newline="") as f:
            rd = csv.DictReader(f)
            cols = rd.fieldnames or []
            rows = list(rd)
        n = 0
        want = ["date"] + files[name]
        if cols != want and set(cols) <= set(want):  # 列が増えたとき(2026-11-12 TikTok・YouTube)は、表の頭をそろえる
            cols = want
            n += 1
        for r in rows:
            if not any((r.get(c) or "").strip() for c in cols):
                continue
            for c in cols:
                if c not in TEXT_COLS and c != "date" and not (r.get(c) or "").strip():
                    r[c] = "0"
                    n += 1
        if n:
            with path.open("w", newline="") as f:
                w = csv.DictWriter(f, fieldnames=cols)
                w.writeheader()
                w.writerows(rows)
            changed += n
    return changed


def label(platform: str, col: str) -> str:
    return LABEL_BY_PLATFORM.get(platform, {}).get(col) or COLUMN_JA.get(col, col)


def post_results(platform: str, content_id: str, account: str = "main") -> dict:
    """1本の投稿の結果(新しい順)と、入力する列"""
    _check(platform, account)
    name, cols = POST_INSIGHTS[platform]
    path = _data(name, account)
    rows = []
    if path.exists():
        with path.open(newline="") as f:
            rows = [r for r in csv.DictReader(f) if (r.get("content_id") or "").strip() == content_id]
    return {"platform": platform, "content_id": content_id,
            "columns": [{"key": c, "label": label(platform, c)} for c in cols if c not in ("content_id", "format")],
            "results": rows[::-1]}


TIME_RE = re.compile(r"^\s*(?:(\d+(?:\.\d+)?)\s*(?:h|時間))?\s*:?\s*(?:(\d+(?:\.\d+)?)\s*(?:m|分))?\s*:?\s*(?:(\d+(?:\.\d+)?)\s*(?:s|秒))?\s*$", re.I)


def to_seconds(value: str) -> str:
    """時間の書き方を秒の数に直す(2026-11-13 社長「0h:04m:04s はなんて打てばいい?」)。
    「0h:04m:04s」「4m4s」「4分4秒」「4:04」(分:秒)「1:02:30」(時:分:秒)「244」(秒)に対応。直せないときはそのまま返す"""
    v = (value or "").strip().replace("：", ":")
    if not v or re.fullmatch(r"\d+(?:\.\d+)?", v):
        return v
    if re.fullmatch(r"\d+(?::\d+){1,2}", v):  # 4:04 / 1:02:30
        parts = [int(x) for x in v.split(":")]
        while len(parts) < 3:
            parts.insert(0, 0)
        return str(parts[0] * 3600 + parts[1] * 60 + parts[2])
    m = TIME_RE.match(v)
    if m and any(m.groups()):
        h, mi, se = (float(x) if x else 0.0 for x in m.groups())
        total = h * 3600 + mi * 60 + se
        return str(int(total)) if total == int(total) else str(round(total, 1))
    return v


def _normalize(col: str, value: str) -> str:
    """秒・時間の列は、時間の書き方で入れても数に直す"""
    if col.endswith("_sec"):
        return to_seconds(value)
    if col.endswith("_hours") and value and not re.fullmatch(r"\s*\d+(?:\.\d+)?\s*", value):
        sec = to_seconds(value)
        return str(round(float(sec) / 3600, 2)) if re.fullmatch(r"\d+(?:\.\d+)?", sec) else value
    return value


def record_insight(platform: str, values: Dict[str, str], date: Optional[str] = None, per_post: bool = False,
                   account: str = "main") -> dict:
    """投稿1本の数字を記録する(足りない列は空のまま)"""
    _check(platform, account)
    name, cols = (POST_INSIGHTS if per_post else INSIGHTS)[platform]
    row = {"date": date or datetime.date.today().isoformat()}
    for c in cols:
        v = values.get(c, "")
        row[c] = _normalize(c, str(v).strip()) if v is not None else ""
        if c not in TEXT_COLS and not row[c]:
            row[c] = "0"  # 2026-11-12 社長: 変わらなかった(入れなかった)数字は 0 で記録する
    if "metric" in cols and not row.get("metric"):
        raise ValueError("項目(metric)を入れてください")
    if per_post and not row.get("content_id"):
        raise ValueError("投稿IDがありません")
    path = _data(name, account)
    path.parent.mkdir(parents=True, exist_ok=True)
    new = not path.exists() or not path.read_text().strip()
    with path.open("a", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["date"] + cols)
        if new:
            w.writeheader()
        w.writerow(row)
    return row


IMPROVEMENTS = "improvements.md"


def _improve_head(platform: str, account: str = "main") -> str:
    if account == "main":
        return PLATFORM_JA[platform]
    return f"別アカウント {PLATFORM_JA[platform]}" if account == "sub" else f"{company.account_label(account)} {PLATFORM_JA[platform]}"


def read_improvements(platform: str, account: str = "main") -> List[dict]:
    path = _data(IMPROVEMENTS)
    if not path.exists():
        return []
    out, cur = [], None
    for line in path.read_text().splitlines():
        m = re.match(r"^##\s+(.+)", line)
        if m:
            cur = m.group(1).strip()
            continue
        m = re.match(r"^-\s+(?:(\d{4}-\d{2}-\d{2})\s+)?(.+)", line)
        if m and cur == _improve_head(platform, account):
            out.append({"date": m.group(1) or "", "text": m.group(2).strip()})
    return out[::-1]


def add_improvement(platform: str, text: str, date: Optional[str] = None, account: str = "main") -> dict:
    """改善点を1行足す(媒体の見出しが無ければ作る)"""
    _check(platform, account)
    text = " ".join(text.split())
    if not text:
        raise ValueError("改善点が空です")
    date = date or datetime.date.today().isoformat()
    path = _data(IMPROVEMENTS)
    lines = path.read_text().splitlines() if path.exists() else [
        "# 改善点(アカウントごと。分析部の金曜の見直し・社長の気づき・差し戻しから)", ""]
    head = f"## {_improve_head(platform, account)}"
    if head not in lines:
        lines += ["", head]
    i = lines.index(head) + 1
    while i < len(lines) and not lines[i].startswith("## "):
        i += 1
    while i > 0 and not lines[i - 1].strip():  # 見出しの塊の最後の行のすぐ後ろへ
        i -= 1
    lines.insert(i, f"- {date} {text}")
    path.write_text("\n".join(lines).rstrip() + "\n")
    return {"date": date, "text": text}


def corrections_for(platform: str, limit: int = 10) -> List[dict]:
    path = _data("corrections.md")
    if not path.exists():
        return []
    out = []
    for line in path.read_text().splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if not line.startswith("|") or len(cells) < 4 or not re.match(r"\d{4}-\d{2}-\d{2}", cells[0]):
            continue
        if any(k in cells[1] + " " for k in KEYWORDS[platform]):
            out.append({"date": cells[0], "target": cells[1], "text": cells[2], "by": cells[3]})
    return out[-limit:][::-1]


def playbook(platform: str, account: str = "main") -> str:
    """ルール。別アカウントは playbooks/sub/{媒体}.md があればそれ、無ければ本アカウントのルールを参考として返す"""
    if account != "main":
        sub = company.COMPANY_DIR / "playbooks" / account / f"{platform}.md"
        if sub.exists():
            return sub.read_text()
        base = company.COMPANY_DIR / "playbooks" / f"{platform}.md"
        return (f"({company.account_label(account)}用のルールはまだありません。playbooks/{account}/" + platform + ".md ができるとここに出ます。"
                "以下は本アカウントのルールで、参考です)\n\n" + (base.read_text() if base.exists() else ""))
    path = company.COMPANY_DIR / "playbooks" / f"{platform}.md"
    return path.read_text() if path.exists() else ""


def revenue_for(account: str, platform: str) -> dict:
    """その媒体の確定した収益(revenue.csv のうち出どころが合うもの)"""
    src = company.revenue_source(account, platform)
    rev = company.read_revenue_all()
    rows = [r for r in rev if r["source"] == src]
    month = datetime.date.today().strftime("%Y-%m")
    return {"source": src, "source_ja": company.REVENUE_SOURCE_JA.get(src, src), "rows": rows[::-1][:30],
            "month_total": sum(r["amount"] for r in rows if r["date"].startswith(month)),
            "all_total": sum(r["amount"] for r in rows)}


def overview(platform: str, account: str = "main") -> dict:
    _check(platform, account)
    series = company.read_followers(account).get(platform, [])
    _, cols = INSIGHTS[platform]
    return {
        "platform": platform, "account": account, "account_label": company.account_label(account),
        "name": PLATFORM_JA[platform], "url": profile_url(platform, account), "registered": bool(profile_url(platform, account)),
        "followers": series, "followers_latest": series[-1] if series else None,
        "insight_columns": [{"key": c, "label": COLUMN_JA.get(c, c)} for c in cols],
        "insights": read_insights(platform, account=account),
        "improvements": read_improvements(platform, account),
        "corrections": corrections_for(platform) if account == "main" else [],
        "playbook": playbook(platform, account),
        "crosspost": crosspost_candidates(platform) if platform in CROSSPOST and account == "main" else [],
        "revenue": revenue_for(account, platform),
        "auto": _auto(platform, account),
    }


def _auto(platform: str, account: str) -> dict:
    try:
        import stats_sync
        return stats_sync.latest(platform, account)
    except Exception as e:
        return {"supported": False, "connected": False, "status": {"detail": str(e)[:120]}, "columns": [], "rows": []}


def account_sets() -> List[dict]:
    return [{"id": x["id"], "label": x["label"], "note": x.get("note", ""),
             "registered": company.registered_platforms(x["id"])} for x in company.account_sets()]


def summary(account: str = "main") -> List[dict]:
    company.check_account(account)
    f = company.read_followers(account)
    return [{"platform": p, "name": PLATFORM_JA[p], "url": profile_url(p, account), "registered": bool(profile_url(p, account)),
             "followers_latest": (f.get(p) or [None])[-1]} for p in PLATFORMS]


# ---------- TikTok・YouTube に出すとよい投稿(2026-11-10 社長の指示) ----------
# 投稿ファイルの front matter:
#   crosspost: tiktok, youtube      … SNS運用部が「この媒体にも出すとよい」と決めた媒体(「なし」で候補から外す)
#   crosspost_note: 理由            … なぜ出すとよいか(社長が読む1行)
#   also_posted: tiktok 2026-11-10, youtube 2026-11-10 … 社長が投稿した記録(秘書ハブのボタンで書く)
# crosspost が無いリールも、承認済み・投稿済みなら「リールなのでそのまま出せる」候補として出す。
CROSSPOST = ("tiktok", "youtube")
READY = ("承認済み", "投稿済み")


def _list_field(v: str) -> List[str]:
    return [x.strip().lower() for x in re.split(r"[,、/\s]+", v or "") if x.strip()]


def _posted_on(also: str, platform: str) -> str:
    m = re.search(platform + r"\s*(\d{4}-\d{2}-\d{2})?", also or "", re.I)
    return (m.group(1) or "済み") if m else ""


def crosspost_candidates(platform: str) -> List[dict]:
    import content
    out = []
    root = content.drafts_dir()
    if not root.exists():
        return out
    for path in sorted(root.glob("*/*.md"), reverse=True):
        if path.name.startswith("_") or not content.WEEK_RE.match(path.parent.name):
            continue
        meta, _ = content.parse(path.read_text())
        cp = _list_field(meta.get("crosspost", ""))
        if "なし" in cp or "none" in cp:
            continue
        explicit = platform in cp
        is_reel = meta.get("format", "") == "reel"
        if not explicit and not (is_reel and meta.get("platform") == "instagram" and meta.get("status") in READY):
            continue
        post = content._post(path)
        posted = _posted_on(meta.get("also_posted", ""), platform)
        post.update({
            "week": path.parent.name,
            "recommended": explicit,
            "reason": meta.get("crosspost_note", "") or ("SNS運用部のおすすめ" if explicit else "承認済みのリール(縦長のまま出せる)"),
            "ready": meta.get("status") in READY,
            "posted_on": posted,
        })
        out.append(post)
    # まだ出していないもの → おすすめ → 新しい順
    out.sort(key=lambda p: (bool(p["posted_on"]), not p["recommended"], not p["ready"]))
    return out[:40]


def mark_crossposted(platform: str, rel: str, date: Optional[str] = None, undo: bool = False) -> dict:
    """社長が TikTok・YouTube に投稿した記録を、投稿ファイルの also_posted に書く(社長の操作からだけ呼ぶ)"""
    import content
    if platform not in CROSSPOST:
        raise ValueError("TikTok か YouTube だけです")
    path = content.safe_path(rel)
    if path.suffix != ".md" or not content.WEEK_RE.match(path.parent.name):
        raise ValueError("投稿ファイルではありません")
    meta, body = content.parse(path.read_text())
    if meta.get("status") not in READY:
        raise ValueError("承認済みの投稿だけ記録できます(未承認のものは出さない)")
    date = date or datetime.date.today().isoformat()
    items = [x.strip() for x in (meta.get("also_posted", "") or "").split(",") if x.strip() and not x.strip().lower().startswith(platform)]
    if not undo:
        items.append(f"{platform} {date}")
    meta["also_posted"] = ", ".join(items)
    path.write_text(content.dump(meta, body))
    return {"path": rel, "platform": platform, "date": None if undo else date, "undone": undo}
