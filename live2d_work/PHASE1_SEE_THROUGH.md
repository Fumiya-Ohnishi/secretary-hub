# Phase 1: 素材分け(PSDレイヤー化)— 調査結果と手順

## 1. See-through 調査結果

| 項目 | 内容 |
|---|---|
| 正体 | [shitagaki-lab/see-through](https://github.com/shitagaki-lab/see-through)(Apache-2.0)。アニメ1枚絵を最大23の意味パーツ(前髪/後ろ髪/顔/眉/白目/瞳/まつ毛/口/首/服…)に分解し、**隠れた部分を拡散モデルで描き足した**PSDを出力する |
| 中身 | LayerDiff 3D(SDXLベース・透過レイヤー生成)+ Marigold(アニメ向け深度推定)。モデル合計 約15GB(初回自動ダウンロード) |
| 必要GPU | NVIDIA CUDA(VRAM 8〜16GB)。`--group_offload` で約10GB、量子化版で約8GB |
| 検証したコミット | `df019de`(2026-10-06) |

### Mac(Apple Silicon)で動くか → **結論: 公式には動かない。Kaggle/Colab の無料GPUで実行する**

根拠(ソースを確認済み):
- 推論コード `common/utils/inference_utils.py` がモデルを `device='cuda'` / `torch.bfloat16` に**ハードコード**している(65〜69行目、195行目)。Apple Silicon の MPS には分岐が無い
- README のインストール手順は CUDA 12.8 と AMD ROCm のみ。Mac/MPS/CPU の記載なし
- ComfyUI 版ラッパー([jtydhr88/ComfyUI-See-through](https://github.com/jtydhr88/ComfyUI-See-through))も MPS 対応コードは無し
- 仮にコードを書き換えて MPS で動かしても、SDXL 規模のモデル(15GB)を bf16 で回すにはユニファイドメモリ 32GB 以上が必要で、1枚に1時間以上かかる見込み(未検証)。
  また Claude のクラウド作業環境も GPU なし・Hugging Face 接続不可のため、ここでは実行できない

→ 指示書の代替ルート「**Kaggle/Colab の無料GPU**」を正式ルートとする(参考実績: T4 x2 で1枚絵→23レイヤー分解)。
社長の作業はブラウザでノートブックを開いて ▶ を押すだけ(約30分、うち待ち時間がほとんど)。

| | Kaggle(推奨) | Google Colab |
|---|---|---|
| GPU | T4 x2(VRAM 15GB×2) | T4(15GB) |
| 無料枠 | 週30時間 | 変動(数時間/日) |
| メモリ | 約29GB | 約12GB(モデル読込で苦しい場合あり) |
| 事前準備 | 電話番号認証(GPU・Internet を使うため) | Googleアカウントのみ |

## 2. 入力画像の前処理(Claude 実施済み)

元イラスト(`brand/secretary_design.png`)は「バストアップ + 全身」の2体が並んだキャラシート。
そのまま入れると2体を1人として分解してしまうため、**左のバストアップだけを切り出して長辺1280pxに拡大**した。

- 入力: `input/secretary_bust.png`(644×1280)
- 再生成: `python3 live2d_work/tools/prepare_input.py`

## 3. 実行手順([人間作業]・約30分)

1. Kaggle(https://www.kaggle.com)にログイン → 「Create → New Notebook」
2. 「File → Import Notebook」で `live2d_work/see_through_kaggle_colab.ipynb` を読み込む
3. 右パネル Settings: **Accelerator = GPU T4 x2**、**Internet = ON**
4. 右パネル「Add Input → Upload」で `live2d_work/input/secretary_bust.png` をアップロード
5. 「Run All」(上から全部実行)。セル5で**レイヤー一覧画像と自動検収レポート**が表示される
6. 右パネル Output から `secretary_psd.zip` をダウンロード → `secretary-hub/live2d_work/secretary_psd/` に展開
7. 秘書に「PSDできた」と伝える → Claude が中身を確認・検収し、git に登録する

Colab の場合: https://colab.research.google.com →「ノートブックをアップロード」→「ランタイム → T4 GPU」→「すべてのセルを実行」。画像はセル3でファイル選択。

> ログイン情報は社長がブラウザで直接入力してください。Claude はパスワード類を一切扱いません。

### 成果物(`secretary_psd/`)

| ファイル | 内容 |
|---|---|
| `secretary_bust.psd` | **本体**。Live2D 用パーツレイヤー(下=奥、上=手前の順) |
| `secretary_bust_depth.psd` | 各パーツの深度マップ(リギング時の前後関係の参考) |
| `layers_overview.png` | 確認用レイヤー一覧画像 |
| `qa_report.md` | 自動検収レポート |

## 4. 品質チェックリスト(自己検収)

`tools/psd_report.py` が自動判定し、`qa_report.md` に結果を書く。

| チェック | 自動判定の方法 | 合格ライン |
|---|---|---|
| [ ] 各パーツの縁に欠けがない | 各レイヤーの不透明部分を連結成分に分け、レイヤー面積の0.2%未満の「切れ端」を数える | 切れ端 5個以下、空レイヤー無し |
| [ ] 遮蔽部分(襟の下の首、前髪の下の額)がインペイントで補完されている | 顔・首・後ろ髪レイヤーのうち、**上のレイヤーに完全に隠れている所まで描かれている割合**を計測 | 3%以上(0% = 見えている所しか無い) |
| [ ] 目・口のパーツが独立している | 前髪/後ろ髪/顔/眉/白目/瞳/まつ毛/口/首/服 のレイヤーが存在するか | 全部あり + 左右の目が別レイヤー |
| [ ] 全レイヤー合成 ≒ 元画像 | 合成画像と入力画像の PSNR(キャラ領域) | 25dB 以上 |

自動判定はあくまで一次チェック。**最終判定は社長の目視**(`qa_report.md` 末尾のチェック欄)。

## 5. 既知の限界と、Phase 2 での対処

See-through は「今見えている絵」を分けるだけなので、Live2D に必要な**描かれていない差分**は作られない:

| 足りないもの | 使う場面 | 対処 |
|---|---|---|
| 口の中(開いた口) | 口パク | 承認後に Claude が口レイヤーの形から「口内」レイヤーを作って PSD に追加(ルートA)/ 外注先に依頼(ルートB) |
| 閉じた目の線 | まばたき | まつ毛レイヤーを下へ変形して作る(リギング仕様書に手順あり) |
| 笑い目・困り眉 | 表情 | 既存パーツの変形で作る(同上) |

## 6. トラブルシューティング

| 症状 | 対処 |
|---|---|
| セル4で `CUDA out of memory` | 自動で量子化ルートに切替わる。それでも落ちる場合は Kaggle(T4 x2)で実行 |
| Colab で「セッションを再起動」と出た | 再起動してセル3から再実行 |
| モデルのダウンロードが途中で止まる | セル4を再実行(続きから再開される) |
| 顔の向きや髪の分かれ方がおかしい | エラー表示と `layers_overview.png` を秘書に渡す → Claude が入力画像の切り出し・解像度を調整して再実行案を出す |
