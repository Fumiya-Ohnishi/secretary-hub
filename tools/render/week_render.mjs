#!/usr/bin/env node
// 部署の作業から、週のフォルダの書き出しスクリプト(content/drafts/YYYY-WW/render.mjs)を動かす入口。2026-11-10 追加。
// Claude Code の許可は「決まった場所のコマンド」でしか通らないため(content/drafts/*/render.mjs のような途中の * は効かない)、
// この1本を許可し、ここから週の render.mjs を呼ぶ。会社のフォルダ(作業のフォルダ)から動かす。
//   node <秘書ハブ>/tools/render/week_render.mjs 2026-47 <render.mjs に渡す引数...>
import { spawnSync } from "node:child_process";
import { existsSync } from "node:fs";
import path from "node:path";

const [week, ...args] = process.argv.slice(2);
if (!/^\d{4}-\d{2}$/.test(week || "")) {
  console.error("使い方: node week_render.mjs <YYYY-WW> [render.mjs の引数...](会社のフォルダから動かす)");
  process.exit(2);
}
const script = path.resolve("content", "drafts", week, "render.mjs");
if (!existsSync(script)) {
  console.error(`書き出しスクリプトがありません: content/drafts/${week}/render.mjs(名前は必ず render.mjs)`);
  process.exit(2);
}
const r = spawnSync(process.execPath, [script, ...args], { stdio: "inherit", cwd: process.cwd(), env: process.env });
process.exit(r.status ?? 1);
