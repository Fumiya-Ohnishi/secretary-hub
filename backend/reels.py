"""リールの声入れ(秘書ハブが起動している Mac で自動実行)。

クラウドでは VOICEVOX が使えないため、リールは声なしで書き出されることがある。
秘書ハブは VOICEVOX が動いているときに、ai-company/content/drafts/YYYY-WW/*.reel.json を探し、
まだ声入りになっていないものを tools/reel/render_record_reel.mjs で声入りに書き出し直す。
- 書き出し先: content/output/YYYY-WW/<名前>.mp4(Google ドライブへは content.sync_media が写す)
- 済みの印: 同じ場所の <名前>.voice.json(台本を直すと、台本の方が新しくなって作り直す)
- 声を入れたら、そのリールを使う投稿のキャプションにクレジット「VOICEVOX:冥鳴ひまり」を足す
社長の作業はない(Node.js と Google Chrome が Mac に入っていること)。
"""
import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import List, Optional

import company
import content

HUB_DIR = Path(__file__).resolve().parent.parent
RENDER = HUB_DIR / "tools" / "reel" / "render_record_reel.mjs"
CREDIT = "VOICEVOX:冥鳴ひまり"
last_error: Optional[str] = None


def _out_for(spec: Path) -> Path:
    name = spec.name[: -len(".reel.json")]
    return company.COMPANY_DIR / "content" / "output" / spec.parent.name / f"{name}.mp4"


def pending() -> List[Path]:
    """声入りになっていない(または台本が直された)リールの台本"""
    d = content.drafts_dir()
    if not d.exists():
        return []
    out = []
    for spec in sorted(d.glob("*/*.reel.json")):
        try:
            if "scene" not in json.loads(spec.read_text()):
                continue  # 旧形式(Live2D+テロップ)は render_reel.mjs の担当
        except Exception:
            continue
        mark = _out_for(spec).with_suffix(".voice.json")
        if not mark.exists() or spec.stat().st_mtime > mark.stat().st_mtime:
            out.append(spec)
    return out


def _ready() -> Optional[str]:
    """書き出しに必要なものがそろっているか。足りなければ理由を返す"""
    if not shutil.which("node"):
        return "Node.js が見つかりません(https://nodejs.org から入れると、リールに声が入ります)"
    nm = RENDER.parent / "node_modules"
    if not (nm / "playwright-core").exists() or not (nm / "ffmpeg-static").exists():
        npm = shutil.which("npm")
        if not npm:
            return "npm が見つかりません"
        r = subprocess.run([npm, "install", "--silent"], cwd=RENDER.parent, capture_output=True, text=True, timeout=600)
        if r.returncode != 0:
            return f"リール書き出しの部品を入れられませんでした: {r.stderr[-300:]}"
    return None


def _add_credit(mp4_rel: str) -> int:
    """そのリールを使う投稿のキャプション末尾にクレジットを足す(すでにあれば何もしない)"""
    n = 0
    for post in content.drafts_dir().glob("*/[0-9]*.md"):
        text = post.read_text()
        meta, body = content.parse(text)
        if mp4_rel not in meta.get("assets", ""):
            continue
        head = "## キャプション"
        i = body.find(head)
        if i == -1:
            continue
        j = body.find("\n## ", i + len(head))
        j = len(body) if j == -1 else j
        cap = body[i:j].rstrip()
        if CREDIT in cap:
            continue
        body = body[:i] + cap + f"\n\n声: {CREDIT}\n\n" + body[j:].lstrip("\n")
        post.write_text(content.dump(meta, body))
        n += 1
    return n


def render_pending(hub_url: str, voicevox_ok: bool) -> List[str]:
    """声入りにできたリールの名前を返す。VOICEVOX が止まっていれば何もしない"""
    global last_error
    todo = pending()
    if not todo or not voicevox_ok:
        return []
    why = _ready()
    if why:
        last_error = why
        return []
    done = []
    for spec in todo:
        out = _out_for(spec)
        out.parent.mkdir(parents=True, exist_ok=True)
        env = dict(os.environ, HUB_URL=hub_url, AI_COMPANY_DIR=str(company.COMPANY_DIR), REEL_REQUIRE_VOICE="1")
        ff = RENDER.parent / "node_modules" / "ffmpeg-static" / "ffmpeg"
        if ff.exists() and not shutil.which("ffmpeg"):
            env["FFMPEG"] = str(ff)
        r = subprocess.run(["node", str(RENDER), str(spec), str(out)], cwd=RENDER.parent, env=env,
                           capture_output=True, text=True, timeout=1800)
        if r.returncode != 0:
            last_error = f"{spec.parent.name}/{spec.name}: {(r.stderr or r.stdout)[-300:]}"
            continue
        out.with_suffix(".voice.json").write_text(json.dumps({"voiced": True, "spec": spec.name}, ensure_ascii=False))
        rel = str(out.relative_to(company.COMPANY_DIR))
        _add_credit(rel)
        done.append(f"{spec.parent.name}/{out.name}")
        last_error = None
    return done
