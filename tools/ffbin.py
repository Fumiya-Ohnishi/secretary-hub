"""ffmpeg / ffprobe の場所を探す(ターミナルから直接動かしたときも、秘書ハブに入っている部品を使えるように)。2026-11-10 追加"""
import os
import platform
import shutil
import sys
from pathlib import Path

HUB = Path(__file__).resolve().parents[1]
EXTRA = ":/opt/homebrew/bin:/usr/local/bin"


def ffmpeg() -> str:
    f = os.getenv("FFMPEG") or shutil.which("ffmpeg", path=os.environ.get("PATH", "") + EXTRA)
    if not f:
        p = HUB / "tools" / "reel" / "node_modules" / "ffmpeg-static" / "ffmpeg"
        f = str(p) if p.exists() else ""
    return f


def ffprobe() -> str:
    f = os.getenv("FFPROBE") or shutil.which("ffprobe", path=os.environ.get("PATH", "") + EXTRA)
    if not f:
        arch = {"x86_64": "x64", "amd64": "x64", "aarch64": "arm64"}.get(platform.machine().lower(), platform.machine().lower())
        p = HUB / "tools" / "reel" / "node_modules" / "ffprobe-static" / "bin" / sys.platform / arch / "ffprobe"
        f = str(p) if p.exists() else ""
    return f
