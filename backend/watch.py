"""参考アカウント(競合・お手本)の台帳。

- 社長か秘書が URL を渡すと台帳に加え、経営戦略部に評価を頼む
- 台帳の控えは会社のリポジトリの data/watch_accounts.csv(Notion に繋がっていなくても残る)
- 正は Notion の「参考アカウント」DB と「参考アカウントのフォロワー記録」DB(NOTION_TOKEN があれば書く)
- 部署は評価・確認の結果を strategy/research/accounts/_updates/*.json に書く。秘書ハブが10分ごとに読み、
  台帳(CSV)と Notion に反映して _done/ へ移す(部署の作業から Notion へ直接は書かないため)
"""
import csv
import datetime
import json
import re
from pathlib import Path
from typing import Dict, List, Optional
from urllib.parse import urlparse

import company
import notion

WATCH_DB = "bb36b4c49295423f8f3eca0e0ae6c396"
FOLLOWER_DB = "699ba643f9024010acb2b52c7d3dbdd2"
FIELDS = ["url", "account", "platform", "found_by", "monitor", "rating", "followers", "checked", "notion_id", "added"]
RATINGS = {"S": "S 真似したい", "A": "A 参考になる", "B": "B 一部参考", "C": "C 参考外"}
HOSTS = {"instagram.com": "Instagram", "x.com": "X", "twitter.com": "X", "threads.net": "Threads", "threads.com": "Threads",
         "note.com": "note", "youtube.com": "YouTube", "youtu.be": "YouTube", "tiktok.com": "TikTok"}


def csv_path() -> Path:
    return company.COMPANY_DIR / "data" / "watch_accounts.csv"


def updates_dir() -> Path:
    return company.COMPANY_DIR / "strategy" / "research" / "accounts" / "_updates"


def platform_of(url: str) -> str:
    host = (urlparse(url).hostname or "").lower().removeprefix("www.").removeprefix("m.")
    return next((v for k, v in HOSTS.items() if host == k or host.endswith("." + k)), "その他")


def normalize(url: str) -> str:
    url = url.strip()
    if not re.match(r"^https?://", url):
        raise ValueError("https:// から始まる URL を渡してください")
    u = urlparse(url)
    path = re.sub(r"/+$", "", u.path)
    return f"https://{(u.hostname or '').lower().removeprefix('m.')}{path}/" if path else f"https://{(u.hostname or '').lower()}/"


def handle_of(url: str) -> str:
    parts = [p for p in urlparse(url).path.split("/") if p]
    return parts[0].lstrip("@") if parts else (urlparse(url).hostname or url)


def load() -> List[Dict[str, str]]:
    p = csv_path()
    if not p.exists():
        return []
    with p.open(newline="", encoding="utf-8") as f:
        return [dict(r) for r in csv.DictReader(f)]


def save(rows: List[Dict[str, str]]):
    p = csv_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, "") for k in FIELDS})


def find(rows: List[Dict[str, str]], url: str) -> Optional[Dict[str, str]]:
    n = normalize(url)
    return next((r for r in rows if normalize(r["url"]) == n), None)


def monitored() -> List[Dict[str, str]]:
    return [r for r in load() if r.get("monitor", "").lower() in ("y", "yes", "true", "1")]


def summary_text() -> str:
    rows = load()
    if not rows:
        return "- 参考アカウント: まだ0件(社長が URL を渡すと台帳に入れて評価する)"
    mon = sum(1 for r in rows if r.get("monitor", "").lower() in ("y", "yes", "true", "1"))
    return f"- 参考アカウント: {len(rows)}件(監視中 {mon}件。台帳 data/watch_accounts.csv と Notion「参考アカウント」。毎週月曜のリサーチで確認)"


# ---------- Notion ----------
def _rt(v: str) -> dict:
    return {"rich_text": [{"type": "text", "text": {"content": (v or "")[:1900]}}]}


async def _notion_find(url: str) -> Optional[str]:
    r = await notion._req("POST", f"/databases/{WATCH_DB}/query", json={"filter": {"property": "URL", "url": {"equals": url}}})
    res = r.get("results") or []
    return res[0]["id"] if res else None


async def _notion_upsert(row: Dict[str, str], extra: Optional[dict] = None, prev_followers: Optional[float] = None) -> str:
    props = {"アカウント": {"title": [{"type": "text", "text": {"content": row.get("account") or handle_of(row["url"])}}]},
             "URL": {"url": row["url"]}, "媒体": {"select": {"name": row.get("platform") or "その他"}},
             "監視": {"checkbox": row.get("monitor", "y").lower() in ("y", "yes", "true", "1")}}
    if row.get("found_by") in ("社長", "秘書"):
        props["見つけた人"] = {"select": {"name": row["found_by"]}}
    if row.get("rating") in RATINGS:
        props["評価"] = {"select": {"name": RATINGS[row["rating"]]}}
    if row.get("followers"):
        props["フォロワー"] = {"number": float(row["followers"])}
        if prev_followers is not None:
            props["前回フォロワー"] = {"number": prev_followers}
    if row.get("checked"):
        props["最終確認日"] = {"date": {"start": row["checked"]}}
    for key, name in (("genre", "ジャンル"), ("strengths", "長所"), ("weaknesses", "短所"), ("patterns", "よく伸びる投稿の型"),
                      ("diff", "当社との違い"), ("adopt", "取り入れること"), ("differentiate", "差別化"), ("memo", "メモ")):
        if extra and extra.get(key):
            props[name] = _rt(extra[key])
    pid = row.get("notion_id") or await _notion_find(row["url"])
    if pid:
        await notion._req("PATCH", f"/pages/{pid}", json={"properties": props})
    else:
        pid = (await notion._req("POST", "/pages", json={"parent": {"database_id": WATCH_DB}, "properties": props}))["id"]
    return pid


