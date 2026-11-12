"""YouTube の分析の数字(総再生時間・平均視聴時間・視聴を継続など)を、YouTube Analytics API で取る(2026-11-12 社長の指示)。

- 最初に一度だけ、社長が Google の画面で「秘書ハブに分析の数字を読ませてよい」と許可する(OAuth)。パスワードは秘書ハブに渡らない
- 許可すると更新用の鍵(リフレッシュトークン)を backend/data/yt_oauth_{アカウント}.json に保存(git に入らない)。以後は毎朝自動
- Google Cloud のアプリは「本番」にしておく(「テスト中」のままだと鍵が7日で切れる)
- 読む権限だけ(yt-analytics.readonly・youtube.readonly)。投稿・編集の権限は付けない

backend/.env:
  YT_OAUTH_CLIENT_ID=      Google Cloud の「OAuth クライアント ID」(種類: ウェブ アプリケーション)
  YT_OAUTH_CLIENT_SECRET=  同じくクライアント シークレット
  承認済みのリダイレクト URI: http://localhost:8000/api/youtube/oauth/callback
手順は ai-company の playbooks/account_connect.md
"""
import datetime
import json
import os
import secrets
import urllib.parse
from pathlib import Path
from typing import Dict, List, Optional

import httpx

DATA_DIR = Path(__file__).resolve().parent / "data"
REDIRECT = os.getenv("YT_OAUTH_REDIRECT", "http://localhost:8000/api/youtube/oauth/callback")
SCOPES = "https://www.googleapis.com/auth/yt-analytics.readonly https://www.googleapis.com/auth/youtube.readonly"
_states: Dict[str, str] = {}  # state → account(許可の画面から戻ってきたときに、どのアカウントかを確かめる)


class YTAError(Exception):
    pass


def _client():
    cid, sec = os.getenv("YT_OAUTH_CLIENT_ID", "").strip(), os.getenv("YT_OAUTH_CLIENT_SECRET", "").strip()
    if not (cid and sec):
        raise YTAError("YT_OAUTH_CLIENT_ID と YT_OAUTH_CLIENT_SECRET が未設定です(手順: playbooks/account_connect.md)")
    return cid, sec


def _path(account: str) -> Path:
    return DATA_DIR / f"yt_oauth_{account}.json"


def _load(account: str) -> dict:
    try:
        return json.loads(_path(account).read_text())
    except Exception:
        return {}


def _save(account: str, d: dict):
    DATA_DIR.mkdir(exist_ok=True)
    _path(account).write_text(json.dumps(d, ensure_ascii=False))
    try:
        _path(account).chmod(0o600)
    except Exception:
        pass


def client_ready() -> bool:
    return bool(os.getenv("YT_OAUTH_CLIENT_ID", "").strip() and os.getenv("YT_OAUTH_CLIENT_SECRET", "").strip())


def configured(account: str = "main") -> bool:
    return client_ready() and bool(_load(account).get("refresh_token"))


def status(account: str = "main") -> dict:
    d = _load(account)
    return {"client": client_ready(), "connected": bool(d.get("refresh_token")), "since": d.get("since", ""),
            "channel": d.get("channel", ""), "error": d.get("error", "")}


def auth_url(account: str = "main") -> str:
    cid, _ = _client()
    state = secrets.token_urlsafe(16)
    _states[state] = account
    q = {"client_id": cid, "redirect_uri": REDIRECT, "response_type": "code", "scope": SCOPES,
         "access_type": "offline", "prompt": "consent", "include_granted_scopes": "true", "state": state}
    return "https://accounts.google.com/o/oauth2/v2/auth?" + urllib.parse.urlencode(q)


