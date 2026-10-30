# 簡易リギング仕様書(ルートA: Live2D Cubism Editor FREE版)

> 対象: Live2D 初心者の社長。所要 3〜6時間(セッション1: 手順0〜5 / セッション2: 手順6〜10)。
> 詰まったら画面のスクリーンショットを秘書に渡してください。Claude が次の操作を指示します。
> メニュー名は Cubism Editor のバージョンで多少異なります。見つからない時もスクショを送ってください。
> 用語: **パラメータ** = 動きのつまみ / **デフォーマ** = パーツをまとめて変形させる枠 / **キーフォーム** = つまみの位置ごとの形

## 0. 準備 [人間作業]

1. Live2D 公式サイトから Cubism Editor(最新版)をダウンロード・インストール。起動時に「FREE版を使う」を選ぶ
   (アカウント作成やログインは社長が直接行う。Claude はログイン情報を扱いません)
2. 公式比較ページで FREE版の上限(パラメータ数・デフォーマ数・アートメッシュ数・テクスチャサイズ)を確認し、下の設計値以内であることを確認
3. Phase 1 で承認済みの `live2d_work/secretary_psd/secretary_bust.psd` と、Claude が追加した口内レイヤー入り PSD(`secretary_bust_l2d.psd`)を用意

## 1. 設計(FREE版の制限内に収める)

### パラメータ一覧(21個 / 上限30)

IDは Live2D 標準ID。**名前を変えないこと**(Phase 3 のアプリがこのIDで動かします)。

| # | ID | 名前 | 範囲 | 用途 |
|---|---|---|---|---|
| 1 | ParamAngleX | 角度 X | -30〜30 | 顔の左右 |
| 2 | ParamAngleY | 角度 Y | -30〜30 | 顔の上下 |
| 3 | ParamAngleZ | 角度 Z | -30〜30 | 首かしげ |
| 4 | ParamEyeLOpen | 左目 開閉 | 0〜1(既定1) | まばたき |
| 5 | ParamEyeROpen | 右目 開閉 | 0〜1(既定1) | まばたき |
| 6 | ParamEyeLSmile | 左目 笑顔 | 0〜1 | 上機嫌 |
| 7 | ParamEyeRSmile | 右目 笑顔 | 0〜1 | 上機嫌 |
| 8 | ParamEyeBallX | 目玉 X | -1〜1 | 目線(考え中) |
| 9 | ParamEyeBallY | 目玉 Y | -1〜1 | 目線(考え中) |
| 10 | ParamBrowLY | 左眉 上下 | -1〜1 | 表情 |
| 11 | ParamBrowRY | 右眉 上下 | -1〜1 | 表情 |
| 12 | ParamBrowLAngle | 左眉 角度 | -1〜1 | 不機嫌/困り |
| 13 | ParamBrowRAngle | 右眉 角度 | -1〜1 | 不機嫌/困り |
| 14 | ParamMouthForm | 口 変形 | -1〜1 | -1=への字 / 1=笑顔 |
| 15 | ParamMouthOpenY | 口 開閉 | 0〜1 | **口パク** |
| 16 | ParamCheek | 照れ | 0〜1 | 上機嫌(頬染め) |
| 17 | ParamBodyAngleX | 体の回転 X | -10〜10 | 体の揺れ |
| 18 | ParamBodyAngleZ | 体の回転 Z | -10〜10 | 体の傾き |
| 19 | ParamBreath | 呼吸 | 0〜1 | **呼吸** |
| 20 | ParamHairFront | 髪揺れ 前 | -1〜1 | 物理演算 |
| 21 | ParamHairBack | 髪揺れ 後 | -1〜1 | 物理演算(三つ編み含む) |

### デフォーマ構成(14個 / 上限50)

```
体の回転(回転デフォーマ) ← ParamBodyAngleZ
└ 体のワープ(ワープ) ← ParamBodyAngleX, ParamBreath      … 服・首・三つ編み下部
  └ 首(ワープ) ← ParamAngleX/Y
    └ 顔の回転(回転) ← ParamAngleZ
      └ 顔のワープ(ワープ) ← ParamAngleX, ParamAngleY      … 顔・耳・ヘッドセット
        ├ 前髪(ワープ) ← ParamHairFront
        ├ 後ろ髪(ワープ) ← ParamHairBack
        ├ 三つ編み(ワープ) ← ParamHairBack
        ├ 左目(ワープ) ← ParamEyeLOpen, ParamEyeLSmile
        ├ 右目(ワープ) ← ParamEyeROpen, ParamEyeRSmile
        ├ 左眉(ワープ) ← ParamBrowLY, ParamBrowLAngle
        ├ 右眉(ワープ) ← ParamBrowRY, ParamBrowRAngle
        └ 口(ワープ) ← ParamMouthForm, ParamMouthOpenY
```

## 2. PSD 読み込みとメッシュ(30分)

1. `secretary_bust_l2d.psd` を Cubism Editor のモデリング画面にドラッグ&ドロップ
2. 全パーツを選択 → メニュー「メッシュの自動生成」→ プリセット「標準」で OK
3. 目・口・眉だけは細かくしたいので、選択して「メッシュの自動生成」→「高精細」

## 3. デフォーマ作成(30分)

1. 上の構成図の**外側から順に**作る: 対象パーツを選ぶ → 「ワープデフォーマの作成」(回転は「回転デフォーマの作成」)
2. ワープデフォーマの分割数は 体・顔 = 5×5、目・口・眉 = 3×3
3. 親子関係は「デフォーマ」パレットで子を親にドラッグして設定

