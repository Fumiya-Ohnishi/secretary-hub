import * as THREE from "three";
import { RoundedBoxGeometry } from "three/examples/jsm/geometries/RoundedBoxGeometry.js";
import { DEPT_COLOR } from "./avatar.js";

/**
 * 3Dのオフィス(全部コードで組み立てる。外部の素材は使わない)
 * 部署ごとに長机の島。奥の壁に壁画とコーヒーカウンター、左の壁に資料室の本棚、右手前にラウンジ。
 */
export const FW = 36, FD = 28;
const COLS = [-12.6, -4.2, 4.5, 13.5], ROWS = [-8.6, -0.4, 8.2];
export const AISLES = [-4.6, 3.9];         // 机の島の間の通路(z)
export const CORRIDORS = [-8.4, 0.15, 9];       // 島の間の縦の通路(x)
export const DEPT_SLOTS = [
  ["秘書室", 0, 0], ["経営戦略部", 1, 0], ["収益化部", 2, 0], ["企画編集部", 3, 0],
  ["ライティング部", 0, 1], ["デザイン部", 1, 1], ["画像制作部", 2, 1], ["映像制作部", 3, 1],
  ["SNS運用部", 0, 2], ["品質管理部", 1, 2], ["データ分析部", 2, 2],
];
export const THEMES = {
  wood: { name: "木目", bg: 0x23262d, floor: 0xb98a5c, floorB: 0xa97a4e, wall: 0xeee9e1, wall2: 0x3b3f46, ceil: 0x8a5a32, table: 0x7a4f2c, metal: 0x2a2c31, rug: 0x55606b,
    mural: ["#1e8a86", "#f08a3c", "#f4efe6", "#24343c", "#f5c26b"], sofa: [0x8c5a3c, 0x5d6b62, 0x6c7a89], chair: 0x2f3238 },
  white: { name: "白", bg: 0x2a2d34, floor: 0xd9d4cc, floorB: 0xcfc9bf, wall: 0xf7f6f3, wall2: 0xffffff, ceil: 0xc6b49a, table: 0xc9a77f, metal: 0x3a3d44, rug: 0x7fb7b5,
    mural: ["#1f6fb2", "#f2c230", "#ffffff", "#1d2b45", "#7fc6e8"], sofa: [0x2f8f8a, 0xf2c230, 0xf08a3c], chair: 0xf08a3c },
  dark: { name: "黒", bg: 0x101216, floor: 0x2b2d33, floorB: 0x25272c, wall: 0x2f3238, wall2: 0x1e2025, ceil: 0x1a1b1f, table: 0x3a3029, metal: 0x111215, rug: 0x3c3f46,
    mural: ["#2a2d35", "#3b4250", "#ff9a3c", "#1d1f24", "#55606e"], sofa: [0x4a3f36, 0x5d6b62, 0x6c7a89], chair: 0x2f3238 },
};

