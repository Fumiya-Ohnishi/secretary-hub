"""一度だけの棚卸し(2026-11-15 社長「毎週作っている明日以降のタスクも直せている?」)。

これまでのタスクの多くは親タスクにつながっておらず、会議で決まったことも起票しただけで誰も部署に頼んでいなかった。
新しい仕組み(親の木で順に頼む・親が仕上がったときだけ報告)に乗せるため、平日に一度だけ秘書室に棚卸しを頼む。
- 済んだもの・不要になったものは「完了」にして理由を備考に残す(消さない)
- まだ要るものはテーマごとの親タスクの子にし、期限を直す → 以後は秘書ハブが期限の早い順に部署へ自動で頼む
"""
import asyncio
import datetime
import json
from pathlib import Path

import company

FLAG = Path(__file__).resolve().parent / "data" / "adopt_done.json"

INSTRUCTION = """タスクの棚卸しをする(2026-11-15 社長の指示。CLAUDE.md「進行管理」「完了の報告は親が仕上がったときだけ」「部署から部署への受け渡し」)。
Notion のタスクDB で、完了・承認済み以外で「親タスク」が空のタスク(下の一覧)を1件ずつ見て、次のどれかにする。

1. 済んでいる(成果物がある・後のタスクや作業で置き換わった)→ ステータス「完了」。備考に根拠(どのファイル・どのタスクで済んだか)を書く
2. 不要になった(方針が変わった・期限が過ぎて意味がない・重複)→ ステータス「完了」。備考に「不要になった: 理由」。ページは消さない
3. まだ要る → テーマごとの親タスクの子にする(Notion の「親タスク」に親をつなぐ)。親は今ある開いたタスクを使うか、無ければ作る
   (例: 「48週の投稿セット」「無料 note と無料チェックリスト」「note 別アカウントの立ち上げ」「11/20 の振り返りで出す数字」)。
   新しく作る親は 担当=秘書・ステータス=進行中・次の一手を書く。子は 担当=部署名、期限を現実的な日付に直し(過ぎていたら今日以降に)、
   「次の一手」に「○○部: 順番が来たら秘書が頼む」と書く。親の下の子は、秘書ハブが期限の早い順に1つずつ部署へ自動で頼む
4. 古い【確認】【社長判断】で「差し戻し」のままのもの → 後の確認タスク・作業で答えが出ていれば「完了」(備考に答えの場所)。
   本当にまだ社長の判断が要り、しかも期限が近いものだけを、報告の「## 社長への確認」に今の形(選択肢 A・B・C、おすすめは記号から)で書く。
   それ以外は社長に聞かずに秘書室で決める(社長の好み knowledge/preferences.md・社長の人物像 knowledge/president_profile.md に沿って)
5. 社長の担当(数字の報告・予約投稿など)で期限が過ぎたもの → 済んでいるかをファイル(data/*.csv・content/drafts の status)で確かめて1か2に。
   分からないものは完了にせず、そのまま残す

守ること: 「承認済み」「承認待ち」「確認待ち」のタスクには触らない。どのタスクも「承認済み」「差し戻し」にはしない(社長だけ)。ページ・データベースは消さない。
新しい作業(制作・リサーチ)はこの作業の中でしない(つなぎ直しと状態の整理だけ。作業は秘書ハブが順に部署へ頼む)。
最後に作業報告へ、件数の表(済んでいた / 不要 / 親につないだ(親ごとの件数)/ 社長への確認)と、作った親タスクの一覧を書く。

## 対象(親が空の開いたタスク)
"""


async def run_once():
    """平日になったら一度だけ、秘書室に棚卸しを頼む"""
    import agent
    import scheduler
    await asyncio.sleep(90)  # 起動直後の見回りが落ち着いてから
    while not FLAG.exists():
        if scheduler.is_off_day() or not scheduler.settings().get("auto", True):
            await asyncio.sleep(1800)
            continue
        try:
            tasks = await company.list_tasks()
        except Exception:
            await asyncio.sleep(1800)
            continue
        orphans = [t for t in tasks if t.get("status") not in ("完了", "承認済み", "承認待ち", "確認待ち")
                   and not t.get("parent") and not t.get("children")]
        if orphans:
            root = await company.create_task("タスクの棚卸し(親タスクにつなぎ直し、済んだもの・不要なものを片づける)", "秘書", None,
                                             status="進行中", next_action="秘書室: 棚卸しの作業中",
                                             note=f"対象 {len(orphans)}件。新しい仕組み(親の木で順に頼む・仕上がったときだけ報告)に乗せるため")
            lines = "\n".join(f"- {t.get('id')} [{t.get('status')}・{t.get('assignee')}・期限{(t.get('due') or 'なし')[:10]}] {t.get('title', '')[:90]}"
                              for t in orphans[:200])
            agent.start_job("秘書", INSTRUCTION + lines, "タスクの棚卸し(進行表につなぎ直し)", root["key"])
        FLAG.parent.mkdir(parents=True, exist_ok=True)
        FLAG.write_text(json.dumps({"at": datetime.datetime.now().isoformat(timespec="seconds"), "count": len(orphans)}), encoding="utf-8")
