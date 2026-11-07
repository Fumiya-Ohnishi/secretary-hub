import Office from "./Office.jsx";
import React, { useEffect, useMemo, useRef, useState } from "react";
import { getToPost, decidePost, getAllPosts, schedulePost, patchTask, getOrg, search, getDiagnostics, createJob } from "./api.js";

const fileUrl = (p) => `/api/content/file?path=${encodeURIComponent(p)}`;
const FORMAT_JA = { reel: "リール", carousel: "カルーセル", story: "ストーリー", post: "投稿", thread: "スレッド", article: "記事" };
const PLATFORM_URL = { instagram: "https://www.instagram.com/", x: "https://x.com/compose/post", threads: "https://www.threads.net/", note: "https://note.com/notes/new" };
const iso = (d) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;

/* ============ 投稿アシスタント ============ */
export function PostingAssistant({ onClose, notify, onDone, say }) {
  const [posts, setPosts] = useState(null);
  const [i, setI] = useState(0);
  const [checked, setChecked] = useState({});
  const [busy, setBusy] = useState(false);
  const today = iso(new Date());
  useEffect(() => { getToPost().then((r) => setPosts(r.posts)).catch((e) => notify(e.message, "error")); }, []);

  if (!posts) return <Modal onClose={onClose}><div className="empty">読み込み中…</div></Modal>;
  if (!posts.length) return <Modal onClose={onClose}><h3>投稿待ちはありません</h3><p className="muted">承認済みの投稿がここに並びます。</p></Modal>;
  if (i >= posts.length) {
    return (
      <Modal onClose={onClose}>
        <div className="pa-done">🎉</div>
        <h3 className="center">今日の投稿はすべて完了です</h3>
        <p className="muted center">お疲れさまでした。数字が出たら「インスタのフォロワー◯人」と教えてください。</p>
        <div className="ac-actions"><button className="btn primary" onClick={onClose}>閉じる</button></div>
      </Modal>
    );
  }
  const p = posts[i];
  const memo = p.sections.find((s) => s.title.includes("投稿メモ"))?.text || "";
  const steps = [
    ["caption", "キャプションをコピーした"],
    ...(p.assets.length ? [["assets", "画像・動画を保存した"]] : []),
    ...(p.pr ? [["pr", "PR表記・タイアップ投稿ラベルを付けた"]] : []),
    ["memo", "投稿メモを確認した"],
  ];
  const allChecked = steps.every(([k]) => checked[`${p.path}:${k}`]);
  const mark = (k) => setChecked((c) => ({ ...c, [`${p.path}:${k}`]: true }));
  const copy = async () => {
    try { await navigator.clipboard.writeText(p.caption); mark("caption"); notify("キャプションをコピーしました", "ok"); }
    catch (e) { notify("コピーできませんでした。本文を選んでコピーしてください", "error"); }
  };
  const posted = async () => {
    setBusy(true);
    try {
      await decidePost(p.path, "posted");
      onDone();
      say(i + 1 < posts.length ? `記録しました。次は${posts[i + 1].platform_ja}の「${posts[i + 1].title}」です。` : "記録しました。今日の投稿はこれで全部です。お疲れさまでした。", "pleased");
      setI(i + 1);
    } catch (e) { notify(e.message, "error"); }
    setBusy(false);
  };
  return (
    <Modal onClose={onClose} wide>
      <div className="pa-head">
        <span className="ac-label">投稿アシスタント ・ {i + 1} / {posts.length}</span>
        <div className="pa-progress"><span style={{ width: `${(i / posts.length) * 100}%` }} /></div>
      </div>
      <div className="pa-title">
        <span className={`plat plat-${p.platform}`}>{p.platform_ja}</span>
        <span className="muted small">{FORMAT_JA[p.format] || p.format}</span>
        <strong>{p.title}</strong>
        <span className={`muted small ${p.scheduled.startsWith(today) ? "today" : ""}`}>{p.scheduled || "予定日なし"}{p.scheduled.startsWith(today) ? "(今日)" : ""}</span>
      </div>
      <div className="pa-grid">
        <div>
          <div className="sec-title">① キャプション<button className="btn primary sm" onClick={copy}>コピー</button></div>
          <div className="sec-text pa-caption">{p.caption || "(キャプションなし)"}</div>
          {p.assets.length > 0 && (
            <>
              <div className="sec-title">② 画像・動画(押すと保存)</div>
              <div className="assets">
                {p.assets.map((a) => (
                  <a key={a} href={fileUrl(a)} download={a.split("/").pop()} onClick={() => mark("assets")}>
                    {/\.(mp4|mov|webm)$/i.test(a) ? <video src={fileUrl(a)} muted /> : <img src={fileUrl(a)} alt="" />}
                  </a>
                ))}
              </div>
            </>
          )}
          {memo && (<><div className="sec-title">投稿メモ</div><div className="sec-text">{memo}</div></>)}
        </div>
        <div className="pa-side">
          <div className="sec-title">チェックリスト</div>
          {steps.map(([k, label]) => (
            <label key={k} className="pa-check">
              <input type="checkbox" checked={!!checked[`${p.path}:${k}`]} onChange={(e) => setChecked((c) => ({ ...c, [`${p.path}:${k}`]: e.target.checked }))} />
              {label}
            </label>
          ))}
          {p.pr && <div className="warnbox">この投稿は PR(アフィリエイト・タイアップ)を含みます。PR表記を必ず付けてください。</div>}
          <a className="btn sm" href={PLATFORM_URL[p.platform]} target="_blank" rel="noreferrer">{p.platform_ja} を開く</a>
          <div className="ac-actions">
            <button className="btn ghost" onClick={() => setI(i + 1)}>あとで</button>
            <button className="btn primary" disabled={busy || !allChecked} onClick={posted}>投稿しました</button>
          </div>
        </div>
      </div>
    </Modal>
  );
}

