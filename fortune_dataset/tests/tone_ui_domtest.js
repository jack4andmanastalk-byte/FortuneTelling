/*
 * tone_ui_domtest.js — 口調切替タブの実 DOM 実行テスト（mts5.26 新設）
 *
 * 目的: 「本物の HTML パーサが、本物の順序で <script> を実行する」環境で
 *       タブをクリックし、口調が実際に切り替わるかを検証する。
 *
 * なぜ必要か（mts5.25 の教訓）:
 *   既存テストは文字列アサーションのみ（JS 非実行）で、Node での DOM モックも
 *   「.tone-text を IIFE 実行前に用意していた」ため、DOM のパース順序バグ
 *   （実行 JS が本文 .tone-text より先に走る）を検出できなかった。
 *   jsdom の runScripts:'dangerously' はインライン <script> を
 *   **文書順（パース位置）で実行**するため、このバグをそのまま再現できる。
 *
 * 使い方:  node tone_ui_domtest.js <report.html>
 * 出力   :  JSON 1行（stdout）。エラー時は {"ok":false,"error":...}
 */
"use strict";

const fs = require("fs");

/* DOMContentLoaded / load まで待つ。
   ★これは測定の都合であって、テストの甘さではない:
   本番のブラウザも「パース完了 → DOMContentLoaded → （ユーザーがクリック）」の
   順で動く。mts5.26 のバグは『DOMContentLoaded 前に querySelectorAll して
   0 件になる』ことだったので、待ってから検証するのが正しい条件。 */
function whenLoaded(win, cb) {
  if (win.document.readyState === "complete") {
    cb();
    return;
  }
  let done = false;
  const once = function () {
    if (done) return;
    done = true;
    cb();
  };
  win.addEventListener("DOMContentLoaded", once);
  win.addEventListener("load", once);
  win.setTimeout(once, 10000); // 保険（load が来ない環境でも報告する）
}

