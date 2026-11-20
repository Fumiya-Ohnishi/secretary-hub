import React, { useEffect, useState } from "react";
import { getExternalPosts, previewExternalPost, addExternalPost, patchExternalPost, removeExternalPost, refreshExternalPosts } from "./api.js";
import { PostResults } from "./Content.jsx";

/** 秘書ハブの外(Muse など)で作って出した投稿を、URL を貼って足す(2026-11-20 社長)。
 *  足した投稿は、投稿日の週(例 2026-47)の一覧に並ぶ(2026-11-20 社長「ここに溜まると見にくい。どの週か分かるように」) */
export const EXT_PLATFORMS = ["tiktok", "youtube", "note", "x"];
const PJA = { tiktok: "TikTok", youtube: "YouTube", note: "note", x: "X" };
const EXT_HINT = {
  tiktok: "題・サムネイル・投稿日を取ります。再生数などは TikTok の画面を見て「数字」から入れてください",
  youtube: "題・投稿日・再生数・いいね・コメントを取ります(毎朝 8:00 に取り直し)",
  note: "題・公開日・スキ・見出し画像を取ります(スキは毎朝 8:00 に取り直し)。ページビューは note の画面を見て「数字」から入れてください",
  x: "本文の頭・投稿日を取ります。数字は X の画面を見て「数字」から入れてください",
};
const PLACEHOLDER = { tiktok: "https://www.tiktok.com/@名前/video/…", youtube: "https://www.youtube.com/shorts/…", note: "https://note.com/名前/n/…", x: "https://x.com/名前/status/…" };

export function useExternalPosts(account, platform) {
  const [items, setItems] = useState(null);
  const load = () => (EXT_PLATFORMS.includes(platform)
    ? getExternalPosts(account || "main", platform).then((r) => setItems(r.items)).catch(() => setItems([]))
    : Promise.resolve(setItems([])));
  useEffect(() => { setItems(null); load(); }, [account, platform]);
  return [items, load];
}

const numText = (it, platform) => Object.entries(it.numbers || {})
  .map(([k, v]) => `${{ views: "再生", likes: platform === "note" ? "スキ" : "いいね", comments: "コメント" }[k] || k} ${Number(v).toLocaleString()}`).join("・");

/** URL を貼る欄。足したら onAdded(足した投稿) — 呼ぶ側がその週に移る */
export function ExtAddBox({ platform, account = "main", notify, onAdded, canRefresh }) {
  const [url, setUrl] = useState("");
  const [pv, setPv] = useState(null);
  const [busy, setBusy] = useState(false);
  const [open, setOpen] = useState(false);
  useEffect(() => { setPv(null); setUrl(""); }, [platform, account]);
  const check = async () => {
    if (!url.trim()) return;
    setBusy(true);
    try { setPv(await previewExternalPost(url.trim(), account)); } catch (e) { setPv(null); notify(e.message, "error"); }
    setBusy(false);
  };
  const add = async (other = false) => {
    setBusy(true);
    try {
      const r = await addExternalPost(url.trim(), account, "", other);
      notify(`「${r.title.slice(0, 30)}」を ${r.week || "その週"} に足しました`, "ok");
      setUrl(""); setPv(null); onAdded && onAdded(r);
    } catch (e) { notify(e.message, "error"); }
    setBusy(false);
  };
  const refresh = async () => {
    setBusy(true);
    try {
      const r = await refreshExternalPosts(account);
      notify(`数字を取り直しました(${r.updated}本)${r.errors.length ? "。取れなかったもの: " + r.errors.join(" / ") : ""}`, r.errors.length ? "error" : "ok");
      onAdded && onAdded(null);
    } catch (e) { notify(e.message, "error"); }
    setBusy(false);
  };
  return (
    <div className="card ext-add">
      <div className="ext-add-head">
        <button className="btn ghost sm" onClick={() => setOpen(!open)}>{open ? "▾" : "▸"} 外で作った {PJA[platform]} の投稿を URL で足す</button>
        {canRefresh && (platform === "note" || platform === "youtube") && <button className="btn ghost sm" disabled={busy} onClick={refresh}>数字を取り直す</button>}
      </div>
      {open && (
        <>
          <div className="muted small">Muse などで作って出した投稿の URL を貼ると、投稿日の週の一覧に足します。{EXT_HINT[platform]}</div>
          <div className="inline-form">
            <input value={url} onChange={(e) => { setUrl(e.target.value); setPv(null); }} onKeyDown={(e) => e.key === "Enter" && check()} placeholder={PLACEHOLDER[platform]} />
            <button className="btn" disabled={busy || !url.trim()} onClick={check}>{busy && !pv ? "読んでいます…" : "読み込む"}</button>
          </div>
          {pv && (
            <div className={`ext-pv ${pv.mismatch ? "warn" : ""}`}>
              {pv.thumbnail ? <img src={pv.thumbnail} alt="" referrerPolicy="no-referrer" /> : <div className="ext-noimg">画像なし</div>}
              <div className="ext-pv-body">
                <b>{pv.title}</b>
                <div className="muted small">{pv.posted_at || "投稿日は不明(足したあとに入れられます)"}{pv.author ? ` ・ @${pv.author}` : ""}{numText(pv, platform) ? ` ・ ${numText(pv, platform)}` : ""}</div>
                {pv.mismatch && <div className="ext-warn">登録したアカウントの投稿ではないようです。URL を確かめてください。</div>}
                <div className="row-btns">
                  {!pv.mismatch && <button className="btn primary sm" disabled={busy} onClick={() => add(false)}>この投稿を足す</button>}
                  {pv.mismatch && <button className="btn sm" disabled={busy} onClick={() => add(true)}>それでも足す</button>}
                  <button className="btn ghost sm" onClick={() => setPv(null)}>やめる</button>
                </div>
              </div>
            </div>
          )}
        </>
      )}
    </div>
  );
}

