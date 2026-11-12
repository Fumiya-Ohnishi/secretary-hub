"""Threads の数字を Meta 公式の Threads API で取る(ログイン・画面の自動操作はしない。2026-11-12)。

backend/.env:
  THREADS_ACCESS_TOKEN=      本アカウントの Threads のトークン(Meta の開発者画面の「ユーザートークン生成」で作る。長期=約60日)
  THREADS_SUB_ACCESS_TOKEN=  別アカウントの Threads のトークン
  THREADS_APP_SECRET=        (任意)短い期限のトークンを長期に交換するときに使う
秘書ハブは期限が近づくと自動で延長し、backend/data/threads_token_*.json に保存する(git に入らない)。
手順は ai-company の playbooks/account_connect.md
"""
import datetime
import json
import os
from pathlib import Path
from typing import Dict, List, Optional

import httpx

API = "https://graph.threads.net/v1.0"
DATA_DIR = Path(__file__).resolve().parent / "data"
USER_METRICS = ["followers_count", "views", "likes", "replies", "reposts", "quotes"]
POST_METRICS = ["views", "likes", "replies", "reposts", "quotes", "shares"]


class ThreadsError(Exception):
    pass


def _env_token(account: str) -> str:
    return os.getenv("THREADS_ACCESS_TOKEN" if account == "main" else f"THREADS_{account.upper()}_ACCESS_TOKEN", "").strip()


def _path(account: str) -> Path:
    return DATA_DIR / f"threads_token_{account}.json"


def _cache(account: str) -> dict:
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


def configured(account: str = "main") -> bool:
    return bool(_env_token(account) or _cache(account).get("token"))


def token_status(account: str = "main") -> str:
    c = _cache(account)
    return f"{c['expires'][:10]} まで(自動で延長)" if c.get("expires") else ("設定済み" if configured(account) else "未設定")


async def _call(url: str, params: dict) -> dict:
    async with httpx.AsyncClient(timeout=30) as c:
        r = await c.get(url, params=params)
    try:
        data = r.json()
    except Exception:
        data = {}
    if r.status_code >= 400 or "error" in data:
        err = data.get("error") or {}
        msg = err.get("message") or r.text[:200]
        if err.get("code") == 190:
            msg = "Threads のトークンの期限切れか無効です。手順書のとおりに発行し直して .env を替えてください"
        elif err.get("code") in (10, 200):
            msg = f"権限が足りません({msg})。threads_basic と threads_manage_insights を付けてトークンを作り直してください"
        raise ThreadsError(msg)
    return data


async def access_token(account: str = "main") -> str:
    env_tok = _env_token(account)
    c = _cache(account)
    if env_tok and c.get("source") != env_tok[-12:]:  # .env のトークンが新しくなった
        c = {"token": env_tok, "source": env_tok[-12:], "expires": ""}
        secret = os.getenv("THREADS_APP_SECRET", "").strip()
        if secret:  # 短い期限のトークンなら長期に交換する(長期のものなら失敗するので、そのまま使う)
            try:
                d = await _call("https://graph.threads.net/access_token",
                                {"grant_type": "th_exchange_token", "client_secret": secret, "access_token": env_tok})
                c["token"] = d["access_token"]
                c["expires"] = (datetime.datetime.now() + datetime.timedelta(seconds=int(d.get("expires_in") or 0))).isoformat(timespec="seconds")
            except ThreadsError:
                pass
        if not c["expires"]:
            c["expires"] = (datetime.datetime.now() + datetime.timedelta(days=60)).isoformat(timespec="seconds")
        _save(account, c)
    if not c.get("token"):
        raise ThreadsError(("THREADS_ACCESS_TOKEN" if account == "main" else "THREADS_SUB_ACCESS_TOKEN") + " が未設定です(手順: playbooks/account_connect.md)")
    try:  # 期限まで10日を切ったら延長する(長期のトークンは使える間なら延長できる)
        left = datetime.datetime.fromisoformat(c["expires"]) - datetime.datetime.now()
        if left < datetime.timedelta(days=10):
            d = await _call("https://graph.threads.net/refresh_access_token", {"grant_type": "th_refresh_token", "access_token": c["token"]})
            c["token"] = d["access_token"]
            c["expires"] = (datetime.datetime.now() + datetime.timedelta(seconds=int(d.get("expires_in") or 60 * 86400))).isoformat(timespec="seconds")
            _save(account, c)
    except (ThreadsError, KeyError, ValueError):
        pass
    return c["token"]


async def _get(path: str, params: dict, account: str) -> dict:
    return await _call(f"{API}/{path.lstrip('/')}", {**params, "access_token": await access_token(account)})


def _value(item: dict):
    if item.get("total_value"):
        return item["total_value"].get("value")
    vals = item.get("values") or []
    return sum((v.get("value") or 0) for v in vals) if vals else None


async def me(account: str = "main") -> dict:
    """ユーザー名とフォロワー数(フォロワー数はインサイトの followers_count)"""
    u = await _get("me", {"fields": "id,username"}, account)
    out = {"username": u.get("username", ""), "followers_count": None}
    try:
        ins = await _get("me/threads_insights", {"metric": "followers_count"}, account)
        for it in ins.get("data", []):
            if it.get("name") == "followers_count":
                out["followers_count"] = _value(it)
    except ThreadsError:
        pass
    return out


async def my_posts(account: str = "main", limit: int = 25) -> List[dict]:
    d = await _get("me/threads", {"fields": "id,text,timestamp,permalink,media_type", "limit": limit}, account)
    out = []
    for m in d.get("data", []):
        row = {"media_id": m["id"], "posted_at": (m.get("timestamp") or "")[:10], "kind": "投稿", "url": m.get("permalink", ""),
               "caption": (m.get("text") or "")[:300]}
        vals: Dict[str, Optional[int]] = {}
        metrics = list(POST_METRICS)
        for _ in range(3):
            try:
                ins = await _get(f"{m['id']}/insights", {"metric": ",".join(metrics)}, account)
                for it in ins.get("data", []):
                    vals[it.get("name")] = _value(it)
                break
            except ThreadsError as e:
                bad = [x for x in metrics if x in str(e)]
                if not bad:
                    break
                metrics = [x for x in metrics if x not in bad]
        row.update({k: vals.get(k) for k in POST_METRICS})
        out.append(row)
    return out
