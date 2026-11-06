import { useEffect, useRef, useState } from "react";

/** 音声入力(ブラウザ音声認識)。1回の発話ごとに認識する。ハンズフリーは呼び出し側が start を繰り返す */
// 音声認識のエラーを社長向けの説明に直す
const RECOGNITION_ERRORS = {
  "not-allowed": "マイクの使用が許可されていません。アドレスバーの鍵アイコンからマイクを「許可」にしてください。",
  "service-not-allowed": "このブラウザでは音声認識が使えません。Chrome か Safari で開いてください。",
  network: "音声認識サーバーに接続できません。Brave などでは使えないため、Chrome か Safari で開いてください。",
  "audio-capture": "マイクが見つかりません。Mac のマイク設定を確認してください。",
};

export function useSpeechInput(onFinal, onError) {
  const [recording, setRecording] = useState(false);
  const [supported, setSupported] = useState(false);
  const [unsupportedReason, setUnsupportedReason] = useState("このブラウザは音声認識非対応です(Chrome か Safari で開いてください)");
  const recRef = useRef(null);
  // コールバックは毎回作り直されるので ref 経由で最新を呼ぶ(認識の仕組みは1回だけ作る)
  const onFinalRef = useRef(onFinal);
  const onErrorRef = useRef(onError);
  onFinalRef.current = onFinal;
  onErrorRef.current = onError;

  useEffect(() => {
    const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (!SR) return;
    // Brave は SpeechRecognition を持っているが、認識サーバーに繋がらず動かない
    if (navigator.brave) {
      setUnsupportedReason("Brave では音声認識が使えません。Chrome か Safari で開いてください");
      return;
    }
    setSupported(true);
    const rec = new SR();
    rec.lang = "ja-JP";
    rec.interimResults = true;
    let finalText = "";
    rec.onstart = () => { setRecording(true); finalText = ""; };
    rec.onresult = (e) => {
      let interim = "";
      for (let i = e.resultIndex; i < e.results.length; i++) {
        if (e.results[i].isFinal) finalText += e.results[i][0].transcript;
        else interim += e.results[i][0].transcript;
      }
      onFinalRef.current(null, finalText || `（聞いています… ${interim}）`);
    };
    rec.onend = () => { setRecording(false); if (finalText.trim()) onFinalRef.current(finalText.trim()); };
    rec.onerror = (e) => {
      setRecording(false);
      onErrorRef.current?.(RECOGNITION_ERRORS[e.error] || "", e.error);
    };
    recRef.current = rec;
    return () => rec.abort();
  }, []);

  const start = () => { try { recRef.current?.start(); } catch (e) {} };
  const stop = () => { try { recRef.current?.stop(); } catch (e) {} };
  return { recording, supported, unsupportedReason, start, stop };
}

// 女性の声を優先して選ぶ(上ほど優先)。前回選んだ声があればそれを使う
const PREFERRED_VOICES = ["O-ren", "Kyoko", "Google 日本語", "Microsoft Nanami", "Haruka", "Ayumi"];
const VOICE_KEY = "secretary-voice";

function pickVoice(list) {
  let saved = "";
  try { saved = localStorage.getItem(VOICE_KEY) || ""; } catch (e) {}
  if (saved && list.some((v) => v.name === saved)) return saved;
  for (const want of PREFERRED_VOICES) {
    // 高音質版(拡張/プレミアム)があればそちらを選ぶ
    const hits = list.filter((v) => v.name.includes(want));
    const best = hits.find((v) => /拡張|プレミアム|Enhanced|Premium/.test(v.name)) || hits[0];
    if (best) return best.name;
  }
  return (list[0] && list[0].name) || "";
}

const VV_VOICE_KEY = "secretary-voice-voicevox";

function loadSaved(key) {
  try { return localStorage.getItem(key) || ""; } catch (e) { return ""; }
}
function save(key, value) {
  try { localStorage.setItem(key, value); } catch (e) {}
}

/**
 * 音声出力。VOICEVOX(無料の読み上げソフト)が起動していればその声、無ければブラウザの声で話す。
 * VOICEVOX のときは levelRef.current に今の音量(0〜1)が入るので、口パクに使える
 * (ブラウザの声のときは null)。
 */
