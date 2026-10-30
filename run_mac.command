#!/bin/bash
# ダブルクリックで秘書ハブを起動(Mac用)
cd "$(dirname "$0")"
if [ ! -d backend/venv ]; then
  python3 -m venv backend/venv
  backend/venv/bin/pip install -q -r backend/requirements.txt
fi
if [ ! -f backend/.env ]; then
  cp backend/.env.example backend/.env
  echo "→ backend/.env に ANTHROPIC_API_KEY を入力してから、このファイルをもう一度ダブルクリックしてください"
  open backend/.env
  exit 0
fi
backend/venv/bin/python backend/main.py
