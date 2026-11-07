import React, { useEffect, useMemo, useState } from "react";
import { getAllPosts, decidePost } from "./api.js";
import { PostPreview } from "./Content.jsx";

/* 「今日」画面: 社長が開いて10秒で、今日やること(投稿・判断)と昨日の成果が分かる */

const fileUrl = (p) => `/api/content/file?path=${encodeURIComponent(p)}`;
const PJA = { instagram: "Instagram", threads: "Threads", x: "X", note: "note" };
const FMT = { reel: "リール", carousel: "カルーセル", story: "ストーリー", post: "投稿", thread: "スレッド", article: "記事" };
const pad = (n) => String(n).padStart(2, "0");
const ymd = (d) => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
const WD = "日月火水木金土";

function load(k, f) { try { const v = localStorage.getItem(k); return v ? JSON.parse(v) : f; } catch (e) { return f; } }
function save(k, v) { try { localStorage.setItem(k, JSON.stringify(v)); } catch (e) {} }

function isoWeek(d) {
  const t = new Date(Date.UTC(d.getFullYear(), d.getMonth(), d.getDate()));
  const day = t.getUTCDay() || 7; t.setUTCDate(t.getUTCDate() + 4 - day);
  return Math.ceil(((t - new Date(Date.UTC(t.getUTCFullYear(), 0, 1))) / 864e5 + 1) / 7);
}

function until(s, now) {
  const t = new Date((s || "").replace(" ", "T"));
  if (isNaN(t)) return "";
  const m = Math.round((t - now) / 60000);
  if (m < -1) return `${-m < 60 ? -m + "分" : Math.floor(-m / 60) + "時間"}過ぎています`;
  if (m <= 1) return "今";
  return m < 60 ? `あと${m}分` : `あと${Math.floor(m / 60)}時間${m % 60 ? (m % 60) + "分" : ""}`;
}

/** X のスレッドはキャプションを「---」で分ける */
function threadParts(post) {
  return (post.caption || "").split(/\n-{3,}\n/).map((t) => t.trim()).filter(Boolean);
}

/** 媒体ごとの手順。id は端末に「済」を覚えておくための名前 */
function stepsFor(post) {
  const approved = ["承認済み", "投稿済み"].includes(post.status);
  const s = [{ id: "approve", label: approved ? "承認(済み)" : `承認待ち(${post.status})`, auto: approved, kind: "approve" }];
  const hasMedia = (post.media || []).some((m) => m.exists);
  if (post.platform === "instagram") {
    s.push({ id: "preview", label: "投稿の見え方を確認", kind: "preview" });
    if (hasMedia) s.push({ id: "media", label: `画像・動画をスマホに保存(${(post.media || []).filter((m) => m.exists).length}点)`, kind: "media" });
    s.push({ id: "copy", label: "キャプションをコピー", kind: "copy" });
  } else if (post.platform === "x" && post.format === "thread") {
    threadParts(post).forEach((_, i, a) => s.push({ id: `part${i}`, label: `${i + 1}/${a.length} をコピーして投稿`, kind: "part", index: i }));
  } else if (post.platform === "note") {
    if (hasMedia) s.push({ id: "media", label: "見出し画像を保存", kind: "media" });
    s.push({ id: "copy", label: "本文をコピー", kind: "copy" });
  } else {
    if (hasMedia) s.push({ id: "media", label: "画像を保存", kind: "media" });
    s.push({ id: "copy", label: "本文をコピー", kind: "copy" });
  }
  s.push({ id: "posted", label: "投稿したら押す", kind: "posted" });
  return s;
}

