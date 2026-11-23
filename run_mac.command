#!/bin/bash
# ダブルクリックで秘書ハブを起動(Mac用)
cd "$(dirname "$0")"
# 最新版を取り込む(秘書ハブと会社のリポジトリ)。手元の変更とぶつかるときや、手元に独自の記録があるときは取り込まずに続ける
for d in . ../ai-company; do
  if [ -d "$d/.git" ]; then
    (git -C "$d" fetch -q && git -C "$d" merge --ff-only -q '@{u}' 2>/dev/null) || echo "ℹ $(basename "$(cd "$d" && pwd)") は最新版を自動で取り込めませんでした(手元の変更とぶつかるため)。秘書に伝えてください"
  fi
done
if [ ! -d backend/venv ]; then
  python3 -m venv backend/venv
fi
# 必要な部品を入れる(入っていれば数秒で終わる)
backend/venv/bin/pip install -q -r backend/requirements.txt || echo "⚠ 部品のインストールに失敗しました。上のエラーを秘書に見せてください"
# 声の確認(tools/voice_check.py)に使う音声認識の部品(初回だけ数分。入っていれば何もしない)
if ! backend/venv/bin/python -c "import faster_whisper, pykakasi" >/dev/null 2>&1; then
  echo "→ 声の確認に使う部品を入れています(初回だけ数分)..."
  backend/venv/bin/pip install -q -r tools/requirements-voice.txt || echo "⚠ 声の確認の部品を入れられませんでした(上のエラーを秘書に見せてください)"
fi
if [ ! -f backend/.env ]; then
  cp backend/.env.example backend/.env
  echo "→ backend/.env に ANTHROPIC_API_KEY を入力してから、このファイルをもう一度ダブルクリックしてください"
  open backend/.env
  exit 0
fi
# 画面(frontend)をビルド。初回と、frontend の中身が更新されたときだけ実行する
if command -v npm >/dev/null 2>&1; then
  if [ ! -f frontend/dist/index.html ] || [ -n "$(find frontend/src frontend/public frontend/package.json frontend/index.html frontend/reel.html -newer frontend/dist/index.html 2>/dev/null | head -1)" ]; then
    echo "→ 画面をビルドしています(初回は1〜2分)..."
    (cd frontend && npm install --silent && npm run build --silent) || echo "⚠ 画面のビルドに失敗しました。上のエラーを秘書に見せてください"
  fi
else
  echo "⚠ npm が見つかりません。画面のビルドには Node.js が必要です(https://nodejs.org)"
fi
# リールの声入れに使う部品(初回だけ)
if command -v npm >/dev/null 2>&1 && { [ ! -d tools/reel/node_modules/playwright-core ] || [ ! -d tools/reel/node_modules/ffmpeg-static ] || [ ! -d tools/reel/node_modules/node ]; }; then
  (cd tools/reel && npm install --silent) || echo "⚠ リール書き出しの部品を入れられませんでした(声入れは後で自動で再試行します)"
fi
if [ ! -f frontend/public/live2d/core/live2dcubismcore.js ]; then
  echo "ℹ Live2D の Cubism Core が無いため、秘書は静止画で表示されます(README の「Live2D の秘書」を参照)"
fi
backend/venv/bin/python backend/main.py
