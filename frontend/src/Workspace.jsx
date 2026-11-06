import React, { useEffect, useState } from "react";
import { createTask, patchTask, getDocs, getDoc, createJob } from "./api.js";
import { Blocks } from "./DocView.jsx";

export const STATUSES = ["未着手", "進行中", "承認待ち", "承認済み", "完了", "差し戻し"];
const ASSIGNEES = ["秘書", "戦略", "企画", "制作", "メディア", "分析", "社長"];
const DEPARTMENTS = ["戦略", "企画", "制作", "メディア", "分析"];
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

function Home({ summary, jobs, onApprove, onSay, onTab, onOpenTask }) {
  const { revenue, tasks } = summary;
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
        <button className={`kpi ${approvals.length ? "attn" : ""}`} onClick={() => onTab("tasks", "承認待ち")}>
          <div className="kpi-num">{approvals.length}</div><div className="kpi-lbl">承認待ち</div>
        </button>
        <button className="kpi" onClick={() => onTab("tasks", "未完了")}>
          <div className="kpi-num">{doing.length}</div><div className="kpi-lbl">未完了タスク</div>
        </button>
        <button className={`kpi ${late.length ? "late" : ""}`} onClick={() => onTab("tasks", "未完了")}>
          <div className="kpi-num">{late.length}</div><div className="kpi-lbl">期限切れ</div>
        </button>
      </div>

      <section className="card">
        <div className="card-head"><h3>社長の判断待ち</h3><span className="muted">{approvals.length}件</span></div>
        {approvals.length === 0 && <div className="empty">いま判断が必要なものはありません。</div>}
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
              <StatusBadge status={t.status} /><span className="ttl">{t.title}</span>
              <span className={`due ${overdue(t) ? "over" : ""}`}>{fmtDate(t.due)}</span>
            </div>
          ))}
          {doing.length === 0 && <div className="empty">未完了のタスクはありません。</div>}
        </section>
        <section className="card">
          <div className="card-head"><h3>部署の作業</h3><button className="link" onClick={() => onTab("jobs")}>すべて</button></div>
          {jobs.slice(0, 4).map((j) => (
            <div key={j.id} className="mini-row" onClick={() => onTab("jobs")}>
              <span className={`job-dot ${j.status}`} /><span className="ttl">{j.department}部:{j.title}</span>
            </div>
          ))}
          {jobs.length === 0 && <div className="empty">まだ依頼はありません。「戦略部に〜を頼んで」と話しかけてください。</div>}
          {running.length > 0 && <div className="muted small">{running.length}件 作業中…</div>}
        </section>
      </div>

      <section className="card say">
        <h3>こう話しかけてみてください</h3>
        <div className="chips">
          {["今日の報告をして", "承認待ちを見せて", "企画書を開いて要約して", "T-015 を進行中にして",
            "戦略部に来週の投稿企画を頼んで", "VOICEVOXの規約確認をタスクに追加して"].map((s) => (
            <button key={s} className="chip" onClick={() => onSay(s)}>「{s}」</button>
          ))}
        </div>
      </section>
    </div>
  );
}

