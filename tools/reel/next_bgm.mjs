// リールの BGM を順番に回す(2026-11-20 P-088: OpenTracks の3曲を順に使い、同じ曲を続けない・音量 0.07)
// 使い方: node tools/reel/next_bgm.mjs [--peek] [--company <ai-company のフォルダ>]
//   次に使う曲のパス・音量・クレジットを JSON で出し、「最後に使った曲」を記録する(--peek は記録しない)
// 曲の一覧と最後に使った曲: <ai-company>/content/assets/sfx/bgm_rotation.json
import { readFileSync, writeFileSync, existsSync } from "fs";
import { resolve, dirname } from "path";
import { fileURLToPath } from "url";

export function companyDirOf(argv = process.argv) {
  const i = argv.indexOf("--company");
  if (i > 0) return resolve(argv[i + 1]);
  if (process.env.AI_COMPANY_DIR) return resolve(process.env.AI_COMPANY_DIR);
  return resolve(dirname(fileURLToPath(import.meta.url)), "../../../ai-company");
}

export function nextBgm(companyDir, { peek = false } = {}) {
  const path = resolve(companyDir, "content/assets/sfx/bgm_rotation.json");
  if (!existsSync(path)) throw new Error(`BGM の一覧がありません: ${path}`);
  const rot = JSON.parse(readFileSync(path, "utf8"));
  // hold: 作者の利用条件を確かめ終わるまで使わない曲(2026-11-20 パステルハウスの「利用条件有」)
  const tracks = (rot.tracks || []).filter((t) => !t.hold && existsSync(resolve(companyDir, t.file)));
  if (!tracks.length) throw new Error("使える BGM がありません(ファイルが置かれているか確かめてください)");
  const i = tracks.findIndex((t) => t.file === rot.last);
  const t = tracks[(i + 1) % tracks.length];
  if (!peek) {
    rot.last = t.file;
    rot.history = [...(rot.history || []), { file: t.file, at: new Date().toISOString().slice(0, 16) }].slice(-30);
    writeFileSync(path, JSON.stringify(rot, null, 2) + "\n");
  }
  return { bgm: t.file, bgm_volume: rot.volume ?? 0.07, credit: t.credit, title: t.title };
}

if (process.argv[1] && fileURLToPath(import.meta.url) === resolve(process.argv[1])) {
  console.log(JSON.stringify(nextBgm(companyDirOf(), { peek: process.argv.includes("--peek") }), null, 2));
}
