import React, { useEffect, useState } from "react";
import { getContentWeeks, getAccount, addInsight, addImprovement, recordFollowers } from "./api.js";
import Content from "./Content.jsx";
import { LineChart, PLATFORM_COLORS } from "./Charts.jsx";

const PLATFORMS = [["instagram", "Instagram"], ["x", "X"], ["threads", "Threads"], ["note", "note"]];

/** アカウントごとの管理。「全部」は4媒体の投稿をまとめて承認、各媒体は投稿・数字・改善点・ルールを1か所に */
export default function Accounts({ week, setWeek, onChanged, notify, onSay }) {
  const [sel, setSel] = useState(() => { try { return localStorage.getItem("acct") || "all"; } catch (e) { return "all"; } });
  const [weeks, setWeeks] = useState([]);
  const pick = (p) => { setSel(p); try { localStorage.setItem("acct", p); } catch (e) {} };
  const loadWeeks = () => getContentWeeks().then((r) => setWeeks(r.weeks)).catch(() => {});
  useEffect(() => { loadWeeks(); }, []);
  const waiting = (p) => weeks.reduce((n, w) => n + ((p === "all" ? w.counts : (w.by_platform?.[p] || {}))["承認待ち"] || 0), 0);
  const changed = () => { loadWeeks(); onChanged(); };

  return (
    <div className="accounts-tab">
      <div className="acct-switch">
        {[["all", "全部"], ...PLATFORMS].map(([k, label]) => (
          <button key={k} className={sel === k ? "on" : ""} onClick={() => pick(k)}
                  style={sel === k && k !== "all" ? { borderColor: PLATFORM_COLORS[k], color: PLATFORM_COLORS[k] } : null}>
            {label}{waiting(k) ? <span className="count warn">{waiting(k)}</span> : null}
          </button>
        ))}
      </div>
      {sel === "all"
        ? <Content week={week} setWeek={setWeek} onChanged={changed} notify={notify} onSay={onSay} />
        : <Account key={sel} platform={sel} week={week} setWeek={setWeek} onChanged={changed} notify={notify} onSay={onSay} />}
    </div>
  );
}

function Account({ platform, week, setWeek, onChanged, notify, onSay }) {
  const [data, setData] = useState(null);
  const [section, setSection] = useState("posts");
  const load = () => getAccount(platform).then(setData).catch((e) => notify(e.message, "error"));
  useEffect(() => { load(); }, [platform]);
  if (!data) return <div className="empty">読み込み中…</div>;
  const latest = data.followers_latest;
  const prev = data.followers.length > 1 ? data.followers[data.followers.length - 2] : null;
  const diff = latest && prev ? latest.followers - prev.followers : null;

  return (
    <>
      <div className="card acct-head" style={{ borderTopColor: PLATFORM_COLORS[platform] }}>
        <div>
          <div className="muted small">アカウント</div>
          <h3>{data.name}</h3>
          {data.url ? <a className="muted small" href={data.url} target="_blank" rel="noreferrer">{data.url}</a>
                    : <span className="muted small">URL 未登録(「{data.name}のURLは〜」と話しかけると登録)</span>}
        </div>
        <div className="acct-kpi">
          <div className="kpi-num">{latest ? latest.followers.toLocaleString() : "—"}</div>
          <div className="kpi-lbl">フォロワー{latest ? `(${latest.date})` : ""}{diff !== null && <span className={diff >= 0 ? "up" : "down"}> {diff >= 0 ? "+" : ""}{diff}</span>}</div>
        </div>
      </div>
      <div className="seg">
        {[["posts", "投稿"], ["numbers", "数字"], ["improve", "改善点"], ["rules", "ルール"]].map(([k, l]) => (
          <button key={k} className={section === k ? "on" : ""} onClick={() => setSection(k)}>
            {l}{k === "improve" && data.improvements.length ? <span className="count">{data.improvements.length}</span> : null}
          </button>
        ))}
      </div>
      {section === "posts" && <Content week={week} setWeek={setWeek} onChanged={onChanged} notify={notify} onSay={onSay} platform={platform} />}
      {section === "numbers" && <Numbers data={data} platform={platform} notify={notify} onDone={() => { load(); onChanged(); }} />}
      {section === "improve" && <Improvements data={data} platform={platform} notify={notify} onDone={load} />}
      {section === "rules" && <div className="card"><div className="sec-text">{data.playbook || "ルールはまだありません。"}</div></div>}
    </>
  );
}