## 4. まばたき(30分)— ParamEyeLOpen / ParamEyeROpen

1. 「パラメータ」パレットで ParamEyeLOpen を作成(ID・範囲は表の通り。既定値 1)
2. 左目のワープデフォーマを選び「キーの2点追加」(0 と 1)
3. つまみを 0 にして:
   - **まつ毛(上まぶた)**を下のまぶたの位置まで下げ、弓なりに少し下へ曲げる(=閉じた目の線)
   - **白目・瞳**は上下につぶす(Y方向に縮めて、まぶたの線の裏に隠す)
4. 右目も同様(左目のキーフォームを「反転コピー」すると速い)
5. つまみを 0↔1 で動かして、途中で白目がまぶたからはみ出さないか確認

## 5. 口パク(40分)— ParamMouthOpenY / ParamMouthForm

1. Claude が追加した **口内レイヤー**(`mouth_inner`)を口レイヤーの下に置く。口内は口の形でクリッピング(「クリッピング」欄に口のIDを入れる)
2. ParamMouthOpenY と ParamMouthForm で「キーの結合」(2×3 = 6つのキーフォーム)
3. 開き 1: 下唇を下げて口内を見せる / 形 1: 口角を上げる / 形 -1: 口角を下げる(への字)
4. 6か所すべて形を作る(開き×形の組み合わせ)

## 6. 顔の向き(60分)— ParamAngleX / ParamAngleY / ParamAngleZ

1. 顔のワープデフォーマに ParamAngleX(-30, 0, 30)のキーを追加
2. 30 では: 顔全体のワープを右に寄せ、**右側を縮め左側を広げる**(立体感)。前髪は顔より少し多めに、後ろ髪は逆方向に少し動かす
3. -30 は「反転コピー」で作る
4. ParamAngleY も同様(上を向く=目・口を上に寄せ、あごを縮める)
5. ParamAngleZ は顔の回転デフォーマを ±10°回すだけ

## 7. 呼吸・体(20分)— ParamBreath / ParamBodyAngleX / ParamBodyAngleZ

1. 体のワープの ParamBreath = 1 で、**肩と胸を 2〜3px 上げる**(大きく動かすと不自然)
2. ParamBodyAngleX ±10 で体をわずかに左右へ / ParamBodyAngleZ は回転デフォーマを ±3°

## 8. 表情用パラメータ(40分)

| パラメータ | 作る形 |
|---|---|
| ParamEyeLSmile / RSmile = 1 | 下まぶたを持ち上げ、目を細めて弧にする(笑い目) |
| ParamBrowLY / RY = 1 | 眉を上げる |
| ParamBrowLAngle / RAngle = -1 | 眉の内側を下げる(怒り) / 1 で内側を上げる(困り) |
| ParamCheek = 1 | 頬に薄いピンクの楕円パーツ(Claude が `cheek` レイヤーとして追加)を不透明度 0→70% |
| ParamEyeBallX / Y | 瞳を白目の中で上下左右に移動 |

## 9. 髪揺れ(物理演算・20分・任意)

1. メニュー「物理演算設定」→ グループ追加「前髪」: 入力 = ParamAngleX(40%)・ParamBodyAngleX(60%)、出力 = ParamHairFront
2. 「後ろ髪」グループも同様に出力 ParamHairBack
3. 前髪/後ろ髪/三つ編みのワープデフォーマに ParamHairFront / Back(-1, 0, 1)のキーで左右に揺れた形を作る
   (FREE版で物理演算設定が使えない場合はスキップしてOK)

## 10. 表情(exp)と書き出し(30分)

1. アニメーション画面ではなく、モデリング画面のメニュー「ファイル → 組み込み用ファイル書き出し → moc3ファイルとして書き出し」
   - 書き出し先: `secretary-hub/frontend/public/live2d/secretary/`、ファイル名 `secretary`
   - テクスチャ: 2048×2048 / 1枚
2. まばたき・リップシンクの設定: 「モデル設定」→ まばたき = ParamEyeLOpen, ParamEyeROpen、リップシンク = ParamMouthOpenY
   (これで `model3.json` の Groups に EyeBlink / LipSync が入る。**設定画面が見つからなければ飛ばしてOK** — Claude が `model3.json` に直接書き足します)
3. 表情は Claude が下表の値で `expressions/*.exp3.json` を作成するので**作業不要**(Cubism で作っても良い)

| 表情 | 中身(パラメータの上書き) |
|---|---|
| normal | なし(既定の顔) |
| pleased | EyeSmile 0.8 / MouthForm 1 / Cheek 0.6 / BrowY 0.3 |
| thinking | EyeBallX -0.5, EyeBallY 0.6 / BrowLY 0.4 / BrowRAngle 0.5 / MouthForm -0.3 / AngleZ 6 |
| pouty | BrowAngle -0.8 / BrowY -0.4 / MouthForm -1 / Cheek 0.4 / EyeOpen 0.85 |

## 11. 完了確認(Phase 2 完了基準)

Cubism Viewer(Editor 同梱)で `secretary.model3.json` を開き:
- [ ] 数秒ごとに自動でまばたきする
- [ ] 「リップシンク」で音声ファイルを入れると口が動く(または ParamMouthOpenY のつまみで開閉する)
- [ ] ParamBreath で肩が上下する
- [ ] 上限超過の警告が出ていない

OKなら秘書に「モデルできた」と伝えてください → Phase 3(秘書ハブへの組み込み)へ。
