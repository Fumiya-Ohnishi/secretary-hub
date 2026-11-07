"""アカウントごとの管理(Instagram / X / Threads / note)。

1つの媒体について、プロフィールURL・フォロワー数の推移・投稿ごとの数字・改善点・運用ルールをまとめて返す。
- URL: ai-company/data/accounts.md
- フォロワー: ai-company/data/followers.csv
- 投稿ごとの数字: ai-company/data/insights_{ig,x,threads,note}.csv(列は data/README.md)
- 改善点: ai-company/data/improvements.md(媒体ごとの見出しの下に箇条書き)+ 修正ログのうちその媒体の行
- ルール: ai-company/playbooks/{instagram,x,threads,note}.md
"""
import csv
import datetime
import re
from pathlib import Path
from typing import Dict, List, Optional

import company

PLATFORMS = company.PLATFORMS
PLATFORM_JA = company.PLATFORM_JA
INSIGHTS = {  # ファイル名と列(date の次から)。data/README.md と同じ
    "instagram": ("insights_ig.csv", ["content_id", "format", "reach", "saves", "likes", "comments", "profile_visits", "follows"]),
    "x": ("insights_x.csv", ["content_id", "impressions", "likes", "reposts", "replies", "follows"]),
    "threads": ("insights_threads.csv", ["content_id", "views", "likes", "replies", "follows"]),
    "note": ("insights_note.csv", ["metric", "value"]),
}
COLUMN_JA = {"content_id": "投稿ID", "format": "形式", "reach": "リーチ", "saves": "保存", "likes": "いいね", "comments": "コメント",
             "profile_visits": "プロフィール訪問", "follows": "フォロー増", "impressions": "表示", "reposts": "リポスト",
             "replies": "返信", "views": "閲覧", "metric": "項目", "value": "値"}
# 修正ログの「対象」から媒体を見分ける言葉
KEYWORDS = {"instagram": ("Instagram", "インスタ", "リール", "カルーセル"), "x": ("X ", "X(", "Xの", "ツイート", "スレッド"),
            "threads": ("Threads",), "note": ("note",)}


def _data(name: str) -> Path:
    return company.COMPANY_DIR / "data" / name


def _check(platform: str):
    if platform not in PLATFORMS:
        raise ValueError(f"媒体は {' / '.join(PLATFORMS)} のどれかです")


def profile_url(platform: str) -> str:
    md = _data("accounts.md")
    if not md.exists():
        return ""
    for line in md.read_text().splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if line.startswith("|") and len(cells) > 1 and cells[0] == PLATFORM_JA[platform] and cells[1].startswith("http"):
            return cells[1]
    return ""


def read_insights(platform: str, limit: int = 30) -> List[dict]:
    name, _ = INSIGHTS[platform]
    path = _data(name)
    if not path.exists():
        return []
    with path.open(newline="") as f:
        rows = [r for r in csv.DictReader(f) if any((v or "").strip() for v in r.values())]
    return rows[-limit:][::-1]


def record_insight(platform: str, values: Dict[str, str], date: Optional[str] = None) -> dict:
    """投稿1本の数字を記録する(足りない列は空のまま)"""
    _check(platform)
    name, cols = INSIGHTS[platform]
    row = {"date": date or datetime.date.today().isoformat()}
    for c in cols:
        v = values.get(c, "")
        row[c] = str(v).strip() if v is not None else ""
    if not any(row[c] for c in cols):
        raise ValueError("記録する数字がありません")
    path = _data(name)
    new = not path.exists() or not path.read_text().strip()
    with path.open("a", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["date"] + cols)
        if new:
            w.writeheader()
        w.writerow(row)
    return row


IMPROVEMENTS = "improvements.md"


def read_improvements(platform: str) -> List[dict]:
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
        if m and cur == PLATFORM_JA[platform]:
            out.append({"date": m.group(1) or "", "text": m.group(2).strip()})
    return out[::-1]


def add_improvement(platform: str, text: str, date: Optional[str] = None) -> dict:
    """改善点を1行足す(媒体の見出しが無ければ作る)"""
    _check(platform)
    text = " ".join(text.split())
    if not text:
        raise ValueError("改善点が空です")
    date = date or datetime.date.today().isoformat()
    path = _data(IMPROVEMENTS)
    lines = path.read_text().splitlines() if path.exists() else [
        "# 改善点(アカウントごと。分析部の金曜の見直し・社長の気づき・差し戻しから)", ""]
    head = f"## {PLATFORM_JA[platform]}"
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


def playbook(platform: str) -> str:
    path = company.COMPANY_DIR / "playbooks" / f"{platform}.md"
    return path.read_text() if path.exists() else ""


def overview(platform: str) -> dict:
    _check(platform)
    series = company.read_followers().get(platform, [])
    _, cols = INSIGHTS[platform]
    return {
        "platform": platform, "name": PLATFORM_JA[platform], "url": profile_url(platform),
        "followers": series, "followers_latest": series[-1] if series else None,
        "insight_columns": [{"key": c, "label": COLUMN_JA.get(c, c)} for c in cols],
        "insights": read_insights(platform),
        "improvements": read_improvements(platform),
        "corrections": corrections_for(platform),
        "playbook": playbook(platform),
    }


def summary() -> List[dict]:
    f = company.read_followers()
    return [{"platform": p, "name": PLATFORM_JA[p], "url": profile_url(p),
             "followers_latest": (f.get(p) or [None])[-1]} for p in PLATFORMS]
