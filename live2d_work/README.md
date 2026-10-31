# 秘書 Live2D 化プロジェクト(作業フォルダ)

静止画+表情差分の秘書を、まばたき・呼吸・口パク・表情変化する Live2D モデルに置き換える。

## 進捗

| Phase | 内容 | 状態 | 次にやること |
|---|---|---|---|
| 1 | 素材分け(See-through で PSD 化) | **完了**(2026-10-31 社長承認) | - |
| 2 | リギング | **社長の選択待ち**(承認ポイント②) | `PHASE2_ROUTES.md` でルートA/Bを選ぶ。素材は `secretary_psd/secretary_bust_l2d.psd` |
| 3 | 秘書ハブへの組み込み | 未着手 | Phase 2 のモデル納品後に Claude が実装 |
| 4 | 仕上げ(任意) | 未着手 | - |

## 社長の承認ポイント

1. Phase 1 完了後: PSD の目視確認(`secretary_psd/qa_report.md` 末尾のチェック欄)
2. Phase 2 開始前: ルートA/B の選択
3. Phase 3 完了後: ブラウザで動作確認
4. 有料発注する場合: 見積もりの承認

## ファイル

| パス | 内容 |
|---|---|
| `PHASE1_SEE_THROUGH.md` | See-through 調査結果(Mac 可否)・Kaggle/Colab 実行手順・品質チェックリスト |
| `see_through_kaggle_colab.ipynb` | Kaggle/Colab 用ノートブック(インストール→分解→自動検収→zip) |
| `input/secretary_bust.png` | See-through への入力(キャラシートからバストアップを切り出し済み) |
| `secretary_psd/` | 成果物の置き場(PSD・レイヤー一覧画像・検収レポート) |
| `PHASE2_ROUTES.md` | リギング ルートA(FREE版)/B(外注3案)の見積もり比較 |
| `RIGGING_SPEC_FREE.md` | ルートA の簡易リギング仕様書(パラメータ21個・ステップ解説) |
| `tools/prepare_input.py` | 入力画像の切り出し |
| `tools/run_lowmem.py` | T4 向けに注意計算を小分けにして See-through を実行するラッパー(ノートブックに埋め込み) |
| `tools/prepare_l2d_psd.py` | PSD に口の中・頬染めレイヤーを追加してリギング用 PSD を作る |
| `tools/psd_report.py` | PSD 自動検収(レイヤー一覧画像 + `qa_report.md`) |
| `tools/build_notebook.py` | ノートブック再生成(`psd_report.py`・`run_lowmem.py` を直したら実行) |

## 検収コマンド(手元で再チェックする場合)

```bash
pip install psd-tools numpy pillow scipy
python3 live2d_work/tools/psd_report.py live2d_work/secretary_psd/secretary_bust.psd --ref live2d_work/input/secretary_bust.png
```
