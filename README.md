# TransRxiv

**作者**: 紫波レント / Roent Shiba  
**ライセンス**: CC BY-NC-SA 4.0 

## 概要

bioRxiv/medRxiv の **details API** から取得した各プレプリントの **title / abstract** を、ローカルの **LM Studio（OpenAI 互換 API）** で日本語訳し、整理された **HTML** に出力するデスクトップ GUI ツールです。日付・カテゴリ・DOI ごとにファイルを階層化、日付・カテゴリ・月次・年次のインデックスも自動生成します。

> スクリプト本体: `biorxiv_gui.py`（Python/Tkinter）

---

## 主な機能

* **日付指定**（カレンダー入力対応 / 手入力フォールバック）
* **期間指定**: Day / Week / Month / Year
  指定日から *さかのぼって* 日単位で順にフェッチ＆生成
* **ナビゲーション物理ボタン**
  `◀年 ◀月 ◀日 ▶日 ▶月 ▶年`（横幅のみ拡大・固定幅）
* **ページング自動対応**
  API の `messages.total` を表示し、100件刻み（0,100,200, …）で自動フェッチ
* **キーワード限定**
  カンマ区切りで複数キーワード、**AND/OR** 選択。英語の **title/abstract（翻訳前）** にマッチするもののみ処理
* **LM Studio 連携**
  `http://127.0.0.1:1234/v1/chat/completions`（既定）で `openai/gpt-oss-20b` を使用（変更可）
* **カテゴリ名のスラグ化**
  保存時のみスペースを **アンダースコア** に、危険文字を `_` に置換（表示は元のカテゴリ名）
* **ファイル出力**
  各論文を HTML 化し、DOI/リンク、JATS XML（あれば）を表示
* **インデックス生成**

  * 日付別: `./date/YYYY-MM-DD/date.html`
  * カテゴリ別（全期間）: `./category/<category_slug>/category.html`
  * 当日×カテゴリ: `./date/YYYY-MM-DD/<category_slug>/category.html`
  * 全日付一覧: `./date/all_date.html`
  * 月次一覧: `./log/YYYY/MM/all_month.html`
  * 年次一覧: `./log/year/all_year.html`
* **設定・ログ保存**

  * **Fetch 実行時の設定**を `./setting/setting.txt` に上書き保存
  * 同一内容を `./log/setting/yyyy-MM-dd_hh-mm.log` にタイムスタンプ別で保存
  * **ログ（GUI の Logs 出力）**

    * 正常終了: `./log/fetch/yyyy-MM-dd_hh-mm.log`
    * 中断時: `./log/pause/yyyy-MM-dd_hh-mm.log`
* **中断制御**

  * **Stop Now**（即時中断）
  * **Stop After This Day**（当日分の処理終了後に停止）
    いずれもインデックス・集計は **処理済み分まで** 反映

---

## 依存・動作環境

* Python **3.9+**
* ライブラリ

  * `requests`
  * `tkcalendar`（任意。なければ日付はテキスト入力）
* OS: Windows / macOS / Linux（Tkinter が動作する環境）

```bash
pip install requests
# カレンダー入力を使う場合（推奨）
pip install tkcalendar
```

---

## 使い方

1. **LM Studio** を起動し、**OpenAI 互換サーバ**（Local Server）を `http://127.0.0.1:1234` で有効化
   例: モデル `openai/gpt-oss-20b` をロード（GUI から変更可）
2. スクリプト実行:

   ```bash
   python biorxiv_gui.py
   ```
3. GUI 手順:

   * **Server**: `biorxiv` / `medrxiv` を選択
   * **Date**: 対象日を選択
   * **Period**: `Day / Week / Month / Year`（指定日からさかのぼる）
   * **Keywords**（任意）: カンマ区切りで複数入力（例: `T cell, tuberculosis`）
   * **Mode**: `OR`（どれか一致）/ `AND`（すべて含む）
   * **Fetch & Generate** をクリック

     * `messages.total`（総件数）をログに表示
     * 100件単位でページング取得
     * 一致レコードを翻訳 → HTML 生成 → 各インデックス更新
   * **Stop Now** / **Stop After This Day** で中断可能

---

## ディレクトリ構成

> Base Dir は GUI で選択（デフォルトはカレント）