function Modal({ children, onClose, wide }) {
  useEffect(() => {
    const k = (e) => { if (e.key === "Escape") onClose(); };
    window.addEventListener("keydown", k);
    return () => window.removeEventListener("keydown", k);
  }, [onClose]);
  return (
    <div className="modal-back" onClick={onClose}>
      <div className={`modal ${wide ? "wide" : ""}`} role="dialog" onClick={(e) => e.stopPropagation()}>{children}</div>
    </div>
  );
}

/* ============ 週カレンダー ============ */
const DOW = ["月", "火", "水", "木", "金", "土", "日"];

export function Calendar({ summary, refresh, notify, onOpenTask, onOpenWeek }) {
  const [offset, setOffset] = useState(0);
  const [posts, setPosts] = useState([]);
  const [drag, setDrag] = useState(null);
  const load = () => getAllPosts().then((r) => setPosts(r.posts)).catch(() => {});
  useEffect(() => { load(); }, [summary]);

  const monday = useMemo(() => {
    const d = new Date(); d.setHours(0, 0, 0, 0);
    d.setDate(d.getDate() - ((d.getDay() + 6) % 7) + offset * 7);
    return d;
  }, [offset]);
  const days = [...Array(7)].map((_, k) => { const d = new Date(monday); d.setDate(d.getDate() + k); return iso(d); });
  const today = iso(new Date());
  const items = (day) => [
    ...posts.filter((p) => (p.scheduled || "").startsWith(day)).map((p) => ({ kind: "post", id: p.path, label: `${p.platform_ja}:${p.title}`, sub: `${(p.scheduled || "").slice(11)} ${p.status}`, raw: p })),
    ...(summary?.tasks || []).filter((t) => (t.due || "").startsWith(day) && !["完了", "承認済み"].includes(t.status))
      .map((t) => ({ kind: "task", id: t.key, label: `${t.id} ${t.title}`, sub: `${t.assignee}・${t.status}`, raw: t })),
    ...(summary?.jobs || []).filter((j) => (j.started || "").startsWith(day))
      .map((j) => ({ kind: "job", id: j.id, label: `${j.department_full || j.department + "部"}:${j.title}`, sub: j.status === "running" ? "作業中" : j.status === "done" ? "完了" : "エラー" })),
  ];
  const drop = async (day) => {
    if (!drag) return;
    try {
      if (drag.kind === "task") { await patchTask(drag.raw.key, { due: day }); notify(`${drag.raw.id} の期限を ${day.slice(5).replace("-", "/")} にしました`, "ok"); }
      if (drag.kind === "post") { await schedulePost(drag.raw.path, day); notify(`「${drag.raw.title}」の予定を ${day.slice(5).replace("-", "/")} にしました`, "ok"); }
      await load(); refresh();
    } catch (e) { notify(e.message, "error"); }
    setDrag(null);
  };
  const sch = summary?.scheduler;
  return (
    <div className="calendar">
      <div className="cal-head">
        <button className="btn sm ghost" onClick={() => setOffset(offset - 1)}>← 前の週</button>
        <strong>{days[0].slice(5).replace("-", "/")} 〜 {days[6].slice(5).replace("-", "/")}</strong>
        <button className="btn sm ghost" onClick={() => setOffset(offset + 1)}>次の週 →</button>
        {offset !== 0 && <button className="btn sm" onClick={() => setOffset(0)}>今週</button>}
        <span className="muted small cal-note">定時チェック {sch?.auto ? sch.times.join("・") : "オフ"} ・ 投稿とタスクはつまんで別の日へ移せます</span>
      </div>
      <div className="cal-grid">
        {days.map((day, k) => (
          <div key={day} className={`cal-day ${day === today ? "today" : ""} ${drag ? "droppable" : ""}`}
               onDragOver={(e) => e.preventDefault()} onDrop={() => drop(day)}>
            <div className="cal-date"><span>{DOW[k]}</span>{Number(day.slice(8))}</div>
            {items(day).map((it) => (
              <div key={it.kind + it.id} className={`cal-item ${it.kind}`} draggable={it.kind !== "job"}
                   onDragStart={() => setDrag(it)} onDragEnd={() => setDrag(null)}
                   onClick={() => it.kind === "task" ? onOpenTask(it.raw) : it.kind === "post" ? onOpenWeek(it.raw.week) : null}
                   title={it.label}>
                <div className="cal-label">{it.label}</div>
                <div className="cal-sub">{it.sub}</div>
              </div>
            ))}
          </div>
        ))}
      </div>
      <div className="legend cal-legend"><span><i className="lg post" />投稿</span><span><i className="lg task" />タスクの期限</span><span><i className="lg job" />部署の作業</span></div>
    </div>
  );
}