function PostItem({ post, open, onToggle, now, notify, onChanged, onOpenWeek }) {
  const key = `hub-steps:${post.path}`;
  const [done, setDone] = useState(() => load(key, {}));
  const [preview, setPreview] = useState(false);
  const posted = post.status === "投稿済み";
  const steps = stepsFor(post);
  const mark = (id) => { const d = { ...done, [id]: true }; setDone(d); save(key, d); };
  const isDone = (st) => posted || st.auto || done[st.id];
  const nextIdx = steps.findIndex((st) => !isDone(st));
  const copy = async (text, id, label) => {
    try { await navigator.clipboard.writeText(text); notify(`${label}をコピーしました`, "ok"); mark(id); }
    catch (e) { notify("コピーできませんでした。プレビューの文を選択してコピーしてください", "error"); }
  };
  const act = async (st) => {
    if (st.kind === "approve") return onOpenWeek(post.week);
    if (st.kind === "preview") { setPreview(true); return mark(st.id); }
    if (st.kind === "copy") return copy(post.caption, st.id, post.platform === "instagram" ? "キャプション" : "本文");
    if (st.kind === "part") return copy(threadParts(post)[st.index], st.id, `${st.index + 1}つ目`);
    if (st.kind === "media") {
      (post.media || []).filter((m) => m.exists).forEach((m, i) => setTimeout(() => {
        const a = document.createElement("a"); a.href = fileUrl(m.path); a.download = m.name; document.body.appendChild(a); a.click(); a.remove();
      }, i * 300));
      notify("保存を始めました(ブラウザのダウンロードに入ります)", "ok");
      return mark(st.id);
    }
    if (st.kind === "posted") {
      try { await decidePost(post.path, "posted"); notify(`${PJA[post.platform]}「${post.title}」を投稿済みにしました`, "ok"); onChanged(); }
      catch (e) { notify(e.message, "error"); }
    }
  };
  const btnLabel = { approve: "中身を見る", preview: "見る", media: "保存", copy: "コピー", part: "コピー", posted: "投稿しました" };
  const sday = (post.scheduled || "").slice(0, 10);
  const otherDay = sday && sday !== ymd(now);
  const time = (otherDay ? `${Number(sday.slice(5, 7))}/${Number(sday.slice(8, 10))} ` : "") + ((post.scheduled || "").slice(11, 16) || "時刻未定");
  const due = otherDay ? "遅れています" : until(post.scheduled, now);
  const late = !posted && (due.endsWith("過ぎています") || due === "遅れています");
  const doneCount = steps.filter(isDone).length;
  const textPreview = post.platform === "x" && post.format === "thread" ? threadParts(post) : [post.caption || ""];
  return (
    <div className={`tp ${posted ? "done" : ""} ${open ? "open" : ""}`}>
      {preview && <PostPreview post={post} onClose={() => setPreview(false)} />}
      <button className="tp-head" onClick={onToggle} aria-expanded={open}>
        {post.cover?.exists && <img className="tp-mini" src={fileUrl(post.cover.path)} alt="" />}
        <span className={`pf pf-${post.platform}`}>{PJA[post.platform] || post.platform}</span>
        <span className={`tp-time ${!posted && open ? "now" : ""} ${late ? "late" : ""}`}>{time}{!posted && due ? ` ${due}` : ""}</span>
        <span className="tp-ttl">{FMT[post.format] ? `${FMT[post.format]}「${post.title}」` : post.title}</span>
        {posted ? <span className="chip2 c-ok">投稿済み</span>
          : <span className="tp-dots" aria-label={`${doneCount}/${steps.length} 済み`}>{steps.map((st, i) => <i key={i} className={isDone(st) ? "d" : ""} />)}</span>}
      </button>
      {open && !posted && (
        <div className="tp-body">
          {post.platform === "instagram" ? (
            <button className="tp-cover" onClick={() => { setPreview(true); mark("preview"); }} title="投稿の見え方で見る">
              {post.cover?.exists ? <img src={fileUrl(post.cover.path)} alt="表紙" /> : <span>表紙がドライブにありません</span>}
            </button>
          ) : (
            <div className="tp-text">
              {textPreview.slice(0, 3).map((t, i) => <p key={i}>{t}</p>)}
              {textPreview.length > 3 && <p className="muted">…ほか{textPreview.length - 3}件</p>}
              <div className="tp-count">{(post.caption || "").length}字</div>
            </div>
          )}
          <ol className="tp-steps">
            {steps.map((st, i) => {
              const d = isDone(st);
              return (
                <li key={st.id} className={`${d ? "d" : ""} ${i === nextIdx ? "now" : ""}`}>
                  <span className="n">{d ? "✓" : i + 1}</span><span className="l">{st.label}</span>
                  {!st.auto && (!d || ["preview", "copy", "part", "media"].includes(st.kind)) &&
                    <button className={`btn sm ${i === nextIdx ? "primary" : ""}`} onClick={() => act(st)}>{d ? "もう一度" : btnLabel[st.kind]}</button>}
                </li>
              );
            })}
          </ol>
        </div>
      )}
    </div>
  );
}

