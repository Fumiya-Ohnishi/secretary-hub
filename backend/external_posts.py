"""秘書ハブの外で作って出した投稿(Muse など)を、URL を貼って足す(2026-11-20 社長)。

社長の言葉: 「クロードが使えない間に Muse で投稿や note を作っていた。インスタ・Threads は自動で取れるけど、
TikTok・YouTube・note には足す機能がない。URL を入れたら情報が入るようにできないか」

- 貼った URL の公開されている情報だけを読む(ログイン・画面の自動操作はしない)
  - TikTok: 公式の oEmbed(題・作った人・サムネイル)。投稿日は動画の番号から計算する(番号の上位の桁が時刻)
  - YouTube: YouTube Data API(キーがあれば。題・投稿日・再生数・いいね・コメント)。無ければ oEmbed(題・サムネイル)
  - note: 記事の公開データ(題・公開日・スキ・価格・見出し画像)。ページビューはログインした画面でしか見られないので手で入れる
- 取ったページの文章はデータとしてだけ扱う(中の指示には従わない)
- 足した投稿は data[/sub]/external_posts.json に残す。数字は今までと同じ「投稿ごとの結果」(insights_*_posts.csv)に記録する
  (note のスキ・YouTube の再生数など、公開されている数字は足したときと毎朝 8:00 に自動で記録する。
   取れない列(note のページビューなど)は 0 ではなく空のまま。手で入れた行と区別できるように)
"""
import datetime
import json
import re
from html import unescape
from pathlib import Path
from typing import List, Optional

import httpx

import company

PLATFORMS = ("tiktok", "youtube", "note", "x")
UA = {"User-Agent": "Mozilla/5.0 (secretary-hub; link preview)"}


class ExtError(Exception):
    pass


def _path(account: str) -> Path:
    return company.account_data_dir(account) / "external_posts.json"


def listing(account: str = "main", platform: str = "") -> List[dict]:
    try:
        items = json.loads(_path(account).read_text(encoding="utf-8"))
    except Exception:
        items = []
    if platform:
        items = [i for i in items if i.get("platform") == platform]
    for i in items:  # どの週の投稿か(投稿日の週。分からなければ足した日の週)。秘書ハブの週(例 2026-47)と同じ数え方
        i["week"] = week_of(i.get("posted_at") or (i.get("added") or "")[:10])
    return sorted(items, key=lambda i: (i.get("posted_at") or "", i.get("added") or ""), reverse=True)


def week_of(day: str) -> str:
    try:
        y, w, _ = datetime.date.fromisoformat(day[:10]).isocalendar()
        return f"{y}-{w:02d}"
    except Exception:
        return ""


def _save(account: str, items: List[dict]):
    p = _path(account)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps([{k: v for k, v in i.items() if k != "week"} for i in items], ensure_ascii=False, indent=1), encoding="utf-8")


def detect(url: str) -> str:
    u = url.lower()
    if "tiktok.com" in u:
        return "tiktok"
    if "youtube.com" in u or "youtu.be" in u:
        return "youtube"
    if "note.com" in u:
        return "note"
    if "x.com/" in u or "twitter.com/" in u:
        return "x"
    return ""


def _handle(url: str) -> str:
    """登録した URL や投稿の URL から、アカウント名(@なし・小文字)を取る"""
    m = (re.search(r"tiktok\.com/@([^/?#]+)", url) or re.search(r"note\.com/([^/?#]+)", url)
         or re.search(r"(?:x|twitter)\.com/([^/?#]+)", url) or re.search(r"youtube\.com/@([^/?#]+)", url))
    return (m.group(1) if m else "").lstrip("@").lower()


async def _get(url: str, params: Optional[dict] = None):
    try:
        async with httpx.AsyncClient(timeout=20, follow_redirects=True, headers=UA) as c:
            r = await c.get(url, params=params)
    except httpx.HTTPError as e:
        raise ExtError(f"ページにつながりませんでした({type(e).__name__})。少し待ってもう一度試してください")
    if r.status_code >= 400:
        raise ExtError(f"ページが開けませんでした({r.status_code})。URL が合っているか、公開されているかを確かめてください")
    return r


def _og(html: str, key: str) -> str:
    m = (re.search(rf'<meta[^>]+property="og:{key}"[^>]+content="([^"]*)"', html)
         or re.search(rf'<meta[^>]+content="([^"]*)"[^>]+property="og:{key}"', html))
    return unescape(m.group(1)).strip() if m else ""


