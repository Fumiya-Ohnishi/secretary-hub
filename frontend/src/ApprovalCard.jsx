import { createPortal } from "react-dom";
import React, { useState } from "react";
import { StatusBadge } from "./Workspace.jsx";

/** 承認カード。承認・差し戻しの確定は社長のこの操作(または「はい」「差し戻し、〜」の声)だけで行う */
/** 確認タスクの備考「背景: … / 選択肢: A … / B … / おすすめ: … / 未回答のとき: …」を見出しごとに分ける(2026-11-15 社長「何が聞きたいのか分からない」) */
function parseAsk(note) {
  const keys = ["背景", "選択肢", "おすすめ", "未回答のとき", "資料", "出どころ", "決め方"];
  const out = {};
  let cur = null;
  (note || "").split(/\s+\/\s+/).forEach((part) => {
    const m = part.match(/^([^::]{1,6})[::]\s*(.*)$/);
    if (m && keys.includes(m[1])) { cur = m[1]; out[cur] = m[2]; }
    else if (cur) out[cur] += " / " + part;
  });
  const opts = [];
  const re = /(?:^|\s|\/)\s*([A-D])[\s):):.]\s*([^/]+?)(?=\s*(?:\/\s*[A-D][\s):):.]|$))/g;
  let mm;
  while ((mm = re.exec(out["選択肢"] || ""))) opts.push({ label: mm[1], text: mm[2].trim() });
  const rec = ((out["おすすめ"] || "").match(/^\s*([A-D])\b/) || (out["おすすめ"] || "").match(/([A-D])(?:案|が|に|で|を|。)/) || [])[1] || "";
  return { ...out, opts, rec };
}

export default function ApprovalCard({ task, busy, onDecide, onClose, onOpenDoc }) {
  const ask = task.status === "確認待ち" ? parseAsk(task.note) : null;
  const [other, setOther] = useState(false);
  const [rejecting, setRejecting] = useState(false);
  const [comment, setComment] = useState("");
  const [memo, setMemo] = useState("");  // 承認に添える一言(「B で進めて」など)
  // 備考の「A 〜 / B 〜」から選択肢を拾い、押すだけでコメントに入るようにする
  const choices = [...new Set((((task.title || "") + " " + (task.note || "")).match(/(?:^|[\s/(:。、])([A-D])(?=\s|[:: ])/g) || []).map((x) => x.trim().slice(-1)))];
  const docId = (() => {
    const m = (task.link || "").toLowerCase().match(/[0-9a-f]{32}|[0-9a-f-]{36}/g);
    return m && /notion\./.test(task.link) ? m[m.length - 1].replace(/-/g, "") : null;
  })();
  return createPortal(
    <div className="modal-back" onClick={onClose}>
      <div className="modal approval-card" role="dialog" aria-label="承認の確認" onClick={(e) => e.stopPropagation()}>
        <div className="ac-label">{task.status === "確認待ち" ? "社長への確認" : "社長の判断"}</div>
        <div className="ac-title"><span className="tid">{task.id}</span>{task.title}</div>
        <div className="ac-meta">
          <StatusBadge status={task.status} /><span>担当:{task.assignee || "—"}</span><span>期限:{task.due || "—"}</span>
        </div>
        {ask && (ask.opts.length || ask["背景"]) ? (
          <div className="ac-ask">
            {ask["背景"] && <p className="ac-why"><b>なぜ聞くか</b> {ask["背景"]}</p>}
            {ask.opts.length > 0 && !other && !rejecting && (
              <div className="ac-opts">
                <div className="muted small">選ぶだけで答えになります(部署が続きを進めます)</div>
                {ask.opts.map((o) => (
                  <button key={o.label} className={`btn ac-opt ${o.label === ask.rec ? "primary" : ""}`} disabled={busy}
                          onClick={() => onDecide("approve", `${o.label}(${o.text})`)}>
                    <b>{o.label}</b> {o.text}{o.label === ask.rec ? " ⭐おすすめ" : ""}
                  </button>
                ))}
                <div className="ac-opt-row">
                  <button className="btn sm" onClick={() => setOther(true)}>その他(一言書く)</button>
                  <button className="btn sm" onClick={() => setRejecting(true)}>直してほしい</button>
                  <button className="btn sm ghost" onClick={onClose}>あとで</button>
                </div>
              </div>
            )}
            {ask["未回答のとき"] && <p className="muted small">答えがないとき: {ask["未回答のとき"]}</p>}
          </div>
        ) : (task.note && <p className="ac-note">{task.note}</p>)}
        {task.report && (
          <div className="ac-links"><a className="btn sm" href={task.report} target="_blank" rel="noreferrer">📄 この確認を出した作業の報告</a></div>
        )}
        {(docId || task.link) && (
          <div className="ac-links">
            {docId ? <button className="btn sm" onClick={() => onOpenDoc(docId)}>資料を読む</button>
                   : <a className="btn sm" href={task.link} target="_blank" rel="noreferrer">資料を開く</a>}
          </div>
        )}
        {task.status !== "承認待ち" && task.status !== "確認待ち" && (
          <p className="ac-warn">このタスクは今「{task.status}」です。承認待ちでなくても、社長の判断として記録できます。</p>
        )}
        {rejecting ? (
          <div className="ac-reject">
            <textarea autoFocus value={comment} onChange={(e) => setComment(e.target.value)} placeholder="差し戻しの理由(何を直してほしいか)" />
            <div className="ac-actions">
              <button className="btn ghost" onClick={() => setRejecting(false)}>戻る</button>
              <button className="btn danger" disabled={busy} onClick={() => onDecide("reject", comment)}>差し戻す</button>
            </div>
          </div>
        ) : (ask && ask.opts.length && !other) ? null : (
          <>
            <div className="ac-memo">
              {choices.length > 1 && (
                <div className="ac-choices">
                  <span className="muted small">選んだ案:</span>
                  {choices.map((c) => (
                    <button key={c} className={`chip ${memo.startsWith(c + " ") || memo === c ? "on" : ""}`}
                            onClick={() => setMemo((m) => c + (m.replace(/^[A-D](\s|$)/, "") ? " " + m.replace(/^[A-D](\s|$)/, "") : ""))}>{c}</button>
                  ))}
                </div>
              )}
              <textarea value={memo} onChange={(e) => setMemo(e.target.value)} rows={2}
                        placeholder="コメント(任意)。例: B で進めて/A でいいけど表紙だけ直して" />
            </div>
            <div className="ac-actions">
              <button className="btn ghost" onClick={onClose}>あとで</button>
              <button className="btn" disabled={busy} onClick={() => setRejecting(true)}>差し戻す</button>
              <button className="btn primary" disabled={busy} onClick={() => onDecide("approve", memo.trim())}>{memo.trim() ? "コメントを付けて承認" : "承認する"}</button>
            </div>
          </>
        )}
        <div className="ac-voice">🎙 声でも決められます:「はい」で承認 /「Bで承認」/「差し戻し、〇〇を直して」/「あとで」</div>
      </div>
    </div>
  , document.body);
}
