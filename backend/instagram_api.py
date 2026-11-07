"""Instagram の数字を Meta 公式の Graph API で取る(ログイン・画面の自動操作はしない)。

できること(運用アカウントがプロアカウントで、Facebook ページとつながっていること):
- 他のプロアカウントのフォロワー数・投稿数・最近の投稿(種類・いいね・コメント)= Business Discovery
- ハッシュタグの人気投稿(週30タグまで。投稿者名は返らない)
- 自社アカウントのフォロワー数・投稿数

backend/.env:
  IG_ACCESS_TOKEN=   Graph API エクスプローラーで発行したトークン(短い期限のものでよい。秘書ハブが長期に交換して backend/data に保存)
  META_APP_ID=       Meta の開発者画面のアプリID(長期への交換に使う)
  META_APP_SECRET=   同じくアプリシークレット
  IG_USER_ID=        (任意)自社の Instagram ビジネスアカウントID。空なら自動で探す
手順は ai-company の playbooks/instagram_api_setup.md
"""
import datetime
import json
import os
import re
from pathlib import Path
from typing import Dict, List, Optional

import httpx

VERSION = os.getenv("META_GRAPH_VERSION", "v23.0").strip()
API = f"https://graph.facebook.com/{VERSION}"
CACHE = Path(__file__).resolve().parent / "data" / "meta_token.json"  # git に入らない場所


class IGError(Exception):
    pass


def token_status() -> str:
    c = _cache()
    if c.get("kind") == "page":
        return "期限なし(ページのトークン)"
    if c.get("expires"):
        return f"{c['expires'][:10]} まで"
    return "短い期限(約1時間。META_APP_ID と META_APP_SECRET を入れると長期にできます)" if c.get("token") else "未設定"


def configured() -> bool:
    return bool(os.getenv("IG_ACCESS_TOKEN", "").strip() or _cache().get("token"))


def _cache() -> dict:
    try:
        return json.loads(CACHE.read_text())
    except Exception:
        return {}


def _save_cache(d: dict):
    CACHE.parent.mkdir(exist_ok=True)
    CACHE.write_text(json.dumps(d, ensure_ascii=False))
    try:
        CACHE.chmod(0o600)
    except Exception:
        pass


async def _get(path: str, params: dict, token: Optional[str] = None) -> dict:
    params = {**params, "access_token": token or await access_token()}
    async with httpx.AsyncClient(timeout=30) as c:
        r = await c.get(f"{API}/{path.lstrip('/')}", params=params)
    data = r.json() if r.headers.get("content-type", "").startswith(("application/json", "text/javascript")) else {}
    if r.status_code >= 400 or "error" in data:
        err = (data.get("error") or {})
        msg = err.get("message") or r.text[:200]
        code = err.get("code")
        if code == 190:
            msg = "トークンの期限切れか無効です。Graph API エクスプローラーで発行し直して .env の IG_ACCESS_TOKEN を替えてください"
        elif code in (4, 17, 32, 613):
            msg = "Meta の利用回数の上限に達しました。1時間ほど待ってください"
        elif code == 10 or code == 200:
            msg = f"権限が足りません({msg})。トークンに instagram_basic・pages_show_list・pages_read_engagement・instagram_manage_insights を付けてください"
        raise IGError(msg)
    return data


async def access_token() -> str:
    """使うトークン。.env のものが変わっていれば、長期(約60日)に交換して保存する。期限が近ければ延長する"""
    env_tok = os.getenv("IG_ACCESS_TOKEN", "").strip()
    c = _cache()
    if env_tok and c.get("source") != env_tok[-12:]:
        c = {"token": env_tok, "source": env_tok[-12:], "expires": ""}
        c.update(await _exchange(env_tok))
        # 長期のユーザートークンから取ったページのトークンは期限が無い。それを使えば作り直しが要らない
        if c.get("expires"):
            try:
                found = await _find_ig(token=c["token"])
                c.update(ig_user_id=found["ig_user_id"], ig_username=found["ig_username"])
                if found.get("page_token"):
                    c.update(token=found["page_token"], expires="", kind="page")
            except IGError:
                pass
        _save_cache(c)
    elif c.get("expires") and c.get("kind") != "page":
        try:
            left = datetime.datetime.fromisoformat(c["expires"]) - datetime.datetime.now()
            if left < datetime.timedelta(days=10):
                c.update(await _exchange(c["token"]))
                _save_cache(c)
        except Exception:
            pass
    if not c.get("token"):
        raise IGError("IG_ACCESS_TOKEN が未設定です(手順: playbooks/instagram_api_setup.md)")
    return c["token"]


