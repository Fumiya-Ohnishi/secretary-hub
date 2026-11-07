import * as THREE from "three";
import { RoundedBoxGeometry } from "three/examples/jsm/geometries/RoundedBoxGeometry.js";

/** 社員のアバター(3D)。見た目は名前から決まる(毎回同じ人に見える) */
export const SKIN = [0xf6dcc8, 0xefc9ae, 0xe3b591, 0xf3d2bd, 0xd9a582];
export const HAIR = [0x262a3f, 0x4a3426, 0x17171f, 0x6b4b2e, 0x3a3f66, 0x8a5a3a, 0x5a2f35, 0xc9a06a];
export const DEPT_COLOR = {
  秘書室: 0x8f96f0, 経営戦略部: 0x3f7fc4, 収益化部: 0xe0a93a, 企画編集部: 0xe0784a, ライティング部: 0xa877c9, デザイン部: 0xe2668f,
  画像制作部: 0x35ad9a, 映像制作部: 0x6c7ce0, SNS運用部: 0x35a3d6, 品質管理部: 0xd65a5a, データ分析部: 0x5fae5a,
};
export const hash = (s) => [...s].reduce((h, c) => (h * 31 + c.charCodeAt(0)) >>> 0, 7);

const cache = {};
const M = (c, o = {}) => {
  const k = c + JSON.stringify(o);
  return cache[k] || (cache[k] = new THREE.MeshStandardMaterial({ color: c, roughness: 0.75, metalness: 0, ...o }));
};
const G = {};
const geo = (k, f) => G[k] || (G[k] = f());

export function makeAvatar(name, dept, boss) {
  const h = hash(name);
  const shirt = DEPT_COLOR[dept] || 0x888888;
  const skin = M(SKIN[(h >> 3) % SKIN.length], { roughness: 0.7 });
  const hairM = M(HAIR[h % HAIR.length], { roughness: 0.5 });
  const style = (h >> 5) % 5; // 0短髪 1ロング 2ボブ 3おだんご 4つんつん
  const shirtM = M(shirt, { roughness: 0.8 });
  const outer = boss ? M(0x2b3140, { roughness: 0.7 }) : shirtM; // 上司はジャケット
  const pants = M((h >> 7) % 2 ? 0x2c3140 : 0x4a4f5c, { roughness: 0.85 });
  const g = new THREE.Group();

  const torso = new THREE.Mesh(geo("torso", () => new THREE.CapsuleGeometry(0.26, 0.42, 6, 14)), outer); torso.position.y = 1.15; g.add(torso);
  if (boss) { // ジャケットの中のシャツ
    const v = new THREE.Mesh(geo("vest", () => new THREE.BoxGeometry(0.2, 0.42, 0.05)), shirtM); v.position.set(0, 1.25, 0.245); g.add(v);
  }
  const neck = new THREE.Mesh(geo("neck", () => new THREE.CylinderGeometry(0.08, 0.09, 0.12)), skin); neck.position.y = 1.52; g.add(neck);
  const head = new THREE.Group(); head.position.y = 1.8; g.add(head);
  const skull = new THREE.Mesh(geo("skull", () => new THREE.SphereGeometry(0.28, 24, 18)), skin); skull.scale.set(1, 1.06, 1); head.add(skull);
  const cap = new THREE.Mesh(geo("hcap", () => new THREE.SphereGeometry(0.3, 24, 18, 0, Math.PI * 2, 0, Math.PI * 0.55)), hairM);
  cap.position.set(0, 0.03, -0.025); cap.rotation.x = -0.28; head.add(cap);
  const fringe = new THREE.Mesh(geo("fringe", () => new THREE.SphereGeometry(0.29, 20, 10, -Math.PI * 0.42, Math.PI * 0.84, 0, Math.PI * 0.32)), hairM);
  fringe.position.set(0, 0.05, 0.02); head.add(fringe);
  if (style === 1) { const b = new THREE.Mesh(geo("long", () => new THREE.CapsuleGeometry(0.25, 0.45, 6, 12)), hairM); b.position.set(0, -0.25, -0.12); head.add(b); }
  if (style === 2) { const b = new THREE.Mesh(geo("bob", () => new THREE.SphereGeometry(0.31, 20, 14, 0, Math.PI * 2, Math.PI * 0.3, Math.PI * 0.45)), hairM); b.position.set(0, -0.02, -0.03); head.add(b); }
  if (style === 3) { const b = new THREE.Mesh(geo("bun", () => new THREE.SphereGeometry(0.12, 12, 10)), hairM); b.position.set(0, 0.24, -0.22); head.add(b); }
  if (style === 4) for (let i = 0; i < 5; i++) {
    const s = new THREE.Mesh(geo("spike", () => new THREE.ConeGeometry(0.07, 0.18, 8)), hairM);
    const a = -0.9 + i * 0.45; s.position.set(Math.sin(a) * 0.18, 0.27, Math.cos(a) * 0.05 - 0.05); s.rotation.set(-0.3, 0, -a * 0.6); head.add(s);
  }
  const eyeM = M(0x1c1c22, { roughness: 0.25 }), white = M(0xffffff, { roughness: 0.2 });
  for (const ex of [-0.095, 0.095]) {
    const e = new THREE.Mesh(geo("eye", () => new THREE.SphereGeometry(0.038, 12, 10)), eyeM); e.scale.set(1, 1.25, 0.6); e.position.set(ex, 0.0, 0.262); head.add(e);
    const hl = new THREE.Mesh(geo("hl", () => new THREE.SphereGeometry(0.012, 8, 6)), white); hl.position.set(ex + 0.012, 0.018, 0.285); head.add(hl);
  }
  const blush = M(0xf2a5a0, { transparent: true, opacity: 0.55 });
  for (const ex of [-0.16, 0.16]) { const b = new THREE.Mesh(geo("blush", () => new THREE.CircleGeometry(0.04, 12)), blush); b.position.set(ex, -0.07, 0.255); b.rotation.y = ex * 1.6; head.add(b); }
  const mouth = new THREE.Mesh(geo("mouth", () => new THREE.TorusGeometry(0.035, 0.008, 6, 12, Math.PI)), M(0x9a4a4a)); mouth.position.set(0, -0.1, 0.268); mouth.rotation.z = Math.PI; head.add(mouth);

  const limbs = {};
  for (const [k, x] of [["armL", -0.34], ["armR", 0.34]]) {
    const pv = new THREE.Group(); pv.position.set(x, 1.38, 0);
    const a = new THREE.Mesh(geo("arm", () => new THREE.CapsuleGeometry(0.075, 0.42, 4, 10)), outer); a.position.y = -0.27; pv.add(a);
    const hd = new THREE.Mesh(geo("hand", () => new THREE.SphereGeometry(0.08, 10, 8)), skin); hd.position.y = -0.55; pv.add(hd);
    g.add(pv); limbs[k] = pv;
  }
  for (const [k, x] of [["legL", -0.13], ["legR", 0.13]]) {
    const pv = new THREE.Group(); pv.position.set(x, 0.82, 0);
    const l = new THREE.Mesh(geo("leg", () => new THREE.CapsuleGeometry(0.1, 0.5, 4, 10)), pants); l.position.y = -0.38; pv.add(l);
    const s = new THREE.Mesh(geo("shoe", () => new RoundedBoxGeometry(0.17, 0.1, 0.28, 2, 0.04)), M(0x1a1a1a)); s.position.set(0, -0.76, 0.05); pv.add(s);
    g.add(pv); limbs[k] = pv;
  }
  g.traverse((m) => { if (m.isMesh) { m.castShadow = true; m.userData.who = name; } });
  g.userData = { name, limbs, head, phase: (h % 100) / 10 };
  return g;
}

