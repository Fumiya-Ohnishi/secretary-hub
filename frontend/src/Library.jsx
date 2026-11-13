import React, { useEffect, useState } from "react";
import { getKnowledge, searchKnowledge, addPref, decidePref, listVideoRefs, uploadVideoRef, getMuse, saveMuse } from "./api.js";
import Md from "./Md.jsx";

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

/* 参考動画の分析: 社長が送った動画を、秘書ハブがカット・音量・言葉・静止画に分けて、映像制作部が秒ごとに分析する(2026-11-13)
   11/13 社長「アップロードしたか分かりにくい・左に寄りすぎ」→ 置き場所を広く、送信中は進み具合、送ったら結果を枠の中に出す */
const fmtMB = (n) => `${(n / 1024 / 1024).toFixed(1)}MB`;
const STATUS_TONE = (st) => /失敗|止まり/.test(st) ? "ng" : /分析中|作成中/.test(st) ? "run" : "ok";

function VideoRefs({ notify }) {
  const [items, setItems] = useState([]);
  const [file, setFile] = useState(null);
  const [name, setName] = useState("");
  const [note, setNote] = useState("");
  const [pct, setPct] = useState(null);       // 送信中の進み具合(0〜100)
  const [result, setResult] = useState(null); // 送り終わったときの知らせ
  const [over, setOver] = useState(false);
  const [open, setOpen] = useState(null);
  const inputRef = React.useRef(null);
  const load = () => listVideoRefs().then((r) => setItems(r.items)).catch(() => {});
  useEffect(() => { load(); const t = setInterval(load, 10000); return () => clearInterval(t); }, []);
  const pick = (f) => { if (f) { setFile(f); setResult(null); if (!name) setName(f.name.replace(/\.[^.]+$/, "")); } };
  const send = async () => {
    if (!file || pct !== null) return;
    setPct(0); setResult(null);
    try {
      const r = await uploadVideoRef(file, name, note, (p) => setPct(p));
      setResult(r.duplicate
        ? { tone: "warn", text: `同じ動画を${r.when || "さっき"}受け取っています。二重には分析しません(下の一覧で進み具合が見られます)` }
        : { tone: "ok", text: `「${r.name}」を受け取りました。カット・音量・言葉に分けてから、映像制作部が分析します(数分〜10分ほど)` });
      setFile(null); setName(""); setNote(""); if (inputRef.current) inputRef.current.value = "";
      load();
    } catch (e) { setResult({ tone: "ng", text: `送れませんでした: ${e.message}` }); notify(e.message, "error"); }
    setPct(null);
  };
  return (
    <section className="card vr">
      <div className="card-head"><h3>🎬 参考動画の分析</h3>
        <span className="muted small">リールの画面収録を入れると、カット・音量・言葉・テロップの出方を秒ごとに分析します(他の人の動画は分析だけに使い、転載しません)</span></div>
      <div className="vr-form">
        <label className={`vr-drop ${over ? "over" : ""} ${file ? "has" : ""}`}
               onDragOver={(e) => { e.preventDefault(); setOver(true); }} onDragLeave={() => setOver(false)}
               onDrop={(e) => { e.preventDefault(); setOver(false); pick(e.dataTransfer.files?.[0]); }}>
          <input ref={inputRef} type="file" accept="video/*" onChange={(e) => pick(e.target.files?.[0])} />
          {file ? <><b>🎞 {file.name}</b><span>{fmtMB(file.size)}・ほかの動画にするときは、もう一度ここを押す</span></>
                : <><b>＋ 動画を選ぶ(ここに置いてもOK)</b><span>iPhone の画面収録(音も入ります)など。600MB まで</span></>}
        </label>
        <div className="vr-fields">
          <label><span>名前</span><input value={name} onChange={(e) => setName(e.target.value)} placeholder="例 yamayuki_design デザイン20選" /></label>
          <label><span>見てほしい所</span><input value={note} onChange={(e) => setNote(e.target.value)} placeholder="例 BGMの入り方とテロップの出る速さ" /></label>
          <button className="btn primary vr-send" disabled={!file || pct !== null} onClick={send}>
            {pct !== null ? (pct < 100 ? `送信中… ${pct}%` : "受け取り中…") : "分析してもらう"}</button>
        </div>
      </div>
      {pct !== null && <div className="vr-bar"><i style={{ width: `${Math.max(pct, 2)}%` }} /></div>}
      {result && <div className={`vr-msg ${result.tone}`}>{result.tone === "ok" ? "✓ " : result.tone === "ng" ? "✕ " : "! "}{result.text}</div>}
      {items.length > 0 && <div className="vr-list">
        {items.map((it) => {
          const st = it.running ? it.status : it.done ? "分析ができました" : "作成中";
          return (
            <div key={it.folder || it.id} className="vr-item">
              <div className="vr-row">
                <span className={`vr-chip ${STATUS_TONE(st)}`}>{st}</span>
                <b className="vr-name">{it.name}</b>
                {it.error && <span className="muted small">{it.error}</span>}
                {it.done && <button className="btn sm ghost" onClick={() => setOpen(open === it.folder ? null : it.folder)}>{open === it.folder ? "閉じる" : "▶ 分析を読む"}</button>}
              </div>
              {open === it.folder && it.done && <div className="md-box"><Md text={it.summary} /><div className="muted small">続きは {it.folder}/analysis.md</div></div>}
            </div>
          );
        })}
      </div>}
    </section>
  );
}

/* Muse の答え: 社長が Instagram の Muse に決まった質問をし、答えを貼る(週次リサーチ・速報チェックが読む) */
function MuseBox({ notify }) {
  const [d, setD] = useState(null);
  const [kind, setKind] = useState("weekly_top");
  const [text, setText] = useState("");
  const load = () => getMuse().then(setD).catch(() => {});
  useEffect(() => { load(); }, []);
  if (!d) return null;
  const q = d.questions.find((x) => x.id === kind);
  const copy = async (t) => { try { await navigator.clipboard.writeText(t); notify("質問をコピーしました。Muse に貼ってください", "ok"); } catch { notify("コピーできませんでした。長押しで選んでください", "error"); } };
  const save = async () => {
    try { const r = await saveMuse(text, kind); notify(`保存しました(URL ${r.urls}件)。次のリサーチで部署が読みます`, "ok"); setText(""); load(); }
    catch (e) { notify(e.message, "error"); }
  };
  return (
    <section className="card">
      <div className="card-head"><h3>📱 Muse の答え</h3>
        <span className="muted small">Instagram の Muse に質問をコピーして聞き、答えをここに貼ります。社長の画面でしか見えない流行を、週次リサーチと速報チェックが使います</span></div>
      <div className="pr-form">
        <label><span>質問</span>
          <select value={kind} onChange={(e) => setKind(e.target.value)}>
            {d.questions.map((x) => <option key={x.id} value={x.id}>{x.text.slice(0, 28)}…({x.when})</option>)}
          </select></label>
        {q && <div className="muse-q"><span>{q.text}</span> <button className="btn sm" onClick={() => copy(q.text)}>コピー</button></div>}
        <label><span>Muse の答え</span><textarea rows={5} value={text} onChange={(e) => setText(e.target.value)} placeholder="Muse の答えをそのまま貼る(URL も一緒に)" /></label>
        <button className="btn primary" disabled={text.trim().length < 10} onClick={save}>保存</button>
      </div>
      {d.recent.length > 0 && <div className="muted small">最近の答え: {d.recent.slice(0, 5).map((r) => r.at.replace("T", " ")).join(" / ")}</div>}
    </section>
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

      <MuseBox notify={notify} />
      <VideoRefs notify={notify} />

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