export function buildOffice(scene, themeKey, departments) {
  const P = THEMES[themeKey] || THEMES.wood;
  const M = (c, o = {}) => new THREE.MeshStandardMaterial({ color: c, roughness: 0.75, metalness: 0, ...o });
  const mat = {
    wall: M(P.wall, { roughness: 0.9 }), wall2: M(P.wall2, { roughness: 0.85 }), wood: M(P.table, { roughness: 0.5 }), slat: M(P.ceil, { roughness: 0.6 }),
    metal: M(P.metal, { roughness: 0.35, metalness: 0.6 }), leaf: M(0x3f7a3a, { roughness: 0.8 }), leaf2: M(0x5d9a4a, { roughness: 0.8 }),
    pot: M(0xe9e3d8, { roughness: 0.6 }), potD: M(0x2b2b2b, { roughness: 0.6 }), white: M(0xf4f2ee), black: M(0x1c1d21, { roughness: 0.4 }),
    rug: M(P.rug, { roughness: 1 }), chair: M(P.chair, { roughness: 0.6 }),
    glass: new THREE.MeshPhysicalMaterial({ color: 0xdfefff, roughness: 0.05, transparent: true, opacity: 0.25 }),
    screenOff: new THREE.MeshStandardMaterial({ color: 0x15181d, roughness: 0.25, metalness: 0.2 }),
  };
  const root = new THREE.Group(); scene.add(root);
  const box = (w, h, d, m, x, y, z, r = 0.04, parent = root) => {
    const g = r ? new RoundedBoxGeometry(w, h, d, 2, Math.min(r, w / 2, h / 2, d / 2)) : new THREE.BoxGeometry(w, h, d);
    const o = new THREE.Mesh(g, m); o.position.set(x, y, z); o.castShadow = o.receiveShadow = true; parent.add(o); return o;
  };

  // 床(板張りの模様を描く)
  const c = document.createElement("canvas"); c.width = c.height = 1024; const g = c.getContext("2d");
  const base = new THREE.Color(P.floor), alt = new THREE.Color(P.floorB);
  let seed = 7; const rnd = () => ((seed = (seed * 16807) % 2147483647) / 2147483647);
  for (let y = 0; y < 1024; y += 32) {
    let x = -((y / 32) % 4) * 90;
    while (x < 1024) {
      const len = 220 + rnd() * 160; g.fillStyle = "#" + base.clone().lerp(alt, rnd()).getHexString(); g.fillRect(x, y, len, 31);
      g.globalAlpha = 0.06; for (let k = 0; k < 6; k++) { g.fillStyle = rnd() > 0.5 ? "#000" : "#fff"; g.fillRect(x, y + rnd() * 30, len, 1); }
      g.globalAlpha = 1; g.fillStyle = "rgba(0,0,0,.25)"; g.fillRect(x, y, 2, 31); x += len;
    }
    g.fillStyle = "rgba(0,0,0,.22)"; g.fillRect(0, y + 31, 1024, 1);
  }
  const ft = new THREE.CanvasTexture(c); ft.wrapS = ft.wrapT = THREE.RepeatWrapping; ft.repeat.set(3.6, 2.8); ft.colorSpace = THREE.SRGBColorSpace; ft.anisotropy = 8;
  const floor = new THREE.Mesh(new THREE.BoxGeometry(FW, 0.4, FD), M(0xffffff, { map: ft, roughness: 0.55 })); floor.position.y = -0.2; floor.receiveShadow = true; root.add(floor);

  // 壁(奥と左だけ。手前は切り取って中を見せる)
  box(FW, 6, 0.3, mat.wall, 0, 3, -FD / 2, 0);
  box(0.3, 6, FD, mat.wall, -FW / 2, 3, 0, 0);
  // 壁画
  const mc = document.createElement("canvas"); mc.width = 1600; mc.height = 500; const mg = mc.getContext("2d"); const cols = P.mural;
  mg.fillStyle = cols[2]; mg.fillRect(0, 0, 1600, 500);
  for (let i = 0; i < 26; i++) {
    mg.fillStyle = cols[i % cols.length]; mg.beginPath();
    const x = (i * 71) % 1600, y = (i * 137) % 500, s = 120 + (i * 53) % 220;
    if (i % 3 === 0) mg.arc(x, y, s / 2, 0, Math.PI * 2); else if (i % 3 === 1) { mg.moveTo(x, y); mg.lineTo(x + s, y); mg.lineTo(x, y + s); } else mg.rect(x, y, s, s * 0.6);
    mg.fill();
  }
  mg.fillStyle = cols[3]; mg.font = "bold 64px sans-serif"; mg.fillText("AI COMPANY", 60, 440);
  const mt = new THREE.CanvasTexture(mc); mt.colorSpace = THREE.SRGBColorSpace;
  const mural = new THREE.Mesh(new THREE.PlaneGeometry(14, 4.2), M(0xffffff, { map: mt, roughness: 0.9 })); mural.position.set(5, 3.2, -FD / 2 + 0.16); root.add(mural);
  // 窓(奥の壁の左)
  const winM = new THREE.MeshStandardMaterial({ color: 0xbfe0ff, emissive: 0xcfe6ff, emissiveIntensity: 0.6 });
  for (let i = 0; i < 3; i++) {
    const w = new THREE.Mesh(new THREE.PlaneGeometry(3.2, 3.6), winM); w.position.set(-15 + i * 3.6, 3.1, -FD / 2 + 0.17); root.add(w);
    box(0.12, 3.8, 0.1, mat.metal, -13.3 + i * 3.6, 3.1, -FD / 2 + 0.2, 0);
  }
  // 天井の木のルーバー(壁ぞいだけ)
  for (let i = 0; i < 55; i++) box(0.18, 0.25, 2.4, mat.slat, -FW / 2 + 0.5 + i * 0.64, 6.0, -FD / 2 + 1.2, 0.02);
  for (let i = 0; i < 42; i++) box(2.4, 0.25, 0.18, mat.slat, -FW / 2 + 1.2, 6.0, -FD / 2 + 0.6 + i * 0.64, 0.02);

  const lamps = [];
  const lampMat = new THREE.MeshStandardMaterial({ color: 0x222222, emissive: 0xffd9a0, emissiveIntensity: 1.2 });
  const pendant = (x, z) => {
    const cord = box(0.03, 2.0, 0.03, mat.black, x, 5.1, z, 0); cord.castShadow = false;
    const sh = new THREE.Mesh(new THREE.ConeGeometry(0.45, 0.45, 24, 1, true), mat.black); sh.position.set(x, 3.95, z); root.add(sh);
    const b = new THREE.Mesh(new THREE.SphereGeometry(0.16, 16, 12), lampMat); b.position.set(x, 3.78, z); root.add(b);
    const pl = new THREE.PointLight(0xffd29a, 4, 7, 1.6); pl.position.set(x, 3.6, z); root.add(pl); lamps.push(pl);
  };
  const chair = (x, z, rot) => {
    const cg = new THREE.Group();
    const s = new THREE.Mesh(new RoundedBoxGeometry(0.6, 0.12, 0.6, 2, 0.05), mat.chair); s.position.y = 0.55;
    const b = new THREE.Mesh(new RoundedBoxGeometry(0.6, 0.6, 0.1, 2, 0.04), mat.chair); b.position.set(0, 0.88, -0.32);
    const p = new THREE.Mesh(new THREE.CylinderGeometry(0.04, 0.04, 0.5), mat.metal); p.position.y = 0.27;
    const f = new THREE.Mesh(new THREE.CylinderGeometry(0.28, 0.28, 0.04, 16), mat.metal); f.position.y = 0.03;
    [s, b, p, f].forEach((m) => { m.castShadow = true; cg.add(m); });
    cg.position.set(x, 0, z); cg.rotation.y = rot; root.add(cg);
  };
  const plant = (x, z, s = 1, dark = false) => {
    box(0.55 * s, 0.6 * s, 0.55 * s, dark ? mat.potD : mat.pot, x, 0.3 * s, z, 0.1 * s);
    for (let i = 0; i < 9; i++) {
      const l = new THREE.Mesh(new THREE.SphereGeometry(0.32 * s, 10, 8), i % 2 ? mat.leaf : mat.leaf2); l.scale.set(1, 0.7, 1); const a = i * 0.7;
      l.position.set(x + Math.cos(a) * 0.25 * s, (0.9 + (i % 4) * 0.28) * s, z + Math.sin(a) * 0.25 * s); l.castShadow = true; root.add(l);
    }
  };
  const tallPlant = (x, z) => {
    box(0.6, 0.7, 0.6, mat.potD, x, 0.35, z, 0.1);
    const tr = new THREE.Mesh(new THREE.CylinderGeometry(0.05, 0.07, 2.2), M(0x6b4a2e)); tr.position.set(x, 1.8, z); root.add(tr);
    for (let i = 0; i < 14; i++) {
      const l = new THREE.Mesh(new THREE.SphereGeometry(0.42, 10, 8), i % 2 ? mat.leaf : mat.leaf2); const a = i * 1.3;
      l.position.set(x + Math.cos(a) * 0.45, 2.3 + (i % 5) * 0.25, z + Math.sin(a) * 0.45); l.scale.set(1, 0.6, 1); l.castShadow = true; root.add(l);
    }
  };
  const shelf = (x, z, w, rotY = 0) => {
    const sg = new THREE.Group();
    for (let i = 0; i < 5; i++) { const b = new THREE.Mesh(new THREE.BoxGeometry(w, 0.05, 0.45), mat.wood); b.position.y = 0.2 + i * 0.8; sg.add(b); }
    for (const sx of [-w / 2, w / 2]) { const p = new THREE.Mesh(new THREE.BoxGeometry(0.05, 3.6, 0.45), mat.metal); p.position.set(sx, 1.8, 0); sg.add(p); }
    const bc = [0xd9534f, 0x3f6fb5, 0xf2c230, 0x3a9b7a, 0xeeeeee, 0x8a5a9e, 0x222222, 0xf08a3c];
    for (let r = 0; r < 4; r++) {
      let bx = -w / 2 + 0.1;
      while (bx < w / 2 - 0.3) {
        if (rnd() < 0.15) { bx += 0.35; continue; }
        const bw = 0.06 + rnd() * 0.06, bh = 0.4 + rnd() * 0.25;
        const b = new THREE.Mesh(new THREE.BoxGeometry(bw, bh, 0.32), M(bc[(rnd() * bc.length) | 0])); b.position.set(bx, 0.23 + r * 0.8 + bh / 2, 0); sg.add(b); bx += bw + 0.01;
      }
    }
    sg.traverse((m) => { if (m.isMesh) m.castShadow = m.receiveShadow = true; });
    sg.position.set(x, 0, z); sg.rotation.y = rotY; root.add(sg);
  };
  const sofa = (x, z, w, color, rotY = 0) => {
    const sg = new THREE.Group(); const cm = M(color, { roughness: 0.95 });
    for (const [a, b, d, px, py, pz] of [[w, 0.45, 1.0, 0, 0.32, 0], [w, 0.75, 0.25, 0, 0.7, -0.4], [0.25, 0.6, 1.0, -w / 2 + 0.12, 0.55, 0], [0.25, 0.6, 1.0, w / 2 - 0.12, 0.55, 0]]) {
      const m = new THREE.Mesh(new RoundedBoxGeometry(a, b, d, 3, 0.1), cm); m.position.set(px, py, pz); m.castShadow = m.receiveShadow = true; sg.add(m);
    }
    sg.position.set(x, 0, z); sg.rotation.y = rotY; root.add(sg);
  };

  // 部署の島: 長机。上司は机の頭(左端)、担当は両側
  const seats = {}, labels = [], monitors = {};
  for (const [dept, ci, ri] of DEPT_SLOTS) {
    const ms = departments[dept] || []; if (!ms.length) continue;
    const cx = COLS[ci], cz = ROWS[ri];
    const boss = ms.filter((m) => m.boss), staff = ms.filter((m) => !m.boss);
    const per = Math.max(1, Math.ceil(staff.length / 2)), L = Math.max(2.6, per * 1.25 + 0.6);
    box(L, 0.08, 1.8, mat.wood, cx, 1.0, cz, 0.03);
    for (const sx of [-L / 2 + 0.25, L / 2 - 0.25]) box(0.08, 1.0, 1.6, mat.metal, cx + sx, 0.5, cz, 0);
    const rug = new THREE.Mesh(new RoundedBoxGeometry(L + 2.6, 0.03, 4.6, 2, 0.01), M(DEPT_COLOR[dept] || 0x888888, { roughness: 1, transparent: true, opacity: 0.18 }));
    rug.position.set(cx, 0.015, cz); rug.receiveShadow = true; root.add(rug);
    const aisle = ri === 0 ? AISLES[0] : AISLES[1];
    const addSeat = (m, x, z, rot, mx, mz, mrot) => {
      const mon = box(0.9, 0.55, 0.05, mat.screenOff, mx, 1.42, mz, 0.01); mon.rotation.y = mrot;
      box(0.06, 0.3, 0.06, mat.metal, mx, 1.18, mz, 0);
      chair(x, z, rot);
      monitors[m.name] = mon;
      seats[m.name] = { x, z, rot, dept, cx, cz, L, aisle, side: z > cz ? 1 : -1 };
    };
    staff.forEach((m, k) => {
      const side = k % 2 === 0 ? 1 : -1, i = Math.floor(k / 2), px = cx - L / 2 + 0.6 + (i + 0.5) * ((L - 0.6) / per);
      addSeat(m, px, cz + side * 1.15, side > 0 ? Math.PI : 0, px, cz + side * 0.35, side > 0 ? Math.PI : 0);
      box(0.5, 0.02, 0.18, mat.white, px, 1.05, cz + side * 0.62, 0.005);
    });
    boss.forEach((m, k) => {
      const bz = cz + (k - (boss.length - 1) / 2) * 0.9;
      addSeat(m, cx - L / 2 - 0.95, bz, Math.PI / 2, cx - L / 2 + 0.3, bz, -Math.PI / 2);
    });
    pendant(cx - L / 4, cz); pendant(cx + L / 4, cz);
    labels.push({ text: dept, pos: new THREE.Vector3(cx, 0.1, cz + (ri === 2 ? 2.6 : 2.5)) });
  }

  // ラウンジ(右手前)と会議の輪
  const LX = 13.6, LZ = 8.4;
  const lr = new THREE.Mesh(new THREE.CylinderGeometry(3.3, 3.3, 0.03, 48), mat.rug); lr.position.set(LX, 0.02, LZ); lr.receiveShadow = true; root.add(lr);
  sofa(LX, LZ - 2.4, 4, P.sofa[0], 0); sofa(LX + 2.8, LZ, 3, P.sofa[1], -Math.PI / 2); sofa(LX - 2.8, LZ, 3, P.sofa[2], Math.PI / 2);
  box(1.8, 0.4, 1.1, mat.wood, LX, 0.4, LZ, 0.08); box(0.3, 0.04, 0.3, mat.white, LX - 0.3, 0.62, LZ, 0.02);
  labels.push({ text: "ラウンジ", pos: new THREE.Vector3(LX, 0.1, LZ + 3.9) });
  // コーヒーカウンター(奥の壁)
  box(4.5, 1.1, 0.8, mat.wood, -2, 0.55, -FD / 2 + 0.7, 0.04); box(0.6, 0.7, 0.5, mat.black, -3.2, 1.45, -FD / 2 + 0.65, 0.05);
  labels.push({ text: "コーヒー", pos: new THREE.Vector3(-2, 0.1, -FD / 2 + 2.0) });
  // 資料室(左の壁の本棚と読書椅子)
  shelf(-FW / 2 + 0.45, -2.6, 4.6, Math.PI / 2); shelf(-FW / 2 + 0.45, 2.4, 4.6, Math.PI / 2); shelf(-FW / 2 + 0.45, 7.4, 4.6, Math.PI / 2);
  sofa(-FW / 2 + 2.3, 5.0, 1.6, 0x3b3f46, Math.PI / 2);
  labels.push({ text: "資料室", pos: new THREE.Vector3(-FW / 2 + 1.6, 0.1, 4.0) });
  // 植物
  plant(-FW / 2 + 0.7, -FD / 2 + 0.8, 1.1, true); tallPlant(1.6, -FD / 2 + 0.9); tallPlant(FW / 2 - 0.9, 3.0); plant(9.2, 12.6, 0.9);
  plant(-0.2, 12.6, 1); tallPlant(-FW / 2 + 0.9, 11.8); plant(FW / 2 - 0.8, 12.8, 1.1, true); plant(-9, -12.8, 0.8); plant(9, -12.8, 0.8, true);
  for (let i = 0; i < 4; i++) plant(7 + i * 3, -FD / 2 + 0.7, 0.6);

  const spots = {
    coffee: [[-3.0, -FD / 2 + 1.7, Math.PI], [-1.2, -FD / 2 + 1.8, Math.PI], [-0.2, -FD / 2 + 2.6, -Math.PI / 2]],
    sofa: [[LX - 1.0, LZ - 2.3, 0, "sofa", 9.9], [LX + 0.6, LZ - 2.3, 0, "sofa", 9.9], [LX + 2.7, LZ - 0.6, -Math.PI / 2, "sofa", 17.5], [LX - 2.7, LZ + 0.5, Math.PI / 2, "sofa", 9.9]],
    library: [[-FW / 2 + 1.3, -4.4, -Math.PI / 2], [-FW / 2 + 1.3, 3.3, -Math.PI / 2], [-FW / 2 + 2.3, 5.0, Math.PI / 2, "sofa"]],
    chat: [[[-9, -4.6, Math.PI / 2], [-8.1, -4.6, -Math.PI / 2]], [[0.4, 3.9, Math.PI / 2], [1.3, 3.9, -Math.PI / 2]], [[9, -4.6, 0], [9, -3.7, Math.PI]]],
    meet: [LX, LZ],
  };
  return { root, seats, labels, monitors, lamps, spots, theme: P };
}