function Numbers({ data, platform, notify, onDone }) {
  const [fol, setFol] = useState("");
  const [vals, setVals] = useState({});
  const [busy, setBusy] = useState(false);
  const saveFollowers = async () => {
    const n = parseInt(fol, 10);
    if (Number.isNaN(n)) return;
    setBusy(true);
    try { await recordFollowers({ platform, followers: n }); notify(`${data.name} のフォロワー ${n}人を記録しました`, "ok"); setFol(""); onDone(); }
    catch (e) { notify(e.message, "error"); }
    setBusy(false);
  };
  const saveInsight = async () => {
    setBusy(true);
    try { await addInsight(platform, vals); notify("数字を記録しました", "ok"); setVals({}); onDone(); }
    catch (e) { notify(e.message, "error"); }
    setBusy(false);
  };
  const series = [{ key: platform, label: data.name, color: PLATFORM_COLORS[platform],
                    points: data.followers.map((p) => ({ date: p.date, value: p.followers })) }];
  return (
    <>
      <div className="card">
        <div className="card-head"><h3>フォロワー数の推移</h3></div>
        {data.followers.length ? <LineChart series={series} unit="人" />
          : <div className="empty">まだ記録がありません。「{data.name}のフォロワー120人」と話しかけるか、下に入力してください。</div>}
        <div className="inline-form">
          <input inputMode="numeric" value={fol} onChange={(e) => setFol(e.target.value)} placeholder="今日のフォロワー数" />
          <button className="btn" disabled={busy || !fol} onClick={saveFollowers}>記録</button>
        </div>
      </div>
      <div className="card">
        <div className="card-head"><h3>投稿ごとの数字</h3><span className="muted small">新しい順・最大30件</span></div>
        {data.insights.length ? (
          <div className="table-wrap">
            <table className="tbl">
              <thead><tr><th>日付</th>{data.insight_columns.map((c) => <th key={c.key}>{c.label}</th>)}</tr></thead>
              <tbody>{data.insights.map((r, i) => (
                <tr key={i}><td>{r.date}</td>{data.insight_columns.map((c) => <td key={c.key}>{r[c.key]}</td>)}</tr>
              ))}</tbody>
            </table>
          </div>
        ) : <div className="empty">まだ記録がありません。「{data.name}の 2026-46-01、保存30・いいね120」のように話しかけても記録できます。</div>}
        <div className="insight-form">
          {data.insight_columns.map((c) => (
            <label key={c.key}><span>{c.label}</span>
              <input value={vals[c.key] || ""} onChange={(e) => setVals({ ...vals, [c.key]: e.target.value })}
                     inputMode={["content_id", "format", "metric"].includes(c.key) ? "text" : "numeric"} /></label>
          ))}
          <button className="btn primary" disabled={busy || !Object.values(vals).some((v) => v)} onClick={saveInsight}>記録</button>
        </div>
      </div>
    </>
  );
}

function Improvements({ data, platform, notify, onDone }) {
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const save = async () => {
    setBusy(true);
    try { await addImprovement(platform, text); notify("改善点を記録しました", "ok"); setText(""); onDone(); }
    catch (e) { notify(e.message, "error"); }
    setBusy(false);
  };
  return (
    <>
      <div className="card">
        <div className="card-head"><h3>改善点</h3><span className="muted small">金曜の見直し・社長の気づき</span></div>
        {data.improvements.length ? (
          <ul className="improve-list">{data.improvements.map((m, i) => <li key={i}><span className="muted small">{m.date}</span> {m.text}</li>)}</ul>
        ) : <div className="empty">まだありません。金曜の見直しで分析部が書き込みます。</div>}
        <div className="inline-form">
          <input value={text} onChange={(e) => setText(e.target.value)} placeholder="気づいたこと(例: 冒頭1秒に結果を出す)" />
          <button className="btn" disabled={busy || !text.trim()} onClick={save}>記録</button>
        </div>
      </div>
      <div className="card">
        <div className="card-head"><h3>この媒体への差し戻し・指摘</h3><span className="muted small">修正ログより</span></div>
        {data.corrections.length ? (
          <ul className="improve-list">{data.corrections.map((c, i) => (
            <li key={i}><span className="muted small">{c.date} ・ {c.by}</span><div className="small">{c.target}</div><div>{c.text}</div></li>
          ))}</ul>
        ) : <div className="empty">まだありません。</div>}
      </div>
    </>
  );
}
