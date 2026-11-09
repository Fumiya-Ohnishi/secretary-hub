"""資料室: 会社の知見(ai-company/knowledge/ と、各所にある記録)を棚ごとに読み、作業の前に関係する知見を探す。

- 棚の定義は SHELVES(会社の knowledge/README.md と同じ)
- search(): 頼んだ仕事の文から、関係する知見の段落を探す(日本語は2文字ずつの重なりで点数を付ける)
- 社長の好み(knowledge/preferences.md): 「確定」と「確認待ち」。アカウントの軸と食い違う・曖昧なものは確認待ちに入れ、
  社長が確定(言い直し可)・却下する
"""
import datetime
import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import company

SHELVES = [
    ("failures", "失敗と再発防止", ["playbooks/learned_rules.md", "data/corrections.md", "knowledge/lessons.md"]),
    ("wins", "うまくいった型", ["knowledge/winning_patterns.md", "content/drafts/*/_prompt_tests.md"]),
    ("reviews", "審査の記録", ["content/drafts/*/_check.md", "playbooks/visual_standard.md"]),
    ("research", "リサーチ", ["strategy/research/*.md", "strategy/research/accounts/*.md"]),
    ("numbers", "数字と改善点", ["data/improvements.md", "reports/weekly_*.md"]),
    ("external", "外部の知見", ["knowledge/external_insights.md"]),
    ("prefs", "社長の好み", ["knowledge/preferences.md"]),
]
PREFS = "knowledge/preferences.md"
LESSONS = "knowledge/lessons.md"
PREF_RE = re.compile(r"^- \[(P-\d+)\]\s*(.*)$")


def _root() -> Path:
    return company.COMPANY_DIR


def _files(patterns: List[str]) -> List[Path]:
    out: List[Path] = []
    for pat in patterns:
        out += sorted(p for p in _root().glob(pat) if p.is_file() and p.name != "README.md")
    return out


