import React, { useEffect, useState } from "react";
import { getContentWeeks, getAccount, getAccounts, addInsight, addImprovement, recordFollowers, markCrossposted, recordRevenue,
         getProposals, addProposal, patchProposal, proposalRevenue, syncStats, registerAccount, addAccountSet, startMeeting } from "./api.js";
import Content, { PostPreview, PostResults } from "./Content.jsx";
import { LineChart, PLATFORM_COLORS } from "./Charts.jsx";

const PLATFORMS = [["instagram", "Instagram"], ["x", "X"], ["threads", "Threads"], ["note", "note"], ["tiktok", "TikTok"], ["youtube", "YouTube"]];
const PJA = Object.fromEntries(PLATFORMS);
const lsGet = (k, d) => { try { return localStorage.getItem(k) || d; } catch (e) { return d; } };
const lsSet = (k, v) => { try { localStorage.setItem(k, v); } catch (e) {} };

/** アカウントごとの管理(2026-11-12 社長: アカウントが増えてもセレクトボックスで選ぶ。どのアカウントも6媒体を並べ、
 *  登録の無い媒体は「利用なし」=投稿を作らない)。請け負い(ランサーズ・ココナラ)は横のボタン */
export default function Accounts({ week, setWeek, onChanged, notify, onSay }) {
  const [acct, setAcct] = useState(() => lsGet("acctSet", "main"));
  const [sel, setSel] = useState(() => lsGet("acct", "all"));
  const [weeks, setWeeks] = useState([]);
  const [sets, setSets] = useState([]);
  const [summary, setSummary] = useState([]);
  const work = acct === "work";
  const pickAcct = (k) => { setAcct(k); lsSet("acctSet", k); };
  const pick = (p) => { setSel(p); lsSet("acct", p); };
  const loadWeeks = () => getContentWeeks().then((r) => setWeeks(r.weeks)).catch(() => {});
  const loadSets = () => getAccounts(work ? "main" : acct).then((r) => {
    setSets(r.sets || []); setSummary(r.accounts || []);
    if (!work && r.sets && !r.sets.some((x) => x.id === acct)) pickAcct("main");
  }).catch((e) => { if (!work) { pickAcct("main"); } notify(e.message, "error"); });
  useEffect(() => { loadWeeks(); }, []);
  useEffect(() => { loadSets(); }, [acct]);
  const waiting = (a, p) => weeks.reduce((n, w) => n + ((w.by_account?.[a]?.[p] || {})["承認待ち"] || 0), 0);
  const changed = () => { loadWeeks(); loadSets(); onChanged(); };
  const cur = sets.find((x) => x.id === acct);
  const reg = (p) => (summary.find((a) => a.platform === p) || {}).registered;
  const platSel = PLATFORMS.some(([k]) => k === sel) ? sel : "all";
  const onSelect = async (v) => {
    if (v !== "__add") return pickAcct(v);
    const label = window.prompt("新しいアカウントの名前(画面に出す名前。例: 別アカウント2)", `別アカウント${sets.length}`);
    if (!label) return;
    const note = window.prompt("ひとこと説明(任意。例: 料理と献立の note)", "") || "";
    try { const r = await addAccountSet(label, note); notify(`「${r.label}」を追加しました。媒体ごとに URL を登録すると使えるようになります`, "ok"); pickAcct(r.id); }
    catch (e) { notify(e.message, "error"); }
  };

  return (
    <div className="accounts-tab">
      <div className="acct-top">
        <label className="acct-select">
          <span className="muted small">アカウント</span>
          <select value={work ? "" : acct} onChange={(e) => onSelect(e.target.value)}>
            {work && <option value="">(選ぶ)</option>}
            {sets.map((x) => <option key={x.id} value={x.id}>{x.label}{waiting(x.id, "all") ? `(承認待ち ${waiting(x.id, "all")})` : ""}</option>)}
            <option value="__add">＋ アカウントを追加…</option>
          </select>
        </label>
        <button className={`btn ${work ? "primary" : ""}`} onClick={() => pickAcct(work ? "main" : "work")}>請け負い(ランサーズ・ココナラ)</button>
      </div>
      {work ? <Proposals notify={notify} onChanged={onChanged} /> : (
        <>
          {cur?.note && <div className="muted small acct-set-note">{cur.note}</div>}
          <div className="acct-switch">
            {[["all", "全部"], ...PLATFORMS].map(([k, label]) => {
              const off = k !== "all" && summary.length > 0 && !reg(k);
              return (
                <button key={k} className={`${platSel === k ? "on" : ""} ${off ? "off" : ""}`} onClick={() => pick(k)}
                        title={off ? "利用なし(URL を登録すると使えます)" : ""}
                        style={platSel === k && k !== "all" ? { borderColor: PLATFORM_COLORS[k], color: PLATFORM_COLORS[k] } : null}>
                  {label}{off ? <span className="off-tag">利用なし</span> : null}
                  {waiting(acct, k) ? <span className="count warn">{waiting(acct, k)}</span> : null}
                </button>
              );
            })}
          </div>
          {platSel === "all"
            ? <Content key={acct} week={week} setWeek={setWeek} onChanged={changed} notify={notify} onSay={onSay} account={acct} />
            : <Account key={acct + platSel} account={acct} platform={platSel} week={week} setWeek={setWeek} onChanged={changed} notify={notify} onSay={onSay} />}
        </>
      )}
    </div>
  );
}

