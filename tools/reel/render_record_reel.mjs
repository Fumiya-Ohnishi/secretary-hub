// 実録リールの書き出し: 場面の HTML(紙・カード・1本の線)+ 右下に小さく Live2D の秘書 + VOICEVOX の声 → 縦動画(MP4)
//
// 使い方(秘書ハブを起動した状態で。VOICEVOX も起動していれば声が入る):
//   node tools/reel/render_record_reel.mjs <台本.json> <出力.mp4>
//   例: node ~/secretary-hub/tools/reel/render_record_reel.mjs ~/ai-company/content/drafts/2026-46/r1.reel.json ~/ai-company/content/output/2026-46/r1.mp4
//
// 台本(JSON):
//   scene  … 場面の HTML(台本からの相対パス)。window.sceneSetup(spec, timeline) と window.sceneFrame(t) を持つ
//   lines  … [{ text, caption?, speech?, mood?, sec? }]。声があれば声の長さ、なければ sec(または文字数)で時間を決める
//   avatar … { x, y, w }  秘書を置く位置と幅(px)。省略すると秘書なし
//   credit … 声を使うときは必須「VOICEVOX:冥鳴ひまり」(場面側で表示する)
//   silent_ok … true なら VOICEVOX が無くても声なしで書き出す(テロップだけで成立する台本に限る)
import { chromium } from "playwright-core";
import { makeWork } from "./tmpwork.mjs";
import { readFileSync, writeFileSync, mkdirSync, existsSync, mkdtempSync } from "fs";
import { resolve, dirname, join } from "path";
import { tmpdir } from "os";
import { pathToFileURL } from "url";
import { spawnSync } from "child_process";

const HUB = process.env.HUB_URL || "http://localhost:8000";
const FPS = Number(process.env.REEL_FPS || 30);
const INTRO = 0.4, GAP = 0.3, OUTRO = 1.2;
const [specPath, outPath] = process.argv.slice(2);
if (!specPath || !outPath) { console.error("使い方: node tools/reel/render_record_reel.mjs <台本.json> <出力.mp4>"); process.exit(1); }
const spec = JSON.parse(readFileSync(specPath, "utf-8"));
const sceneUrl = pathToFileURL(resolve(dirname(resolve(specPath)), spec.scene)).href;
const ffmpeg = process.env.FFMPEG || "ffmpeg";

// ---- 1. 声(秘書ハブ経由で VOICEVOX)。無ければ silent_ok のときだけ声なし ----
function parseWav(buf) {
  let off = 12, fmt = null, data = null;
  while (off + 8 <= buf.length) {
    const id = buf.toString("ascii", off, off + 4), size = buf.readUInt32LE(off + 4);
    if (id === "fmt ") fmt = { channels: buf.readUInt16LE(off + 10), rate: buf.readUInt32LE(off + 12), bits: buf.readUInt16LE(off + 22) };
    if (id === "data") data = buf.subarray(off + 8, off + 8 + size);
    off += 8 + size + (size % 2);
  }
  const n = data.length / 2 / fmt.channels, mono = new Float32Array(n);
  for (let i = 0; i < n; i++) mono[i] = data.readInt16LE(i * 2 * fmt.channels) / 32768;
  return { rate: fmt.rate, samples: mono };
}
let voices = null;
try {
  const vs = [];
  for (const line of spec.lines) {
    const r = await fetch(`${HUB}/api/tts`, { method: "POST", headers: { "content-type": "application/json" },
      body: JSON.stringify({ text: line.speech ?? line.text, speaker: spec.speaker ?? null }) });
    if (!r.ok || !(r.headers.get("content-type") || "").includes("audio")) throw new Error(await r.text());
    vs.push(parseWav(Buffer.from(await r.arrayBuffer())));
  }
  voices = vs;
} catch (e) {
  if (!spec.silent_ok || process.env.REEL_REQUIRE_VOICE) throw new Error(`声を作れませんでした(VOICEVOX と秘書ハブを確認): ${e.message}`);
  console.warn("⚠ VOICEVOX が使えないため、声なしで書き出します(silent_ok)");
}
const rate = voices ? voices[0].rate : 24000;
const lines = [];
let t = INTRO;
spec.lines.forEach((line, index) => {
  const dur = voices ? voices[index].samples.length / rate : (line.sec ?? Math.max(1.6, [...(line.caption ?? line.text)].length * 0.13));
  lines.push({ index, start: t, end: t + dur });
  t += dur + GAP;
});
const duration = t - GAP + OUTRO;
const frames = Math.ceil(duration * FPS);
const total = Math.ceil(duration * rate), pcm = new Float32Array(total);
if (voices) lines.forEach((l, k) => pcm.set(voices[k].samples, Math.round(l.start * rate)));
const per = rate / FPS, levels = [];
for (let f = 0; f < frames; f++) {
  let s = 0, n = 0;
  for (let i = Math.floor(f * per); i < Math.min(total, Math.floor((f + 1) * per)); i++) { s += pcm[i] * pcm[i]; n++; }
  levels.push(n ? Math.sqrt(s / n) : 0);
}
const tl = { fps: FPS, duration, gap: GAP, lines, levels, voiced: !!voices };
console.log(`台本: ${spec.lines.length}行 / ${duration.toFixed(1)}秒 / ${frames}コマ / 声: ${voices ? "あり" : "なし"}`);