/* ============ 組織図 ============ */
const SHORT_OF = { 経営戦略部: "戦略", 収益化部: "収益化", 企画編集部: "企画", ライティング部: "ライティング", デザイン部: "デザイン",
  画像制作部: "画像", 映像制作部: "映像", SNS運用部: "SNS運用", 品質管理部: "品質管理", データ分析部: "分析" };
const hm = (t) => (t || "").slice(11, 16);

function MemberStatus({ st }) {
  if (!st) return <span className="ms idle">待機中</span>;
  if (st.state === "working") return <span className="ms working"><i />作業中:{st.desc}</span>;
  return <span className="ms idle">待機中 ・ 最近 {hm(st.at)}「{st.desc}」{st.result === "error" ? "(エラー)" : ""}</span>;
}

function DeptDetail({ dept, members, data, onBack, notify, onSay }) {
  const short = SHORT_OF[dept];
  const [form, setForm] = useState({ title: "", instruction: "" });
  const [sending, setSending] = useState(false);
  const jobs = data.jobs.filter((j) => (j.department_full || "") === dept || SHORT_OF[dept] === j.department);
  const working = members.filter((m) => data.members[m.name]?.state === "working");
  const send = async (e) => {
    e.preventDefault();
    if (!form.title.trim() || !form.instruction.trim()) return;
    setSending(true);
    try {
      await createJob({ department: short, title: form.title, instruction: form.instruction });
      notify(`${dept}に依頼しました`, "ok");
      setForm({ title: "", instruction: "" });
    } catch (err) { notify(err.message, "error"); }
    setSending(false);
  };
  return (
    <div className="dept-detail">
      <div className="dd-head">
        <button className="btn sm" onClick={onBack}>← 組織図に戻る</button>
        <h2>{dept}</h2>
        <span className="muted small">{members.length}名{working.length ? ` ・ ${working.length}名が作業中` : " ・ 全員待機中"}</span>
      </div>
      <section className="card">
        <div className="card-head"><h3>社員と今の状況</h3></div>
        {members.map((m) => (
          <div key={m.name} className={`dd-member ${m.boss ? "boss" : ""}`}>
            <span className="avatar">{m.boss ? "★" : m.title.slice(0, 1)}</span>
            <div className="om-text">
              <div><strong>{m.title}</strong>{m.boss && <span className="muted small">(上司)</span>} <span className="muted small">{m.name}{m.model ? ` ・ ${m.model}` : ""}</span></div>
              <div className="muted small">{m.description.replace(`${dept}の${m.title}。`, "")}</div>
              <MemberStatus st={data.members[m.name]} />
            </div>
          </div>
        ))}
      </section>
      {short && (
        <form className="card job-form" onSubmit={send}>
          <div className="card-head"><h3>{dept}に依頼する</h3><span className="muted small">担当が作る → 上司がチェック{["企画", "ライティング", "デザイン", "画像", "映像", "SNS運用", "収益化"].includes(short) ? " → 品質管理部が合否" : ""}</span></div>
          <input value={form.title} onChange={(e) => setForm({ ...form, title: e.target.value })} placeholder="件名(例: 来週のリール台本)" />
          <textarea value={form.instruction} onChange={(e) => setForm({ ...form, instruction: e.target.value })} placeholder="指示(何を・どこに保存するか)。秘書に話しかけて頼むこともできます" />
          <button className="btn primary" disabled={sending || !form.title.trim() || !form.instruction.trim()}>依頼する</button>
        </form>
      )}
      <section className="card">
        <div className="card-head"><h3>最近の作業</h3><button className="link" onClick={() => onSay(`${dept}の最近の成果を教えて`)}>秘書に要約してもらう</button></div>
        {jobs.length === 0 && <div className="empty">まだ作業はありません。</div>}
        {jobs.slice(0, 8).map((j) => (
          <div key={j.id} className="dd-job">
            <div className="job-head"><span className={`job-dot ${j.status}`} /><span className="ttl">{j.title}</span>
              <span className="muted small">{j.started.slice(5, 16).replace("T", " ")}{j.finished ? `〜${hm(j.finished)}` : " 作業中…"}</span></div>
            <Activity job={j} members={members} />
            {j.output && j.status !== "running" && <pre className="job-out">{j.output}</pre>}
          </div>
        ))}
      </section>
    </div>
  );
}

