# 設計の概要（architecture）

このページは Fortune Dataset の「仕組み」をまとめたものです。版・件数の正本は
`fortune_dataset/data/dataset_version.json`、モデル割当の正本は `fortune_dataset/data/model_plan.json` です。
本文に数値を写すときは、それらのファイルが正とします。

## 1. 全体の流れ

```
CSV（people.csv）
  │  normalize_input()                       fortunelib/profile.py
  ▼
Stage A  個別占術（52 件 ＋ 先送りの神々 1 件）   fortunelib/pipeline.py, mts.py
  │  計算（決定論）→ プロンプト組み立て → Gemini Flash-Lite 2 レーン → 検証（字数・禁止事項）
  │  results/Mxx_<slug>.md / Mxx_<slug>_raw.json
  ▼
Stage B  クラスタ中間レポート（method 軸 5 本 ＋ culture 軸 6 本）
  │  cluster_reports/M-A_method.md … C-MO_culture.md
  ▼
Stage C  軸サマリー 2 本 → 最終統合レポート → 御縁のある神さま Top10
  │  cluster_reports/AXIS_method.md, AXIS_culture.md, final_report.md, synthesis_report.md
  ▼
Stage D  読み物版（標準／やさしい／スピリチュアル）          fortunelib/tone.py
  │  tone_reports/<tone>/…, tone_manifest.json
  ▼
HTML     <person_id>_report.html（画像を Base64 で埋め込んだ 1 枚）  fortunelib/html_report.py
```

Kaggle Notebook では Cell 1 が Stage A まで、Cell N2 が Stage B 以降と HTML 生成を担当します。
ローカルでは `tools/demo_local_html.py` が LLM を呼ばずに同じ構造の成果物を作ります（文章はダミー）。

## 2. 入力と正規化

- 入力は CSV 1 枚（列は `docs/kaggle_setup.md`）。1 行 = 1 人。相手の生年月日などを `partner_*` 列に書くと
  相性占い（シナストリー・パリミチャム）が有効になります。
- `fortunelib/profile.py` が日付・時刻・出生地（都道府県名 → 座標・時差）・氏名（漢字・かな）を正規化します。
- 出生時刻が不明でも動きます。時刻を使う占術は正午（12:00）の近似で計算します（`fortunelib/profile.py`）。
- 「ご相談」（`consultation` 列）は統合鑑定の冒頭に 1 回だけ表示し、各占術の本文からは参照行で指し示します。
  対象日（`target` 列）が空で相談があるときは「対象日」行を出しません（今日の運勢モードでは出します）。

## 3. 占術レジストリと計算

`fortunelib/registry.py` の `_REGISTRY` が 53 占術の定義（slug・和名・M コード・グループ・プロンプト ID・
必要入力・計算モジュール名）を持ちます。グループは G1（生年月日）〜G6（象徴・古代）です。

- 計算モジュールは `fortunelib/calc/`（bazi.py・astrology.py・ziwei.py・iching.py・numerology.py・seimei.py ほか）に分かれ、
  入力が同じなら必ず同じ結果を返します。暦・天体計算には sxtwl / lunar-python / pyswisseph / iztro-py / divicast / kinqimen を使います。
- 卜占系（タロット・易・ルーン・おみくじなど）の「引き」は `fortunelib/rng.py` の共通 RNG で行います。
  既定はランダムモード（実行のたびに変わる）、再現モード（`rng_mode="reproducible"`）では
  セッション ID・相談内容・日時から作るシードで同じ札が出ます（テストで使用）。
- 六爻（M22）の時刻基準は日本標準時です。
- 占術の計算結果は `results/Mxx_<slug>_raw.json` に保存され、HTML の画像選択や検証ツール
  （`verify/verify_run_output.py`）はこの JSON を読みます。

## 4. プロンプトと鑑定文の検証

- プロンプトは `fortune_dataset/data/prompts.json`（P01〜）にあり、`fortunelib/prompt.py` が計算結果と
  人物情報を差し込んで組み立てます。
- 生成文は字数レンジ・見出し構成・禁止事項（断定的な医療・法律助言、元に無い数値の創作など）を検査し、
  不合格なら作り直します。字数の余白 `INSTRUCT_MARGIN` と検査規則は品質の前提なので、
  変更するときはテストも更新してください。
- 中国語圏のライブラリが返す術語は `fortunelib/text_ja.py` で日本語の通用字形に正規化します。
  `data/*.json` に残る旧字体・簡体字は古典用語として正しいものなので「修正」しないでください。

## 5. MTS（マルチモデル）

`fortunelib/mts.py` は「モデルごとに独立した backend ＋ 1 ワーカースレッド」で Stage A〜C を回します。

- **レーン**: Stage A は `model_plan.json` の `models` に書かれた Flash-Lite 2 レーンに占術を半分ずつ
  割り当てます。手が空いたレーンは相手の残件を引き取ります（`stage_a.pull`、相手の最後の 1 件は残す）。