async def _notion_follower(pid: str, row: Dict[str, str], posts: Optional[float], source: str):
    props = {"記録": {"title": [{"type": "text", "text": {"content": f"{row.get('account') or handle_of(row['url'])} {row['checked']}"}}]},
             "アカウント": {"relation": [{"id": pid}]}, "日付": {"date": {"start": row["checked"]}},
             "フォロワー": {"number": float(row["followers"])}, "出典": _rt(source)}
    if posts is not None:
        props["投稿数"] = {"number": float(posts)}
    await notion._req("POST", "/pages", json={"parent": {"database_id": FOLLOWER_DB}, "properties": props})


# ---------- 追加 ----------
async def add(url: str, found_by: str = "社長", memo: str = "") -> Dict[str, str]:
    url = normalize(url)
    rows = load()
    row = find(rows, url)
    created = row is None
    if created:
        row = {"url": url, "account": handle_of(url), "platform": platform_of(url), "found_by": found_by if found_by in ("社長", "秘書") else "社長",
               "monitor": "y", "rating": "", "followers": "", "checked": "", "notion_id": "", "added": datetime.date.today().isoformat()}
        rows.append(row)
    else:
        row["monitor"] = "y"
    save(rows)
    row["notion"] = None
    if notion.configured():
        try:
            row["notion_id"] = await _notion_upsert(row, {"memo": memo} if memo else None)
            save(rows)
            row["notion"] = True
        except Exception as e:
            row["notion"] = str(e)
    row["created"] = created
    return row


def evaluation_instruction(row: Dict[str, str], memo: str = "") -> str:
    from scheduler import RESEARCH_RULES
    return (f"参考アカウントの評価: {row['url']}({row['platform']})。{('社長のメモ: ' + memo + '。') if memo else ''}"
            "競合アナリストが調べ、戦略部長が評価をまとめる。"
            "見ること: プロフィール(誰に・何を約束しているか)、フォロワー数・投稿数(公開ページで見える範囲)、"
            "最近のカルーセル・リールの型(1枚目/最初の3秒のフック、構成、文字の量、デザイン、頻度、キャプションと導線)、"
            "反応が多い投稿と少ない投稿の違い。"
            "評価: S=真似したい/A=参考になる/B=一部参考/C=参考外 と、長所・短所・よく伸びる投稿の型・当社(AI会社の実録・秘書セナ)との違い・"
            "取り入れること(型だけ)・差別化 を書く。"
            f"結果は strategy/research/accounts/{handle_of(row['url'])}.md(読み物)と、"
            "strategy/research/accounts/_updates/YYYY-MM-DD_<アカウント>.json に次のキーで保存する(秘書ハブが台帳と Notion に反映する): "
            '{"url","account","platform","followers","posts","checked","rating","genre","strengths","weaknesses","patterns","diff","adopt","differentiate","memo","monitor":true,"found_by","source"}。'
            "見えなかった数字は空にして、memo に「公開ページでは見えない」と書く(推測で埋めない)。" + RESEARCH_RULES)


# ---------- 部署の結果を反映 ----------
async def sync_updates() -> int:
    d = updates_dir()
    if not d.exists():
        return 0
    done = d.parent / "_done"
    rows, n = load(), 0
    for f in sorted(d.glob("*.json")):
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            url = normalize(data["url"])
        except Exception as e:
            print("参考アカウントの更新を読めませんでした:", f.name, e)
            continue
        row = find(rows, url)
        if row is None:
            row = {"url": url, "account": data.get("account") or handle_of(url), "platform": data.get("platform") or platform_of(url),
                   "found_by": data.get("found_by") or "秘書", "monitor": "y", "notion_id": "", "added": datetime.date.today().isoformat()}
            rows.append(row)
        prev = row.get("followers") or ""
        row["account"] = data.get("account") or row.get("account")
        if str(data.get("rating", ""))[:1] in RATINGS:
            row["rating"] = str(data["rating"])[:1]
        if data.get("followers") not in (None, ""):
            try:
                row["followers"] = str(int(float(str(data["followers"]).replace(",", ""))))
            except ValueError:
                pass
        row["checked"] = data.get("checked") or datetime.date.today().isoformat()
        if data.get("monitor") is False:
            row["monitor"] = "n"
        save(rows)
        if notion.configured():
            try:
                pf = float(prev) if prev and row.get("followers") and prev != row["followers"] else None
                row["notion_id"] = await _notion_upsert(row, data, pf)
                if row.get("followers") and (data.get("followers") not in (None, "")):
                    await _notion_follower(row["notion_id"], row, data.get("posts") or None, data.get("source") or "経営戦略部の確認")
                save(rows)
            except Exception as e:
                print("参考アカウントを Notion に書けませんでした:", e)
                continue  # 次回また試す
        done.mkdir(parents=True, exist_ok=True)
        f.replace(done / f.name)
        n += 1
    return n
