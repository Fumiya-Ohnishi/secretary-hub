import React, { useEffect, useRef, useState } from "react";
import * as THREE from "three";
import { RoomEnvironment } from "three/examples/jsm/environments/RoomEnvironment.js";
import { makeAvatar, pose, hash } from "./office3d/avatar.js";
import { buildOffice, routeFromSeat, THEMES } from "./office3d/scene.js";

/**
 * 高品質のオフィス(眺める画面)。2つの見せ方を切り替える:
 *  - mode="3d"  : 全部3D。部署ごとの長机・会議はラウンジ・資料室の本棚。木目/白/黒の3色
 *  - mode="art" : AIで描いたオフィスのイラスト(public/office/art_wood.jpg)の上に3Dの社員を重ねる。主な社員だけ映る
 * 動き: 作業中の社員(秘書ハブの実際の作業ログ)は席でタイピングし、画面が点く。待機中はコーヒー・ラウンジ・資料室・立ち話へ歩く(演出)。
 *       作業が終わると書類が上司の席へ飛ぶ。会議中は参加者がラウンジ(イラスト版はガラスの会議室)に集まる。
 */
const ACT = { coffee: "コーヒー休憩中", sofa: "ラウンジで休憩中", chat: "立ち話中", library: "資料室で調べもの中", meeting: "会議中", walk: "移動中" };
const UL = Math.PI, DR = 0, UR = -Math.PI / 2, DL = Math.PI / 2;
// イラスト(1920x1080)の上の位置: [x, y, 向き]
const ART = {
  desks: [[350, 456, UL], [458, 406, UL], [548, 356, UL], [702, 504, UL], [792, 462, UL], [882, 400, UL], [598, 386, DR], [692, 344, DR],
    [932, 636, UL], [1002, 594, UL], [1077, 541, UL], [822, 499, DR], [952, 432, DR]],
  meet: [[1192, 406, DR], [1322, 386, DL], [1245, 446, UL], [1262, 352, DR], [1150, 470, UR], [1110, 452, UR]],
  sofa: [[1460, 492, DR], [1602, 539, UL], [330, 594, DR], [1065, 724, UL], [395, 565, DR]],
  coffee: [[935, 212, UL], [985, 238, UL]],
  chat: [[1415, 600, UR], [1475, 560, DL]],
  walks: [[[640, 600], [745, 650], [860, 600]], [[1130, 560], [1230, 515], [1130, 470]], [[1000, 300], [1080, 262]]],
};
const AW = 1920, AH = 1080;

function tod(h) { // 時間帯の光: [太陽の強さ, 太陽の色, 環境光, 天井の灯り, イラストに重ねる色]
  if (h >= 6 && h < 10) return [1.8, 0xffe7c4, 0.6, 2.5, "rgba(255,200,140,.10)"];
  if (h >= 10 && h < 16) return [2.2, 0xfff4e6, 0.65, 2.0, "rgba(0,0,0,0)"];
  if (h >= 16 && h < 19) return [1.3, 0xffb27a, 0.5, 5, "rgba(255,140,60,.18)"];
  return [0.35, 0x8fa6ff, 0.28, 7, "rgba(20,30,80,.38)"];
}