/** 作業の中で、誰がいつ何をしたか */
export function Activity({ job, members = [], titles = {} }) {
  const acts = job.activity || [];
  if (!acts.length) return null;
  const title = (name) => titles[name] || members.find((m) => m.name === name)?.title || name;
  return (
    <ol className="activity">
      {acts.map((a) => (
        <li key={a.id} className={a.status}>
          <span className="act-mark">{a.status === "running" ? "●" : a.status === "done" ? "✓" : "!"}</span>
          <strong>{title(a.agent)}</strong> {a.desc}
          <span className="muted small"> {hm(a.started)}{a.finished ? `〜${hm(a.finished)}` : ""}</span>
        </li>
      ))}
    </ol>
  );
}

export function OrgChart({ onSay, notify }) {
  const [data, setData] = useState(null);
  const [dept, setDept] = useState(null);
  const [view, setViewState] = useState(() => { try { return localStorage.getItem("orgview") || "office"; } catch (e) { return "office"; } });
  useEffect(() => {
    const load = () => getOrg().then(setData).catch(() => {});
    load();
    const id = setInterval(load, 5000);
    return () => clearInterval(id);
  }, []);
  if (!data) return <div className="empty">読み込み中…</div>;
  const depts = Object.entries(data.departments);
  const total = depts.reduce((n, [, m]) => n + m.length, 0);
  if (!total) return <div className="card setup"><h3>まだ社員がいません</h3><p className="muted">ai-company/.claude/agents/ に人材定義を置くと、ここに並びます。</p></div>;
  if (dept && data.departments[dept]) {
    return <DeptDetail dept={dept} members={data.departments[dept]} data={data} onBack={() => setDept(null)} notify={notify} onSay={onSay} />;
  }
  const workingAll = Object.entries(data.members).filter(([, st]) => st.state === "working");
  const titleOf = Object.fromEntries(depts.flatMap(([, ms]) => ms.map((m) => [m.name, m.title])));
  const deptOf = Object.fromEntries(depts.flatMap(([d, ms]) => ms.map((m) => [m.name, d])));
  const setView = (v) => { setViewState(v); try { localStorage.setItem("orgview", v); } catch (e) {} };
  return (
    <div className="org">
      <div className="org-top card">
        <div><div className="muted small">社長</div><strong>拒否権・最終承認・投稿</strong></div>
        <div className="org-line" />
        <div><div className="muted small">秘書室</div><strong>統括秘書セナ</strong></div>
        <span className="muted small org-count">社員 {total}名 ・ {depts.length}部署 ・ 作業中 {workingAll.length}名</span>
        <div className="seg org-view">
          <button className={view === "office" ? "on" : ""} onClick={() => setView("office")}>オフィス</button>
          <button className={view === "list" ? "on" : ""} onClick={() => setView("list")}>一覧</button>
        </div>
      </div>
      {view === "office" && (
        <>
          <Office data={data} onOpenDept={setDept} />
          <section className="card now-working">
            <div className="card-head"><h3>いま作業中の社員</h3><span className="muted small">机に座っている社員が作業中。終わると書類が上司の机へ飛びます</span></div>
            {workingAll.length === 0 && <div className="empty">いまは全員待機中です。部署に仕事を頼むと、担当が机に向かって作業を始めます。</div>}
            {workingAll.map(([name, st]) => (
              <div key={name} className="mini-row clickable" onClick={() => setDept(deptOf[name])}><span className="job-dot running" /><strong>{titleOf[name] || name}</strong><span className="muted small">{deptOf[name]}</span><span className="ttl">{st.desc}({st.job})</span><span className="due">{hm(st.at)}〜</span></div>
            ))}
          </section>
        </>
      )}
      {view === "list" && <>
      {workingAll.length > 0 && (
        <section className="card now-working">
          <div className="card-head"><h3>いま作業中の社員</h3></div>
          {workingAll.map(([name, st]) => (
            <div key={name} className="mini-row"><span className="job-dot running" /><strong>{titleOf[name] || name}</strong><span className="ttl">{st.desc}({st.job})</span><span className="due">{hm(st.at)}〜</span></div>
          ))}
        </section>
      )}
      <p className="muted small">部署を押すと、社員ごとの状況・最近の作業・依頼の画面が開きます。</p>
      <div className="org-grid">
        {depts.map(([name, members]) => {
          const working = members.filter((m) => data.members[m.name]?.state === "working");
          const busy = working.length > 0 || data.running_departments.includes(name);
          return (
            <section key={name} className={`card org-dept clickable ${busy ? "busy" : ""}`} onClick={() => setDept(name)} role="button" tabIndex={0}
                     onKeyDown={(e) => e.key === "Enter" && setDept(name)}>
              <div className="card-head"><h3>{name}</h3>{busy ? <span className="badge s-doing">作業中</span> : <span className="muted small">{members.length}名</span>}</div>
              {members.map((m) => {
                const st = data.members[m.name];
                return (
                  <div key={m.name} className={`org-member ${m.boss ? "boss" : ""}`}>
                    <span className={`avatar ${st?.state === "working" ? "on" : ""}`}>{m.boss ? "★" : m.title.slice(0, 1)}</span>
                    <div className="om-text">
                      <div>{m.title}{m.boss && <span className="muted small">(上司)</span>}</div>
                      {m.persona && <div className="muted small">{m.persona}</div>}
                      {st?.state === "working" && <div className="ms working small"><i />{st.desc}</div>}
                    </div>
                  </div>
                );
              })}
              <div className="link">詳しく見る・依頼する →</div>
            </section>
          );
        })}
      </div>
      </>}
    </div>
  );
}