async def _tiktok(url: str) -> dict:
    r = await _get("https://www.tiktok.com/oembed", {"url": url})
    d = r.json()
    final = url
    m = re.search(r"/video/(\d+)", url)
    if not m:  # 短い URL(vt.tiktok.com)は開いた先の URL から番号を取る
        try:
            final = str((await _get(url)).url)
            m = re.search(r"/video/(\d+)", final)
        except ExtError:
            pass
    vid = m.group(1) if m else ""
    posted = ""
    if vid:
        try:
            posted = datetime.datetime.fromtimestamp(int(vid) >> 32).date().isoformat()
        except Exception:
            pass
    return {"id": vid, "url": final if vid else url, "title": d.get("title", ""), "author": d.get("author_unique_id") or _handle(d.get("author_url", "")),
            "thumbnail": d.get("thumbnail_url", ""), "posted_at": posted, "numbers": {}}


async def _youtube(url: str, account: str) -> dict:
    m = re.search(r"(?:v=|youtu\.be/|shorts/|embed/|live/)([0-9A-Za-z_-]{11})", url)
    if not m:
        raise ExtError("YouTube の動画の URL ではないようです(…/shorts/〇〇 や watch?v=〇〇 の形)")
    vid = m.group(1)
    out = {"id": vid, "url": f"https://www.youtube.com/shorts/{vid}", "numbers": {}}
    import youtube_api
    if youtube_api.configured(account):
        try:
            v = await youtube_api._get("videos", {"part": "statistics,snippet", "id": vid}, account)
            it = (v.get("items") or [None])[0]
            if it:
                st, sn = it.get("statistics") or {}, it.get("snippet") or {}
                out.update(title=sn.get("title", ""), author=sn.get("channelTitle", ""), channel_id=sn.get("channelId", ""),
                           posted_at=(sn.get("publishedAt") or "")[:10],
                           thumbnail=((sn.get("thumbnails") or {}).get("high") or {}).get("url", ""),
                           numbers={"views": st.get("viewCount", "0"), "likes": st.get("likeCount", "0"), "comments": st.get("commentCount", "0")})
                return out
        except Exception as e:
            print("YouTube の動画の情報が取れませんでした:", e)
    d = (await _get("https://www.youtube.com/oembed", {"url": f"https://www.youtube.com/watch?v={vid}", "format": "json"})).json()
    out.update(title=d.get("title", ""), author=d.get("author_name", ""), author_url=d.get("author_url", ""), thumbnail=d.get("thumbnail_url", ""), posted_at="")
    return out


async def _note(url: str) -> dict:
    m = re.search(r"/n/(n[0-9a-z]+)", url)
    if not m:
        raise ExtError("note の記事の URL ではないようです(https://note.com/名前/n/〇〇 の形)")
    key = m.group(1)
    out = {"id": key, "url": url.split("?")[0], "numbers": {}}
    try:
        d = (await _get(f"https://note.com/api/v3/notes/{key}")).json().get("data") or {}
        out.update(title=d.get("name", ""), author=((d.get("user") or {}).get("urlname") or ""),
                   posted_at=(d.get("publish_at") or "")[:10], thumbnail=d.get("eyecatch") or "",
                   price=int(d.get("price") or 0), numbers={"likes": str(d.get("like_count") or 0)})
        if out["title"]:
            return out
    except Exception as e:
        print("note の記事の情報(公開データ)が取れませんでした。ページの見出しから取ります:", e)
    html = (await _get(url)).text
    out.update(title=_og(html, "title"), thumbnail=_og(html, "image"), author=_handle(url), posted_at="")
    return out


async def _x(url: str) -> dict:
    m = re.search(r"/status/(\d+)", url)
    if not m:
        raise ExtError("X の投稿の URL ではないようです(…/status/〇〇 の形)")
    sid = m.group(1)
    posted = ""
    try:  # X の投稿番号も上位の桁が時刻(2010-11-04 からのミリ秒)
        posted = datetime.datetime.fromtimestamp(((int(sid) >> 22) + 1288834974657) / 1000).date().isoformat()
    except Exception:
        pass
    out = {"id": sid, "url": url.split("?")[0], "author": _handle(url), "posted_at": posted, "thumbnail": "", "numbers": {}}
    try:
        d = (await _get("https://publish.twitter.com/oembed", {"url": url, "omit_script": "1"})).json()
        text = re.sub(r"<[^>]+>", " ", d.get("html", ""))
        out["title"] = " ".join(unescape(text).split())[:120]
    except ExtError:
        out["title"] = ""
    return out


