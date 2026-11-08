import React, { useEffect, useRef, useState } from "react";

/**
 * AI会社のオフィス(斜め上から見たフロア)。
 * - 部署ごとの部屋に、社員(.claude/agents)の机とアバター
 * - 作業中の社員(秘書ハブの実際の作業ログ)だけが机で画面を点け、吹き出しに作業内容を出す
 * - 作業が終わると書類が上司の机へ飛ぶ
 * - 待機中の社員は、コーヒー・ラウンジのソファ・立ち話・同僚の机へ歩いて行き来する
 *   立ち話のセリフは用意したひな形に「いま実際に動いている仕事」の名前を入れて作る(AIは呼ばない=費用ゼロ)
 */
const TW = 56, TH = 28;   // 1マスの幅・高さ
const K = 1.45;           // 人・小物の大きさ
const SPEED = 2.2;        // 歩く速さ(マス/秒)
const GW = 28, GH = 28;   // フロアの広さ(マス)
const ROOMS = [
  // 部署, x, y, 幅, 奥行き, 床
  ["秘書室", 0, 0, 6, 6, "wood"], ["経営戦略部", 7, 0, 6, 6, "carpet"], ["収益化部", 14, 0, 7, 6, "carpet"], ["企画編集部", 22, 0, 6, 6, "wood"],
  ["ライティング部", 0, 7, 6, 6, "carpet"], ["デザイン部", 7, 7, 6, 6, "wood"], ["画像制作部", 14, 7, 7, 6, "carpet"], ["映像制作部", 22, 7, 6, 6, "carpet"],
  ["SNS運用部", 0, 14, 8, 7, "carpet"], ["品質管理部", 9, 14, 7, 7, "wood"], ["データ分析部", 17, 14, 5, 7, "carpet"], ["ラウンジ", 23, 14, 5, 7, "lounge"],
  ["経理・税務部", 0, 22, 8, 6, "wood"], ["広報部", 9, 22, 8, 6, "carpet"], ["人事部", 18, 22, 10, 6, "wood"],
];
const COLORS = {
  秘書室: "#9aa0f5", 経営戦略部: "#5aa7e8", 収益化部: "#e8b84e", 企画編集部: "#e58a5e", ライティング部: "#c690de", デザイン部: "#ec7fa3",
  画像制作部: "#4fc7b2", 映像制作部: "#8090f2", SNS運用部: "#4bb6e6", 品質管理部: "#e86e6e", データ分析部: "#7cc977", ラウンジ: "#c9a77c", 経理・税務部: "#d0b25c", 広報部: "#f08ac0", 人事部: "#6cc3a8",
};
const SKIN = ["#f6dcc8", "#efc9ae", "#e3b591", "#f3d2bd", "#d9a582"];
const HAIR = ["#262a3f", "#4a3426", "#17171f", "#6b4b2e", "#3a3f66", "#8a5a3a", "#5a2f35", "#2f3b2b"];
const STYLES = ["short", "long", "bob", "bun", "spiky"];
const COFFEE = [[24.0, 15.0], [24.7, 15.0]];
const SOFA = [[24.5, 18.05], [25.3, 18.05], [26.1, 18.05], [26.9, 18.05]];
const CHAT = [[[25.0, 19.8], [25.8, 20.1]], [[26.6, 16.4], [27.3, 16.8]], [[13.6, 6.6], [14.4, 6.9]], [[6.5, 13.4], [7.2, 13.7]], [[21.5, 13.5], [22.2, 13.8]]];
const ASK = ["おつかれさまです", "コーヒー、もう1杯いきます?", "次の定時チェック、何時でしたっけ", "社長の判断待ち、今何件?", "差し戻しのログ、見ました?",
  "貼る文は試用記録と同じ文面、ですよね", "金曜の見直し、何を見ます?", "次の企画、どうします?", "その資料、あとで見せてください"];
const ANS = ["おつかれさまです!", "あと1杯だけ…", "9時・12時・17時です", "秘書ハブで見られますよ", "主語の取り違え、気をつけます", "そうそう、そこ大事",
  "保存数と最後まで見た割合ですね", "読者の場面から考えたいです", "あとで共有しますね"];

const iso = (gx, gy) => ({ x: (gx - gy) * TW / 2, y: (gx + gy) * TH / 2 });
const hash = (s) => [...s].reduce((h, c) => (h * 31 + c.charCodeAt(0)) >>> 0, 7);
const pickOne = (arr) => arr[Math.floor(Math.random() * arr.length)];
const shade = (hex, f) => {
  const n = parseInt(hex.slice(1), 16);
  const c = [n >> 16, (n >> 8) & 255, n & 255].map((v) => Math.max(0, Math.min(255, Math.round(v * f))));
  return `rgb(${c[0]},${c[1]},${c[2]})`;
};

function layoutDesks(departments) {
  const desks = {};
  for (const [dept, x, y, w] of ROOMS) {
    const ms = departments[dept] || [];
    const boss = ms.filter((m) => m.boss), staff = ms.filter((m) => !m.boss);
    boss.forEach((m, i) => { desks[m.name] = { gx: x + w - 2.2 - i * 2, gy: y + 1.7, dept, boss: true }; });
    const cols = Math.max(1, Math.floor((w - 1) / 1.9));
    staff.forEach((m, k) => { desks[m.name] = { gx: x + 1.0 + (k % cols) * 1.9, gy: y + 3.7 + Math.floor(k / cols) * 2.0, dept, boss: false }; });
  }
  return desks;
}

