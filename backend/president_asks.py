"""部署の作業報告から「社長への確認・判断」を拾い、タスク(状態=確認待ち・担当=社長)にする。

2026-11-10 社長の指示: 「確認漏れが起こらないように、私への確認事項がある際はタスク化して確認待ちで判断を仰ぐ。
何についてなのかがちゃんとわかるように記載してタスク化する」
これまで部署が data/tasks.md(控え)にだけ書き、Notion(社長が見る場所)に届かず、作業ログで初めて気づく事が起きていた。

1. 作業報告の「## 社長への確認」の節(決まった形)を読む
2. 節が無いのに「社長の判断」などの言葉があれば、AI で同じ形に取り出す(API が使えないときは、作業報告を見てほしいという1件にする)
3. 同じ件名の確認がまだ開いていれば、二重に作らない
"""
import json
import re
import subprocess
from typing import List, Optional

import company

SECTION = re.compile(r"^#{2,3}\s*社長への確認\s*$", re.M)
SIGNALS = ("社長の判断", "社長に確認", "社長への確認", "社長判断", "社長に決めて", "社長が決め", "社長の承認が要", "社長にお願いしたい")
OPEN = ("未着手", "進行中", "確認待ち", "承認待ち")
FIELDS = {"背景": "background", "何について": "background", "選択肢": "options", "おすすめ": "recommend",
          "部署のおすすめ": "recommend", "未回答のとき": "if_no_answer", "期限": "due", "資料": "source"}

# 社長の回答で再開した作業の件名(2026-11-12 社長「社長確認になった後のタイトルが1番わかりにくい」)
# 以前は「T-312 への社長の回答を受けて再開:T-311 への社長の回答を受けて再開:表示名…」と前の件名に積み重なり、途中で切れていた
RESUME_PREFIX = re.compile(r"^(?:\s*T-\d+\s*への社長の回答を受けて再開[::]?\s*)+")
RESUME_SUFFIX = re.compile(r"(?:\s*[((]社長の回答で続き[・･][^))]*[))])+\s*$")


def base_title(title: str) -> str:
    """作業の件名から、再開のたびに付いた前置き・後ろ書きを外して、元の作業名だけにする"""
    t = re.sub(r"^【[^】]*】", "", (title or "").strip())
    t = RESUME_SUFFIX.sub("", RESUME_PREFIX.sub("", t))
    t = re.sub(r"\s*の報告に、社長の判断が要る事項があります$", "", t)
    return t.strip()


def resume_title(work: str, task_id: str, question: str = "") -> str:
    """再開した作業の件名: 「元の作業名(社長の回答で続き・T-329)」。元の作業名が分からなければ確認の件名を使う"""
    base = base_title(work) or base_title(question) or "止まっていた作業"
    if len(base) > 60:
        base = base[:59] + "…"
    return f"{base}(社長の回答で続き・{task_id})" if task_id else f"{base}(社長の回答で続き)"


FORMAT_HELP = """## 社長への確認
### (件名: 何についての判断か、社長が件名だけで分かる1行。例: 47週カルーセル03の表紙を、どの形で出すか)
- 背景: (何が起きていて、なぜ社長の判断が要るか。点数・社内の言葉は言い換える)
- 選択肢: A 〜 / B 〜 / C 〜
- おすすめ: (部署のおすすめと理由)
- 未回答のとき: (例: 出さない)
- 期限: YYYY-MM-DD
- 資料: (会社のフォルダの中のパス)"""


def parse(text: str) -> List[dict]:
    """作業報告の「## 社長への確認」の節から、確認事項を取り出す"""
    m = SECTION.search(text or "")
    if not m:
        return []
    body = text[m.end():]
    nxt = re.search(r"^#{1,2}\s(?!#)", body, re.M)  # 次の大見出しまで
    body = body[:nxt.start()] if nxt else body
    asks, cur = [], None
    for line in body.splitlines():
        h = re.match(r"^#{3,4}\s*(.+?)\s*$", line)
        if h:
            cur = {"title": h.group(1).strip("()() ")}
            asks.append(cur)
            continue
        f = re.match(r"^\s*[-・*]\s*([^::]{1,8})[::]\s*(.+)$", line)
        if f and cur is not None and f.group(1).strip() in FIELDS:
            key = FIELDS[f.group(1).strip()]
            cur[key] = (cur.get(key, "") + " " + f.group(2).strip()).strip()
    return [a for a in asks if a.get("title")]


def needs_extraction(text: str) -> bool:
    return not SECTION.search(text or "") and any(w in (text or "") for w in SIGNALS)


