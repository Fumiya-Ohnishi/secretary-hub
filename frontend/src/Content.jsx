import React, { useEffect, useState } from "react";
import { getContentWeeks, getContentWeek, decidePost, approveWeek } from "./api.js";

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
function PostPreview({ post, start = 0, onClose }) {
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
  return (
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
  );
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
      notify(`${post.title}:${{ approve: "承認しました", reject: "差し戻しました", posted: "投稿済みにしました" }[decision]}`, "ok");
      setRejecting(false); setComment("");
      onChanged();
    } catch (e) { notify(e.message, "error"); }
    setBusy(false);
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
        <span className="ttl">{post.title}</span>
        {post.pr && <span className="badge s-wait">PR</span>}
        <span className="muted small">{post.scheduled}</span>
        <span className={`badge ${POST_CLASS[post.status] || ""}`}>{post.status}</span>
      </div>
      {open && (
        <div className="post-body">
          {post.media || post.cover ? <MediaPanel post={post} />
            : post.assets.length > 0 && <div className="assets">{post.assets.map((a) => <Asset key={a} path={a} />)}</div>}
          {post.sections.map((s, i) => (
            <div key={i} className={`post-sec ${s.title.includes("社長コメント") ? "comment" : ""}`}>
              {s.title && <div className="sec-title">{s.title}
                {s.title.includes("キャプション") && <button className="btn ghost sm" onClick={copy}>コピー</button>}</div>}
              <div className="sec-text">{s.text}</div>
            </div>
          ))}
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
            </div>
          )}
        </div>
      )}
    </div>
  );
}

/** 投稿セット(週ごと)。台本・キャプション・画像を見て、承認・差し戻し・投稿済みを付ける */
export default function Content({ week, setWeek, onChanged, notify, onSay, platform = null }) {
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
  const posts = data ? data.posts.filter((p) => !platform || p.platform === platform) : [];
  const wcount = (w) => (platform ? (w.by_platform?.[platform] || {}) : w.counts)["承認待ち"] || 0;
  const waiting = posts.filter((p) => p.status === "承認待ち").length;
  const approveAll = async () => {
    setBusy(true);
    try { const r = await approveWeek(week); notify(`${week} の ${r.approved}件を承認しました`, "ok"); changed(); }
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
              {data.summary && <p className="muted small">{data.summary}</p>}
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
