"""会議: 部署をまたいで意見を出し合い、議事録(meetings/*.md)を Notion「議事録」に載せる。

- start(): 会議を開く(Claude Code に司会をさせ、参加者=サブエージェントに順番に話させて議事録を書かせる)
- sync(): 書き上がった議事録を Notion に載せ、「やること」を秘書がタスクにし、社長に決まったことを3行で知らせる
進め方と風通しの決まりは ai-company の playbooks/meetings.md
"""
import datetime
import os
import re
from pathlib import Path
from typing import Dict, List, Optional

import company
import notion

MEETING_DB = os.getenv("NOTION_MEETING_DB", "829d077c4b49458693c6739888105d13").strip()
KINDS = {
    "planning": {"name": "企画会議", "depts": ["企画編集部", "ライティング部", "デザイン部", "映像制作部", "SNS運用部", "データ分析部", "広報部"],
                 "devil": "planner-contrarian(逆張りの企画担当)",
                 "agenda": "今週のテーマを決める。月曜の週次リサーチ(strategy/research/ の最新)と資料室を読み、各部署から『作りやすさ・伸びそうか・懸念』を出し、編集長が決める"},
    "review": {"name": "振り返り会議", "depts": ["経営戦略部", "企画編集部", "ライティング部", "デザイン部", "画像制作部", "映像制作部", "SNS運用部", "品質管理部", "データ分析部", "人事部"],
               "devil": "risk-analyst(リスクアナリスト)",
               "agenda": "今週の振り返り。数字(data/*.csv・data/improvements.md)と差し戻し(data/corrections.md)・作業後の知見(knowledge/lessons.md)を見て、よかったこと・まずかったこと・次に試すことを出す"},
    "allhands": {"name": "全体会議", "depts": ["秘書室", "経営戦略部", "収益化部", "企画編集部", "ライティング部", "デザイン部", "画像制作部", "映像制作部", "SNS運用部", "品質管理部", "データ分析部", "経理・税務部", "広報部", "人事部"],
                 "devil": "risk-analyst(リスクアナリスト)",
                 "agenda": "月次の全体会議。目標(strategy/roadmap.md)の進み具合、続けるか変えるか、来月の重点を各部署の上司が話す"},
    "adhoc": {"name": "臨時会議", "depts": [], "devil": "risk-analyst(リスクアナリスト)", "agenda": ""},
}
SECTIONS = ["議題", "発言(話した順)", "決まったこと", "少数意見(採らなかった意見と理由)", "やること", "社長に確認したいこと"]


def folder() -> Path:
    return company.COMPANY_DIR / "meetings"


def instruction(kind: str, topic: str = "", depts: Optional[List[str]] = None) -> str:
    k = KINDS.get(kind, KINDS["adhoc"])
    depts = depts or k["depts"]
    today = datetime.date.today().isoformat()
    file = f"meetings/{today}_{k['name']}.md"
    return (f"{k['name']}を開く。司会は秘書室(あなた)。進め方と風通しの決まりは playbooks/meetings.md を必ず読んで守る。"
            f"議題: {topic or k['agenda']}。参加部署: {'・'.join(depts)}(各部署の代表=担当を先に、上司は最後)。反対役: {k['devil']}。"
            "最初に meetings/_suggestions.md(目安箱)の未処理を議題に足す。各参加者はサブエージェントとして呼び、1人2〜4文で話させる。2周まで"
            "(1周目=意見、2周目=他の意見を聞いての修正・反対)。全員賛成なら決める前に反対役に『うまくいかない場合』を出させる。"
            f"議事録を {file} に playbooks/meetings.md の形(front matter に kind・date・participants)で書く。"
            "やることは『- [部署の短い名前] 内容(期限 YYYY-MM-DD)』の形(部署の短い名前: 戦略/収益化/企画/ライティング/デザイン/画像/映像/SNS運用/品質管理/分析/経理/広報/人事)。"
            "タスクの起票はしない(秘書ハブが議事録から起票する)。投稿の中身の最終決定・社長の好み(knowledge/preferences.md の確定)と軸に反することは決めない。"
            "決まったことは knowledge/lessons.md にも1行で残す。")


def parse(path: Path) -> dict:
    text = path.read_text(encoding="utf-8")
    meta, body = {}, text
    m = re.match(r"^---\n(.*?)\n---\n(.*)$", text, flags=re.S)
    if m:
        for line in m.group(1).splitlines():
            if ":" in line:
                k, v = line.split(":", 1)
                meta[k.strip()] = v.strip()
        body = m.group(2)
    secs: Dict[str, List[str]] = {}
    cur = None
    for line in body.splitlines():
        h = re.match(r"^##\s+(.+)$", line)
        if h:
            cur = h.group(1).strip()
            secs[cur] = []
        elif cur and line.strip():
            secs[cur].append(line.strip())

    def sec(prefix):
        for k, v in secs.items():
            if k.startswith(prefix):
                return [re.sub(r"^[-*]\s*", "", x) for x in v if not x.startswith("(なし")]
        return []
    return {"path": path, "meta": meta, "body": body, "title": (re.search(r"^#\s+(.+)$", body, flags=re.M) or [None, path.stem])[1],
            "decisions": sec("決まったこと"), "minority": sec("少数意見"), "todos": sec("やること"),
            "ask": [x for x in sec("社長に確認") if x not in ("なし", "特になし")]}


