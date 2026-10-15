# -*- coding: utf-8 -*-
"""
出力バリデーション（Phase 4・ローカル実装）
仕様：プロンプト設計書 §5
- 文字数（min/max）
- 禁止語句（※・免責・占いです・当たる・絶対に・必ず 等）
- 事実整合（計算結果の値が出現する場合は一致するか）
- フォーマット（#見出し・表・コードブロックを検出）
- 日本語率
- 必須言及（G6: プロファイル事実を1つ以上織り込む）
"""
from __future__ import annotations

import re

# 断定・免責に関する禁止語句
# ★BUG-06（2026-08-16 実機ログ）: 「確実に」「必ず」は副詞用法（"静かに、しかし
#   確実に存在感を示す"）まで拾う誤検出があった。予言・断定として問題になるのは
#   「〜します」「〜でしょう」等の述語と結びつく形なので、正規表現で限定する。
FORBIDDEN_WORDS = [
    "※", "免責", "これは占い", "占いです", "当たる",
    "ご了承ください", "エンターテインメント", "疑似体験", "シミュレーション",
]

# 断定表現（述語と結びつく場合のみ違反とする）
FORBIDDEN_PATTERNS = [
    (r"絶対に(?![^。]{0,10}(?:避け|しない|ならない))",
     "絶対に（断定）"),
    (r"(?:確実に|必ず)[^。]{0,12}?(?:します|しま|でしょう|なります|訪れ|叶い|成功)",
     "確実に/必ず（断定的予言）"),
]

# バリデーションで「問題なし」とする日本語率の下限
MIN_JAPANESE_RATIO = 0.4


def char_count(text: str) -> int:
    return len(text.strip())


def japanese_ratio(text: str) -> float:
    """ひらがな・カタカナ・漢字の割合（空白・記号を除く）"""
    total = 0
    jp = 0
    for ch in text:
        if ch.isspace():
            continue
        total += 1
        o = ord(ch)
        if (0x3040 <= o <= 0x309F or   # ひらがな
                0x30A0 <= o <= 0x30FF or   # カタカナ
                0x4E00 <= o <= 0x9FFF):    # 漢字
            jp += 1
    return jp / total if total else 0.0


def check_format(text: str) -> list:
    """Markdown構造の検出"""
    issues = []
    if re.search(r"(^|\n)#+\s", text):
        issues.append("フォーマット: Markdown見出し（#）を含む")
    if "```" in text:
        issues.append("フォーマット: コードブロックを含む")
    # 表（| で区切られた行）の検出
    for line in text.splitlines():
        if line.strip().startswith("|") and "|" in line[1:]:
            issues.append("フォーマット: テーブル（|）を含む")
            break
    return issues


# 全角英数字 → 半角（照合時の正規化用）
_ZEN2HAN = str.maketrans(
    "０１２３４５６７８９ＡＢＣＤＥＦＧＨＩＪＫＬＭＮＯＰＱＲＳＴＵＶＷＸＹＺ"
    "ａｂｃｄｅｆｇｈｉｊｋｌｍｎｏｐｑｒｓｔｕｖｗｘｙｚ　",
    "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    "abcdefghijklmnopqrstuvwxyz ")


def normalize_for_match(text: str) -> str:
    """照合用の正規化。

    ★BUG-15（2026-08-17 実機で判明）: LLM が「ライフパス７」と全角数字で
      出力したため、半角の "ライフパス7" と一致せず「事実が織り込まれて
      いない」と誤判定された。全角英数字・空白を半角に寄せて比較する。
    """
    return text.translate(_ZEN2HAN)


def check_facts(text: str, expected: list | None = None,
                must_mention: list | None = None) -> list:
    """
    事実整合チェック。

    Args:
        expected: 計算結果の値（正準値）。出現すれば整合。
        must_mention: このうち1つ以上が必ず文中に出現すること（G6用）

    Returns:
        issues: 問題リスト
    """
    issues = []
    if must_mention:
        norm = normalize_for_match(text)
        found = [m for m in must_mention
                 if m and normalize_for_match(m) in norm]
        if not found:
            issues.append(f"事実整合: プロファイル事実（{must_mention[0]} 等）が1つも織り込まれていない")
    return issues


def validate_output(
    text: str,
    min_chars: int | None = None,
    max_chars: int | None = None,
    expected_facts: list | None = None,
    must_mention: list | None = None,
    forbid_words: list | None = None,
) -> list:
    """
    総合バリデーション。問題があれば issue 文字列のリストを返す（空ならOK）。

    Args:
        text: LLM出力
        min_chars / max_chars: 文字数範囲
        expected_facts: 計算結果の値（出現すれば整合とみなす）
        must_mention: 必須言及（1つ以上）
        forbid_words: 追加の禁止語句
    """
    issues = []
    n = char_count(text)

    if min_chars is not None and n < min_chars:
        issues.append(f"文字数: {n}字（期待 {min_chars}〜{max_chars}字）")
    if max_chars is not None and n > max_chars:
        issues.append(f"文字数: {n}字（期待 {min_chars}〜{max_chars}字）")

    words = list(FORBIDDEN_WORDS) + (forbid_words or [])
    for w in words:
        if w in text:
            issues.append(f"禁止語句: 「{w}」を含む")

    for pat, label in FORBIDDEN_PATTERNS:
        m = re.search(pat, text)
        if m:
            issues.append(f"禁止語句: 「{m.group(0)}」を含む（{label}）")

    issues.extend(check_format(text))
    issues.extend(check_facts(text, expected_facts, must_mention))

    ratio = japanese_ratio(text)
    if ratio < MIN_JAPANESE_RATIO:
        issues.append(f"日本語率: {ratio:.2f}（閾値 {MIN_JAPANESE_RATIO} 未満）")

    return issues
