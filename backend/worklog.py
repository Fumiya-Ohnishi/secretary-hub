"""作業ログ: 社員(各部署)の作業が終わるたびに、成果を1か所にまとめる。

- Notion「AI会社 > 作業ログ」(データベース)に 1作業=1ページ。日付・部署・種類・状態で探せる
- 会社のフォルダにも日付ごとに残す: worklog/YYYY-MM/YYYY-MM-DD/HHMM_部署_作業名.md
- どのファイルを作った・直したかは、作業の前後でファイルの更新時刻を比べて秘書ハブが調べる(部署が書き忘れても残る)
"""
import datetime
import os
import re
from pathlib import Path
from typing import Dict, List

import company
import notion

SKIP_DIRS = {".git", "node_modules", "__pycache__", ".venv", "venv", "worklog"}
SKIP_EXT = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".mp4", ".mov", ".webm", ".mp3", ".wav", ".zip", ".pdf"}
NOISE = {"data/employee_voice.md"}  # 毎回の追記で、成果物ではないもの


def snapshot() -> Dict[str, float]:
    root = company.COMPANY_DIR
    out: Dict[str, float] = {}
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS and not d.startswith(".") or d == ".claude"]
        for f in filenames:
            p = Path(dirpath) / f
            try:
                out[str(p.relative_to(root))] = p.stat().st_mtime
            except Exception:
                pass
    return out


def changed(before: Dict[str, float]) -> List[str]:
    after = snapshot()
    files = [p for p, t in after.items() if before.get(p) != t]
    return sorted(files, key=lambda p: after[p], reverse=True)


def kind_of(job: dict) -> str:
    key, dept, title = job.get("task_key") or "", job.get("department", ""), job.get("title", "")
    if key.startswith("meeting:"):
        return "会議"
    if "リサーチ" in title or "ニュース" in title:
        return "リサーチ"
    return {"戦略": "戦略", "企画": "企画・投稿", "ライティング": "企画・投稿", "デザイン": "企画・投稿", "画像": "企画・投稿",
            "映像": "企画・投稿", "SNS運用": "企画・投稿", "品質管理": "企画・投稿", "Codex": "企画・投稿", "収益化": "戦略",
            "分析": "レポート", "経理": "経理", "広報": "広報", "人事": "人事"}.get(dept, "その他")


def status_of(job: dict) -> str:
    if job.get("status") == "done":
        return "完了"
    return "途中で止まった" if "制限時間" in (job.get("output") or "") else "エラー"


def _summary(job: dict) -> str:
    out = (job.get("output") or "").strip()
    return out[-1500:] if out else "(結果の文はありません)"


def local_note(job: dict, files: List[str], url: str = "") -> str:
    """worklog/YYYY-MM/YYYY-MM-DD/HHMM_部署_作業名.md を書いて、そのパスを返す"""
    start = datetime.datetime.fromisoformat(job["started"])
    dept = job.get("department_full") or job.get("department", "")
    name = re.sub(r"[\\/:*?\"<>|\s]+", "_", f"{start:%H%M}_{dept}_{job.get('title', '')}")[:80]
    path = company.COMPANY_DIR / "worklog" / f"{start:%Y-%m}" / f"{start:%Y-%m-%d}" / f"{name}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [f"# {job.get('title', '')}", "",
             f"- 日時: {start:%Y-%m-%d %H:%M}〜{(job.get('finished') or '')[11:16]}",
             f"- 部署: {dept}", f"- 種類: {kind_of(job)}", f"- 状態: {status_of(job)}"]
    if url:
        lines.append(f"- Notion: {url}")
    lines += ["", "## 作ったファイル・直したファイル"] + ([f"- `{f}`" for f in files] or ["(なし)"])
    lines += ["", "## まとめ", _summary(job), ""]
    path.write_text("\n".join(lines), encoding="utf-8")
    return str(path.relative_to(company.COMPANY_DIR))


def _blocks(job: dict, files: List[str]) -> List[dict]:
    md = [f"> {kind_of(job)} ・ {job.get('department_full') or job.get('department', '')} ・ {job['started'][:16].replace('T', ' ')}", "",
          "## まとめ", _summary(job), "", "## 作ったファイル・直したファイル"]
    md += [f"- {f}" for f in files] or ["(なし)"]
    blocks = notion.markdown_to_blocks("\n".join(md))
    shown = 0
    for f in files:  # 中身も読めるように、文章のファイルを3つまで載せる
        p = company.COMPANY_DIR / f
        if shown >= 3 or p.suffix.lower() not in (".md", ".txt") or f in NOISE:
            continue
        try:
            text = p.read_text(encoding="utf-8")[:8000]
        except Exception:
            continue
        text = re.sub(r"^---\n.*?\n---\n", "", text, flags=re.S)
        blocks += notion.markdown_to_blocks(f"## 📄 {f}")
        blocks += notion.markdown_to_blocks(text)[:80]
        shown += 1
    return blocks[:400]


async def publish(job: dict, files: List[str]) -> dict:
    files = [f for f in files if f not in NOISE and Path(f).suffix.lower() not in SKIP_EXT][:40] + \
            [f for f in files if Path(f).suffix.lower() in SKIP_EXT][:20]
    result = {"local": "", "url": ""}
    if notion.configured():
        try:
            day = job["started"][:10]
            r = await notion.add_worklog(job.get("title", "作業"), day, job.get("department_full") or "", kind_of(job), status_of(job),
                                         files, job.get("task_key") or "", job["id"], _blocks(job, files))
            result["url"] = r["url"]
            try:  # 作業のまとまり(やり取りの流れ)に「報告」を1行足す(2026-11-12)
                import threads
                dept = job.get("department_full") or job.get("department", "")
                await threads.add(job.get("title", ""), "📝" if job.get("status") == "done" else "⚠️",
                                  f"{dept}の報告: {job.get('title', '')}" + ("" if job.get("status") == "done" else "(途中で止まりました)"),
                                  dept=dept, link=r["url"], link_text="作業ログ", state="進行中", relate_worklog=r["id"])
            except Exception:
                pass
            if job.get("task_key") and not str(job["task_key"]).startswith(("meeting:", "routine:")):
                try:
                    await company.update_task(job["task_key"], link=r["url"])
                except Exception:
                    pass
        except Exception as e:
            result["error"] = str(e)[:200]
    try:
        result["local"] = local_note(job, files, result["url"])
    except Exception as e:
        result["error"] = (result.get("error", "") + f" / {e}")[:300]
    return result
