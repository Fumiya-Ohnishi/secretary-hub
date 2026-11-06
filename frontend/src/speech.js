import { useEffect, useRef, useState } from "react";

/** 音声入力(ブラウザ音声認識, push-to-talk) */
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
      const msg = RECOGNITION_ERRORS[e.error];
      if (msg) onErrorRef.current?.(msg);
    };
    recRef.current = rec;
    return () => rec.abort();
  }, []);

  const start = () => { try { recRef.current?.start(); } catch (e) {} };
  return { recording, supported, unsupportedReason, start };
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

/** 音声出力(ブラウザTTS) */
export function useSpeechOutput() {
  const [voices, setVoices] = useState([]);
  const [voiceName, setVoiceName] = useState("");
  const [speaking, setSpeaking] = useState(false);

  useEffect(() => {
    const load = () => {
      const all = speechSynthesis.getVoices();
      const ja = all.filter((v) => v.lang && v.lang.toLowerCase().startsWith("ja"));
      const list = ja.length ? ja : all;
      setVoices(list);
      setVoiceName((prev) => prev || pickVoice(list));
    };
    load();
    speechSynthesis.onvoiceschanged = load;
  }, []);

  const speak = (text) => {
    if (!("speechSynthesis" in window) || !text) return;
    speechSynthesis.cancel();
    const u = new SpeechSynthesisUtterance(text);
    const v = voices.find((x) => x.name === voiceName);
    if (v) u.voice = v;
    u.lang = "ja-JP";
    u.rate = 1.05;
    u.pitch = 1.2;
    u.onstart = () => setSpeaking(true);
    u.onend = u.onerror = () => setSpeaking(false);
    speechSynthesis.speak(u);
  };

  const chooseVoice = (name) => {
    setVoiceName(name);
    try { localStorage.setItem(VOICE_KEY, name); } catch (e) {}
  };

  return { voices, voiceName, setVoiceName: chooseVoice, speak, speaking };
}