```
Base Dir
├─ date/
│  ├─ YYYY-MM-DD/
│  │  ├─ <category_slug>/
│  │  │  └─ <doidate>/<doino>.html
│  │  └─ date.html
│  └─ all_date.html
├─ category/
│  └─ <category_slug>/
│     └─ category.html
├─ log/
│  ├─ YYYY/MM/all_month.html
│  ├─ year/all_year.html
│  ├─ setting/yyyy-MM-dd_hh-mm.log     # Fetch 開始時の設定スナップショット
│  ├─ fetch/yyyy-MM-dd_hh-mm.log       # 処理完了時のログ
│  └─ pause/yyyy-MM-dd_hh-mm.log       # 中断時のログ
└─ setting/
   └─ setting.txt                      # 直近の設定（上書き）
```

* **個別 HTML**: `./date/YYYY-MM-DD/<category_slug>/<doidate>/<doino>.html`
* **DOI リンク**: `https://doi.org/10.1101/<doidate>.<doino>` を本文に表示
  ※ 入力 DOI から `doidate`（例: `2023.08.24`）と `doino`（例: `554661`）を抽出して整形

---

## 生成される HTML（抜粋）

* タイトル（日本語/英語）
* 日付 / カテゴリ / サーバ
* DOI（整形リンク）＆ Raw DOI リンク
* JATS XML（あれば）
* 抄録（日本語 / 原文）

---

## キーワードフィルタの挙動

* 対象: **翻訳前の英語** `title + abstract`
* 入力: カンマ区切り（例: `nanopore, m6A, segmentation`）
* モード:

  * **OR**: いずれかを含むレコードを処理
  * **AND**: すべてを含むレコードのみ処理

---

## ページング（100件超の対応）

* API の `messages.total` をログに表示
* 100件ずつ `cursor=0, 100, 200, …` で連続フェッチ（GUI ログに各 URL を表示）
* 収集件数を `collected (raw)` としてログ出力

---

## 中断の仕様

* **Stop Now**
  即時停止。**当日分が途中でも終了**。その時点までの出力・インデックスは反映
* **Stop After This Day**
  **現在処理中の日が完了したら**停止（翌日以降に進まない）
* ログ保存先

  * 停止を行った時刻で `./log/pause/yyyy-MM-dd_hh-mm.log`
  * 正常完了時は Fetch 開始時刻で `./log/fetch/yyyy-MM-dd_hh-mm.log`

---

## 設定の保存

* Fetch 実行のたびに **現在の設定**を:

  * `./setting/setting.txt` に **上書き**
  * `./log/setting/yyyy-MM-dd_hh-mm.log` に **保存（履歴）**

保存項目:

```
server, date, period, base_dir, lm_url, lm_model, keywords, mode, timestamp
```

> 起動時の自動ロードは未実装ですが、追加可能です（要望があれば対応）。

---

## トラブルシューティング

* **LM Studio に接続できない**

  * LM Studio の Local Server が有効か確認（既定 `http://127.0.0.1:1234`）
  * モデル（例: `openai/gpt-oss-20b`）がロード済みか確認
* **tkcalendar がない / カレンダーが出ない**

  * `pip install tkcalendar`。未導入でも **手入力**で日付指定可（`YYYY-MM-DD`）
* **ネットワーク**

  * API 取得に失敗する場合、Proxy/Firewall 設定を確認
* **パス/権限**

  * Base Dir に書き込み権限があることを確認

---

## カスタマイズ

* 期間の定義（Day=1, Week=7, Month=30, Year=365）を変更
  → `PERIOD_MAP` の値を調整
* 生成 HTML のスタイル調整
  → `HTML_DOC_TPL / HTML_INDEX_TPL` を編集
* モデル名・LM URL の既定値変更
  → 冒頭の `LMSTUDIO_MODEL_DEFAULT`, `LMSTUDIO_API_URL_DEFAULT`

---

## ライセンス

プロジェクトのライセンスはリポジトリ方針に合わせて設定してください（例: MIT）。README への追記もお忘れなく。

---

## 謝辞

* bioRxiv / medRxiv の公開 API に感謝します
* LM Studio（OpenAI 互換 API モード）を利用しています

---

## ライセンス

このプロジェクトは **CC BY-NC-SA 4.0** の下で公開します。
帰属: 紫波レント / Roent Shiba

**短い表示例（LICENSE ファイルに追記してください）**:

```
Copyright (c) Roent Shiba (紫波レント)

This work is licensed under the Creative Commons Attribution-NonCommercial-ShareAlike 4.0 International License.
To view a copy of this license, visit http://creativecommons.org/licenses/by-nc-sa/4.0/
```

---

