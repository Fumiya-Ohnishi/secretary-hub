import React, { useEffect, useRef, useState } from "react";

/**
 * AI会社のオフィス(斜め上から見たフロア)。
 * - 部署ごとの部屋に、社員(.claude/agents)の机とアバターを置く
 * - 実際に作業中の社員(秘書ハブの作業ログ)だけが机に座って画面が点き、吹き出しに作業内容が出る
 * - 作業が始まると机へ歩き、終わると書類が上司の机へ飛ぶ。待機中の社員はときどきラウンジへ行って戻る
 * - アバターを押すと、その部署の詳細(依頼画面)を開く
 */
const TW = 56, TH = 28; // 1マスの幅・高さ(画面の点)
const K = 1.45; // 人・机の小物の大きさ(全体に対して)
const LAYOUT = [
  ["秘書室", 0, 0, 6, 6], ["経営戦略部", 7, 0, 6, 6], ["収益化部", 14, 0, 7, 6], ["企画編集部", 22, 0, 6, 6],
  ["ライティング部", 0, 7, 6, 6], ["デザイン部", 7, 7, 6, 6], ["画像制作部", 14, 7, 7, 6], ["映像制作部", 22, 7, 6, 6],
  ["SNS運用部", 0, 14, 9, 6], ["品質管理部", 10, 14, 7, 6], ["データ分析部", 18, 14, 5, 6], ["ラウンジ", 24, 14, 4, 6],
];
const COLORS = {
  秘書室: "#8e95f2", 経営戦略部: "#5aa7e8", 収益化部: "#e0b04c", 企画編集部: "#d9805a", ライティング部: "#c78bd6", デザイン部: "#e2779a",
  画像制作部: "#58c4b0", 映像制作部: "#7d8cf0", SNS運用部: "#55b4e0", 品質管理部: "#e06a6a", データ分析部: "#7fc77a", ラウンジ: "#9aa3c7",
};
const HAIR = ["#2b2f45", "#4a3426", "#1d1d28", "#6b4b2e", "#3b3f63", "#5a2f35"];
const SPEED = 2.4; // マス/秒

const iso = (gx, gy) => ({ x: (gx - gy) * TW / 2, y: (gx + gy) * TH / 2 });
const hash = (s) => [...s].reduce((h, c) => (h * 31 + c.charCodeAt(0)) >>> 0, 7);
const shade = (hex, f) => {
  const n = parseInt(hex.slice(1), 16);
  const c = [n >> 16, (n >> 8) & 255, n & 255].map((v) => Math.max(0, Math.min(255, Math.round(v * f))));
  return `rgb(${c[0]},${c[1]},${c[2]})`;
};

function layoutDesks(departments) {
  const desks = {}; // name -> {gx, gy, dept, boss}
  for (const [dept, x, y, w] of LAYOUT) {
    const members = departments[dept] || [];
    const boss = members.filter((m) => m.boss), staff = members.filter((m) => !m.boss);
    boss.forEach((m, i) => { desks[m.name] = { gx: x + 1.2 + i * 2, gy: y + 1.6, dept, boss: true }; });
    const cols = Math.max(1, Math.floor((w - 1) / 2));
    staff.forEach((m, k) => {
      desks[m.name] = { gx: x + 1.2 + (k % cols) * 2, gy: y + 3.6 + Math.floor(k / cols) * 2, dept, boss: false };
    });
  }
  return desks;
}

const LOUNGE_SPOTS = [[25, 16.2], [26.2, 16.4], [25.4, 18.4], [26.6, 18.2], [24.8, 17.3]];