async function main() {
  const path = process.argv[2];
  if (!path) {
    throw new Error("usage: node tone_ui_domtest.js <report.html>");
  }
  const html = fs.readFileSync(path, "utf8");

  const { JSDOM } = require("jsdom");
  // runScripts:'dangerously' = インライン script をパース位置で実行（本番と同じ）
  // url は http(s) にする（file:// は不透明オリジンで localStorage が使えないため）
  const dom = new JSDOM(html, {
    runScripts: "dangerously",
    url: "https://example.org/report.html",
    pretendToBeVisual: true,
    beforeParse: function (window) {
      // Old card preference must not override mts5.46's standard-first default.
      try { window.localStorage.setItem("fortune_omake", "easy"); } catch (e) {}
    },
  });
  const win = dom.window;
  const doc = win.document;

  await new Promise(function (resolve) {
    whenLoaded(win, resolve);
  });

  const res = {
    ok: true,
    has_bar: !!doc.getElementById("tonebar"),
    n_buttons: doc.querySelectorAll(".tb-btn").length,
    n_tone_text: doc.querySelectorAll(".tone-text").length,
    n_data_unit: doc.querySelectorAll(".tone-text[data-unit]").length,
    tone_data_ok: false,
    errors: [],
  };

  // tone-data JSON が読めるか
  const td = doc.getElementById("tone-data");
  if (td) {
    try {
      const D = JSON.parse(td.textContent);
      res.tone_data_ok = !!D.tones;
      res.tone_ids = Object.keys(D.tones || {});
    } catch (e) {
      res.errors.push("tone-data JSON parse failed: " + e.message);
    }
  }

  // 二重エスケープ検出（mts5.25 回帰）: 表示テキストに "&lt;p&gt;" が
  // 見えたら HTML 文字列が文字として表示されている（＝壊れている）
  function visibleBroken(el) {
    const t = el ? el.textContent || "" : "";
    return t.indexOf("&lt;") !== -1 || t.indexOf("&gt;") !== -1;
  }

  // クリック前の本文（synthesis を代表とする）
  const pickUnit = () => {
    const el = doc.querySelector('.tone-text[data-unit="synthesis"]');
    return el || doc.querySelector(".tone-text");
  };

  const target = pickUnit();
  if (!target) {
    res.errors.push("no .tone-text element in DOM");
  }
  const uid = target ? target.getAttribute("data-unit") : "";
  res.unit = uid;
  res.before = target ? target.innerHTML : null;
  res.before_broken = target ? visibleBroken(target) : null;

  function clickTone(tid) {
    const btn = doc.querySelector('.tb-btn[data-tone="' + tid + '"]');
    if (!btn) {
      res.errors.push("button not found: " + tid);
      return null;
    }
    btn.dispatchEvent(
      new win.MouseEvent("click", { bubbles: true, cancelable: true })
    );
    const el = doc.querySelector('.tone-text[data-unit="' + uid + '"]');
    return el ? el.innerHTML : null;
  }

  function ariaPressed(tid) {
    const btn = doc.querySelector('.tb-btn[data-tone="' + tid + '"]');
    return btn ? btn.getAttribute("aria-pressed") : null;
  }

  // mts5.29: 読み物版のみのページには #tone-data（全節切替 UI）が無い。
  // その場合はタブ検証を飛ばし、カード側の検証だけ行う。
  res.tab_ui_present = !!td;
  // 1) 非標準トーンへ切替 → 本文が変わるか
  const afterEasy = td ? clickTone("easy") : null;
  res.after_easy = afterEasy;
  res.aria_easy = ariaPressed("easy");
  res.changed_on_easy = afterEasy !== null && afterEasy !== res.before;
  res.broken_on_easy = afterEasy !== null && visibleBroken(
    doc.querySelector('.tone-text[data-unit="' + uid + '"]'));

  // 2) 標準へ戻す → 元に戻るか
  const backStd = td ? clickTone("standard") : null;
  res.after_standard = backStd;
  res.restored_on_standard = backStd !== null && backStd === res.before;

  // 3) localStorage に選択が保存されるか
  let saved = null;
  try {
    saved = win.localStorage.getItem("fortune_tone");
  } catch (e) {
    res.errors.push("localStorage unavailable: " + e.message);
  }
  res.saved_tone = saved;

  // 4) 全 .tone-text が切替対象（テキスト数＝データユニット数）か
  res.all_units_present =
    res.n_tone_text === res.n_data_unit && res.n_tone_text > 0;

  // 5) mts5.27: 対象範囲（scope）— 対象外ユニットは切替後も標準のままか
  //    tone-data に tone_units（対象ユニットid配列）があるときだけ検証する。
  var scopeUnits = null;
  if (td) {
    try {
      var DJ = JSON.parse(td.textContent);
      if (Array.isArray(DJ.tone_units)) scopeUnits = DJ.tone_units;
    } catch (e) { /* noop */ }
  }
  res.scope_units = scopeUnits ? scopeUnits.length : null;
  if (scopeUnits && scopeUnits.length) {
    var outside = Array.prototype.slice
      .call(doc.querySelectorAll(".tone-text[data-unit]"))
      .filter(function (el) {
        return scopeUnits.indexOf(el.getAttribute("data-unit")) === -1;
      });
    res.n_out_of_scope = outside.length;
    if (outside.length) {
      var outEl = outside[0];
      var outUid = outEl.getAttribute("data-unit");
      var origOut = outEl.innerHTML;
      clickTone("easy");
      var afterOut = doc.querySelector(
        '.tone-text[data-unit="' + outUid + '"]').innerHTML;
      res.out_of_scope_unit = outUid;
      res.out_of_scope_unchanged = afterOut === origOut;
      // 対象内は変わっていることも同時に確認
      var inEl = doc.querySelector('.tone-text[data-unit="' + uid + '"]');
      res.in_scope_changed = !!inEl && inEl.innerHTML !== res.before;
      clickTone("standard");
    }
  }

  // 6) mts5.46: 統合鑑定レポート見出し内の表示切替
  var od = doc.getElementById("omake-data");
  var switcher = doc.getElementById("synthesis-switcher");
  var synBody = doc.getElementById("synthesis-body");
  res.synthesis_variants_json_present = !!od;
  res.synthesis_switcher_present = !!switcher;
  res.legacy_omake_card_absent =
    !doc.getElementById("omake") && !doc.querySelector(".omake-card");
  if (od && switcher && synBody) {
    var OD = {};
    try { OD = JSON.parse(od.textContent); } catch (e) {
      res.errors.push("synthesis variants JSON parse failed: " + e.message);
    }
    var variants = OD.omake || {};
    res.synthesis_tones = Object.keys(variants).sort();
    var sbuttons = Array.prototype.slice.call(
      switcher.querySelectorAll(".synthesis-view-btn"));
    res.synthesis_buttons = sbuttons.length;
    var standardButton = switcher.querySelector('[data-tone="standard"]');
    res.standard_default = !!standardButton
      && standardButton.getAttribute("aria-pressed") === "true"
      && standardButton.getAttribute("aria-selected") === "true"
      && switcher.getAttribute("data-active-tone") === "standard";
    res.initial_standard_html = synBody.innerHTML;
    res.old_preference_ignored = win.localStorage.getItem("fortune_omake") === "easy"
      && res.standard_default;
    res.synthesis_note_present = !!doc.querySelector(".synthesis-note")
      && doc.querySelector(".synthesis-note").textContent.indexOf("正確な内容・数値") !== -1;
    function clickSynthesis(tid) {
      var btn = switcher.querySelector('[data-tone="' + tid + '"]');
      if (!btn) {
        res.errors.push("synthesis button not found: " + tid);
        return null;
      }
      btn.click();
      return synBody.innerHTML;
    }
    var readable = {};
    ["easy", "spiritual"].forEach(function (tid) {
      readable[tid] = clickSynthesis(tid);
    });
    res.reading_version_changed = readable.easy !== null
      && readable.easy !== res.initial_standard_html;
    res.reading_versions_differ = !!readable.easy
      && !!readable.spiritual
      && readable.easy !== readable.spiritual;
    res.no_broken_escape = !visibleBroken(synBody);
    var restored = clickSynthesis("standard");
    res.standard_restored = restored === res.initial_standard_html
      && switcher.getAttribute("data-active-tone") === "standard";
    res.no_extra_reading_card = res.legacy_omake_card_absent;
  }

  finish(dom, res);
}

function finish(dom, res) {
  process.stdout.write(JSON.stringify(res) + "\n");
  try {
    dom.window.close();
  } catch (e) {
    /* noop */
  }
}

main().catch(function (e) {
  process.stdout.write(
    JSON.stringify({ ok: false, error: String((e && e.message) || e) }) + "\n"
  );
  process.exitCode = 1;
});