/** 登録の無い媒体: 利用なし。URL を入れて登録する(登録すると次の企画会議の議題に入る) */
function Unregistered({ data, account, platform, notify, onDone }) {
  const [url, setUrl] = useState("");
  const [busy, setBusy] = useState(false);
  const save = async () => {
    setBusy(true);
    try { await registerAccount(platform, url.trim(), account); notify(`${data.account_label}の${data.name}を登録しました。次の企画会議から投稿を作ります`, "ok"); setUrl(""); onDone(); }
    catch (e) { notify(e.message, "error"); }
    setBusy(false);
  };
  return (
    <div className="card unreg">
      <div className="card-head"><h3>{data.account_label}の{data.name}: 利用なし</h3></div>
      <p className="muted small">この媒体はまだ登録されていないので、<b>投稿は作りません</b>(企画会議でも考えません)。アカウントを作ったら、プロフィールの URL を登録してください。登録すると、<b>次の企画会議からこの媒体の投稿を作ります</b>(すぐ始めたいときは、登録のあとに出る「投稿を作る会議を始める」を押してください)。</p>
      <div className="inline-form">
        <input value={url} onChange={(e) => setUrl(e.target.value)} placeholder={`${data.name} のプロフィールの URL(https://…)`} />
        <button className="btn primary" disabled={busy || !/^https:\/\//.test(url.trim())} onClick={save}>登録</button>
      </div>
      <div className="muted small" style={{ marginTop: 6 }}>登録するのは URL だけです。パスワードやログイン情報は入れないでください。</div>
    </div>
  );
}

/** 登録済みの媒体: 投稿を作る臨時会議をすぐ始める */
function StartPostsButton({ data, account, platform, notify }) {
  const [busy, setBusy] = useState(false);
  const go = async () => {
    if (!window.confirm(`${data.account_label}の${data.name}の投稿を作る会議を、今から始めますか?`)) return;
    setBusy(true);
    const topic = `${data.account_label}(account: ${account})の${data.name}(${data.url})の運用を始める。この媒体の運用の型・週の本数・最初の投稿セットを決め、`
      + `投稿ファイル(front matter に account: ${account} と platform: ${platform})を作って品質管理を通し、承認待ちにする。本アカウントとは完全に分ける`;
    try { await startMeeting("adhoc", topic, ["企画編集部", "SNS運用部", "ライティング部", "デザイン部", "映像制作部", "収益化部"]); notify("会議を始めました。終わると議事録とやることが届きます", "ok"); }
    catch (e) { notify(e.message, "error"); }
    setBusy(false);
  };
  return <button className="btn sm" disabled={busy} onClick={go}>{busy ? "始めています…" : "投稿を作る会議を始める"}</button>;
}

function Account({ account = "main", platform, week, setWeek, onChanged, notify, onSay }) {
  const [data, setData] = useState(null);
  const [section, setSection] = useState("posts");
  const load = () => getAccount(platform, account).then(setData).catch((e) => notify(e.message, "error"));
  useEffect(() => { load(); }, [platform, account]);
  if (!data) return <div className="empty">読み込み中…</div>;
  if (!data.registered) return <Unregistered data={data} account={account} platform={platform} notify={notify} onDone={() => { load(); onChanged(); }} />;
  const latest = data.followers_latest;
  const prev = data.followers.length > 1 ? data.followers[data.followers.length - 2] : null;
  const diff = latest && prev ? latest.followers - prev.followers : null;

  return (
    <>
      <div className="card acct-head" style={{ borderTopColor: PLATFORM_COLORS[platform] }}>
        <div>
          <div className="muted small">{data.account_label}</div>
          <h3>{data.name}</h3>
          {data.url ? <a className="muted small" href={data.url} target="_blank" rel="noreferrer">{data.url}</a>
                    : <span className="muted small">URL 未登録(「{account === "sub" ? "別アカウントの" : ""}{data.name}のURLは〜」と話しかけると登録)</span>}
          {account !== "main" && <div style={{ marginTop: 6 }}><StartPostsButton data={data} account={account} platform={platform} notify={notify} /></div>}
        </div>
        <div className="acct-kpi">
          <div className="kpi-num">{latest ? latest.followers.toLocaleString() : "—"}</div>
          <div className="kpi-lbl">フォロワー{latest ? `(${latest.date})` : ""}{diff !== null && <span className={diff >= 0 ? "up" : "down"}> {diff >= 0 ? "+" : ""}{diff}</span>}</div>
        </div>
      </div>
      <div className="seg">
        {[["posts", "投稿"], ["numbers", "数字"], ["revenue", "収益"], ["improve", "改善点"], ["rules", "ルール"]].map(([k, l]) => (
          <button key={k} className={section === k ? "on" : ""} onClick={() => setSection(k)}>
            {l}{k === "improve" && data.improvements.length ? <span className="count">{data.improvements.length}</span> : null}
          </button>
        ))}
      </div>
      {section === "posts" && data.crosspost && (platform === "tiktok" || platform === "youtube") &&
        <Crosspost data={data} platform={platform} notify={notify} onDone={() => { load(); onChanged(); }} />}
      {section === "posts" && !(platform === "tiktok" || platform === "youtube") && <Content week={week} setWeek={setWeek} onChanged={onChanged} notify={notify} onSay={onSay} platform={platform} account={account} />}
      {section === "numbers" && <Numbers data={data} platform={platform} account={account} notify={notify} onDone={() => { load(); onChanged(); }} />}
      {section === "revenue" && <Revenue data={data} notify={notify} onDone={() => { load(); onChanged(); }} />}
      {section === "improve" && <Improvements data={data} platform={platform} account={account} notify={notify} onDone={load} />}
      {section === "rules" && <div className="card"><div className="sec-text">{data.playbook || "ルールはまだありません。"}</div></div>}
    </>
  );
}

const TEXT_COLS = ["content_id", "format", "metric"];
const zeroVals = (cols) => Object.fromEntries((cols || []).filter((c) => !TEXT_COLS.includes(c.key)).map((c) => [c.key, "0"]));

function Numbers({ data, platform, account = "main", notify, onDone }) {
  const [fol, setFol] = useState("");
  // 2026-11-12 社長: 数字は 0 から始め、変えなかった欄は 0 で記録する(投稿ID・形式・項目は空から)
  const [vals, setVals] = useState(() => zeroVals(data.insight_columns));
  const [busy, setBusy] = useState(false);
  const saveFollowers = async () => {
    const n = parseInt(fol, 10);
    if (Number.isNaN(n)) return;
    setBusy(true);
    try { await recordFollowers({ platform, followers: n, account }); notify(`${data.name} のフォロワー ${n}人を記録しました`, "ok"); setFol(""); onDone(); }
    catch (e) { notify(e.message, "error"); }
    setBusy(false);
  };
  const saveInsight = async () => {
    setBusy(true);
    try { await addInsight(platform, vals, undefined, false, account); notify("数字を記録しました", "ok"); setVals(zeroVals(data.insight_columns)); onDone(); }
    catch (e) { notify(e.message, "error"); }
    setBusy(false);
  };
  const series = [{ key: platform, label: data.name, color: PLATFORM_COLORS[platform],
                    points: data.followers.map((p) => ({ date: p.date, value: p.followers })) }];
  return (
    <>
      <AutoStats data={data} platform={platform} account={account} notify={notify} onDone={onDone} />
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
              <input value={vals[c.key] ?? ""} onChange={(e) => setVals({ ...vals, [c.key]: e.target.value })}
                     onFocus={(e) => !TEXT_COLS.includes(c.key) && e.target.select()}
                     inputMode={TEXT_COLS.includes(c.key) ? "text" : "numeric"} /></label>
          ))}
          <button className="btn primary" disabled={busy || !data.insight_columns.some((c) => TEXT_COLS.includes(c.key) && (vals[c.key] || "").trim())} onClick={saveInsight}>記録</button>
        </div>
      </div>
    </>
  );
}