def _chunks(path: Path) -> List[str]:
    """段落(空行区切り)と箇条書きの1項目を、知見の1単位にする"""
    try:
        text = path.read_text(encoding="utf-8")
    except Exception:
        return []
    text = re.sub(r"^---\n.*?\n---\n", "", text, flags=re.S)
    out = []
    for block in re.split(r"\n\s*\n", text):
        lines = [l for l in block.strip().splitlines() if l.strip()]
        if not lines:
            continue
        if sum(l.lstrip().startswith(("- ", "* ", "| ")) for l in lines) >= max(2, len(lines) // 2):
            out += [l.strip() for l in lines if len(l.strip()) > 8 and not re.match(r"^\|[-\s|]+\|$", l.strip())]
        else:
            out.append(" ".join(lines))
    return [c for c in out if not c.startswith("#") and len(c) > 8]


def _grams(text: str) -> set:
    """英数字の単語と、日本語の2文字ずつ(記号・空白をまたがない)"""
    t = text.lower()
    out = set(re.findall(r"[a-z0-9]{3,}", t))
    for seg in re.findall(r"[^\sa-z0-9\W_]+", t):
        out |= {seg[i:i + 2] for i in range(len(seg) - 1)}
    return out


STOP = _grams("します。ください。こと。もの。ため。よう。する。いる。ある。なる。です。ます。から。まで。について")


def search(query: str, limit: int = 8, shelves: Optional[List[str]] = None) -> List[dict]:
    q = _grams(query) - STOP
    if not q:
        return []
    hits = []
    for key, name, pats in SHELVES:
        if shelves and key not in shelves or key == "prefs":
            continue
        for f in _files(pats):
            rel = str(f.relative_to(_root()))
            for c in _chunks(f):
                g = _grams(c)
                score = len(q & g) / (len(q) ** 0.5 * max(len(g), 1) ** 0.3)
                if score > 0.12:
                    hits.append({"shelf": key, "shelf_name": name, "source": rel, "text": c[:400], "score": round(score, 3)})
    hits.sort(key=lambda h: h["score"], reverse=True)
    seen, out = set(), []
    for h in hits:
        k = h["text"][:60]
        if k not in seen:
            seen.add(k)
            out.append(h)
        if len(out) >= limit:
            break
    return out


# ---------- 社長の好み ----------
def _pref_path() -> Path:
    return _root() / PREFS


def prefs() -> Dict[str, List[dict]]:
    out = {"confirmed": [], "pending": []}
    p = _pref_path()
    if not p.exists():
        return out
    sec = None
    for line in p.read_text(encoding="utf-8").splitlines():
        if line.startswith("## 確定"):
            sec = "confirmed"
        elif line.startswith("## 確認待ち"):
            sec = "pending"
        else:
            m = PREF_RE.match(line.strip())
            if m and sec:
                body = m.group(2)
                reason = ""
                if " ／ 確認する理由: " in body:
                    body, reason = body.split(" ／ 確認する理由: ", 1)
                out[sec].append({"id": m.group(1), "text": body, "reason": reason})
    return out


def _write_prefs(p: Dict[str, List[dict]]):
    path = _pref_path()
    head = "# 社長の好み\n\n部署が従うのは「確定」だけ。書き方は `knowledge/README.md`。各行の [P-xxx] は番号(消さない)。\n"
    if path.exists():
        m = re.match(r"(.*?)(?=^## 確定)", path.read_text(encoding="utf-8"), flags=re.S | re.M)
        if m and m.group(1).strip():
            head = m.group(1).rstrip() + "\n"
    lines = [head, "## 確定"]
    lines += [f"- [{x['id']}] {x['text']}" for x in p["confirmed"]] or ["(なし)"]
    lines += ["", "## 確認待ち"]
    lines += [f"- [{x['id']}] {x['text']} ／ 確認する理由: {x['reason'] or '要確認'}" for x in p["pending"]] or ["(なし)"]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _next_id(p) -> str:
    nums = [int(x["id"][2:]) for x in p["confirmed"] + p["pending"]]
    return f"P-{(max(nums) if nums else 0) + 1:03d}"


def add_pref(text: str, needs_check: bool, reason: str = "", source: str = "社長・会話") -> dict:
    """好みを足す。needs_check=True(軸と食い違う・曖昧・言い直しが必要)なら確認待ちへ"""
    p = prefs()
    text = re.sub(r"\s+", " ", text).strip()
    for x in p["confirmed"] + p["pending"]:
        if text and text in x["text"]:
            return {**x, "status": "confirmed" if x in p["confirmed"] else "pending", "duplicate": True}
    item = {"id": _next_id(p), "text": f"{datetime.date.today().isoformat()} ({source}) {text}", "reason": reason}
    (p["pending"] if needs_check else p["confirmed"]).append(item)
    _write_prefs(p)
    return {**item, "status": "pending" if needs_check else "confirmed"}


def decide_pref(pid: str, approve: bool, revised: str = "") -> dict:
    p = prefs()
    item = next((x for x in p["pending"] if x["id"] == pid), None)
    if not item:
        raise KeyError(f"{pid} は確認待ちにありません")
    p["pending"].remove(item)
    if approve:
        if revised.strip():
            date_src = re.match(r"^(\d{4}-\d{2}-\d{2} \([^)]*\))", item["text"])
            item["text"] = f"{date_src.group(1) if date_src else datetime.date.today().isoformat()} {revised.strip()}(社長が確認して言い直し)"
        else:
            item["text"] += "(社長確認済み)"
        item["reason"] = ""
        p["confirmed"].append(item)
    _write_prefs(p)
    return {**item, "status": "confirmed" if approve else "rejected"}


def add_lesson(dept: str, text: str, source: str = "") -> str:
    path = _root() / LESSONS
    line = f"- {datetime.date.today().isoformat()} {dept}: {text.strip()}{f'({source})' if source else ''}"
    old = path.read_text(encoding="utf-8") if path.exists() else "# 作業後の知見\n\n"
    path.write_text(old.rstrip() + "\n" + line + "\n", encoding="utf-8")
    return line


# ---------- 画面と指示書 ----------
def overview() -> dict:
    shelves = []
    for key, name, pats in SHELVES:
        files = _files(pats)
        n = sum(len(_chunks(f)) for f in files)
        latest = max(files, key=lambda f: f.stat().st_mtime) if files else None
        shelves.append({"key": key, "name": name, "count": n, "files": [str(f.relative_to(_root())) for f in files][:20],
                        "updated": datetime.datetime.fromtimestamp(latest.stat().st_mtime).isoformat(timespec="minutes") if latest else None})
    lessons = _chunks(_root() / LESSONS) if (_root() / LESSONS).exists() else []
    return {"shelves": shelves, "prefs": prefs(), "recent_lessons": [l.lstrip("- ") for l in lessons[-8:]][::-1]}


DATE_SRC = re.compile(r"^\d{4}-\d{2}-\d{2} \([^)]*\) ")


def _plain(text: str) -> str:
    """好みの行から「日付 (出どころ)」を取る"""
    return DATE_SRC.sub("", text)


def brief_for(instruction: str, dept: str = "") -> List[str]:
    """部署への指示書に入れる「資料室」の節"""
    p = prefs()
    hits = search(f"{dept} {instruction}", limit=6)
    lines = ["## 資料室(作業の前に必ず確認。knowledge/README.md)"]
    if p["confirmed"]:
        lines.append("社長の好み(確定。必ず守る):")
        lines += ["- " + _plain(x["text"])[:160] for x in p["confirmed"][-12:]]
    if hits:
        lines.append("この仕事に関係しそうな過去の知見(出典つき。同じ失敗をしない):")
        lines += [f"- [{h['shelf_name']}] {h['text'][:220]}({h['source']})" for h in hits]
    lines += ["- 最初の作業ログに「確認した知見」を1行で書く。知見と違うことをするときは理由を書く",
              "- 作業の最後に、上司が knowledge/lessons.md へ「- YYYY-MM-DD 部署: 分かったこと → 次からこうする(出典)」を1〜3行追記する。"
              "差し戻し・止まった・やり直しがあったときは、原因と対策を必ず書く", ""]
    return lines


def summary_text() -> str:
    p = prefs()
    conf = "、".join(_plain(x["text"])[:50] for x in p["confirmed"][-8:])
    s = f"- 資料室: 社長の好み 確定{len(p['confirmed'])}件・確認待ち{len(p['pending'])}件"
    if conf:
        s += f"。確定の主なもの: {conf}"
    if p["pending"]:
        s += "。確認待ち: " + " / ".join(f"{x['id']} {x['text'][:40]}" for x in p["pending"])
    return s
