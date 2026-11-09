import React, { useEffect, useState } from "react";
import { createTask, patchTask, getDocs, getDoc, getWorklog, getDocTree, createJob, recordRevenue, recordFollowers, getOrg } from "./api.js";
import { Blocks } from "./DocView.jsx";
import Accounts from "./Accounts.jsx";
import { Calendar, OrgChart, Activity } from "./Extras.jsx";
import { LineChart, PLATFORM_COLORS } from "./Charts.jsx";
import Today from "./Today.jsx";
import Library from "./Library.jsx";
import { stripTone } from "./speech.js";

export const STATUSES = ["未着手", "進行中", "承認待ち", "承認済み", "完了", "差し戻し"];
const ASSIGNEES = ["秘書", "戦略", "収益化", "企画", "ライティング", "デザイン", "画像", "映像", "SNS運用", "品質管理", "分析", "社長"];
const DEPARTMENTS = ["戦略", "収益化", "企画", "ライティング", "デザイン", "画像", "映像", "SNS運用", "品質管理", "分析", "経理", "広報", "人事", "Codex"];
const DEPT_FULL = { 戦略: "経営戦略部", 収益化: "収益化部", 企画: "企画編集部", ライティング: "ライティング部", デザイン: "デザイン部",
  画像: "画像制作部", 映像: "映像制作部", SNS運用: "SNS運用部", 品質管理: "品質管理部", 分析: "データ分析部", 経理: "経理・税務部", 広報: "広報部", 人事: "人事部", Codex: "社外制作室(Codex)" };
const STATUS_CLASS = { 未着手: "s-todo", 進行中: "s-doing", 承認待ち: "s-wait", 承認済み: "s-ok", 完了: "s-done", 差し戻し: "s-ng" };

export function StatusBadge({ status }) {
  return <span className={`badge ${STATUS_CLASS[status] || ""}`}>{status}</span>;
}

function fmtDate(d) {
  if (!d) return "—";
  const [, m, day] = d.slice(0, 10).split("-");
  return `${Number(m)}/${Number(day)}`;
}

function overdue(t) {
  return t.due && !["完了", "承認済み"].includes(t.status) && t.due.slice(0, 10) < new Date().toISOString().slice(0, 10);
}

function notionId(url) {
  const m = (url || "").toLowerCase().match(/[0-9a-f]{32}|[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}/g);
  return m && /notion\.(so|site)/.test(url) ? m[m.length - 1].replace(/-/g, "") : null;
}

/* ---------------- 数字(グラフと記録) ---------------- */
const PLATFORM_JA = { instagram: "Instagram", x: "X", threads: "Threads", note: "note" };
const SOURCES = [["note_sales", "note販売"], ["amazon_affiliate", "Amazonアフィ"], ["other", "その他"]];

