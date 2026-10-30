"""see_through_kaggle_colab.ipynb を生成する(psd_report.py・run_lowmem.py を埋め込むため、それらを直したら再実行)。"""
import json
from pathlib import Path
WORK = Path(__file__).resolve().parent.parent
report_src = (WORK / "tools" / "psd_report.py").read_text()
lowmem_src = (WORK / "tools" / "run_lowmem.py").read_text()
COMMIT = "df019de5129d6c4b406587a14c3501669441a783"

def md(s): return {"cell_type": "markdown", "metadata": {}, "source": s.strip("\n")}
def code(s): return {"cell_type": "code", "metadata": {}, "execution_count": None, "outputs": [], "source": s.strip("\n")}

cells = [
md("""
# 秘書 Live2D 化 Phase 1: See-through で PSD パーツ分け

**上から順に ▶ を押すだけ**で、秘書のイラストを Live2D 用の PSD(前髪/後ろ髪/眉/白目/瞳/まつ毛/口/顔/首/服…)に分解します。

- 対応環境: **Kaggle**(推奨・GPU T4 x2・週30時間無料)/ **Google Colab**(無料 T4)
- 所要時間の目安: インストール 10〜15分 + 分解 10〜20分(初回はモデル約15GBのダウンロード込み)
- 必要なもの: `secretary_bust.png`(秘書ハブの `live2d_work/input/` にあります)
- このノートブックは**パスワード等を一切使いません**(公開モデルのみ使用)

### 事前設定
- **Kaggle**: 右パネル Settings → Accelerator を **GPU T4 x2**、Internet を **ON**(電話番号認証済みアカウントが必要)。
  右パネル「Add Input → Upload」で `secretary_bust.png` をアップロード(Dataset名は何でも可)。
- **Colab**: メニュー「ランタイム → ランタイムのタイプを変更 → T4 GPU」。画像はセル3で選択します。
"""),
md("## 1. GPU 確認"),
code("""
import subprocess, sys
print(sys.version)
out = subprocess.run(["nvidia-smi", "--query-gpu=name,memory.total,compute_cap", "--format=csv,noheader"],
                     capture_output=True, text=True).stdout.strip()
print(out or "GPU が見つかりません")
if not out:
    raise SystemExit("GPU が有効になっていません。Kaggle: Settings → Accelerator を『GPU T4 x2』に / Colab: ランタイムのタイプを『T4 GPU』に")
cap = float(out.splitlines()[0].split(",")[-1])
if cap < 7.5:
    # See-through が使う PyTorch 2.8 (CUDA 12.8 版) は P100 など古いGPUに対応していない
    raise SystemExit(f"このGPU({out.splitlines()[0]})は非対応です。Kaggle は Accelerator を『GPU T4 x2』に変えてください(P100 は不可)")
print("GPU OK")
"""),
md("## 2. See-through のインストール(10〜15分)"),
code("""
import os, subprocess, urllib.error, urllib.request
# Kaggle かどうかは環境変数で判定する(Colab にも /kaggle フォルダがあるため、フォルダの有無では判定できない)
ROOT = "/kaggle/working" if os.environ.get("KAGGLE_KERNEL_RUN_TYPE") else "/content"
REPO = ROOT + "/see-through"
COMMIT = "__COMMIT__"

# インターネット接続の確認(Kaggle は Settings → Internet を ON にする必要あり)
try:
    urllib.request.urlopen("https://github.com", timeout=15)
except urllib.error.HTTPError:
    pass  # 応答が返ってくれば接続はできている
except Exception as e:
    raise SystemExit("インターネットに繋がっていません。Kaggle の右パネル Settings → Internet を ON にしてから"
                     "(電話番号認証が必要)、このセルをもう一度実行してください。詳細: " + repr(e))

def sh(cmd, cwd=REPO):
    print("$", cmd)
    rc = subprocess.run(cmd, shell=True, cwd=cwd).returncode
    if rc != 0:
        raise SystemExit("失敗しました: " + cmd + "  ← この上のエラー表示を秘書に貼ってください")

if not os.path.exists(REPO + "/.git"):
    sh("git clone https://github.com/shitagaki-lab/see-through.git " + REPO, cwd=ROOT)
sh("git checkout -q " + COMMIT)
# PyTorch: Kaggle/Colab に最初から入っている CUDA 版(2.8以上)があればそれを使う。
# 入れ替えると環境の CUDA ライブラリと食い違い、CUBLAS_STATUS_NOT_INITIALIZED で落ちることがあるため
pre = subprocess.run(["python", "-c", "import torch;print(torch.__version__, torch.version.cuda)"],
                     capture_output=True, text=True).stdout.split()
ver = tuple(int(x) for x in pre[0].split("+")[0].split(".")[:2]) if pre else (0, 0)
if ver >= (2, 8) and pre[1] != "None":
    print("PyTorch はプリインストール版を使います:", " ".join(pre))
else:
    sh("pip install -q torch==2.8.0+cu128 torchvision==0.23.0+cu128 torchaudio==2.8.0+cu128 --index-url https://download.pytorch.org/whl/cu128")
# 推論に不要な開発用・UI用ライブラリは入れない
# (ipykernel 等を入れ替えると Colab/Kaggle 本体が不安定になるため)
SKIP = ("ipykernel", "pytest", "pyqt6", "qtpy", "lpips", "convnext_perceptual_loss")
with open(REPO + "/requirements.txt") as f:
    reqs = [l for l in f if not l.strip().lower().startswith(SKIP)]
with open(REPO + "/requirements-notebook.txt", "w") as f:
    f.writelines(reqs)
sh("pip install -q -r requirements-notebook.txt")
sh("pip install -q -r requirements-inference-bnb.txt")  # 8GB 量子化ルート(予備)用
sh("ln -sfn common/assets assets")
os.chdir(REPO)
print("インストール完了。依存関係の ERROR/警告(dependency conflicts)が出ていても問題ありません。"\n      "Colab で『セッションを再起動』と出たら、再起動してからセル3へ進んでください。")
""".replace("__COMMIT__", COMMIT)),
md("## 3. 秘書の画像を用意"),
code("""
import glob, os, shutil
REPO = ("/kaggle/working" if os.environ.get("KAGGLE_KERNEL_RUN_TYPE") else "/content") + "/see-through"
if not os.path.exists(REPO + "/inference"):
    raise SystemExit("See-through がまだインストールされていません。セル2を実行し、最後に『インストール完了』と出るのを確認してください。")
os.chdir(REPO)
os.makedirs("input", exist_ok=True)
found = glob.glob("/kaggle/input/**/secretary_bust.png", recursive=True)
if found:
    shutil.copy(found[0], "input/secretary_bust.png")
else:
    try:
        from google.colab import files
        up = files.upload()  # secretary_bust.png を選択
        shutil.move(next(iter(up)), "input/secretary_bust.png")
    except ImportError:
        raise SystemExit("Kaggle: 右パネルの Add Input から secretary_bust.png をアップロードしてください")
from PIL import Image
Image.open("input/secretary_bust.png").resize((322, 640))
"""),
md("""
## 4. パーツ分け実行(10〜20分)

T4(VRAM 15GB)向けに `--group_offload`(約10GB)で実行。T4 は省メモリ版の注意計算(bf16)に対応していないため、`run_lowmem.py` で注意計算を小分けにして実行します(結果は同じ)。失敗したら自動で 8GB 量子化ルートに切り替えます。\n両方失敗した場合は、それぞれのエラーの末尾をまとめて表示します。
`--tblr_split` で左右の目・眉を別レイヤーにします(片目ウインク用)。
"""),
code("%%writefile run_lowmem.py\n" + lowmem_src),
code("""
import os, subprocess
env = dict(os.environ, CUDA_VISIBLE_DEVICES="0")  # T4 x2 でも1枚目だけを使う

# まず GPU 計算が動くかを確認(ここで落ちる場合はGPUの種類かドライバの問題)
test = subprocess.run(["python", "-c", "import torch; a = torch.randn(64, 64, device='cuda', dtype=torch.bfloat16); "
                       "print(torch.cuda.get_device_name(0), float((a @ a).sum()))"], env=env, capture_output=True, text=True)
print(test.stdout or test.stderr[-2000:])
if test.returncode != 0:
    raise SystemExit("GPU 計算の確認に失敗しました。上の表示とセル1の表示を秘書に貼ってください")

def run(script, extra=(), log="run.log"):
    cmd = ["python", "run_lowmem.py", f"inference/scripts/{script}", "--srcp", "input/secretary_bust.png",
           "--save_to_psd", "--tblr_split", "--save_dir", "workspace/layerdiff_output", *extra]
    print("$", " ".join(cmd))
    with open(log, "w") as f:
        p = subprocess.Popen(cmd, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        for line in p.stdout:
            print(line, end=""); f.write(line)
    return p.wait()

def tail(log, n=25):
    return "".join(open(log).readlines()[-n:])

rc = run("inference_psd.py", ["--group_offload"], log="run_main.log")
if rc != 0:
    print("\\n→ 標準ルートが失敗したので、量子化ルートで再実行します\\n")
    rc = run("inference_psd_quantized.py", log="run_quantized.log")
if rc != 0:
    print("=" * 60)
    print("【標準ルートのエラー(末尾)】\\n" + tail("run_main.log"))
    print("【量子化ルートのエラー(末尾)】\\n" + tail("run_quantized.log"))
    print("=" * 60)
    raise SystemExit("失敗しました。==== で囲まれた部分を秘書に貼ってください")
!ls -la workspace/layerdiff_output
"""),
md("## 5. 自動検収(レイヤー一覧画像 + 検収レポート)"),
code("%%writefile psd_report.py\n" + report_src),
code("""
!mkdir -p secretary_psd
!cp workspace/layerdiff_output/secretary_bust.psd workspace/layerdiff_output/secretary_bust_depth.psd secretary_psd/
!python psd_report.py secretary_psd/secretary_bust.psd --ref input/secretary_bust.png --out secretary_psd
from IPython.display import Image as IPImage, Markdown, display
display(IPImage("secretary_psd/layers_overview.png"))
display(Markdown(open("secretary_psd/qa_report.md", encoding="utf-8").read()))
"""),
md("""
## 6. ダウンロード

`secretary_psd.zip` を保存し、Mac の `secretary-hub/live2d_work/secretary_psd/` に展開してください。
- Kaggle: 右パネル Output(`/kaggle/working`)から `secretary_psd.zip` をダウンロード
- Colab: 下のセルで自動ダウンロード
"""),
code("""
!cd secretary_psd && zip -q -r ../secretary_psd.zip . && cd .. && ls -la secretary_psd.zip
try:
    from google.colab import files; files.download("secretary_psd.zip")
except ImportError:
    import shutil; shutil.copy("secretary_psd.zip", "/kaggle/working/secretary_psd.zip")
"""),
]
nb = {"cells": cells, "metadata": {"accelerator": "GPU", "kernelspec": {"name": "python3", "display_name": "Python 3"},
      "language_info": {"name": "python"}}, "nbformat": 4, "nbformat_minor": 5}
for c in nb["cells"]:
    c["source"] = c["source"].splitlines(keepends=True)
(WORK / "see_through_kaggle_colab.ipynb").write_text(json.dumps(nb, ensure_ascii=False, indent=1))
print("ok")
