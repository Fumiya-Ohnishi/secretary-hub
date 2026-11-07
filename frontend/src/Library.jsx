import React, { useEffect, useState } from "react";
import { getKnowledge, searchKnowledge, addPref, decidePref } from "./api.js";

/* 資料室: 会社の知見の棚。社長の好み(確定/確認待ち)の確認、知見の検索、最近の知見 */
const ICON = { failures: "⚠", wins: "★", reviews: "✓", research: "🔍", numbers: "📈", prefs: "♥" };
const strip = (t) => (t || "").replace(/^\d{4}-\d{2}-\d{2} \([^)]*\) /, "");

function PendingPref({ p, onDone, notify }) {
  const [edit, setEdit] = useState(false);
  const [text, setText] = useState(strip(p.text));
  const act = async (approve) => {
    try { await decidePref(p.id, approve, edit ? text : ""); notify(approve ? `${p.id} を確定しました` : `${p.id} を却下しました`, "ok"); onDone(); }
    catch (e) { notify(e.message, "error"); }
  };
  return (
    <div className="lib-pend">
      <div className="lib-pend-t"><span className="chip2 c-wait">確認待ち</span><b>{p.id}</b> {strip(p.text)}</div>
      {p.reason && <div className="lib-why">確認する理由:{p.reason}</div>}
      {edit && <textarea value={text} onChange={(e) => setText(e.target.value)} rows={2} aria-label="言い直す" />}
      <div className="lib-pend-b">
        <button className="btn sm primary" onClick={() => act(true)}>{edit ? "この言い方で確定" : "このまま確定"}</button>
        <button className="btn sm" onClick={() => setEdit(!edit)}>{edit ? "戻る" : "言い直す"}</button>
        <button className="btn sm ghost" onClick={() => act(false)}>却下(記録しない)</button>
      </div>
    </div>
  );
}

export default function Library({ notify }) {
  const [data, setData] = useState(null);
  const [q, setQ] = useState("");
  const [hits, setHits] = useState(null);
  const [shelf, setShelf] = useState(null);
  const [newPref, setNewPref] = useState("");
  const load = () => getKnowledge().then(setData).catch((e) => notify(e.message, "error"));
  useEffect(() => { load(); }, []);
  const run = async (e) => { e?.preventDefault(); if (!q.trim()) return setHits(null); try { setHits((await searchKnowledge(q)).hits); } catch (err) { notify(err.message, "error"); } };
  const add = async (e) => {
    e.preventDefault(); if (!newPref.trim()) return;
    try { const r = await addPref({ text: newPref, needs_check: false }); notify(r.duplicate ? "同じ好みがすでにあります" : `${r.id} を確定しました`, "ok"); setNewPref(""); load(); }
    catch (err) { notify(err.message, "error"); }
  };
  if (!data) return <div className="empty">読み込み中…</div>;
  const { prefs } = data;
  const shown = hits ? hits.filter((h) => !shelf || h.shelf === shelf) : null;
  return (
    <div className="library">
      <div className="lib-head">
        <div><h2>資料室</h2><div className="muted small">部署は作業の前にここを確認し、作業の後に分かったことを追記します(秘書ハブが関係する知見を指示書に自動で入れます)</div></div>
        <form className="lib-search" onSubmit={run} role="search">
          <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="知見を探す(例: 表紙 文字 重なる)" aria-label="知見を探す" />
          <button className="btn sm primary">探す</button>
        </form>
      </div>

      {prefs.pending.length > 0 && (
        <section className="card lib-pends">
          <div className="card-head"><h3>社長の確認待ち({prefs.pending.length}件)</h3><span className="muted small">アカウントの軸と食い違う・曖昧なので、確定する前に確認します</span></div>
          {prefs.pending.map((p) => <PendingPref key={p.id} p={p} onDone={load} notify={notify} />)}
        </section>
      )}

      <div className="lib-shelves">
        {data.shelves.map((s) => (
          <button key={s.key} className={`lib-shelf ${shelf === s.key ? "on" : ""}`} onClick={() => { setShelf(shelf === s.key ? null : s.key); if (!hits && s.key !== "prefs") { setQ(s.name); searchKnowledge(s.name).then((r) => setHits(r.hits)).catch(() => {}); } }}>
            <span className="lib-ic" aria-hidden="true">{ICON[s.key]}</span>
            <span className="lib-nm">{s.name}</span>
            <b>{s.count}</b><span className="muted small">件</span>
            <span className="lib-files muted small">{s.files.slice(0, 2).join("・")}{s.files.length > 2 ? ` ほか${s.files.length - 2}` : ""}</span>
          </button>
        ))}
      </div>

      {shown && (
        <section className="card">
          <div className="card-head"><h3>見つかった知見 {shown.length}件</h3><button className="link" onClick={() => { setHits(null); setQ(""); setShelf(null); }}>閉じる</button></div>
          {!shown.length && <div className="empty">見つかりませんでした。言葉を変えて探してください。</div>}
          {shown.map((h, i) => (
            <div key={i} className="lib-hit"><span className="chip2 c-run">{h.shelf_name}</span><div className="lib-hit-t">{h.text}</div><div className="muted small">{h.source}</div></div>
          ))}
        </section>
      )}

      <div className="two-col">
        <section className="card">
          <div className="card-head"><h3>社長の好み(確定 {prefs.confirmed.length}件)</h3><span className="muted small">部署はこれに必ず従います</span></div>
          {prefs.confirmed.map((p) => <div key={p.id} className="lib-pref"><b>{p.id}</b><span>{strip(p.text)}</span></div>)}
          <form className="lib-add" onSubmit={add}>
            <input value={newPref} onChange={(e) => setNewPref(e.target.value)} placeholder="覚えておいてほしいこと(例: 絵文字は使わない)" aria-label="好みを足す" />
            <button className="btn sm" disabled={!newPref.trim()}>覚えておく</button>
          </form>
        </section>
        <section className="card">
          <div className="card-head"><h3>最近の知見</h3><span className="muted small">knowledge/lessons.md</span></div>
          {data.recent_lessons.length ? data.recent_lessons.map((l, i) => <div key={i} className="lib-lesson">{l}</div>) : <div className="empty">まだありません。</div>}
        </section>
      </div>
    </div>
  );
}
