"""進行管理: 親タスクの下が全部終わって、社長に見せられる状態になったときだけ報告する(2026-11-15 社長)。

社長の言葉: 「親タスクが完了していないのに作業完了報告が来た。途中経過の報告はいらない。
進行表で全て完了済み・私に見せられる状態になってから完了報告をして。親タスクが完了した際に教えて」

流れ(部署の作業が終わるたび・社長が答えるたび・朝のチェックで呼ぶ):
1. そのタスクの一番上の親(根)をたどる(親タスクの欄)
2. 根の下の子・孫を全部集める(子タスクの欄)
3. 1件でも まだ動いている(未着手・進行中・差し戻し・確認待ち)か、部署の作業が走っていれば、報告しない
   (次の一手に「残り n件」を書くだけ)
4. 全部が 完了・承認済み・承認待ち になったら、根を締めくくる
   - 承認待ち(社長に見てほしい投稿・企画書)が1件でもあれば、根も「承認待ち」。無ければ「完了」
   - 社長に1回だけ知らせる: 何が仕上がったか・見てほしいもの(承認待ち)の一覧
5. 同じ内容で2回知らせない(data/progress_notified.json に、知らせた親と見てほしいものを残す。
   親に新しい子が入って開き直したら記録を消し、もう一度全部終わったときに知らせる)
"""
import json
from pathlib import Path
from typing import Dict, List, Optional

import company

STATE = Path(__file__).resolve().parent / "data" / "progress_notified.json"
OPEN = ("未着手", "進行中", "差し戻し", "確認待ち")