export function useSpeechOutput() {
  const [engine, setEngine] = useState("browser");
  const engineRef = useRef("browser");
  const [voices, setVoices] = useState([]); // [{ value, label }]
  const [voiceValue, setVoiceValueState] = useState("");
  // 話す処理は古い画面の状態から呼ばれることがあるので、声の設定は常に ref から読む
  const voiceRef = useRef("");
  const setVoiceValue = (v) => {
    setVoiceValueState((prev) => {
      const next = typeof v === "function" ? v(prev) : v;
      voiceRef.current = next;
      return next;
    });
  };
  const [speaking, setSpeaking] = useState(false);
  const levelRef = useRef(null);
  const audioRef = useRef({ ctx: null, source: null });
  const browserVoicesRef = useRef([]);

  useEffect(() => {
    let cancelled = false;
    const loadBrowserVoices = () => {
      if (!("speechSynthesis" in window)) return [];
      const all = speechSynthesis.getVoices();
      const ja = all.filter((v) => v.lang && v.lang.toLowerCase().startsWith("ja"));
      browserVoicesRef.current = ja.length ? ja : all;
      return browserVoicesRef.current;
    };
    const useBrowser = () => {
      const list = loadBrowserVoices();
      setEngine("browser");
      setVoices(list.map((v) => ({ value: v.name, label: v.name })));
      setVoiceValue((prev) => prev || pickVoice(list));
    };
    if ("speechSynthesis" in window) {
      // ブラウザの声の一覧は後から届くことがある
      speechSynthesis.onvoiceschanged = () => { if (!cancelled && engineRef.current === "browser") useBrowser(); };
    }
    // VOICEVOX があればその声に。後から VOICEVOX を起動しても、20秒以内に自動で切り替わる
    const detect = (first) => fetch("/api/tts/speakers").then((r) => r.json()).then((d) => {
      if (cancelled || engineRef.current === "voicevox") return;
      if (!d.available) return first ? useBrowser() : undefined;
      engineRef.current = "voicevox";
      setEngine("voicevox");
      setVoices(d.speakers.map((sp) => ({ value: String(sp.id), label: sp.name })));
      const saved = loadSaved(VV_VOICE_KEY);
      setVoiceValue(d.speakers.some((sp) => String(sp.id) === saved) ? saved : String(d.default));
      loadBrowserVoices(); // VOICEVOX が落ちたときの予備
    }).catch(() => { if (!cancelled && first) useBrowser(); });
    detect(true);
    const recheck = setInterval(() => { if (engineRef.current === "browser") detect(false); }, 20000);

    // ブラウザは「ユーザー操作の後」でないと音を鳴らせないので、最初の操作で音声の準備をしておく
    const unlock = () => {
      const a = audioRef.current;
      if (!a.ctx) a.ctx = new (window.AudioContext || window.webkitAudioContext)();
      a.ctx.resume();
    };
    window.addEventListener("pointerdown", unlock);
    window.addEventListener("keydown", unlock);
    return () => {
      cancelled = true;
      clearInterval(recheck);
      window.removeEventListener("pointerdown", unlock);
      window.removeEventListener("keydown", unlock);
    };
  }, []);

  /* ---- 読み上げの順番待ち(1文ずつ。VOICEVOX は次の文の音声を先に作っておく) ---- */
  const queueRef = useRef([]);      // [{ text, audio: Promise<ArrayBuffer> | null }]
  const playingRef = useRef(false);
  const streamOpenRef = useRef(false);
  const bufRef = useRef("");
  const genRef = useRef(0);         // stop() のたびに増やし、古い再生の続きを無視する

  const fetchAudio = (text) => fetch("/api/tts", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ text, speaker: Number(voiceRef.current) }),
  }).then((r) => { if (!r.ok) throw new Error("VOICEVOX error"); return r.arrayBuffer(); });

  const finishIfIdle = () => {
    if (!playingRef.current && !queueRef.current.length && !streamOpenRef.current) setSpeaking(false);
  };

  const playBuffer = async (arrayBuffer, gen) => {
    const a = audioRef.current;
    if (!a.ctx) a.ctx = new (window.AudioContext || window.webkitAudioContext)();
    await a.ctx.resume();
    const buffer = await a.ctx.decodeAudioData(arrayBuffer);
    if (gen !== genRef.current) return;
    await new Promise((resolve) => {
      const source = a.ctx.createBufferSource();
      const analyser = a.ctx.createAnalyser();
      analyser.fftSize = 1024;
      source.buffer = buffer;
      source.connect(analyser);
      analyser.connect(a.ctx.destination);
      const data = new Float32Array(analyser.fftSize);
      const meter = () => {
        if (a.source !== source) return;
        analyser.getFloatTimeDomainData(data);
        let sum = 0;
        for (let i = 0; i < data.length; i++) sum += data[i] * data[i];
        levelRef.current = Math.sqrt(sum / data.length);
        requestAnimationFrame(meter);
      };
      source.onended = () => { if (a.source === source) { a.source = null; levelRef.current = null; } resolve(); };
      a.source = source;
      levelRef.current = 0;
      source.start();
      meter();
    });
  };

  const playBrowser = (text, gen) => new Promise((resolve) => {
    if (!("speechSynthesis" in window) || gen !== genRef.current) return resolve();
    const u = new SpeechSynthesisUtterance(text);
    const v = browserVoicesRef.current.find((x) => x.name === voiceRef.current)
      || browserVoicesRef.current.find((x) => x.name === pickVoice(browserVoicesRef.current));
    if (v) u.voice = v;
    u.lang = "ja-JP";
    u.rate = 1.05;
    u.pitch = 1.2;
    u.onend = u.onerror = () => resolve();
    speechSynthesis.speak(u);
  });

  const playNext = async () => {
    const gen = genRef.current;
    const item = queueRef.current.shift();
    if (!item) { playingRef.current = false; finishIfIdle(); return; }
    playingRef.current = true;
    setSpeaking(true);
    try {
      if (item.audio) await playBuffer(await item.audio, gen);
      else await playBrowser(item.text, gen);
    } catch (e) {
      console.warn("VOICEVOX で話せないため、ブラウザの声で話します:", e);
      levelRef.current = null;
      await playBrowser(item.text, gen);
    }
    if (gen === genRef.current) playNext();
  };

  const enqueue = (text) => {
    const t = text.trim();
    if (!t) return;
    const audio = engineRef.current === "voicevox" ? fetchAudio(t) : null;
    if (audio) audio.catch(() => {}); // 失敗は再生時にブラウザの声へ
    queueRef.current.push({ text: t, audio });
    setSpeaking(true);
    if (!playingRef.current) playNext();
  };

  const stop = () => {
    genRef.current += 1;
    queueRef.current = [];
    streamOpenRef.current = false;
    bufRef.current = "";
    playingRef.current = false;
    const a = audioRef.current;
    if (a.source) { const src = a.source; a.source = null; try { src.stop(); } catch (e) {} }
    if ("speechSynthesis" in window) speechSynthesis.cancel();
    levelRef.current = null;
    setSpeaking(false);
  };

  // 流れてくる文章を、句点や改行で区切って順に読み上げる
  const streamStart = () => { stop(); streamOpenRef.current = true; };
  const streamPush = (chunk) => {
    if (!streamOpenRef.current) return;
    bufRef.current += chunk;
    const re = /[^。!?！？\n]*[。!?！？\n]+/g;
    let m, last = 0;
    while ((m = re.exec(bufRef.current))) { enqueue(m[0]); last = re.lastIndex; }
    bufRef.current = bufRef.current.slice(last);
  };
  const streamEnd = () => {
    if (!streamOpenRef.current) return;
    enqueue(bufRef.current);
    bufRef.current = "";
    streamOpenRef.current = false;
    finishIfIdle();
  };

  const speak = (text) => {
    if (!text) return;
    streamStart();
    streamPush(text);
    streamEnd();
  };

  const chooseVoice = (value) => {
    setVoiceValue(value);
    save(engineRef.current === "voicevox" ? VV_VOICE_KEY : VOICE_KEY, value);
  };

  return { engine, voices, voiceValue, setVoice: chooseVoice, speak, stop, streamStart, streamPush, streamEnd, speaking, levelRef };
}
