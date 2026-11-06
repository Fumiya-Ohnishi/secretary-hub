/**
 * リール制作スタジオ(1080×1920)。tools/reel/render_reel.mjs が開いて、1コマずつ描かせて録画する。
 *   window.reelSetup(spec, timeline) … 台本と時間割を受け取る
 *   window.reelFrame(i)              … i コマ目を描く(Live2D は 1/fps 秒だけ進める)
 * 画面の見た目は ai-company/brand/guide.md の3テーマ(A/B/C)とリールの安全範囲に合わせる。
 */
import "./reel.css";

const BASE = import.meta.env.BASE_URL;
const CORE_URL = `${BASE}live2d/core/live2dcubismcore.js`;
const MODEL_URL = `${BASE}live2d/secretary/secretary.model3.json`;
const W = 1080, H = 1920, STAGE_H = 1360, FIT_H = 1150; // 体は画面の下端まで描く(大きさは FIT_H で決める)

const root = document.getElementById("reel");
root.innerHTML = `
  <div class="reel" id="r">
    <div class="bg"></div>
    <div class="progress"><span id="bar"></span></div>
    <div class="tag" id="tag"></div>
    <h1 class="title" id="title"></h1>
    <div class="stage" id="stage"></div>
    <div class="panel" id="panel"></div>
    <div class="caption" id="caption"></div>
    <div class="foot"><span>※AIの秘書キャラクターです</span><span id="credit"></span></div>
  </div>`;
const $ = (id) => document.getElementById(id);
const esc = (s) => String(s ?? "").replace(/[&<>]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;" }[c]));
const md = (s) => esc(s).replace(/\*\*(.+?)\*\*/g, '<span class="em">$1</span>').replace(/\{\{(.+?)\}\}/g, '<span class="num">$1</span>').replace(/\n/g, "<br>");

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

let app, model, mouth = 0, level = 0, mood = null, spec = null, tl = null;

async function init() {
  await loadCore();
  const { Model } = window.Live2DCubismCore;
  if (!Model.__patchedRenderOrders) { // Cubism Core 6 との互換(Live2DStage.jsx と同じ)
    const fromMoc = Model.fromMoc;
    Model.fromMoc = function (moc) {
      const m = fromMoc.call(this, moc);
      if (m && m.drawables && !m.drawables.renderOrders && m.getRenderOrders) m.drawables.renderOrders = m.getRenderOrders().subarray(0, m.drawables.count);
      return m;
    };
    Model.__patchedRenderOrders = true;
  }
  const PIXI = await import("pixi.js");
  const { Live2DModel } = await import("pixi-live2d-display/cubism4");
  Live2DModel.registerTicker(PIXI.Ticker);
  PIXI.Ticker.shared.autoStart = false;
  PIXI.Ticker.shared.stop();
  app = new PIXI.Application({ width: W, height: STAGE_H, backgroundAlpha: 0, antialias: true, autoStart: false,
                               preserveDrawingBuffer: true, resolution: 1 });
  app.ticker.stop();
  $("stage").appendChild(app.view);
  model = await Live2DModel.from(MODEL_URL, { autoInteract: false, autoUpdate: false });
  app.stage.addChild(model);
  const size = model.internalModel.originalHeight;
  model.scale.set((FIT_H / size) * 1.25);
  model.x = (W - model.width) / 2;
  model.y = 0;

  // 口の見え方の補正(Live2DStage.jsx と同じ)
  const core = model.internalModel.coreModel;
  const ids = core.getModel().drawables.ids;
  const lineIdx = ids.indexOf("mouth"), innerIdx = ids.indexOf("mouth_inner");
  const getOpacity = core.getDrawableOpacity.bind(core);
  core.getDrawableOpacity = (i) => {
    const o = getOpacity(i);
    if (i === lineIdx) return o * Math.max(0, 1 - mouth * 3.5);
    if (i === innerIdx) return Math.min(1, o * 5);
    return o;
  };
  model.internalModel.on("beforeModelUpdate", () => {
    const target = level < 0.02 ? 0 : Math.min(1, (level - 0.02) * 6);
    mouth += (target - mouth) * 0.6;
    core.setParameterValueById("ParamMouthOpenY", mouth);
  });
  await document.fonts.ready;
}
const ready = init().then(() => true).catch((e) => { console.error(e); return String(e); });
window.reelReady = () => ready;

window.reelSetup = (s, timeline) => {
  spec = s; tl = timeline;
  const r = $("r");
  r.className = `reel ${s.theme || "B"}`;
  $("tag").innerHTML = s.theme === "B" ? `SECRETARY SENA // ${esc(s.series || "AI WORK")}` : `AI秘書セナの${esc(s.series || "")}`;
  $("title").innerHTML = md(s.title || "");
  $("credit").textContent = s.credit || "";
  return true;
};

window.reelFrame = (i) => {
  const t = i / tl.fps;
  $("bar").style.width = `${Math.min(100, (t / tl.duration) * 100)}%`;
  const cur = tl.lines.find((l) => t >= l.start && t < l.end + tl.gap) || null;
  const line = cur ? spec.lines[cur.index] : null;
  $("caption").innerHTML = line ? md(line.caption ?? line.text) : "";
  $("caption").style.visibility = line ? "visible" : "hidden";
  const panel = line?.panel || "";
  $("panel").innerHTML = md(panel);
  $("panel").style.display = panel ? "block" : "none";
  const want = (line?.mood) || spec.mood || "normal";
  if (want !== mood) { mood = want; try { model.expression(want); } catch (e) {} }
  level = tl.levels[i] || 0;
  model.update(1000 / tl.fps);
  app.renderer.render(app.stage);
  return t;
};
