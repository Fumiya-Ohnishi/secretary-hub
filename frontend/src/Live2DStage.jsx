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
export default function Live2DStage({ mood, speaking, onError }) {
  const boxRef = useRef(null);
  const modelRef = useRef(null);
  const speakingRef = useRef(speaking);
  const [ready, setReady] = useState(false);

  speakingRef.current = speaking;

  useEffect(() => {
    let app = null;
    let disposed = false;

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

      // 口パク: 話している間、口の開き具合を滑らかにランダムに動かす(ブラウザ TTS は音量が取れないため)
      let mouth = 0, target = 0, nextChange = 0;
      model.internalModel.on("beforeModelUpdate", () => {
        const now = performance.now();
        if (speakingRef.current) {
          if (now > nextChange) { target = 0.2 + Math.random() * 0.8; nextChange = now + 70 + Math.random() * 90; }
        } else {
          target = 0;
        }
        mouth += (target - mouth) * 0.35;
        model.internalModel.coreModel.setParameterValueById("ParamMouthOpenY", mouth);
      });

      setReady(true);
    })().catch((e) => {
      console.warn("Live2D を表示できないため静止画に切り替えます:", e);
      if (!disposed) onError?.(e);
    });

    return () => {
      disposed = true;
      modelRef.current = null;
      if (app) app.destroy(true, { children: true });
    };
  }, []);

  useEffect(() => {
    if (ready && modelRef.current) modelRef.current.expression(mood || "normal");
  }, [mood, ready]);

  return <div className="live2d" ref={boxRef} aria-label="秘書" />;
}