function Metrics({ metrics, usage, onChanged, notify }) {
  const [rev, setRev] = useState({ amount: "", source: "note_sales" });
  const [fol, setFol] = useState({ platform: "instagram", followers: "" });
  const followers = metrics?.followers || {};
  const series = Object.keys(PLATFORM_COLORS).filter((k) => followers[k]?.length).map((k) => ({
    key: k, label: PLATFORM_JA[k], color: PLATFORM_COLORS[k],
    points: followers[k].map((p) => ({ date: p.date, value: p.followers })),
  }));
  const daily = metrics?.revenue_daily || [];
  const saveRev = async (e) => {
    e.preventDefault();
    try { const r = await recordRevenue({ amount: Number(rev.amount), source: rev.source }); notify(`収益 ¥${r.amount.toLocaleString()} を記録しました`, "ok"); setRev({ ...rev, amount: "" }); onChanged(); }
    catch (err) { notify(err.message, "error"); }
  };
  const saveFol = async (e) => {
    e.preventDefault();
    try { const r = await recordFollowers({ platform: fol.platform, followers: Number(fol.followers) }); notify(`${PLATFORM_JA[r.platform]} ${r.followers}人を記録しました`, "ok"); setFol({ ...fol, followers: "" }); onChanged(); }
    catch (err) { notify(err.message, "error"); }
  };
  return (
    <div className="two-col">
      <section className="card">
        <div className="card-head"><h3>フォロワー数の推移</h3></div>
        {series.length ? <LineChart series={series} unit="人" /> : <div className="empty">まだ記録がありません。「インスタのフォロワー120人」と話しかけてください。</div>}
        <form className="rec-form" onSubmit={saveFol}>
          <select value={fol.platform} onChange={(e) => setFol({ ...fol, platform: e.target.value })}>
            {Object.entries(PLATFORM_JA).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
          </select>
          <input type="number" min="0" inputMode="numeric" value={fol.followers} placeholder="人数" onChange={(e) => setFol({ ...fol, followers: e.target.value })} />
          <button className="btn sm" disabled={fol.followers === ""}>記録</button>
        </form>
      </section>
      <section className="card">
        <div className="card-head"><h3>今月の収益(累計)</h3>{usage && <span className="muted small" title={`入力 ${usage.input.toLocaleString()} / 出力 ${usage.output.toLocaleString()} トークン・${usage.calls}回(1ドル=${usage.rate}円で概算)`}>AI利用料 約¥{usage.jpy.toLocaleString()}</span>}</div>
        {daily.length ? <LineChart series={[{ key: "rev", label: "累計収益", color: PLATFORM_COLORS.instagram, points: daily.map((d) => ({ date: d.date, value: d.cumulative })) }]} format={(v) => `¥${v.toLocaleString()}`} />
          : <div className="empty">今月の収益はまだありません。「今日 note が500円売れた」と話しかけると記録します。</div>}
        <form className="rec-form" onSubmit={saveRev}>
          <select value={rev.source} onChange={(e) => setRev({ ...rev, source: e.target.value })}>
            {SOURCES.map(([k, v]) => <option key={k} value={k}>{v}</option>)}
          </select>
          <input type="number" min="0" inputMode="numeric" value={rev.amount} placeholder="金額(円)" onChange={(e) => setRev({ ...rev, amount: e.target.value })} />
          <button className="btn sm" disabled={rev.amount === ""}>記録</button>
        </form>
      </section>
    </div>
  );
}

/* ---------------- ホーム ---------------- */
function Ring({ pct }) {
  const r = 34, c = 2 * Math.PI * r, p = Math.min(100, Math.max(0, pct));
  return (
    <svg className="ring" viewBox="0 0 80 80" aria-hidden="true">
      <circle cx="40" cy="40" r={r} className="ring-bg" />
      <circle cx="40" cy="40" r={r} className="ring-fg" strokeDasharray={`${(c * p) / 100} ${c}`} />
      <text x="40" y="45" textAnchor="middle">{p}%</text>
    </svg>
  );
}

function Home({ summary, jobs, onApprove, onSay, onTab, onOpenTask, onChanged, notify, onOpenWeek, onRule }) {
  const rules = summary.rule_proposals || [];
  const { revenue, tasks } = summary;
  const contentWaiting = (summary.content_weeks || []).filter((w) => w.counts["承認待ち"]);
  const approvals = tasks.filter((t) => t.status === "承認待ち");
  const doing = tasks.filter((t) => ["進行中", "未着手", "差し戻し"].includes(t.status));
  const running = jobs.filter((j) => j.status === "running");
  const late = tasks.filter(overdue);
  return (
    <div className="home">
      <div className="kpis">
        <div className="kpi kpi-rev">
          <Ring pct={revenue.progress} />
          <div>
            <div className="kpi-num">¥{revenue.month_total.toLocaleString()}</div>
            <div className="kpi-lbl">今月の収益 / 目標 ¥{revenue.goal.toLocaleString()}</div>
          </div>
        </div>
        <button className={`kpi ${approvals.length + contentWaiting.length ? "attn" : ""}`} onClick={() => onTab("tasks", "承認待ち")}>
          <div className="kpi-num">{approvals.length + contentWaiting.length}</div><div className="kpi-lbl">承認待ち</div>
        </button>
        <button className="kpi" onClick={() => onTab("tasks", "未完了")}>
          <div className="kpi-num">{doing.length}</div><div className="kpi-lbl">未完了タスク</div>
        </button>
        <button className={`kpi ${late.length ? "late" : ""}`} onClick={() => onTab("tasks", "未完了")}>
          <div className="kpi-num">{late.length}</div><div className="kpi-lbl">期限切れ</div>
        </button>
      </div>

      <section className="card">
        <div className="card-head"><h3>社長の判断待ち</h3><span className="muted">{approvals.length + contentWaiting.length + rules.length}件
          {summary.scheduler && ` ・ 次の定時チェック ${summary.scheduler.auto ? summary.scheduler.next : "オフ"}`}</span></div>
        {approvals.length === 0 && contentWaiting.length === 0 && rules.length === 0 && <div className="empty">いま判断が必要なものはありません。</div>}
        {rules.map((p) => (
          <div key={p.id} className="approval-item">
            <div className="ai-main" onClick={() => onRule(p)}>
              <span className="tid">ルール</span><span className="ttl">{p.rule}</span>
            </div>
            <button className="btn primary sm" onClick={() => onRule(p)}>確認する</button>
          </div>
        ))}
        {contentWaiting.map((w) => (
          <div key={w.week} className="approval-item">
            <div className="ai-main" onClick={() => onOpenWeek(w.week)}>
              <span className="tid">投稿</span><span className="ttl">{w.week} の投稿セット「{w.theme || "テーマ未定"}」承認待ち {w.counts["承認待ち"]}件</span>
            </div>
            <button className="btn primary sm" onClick={() => onOpenWeek(w.week)}>中身を見る</button>
          </div>
        ))}
        {approvals.map((t) => (
          <div key={t.key} className="approval-item">
            <div className="ai-main" onClick={() => onOpenTask(t)}>
              <span className="tid">{t.id}</span><span className="ttl">{t.title}</span>
            </div>
            <button className="btn primary sm" onClick={() => onApprove(t)}>確認する</button>
          </div>
        ))}
      </section>

      <div className="two-col">
        <section className="card">
          <div className="card-head"><h3>進めている仕事</h3><button className="link" onClick={() => onTab("tasks", "未完了")}>すべて</button></div>
          {doing.slice(0, 6).map((t) => (
            <div key={t.key} className="mini-row" onClick={() => onOpenTask(t)}>
              <StatusSelect task={t} onApprove={onApprove} onChanged={onChanged} notify={notify} />
              <span className="ttl" title="クリックでタスクの詳細へ">{t.title}</span>
              <DueButton task={t} onChanged={onChanged} notify={notify} />
            </div>
          ))}
          {doing.length === 0 && <div className="empty">未完了のタスクはありません。</div>}
        </section>
        <section className="card">
          <div className="card-head"><h3>部署の作業</h3><button className="link" onClick={() => onTab("jobs")}>すべて</button></div>
          {jobs.slice(0, 4).map((j) => (
            <div key={j.id} className="mini-row" onClick={() => onTab("jobs")}>
              <span className={`job-dot ${j.status}`} /><span className="ttl">{j.department_full || j.department + "部"}:{j.title}</span>
            </div>
          ))}
          {jobs.length === 0 && <div className="empty">まだ依頼はありません。「戦略部に〜を頼んで」と話しかけてください。</div>}
          {running.length > 0 && <div className="muted small">{running.length}件 作業中…</div>}
        </section>
      </div>

      <Metrics metrics={summary.metrics} usage={summary.usage} onChanged={onChanged} notify={notify} />

      <section className="card say">
        <h3>こう話しかけてみてください</h3>
        <div className="chips">
          {["今日の報告をして", "今日の投稿を始めて", "今週の投稿を見せて", "企画書を開いて要約して", "T-014 の期限を来週金曜にして",
            "企画部に来週の投稿セットを作ってもらって", "インスタのフォロワー120人", "今日 note が500円売れた",
            "週次レポートを作って", "来週金曜の投稿に向けて逆算して進めて", "これを今後のルールにして"].map((s) => (
            <button key={s} className="chip" onClick={() => onSay(s)}>「{s}」</button>
          ))}
        </div>
      </section>
    </div>
  );
}

/* ---------------- タスク ---------------- */
const FILTERS = ["未完了", "承認待ち", "完了", "すべて"];

/** 期限の変更(日付を選んで「変更」。「期限なし」で消す) */
function DueEditor({ task, onChanged, notify, onDone, autoFocus }) {
  const current = (task.due || "").slice(0, 10);
  const [value, setValue] = useState(current);
  const [saving, setSaving] = useState(false);
  useEffect(() => setValue(current), [current]);
  const save = async (due) => {
    setSaving(true);
    try {
      const t = await patchTask(task.key, { due });
      notify(due ? `${t.id} の期限を ${fmtDate(due)} にしました` : `${t.id} の期限をなしにしました`, "ok");
      onChanged();
      onDone?.();
    } catch (err) { notify(err.message, "error"); setValue(current); }
    setSaving(false);
  };
  return (
    <div className="due-editor" onClick={(e) => e.stopPropagation()}>
      <span className="muted small">期限</span>
      <input type="date" value={value} autoFocus={autoFocus} onChange={(e) => setValue(e.target.value)}
             onKeyDown={(e) => { if (e.key === "Enter" && value && value !== current) save(value); if (e.key === "Escape") onDone?.(); }} />
      <button className="btn primary sm" disabled={saving || !value || value === current} onClick={() => save(value)}>変更</button>
      {current && <button className="btn ghost sm" disabled={saving} onClick={() => save("")}>期限なし</button>}
    </div>
  );
}

/** 状態の選択。承認済み・差し戻しは承認カードで確定する */
function StatusSelect({ task, onApprove, onChanged, notify }) {
  const change = async (status) => {
    if (status === "承認済み" || status === "差し戻し") return onApprove(task);
    try { await patchTask(task.key, { status }); notify(`${task.id} を「${status}」にしました`, "ok"); onChanged(); }
    catch (err) { notify(err.message, "error"); }
  };
  return (
    <select className={`status-sel ${STATUS_CLASS[task.status] || ""}`} value={task.status} title="クリックで状態を変更"
            onClick={(e) => e.stopPropagation()} onChange={(e) => change(e.target.value)}>
      {STATUSES.map((st) => <option key={st}>{st}</option>)}
    </select>
  );
}

/** 期限の表示。クリックするとその場で変更できる */
function DueButton({ task, onChanged, notify }) {
  const [open, setOpen] = useState(false);
  const ref = React.useRef(null);
  useEffect(() => {
    if (!open) return;
    const close = (e) => { if (ref.current && !ref.current.contains(e.target)) setOpen(false); };
    document.addEventListener("pointerdown", close);
    return () => document.removeEventListener("pointerdown", close);
  }, [open]);
  return (
    <span className="due-wrap" ref={ref} onClick={(e) => e.stopPropagation()}>
      <button className={`due due-btn ${overdue(task) ? "over" : ""}`} title="クリックで期限を変更" onClick={() => setOpen(!open)}>
        {task.due ? fmtDate(task.due) : "期限なし"}
      </button>
      {open && (
        <div className="due-pop">
          <DueEditor task={task} onChanged={onChanged} notify={notify} onDone={() => setOpen(false)} autoFocus />
        </div>
      )}
    </span>
  );
}

function Tasks({ summary, filter, setFilter, onApprove, onChanged, onOpenDoc, focusKey, notify }) {
  const [form, setForm] = useState({ title: "", assignee: "秘書", due: "" });
  const [open, setOpen] = useState(focusKey);
  const [saving, setSaving] = useState(false);
  useEffect(() => setOpen(focusKey), [focusKey]);

  const list = summary.tasks.filter((t) =>
    filter === "すべて" ? true : filter === "未完了" ? !["完了", "承認済み"].includes(t.status) : filter === "完了" ? ["完了", "承認済み"].includes(t.status) : t.status === filter);

  const add = async (e) => {
    e.preventDefault();
    if (!form.title.trim()) return;
    setSaving(true);
    try {
      const t = await createTask({ ...form, due: form.due || null });
      notify(`${t.id} を起票しました`);
      setForm({ title: "", assignee: "秘書", due: "" });
      onChanged();
    } catch (err) { notify(err.message, "error"); }
    setSaving(false);
  };

  return (
    <div className="tasks">
      <form className="add-task" onSubmit={add}>
        <input value={form.title} onChange={(e) => setForm({ ...form, title: e.target.value })} placeholder="新しいタスク(話しかけて起票もできます)" />
        <select value={form.assignee} onChange={(e) => setForm({ ...form, assignee: e.target.value })}>
          {ASSIGNEES.map((a) => <option key={a}>{a}</option>)}
        </select>
        <input type="date" value={form.due} onChange={(e) => setForm({ ...form, due: e.target.value })} />
        <button className="btn primary" disabled={saving || !form.title.trim()}>起票</button>
      </form>
      <div className="seg">
        {FILTERS.map((f) => <button key={f} className={filter === f ? "on" : ""} onClick={() => setFilter(f)}>{f}</button>)}
        <span className="muted small src">{summary.task_source === "notion" ? "Notion と同期" : "控えファイル(Notion 未接続)"}</span>
      </div>
      {summary.task_error && <div className="warnbox">Notion に接続できないため控えを表示中:{summary.task_error}</div>}
      <div className="task-list">
        {list.map((t) => (
          <div key={t.key} className={`task ${open === t.key ? "open" : ""}`}>
            <div className="task-row" onClick={() => setOpen(open === t.key ? null : t.key)}>
              <span className="tid">{t.id}</span>
              <span className="ttl">{t.title}</span>
              <span className="who">{t.assignee}</span>
              <DueButton task={t} onChanged={onChanged} notify={notify} />
              <StatusSelect task={t} onApprove={onApprove} onChanged={onChanged} notify={notify} />
            </div>
            {open === t.key && (
              <div className="task-detail">
                <DueEditor task={t} onChanged={onChanged} notify={notify} />
                {t.note ? <p>{t.note}</p> : <p className="muted">備考なし</p>}
                <div className="row-actions">
                  {t.status === "承認待ち" && <button className="btn primary sm" onClick={() => onApprove(t)}>承認 / 差し戻し</button>}
                  {notionId(t.link) && <button className="btn sm" onClick={() => onOpenDoc(notionId(t.link))}>資料を開く</button>}
                  {t.link && !notionId(t.link) && <a className="btn sm" href={t.link} target="_blank" rel="noreferrer">資料</a>}
                  {t.url && <a className="btn ghost sm" href={t.url} target="_blank" rel="noreferrer">Notion で開く</a>}
                </div>
              </div>
            )}
          </div>
        ))}
        {list.length === 0 && <div className="empty">該当するタスクはありません。</div>}
      </div>
    </div>
  );
}

/* ---------------- 資料 ---------------- */
function NotionSetup() {
  return (
    <div className="card setup">
      <h3>Notion をつなぐと、ここで資料を読めます</h3>
      <ol>
        <li><a href="https://www.notion.so/profile/integrations" target="_blank" rel="noreferrer">Notion のインテグレーション画面</a>で「新しいインテグレーション」を作る(名前: 秘書ハブ、種類: 内部)</li>
        <li>表示された「シークレット」をコピーし、<code>secretary-hub/backend/.env</code> に <code>NOTION_TOKEN=コピーした値</code> を1行追加(チャットには貼らないでください)</li>
        <li>Notion の「AI会社」ページ右上の「•••」→「接続」→「秘書ハブ」を選ぶ</li>
        <li>秘書ハブを再起動(ターミナルで Ctrl+C → <code>run_mac.command</code>)</li>
      </ol>
      <p className="muted small">つなぐまでは、タスクは ai-company/data/tasks.md(控え)で管理します。</p>
    </div>
  );
}

function Docs({ docId, setDocId, notify }) {
  const [docs, setDocs] = useState(null);
  const [doc, setDoc] = useState(null);
  const [q, setQ] = useState("");
  const [kind, setKind] = useState("all");
  const [rowQ, setRowQ] = useState("");
  const [loading, setLoading] = useState(false);
  const [view, setViewState] = useState(() => { try { return localStorage.getItem("docsView") || "log"; } catch (e) { return "log"; } });
  const setView = (v) => { setViewState(v); try { localStorage.setItem("docsView", v); } catch (e) {} };
  const [log, setLog] = useState(null);
  const [tree, setTree] = useState(null);
  const [dept, setDept] = useState("");
  const [open, setOpen] = useState({});

  useEffect(() => {
    getDocs().then(setDocs).catch((e) => { setDocs({ configured: true, docs: [], error: e.message }); });
    getWorklog().then(setLog).catch((e) => setLog({ rows: [], error: e.message }));
    getDocTree().then(setTree).catch((e) => setTree({ tree: [], error: e.message }));
  }, []);
  useEffect(() => {
    if (!docId) { setDoc(null); return; }
    setLoading(true); setRowQ("");
    getDoc(docId).then(setDoc).catch((e) => { notify(e.message, "error"); setDocId(null); }).finally(() => setLoading(false));
  }, [docId]);

  if (!docs) return <div className="empty">読み込み中…</div>;
  if (!docs.configured) return <NotionSetup />;
  const ql = q.toLowerCase();
  const shown = docs.docs.filter((d) => d.title.toLowerCase().includes(ql) && (kind === "all" || (d.kind || "page") === kind));
  const nDb = docs.docs.filter((d) => d.kind === "database").length, nPage = docs.docs.length - nDb;
  const rowsShown = doc?.kind === "database" ? doc.rows.filter((r) => !rowQ || r.cells.join(" ").toLowerCase().includes(rowQ.toLowerCase())) : [];

  return (
    <div className={`docs ${docId ? "reading" : ""}`}>
      <aside className="doc-list">
        <div className="doc-views">
          {[["log", "📅 作業ログ"], ["folder", "📁 フォルダ"], ["all", "🔍 全部"]].map(([k, l]) => (
            <button key={k} className={view === k ? "on" : ""} onClick={() => setView(k)}>{l}</button>
          ))}
        </div>
        <input className="search" value={q} onChange={(e) => setQ(e.target.value)} placeholder={view === "log" ? "作業名で探す" : "資料を検索"} />
        {view === "log" && <WorkLogList log={log} q={ql} dept={dept} setDept={setDept} open={open} setOpen={setOpen} docId={docId} setDocId={setDocId} />}
        {view === "folder" && <FolderTree tree={tree} q={ql} open={open} setOpen={setOpen} docId={docId} setDocId={setDocId} />}
        {view === "all" && <>
          <div className="doc-kinds">
            {[["all", `すべて ${docs.docs.length}`], ["page", `ページ ${nPage}`], ["database", `データベース ${nDb}`]].map(([k, l]) => (
              <button key={k} className={kind === k ? "on" : ""} onClick={() => setKind(k)}>{l}</button>
            ))}
          </div>
          {docs.error && <div className="warnbox">{docs.error}</div>}
          {shown.map((d) => (
            <button key={d.id} className={`doc-item ${docId === d.id ? "on" : ""} ${d.kind === "database" ? "db" : ""}`} onClick={() => setDocId(d.id)}>
              <span className="doc-icon">{d.icon || "📄"}</span>
              <span className="doc-title">{d.title}{d.kind === "database" && <span className="doc-kind">表</span>}</span>
              <span className="muted small">{d.edited?.slice(5, 10).replace("-", "/")}</span>
            </button>
          ))}
          {shown.length === 0 && <div className="empty">資料がありません。</div>}
          <div className="muted small doc-note">秘書ハブに接続したページの中だけが出ます。足りないときは Notion でそのページの「•••」→「接続」→「秘書ハブ」。</div>
        </>}
      </aside>
      <article className="doc-reader">
        {!docId && <div className="empty big">左の一覧から選ぶか、「企画書を開いて」と話しかけてください。</div>}
        {docId && loading && <div className="empty">読み込み中…</div>}
        {docId && !loading && doc && (
          <>
            <div className="doc-head">
              <button className="btn ghost sm back" onClick={() => setDocId(null)}>← 一覧</button>
              <h2>{doc.icon} {doc.title}</h2>
              <a className="btn ghost sm" href={doc.url} target="_blank" rel="noreferrer">Notion で開く</a>
            </div>
            {doc.kind === "database" ? (
              <div className="doc-body">
                <div className="doc-db-bar">
                  <input className="search" value={rowQ} onChange={(e) => setRowQ(e.target.value)} placeholder="この表の中を検索" />
                  <span className="muted small">{rowsShown.length}件{doc.more ? "(新しい300件まで)" : ""}</span>
                </div>
                <div className="doc-table-wrap">
                  <table className="doc-table doc-db">
                    <thead><tr>{doc.columns.map((c) => <th key={c}>{c}</th>)}</tr></thead>
                    <tbody>
                      {rowsShown.map((r) => (
                        <tr key={r.id} onClick={() => setDocId(r.id)} title="押すとこの行のページを開きます">
                          {r.cells.map((c, j) => <td key={j}>{j === 0 ? <span className="doc-row-title">{r.icon} {c || "(無題)"}</span> : c}</td>)}
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
                {rowsShown.length === 0 && <div className="empty">行がありません。</div>}
              </div>
            ) : (
              <div className="doc-body"><Blocks blocks={doc.blocks} onOpenPage={setDocId} /></div>
            )}
          </>
        )}
      </article>
    </div>
  );
}

/* 作業ログ: 日付のフォルダ(今日・昨日・…)に、その日の社員の作業を並べる */
const WD = "日月火水木金土";
function dayLabel(d) {
  const t = new Date(); t.setHours(0, 0, 0, 0);
  const x = new Date(d + "T00:00:00"), diff = Math.round((t - x) / 864e5);
  const md = `${x.getMonth() + 1}/${x.getDate()}(${WD[x.getDay()]})`;
  return diff === 0 ? `今日 ${md}` : diff === 1 ? `昨日 ${md}` : md;
}
function WorkLogList({ log, q, dept, setDept, open, setOpen, docId, setDocId }) {
  if (!log) return <div className="empty">読み込み中…</div>;
  const rows = (log.rows || []).filter((r) => (!q || r.title.toLowerCase().includes(q)) && (!dept || r.dept === dept));
  const depts = [...new Set((log.rows || []).map((r) => r.dept).filter(Boolean))];
  const days = [];
  for (const r of rows) { const last = days[days.length - 1]; if (last && last.date === r.date) last.items.push(r); else days.push({ date: r.date, items: [r] }); }
  const months = {};
  return (
    <div className="wl">
      {log.error && <div className="warnbox">{log.error}</div>}
      {depts.length > 0 && (
        <select className="wl-dept" value={dept} onChange={(e) => setDept(e.target.value)}>
          <option value="">すべての部署</option>
          {depts.map((d) => <option key={d} value={d}>{d}</option>)}
        </select>
      )}
      {days.map((d, i) => {
        const key = "d" + d.date, isOpen = open[key] ?? i < 2;
        const ym = d.date.slice(0, 7), head = !months[ym] && i >= 2; months[ym] = true;
        return (
          <React.Fragment key={d.date}>
            {head && <div className="wl-month">{Number(ym.slice(5))}月</div>}
            <div className={`wl-day ${isOpen ? "open" : ""}`}>
              <button className="wl-day-head" onClick={() => setOpen({ ...open, [key]: !isOpen })}>
                <span>{isOpen ? "📂" : "📁"} {dayLabel(d.date)}</span><span className="muted small">{d.items.length}件</span>
              </button>
              {isOpen && d.items.map((r) => (
                <button key={r.id} className={`doc-item wl-item ${docId === r.id ? "on" : ""}`} onClick={() => setDocId(r.id)}>
                  <span className={`wl-st ${r.status === "完了" ? "ok" : "ng"}`} title={r.status} />
                  <span className="doc-title">{r.title}<span className="wl-meta">{r.dept}{r.kind ? ` ・ ${r.kind}` : ""}{r.time ? ` ・ ${r.time}` : ""}</span></span>
                </button>
              ))}
            </div>
          </React.Fragment>
        );
      })}
      {days.length === 0 && <div className="empty">まだ作業ログがありません。部署の作業が終わると、日付ごとにここへ並びます。</div>}
    </div>
  );
}

/* フォルダ: Notion「AI会社」ページの中身(フォルダ・データベース) */
function FolderTree({ tree, q, open, setOpen, docId, setDocId }) {
  if (!tree) return <div className="empty">読み込み中…</div>;
  const match = (it) => !q || it.title.toLowerCase().includes(q) || (it.children || []).some(match);
  const Item = ({ it, depth }) => {
    const hasKids = it.children && it.children.length > 0, key = "f" + it.id, isOpen = q ? true : (open[key] ?? (depth === 0 && it.title.includes("戦略")));
    return (
      <div className="ft-item" style={{ paddingLeft: depth * 14 }}>
        <div className="ft-row">
          {hasKids ? <button className="ft-tg" onClick={() => setOpen({ ...open, [key]: !isOpen })}>{isOpen ? "▾" : "▸"}</button> : <span className="ft-tg" />}
          <button className={`doc-item ${docId === it.id ? "on" : ""}`} onClick={() => (hasKids && !isOpen ? setOpen({ ...open, [key]: true }) : setDocId(it.id))}>
            <span className="doc-icon">{it.kind === "database" ? "🗂" : it.children ? (isOpen && hasKids ? "📂" : "📁") : "📄"}</span>
            <span className="doc-title">{it.title}{it.kind === "database" && <span className="doc-kind">表</span>}</span>
          </button>
        </div>
        {hasKids && isOpen && it.children.filter(match).map((c) => <Item key={c.id} it={c} depth={depth + 1} />)}
      </div>
    );
  };
  return (
    <div className="ft">
      {tree.error && <div className="warnbox">{tree.error}</div>}
      {(tree.tree || []).filter(match).map((it) => <Item key={it.id} it={it} depth={0} />)}
      {(tree.tree || []).length === 0 && <div className="empty">「AI会社」ページの中身を読めませんでした。</div>}
    </div>
  );
}

/* ---------------- 部署の作業 ---------------- */
function Jobs({ jobs, claudeCli, onChanged, notify }) {
  const [titles, setTitles] = useState({});
  useEffect(() => {
    getOrg().then((d) => setTitles(Object.fromEntries(Object.values(d.departments).flat().map((m) => [m.name, m.title])))).catch(() => {});
  }, []);
  const [form, setForm] = useState({ department: "戦略", title: "", instruction: "" });
  const [open, setOpen] = useState(null);
  const submit = async (e) => {
    e.preventDefault();
    if (!form.title.trim() || !form.instruction.trim()) return;
    try {
      await createJob(form);
      notify(`${DEPT_FULL[form.department] || form.department}に依頼しました`);
      setForm({ ...form, title: "", instruction: "" });
      onChanged();
    } catch (err) { notify(err.message, "error"); }
  };
  return (
    <div className="jobs">
      {!claudeCli && <div className="warnbox">この Mac に Claude Code(claude コマンド)が見つかりません。部署への依頼は、インストールしてログインすると動きます。</div>}
      <form className="card job-form" onSubmit={submit}>
        <div className="row">
          <select value={form.department} onChange={(e) => setForm({ ...form, department: e.target.value })}>
            {DEPARTMENTS.map((d) => <option key={d} value={d}>{DEPT_FULL[d]}</option>)}
          </select>
          <input value={form.title} onChange={(e) => setForm({ ...form, title: e.target.value })} placeholder="件名(例: 来週の投稿企画)" />
        </div>
        <textarea value={form.instruction} onChange={(e) => setForm({ ...form, instruction: e.target.value })}
                  placeholder="指示(何を・どこに保存するか)。秘書に話しかけて依頼することもできます" />
        <button className="btn primary" disabled={!form.title.trim() || !form.instruction.trim()}>依頼する</button>
      </form>
      {jobs.map((j) => (
        <div key={j.id} className={`card job ${j.status}`}>
          <div className="job-head" onClick={() => setOpen(open === j.id ? null : j.id)}>
            <span className={`job-dot ${j.status}`} />
            <strong>{j.department_full || j.department + "部"}</strong><span className="ttl">{j.title}</span>
            <span className="muted small">{j.started.slice(11, 16)}{j.finished ? `〜${j.finished.slice(11, 16)}` : " 作業中…"}</span>
          </div>
          <Activity job={j} titles={titles} />
          {(open === j.id || j.status !== "running") && j.output && (
            <pre className={`job-out ${open === j.id ? "full" : ""}`}>{j.output}</pre>
          )}
        </div>
      ))}
      {jobs.length === 0 && <div className="empty">まだ依頼はありません(サーバーを再起動すると履歴は消えます。成果物はリポジトリに残ります)。</div>}
    </div>
  );
}

/* ---------------- 会話履歴 ---------------- */
function Chat({ log, logRef }) {
  return (
    <div className="chat" ref={logRef}>
      {log.map((m, i) => <div key={i} className={`bubble ${m.role}`}>{stripTone(m.text)}</div>)}
    </div>
  );
}

export const TABS = [
  ["home", "今日"], ["content", "アカウント"], ["calendar", "予定"], ["tasks", "タスク"], ["docs", "資料"], ["library", "資料室"], ["jobs", "部署の作業"],
  ["org", "組織図"], ["chat", "会話"],
];

export default function Workspace(props) {
  const { tab, setTab, summary, jobs, health, log, logRef, taskFilter, setTaskFilter, docId, setDocId,
          focusTask, setFocusTask, onApprove, onSay, refresh, notify, week, setWeek, onRule } = props;
  const contentWaiting = summary ? (summary.content_weeks || []).reduce((n, w) => n + (w.counts["承認待ち"] || 0), 0) : 0;
  const approvals = summary ? summary.tasks.filter((t) => t.status === "承認待ち").length : 0;
  const running = jobs.filter((j) => j.status === "running").length;
  const goTab = (t, filter) => { if (filter) setTaskFilter(filter); setTab(t); };
  const openTask = (t) => { setTaskFilter(["完了", "承認済み"].includes(t.status) ? "すべて" : "未完了"); setFocusTask(t.key); setTab("tasks"); };

  return (
    <section className="workspace">
      <nav className="tabs" role="tablist">
        {TABS.map(([k, label]) => (
          <button key={k} role="tab" aria-selected={tab === k} className={tab === k ? "on" : ""} onClick={() => setTab(k)}>
            {label}
            {k === "tasks" && approvals > 0 && <span className="count warn">{approvals}</span>}
            {k === "content" && contentWaiting > 0 && <span className="count warn">{contentWaiting}</span>}
            {k === "jobs" && running > 0 && <span className="count">{running}</span>}
            {k === "library" && summary?.pref_pending?.length > 0 && <span className="count warn">{summary.pref_pending.length}</span>}
          </button>
        ))}
      </nav>
      <div className="tab-body">
        {!summary && <div className="empty">会社データを読み込み中…</div>}
        {summary && !summary.company_found && tab !== "docs" && (
          <div className="warnbox">会社リポジトリ(ai-company)が見つかりません。backend/.env の AI_COMPANY_DIR を確認してください。</div>
        )}
        {summary && tab === "home" && (
          <Today summary={summary} jobs={jobs} onApprove={onApprove} onSay={onSay} onTab={goTab} onOpenTask={openTask}
                 onChanged={refresh} notify={notify} onOpenWeek={(w) => { setWeek(w); setTab("content"); }} onRule={onRule}>
            <details className="t-more">
              <summary>数字の記録・タスク・話しかけ方(これまでのホーム)</summary>
              <Home summary={summary} jobs={jobs} onApprove={onApprove} onSay={onSay} onTab={goTab} onOpenTask={openTask}
                    onChanged={refresh} notify={notify} onOpenWeek={(w) => { setWeek(w); setTab("content"); }} onRule={onRule} />
            </details>
          </Today>
        )}
        {summary && tab === "calendar" && <Calendar summary={summary} refresh={refresh} notify={notify} onOpenTask={openTask}
                                                    onOpenWeek={(w) => { setWeek(w); setTab("content"); }} />}
        {tab === "org" && <OrgChart onSay={onSay} notify={notify} onOpenLibrary={() => setTab("library")} />}
        {tab === "content" && <Accounts week={week} setWeek={setWeek} onChanged={refresh} notify={notify} onSay={onSay} />}
        {summary && tab === "tasks" && <Tasks summary={summary} filter={taskFilter} setFilter={setTaskFilter} onApprove={onApprove}
                                              onChanged={refresh} onOpenDoc={(id) => { setDocId(id); setTab("docs"); }}
                                              focusKey={focusTask} notify={notify} />}
        {tab === "docs" && <Docs docId={docId} setDocId={setDocId} notify={notify} />}
        {tab === "library" && <Library notify={notify} />}
        {tab === "jobs" && <Jobs jobs={jobs} claudeCli={health?.claude_cli} onChanged={refresh} notify={notify} />}
        {tab === "chat" && <Chat log={log} logRef={logRef} />}
      </div>
    </section>
  );
}