export default function Office3D({ data, mode = "3d", theme = "wood", onShowFloor }) {
  const wrap = useRef(null), stageRef = useRef(null), overlay = useRef(null);
  const S = useRef({ avatars: {}, prev: {}, flyers: [], chats: [], bubbles: {} }).current;
  const [hover, setHover] = useState(null);
  const [card, setCard] = useState(null);
  const [nowOpen, setNowOpen] = useState(true);
  const [auto, setAuto] = useState(false);  // 自動カメラ(初めはオフ。▶ で動かす。2026-11-10 社長の指示)
  const [cinema, setCinema] = useState(false);
  const [tint, setTint] = useState("rgba(0,0,0,0)");
  useEffect(() => { S.auto = auto; }, [auto]);
  useEffect(() => { S.cinema = cinema; }, [cinema]);
  useEffect(() => {
    const fs = () => { if (!document.fullscreenElement) setCinema(false); };
    document.addEventListener("fullscreenchange", fs); return () => document.removeEventListener("fullscreenchange", fs);
  }, []);
  S.data = data; S.mode = mode;
  try { if (localStorage.getItem("o3debug")) window.__o3 = S; } catch (e) {}

  // ---------- シーンを作る(見せ方・色が変わったら作り直す) ----------
  useEffect(() => {
    const host = stageRef.current;
    const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: mode === "art" });
    renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
    renderer.shadowMap.enabled = true; renderer.shadowMap.type = THREE.PCFSoftShadowMap;
    renderer.toneMapping = THREE.ACESFilmicToneMapping; renderer.outputColorSpace = THREE.SRGBColorSpace;
    renderer.domElement.className = "o3-canvas";
    host.appendChild(renderer.domElement);
    const scene = new THREE.Scene();
    const pmrem = new THREE.PMREMGenerator(renderer);
    scene.environment = pmrem.fromScene(new RoomEnvironment(), 0.04).texture;
    const hemi = new THREE.HemisphereLight(0xfff4e6, 0x3a3328, 0.6); scene.add(hemi);
    const sun = new THREE.DirectionalLight(0xfff1dc, 2.2); sun.castShadow = true;
    sun.shadow.mapSize.set(2048, 2048); sun.shadow.bias = -0.0004; sun.shadow.normalBias = 0.03;
    Object.assign(sun.shadow.camera, { left: -32, right: 32, top: 32, bottom: -32, near: 1, far: 120 });
    scene.add(sun); scene.add(sun.target);
    const cam = new THREE.OrthographicCamera(-1, 1, 1, -1, 0.1, 300);
    S.scene = scene; S.cam = cam; S.renderer = renderer; S.sun = sun; S.hemi = hemi;
    S.avatars = {}; S.prev = {}; S.flyers = []; S.chats = []; S.view = { a: Math.PI / 4, zoom: 1, tx: 0, tz: 0, pan: { x: 0, y: 0 }, s: 1 };

    if (mode === "3d") {
      scene.background = new THREE.Color(THEMES[theme]?.bg || 0x23262d);
      sun.position.set(-18, 30, 12);
      S.office = buildOffice(scene, theme, data.departments);
    } else {
      sun.position.set(-10, 30, 18);
      const ground = new THREE.Mesh(new THREE.PlaneGeometry(200, 200), new THREE.ShadowMaterial({ opacity: 0.28 }));
      ground.rotation.x = -Math.PI / 2; ground.receiveShadow = true; scene.add(ground);
      const vs = 11.3; Object.assign(cam, { left: -vs * AW / AH, right: vs * AW / AH, top: vs, bottom: -vs });
      cam.position.set(30, 30, 30); cam.lookAt(0, 0, 0); cam.updateProjectionMatrix(); cam.updateMatrixWorld();
      const ray = new THREE.Raycaster(), plane = new THREE.Plane(new THREE.Vector3(0, 1, 0), 0);
      S.at = (px, py) => { ray.setFromCamera(new THREE.Vector2(px / AW * 2 - 1, 1 - py / AH * 2), cam); const v = new THREE.Vector3(); ray.ray.intersectPlane(plane, v); return v; };
      S.office = null;
    }
    // 書類(作業が終わると上司の席へ飛ぶ)
    S.paperGeo = new THREE.BoxGeometry(0.42, 0.02, 0.56); S.paperMat = new THREE.MeshStandardMaterial({ color: 0xffffff, emissive: 0xfff3c4, emissiveIntensity: 0.4 });
    S.monOn = new THREE.MeshStandardMaterial({ color: 0x111418, emissive: 0x4aa3ff, emissiveIntensity: 0.8, roughness: 0.2 });
    S.monOff = null;

    const resize = () => {
      const r = wrap.current.getBoundingClientRect();
      if (mode === "3d") {
        renderer.setSize(r.width, r.height);
        S.W = r.width; S.H = r.height;
      } else {
        renderer.setSize(AW, AH, false);
        renderer.domElement.style.width = AW + "px"; renderer.domElement.style.height = AH + "px";
        S.fit = Math.min(r.width / AW, r.height / AH); S.W = r.width; S.H = r.height;
      }
    };
    resize();
    const ro = new ResizeObserver(resize); ro.observe(wrap.current);
    S.ready = true; S.sync?.();

    let raf, last = performance.now(), T = 0;
    const loop = (now) => {
      raf = requestAnimationFrame(loop);
      if (document.hidden) { last = now; return; }
      const dt = Math.max(0, Math.min((now - last) / 1000, 0.25)); last = now; T += dt;
      step(dt, T);
      placeCamera(T);
      renderer.render(scene, cam);
      drawOverlay();
    };
    raf = requestAnimationFrame(loop);
    const lightTimer = setInterval(applyLight, 60000); applyLight();
    return () => {
      cancelAnimationFrame(raf); clearInterval(lightTimer); ro.disconnect();
      scene.traverse((o) => { o.geometry?.dispose?.(); });
      renderer.dispose(); pmrem.dispose(); renderer.domElement.remove();
      S.ready = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [mode, theme]);

  function applyLight() {
    const [si, sc, hi, li, ov] = tod(new Date().getHours());
    S.sun.intensity = si; S.sun.color.setHex(sc); S.hemi.intensity = hi;
    for (const l of S.office?.lamps || []) l.intensity = li;
    setTint(ov);
  }

  // ---------- データ → 社員の居場所 ----------
  S.sync = () => {
    if (!S.ready) return;
    const data = S.data, info = {}, deptBoss = {};
    for (const [d, ms] of Object.entries(data.departments)) for (const m of ms) { info[m.name] = { ...m, dept: d }; if (m.boss) deptBoss[d] = m.name; }
    S.info = info;
    const mj = (data.jobs || []).find((j) => j.status === "running" && (j.task_key || "").startsWith("meeting:"));
    const meetNames = mj ? [...new Set(["secretary-chief", ...(mj.activity || []).map((a) => a.agent)])].filter((n) => info[n]).slice(0, 10) : [];
    S.meetSay = {};
    for (const a of mj?.activity || []) if (a.status === "running") S.meetSay[a.agent] = (a.desc || "").slice(0, 18) + "…";
    const working = (n) => data.members[n]?.state === "working";
    if (S.mode === "3d") sync3d(info, deptBoss, meetNames, working);
    else syncArt(info, meetNames, working);
    for (const n of Object.keys(info)) S.prev[n] = data.members[n]?.state;
  };
  useEffect(() => { S.sync(); }, [data]);

  function addAvatar(name) {
    const m = S.info[name];
    const a = makeAvatar(name, m.dept, !!m.boss, m.gender || "");
    S.scene.add(a);
    const st = { name, obj: a, path: [], act: "seat", wait: 8 + (hash(name) % 40), t: (hash(name) % 100) / 10, kind: "sit" };
    S.avatars[name] = st; return st;
  }
  function placeAt(st, x, z, rot, kind) { st.obj.position.set(x, 0, z); st.obj.rotation.y = rot; st.kind = kind; st.path = []; }
  function walkTo(st, pts, then) { st.path = pts.map(([x, z]) => new THREE.Vector3(x, 0, z)); st.then = then; st.kind = "walk"; }

  function sync3d(info, deptBoss, meetNames, working) {
    const seats = S.office.seats;
    const meet = S.office.spots.meet;
    for (const name of Object.keys(info)) {
      const seat = seats[name]; if (!seat) continue;
      let st = S.avatars[name];
      if (!st) { st = addAvatar(name); placeAt(st, seat.x, seat.z, seat.rot, "sit"); st.act = "seat"; }
      const w = working(name), wasW = S.prev[name] === "working";
      const mi = meetNames.indexOf(name);
      // 画面の点灯
      const mon = S.office.monitors[name];
      if (mon) { if (!S.monOff) S.monOff = mon.material; mon.material = w ? S.monOn : S.monOff; }
      st.working = w; st.desc = S.data.members[name]?.desc || "";
      if (mi >= 0) {
        if (st.act !== "meeting") {
          const ang = (mi / meetNames.length) * Math.PI * 2, x = meet[0] + Math.cos(ang) * 1.9, z = meet[1] + Math.sin(ang) * 1.9;
          leaveChat(st);
          walkTo(st, pathFrom(st, [x, z], { front: true }), () => { st.obj.rotation.y = Math.atan2(meet[0] - x, meet[1] - z); st.kind = "talk"; });
          st.act = "meeting"; st.opts = { front: true };
        }
        continue;
      }
      if (st.act === "meeting") { goSeat(st); continue; }
      if (w && !wasW && st.act !== "seat") goSeat(st);
      if (!w && wasW) {
        const boss = seats[deptBoss[seat.dept] === name ? deptBoss["秘書室"] : deptBoss[seat.dept]];
        if (boss && boss !== seat) S.flyers.push({ from: new THREE.Vector3(seat.x, 1.3, seat.z), to: new THREE.Vector3(boss.x, 1.3, boss.z), t: 0 });
      }
    }
  }
  function pathFrom(st, to, opts) { // いったん席まで戻ってから目的地へ(通路だけを通る)
    const seat = S.office.seats[st.name];
    const go = routeFromSeat(seat, to, opts);
    if (st.act === "seat") return go;
    const p = st.obj.position;
    const back = routeFromSeat(seat, [p.x, p.z], st.opts || {}).reverse().slice(1);
    return [...back, ...go];
  }
  function goSeat(st) {
    const seat = S.office.seats[st.name]; if (!seat) return;
    leaveChat(st);
    const back = routeFromSeat(seat, [st.obj.position.x, st.obj.position.z], st.opts || {}).reverse();
    walkTo(st, [...back.slice(1), [seat.x, seat.z]], () => { placeAt(st, seat.x, seat.z, seat.rot, "sit"); st.act = "seat"; st.opts = null; st.wait = 25 + Math.random() * 50; });
    st.act = "return";
  }
  function leaveChat(st) {
    S.chats = S.chats.filter((c) => { if (c.includes(st)) { c.forEach((x) => { x.say = null; }); return false; } return true; });
    st.say = null;
  }
  function idleTrip(st) { // 待機中の寄り道(演出)
    const sp = S.office.spots, r = Math.random();
    let kind, spot;
    if (r < 0.3) { kind = "coffee"; spot = sp.coffee[(Math.random() * sp.coffee.length) | 0]; }
    else if (r < 0.6) { kind = "sofa"; spot = sp.sofa[(Math.random() * sp.sofa.length) | 0]; }
    else if (r < 0.8) { kind = "library"; spot = sp.library[(Math.random() * sp.library.length) | 0]; }
    else {
      const free = Object.values(S.avatars).filter((o) => o !== st && o.act === "seat" && !o.working);
      const mate = free[(Math.random() * free.length) | 0]; const pair = sp.chat[(Math.random() * sp.chat.length) | 0];
      if (mate && !S.chats.some((c) => c.pair === pair)) {
        const c = [st, mate]; c.pair = pair; S.chats.push(c);
        [st, mate].forEach((o, i) => {
          const [x, z, rot] = pair[i]; o.act = "chat"; o.stay = 14 + Math.random() * 8;
          o.opts = {}; walkTo(o, pathFrom(o, [x, z]), () => { o.obj.rotation.y = rot; o.kind = "talk"; o.say = i === 0 ? ASK[(Math.random() * ASK.length) | 0] : null; o.ansAt = 3; });
        });
        return;
      }
      kind = "coffee"; spot = sp.coffee[0];
    }
    if (Object.values(S.avatars).some((o) => o !== st && o.spot === spot)) return; // 先客がいる
    const opts = spot[4] !== undefined ? { ax: spot[4] } : {};
    walkTo(st, pathFrom(st, [spot[0], spot[1]], opts), () => { st.obj.rotation.y = spot[2]; st.kind = spot[3] === "sofa" ? "sofa" : "stand"; });
    st.act = kind; st.spot = spot; st.stay = 12 + Math.random() * 20; st.opts = opts;
  }

  function syncArt(info, meetNames, working) {
    const names = Object.keys(info);
    const wk = names.filter((n) => working(n) && !meetNames.includes(n));
    const idle = names.filter((n) => !working(n) && !meetNames.includes(n)).sort((a, b) => hash(a + "d") - hash(b + "d"));
    const plan = {}; // name → {slot:[x,y,rot], kind}
    meetNames.slice(0, ART.meet.length).forEach((n, i) => { plan[n] = { slot: ART.meet[i], kind: i < 4 ? "sit" : "talk", act: "meeting" }; });
    let di = 0;
    for (const n of wk) if (di < ART.desks.length) plan[n] = { slot: ART.desks[di++], kind: "type", act: "seat" };
    let k = 0;
    while (di < ART.desks.length - 3 && k < idle.length) plan[idle[k++]] = { slot: ART.desks[di++], kind: "sit", act: "seat" };
    for (const s of ART.sofa) if (k < idle.length) plan[idle[k++]] = { slot: s, kind: "sofa", act: "sofa" };
    for (const s of ART.coffee) if (k < idle.length) plan[idle[k++]] = { slot: s, kind: "stand", act: "coffee" };
    ART.chat.forEach((s, i) => { if (k < idle.length) plan[idle[k++]] = { slot: s, kind: i === 0 ? "talk" : "stand", act: "chat" }; });
    ART.walks.forEach((w) => { if (k < idle.length) plan[idle[k++]] = { walk: w, act: "walk" }; });
    for (const [n, st] of Object.entries(S.avatars)) if (!plan[n]) { S.scene.remove(st.obj); delete S.avatars[n]; }
    for (const [n, p] of Object.entries(plan)) {
      let st = S.avatars[n]; if (!st) st = addAvatar(n);
      st.obj.scale.setScalar(1.15);
      st.working = working(n); st.desc = S.data.members[n]?.desc || ""; st.act = p.act;
      if (p.walk) { if (!st.loop) { st.loop = p.walk.map(([x, y]) => S.at(x, y)); st.seg = 0; st.u = (hash(n) % 10) / 10; } st.kind = "walk"; continue; }
      st.loop = null;
      const [x, y, rot] = p.slot; const sitting = p.kind === "sit" || p.kind === "type" || p.kind === "sofa";
      const v = S.at(x, sitting ? y : y - 34);
      st.obj.position.set(v.x, 0, v.z); st.obj.rotation.y = rot; st.kind = p.kind;
    }
    const chatters = Object.values(S.avatars).filter((o) => o.act === "chat");
    if (chatters[0] && !chatters[0].say) chatters[0].say = "この表紙、もう少し明るく?";
  }

  // ---------- 毎フレーム ----------
  function step(dt, T) {
    for (const st of Object.values(S.avatars)) {
      st.t += dt; const o = st.obj;
      if (S.mode === "art" && st.loop) {
        const A = st.loop[st.seg], B = st.loop[(st.seg + 1) % st.loop.length];
        st.u += dt * 1.1 / Math.max(A.distanceTo(B), 0.01);
        if (st.u >= 1) { st.u = 0; st.seg = (st.seg + 1) % st.loop.length; }
        o.position.lerpVectors(A, B, st.u); o.rotation.y = Math.atan2(B.x - A.x, B.z - A.z);
        pose(o, "walk", st.t); continue;
      }
      if (st.path.length) {
        const target = st.path[0], p = o.position, dx = target.x - p.x, dz = target.z - p.z, d = Math.hypot(dx, dz), sp = 1.7 * dt;
        if (d <= sp || d < 1e-6) { p.x = target.x; p.z = target.z; st.path.shift(); if (!st.path.length) { const f = st.then; st.then = null; f?.(); } }
        else { p.x += dx / d * sp; p.z += dz / d * sp; const want = Math.atan2(dx, dz); o.rotation.y += angDiff(want, o.rotation.y) * Math.min(1, dt * 10); }
        if (st.path.length) { pose(o, "walk", st.t); continue; }
      }
      const kind = st.kind === "sit" && st.working ? "type" : st.kind;
      pose(o, kind === "walk" ? "stand" : kind, st.t);
      if (S.mode !== "3d") continue;
      // 待機中の寄り道
      if (st.act === "seat" && !st.working) { st.wait -= dt; if (st.wait <= 0) { st.wait = 30 + Math.random() * 60; idleTrip(st); } }
      if (["coffee", "sofa", "library", "chat"].includes(st.act) && !st.path.length) {
        if (st.act === "chat" && st.ansAt !== undefined) {
          st.ansAt -= dt;
          if (st.ansAt <= 0) { const c = S.chats.find((x) => x.includes(st)); if (c && c[0].say) { c[1].say = ANS[(Math.random() * ANS.length) | 0]; } st.ansAt = undefined; }
        }
        st.stay -= dt; if (st.stay <= 0 || st.working) { st.spot = null; goSeat(st); }
      }
    }
    // 書類
    S.flyers = S.flyers.filter((f) => {
      if (!f.mesh) { f.mesh = new THREE.Mesh(S.paperGeo, S.paperMat); S.scene.add(f.mesh); }
      f.t += dt / 1.6; const t = Math.min(f.t, 1);
      f.mesh.position.lerpVectors(f.from, f.to, t); f.mesh.position.y = 1.3 + Math.sin(t * Math.PI) * 3; f.mesh.rotation.y = t * 6;
      if (f.t >= 1) { S.scene.remove(f.mesh); return false; }
      return true;
    });
  }
  const angDiff = (a, b) => { let d = a - b; while (d > Math.PI) d -= Math.PI * 2; while (d < -Math.PI) d += Math.PI * 2; return d; };

  function placeCamera(T) {
    const v = S.view;
    if (S.mode === "art") {
      const st = stageRef.current; if (!st) return;
      let s = S.fit * v.s, x = v.pan.x, y = v.pan.y;
      if (S.auto && !S.focusUntil) { const k = 1 + 0.12 * (0.5 + 0.5 * Math.sin(T * 0.05)); s = S.fit * k; x = Math.sin(T * 0.035) * 60 * k; y = Math.cos(T * 0.04) * 25 * k; }
      const ox = (S.W - AW * s) / 2 + x, oy = (S.H - AH * s) / 2 + y;
      st.style.transform = `translate(${ox}px, ${oy}px) scale(${s})`;
      S.stageXf = { ox, oy, s };
      return;
    }
    const cam = S.cam, aspect = S.W / Math.max(S.H, 1);
    let a = v.a, zoom = v.zoom, tx = v.tx, tz = v.tz;
    if (S.auto && !(S.focusUntil > T)) { a = Math.PI / 4 + Math.sin(T * 0.06) * 0.35; zoom = 1.05 + 0.2 * (0.5 + 0.5 * Math.sin(T * 0.045)); tx = Math.sin(T * 0.03) * 3; tz = Math.cos(T * 0.025) * 2; v.a = a; }
    if (S.focus && S.focusUntil > T) { const f = S.avatars[S.focus]?.obj.position; if (f) { tx = f.x; tz = f.z; zoom = 2.4; } }
    else if (S.focusUntil && S.focusUntil <= T) { S.focusUntil = 0; S.focus = null; }
    const h = Math.max(13.5, 27 / aspect) / zoom;
    Object.assign(cam, { left: -h * aspect, right: h * aspect, top: h, bottom: -h });
    const R = 60, e = 0.6155;
    cam.position.set(tx + Math.sin(a) * Math.cos(e) * R, Math.sin(e) * R, tz + Math.cos(a) * Math.cos(e) * R);
    cam.lookAt(tx, 0, tz); cam.updateProjectionMatrix();
    S.T = T;
  }

  // 吹き出し・名札(HTML)
  const pv = new THREE.Vector3();
  function toScreen(pos, y) {
    pv.copy(pos); pv.y += y; pv.project(S.cam);
    if (S.mode === "art") { const x = (pv.x + 1) / 2 * AW, yy = (1 - pv.y) / 2 * AH, xf = S.stageXf || { ox: 0, oy: 0, s: 1 }; return [xf.ox + x * xf.s, xf.oy + yy * xf.s]; }
    return [(pv.x + 1) / 2 * S.W, (1 - pv.y) / 2 * S.H];
  }
  function drawOverlay() {
    const el = overlay.current; if (!el) return;
    const want = [];
    if (!S.cinema && S.office) for (const l of S.office.labels) want.push({ key: "L" + l.text, cls: "o3-label", text: l.text, xy: toScreen(l.pos, 0) });
    const sc = S.mode === "art" ? 1.15 : 1;
    for (const st of Object.values(S.avatars)) {
      let text = null, cls = "o3-bub";
      if (st.act === "meeting" && S.meetSay?.[st.name]) text = "💬 " + S.meetSay[st.name];
      else if (st.working && st.kind !== "walk" && !st.path.length) { text = (st.desc || "作業中").slice(0, 16); cls = "o3-bub work"; }
      else if (st.say) text = st.say;
      if (text) want.push({ key: "B" + st.name, cls, text, xy: toScreen(st.obj.position, 2.75 * sc) });
    }
    const have = S.bubbles;
    const seen = new Set();
    for (const w of want) {
      seen.add(w.key);
      let d = have[w.key];
      if (!d) { d = document.createElement("div"); el.appendChild(d); have[w.key] = d; }
      if (d.className !== w.cls) d.className = w.cls;
      if (d.textContent !== w.text) d.textContent = w.text;
      d.style.transform = `translate(${w.xy[0]}px, ${w.xy[1]}px) translate(-50%, -100%)`;
    }
    for (const k of Object.keys(have)) if (!seen.has(k)) { have[k].remove(); delete have[k]; }
  }

  // ---------- 操作 ----------
  const ray = useRef(new THREE.Raycaster()).current;
  function pick(e) {
    if (!S.cam) return null;
    const r = wrap.current.getBoundingClientRect(); let nx, ny;
    if (S.mode === "art") { const xf = S.stageXf || { ox: 0, oy: 0, s: 1 }; const x = (e.clientX - r.left - xf.ox) / xf.s, y = (e.clientY - r.top - xf.oy) / xf.s; nx = x / AW * 2 - 1; ny = 1 - y / AH * 2; }
    else { nx = (e.clientX - r.left) / r.width * 2 - 1; ny = 1 - (e.clientY - r.top) / r.height * 2; }
    ray.setFromCamera(new THREE.Vector2(nx, ny), S.cam);
    const objs = Object.values(S.avatars).map((s) => s.obj);
    const hit = ray.intersectObjects(objs, true)[0];
    const who = hit?.object.userData.who;
    return who ? { name: who, ex: e.clientX - r.left, ey: e.clientY - r.top } : null;
  }
  const onMove = (e) => {
    if (S.drag) {
      const dx = e.clientX - S.drag.x, dy = e.clientY - S.drag.y; S.drag = { x: e.clientX, y: e.clientY, moved: S.drag.moved || Math.abs(dx) + Math.abs(dy) > 3 };
      if (mode === "3d") S.view.a -= dx * 0.006; else { S.view.pan.x += dx; S.view.pan.y += dy; }
      return;
    }
    const h = pick(e); setHover(h);
  };
  const onDown = (e) => { S.drag = { x: e.clientX, y: e.clientY, moved: false }; if (S.auto) { setAuto(false); S.auto = false; if (mode === "art") S.view.s = 1.1; } };
  const onUp = (e) => { const moved = S.drag?.moved; S.drag = null; if (!moved) { const h = pick(e); setCard(h ? h.name : null); } };
  const zoom = (f) => { if (mode === "3d") S.view.zoom = Math.max(0.6, Math.min(3.5, S.view.zoom * f)); else S.view.s = Math.max(0.8, Math.min(3, S.view.s * f)); };
  useEffect(() => {
    const c = wrap.current;
    const wh = (e) => { e.preventDefault(); if (S.auto) { setAuto(false); S.auto = false; } zoom(e.deltaY < 0 ? 1.1 : 0.9); };
    c.addEventListener("wheel", wh, { passive: false }); return () => c.removeEventListener("wheel", wh);
  }, [mode]);
  const focus = (name) => {
    if (!S.avatars[name]) return;
    if (mode === "3d") { S.focus = name; S.focusUntil = (S.T || 0) + 5; }
    setCard(name);
  };
  const home = () => { setAuto(false); S.auto = false; S.view = { a: Math.PI / 4, zoom: 1, tx: 0, tz: 0, pan: { x: 0, y: 0 }, s: 1 }; };
  const goCinema = async () => { setCinema(true); setAuto(true); try { await wrap.current?.requestFullscreen?.(); } catch (e) {} };

  const info = S.info || {};
  const doing = (n) => {
    const st = data.members[n], a = S.avatars[n];
    if (st?.state === "working") return `作業中: ${st.desc}${st.job ? `(${st.job})` : ""}`;
    return ACT[a?.act] || "待機中";
  };
  const working = Object.entries(data.members).filter(([n, st]) => st.state === "working" && info[n]);
  const m = hover && info[hover.name];
  return (
    <div className={`office o3 o3-${mode}`} ref={wrap} onMouseMove={onMove} onMouseDown={onDown} onMouseUp={onUp}
         onMouseLeave={() => { S.drag = null; setHover(null); }} style={{ cursor: hover ? "pointer" : "grab" }}>
      <div className="o3-stage" ref={stageRef} style={mode === "art" ? { width: AW, height: AH } : null}>
        {mode === "art" && <img className="o3-bg" src="/office/art_wood.jpg" alt="" draggable={false} />}
      </div>
      <div className="o3-tint" style={{ background: tint }} />
      <div className="o3-overlay" ref={overlay} />
      {!cinema && (
        <div className={`office-now ${nowOpen ? "" : "closed"}`} onMouseDown={(e) => e.stopPropagation()} onMouseUp={(e) => e.stopPropagation()}>
          <button className="office-now-head" onClick={() => setNowOpen(!nowOpen)}><span className={`dot ${working.length ? "on" : ""}`} />いま作業中 {working.length}名 {nowOpen ? "▴" : "▾"}</button>
          {nowOpen && working.length === 0 && <div className="muted small">全員待機中です</div>}
          {nowOpen && working.map(([n, st]) => (
            <button key={n} className="office-now-row" onClick={() => focus(n)} title="押すとその社員を映します">
              <strong>{info[n].pname ? `${info[n].pname}(${info[n].title})` : info[n].title}</strong><span>{st.desc}</span>
            </button>
          ))}
        </div>
      )}
      {!cinema && <div className="office-legend small">{mode === "art" ? "イラスト版: 主な社員だけ映ります(作業中の人は必ず席に)" : "3D版: ドラッグで回転・ホイールで拡大"} ・ 休憩と立ち話は演出です ・ 詳しくはフロア図で</div>}
      <div className={`office-zoom ${cinema ? "cinema" : ""}`} onMouseDown={(e) => e.stopPropagation()} onMouseUp={(e) => e.stopPropagation()}>
        <button onClick={() => { setAuto(!auto); }} title={auto ? "自動カメラを止める" : "自動カメラで眺める"} className={auto ? "on" : ""}>{auto ? "■" : "▶"}</button>
        {!cinema && <><button onClick={() => { setAuto(false); zoom(1.2); }}>＋</button><button onClick={() => { setAuto(false); zoom(1 / 1.2); }}>−</button><button onClick={home}>⌂</button></>}
        <button onClick={() => (cinema ? document.exitFullscreen?.() : goCinema())} title={cinema ? "全画面を終える" : "全画面で眺める"}>{cinema ? "✕" : "⛶"}</button>
      </div>
      {card && !cinema && info[card] && (
        <div className="office-tag o3-tag" onMouseDown={(e) => e.stopPropagation()} onMouseUp={(e) => e.stopPropagation()}>
          <strong>{info[card].pname ? `${info[card].pname}(${info[card].title})` : info[card].title}</strong><span className="muted small">{info[card].dept}</span>
          <div className="small">{doing(card)}</div>
          <div className="office-tag-btns">
            {onShowFloor && <button className="link" onClick={() => onShowFloor(card)}>フロア図で詳しく ›</button>}
            <button className="link" onClick={() => setCard(null)}>閉じる</button>
          </div>
        </div>
      )}
      {hover && !card && !cinema && m && (
        <div className="office-tip" style={{ left: Math.min(hover.ex + 14, (wrap.current?.clientWidth || 600) - 290), top: hover.ey + 12 }}>
          <strong>{m.pname ? `${m.pname}(${m.title})` : m.title}{m.boss ? "(上司)" : ""}</strong><span className="muted small">{m.dept}</span>
          {m.persona && <div className="small persona">{m.persona}</div>}
          <div className="small">{doing(hover.name)}</div>
          <div className="muted small">押すと名刺を出します</div>
        </div>
      )}
    </div>
  );
}

const ASK = ["おつかれさまです", "コーヒー、もう1杯いきます?", "社長の判断待ち、今何件?", "差し戻しのログ、見ました?", "金曜の振り返り、何を見ます?",
  "次の企画、どうします?", "資料室のあの知見、読みました?", "その資料、あとで見せてください"];
const ANS = ["おつかれさまです!", "あと1杯だけ…", "秘書ハブで見られますよ", "見ました、気をつけます", "保存数と最後まで見た割合ですね",
  "読者の場面から考えたいです", "同じ失敗はしません!", "あとで共有しますね"];