function JobAlerts({ jobs, onSay, onTab }) {
  const [hidden, setHidden] = useState(() => load("hub-hidden-alerts", []));
  const day = Date.now() - 864e5;
  const failed = jobs.filter((j) => j.status === "error" && !hidden.includes(j.id) && new Date(j.finished || j.started).getTime() > day);
  if (!failed.length) return null;
  const why = (j) => {
    const o = j.output || "";
    if (o.includes("制限時間")) return "制限時間で止まりました(途中までは保存済み)";
    if (o.includes("残高")) return "AIの残高が足りませんでした";
    if (o.includes("利用枠")) return "プランの利用枠に達しました";
    if (o.includes("再起動")) return "秘書ハブの再起動で中断しました";
    return (o.split("\n").find((l) => l.trim()) || "原因は作業タブで確認できます").slice(0, 60);
  };
  const close = (id) => { const h = [...hidden, id].slice(-50); setHidden(h); save("hub-hidden-alerts", h); };
  return failed.slice(0, 3).map((j) => (
    <div key={j.id} className="t-alert" role="alert">
      <b>● 止まっています</b>
      <span className="t-alert-msg">{j.department_full || j.department + "部"}「{j.title}」— {why(j)}</span>
      <button className="btn sm danger" onClick={() => onSay(`「${j.title}」が止まりました。原因を見て、残りを小さく分けて頼み直して`)}>分けて頼み直す</button>
      <button className="btn sm ghost" onClick={() => onTab("jobs")}>詳細</button>
      <button className="t-x" onClick={() => close(j.id)} aria-label="この知らせを閉じる">×</button>
    </div>
  ));
}

function Yesterday({ metrics, jobs, revenue }) {
  const f = metrics?.followers || {};
  const rows = Object.keys(PJA).filter((p) => f[p]?.length).map((p) => {
    const s = f[p], last = s[s.length - 1], prev = s.length > 1 ? s[s.length - 2] : null;
    return { p, n: last.followers, diff: prev ? last.followers - prev.followers : null };
  });
  const total = rows.reduce((a, r) => a + r.n, 0);
  const diff = rows.reduce((a, r) => a + (r.diff || 0), 0);
  const since = Date.now() - 864e5;
  const done = jobs.filter((j) => j.status === "done" && new Date(j.finished || j.started).getTime() > since).length;
  return (
    <section className="card">
      <div className="card-head"><h3>③ 成果</h3><span className="muted small">最新の記録</span></div>
      <div className="t-kpis">
        <div className="t-k"><b>{total.toLocaleString()}{rows.some((r) => r.diff != null) && <em className={diff < 0 ? "neg" : ""}>{diff >= 0 ? "+" : ""}{diff}</em>}</b>
          <span>フォロワー合計</span>
          <small>{rows.length ? rows.map((r) => `${PJA[r.p]} ${r.n}`).join(" / ") : "まだ記録がありません"}</small></div>
        <div className="t-k"><b>¥{(revenue?.month_total || 0).toLocaleString()}</b><span>今月の収益</span><small>目標 ¥{(revenue?.goal || 50000).toLocaleString()}</small></div>
        <div className="t-k"><b>{done}</b><span>AI社員が終えた仕事</span><small>この24時間</small></div>
      </div>
    </section>
  );
}

const WEEK = [[1, "月", "リサーチ"], [2, "火", "企画"], [3, "水", "制作"], [4, "木", "制作・ニュース"], [5, "金", "承認・数字"], [6, "土日", "休み"]];

