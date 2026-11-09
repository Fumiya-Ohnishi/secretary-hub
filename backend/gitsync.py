"""会社のフォルダ(ai-company)の自動保存: 秘書ハブと部署が書いたファイルを、止まらずに GitHub とそろえる。

10分ごと(部署の作業や会議が動いていないとき)に:
 1. 変わったファイルを全部コミットする(.gitignore の画像・動画などは入らない。大きすぎるファイルも入れない)
 2. GitHub の新しい変更を取り込む(git pull --no-rebase)。同じ行を両方で変えていたら Mac 側を優先して取り込み、通知する
 3. GitHub に上げる(git push)
社長が手で git pull するときに「local changes would be overwritten」で止まらなくなる。
"""
import datetime
import os
import subprocess
from pathlib import Path
from typing import List, Optional

import company

MAX_MB = 20  # これより大きいファイルは入れない(GitHub は 100MB で拒否。容量も食うため)
state = {"last": None, "ok": None, "detail": "", "conflicts": []}


def enabled() -> bool:
    return os.getenv("AUTO_GIT_SYNC", "1").strip() not in ("0", "false", "no")


def _git(*args: str, timeout: int = 120) -> subprocess.CompletedProcess:
    env = dict(os.environ, GIT_TERMINAL_PROMPT="0", GIT_MERGE_AUTOEDIT="no")  # 入力待ちで止まらない
    return subprocess.run(["git", "-c", "core.quotepath=false", "-c", "http.postBuffer=524288000", *args],
                          cwd=str(company.COMPANY_DIR), capture_output=True, text=True, timeout=timeout, env=env)


def _is_repo() -> bool:
    return (company.COMPANY_DIR / ".git").exists()


def _branch() -> str:
    return _git("rev-parse", "--abbrev-ref", "HEAD").stdout.strip()


def _commit_local() -> int:
    """変わったファイルをコミットする。入れたファイル数を返す"""
    _git("add", "-A")
    staged = [l for l in _git("diff", "--cached", "--name-only").stdout.splitlines() if l.strip()]
    big = []
    for f in staged:
        p = company.COMPANY_DIR / f
        if p.is_file() and p.stat().st_size > MAX_MB * 1024 * 1024:
            big.append(f)
    if big:
        _git("reset", "-q", "HEAD", "--", *big)
        state["detail"] = f"大きすぎて入れなかったファイル: {', '.join(big[:3])}"
    staged = [f for f in staged if f not in big]
    if not staged:
        return 0
    msg = f"秘書ハブの自動保存({datetime.datetime.now():%m/%d %H:%M}・{len(staged)}ファイル)"
    r = _git("commit", "-q", "-m", msg)
    return len(staged) if r.returncode == 0 else 0


def sync() -> dict:
    """1回分の自動保存。結果を state に残して返す"""
    state.update(last=datetime.datetime.now().isoformat(timespec="minutes"), conflicts=[], detail="")
    if not _is_repo():
        state.update(ok=False, detail="会社のフォルダが git の保存場所ではありません")
        return dict(state)
    if (company.COMPANY_DIR / ".git" / "MERGE_HEAD").exists():  # 前回の取り込みが途中なら、いったん戻す
        _git("merge", "--abort")
    try:
        n = _commit_local()
        branch = _branch()
        f = _git("fetch", "-q", "origin", branch)
        if f.returncode != 0:
            state.update(ok=False, detail=f"GitHub に接続できませんでした: {(f.stderr or '').strip()[:160]}")
            return dict(state)
        p = _git("pull", "--no-rebase", "--no-edit", "origin", branch)
        if p.returncode != 0:
            conflicts = [l for l in _git("diff", "--name-only", "--diff-filter=U").stdout.splitlines() if l.strip()]
            _git("merge", "--abort")
            if conflicts:  # 同じ行を両方で変えていた → Mac 側を優先して、ほかはそのまま取り込む
                p = _git("pull", "--no-rebase", "--no-edit", "-X", "ours", "origin", branch)
                state["conflicts"] = conflicts
            if p.returncode != 0:
                state.update(ok=False, detail=f"取り込みに失敗: {(p.stderr or p.stdout).strip()[:200]}")
                return dict(state)
        ahead = _git("rev-list", "--count", f"origin/{branch}..HEAD").stdout.strip()
        if ahead and ahead != "0":
            u = _git("push", "-q", "origin", branch, timeout=300)
            if u.returncode != 0:
                state.update(ok=False, detail=f"GitHub に上げられませんでした: {(u.stderr or '').strip()[:200]}")
                return dict(state)
        state.update(ok=True, detail=(f"保存 {n}ファイル" if n else "変更なし") + (f" ・ {state['detail']}" if "大きすぎ" in state.get("detail", "") else ""))
    except Exception as e:
        state.update(ok=False, detail=str(e)[:200])
    return dict(state)