def _repo_url() -> str:
    try:
        url = subprocess.run(["git", "remote", "get-url", "origin"], cwd=str(company.COMPANY_DIR),
                             capture_output=True, text=True, timeout=10).stdout.strip()
        url = re.sub(r"https://[^@/]+@", "https://", url).removesuffix(".git")
        return url if url.startswith("https://github.com/") else ""
    except Exception:
        return ""


def _link(source: str) -> str:
    """資料のパスを GitHub の URL にする(社長がスマホでも開ける)"""
    m = re.search(r"(?:^|\s|`)((?:content|strategy|playbooks|brand|data|knowledge|reports|meetings|finance|hr)/[^\s`、,()()]+)", source or "")
    if not m:
        return ""
    base = _repo_url()
    return f"{base}/blob/main/{m.group(1)}" if base else ""


def _note(a: dict, job: dict) -> str:
    parts = []
    for label, key in (("背景", "background"), ("選択肢", "options"), ("おすすめ", "recommend"),
                       ("未回答のとき", "if_no_answer"), ("資料", "source")):
        if a.get(key):
            parts.append(f"{label}: {a[key]}")
    parts.append(f"出どころ: {job.get('department', '')}の作業「{base_title(job.get('title') or '')[:60]}」の報告")
    parts.append("決め方: 備考に選んだ案を書いて「承認済み」に(直してほしいときは「差し戻し」)")
    return " / ".join(parts)


def _due(a: dict) -> Optional[str]:
    m = re.search(r"(20\d\d)[-/](\d{1,2})[-/](\d{1,2})", a.get("due", ""))
    return f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}" if m else None


async def create_tasks(job: dict, asks: List[dict]) -> List[dict]:
    """確認事項をタスク(確認待ち・担当=社長)にする。同じ件名が開いていれば作らない"""
    try:
        existing = await company.list_tasks()
    except Exception:
        existing = []
    # 控え(tasks.md)では件名のうしろに備考が付くので、件名の先頭が同じなら同じ確認とみなす
    open_titles = [re.sub(r"^【[^】]*】", "", t.get("title", "")).strip() for t in existing if t.get("status") in OPEN]
    made = []
    for a in asks:
        name = re.sub(r"^【[^】]*】", "", a["title"]).strip()[:90]
        if not name or any(o == name or o.startswith(name + "(") for o in open_titles):
            continue
        t = await company.create_task(f"【確認】{name}", "社長", _due(a), _note(a, job), _link(a.get("source", "")), status="確認待ち")
        open_titles.append(name)
        made.append(t)
        try:  # 作業のまとまりに「社長への確認」を1行足す(2026-11-12)
            import threads
            await threads.add(job.get("title", ""), "❓", f"社長への確認 {t.get('id', '')}「{name}」",
                              dept=job.get("department_full") or "", link=t.get("url", ""), link_text="確認タスク",
                              state="社長の確認待ち", relate_task=t.get("key", ""))
        except Exception:
            pass
    return made


async def extract_with_ai(job: dict) -> List[dict]:
    """「## 社長への確認」の節が無い報告から、AI で確認事項を取り出す(API が使えないときは空)"""
    import agent
    if not agent.API_KEY:
        return []
    system = ("あなたは秘書。部署の作業報告から「社長に判断・確認してほしいこと」だけを取り出し、JSON の配列で返す。"
              "各要素は title(何についての判断か、社長が件名だけで分かる1行。社内の略語・点数・記号は使わない)・"
              "background・options・recommend・if_no_answer・due(YYYY-MM-DD か空)・source(会社のフォルダ内のパスか空)。"
              "社長の判断が要らない報告なら [] を返す。JSON 以外は書かない。")
    raw = await agent._one_shot(system, (job.get("output") or "")[-8000:], max_tokens=3000, model=agent.ROUTINE_MODEL)
    m = re.search(r"\[.*\]", raw, re.S)
    try:
        items = json.loads(m.group()) if m else []
    except ValueError:
        return []
    return [i for i in items if isinstance(i, dict) and i.get("title")]


async def from_job(job: dict) -> List[dict]:
    """作業が終わったあとに呼ぶ。作ったタスクを返す"""
    text = job.get("output") or ""
    asks = parse(text)
    if not asks and needs_extraction(text):
        try:
            asks = await extract_with_ai(job)
        except Exception:
            asks = []
        if not asks:  # 取り出せなくても、確認があることだけは必ず残す
            asks = [{"title": f"「{base_title(job.get('title') or '')[:50] or '部署の作業'}」で、社長に決めてほしいことがあります(中身は作業ログ)",
                     "background": "作業報告に社長の判断・確認を求める文があります。作業タブか作業ログで報告を読んでください",
                     "source": ""}]
    return await create_tasks(job, asks) if asks else []