/* ============ まとめて検索(⌘K) ============ */
const KIND_JA = { task: "タスク", post: "投稿", doc: "資料", job: "作業", chat: "会話" };

export function SearchPalette({ onClose, log, onPick }) {
  const [q, setQ] = useState("");
  const [res, setRes] = useState([]);
  const [sel, setSel] = useState(0);
  useEffect(() => {
    if (!q.trim()) { setRes([]); return; }
    const id = setTimeout(async () => {
      let hits = [];
      try { hits = (await search(q)).results; } catch (e) {}
      const chats = log.filter((m) => m.role !== "sys" && m.text.toLowerCase().includes(q.toLowerCase())).slice(-5).reverse()
        .map((m) => ({ kind: "chat", title: m.text.slice(0, 60), sub: m.role === "user" ? "社長" : "秘書" }));
      setRes([...hits, ...chats]); setSel(0);
    }, 200);
    return () => clearTimeout(id);
  }, [q]);
  const key = (e) => {
    if (e.key === "ArrowDown") { e.preventDefault(); setSel((s) => Math.min(s + 1, res.length - 1)); }
    if (e.key === "ArrowUp") { e.preventDefault(); setSel((s) => Math.max(s - 1, 0)); }
    if (e.key === "Enter" && res[sel]) onPick(res[sel]);
    if (e.key === "Escape") onClose();
  };
  return (
    <div className="modal-back top" onClick={onClose}>
      <div className="modal palette" onClick={(e) => e.stopPropagation()}>
        <input autoFocus value={q} onChange={(e) => setQ(e.target.value)} onKeyDown={key} placeholder="タスク・投稿・資料・作業・会話を検索" />
        <div className="pal-list">
          {res.map((r, k) => (
            <div key={k} className={`pal-item ${k === sel ? "on" : ""}`} onMouseEnter={() => setSel(k)} onClick={() => onPick(r)}>
              <span className="tid">{KIND_JA[r.kind]}</span><span className="ttl">{r.title}</span><span className="muted small">{r.sub}</span>
            </div>
          ))}
          {q && !res.length && <div className="empty">見つかりません</div>}
          {!q && <div className="empty small">⌘K(Ctrl+K)でいつでも開けます。↑↓で選んで Enter</div>}
        </div>
      </div>
    </div>
  );
}