function Improvements({ data, platform, account = "main", notify, onDone }) {
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const save = async () => {
    setBusy(true);
    try { await addImprovement(platform, text, account); notify("改善点を記録しました", "ok"); setText(""); onDone(); }
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

/** TikTok・YouTube に出すとよい投稿(Instagram のリールの流用。SNS運用部のおすすめが上) */
function Crosspost({ data, platform, notify, onDone }) {
  const [view, setView] = useState(null);
  const [busy, setBusy] = useState("");
  const [resultsFor, setResultsFor] = useState("");
  const todo = data.crosspost.filter((p) => !p.posted_on);
  const done = data.crosspost.filter((p) => p.posted_on);
  const mark = async (p) => {
    setBusy(p.path);
    try { await markCrossposted(platform, p.path); notify(`${data.name}に「${p.title}」を投稿済みにしました`, "ok"); onDone(); }
    catch (e) { notify(e.message, "error"); }
    setBusy("");
  };
  const unmark = async (p) => {
    if (!window.confirm(`${data.name}の「${p.title}」の投稿済みを取り消しますか?`)) return;
    setBusy(p.path);
    try { await markCrossposted(platform, p.path, true); notify(`${data.name}の「${p.title}」を未投稿に戻しました`, "ok"); onDone(); }
    catch (e) { notify(e.message, "error"); }
    setBusy("");
  };
  const row = (p) => (<React.Fragment key={p.path}>
    <li className="xp-row">
      <div className="xp-main">
        <div className="xp-title">
          {p.recommended && <span className="badge s-ask">おすすめ</span>}
          <span className="muted small">{p.week}</span> {p.title}
        </div>
        <div className="muted small">{p.reason}{!p.ready && "(まだ承認前。承認されてから出す)"}</div>
      </div>
      <div className="xp-act">
        <button className="btn" onClick={() => setView(p)}>見る</button>
        {p.posted_on ? <><span className="muted small">投稿済み {p.posted_on}</span>
            <button className="btn sm primary" onClick={() => setResultsFor(resultsFor === p.path ? "" : p.path)}>結果</button>
            <button className="btn sm" disabled={busy === p.path} onClick={() => unmark(p)} title="間違えて押したとき">取り消す</button></>
          : <button className="btn primary" disabled={!p.ready || busy === p.path} onClick={() => mark(p)}>投稿した</button>}
      </div>
    </li>
    {resultsFor === p.path && p.posted_on && <li className="xp-results"><PostResults post={p} platform={platform} postedOn={/^\d/.test(p.posted_on) ? p.posted_on : ""} notify={notify} /></li>}
  </React.Fragment>);
  return (
    <div className="card">
      <div className="card-head"><h3>{data.name}に出すとよい投稿</h3><span className="muted small">Instagram のリールをそのまま流用・未投稿が上</span></div>
      {todo.length ? <ul className="xp-list">{todo.map(row)}</ul>
        : <div className="empty">今出せる候補はありません。リールが承認されるか、SNS運用部がおすすめを付けるとここに出ます。</div>}
      {done.length > 0 && <details className="xp-done"><summary className="muted small">投稿済み {done.length}件</summary><ul className="xp-list">{done.map(row)}</ul></details>}
      <div className="muted small" style={{ marginTop: 8 }}>
        {platform === "tiktok" ? "AI生成コンテンツの表示は、欄があればオン(無ければ動画とキャプションの表示でよい)"
          : "「改変または合成されたコンテンツ」は「はい」"}。動画の中とキャプションの「AIで作ったキャラクター」の表示は消さない。
      </div>
      {view && <PostPreview post={view} onClose={() => setView(null)} />}
    </div>
  );
}

const yen = (n) => `${Number(n || 0).toLocaleString()}円`;
const today = () => new Date().toISOString().slice(0, 10);

/** その媒体の確定した収益を入れる(2026-11-12 社長: 収益が確定したら入力できる仕組み) */
function Revenue({ data, notify, onDone }) {
  const rv = data.revenue || { rows: [] };
  const [amount, setAmount] = useState("");
  const [date, setDate] = useState(today());
  const [memo, setMemo] = useState("");
  const [busy, setBusy] = useState(false);
  const save = async () => {
    const n = parseInt(amount.replace(/[^0-9]/g, ""), 10);
    if (!n) return;
    if (!window.confirm(`${rv.source_ja} に ${yen(n)}(${date})を記録します。確定した金額ですか?`)) return;
    setBusy(true);
    try { await recordRevenue({ amount: n, source: rv.source, date, memo }); notify(`${rv.source_ja} ${yen(n)} を記録しました`, "ok"); setAmount(""); setMemo(""); onDone(); }
    catch (e) { notify(e.message, "error"); }
    setBusy(false);
  };
  return (
    <div className="card">
      <div className="card-head"><h3>収益({rv.source_ja})</h3>
        <span className="muted small">今月 {yen(rv.month_total)} ・ 合計 {yen(rv.all_total)}</span></div>
      {rv.rows.length ? (
        <div className="table-wrap"><table className="tbl">
          <thead><tr><th>日付</th><th>金額</th><th>メモ</th></tr></thead>
          <tbody>{rv.rows.map((r, i) => <tr key={i}><td>{r.date}</td><td>{yen(r.amount)}</td><td>{r.memo}</td></tr>)}</tbody>
        </table></div>
      ) : <div className="empty">まだ記録がありません。売上が確定したら(note の売上管理・各アプリの収益の画面で確かめてから)下に入れてください。</div>}
      <div className="insight-form">
        <label><span>確定した日</span><input type="date" value={date} onChange={(e) => setDate(e.target.value)} /></label>
        <label><span>金額(円)</span><input inputMode="numeric" value={amount} placeholder="例 500" onChange={(e) => setAmount(e.target.value.replace(/[^0-9]/g, ""))} /></label>
        <label className="wide"><span>メモ</span><input value={memo} placeholder="例 有料記事「大掃除の段取り表」2件" onChange={(e) => setMemo(e.target.value)} /></label>
        <button className="btn primary" disabled={busy || !amount} onClick={save}>収益を記録</button>
      </div>
      <div className="muted small">記録すると、会社の収益(data/revenue.csv)と Notion の収益にも入ります。手数料を引いた後の金額か前の金額かは、メモに書いてください。</div>
    </div>
  );
}

const P_STATUS_CLASS = { "提案した": "s-todo", "やりとり中": "s-doing", "採用": "s-ok", "不採用": "s-ng", "納品した": "s-ask", "入金済み": "s-done" };

/** 請け負いの提案と入金(ランサーズ・ココナラ。2026-11-12 社長) */
function Proposals({ notify, onChanged }) {
  const [service, setService] = useState(() => lsGet("propSvc", "lancers"));
  const [data, setData] = useState(null);
  const [form, setForm] = useState({ title: "", url: "", amount: "", memo: "" });
  const [busy, setBusy] = useState("");
  const load = () => getProposals(service).then(setData).catch((e) => notify(e.message, "error"));
  useEffect(() => { load(); }, [service]);
  const pickSvc = (k) => { setService(k); lsSet("propSvc", k); };
  const add = async () => {
    setBusy("add");
    try { const r = await addProposal({ service, ...form }); notify(`${r.id}「${r.title}」を記録しました`, "ok"); setForm({ title: "", url: "", amount: "", memo: "" }); load(); }
    catch (e) { notify(e.message, "error"); }
    setBusy("");
  };
  const setStatus = async (r, status) => {
    setBusy(r.id);
    try { await patchProposal(r.id, { status }); load(); }
    catch (e) { notify(e.message, "error"); }
    setBusy("");
  };
  const toRevenue = async (r) => {
    const v = window.prompt(`${r.id}「${r.title}」の入金が確定した金額(円)`, r.amount || "");
    if (v === null) return;
    setBusy(r.id);
    try { const x = await proposalRevenue(r.id, v.replace(/[^0-9]/g, "")); notify(`${yen(x.revenue.amount)} を収益(${data.services.find((s) => s.id === r.service)?.label})に入れました`, "ok"); load(); onChanged(); }
    catch (e) { notify(e.message, "error"); }
    setBusy("");
  };
  if (!data) return <div className="empty">読み込み中…</div>;
  const sm = data.summary;
  return (
    <>
      <div className="acct-switch">
        {data.services.map((s) => <button key={s.id} className={service === s.id ? "on" : ""} onClick={() => pickSvc(s.id)}>{s.label}</button>)}
      </div>
      <div className="card">
        <div className="prop-kpis">
          <div><div className="kpi-num">{sm.proposals}</div><div className="kpi-lbl">提案数(今月 {sm.this_month})</div></div>
          <div><div className="kpi-num">{sm.won}</div><div className="kpi-lbl">採用</div></div>
          <div><div className="kpi-num">{sm.win_rate === null ? "—" : `${sm.win_rate}%`}</div><div className="kpi-lbl">採用率(決まったものの中)</div></div>
          <div><div className="kpi-num">{yen(sm.paid_total)}</div><div className="kpi-lbl">入金済み</div></div>
          <div><div className="kpi-num">{yen(sm.expected_total)}</div><div className="kpi-lbl">入金待ち(採用・納品)</div></div>
        </div>
      </div>
      <div className="card">
        <div className="card-head"><h3>提案した案件を記録</h3><span className="muted small">応募を送ったら入れる</span></div>
        <div className="insight-form">
          <label className="wide"><span>案件名</span><input value={form.title} placeholder="例 会議の議事録の整形(5本)" onChange={(e) => setForm({ ...form, title: e.target.value })} /></label>
          <label className="wide"><span>案件のURL</span><input value={form.url} placeholder="https://www.lancers.jp/work/detail/..." onChange={(e) => setForm({ ...form, url: e.target.value })} /></label>
          <label><span>提案した金額(円)</span><input inputMode="numeric" value={form.amount} onChange={(e) => setForm({ ...form, amount: e.target.value.replace(/[^0-9]/g, "") })} /></label>
          <label className="wide"><span>メモ</span><input value={form.memo} placeholder="例 納期3日・応募文は案A" onChange={(e) => setForm({ ...form, memo: e.target.value })} /></label>
          <button className="btn primary" disabled={busy === "add" || !form.title.trim()} onClick={add}>記録</button>
        </div>
      </div>
      <div className="card">
        <div className="card-head"><h3>提案した案件</h3><span className="muted small">新しい順・状態を押して変える</span></div>
        {data.rows.length ? (
          <ul className="prop-list">{data.rows.map((r) => (
            <li key={r.id} className="prop-row">
              <div className="prop-main">
                <div><span className={`badge ${P_STATUS_CLASS[r.status] || ""}`}>{r.status}</span> <span className="muted small">{r.id} ・ {r.date}</span></div>
                <div className="prop-title">{r.url ? <a href={r.url} target="_blank" rel="noreferrer">{r.title}</a> : r.title}</div>
                <div className="muted small">{r.amount ? yen(r.amount) : "金額未入力"}{r.memo ? ` ・ ${r.memo}` : ""}{r.revenue_date ? ` ・ 収益に記録済み(${r.revenue_date})` : ""}</div>
              </div>
              <div className="prop-act">
                <select value={r.status} disabled={busy === r.id} onChange={(e) => setStatus(r, e.target.value)}>
                  {data.statuses.map((s) => <option key={s}>{s}</option>)}
                </select>
                {!r.revenue_date && ["採用", "納品した", "入金済み"].includes(r.status) &&
                  <button className="btn sm primary" disabled={busy === r.id} onClick={() => toRevenue(r)}>入金を収益に入れる</button>}
              </div>
            </li>
          ))}</ul>
        ) : <div className="empty">まだありません。応募を送ったら、上で記録してください。</div>}
        <div className="muted small" style={{ marginTop: 8 }}>当社はサービスにログインしません。応募・やりとり・納品は社長が行い、結果をここに入れてください。</div>
      </div>
    </>
  );
}

/** 公式の仕組み(API)で自動で取った数字(2026-11-12 社長: つないだアカウントは自動で数字を取りたい) */
function AutoStats({ data, platform, account, notify, onDone }) {
  const a = data.auto || {};
  const [busy, setBusy] = useState(false);
  if (!a.supported) {
    return <div className="card auto-card"><div className="muted small">
      {data.name} は公式の無料の仕組みで数字を自動では取れません(X は有料の API、note・TikTok は公開の API がありません)。下の欄に入力してください。
    </div></div>;
  }
  const run = async () => {
    setBusy(true);
    try { const r = await syncStats(`${account}:${platform}`); const v = r[`${account}:${platform}`] || {}; notify(v.ok ? `取得しました: ${v.detail}` : `取れませんでした: ${v.detail}`, v.ok ? "ok" : "error"); onDone(); }
    catch (e) { notify(e.message, "error"); }
    setBusy(false);
  };
  const st = a.status || {};
  return (
    <div className="card auto-card">
      <div className="card-head"><h3>自動で取った数字({data.name} 公式)</h3>
        <span className="muted small">{a.connected ? (st.at ? `前回 ${st.at.slice(5, 16).replace("T", " ")}・毎朝 8:00 に自動` : "つないであります・毎朝 8:00 に自動") : "未接続"}</span>
        {a.connected && <button className="btn sm" disabled={busy} onClick={run}>{busy ? "取得中…" : "今すぐ取る"}</button>}</div>
      {!a.connected ? (
        <div className="empty">まだつないでいません。会社のフォルダの <b>playbooks/account_connect.md</b>(アカウント連携マニュアル)の手順でつなぐと、フォロワー数と投稿ごとの閲覧数などを毎朝自動で記録します。</div>
      ) : (
        <>
          {st.ok === false && st.detail && <div className="warn-box small">前回は取れませんでした: {st.detail}</div>}
          {a.rows.length ? (
            <div className="table-wrap"><table className="tbl">
              <thead><tr><th>投稿日</th><th>種類</th><th>投稿</th>{a.columns.map((c) => <th key={c.key}>{c.label}</th>)}<th>取った日</th></tr></thead>
              <tbody>{a.rows.map((r) => (
                <tr key={r.media_id}>
                  <td>{r.posted_at}</td><td>{r.kind}</td>
                  <td className="auto-cap">{r.url ? <a href={r.url} target="_blank" rel="noreferrer">{(r.caption || "(本文なし)").slice(0, 24)}</a> : (r.caption || "").slice(0, 24)}{r.content_id ? <span className="muted small"> {r.content_id}</span> : null}</td>
                  {a.columns.map((c) => <td key={c.key}>{r[c.key] === "" || r[c.key] == null ? "—" : Number(r[c.key]).toLocaleString()}</td>)}
                  <td className="muted small">{r.date}</td>
                </tr>
              ))}</tbody>
            </table></div>
          ) : <div className="empty">まだ取っていません。「今すぐ取る」を押すか、次の 8:00 をお待ちください。</div>}
          <div className="muted small" style={{ marginTop: 6 }}>「—」はその投稿では公式に取れない数字です。投稿日が同じ当社の投稿が1つだけなら、投稿IDを横に出します。</div>
        </>
      )}
    </div>
  );
}
