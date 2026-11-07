#!/bin/bash
# ダブルクリックで秘書ハブを起動(Mac用)
cd "$(dirname "$0")"
if [ ! -d backend/venv ]; then
  python3 -m venv backend/venv
fi
# 必要な部品を入れる(入っていれば数秒で終わる)
backend/venv/bin/pip install -q -r backend/requirements.txt || echo "⚠ 部品のインストールに失敗しました。上のエラーを秘書に見せてください"
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
if command -v npm >/dev/null 2>&1 && [ ! -d tools/reel/node_modules/playwright-core ]; then
  (cd tools/reel && npm install --silent) || echo "⚠ リール書き出しの部品を入れられませんでした(声入れは後で自動で再試行します)"
fi
if [ ! -f frontend/public/live2d/core/live2dcubismcore.js ]; then
  echo "ℹ Live2D の Cubism Core が無いため、秘書は静止画で表示されます(README の「Live2D の秘書」を参照)"
fi
backend/venv/bin/python backend/main.py