async def finish(code: str, state: str) -> dict:
    account = _states.pop(state, None)
    if not account:
        raise YTAError("許可の画面から戻ってきた情報が合いません。秘書ハブの「Google で許可する」からやり直してください")
    cid, sec = _client()
    async with httpx.AsyncClient(timeout=30) as c:
        r = await c.post("https://oauth2.googleapis.com/token", data={"code": code, "client_id": cid, "client_secret": sec,
                                                                     "redirect_uri": REDIRECT, "grant_type": "authorization_code"})
    d = r.json()
    if "refresh_token" not in d:
        raise YTAError("更新用の鍵がもらえませんでした(" + (d.get("error_description") or d.get("error") or r.text[:120]) + ")。もう一度許可してください")
    saved = {"refresh_token": d["refresh_token"], "since": datetime.date.today().isoformat(), "error": ""}
    _save(account, saved)
    try:
        ch = await _api("https://www.googleapis.com/youtube/v3/channels", {"part": "snippet", "mine": "true"}, account)
        saved["channel"] = ((ch.get("items") or [{}])[0].get("snippet") or {}).get("title", "")
        _save(account, saved)
    except YTAError:
        pass
    return {"account": account, "channel": saved.get("channel", "")}


async def _token(account: str) -> str:
    d = _load(account)
    if not d.get("refresh_token"):
        raise YTAError("YouTube アナリティクスが未接続です(秘書ハブのアカウント → YouTube → 数字 の「Google で許可する」)")
    if d.get("access_token") and d.get("expires", "") > datetime.datetime.now().isoformat():
        return d["access_token"]
    cid, sec = _client()
    async with httpx.AsyncClient(timeout=30) as c:
        r = await c.post("https://oauth2.googleapis.com/token", data={"client_id": cid, "client_secret": sec,
                                                                     "refresh_token": d["refresh_token"], "grant_type": "refresh_token"})
    t = r.json()
    if "access_token" not in t:
        d["error"] = "許可が切れました(" + (t.get("error") or "") + ")。Google で許可し直してください。Google Cloud のアプリが「テスト中」なら「本番」にしてください"
        _save(account, d)
        raise YTAError(d["error"])
    d.update(access_token=t["access_token"], error="",
             expires=(datetime.datetime.now() + datetime.timedelta(seconds=int(t.get("expires_in") or 3600) - 120)).isoformat(timespec="seconds"))
    _save(account, d)
    return d["access_token"]


async def _api(url: str, params: dict, account: str) -> dict:
    tok = await _token(account)
    async with httpx.AsyncClient(timeout=30) as c:
        r = await c.get(url, params=params, headers={"Authorization": f"Bearer {tok}"})
    try:
        d = r.json()
    except Exception:
        d = {}
    if r.status_code >= 400 or "error" in d:
        raise YTAError(((d.get("error") or {}).get("message") if isinstance(d.get("error"), dict) else d.get("error")) or r.text[:200])
    return d


BASE_METRICS = ["views", "estimatedMinutesWatched", "averageViewDuration", "averageViewPercentage", "likes", "subscribersGained"]


async def per_video(account: str = "main", days: int = 90) -> Dict[str, dict]:
    """動画ごとの分析の数字 {動画ID: {...}}。engagedViews(最初の数秒を過ぎて見た回数)が取れれば「視聴を継続」を計算する"""
    end = datetime.date.today()
    start = end - datetime.timedelta(days=days)
    out: Dict[str, dict] = {}
    for metrics in (BASE_METRICS + ["engagedViews"], BASE_METRICS):  # engagedViews が使えなければ外して取り直す
        try:
            d = await _api("https://youtubeanalytics.googleapis.com/v2/reports",
                           {"ids": "channel==MINE", "startDate": start.isoformat(), "endDate": end.isoformat(),
                            "metrics": ",".join(metrics), "dimensions": "video", "sort": "-views", "maxResults": 50}, account)
        except YTAError as e:
            if "engagedViews" in metrics:
                continue
            raise
        cols = [h["name"] for h in d.get("columnHeaders", [])]
        for row in d.get("rows", []) or []:
            v = dict(zip(cols, row))
            views = v.get("views") or 0
            out[v["video"]] = {
                "watch_hours": round((v.get("estimatedMinutesWatched") or 0) / 60, 2),
                "avg_view_sec": v.get("averageViewDuration"),
                "avg_view_pct": round(v["averageViewPercentage"], 1) if v.get("averageViewPercentage") is not None else None,
                "stayed_rate": round(v["engagedViews"] / views * 100, 1) if v.get("engagedViews") is not None and views else None,
                "subscribers_gained": v.get("subscribersGained"),
            }
        break
    return out