def _set_meta(path: Path, **kv):
    text = path.read_text(encoding="utf-8")
    m = re.match(r"^---\n(.*?)\n---\n", text, flags=re.S)
    add = "".join(f"{k}: {v}\n" for k, v in kv.items())
    text = (f"---\n{m.group(1)}\n{add}---\n" + text[m.end():]) if m else f"---\n{add}---\n" + text
    path.write_text(text, encoding="utf-8")


def list_minutes(limit: int = 12) -> List[dict]:
    if not folder().exists():
        return []
    out = []
    for p in sorted(folder().glob("20*.md"), reverse=True)[:limit]:
        d = parse(p)
        out.append({"file": str(p.relative_to(company.COMPANY_DIR)), "title": d["title"], "kind": d["meta"].get("kind", ""),
                    "date": d["meta"].get("date", ""), "decisions": d["decisions"][:5], "ask": d["ask"], "notion": d["meta"].get("notion", "")})
    return out


TODO_RE = re.compile(r"^\[([^\]]+)\]\s*(.+?)\s*(?:[(（]\s*期限\s*(\d{4}-\d{2}-\d{2})\s*[)）])?\s*$")


async def sync() -> List[dict]:
    """書き上がった(synced の印がない)議事録を Notion に載せ、やることをタスクにし、通知する"""
    import scheduler
    done = []
    if not folder().exists():
        return done
    for p in sorted(folder().glob("20*.md")):
        d = parse(p)
        if d["meta"].get("synced") or not d["decisions"] and not d["todos"]:
            continue
        url = ""
        if notion.configured():
            try:
                props = {"会議": {"title": [{"type": "text", "text": {"content": d["title"][:200]}}]},
                         "決まったこと": {"rich_text": [{"type": "text", "text": {"content": "\n".join(d["decisions"])[:1900]}}]},
                         "少数意見": {"rich_text": [{"type": "text", "text": {"content": "\n".join(d["minority"])[:1900]}}]},
                         "社長に確認": {"rich_text": [{"type": "text", "text": {"content": "\n".join(d["ask"])[:1900] or "なし"}}]},
                         "ファイル": {"rich_text": [{"type": "text", "text": {"content": str(p.relative_to(company.COMPANY_DIR))}}]}}
                kind = d["meta"].get("kind", "")
                if kind in [k["name"] for k in KINDS.values()]:
                    props["種類"] = {"select": {"name": kind}}
                if re.match(r"\d{4}-\d{2}-\d{2}$", d["meta"].get("date", "")):
                    props["日付"] = {"date": {"start": d["meta"]["date"]}}
                parts = [x.strip() for x in d["meta"].get("participants", "").split(",") if x.strip()]
                if parts:
                    props["参加"] = {"multi_select": [{"name": x} for x in parts if x in KINDS["allhands"]["depts"]]}
                blocks = notion.markdown_to_blocks(re.sub(r"^#\s+.+\n", "", d["body"], count=1))
                page = await notion._req("POST", "/pages", json={"parent": {"database_id": MEETING_DB}, "icon": {"type": "emoji", "emoji": "🗣"},
                                                                 "properties": props, "children": blocks[:100]})
                url = page.get("url", "")
                pid = page["id"].replace("-", "")
                for i in range(100, len(blocks), 100):
                    await notion.append_blocks(pid, blocks[i:i + 100])
            except Exception as e:
                print("議事録を Notion に載せられませんでした:", e)
                continue  # 次回また試す
        made = []
        for t in d["todos"]:
            m = TODO_RE.match(t)
            dept, title, due = (m.group(1), m.group(2).strip(), m.group(3)) if m else ("秘書", t, None)
            try:
                await company.create_task(f"{title}({d['meta'].get('kind', '会議')}で決定)", dept, due, note=f"議事録: {p.name}", link=url)
                made.append(title)
            except Exception as e:
                print("会議のやることを起票できませんでした:", e)
        _set_meta(p, synced=datetime.datetime.now().isoformat(timespec="minutes"), **({"notion": url} if url else {}))
        lines = [f"・{x}" for x in d["decisions"][:3]]
        if d["ask"]:
            lines.append(f"・社長に確認: {d['ask'][0]}")
        scheduler.notify(f"{d['meta'].get('kind', '会議')}の議事録", "\n".join(lines) + (f"\n(タスク {len(made)}件を起票)" if made else "") +
                         (f"\n{url}" if url else ""), "meeting")
        done.append({"file": p.name, "notion": url, "tasks": len(made)})
    return done
