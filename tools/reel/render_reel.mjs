// リールの自動制作: 台本(JSON)→ VOICEVOX の声 → Live2D の秘書を1コマずつ録画 → テロップ・BGM つきの縦動画(MP4)
//
// 使い方(秘書ハブと VOICEVOX を起動した状態で):
//   node tools/reel/render_reel.mjs <台本.json> <出力.mp4>
//   例: node ~/secretary-hub/tools/reel/render_reel.mjs ~/ai-company/content/drafts/2026-46/02_ig_reel.reel.json ~/ai-company/content/output/2026-46/02_reel.mp4
//
// 必要なもの: Google Chrome、ffmpeg(brew install ffmpeg)、このフォルダで一度だけ `npm install`
// 台本の形式は ai-company/playbooks/reel_format.md
import { chromium } from "playwright-core";
import { readFileSync, writeFileSync, mkdirSync, existsSync, mkdtempSync } from "fs";
import { resolve, dirname, join, isAbsolute } from "path";
import { tmpdir } from "os";
import { spawnSync } from "child_process";

const HUB = process.env.HUB_URL || "http://localhost:8000";
const FPS = Number(process.env.REEL_FPS || 30);
const INTRO = 0.6, GAP = 0.25, OUTRO = 1.0; // 秒

const [specPath, outPath] = process.argv.slice(2);
if (!specPath || !outPath) {
  console.error("使い方: node tools/reel/render_reel.mjs <台本.json> <出力.mp4>");
  process.exit(1);
}
const spec = JSON.parse(readFileSync(specPath, "utf-8"));
if (!Array.isArray(spec.lines) || !spec.lines.length) throw new Error("台本に lines がありません");
const ffmpeg = process.env.FFMPEG || "ffmpeg";
if (spawnSync(ffmpeg, ["-version"]).status !== 0) throw new Error("ffmpeg が見つかりません。ターミナルで `brew install ffmpeg` を実行してください");

// ---- 1. 声(秘書ハブ経由で VOICEVOX)----
function parseWav(buf) {
  let off = 12, fmt = null, data = null;
  while (off + 8 <= buf.length) {
    const id = buf.toString("ascii", off, off + 4), size = buf.readUInt32LE(off + 4);
    if (id === "fmt ") fmt = { channels: buf.readUInt16LE(off + 10), rate: buf.readUInt32LE(off + 12), bits: buf.readUInt16LE(off + 22) };
    if (id === "data") data = buf.subarray(off + 8, off + 8 + size);
    off += 8 + size + (size % 2);
  }
  if (!fmt || !data || fmt.bits !== 16) throw new Error("音声の形式が想定外です(16bit WAV を想定)");
  const n = data.length / 2 / fmt.channels, mono = new Float32Array(n);
  for (let i = 0; i < n; i++) mono[i] = data.readInt16LE(i * 2 * fmt.channels) / 32768;
  return { rate: fmt.rate, samples: mono };
}

console.log(`台本: ${spec.lines.length}行 / テーマ ${spec.theme || "B"}`);
const voices = [];
for (const [i, line] of spec.lines.entries()) {
  const r = await fetch(`${HUB}/api/tts`, { method: "POST", headers: { "content-type": "application/json" },
    body: JSON.stringify({ text: line.speech ?? line.text, speaker: spec.speaker ?? null }) });
  if (!r.ok) throw new Error(`声を作れませんでした(${i + 1}行目): ${await r.text()}  ※VOICEVOX と秘書ハブが起動しているか確認`);
  voices.push(parseWav(Buffer.from(await r.arrayBuffer())));
  process.stdout.write(`  声 ${i + 1}/${spec.lines.length}\r`);
}
const rate = voices[0].rate;
if (voices.some((v) => v.rate !== rate)) throw new Error("声のサンプリングレートがそろっていません");

// ---- 2. 時間割と、1コマごとの声の大きさ(口パク用)----
const lines = [];
let t = INTRO;
voices.forEach((v, index) => {
  const dur = v.samples.length / rate;
  lines.push({ index, start: t, end: t + dur });
  t += dur + GAP;
});
const duration = t - GAP + OUTRO;
const total = Math.ceil(duration * rate), pcm = new Float32Array(total);
lines.forEach((l, k) => pcm.set(voices[k].samples, Math.round(l.start * rate)));
const frames = Math.ceil(duration * FPS), per = rate / FPS, levels = [];
for (let f = 0; f < frames; f++) {
  let s = 0, n = 0;
  for (let i = Math.floor(f * per); i < Math.min(total, Math.floor((f + 1) * per)); i++) { s += pcm[i] * pcm[i]; n++; }
  levels.push(n ? Math.sqrt(s / n) : 0);
}
if (duration > 60) console.warn(`⚠ ${duration.toFixed(1)}秒あります(リールは30〜45秒が目安)`);

