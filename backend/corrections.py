"""修正ログとルール化。

- 社長の差し戻し(タスク・投稿)を ai-company/data/corrections.md に自動で残す
- 同じ種類の指摘が繰り返されたら、秘書が「ルールに1行足す」案を出す(rule_proposals)
- 社長が承認した案だけを ai-company/playbooks/learned_rules.md に追記する(全部署が最初に読む)
"""
import datetime
import json
import threading
import uuid
from pathlib import Path
from typing import List, Optional

import company

DATA_DIR = Path(__file__).resolve().parent / "data"
DATA_DIR.mkdir(exist_ok=True)
PROPOSALS_FILE = DATA_DIR / "rule_proposals.json"
_lock = threading.Lock()

LOG_HEADER = """# 修正ログ(秘書ハブが自動で記録)

社長の差し戻し・チェック役の指摘を残す。同じ指摘が繰り返されたら、秘書が `playbooks/learned_rules.md` への追加を社長に提案する。

| 日付 | 対象 | 指摘 | 出所 |
|---|---|---|---|
"""
RULES_HEADER = """# 過去の失敗から学んだルール(全部署が作業前に読む)

社長が承認したものだけをここに追加する(秘書ハブの「ルール追加の提案」から)。

"""


def log_path() -> Path:
    return company.COMPANY_DIR / "data" / "corrections.md"


def rules_path() -> Path:
    return company.COMPANY_DIR / "playbooks" / "learned_rules.md"


def _cell(text: str) -> str:
    return " ".join((text or "").split()).replace("|", "/")[:300]


def add(target: str, comment: str, source: str = "社長") -> dict:
    p = log_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    with _lock:
        text = p.read_text() if p.exists() else LOG_HEADER
        row = f"| {datetime.date.today().isoformat()} | {_cell(target)} | {_cell(comment)} | {source} |"
        p.write_text(text.rstrip("\n") + "\n" + row + "\n")
    return {"target": target, "comment": comment, "source": source}


def recent(limit: int = 40) -> List[dict]:
    p = log_path()
    if not p.exists():
        return []
    rows = []
    for line in p.read_text().splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if line.startswith("|") and len(cells) >= 4 and cells[0][:2] == "20":
            rows.append({"date": cells[0], "target": cells[1], "comment": cells[2], "source": cells[3]})
    return rows[-limit:]


def rules() -> List[str]:
    p = rules_path()
    if not p.exists():
        return []
    return [l[2:].strip() for l in p.read_text().splitlines() if l.startswith("- ")]


# ---------- ルール追加の提案(社長が承認したら追記) ----------
def proposals(status: Optional[str] = "pending") -> List[dict]:
    try:
        items = json.loads(PROPOSALS_FILE.read_text())
    except Exception:
        items = []
    return [i for i in items if status is None or i["status"] == status]


def _save(items: List[dict]):
    with _lock:
        PROPOSALS_FILE.write_text(json.dumps(items[-100:], ensure_ascii=False, indent=1))


def propose(rule: str, reason: str) -> Optional[dict]:
    items = proposals(None)
    if any(i["rule"] == rule for i in items) or rule in rules():
        return None
    item = {"id": uuid.uuid4().hex[:8], "rule": rule.strip(), "reason": reason.strip(),
            "status": "pending", "created": datetime.datetime.now().isoformat(timespec="seconds")}
    _save(items + [item])
    return item


def decide(pid: str, approve: bool) -> dict:
    """社長の判断。承認なら learned_rules.md に1行足す"""
    items = proposals(None)
    item = next((i for i in items if i["id"] == pid), None)
    if not item:
        raise KeyError("提案が見つかりません")
    if item["status"] != "pending":
        return item
    item["status"] = "approved" if approve else "rejected"
    item["decided"] = datetime.datetime.now().isoformat(timespec="seconds")
    if approve:
        p = rules_path()
        p.parent.mkdir(parents=True, exist_ok=True)
        text = p.read_text() if p.exists() else RULES_HEADER
        p.write_text(text.rstrip("\n") + f"\n- {item['rule']}({datetime.date.today():%Y-%m-%d} 追加)\n")
    _save(items)
    return item


def summary_text() -> str:
    pend = proposals()
    return f"- 修正ログ: 直近{len(recent())}件 / 学んだルール{len(rules())}件 / 社長の判断待ちのルール案{len(pend)}件"
