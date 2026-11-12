"""公式の仕組み(API)で取れる数字を、アカウントごとに自動で記録する(2026-11-12 社長の指示)。

- Instagram(Meta Graph API)・Threads(Threads API)・YouTube(YouTube Data API)
- 本アカウント(main)と別アカウント(sub)をそれぞれ。つないだもの(.env にトークン・キーがあるもの)だけ取る
- フォロワー数 → data[/sub]/followers.csv(いつものグラフ)
- 投稿ごとの数字(閲覧数など) → data[/sub]/auto_{媒体}.csv(取った日ごとの記録。同じ日・同じ投稿は上書き)
- X・note・TikTok は公式の無料の仕組みで数字が取れないので、今までどおり社長が入力する
ログイン・画面の自動操作はしない。トークン・キーは backend/.env にだけ置く。
"""
import csv
import datetime
import json
from pathlib import Path
from typing import Dict, List

import company

STATE = Path(__file__).resolve().parent / "data" / "stats_sync.json"
AUTO_PLATFORMS = ("instagram", "threads", "youtube")
BASE_COLS = ["date", "media_id", "content_id", "posted_at", "kind", "url", "caption"]
METRIC_COLS = {
    "instagram": ["views", "reach", "likes", "comments", "saved", "shares", "total_interactions"],
    "threads": ["views", "likes", "replies", "reposts", "quotes", "shares"],
    "youtube": ["views", "likes", "comments", "watch_hours", "avg_view_sec", "avg_view_pct", "stayed_rate", "subscribers_gained"],
}
METRIC_JA = {"views": "閲覧数", "reach": "リーチ", "likes": "いいね", "comments": "コメント", "saved": "保存", "shares": "シェア",
             "total_interactions": "反応の合計", "replies": "返信", "reposts": "再投稿", "quotes": "引用",
             "watch_hours": "総再生時間(時間)", "avg_view_sec": "平均視聴時間(秒)", "avg_view_pct": "平均再生率(%)",
             "stayed_rate": "視聴を継続(%)※計算", "subscribers_gained": "登録者の増加"}


def auto_csv(platform: str, account: str = "main") -> Path:
    return company.account_data_dir(account) / f"auto_{platform}.csv"


def _state() -> dict:
    try:
        return json.loads(STATE.read_text())
    except Exception:
        return {}


def _save_state(d: dict):
    STATE.parent.mkdir(exist_ok=True)
    STATE.write_text(json.dumps(d, ensure_ascii=False, indent=1))


def configured(platform: str, account: str = "main") -> bool:
    if platform == "instagram":
        import instagram_api
        return instagram_api.configured(account)
    if platform == "threads":
        import threads_api
        return threads_api.configured(account)
    if platform == "youtube":
        import youtube_api
        import accounts
        return youtube_api.configured() and bool(accounts.profile_url("youtube", account))
    return False


async def _fetch(platform: str, account: str):
    """(フォロワー数, 投稿ごとの数字の一覧)"""
    if platform == "instagram":
        import instagram_api
        m = await instagram_api.me(account)
        return m.get("followers_count"), await instagram_api.my_media(account), m.get("username", "")
    if platform == "threads":
        import threads_api
        m = await threads_api.me(account)
        return m.get("followers_count"), await threads_api.my_posts(account), m.get("username", "")
    if platform == "youtube":
        import youtube_api
        import accounts
        url = accounts.profile_url("youtube", account)
        ch = await youtube_api.channel(url)
        items = await youtube_api.my_videos(url)
        import youtube_analytics  # 2026-11-12: 許可があれば、総再生時間・平均視聴時間・視聴を継続(計算)も足す
        if youtube_analytics.configured(account):
            try:
                an = await youtube_analytics.per_video(account)
                for it in items:
                    it.update({k: v for k, v in (an.get(it["media_id"]) or {}).items() if v is not None})
            except youtube_analytics.YTAError as e:
                print("YouTube アナリティクスでエラー:", e)
        return ch.get("followers_count"), items, ch.get("title", "")
    raise ValueError(platform)


