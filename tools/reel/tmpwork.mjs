// リール書き出しの一時フォルダ(コマ画像。1本で0.5〜1GB)を作り、終わったら必ず消す。
// 2026-11-10: 消していなかったため Mac の一時フォルダに 14GB 残り、書き出しの途中でディスクがいっぱいになった。
import * as fs from "fs";
const { mkdtempSync, rmSync, readdirSync, statSync } = fs;
import { join } from "path";
import { tmpdir } from "os";

const PREFIXES = ["rec-reel-", "reel-"];
const STALE_MS = 6 * 3600 * 1000; // これより古い消し残しは、次の書き出しのときに片付ける
const MIN_FREE_GB = 5; // 空きがこれより少なければ書き出しを始めない

export function makeWork(prefix) {
  // 前回までの消し残し(書き出しが強制終了したときなど)を片付ける
  for (const name of readdirSync(tmpdir())) {
    if (!PREFIXES.some((p) => name.startsWith(p))) continue;
    const p = join(tmpdir(), name);
    try { if (Date.now() - statSync(p).mtimeMs > STALE_MS) rmSync(p, { recursive: true, force: true }); } catch {}
  }
  // 空きの確認(Node 18.15 以上。無ければ確かめずに進む)
  try {
    if (typeof fs.statfsSync !== "function") throw 0; // 古い Node では確かめずに進む
    const s = fs.statfsSync(tmpdir());
    const freeGB = (s.bavail * s.bsize) / 1024 ** 3;
    if (freeGB < MIN_FREE_GB) {
      console.error(`ディスクの空きが ${freeGB.toFixed(1)}GB しかありません(書き出しには ${MIN_FREE_GB}GB 以上必要)。容量を空けてからもう一度実行してください。`);
      process.exit(1);
    }
  } catch {}
  const work = mkdtempSync(join(tmpdir(), prefix));
  const clean = () => { try { rmSync(work, { recursive: true, force: true }); } catch {} };
  process.on("exit", clean); // 正常終了・エラー終了のどちらでも消す
  for (const sig of ["SIGINT", "SIGTERM", "SIGHUP"]) process.on(sig, () => process.exit(1));
  return work;
}