- **Stage B** は軸ごとに既定レーンを使い（`stage_b.axis_to_model`）、全クラスタが完走するまで Stage C へ進みません。
- **Stage C** は上位 Flash（`stage_c.model` → `fallback` の順）で軸サマリー 2 本と最終統合を書き、
  神々（M31）は `deities_model` で選びます。
- **Stage D** は Flash-Lite だけを使い、`scope` で対象（既定 `synthesis` = 統合鑑定レポートのみ）を選びます。

### 信頼性の仕組み

| 仕組み | 設定（model_plan.json） | 意味 |
|---|---|---|
| fallback | `models.<id>.fallback` | 429/503/404 や検証不合格の作り直し上限で、次のモデルへ同じ仕事を渡す |
| 503 待ち | `reliability.backoff_503_s` | 503 のとき 1 回だけ待って再試行する（指数バックオフにはしない） |
| 応答の打ち切り | `stage_a.response_timeout` / `stage_c.response_timeout` | 1 回の生成が規定秒を超えたら打ち切り、別レーン／次のモデルへ渡す。エラーを伴わない長い無応答が全体の律速になるのを防ぐ |
| レート制限 | `models.<id>.rpm` / `rpd` | 無料枠を前提に保守的な値。上位 Flash は Stage C だけに使い、Stage D の多数回呼び出しで枯渇させない |
| 進捗の記録 | `progress`（実行時） | レーンごとの処理数・引き取り数・fallback 回数を残し、ログで原因を追える |
| 事前の疎通 | `backend.PING_MODELS`（コード） | Cell 0.1 が本番の前に軽量モデル 3 本を順に 1 回ずつ叩く（`backend.ping_gemini`）。混雑（503/408）だけ次のモデルへ進み、致命エラー（400/403/404・日次 429）はその場で止める。3 本とも混雑なら「Gemini 側の都合」と明示して中断する |

非推奨になったモデル ID は一次・fallback の全経路から外します（停止後の無駄打ちを避ける）。

## 6. HTML レポートと画像

`fortunelib/html_report.py` の `build_html(person_dir, title="", person_id="", images_dir=None, intro_video_html="")` が
Markdown と JSON を読み、1 枚の HTML にまとめます。

- 画像は `data/image_mapping.json` の対応表に従って、占術ごとに該当する 1 枚（または 2 枚）だけを
  Base64 で埋め込みます。画像が見つからなければ飛ばし、レポート生成は失敗しません。
- 画像ディレクトリの探索順: 環境変数 `FORTUNE_ASSETS_DIR` → `FORTUNE_DATA_DIR` の親 → 既定候補
  （`assets/images`、`/kaggle/input/fortune-dataset/assets/images`）→ `/kaggle/input/**/assets/images`。
  `html_report.discover_assets_root()` で確認できます。
- 型 C（九星気学・数秘術・カバラ）のチャートは `fortunelib/chartdraw.py` が実行時に Pillow で描きます
  （`docs/images.md`）。
- 冒頭動画カードは `assets/video/intro_video.json` の設定で、Cell N2 の `EMBED_INTRO_VIDEO` で ON/OFF できます。
- 読み物版（Stage D）は統合鑑定レポートの直下のボタンで切り替え、標準を初期表示します。

## 7. 成果物の構成

```
output/<person_id>/
  <person_id>_report.html      1 枚 HTML（スマホ保存用）
  profile_summary.json         正規化した入力と計算の要約
  results/Mxx_<slug>.md        個別占術の鑑定文（53 件）
  results/Mxx_<slug>_raw.json  計算結果・プロンプト・モデル・検証結果
  cluster_reports/*.md         クラスタ中間レポート 11 本＋軸サマリー 2 本
  final_report.md              最終統合（神々 Top10 を追記）
  synthesis_report.md          統合鑑定レポート（HTML の本文）
  tone_reports/<tone>/…        読み物版（units.json / segments.json / raw/）
  tone_reports/tone_manifest.json
```

## 8. テストと検証ツール

- `fortune_dataset/tests/`: pytest 一式。Kaggle の Cell 0.1（セルフテスト）も同じテストを実行します。
  API を呼ぶテストは `MockBackend` を使い、ネットワークなしで通ります（`tools/check_tests_are_hermetic.py` で確認）。
- `verify/verify_run_output.py`: 実行結果（`output/` の ZIP）と計算結果・画像の突合（問題 0 が合格）。
- `verify/asset_matching_audit.py`: 占術の結果 → 画像ファイル名の対応が解決できるかの監査。
- `verify/asset_checksums.sha256`: 画像とフォントの SHA-256（`sha256sum -c` で確認）。
- `tools/build_dataset_zip.py --verify <zip>`: 配布 ZIP の読み取り専用検査（必須同梱物・版印・画像枚数・秘密情報の混入）。
