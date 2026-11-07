import React, { useEffect, useRef, useState } from "react";

const BASE = import.meta.env.BASE_URL;
const CORE_URL = `${BASE}live2d/core/live2dcubismcore.js`;
const MODEL_URL = `${BASE}live2d/secretary/secretary.model3.json`;
// 映し方: 全身 / 上半身(これまでの見え方) / アップ。z=画面の高さに対する倍率、top=上へずらす量(モデルの高さに対する割合)
export const VIEWS = { full: { label: "全身", z: 1.0, top: 0, center: true }, half: { label: "上半身", z: 1.12, top: 0 }, up: { label: "アップ", z: 1.85, top: 0.015 } };

/** Cubism Core(Live2D 公式の実行用ファイル)を <script> で読み込む。無ければ reject */
function loadCore() {
  if (window.Live2DCubismCore) return Promise.resolve();
  return new Promise((resolve, reject) => {
    const s = document.createElement("script");
    s.src = CORE_URL;
    s.onload = () => (window.Live2DCubismCore ? resolve() : reject(new Error("Cubism Core が初期化されませんでした")));
    s.onerror = () => reject(new Error(`${CORE_URL} が見つかりません`));
    document.head.appendChild(s);
  });
}

/**
 * Cubism Core 6 との互換処理。
 * pixi-live2d-display 0.4 は描画順を drawables.renderOrders から読むが、Core 6 では
 * model.getRenderOrders() に移ったため、同じ配列(描画物の分)を drawables 側にも置く。
 */
function patchCoreForPixiLive2D() {
  const { Model } = window.Live2DCubismCore;
  if (Model.__patchedRenderOrders) return;
  const fromMoc = Model.fromMoc;
  Model.fromMoc = function (moc) {
    const model = fromMoc.call(this, moc);
    if (model && model.drawables && !model.drawables.renderOrders && model.getRenderOrders) {
      model.drawables.renderOrders = model.getRenderOrders().subarray(0, model.drawables.count);
    }
    return model;
  };
  Model.__patchedRenderOrders = true;
}

/**
 * Live2D の秘書。気分(mood)を表情に、話し中(speaking)を口パクに反映する。
 * 自動まばたき・呼吸はモデルの設定(EyeBlink / ParamBreath)で動く。
 * Core やモデルが読み込めなければ onError を呼ぶ(呼び出し側で静止画に戻す)。
 */
/* ---------- 人らしい動き(手付けのモーションが無いので、コードで作る) ----------
 * ・待機: 頭と体がゆっくり揺れる。ときどき目線と顔を横へ流す
 * ・話す: 声の強さに合わせてうなずく・眉が上がる・体が前へ。文の切れ目で首をかしげる向きを変える
 * ・聞く: 首をかしげて少し前のめり。ときどき小さくうなずく
 * ・考える: 目線と顔を斜め上へ
 * ・気分が変わった瞬間: 喜ぶ=小さく弾む / むっ=顔をそむける / 考える=首をかしげる
 * ・髪: 頭の動きの速さに遅れてついてくるバネで揺らす(+わずかな風)
 */
const clampN = (v, a, b) => Math.max(a, Math.min(b, v));
function smoothNoise(seed) {
  const ph = [0, 1, 2].map((i) => Math.sin(seed * 12.9898 + i * 78.233) * 43758.5453 % (Math.PI * 2));
  return (t) => (Math.sin(t * 0.31 + ph[0]) * 0.5 + Math.sin(t * 0.73 + ph[1]) * 0.33 + Math.sin(t * 1.37 + ph[2]) * 0.17);
}
function spring(k = 60, d = 9) {
  let x = 0, v = 0;
  return { step(target, dt) { const a = k * (target - x) - d * v; v += a * dt; x += v * dt; return x; }, get value() { return x; } };
}