export default function Office({ data, onOpenDept }) {
  const wrap = useRef(null), cvs = useRef(null);
  const state = useRef({ avatars: {}, flyers: [], cam: { s: 1, x: 0, y: 0 }, hover: null, prev: {}, drag: null, fitted: false });
  const [hover, setHover] = useState(null);
  const dataRef = useRef(data);
  dataRef.current = data;

  // 作業ログの変化を、歩く・座る・書類を渡す動きに変える
  useEffect(() => {
    const S = state.current, desks = layoutDesks(data.departments);
    S.desks = desks;
    const titleOf = {}, deptBoss = {};
    for (const [d, ms] of Object.entries(data.departments)) for (const m of ms) { titleOf[m.name] = m.title; if (m.boss) deptBoss[d] = m.name; }
    S.titleOf = titleOf;
    for (const [name, dk] of Object.entries(desks)) {
      const st = data.members[name];
      const working = st?.state === "working";
      let a = S.avatars[name];
      if (!a) {
        a = S.avatars[name] = { name, dept: dk.dept, boss: dk.boss, gx: dk.gx, gy: dk.gy - 0.55, path: [], wait: 5 + (hash(name) % 30),
                                hair: HAIR[hash(name) % HAIR.length], phase: (hash(name) % 100) / 10 };
      }
      const was = S.prev[name];
      if (working && was !== "working") a.path = [[dk.gx, dk.gy - 0.55]]; // 作業が始まったら机へ
      if (!working && was === "working") { // 終わったら書類を上司(上司なら秘書室)へ
        const to = desks[dk.boss ? deptBoss["秘書室"] : deptBoss[dk.dept]] || null;
        if (to && to !== dk) S.flyers.push({ from: [dk.gx + 0.3, dk.gy], to: [to.gx + 0.3, to.gy], t: 0 });
      }
      a.working = working;
      a.desc = st?.desc || "";
      S.prev[name] = st?.state;
    }
  }, [data]);

  // 描く
  useEffect(() => {
    const S = state.current, canvas = cvs.current, ctx = canvas.getContext("2d");
    let raf, last = performance.now();
    const resize = () => {
      const r = wrap.current.getBoundingClientRect(), dpr = window.devicePixelRatio || 1;
      canvas.width = r.width * dpr; canvas.height = r.height * dpr;
      canvas.style.width = r.width + "px"; canvas.style.height = r.height + "px";
      if (!S.fitted || S.lastW !== r.width) { // 全体が収まる大きさに
        const left = iso(0, 20).x, right = iso(28, 0).x, top = iso(0, 0).y, bottom = iso(28, 20).y;
        const s = Math.min(r.width / (right - left + 60), r.height / (bottom - top + 110));
        S.cam = { s, x: r.width / 2 - ((left + right) / 2) * s, y: 70 - top * s };
        S.fitted = true; S.lastW = r.width;
      }
    };
    resize();
    S.refit = () => { S.fitted = false; resize(); };
    const ro = new ResizeObserver(resize); ro.observe(wrap.current);

    const P = (gx, gy) => { const p = iso(gx, gy); return { x: p.x * S.cam.s + S.cam.x, y: p.y * S.cam.s + S.cam.y }; };
    const poly = (pts, fill, stroke) => {
      ctx.beginPath(); pts.forEach((p, i) => (i ? ctx.lineTo(p.x, p.y) : ctx.moveTo(p.x, p.y))); ctx.closePath();
      if (fill) { ctx.fillStyle = fill; ctx.fill(); }
      if (stroke) { ctx.strokeStyle = stroke; ctx.stroke(); }
    };
    const box = (gx, gy, w, d, h, color) => { // 直方体(上・左・右の面)
      const z = h * S.cam.s;
      const a = P(gx, gy), b = P(gx + w, gy), c = P(gx + w, gy + d), e = P(gx, gy + d);
      const up = (p) => ({ x: p.x, y: p.y - z });
      poly([e, c, up(c), up(e)], shade(color, 0.62));
      poly([c, b, up(b), up(c)], shade(color, 0.78));
      poly([up(a), up(b), up(c), up(e)], color);
    };
    const label = (text, x, y, bg, fg = "#fff", size = 11) => {
      ctx.font = `700 ${size * Math.max(0.85, S.cam.s)}px "Noto Sans JP", sans-serif`;
      const w = ctx.measureText(text).width + 16 * Math.max(0.85, S.cam.s), h = (size + 9) * Math.max(0.85, S.cam.s);
      ctx.fillStyle = bg; ctx.beginPath(); ctx.roundRect(x - w / 2, y - h / 2, w, h, h / 2); ctx.fill();
      ctx.fillStyle = fg; ctx.textAlign = "center"; ctx.textBaseline = "middle"; ctx.fillText(text, x, y + 0.5);
      return { w, h };
    };

    const step = (dt, now) => {
      const D = dataRef.current, desks = S.desks || {};
      for (const a of Object.values(S.avatars)) {
        const dk = desks[a.name];
        if (!dk) continue;
        if (a.path.length) { // 歩く
          const [tx, ty] = a.path[0], dx = tx - a.gx, dy = ty - a.gy, dist = Math.hypot(dx, dy);
          const mv = SPEED * dt;
          if (dist <= mv || dist < 1e-6) { a.gx = tx; a.gy = ty; a.path.shift(); if (!a.path.length) a.wait = a.atDesk ? 20 + Math.random() * 40 : 6 + Math.random() * 10; }
          else { a.gx += (dx / dist) * mv; a.gy += (dy / dist) * mv; }
          a.walking = true;
        } else {
          a.walking = false;
          a.atDesk = Math.hypot(a.gx - dk.gx, a.gy - (dk.gy - 0.55)) < 0.05;
          if (!a.working) {
            a.wait -= dt;
            if (a.wait <= 0) { // 待機中: ときどきラウンジへ行って戻る
              if (a.atDesk && Math.random() < 0.35) {
                const [lx, ly] = LOUNGE_SPOTS[Math.floor(Math.random() * LOUNGE_SPOTS.length)];
                a.path = [[a.gx, 13.5], [lx, 13.5], [lx, ly]]; a.atDesk = false;
              } else if (!a.atDesk) {
                a.path = [[a.gx, 13.5], [dk.gx, 13.5], [dk.gx, dk.gy - 0.55]]; a.atDesk = true;
              } else a.wait = 15 + Math.random() * 30;
            }
          }
        }
      }
      S.flyers = S.flyers.filter((f) => (f.t += dt / 1.4) < 1);
    };

    const draw = (now) => {
      const D = dataRef.current, desks = S.desks || {};
      const W = canvas.width, H = canvas.height, dpr = window.devicePixelRatio || 1;
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      ctx.clearRect(0, 0, W, H);
      // 床
      poly([P(-0.6, -0.6), P(28.6, -0.6), P(28.6, 20.6), P(-0.6, 20.6)], "#121731");
      const base = [P(-0.6, 20.6), P(28.6, 20.6), P(28.6, -0.6)];
      poly([base[0], base[1], { x: base[1].x, y: base[1].y + 10 * S.cam.s }, { x: base[0].x, y: base[0].y + 10 * S.cam.s }], "#0b0f22");
      poly([base[1], base[2], { x: base[2].x, y: base[2].y + 10 * S.cam.s }, { x: base[1].x, y: base[1].y + 10 * S.cam.s }], "#0e1328");
      // 部屋
      const busyDept = {};
      for (const a of Object.values(S.avatars)) if (a.working) busyDept[a.dept] = (busyDept[a.dept] || 0) + 1;
      for (const [dept, x, y, w, h] of LAYOUT) {
        const c = COLORS[dept], busy = busyDept[dept];
        poly([P(x, y), P(x + w, y), P(x + w, y + h), P(x, y + h)], shade(c, busy ? 0.32 : 0.22), shade(c, busy ? 0.9 : 0.5));
        ctx.save(); ctx.globalAlpha = 0.18; ctx.strokeStyle = c; ctx.lineWidth = 1;
        for (let i = 1; i < w; i++) { ctx.beginPath(); const p = P(x + i, y), q = P(x + i, y + h); ctx.moveTo(p.x, p.y); ctx.lineTo(q.x, q.y); ctx.stroke(); }
        for (let j = 1; j < h; j++) { ctx.beginPath(); const p = P(x, y + j), q = P(x + w, y + j); ctx.moveTo(p.x, p.y); ctx.lineTo(q.x, q.y); ctx.stroke(); }
        ctx.restore();
        // 奥の低い壁
        const z = 14 * S.cam.s;
        const a0 = P(x, y), b0 = P(x + w, y), e0 = P(x, y + h);
        poly([a0, b0, { x: b0.x, y: b0.y - z }, { x: a0.x, y: a0.y - z }], shade(c, 0.42));
        poly([a0, e0, { x: e0.x, y: e0.y - z }, { x: a0.x, y: a0.y - z }], shade(c, 0.34));
      }
      // 物(机・ラウンジ・アバター)を奥から順に
      const items = [];
      for (const [name, dk] of Object.entries(desks)) items.push({ k: dk.gx + dk.gy, kind: "desk", name, dk });
      items.push({ k: 24.6 + 18.9, kind: "sofa" }, { k: 25.6 + 15.2, kind: "kitchen" }, { k: 27 + 19.4, kind: "plant", gx: 27.2, gy: 19.2 },
                 { k: 6.4 + 0.4, kind: "plant", gx: 6.3, gy: 0.4 }, { k: 13.4 + 13.4, kind: "plant", gx: 13.4, gy: 13.4 }, { k: 21.4 + 6.4, kind: "plant", gx: 21.4, gy: 6.4 });
      for (const a of Object.values(S.avatars)) items.push({ k: a.gx + a.gy + 0.01, kind: "av", a });
      items.sort((p, q) => p.k - q.k);
      const bubbles = [];
      const t = now / 1000;
      S.hit = [];
      for (const it of items) {
        if (it.kind === "desk") {
          const { gx, gy, boss, dept } = it.dk, on = S.avatars[it.name]?.working;
          box(gx - 0.1, gy - 0.25, boss ? 1.5 : 1.2, 0.7, 12 * K, boss ? "#5a4a3a" : "#3b4470");
          const m = P(gx + (boss ? 0.55 : 0.4), gy - 0.15), s = S.cam.s * K; // 画面(裏側がこちら向き)
          ctx.fillStyle = "#1a1f3a"; ctx.fillRect(m.x - 9 * s, m.y - 30 * s, 18 * s, 13 * s);
          if (on) { ctx.fillStyle = shade(COLORS[dept], 1.15); ctx.globalAlpha = 0.55 + 0.25 * Math.sin(t * 6); ctx.fillRect(m.x - 10 * s, m.y - 31 * s, 20 * s, 2 * s); ctx.globalAlpha = 1; }
          ctx.fillStyle = "#2a3050"; ctx.fillRect(m.x - 1.5 * s, m.y - 17 * s, 3 * s, 5 * s);
        } else if (it.kind === "sofa") {
          box(24.4, 18.6, 2.8, 0.9, 9, "#4b5a7a"); box(24.4, 18.6, 2.8, 0.25, 16, "#56668a");
        } else if (it.kind === "kitchen") {
          box(24.4, 14.4, 3.2, 0.7, 16, "#6a5a48"); const p = P(25.2, 14.6); ctx.fillStyle = "#c9a26b"; ctx.beginPath(); ctx.arc(p.x, p.y - 18 * S.cam.s, 3 * S.cam.s, 0, 7); ctx.fill();
        } else if (it.kind === "plant") {
          const p = P(it.gx, it.gy), s = S.cam.s * K;
          ctx.fillStyle = "#6b4f3a"; ctx.fillRect(p.x - 5 * s, p.y - 8 * s, 10 * s, 8 * s);
          ctx.fillStyle = "#3f8a5a"; ctx.beginPath(); ctx.arc(p.x, p.y - 15 * s, 9 * s, 0, 7); ctx.fill();
          ctx.fillStyle = "#4fa36b"; ctx.beginPath(); ctx.arc(p.x + 3 * s, p.y - 19 * s, 6 * s, 0, 7); ctx.fill();
        } else {
          const a = it.a, p = P(a.gx, a.gy), s = S.cam.s * K, c = COLORS[a.dept];
          const bob = a.walking ? Math.abs(Math.sin(t * 9 + a.phase)) * 3 * s : (a.working ? Math.sin(t * 12 + a.phase) * 0.6 * s : Math.sin(t * 1.5 + a.phase) * 0.8 * s);
          const y0 = p.y - bob, hov = S.hover === a.name;
          ctx.fillStyle = "rgba(0,0,0,.35)"; ctx.beginPath(); ctx.ellipse(p.x, p.y, 8 * s, 3.5 * s, 0, 0, 7); ctx.fill();
          if (a.walking) { // 脚
            const sw = Math.sin(t * 9 + a.phase) * 3 * s;
            ctx.strokeStyle = "#20253f"; ctx.lineWidth = 3 * s; ctx.lineCap = "round";
            ctx.beginPath(); ctx.moveTo(p.x - 2.5 * s, y0 - 9 * s); ctx.lineTo(p.x - 2.5 * s + sw, p.y - 1 * s); ctx.stroke();
            ctx.beginPath(); ctx.moveTo(p.x + 2.5 * s, y0 - 9 * s); ctx.lineTo(p.x + 2.5 * s - sw, p.y - 1 * s); ctx.stroke();
          }
          ctx.fillStyle = hov ? shade(c, 1.2) : c; ctx.beginPath(); ctx.roundRect(p.x - 7 * s, y0 - 25 * s, 14 * s, 17 * s, 6 * s); ctx.fill();
          if (a.boss) { ctx.fillStyle = "#f3d27a"; ctx.font = `${9 * s}px sans-serif`; ctx.textAlign = "center"; ctx.fillText("★", p.x, y0 - 13 * s); }
          ctx.fillStyle = "#f2d6c2"; ctx.beginPath(); ctx.arc(p.x, y0 - 31 * s, 7 * s, 0, 7); ctx.fill();
          ctx.fillStyle = a.hair; ctx.beginPath(); ctx.arc(p.x, y0 - 32.5 * s, 7.3 * s, Math.PI * 1.02, Math.PI * 1.98); ctx.fill();
          if (a.working && !a.walking) bubbles.push({ a, x: p.x, y: y0 - 44 * s });
          S.hit.push({ name: a.name, dept: a.dept, x: p.x, y: y0 - 20 * s, r: 16 * s });
        }
      }
      // 書類が飛ぶ
      for (const f of S.flyers) {
        const a = P(...f.from), b = P(...f.to), u = f.t;
        const x = a.x + (b.x - a.x) * u, y = a.y + (b.y - a.y) * u - Math.sin(u * Math.PI) * 60 * S.cam.s - 30 * S.cam.s;
        ctx.fillStyle = "#fff"; ctx.save(); ctx.translate(x, y); ctx.rotate(Math.sin(u * 8) * 0.3);
        ctx.fillRect(-6 * S.cam.s, -8 * S.cam.s, 12 * S.cam.s, 16 * S.cam.s); ctx.fillStyle = "#8e95f2";
        ctx.fillRect(-4 * S.cam.s, -5 * S.cam.s, 8 * S.cam.s, 1.5 * S.cam.s); ctx.fillRect(-4 * S.cam.s, -1 * S.cam.s, 8 * S.cam.s, 1.5 * S.cam.s); ctx.restore();
      }
      // 部屋の名札
      for (const [dept, x, y] of LAYOUT) {
        const p = P(x + 0.2, y + 0.2), n = busyDept[dept];
        label(n ? `${dept} ・ 作業中 ${n}` : dept, p.x, p.y - 26 * S.cam.s, n ? COLORS[dept] : "rgba(20,25,50,.85)", n ? "#0b0e1a" : "#c9cde8", 12);
      }
      // 吹き出し(作業内容)
      for (const b of bubbles) {
        const txt = (S.titleOf?.[b.a.name] || "") + ":" + (b.a.desc.length > 16 ? b.a.desc.slice(0, 16) + "…" : b.a.desc) + " " + ".".repeat(1 + (Math.floor(t * 2) % 3));
        label(txt, b.x, b.y, "rgba(255,255,255,.96)", "#161a35", 12);
      }
    };

    const loop = (now) => {
      const dt = Math.max(0, Math.min(0.05, (now - last) / 1000)); last = now;
      step(dt, now); draw(now);
      raf = requestAnimationFrame(loop);
    };
    raf = requestAnimationFrame(loop);
    return () => { cancelAnimationFrame(raf); ro.disconnect(); };
  }, []);

  // 操作: なぞる(社員名)・押す(部署を開く)・ドラッグ(移動)・ホイール(拡大)
  const pick = (e) => {
    const r = cvs.current.getBoundingClientRect(), x = e.clientX - r.left, y = e.clientY - r.top;
    let best = null;
    for (const h of state.current.hit || []) { const d = Math.hypot(h.x - x, h.y - y); if (d < h.r && (!best || d < best.d)) best = { ...h, d }; }
    return best;
  };
  const onMove = (e) => {
    const S = state.current;
    if (S.drag) { S.cam.x += e.clientX - S.drag.x; S.cam.y += e.clientY - S.drag.y; S.drag = { x: e.clientX, y: e.clientY, moved: true }; return; }
    const h = pick(e);
    S.hover = h?.name || null;
    setHover(h ? { ...h, ex: e.clientX - cvs.current.getBoundingClientRect().left, ey: e.clientY - cvs.current.getBoundingClientRect().top } : null);
  };
  const onDown = (e) => { state.current.drag = { x: e.clientX, y: e.clientY, moved: false }; };
  const onUp = (e) => {
    const S = state.current, moved = S.drag?.moved; S.drag = null;
    if (!moved) { const h = pick(e); if (h) onOpenDept(h.dept); }
  };
  const zoom = (f, cx, cy) => {
    const S = state.current, r = cvs.current.getBoundingClientRect();
    cx = cx ?? r.width / 2; cy = cy ?? r.height / 2;
    const s = Math.max(0.4, Math.min(2.5, S.cam.s * f)), k = s / S.cam.s;
    S.cam.x = cx - (cx - S.cam.x) * k; S.cam.y = cy - (cy - S.cam.y) * k; S.cam.s = s;
  };
  const onWheel = (e) => { e.preventDefault(); const r = cvs.current.getBoundingClientRect(); zoom(e.deltaY < 0 ? 1.1 : 0.9, e.clientX - r.left, e.clientY - r.top); };
  useEffect(() => { const c = cvs.current; c.addEventListener("wheel", onWheel, { passive: false }); return () => c.removeEventListener("wheel", onWheel); }, []);

  const st = hover && data.members[hover.name];
  const title = hover && state.current.titleOf?.[hover.name];
  return (
    <div className="office" ref={wrap}>
      <canvas ref={cvs} onMouseMove={onMove} onMouseDown={onDown} onMouseUp={onUp} onMouseLeave={() => { state.current.drag = null; state.current.hover = null; setHover(null); }}
              style={{ cursor: hover ? "pointer" : "grab" }} />
      <div className="office-zoom">
        <button onClick={() => zoom(1.2)}>＋</button><button onClick={() => zoom(1 / 1.2)}>−</button>
        <button onClick={() => state.current.refit?.()}>⌂</button>
      </div>
      {hover && (
        <div className="office-tip" style={{ left: hover.ex + 14, top: hover.ey + 10 }}>
          <strong>{title}</strong><span className="muted small">{hover.dept}</span>
          <div className="small">{st?.state === "working" ? `作業中: ${st.desc}(${st.job})` : st?.desc ? `待機中(最後: ${st.desc})` : "待機中"}</div>
          <div className="muted small">押すと部署の画面を開きます</div>
        </div>
      )}
    </div>
  );
}