def _load() -> Dict[str, str]:
    try:
        return json.loads(STATE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save(d: Dict[str, str]):
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")


def root_of(key: str, by_key: Dict[str, dict]) -> str:
    seen = set()
    while key in by_key and by_key[key].get("parent") and key not in seen:
        seen.add(key)
        nxt = by_key[key]["parent"][0]
        if nxt not in by_key:
            break
        key = nxt
    return key


def descendants(key: str, by_key: Dict[str, dict]) -> List[dict]:
    out, stack, seen = [], list(by_key.get(key, {}).get("children") or []), {key}
    while stack:
        k = stack.pop()
        if k in seen or k not in by_key:
            continue
        seen.add(k)
        out.append(by_key[k])
        stack.extend(by_key[k].get("children") or [])
    return out


def _is_president_step(t: dict) -> bool:
    """社長がする工程(承認・投稿など。確認待ち以外)は、そこまで来たら「社長に見せられる状態」"""
    return t.get("assignee") == "社長" and t.get("status") in ("未着手", "進行中")


def _blocks(t: dict, running: set) -> bool:
    return t["key"] in running or (t.get("status") in OPEN and not _is_president_step(t))


def _running_keys() -> set:
    try:
        import agent
        return {j.get("task_key") for j in agent.job_list() if j.get("status") == "running" and j.get("task_key")}
    except Exception:
        return set()


async def check(key: str, tasks: Optional[List[dict]] = None, notify: bool = True) -> dict:
    """key のタスクが属する親(根)を見て、全部終わっていれば締めくくって社長に知らせる。結果を返す"""
    if not key or key.startswith(("meeting:", "routine:")):
        return {"skipped": True}
    tasks = tasks if tasks is not None else await company.list_tasks()
    by_key = {t["key"]: t for t in tasks}
    if key not in by_key:
        return {"skipped": True}
    root = by_key[root_of(key, by_key)]
    family = [root] + descendants(root["key"], by_key)
    keys = {t["key"] for t in family}
    running = _running_keys() & keys
    # 途中のタスクの締めくくり(下から順に): 差し戻し・進行中のタスクで、下の子が全部終わり作業も走っていなければ完了にする
    # (差し戻しの直しが終わった/社長への確認の答えの続きが終わった工程など。承認待ちのものは子に残る)
    changed = True
    while changed:
        changed = False
        for t in family[1:]:
            if t.get("status") in ("差し戻し", "進行中") and t.get("children") and t["key"] not in running:
                sub = descendants(t["key"], by_key)
                if sub and not any(_blocks(c, running) for c in sub):
                    try:
                        await company.update_task(t["key"], status="完了", next_action="なし(子のタスクで済んだ)",
                                                  append_note="下の子のタスクが全部終わった(秘書が進行表で確認)")
                        t["status"] = "完了"
                        changed = True
                    except Exception:
                        pass
    # 逆算プランの次の工程を、ここで部署に頼む(デザインが終わったら品質管理へ、など)。頼んだらまだ途中
    try:
        import scheduler
        started = await scheduler.advance()
        for st in started:
            k = next((t["key"] for t in family if t.get("id") == st.get("task")), None)
            if k:
                running.add(k)
                by_key[k]["status"] = "進行中"
    except Exception:
        pass
    waiting = [t for t in family[1:] if _blocks(t, set())]
    state = _load()
    # まだ終わっていない: 子・孫に動いているものがある/部署の作業が走っている/根そのものが作業中
    if running or waiting or root.get("status") in ("未着手", "差し戻し", "確認待ち") or (len(family) == 1 and root.get("status") == "進行中"):
        left = len(waiting) + len(running - {t["key"] for t in waiting})
        if state.pop(root["key"], None) is not None:  # 一度締めた親に新しい子(差し戻しの直しなど)が入った
            _save(state)
        if len(family) > 1 and root.get("status") not in ("承認済み",):
            try:
                names = "・".join((t.get("id") or "") for t in waiting[:5])
                reopen = "進行中" if root.get("status") in ("完了", "承認待ち") else None
                await company.update_task(root["key"], status=reopen,
                                          next_action=f"秘書: 子の残り {left}件({names or '作業中'})。全部終わったら社長に報告")
            except Exception:
                pass
        return {"root": root.get("id"), "ready": False, "left": left}
    review = [t for t in family if t.get("status") == "承認待ち" or (t is not root and _is_president_step(t))]
    new_status = "承認待ち" if review else "完了"
    review_ids = sorted(t["key"] for t in review)
    told = state.get(root["key"])
    if told is not None and not (set(review_ids) - set(told)):
        return {"root": root.get("id"), "ready": True, "already": True}  # 同じ内容で2回知らせない(承認しただけ等)
    if len(family) > 1 and root.get("status") not in ("完了", "承認済み"):
        try:
            nxt = "社長: 承認待ちの中身を見て承認" if review else "なし(完了)"
            await company.update_task(root["key"], status=new_status if root.get("status") != new_status else None,
                                      next_action=nxt, append_note="子のタスクが全部終わり、社長に見せられる状態になった(秘書が進行表で確認)")
        except Exception:
            pass
    state[root["key"]] = review_ids
    _save(state)
    if notify:
        try:
            import scheduler
            head = f"「{root.get('title', '')}」({root.get('id', '')})が仕上がりました。"
            mine = [t for t in family[1:] if _is_president_step(t)]
            if len(family) > 1:
                head += f"進行表で確認し、子のタスク {len(family) - 1 - len(mine)}件は全部終わっています。"
            if mine:
                head += "あとは社長の番(" + "・".join(t.get("title", "").split(": ")[-1][:20] for t in mine[:3]) + ")です。"
            lines = [head]
            if review:
                lines.append("見てほしいもの: " + "、".join(f"{t.get('id')} {t.get('title', '')[:40]}" for t in review[:6]))
            else:
                lines.append("社長に見ていただくものはありません(結果は作業ログ)。")
            scheduler.notify("仕上がりました", "\n".join(lines), "done")
        except Exception:
            pass
    return {"root": root.get("id"), "ready": True, "status": new_status, "review": [t.get("id") for t in review]}


async def check_all(tasks: Optional[List[dict]] = None) -> List[dict]:
    """開いている親(子を持つタスク)を全部見る。朝のチェックや見回りから呼ぶ"""
    tasks = tasks if tasks is not None else await company.list_tasks()
    out = []
    for t in tasks:
        if t.get("children") and not t.get("parent") and t.get("status") not in ("完了", "承認済み"):
            out.append(await check(t["key"], tasks))
    return out