const work = mkdtempSync(join(tmpdir(), "reel-"));
const wav = Buffer.alloc(44 + total * 2);
wav.write("RIFF", 0); wav.writeUInt32LE(36 + total * 2, 4); wav.write("WAVE", 8); wav.write("fmt ", 12);
wav.writeUInt32LE(16, 16); wav.writeUInt16LE(1, 20); wav.writeUInt16LE(1, 22); wav.writeUInt32LE(rate, 24);
wav.writeUInt32LE(rate * 2, 28); wav.writeUInt16LE(2, 32); wav.writeUInt16LE(16, 34); wav.write("data", 36); wav.writeUInt32LE(total * 2, 40);
for (let i = 0; i < total; i++) wav.writeInt16LE(Math.max(-32768, Math.min(32767, Math.round(pcm[i] * 32767))), 44 + i * 2);
writeFileSync(join(work, "voice.wav"), wav);

// ---- 3. Live2D の秘書を1コマずつ描いて保存 ----
const chromePaths = [process.env.CHROME_PATH, "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
  "/Applications/Chromium.app/Contents/MacOS/Chromium", "/opt/pw-browsers/chromium", "/usr/bin/chromium", "/usr/bin/google-chrome"].filter(Boolean);
const executablePath = chromePaths.find((p) => existsSync(p));
const browser = await chromium.launch({ ...(executablePath ? { executablePath } : { channel: "chrome" }),
  args: ["--use-angle=swiftshader", "--enable-unsafe-swiftshader", "--autoplay-policy=no-user-gesture-required"] });
const page = await browser.newPage({ viewport: { width: 1080, height: 1920 }, deviceScaleFactor: 1 });
page.on("pageerror", (e) => console.error("画面のエラー:", e.message));
await page.goto(`${HUB}/reel.html`);
const ok = await page.evaluate(() => window.reelReady());
if (ok !== true) throw new Error(`リール制作スタジオを開けませんでした: ${ok}(Cubism Core の配置を確認)`);
await page.evaluate(([s, tl]) => window.reelSetup(s, tl), [spec, { fps: FPS, duration, gap: GAP, lines, levels }]);
mkdirSync(join(work, "frames"), { recursive: true });
const started = Date.now();
for (let f = 0; f < frames; f++) {
  await page.evaluate((i) => window.reelFrame(i), f);
  await page.screenshot({ path: join(work, "frames", `${String(f).padStart(5, "0")}.jpg`), type: "jpeg", quality: 88 });
  if (f % 30 === 0) process.stdout.write(`  録画 ${f}/${frames}コマ(${Math.round((Date.now() - started) / 1000)}秒)\r`);
}
await browser.close();

// ---- 4. 動画にまとめる(BGM があれば小さく重ねる)----
mkdirSync(dirname(resolve(outPath)), { recursive: true });
const args = ["-y", "-loglevel", "error", "-framerate", String(FPS), "-i", join(work, "frames", "%05d.jpg"), "-i", join(work, "voice.wav")];
if (spec.bgm) {
  const companyDir = process.env.AI_COMPANY_DIR || resolve(dirname(new URL(import.meta.url).pathname), "../../../ai-company");
  const bgm = isAbsolute(spec.bgm) ? spec.bgm : resolve(companyDir, spec.bgm);
  if (!existsSync(bgm)) throw new Error(`BGM が見つかりません: ${bgm}`);
  args.push("-stream_loop", "-1", "-i", bgm, "-filter_complex",
    `[2:a]volume=${spec.bgm_volume ?? 0.12}[b];[1:a][b]amix=inputs=2:duration=first:dropout_transition=0[a]`, "-map", "0:v", "-map", "[a]");
}
args.push("-c:v", "libx264", "-pix_fmt", "yuv420p", "-preset", "medium", "-crf", "20", "-r", String(FPS), "-c:a", "aac", "-b:a", "160k", "-shortest", resolve(outPath));
const enc = spawnSync(ffmpeg, args, { stdio: "inherit" });
if (enc.status !== 0) throw new Error("ffmpeg で動画にできませんでした");
// 表紙用の1枚(タイトルが見えている最初のコマ)
spawnSync(ffmpeg, ["-y", "-loglevel", "error", "-i", join(work, "frames", "00005.jpg"), resolve(outPath).replace(/\.mp4$/, "_cover.jpg")]);
console.log(`\n完成: ${resolve(outPath)}(${duration.toFixed(1)}秒・${frames}コマ)`);