/* ============ 接続の診断 ============ */
export function Diagnostics({ onClose }) {
  const [data, setData] = useState(null);
  const load = () => { setData(null); getDiagnostics().then(setData).catch((e) => setData({ checks: [{ key: "hub", label: "秘書ハブ", ok: false, detail: e.message, fix: "run_mac.command で起動し直す" }] })); };
  useEffect(load, []);
  return (
    <Modal onClose={onClose}>
      <div className="ac-label">接続の診断</div>
      {!data && <div className="empty">確認しています…(10秒ほど)</div>}
      {data && data.checks.map((c) => (
        <div key={c.key} className={`diag ${c.ok ? "ok" : "ng"}`}>
          <span className="diag-mark">{c.ok ? "✅" : "⚠"}</span>
          <div>
            <strong>{c.label}</strong> <span className="muted small">{c.detail}</span>
            {!c.ok && c.fix && <div className="diag-fix">直し方:{c.fix}</div>}
          </div>
        </div>
      ))}
      <div className="ac-actions"><button className="btn ghost" onClick={load}>もう一度確認</button><button className="btn primary" onClick={onClose}>閉じる</button></div>
    </Modal>
  );
}

/* ============ キーボード操作 ============ */
export function useHotkeys({ onTalkStart, onTalkEnd, onSearch, enabled = true }) {
  const holding = useRef(false);
  useEffect(() => {
    const typing = (e) => /^(INPUT|TEXTAREA|SELECT)$/.test(e.target.tagName) || e.target.isContentEditable;
    const down = (e) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") { e.preventDefault(); onSearch(); return; }
      if (!enabled || typing(e)) return;
      if (e.code === "Space" && !e.repeat && !holding.current) { e.preventDefault(); holding.current = true; onTalkStart(); }
    };
    const up = (e) => {
      if (e.code === "Space" && holding.current) { e.preventDefault(); holding.current = false; onTalkEnd(); }
    };
    window.addEventListener("keydown", down);
    window.addEventListener("keyup", up);
    return () => { window.removeEventListener("keydown", down); window.removeEventListener("keyup", up); };
  }, [onTalkStart, onTalkEnd, onSearch, enabled]);
}
