# AI秘書ハブ(Macローカル版)

顔(React)+ 脳(Claude API)+ 会社(Claude Code リポジトリ)をつなぐ中継サーバー。

## セットアップ(初回だけ・10分)

1. この `secretary-hub` フォルダと `ai-company` フォルダを**同じ階層**に置く
   (別の場所に置く場合は `backend/.env` の `AI_COMPANY_DIR` にフルパスを書く)
2. `backend/.env.example` をコピーして `backend/.env` にリネームし、
   `ANTHROPIC_API_KEY=sk-ant-...` に自分のキーを貼る(コンソール: console.anthropic.com)
3. **`run_mac.command` をダブルクリック** → ブラウザで http://localhost:8000 が開く
   (初回はPython仮想環境の作成で数分かかります)

## 使い方

- マイク(🎙)で話しかける / 下部の入力欄で会話
- 「今日の収益は?」→ revenue.csv を読んで報告
- 「承認待ちは?」→ tasks.md の承認待ちを報告
- 「戦略部に今週の企画を頼んで」「企画書を作って」→ **裏でClaude Code CLIが
  ai-company リポジトリで作業**し、完了すると秘書が報告します
  (要: ターミナルで `npm install -g @anthropic-ai/claude-code` 済み & `claude` でログイン済み)

## 画面の見方

- 左: 秘書(表情が気分で変化: 通常/上機嫌/考え中/不機嫌)
- 右上パネル: 収益進捗(目標5万)・未完了・承認待ち
- チャット: 会話ログ。作業完了はシステムメッセージで通知

## トラブルシューティング

| 症状 | 対処 |
|---|---|
| 会社データが「見つかりません」 | `backend/.env` の `AI_COMPANY_DIR` に ai-company のフルパスを設定 |
| 音声入力が効かない | Chrome または Safari で開く。マイク権限を許可 |
| 「Claude Code CLI未接続」 | ターミナルで `claude --version` が通るか確認。なければ npm install -g |
| APIキーを変えたい | `backend/.env` を編集して再起動 |

## セキュリティ

- APIキーは `backend/.env` のみ(gitコミット禁止)。ブラウザ側には渡しません
- パスワード類はこのシステムでは一切扱いません(投稿は社長が実行)

## Live2D の秘書

左の秘書は Live2D モデルで動きます(自動まばたき・呼吸、話すと口パク、気分で表情が変わる)。
読み込めない場合は、従来の静止画(`frontend/public/faces/`)に自動で切り替わります。

| 気分 | 表情 | いつ変わるか |
|---|---|---|
| normal | 通常 | ふだん |
| pleased | 上機嫌(笑い目・頬染め) | 褒めたとき・お礼を言ったとき |
| thinking | 考え中(困り眉) | 部署に作業を頼んだとき・考えているとき |
| pouty | 不機嫌(軽) | 無理を言ったとき・からかったとき |

### 初回だけ: Cubism Core を置く

Live2D の表示には Live2D 公式の実行用ファイル **Cubism Core** が必要です。ライセンス上、このリポジトリ(公開)には含めていません。

1. Live2D 公式サイトの「Cubism SDK for Web」をダウンロード(利用規約に同意)
2. zip の中の `Core/live2dcubismcore.js` を `frontend/public/live2d/core/live2dcubismcore.js` に置く
3. `run_mac.command` をダブルクリック(画面が自動でビルドし直されます)

### 声と音声入力

**おすすめ: VOICEVOX の声で話す(無料)**

[VOICEVOX](https://voicevox.hiroshiba.jp/) は無料の日本語読み上げソフトです(商用利用も可。キャラクターごとの規約あり)。
起動しておくと、秘書はその声で話し、**声の大きさに合わせて口が動きます**。

1. VOICEVOX 公式サイトから Mac 版をダウンロードしてインストール
2. VOICEVOX を起動したまま、秘書ハブを開く(画面を再読み込み)
3. 画面右下の一覧から声を選ぶ(既定は「冥鳴ひまり」。選んだ声は次回も使われます)

- 既定の声は `backend/.env` の `VOICEVOX_SPEAKER=声の名前の一部` で変えられます
- 秘書ハブ内で聞くだけならクレジット表記は不要です。作った音声を SNS などに出す場合は「VOICEVOX:キャラ名」の表記が必要です(各キャラクターの規約を確認)

**VOICEVOX が起動していないとき**は、Mac に入っている日本語の女性の声(O-ren → Kyoko の順)で話します。
Mac の「システム設定 → アクセシビリティ → 読み上げコンテンツ → システムの声 → 声を管理」で
**Kyoko(拡張)** や **O-ren(プレミアム)** を追加すると、少し自然になります。

**音声入力(🎙)**は **Chrome か Safari** で使えます。Brave では使えません(認識サーバーに繋がらないため)。

### ファイル

| 場所 | 内容 |
|---|---|
| `frontend/public/live2d/secretary/` | モデル一式(moc3・テクスチャ・表情4種) |
| `frontend/src/Live2DStage.jsx` | 表示部品(pixi-live2d-display)。気分→表情、話し中→口パク |
| `live2d_work/` | モデルを作った過程(PSD・手順書・ツール)。[`live2d_work/README.md`](live2d_work/README.md) |