def _content_ids(platform: str, account: str) -> Dict[str, List[str]]:
    """投稿済みの当社の投稿: {投稿した日: [投稿ID]}(API の投稿と結びつけるため)"""
    import content
    out: Dict[str, List[str]] = {}
    import re
    try:
        for p in content.all_posts():
            if (p.get("account") or "main") != account:
                continue
            if p.get("platform") == platform and p.get("posted"):
                out.setdefault(p["posted"][:10], []).append(p["id"])
            elif platform in ("youtube", "tiktok"):  # リールを YouTube・TikTok にも出した記録(also_posted: youtube 2026-11-10)
                meta, _ = content.parse((company.COMPANY_DIR / p["path"]).read_text())
                m = re.search(platform + r"\s*(\d{4}-\d{2}-\d{2})", meta.get("also_posted", ""), re.I)
                if m:
                    out.setdefault(m.group(1), []).append(p["id"])
    except Exception:
        pass
    return out


def _write(platform: str, account: str, items: List[dict], today: str):
    path = auto_csv(platform, account)
    cols = BASE_COLS + METRIC_COLS[platform]
    rows = []
    if path.exists():
        with path.open(newline="") as f:
            rows = [r for r in csv.DictReader(f)]
    ids = {i["media_id"] for i in items}
    rows = [r for r in rows if not (r.get("date") == today and r.get("media_id") in ids)]
    by_day = _content_ids(platform, account)
    for it in items:
        cands = by_day.get(it.get("posted_at", ""), [])
        rows.append({"date": today, "content_id": cands[0] if len(cands) == 1 else "", **{c: it.get(c, "") for c in cols if c not in ("date", "content_id")},
                     "caption": " ".join(str(it.get("caption") or "").split())[:120]})
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow({c: ("" if r.get(c) is None else r.get(c, "")) for c in cols})


async def run(only: str = "") -> dict:
    """つないだアカウント・媒体の数字を全部取る。結果は stats_sync.json に残す(診断と画面で見る)"""
    import accounts
    today = datetime.date.today().isoformat()
    st = _state()
    out = {}
    for account in company.account_ids():
        for platform in AUTO_PLATFORMS:
            key = f"{account}:{platform}"
            if only and only not in (key, account, platform):
                continue
            if not configured(platform, account):
                out[key] = st[key] = {"ok": False, "connected": False, "at": "", "detail": "未接続"}
                continue
            try:
                followers, items, name = await _fetch(platform, account)
                if followers is not None:
                    company.record_followers(platform, int(followers), today, account)
                _write(platform, account, items, today)
                out[key] = st[key] = {"ok": True, "connected": True, "at": datetime.datetime.now().isoformat(timespec="seconds"),
                                      "detail": f"{name}・フォロワー {followers if followers is not None else '非公開'}・投稿 {len(items)}本"}
            except Exception as e:
                out[key] = st[key] = {"ok": False, "connected": True, "at": datetime.datetime.now().isoformat(timespec="seconds"),
                                      "detail": str(e)[:200]}
    _save_state(st)
    return out


def analytics_status(platform: str, account: str) -> dict:
    if platform != "youtube":
        return {}
    try:
        import youtube_analytics
        return youtube_analytics.status(account)
    except Exception as e:
        return {"error": str(e)[:120]}


def latest(platform: str, account: str = "main", limit: int = 30) -> dict:
    """画面用: 投稿ごとの最新の数字(新しい投稿から)と、接続の状態"""
    st = _state().get(f"{account}:{platform}") or {}
    path = auto_csv(platform, account)
    rows: Dict[str, dict] = {}
    if path.exists():
        with path.open(newline="") as f:
            for r in csv.DictReader(f):
                if not rows.get(r["media_id"]) or r["date"] >= rows[r["media_id"]]["date"]:
                    rows[r["media_id"]] = r
    items = sorted(rows.values(), key=lambda r: r.get("posted_at", ""), reverse=True)[:limit]
    return {"supported": platform in AUTO_PLATFORMS, "connected": configured(platform, account) if platform in AUTO_PLATFORMS else False,
            "status": st, "analytics": analytics_status(platform, account), "columns": [{"key": c, "label": METRIC_JA.get(c, c)} for c in METRIC_COLS.get(platform, [])], "rows": items}
