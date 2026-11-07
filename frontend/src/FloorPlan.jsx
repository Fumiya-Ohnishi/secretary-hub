import React, { useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { getKnowledge } from "./api.js";

/* フロア図(平面): いま会社がどう動いているかを確かめる画面
 * ・部屋ごとの看板(状態・今の仕事・進み具合・止まっている)
 * ・仕事の流れ(企画→ライティング→デザイン→品質管理→秘書室)。動いている区間を書類が流れる
 * ・社員を押すと名刺(性格・今していること・実績・この部署に頼む) */

const ORDER = ["秘書室", "経営戦略部", "収益化部", "企画編集部", "ライティング部", "デザイン部", "画像制作部", "映像制作部",
  "SNS運用部", "品質管理部", "データ分析部"];
const FLOW = ["企画編集部", "ライティング部", "デザイン部", "品質管理部", "秘書室"];
const COLORS = { 秘書室: "#9aa0f5", 経営戦略部: "#5aa7e8", 収益化部: "#e8b84e", 企画編集部: "#e58a5e", ライティング部: "#c690de", デザイン部: "#ec7fa3",
  画像制作部: "#4fc7b2", 映像制作部: "#8090f2", SNS運用部: "#4bb6e6", 品質管理部: "#e86e6e", データ分析部: "#7cc977" };
const hash = (s) => [...s].reduce((h, c) => (h * 31 + c.charCodeAt(0)) >>> 0, 7);
const AV = ["#8e95f2", "#e86e6e", "#4fc7b2", "#e8b84e", "#c690de", "#4bb6e6", "#7cc977", "#f08aa8"];
const full = (j) => j.department_full || `${j.department}部`;
const cut = (t, n) => (t && t.length > n ? t.slice(0, n) + "…" : t || "");

function deptState(data) {
  const job = {}, stop = {}, day = Date.now() - 864e5;
  for (const j of [...(data.jobs || [])].reverse()) {
    const d = full(j);
    if (j.status === "running") {
      const acts = j.activity || [];
      job[d] = { title: j.title, done: acts.filter((a) => a.status === "done").length, total: Math.max(acts.length, 1) };
      delete stop[d];
    } else if (j.status === "error" && new Date(j.finished || j.started).getTime() > day) stop[d] = { title: j.title, why: (j.output || "").includes("制限時間") ? "制限時間" : "" };
    else if (j.status === "done") delete stop[d];
  }
  return { job, stop };
}

function records(data) {
  const rec = {};
  for (const j of data.jobs || []) for (const a of j.activity || []) {
    const r = (rec[a.agent] = rec[a.agent] || { done: 0, err: 0, last: null });
    if (a.status === "done") r.done++; if (a.status === "error") r.err++;
    if (!r.last || (a.started || "") > (r.last.started || "")) r.last = { desc: a.desc, started: a.started };
  }
  return rec;
}

function NameCard({ m, dept, st, rec, onClose, onOpenDept }) {
  const r = rec || { done: 0, err: 0 };
  const rate = r.done + r.err ? Math.round((r.err / (r.done + r.err)) * 100) : 0;
  return (
    <div className="office-card" role="dialog" aria-label={`${m.title}の名刺`}>
      <button className="office-card-x" onClick={onClose} aria-label="閉じる">×</button>
      <div className="oc-top"><div className="oc-ph" style={{ background: COLORS[dept] || "#8e95f2" }}>{(m.title || "?").slice(0, 1)}</div>
        <div><div className="oc-nm">{m.title}{m.boss ? "(上司)" : ""}</div><div className="oc-rl">{dept} ・ {m.name}</div></div></div>
      {m.persona && <div className="oc-pers">性格:{m.persona}</div>}
      <div className="oc-now">いま:<b className={st?.state === "working" ? "on" : ""}>{st?.state === "working" ? st.desc : "待機中"}</b>{st?.job && <div className="muted small">作業:{st.job}</div>}</div>
      <div className="oc-kp"><div><b>{r.done}</b><span>終えた担当</span></div><div><b>{r.err}</b><span>止まった</span></div><div><b>{rate}%</b><span>止まった割合</span></div></div>
      {r.last && <div className="muted small oc-last">最近:{r.last.desc}</div>}
      <div className="oc-btns"><button className="btn sm primary" onClick={() => onOpenDept(dept)}>この部署に頼む</button></div>
      {m.description && <div className="muted small oc-desc">{m.description}</div>}
    </div>
  );
}

export default function FloorPlan({ data, onOpenDept, focusName, onOpenLibrary }) {
  const [lib, setLib] = useState(null);
  useEffect(() => { getKnowledge().then(setLib).catch(() => {}); }, []);
  const [card, setCard] = useState(focusName || null);
  const wrap = useRef(null), refs = useRef({});
  const [pts, setPts] = useState([]);
  const { job, stop } = useMemo(() => deptState(data), [data]);
  const rec = useMemo(() => records(data), [data]);
  const depts = ORDER.filter((d) => data.departments[d]).concat(Object.keys(data.departments).filter((d) => !ORDER.includes(d)));
  const info = Object.fromEntries(depts.flatMap((d) => data.departments[d].map((m) => [m.name, { m, d }])));

  // 流れの線: 部屋の中心をつなぐ(画面の大きさが変わったら測り直す)
  useLayoutEffect(() => {
    const measure = () => {
      const box = wrap.current?.getBoundingClientRect(); if (!box) return;
      setPts(FLOW.map((d) => { const r = refs.current[d]?.getBoundingClientRect(); return r ? { d, x: r.left - box.left + r.width / 2, y: r.top - box.top + r.height / 2 } : null; }));
    };
    measure();
    const ro = new ResizeObserver(measure); if (wrap.current) ro.observe(wrap.current);
    return () => ro.disconnect();
  }, [depts.length]);

  const counts = { run: 0, stop: 0, idle: 0 };
  depts.forEach((d) => { const s = job[d] ? "run" : stop[d] ? "stop" : (data.departments[d].some((m) => data.members[m.name]?.state === "working") ? "run" : "idle"); counts[s]++; });
  const sel = card && info[card];

  return (
    <div className="floor-wrap" ref={wrap}>
      <div className="fp-stat">
        <span><i className="dot run" />作業中 <b>{counts.run}</b></span>
        <span><i className="dot stop" />止まっている <b>{counts.stop}</b></span>
        <span><i className="dot idle" />待機 <b>{counts.idle}</b></span>
        <span className="muted small">部屋を押すと部署の画面 ・ 社員を押すと名刺</span>
      </div>
      <svg className="fp-flow" width="100%" height="100%" aria-hidden="true">
        <defs><marker id="fp-ar" markerWidth="8" markerHeight="8" refX="6" refY="3" orient="auto"><path d="M0,0 L6,3 L0,6" fill="var(--accent)" /></marker></defs>
        {pts.slice(0, -1).map((a, i) => {
          const b = pts[i + 1]; if (!a || !b) return null;
          const live = job[a.d] || job[b.d];
          const d = `M${a.x},${a.y} L${b.x},${b.y}`;
          return (
            <g key={i} className={live ? "live" : ""}>
              <path d={d} className="fp-line" markerEnd="url(#fp-ar)" />
              {live && <rect className="fp-doc" width="14" height="18" x="-7" y="-9" rx="2"><animateMotion dur="2.6s" repeatCount="indefinite" path={d} /></rect>}
            </g>
          );
        })}
      </svg>
      <div className="fp-grid">
        {depts.map((d) => {
          const ms = data.departments[d], j = job[d], s = stop[d];
          const working = ms.filter((m) => data.members[m.name]?.state === "working");
          const state = j || working.length ? "run" : s ? "stop" : "idle";
          return (
            <section key={d} ref={(el) => (refs.current[d] = el)} className={`fp-room ${state}`} style={{ "--rc": COLORS[d] || "#8e95f2" }}>
              <button className="fp-sign" onClick={() => onOpenDept(d)} title="部署の画面を開く">
                <span className="fp-n">{d}<em className={`fp-st ${state}`}>{{ run: "作業中", stop: "止まっています", idle: "待機" }[state]}</em></span>
                <span className="fp-w">{j ? j.title : s ? `${s.title}${s.why ? "(制限時間)" : ""}` : working.length ? working[0].title + "が作業中" : "待機中"}</span>
                {j && <span className="fp-prog"><i style={{ width: `${Math.max(8, (j.done / j.total) * 100)}%` }} /></span>}
              </button>
              <div className="fp-desks">
                {ms.map((m) => {
                  const st = data.members[m.name], on = st?.state === "working";
                  return (
                    <button key={m.name} className={`fp-seat ${on ? "on" : ""} ${card === m.name ? "sel" : ""}`} onClick={() => setCard(m.name)} title={`${m.title}${on ? `:${st.desc}` : ""}`}>
                      <span className="fp-desk" />
                      <span className="fp-av" style={{ background: AV[hash(m.name) % AV.length] }}>{m.boss ? "★" : m.title.slice(0, 1)}</span>
                      {on && <span className="fp-bub">{cut(st.desc, 12)}</span>}
                    </button>
                  );
                })}
              </div>
            </section>
          );
        })}
        {lib && (
          <section className="fp-room lib" style={{ "--rc": "#c9a77c" }}>
            <button className="fp-sign" onClick={onOpenLibrary} title="資料室を開く">
              <span className="fp-n">資料室<em className={`fp-st ${lib.prefs.pending.length ? "stop" : "idle"}`}>{lib.prefs.pending.length ? `確認待ち ${lib.prefs.pending.length}` : "知見の棚"}</em></span>
              <span className="fp-w">作業の前に、ここで過去の失敗と社長の好みを確認</span>
            </button>
            <button className="fp-shelves" onClick={onOpenLibrary}>
              {lib.shelves.map((s) => <span key={s.key} className="fp-book"><i style={{ height: `${Math.min(100, 20 + s.count)}%` }} /><em>{s.name}</em><b>{s.count}</b></span>)}
            </button>
            {lib.recent_lessons[0] && <div className="fp-lib-new muted small">最新:{cut(lib.recent_lessons[0], 46)}</div>}
          </section>
        )}
      </div>
      {sel && <NameCard m={sel.m} dept={sel.d} st={data.members[card]} rec={rec[card]} onClose={() => setCard(null)} onOpenDept={onOpenDept} />}
    </div>
  );
}
