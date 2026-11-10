import { createPortal } from "react-dom";
import React, { useState } from "react";
import { StatusBadge } from "./Workspace.jsx";

/** 承認カード。承認・差し戻しの確定は社長のこの操作(または「はい」「差し戻し、〜」の声)だけで行う */
export default function ApprovalCard({ task, busy, onDecide, onClose, onOpenDoc }) {
  const [rejecting, setRejecting] = useState(false);
  const [comment, setComment] = useState("");
  const docId = (() => {
    const m = (task.link || "").toLowerCase().match(/[0-9a-f]{32}|[0-9a-f-]{36}/g);
    return m && /notion\./.test(task.link) ? m[m.length - 1].replace(/-/g, "") : null;
  })();
  return createPortal(
    <div className="modal-back" onClick={onClose}>
      <div className="modal approval-card" role="dialog" aria-label="承認の確認" onClick={(e) => e.stopPropagation()}>
        <div className="ac-label">社長の判断</div>
        <div className="ac-title"><span className="tid">{task.id}</span>{task.title}</div>
        <div className="ac-meta">
          <StatusBadge status={task.status} /><span>担当:{task.assignee || "—"}</span><span>期限:{task.due || "—"}</span>
        </div>
        {task.note && <p className="ac-note">{task.note}</p>}
        {(docId || task.link) && (
          <div className="ac-links">
            {docId ? <button className="btn sm" onClick={() => onOpenDoc(docId)}>資料を読む</button>
                   : <a className="btn sm" href={task.link} target="_blank" rel="noreferrer">資料を開く</a>}
          </div>
        )}
        {task.status !== "承認待ち" && (
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
        ) : (
          <div className="ac-actions">
            <button className="btn ghost" onClick={onClose}>あとで</button>
            <button className="btn" disabled={busy} onClick={() => setRejecting(true)}>差し戻す</button>
            <button className="btn primary" disabled={busy} onClick={() => onDecide("approve", "")}>承認する</button>
          </div>
        )}
        <div className="ac-voice">🎙 声でも決められます:「はい」で承認 /「差し戻し、〇〇を直して」/「あとで」</div>
      </div>
    </div>
  , document.body);
}
