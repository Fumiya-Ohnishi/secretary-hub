import React, { useCallback, useEffect, useRef, useState } from "react";
import { getHealth, getSummary, sendChat, decideTask } from "./api.js";
import { useSpeechInput, useSpeechOutput } from "./speech.js";
import Live2DStage from "./Live2DStage.jsx";
import Workspace from "./Workspace.jsx";
import ApprovalCard from "./ApprovalCard.jsx";

const FACES = { normal: "faces/normal.jpg", pleased: "faces/pleased.jpg", thinking: "faces/thinking.jpg", pouty: "faces/pouty.jpg" };
const FATAL_MIC = ["not-allowed", "service-not-allowed", "network", "audio-capture"];
const PANEL_TABS = ["home", "tasks", "docs", "jobs", "chat"];

function load(key, fallback) {
  try { const v = localStorage.getItem(key); return v == null ? fallback : JSON.parse(v); } catch (e) { return fallback; }
}
function save(key, value) {
  try { localStorage.setItem(key, JSON.stringify(value)); } catch (e) {}
}

/** 秘書のセリフを1文字ずつ表示する */
function Typewriter({ text }) {
  const [n, setN] = useState(0);
  useEffect(() => {
    setN(0);
    if (!text) return;
    const id = setInterval(() => setN((v) => (v >= text.length ? (clearInterval(id), v) : v + 1)), 28);
    return () => clearInterval(id);
  }, [text]);
  return <>{text.slice(0, n)}<span className="caret" style={{ opacity: n < text.length ? 1 : 0 }} /></>;
}

function greeting(summary, name) {
  const h = new Date().getHours();
  const hello = h < 11 ? "おはようございます" : h < 18 ? "お疲れさまです" : "こんばんは";
  if (!summary) return `${hello}、社長。${name}です。`;
  const appr = summary.tasks.filter((t) => t.status === "承認待ち").length;
  const today = new Date().toISOString().slice(0, 10);
  const late = summary.tasks.filter((t) => t.due && t.due.slice(0, 10) < today && !["完了", "承認済み"].includes(t.status)).length;
  const parts = [`今月の収益は${summary.revenue.month_total.toLocaleString()}円です`];
  parts.push(appr ? `承認待ちが${appr}件あります` : "承認待ちはありません");
  if (late) parts.push(`期限切れが${late}件です`);
  return `${hello}、社長。${parts.join("、")}。ご用件をどうぞ。`;
}