async def _exchange(tok: str) -> dict:
    app_id, secret = os.getenv("META_APP_ID", "").strip(), os.getenv("META_APP_SECRET", "").strip()
    if not (app_id and secret):
        return {}  # 交換できない(短い期限のまま使う)
    async with httpx.AsyncClient(timeout=30) as c:
        r = await c.get(f"{API}/oauth/access_token", params={"grant_type": "fb_exchange_token", "client_id": app_id,
                                                            "client_secret": secret, "fb_exchange_token": tok})
    d = r.json()
    if "access_token" not in d:
        return {}
    exp = datetime.datetime.now() + datetime.timedelta(seconds=int(d.get("expires_in") or 60 * 86400))
    return {"token": d["access_token"], "expires": exp.isoformat(timespec="seconds")}


async def _find_ig(token: Optional[str] = None) -> dict:
    """トークンから、つながった Instagram プロアカウントを探す。見つからなければ、何が見えたかを添えて IGError"""
    fields = "name,access_token,instagram_business_account{id,username},connected_instagram_account{id,username}"
    pages = (await _get("me/accounts", {"fields": fields, "limit": 100}, token=token)).get("data", [])
    for p in pages:
        ig = p.get("instagram_business_account") or p.get("connected_instagram_account")
        if not ig and p.get("access_token"):  # 一覧に出ないときは、ページのトークンでページ自身に聞く
            try:
                d = await _get(p["id"], {"fields": "instagram_business_account{id,username},connected_instagram_account{id,username}"}, token=p["access_token"])
                ig = d.get("instagram_business_account") or d.get("connected_instagram_account")
            except IGError:
                pass
        if ig:
            return {"ig_user_id": ig["id"], "ig_username": ig.get("username", ""), "page": p.get("name", ""), "page_token": p.get("access_token", "")}
    if not pages:
        # ページのトークンの場合は me がページ自身
        try:
            d = await _get("me", {"fields": "name,instagram_business_account{id,username},connected_instagram_account{id,username}"}, token=token)
            ig = d.get("instagram_business_account") or d.get("connected_instagram_account")
            if ig:
                return {"ig_user_id": ig["id"], "ig_username": ig.get("username", ""), "page": d.get("name", ""), "page_token": ""}
        except IGError:
            pass
        raise IGError("トークンから Facebook ページが1つも見えません。グラフAPIエクスプローラーでトークンを発行し直すとき、"
                      "確認画面で「Ai秘書セナ」のページにチェックを入れてください(pages_show_list の許可も必要)")
    names = "・".join(p.get("name", "?") for p in pages)
    raise IGError(f"見えているページ({names})に、Instagram のプロアカウントがつながっていません。"
                  "トークンを発行し直すとき、確認画面で Instagram の @アカウントにもチェックを入れてください(instagram_basic の許可も必要)")


async def my_ig_id() -> str:
    if os.getenv("IG_USER_ID", "").strip():
        return os.getenv("IG_USER_ID").strip()
    c = _cache()
    if c.get("ig_user_id"):
        return c["ig_user_id"]
    found = await _find_ig()
    c.update(ig_user_id=found["ig_user_id"], ig_username=found["ig_username"])
    if found.get("page_token") and c.get("kind") != "page" and c.get("expires"):
        c.update(token=found["page_token"], expires="", kind="page")  # 期限なしのページ用トークンに切り替える
    _save_cache(c)
    return c["ig_user_id"]


MEDIA_FIELDS = "caption,media_type,media_product_type,like_count,comments_count,timestamp,permalink"


async def me() -> dict:
    uid = await my_ig_id()
    return await _get(uid, {"fields": "username,followers_count,follows_count,media_count"})


def username_from(url: str) -> str:
    m = re.search(r"instagram\.com/([A-Za-z0-9._]+)", url or "")
    if not m or m.group(1) in ("p", "reel", "reels", "explore", "stories"):
        raise IGError("Instagram のプロフィール URL(https://www.instagram.com/ユーザー名/)を渡してください")
    return m.group(1)


