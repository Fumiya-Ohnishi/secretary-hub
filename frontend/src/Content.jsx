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
        <span className={`plat plat-${post.platform}`}>{post.platform_ja}</span>
        <span className="muted small">{FORMAT_JA[post.format] || post.format}</span>
        <span className="ttl">{post.title}</span>
        {post.pr && <span className="badge s-wait">PR</span>}
        <span className="muted small">{post.scheduled}</span>
        <span className={`badge ${POST_CLASS[post.status] || ""}`}>{post.status}</span>
      </div>
      {open && (
        <div className="post-body">
          {post.assets.length > 0 && <div className="assets">{post.assets.map((a) => <Asset key={a} path={a} />)}</div>}
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
