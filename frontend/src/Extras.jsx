import React, { useEffect, useMemo, useRef, useState } from "react";
import { getToPost, decidePost, getAllPosts, schedulePost, patchTask, getOrg, search, getDiagnostics } from "./api.js";

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
      .map((j) => ({ kind: "job", id: j.id, label: `${j.department}部:${j.title}`, sub: j.status === "running" ? "作業中" : j.status === "done" ? "完了" : "エラー" })),
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
export function OrgChart({ onSay }) {
  const [data, setData] = useState(null);
  const [open, setOpen] = useState(null);
  useEffect(() => {
    const load = () => getOrg().then(setData).catch(() => {});
    load();
    const id = setInterval(load, 15000);
    return () => clearInterval(id);
  }, []);
  if (!data) return <div className="empty">読み込み中…</div>;
  const depts = Object.entries(data.departments);
  const total = depts.reduce((n, [, m]) => n + m.length, 0);
  if (!total) return <div className="card setup"><h3>まだ社員がいません</h3><p className="muted">ai-company/.claude/agents/ に人材定義を置くと、ここに並びます。</p></div>;
  const jobsOf = (dept) => data.jobs.filter((j) => dept.includes(j.department));
  return (
    <div className="org">
      <div className="org-top card">
        <div><div className="muted small">社長</div><strong>拒否権・最終承認・投稿</strong></div>
        <div className="org-line" />
        <div><div className="muted small">秘書室</div><strong>統括秘書セナ</strong></div>
        <span className="muted small org-count">社員 {total}名 ・ {depts.length}部署</span>
      </div>
      <div className="org-grid">
        {depts.map(([dept, members]) => {
          const busy = data.running_departments.some((d) => dept.includes(d));
          const jobs = jobsOf(dept);
          return (
            <section key={dept} className={`card org-dept ${busy ? "busy" : ""}`}>
              <div className="card-head"><h3>{dept}</h3>{busy ? <span className="badge s-doing">作業中</span> : <span className="muted small">{members.length}名</span>}</div>
              {members.map((m) => (
                <div key={m.name} className={`org-member ${m.boss ? "boss" : ""}`} onClick={() => setOpen(open === m.name ? null : m.name)}>
                  <span className="avatar">{m.boss ? "★" : m.title.slice(0, 1)}</span>
                  <div className="om-text">
                    <div>{m.title}{m.boss && <span className="muted small">(上司)</span>}</div>
                    {open === m.name && <div className="muted small">{m.description}<br />定義: {m.file}{m.model ? ` ・ AI: ${m.model}` : ""}</div>}
                  </div>
                </div>
              ))}
              {jobs.length > 0 && <div className="muted small org-last">最近: {jobs[0].title}({jobs[0].status === "done" ? "完了" : jobs[0].status === "running" ? "作業中" : "エラー"})</div>}
              <button className="link" onClick={() => onSay(`${dept.replace(/部$/, "")}部の最近の成果を教えて`)}>成果を聞く</button>
            </section>
          );
        })}
      </div>
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