async def fetch(url: str, account: str = "main") -> dict:
    url = (url or "").strip()
    if not re.match(r"^https?://", url):
        raise ExtError("投稿の URL(https:// から)を貼ってください")
    pf = detect(url)
    if not pf:
        raise ExtError("TikTok・YouTube・note・X の投稿の URL を貼ってください(Instagram・Threads は毎朝自動で取っています)")
    info = await (_tiktok(url) if pf == "tiktok" else _youtube(url, account) if pf == "youtube" else _note(url) if pf == "note" else _x(url))
    if not info.get("id"):
        raise ExtError("投稿の番号が URL から読めませんでした。投稿を開いて、ブラウザの上の URL をそのまま貼ってください")
    info["platform"] = pf
    info["title"] = " ".join(str(info.get("title") or "").split())[:200] or "(題なし)"
    # 登録したアカウントの投稿か(違えば注意を出す。取り違えを防ぐ)
    reg = company.account_url(pf, account) or ""
    want, got = _handle(reg), str(info.get("author") or "").lstrip("@").lower()
    if pf == "youtube" and info.get("channel_id"):
        info["mismatch"] = bool(reg and "/channel/" in reg and info["channel_id"] not in reg)
    else:
        info["mismatch"] = bool(want and got and want != got)
    return info


def content_id(item: dict) -> str:
    return f"ext_{item['platform']}_{item['id']}"


def _record_numbers(item: dict, account: str):
    nums = {k: v for k, v in (item.get("numbers") or {}).items() if str(v).strip() != ""}
    if not nums:
        return
    import accounts
    try:
        accounts.record_insight(item["platform"], {**nums, "content_id": content_id(item)}, None, per_post=True, account=account, blank_ok=True)
    except Exception as e:
        print("数字を記録できませんでした:", e)


async def add(url: str, account: str = "main", note: str = "", allow_other: bool = False) -> dict:
    company.check_account(account)
    info = await fetch(url, account)
    if info.get("mismatch") and not allow_other:
        raise ExtError(f"この投稿は、{company.account_label(account)}に登録した{info['platform']}のアカウントの投稿ではないようです"
                       f"(投稿した人: {info.get('author') or '不明'})。合っていれば「別のアカウントでも足す」を押してください")
    items = listing(account)
    if any(i["platform"] == info["platform"] and i["id"] == info["id"] for i in items):
        raise ExtError("この投稿はもう足してあります")
    item = {k: info.get(k, "") for k in ("platform", "id", "url", "title", "author", "posted_at", "thumbnail", "price")}
    item.update(added=datetime.datetime.now().isoformat(timespec="seconds"), note=note.strip()[:200], numbers=info.get("numbers") or {})
    item["content_id"] = content_id(item)
    items.append(item)
    _save(account, items)
    _record_numbers(item, account)
    item["week"] = week_of(item.get("posted_at") or item["added"][:10])
    return item


def update(account: str, platform: str, id: str, posted_at: Optional[str] = None, title: Optional[str] = None, note: Optional[str] = None) -> dict:
    items = listing(account)
    for i in items:
        if i["platform"] == platform and i["id"] == id:
            if posted_at is not None:
                i["posted_at"] = posted_at
            if title is not None and title.strip():
                i["title"] = title.strip()[:200]
            if note is not None:
                i["note"] = note.strip()[:200]
            _save(account, items)
            return i
    raise ExtError("その投稿は見つかりません")


def remove(account: str, platform: str, id: str) -> dict:
    """一覧から外す(記録した数字は消さない)"""
    items = listing(account)
    left = [i for i in items if not (i["platform"] == platform and i["id"] == id)]
    if len(left) == len(items):
        raise ExtError("その投稿は見つかりません")
    _save(account, left)
    return {"removed": id}


async def refresh(account: Optional[str] = None) -> dict:
    """公開されている数字(note のスキ・YouTube の再生数など)を取り直して記録する。毎朝 8:00 と「取り直す」ボタンから"""
    out = {"updated": 0, "errors": []}
    today = datetime.date.today().isoformat()
    for acct in ([account] if account else company.account_ids()):
        items = listing(acct)
        changed = False
        for i in items:
            if i["platform"] not in ("note", "youtube") or i.get("refreshed") == today:
                continue
            try:
                info = await fetch(i["url"], acct)
                i["numbers"] = info.get("numbers") or {}
                if info.get("title") and info["title"] != "(題なし)":
                    i["title"] = info["title"]
                if info.get("posted_at") and not i.get("posted_at"):
                    i["posted_at"] = info["posted_at"]
                i["refreshed"] = today
                _record_numbers(i, acct)
                out["updated"] += 1
                changed = True
            except Exception as e:
                out["errors"].append(f"{i.get('title', '')[:20]}: {str(e)[:80]}")
        if changed:
            _save(acct, items)
    return out