/** 立体のオフィス: 働いている風景を眺める画面(文字の看板・流れの線は出さない。詳しい状況はフロア図で見る) */
export default function Office({ data, onOpenDept, onShowFloor }) {
  const wrap = useRef(null), cvs = useRef(null);
  const S = useRef({ avatars: {}, flyers: [], chats: [], cam: { s: 1, x: 0, y: 0 }, prev: {}, hit: [] }).current;
  const [hover, setHover] = useState(null);
  const [nowOpen, setNowOpen] = useState(true);
  const [card, setCard] = useState(null); // 押した社員(名前と今していることだけ出す)
  const [auto, setAuto] = useState(true);   // 自動カメラ
  const [cinema, setCinema] = useState(false); // 全画面(文字を全部消す)
  useEffect(() => { S.auto = auto; }, [auto]);
  useEffect(() => { S.cinema = cinema; }, [cinema]);
  useEffect(() => {
    const fs = () => { if (!document.fullscreenElement) setCinema(false); };
    document.addEventListener("fullscreenchange", fs); return () => document.removeEventListener("fullscreenchange", fs);
  }, []);
  const goCinema = async () => {
    setCinema(true); setAuto(true);
    try { await wrap.current?.requestFullscreen?.(); } catch (e) {}
    setTimeout(() => S.refit?.(), 300);
  };

  function seat(a) { const dk = S.desks[a.name]; return [dk.gx + 0.35, dk.gy - 0.6]; }
  function route(a, to) { // 廊下(y=6.5 / 13.5 / 21.5)を通る。廊下の間は決まった通り道(x)で上下する
    const lv = (y) => (y < 6.5 ? 0 : y < 21.5 ? 1 : 2), LY = [6.5, 13.5, 21.5];
    let li = lv(a.gy), x = a.gx;
    const ti = lv(to[1]);
    const pts = [[x, LY[li]]];
    while (li !== ti) {
      const ni = li + (ti > li ? 1 : -1);
      const cx = Math.min(li, ni) === 0 ? (x < 13 ? 6.5 : 13.5) : 22.5;
      pts.push([cx, LY[li]], [cx, LY[ni]]); li = ni; x = cx;
    }
    pts.push([to[0], LY[ti]], to);
    return pts;
  }
  function endChat(a) {
    S.chats = S.chats.filter((c) => { if (c.a === a || c.b === a) { c.a.say = c.b.say = null; return false; } return true; });
  }
  function goDesk(a) { endChat(a); a.path = route(a, seat(a)); a.act = "desk"; }

  // 作業ログの変化 → 机へ向かう・書類を渡す
  useEffect(() => {
    const desks = layoutDesks(data.departments);
    S.desks = desks;
    const info = {}, deptBoss = {};
    for (const [d, ms] of Object.entries(data.departments)) for (const m of ms) { info[m.name] = m; if (m.boss) deptBoss[d] = m.name; }
    S.info = info;
    S.jobs = (data.jobs || []).filter((j) => j.status === "running").map((j) => j.title);
    // 部署ごとの今の仕事(看板用): 作業中の作業名と進み具合、24時間以内に止まった作業
    const full = (j) => j.department_full || `${j.department}部`;
    const dj = {}, stop = {}, day = Date.now() - 864e5;
    for (const j of [...(data.jobs || [])].reverse()) { // 古い順。あとの作業が上書きする
      const d = full(j);
      if (j.status === "running") {
        const acts = j.activity || [], done = acts.filter((a) => a.status === "done").length;
        dj[d] = { title: j.title, done, total: Math.max(acts.length, 1), started: j.started }; delete stop[d];
      } else if (j.status === "error" && new Date(j.finished || j.started).getTime() > day) stop[d] = j.title;
      else if (j.status === "done") delete stop[d];
    }
    S.deptJob = dj; S.deptStop = stop;
    // 社員ごとの実績(作業の記録から): 担当した数・差し戻し(エラー)の数
    const rec = {};
    for (const j of data.jobs || []) for (const a of j.activity || []) {
      const r = (rec[a.agent] = rec[a.agent] || { done: 0, err: 0, last: null });
      if (a.status === "done") r.done++; if (a.status === "error") r.err++;
      if (!r.last || (a.started || "") > (r.last.started || "")) r.last = { desc: a.desc, started: a.started, job: j.title };
    }
    S.rec = rec;
    // 会議中: 参加者(作業の記録に出てきた社員と司会の秘書)はラウンジの机のまわりに集まる
    const mj = (data.jobs || []).find((j) => j.status === "running" && (j.task_key || "").startsWith("meeting:"));
    S.meet = null; S.meetSay = {};
    if (mj) {
      const names = [...new Set(["secretary-chief", ...(mj.activity || []).map((a) => a.agent)])].filter((n) => desks[n]).slice(0, 10);
      const cx = 25.6, cy = 19.2;
      S.meet = Object.fromEntries(names.map((n, i) => { const ang = (i / names.length) * Math.PI * 2; return [n, [cx + Math.cos(ang) * 1.35, cy + Math.sin(ang) * 0.95]]; }));
      for (const a of mj.activity || []) if (a.status === "running" && S.meet[a.agent]) S.meetSay[a.agent] = (a.desc || "").slice(0, 16) + "…";
    }
    for (const [name, dk] of Object.entries(desks)) {
      const st = data.members[name], working = st?.state === "working", h = hash(name);
      let a = S.avatars[name];
      if (!a) {
        a = S.avatars[name] = { name, dept: dk.dept, boss: dk.boss, gx: dk.gx + 0.35, gy: dk.gy - 0.6, path: [], act: "desk", wait: 3 + (h % 20),
          hair: HAIR[h % HAIR.length], skin: SKIN[(h >> 3) % SKIN.length], style: STYLES[(h >> 5) % STYLES.length], phase: (h % 100) / 10, say: null };
      }
      if (working && S.prev[name] !== "working" && !S.meet?.[name]) goDesk(a);
      if (!working && S.prev[name] === "working") {
        const to = desks[dk.boss ? deptBoss["秘書室"] : deptBoss[dk.dept]];
        if (to && to !== dk) S.flyers.push({ from: [dk.gx + 0.5, dk.gy], to: [to.gx + 0.5, to.gy], t: 0 });
      }
      a.working = working;
      a.desc = st?.desc || "";
      S.prev[name] = st?.state;
    }
  }, [data]);

  // 描画
  useEffect(() => {
    const canvas = cvs.current, ctx = canvas.getContext("2d");
    let raf, last = performance.now();
    const resize = () => {
      const r = wrap.current.getBoundingClientRect(), dpr = window.devicePixelRatio || 1;
      canvas.width = r.width * dpr; canvas.height = r.height * dpr;
      canvas.style.width = r.width + "px"; canvas.style.height = r.height + "px";
      if (!S.fitted || S.lastW !== r.width) {
        const left = iso(0, GH).x, right = iso(GW, 0).x, top = iso(0, 0).y - 90, bottom = iso(GW, GH).y;
        const s = Math.min(r.width / (right - left + 40), r.height / (bottom - top + 40));
        S.cam = { s, x: r.width / 2 - ((left + right) / 2) * s, y: 20 - top * s };
        S.fitted = true; S.lastW = r.width;
      }
    };
    resize();
    S.refit = () => { S.fitted = false; resize(); };
    const ro = new ResizeObserver(resize); ro.observe(wrap.current);

    const P = (gx, gy, z = 0) => { const p = iso(gx, gy); return { x: p.x * S.cam.s + S.cam.x, y: p.y * S.cam.s + S.cam.y - z * S.cam.s }; };
    const poly = (pts, fill, stroke, lw = 1) => {
      ctx.beginPath(); pts.forEach((p, i) => (i ? ctx.lineTo(p.x, p.y) : ctx.moveTo(p.x, p.y))); ctx.closePath();
      if (fill) { ctx.fillStyle = fill; ctx.fill(); }
      if (stroke) { ctx.lineWidth = lw; ctx.strokeStyle = stroke; ctx.stroke(); }
    };
    const box = (gx, gy, w, d, h, color, z = 0, topColor) => {
      const a = P(gx, gy, z), b = P(gx + w, gy, z), c = P(gx + w, gy + d, z), e = P(gx, gy + d, z);
      const H = h * K * S.cam.s, up = (p) => ({ x: p.x, y: p.y - H });
      poly([e, c, up(c), up(e)], shade(color, 0.62));
      poly([c, b, up(b), up(c)], shade(color, 0.8));
      poly([up(a), up(b), up(c), up(e)], topColor || color);
    };
    const pill = (text, x, y, bg, fg, size = 12, tail = false) => {
      const sc = Math.max(0.85, S.cam.s);
      ctx.font = `700 ${size * sc}px "Noto Sans JP", sans-serif`;
      const w = ctx.measureText(text).width + 16 * sc, h = (size + 10) * sc;
      ctx.fillStyle = bg; ctx.beginPath(); ctx.roundRect(x - w / 2, y - h, w, h, 8 * sc); ctx.fill();
      if (tail) { ctx.beginPath(); ctx.moveTo(x - 5 * sc, y - 1); ctx.lineTo(x, y + 6 * sc); ctx.lineTo(x + 5 * sc, y - 1); ctx.fill(); }
      ctx.fillStyle = fg; ctx.textAlign = "center"; ctx.textBaseline = "middle"; ctx.fillText(text, x, y - h / 2 + 0.5);
    };

    // ---- 動き ----
    const step = (dt) => {
      const desks = S.desks || {}, avs = Object.values(S.avatars);
      const away = avs.filter((a) => a.act !== "desk").length;
      for (const a of avs) {
        if (!desks[a.name]) continue;
        if (a.path.length) {
          const [tx, ty] = a.path[0], dx = tx - a.gx, dy = ty - a.gy, dist = Math.hypot(dx, dy), mv = SPEED * dt;
          if (dist <= mv || dist < 1e-6) { a.gx = tx; a.gy = ty; a.path.shift(); }
          else { a.gx += (dx / dist) * mv; a.gy += (dy / dist) * mv; a.face = dx - dy >= 0 ? 1 : -1; }
          a.walking = a.path.length > 0;
          if (!a.walking) a.wait = a.act === "desk" ? 10 + Math.random() * 25 : 7 + Math.random() * 10;
          continue;
        }
        a.walking = false;
        if (S.meet?.[a.name]) {
          if (a.act !== "meeting") { endChat(a); a.act = "meeting"; a.path = route(a, S.meet[a.name]); }
          a.say = S.meetSay?.[a.name] || null;
          if (!a.path.length) { const [mx, my] = S.meet[a.name]; a.face = mx - my > 25.6 - 19.2 ? -1 : 1; }
          continue;
        }
        if (a.act === "meeting") { a.say = null; goDesk(a); continue; }
        if (a.working) { if (a.act !== "desk") goDesk(a); continue; }
        if (a.act === "chat") continue;
        a.wait -= dt;
        if (a.wait > 0) continue;
        if (a.act !== "desk") { goDesk(a); continue; }
        if (away > avs.length * 0.45) { a.wait = 8 + Math.random() * 12; continue; }
        const r = Math.random();
        if (r < 0.28) { a.act = "coffee"; a.path = route(a, [pickOne(COFFEE)[0] + (Math.random() - 0.5) * 0.3, 15.4]); }
        else if (r < 0.5) {
          const free = SOFA.filter((p) => !avs.some((o) => o.act === "sofa" && o.target === p));
          if (free.length) { const p = pickOne(free); a.act = "sofa"; a.target = p; a.path = route(a, p); } else a.wait = 6;
        } else if (r < 0.8) {
          const mate = avs.find((o) => o !== a && !o.working && o.act === "desk" && !o.path.length && Math.random() < 0.5);
          const spot = CHAT.find((c) => !S.chats.some((x) => x.spot === c));
          if (mate && spot) {
            a.act = mate.act = "chat"; a.path = route(a, spot[0]); mate.path = route(mate, spot[1]);
            const job = S.jobs?.length ? pickOne(S.jobs) : null;
            const lines = job ? [[`「${job.slice(0, 12)}」進んでます?`, pickOne(["もう少しです", "上司に見てもらってます", "品質管理部待ちです"])], [pickOne(ASK), pickOne(ANS)]]
                              : [[pickOne(ASK), pickOne(ANS)], [pickOne(ASK), pickOne(ANS)]];
            S.chats.push({ a, b: mate, spot, lines: lines.flat(), i: -1, timer: 0 });
          } else a.wait = 5;
        } else {
          const o = pickOne(avs.filter((x) => x.dept === a.dept && x !== a));
          if (o) { const [sx, sy] = seat(o); a.act = "visit"; a.path = route(a, [sx + 0.7, sy + 1.1]); } else a.wait = 5;
        }
      }
      for (const c of [...S.chats]) {
        if (c.a.working || c.b.working) { endChat(c.a); continue; }
        if (c.a.path.length || c.b.path.length) continue;
        c.timer -= dt;
        if (c.timer > 0) continue;
        c.i += 1;
        if (c.i >= c.lines.length) { endChat(c.a); c.a.act = c.b.act = "back"; c.a.wait = c.b.wait = 0.5 + Math.random(); continue; }
        const sp = c.i % 2 === 0 ? c.a : c.b, ls = c.i % 2 === 0 ? c.b : c.a;
        sp.say = c.lines[c.i]; ls.say = null; c.timer = 2.8;
        sp.face = sp.gx - sp.gy < ls.gx - ls.gy ? 1 : -1; ls.face = -sp.face;
      }
      S.flyers = S.flyers.filter((f) => (f.t += dt / 1.5) < 1);
    };

    // ---- 人 ----
    const person = (a, t) => {
      const p = P(a.gx, a.gy), s = S.cam.s * K, c = COLORS[a.dept];
      const seated = !a.walking && (a.act === "desk" || a.act === "sofa");
      const bob = a.walking ? Math.abs(Math.sin(t * 10 + a.phase)) * 2.2 * s : a.working ? Math.sin(t * 14 + a.phase) * 0.5 * s : Math.sin(t * 1.6 + a.phase) * 0.6 * s;
      const y0 = p.y - bob - (seated ? 0 : 6 * s), hov = S.hover === a.name;
      ctx.fillStyle = "rgba(0,0,0,.32)"; ctx.beginPath(); ctx.ellipse(p.x, p.y, 9 * s, 3.8 * s, 0, 0, 7); ctx.fill();
      if (a.working || S.focus === a.name) { // 作業中(または選んだ人)は足元が光る
        const k2 = 1 + 0.25 * Math.sin(t * 4);
        ctx.save(); ctx.strokeStyle = a.working ? "#ffd166" : "#9aa0f5"; ctx.lineWidth = 2.4 * s; ctx.shadowColor = ctx.strokeStyle; ctx.shadowBlur = 12 * s;
        ctx.beginPath(); ctx.ellipse(p.x, p.y, 14 * s * k2, 6 * s * k2, 0, 0, 7); ctx.stroke(); ctx.restore();
      }
      if (!seated) {
        const sw = a.walking ? Math.sin(t * 10 + a.phase) * 3.2 * s : 0;
        ctx.strokeStyle = a.boss ? "#2b2f45" : "#30375c"; ctx.lineWidth = 3.4 * s; ctx.lineCap = "round";
        ctx.beginPath(); ctx.moveTo(p.x - 2.6 * s, y0 - 9 * s); ctx.lineTo(p.x - 2.6 * s + sw, p.y - 1.5 * s); ctx.stroke();
        ctx.beginPath(); ctx.moveTo(p.x + 2.6 * s, y0 - 9 * s); ctx.lineTo(p.x + 2.6 * s - sw, p.y - 1.5 * s); ctx.stroke();
        ctx.fillStyle = "#1b1f33"; ctx.beginPath(); ctx.ellipse(p.x - 2.6 * s + sw, p.y - 1.2 * s, 2.4 * s, 1.3 * s, 0, 0, 7); ctx.fill();
        ctx.beginPath(); ctx.ellipse(p.x + 2.6 * s - sw, p.y - 1.2 * s, 2.4 * s, 1.3 * s, 0, 0, 7); ctx.fill();
      }
      const body = a.boss ? "#2f3554" : c;
      ctx.fillStyle = hov ? shade(body, 1.25) : body; ctx.beginPath(); ctx.roundRect(p.x - 7 * s, y0 - 26 * s, 14 * s, 18 * s, [6 * s, 6 * s, 4 * s, 4 * s]); ctx.fill();
      if (a.boss) {
        ctx.fillStyle = "#e9ebf5"; ctx.beginPath(); ctx.moveTo(p.x - 3 * s, y0 - 26 * s); ctx.lineTo(p.x, y0 - 19 * s); ctx.lineTo(p.x + 3 * s, y0 - 26 * s); ctx.fill();
        ctx.fillStyle = c; ctx.fillRect(p.x - 1 * s, y0 - 22 * s, 2 * s, 8 * s);
      }
      const swing = a.walking ? Math.sin(t * 10 + a.phase) * 4 * s : 0, type = a.working && seated ? Math.sin(t * 18 + a.phase) * 1.2 * s : 0;
      ctx.strokeStyle = hov ? shade(body, 1.15) : shade(body, 0.85); ctx.lineWidth = 3.2 * s; ctx.lineCap = "round";
      ctx.beginPath(); ctx.moveTo(p.x - 6.5 * s, y0 - 23 * s); ctx.lineTo(p.x - 8 * s - swing, y0 - 13 * s + type); ctx.stroke();
      ctx.beginPath(); ctx.moveTo(p.x + 6.5 * s, y0 - 23 * s); ctx.lineTo(p.x + 8 * s + swing, y0 - 13 * s - type); ctx.stroke();
      if (a.act === "coffee" && !a.walking) { ctx.fillStyle = "#f4efe6"; ctx.fillRect(p.x + 7 * s, y0 - 16 * s, 4 * s, 5 * s); }
      const hx = p.x, hy = y0 - 33 * s;
      if (a.style === "long") { ctx.fillStyle = a.hair; ctx.beginPath(); ctx.roundRect(hx - 8 * s, hy - 4 * s, 16 * s, 15 * s, 6 * s); ctx.fill(); }
      ctx.fillStyle = a.skin; ctx.beginPath(); ctx.arc(hx, hy, 7.2 * s, 0, 7); ctx.fill();
      ctx.fillStyle = a.hair;
      ctx.beginPath(); ctx.arc(hx, hy - 1.2 * s, 7.6 * s, Math.PI * 1.0, Math.PI * 2.0); ctx.fill();
      if (a.style === "bob") { ctx.fillRect(hx - 7.8 * s, hy - 1.5 * s, 2.6 * s, 7 * s); ctx.fillRect(hx + 5.2 * s, hy - 1.5 * s, 2.6 * s, 7 * s); }
      if (a.style === "bun") { ctx.beginPath(); ctx.arc(hx + 2 * s, hy - 9 * s, 3.4 * s, 0, 7); ctx.fill(); }
      if (a.style === "spiky") { for (let i = -2; i <= 2; i++) { ctx.beginPath(); ctx.moveTo(hx + i * 3 * s - 2 * s, hy - 6 * s); ctx.lineTo(hx + i * 3 * s, hy - 11 * s); ctx.lineTo(hx + i * 3 * s + 2 * s, hy - 6 * s); ctx.fill(); } }
      if (!(seated && a.act === "desk")) {
        const f = (a.face || 1) * 1.4 * s;
        ctx.fillStyle = "#2a2d3f"; ctx.beginPath(); ctx.arc(hx - 2.6 * s + f, hy + 1 * s, 1 * s, 0, 7); ctx.arc(hx + 2.6 * s + f, hy + 1 * s, 1 * s, 0, 7); ctx.fill();
        ctx.fillStyle = "rgba(236,120,120,.35)"; ctx.beginPath(); ctx.arc(hx - 4.4 * s + f, hy + 3 * s, 1.4 * s, 0, 7); ctx.arc(hx + 4.4 * s + f, hy + 3 * s, 1.4 * s, 0, 7); ctx.fill();
      }
      if (a.boss) { ctx.fillStyle = "#f3d27a"; ctx.font = `${8 * s}px sans-serif`; ctx.textAlign = "center"; ctx.textBaseline = "middle"; ctx.fillText("★", hx + 8 * s, hy - 7 * s); }
      S.hit.push({ name: a.name, dept: a.dept, x: p.x, y: y0 - 20 * s, r: 15 * s });
      return { x: hx, y: hy - 12 * s };
    };

    // ---- 机・小物 ----
    const desk = (dk, on, t) => {
      const { gx, gy, boss, dept } = dk, w = boss ? 1.5 : 1.2, c = COLORS[dept];
      box(gx + 0.1, gy - 0.95, 0.55, 0.45, 9, "#2b3150");
      box(gx, gy - 0.3, w, 0.72, 11, boss ? "#7a5a3e" : "#d9d4c7", 0, boss ? "#8a6a4c" : "#ece7da");
      const m = P(gx + 0.35, gy - 0.05, 11 * K), s = S.cam.s * K;
      ctx.fillStyle = "#1c2138"; ctx.beginPath(); ctx.roundRect(m.x - 8 * s, m.y - 13 * s, 16 * s, 11 * s, 1.5 * s); ctx.fill();
      if (on) {
        ctx.save(); ctx.globalAlpha = 0.45 + 0.25 * Math.sin(t * 5); ctx.fillStyle = c; ctx.shadowColor = c; ctx.shadowBlur = 14 * s;
        ctx.fillRect(m.x - 9 * s, m.y - 14 * s, 18 * s, 2 * s); ctx.restore();
      }
      ctx.fillStyle = "#2a3050"; ctx.fillRect(m.x - 1.2 * s, m.y - 2 * s, 2.4 * s, 3 * s);
      const l = P(gx + w - 0.15, gy - 0.15, 11 * K);
      ctx.strokeStyle = "#555c7e"; ctx.lineWidth = 1.4 * s; ctx.beginPath(); ctx.moveTo(l.x, l.y); ctx.lineTo(l.x, l.y - 10 * s); ctx.lineTo(l.x - 4 * s, l.y - 12 * s); ctx.stroke();
      if (on || boss) { ctx.fillStyle = "rgba(255,214,140,.9)"; ctx.beginPath(); ctx.arc(l.x - 4 * s, l.y - 11 * s, 2 * s, 0, 7); ctx.fill(); }
      const cup = P(gx + 0.95, gy + 0.2, 11 * K); ctx.fillStyle = "#f2efe8"; ctx.fillRect(cup.x - 1.6 * s, cup.y - 4 * s, 3.2 * s, 4 * s);
    };
    const plant = (gx, gy, big) => {
      const p = P(gx, gy), s = S.cam.s * K * (big ? 1.3 : 1);
      ctx.fillStyle = "#c9b79a"; ctx.beginPath(); ctx.roundRect(p.x - 5 * s, p.y - 9 * s, 10 * s, 9 * s, 2 * s); ctx.fill();
      for (const [dx, dy, r, col] of [[0, -18, 8, "#3c8a58"], [-5, -14, 6, "#2f7a4c"], [5, -15, 6, "#4aa267"], [1, -23, 5, "#55b273"]]) {
        ctx.fillStyle = col; ctx.beginPath(); ctx.arc(p.x + dx * s, p.y + dy * s, r * s, 0, 7); ctx.fill();
      }
    };

    // ---- 部屋の看板: 部署名・状態・今の仕事・進み具合 ----
    const sign = (dept, x, y, n, t) => {
      if (dept === "ラウンジ") return;
      const fut = document.documentElement.dataset.look === "future";
      const p = P(x + 0.25, y + 0.25, 26), sc = Math.max(0.62, Math.min(1.2, S.cam.s * 0.95));
      const job = S.deptJob?.[dept], stop = S.deptStop?.[dept];
      const state = stop && !job ? "stop" : job || n ? "run" : "idle";
      const chip = { stop: "止まっています", run: "作業中", idle: "待機" }[state];
      const chipBg = { stop: fut ? "#ff4d8d" : "#ff8a9a", run: fut ? "#00e5ff" : "#7cc4f7", idle: "rgba(255,255,255,.12)" }[state];
      const line2 = state === "stop" ? stop : job ? job.title : "待機中";
      const t2 = line2.length > 17 ? line2.slice(0, 17) + "…" : line2;
      ctx.font = `800 ${12 * sc}px "Noto Sans JP", sans-serif`; const w1 = ctx.measureText(dept).width;
      ctx.font = `700 ${9.5 * sc}px "Noto Sans JP", sans-serif`; const wc = ctx.measureText(chip).width + 12 * sc;
      ctx.font = `500 ${10 * sc}px "Noto Sans JP", sans-serif`; const w2 = ctx.measureText(t2).width;
      const W = Math.max(w1 + wc + 22 * sc, w2 + 18 * sc), H = (job ? 44 : 38) * sc, bx = p.x - 6 * sc, by = p.y - H;
      ctx.save();
      if (state === "stop") { ctx.shadowColor = chipBg; ctx.shadowBlur = (10 + 6 * Math.sin(t * 4)) * sc; }
      else if (fut) { ctx.shadowColor = "#00e5ff"; ctx.shadowBlur = 8 * sc; }
      ctx.fillStyle = fut ? "rgba(4,12,26,.92)" : "rgba(16,20,42,.93)";
      ctx.beginPath(); ctx.roundRect(bx, by, W, H, (fut ? 3 : 8) * sc); ctx.fill(); ctx.shadowBlur = 0;
      ctx.lineWidth = 1.2; ctx.strokeStyle = state === "stop" ? chipBg : fut ? "rgba(0,229,255,.5)" : COLORS[dept]; ctx.stroke();
      ctx.textAlign = "left"; ctx.textBaseline = "middle";
      ctx.fillStyle = fut ? "#e6fbff" : "#eef0fb"; ctx.font = `800 ${12 * sc}px "Noto Sans JP", sans-serif`; ctx.fillText(dept, bx + 8 * sc, by + 12 * sc);
      const cx = bx + W - wc - 7 * sc;
      ctx.fillStyle = chipBg; ctx.beginPath(); ctx.roundRect(cx, by + 5 * sc, wc, 14 * sc, 7 * sc); ctx.fill();
      ctx.fillStyle = state === "idle" ? "#aab0cc" : "#0b0e1a"; ctx.font = `700 ${9.5 * sc}px "Noto Sans JP", sans-serif`; ctx.fillText(chip, cx + 6 * sc, by + 12.5 * sc);
      ctx.fillStyle = state === "stop" ? chipBg : fut ? "#8fb8c9" : "#a8afd0"; ctx.font = `500 ${10 * sc}px "Noto Sans JP", sans-serif`; ctx.fillText(t2, bx + 8 * sc, by + 28 * sc);
      if (job) {
        const pw = W - 16 * sc, u = Math.min(1, (job.done + 0.3 + 0.2 * Math.sin(t * 2)) / (job.total + 0.5));
        ctx.fillStyle = "rgba(255,255,255,.1)"; ctx.fillRect(bx + 8 * sc, by + 37 * sc, pw, 3 * sc);
        ctx.fillStyle = fut ? "#00e5ff" : COLORS[dept]; ctx.fillRect(bx + 8 * sc, by + 37 * sc, pw * u, 3 * sc);
      }
      ctx.restore();
    };
    // ---- 仕事の流れ(企画→ライティング→デザイン→品質管理→秘書室)。床に光る点線、動いている区間だけ流れる ----
    const FLOW = ["企画編集部", "ライティング部", "デザイン部", "品質管理部", "秘書室"];
    const center = (d) => { const r = ROOMS.find((q) => q[0] === d); return [r[1] + r[3] / 2, r[2] + r[4] / 2]; };
    const flow = (t) => {
      const fut = document.documentElement.dataset.look === "future";
      for (let i = 0; i < FLOW.length - 1; i++) {
        const a = center(FLOW[i]), b = center(FLOW[i + 1]);
        const live = S.deptJob?.[FLOW[i]] || S.deptJob?.[FLOW[i + 1]];
        const pa = P(...a), pb = P(...b);
        ctx.save();
        ctx.strokeStyle = live ? (fut ? "rgba(0,229,255,.85)" : "rgba(185,189,250,.85)") : "rgba(185,189,250,.18)";
        ctx.lineWidth = (live ? 3 : 2) * S.cam.s; ctx.setLineDash([8 * S.cam.s, 7 * S.cam.s]); ctx.lineDashOffset = live ? -t * 30 * S.cam.s : 0;
        if (live && fut) { ctx.shadowColor = "#00e5ff"; ctx.shadowBlur = 10; }
        ctx.beginPath(); ctx.moveTo(pa.x, pa.y); ctx.lineTo(pb.x, pb.y); ctx.stroke();
        // 向きの矢印
        const mx = (pa.x + pb.x) / 2, my = (pa.y + pb.y) / 2, ang = Math.atan2(pb.y - pa.y, pb.x - pa.x), r = 7 * S.cam.s;
        ctx.setLineDash([]); ctx.fillStyle = ctx.strokeStyle; ctx.beginPath();
        ctx.moveTo(mx + Math.cos(ang) * r, my + Math.sin(ang) * r); ctx.lineTo(mx + Math.cos(ang + 2.5) * r, my + Math.sin(ang + 2.5) * r);
        ctx.lineTo(mx + Math.cos(ang - 2.5) * r, my + Math.sin(ang - 2.5) * r); ctx.fill();
        ctx.restore();
      }
    };

    // ---- 1コマ ----
    const draw = (t) => {
      const desks = S.desks || {}, dpr = window.devicePixelRatio || 1;
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0); ctx.clearRect(0, 0, canvas.width, canvas.height);
      S.hit = [];
      // 奥の壁と窓(夜景)
      for (const [horiz, n] of [[true, GW], [false, GH]]) {
        const a = P(-0.3, -0.3), b = horiz ? P(GW, -0.3) : P(-0.3, GH);
        const WH = 70 * S.cam.s;
        poly([a, b, { x: b.x, y: b.y - WH }, { x: a.x, y: a.y - WH }], horiz ? "#1b2142" : "#161b36");
        for (let i = 0; i < n; i += 2) {
          const u0 = (i + 0.25) / n, u1 = (i + 1.75) / n;
          const q0 = { x: a.x + (b.x - a.x) * u0, y: a.y + (b.y - a.y) * u0 }, q1 = { x: a.x + (b.x - a.x) * u1, y: a.y + (b.y - a.y) * u1 };
          const top = 60 * S.cam.s, bot = 16 * S.cam.s;
          const g = ctx.createLinearGradient(0, q0.y - top, 0, q0.y - bot); g.addColorStop(0, "#2c3a78"); g.addColorStop(1, "#131938");
          poly([{ x: q0.x, y: q0.y - bot }, { x: q1.x, y: q1.y - bot }, { x: q1.x, y: q1.y - top }, { x: q0.x, y: q0.y - top }], g, "#3a4680");
          ctx.fillStyle = "rgba(255,220,150,.6)";
          for (let k = 0; k < 4; k++) {
            const u = (hash(`${horiz}${i}${k}`) % 100) / 100, v = (hash(`${i}${k}${horiz}`) % 60) / 100;
            const wx = q0.x + (q1.x - q0.x) * u, wy = q0.y + (q1.y - q0.y) * u - bot - (top - bot) * (0.12 + v);
            ctx.fillRect(wx, wy, 2 * S.cam.s, 2 * S.cam.s);
          }
        }
      }
      // 床
      const FUT = document.documentElement.dataset.look === "future";
      poly([P(0, 0), P(GW, 0), P(GW, GH), P(0, GH)], FUT ? "#06101f" : "#2a2f4a");
      const ed = [P(0, GH), P(GW, GH), P(GW, 0)], dz = 12 * S.cam.s;
      poly([ed[0], ed[1], { x: ed[1].x, y: ed[1].y + dz }, { x: ed[0].x, y: ed[0].y + dz }], "#151a30");
      poly([ed[1], ed[2], { x: ed[2].x, y: ed[2].y + dz }, { x: ed[1].x, y: ed[1].y + dz }], "#1b2038");
      const busy = {};
      for (const a of Object.values(S.avatars)) if (a.working) busy[a.dept] = (busy[a.dept] || 0) + 1;
      for (const [dept, x, y, w, h, floor] of ROOMS) {
        const c = COLORS[dept];
        const base = FUT ? (floor === "lounge" ? "#0d1a33" : "#091428") : floor === "wood" ? "#6b5640" : floor === "lounge" ? "#7a6248" : shade(c, 0.36);
        poly([P(x, y), P(x + w, y), P(x + w, y + h), P(x, y + h)], base);
        ctx.save(); ctx.globalAlpha = FUT ? 0.35 : floor === "carpet" ? 0.1 : 0.22; ctx.strokeStyle = FUT ? "#00e5ff" : floor === "carpet" ? "#fff" : "#2d2218"; ctx.lineWidth = 1;
        if (floor === "carpet" || FUT) {
          for (let i = 1; i < w; i++) { const p = P(x + i, y), q = P(x + i, y + h); ctx.beginPath(); ctx.moveTo(p.x, p.y); ctx.lineTo(q.x, q.y); ctx.stroke(); }
          for (let j = 1; j < h; j++) { const p = P(x, y + j), q = P(x + w, y + j); ctx.beginPath(); ctx.moveTo(p.x, p.y); ctx.lineTo(q.x, q.y); ctx.stroke(); }
        } else for (let j = 0.5; j < h; j += 0.5) { const p = P(x, y + j), q = P(x + w, y + j); ctx.beginPath(); ctx.moveTo(p.x, p.y); ctx.lineTo(q.x, q.y); ctx.stroke(); }
        ctx.restore();
        if (floor === "lounge") poly([P(x + 1.2, y + 3.2), P(x + 4.4, y + 3.2), P(x + 4.4, y + 5.6), P(x + 1.2, y + 5.6)], "#a4865f");
        if (busy[dept]) { ctx.save(); ctx.globalAlpha = 0.14 + 0.06 * Math.sin(t * 2); poly([P(x, y), P(x + w, y), P(x + w, y + h), P(x, y + h)], FUT ? "#00e5ff" : c); ctx.restore(); }
        if (S.deptStop?.[dept] && !S.deptJob?.[dept]) { ctx.save(); ctx.globalAlpha = 0.16 + 0.1 * Math.sin(t * 4); poly([P(x, y), P(x + w, y), P(x + w, y + h), P(x, y + h)], "#ff4d6d", "#ff8a9a", 2); ctx.restore(); }
        const gz = 18;
        ctx.save(); ctx.globalAlpha = 0.16;
        poly([P(x, y + h), P(x + w, y + h), P(x + w, y + h, gz), P(x, y + h, gz)], FUT ? "#00e5ff" : "#bfd3ff");
        poly([P(x + w, y), P(x + w, y + h), P(x + w, y + h, gz), P(x + w, y, gz)], FUT ? "#00e5ff" : "#bfd3ff");
        ctx.restore();
        ctx.strokeStyle = FUT ? "rgba(0,229,255,.7)" : "rgba(200,215,255,.35)"; ctx.lineWidth = 1;
        for (const [px, py] of [[x + w, y + h], [x + w, y], [x, y + h]]) { const a = P(px, py), b = P(px, py, gz); ctx.beginPath(); ctx.moveTo(a.x, a.y); ctx.lineTo(b.x, b.y); ctx.stroke(); }
      }
      // 置く物を奥から順に
      const items = [];
      for (const [name, dk] of Object.entries(desks)) items.push({ k: dk.gx + dk.gy, f: () => desk(dk, S.avatars[name]?.working, t) });
      items.push({ k: 23.3 + 14.6, f: () => {
        box(23.3, 14.3, 2.6, 0.6, 15, "#8a6d4f", 0, "#a88a66");
        const m = P(24.0, 14.5, 15 * K), s = S.cam.s * K; ctx.fillStyle = "#30364f"; ctx.fillRect(m.x - 4 * s, m.y - 9 * s, 8 * s, 9 * s);
        ctx.fillStyle = "#e0453a"; ctx.fillRect(m.x - 1 * s, m.y - 7 * s, 2 * s, 2 * s);
      } });
      items.push({ k: 27.2 + 14.6, f: () => box(26.9, 14.3, 0.8, 0.6, 22, "#4b6da8", 0, "#5c80c0") });
      items.push({ k: 24.3 + 17.4, f: () => { box(24.3, 17.25, 3.1, 0.5, 13, "#5a6e9a"); box(24.3, 17.6, 3.1, 0.55, 6, "#6b80ad"); } });
      items.push({ k: 25.2 + 19.0, f: () => box(24.9, 18.9, 1.4, 0.7, 5, "#8a6d4f", 0, "#a88a66") });
      items.push({ k: 2.0 + 3.6, f: () => box(1.4, 3.3, 2.4, 1.0, 8, "#7a5a3e", 0, "#8f6c4c") });
      items.push({ k: 7.3 + 0.4, f: () => box(7.2, 0.15, 2.2, 0.3, 26, "#6a4f3a", 0, "#7d5e45") });
      items.push({ k: 22.6 + 0.4, f: () => box(22.3, 0.2, 2.0, 0.12, 24, "#e6e8f0") });
      items.push({ k: 26.2 + 8.6, f: () => box(26.1, 8.5, 0.3, 0.3, 20, "#3a3f5c") });
      for (const [gx, gy, big] of [[6.6, 0.4, 1], [13.6, 0.4, 0], [21.6, 6.0, 0], [0.4, 12.6, 0], [27.5, 20.4, 1], [23.4, 20.4, 0], [8.5, 20.5, 0], [16.5, 20.5, 0]])
        items.push({ k: gx + gy, f: () => plant(gx, gy, big) });
      const heads = [];
      for (const a of Object.values(S.avatars)) {
        const k = a.gx + a.gy + (a.act === "sofa" && !a.walking ? 0.6 : 0.02);
        items.push({ k, f: () => heads.push({ a, ...person(a, t) }) });
      }
      items.sort((p, q) => p.k - q.k).forEach((it) => it.f());
      for (const f of S.flyers) {
        const a = P(...f.from), b = P(...f.to), u = f.t, s = S.cam.s * K;
        const x = a.x + (b.x - a.x) * u, y = a.y + (b.y - a.y) * u - Math.sin(u * Math.PI) * 50 * s - 26 * s;
        ctx.save(); ctx.translate(x, y); ctx.rotate(Math.sin(u * 9) * 0.35); ctx.fillStyle = "#fff"; ctx.shadowColor = "#9aa0f5"; ctx.shadowBlur = 10 * s;
        ctx.fillRect(-6 * s, -8 * s, 12 * s, 16 * s); ctx.shadowBlur = 0; ctx.fillStyle = "#8e95f2";
        for (let i = 0; i < 3; i++) ctx.fillRect(-4 * s, (-5 + i * 3.5) * s, 8 * s, 1.4 * s);
        ctx.restore();
      }
      // 部屋の名前は小さく、薄く(風景を邪魔しない)
      if (!S.cinema) for (const [dept, x, y] of ROOMS) { const p = P(x + 0.25, y + 0.25, 24); pill(dept, p.x, p.y, "rgba(16,20,42,.55)", "rgba(213,217,240,.8)", 10); }
      for (const h of heads) {
        const a = h.a, title = S.info?.[a.name]?.title || "";
        if (a.working && !a.walking && !S.cinema && S.hover === a.name) {
          const d = a.desc.length > 15 ? a.desc.slice(0, 15) + "…" : a.desc;
          pill(`${title}:${d} ${".".repeat(1 + (Math.floor(t * 2) % 3))}`, h.x, h.y, "rgba(255,255,255,.97)", "#161a35", 12, true);
        } else if (a.say) pill(a.say, h.x, h.y, "rgba(255,248,226,.97)", "#3a2c12", 12, true);
      }
      light(t, heads);
    };

    // ---- 光: 時間帯の色と、作業中の机の画面の光(顔が照らされる) ----
    const light = (t, heads) => {
      const W = canvas.width / dpr0(), H = canvas.height / dpr0();
      const hr = new Date().getHours() + new Date().getMinutes() / 60;
      const fut = document.documentElement.dataset.look === "future";
      // 朝(6-10)=暖かい / 昼=そのまま / 夕(16-19)=橙 / 夜=青く暗い
      const tint = hr >= 6 && hr < 10 ? [255, 214, 170, 0.10] : hr >= 10 && hr < 16 ? [255, 255, 255, 0] : hr >= 16 && hr < 19 ? [255, 150, 90, 0.16] : [20, 30, 80, 0.34];
      if (tint[3]) { ctx.save(); ctx.globalCompositeOperation = hr >= 19 || hr < 6 ? "multiply" : "soft-light"; ctx.fillStyle = `rgba(${tint[0]},${tint[1]},${tint[2]},${tint[3] * (hr >= 19 || hr < 6 ? 2.2 : 1)})`; ctx.fillRect(0, 0, W, H); ctx.restore(); }
      ctx.save(); ctx.globalCompositeOperation = "screen";
      for (const h of heads) {
        if (!h.a.working || h.a.walking) continue;
        const r = 34 * S.cam.s * K, g = ctx.createRadialGradient(h.x, h.y + 18 * S.cam.s, 0, h.x, h.y + 18 * S.cam.s, r);
        const c = fut ? "0,229,255" : "150,190,255", a = 0.32 + 0.06 * Math.sin(t * 6 + h.x);
        g.addColorStop(0, `rgba(${c},${a})`); g.addColorStop(1, `rgba(${c},0)`);
        ctx.fillStyle = g; ctx.beginPath(); ctx.arc(h.x, h.y + 18 * S.cam.s, r, 0, 7); ctx.fill();
      }
      ctx.restore();
      // 画面の縁を少し暗く(映画のような見え方)
      const v = ctx.createRadialGradient(W / 2, H / 2, Math.min(W, H) * 0.35, W / 2, H / 2, Math.max(W, H) * 0.75);
      v.addColorStop(0, "rgba(0,0,0,0)"); v.addColorStop(1, "rgba(0,0,0,.45)"); ctx.fillStyle = v; ctx.fillRect(0, 0, W, H);
    };
    const dpr0 = () => window.devicePixelRatio || 1;

    // ---- 自動カメラ: 作業中の人へゆっくり寄る → 全体を見渡す、を繰り返す ----
    const tour = (dt) => {
      if (!S.auto || S.drag) return;
      S.tourT = (S.tourT || 0) + dt;
      const r = wrap.current?.getBoundingClientRect(); if (!r) return;
      if (!S.tourTarget || S.tourT > 9) {
        S.tourT = 0;
        const ws = Object.values(S.avatars).filter((a) => a.working), all = Object.values(S.avatars);
        const wide = S.tourWide = !S.tourWide;
        if (wide || !all.length) { S.tourTarget = { wide: true }; }
        else { const a = (ws.length ? ws : all)[Math.floor(Math.random() * (ws.length || all.length))]; S.tourTarget = { name: a.name }; }
      }
      let goal;
      if (S.tourTarget.wide) {
        const left = iso(0, GH).x, right = iso(GW, 0).x, top = iso(0, 0).y - 90, bottom = iso(GW, GH).y;
        const sc = Math.min(r.width / (right - left + 40), r.height / (bottom - top + 40));
        goal = { s: sc, x: r.width / 2 - ((left + right) / 2) * sc, y: 20 - top * sc };
      } else {
        const a = S.avatars[S.tourTarget.name]; if (!a) return;
        const sc = Math.max(1.5, S.cam.s), p = iso(a.gx, a.gy);
        goal = { s: 1.7, x: r.width / 2 - p.x * 1.7, y: r.height / 2 - p.y * 1.7 + 40 };
      }
      const k = Math.min(1, dt * 0.6);
      S.cam.s += (goal.s - S.cam.s) * k; S.cam.x += (goal.x - S.cam.x) * k; S.cam.y += (goal.y - S.cam.y) * k;
    };

    const loop = (now) => {
      const dt = Math.max(0, Math.min(0.05, (now - last) / 1000)); last = now;
      step(dt); tour(dt); draw(now / 1000);
      raf = requestAnimationFrame(loop);
    };
    raf = requestAnimationFrame(loop);
    return () => { cancelAnimationFrame(raf); ro.disconnect(); };
  }, []);

  // 操作
  const pick = (e) => {
    const r = cvs.current.getBoundingClientRect(), x = e.clientX - r.left, y = e.clientY - r.top;
    let best = null;
    for (const h of S.hit) { const d = Math.hypot(h.x - x, h.y - y); if (d < h.r && (!best || d < best.d)) best = { ...h, d }; }
    return best ? { ...best, ex: x, ey: y } : null;
  };
  const onMove = (e) => {
    if (S.drag) { S.cam.x += e.clientX - S.drag.x; S.cam.y += e.clientY - S.drag.y; S.drag = { x: e.clientX, y: e.clientY, moved: true }; return; }
    const h = pick(e); S.hover = h?.name || null; setHover(h);
  };
  const onDown = (e) => { S.drag = { x: e.clientX, y: e.clientY, moved: false }; if (S.auto) setAuto(false); };
  const onUp = (e) => { const moved = S.drag?.moved; S.drag = null; if (!moved) { const h = pick(e); setCard(h ? h.name : null); if (h) { S.focus = h.name; } } };
  const focus = (name) => { // その社員を画面の真ん中に、少し寄せて映す
    const a = S.avatars[name]; if (!a || !cvs.current) return;
    const r = cvs.current.getBoundingClientRect(), s = Math.max(S.cam.s, 1.3), p = iso(a.gx, a.gy);
    S.cam = { s, x: r.width / 2 - p.x * s, y: r.height / 2 - p.y * s + 40 };
    S.focus = name; setTimeout(() => { if (S.focus === name) S.focus = null; }, 4000);
  };
  const zoom = (f, cx, cy) => {
    const r = cvs.current.getBoundingClientRect(); cx = cx ?? r.width / 2; cy = cy ?? r.height / 2;
    const s = Math.max(0.35, Math.min(2.6, S.cam.s * f)), k = s / S.cam.s;
    S.cam.x = cx - (cx - S.cam.x) * k; S.cam.y = cy - (cy - S.cam.y) * k; S.cam.s = s;
  };
  useEffect(() => {
    const c = cvs.current;
    const wh = (e) => { e.preventDefault(); const r = c.getBoundingClientRect(); zoom(e.deltaY < 0 ? 1.1 : 0.9, e.clientX - r.left, e.clientY - r.top); };
    c.addEventListener("wheel", wh, { passive: false }); return () => c.removeEventListener("wheel", wh);
  }, []);

  const st = hover && data.members[hover.name], m = hover && S.info?.[hover.name], av = hover && S.avatars[hover.name];
  const doing = !hover ? "" : st?.state === "working" ? `作業中: ${st.desc}(${st.job})`
    : { coffee: "コーヒー休憩中", sofa: "ラウンジで休憩中", chat: "立ち話中", visit: "同僚の机に寄り道中", meeting: "会議中" }[av?.act] || "待機中";
  return (
    <div className="office" ref={wrap}>
      <canvas ref={cvs} onMouseMove={onMove} onMouseDown={onDown} onMouseUp={onUp}
              onMouseLeave={() => { S.drag = null; S.hover = null; setHover(null); }} style={{ cursor: hover ? "pointer" : "grab" }} />
      {(() => {
        const working = Object.entries(data.members).filter(([n, st]) => st.state === "working" && S.info?.[n]);
        if (cinema) return null;
        return (
          <div className={`office-now ${nowOpen ? "" : "closed"}`}>
            <button className="office-now-head" onClick={() => setNowOpen(!nowOpen)}><span className={`dot ${working.length ? "on" : ""}`} />いま作業中 {working.length}名 {nowOpen ? "▴" : "▾"}</button>
            {nowOpen && working.length === 0 && <div className="muted small">全員待機中です</div>}
            {nowOpen && working.map(([n, st]) => (
              <button key={n} className="office-now-row" onClick={() => focus(n)} title="押すとその社員の席を映します">
                <strong>{S.info[n].title}</strong><span>{st.desc}</span>
              </button>
            ))}
          </div>
        );
      })()}
      {!cinema && <div className="office-legend small">働いている様子を眺める画面です(時間帯で光が変わります)・ 詳しい状況はフロア図で ・ 休憩と立ち話は演出です</div>}
      <div className={`office-zoom ${cinema ? "cinema" : ""}`}>
        <button onClick={() => setAuto(!auto)} title={auto ? "自動カメラを止める" : "自動カメラで眺める"} className={auto ? "on" : ""}>{auto ? "■" : "▶"}</button>
        {!cinema && <><button onClick={() => zoom(1.2)}>＋</button><button onClick={() => zoom(1 / 1.2)}>−</button><button onClick={() => { setAuto(false); S.refit?.(); }}>⌂</button></>}
        <button onClick={() => (cinema ? document.exitFullscreen?.() : goCinema())} title={cinema ? "全画面を終える" : "全画面で眺める(録画にも)"}>{cinema ? "✕" : "⛶"}</button>
      </div>
      {card && !cinema && (() => {
        const m2 = S.info?.[card] || {}, st2 = data.members[card], a2 = S.avatars[card];
        const now2 = st2?.state === "working" ? st2.desc : { coffee: "コーヒー休憩中", sofa: "ラウンジで休憩中", chat: "立ち話中", visit: "同僚の机に寄り道中", meeting: "会議中" }[a2?.act] || "待機中";
        return (
          <div className="office-tag">
            <strong>{m2.title}</strong><span className="muted small">{a2?.dept}</span>
            <div className="small">{now2}</div>
            <div className="office-tag-btns">
              {onShowFloor && <button className="link" onClick={() => onShowFloor(card)}>フロア図で詳しく ›</button>}
              <button className="link" onClick={() => setCard(null)}>閉じる</button>
            </div>
          </div>
        );
      })()}
      {hover && !card && !cinema && (
        <div className="office-tip" style={{ left: Math.min(hover.ex + 14, (wrap.current?.clientWidth || 600) - 290), top: hover.ey + 12 }}>
          <strong>{m?.title}{m?.boss ? "(上司)" : ""}</strong><span className="muted small">{hover.dept}</span>
          {m?.persona && <div className="small persona">{m.persona}</div>}
          <div className="small">{doing}</div>
          <div className="muted small">押すと名刺を出します</div>
        </div>
      )}
    </div>
  );
}