export default function Live2DStage({ mood, speaking, levelRef, onError, state = "idle", view = "half" }) {
  const boxRef = useRef(null);
  const modelRef = useRef(null);
  const speakingRef = useRef(speaking);
  const stateRef = useRef(state);
  const gestureRef = useRef(null);   // { kind, start } 気分が変わった瞬間の一回きりの動き
  const viewRef = useRef(view);
  const fitRef = useRef(null);
  viewRef.current = VIEWS[view] ? view : "half";
  const [ready, setReady] = useState(false);

  speakingRef.current = speaking;
  // 動作確認用: URL に ?sena=listening などを付けると、その状態の動きを見られる
  const forced = typeof location !== "undefined" ? new URLSearchParams(location.search).get("sena") : null;
  stateRef.current = forced || (speaking ? "speaking" : state);
  if (forced === "speaking") speakingRef.current = true;

  useEffect(() => {
    let app = null;
    let disposed = false;
    let onMove = null;

    (async () => {
      await loadCore();
      patchCoreForPixiLive2D();
      // Core が window に居る状態で読み込む必要がある
      const PIXI = await import("pixi.js");
      const { Live2DModel } = await import("pixi-live2d-display/cubism4");
      if (disposed) return;
      Live2DModel.registerTicker(PIXI.Ticker);

      const box = boxRef.current;
      app = new PIXI.Application({ resizeTo: box, backgroundAlpha: 0, antialias: true, autoDensity: true,
                                   resolution: window.devicePixelRatio || 1 });
      box.appendChild(app.view);

      const model = await Live2DModel.from(MODEL_URL, { autoInteract: false });
      if (disposed) { model.destroy(); return; }
      modelRef.current = model;
      app.stage.addChild(model);

      let base = { x: 0, y: 0, w: 0, h: 0 };
      let target = null; // 映し方を変えたときは、なめらかに寄る・引く
      const fit = (instant = false) => {
        const { width, height } = app.screen;
        const oh = model.internalModel.originalHeight, ow = model.internalModel.originalWidth;
        const v = VIEWS[viewRef.current];
        let sc = (height / oh) * v.z;
        if (v.center) sc = Math.min(sc, (width / ow) * 0.98);
        const w = ow * sc, h = oh * sc;
        const t = { x: (width - w) / 2, y: v.center ? (height - h) / 2 : -h * v.top, w, h, sc };
        if (instant || !base.w) { target = null; model.scale.set(sc); base = { x: t.x, y: t.y, w, h, sc }; model.x = t.x; model.y = t.y; }
        else target = t;
      };
      fitRef.current = () => fit(false);
      const stepView = (dt) => {
        if (!target) return;
        const k = Math.min(1, dt * 6);
        for (const key of ["x", "y", "w", "h", "sc"]) base[key] += (target[key] - base[key]) * k;
        model.scale.set(base.sc);
        if (Math.abs(target.sc - base.sc) < 1e-4 && Math.abs(target.y - base.y) < 0.5) { Object.assign(base, target); model.scale.set(base.sc); target = null; }
      };
      fit(true);
      app.renderer.on("resize", () => fit(true));

      // 目線: マウスの方を見る(画面の外ならゆっくり正面に戻る)
      onMove = (e) => {
        const r = app.view.getBoundingClientRect();
        model.focus(e.clientX - r.left, e.clientY - r.top);
      };
      window.addEventListener("pointermove", onMove);

      // 口パク: VOICEVOX の声なら実際の音量(levelRef)に合わせて開く。
      // ブラウザの声は音量が取れないため、「1音ずつ開いて閉じる」動きを作る
      // (1音 = 130〜220ms。開き具合は音ごとに少し変え、ときどき短い間(ま)を入れる)
      let mouth = 0, sylStart = 0, sylLen = 0, sylAmp = 0;
      const core = model.internalModel.coreModel;

      // 口の見え方の補正(リギングの作りに合わせる):
      // ・閉じた唇の線(mouth)は、口が開くほど薄くする(開いた口の真ん中に線が残らないように)
      // ・口の中(mouth_inner)は少し開いた時点で濃くする(半透明で透けて見えないように)
      const drawableIds = core.getModel().drawables.ids;
      const lineIdx = drawableIds.indexOf("mouth");
      const innerIdx = drawableIds.indexOf("mouth_inner");
      const getOpacity = core.getDrawableOpacity.bind(core);
      core.getDrawableOpacity = (i) => {
        const o = getOpacity(i);
        if (i === lineIdx) return o * Math.max(0, 1 - mouth * 3.5);
        if (i === innerIdx) return Math.min(1, o * 5);
        return o;
      };

      model.internalModel.on("beforeModelUpdate", () => {
        const now = performance.now();
        const level = levelRef?.current;
        let target = 0;
        if (speakingRef.current && level != null) {
          target = level < 0.02 ? 0 : Math.min(1, (level - 0.02) * 6);
        } else if (speakingRef.current) {
          if (now - sylStart >= sylLen) {
            sylStart = now;
            sylLen = 130 + Math.random() * 90;
            sylAmp = Math.random() < 0.12 ? 0.15 : 0.55 + Math.random() * 0.45;
          }
          target = sylAmp * Math.sin(Math.PI * Math.min(1, (now - sylStart) / sylLen));
        }
        mouth += (target - mouth) * 0.5;
        model.internalModel.coreModel.setParameterValueById("ParamMouthOpenY", mouth);
        animate(now, mouth);
      });

      /* ---- 体・頭・目・眉・髪 ---- */
      const nHead = [smoothNoise(1), smoothNoise(2), smoothNoise(3)], nBody = [smoothNoise(4), smoothNoise(5)], nWind = smoothNoise(6);
      const sp = {}; // 目標へなめらかに寄せる値
      const ease = (key, target, rate, dt) => { const v = sp[key] ?? 0; sp[key] = v + (target - v) * Math.min(1, rate * dt); return sp[key]; };
      const hair = { front: spring(55, 7), side: spring(45, 6), back: spring(35, 5) };
      let last = performance.now(), prevHeadX = 0, prevHeadZ = 0, prevBodyX = 0;
      let glance = { until: 0, next: performance.now() + 3000, x: 0, y: 0 };
      let tiltSign = 1, lastSpeakEdge = 0, nodNext = 0, nodStart = -1e9, wasLoud = false;
      const add = (id, v) => core.addParameterValueById(id, v);
      const get = (id) => core.getParameterValueById(id);

      function animate(now, mouthOpen) {
        const dt = Math.min(0.05, (now - last) / 1000); last = now;
        stepView(dt);
        const t = now / 1000, st = stateRef.current;
        const level = speakingRef.current ? (levelRef?.current != null ? clampN((levelRef.current - 0.02) * 6, 0, 1) : mouthOpen) : 0;

        // 目線をときどき外す(人は話を聞いていても、たまに視線を流す)
        if (now > glance.next && st !== "listening") {
          glance = { until: now + 700 + Math.random() * 1600, next: now + 3500 + Math.random() * 6000,
                     x: (Math.random() < 0.5 ? -1 : 1) * (0.4 + Math.random() * 0.5), y: (Math.random() - 0.4) * 0.6 };
        }
        const gl = now < glance.until ? 1 : 0;

        let hx = nHead[0](t) * 5, hy = nHead[1](t) * 3, hz = nHead[2](t) * 4, bx = nBody[0](t) * 3, bz = nBody[1](t) * 2, by = 0;
        let ex = gl * glance.x, ey = gl * glance.y, brow = 0;
        hx += gl * glance.x * 9; hy += gl * glance.y * 5;

        if (st === "speaking") {
          // 声の山でうなずく(下を向いて戻る)。強くなった瞬間に眉が上がる
          if (level > 0.55 && !wasLoud && now - nodStart > 450) nodStart = now;
          wasLoud = level > 0.45;
          if (now - lastSpeakEdge > 2600 + Math.random() * 2000) { tiltSign = -tiltSign; lastSpeakEdge = now; }
          hz += tiltSign * 7; bz += tiltSign * 2.5; by += 3; hy += level * 4; brow += level * 0.6; hx += tiltSign * 4;
          bx += Math.sin(t * 2.1) * 1.5; // 話しながら体が少し揺れる
        } else if (st === "listening") {
          hz += 12; by += 4; hy -= 2; ex *= 0.2; ey *= 0.2; brow += 0.2;
          if (now > nodNext) { nodStart = now; nodNext = now + 1800 + Math.random() * 2500; }
        } else if (st === "thinking") {
          hx -= 18; hy += 12; hz -= 8; ex = -0.8; ey = 0.9; brow += 0.35; bx -= 4;
        }
        const nodT = (now - nodStart) / 420;
        const nod = nodT >= 0 && nodT < 1 ? Math.sin(Math.PI * nodT) : 0;
        hy -= nod * (st === "listening" ? 7 : 9);

        // 気分が変わった瞬間の一回きりの動き
        const g = gestureRef.current;
        if (g) {
          const p = (now - g.start) / 1000;
          if (g.kind === "pleased" && p < 0.9) { const b = Math.sin(Math.PI * Math.min(1, p / 0.45)) * (p < 0.45 ? 1 : 0.4); by += b * 4; hy += b * 6; bz += b * 2; }
          else if (g.kind === "pouty" && p < 2.2) { const w = Math.min(1, p / 0.25) * Math.min(1, (2.2 - p) / 0.5); hx += w * 16; hz -= w * 6; ex += w * 0.7; }
          else if (g.kind === "thinking" && p < 1.6) { const w = Math.min(1, p / 0.3) * Math.min(1, (1.6 - p) / 0.4); hz -= w * 10; hy += w * 4; }
          else if (p > 2.5) gestureRef.current = null;
        }

        const k = 6;
        add("ParamAngleX", ease("hx", hx, k, dt)); add("ParamAngleY", ease("hy", hy, k * 1.4, dt)); add("ParamAngleZ", ease("hz", hz, k, dt));
        add("ParamBodyAngleX", ease("bx", bx, 4, dt)); add("ParamBodyAngleY", ease("by", by, 4, dt)); add("ParamBodyAngleZ", ease("bz", bz, 4, dt));
        add("ParamEyeBallX", ease("ex", ex, 14, dt)); add("ParamEyeBallY", ease("ey", ey, 14, dt));
        const br = ease("brow", brow, 10, dt);
        add("ParamBrowLY", br); add("ParamBrowRY", br);

        // 体全体: 体の向きに合わせてわずかに傾け、弾むときは上下させる(足元を軸に)
        let lift = 0;
        if (g && g.kind === "pleased") { const p = (now - g.start) / 1000; if (p < 0.9) lift = Math.max(0, Math.sin(Math.PI * Math.min(1, p / 0.45))) * (p < 0.45 ? 1 : 0.3); }
        const rot = ease("rot", (bz * 0.006) + (st === "listening" ? 0.012 : 0) + (st === "speaking" ? Math.sin(t * 1.3) * 0.006 : 0), 3, dt);
        const lift2 = ease("lift", lift, 12, dt);
        if (base.w) {
          // 画面の下の真ん中(体の付け根あたり)を軸に回す
          const px = base.x + base.w / 2, py = app.screen.height;
          const ox = base.x + (st === "listening" ? base.w * 0.01 : 0) - px;
          const oy = base.y - lift2 * base.h * 0.018 + (st === "listening" ? base.h * 0.008 : 0) - py;
          const c = Math.cos(rot), s2 = Math.sin(rot);
          model.rotation = rot;
          model.x = px + c * ox - s2 * oy;
          model.y = py + s2 * ox + c * oy;
        }

        // 髪: 頭と体の動きの速さに遅れてついてくる
        const HX = get("ParamAngleX"), HZ = get("ParamAngleZ"), BX = get("ParamBodyAngleX");
        const vx = (HX - prevHeadX) / Math.max(dt, 1e-3), vz = (HZ - prevHeadZ) / Math.max(dt, 1e-3), vb = (BX - prevBodyX) / Math.max(dt, 1e-3);
        prevHeadX = HX; prevHeadZ = HZ; prevBodyX = BX;
        const wind = nWind(t * 1.7) * 0.12;
        core.setParameterValueById("ParamHairFront", clampN(hair.front.step(-(vx * 0.018 + vz * 0.01) + wind, dt), -1, 1));
        core.setParameterValueById("ParamHairSide", clampN(hair.side.step(-(vz * 0.025 + vb * 0.02) + wind * 1.3, dt), -1, 1));
        core.setParameterValueById("ParamHairBack", clampN(hair.back.step(-(vx * 0.012 + vb * 0.03) + wind * 0.8, dt), -1, 1));
      }

      setReady(true);
    })().catch((e) => {
      console.warn("Live2D を表示できないため静止画に切り替えます:", e);
      if (!disposed) onError?.(e);
    });

    return () => {
      disposed = true;
      if (onMove) window.removeEventListener("pointermove", onMove);
      modelRef.current = null;
      if (app) app.destroy(true, { children: true });
    };
  }, []);

  useEffect(() => {
    if (ready && modelRef.current) modelRef.current.expression(mood || "normal");
    if (ready && mood && mood !== "normal") gestureRef.current = { kind: mood, start: performance.now() };
  }, [mood, ready]);

  useEffect(() => { fitRef.current?.(); }, [view]);

  return <div className="live2d" ref={boxRef} aria-label="秘書" />;
}