/* ---------------- タスク ---------------- */
const FILTERS = ["未完了", "承認待ち", "完了", "すべて"];

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

  const change = async (t, status) => {
    if (status === "承認済み" || status === "差し戻し") return onApprove(t);
    try { await patchTask(t.key, { status }); notify(`${t.id} を「${status}」にしました`); onChanged(); }
    catch (err) { notify(err.message, "error"); }
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
              <span className={`due ${overdue(t) ? "over" : ""}`}>{fmtDate(t.due)}</span>
              <select className={`status-sel ${STATUS_CLASS[t.status]}`} value={t.status}
                      onClick={(e) => e.stopPropagation()} onChange={(e) => change(t, e.target.value)}>
                {STATUSES.map((s) => <option key={s}>{s}</option>)}
              </select>
            </div>
            {open === t.key && (
              <div className="task-detail">
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
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    getDocs().then(setDocs).catch((e) => { setDocs({ configured: true, docs: [], error: e.message }); });
  }, []);
  useEffect(() => {
    if (!docId) { setDoc(null); return; }
    setLoading(true);
    getDoc(docId).then(setDoc).catch((e) => { notify(e.message, "error"); setDocId(null); }).finally(() => setLoading(false));
  }, [docId]);

  if (!docs) return <div className="empty">読み込み中…</div>;
  if (!docs.configured) return <NotionSetup />;
  const shown = docs.docs.filter((d) => d.title.toLowerCase().includes(q.toLowerCase()));

  return (
    <div className={`docs ${docId ? "reading" : ""}`}>
      <aside className="doc-list">
        <input className="search" value={q} onChange={(e) => setQ(e.target.value)} placeholder="資料を検索" />
        {docs.error && <div className="warnbox">{docs.error}</div>}
        {shown.map((d) => (
          <button key={d.id} className={`doc-item ${docId === d.id ? "on" : ""}`} onClick={() => setDocId(d.id)}>
            <span className="doc-icon">{d.icon || "📄"}</span>
            <span className="doc-title">{d.title}</span>
            <span className="muted small">{d.edited?.slice(5, 10).replace("-", "/")}</span>
          </button>
        ))}
        {shown.length === 0 && <div className="empty">資料がありません。</div>}
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
            <div className="doc-body"><Blocks blocks={doc.blocks} onOpenPage={setDocId} /></div>
          </>
        )}
      </article>
    </div>
  );
}

/* ---------------- 部署の作業 ---------------- */
function Jobs({ jobs, claudeCli, onChanged, notify }) {
  const [form, setForm] = useState({ department: "戦略", title: "", instruction: "" });
  const [open, setOpen] = useState(null);
  const submit = async (e) => {
    e.preventDefault();
    if (!form.title.trim() || !form.instruction.trim()) return;
    try {
      await createJob(form);
      notify(`${form.department}部に依頼しました`);
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
            {DEPARTMENTS.map((d) => <option key={d} value={d}>{d}部</option>)}
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
            <strong>{j.department}部</strong><span className="ttl">{j.title}</span>
            <span className="muted small">{j.started.slice(11, 16)}{j.finished ? `〜${j.finished.slice(11, 16)}` : " 作業中…"}</span>
          </div>
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
      {log.map((m, i) => <div key={i} className={`bubble ${m.role}`}>{m.text}</div>)}
    </div>
  );
}

export const TABS = [
  ["home", "ホーム"], ["tasks", "タスク"], ["docs", "資料"], ["jobs", "部署の作業"], ["chat", "会話"],
];

export default function Workspace(props) {
  const { tab, setTab, summary, jobs, health, log, logRef, taskFilter, setTaskFilter, docId, setDocId,
          focusTask, setFocusTask, onApprove, onSay, refresh, notify } = props;
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
            {k === "jobs" && running > 0 && <span className="count">{running}</span>}
          </button>
        ))}
      </nav>
      <div className="tab-body">
        {!summary && <div className="empty">会社データを読み込み中…</div>}
        {summary && !summary.company_found && tab !== "docs" && (
          <div className="warnbox">会社リポジトリ(ai-company)が見つかりません。backend/.env の AI_COMPANY_DIR を確認してください。</div>
        )}
        {summary && tab === "home" && <Home summary={summary} jobs={jobs} onApprove={onApprove} onSay={onSay} onTab={goTab} onOpenTask={openTask} />}
        {summary && tab === "tasks" && <Tasks summary={summary} filter={taskFilter} setFilter={setTaskFilter} onApprove={onApprove}
                                              onChanged={refresh} onOpenDoc={(id) => { setDocId(id); setTab("docs"); }}
                                              focusKey={focusTask} notify={notify} />}
        {tab === "docs" && <Docs docId={docId} setDocId={setDocId} notify={notify} />}
        {tab === "jobs" && <Jobs jobs={jobs} claudeCli={health?.claude_cli} onChanged={refresh} notify={notify} />}
        {tab === "chat" && <Chat log={log} logRef={logRef} />}
      </div>
    </section>
  );
}