/** 足した投稿1本(週の一覧の中に、当社の投稿と並べて出す) */
export function ExtRow({ it, account = "main", notify, onChanged }) {
  const [open, setOpen] = useState(false);
  const setDate = async (d) => { try { await patchExternalPost(it.platform, it.id, { posted_at: d }, account); onChanged && onChanged(); } catch (e) { notify(e.message, "error"); } };
  const drop = async () => {
    if (!window.confirm(`「${it.title.slice(0, 30)}」を一覧から外しますか?(記録した数字は消えません)`)) return;
    try { await removeExternalPost(it.platform, it.id, account); onChanged && onChanged(); } catch (e) { notify(e.message, "error"); }
  };
  return (
    <div className="card post ext-item">
      <div className="ext-row">
        {it.thumbnail ? <img src={it.thumbnail} alt="" referrerPolicy="no-referrer" /> : <div className="ext-noimg">—</div>}
        <div className="ext-pv-body">
          <a href={it.url} target="_blank" rel="noreferrer" className="ttl">{it.title}</a>
          <div className="muted small">
            {it.posted_at || <input type="date" className="ext-date" onChange={(e) => e.target.value && setDate(e.target.value)} title="投稿日を入れる" />}
            {it.price ? ` ・ 有料 ${it.price}円` : ""}{numText(it, it.platform) ? ` ・ ${numText(it, it.platform)}` : ""}<span className="ext-tag">外で作成</span>
          </div>
        </div>
        <span className="badge s-done">投稿済み</span>
        <div className="row-btns">
          <button className="btn sm" onClick={() => setOpen(!open)}>{open ? "閉じる" : "数字"}</button>
          <button className="btn ghost sm" onClick={drop}>外す</button>
        </div>
      </div>
      {open && <PostResults post={{ id: it.content_id, platform: it.platform, account, title: it.title, posted: it.posted_at }} platform={it.platform} notify={notify} />}
    </div>
  );
}

/** TikTok・YouTube(週の一覧が無い媒体)用: 足した投稿を週ごとに分けて出す */
export default function ExternalPosts({ platform, account = "main", notify }) {
  const [items, load] = useExternalPosts(account, platform);
  const [week, setWeek] = useState("");
  const weeks = [...new Set((items || []).map((i) => i.week).filter(Boolean))].sort().reverse();
  useEffect(() => { if (weeks.length && !weeks.includes(week)) setWeek(weeks[0]); }, [items]);
  const shown = (items || []).filter((i) => i.week === week).sort((a, b) => (a.posted_at || "").localeCompare(b.posted_at || ""));
  return (
    <>
      <ExtAddBox platform={platform} account={account} notify={notify} canRefresh={!!items?.length}
                 onAdded={(r) => { load(); if (r?.week) setWeek(r.week); }} />
      {weeks.length > 0 && (
        <div className="seg">
          {weeks.map((w) => <button key={w} className={w === week ? "on" : ""} onClick={() => setWeek(w)}>{w}<span className="muted small"> {(items || []).filter((i) => i.week === w).length}</span></button>)}
        </div>
      )}
      {shown.map((it) => <ExtRow key={it.id} it={it} account={account} notify={notify} onChanged={load} />)}
    </>
  );
}
