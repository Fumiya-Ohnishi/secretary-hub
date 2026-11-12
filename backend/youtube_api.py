"""YouTube の数字を Google 公式の YouTube Data API で取る(APIキーだけ。ログインはしない。2026-11-12)。

backend/.env:
  YOUTUBE_API_KEY=   Google Cloud で作った「APIキー」(YouTube Data API v3 を有効にしたもの)
チャンネルは ai-company/data/accounts.md の URL(https://www.youtube.com/channel/UC... の形)から読む。
取れるもの: 登録者数(非公開にしていなければ)・総再生数・動画ごとの再生数・高評価・コメント数(どれも公開の数字)。
"""
import os
import re
from typing import List

import httpx

API = "https://www.googleapis.com/youtube/v3"


class YTError(Exception):
    pass


def configured() -> bool:
    return bool(os.getenv("YOUTUBE_API_KEY", "").strip())


def channel_id(url: str) -> str:
    m = re.search(r"youtube\.com/channel/(UC[0-9A-Za-z_-]{20,})", url or "")
    if not m:
        raise YTError("YouTube の URL は https://www.youtube.com/channel/UC… の形で台帳に入れてください(@名前の形では取れません)")
    return m.group(1)


async def _get(path: str, params: dict) -> dict:
    key = os.getenv("YOUTUBE_API_KEY", "").strip()
    if not key:
        raise YTError("YOUTUBE_API_KEY が未設定です(手順: playbooks/account_connect.md)")
    async with httpx.AsyncClient(timeout=30) as c:
        r = await c.get(f"{API}/{path}", params={**params, "key": key})
    try:
        d = r.json()
    except Exception:
        d = {}
    if r.status_code >= 400 or "error" in d:
        raise YTError(((d.get("error") or {}).get("message") or r.text[:200]))
    return d


async def channel(url: str) -> dict:
    d = await _get("channels", {"part": "statistics,contentDetails,snippet", "id": channel_id(url)})
    items = d.get("items") or []
    if not items:
        raise YTError("チャンネルが見つかりません(URL の UC… を確かめてください)")
    it = items[0]
    st = it.get("statistics") or {}
    return {"title": (it.get("snippet") or {}).get("title", ""),
            "followers_count": None if st.get("hiddenSubscriberCount") else int(st.get("subscriberCount") or 0),
            "views": int(st.get("viewCount") or 0), "videos": int(st.get("videoCount") or 0),
            "uploads": ((it.get("contentDetails") or {}).get("relatedPlaylists") or {}).get("uploads", "")}


async def my_videos(url: str, limit: int = 25) -> List[dict]:
    ch = await channel(url)
    if not ch["uploads"]:
        return []
    pl = await _get("playlistItems", {"part": "contentDetails", "playlistId": ch["uploads"], "maxResults": min(limit, 50)})
    ids = [x["contentDetails"]["videoId"] for x in pl.get("items", [])]
    if not ids:
        return []
    v = await _get("videos", {"part": "statistics,snippet", "id": ",".join(ids)})
    out = []
    for it in v.get("items", []):
        st, sn = it.get("statistics") or {}, it.get("snippet") or {}
        out.append({"media_id": it["id"], "posted_at": (sn.get("publishedAt") or "")[:10], "kind": "動画",
                    "url": f"https://www.youtube.com/shorts/{it['id']}", "caption": (sn.get("title") or "")[:300],
                    "views": int(st.get("viewCount") or 0), "likes": int(st.get("likeCount") or 0),
                    "comments": int(st.get("commentCount") or 0)})
    return out