export default function Today({ summary, jobs, onApprove, onSay, onTab, onOpenTask, onOpenWeek, onRule, notify, onChanged, children }) {
  const [posts, setPosts] = useState(null);
  const [filter, setFilter] = useState("all");
  const [openKey, setOpenKey] = useState(null);
  // 動作確認用: URL に ?date=YYYY-MM-DD を付けると、その日の「今日」を表示する
  const forced = typeof location !== "undefined" ? new URLSearchParams(location.search).get("date") : null;
  const mkNow = () => (forced ? new Date(`${forced}T11:40:00`) : new Date());
  const [now, setNow] = useState(mkNow);
  const loadPosts = () => getAllPosts().then((r) => setPosts(r.posts || [])).catch(() => setPosts([]));
  useEffect(() => { loadPosts(); const t = setInterval(() => setNow(mkNow()), 30000); return () => clearInterval(t); }, []);
  useEffect(() => { loadPosts(); }, [summary]);
  const today = ymd(now);
  const todays = useMemo(() => (posts || []).filter((p) => (p.scheduled || "").startsWith(today)
      || (p.status === "承認済み" && p.scheduled && p.scheduled.slice(0, 10) < today))  // 遅れている投稿も今日に入れる
    .sort((a, b) => (a.scheduled || "").localeCompare(b.scheduled || "")), [posts, today]);
  const shown = todays.filter((p) => filter === "all" || p.platform === filter);
  const remaining = todays.filter((p) => p.status !== "投稿済み");
  const nextKey = (shown.find((p) => p.status !== "投稿済み") || {}).path;
  const curOpen = openKey === null ? nextKey : openKey;

  const rules = summary.rule_proposals || [];
  const contentWaiting = (summary.content_weeks || []).filter((w) => w.counts["承認待ち"]);
  const approvals = summary.tasks.filter((t) => t.status === "承認待ち");
  const decisions = rules.length + contentWaiting.length + approvals.length;
  const running = jobs.filter((j) => j.status === "running");
  const rev = summary.revenue || {};
  const pct = Math.min(100, Math.max(0, rev.progress || 0));
  const wd = now.getDay();
  const weekIdx = wd === 0 || wd === 6 ? 5 : wd - 1;
  const changed = () => { loadPosts(); onChanged(); };

  return (
    <div className="today">
      <div className="t-hello">
        <div>
          <div className="muted">{now.getMonth() + 1}月{now.getDate()}日({WD[wd]})・第{isoWeek(now)}週</div>
          <h2>社長の今日:{remaining.length ? `投稿 残り${remaining.length}件` : "投稿は全部済み"}・判断 {decisions}件</h2>
        </div>
        <div className="t-goal">
          <div className="t-goal-t"><span>今月の収益 ¥{(rev.month_total || 0).toLocaleString()}</span><span>目標まで あと ¥{Math.max(0, (rev.goal || 50000) - (rev.month_total || 0)).toLocaleString()}</span></div>
          <div className="t-bar"><i style={{ width: `${Math.max(pct, 1.5)}%` }} /></div>
        </div>
      </div>

      <JobAlerts jobs={jobs} onSay={onSay} onTab={onTab} />

      <div className="t-grid">
        <section className="card t-posts">
          <div className="card-head"><h3>① 今日の投稿</h3><span className="muted small">{todays.length}件(済 {todays.length - remaining.length}・残り {remaining.length})</span></div>
          <div className="t-filter" role="group" aria-label="媒体で絞り込む">
            {[["all", "すべて"], ...Object.entries(PJA)].map(([k, v]) => {
              const n = k === "all" ? todays.length : todays.filter((p) => p.platform === k).length;
              return <button key={k} className={filter === k ? "on" : ""} onClick={() => { setFilter(k); setOpenKey(null); }}>{v} {n}</button>;
            })}
          </div>
          {posts === null && <div className="empty">読み込み中…</div>}
          {posts && !shown.length && <div className="empty">今日の投稿予定はありません。{filter === "all" && <button className="link" onClick={() => onTab("calendar")}>予定を見る</button>}</div>}
          {shown.map((p) => (
            <PostItem key={p.path} post={p} now={now} open={curOpen === p.path} notify={notify} onChanged={changed} onOpenWeek={onOpenWeek}
                      onToggle={() => setOpenKey(curOpen === p.path ? "" : p.path)} />
          ))}
        </section>

        <div className="t-side">
          <section className="card">
            <div className="card-head"><h3>② 社長の判断待ち</h3><span className="muted small">{decisions}件</span></div>
            <div className="t-legend"><span className="tlg stop">止まっている</span><span className="tlg wait">待っている</span><span className="tlg run">進んでいる</span><span className="tlg ok">終わった</span></div>
            {rules.map((r) => <div key={r.id} className="t-row" onClick={() => onRule(r)}><span className="chip2 c-wait">ルール案</span><span className="t-row-t">{r.rule}</span><span className="go">確認 ›</span></div>)}
            {contentWaiting.map((w) => <div key={w.week} className="t-row" onClick={() => onOpenWeek(w.week)}><span className="chip2 c-wait">承認待ち</span><span className="t-row-t">{w.week} の投稿セット({w.counts["承認待ち"]}件)</span><span className="go">中身を見る ›</span></div>)}
            {approvals.map((t) => <div key={t.key} className="t-row" onClick={() => onApprove(t)}><span className="chip2 c-wait">承認待ち</span><span className="t-row-t">{t.id} {t.title}</span><span className="go">確認 ›</span></div>)}
            {running.slice(0, 3).map((j) => <div key={j.id} className="t-row" onClick={() => onTab("jobs")}><span className="chip2 c-run">作業中</span><span className="t-row-t">{j.department_full || j.department + "部"}:{j.title}</span><span className="go">見る ›</span></div>)}
            {!decisions && !running.length && <div className="empty">いま判断が必要なものはありません。</div>}
          </section>
          <Yesterday metrics={summary.metrics} jobs={jobs} revenue={rev} />
        </div>
      </div>

      <section className="card t-week" aria-label="今週の流れ">
        {WEEK.map(([, d, l], i) => <div key={d} className={`wd ${i < weekIdx ? "done" : ""} ${i === weekIdx ? "now" : ""}`}><div className="dot" />{d} {l}</div>)}
      </section>

      {children}
    </div>
  );
}
