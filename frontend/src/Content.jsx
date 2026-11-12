import { createPortal } from "react-dom";
import Md from "./Md.jsx";
import React, { useEffect, useState } from "react";
import { getContentWeeks, getContentWeek, decidePost, approveWeek, getPostResults, addInsight } from "./api.js";

const POST_CLASS = { 下書き: "s-todo", 承認待ち: "s-wait", 承認済み: "s-ok", 差し戻し: "s-ng", 投稿済み: "s-done" };
const FORMAT_JA = { reel: "リール", carousel: "カルーセル", story: "ストーリー", post: "投稿", thread: "スレッド", article: "記事" };
const fileUrl = (p) => `/api/content/file?path=${encodeURIComponent(p)}`;

function Asset({ path }) {
  const ext = path.split(".").pop().toLowerCase();
  if (["png", "jpg", "jpeg", "webp", "gif"].includes(ext)) return <a href={fileUrl(path)} target="_blank" rel="noreferrer"><img src={fileUrl(path)} alt="" /></a>;
  if (["mp4", "mov", "webm"].includes(ext)) return <video src={fileUrl(path)} controls preload="metadata" />;
  return <a className="btn sm" href={fileUrl(path)} target="_blank" rel="noreferrer">{path.split("/").pop()}</a>;
}

function Thumb({ item, onOpen }) {
  if (!item.exists) return <div className="m-missing">ドライブに<br />まだありません</div>;
  if (item.kind === "image") return <button className="m-open" onClick={onOpen} title="投稿の見え方で見る"><img src={fileUrl(item.path)} alt={item.name} /></button>;
  if (item.kind === "video") return <button className="m-open" onClick={onOpen} title="投稿の見え方で見る"><video src={fileUrl(item.path)} muted preload="metadata" /><span className="m-play">▶</span></button>;
  return <a className="btn sm" href={fileUrl(item.path)} target="_blank" rel="noreferrer">{item.name}</a>;
}

const IG_HANDLE = "ai_hisho_sena";
const AVATAR = "/faces/normal.jpg";

/** Instagram の投稿画面に近い見え方(スマホの枠)。カルーセルは左右で送る、リールは縦の全画面 */
// ---------- note の記事: タイトル・本文・ハッシュタグを分けて見せ、それぞれコピーできるようにする ----------
/** 記事を頭から最後まで Markdown にする(note に貼る用。見出し=##、小見出し=###、箇条書き=-) */
export const articleMarkdown = (a) => a.blocks.map((b) => (b.heading ? `## ${b.heading}\n\n` : "") + (b.text || "")).join("\n\n").trim();

export async function copyArticle(article, notify) {
  const text = articleMarkdown(article);  // 頭から最後まで Markdown(## 見出し・- 箇条書き)
  try {
    await navigator.clipboard.writeText(text);
    notify && notify("本文を Markdown でコピーしました(note の本文に貼り付け)", "ok");
    return true;
  } catch (e) { notify && notify("コピーできませんでした。本文を選択してコピーしてください", "error"); return false; }
}


