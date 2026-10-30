import React, { useEffect, useRef, useState } from "react";
import { getHealth, getSummary, sendChat, claudeStatus, addTask } from "./api.js";
import { useSpeechInput, useSpeechOutput } from "./speech.js";

const FACES = {
  normal: "faces/normal.jpg",
  pleased: "faces/pleased.jpg",
  thinking: "faces/thinking.jpg",
  pouty: "faces/pouty.jpg",
};
const MOOD_JA = { normal: "通常", pleased: "上機嫌", thinking: "考え中", pouty: "不機嫌(軽)" };

function Bubble({ role, text }) {
  return <div className={`bubble ${role}`}>{text}</div>;
}

function CompanyPanel({ summary, onRefresh }) {
  if (!summary) return <div className="panel empty">会社データ読込中…</div>;
  const { revenue, tasks, company_found } = summary;
  if (!company_found)
    return (
      <div className="panel empty">
        会社リポジトリ(ai-company)が見つかりません。<br />
        backend/.env の AI_COMPANY_DIR を確認してください。
      </div>
    );
  const approvals = tasks.filter((t) => t.status === "承認待ち");
  const open = tasks.filter((t) => t.status !== "完了");
  return (
    <div className="panel">
      <div className="panel-head">
        <span>会社の状態</span>
        <button className="mini" onClick={onRefresh}>更新</button>
      </div>
      <div className="stat">
        <div className="stat-item">
          <div className="num">¥{revenue.month_total.toLocaleString()}</div>
          <div className="lbl">今月の収益(目標5万)</div>
          <div className="bar"><span style={{ width: `${Math.min(100, revenue.month_total / 50000 * 100)}%` }} /></div>
        </div>
        <div className="stat-item">
          <div className="num">{open.length}<small> 件</small></div>
          <div className="lbl">未完了タスク</div>
        </div>
        <div className="stat-item">
          <div className={`num ${approvals.length ? "warn" : ""}`}>{approvals.length}<small> 件</small></div>
          <div className="lbl">承認待ち</div>
        </div>
      </div>
      {approvals.length > 0 && (
        <div className="approval">
          {approvals.slice(0, 3).map((t) => (
            <div key={t.id} className="approval-row">
              <span>{t.id} {t.title}</span>
              <button className="mini ok" onClick={() => onRefresh()}>承認はNotion/タスク表で</button>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

export default function App() {
  const [log, setLog] = useState([
    { role: "sys", text: "AI秘書ハブ起動。話しかけてください。「企画して」など作業を頼むと、裏でClaude Codeが動きます。" },
  ]);
  const [mood, setMood] = useState("normal");
  const [busy, setBusy] = useState(false);
  const [input, setInput] = useState("");
  const [summary, setSummary] = useState(null);
  const [health, setHealth] = useState(null);
  const logRef = useRef(null);

  const tts = useSpeechOutput();
  const { recording, supported, start: startRec } = useSpeechInput((final, interim) => {
    if (final) submit(final);
    else setInput(interim || "");
  });

  const refresh = async () => {
    try { setSummary(await getSummary()); } catch (e) {}
  };
  useEffect(() => { refresh(); getHealth().then(setHealth).catch(() => {}); }, []);

  useEffect(() => { logRef.current?.scrollTo(0, 1e9); }, [log]);

  const submit = async (text) => {
    if (!text.trim() || busy) return;
    setInput("");
    setLog((l) => [...l, { role: "user", text }]);
    setBusy(true);
    try {
      const res = await sendChat(text);
      setLog((l) => [...l, { role: "ai", text: res.reply }]);
      if (res.mood) setMood(res.mood);
      tts.speak(res.reply);
      if (res.ran_claude) {
        const jobId = res.ran_claude;
        const poll = setInterval(async () => {
          const st = await claudeStatus(jobId);
          if (st.status === "done") {
            clearInterval(poll);
            setLog((l) => [...l, { role: "sys", text: "✅ 部署の作業が完了しました(GitHub/リポジトリを確認)" }]);
            refresh();
          } else if (st.status === "error") {
            clearInterval(poll);
            setLog((l) => [...l, { role: "sys", text: "⚠ 作業エラー: " + (st.output || "").slice(0, 200) }]);
          }
        }, 10000);
      }
      refresh();
    } catch (e) {
      setLog((l) => [...l, { role: "sys", text: "接続エラー: サーバー(localhost:8000)が起動しているか確認してください。" }]);
    }
    setBusy(false);
  };

  return (
    <div className="app">
      <header>
        <div className="title">AI秘書ハブ <small>{health?.api_key_set ? "API接続" : "簡易モード"}</small></div>
        <div className="hright">
          <span className={`dot ${health?.claude_cli ? "ok" : ""}`} title="Claude Code CLIの接続状態" />
          <span className="sub">{health?.claude_cli ? "Claude Code 連携OK" : "Claude Code CLI未接続"}</span>
        </div>
      </header>
      <main>
        <div className="stage">
          <img src={FACES[mood]} alt="秘書" draggable="false" />
          <span className="moodtag">{MOOD_JA[mood]}</span>
          {tts.speaking && <span className="speaking">speaking…</span>}
        </div>
        <div className="right">
          <CompanyPanel summary={summary} onRefresh={refresh} />
          <div className="chat" ref={logRef}>
            {log.map((m, i) => <Bubble key={i} {...m} />)}
          </div>
          <div className="composer">
            <button
              className={`mic ${recording ? "rec" : ""}`}
              onClick={startRec}
              title={supported ? "話しかける" : "このブラウザは音声認識非対応"}
              disabled={!supported}
            >🎙</button>
            <textarea
              value={input}
              placeholder="話しかける / 入力してEnter"
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); submit(input); } }}
            />
            <button className="send" onClick={() => submit(input)} disabled={busy}>送信</button>
          </div>
          <div className="hints">
            <button className="hint-chip" onClick={() => submit("今日の収益を教えて")}>今日の収益は?</button>
            <button className="hint-chip" onClick={() => submit("承認待ちのタスクを教えて")}>承認待ちは?</button>
            <button className="hint-chip" onClick={() => submit("戦略部に今週の企画を頼んで")}>企画を頼む</button>
            {tts.voices.length > 0 && (
              <select value={tts.voiceName} onChange={(e) => tts.setVoiceName(e.target.value)} className="voice-sel">
                {tts.voices.map((v) => <option key={v.name} value={v.name}>{v.name}</option>)}
              </select>
            )}
          </div>
        </div>
      </main>
    </div>
  );
}