async def discover(username: str, posts: int = 12) -> dict:
    """他のプロアカウントの公開データ。個人アカウントは取れない(Meta の仕様)"""
    uid = await my_ig_id()
    f = (f"business_discovery.username({username}){{username,name,biography,followers_count,follows_count,media_count,"
         f"media.limit({posts}){{{MEDIA_FIELDS}}}}}")
    try:
        d = await _get(uid, {"fields": f})
    except IGError as e:
        if "Invalid user id" in str(e) or "Cannot find User" in str(e) or "cannot be found" in str(e):
            raise IGError(f"{username} はプロアカウントではないか、見つかりません(個人アカウントは Meta の仕組みで取れません)")
        raise
    bd = d.get("business_discovery") or {}
    media = (bd.get("media") or {}).get("data", [])
    return {"username": bd.get("username", username), "name": bd.get("name", ""), "biography": bd.get("biography", ""),
            "followers": bd.get("followers_count"), "following": bd.get("follows_count"), "posts": bd.get("media_count"),
            "recent": [_media(m) for m in media]}


def _media(m: dict) -> dict:
    kind = "リール" if m.get("media_product_type") == "REELS" else {"CAROUSEL_ALBUM": "カルーセル", "VIDEO": "動画", "IMAGE": "画像"}.get(m.get("media_type"), m.get("media_type"))
    return {"kind": kind, "likes": m.get("like_count"), "comments": m.get("comments_count"), "at": (m.get("timestamp") or "")[:10],
            "url": m.get("permalink"), "caption": (m.get("caption") or "")[:300]}


async def hashtag_top(tag: str, limit: int = 15) -> List[dict]:
    """ハッシュタグの人気投稿(1週間に30タグまで)。投稿者名は返らない"""
    uid = await my_ig_id()
    h = await _get("ig_hashtag_search", {"user_id": uid, "q": tag.lstrip("#")})
    if not h.get("data"):
        return []
    hid = h["data"][0]["id"]
    d = await _get(f"{hid}/top_media", {"user_id": uid, "fields": MEDIA_FIELDS, "limit": limit})
    return [_media(m) for m in d.get("data", [])]


def summarize(acc: dict) -> dict:
    """投稿の種類ごとの平均反応と、反応が多い投稿上位3件"""
    by: Dict[str, List[int]] = {}
    for m in acc["recent"]:
        by.setdefault(m["kind"], []).append((m["likes"] or 0) + (m["comments"] or 0))
    top = sorted(acc["recent"], key=lambda m: (m["likes"] or 0) + (m["comments"] or 0), reverse=True)[:3]
    return {"mix": {k: {"件数": len(v), "平均反応": round(sum(v) / len(v))} for k, v in by.items()}, "top": top}


async def refresh_watched() -> dict:
    """監視中の Instagram 参考アカウントの数字を取り、台帳(CSV・Notion)と、部署が読む資料に書く"""
    import company
    import watch
    out_dir = company.COMPANY_DIR / "strategy" / "research" / "accounts" / "_api"
    out_dir.mkdir(parents=True, exist_ok=True)
    today = datetime.date.today().isoformat()
    ok, ng = [], []
    for row in watch.monitored():
        if row.get("platform") != "Instagram":
            continue
        try:
            acc = await discover(username_from(row["url"]))
        except IGError as e:
            ng.append(f"{row['account']}: {e}")
            continue
        s = summarize(acc)
        (out_dir / f"{acc['username']}.json").write_text(json.dumps({"checked": today, **acc, "summary": s}, ensure_ascii=False, indent=1), encoding="utf-8")
        upd = {"url": row["url"], "account": row.get("account") or acc["username"], "platform": "Instagram",
               "followers": acc["followers"], "posts": acc["posts"], "checked": today, "source": "Instagram Graph API(Business Discovery)",
               "patterns": " / ".join(f"{k} {v['件数']}件・平均反応{v['平均反応']}" for k, v in s["mix"].items())}
        watch.updates_dir().mkdir(parents=True, exist_ok=True)
        (watch.updates_dir() / f"{today}_api_{acc['username']}.json").write_text(json.dumps(upd, ensure_ascii=False), encoding="utf-8")
        ok.append(acc["username"])
    n = await watch.sync_updates()
    return {"ok": ok, "ng": ng, "synced": n}