const IMG_MARK = /^\s*【画像\s*(\d+)\s*[::]\s*([^\s―—】]+)?[^】]*】\s*$/;
/** note の画面に近い見た目で記事を見る(見出し画像・タイトル・見出し・図の位置) */
export function NotePreview({ post, onClose }) {
  const a = post.article;
  const imgs = (post.media || []).filter((m) => m.exists && m.kind !== "video" && m.kind !== "file");
  const imgFor = (n, name) => imgs.find((m) => name && m.name === name) || imgs.find((m) => name && m.name.includes(name.replace(/\.png$/, ""))) || imgs[n - 1];
  const head = imgs.find((m) => /見出し|_01_/.test(m.name)) || imgs[0];
  useEffect(() => { const k = (e) => { if (e.key === "Escape") onClose(); }; window.addEventListener("keydown", k); return () => window.removeEventListener("keydown", k); }, []);
  const body = (text) => {
    const out = []; let buf = [];
    const flush = () => { if (buf.length) out.push(<Md key={out.length} className="np-text" text={buf.join("\n")} />); buf = []; };
    for (const line of (text || "").split("\n")) {
      const m = line.match(IMG_MARK);
      if (m) { flush(); const im = imgFor(Number(m[1]), m[2]);
        out.push(im ? <figure key={out.length} className="np-fig"><img src={fileUrl(im.path)} alt={im.name} /></figure>
                    : <div key={out.length} className="np-missing">{line.trim()}(画像がドライブにありません)</div>); }
      else if (/^###\s+/.test(line)) { flush(); out.push(<h3 key={out.length}>{line.replace(/^###\s+/, "")}</h3>); }
      else buf.push(line);
    }
    flush();
    return out;
  };
  return createPortal(
    <div className="pv-back" onClick={onClose}>
      <div className="np-wrap" onClick={(e) => e.stopPropagation()}>
        <div className="pv-tabs"><span className="np-label">note のプレビュー(実際の見え方に近い表示)</span>
          <button className="pv-x" onClick={onClose} aria-label="閉じる">×</button></div>
        <article className="np-page">
          {head && <img className="np-head" src={fileUrl(head.path)} alt="見出し画像" />}
          <h1 className="np-title">{a.title}</h1>
          <div className="np-author"><img src={AVATAR} alt="" /><span>AI秘書セナ|AI会社の実録</span></div>
          {a.blocks.map((b, i) => (
            <section key={i}>{b.heading && <h2>{b.heading}</h2>}{body(b.text)}</section>
          ))}
          {a.tags.length > 0 && <div className="np-tags">{a.tags.map((t) => <span key={t}>#{t}</span>)}</div>}
        </article>
      </div>
    </div>, document.body);
}

export function NoteArticle({ post, notify }) {
  const a = post.article;
  const [view, setView] = useState("split");  // split = 分けて見る / md = Markdown(コードブロック)
  const [preview, setPreview] = useState(false);
  const md = articleMarkdown(a);
  const copyText = async (t, label) => {
    try { await navigator.clipboard.writeText(t); notify(`${label}をコピーしました`, "ok"); }
    catch (e) { notify("コピーできませんでした", "error"); }
  };
  const tags = (a.tags || []).map((t) => "#" + t).join(" ");
  return (
    <div className="note-art">
      {preview && <NotePreview post={post} onClose={() => setPreview(false)} />}
      <div className="na-bar">
        <div className="seg">
          <button className={view === "split" ? "on" : ""} onClick={() => setView("split")}>分けて見る</button>
          <button className={view === "md" ? "on" : ""} onClick={() => setView("md")}>Markdown(全文)</button>
        </div>
        <button className="btn" onClick={() => setPreview(true)}>プレビュー</button>
      </div>
      <div className="na-box">
        <div className="na-head"><span className="na-label">① タイトル</span><span className="muted small">{a.title.length}字</span>
          <button className="btn sm" onClick={() => copyText(a.title, "タイトル")}>コピー</button></div>
        <div className="na-title">{a.title}</div>
      </div>
      {view === "md" ? (
        <div className="na-box na-body">
          <div className="na-head"><span className="na-label">② 本文(Markdown・頭から最後まで)</span><span className="muted small">{md.length.toLocaleString()}字</span>
            <button className="btn sm primary" onClick={() => copyArticle(a, notify)}>全部コピー</button></div>
          <div className="muted small na-hint">## = 見出し、### = 小見出し、- = 箇条書き。note の本文にそのまま貼り付けます。【画像N】の行は、その位置に図を入れてから消します</div>
          <pre className="na-md"><code>{md}</code></pre>
        </div>
      ) : (
      <div className="na-box na-body">
        <div className="na-head"><span className="na-label">② 本文(記事)</span><span className="muted small">{a.chars.toLocaleString()}字・見出し{a.blocks.filter((b) => b.heading).length}個</span>
          <button className="btn sm primary" onClick={() => copyArticle(a, notify)}>本文を全部コピー(Markdown)</button></div>
        <div className="muted small na-hint">コピーは Markdown(## = 見出し)。見出しにならなかったら、その行を選んで note の見出しに設定。【画像N】の所に図を入れます</div>
        {a.blocks.map((b, i) => (
          <div key={i} className="na-block">
            {b.heading && <div className="na-h"><span className="na-tag">見出し</span>{b.heading}
              <button className="btn ghost sm" onClick={() => copyText(b.heading, "見出し")}>コピー</button></div>}
            <Md className="sec-text" text={b.text} />
          </div>
        ))}
      </div>
      )}
      <div className="na-box">
        <div className="na-head"><span className="na-label">③ ハッシュタグ</span>
          {tags && <button className="btn sm" onClick={() => copyText(tags, "ハッシュタグ")}>コピー</button>}</div>
        {tags ? <div className="na-tags">{a.tags.map((t) => <span key={t} className="chip2">#{t}</span>)}</div>
              : <div className="muted small">未設定です(記事ファイルに「## ハッシュタグ」が無い)。SNS運用部に付けてもらうか、note の画面で付けてください</div>}
      </div>
      {a.memo && <div className="post-sec"><div className="sec-title">社長の投稿メモ</div><Md className="sec-text" text={a.memo} /></div>}
      {a.internal.filter((x) => x.title.includes("社長コメント")).map((x, i) => (
        <div key={"c" + i} className="post-sec comment"><div className="sec-title">{x.title}</div><Md className="sec-text" text={x.text} /></div>))}
      {a.internal.length > 0 && (
        <details className="na-internal">
          <summary className="muted small">制作メモ(社内用・コピーしない): {a.internal.map((x) => x.title).join("・")}</summary>
          {a.internal.filter((x) => !x.title.includes("社長コメント")).map((x, i) => <div key={i} className="post-sec"><div className="sec-title">{x.title}</div><Md className="sec-text" text={x.text} /></div>)}
        </details>
      )}
    </div>
  );
}

const PJA_R = { instagram: "Instagram", x: "X", threads: "Threads", note: "note", tiktok: "TikTok", youtube: "YouTube" };
const plusDays = (d, n) => { try { const t = new Date(d + "T00:00:00"); t.setDate(t.getDate() + n); return t.toISOString().slice(0, 10); } catch (e) { return ""; } };
const todayStr = () => new Date().toISOString().slice(0, 10);
/** 投稿1本の結果(エンゲージメント)を見て・記録する。社長が投稿の画面からそのまま入れる */
export function PostResults({ post, platform, postedOn, notify }) {
  const pf = platform || post.platform;
  const [data, setData] = useState(null);
  const [vals, setVals] = useState({});
  const [date, setDate] = useState(todayStr());
  const [busy, setBusy] = useState(false);
  const acct = post.account || "main";
  const load = () => getPostResults(pf, post.id, acct).then(setData).catch((e) => notify && notify(e.message, "error"));
  useEffect(() => { load(); }, [pf, post.id]);
  const posted = postedOn || post.posted;
  const due = posted ? plusDays(posted, 3) : "";
  const save = async () => {
    setBusy(true);
    try { await addInsight(pf, { ...vals, content_id: post.id, format: post.format || "" }, date, true, acct); notify(`${PJA_R[pf] || pf}「${post.title}」の結果を記録しました`, "ok"); setVals({}); load(); }
    catch (e) { notify(e.message, "error"); }
    setBusy(false);
  };
  if (!data) return null;
  return (
    <div className="pr-box">
      <div className="pr-head"><b>結果(エンゲージメント)</b><span className="muted small">{PJA_R[pf] || pf}・{post.id}</span>
        {due && <span className="muted small">投稿 {posted} → 3日後(72時間後)の数字で記録: {due} ごろ</span>}</div>
      {data.results.length > 0 && (
        <div className="table-wrap"><table className="tbl">
          <thead><tr><th>記録日</th>{data.columns.map((c) => <th key={c.key}>{c.label}</th>)}</tr></thead>
          <tbody>{data.results.map((r, i) => <tr key={i}><td>{r.date}</td>{data.columns.map((c) => <td key={c.key}>{r[c.key]}</td>)}</tr>)}</tbody>
        </table></div>
      )}
      <div className="pr-form">
        <label><span>記録日</span><input type="date" value={date} onChange={(e) => setDate(e.target.value)} /></label>
        {data.columns.map((c) => (
          <label key={c.key}><span>{c.label}</span>
            <input inputMode="numeric" value={vals[c.key] || ""} placeholder="0" onChange={(e) => setVals({ ...vals, [c.key]: e.target.value.replace(/[^0-9.]/g, "") })} /></label>
        ))}
        <button className="btn primary" disabled={busy || !Object.values(vals).some((v) => v)} onClick={save}>結果を記録</button>
      </div>
      <div className="muted small">金曜の数字の見直しで、分析部がこの数字を使います(同じ投稿を何度記録しても、新しい順に残ります)</div>
    </div>
  );
}

export function PostPreview({ post, start = 0, onClose }) {
  const items = (post.media || []).filter((m) => m.exists && m.kind !== "file");
  const [i, setI] = useState(Math.min(start, Math.max(0, items.length - 1)));
  const [more, setMore] = useState(false);
  const [mode, setMode] = useState(post.format === "reel" ? "reel" : "feed");
  const next = () => setI((v) => Math.min(items.length - 1, v + 1));
  const prev = () => setI((v) => Math.max(0, v - 1));
  useEffect(() => {
    const k = (e) => { if (e.key === "Escape") onClose(); if (e.key === "ArrowRight") next(); if (e.key === "ArrowLeft") prev(); };
    window.addEventListener("keydown", k);
    return () => window.removeEventListener("keydown", k);
  }, [items.length]);
  const touch = React.useRef(null);
  const cap = post.caption || "";
  const capShort = cap.length > 90 && !more;
  const cur = items[i];
  const media = cur && (cur.kind === "video"
    ? <video key={cur.path} src={fileUrl(cur.path)} autoPlay loop playsInline controls={mode !== "reel"} onClick={(e) => { const v = e.currentTarget; v.paused ? v.play() : v.pause(); }} />
    : <img key={cur.path} src={fileUrl(cur.path)} alt={cur.name} />);
  const grid = (
    <div className="pv-grid">
      {post.cover?.exists && <div className="pv-gcell on"><img src={fileUrl(post.cover.path)} alt="" /></div>}
      {[1, 2, 3, 4, 5].map((n) => <div key={n} className="pv-gcell" />)}
    </div>
  );
  return createPortal(
    <div className="pv-back" onClick={onClose}>
      <div className="pv-wrap" onClick={(e) => e.stopPropagation()}>
        <div className="pv-tabs">
          {post.format === "reel" ? <button className={mode === "reel" ? "on" : ""} onClick={() => setMode("reel")}>リール</button>
            : <button className={mode === "feed" ? "on" : ""} onClick={() => setMode("feed")}>フィード</button>}
          {post.format === "reel" && <button className={mode === "feed" ? "on" : ""} onClick={() => setMode("feed")}>フィード</button>}
          {post.cover && <button className={mode === "grid" ? "on" : ""} onClick={() => setMode("grid")}>プロフィール一覧</button>}
          <button className="pv-x" onClick={onClose} aria-label="閉じる">×</button>
        </div>
        <div className={`pv-phone ${mode}`}>
          {mode === "grid" ? (
            <div className="pv-profile">
              <div className="pv-ph-head"><b>{IG_HANDLE}</b></div>
              <div className="pv-prow"><img className="pv-av lg" src={AVATAR} alt="" /><div className="pv-stats"><div><b>-</b><span>投稿</span></div><div><b>-</b><span>フォロワー</span></div><div><b>-</b><span>フォロー中</span></div></div></div>
              <div className="pv-note">この投稿の表紙が、一覧の左上(最新)に並んだときの見え方</div>
              {grid}
            </div>
          ) : mode === "reel" ? (
            <div className="pv-reel">
              {media}
              <div className="pv-reel-side"><span>♡</span><span>💬</span><span>➤</span><span>⋯</span></div>
              <div className="pv-reel-cap">
                <div className="pv-user"><img className="pv-av" src={AVATAR} alt="" /><b>{IG_HANDLE}</b><span className="pv-follow">フォロー</span></div>
                <div className="pv-cap-text" onClick={() => setMore(!more)}>{capShort ? cap.slice(0, 60) + "… 続きを読む" : cap}</div>
              </div>
            </div>
          ) : (
            <div className="pv-feed">
              <div className="pv-user top"><img className="pv-av" src={AVATAR} alt="" /><b>{IG_HANDLE}</b><span className="pv-dots">⋯</span></div>
              <div className={`pv-media ${cur?.kind === "video" ? "video" : ""}`}
                   onTouchStart={(e) => (touch.current = e.touches[0].clientX)}
                   onTouchEnd={(e) => { const d = e.changedTouches[0].clientX - (touch.current ?? 0); if (d < -40) next(); if (d > 40) prev(); }}>
                {media}
                {items.length > 1 && <span className="pv-count">{i + 1}/{items.length}</span>}
                {i > 0 && <button className="pv-nav l" onClick={prev} aria-label="前へ">‹</button>}
                {i < items.length - 1 && <button className="pv-nav r" onClick={next} aria-label="次へ">›</button>}
              </div>
              <div className="pv-actions"><span>♡</span><span>💬</span><span>➤</span>
                {items.length > 1 && <div className="pv-dotsrow">{items.map((_, k) => <i key={k} className={k === i ? "on" : ""} onClick={() => setI(k)} />)}</div>}
                <span className="pv-save">🔖</span></div>
              <div className="pv-cap"><b>{IG_HANDLE}</b> <span onClick={() => setMore(!more)}>{capShort ? cap.slice(0, 90) + "… 続きを読む" : cap}</span></div>
              <div className="pv-when">{post.scheduled ? `${post.scheduled} 公開予定` : ""}</div>
            </div>
          )}
        </div>
        {items.length === 0 && <div className="pv-empty">ドライブに画像・動画がまだありません</div>}
        <div className="pv-hint">← → で送る ・ Esc で閉じる ・ 「いいね」などの数は表示用の飾りです</div>
      </div>
    </div>
  , document.body);
}

/** 投稿する素材(どの画像・動画を、どの順で上げるか)と表紙 */
function MediaPanel({ post }) {
  const { media = [], cover } = post;
  const [preview, setPreview] = useState(null);
  if (!media.length && !cover) return null;
  const missing = media.filter((m) => !m.exists).length + (cover && !cover.exists && !media.some((m) => m.is_cover) ? 1 : 0);
  const openAt = (path) => setPreview({ start: Math.max(0, (media || []).filter((m) => m.exists && m.kind !== "file").findIndex((m) => m.path === path)) });
  return (
    <div className="media-panel">
      {preview && <PostPreview post={post} start={preview.start} onClose={() => setPreview(null)} />}
      {cover && (
        <div className="m-cover">
          <div className="sec-title">表紙</div><div className="muted small">プロフィールの一覧に出る1枚</div>
          <div className="m-tile cover"><Thumb item={{ ...cover, kind: "image" }} onOpen={() => openAt(cover.path)} /></div>
          <div className="m-name">{cover.name}</div>
          {cover.how && <div className="muted small">{cover.how}</div>}
          {!cover.how && post.cover_note && <div className="muted small">{post.cover_note}</div>}
        </div>
      )}
      {media.length > 0 && (
        <div className="m-list">
          <div className="sec-title">投稿する素材<span className="muted small">({media.length}点・この順で選ぶ)</span>
            {missing > 0 && <span className="badge s-ng">未保存 {missing}</span>}
            {media.some((m) => m.exists) && <button className="btn sm primary pv-open-btn" onClick={() => setPreview({ start: 0 })}>投稿の見え方で見る</button>}</div>
          <div className="m-grid">
            {media.map((m) => (
              <div key={m.path} className="m-item">
                <div className={`m-tile ${m.kind}`}>
                  <span className="m-no">{m.label}{m.is_cover ? "・表紙" : ""}</span>
                  <Thumb item={m} onOpen={() => openAt(m.path)} />
                </div>
                <div className="m-name">{m.name}</div>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

function Post({ post, open, onToggle, onChanged, notify }) {
  const [rejecting, setRejecting] = useState(false);
  const [comment, setComment] = useState("");
  const [busy, setBusy] = useState(false);
  const act = async (decision, c = "") => {
    setBusy(true);
    try {
      await decidePost(post.path, decision, c);
      notify(`${post.title}:${{ approve: "承認しました", reject: "差し戻しました", posted: "投稿済みにしました", unpost: "投稿前(承認済み)に戻しました", draft: "下書きに戻しました", wait: "承認待ちにしました" }[decision]}`, "ok");
      setRejecting(false); setComment("");
      onChanged();
    } catch (e) { notify(e.message, "error"); }
    setBusy(false);
  };
  const STATUS_TO = { 下書き: "draft", 承認待ち: "wait", 承認済み: "approve", 差し戻し: "reject", 投稿済み: "posted" };
  const change = (st) => {
    if (!st || st === post.status) return;
    if (st === "差し戻し") { setRejecting(true); return; }
    if (st === "承認済み" && post.status === "下書き"
        && !window.confirm("この投稿は、まだ品質管理部のチェック前(下書き)です。このまま承認しますか?")) return;
    if (post.status === "投稿済み" && st === "承認済み") { act("unpost"); return; }
    if (st === "投稿済み" && post.status !== "承認済み"
        && !window.confirm("まだ承認されていない投稿です。投稿済みにしますか?")) return;
    act(STATUS_TO[st]);
  };
  const copy = async () => {
    try { await navigator.clipboard.writeText(post.caption); notify("キャプションをコピーしました", "ok"); }
    catch (e) { notify("コピーできませんでした。本文を選択してコピーしてください", "error"); }
  };
  return (
    <div className={`card post ${open ? "open" : ""}`}>
      <div className="post-head" onClick={onToggle}>
        {post.cover?.exists && <img className="head-cover" src={fileUrl(post.cover.path)} alt="" />}
        <span className={`plat plat-${post.platform}`}>{post.platform_ja}</span>
        <span className="muted small">{FORMAT_JA[post.format] || post.format}</span>
        <span className="ttl">{post.title}{post.author === "codex" && <span className="by-codex" title="別の会社のAI(OpenAI Codex)が作った別案">Codex案</span>}</span>
        {post.pr && <span className="badge s-wait">PR</span>}
        <span className="muted small">{post.scheduled}</span>
        <span className={`badge ${POST_CLASS[post.status] || ""}`}>{post.status}</span>
      </div>
      {open && (
        <div className="post-body">
          {post.media || post.cover ? <MediaPanel post={post} />
            : post.assets.length > 0 && <div className="assets">{post.assets.map((a) => <Asset key={a} path={a} />)}</div>}
          {post.article ? <NoteArticle post={post} notify={notify} /> : post.sections.map((s, i) => (
            <div key={i} className={`post-sec ${s.title.includes("社長コメント") ? "comment" : ""}`}>
              {s.title && <div className="sec-title">{s.title}
                {s.title.includes("キャプション") && <button className="btn ghost sm" onClick={copy}>コピー</button>}</div>}
              <Md className="sec-text" text={s.text} />
            </div>
          ))}
          {post.status === "投稿済み" && <PostResults post={post} notify={notify} />}
          {rejecting ? (
            <div className="ac-reject">
              <textarea autoFocus value={comment} onChange={(e) => setComment(e.target.value)} placeholder="差し戻しの理由(何を直してほしいか)" />
              <div className="ac-actions">
                <button className="btn ghost" onClick={() => setRejecting(false)}>戻る</button>
                <button className="btn danger" disabled={busy} onClick={() => act("reject", comment)}>差し戻す</button>
              </div>
            </div>
          ) : (
            <div className="ac-actions">
              {["承認待ち", "差し戻し", "下書き"].includes(post.status) && <button className="btn" disabled={busy} onClick={() => setRejecting(true)}>差し戻す</button>}
              {post.status === "承認待ち" && <button className="btn primary" disabled={busy} onClick={() => act("approve")}>承認する</button>}
              {post.status === "承認済み" && <button className="btn primary" disabled={busy} onClick={() => act("posted")}>投稿しました</button>}
              {post.status === "投稿済み" && <button className="btn" disabled={busy} title="間違えて投稿済みにしたとき"
                onClick={() => window.confirm("「投稿済み」を取り消して、投稿前(承認済み)に戻しますか?") && act("unpost")}>投稿前に戻す</button>}
              <label className="status-pick">状態を変える
                <select value={post.status} disabled={busy} onChange={(e) => change(e.target.value)}>
                  {Object.keys(STATUS_TO).map((st) => <option key={st} value={st}>{st}</option>)}
                </select>
              </label>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

/** 投稿セット(週ごと)。台本・キャプション・画像を見て、承認・差し戻し・投稿済みを付ける */
export default function Content({ week, setWeek, onChanged, notify, onSay, platform = null, account = null }) {
  const [weeks, setWeeks] = useState(null);
  const [data, setData] = useState(null);
  const [open, setOpen] = useState(null);
  const [busy, setBusy] = useState(false);

  const loadWeeks = () => getContentWeeks().then((r) => {
    setWeeks(r.weeks);
    if (!week && r.weeks.length) setWeek(r.weeks[0].week);
  }).catch((e) => notify(e.message, "error"));
  const loadWeek = () => week && getContentWeek(week).then(setData).catch(() => setData(null));
  useEffect(() => { loadWeeks(); }, []);
  useEffect(() => { setOpen(null); loadWeek(); }, [week]);
  const changed = () => { loadWeek(); loadWeeks(); onChanged(); };

  if (!weeks) return <div className="empty">読み込み中…</div>;
  if (!weeks.length) {
    return (
      <div className="card setup">
        <h3>まだ投稿セットがありません</h3>
        <p className="muted">企画部・制作部が作った週の投稿(台本・キャプション・画像)がここに並び、社長が承認します。</p>
        <button className="btn primary" onClick={() => onSay("企画部に今週の投稿セットを作ってもらって")}>「今週の投稿セットを作って」と頼む</button>
      </div>
    );
  }
  // account: main=本アカウント / sub=別アカウント(2026-11-12)。未指定なら全部
  const posts = data ? data.posts.filter((p) => (!platform || p.platform === platform) && (!account || (p.account || "main") === account)) : [];
  const wcount = (w) => (account ? (w.by_account?.[account]?.[platform || "all"] || {})
                                 : (platform ? (w.by_platform?.[platform] || {}) : w.counts))["承認待ち"] || 0;
  const waiting = posts.filter((p) => p.status === "承認待ち").length;
  const approveAll = async () => {
    setBusy(true);
    try { const r = await approveWeek(week, account || undefined); notify(`${week} の ${r.approved}件を承認しました`, "ok"); changed(); }
    catch (e) { notify(e.message, "error"); }
    setBusy(false);
  };

  return (
    <div className="content-tab">
      <div className="seg">
        {weeks.map((w) => (
          <button key={w.week} className={week === w.week ? "on" : ""} onClick={() => setWeek(w.week)}>
            {w.week}{wcount(w) ? <span className="count warn">{wcount(w)}</span> : null}
          </button>
        ))}
      </div>
      {data && (
        <>
          <div className="card week-head">
            <div>
              <div className="muted small">{data.week} のテーマ{data.task ? ` ・ タスク ${data.task}` : ""}</div>
              <h3 className="week-theme">{data.theme || "(未定)"}</h3>
              {data.summary && <WeekNote text={data.summary} />}
            </div>
            {waiting > 0 && !platform && <button className="btn primary" disabled={busy} onClick={approveAll}>承認待ち {waiting}件を全部承認</button>}
          </div>
          {posts.map((p) => (
            <Post key={p.path} post={p} open={open === p.path} onToggle={() => setOpen(open === p.path ? null : p.path)}
                  onChanged={changed} notify={notify} />
          ))}
          {posts.length === 0 && <div className="empty">この週の{platform ? "この媒体の" : ""}投稿はまだありません。</div>}
        </>
      )}
    </div>
  );
}

/** 週のテーマの説明(長いので最初は畳んでおく) */
function WeekNote({ text }) {
  const [open, setOpen] = React.useState(false);
  const long = text.length > 400;
  return (
    <div className={`week-note ${open || !long ? "open" : ""}`}>
      <Md text={text} />
      {long && <button className="btn ghost sm week-more" onClick={() => setOpen(!open)}>{open ? "たたむ ▴" : "全部読む ▾"}</button>}
    </div>
  );
}