const work = makeWork("rec-reel-"); // 終わったら自動で消す(tmpwork.mjs)
mkdirSync(join(work, "scene")); mkdirSync(join(work, "avatar"));
const chromePaths = [process.env.CHROME_PATH, "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
  "/Applications/Chromium.app/Contents/MacOS/Chromium", "/opt/pw-browsers/chromium", "/usr/bin/chromium", "/usr/bin/google-chrome"].filter(Boolean);
const executablePath = chromePaths.find((p) => existsSync(p));
const browser = await chromium.launch({ ...(executablePath ? { executablePath } : { channel: "chrome" }),
  args: ["--use-angle=swiftshader", "--enable-unsafe-swiftshader", "--allow-file-access-from-files"] });

// ---- 2. 場面を1コマずつ ----
const scene = await browser.newPage({ viewport: { width: 1080, height: 1920 }, deviceScaleFactor: 1 });
scene.on("pageerror", (e) => console.error("場面のエラー:", e.message));
await scene.goto(sceneUrl);
await scene.evaluate(() => document.fonts.ready);
await scene.evaluate(([s, t]) => window.sceneSetup(s, t), [spec, tl]);
for (let f = 0; f < frames; f++) {
  await scene.evaluate((x) => window.sceneFrame(x), f / FPS);
  await scene.screenshot({ path: join(work, "scene", `${String(f).padStart(5, "0")}.jpg`), type: "jpeg", quality: 90 });
  if (f % 60 === 0) process.stdout.write(`  場面 ${f}/${frames}\r`);
}

// ---- 3. 秘書(透明背景)を1コマずつ ----
const av = spec.avatar;
if (av) {
  const page = await browser.newPage({ viewport: { width: 1080, height: 1920 }, deviceScaleFactor: 1 });
  page.on("pageerror", (e) => console.error("秘書のエラー:", e.message));
  await page.goto(`${HUB}/reel.html`);
  const ok = await page.evaluate(() => window.reelReady());
  if (ok !== true) throw new Error(`リール制作スタジオを開けませんでした: ${ok}`);
  await page.evaluate(([s, t]) => window.reelSetup(s, t), [{ ...spec, avatar: true, theme: "A" }, tl]);
  const clip = av.clip || { x: 190, y: 0, width: 700, height: 760 }; // 頭〜胸
  for (let f = 0; f < frames; f++) {
    await page.evaluate((i) => window.reelFrame(i), f);
    await page.screenshot({ path: join(work, "avatar", `${String(f).padStart(5, "0")}.png`), clip, omitBackground: true });
    if (f % 60 === 0) process.stdout.write(`  秘書 ${f}/${frames}\r`);
  }
}
await browser.close();

// ---- 4. 重ねて動画に ----
const wav = Buffer.alloc(44 + total * 2);
wav.write("RIFF", 0); wav.writeUInt32LE(36 + total * 2, 4); wav.write("WAVE", 8); wav.write("fmt ", 12);
wav.writeUInt32LE(16, 16); wav.writeUInt16LE(1, 20); wav.writeUInt16LE(1, 22); wav.writeUInt32LE(rate, 24);
wav.writeUInt32LE(rate * 2, 28); wav.writeUInt16LE(2, 32); wav.writeUInt16LE(16, 34); wav.write("data", 36); wav.writeUInt32LE(total * 2, 40);
for (let i = 0; i < total; i++) wav.writeInt16LE(Math.max(-32768, Math.min(32767, Math.round(pcm[i] * 32767))), 44 + i * 2);
writeFileSync(join(work, "voice.wav"), wav);
mkdirSync(dirname(resolve(outPath)), { recursive: true });
const args = ["-y", "-loglevel", "error", "-framerate", String(FPS), "-i", join(work, "scene", "%05d.jpg")];
if (av) args.push("-framerate", String(FPS), "-i", join(work, "avatar", "%05d.png"));
args.push("-i", join(work, "voice.wav"));
const audioIdx = av ? 2 : 1;
if (av) args.push("-filter_complex", `[1:v]scale=${av.w}:-1[a];[0:v][a]overlay=${av.x}:${av.y}[v]`, "-map", "[v]", "-map", `${audioIdx}:a`);
args.push("-c:v", "libx264", "-pix_fmt", "yuv420p", "-preset", "medium", "-crf", "19", "-r", String(FPS), "-c:a", "aac", "-b:a", "160k", "-shortest", resolve(outPath));
if (spawnSync(ffmpeg, args, { stdio: "inherit" }).status !== 0) throw new Error("ffmpeg で動画にできませんでした");
spawnSync(ffmpeg, ["-y", "-loglevel", "error", "-i", resolve(outPath), "-ss", "0.6", "-frames:v", "1", resolve(outPath).replace(/\.mp4$/, "_cover.jpg")]);
console.log(`\n完成: ${resolve(outPath)}(${duration.toFixed(1)}秒・声${voices ? "あり" : "なし"})`);