/** ポーズ: walk(歩く) / type(タイピング) / sit(座って休む) / sofa / talk(身振り) / stand */
export function pose(a, kind, t) {
  const { limbs, head } = a.userData;
  const reset = () => { for (const k of ["armL", "armR", "legL", "legR"]) limbs[k].rotation.set(0, 0, 0); head.rotation.set(0, 0, 0); };
  reset();
  if (kind === "walk") {
    const s = Math.sin(t * 7) * 0.6;
    limbs.legL.rotation.x = s; limbs.legR.rotation.x = -s; limbs.armL.rotation.x = -s * 0.8; limbs.armR.rotation.x = s * 0.8;
    a.position.y = Math.abs(Math.sin(t * 7)) * 0.05;
    return;
  }
  if (kind === "type" || kind === "sit" || kind === "sofa") {
    limbs.legL.rotation.x = limbs.legR.rotation.x = -1.45;
    a.position.y = kind === "sofa" ? 0.0 : 0.1;
    if (kind === "type") {
      const ty = Math.sin(t * 18) * 0.12;
      limbs.armL.rotation.x = -1.1 + ty; limbs.armR.rotation.x = -1.1 - ty;
      head.rotation.x = 0.12 + Math.sin(t * 0.7) * 0.05; head.rotation.y = Math.sin(t * 0.4) * 0.2;
    } else {
      limbs.armL.rotation.x = -0.5; limbs.armR.rotation.x = -0.7 + Math.sin(t * 1.3) * 0.15;
      head.rotation.y = Math.sin(t * 0.5) * 0.45; head.rotation.x = -0.05;
    }
    return;
  }
  a.position.y = 0;
  if (kind === "talk") {
    limbs.armR.rotation.x = -1.3 + Math.sin(t * 2.2) * 0.35; limbs.armR.rotation.z = 0.3;
    limbs.armL.rotation.x = -0.3 + Math.sin(t * 1.7) * 0.15;
    head.rotation.y = Math.sin(t * 0.9) * 0.3; head.rotation.x = Math.sin(t * 2.2) * 0.05;
  } else {
    limbs.armL.rotation.x = -0.15; limbs.armR.rotation.x = -0.15 + Math.sin(t * 0.8) * 0.05;
    head.rotation.y = Math.sin(t * 0.5) * 0.3;
  }
}