/** 席 → 通路 → 目的地 の道順(机やソファを突っ切らない)。opts.ax=最後に縦に入る x、opts.front=ラウンジの輪へ手前から入る */
export function routeFromSeat(s, to, opts = {}) {
  const out = [s.x, s.cz + s.side * 2.1];
  if (s.x < s.cx - s.L / 2) out[1] = s.cz + (s.aisle > s.cz ? 2.1 : -2.1); // 上司は机の頭。通路側へ出てから回り込む
  const endX = to[0] < s.cx ? s.cx - s.L / 2 - 1.6 : s.cx + s.L / 2 + 1.2;
  const pts = [out, [endX, out[1]], [endX, s.aisle]];
  const corr = nearest(CORRIDORS, endX);
  const tAisle = to[1] < AISLES[0] ? AISLES[0] : to[1] > AISLES[1] ? AISLES[1] : nearest(AISLES, to[1]);
  if (tAisle !== s.aisle) pts.push([corr, s.aisle], [corr, tAisle]);
  if (opts.front) pts.push([9.9, tAisle], [9.9, 12.4], [to[0], 12.4]);
  else if (Math.abs(to[1] - tAisle) > 0.4) {
    const vx = opts.ax ?? (to[0] < -15 ? to[0] + 0.6 : nearest(CORRIDORS, to[0]));
    pts.push([vx, tAisle], [vx, to[1]]);
  } else pts.push([to[0], tAisle]);
  pts.push([to[0], to[1]]);
  return pts;
}
const nearest = (arr, v) => arr.reduce((a, b) => (Math.abs(b - v) < Math.abs(a - v) ? b : a));
