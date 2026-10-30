import { useEffect, useRef, useState } from "react";

/** 音声入力(ブラウザ音声認識, push-to-talk) */
export function useSpeechInput(onFinal) {
  const [recording, setRecording] = useState(false);
  const [supported, setSupported] = useState(false);
  const recRef = useRef(null);

  useEffect(() => {
    const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (!SR) return;
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
      onFinal(null, finalText || `（聞いています… ${interim}）`);
    };
    rec.onend = () => { setRecording(false); if (finalText.trim()) onFinal(finalText.trim()); };
    rec.onerror = () => setRecording(false);
    recRef.current = rec;
  }, [onFinal]);

  const start = () => { try { recRef.current?.start(); } catch (e) {} };
  return { recording, supported, start };
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
      setVoiceName((prev) => prev || (list[0] && list[0].name) || "");
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
    u.rate = 1.02;
    u.pitch = 1.05;
    u.onstart = () => setSpeaking(true);
    u.onend = u.onerror = () => setSpeaking(false);
    speechSynthesis.speak(u);
  };

  return { voices, voiceName, setVoiceName, speak, speaking };
}
