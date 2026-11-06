"""組織図: ai-company/.claude/agents/*.md(部署の人材定義)を読む。

各ファイルの先頭(--- で囲んだ部分)の name / description に加えて、任意で
department(部署名)/ title(役職)/ boss(true なら上司)/ model を読む。
"""
import re
from typing import Dict, List

import company
import content

DEPT_FROM_NAME = {"strategy": "経営戦略部", "planning": "企画編集部", "production": "ライティング部",
                  "media": "SNS運用部", "analysis": "データ分析部"}


def members() -> List[dict]:
    d = company.COMPANY_DIR / ".claude" / "agents"
    out = []
    for p in sorted(d.glob("*.md")) if d.exists() else []:
        meta, body = content.parse(p.read_text())
        name = meta.get("name", p.stem)
        desc = meta.get("description", "")
        dept = meta.get("department") or DEPT_FROM_NAME.get(name) or (re.match(r"^(\S+?部)", desc) or [None, "その他"])[1]
        out.append({"name": name, "department": dept, "title": meta.get("title") or desc.split("。")[0][:30],
                    "boss": meta.get("boss", "").lower() == "true", "model": meta.get("model", ""),
                    "description": desc, "file": str(p.relative_to(company.COMPANY_DIR))})
    return out


ORDER = ["秘書室", "経営戦略部", "収益化部", "企画編集部", "ライティング部", "デザイン部", "画像制作部", "映像制作部",
         "SNS運用部", "品質管理部", "データ分析部"]


def chart() -> Dict[str, List[dict]]:
    """部署 → 社員(上司が先)。部署の並びは組織図の順"""
    depts: Dict[str, List[dict]] = {}
    for m in members():
        depts.setdefault(m["department"], []).append(m)
    for v in depts.values():
        v.sort(key=lambda m: not m["boss"])  # 上司を先に、担当は定義の並び
    rank = {d: i for i, d in enumerate(ORDER)}
    return dict(sorted(depts.items(), key=lambda kv: rank.get(kv[0], len(ORDER))))