export default function App() {
  const [log, setLog] = useState([]);
  const [line, setLine] = useState("");
  const [mood, setMood] = useState("normal");
  const [busy, setBusy] = useState(false);
  const [input, setInput] = useState("");
  const [heard, setHeard] = useState("");
  const [summary, setSummary] = useState(null);
  const [jobs, setJobs] = useState([]);
  const [health, setHealth] = useState(null);
  const [tab, setTab] = useState("home");
  const [taskFilter, setTaskFilter] = useState("未完了");
  const [docId, setDocId] = useState(null);
  const [focusTask, setFocusTask] = useState(null);
  const [approval, setApproval] = useState(null);
  const [deciding, setDeciding] = useState(false);
  const [handsFree, setHandsFree] = useState(() => load("hub-handsfree", false));
  const [muted, setMuted] = useState(() => load("hub-muted", false));
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [toasts, setToasts] = useState([]);
  const [live2dFailed, setLive2dFailed] = useState(false);
  const logRef = useRef(null);
  const jobsRef = useRef([]);
  const submitRef = useRef(null);

  const tts = useSpeechOutput();
  const name = health?.secretary || "セナ";

  const notify = useCallback((text, kind = "info") => {
    const id = Math.random();
    setToasts((t) => [...t, { id, text, kind }]);
    setTimeout(() => setToasts((t) => t.filter((x) => x.id !== id)), 4500);
  }, []);

  const say = useCallback((text, m = "normal", speakIt = true) => {
    setLine(text);
    setMood(m);
    setLog((l) => [...l, { role: "ai", text }]);
    if (speakIt && !load("hub-muted", false)) tts.speak(text);
  }, [tts]);

  const { recording, supported, unsupportedReason, start: startRec, stop: stopRec } = useSpeechInput(
    (final, interim) => {
      if (final) { setHeard(""); submitRef.current?.(final); }
      else setHeard(interim || "");
    },
    (msg, code) => {
      setHeard("");
      if (FATAL_MIC.includes(code)) { setHandsFree(false); save("hub-handsfree", false); }
      if (msg) notify("🎙 " + msg, "error");
    },
  );

  /* ---------- 会社データの取得と、部署の作業の完了通知 ---------- */
  const refresh = useCallback(async () => {
    try {
      const s = await getSummary();
      setSummary(s);
      const prev = jobsRef.current;
      for (const j of s.jobs || []) {
        const before = prev.find((p) => p.id === j.id);
        if (before && before.status === "running" && j.status !== "running") {
          const ok = j.status === "done";
          notify(`${j.department}部「${j.title}」${ok ? "完了" : "エラー"}`, ok ? "ok" : "error");
          say(ok ? `社長、${j.department}部から「${j.title}」の作業が終わったと報告がありました。作業タブで結果を確認できます。`
                 : `${j.department}部の「${j.title}」でエラーが出ました。作業タブに内容を出しています。`, ok ? "pleased" : "thinking");
        }
      }
      jobsRef.current = s.jobs || [];
      setJobs(s.jobs || []);
      return s;
    } catch (e) { return null; }
  }, [notify, say]);

  useEffect(() => {
    getHealth().then(setHealth).catch(() => setHealth({ offline: true }));
    refresh().then((s) => {
      const g = greeting(s, name);
      setLine(g);
      setLog([{ role: "ai", text: g }]);
    });
  }, []);

  const running = jobs.some((j) => j.status === "running");
  useEffect(() => {
    const id = setInterval(refresh, running ? 6000 : 30000);
    return () => clearInterval(id);
  }, [running, refresh]);

  useEffect(() => { logRef.current?.scrollTo(0, 1e9); }, [log, tab]);

  /* ---------- 承認・差し戻し(社長の操作) ---------- */
  const decide = async (decision, comment) => {
    if (!approval) return;
    setDeciding(true);
    try {
      const t = await decideTask(approval.key, decision, comment);
      setApproval(null);
      notify(`${t.id} を${decision === "approve" ? "承認しました" : "差し戻しました"}`, "ok");
      say(decision === "approve" ? `${t.id}、承認を記録しました。進めます。` : `${t.id}を差し戻しました。直して再提出します。`,
          decision === "approve" ? "pleased" : "normal");
      refresh();
    } catch (e) { notify(e.message, "error"); }
    setDeciding(false);
  };

  /* ---------- 話しかける ---------- */
  const handleActions = (actions = []) => {
    for (const a of actions) {
      if (a.type === "show_panel" && PANEL_TABS.includes(a.panel)) setTab(a.panel);
      if (a.type === "open_doc") { setDocId(a.id); setTab("docs"); }
      if (a.type === "approval") setApproval(a.task);
      if (a.type === "job") setTab("jobs");
    }
    if (actions.some((a) => ["refresh", "job", "approval"].includes(a.type))) refresh();
  };

  const submit = async (raw) => {
    const text = (raw || "").trim();
    if (!text || busy) return;
    setInput("");
    // 承認カードが出ているときは、声の返事で確定できる(AI は介さず、社長の言葉で直接決める)
    if (approval) {
      setLog((l) => [...l, { role: "user", text }]);
      if (/差し?戻/.test(text)) return decide("reject", text.replace(/^.*?差し?戻し?て?(ください)?[、。,\s]*/, ""));
      if (/^(はい|承認|ok|オッケー|オーケー|お願いします|いいよ|いいです|大丈夫)/i.test(text)) return decide("approve", "");
      if (/(あとで|後で|キャンセル|やめ|保留)/.test(text)) { setApproval(null); return say("承知しました。あとで確認できるようにしておきます。"); }
    }
    const history = log.filter((m) => m.role !== "sys").slice(-16);
    setLog((l) => [...l, { role: "user", text }]);
    setBusy(true);
    setMood("thinking");
    try {
      const res = await sendChat(text, history);
      say(res.reply, res.mood || "normal");
      handleActions(res.actions);
    } catch (e) {
      say("サーバーに接続できません。秘書ハブ(run_mac.command)が起動しているか確認してください。", "normal", false);
    }
    setBusy(false);
  };
  submitRef.current = submit;

  /* ---------- ハンズフリー: 話し終わったら自動で聞き取りを再開 ---------- */
  useEffect(() => {
    if (!handsFree || !supported || tts.speaking || busy || recording || deciding) return;
    const id = setTimeout(startRec, 700);
    return () => clearTimeout(id);
  }, [handsFree, supported, tts.speaking, busy, recording, deciding]);

  const toggleHandsFree = () => {
    const v = !handsFree;
    setHandsFree(v);
    save("hub-handsfree", v);
    if (!v) stopRec();
    notify(v ? "ハンズフリー: 話しかけるだけで会話が続きます" : "ハンズフリーを止めました");
  };
  const toggleMute = () => { const v = !muted; setMuted(v); save("hub-muted", v); if (v) tts.stop(); };
  const micClick = () => {
    if (tts.speaking) tts.stop();
    if (recording) stopRec(); else startRec();
  };

  const appr = summary ? summary.tasks.filter((t) => t.status === "承認待ち").length : 0;
  const pills = [
    { label: health?.api_key_set ? "頭脳 OK" : "簡易モード", ok: !!health?.api_key_set, title: health?.api_key_set ? `Claude API(${health.model})` : "backend/.env に ANTHROPIC_API_KEY を入れると何でも頼めます" },
    { label: health?.notion ? "Notion 接続" : "Notion 未接続", ok: !!health?.notion, title: health?.notion ? "タスクと資料を Notion と同期中" : "資料タブに接続手順があります" },
    { label: health?.claude_cli ? "部署 OK" : "部署 未接続", ok: !!health?.claude_cli, title: "部署の作業は Claude Code(claude コマンド)で動きます" },
    { label: tts.engine === "voicevox" ? "VOICEVOX" : "ブラウザの声", ok: tts.engine === "voicevox", title: "VOICEVOX を起動すると自然な声になります" },
  ];

  const status = recording ? "listening" : busy ? "thinking" : tts.speaking ? "speaking" : "idle";
  const statusText = { listening: "聞いています…", thinking: "考えています…", speaking: "話しています", idle: handsFree ? "待機中(話しかけてください)" : "" }[status];

  return (
    <div className="app">
      <header className="topbar">
        <div className="brand">
          <span className="logo">◆</span>
          <div><div className="brand-name">AI会社 秘書室</div><div className="brand-sub">{new Date().toLocaleDateString("ja-JP", { month: "long", day: "numeric", weekday: "short" })}</div></div>
        </div>
        <div className="pills">
          {pills.map((p) => <span key={p.label} className={`pill ${p.ok ? "ok" : ""}`} title={p.title}><i />{p.label}</span>)}
        </div>
        <div className="settings-wrap">
          <button className="icon-btn" onClick={() => setSettingsOpen(!settingsOpen)} aria-label="設定">⚙</button>
          {settingsOpen && (
            <div className="settings" onMouseLeave={() => setSettingsOpen(false)}>
              <label className="set-row"><span>読み上げ</span><input type="checkbox" checked={!muted} onChange={toggleMute} /></label>
              <label className="set-row"><span>ハンズフリー</span><input type="checkbox" checked={handsFree} onChange={toggleHandsFree} disabled={!supported} /></label>
              {tts.voices.length > 0 && (
                <label className="set-col"><span>声({tts.engine === "voicevox" ? "VOICEVOX" : "ブラウザ"})</span>
                  <select value={tts.voiceValue} onChange={(e) => tts.setVoice(e.target.value)}>
                    {tts.voices.map((v) => <option key={v.value} value={v.value}>{v.label}</option>)}
                  </select>
                </label>
              )}
              {!supported && <p className="muted small">{unsupportedReason}</p>}
            </div>
          )}
        </div>
      </header>

      <main className="layout">
        <section className={`stage-col ${status}`}>
          <div className="stage">
            <div className="stage-bg" />
            {live2dFailed
              ? <img className="still" src={FACES[mood]} alt={name} draggable="false" />
              : <Live2DStage mood={mood} speaking={tts.speaking} levelRef={tts.levelRef} onError={() => setLive2dFailed(true)} />}
            <div className="nameplate"><span className="np-name">{name}</span><span className="np-role">統括秘書</span></div>
            {statusText && <div className={`state-chip ${status}`}><i />{statusText}</div>}
            <div className="dialogue" onClick={() => setTab("chat")}>
              {heard ? <div className="heard">「{heard}」</div>
                : busy ? <div className="dots"><span /><span /><span /></div>
                : <Typewriter text={line} />}
            </div>
          </div>

          <div className="composer">
            <button className={`mic ${recording ? "rec" : ""}`} onClick={micClick} disabled={!supported}
                    title={supported ? "押して話す" : unsupportedReason} aria-label="話しかける">
              <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 15a3 3 0 0 0 3-3V6a3 3 0 1 0-6 0v6a3 3 0 0 0 3 3Zm5-3a5 5 0 0 1-10 0H5a7 7 0 0 0 6 6.92V21h2v-2.08A7 7 0 0 0 19 12h-2Z" /></svg>
            </button>
            <input value={input} placeholder={`${name}に話しかける / 入力して Enter`}
                   onChange={(e) => setInput(e.target.value)}
                   onKeyDown={(e) => { if (e.key === "Enter" && !e.nativeEvent.isComposing) { e.preventDefault(); submit(input); } }} />
            <button className="send" onClick={() => submit(input)} disabled={busy || !input.trim()} aria-label="送信">↑</button>
            <button className={`hf ${handsFree ? "on" : ""}`} onClick={toggleHandsFree} disabled={!supported}
                    title="ハンズフリー: 話しかけるだけで会話が続きます">{handsFree ? "ハンズフリー中" : "ハンズフリー"}</button>
          </div>
          <div className="quick">
            <button onClick={() => submit("今日の報告をして")}>今日の報告</button>
            <button onClick={() => submit("承認待ちを見せて")}>承認待ち{appr ? `(${appr})` : ""}</button>
            <button onClick={() => submit("資料の一覧を見せて")}>資料</button>
          </div>
        </section>

        <Workspace tab={tab} setTab={setTab} summary={summary} jobs={jobs} health={health} log={log} logRef={logRef}
                   taskFilter={taskFilter} setTaskFilter={setTaskFilter} docId={docId} setDocId={setDocId}
                   focusTask={focusTask} setFocusTask={setFocusTask} onApprove={setApproval} onSay={submit}
                   refresh={refresh} notify={notify} />
      </main>

      {approval && (
        <ApprovalCard task={approval} busy={deciding} onDecide={decide} onClose={() => setApproval(null)}
                      onOpenDoc={(id) => { setDocId(id); setTab("docs"); setApproval(null); }} />
      )}
      <div className="toasts">{toasts.map((t) => <div key={t.id} className={`toast ${t.kind}`}>{t.text}</div>)}</div>
    </div>
  );
}
