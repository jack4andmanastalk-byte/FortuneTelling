#!/usr/bin/env bash
# ワークスペースはセッションをまたぐと pip パッケージが消えるため、テスト/生成の前に実行する
set -e
pip install -q sxtwl lunar_python pyswisseph iztro-py divicast timezonefinder \
    "ephem==4.2.1" google-genai zhconv
pip install -q --no-deps kinqimen
python3 -c "import sxtwl, lunar_python, swisseph, timezonefinder, ephem; print('deps OK')"

# --- 任意: 口調切替タブの「実 DOM 実行」テスト用（mts5.26 追加） ---------------
# jsdom は Node 上の本物の DOM 実装で、インライン <script> を文書順（パース位置）で
# 実行する。mts5.25 で見逃した「実行 JS が本文 .tone-text より先に走る」バグを
# 再現できる唯一の手段（tests/test_tones.py: TestToneUiDomBehaviour）。
# ワークスペースを汚さないよう /tmp に入れる（毎セッション再導入）。
# node/npm が無い・オフライン等でも本処理は失敗させない（テストは skip に落ちる）。
if command -v npm >/dev/null 2>&1; then
  if npm install --silent --no-fund --no-audit --prefix /tmp/tone_jsdom jsdom \
       >/dev/null 2>&1; then
    echo "jsdom OK（口調タブの実 DOM テストが有効）"
  else
    echo "jsdom 未導入（口調タブの実 DOM テストは skip されます）"
  fi
else
  echo "npm が無いため jsdom を skip（口調タブの実 DOM テストは skip）"
fi
