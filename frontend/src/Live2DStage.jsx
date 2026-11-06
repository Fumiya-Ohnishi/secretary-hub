import React, { useEffect, useRef, useState } from "react";

const BASE = import.meta.env.BASE_URL;
const CORE_URL = `${BASE}live2d/core/live2dcubismcore.js`;
const MODEL_URL = `${BASE}live2d/secretary/secretary.model3.json`;
// モデルのキャンバス(正方形)に対して、表示する範囲の倍率。1 で全身が縦に収まる
const ZOOM = 1.12;

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
export default function Live2DStage({ mood, speaking, levelRef, onError }) {
  const boxRef = useRef(null);
  const modelRef = useRef(null);
  const speakingRef = useRef(speaking);
  const [ready, setReady] = useState(false);

  speakingRef.current = speaking;

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

      const fit = () => {
        const { width, height } = app.screen;
        const size = model.internalModel.originalHeight;
        model.scale.set((height / size) * ZOOM);
        model.x = (width - model.width) / 2;
        model.y = 0;
      };
      fit();
      app.renderer.on("resize", fit);

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
      });

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
  }, [mood, ready]);

  return <div className="live2d" ref={boxRef} aria-label="秘書" />;
}
