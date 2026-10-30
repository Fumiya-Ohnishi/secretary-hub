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

## Live2D 化(進行中)

秘書を Live2D モデルに置き換えるプロジェクトを `live2d_work/` で進めています。進捗と次の作業は [`live2d_work/README.md`](live2d_work/README.md) を参照。
